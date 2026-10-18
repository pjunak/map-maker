# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Level parents: a coarser regional level presented as the parent of finer detail.

Level-n tiles are enriched like level-1 tiles, but their parent is a patch mesh
at level n-1 spacing (ADR-0088). The patch carries:
- the blended level n-1 relief, with the valley courses that level's mesh
  resolves (``ReliefWarp``);
- planet forcing sampled smoothly onto the patch, as level 1 takes it, and
  climate and young landforms sampled onto it, with temperatures lapse-corrected
  to the patch relief;
- the planet's lakes and sediment basins, which every level refines itself;
- drainage routed on the patch, with planet rivers entering across its rim.

A patch depends only on the build, the cached coarser tiles and its own
location, so it can be rebuilt whenever it is needed.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from map_maker.terrain.pipeline.planet_coast import coastline, level_finest_m
from map_maker.terrain.pipeline.planet_evolution import route
from map_maker.terrain.pipeline.planet_patch import regional_mesh
from map_maker.terrain.pipeline.planet_regional import (
    MIN_RUNOFF_WEIGHT,
    RegionalParent,
    parent_inflows,
)
from map_maker.terrain.pipeline.planet_tiles import ReliefWarp, TileGrid, TileSurface, blend

type F64 = NDArray[np.float64]

# A patch reaches this much beyond the area it serves, so that drainage near its
# rim is not cut off by the patch boundary.
LEVEL_PARENT_MARGIN = 1.25


def level_parent_radius(planet: RegionalParent, radius_m: float, spacing_km: float) -> float:
    """How far the level parent serving ``radius_m`` about its centre reaches.

    A planet river enters a patch at the patch node nearest its first planet
    node inside, up to the longest planet step (and a patch spacing) in from the
    rim. The patch reaches far enough for that node to lie outside the area
    served, so every inherited river crosses into that area instead of starting
    inside it. Small deep windows need this: 25 % of a 25 km local window is
    less than one 12 km step of a 3.2M-node planet.
    """
    step_m = float(planet.mesh.length_m.max())
    return max(LEVEL_PARENT_MARGIN * radius_m, radius_m + step_m + 2 * spacing_km * 1e3)


def level_parent(
    planet: RegionalParent,
    grid: TileGrid,
    tiles: dict[int, TileSurface],
    centre: tuple[float, float],
    radius_m: float,
    spacing_km: float,
    seed: int,
    relief: ReliefWarp,
) -> RegionalParent:
    """A parent for detail within ``radius_m`` of ``centre``, built from coarser tiles.

    ``relief`` is where the coarser tiles' blend is sampled
    (``ReliefWarp.for_parent``).
    """
    region = regional_mesh(
        centre[0], centre[1], level_parent_radius(planet, radius_m, spacing_km) / 1e3,
        spacing_km, planet.mesh.radius_m, seed,
    )
    mesh = region.mesh
    xyz = mesh.xyz
    land = coastline(planet.world).contains(
        xyz, level_finest_m(region.spacing_m), planet.settings.seed
    )
    surface = blend(grid, tiles, relief(xyz, planet.mesh.radius_m))
    relief_m = np.where(land, np.maximum(surface, 1.0), 0.0)

    def sample(values: F64 | None) -> F64 | None:
        return None if values is None else planet.sample(xyz, values)

    # Fields that seed the finer level's relief come smoothly from the planet, as
    # level 1 takes them (``enrich``): triangle-linear ones carried the planet's
    # triangles down every level as straight creases.
    smoothly = planet.smooth_sampler(xyz)
    runoff = (
        None if planet.runoff_weight is None
        else np.maximum(smoothly(planet.runoff_weight), MIN_RUNOFF_WEIGHT)
    )
    erodibility = smoothly(planet.erodibility)
    flow = route(
        mesh, relief_m, ~land | region.boundary, runoff, parent_inflows(planet, region)
    )
    nearest = np.asarray(KDTree(planet.mesh.xyz).query(xyz, workers=-1)[1], dtype=np.int64)
    # A parent's temperatures hold at its own surface, so the planet's are
    # lapse-corrected to the coarser tiles' relief. Sampled unchanged, they made a
    # province 6.5 C too warm on level-1 mountains 1 km above the planet surface.
    temperatures = planet.temperatures_at(xyz, relief_m)
    patch = RegionalParent(
        world=planet.world,
        settings=planet.settings,
        mesh=mesh,
        land=land,
        surface_m=relief_m,
        steady_uplift=np.maximum(smoothly(planet.steady_uplift), 0.0),
        pulse_uplift=np.maximum(smoothly(planet.pulse_uplift), 0.0),
        erodibility=erodibility,
        runoff_weight=runoff,
        receiver=flow.receiver,
        area_m2=flow.area_m2,
        temperature_c=None if temperatures is None else temperatures[0],
        precipitation_mm=sample(planet.precipitation_mm),
        biome=None if planet.biome is None else planet.biome[nearest],
        warm_season_c=None if temperatures is None else temperatures[1],
        coast_m=sample(planet.coast_m),
        sea_floor_m=sample(planet.sea_floor_m),
        # Basins stay on the planet mesh, like lakes, so every level refines the
        # same margins instead of the coarser level's sampled contour.
        basin_depth_m=planet.basin_depth_m,
        volcanic_m=sample(planet.volcanic_m),
        volcanoes=planet.volcanoes,
        precip_warm_mm=sample(planet.precip_warm_mm),
        lake=planet.lake,
        lake_level_m=planet.lake_level_m,
        lake_endorheic=planet.lake_endorheic,
        flood_basalt=sample(planet.flood_basalt),
        wind_east=sample(planet.wind_east),
        wind_north=sample(planet.wind_north),
        wonder_m=sample(planet.wonder_m),
        wonders=planet.wonders,
        crater_floor_m=sample(planet.crater_floor_m),
        planet_mesh=planet.mesh if planet.planet_mesh is None else planet.planet_mesh,
        ice=planet.ice,
        ice_margin=planet.ice_margin_m,
    )
    # Coarser tiles leave out volcanoes and wonders, which windows redraw sharply
    # from the planet's lists. The patch carries them as young relief on top of
    # that surface, as the planet does, so its lake levels match its surface.
    return replace(patch, surface_m=relief_m + patch.young_m())
