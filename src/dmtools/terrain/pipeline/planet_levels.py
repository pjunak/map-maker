# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Level parents: a coarser regional level presented as the parent of finer detail.

Level-n tiles are enriched like level-1 tiles, but their parent is a patch mesh
at level n-1 spacing (ADR-0088). The patch carries:
- the blended level n-1 relief;
- planet forcing, climate, lakes and young landforms sampled onto the patch;
- drainage routed on the patch, with planet rivers entering across its rim.

A patch depends only on the build, the cached coarser tiles and its own
location, so it can be rebuilt whenever it is needed.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from dmtools.terrain.pipeline.planet_coast import coastline, level_finest_m
from dmtools.terrain.pipeline.planet_evolution import route
from dmtools.terrain.pipeline.planet_patch import regional_mesh
from dmtools.terrain.pipeline.planet_regional import RegionalParent, parent_inflows
from dmtools.terrain.pipeline.planet_tiles import TileGrid, TileSurface, blend

type F64 = NDArray[np.float64]

# A patch reaches this much beyond the area it serves, so that drainage near its
# rim is not cut off by the patch boundary.
LEVEL_PARENT_MARGIN = 1.25


def level_parent(
    planet: RegionalParent,
    grid: TileGrid,
    tiles: dict[int, TileSurface],
    centre: tuple[float, float],
    radius_m: float,
    spacing_km: float,
    seed: int,
) -> RegionalParent:
    """A parent for detail within ``radius_m`` of ``centre``, built from coarser tiles."""
    region = regional_mesh(
        centre[0], centre[1], LEVEL_PARENT_MARGIN * radius_m / 1e3, spacing_km,
        planet.mesh.radius_m, seed,
    )
    mesh = region.mesh
    xyz = mesh.xyz
    land = coastline(planet.world).contains(
        xyz, level_finest_m(region.spacing_m), planet.settings.seed
    )
    relief = np.where(land, np.maximum(blend(grid, tiles, xyz), 1.0), 0.0)

    def sample(values: F64 | None) -> F64 | None:
        return None if values is None else planet.sample(xyz, values)

    runoff = sample(planet.runoff_weight)
    flow = route(
        mesh, relief, ~land | region.boundary, runoff, parent_inflows(planet, region)
    )
    nearest = np.asarray(KDTree(planet.mesh.xyz).query(xyz, workers=-1)[1], dtype=np.int64)
    patch = RegionalParent(
        world=planet.world,
        settings=planet.settings,
        mesh=mesh,
        land=land,
        surface_m=relief,
        steady_uplift=planet.sample(xyz, planet.steady_uplift),
        pulse_uplift=planet.sample(xyz, planet.pulse_uplift),
        erodibility=planet.sample(xyz, planet.erodibility),
        runoff_weight=runoff,
        receiver=flow.receiver,
        area_m2=flow.area_m2,
        temperature_c=sample(planet.temperature_c),
        precipitation_mm=sample(planet.precipitation_mm),
        biome=None if planet.biome is None else planet.biome[nearest],
        warm_season_c=sample(planet.warm_season_c),
        coast_m=sample(planet.coast_m),
        sea_floor_m=sample(planet.sea_floor_m),
        basin_depth_m=sample(planet.basin_depth_m),
        volcanic_m=sample(planet.volcanic_m),
        volcanoes=planet.volcanoes,
        precip_warm_mm=sample(planet.precip_warm_mm),
        # Lakes stay on the planet mesh, so every level refines the same outlines.
        lake=planet.lake,
        lake_level_m=planet.lake_level_m,
        lake_endorheic=planet.lake_endorheic,
        flood_basalt=sample(planet.flood_basalt),
        wind_east=sample(planet.wind_east),
        wind_north=sample(planet.wind_north),
        wonder_m=sample(planet.wonder_m),
        wonders=planet.wonders,
        planet_mesh=planet.mesh if planet.planet_mesh is None else planet.planet_mesh,
        ice=planet.ice,
        ice_margin=planet.ice_margin_m,
    )
    # Coarser tiles leave out volcanoes and wonders, which windows redraw sharply
    # from the planet's lists. The patch carries them as young relief on top of
    # that surface, as the planet does, so its lake levels match its surface.
    return replace(patch, surface_m=relief + patch.young_m())
