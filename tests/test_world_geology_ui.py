# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Real Tk geology edits, guarded lifecycle and source/context isolation."""

import time
import tkinter as tk
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event

import pytest

from dmtools.terrain import ui, world_geology_ui
from dmtools.terrain.adapters.build import file_sha256
from dmtools.terrain.application.world import open_world
from dmtools.terrain.application.world_context import generate_context
from dmtools.terrain.application.world_geology import open_geology
from dmtools.terrain.domain.world_context import WorldContextSettings
from dmtools.terrain.domain.world_geology import WorldGeologyRecipe
from dmtools.terrain.pipeline.control import CancellationToken
from dmtools.terrain.pipeline.world import WorldMap
from dmtools.terrain.pipeline.world_geology import GeologyCoverage
from dmtools.terrain.world_geology_ui import GeologyEditor

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
        open_world(EXAMPLES / "four-shores.dmworld.json"), EXAMPLES / "four-shores.dmworld.json"
    )
    yield application
    if not application._closed:
        application._close()


def edit(app: ui.TerrainApp) -> GeologyEditor:
    app.world_workspace.edit_geology()
    editor = app.world_workspace.geology_editor
    assert editor is not None
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
    original_source = file_sha256(EXAMPLES / "four-shores.dmworld.json")
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
    path = tmp_path / "world.dmgeology.json"
    monkeypatch.setattr(world_geology_ui.filedialog, "asksaveasfilename", reply(str(path)))
    editor.save()
    wait(editor)
    assert editor.file is not None and editor.file.path == path and not editor.dirty
    assert open_geology(path).coverage.recipe.provinces == editor.recipe.provinces
    editor.close()
    reopened = edit(app)
    assert reopened.file is not None and reopened.file.path == path
    assert reopened.recipe.provinces == before_delete.provinces
    assert file_sha256(EXAMPLES / "four-shores.dmworld.json") == original_source


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
    assert continued == [True] and editor._closed
    assert app.world_workspace.geology_editor is None


def test_recipe_open_retains_source_and_context_and_rejects_foreign_identity(
    app: ui.TerrainApp,
    tmp_path: Path,
) -> None:
    view = app.world_workspace
    assert view.validated is not None
    run = generate_context(view.validated.project, WorldContextSettings(8))
    view.context_run = run
    editor = edit(app)
    editor.load(EXAMPLES / "four-shores.dmgeology.json")
    wait(editor)
    assert len(editor.recipe.provinces) == 2 and not editor.dirty
    editor.layer.set("Shore distance")
    editor.canvas.draw_now()
    assert editor.canvas.photo is not None and view.context_run is run
    current = editor.recipe
    path = tmp_path / "bad.dmgeology.json"
    text = (EXAMPLES / "four-shores.dmgeology.json").read_text(encoding="utf-8")
    path.write_text(text.replace('"radius_km": 6500.0', '"radius_km": 6000.0'), encoding="utf-8")
    editor.load(path)
    wait(editor)
    assert editor.recipe == current and "fingerprint" in editor.status.get()
    assert view.path == EXAMPLES / "four-shores.dmworld.json"


def test_external_file_change_blocks_save_including_save_as_same_path(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    path = tmp_path / "world.dmgeology.json"
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
    editor = edit(app)
    app.root.deiconify()
    editor.deiconify()
    editor.geometry("1050x740")
    editor.update()
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


def test_save_on_parent_close_applies_form_then_saves_before_closing(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    target = tmp_path / "closing.dmgeology.json"
    monkeypatch.setattr(world_geology_ui.filedialog, "asksaveasfilename", reply(str(target)))
    monkeypatch.setattr(world_geology_ui.messagebox, "askyesnocancel", reply(True))
    editor.values["rejuvenation"].set("0.125")
    continued: list[bool] = []
    app.world_workspace.guard(lambda: continued.append(True))
    deadline = time.monotonic() + 8
    while not continued and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert continued == [True] and editor._closed
    assert open_geology(target).coverage.recipe.defaults[0].profile.rejuvenation_age_ma == 0.125


def test_explicit_landforms_are_guarded_saved_and_exposed_to_terrain(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = edit(app)
    panel = editor.landform_form
    assert panel.read() is None
    editor.form_tabs.select(panel)
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
    path = tmp_path / "landforms.dmgeology.json"
    monkeypatch.setattr(world_geology_ui.filedialog, "asksaveasfilename", reply(str(path)))
    editor.save()
    wait(editor)
    assert not editor.dirty
    assert open_geology(path).coverage.recipe.defaults[0].profile.landform == accepted
    # Inspect the actual laid-out minimum window: all controls and actions fit.
    app.root.deiconify()
    editor.deiconify()
    editor.geometry("1050x740")
    editor.update()
    assert panel.preset_button.winfo_ismapped()
    assert panel.preset_button.winfo_rooty() + panel.preset_button.winfo_height() < (
        editor.winfo_rooty() + editor.winfo_height()
    )
    editor.close()
    assert app.world_workspace.terrain_panel.geology_path == path
    assert "landforms.dmgeology.json" in app.world_workspace.terrain_panel.geology_label.get()


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
    editor.landmark["kind"].set("titan")
    editor.landmark["diameter"].set("400")
    editor.place_landmark()
    assert editor._placing
    editor._click((0.4, 0.4), tk.Event())  # type: ignore[arg-type]
    wait(editor)
    (titan,) = editor.recipe.landmarks
    assert titan.kind == "titan" and titan.diameter_km == 400.0 and titan.name == "Titan 1"
    assert editor.tree.exists(titan.id)
    editor.landmark["name"].set("Skyfather")
    editor.landmark["diameter"].set("")
    editor.update_landmark()
    wait(editor)
    (renamed,) = editor.recipe.landmarks
    assert renamed.name == "Skyfather" and renamed.size_km == 560.0
    assert renamed.position == titan.position
    editor.landmark["diameter"].set("nonsense")
    editor.update_landmark()
    assert "diameter" in editor.status.get() and editor.recipe.landmarks == (renamed,)
    editor.delete_landmark()
    wait(editor)
    assert editor.recipe.landmarks == ()
    editor.undo()
    assert editor.recipe.landmarks == (renamed,)
