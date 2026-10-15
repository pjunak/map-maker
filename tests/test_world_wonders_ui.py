# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""The Wonders step: place wonders by hand and apply them without eroding again."""

import time
import tkinter as tk
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from map_maker.terrain import ui, world_wonders_ui
from map_maker.terrain.application.world import open_world
from map_maker.terrain.domain.planet import PlanetSettings
from map_maker.terrain.domain.wonders import WonderSettings
from map_maker.terrain.world_wonders_ui import WonderEditor

EXAMPLES = Path(__file__).parents[1] / "examples/world"
SMALL = PlanetSettings(nodes=6_000, duration_myr=4.0, step_kyr=250.0, climate_passes=0)


def reply(value: object) -> Callable[..., object]:
    def respond(*_args: object, **_kwargs: object) -> object:
        return value

    return respond


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


def wait(app: ui.TerrainApp, seconds: float = 300) -> None:
    view = app.world_workspace
    deadline = time.monotonic() + seconds
    while view.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    app.root.update()
    assert not view.busy


def place(app: ui.TerrainApp) -> WonderEditor:
    """Open the Wonders step with no wonders placed yet."""
    view = app.world_workspace
    view.start_wonders()
    wait(app)
    editor = view.wonders
    assert editor is not None and view.step == "wonders"
    return editor


def test_wonders_are_placed_updated_reshaped_and_deleted(app: ui.TerrainApp) -> None:
    view = app.world_workspace
    editor = place(app)
    assert view.rail.status("wonders").startswith("0 wonders")
    editor.values["kind"].set("Titan volcano")
    editor.values["size"].set("400")
    # The form offers the kind's settings from the catalog; blank is automatic.
    assert set(editor.option_values) == {"height_m"}
    editor.option_values["height_m"].set("12000")
    editor.place()
    assert editor.editing and "unsaved" in view.rail.status("wonders")
    editor._click((0.4, 0.4), tk.Event())  # type: ignore[arg-type]
    (titan,) = editor.wonders.wonders
    assert titan.kind == "titan" and titan.size_km == 400.0 and titan.name == "Titan volcano 1"
    assert titan.options == (("height_m", 12000.0),)
    assert editor.tree.exists(titan.id) and not editor.editing
    editor.values["name"].set("Skyfather")
    editor.values["size"].set("")
    editor.option_values["height_m"].set("20000")
    editor.update_selected()
    assert "height must be a number from 6,000 to 14,000 m" in editor.status.get()
    editor.option_values["height_m"].set("high")
    editor.update_selected()
    assert "Height must be a number" in editor.status.get()
    editor.option_values["height_m"].set("")
    editor.update_selected()
    (renamed,) = editor.wonders.wonders
    assert renamed.name == "Skyfather" and renamed.effective_size_km == 560.0
    assert (renamed.position, renamed.seed, renamed.options) == (titan.position, titan.seed, ())
    # Another kind brings its own settings; selecting a wonder brings back its own.
    editor.values["kind"].set("Great chasm")
    assert set(editor.option_values) == {"depth_m", "side_canyons", "parallel_troughs"}
    editor.tree.selection_remove(*editor.tree.selection())
    editor.selected = None
    editor.tree.selection_set(renamed.id)
    editor.update()
    assert editor.values["kind"].get() == "Titan volcano" and set(editor.option_values) == {
        "height_m"
    }
    editor.new_shape()
    (reshaped,) = editor.wonders.wonders
    assert reshaped.seed != renamed.seed and reshaped.position == renamed.position
    editor.values["size"].set("nonsense")
    editor.update_selected()
    assert "Size" in editor.status.get() and editor.wonders.wonders == (reshaped,)
    editor.delete()
    assert editor.wonders.wonders == ()
    editor.undo()
    assert editor.wonders.wonders == (reshaped,)
    editor.redo()
    assert editor.wonders.wonders == ()


def test_a_chasm_is_placed_with_two_clicks_and_escape_cancels(app: ui.TerrainApp) -> None:
    editor = place(app)
    editor.values["kind"].set("Great chasm")
    editor.place()
    editor._click((0.40, 0.45), tk.Event())  # type: ignore[arg-type]
    assert editor.wonders.wonders == () and "other end" in editor.status.get()
    editor._click((0.42, 0.45), tk.Event())  # type: ignore[arg-type]
    (chasm,) = editor.wonders.wonders
    assert chasm.kind == "chasm" and chasm.end is not None and chasm.end != chasm.position
    assert not editor.editing
    # Renaming keeps both ends.
    editor.values["name"].set("The Rift")
    editor.update_selected()
    (renamed,) = editor.wonders.wonders
    assert renamed.name == "The Rift" and renamed.end == chasm.end
    # Escape abandons a half-placed chasm.
    editor.place()
    editor._click((0.40, 0.50), tk.Event())  # type: ignore[arg-type]
    editor.cancel_placing()
    assert not editor.editing and editor.wonders.wonders == (renamed,)


def test_wonders_save_open_and_guard_unsaved_edits(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = app.world_workspace
    editor = place(app)
    editor.place()
    editor._click((0.4, 0.4), tk.Event())  # type: ignore[arg-type]
    target = tmp_path / "w.wonders.json"
    monkeypatch.setattr(world_wonders_ui.filedialog, "asksaveasfilename", reply(str(target)))
    editor.save()
    wait(app)
    assert target.exists() and not editor.dirty and "w.wonders.json" in editor.file_label.get()
    saved = editor.wonders
    editor.selected = saved.wonders[0].id
    editor.delete()
    assert editor.dirty and view.unsaved
    # Removing unsaved wonders asks first; declining keeps nothing.
    monkeypatch.setattr(world_wonders_ui.messagebox, "askyesnocancel", reply(False))
    view.stop_wonders()
    assert view.wonders is None and "Optional" in view.rail.status("wonders")
    view.start_wonders(target)
    wait(app)
    assert view.wonders is not None and view.wonders.wonders.wonders == saved.wonders


def test_applying_wonders_reruns_only_the_wonder_pass(app: ui.TerrainApp) -> None:
    view = app.world_workspace
    view.generate_planet(SMALL)
    wait(app)
    first = view.planet_run
    assert first is not None and not len(first.result.wonders)
    editor = place(app)
    assert str(view.apply_wonders_button["state"]) == "disabled"
    # Wonders are placed on the planet's relief, with the planet read out under the cursor.
    assert "Planet relief" in editor.layer_input.cget("values")
    assert editor.layer.get() == "Planet relief"
    editor._hover((0.5, 0.5))
    assert "Ground" in editor.inspection.get() or "Sea" in editor.inspection.get()
    # A crater on the deepest inland node of the planet.
    planet = first.result
    deepest = int(np.argmax(np.where(planet.land, planet.coast_m, -1.0)))
    x, y, z = planet.mesh.xyz[deepest]
    frame = planet.world.project.frame
    sx, sy = frame.lonlat_to_source(
        (float(np.degrees(np.arctan2(y, x))), float(np.degrees(np.arcsin(z))))
    )
    x0, y0, _, _ = frame.bounds
    editor.values["kind"].set("Impact crater")
    editor.place()
    editor._click(((sx - x0) / frame.width, (sy - y0) / frame.height), tk.Event())  # type: ignore[arg-type]
    assert len(editor.wonders.wonders) == 1
    assert "not applied" in view.rail.status("wonders")
    assert "Apply them" in view.result_panel.outdated.get()
    assert str(view.apply_wonders_button["state"]) == "normal"
    view.apply_wonders()
    wait(app)
    run = view.planet_run
    assert run is not None and run is not first
    assert run.base is first.base and run.base_sha256 == first.base_sha256
    # Applying draws the map under the wonders with the planet; others wait until chosen.
    assert editor.planet_maps.ready("Planet relief")
    assert [label for label in run.maps.labels if run.maps.image(label)] == ["Planet relief"]
    editor.layer.set("Planet topographic")
    editor._layer_picked()
    assert editor.legend.get().startswith("Drawing Planet topographic")
    deadline = time.monotonic() + 60
    while not editor.legend.get().startswith("Atlas-style") and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert run.maps.image("Planet topographic") is not None
    assert editor.legend.get().startswith("Atlas-style")
    assert editor.shown_planet_maps() == ("Planet topographic",)
    editor.layer.set("Planet relief")
    editor._layer_picked()
    first_base = first.base
    assert run.result.placed is not None and len(run.result.wonders.craters) == 1
    assert run.inputs["wonders_sha256"] is not None
    assert view.result_panel.outdated.get() == ""
    assert str(view.apply_wonders_button["state"]) == "disabled"
    # Random wonders chosen in the Generate step: Generate keeps the base too.
    view.planet_panel.wonders["tepui"].set(True)
    assert view._wonders_changed()
    view.show_step("generate")
    view.generate_planet(SMALL, view.planet_panel.wonder_settings())
    wait(app)
    again = view.planet_run
    assert again is not None and again.base is first.base and view.step == "explore"
    assert again.result.wonder_settings == WonderSettings(("tepui",))
    assert len(again.result.wonders.tepuis) >= 1 and len(again.result.wonders.craters) == 1
    # Suggested sites: found on the planet, kept as placed wonders or rejected.
    assert str(editor.suggest_button["state"]) == "normal"
    view.suggest_wonders()
    wait(app)
    found = editor.suggestions
    assert found and editor.suggestion_tree.get_children()
    first, second = found[0], found[1]
    editor.suggestion_tree.selection_set(first.id)
    editor.update()
    assert editor.suggested == first.id and first.reason in editor.suggestion_reason.get()
    editor.keep_suggestion()
    kept = editor.wonders.wonders[-1]
    assert (kept.kind, kept.position, kept.size_km) == (first.kind, first.position, first.size_km)
    assert first not in editor.suggestions and editor.selected == kept.id
    editor.suggestion_tree.selection_set(second.id)
    editor.update()
    editor.reject_suggestion()
    assert second not in editor.suggestions and len(editor.wonders.wonders) == 2
    # Applying keeps the planet without wonders, so the suggestions still apply.
    view.apply_wonders()
    wait(app)
    assert editor.suggestions and view.planet_run is not None
    assert view.planet_run.base is first_base
    # Another planet without wonders makes them stale.
    editor.set_planet(None, None, "another planet")
    assert editor.suggestions == () and str(editor.suggest_button["state"]) == "disabled"
