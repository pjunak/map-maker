# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Exercise world handoff through real Tk controls and document guards."""

import time
import tkinter as tk
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from dmtools.terrain import ui, world_terrain_ui, world_ui
from dmtools.terrain.adapters import load_svg_coastline_source, save_terrain_project
from dmtools.terrain.application.world import open_world

ROOT = Path(__file__).parents[1]


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
        open_world(ROOT / "examples/world/four-shores.dmworld.json"), None,
    )
    root.update()
    yield application
    if not application._closed:
        application._close()


def wait(app: ui.TerrainApp) -> None:
    deadline = time.monotonic() + 8
    while (app.world_workspace.busy or app._busy) and time.monotonic() < deadline:
        app.root.update()
        time.sleep(.01)
    app.root.update()
    assert not app.world_workspace.busy and not app._busy


def test_create_button_opens_saved_project_with_fixed_world_scale(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = app.world_workspace
    panel = view.terrain_panel
    view.pages.select(panel)
    assert view.pages.select() == str(panel)
    panel.continent.set("Southmere")
    target = tmp_path / "terrain"
    monkeypatch.setattr(world_terrain_ui.filedialog, "asksaveasfilename", reply(str(target)))
    panel.create_button.invoke()
    assert view.busy
    assert str(panel.create_button["state"]) == "disabled"
    wait(app)
    assert app._project_path == target / "terrain.dmterrain.json"
    assert app._coastline_source is not None
    assert app._coastline_source.world_terrain is not None
    assert not app._world_active()
    assert not app._document_is_dirty()
    assert app._read_settings().resolution_px == 257
    assert all(str(w["state"]) == "disabled" for w in app._world_scale_widgets)
    assert "Southmere" in panel.detail.get()
    assert str(panel.open_button["state"]) == "normal"
    assert "fixed" in str(app.status_label["text"])
    source = load_svg_coastline_source(ROOT / "tests/fixtures/terrain/closed-coast.svg")
    app._accept_coastline(source.coastline, source)
    assert all(str(w["state"]) == "normal" for w in app._world_scale_widgets)


def test_unsaved_terrain_survives_declined_handoff_and_can_open_later(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = load_svg_coastline_source(ROOT / "tests/fixtures/terrain/closed-coast.svg")
    app._accept_coastline(source.coastline, source)
    assert app._document_is_dirty()
    monkeypatch.setattr(ui.messagebox, "askyesnocancel", reply(None))
    view = app.world_workspace
    selected = next(c.id for c in view.continents if c.name == "Southmere")
    view.create_terrain(selected, tmp_path / "terrain")
    wait(app)
    assert app._coastline_source is source
    assert view.terrain_panel.created is not None
    assert view.terrain_panel.created.loaded.path.exists()
    monkeypatch.setattr(ui.messagebox, "askyesnocancel", reply(False))
    view.terrain_panel.open_button.invoke()
    wait(app)
    assert app._project_path == view.terrain_panel.created.loaded.path


def test_failed_projection_preserves_world_and_current_terrain(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = app.world_workspace
    original = view.project()
    errors: list[str] = []

    def error(_title: str, message: str, **_kwargs: object) -> None:
        errors.append(message)

    monkeypatch.setattr(world_ui.messagebox, "showerror", error)
    selected = next(c.id for c in view.continents if c.name == "Westreach")
    view.create_terrain(selected, tmp_path / "terrain")
    wait(app)
    assert errors and "regional" in errors[0]
    assert view.project() == original
    assert view.terrain_panel.created is None
    assert app._coastline is None
    assert not (tmp_path / "terrain").exists()
    assert str(view.terrain_panel.create_button["state"]) == "normal"


def test_open_prepared_reloads_latest_saved_instructions(
    app: ui.TerrainApp, tmp_path: Path,
) -> None:
    view = app.world_workspace
    selected = next(c.id for c in view.continents if c.name == "Southmere")
    view.create_terrain(selected, tmp_path / "terrain")
    wait(app)
    created = view.terrain_panel.created
    assert created is not None
    project = replace(created.loaded.project,
                      settings=replace(created.loaded.project.settings, seed=784))
    save_terrain_project(project, created.loaded.coastline_source, created.loaded.path)
    view.terrain_panel.open_button.invoke()
    wait(app)
    assert app._read_settings().seed == 784


def test_selected_geology_is_reloaded_at_creation(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmtools.terrain.adapters.world_geology import write_geology
    from dmtools.terrain.domain import TerrainRegion, landform_preset
    from dmtools.terrain.domain.world_geology import GeologyProfile, blank_geology

    view = app.world_workspace
    panel = view.terrain_panel
    value = blank_geology(view.project())
    path = tmp_path / "recipe.dmgeology.json"
    digest = write_geology(value, path, None)
    monkeypatch.setattr(world_terrain_ui.filedialog, "askopenfilename", reply(str(path)))
    panel.geology_button.invoke()
    assert panel.geology_path == path
    # Edits made after choosing the file must be included.
    value = replace(value, defaults=tuple(replace(
        d, profile=GeologyProfile(landform=landform_preset("plateau")),
    ) for d in value.defaults))
    write_geology(value, path, digest)
    panel.continent.set("Southmere")
    monkeypatch.setattr(world_terrain_ui.filedialog, "asksaveasfilename",
                        reply(str(tmp_path / "terrain")))
    panel.create_button.invoke()
    wait(app)
    assert panel.created is not None
    assert app._constraints
    assert all(isinstance(c, TerrainRegion) and c.settings.character == "plateau"
               for c in app._constraints)
    panel.clear_geology_button.invoke()
    assert panel.geology_path is None
    assert panel.created.source.geology is not None


def test_context_survives_handoff_save_and_generation(app: ui.TerrainApp, tmp_path: Path) -> None:
    view = app.world_workspace
    view.context_rows.set("18")
    view.generate_context()
    wait(app)
    assert view.context_run is not None
    selected = next(c.id for c in view.continents if c.name == "Southmere")
    view.create_terrain(selected, tmp_path / "terrain")
    wait(app)
    assert app._world_context is not None
    assert "context is connected" in str(app.status_label["text"])
    settings = replace(app._read_settings(), resolution_px=65)
    app._apply_settings(settings)
    app._generate()
    wait(app)
    assert app._terrain is not None
    assert app._terrain.world_context == app._world_context
    assert app._generated_inputs is not None
    assert app._generated_inputs.world_context == app._world_context
    app._save_project()
    wait(app)
    saved = view.terrain_panel.created
    assert saved is not None
    from dmtools.terrain.adapters.project import load_terrain_project

    reopened = load_terrain_project(saved.loaded.path)
    assert reopened.project.world_context == app._world_context
    app._accept_project(reopened)
    assert not app._document_is_dirty()
    source = load_svg_coastline_source(ROOT / "tests/fixtures/terrain/closed-coast.svg")
    app._accept_coastline(source.coastline, source)
    assert app._world_context is None
