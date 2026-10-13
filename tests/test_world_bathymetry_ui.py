# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Real Tk ocean selection, stale previews and guarded authored-input lifecycle."""

import time
import tkinter as tk
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from dmtools.terrain import ui
from dmtools.terrain import world_bathymetry_ui as module
from dmtools.terrain.adapters.build import file_sha256
from dmtools.terrain.application.world import open_world
from dmtools.terrain.application.world_bathymetry import BathymetryRun
from dmtools.terrain.application.world_context import WorldContextRun, generate_context
from dmtools.terrain.domain.world_bathymetry import BathymetryInputs
from dmtools.terrain.domain.world_context import WorldContextSettings
from dmtools.terrain.pipeline.control import CancellationToken, ProgressCallback
from dmtools.terrain.world_bathymetry_ui import BathymetryEditor

EXAMPLES = Path(__file__).parents[1] / "examples/world"


def reply(value: object) -> Callable[..., object]:
    def respond(*_args: object, **_kwargs: object) -> object:
        return value

    return respond


def wait(editor: BathymetryEditor) -> None:
    deadline = time.monotonic() + 10
    while editor.busy and time.monotonic() < deadline:
        editor.update()
        time.sleep(0.01)
    if not editor._closed:
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


def edit(app: ui.TerrainApp) -> BathymetryEditor:
    workspace = app.world_workspace
    assert workspace.validated is not None
    workspace.context_run = generate_context(workspace.validated.project, WorldContextSettings(8))
    workspace.edit_bathymetry()
    editor = workspace.bathymetry_editor
    assert editor is not None
    wait(editor)
    return editor


def test_generates_missing_context_and_reuses_window(app: ui.TerrainApp) -> None:
    workspace = app.world_workspace
    workspace.context_rows.set("8")
    workspace.edit_bathymetry()
    assert workspace.bathymetry_editor is None and workspace.busy  # context comes first
    deadline = time.monotonic() + 10
    while workspace.bathymetry_editor is None and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    editor = workspace.bathymetry_editor
    assert editor is not None and workspace.context_run is not None
    assert workspace.step == "ocean"
    wait(editor)
    workspace.edit_bathymetry()
    assert workspace.bathymetry_editor is editor
    assert editor.inputs().ocean_ids == (1,)
    assert not editor.dirty


def test_generate_stale_export_and_parent_source_isolation(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = EXAMPLES / "four-shores.dmworld.json"
    before = file_sha256(source)
    editor = edit(app)
    parent_context = app.world_workspace.context_run
    editor.generate()
    wait(editor)
    assert editor.run is not None and editor.current
    assert editor.run.result.sampled_cells > 0
    previous = editor.run
    for layer in ("Connected water", "Ocean floor", "Distance error", "Resolution support"):
        editor.layer.set(layer)
        editor.canvas.draw_now()
        assert editor.canvas.photo is not None
    editor.values["basin_depth_m"].set("5000")
    assert editor.dirty and not editor.current and editor.run is previous
    path = tmp_path / "ocean"
    monkeypatch.setattr(module.filedialog, "asksaveasfilename", reply(str(path)))
    editor.export()
    assert not editor.busy and not path.exists()
    editor.canvas.draw_now()
    assert any(
        "PREVIOUS RESULT" in cast(str, editor.canvas.itemcget(item, "text"))
        for item in editor.canvas.find_all()
        if editor.canvas.type(item) == "text"
    )
    editor.generate()
    wait(editor)
    editor.export()
    wait(editor)
    assert (path / "bathymetry.json").exists()
    assert app.world_workspace.context_run is parent_context
    assert file_sha256(source) == before and not app.world_workspace.dirty


def test_saved_inputs_external_change_and_generated_snapshot_save_target(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = edit(app)
    editor.values["basin_depth_m"].set("5000")
    path = tmp_path / "ocean.dmbathy.json"
    monkeypatch.setattr(module.filedialog, "asksaveasfilename", reply(str(path)))
    editor.save()
    wait(editor)
    assert editor.file and editor.file.path == path and not editor.dirty
    editor.close()
    app.world_workspace.edit_bathymetry()
    reopened = app.world_workspace.bathymetry_editor
    assert reopened is not None
    wait(reopened)
    assert reopened.inputs().settings.basin_depth_m == 5000
    path.write_bytes(path.read_bytes() + b" ")
    reopened.values["basin_depth_m"].set("6000")
    continued: list[bool] = []
    reopened.save(after=lambda: continued.append(True))
    wait(reopened)
    assert not continued and reopened.dirty and "outside" in reopened.status.get()
    reopened.generate()
    wait(reopened)
    output = tmp_path / "result"
    monkeypatch.setattr(module.filedialog, "asksaveasfilename", reply(str(output)))
    reopened.export()
    wait(reopened)
    reopened.load_result(output / "bathymetry.json")
    wait(reopened)
    assert reopened.file is None and reopened.current and not reopened.dirty
    assert reopened.inputs().settings.basin_depth_m == 6000


def test_invalid_inputs_close_guard_and_save_before_continue(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = edit(app)
    editor.tree.selection_set(())
    editor.update()
    editor.generate()
    assert not editor.busy and "Select" in editor.status.get()
    continued: list[bool] = []
    monkeypatch.setattr(module.messagebox, "askyesnocancel", reply(True))
    editor.guard(lambda: continued.append(True))
    assert not continued
    editor.tree.selection_set(("1",))
    editor.values["shelf_width_km"].set("not a number")
    editor.generate()
    assert not editor.busy
    editor.values["shelf_width_km"].set("150")
    path = tmp_path / "saved.dmbathy.json"
    monkeypatch.setattr(module.filedialog, "asksaveasfilename", reply(str(path)))
    editor.guard(lambda: continued.append(True))
    wait(editor)
    assert continued == [True] and path.exists() and not editor.dirty
    editor.values["shelf_width_km"].set("200")
    monkeypatch.setattr(module.messagebox, "askyesnocancel", reply(None))
    app.world_workspace.guard(lambda: continued.append(False))
    assert continued == [True] and not editor._closed
    monkeypatch.setattr(module.messagebox, "askyesnocancel", reply(False))
    app.world_workspace.guard(lambda: continued.append(False))
    assert continued == [True, False] and editor._closed


def test_cancel_retains_previous_result_and_freezes_selection(
    app: ui.TerrainApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = edit(app)
    editor.generate()
    wait(editor)
    previous = editor.run
    editor.values["shelf_width_km"].set("150")
    entered, release = Event(), Event()
    original = module.generate_bathymetry

    def slow(
        inputs: BathymetryInputs,
        context: WorldContextRun | None = None,
        progress: ProgressCallback | None = None,
        *,
        cancellation: CancellationToken | None = None,
    ) -> BathymetryRun:
        entered.set()
        release.wait(3)
        return original(inputs, context, progress, cancellation=cancellation)

    monkeypatch.setattr(module, "generate_bathymetry", slow)
    editor.generate()
    assert entered.wait(2)
    editor.tree.selection_set(())
    editor.update()
    assert editor.tree.selection() == ("1",)
    editor.cancel()
    release.set()
    wait(editor)
    assert editor.run is previous and not editor.current
    assert "Cancelled" in editor.status.get()
