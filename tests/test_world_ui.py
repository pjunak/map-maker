# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Real Tk world workflow: identity editing, document guards and workspace isolation."""

import time
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path

import pytest

from dmtools.terrain import ui, world_ui
from dmtools.terrain.adapters.world_svg import load_world_svg
from dmtools.terrain.application.world import open_world

EXAMPLES = Path(__file__).parents[1] / "examples/world"


@pytest.fixture
def app() -> Iterator[ui.TerrainApp]:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}")
    root.withdraw()
    application = ui.TerrainApp(root)
    root.update()
    yield application
    if not application._closed:
        application._close()


def wait_world(app: ui.TerrainApp) -> None:
    deadline = time.monotonic() + 5
    while app.world_workspace.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    app.root.update()
    assert not app.world_workspace.busy


def test_world_import_assignment_validate_save_and_reopen(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = app.world_workspace
    assert app._world_active()
    view.load_svg(EXAMPLES / "coastlines.svg")
    wait_world(app)
    assert view.source is not None and not view.assignments and view.dirty
    view.suggest_groups()
    assert len(view.continents) == 4
    before = view.assignments
    view.undo()
    assert not view.assignments
    view.redo()
    assert view.assignments == before
    view.values["radius"].set("6500")
    for key, value in (("x", "10"), ("y", "10"), ("width", "360"), ("height", "180")):
        view.values[key].set(value)
    view.validate()
    wait_world(app)
    assert view.validated is not None and view.dirty
    destination = tmp_path / "world.dmworld.json"

    def save_path(**_kwargs: object) -> str:
        return str(destination)

    monkeypatch.setattr(world_ui.filedialog, "asksaveasfilename", save_path)
    view.save()
    wait_world(app)
    assert not view.dirty and view.path == destination
    assert len(open_world(destination).continents) == 4
    view.values["name"].set("Edited")
    assert view.dirty and view.validated is None
    view.load_world(destination)
    wait_world(app)
    assert not view.dirty and view.values["name"].get() != "Edited"


def test_world_assign_exclude_and_rename_retain_identity(
    app: ui.TerrainApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tkinter import simpledialog

    view = app.world_workspace
    view.accept_world(
        open_world(EXAMPLES / "four-shores.dmworld.json"), EXAMPLES / "four-shores.dmworld.json"
    )
    west = next(c for c in view.continents if c.name == "Westreach")
    view.owner.set("Westreach")

    def rename_reply(*_args: object, **_kwargs: object) -> str:
        return "Renamed"

    monkeypatch.setattr(simpledialog, "askstring", rename_reply)
    view.rename_continent()
    assert next(c for c in view.continents if c.id == west.id).name == "Renamed"
    view.tree.selection_set("south-island")
    view.owner.set("Westreach")
    view.role.set("Island")
    view.assign_selected()
    added = next(c for c in view.continents if c.name == "Westreach")
    assert added.id != west.id
    assert next(a for a in view.assignments if a.feature_id == "west-main").continent_id == west.id
    view.tree.selection_set("south-island")
    view.role.set("Exclude")
    view.assign_selected()
    assert next(a for a in view.assignments if a.feature_id == "south-island").continent_id is None
    assert added.id not in {c.id for c in view.continents}


def test_world_shortcuts_do_not_edit_hidden_terrain(app: ui.TerrainApp) -> None:
    view = app.world_workspace
    view.accept_source(load_world_svg(EXAMPLES / "coastlines.svg"))
    view.suggest_groups()
    assert view.assignments
    app._shortcut(app._undo_constraint, editing=True)
    assert not view.assignments and not app._history.constraints
    app.workspaces.select(app.terrain_page)
    app.root.update()
    assert not app._world_active()
    app._shortcut(app._redo_constraint, editing=True)
    assert not view.assignments
    app.workspaces.select(view)
    app.root.update()
    app._shortcut(app._redo_constraint, editing=True)
    assert view.assignments


def test_world_close_cancel_and_failed_load_preserve_work(
    app: ui.TerrainApp,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    view = app.world_workspace
    view.accept_source(load_world_svg(EXAMPLES / "coastlines.svg"))
    retained = view.source

    def cancel_reply(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(world_ui.messagebox, "askyesnocancel", cancel_reply)
    app._request_close()
    assert not app._closed and view.source is retained
    errors: list[str] = []

    def collect_error(*args: object, **_kwargs: object) -> None:
        errors.append(str(args))

    monkeypatch.setattr(world_ui.messagebox, "showerror", collect_error)
    view.load_world(tmp_path / "missing.dmworld.json")
    wait_world(app)
    assert errors and view.source is retained and view.dirty


def test_world_busy_guard_and_cleanup(app: ui.TerrainApp) -> None:
    import threading

    view = app.world_workspace
    calls: list[bool] = []
    release = threading.Event()
    view.jobs.start("Blocking", lambda _report, _token: release.wait(5), lambda _done: None)
    assert view.busy
    view.guard(lambda: calls.append(True))
    assert not calls and "Wait" in view.status.get()
    release.set()
    wait_world(app)
    view.guard(lambda: calls.append(True))
    assert calls
    app._close()
    assert view._closed and view.pump.closed and not view.busy


def test_import_issues_are_visible_and_selected(app: ui.TerrainApp) -> None:
    from dmtools.terrain.adapters.world_svg import parse_world_svg

    view = app.world_workspace
    view.accept_source(
        parse_world_svg(
            '<svg viewBox="0 0 360 180"><g id="North">'
            '<path id="land" d="M10 10 H30 V30 H10 Z"/>'
            '<path id="broken" d="M50 50 L60 60"/></g></svg>',
            "issues.svg",
        )
    )
    app.root.update()
    assert view.tree.selection() == ("broken",)
    assert "Needs attention" in view.tree.item("broken", "values")
    assert "1 import issues" in view.summary.get()
    assert "Open path" in str(view.detail.cget("text"))
    view.suggest_groups()
    assert "1 unassigned" in view.summary.get() and "0 excluded" in view.summary.get()
    view.role.set("Exclude")
    view.assign_selected()
    assert "1 excluded" in view.summary.get()


def test_validation_selects_overlapping_shapes(
    app: ui.TerrainApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmtools.terrain.adapters.world_svg import parse_world_svg

    view = app.world_workspace
    view.accept_source(
        parse_world_svg(
            '<svg viewBox="0 0 360 180"><g id="North">'
            '<path id="first" d="M10 10 H30 V30 H10 Z"/>'
            '</g><g id="South"><path id="second" d="M20 20 H40 V40 H20 Z"/>'
            '<path id="separate" d="M100 100 H120 V120 H100 Z"/></g></svg>',
            "overlap.svg",
        )
    )
    view.suggest_groups()
    view.values["radius"].set("6000")
    errors: list[str] = []

    def collect_error(*args: object, **_kwargs: object) -> None:
        errors.append(str(args))

    monkeypatch.setattr(world_ui.messagebox, "showerror", collect_error)
    view.validate()
    wait_world(app)
    assert errors and "100 square source units" in errors[0]
    assert set(view.tree.selection()) == {"first", "second"}
    assert view.validated is None


def test_tolerated_import_adjustments_validate_save_reopen_and_clear(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmtools.terrain.adapters.world_svg import parse_world_svg

    view = app.world_workspace
    view.accept_source(
        parse_world_svg(
            '<svg viewBox="0 0 360 180"><g id="West">'
            '<path id="west" d="M10 170 H100 V180.0009 H10 Z"/>'
            '<path id="contained" d="M20 172 H30 V175 H20 Z"/></g>'
            '<g id="East"><path id="east" d="M99.9995 170 H180 V180 H99.9995 Z"/></g></svg>',
            "rounding.svg",
        )
    )
    source = view.source
    view.suggest_groups()
    assignments = view.assignments
    view.values["radius"].set("1000")
    view.validate()
    wait_world(app)
    assert view.validated is not None
    assert len(view.validated.adjustments) == 3
    assert "3 import adjustments" in view.summary.get()
    view.pages.select(view.adjustments_page)
    view.adjustment_tree.selection_set("0")
    view._review_adjustment()
    assert set(view.tree.selection()) == set(view.validated.adjustments[0].feature_ids)
    assert "export overflow" in str(view.adjustment_detail.cget("text"))
    target = tmp_path / "accepted.dmworld.json"

    def save_path(**_kwargs: object) -> str:
        return str(target)

    monkeypatch.setattr(world_ui.filedialog, "asksaveasfilename", save_path)
    view.save()
    wait_world(app)
    assert target.exists() and not view.dirty
    view.load_world(target)
    wait_world(app)
    assert view.source == source and set(view.assignments) == set(assignments)
    assert view.validated is not None and len(view.validated.adjustments) == 3
    assert len(view.adjustment_tree.get_children()) == 3
    view.values["radius"].set("1100")
    assert view.validated is None and not view.adjustment_tree.get_children()


def test_context_generate_inspect_export_and_invalidate(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = app.world_workspace
    view.accept_world(
        open_world(EXAMPLES / "four-shores.dmworld.json"), EXAMPLES / "four-shores.dmworld.json"
    )
    view.context_rows.set("12")
    view.generate_context()
    wait_world(app)
    assert view.context_run is not None
    assert view.map_view.display_layer.get() == "Land coverage"
    assert "connected water regions" in view.context_detail.get()
    assert not view.dirty
    generated = view.context_run
    maps = view.map_view
    maps.set_layer("Water exposure")
    assert maps.bearing_input.winfo_manager() == "pack"
    maps.exposure_bearing.set("W")
    maps.set_layer()
    maps.draw_now()
    assert view.context_run is generated and not view.dirty
    assert "not rainfall" in maps.legend.get()
    maps.set_layer("Shore distance")
    assert not maps.bearing_input.winfo_manager()
    assert "inland shores" in maps.legend.get()
    maps.set_layer("Resolution support")
    maps.draw_now()
    assert maps.photo is not None
    target = tmp_path / "context"

    def choose_path(**_kwargs: object) -> str:
        return str(target)

    monkeypatch.setattr(world_ui.filedialog, "asksaveasfilename", choose_path)
    view.export_context()
    wait_world(app)
    assert (target / "context.json").exists()
    assert "Context exported" in view.status.get()
    view.context_rows.set("24")
    assert view.context_run is None and view.map_view.display_layer.get() == "Source"
    assert not view.dirty
    view.generate_context()
    wait_world(app)
    assert view.context_run is not None
    view.values["radius"].set("5000")
    assert view.context_run is None and view.dirty


def test_context_cancel_and_changed_inputs_never_install_new_results(app: ui.TerrainApp) -> None:
    view = app.world_workspace
    view.accept_world(
        open_world(EXAMPLES / "four-shores.dmworld.json"), EXAMPLES / "four-shores.dmworld.json"
    )
    view.context_rows.set("12")
    view.generate_context()
    view.cancel_job()
    wait_world(app)
    assert view.context_run is None
    assert "cancelled" in view.status.get()
    view.generate_context()
    # Programmatic edits also invalidate a pending result, even though UI controls lock.
    view.values["radius"].set("4000")
    wait_world(app)
    assert view.context_run is None
    assert "inputs changed" in view.status.get()


def test_issue_highlighting_returns_to_source_after_context(app: ui.TerrainApp) -> None:
    view = app.world_workspace
    view.accept_world(
        open_world(EXAMPLES / "four-shores.dmworld.json"), EXAMPLES / "four-shores.dmworld.json"
    )
    view.context_rows.set("12")
    view.generate_context()
    wait_world(app)
    assert view.context_run is not None and view.source is not None
    selected = view.source.features[0].id
    view._select_issues((selected,))
    assert view.map_view.display_layer.get() == "Source"
    assert view.tree.selection() == (selected,)


def test_context_reopen_restores_inputs_without_making_snapshot_a_save_target(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmtools.terrain.adapters.build import file_sha256
    from dmtools.terrain.application.world_context import export_context, generate_context
    from dmtools.terrain.domain.world_context import WorldContextSettings

    source = open_world(EXAMPLES / "four-shores.dmworld.json")
    run = generate_context(source.project, WorldContextSettings(12))
    bundle = export_context(run, tmp_path / "saved-context")
    snapshot = bundle.parent / "world.dmworld.json"
    before = file_sha256(snapshot)
    view = app.world_workspace
    view.load_context(bundle)
    wait_world(app)
    assert view.context_run is not None and view.path is None and not view.dirty
    assert view.context_rows.get() == "12"
    assert view.context_run.context.world.project == source.project
    view.map_view.set_layer("Water openings")
    view.map_view.draw_now()
    assert view.map_view.photo is not None
    edited = tmp_path / "edited.dmworld.json"

    def choose_save(**_kwargs: object) -> str:
        return str(edited)

    monkeypatch.setattr(world_ui.filedialog, "asksaveasfilename", choose_save)
    view.values["name"].set("Separate authored project")
    assert view.context_run is None and view.dirty
    view.save()
    wait_world(app)
    assert view.path == edited and edited.exists()
    assert file_sha256(snapshot) == before


def test_failed_cancelled_or_obsolete_context_open_preserves_current_work(
    app: ui.TerrainApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmtools.terrain.application.world_context import export_context, generate_context
    from dmtools.terrain.domain.world_context import WorldContextSettings

    source = open_world(EXAMPLES / "four-shores.dmworld.json")
    run = generate_context(source.project, WorldContextSettings(12))
    bundle = export_context(run, tmp_path / "context")
    view = app.world_workspace
    view.accept_world(source, EXAMPLES / "four-shores.dmworld.json")
    errors: list[str] = []

    def show_error(*args: object, **_kwargs: object) -> None:
        errors.append(str(args))

    monkeypatch.setattr(world_ui.messagebox, "showerror", show_error)
    view.load_context(tmp_path / "missing" / "context.json")
    wait_world(app)
    assert errors and view.source == source.project.source
    view.load_context(bundle)
    view.cancel_job()
    wait_world(app)
    assert view.context_run is None and "cancelled" in view.status.get()
    view.load_context(bundle)
    view.values["name"].set("Keep these edits")
    wait_world(app)
    assert view.values["name"].get() == "Keep these edits" and view.dirty
    assert view.context_run is None and "inputs changed" in view.status.get()


def test_water_connectivity_inspection_shows_pieces_and_finite_links(app: ui.TerrainApp) -> None:
    import numpy as np
    from test_world_context import project

    from dmtools.terrain.application.world_context import generate_context
    from dmtools.terrain.domain.world_context import WorldContextSettings

    app.root.geometry("1160x760")
    app.root.deiconify()
    app.root.update()
    p = project('<path d="M172 50 H178 V100 H172 Z"/>')
    run = generate_context(p, WorldContextSettings(12))
    view = app.world_workspace
    view.accept_world(run.context.world, None)
    view._show_context(run)
    maps = view.map_view
    maps.set_layer("Water connectivity")
    maps.draw_now()
    assert maps.photo is not None
    assert "gold" in maps.legend.get()
    assert "shared intervals" in view.context_detail.get()
    assert "components match source" in view.context_detail.get()
    view.pages.select(view.context_page)
    app.root.update()
    assert view.context_text.cget("state") == "disabled"
    assert view.context_text.get("1.0", "end-1c") == view.context_detail.get()
    view.context_text.yview_moveto(1)
    app.root.update()
    assert view.context_text.yview()[1] == 1
    assert view.context_text.winfo_height() > 40
    cell = int(np.flatnonzero(np.diff(run.context.connectivity.cell_offsets) > 1)[0])
    row, col = divmod(cell, 24)
    x, y = maps.flat.to_canvas((col + 0.5) / 24, (row + 0.5) / 12)
    event: tk.Event[tk.Misc] = tk.Event()
    event.x, event.y = round(x), round(y)
    maps.flat._motion(event)
    assert "2 water pieces" in maps.inspection.get()
    assert "region 1" in maps.inspection.get() and "intervals" in maps.inspection.get()
