# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Real Tk input-editing flow; skipped only where no desktop display is available."""

import time
import tkinter as tk
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any, cast

import numpy as np
import pytest
from PIL import Image

from benchmarks.terrain import fixture
from map_maker.terrain import ui
from map_maker.terrain.adapters import load_terrain_project
from map_maker.terrain.domain import (
    ElevationPoint,
    TerrainBasin,
    TerrainBrushStroke,
    TerrainRegion,
    TerrainStructure,
    landform_preset,
)
from map_maker.terrain.pipeline import GeneratedTerrain, generate_terrain
from map_maker.terrain.pipeline.control import CancellationToken
from map_maker.terrain.workbench import GenerationInputs


@pytest.fixture(scope="module")
def generated() -> tuple[GenerationInputs, GeneratedTerrain]:
    coast, settings, _ = fixture("square", 65, 42)
    inputs = GenerationInputs(coast, settings, (ElevationPoint((0.5, 0.5), 1200, 80),))
    return inputs, generate_terrain(coast, settings, constraints=inputs.constraints)


@pytest.fixture
def app(generated: tuple[GenerationInputs, GeneratedTerrain]) -> Iterator[ui.TerrainApp]:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    root.withdraw()
    workbench = ui.TerrainApp(root)
    inputs, terrain = generated
    workbench._accept_coastline(inputs.coastline)
    workbench._apply_settings(inputs.settings)
    workbench._history.reset(inputs.constraints)
    workbench._events.put(ui._ResultEvent(inputs, terrain, Image.new("RGBA", (65, 65)), None))
    workbench._poll_events()
    yield workbench
    if not workbench._closed:
        for callback in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(str(callback))
        workbench._close()


def test_edit_keeps_readonly_reference_and_undo_restores_freshness(app: ui.TerrainApp) -> None:
    terrain, image = app._terrain, app._image
    assert terrain is not None
    original = terrain.elevation_m.copy()
    app._select_instruction(0)
    app._tool_elevations["height"].set(2300)
    assert app._has_pending_instruction()
    point = app._constraints[0]
    assert isinstance(point, ElevationPoint) and point.elevation_m == 1200
    app._apply_instruction()
    assert not app._has_pending_instruction()
    assert not app._reference_is_current()
    assert "Previous generation" in str(app.reference_label["text"])
    assert str(app.export_button["state"]) == "disabled"
    assert app._terrain is terrain and app._image is image
    np.testing.assert_array_equal(terrain.elevation_m, original)
    app._undo_constraint()
    assert app._reference_is_current()
    assert str(app.export_button["state"]) == "normal"
    app._redo_constraint()
    assert not app._reference_is_current()


def test_settings_and_late_results_use_exact_snapshot(app: ui.TerrainApp) -> None:
    request = app._generation_inputs()
    terrain, image = app._terrain, app._image
    assert terrain is not None and image is not None
    app._variables["seed"].set(1234)
    assert not app._reference_is_current()
    app._events.put(ui._ResultEvent(request, terrain, image, app._water_display))
    app._poll_events()
    assert not app._reference_is_current()
    assert str(app.export_button["state"]) == "disabled"
    app._variables["seed"].set(request.settings.seed)
    assert app._reference_is_current()
    app.root.setvar(str(app._variables["seed"]), "")
    assert not app._reference_is_current()


def test_save_and_failure_do_not_relabel_stale_reference(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[object] = []
    def showerror(*args: object, **kwargs: object) -> None:
        errors.extend(args)
    monkeypatch.setattr(ui.messagebox, "showerror", showerror)
    app._variables["seed"].set(99)
    image = app._image
    app._events.put(ui._ProjectSavedEvent(Path("test.terrain.json"), app._generation_inputs()))
    app._poll_events()
    assert str(app.export_button["state"]) == "disabled"
    app._events.put(ui._ErrorEvent("Failed", "Generation failed", ValueError("test")))
    app._poll_events()
    assert errors and app._image is image
    assert str(app.export_button["state"]) == "disabled"


def test_all_instruction_kinds_edit_properties_without_moving_geometry(app: ui.TerrainApp) -> None:
    ring = ((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.2))
    constraints = (
        TerrainRegion(ring),
        TerrainBrushStroke(((0.3, 0.3),), 400, 90, 0.5, "relative"),
        TerrainStructure("ridge", ((0.3, 0.3), (0.4, 0.4)), 900, 40, "relative"),
        TerrainStructure("valley", ((0.6, 0.3), (0.7, 0.4)), 150, 40, "absolute"),
        TerrainBasin(ring, "lake", 200, (0.4, 0.3)),
        TerrainBasin(ring, "dry_basin"),
    )
    app._history.reset(constraints)
    app._select_instruction(0)
    app._region_character.set("mountains")
    app._region_values["relief_m"].set(3500)
    app._apply_instruction()
    region = app._constraints[0]
    assert isinstance(region, TerrainRegion)
    assert region.settings.character == "mountains" and region.settings.relief_m == 3500
    for index, tool in ((1, "brush"), (2, "ridge"), (3, "valley")):
        app._select_instruction(index)
        app._tool_elevations[tool].set(700)
        app._tool_sizes[tool].set(120)
        app._apply_instruction()
        feature = app._constraints[index]
        assert isinstance(feature, (TerrainBrushStroke, TerrainStructure))
        assert feature.elevation_m == 700
        assert feature.influence_radius_km == (60 if tool == "brush" else 120)
    app._select_instruction(4)
    app._lake_level.set(250)
    app._apply_instruction()
    lake = app._constraints[4]
    assert isinstance(lake, TerrainBasin) and lake.water_level_m == 250
    assert lake.outlet == (0.4, 0.3)
    app._select_instruction(5)
    assert not app._has_pending_instruction()
    for before, after in zip(constraints, app._constraints, strict=True):
        assert not isinstance(after, ElevationPoint)
        assert before.points == after.points


def test_delete_and_clear_are_reversible(app: ui.TerrainApp) -> None:
    original = app._constraints
    app._select_instruction(0)
    app._delete_instruction()
    assert not app._constraints
    app._undo_constraint()
    assert app._constraints == original
    app._clear_constraints()
    app._undo_constraint()
    assert app._constraints == original and app._reference_is_current()


def test_invalid_property_edit_is_atomic(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def showerror(*args: object, **kwargs: object) -> None:
        pass
    monkeypatch.setattr(ui.messagebox, "showerror", showerror)
    original = app._constraints
    app._select_instruction(0)
    app._tool_sizes["height"].set(-1)
    app._apply_instruction()
    assert app._constraints == original and not app._history.can_undo
    assert app._has_pending_instruction()


def test_new_coastline_drops_incompatible_reference_and_history(app: ui.TerrainApp) -> None:
    app._clear_constraints()
    assert app._coastline is not None
    app._accept_coastline(replace(app._coastline, source_name="another.svg"))
    assert app._image is None and app._terrain is None and app._generated_inputs is None
    assert not app._history.can_undo and not app._history.can_redo
    assert not app._reference_is_current()


def test_selection_by_canvas_and_list_never_paints(app: ui.TerrainApp) -> None:
    event: tk.Event[tk.Misc] = tk.Event()
    x, y = app._normalized_to_canvas((0.5, 0.5))
    event.x, event.y = round(x), round(y)
    assert app._select_on_map(event) == "break"
    assert app._selected_instruction == 0
    app._on_map_press(event)
    assert len(app._constraints) == 1 and not app._draft_points
    app._set_authoring_tool("height")
    assert app._selected_instruction is None
    app.instruction_input.current(1)
    app._on_instruction_selected(event)
    assert app._selected_instruction == 0


def test_regeneration_uses_changed_inputs_and_leaves_previous_dem_untouched(
    app: ui.TerrainApp,
) -> None:
    previous = app._terrain
    assert previous is not None
    original = previous.elevation_m.copy()
    app._history.append(TerrainRegion(
        ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8), (0.2, 0.2)),
        landform_preset("mountains"),
    ))
    app._instructions_changed("Mountains added")
    inputs = app._generation_inputs()
    app._generate()
    deadline = time.monotonic() + 30
    while not app._authoring_enabled and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert app._reference_is_current() and app._generated_inputs == inputs
    assert app._terrain is not None and app._terrain is not previous
    assert np.any(app._terrain.elevation_m != original)
    np.testing.assert_array_equal(previous.elevation_m, original)


def test_generation_requires_applied_properties_or_completed_draft(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[object] = []
    def showinfo(*args: object, **kwargs: object) -> None:
        messages.extend(args)
    monkeypatch.setattr(ui.messagebox, "showinfo", showinfo)
    app._select_instruction(0)
    app._tool_elevations["height"].set(3000)
    original = app._terrain
    app._generate()
    assert messages and app._terrain is original and app._authoring_enabled
    messages.clear()
    app._set_authoring_tool("ridge")
    app._draft_points.append((0.3, 0.3))
    app._generate()
    assert messages and app._terrain is original and app._authoring_enabled


def test_new_instruction_cancels_an_unfinished_draft(app: ui.TerrainApp) -> None:
    app._set_authoring_tool("ridge")
    app._draft_points.extend(((0.2, 0.2), (0.4, 0.4)))
    app.instruction_input.current(0)
    event: tk.Event[tk.Misc] = tk.Event()
    app._on_instruction_selected(event)
    assert not app._draft_points and not app._has_pending_instruction()


def _show_canvas(app: ui.TerrainApp) -> None:
    app.root.deiconify()
    app.root.geometry("1280x840")
    app.root.update()


def _map_event(app: ui.TerrainApp, position: tuple[float, float]) -> tk.Event[tk.Misc]:
    event: tk.Event[tk.Misc] = tk.Event()
    x, y = app._normalized_to_canvas(position)
    event.x, event.y = round(x), round(y)
    event.state = 0
    return event


def _wait_for_operation(app: ui.TerrainApp) -> None:
    deadline = time.monotonic() + 20
    while app._busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not app._busy


def test_view_navigation_preserves_inputs_and_reference_and_probe_uses_dem(
    app: ui.TerrainApp,
) -> None:
    _show_canvas(app)
    inputs, terrain, image = app._generation_inputs(), app._terrain, app._image
    assert terrain is not None
    app._saved_inputs = inputs
    app._zoom_view(4, (app.preview.winfo_width() / 2, app.preview.winfo_height() / 2))
    event = _map_event(app, (0.5, 0.5))
    app._begin_pan(event)
    event.x += 20
    app._pan_view(event)
    app._end_pan(event)
    position = (0.53, 0.47)
    canvas = app._normalized_to_canvas(position)
    assert app._canvas_to_normalized(*canvas) == pytest.approx(position)
    app._inspect_position(*app._normalized_to_canvas((0.5, 0.5)))
    assert "1,200 m ground" in str(app.cursor_label["text"])
    assert app._viewport.zoom == 4 and app._viewport.centre != (0.5, 0.5)
    assert app._generation_inputs() == inputs and app._reference_is_current()
    assert not app._document_is_dirty() and app._terrain is terrain and app._image is image
    app._fit_view()
    assert app._viewport.centre == (0.5, 0.5) and app._viewport.zoom == 1


def test_drag_commits_once_and_undo_restores_the_reference(app: ui.TerrainApp) -> None:
    _show_canvas(app)
    original = app._constraints
    terrain = app._terrain
    app._select_instruction(0)
    app.root.update()
    app._zoom_view(2)
    app._on_map_press(_map_event(app, (0.5, 0.5)))
    for x in (0.52, 0.54, 0.55):
        app._on_map_drag(_map_event(app, (x, 0.5)))
        assert app._constraints == original and not app._history.can_undo
    app._on_map_release(_map_event(app, (0.55, 0.5)))
    point = app._constraints[0]
    assert isinstance(point, ElevationPoint)
    assert point.position[0] == pytest.approx(0.55, abs=0.003)
    assert app._history.can_undo and not app._reference_is_current()
    app._undo_constraint()
    assert app._constraints == original and not app._history.can_undo
    assert app._reference_is_current() and app._terrain is terrain


def test_crossed_region_drag_is_rejected_and_escape_cancels_preview(app: ui.TerrainApp) -> None:
    _show_canvas(app)
    ring = ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8), (0.2, 0.2))
    app._history.reset((TerrainRegion(ring),))
    app._select_instruction(0)
    app._on_map_press(_map_event(app, ring[1]))
    app._on_map_drag(_map_event(app, (0.35, 0.9)))
    app._on_map_release(_map_event(app, (0.35, 0.9)))
    assert app._constraints == (TerrainRegion(ring),) and not app._history.can_undo
    assert "rejected" in str(app.status_label["text"])
    app._on_map_press(_map_event(app, ring[1]))
    app._on_map_drag(_map_event(app, (0.6, 0.3)))
    app._cancel_edit()
    app._on_map_release(_map_event(app, (0.6, 0.3)))
    assert app._constraints == (TerrainRegion(ring),) and not app._has_pending_instruction()


def test_geometry_guard_rejects_basins_touching_and_lines_crossing_water(
    app: ui.TerrainApp,
) -> None:
    ring = ((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4), (0.2, 0.2))
    basin = TerrainBasin(ring, "lake", 200, ring[0])
    app._history.reset((basin,))
    app._validate_instruction_geometry(basin, excluding=0)
    with pytest.raises(ValueError, match="overlap or touch"):
        app._validate_instruction_geometry(basin)
    outer = ((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.))
    app._coast_polygon = ui.Polygon(
        [app._normalized_to_source(p) for p in outer],
        holes=[[app._normalized_to_source(p) for p in ring]],
    )
    for instruction in (ElevationPoint((0.3, 0.3), 100, 20),
                        TerrainStructure("ridge", ((0.1, 0.3), (0.7, 0.3)), 200, 30)):
        with pytest.raises(ValueError, match="water holes"):
            app._validate_instruction_geometry(instruction)


def test_review_cache_is_reused_on_navigation_and_hidden_inputs_cannot_be_selected(
    app: ui.TerrainApp,
) -> None:
    _show_canvas(app)
    app._show_drainage.set(True)
    app._draw_preview()
    overlay = app._review_image
    assert overlay is not None
    app._zoom_view(32)
    assert app._review_image is overlay
    photo = app._review_photo
    assert photo is not None
    assert (photo.width(), photo.height()) == (app.preview.winfo_width(),
                                               app.preview.winfo_height())
    app._show_instructions.set(False)
    app._draw_preview()
    assert app._instruction_at(*app._normalized_to_canvas((0.5, 0.5))) is None
    app._show_catchments.set(True)
    app._draw_preview()
    assert app._review_image is not overlay


def test_input_shortcuts_leave_typing_alone_and_busy_workers_lock_inputs(
    app: ui.TerrainApp,
) -> None:
    _show_canvas(app)
    calls: list[str] = []
    app.root.focus_force()
    app.value_input.focus_set()
    app.root.update()
    assert app._shortcut(lambda: calls.append("delete"), editing=True) is None
    assert not calls
    app._set_busy(True)
    app._shortcut(lambda: calls.append("generate"))
    assert not calls
    assert all(str(widget["state"]) == "disabled" for widget in app._settings_widgets)
    app._set_busy(False)


def test_save_as_then_save_uses_known_path_and_roundtrips_edits(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    source = Path("examples/terrain/landform-regions.terrain.json")
    source_bytes = source.read_bytes()
    app._accept_project(load_terrain_project(source))
    assert not app._document_is_dirty()
    app._set_resolution(257)
    assert app._document_is_dirty() and app.root.title().startswith("* ")
    destination = tmp_path / "edited.terrain.json"
    dialogs: list[str] = []
    def save_dialog(**_kwargs: object) -> str:
        dialogs.append("save as")
        return str(destination)
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", save_dialog)
    app._save_project(save_as=True)
    _wait_for_operation(app)
    assert not app._document_is_dirty() and app._project_path == destination
    app._variables["seed"].set(18)
    app._save_project()
    _wait_for_operation(app)
    assert dialogs == ["save as"] and not app._document_is_dirty()
    loaded = load_terrain_project(destination)
    assert loaded.project.settings.seed == 18 and loaded.project.settings.resolution_px == 257
    assert source.read_bytes() == source_bytes


@pytest.mark.parametrize("answer, expected", [(None, []), (False, ["continued"])])
def test_unsaved_guard_can_cancel_or_discard(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
    answer: bool | None, expected: list[str],
) -> None:
    calls: list[str] = []
    def ask(*_args: object, **_kwargs: object) -> bool | None:
        return answer
    monkeypatch.setattr(ui.messagebox, "askyesnocancel", ask)
    app._guard_unsaved(lambda: calls.append("continued"))
    assert calls == expected


def test_save_guard_waits_for_success_and_cancelled_dialog_keeps_document_open(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app._accept_project(load_terrain_project(Path("examples/terrain/landform-regions.terrain.json")))
    app._project_path = None
    app._variables["seed"].set(24)
    calls: list[str] = []
    def ask(*_args: object, **_kwargs: object) -> bool:
        return True
    destination = ""
    def save_dialog(**_kwargs: object) -> str:
        return destination
    monkeypatch.setattr(ui.messagebox, "askyesnocancel", ask)
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", save_dialog)
    app._guard_unsaved(lambda: calls.append("continued"))
    assert not calls and not app._busy and app._document_is_dirty()
    destination = str(tmp_path / "saved.terrain.json")
    app._guard_unsaved(lambda: calls.append("continued"))
    assert not calls and app._busy
    _wait_for_operation(app)
    assert calls == ["continued"] and not app._document_is_dirty()


def test_failed_or_outdated_save_never_runs_destructive_continuation(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app._accept_project(load_terrain_project(Path("examples/terrain/landform-regions.terrain.json")))
    app._project_path = tmp_path / "saved.terrain.json"
    app._variables["seed"].set(42)
    calls: list[str] = []
    errors: list[object] = []
    def showerror(*args: object, **_kwargs: object) -> None:
        errors.extend(args)
    monkeypatch.setattr(ui.messagebox, "showerror", showerror)
    app._save_project(after_save=lambda: calls.append("continued"))
    # Programmatic changes can still arrive while widgets are disabled.
    app._variables["seed"].set(43)
    _wait_for_operation(app)
    assert not calls and app._document_is_dirty()
    assert load_terrain_project(app._project_path).project.settings.seed == 42
    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("Simulated write failure")
    monkeypatch.setattr(ui, "save_terrain_project", fail)
    app._save_project(after_save=lambda: calls.append("continued"))
    _wait_for_operation(app)
    assert errors and not calls and app._after_save is None and app._document_is_dirty()


def test_select_click_cannot_move_an_instruction_when_the_properties_change_layout(
    app: ui.TerrainApp,
) -> None:
    _show_canvas(app)
    app._set_selection_mode()
    app.root.update()
    original = app._constraints
    event = _map_event(app, (0.5, 0.5))
    app._on_map_press(event)
    app.root.update()
    app._on_map_release(event)
    assert app._constraints == original and not app._history.can_undo


def test_water_visibility_tracks_zoom_and_style_without_changing_or_exporting_viewport(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from map_maker.terrain.adapters.render import render_height_map, render_height_map_layers
    from map_maker.terrain.adapters.water_display import WATER_COLOUR, WATER_DISPLAY_ID

    terrain = app._terrain
    assert terrain is not None
    surface = np.full_like(terrain.water.surface_m, np.nan)
    surface[32, 32] = 2000.
    terrain = replace(terrain, water=replace(terrain.water, surface_m=surface))
    image, water = render_height_map_layers(terrain)
    app._events.put(ui._ResultEvent(app._generation_inputs(), terrain, image, water))
    app._poll_events()
    _show_canvas(app)
    app._show_instructions.set(False)
    before = terrain.elevation_m.copy(), terrain.water.surface_m.copy()
    assert app._water_display is water and water is not None
    app._zoom_view(4)
    assert app._water_display is water
    assert "km/sample" in str(app.zoom_label["text"])
    assert app._reference_is_current()
    photo = app._preview_photo
    assert photo is not None
    centre = (photo.width() // 2, photo.height() // 2)
    assert app.root.tk.call(str(photo), "get", *centre) == WATER_COLOUR
    export = tmp_path / "water.png"
    def choose_export(**_kwargs: object) -> str:
        return str(export)
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", choose_export)
    app._export()
    with Image.open(export) as exported, render_height_map(terrain) as expected:
        assert exported.size == image.size
        assert exported.tobytes() == expected.tobytes()
        assert exported.info["map-maker.water_visibility"] == WATER_DISPLAY_ID
    app._render_style_label.set("Scientific elevation")
    app._on_render_style_changed()
    assert app._water_display is None
    app._render_style_label.set("Cartographic relief")
    app._on_render_style_changed()
    assert app._water_display is not None
    for actual, expected in zip((terrain.elevation_m, terrain.water.surface_m),
                                 before, strict=True):
        np.testing.assert_array_equal(actual, expected)
    # Pending scale edits do not relabel the old generated map with the new scale.
    label = str(app.zoom_label["text"])
    app._inspect_position(*app._normalized_to_canvas((0.5, 0.5)))
    probe = str(app.cursor_label["text"])
    app._variables["object_scale_km"].set(terrain.settings.object_scale_km * 2)
    assert str(app.zoom_label["text"]) == label
    app._inspect_position(*app._normalized_to_canvas((0.5, 0.5)))
    assert str(app.cursor_label["text"]) == probe
    assert not app._reference_is_current()


def test_resolution_readout_keeps_navigation_available_in_small_window(app: ui.TerrainApp) -> None:
    _show_canvas(app)
    app.root.geometry("1040x700")
    app.root.update()
    app._draw_preview()
    app.root.update()
    for widget in app.zoom_label.master.winfo_children():
        assert widget.winfo_ismapped()
        assert widget.winfo_width() >= widget.winfo_reqwidth()


@pytest.mark.parametrize("escape", [False, True])
def test_cancel_waits_for_worker_and_preserves_reference_and_inputs(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch, escape: bool,
) -> None:
    entered, release = Event(), Event()
    terrain, image, inputs = app._terrain, app._image, app._generation_inputs()
    assert terrain is not None
    original = terrain.elevation_m.copy()
    errors: list[object] = []
    def show_error(*args: object, **_kwargs: object) -> None:
        errors.extend(args)

    monkeypatch.setattr(ui.messagebox, "showerror", show_error)

    def generate(*_args: object, **_kwargs: object) -> GeneratedTerrain:
        entered.set()
        assert release.wait(5), "Worker was not released"
        return terrain

    monkeypatch.setattr(ui, "generate_terrain", generate)
    app._generate()
    token = app._generation_cancel
    assert token is not None
    try:
        assert entered.wait(5)
        assert str(app.generate_button["text"]) == "Cancel generation"
        assert str(app.generate_button["state"]) == "normal"
        app._generation_started = time.monotonic() - 12
        app._poll_events()
        assert " s" in str(app.status_label["text"])
        if escape:
            assert app._escape() == "break"
        else:
            app.generate_button.invoke()
        assert token.is_cancelled and app._busy
        assert str(app.generate_button["state"]) == "disabled"
        app._events.put(ui._ProgressEvent(0.9, "Late progress", token))
        app._poll_events()
        assert "Cancelling" in str(app.status_label["text"])
        assert app._terrain is terrain and app._image is image
        assert not app._authoring_enabled
    finally:
        release.set()
    _wait_for_operation(app)
    assert not errors
    assert app._generation_cancel is None
    assert app._terrain is terrain and app._image is image
    assert app._generation_inputs() == inputs
    np.testing.assert_array_equal(terrain.elevation_m, original)
    assert app._reference_is_current()
    assert app._authoring_enabled
    assert str(app.generate_button["text"]) == "Generate terrain"
    assert str(app.generate_button["state"]) == "normal"
    assert "Generation cancelled" in str(app.status_label["text"])


def test_cancel_discards_a_result_already_waiting_in_the_ui_queue(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    terrain, image = app._terrain, app._image
    assert terrain is not None
    candidate = Image.new("RGBA", (65, 65))
    def completed(*_args: object, **_kwargs: object) -> GeneratedTerrain:
        return terrain

    monkeypatch.setattr(ui, "generate_terrain", completed)
    def rendered(*_args: object, **_kwargs: object) -> tuple[Image.Image, None]:
        return candidate, None

    monkeypatch.setattr(ui, "render_height_map_layers", rendered)
    app._generate()
    # Do not pump Tk until the worker has enqueued its completed result.
    while True:
        event = app._events.get(timeout=5)
        if isinstance(event, ui._ResultEvent):
            break
    app._events.put(event)
    app._cancel_generation()
    app._poll_events()
    assert not app._busy
    assert app._terrain is terrain and app._image is image
    with pytest.raises(ValueError, match="closed"):
        candidate.getpixel((0, 0))
    assert "cancelled" in str(app.status_label["text"])


def test_cancel_during_render_releases_new_images_and_does_not_show_an_error(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = Event(), Event()
    closing, release_cleanup = Event(), Event()
    terrain, image = app._terrain, app._image
    assert terrain is not None
    candidate, pool = Image.new("RGBA", (65, 65)), Image.new("F", (65, 65))
    close = candidate.close

    def finish_image() -> None:
        closing.set()
        assert release_cleanup.wait(5)
        close()

    monkeypatch.setattr(candidate, "close", finish_image)
    errors: list[object] = []
    def show_error(*args: object, **_kwargs: object) -> None:
        errors.extend(args)

    monkeypatch.setattr(ui.messagebox, "showerror", show_error)
    def completed(*_args: object, **_kwargs: object) -> GeneratedTerrain:
        return terrain

    monkeypatch.setattr(ui, "generate_terrain", completed)

    def render(*_args: object, **_kwargs: object) -> tuple[Image.Image, ui.WaterDisplay]:
        entered.set()
        assert release.wait(5)
        return candidate, ui.WaterDisplay(pool)

    monkeypatch.setattr(ui, "render_height_map_layers", render)
    app._generate()
    try:
        assert entered.wait(5)
        app._cancel_generation()
    finally:
        release.set()
    try:
        assert closing.wait(5)
        app._poll_events()
        assert app._busy, "Cancellation acknowledgement must follow resource cleanup"
    finally:
        release_cleanup.set()
    _wait_for_operation(app)
    assert not errors
    assert app._terrain is terrain and app._image is image
    for discarded in (candidate, pool):
        with pytest.raises(ValueError, match="closed"):
            discarded.getpixel((0, 0))


def test_old_generation_events_cannot_finish_or_replace_a_new_request(app: ui.TerrainApp) -> None:
    terrain, image = app._terrain, app._image
    assert terrain is not None
    old, current = CancellationToken(), CancellationToken()
    app._generation_cancel = current
    app._generation_started = time.monotonic()
    app._generation_message = "New request"
    app._set_busy(True)
    candidate = Image.new("RGBA", (65, 65))
    app._events.put(ui._CancelledEvent(old))
    app._events.put(ui._ErrorEvent("Old error", "Old failure", RuntimeError("old"), old))
    app._events.put(ui._ProgressEvent(1.0, "Old progress", old))
    app._events.put(ui._ResultEvent(app._generation_inputs(), terrain, candidate, None, old))
    app._poll_events()
    assert app._busy and app._generation_cancel is current
    assert app._terrain is terrain and app._image is image
    assert "New request" in str(app.status_label["text"])
    with pytest.raises(ValueError, match="closed"):
        candidate.getpixel((0, 0))
    current.cancel()
    app._events.put(ui._CancelledEvent(current))
    app._poll_events()
    assert not app._busy



def _assert_closed(*images: Image.Image | None) -> None:
    for image in images:
        assert image is not None
        with pytest.raises(ValueError, match="closed"):
            image.getpixel((0, 0))


def test_replacement_and_project_reset_release_previous_preview_owners(app: ui.TerrainApp) -> None:
    old_ground = app._image
    old_pool = Image.new("F", (65, 65), 16.)
    app._water_display = ui.WaterDisplay(old_pool)
    app._show_drainage.set(True)
    app._draw_preview()
    old_review = app._review_image
    terrain = app._terrain
    assert terrain is not None
    ground, pool = Image.new("RGBA", (65, 65)), Image.new("F", (65, 65), 16.)
    app._events.put(ui._ResultEvent(
        app._generation_inputs(), terrain, ground, ui.WaterDisplay(pool)))
    app._poll_events()
    _assert_closed(old_ground, old_pool, old_review)
    assert app._image is ground and pool.getpixel((0, 0)) == 16.
    current_review = app._review_image
    coast = app._coastline
    assert coast is not None
    app._accept_coastline(coast)
    _assert_closed(ground, pool, current_review)
    assert app._image is app._water_display is app._review_image is None
    assert app._preview_photo is app._review_photo is None


def test_successful_style_switch_releases_previous_ground_and_water(app: ui.TerrainApp) -> None:
    ground, pool = app._image, Image.new("F", (65, 65), 16.)
    app._water_display = ui.WaterDisplay(pool)
    app._render_style_label.set("Scientific elevation")
    app._on_render_style_changed()
    _assert_closed(ground, pool)
    assert app._image is not None and app._image.getpixel((0, 0)) is not None
    assert app._water_display is None
    assert app._image.info["map-maker.render_style"] == "scientific"


def test_failed_style_switch_keeps_pixels_water_and_legend(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image, water = app._image, app._water_display
    legend = str(app._legend_high_label["text"])
    errors: list[object] = []
    def fail(*_args: object, **_kwargs: object) -> tuple[Image.Image, ui.WaterDisplay | None]:
        raise MemoryError("replacement failed")
    def error(*args: object, **_kwargs: object) -> None:
        errors.extend(args)
    monkeypatch.setattr(ui, "render_height_map_layers", fail)
    monkeypatch.setattr(ui.messagebox, "showerror", error)
    app._render_style_label.set("Scientific elevation")
    app._on_render_style_changed()
    assert errors and app._image is image and app._water_display is water
    assert image is not None and image.getpixel((0, 0)) is not None
    assert app._render_style_label.get() == "Cartographic relief"
    assert str(app._legend_high_label["text"]) == legend


def test_overlay_toggle_releases_hidden_pixels_and_navigation_releases_tk_photos(
    app: ui.TerrainApp,
) -> None:
    _show_canvas(app)
    app._show_drainage.set(True)
    app._draw_preview()
    previous_review = app._review_image
    assert previous_review is not None
    for _ in range(4):
        old_names = str(app._preview_photo), str(app._review_photo)
        app._draw_preview()
        names = app.root.tk.splitlist(app.root.tk.call("image", "names"))
        assert not set(old_names).intersection(names)
        assert app._review_image is previous_review
    app._show_catchments.set(True)
    app._draw_preview()
    _assert_closed(previous_review)
    previous_review = app._review_image
    app._show_drainage.set(False)
    app._show_catchments.set(False)
    app._draw_preview()
    _assert_closed(previous_review)
    assert app._review_image is app._review_photo is None


@pytest.mark.parametrize("failed_transfer", [False, True])
def test_viewport_images_close_after_tk_transfer_or_failure(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch, failed_transfer: bool,
) -> None:
    _show_canvas(app)
    owned: list[Image.Image] = []
    render = ui.render_viewport
    def recorded(*args: Any, **kwargs: Any) -> Image.Image:
        image = render(*args, **kwargs)
        owned.append(image)
        return image
    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Tk transfer failed")
    monkeypatch.setattr(ui, "render_viewport", recorded)
    if failed_transfer:
        monkeypatch.setattr(ui.ImageTk, "PhotoImage", fail)
        with pytest.raises(RuntimeError, match="Tk transfer"):
            app._draw_preview()
    else:
        app._draw_preview()
    assert owned
    _assert_closed(*owned)
    assert app._image is not None and app._image.getpixel((0, 0)) is not None


def test_close_releases_ground_water_reviews_and_poll_callback(app: ui.TerrainApp) -> None:
    _show_canvas(app)
    ground, pool = app._image, Image.new("F", (65, 65), 16.)
    app._water_display = ui.WaterDisplay(pool)
    app._show_drainage.set(True)
    app._draw_preview()
    review = app._review_image
    callback = app._poll_after_id
    assert callback is not None
    app._close()
    _assert_closed(ground, pool, review)
    assert app._image is app._water_display is app._review_image is app._terrain is None
    assert app._preview_photo is app._review_photo is app._poll_after_id is None
    assert callback not in app.root.tk.splitlist(app.root.tk.call("after", "info"))
    app._close()  # Repeated disposal is harmless.



def test_failed_review_replacement_releases_new_canvas_and_keeps_previous_cache(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app._show_drainage.set(True)
    previous = app._review_layer()
    app._show_catchments.set(True)
    owned: list[Image.Image] = []
    new = Image.new
    def record(*args: Any, **kwargs: Any) -> Image.Image:
        image = new(*args, **kwargs)
        if image.mode == "RGBA" and image.size == previous.size:
            owned.append(image)
        return image
    def fail(*_args: object, **_kwargs: object) -> Image.Image:
        raise RuntimeError("review failed")
    monkeypatch.setattr(Image, "new", record)
    monkeypatch.setattr(ui, "render_basin_catchment_overlay", fail)
    with pytest.raises(RuntimeError, match="review failed"):
        app._review_layer()
    assert owned and app._review_image is previous
    _assert_closed(*owned)
    assert previous.getpixel((0, 0)) is not None


def test_failed_png_export_closes_export_image_and_keeps_readonly_reference(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ground = app._image
    assert ground is not None
    before = ground.tobytes()
    owned: list[Image.Image] = []
    errors: list[object] = []
    compose = ui.compose_height_map
    def record(*args: Any, **kwargs: Any) -> Image.Image:
        image = compose(*args, **kwargs)
        owned.append(image)
        return image
    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("PNG write failed")
    def error(*args: object, **_kwargs: object) -> None:
        errors.extend(args)
    def destination(**_kwargs: object) -> str:
        return str(tmp_path / "unwritten.png")
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", destination)
    monkeypatch.setattr(ui, "compose_height_map", record)
    monkeypatch.setattr(ui, "save_height_map", fail)
    monkeypatch.setattr(ui.messagebox, "showerror", error)
    app._export()
    assert errors and owned
    _assert_closed(*owned)
    assert app._image is ground and ground.tobytes() == before
    assert app._reference_is_current()


def test_density_is_an_input_and_channel_navigation_keeps_ground_immutable(
    app: ui.TerrainApp,
) -> None:
    _show_canvas(app)
    terrain = app._terrain
    assert terrain is not None
    ground = terrain.elevation_m.copy()
    assert "drainage_density" in app._variables
    app._show_drainage.set(True)
    app._draw_preview()
    display = app._channel_display
    assert display is not None
    fit = app._map_rect()
    assert fit is not None
    count = display.visible_reach_count(fit)
    app._zoom_view(4)
    zoom = app._map_rect()
    assert zoom is not None
    assert app._channel_display is display
    assert display.visible_reach_count(zoom) >= count
    app._all_channels.set(True)
    app._draw_preview()
    assert app._channel_display is display
    texts = " ".join(cast(str, app.preview.itemcget(item, "text"))
                     for item in app.preview.find_all() if str(app.preview.type(item)) == "text")
    assert "All channels" in texts and "all uphill edges red" in texts
    app._variables["drainage_density"].set(.5)
    assert app._read_settings().drainage_density == .5
    assert not app._reference_is_current()
    np.testing.assert_array_equal(terrain.elevation_m, ground)
    app._show_drainage.set(False)
    app._draw_preview()
    assert app._channel_display is None


def test_depressions_can_be_inspected_separately_from_channels(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _show_canvas(app)
    calls: list[str] = []
    render = ui.render_basin_overlay
    def record(*args: Any, **kwargs: Any) -> Image.Image:
        calls.append("basins")
        return render(*args, **kwargs)
    monkeypatch.setattr(ui, "render_basin_overlay", record)
    app._show_drainage.set(True)
    app._draw_preview()
    assert app._channel_display is not None
    assert calls == []
    app._show_depressions.set(True)
    app._draw_preview()
    assert calls == ["basins"]
    app._show_drainage.set(False)
    app._draw_preview()
    assert app._channel_display is None
    assert app._review_image is not None
    texts = " ".join(cast(str, app.preview.itemcget(item, "text"))
                     for item in app.preview.find_all() if str(app.preview.type(item)) == "text")
    assert "Purple: depressions" in texts and "reaches" not in texts
    app._show_depressions.set(False)
    app._draw_preview()
    assert app._review_image is None


def test_region_hole_selection_and_vertex_drag_preserve_the_cutout(app: ui.TerrainApp) -> None:
    _show_canvas(app)
    outer = ((.1, .1), (.9, .1), (.9, .9), (.1, .9), (.1, .1))
    hole = ((.4, .4), (.6, .4), (.6, .6), (.4, .6), (.4, .4))
    region = TerrainRegion(outer, holes=(hole,))
    app._history.reset((region,))
    app._select_instruction(0)
    assert app._instruction_at(*app._normalized_to_canvas((.5, .5))) is None
    assert app._instruction_at(*app._normalized_to_canvas((.2, .5))) == 0
    start, end = _map_event(app, hole[0]), _map_event(app, (.35, .35))
    a = app._canvas_to_normalized(float(start.x), float(start.y))
    b = app._canvas_to_normalized(float(end.x), float(end.y))
    assert a is not None and b is not None
    expected = (hole[0][0] + b[0] - a[0], hole[0][1] + b[1] - a[1])
    app._on_map_press(start)
    app._on_map_drag(end)
    app._on_map_release(end)
    updated = app._constraints[0]
    assert isinstance(updated, TerrainRegion)
    assert updated.points == outer
    assert updated.holes[0][0] == updated.holes[0][-1] == pytest.approx(expected)
    app._undo_constraint()
    assert app._constraints == (region,)


def test_line_profile_action_uses_history_and_retains_the_generated_reference(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from map_maker.terrain.domain import StructureProfileKnot as Knot
    ridge = TerrainStructure("ridge", ((.2, .4), (.8, .4)), 1200., 40., "relative")
    app._history.append(ridge)
    app._select_instruction(1)
    assert str(app.structure_profile_button["state"]) == "normal"
    original, image = app._terrain, app._image
    updated = replace(ridge, profile=(Knot(0., 600.), Knot(.5, 200.), Knot(1., 700.)))
    def edit_profile(*_args: object) -> TerrainStructure:
        return updated
    monkeypatch.setattr(ui, "edit_structure_profile", edit_profile)
    app._edit_structure_profile()
    assert app._constraints[1] == updated
    assert app._terrain is original and app._image is image
    assert not app._reference_is_current()
    app._undo_constraint()
    assert app._constraints[1] == ridge
    app._redo_constraint()
    assert app._constraints[1] == updated
    app._select_instruction(0)
    assert str(app.structure_profile_button["state"]) == "disabled"


def test_ridge_junction_failure_reaches_editor_without_replacing_reference(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from map_maker.terrain.domain import StructureProfileKnot as Knot
    main = TerrainStructure("ridge", ((.2, .4), (.8, .4)), 2000., 40.,
                            profile=(Knot(0., 2000.), Knot(1., 2000.)))
    branch = TerrainStructure("ridge", ((.5, .4), (.5, .8)), 1800., 30.,
                              profile=(Knot(0., 1800.), Knot(1., 600.)))
    app._history.reset((main, branch))
    app._instructions_changed("Test connected ridge conflict")
    terrain, image = app._terrain, app._image
    errors: list[str] = []
    def show_error(*args: object, **_kwargs: object) -> None:
        errors.extend(str(value) for value in args)
    monkeypatch.setattr(ui.messagebox, "showerror", show_error)
    app._generate()
    _wait_for_operation(app)
    assert any("Ridge junction conflict" in message and "profiles" in message for message in errors)
    assert app._terrain is terrain and app._image is image
    assert app._constraints == (main, branch)
    assert not app._reference_is_current() and app._authoring_enabled
