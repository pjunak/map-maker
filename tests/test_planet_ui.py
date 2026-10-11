# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Real Tk World-tab planet workflow: generate, view maps in any projection, zoom to
regional detail, export, cancel and invalidate."""

import json
import time
import tkinter as tk
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dmtools.terrain import ui
from dmtools.terrain.adapters.map_projection import PROJECTIONS
from dmtools.terrain.adapters.map_views import PREVIEW_LAYERS, THEMES, MapTheme
from dmtools.terrain.domain.planet import PlanetSettings

EXAMPLES = Path(__file__).parents[1] / "examples/world"
SMALL = PlanetSettings(nodes=6_000, duration_myr=4.0, step_kyr=250.0, climate_passes=1)


@pytest.fixture
def app() -> Iterator[ui.TerrainApp]:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}")
    root.geometry("1200x800")
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


def settle(app: ui.TerrainApp, condition: Callable[[], bool], seconds: float = 30) -> None:
    """Pump Tk until background view renders are delivered and ``condition`` holds."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.root.update()
        if app.world_workspace.renders.idle and condition():
            return
        time.sleep(0.01)
    raise AssertionError("The view did not finish rendering.")


def globe_current(app: ui.TerrainApp) -> bool:
    """The globe shows a full frame of its current view."""
    globe = app.world_workspace.map_view.globe
    frame = globe.frame
    return frame is not None and frame.lon is not None and frame.projection == globe.projection()


def planet_app(app: ui.TerrainApp) -> None:
    view = app.world_workspace
    view.load_world(EXAMPLES / "four-shores.dmworld.json")
    wait(app)
    view.generate_planet(SMALL, None)
    wait(app)
    assert view.planet_run is not None


def test_planet_maps_follow_the_registry_in_every_projection(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dmtools.terrain import world_view

    view = app.world_workspace
    view.load_world(EXAMPLES / "four-shores.dmworld.json")
    wait(app)
    panel, maps = view.planet_panel, view.map_view
    assert str(panel.export_button["state"]) == "disabled"
    assert str(maps.group_choice.buttons["Planet"]["state"]) == "disabled"
    view.generate_planet(SMALL, None)
    assert view.busy and view.status_bar.cancel_button.winfo_manager() == "grid"
    wait(app)
    run = view.planet_run
    assert run is not None and panel.run is run and maps.probe is not None
    assert set(run.previews) == set(PREVIEW_LAYERS)
    assert maps.display_layer.get() == "Planet atlas" and maps.group.get() == "Planet"
    assert tuple(maps.layer_input.cget("values")) == PREVIEW_LAYERS
    assert "nodes" in panel.detail.get() and f"{len(THEMES)} of {len(THEMES)}" in (
        panel.detail.get()
    )
    for theme in THEMES:
        maps.set_layer(theme.label)
        maps.draw_now()
        assert maps.photo is not None and maps.legend.get().startswith(theme.legend)
    # Every projection draws, globe and polar views off the Tk thread.
    maps.set_layer("Planet relief")
    for kind in PROJECTIONS:
        maps.projection.set(kind)
        maps.refresh()
        if kind != "equirectangular":
            settle(app, lambda: globe_current(app))
        assert maps.photo is not None
    maps.projection.set("globe")
    maps.refresh()
    settle(app, lambda: globe_current(app))
    centre = maps.globe.to_lonlat(maps.globe.winfo_width() / 2, maps.globe.winfo_height() / 2)
    assert centre is not None
    maps._hover_globe(centre)
    assert "°" in maps.inspection.get() and ("Ground" in maps.inspection.get()
                                              or "Sea" in maps.inspection.get())
    # Dragging turns the globe with quick frames, then a sharp one.
    before = maps.globe.lon
    maps.globe._press_left(SimpleNamespace(x=200, y=200))  # type: ignore[arg-type]
    maps.globe._drag(SimpleNamespace(x=260, y=180))  # type: ignore[arg-type]
    maps.globe._release(SimpleNamespace(x=260, y=180))  # type: ignore[arg-type]
    settle(app, lambda: globe_current(app))
    assert maps.globe.lon != before
    # Saving writes what is shown.
    render = maps.current_image()
    assert render is not None
    maps.save_image(tmp_path / "globe.png", render)
    wait(app)
    assert (tmp_path / "globe.png").stat().st_size > 0
    # A new registry theme appears without UI code once a build renders it.
    extra = MapTheme("political", "Political", "Realms and borders.")
    monkeypatch.setattr(world_view, "THEMES", (*THEMES, extra))
    monkeypatch.setattr(world_view, "THEME_BY_LABEL", {t.label: t for t in (*THEMES, extra)})
    run.previews["Political"] = run.previews["Planet relief"]
    maps.set_planet(run, maps.probe)
    assert "Political" in maps.layer_input.cget("values")
    maps.set_layer("Political")
    assert maps.display_layer.get() == "Political" and maps.legend.get() == "Realms and borders."
    del run.previews["Political"]
    destination = tmp_path / "planet"
    view.export_planet(destination)
    wait(app)
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["settings"]["nodes"] == SMALL.nodes
    # Editing the world invalidates the planet and returns the viewer to the source.
    view.values["name"].set("Edited world")
    app.root.update()
    assert view.planet_run is None and maps.display_layer.get() == "Source"
    assert maps.planet_run is None and str(panel.export_button["state"]) == "disabled"


def test_planet_cancel_and_changed_inputs_never_install_results(app: ui.TerrainApp) -> None:
    view = app.world_workspace
    view.load_world(EXAMPLES / "four-shores.dmworld.json")
    wait(app)
    view.generate_planet(SMALL, None)
    view.cancel_job()
    wait(app)
    assert view.planet_run is None and "cancelled" in view.status.get()
    view.generate_planet(SMALL, None)
    view.values["name"].set("Changed while generating")
    wait(app)
    assert view.planet_run is None
    view.map_view.set_layer("Planet relief")
    assert view.map_view.display_layer.get() == "Source"


def test_planet_panel_rejects_an_invalid_seed(app: ui.TerrainApp) -> None:
    panel = app.world_workspace.planet_panel
    panel.seed.set("not a number")
    panel.request_generate()
    assert "Seed" in panel.detail.get()
    assert not app.world_workspace.busy


def test_planet_probe_describes_sea_land_climate_and_lakes(app: ui.TerrainApp) -> None:
    from dmtools.terrain.map_probes import PlanetProbe
    from dmtools.terrain.pipeline.planet_koppen import KOPPEN

    planet_app(app)
    run = app.world_workspace.planet_run
    assert run is not None
    result = run.result
    probe = PlanetProbe(result)
    lon, lat = np.rad2deg(result.mesh.lon), np.rad2deg(result.mesh.lat)
    sea, land = int(np.flatnonzero(~result.land)[0]), int(np.flatnonzero(result.land)[0])
    assert probe.describe(float(lon[sea]), float(lat[sea])).startswith("Sea")
    text = probe.describe(float(lon[land]), float(lat[land]))
    assert text.startswith("Ground") and "mm/yr" in text and "°C" in text
    assert any(f" {code} " in text for code in KOPPEN[1:])
    volcanoes = result.volcanoes
    if len(volcanoes):
        x, y, z = (float(c) for c in volcanoes.xyz[0])
        on_volcano = probe.describe(
            float(np.degrees(np.arctan2(y, x))), float(np.degrees(np.arcsin(z)))
        )
        assert "volcano" in on_volcano or "caldera" in on_volcano or "seamount" in on_volcano


def test_zoom_to_region_drills_down_in_the_map_and_reuses_cached_tiles(
    app: ui.TerrainApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dmtools.terrain import world_ui
    from dmtools.terrain.domain.planet import RegionalSettings

    monkeypatch.setattr(world_ui, "user_tile_cache", lambda: tmp_path / "cache")
    monkeypatch.setattr(world_ui, "REGION_PIXELS", 160)
    coarse = RegionalSettings(
        spacing_km=40, process_area_km2=4_000, calibration_iterations=1, tile_km=1500,
        halo_km=200,
    )
    original = world_ui.region_window

    def coarse_window(*args: object, **kwargs: object) -> object:
        return original(*args, settings=coarse, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(world_ui, "region_window", coarse_window)
    view = app.world_workspace
    view.region_workers = 1
    planet_app(app)
    maps = view.map_view
    assert str(maps.pick_button["state"]) == "normal"
    # Picking: click the map, then the region opens in the same view.
    maps.picking.set(True)
    maps._picking_changed()
    maps.region_radius.set("600 km")
    maps._hover_flat((0.5, 0.45))
    assert maps._pick_at is not None and "radius 600 km" in maps.inspection.get()
    x, y = maps.flat.to_canvas(0.5, 0.45)
    maps._click_flat((0.5, 0.45), SimpleNamespace(x=x, y=y, state=0))  # type: ignore[arg-type]
    assert view.busy and not maps.picking.get()
    wait(app)
    assert maps.level == 1 and len(maps.levels) == 1
    level = maps.levels[0]
    assert level.run.window.tiles and abs(level.run.window.radius_m - 600e3) < 1
    assert maps.display_layer.get() == "Planet atlas"
    assert str(maps.projection_choice.buttons["globe"]["state"]) == "disabled"
    maps.draw_now()
    assert maps.photo is not None
    assert "of centre" in maps.describe_at(0.5, 0.5)
    # Other regional maps render in the background and are kept.
    maps.set_layer("Planet topographic")
    settle(app, lambda: "topographic" in level.images)
    assert level.theme_id == "topographic" and maps.legend.get().startswith("Atlas-style")
    maps.set_layer("Planet plates")  # not available for a region
    assert maps.display_layer.get() == "Planet topographic"
    tiles = sorted((tmp_path / "cache").rglob("tile-*.npz"))
    stamps = [p.stat().st_mtime_ns for p in tiles]
    # Back to the world keeps its map; the region is outlined there.
    maps.go_to_level(0)
    assert maps.level == 0 and maps.display_layer.get() == "Planet atlas"
    assert str(maps.pick_button["state"]) == "normal"
    lon, lat = level.run.window.centre
    view.zoom_region(lon, lat, 600)
    wait(app)
    assert tiles and [p.stat().st_mtime_ns for p in tiles] == stamps
    view.export_region(maps.levels[0].run, tmp_path / "region")
    wait(app)
    assert (tmp_path / "region" / "manifest.json").exists()
    # A new planet clears regional levels made from the old one.
    assert view.planet_run is not None
    maps.set_planet(replace(view.planet_run), maps.probe)
    assert maps.level == 0 and not maps.levels
