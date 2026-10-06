# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Real Tk World-tab Planet stage: generate, view layers, export, cancel and invalidate."""

import json
import time
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from dmtools.terrain import ui
from dmtools.terrain.adapters.planet_render import PREVIEW_LAYERS
from dmtools.terrain.domain.planet import PlanetSettings

EXAMPLES = Path(__file__).parents[1] / "examples/world"
SMALL = PlanetSettings(nodes=6_000, duration_myr=4.0, step_kyr=250.0, climate_passes=1)


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


def wait(app: ui.TerrainApp, seconds: float = 120) -> None:
    deadline = time.monotonic() + seconds
    while app.world_workspace.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    app.root.update()
    assert not app.world_workspace.busy


def test_planet_stage_generates_shows_layers_exports_and_invalidates(
    app: ui.TerrainApp, tmp_path: Path
) -> None:
    view = app.world_workspace
    view.load_world(EXAMPLES / "four-shores.dmworld.json")
    wait(app)
    panel = view.planet_panel
    assert str(panel.export_button["state"]) == "disabled"
    view.generate_planet(SMALL, None)
    assert view.busy and str(panel.cancel_button["state"]) == "normal"
    wait(app)
    run = view.planet_run
    assert run is not None and panel.run is run
    assert set(run.previews) == set(PREVIEW_LAYERS)
    assert view.display_layer.get() == "Planet atlas"
    assert "nodes" in panel.detail.get() and "Lakes" in panel.detail.get()
    for layer in PREVIEW_LAYERS:
        view.display_layer.set(layer)
        view._layer_changed()
        view._draw()
        assert view._photo is not None
    assert str(panel.export_button["state"]) == "normal"
    destination = tmp_path / "planet"
    view.export_planet(destination)
    wait(app)
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["settings"]["nodes"] == SMALL.nodes
    # Editing the world invalidates the planet and returns the viewer to the source.
    view.values["name"].set("Edited world")
    app.root.update()
    assert view.planet_run is None and view.display_layer.get() == "Source"
    assert str(panel.export_button["state"]) == "disabled"


def test_planet_cancel_and_changed_inputs_never_install_results(app: ui.TerrainApp) -> None:
    view = app.world_workspace
    view.load_world(EXAMPLES / "four-shores.dmworld.json")
    wait(app)
    view.generate_planet(SMALL, None)
    view.cancel_context()
    wait(app)
    assert view.planet_run is None
    view.generate_planet(SMALL, None)
    view.values["name"].set("Changed while generating")
    wait(app)
    assert view.planet_run is None
    view.display_layer.set("Planet relief")
    view._layer_changed()
    assert view.display_layer.get() == "Source"


def test_planet_panel_rejects_an_invalid_seed(app: ui.TerrainApp) -> None:
    panel = app.world_workspace.planet_panel
    panel.seed.set("not a number")
    panel.request_generate()
    assert "Seed" in panel.detail.get()
    assert not app.world_workspace.busy


def test_planet_probe_describes_sea_land_climate_and_lakes(app: ui.TerrainApp) -> None:
    from dmtools.terrain.planet_ui import PlanetProbe

    view = app.world_workspace
    view.load_world(EXAMPLES / "four-shores.dmworld.json")
    wait(app)
    view.generate_planet(SMALL, None)
    wait(app)
    assert view.planet_run is not None
    result = view.planet_run.result
    probe = PlanetProbe(result)
    lon, lat = np.rad2deg(result.mesh.lon), np.rad2deg(result.mesh.lat)
    sea, land = int(np.flatnonzero(~result.land)[0]), int(np.flatnonzero(result.land)[0])
    assert probe.describe(float(lon[sea]), float(lat[sea])).startswith("Sea")
    text = probe.describe(float(lon[land]), float(lat[land]))
    assert text.startswith("Ground") and "mm/yr" in text and "°C" in text
