# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Real Tk geology edits, guarded lifecycle and source/context isolation."""

import time
import tkinter as tk
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event

import pytest

from map_maker.terrain import ui, world_geology_ui
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.application.world import open_world
from map_maker.terrain.application.world_context import generate_context
from map_maker.terrain.application.world_geology import open_geology
from map_maker.terrain.domain.world_context import WorldContextSettings
from map_maker.terrain.domain.world_geology import WorldGeologyRecipe
from map_maker.terrain.pipeline.control import CancellationToken
from map_maker.terrain.pipeline.world import WorldMap
from map_maker.terrain.pipeline.world_geology import GeologyCoverage
from map_maker.terrain.world_geology_ui import GeologyEditor

EXAMPLES = Path(__file__).parents[1] / "examples/world"


def reply(value: object) -> Callable[..., object]:
    def respond(*_args: object, **_kwargs: object) -> object:
        return value

    return respond


def wait(editor: GeologyEditor) -> None:
    deadline = time.monotonic() + 8
    while editor.busy and time.monotonic() < deadline:
        editor.update()
        time.sleep(0.01)
    editor.update()
    assert not editor.busy


@pytest.fixture
def app() -> Iterator[ui.TerrainApp]:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}")
    root.withdraw()
    application = ui.TerrainApp(root)
    application.world_workspace.accept_world(
        open_world(EXAMPLES / "four-shores.world.json"), EXAMPLES / "four-shores.world.json"
    )
    yield application
    if not application._closed:
        application._close()


def edit(app: ui.TerrainApp, path: Path | None = None) -> GeologyEditor:
    """Open the Geology step with a new recipe, or the one at ``path``."""
    view = app.world_workspace
    view.start_geology(path)
    deadline = time.monotonic() + 8
    while (view.busy or view.geology is None) and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    editor = view.geology
    assert editor is not None and view.step == "geology"
    wait(editor)
    return editor


def draw(editor: GeologyEditor, name: str = "Belt", priority: str = "10") -> None:
    editor.start_drawing()
    editor.values["name"].set(name)
    editor.values["priority"].set(priority)
    editor.values["setting"].set("active-belt")
    editor.values["crust"].set("2500.1234567890123")
    editor.values["rejuvenation"].set("12")
    editor.values["duration"].set("2")
    editor._draft = [(150, 75), (205, 75), (205, 105), (150, 105)]
    editor.apply()
    wait(editor)


def test_defaults_province_edit_history_and_roundtrip(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    original_source = file_sha256(EXAMPLES / "four-shores.world.json")
    editor.values["crust"].set("1800")
    editor.apply()
    wait(editor)
    assert editor.recipe.defaults[0].profile.crust_age_ma == 1800
    assert editor.dirty and not app.world_workspace.dirty
    draw(editor)
    assert len(editor.recipe.provinces) == 1
    editor.values["name"].set("Young belt on old crust")
    editor.apply()
    wait(editor)
    assert editor.recipe.provinces[0].profile.crust_age_ma == 2500.1234567890123
    before_delete = editor.recipe
    editor.delete()
    wait(editor)
    assert not editor.recipe.provinces
    editor.undo()
    assert editor.recipe == before_delete
    editor.redo()
    assert not editor.recipe.provinces
    editor.undo()
    path = tmp_path / "world.geology.json"
    monkeypatch.setattr(world_geology_ui.filedialog, "asksaveasfilename", reply(str(path)))
    editor.save()
    wait(editor)
    assert editor.file is not None and editor.file.path == path and not editor.dirty
    assert open_geology(path).coverage.recipe.provinces == editor.recipe.provinces
    view = app.world_workspace
    view.stop_geology()  # saved, so it closes without asking
    assert view.geology is None and editor._closed
    reopened = edit(app, path)
    assert reopened.file is not None and reopened.file.path == path
    assert reopened.recipe.provinces == before_delete.provinces
    assert file_sha256(EXAMPLES / "four-shores.world.json") == original_source


def test_failed_overlap_and_redraw_retain_current_recipe(app: ui.TerrainApp) -> None:
    editor = edit(app)
    draw(editor)
    accepted = editor.recipe
    draw(editor, "Conflicting belt")
    assert editor.recipe == accepted and editor._draft is not None
    assert "overlap on land" in editor.status.get()
    editor.values["priority"].set("20")
    editor.apply()
    wait(editor)
    assert len(editor.recipe.provinces) == 2
    editor.start_drawing(redraw=True)
    editor._draft = [(150, 75), (205, 105), (150, 105), (205, 75)]
    editor.apply()
    wait(editor)
    assert "invalid polygon" in editor.status.get()
    editor.revert()
    assert not editor.form_dirty and editor._draft is None


def test_invalid_form_and_draft_never_silently_discard_on_selection_or_save(
    app: ui.TerrainApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    selected = editor._selected
    editor.values["crust"].set("unknown text")
    other = next(c for c in editor.world.continents if "continent:" + c.id != selected)
    editor.tree.selection_set("continent:" + other.id)
    editor.update()
    assert editor._selected == selected and editor.form_dirty
    monkeypatch.setattr(world_geology_ui.messagebox, "askyesnocancel", reply(True))
    closed: list[bool] = []
    editor.guard(lambda: closed.append(True))
    assert not closed and not editor.busy and editor.form_dirty
    editor.revert()
    editor.start_drawing()
    editor._draft = [(150, 75), (205, 105)]
    editor.guard(lambda: closed.append(True))
    assert not closed and "3-256" in editor.status.get()


def test_cancelling_a_resolve_preserves_applied_and_unapplied_inputs(
    app: ui.TerrainApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    recipe = editor.recipe
    entered, release = Event(), Event()
    original = world_geology_ui.resolve_geology

    def slow(
        world: WorldMap,
        candidate: WorldGeologyRecipe,
        cancellation: CancellationToken | None = None,
    ) -> GeologyCoverage:
        entered.set()
        release.wait(3)
        return original(world, candidate, cancellation)

    monkeypatch.setattr(world_geology_ui, "resolve_geology", slow)
    editor.values["crust"].set("2400")
    editor.apply()
    assert entered.wait(2)
    editor.cancel()
    release.set()
    wait(editor)
    assert editor.recipe == recipe and editor.form_dirty
    assert "Cancelled" in editor.status.get()


def test_world_guard_includes_geology_unsaved_changes(
    app: ui.TerrainApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    editor.values["crust"].set("2400")
    continued: list[bool] = []
    monkeypatch.setattr(world_geology_ui.messagebox, "askyesnocancel", reply(None))
    app.world_workspace.guard(lambda: continued.append(True))
    assert not continued and not editor._closed
    monkeypatch.setattr(world_geology_ui.messagebox, "askyesnocancel", reply(False))
    app.world_workspace.guard(lambda: continued.append(True))
    # Continuing without saving keeps the recipe in its step.
    assert continued == [True] and app.world_workspace.geology is editor
    assert not editor._closed and editor.form_dirty


def test_recipe_open_retains_source_and_context_and_rejects_foreign_identity(
    app: ui.TerrainApp,
    tmp_path: Path,
) -> None:
    view = app.world_workspace
    assert view.validated is not None
    run = generate_context(view.validated.project, WorldContextSettings(8))
    view.context_run = run
    editor = edit(app)
    editor.load(EXAMPLES / "four-shores.geology.json")
    wait(editor)
    assert len(editor.recipe.provinces) == 2 and not editor.dirty
    editor.layer.set("Shore distance")
    editor.canvas.draw_now()
    assert editor.canvas.photo is not None and view.context_run is run
    current = editor.recipe
    path = tmp_path / "bad.geology.json"
    text = (EXAMPLES / "four-shores.geology.json").read_text(encoding="utf-8")
    path.write_text(text.replace('"radius_km": 6500.0', '"radius_km": 6000.0'), encoding="utf-8")
    editor.load(path)
    wait(editor)
    assert editor.recipe == current and "fingerprint" in editor.status.get()
    assert view.path == EXAMPLES / "four-shores.world.json"


def test_external_file_change_blocks_save_including_save_as_same_path(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    path = tmp_path / "world.geology.json"
    monkeypatch.setattr(world_geology_ui.filedialog, "asksaveasfilename", reply(str(path)))
    editor.save()
    wait(editor)
    path.write_text("another PC edit", encoding="utf-8")
    editor.values["crust"].set("1800")
    editor.save(save_as=True)
    wait(editor)
    assert "changed outside" in editor.status.get() and editor.dirty
    assert path.read_text(encoding="utf-8") == "another PC edit"


def test_canvas_drawing_unwraps_the_seam_and_preserves_zoom(app: ui.TerrainApp) -> None:
    app.root.deiconify()
    app.root.geometry("1160x760")
    editor = edit(app)
    app.root.update()
    assert editor.map.winfo_ismapped() and not app.world_workspace.map_view.winfo_ismapped()
    editor.start_drawing()
    frame = editor.world.project.frame
    for x, y in ((365, 92), (15, 92), (15, 113), (365, 113)):
        cx, cy = editor.canvas.to_canvas(
            (x - frame.bounds[0]) / frame.width, (y - frame.bounds[1]) / frame.height
        )
        point = editor.canvas.to_map(round(cx), round(cy))
        assert point is not None
        editor._click(point, tk.Event())
    assert editor._draft is not None and max(x for x, _ in editor._draft) > frame.bounds[2]
    editor.apply()
    wait(editor)
    assert len(editor.recipe.provinces) == 1
    assert editor.coverage is not None
    assert editor.coverage.regions[0].area_km2 > 0
    editor.canvas.zoom_by(2, (500, 300))
    editor.canvas.draw_now()
    assert editor.viewport.zoom == 2
    editor.start_drawing(redraw=True)
    editor.revert()
    assert len(editor.recipe.provinces) == 1 and editor.viewport.zoom == 2


def test_save_on_parent_close_applies_form_then_saves_before_continuing(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    target = tmp_path / "closing.geology.json"
    monkeypatch.setattr(world_geology_ui.filedialog, "asksaveasfilename", reply(str(target)))
    monkeypatch.setattr(world_geology_ui.messagebox, "askyesnocancel", reply(True))
    editor.values["rejuvenation"].set("0.125")
    continued: list[bool] = []
    app.world_workspace.guard(lambda: continued.append(True))
    deadline = time.monotonic() + 8
    while not continued and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert continued == [True] and not editor.dirty
    assert open_geology(target).coverage.recipe.defaults[0].profile.rejuvenation_age_ma == 0.125


def test_explicit_landforms_are_guarded_saved_and_exposed_to_terrain(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    panel = editor.landform_form
    assert panel.read() is None and not editor.landform_section.expanded
    editor.landform_section.toggle()
    panel.character.set("mountains")
    panel.set_busy(False)
    panel.preset_button.invoke()
    panel.values["orientation_deg"].set("37")
    assert editor.form_dirty
    editor.apply()
    wait(editor)
    accepted = panel.read()
    assert accepted is not None and accepted.orientation_deg == 37
    assert editor.recipe.defaults[0].profile.landform == accepted
    editor.undo()
    assert panel.read() is None
    editor.redo()
    assert panel.read() == accepted
    path = tmp_path / "landforms.geology.json"
    monkeypatch.setattr(world_geology_ui.filedialog, "asksaveasfilename", reply(str(path)))
    editor.save()
    wait(editor)
    assert not editor.dirty
    assert open_geology(path).coverage.recipe.defaults[0].profile.landform == accepted
    # At the smallest window the step page scrolls to every control.
    app.root.deiconify()
    app.root.geometry("1160x760")
    app.root.update()
    assert panel.preset_button.winfo_ismapped()
    page = app.world_workspace.pages["geology"]
    assert page.body.winfo_reqheight() > page.canvas.winfo_height()
    assert "From the Geology step" in app.world_workspace.terrain_panel.geology_label.get()


def test_invalid_landform_keeps_pending_form_and_busy_controls_lock(app: ui.TerrainApp) -> None:
    editor = edit(app)
    panel = editor.landform_form
    panel.character.set("plateau")
    panel.set_busy(False)
    panel.preset()
    panel.values["transition_km"].set("0")
    before = editor.recipe
    editor.apply()
    assert editor.recipe == before and editor.form_dirty
    assert "positive" in editor.status.get()
    panel.set_busy(True)
    assert str(panel.selection["state"]) == "disabled"
    assert all(str(e["state"]) == "disabled" for e in panel.entries)
    editor.revert()
    assert panel.read() is None


def test_landmarks_are_placed_updated_and_deleted(app: ui.TerrainApp) -> None:
    editor = edit(app)
    editor.landmark["kind"].set("Titan volcano")
    editor.landmark["size"].set("400")
    editor.place_landmark()
    assert editor._placing
    editor._click((0.4, 0.4), tk.Event())  # type: ignore[arg-type]
    wait(editor)
    (titan,) = editor.recipe.landmarks
    assert titan.kind == "titan" and titan.size_km == 400.0
    assert titan.name == "Titan volcano 1"
    assert editor.tree.exists(titan.id)
    editor.landmark["name"].set("Skyfather")
    editor.landmark["size"].set("")
    editor.update_landmark()
    wait(editor)
    (renamed,) = editor.recipe.landmarks
    assert renamed.name == "Skyfather" and renamed.effective_size_km == 560.0
    assert renamed.position == titan.position
    editor.landmark["size"].set("nonsense")
    editor.update_landmark()
    assert "size" in editor.status.get() and editor.recipe.landmarks == (renamed,)
    editor.delete_landmark()
    wait(editor)
    assert editor.recipe.landmarks == ()
    editor.undo()
    assert editor.recipe.landmarks == (renamed,)


def test_a_chasm_is_placed_with_two_clicks(app: ui.TerrainApp) -> None:
    editor = edit(app)
    editor.landmark["kind"].set("Great chasm")
    editor.place_landmark()
    editor._click((0.40, 0.45), tk.Event())  # type: ignore[arg-type]
    assert editor.recipe.landmarks == () and "other end" in editor.status.get()
    editor._click((0.46, 0.45), tk.Event())  # type: ignore[arg-type]
    wait(editor)
    (chasm,) = editor.recipe.landmarks
    assert chasm.kind == "chasm" and chasm.end is not None and chasm.end != chasm.position
    assert not editor._placing and editor._line_start is None
    # Renaming keeps both ends.
    editor.landmark["name"].set("The Rift")
    editor.update_landmark()
    wait(editor)
    (renamed,) = editor.recipe.landmarks
    assert renamed.name == "The Rift" and renamed.end == chasm.end
    # Escape abandons a half-placed chasm.
    editor.place_landmark()
    editor._click((0.40, 0.50), tk.Event())  # type: ignore[arg-type]
    editor.revert()
    assert not editor._placing and editor._line_start is None


def test_geology_follows_world_edits_and_feeds_the_planet(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hashlib import sha256

    from map_maker.terrain import world_ui
    from map_maker.terrain.adapters.build import canonical_json
    from map_maker.terrain.adapters.world_geology import geology_document
    from map_maker.terrain.domain.planet import PlanetSettings

    view = app.world_workspace
    editor = edit(app, EXAMPLES / "four-shores.geology.json")
    provinces = editor.recipe.provinces
    assert len(provinces) == 2 and not editor.dirty
    # Renaming the world used to orphan its recipe; now the recipe follows it.
    view.show_step("planet")
    view.values["name"].set("Renamed shores")
    view.show_step("geology")
    wait(editor)
    assert editor.world.project.name == "Renamed shores"
    assert editor.recipe.world == view.project() and editor.recipe.provinces == provinces
    assert editor.dirty and "unsaved" in view.rail.status("geology")
    # An unapplied edit is not silently left out of a planet.
    errors: list[str] = []

    def show_error(_title: str, message: str, **_kwargs: object) -> None:
        errors.append(message)

    monkeypatch.setattr(world_ui.messagebox, "showerror", show_error)
    editor.values["crust"].set("2000")
    view.generate_planet(PlanetSettings(nodes=6_000, duration_myr=4.0, step_kyr=250.0,
                                        climate_passes=0))
    assert errors and "not applied" in errors[0] and not view.busy
    editor.revert()
    # The planet uses the recipe as it stands in the step, saved or not.
    view.generate_planet(PlanetSettings(nodes=6_000, duration_myr=4.0, step_kyr=250.0,
                                        climate_passes=0))
    deadline = time.monotonic() + 120
    while view.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    assert view.planet_run is not None
    expected = sha256(canonical_json(geology_document(editor.recipe))).hexdigest()
    assert view.planet_run.inputs["geology_sha256"] == expected
    assert "From the Geology step: 2 provinces" in view.planet_panel.geology_label.get()
    assert view.result_panel.outdated.get() == ""
    # A later geology edit says the planet was made with older geology.
    editor.values["crust"].set("2000")
    editor.apply()
    wait(editor)
    assert "geology changed" in view.rail.status("generate")
    assert "Generate again" in view.result_panel.outdated.get()
    # Removing geology goes back to automatic ranges.
    monkeypatch.setattr(world_geology_ui.messagebox, "askyesnocancel", reply(False))
    view.stop_geology()
    assert view.geology is None and view.rail.status("geology") == "Optional · automatic"
    assert view.geology_empty.winfo_manager() == "pack"


def test_geology_closes_when_another_source_map_opens(app: ui.TerrainApp) -> None:
    from map_maker.terrain.adapters.world_svg import parse_world_svg

    view = app.world_workspace
    editor = edit(app)
    view.accept_world(open_world(EXAMPLES / "four-shores.world.json"),
                      EXAMPLES / "four-shores.world.json")
    assert view.geology is editor  # the same drawing keeps its geology
    view.accept_source(parse_world_svg(
        '<svg viewBox="0 0 360 180"><g id="North"><path id="land" d="M10 10 H30 V30 H10 Z"/>'
        '</g></svg>', "other.svg",
    ))
    assert view.geology is None and editor._closed
