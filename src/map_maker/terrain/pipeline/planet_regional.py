# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Parent-conditioned regional enrichment of a planet on a fine local mesh (M6).

A circular region is regenerated with finer, physically eroded detail:

* **Mesh.** A jittered triangular lattice in a local azimuthal-equidistant plane,
  plus an even outer ring, mapped to the sphere. Planet kernels run unchanged.
* **Land** is the refined coast (ADR-0090) with detail down to twice the spacing.
* **Boundary.** Ring land nodes are fixed at the parent surface. Parent rivers
  that cross into the region enter as drainage-area sources.
* **Forcing.** Parent uplift, erodibility and runoff are interpolated, with finer
  rock texture and a smaller process area, so smaller valleys resolve. Sediment
  basins keep their plain; their margins are refined down to the spacing.
* **Consistency.** A per-node uplift correction (ratio, then secant) makes the
  regional relief, smoothed over the parent spacing, match the parent surface.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cached_property, partial

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import CloughTocher2DInterpolator
from scipy.spatial import Delaunay, KDTree

from map_maker.terrain.domain.planet import PlanetSettings
from map_maker.terrain.domain.seeds import stage_seed
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.planet import PlanetResult
from map_maker.terrain.pipeline.planet_coast import (
    coastline,
    displace,
    level_finest_m,
    noise_octaves,
)
from map_maker.terrain.pipeline.planet_evolution import EvolutionRun, evolve
from map_maker.terrain.pipeline.planet_forcing import Forcing, smooth_over_land
from map_maker.terrain.pipeline.planet_ice import (
    IceSheets,
    ice_sheet_nodes,
    margin_distance,
    sample_ice,
)
from map_maker.terrain.pipeline.planet_lakes import refined_lake_cover
from map_maker.terrain.pipeline.planet_mesh import SphereMesh, sample_field
from map_maker.terrain.pipeline.planet_noise import fbm3
from map_maker.terrain.pipeline.planet_patch import Region, forward_aeqd, inverse_aeqd
from map_maker.terrain.pipeline.planet_volcanism import Volcanoes
from map_maker.terrain.pipeline.planet_wonders import Wonders
from map_maker.terrain.pipeline.world import WorldMap

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

FINE_TEXTURE = 0.5
BASIN_FULL_M = 200.0  # basin depth at which a node counts as fully depositional
# Basin margins are refined below the planet mesh spacing like lake shores
# (ADR-0092), with noise octaves from BASIN_TOP_SPACINGS planet spacings down to
# a level's finest scale. They wander further than shores: sediment runs up the
# valleys of a range front and spurs reach out into the plain, kilometres at the
# scale of the range's valleys. With BASIN_AMPLITUDE_SPACINGS at the top, every
# octave from one spacing down is as steep as the coast's, so fronts look alike
# at every level.
BASIN_MARGIN_STAGE = "planet.basin-margin"
BASIN_TOP_SPACINGS = 4.0
BASIN_AMPLITUDE_SPACINGS = 0.5
LAKE_CORE_COVER = 0.5  # parent lake cover above which regional ground is lake water
# Rock texture at every level: its wavelength follows the mesh spacing (40 km at
# 5 km). A fixed wavelength left fine tiles uniform, so water cut straight,
# parallel gullies down every slope instead of branching networks.
FINE_TEXTURE_SPACINGS = 8.0
MIN_RUNOFF_WEIGHT = 0.05


@dataclass(frozen=True)
class RegionalParent:
    """The parent fields that regional enrichment needs (in memory or from a build)."""

    world: WorldMap
    settings: PlanetSettings
    mesh: SphereMesh
    land: B
    surface_m: F64  # dry ground and lake surfaces on land; 0 at sea
    steady_uplift: F64
    pulse_uplift: F64
    erodibility: F64
    runoff_weight: F64 | None
    receiver: I64
    area_m2: F64
    temperature_c: F64 | None = None
    precipitation_mm: F64 | None = None
    biome: NDArray[np.int8] | None = None
    warm_season_c: F64 | None = None
    coast_m: F64 | None = None
    sea_floor_m: F64 | None = None  # display bathymetry on water nodes; 0 on land
    basin_depth_m: F64 | None = None  # sediment-filled flexural basins, on the lake mesh
    volcanic_m: F64 | None = None  # edifice height the mesh carries from volcanoes
    volcanoes: Volcanoes | None = None
    precip_warm_mm: F64 | None = None  # warm-half-year precipitation rate
    lake: I64 | None = None  # lake id per node of the lake mesh, -1 if none
    lake_level_m: F64 | None = None  # surface per lake id
    lake_endorheic: B | None = None  # closed lake per lake id
    flood_basalt: F64 | None = None  # 0..1 trap cover
    wind_east: F64 | None = None  # annual mean surface wind (m/s)
    wind_north: F64 | None = None
    wonder_m: F64 | None = None  # height change the mesh carries from craters and chasms
    wonders: Wonders | None = None
    crater_floor_m: F64 | None = None  # crater floors levelled below their relief
    planet_mesh: SphereMesh | None = None  # the mesh lakes, basins and ice are on, if not `mesh`
    ice: IceSheets | None = None  # on the planet mesh
    ice_margin: F64 | None = None  # signed margin distance on the planet mesh; computed if None

    def young_m(self) -> F64:
        """Height that volcanoes and wonders added on land after erosion and climate."""
        young = np.zeros(self.mesh.size)
        for added in (self.volcanic_m, self.wonder_m, self.crater_floor_m):
            if added is not None:
                young = young + added
        return np.where(self.land, young, 0.0)

    @classmethod
    def from_result(cls, result: PlanetResult) -> RegionalParent:
        climate = result.climate
        return cls(
            result.world, result.settings, result.mesh, result.land,
            np.where(
                result.land,
                result.lakes.surface_m,
                np.where(result.islands, result.elevation_m, 0.0),
            ),
            result.forcing.steady_uplift, result.forcing.pulse_uplift, result.forcing.erodibility,
            result.runoff_weight, result.flow.receiver, result.flow.area_m2,
            None if climate is None else climate.temperature_c,
            None if climate is None else climate.precipitation_mm,
            None if climate is None else climate.biome,
            None if climate is None else climate.warm_c,
            result.coast_m,
            np.where(result.land, 0.0, result.elevation_m),
            result.forcing.basin_depth_m,
            result.volcanic_m,
            result.volcanoes,
            None if climate is None else climate.precip_warm_mm,
            result.lakes.lake,
            result.lakes.level_m,
            result.lakes.endorheic,
            result.forcing.flood_basalt,
            None if climate is None else climate.wind_east,
            None if climate is None else climate.wind_north,
            result.wonder_m,
            result.wonders,
            result.crater_floor_m,
            ice=result.ice if climate is not None else None,
        )

    @classmethod
    def tiles_from(cls, result: PlanetResult) -> RegionalParent:
        """The parent that regional tiles are enriched from: ``result`` without ice.

        Tiles come from the planet without wonders (ADR-0097), so ``result`` is the
        base planet; tiles never use ice, which would only cost its margins.
        """
        return replace(cls.from_result(result), ice=None)

    def lakes_at(self, xyz: F64, detail_m: float) -> tuple[F64, F64, B]:
        """Lake cover (0..1), the nearest lake's level and whether it is closed.

        The cover is linear inside each lake-mesh triangle, so its contours are
        straight; it is sampled at points displaced by noise down to ``detail_m``,
        which refines lake outlines below the mesh spacing as coasts are. Every
        level samples the planet's lakes, so finer levels only add detail.
        """
        if self.lake is None or self.lake_level_m is None or not np.any(self.lake >= 0):
            n = len(xyz)
            return np.zeros(n), np.full(n, -np.inf), np.zeros(n, dtype=bool)
        mesh = self.mesh if self.planet_mesh is None else self.planet_mesh
        cover, ids = refined_lake_cover(mesh, self.lake, self.settings.seed, xyz, detail_m)
        closed = (
            np.zeros(len(xyz), dtype=bool)
            if self.lake_endorheic is None
            else self.lake_endorheic[ids].astype(bool)
        )
        return cover, self.lake_level_m[ids].astype(np.float64), closed

    @cached_property
    def ice_margin_m(self) -> F64 | None:
        """Signed distance (m) to the ice-sheet margin on the planet mesh, positive on ice."""
        if self.ice is None:
            return None
        if self.ice_margin is not None:
            return self.ice_margin
        # Only the planet's own parent holds ice on its mesh; level parents carry
        # the planet's margin.
        assert self.planet_mesh is None
        bed = np.where(self.land, self.surface_m, 0.0)
        return margin_distance(self.mesh, ice_sheet_nodes(self.mesh, self.ice.thickness_m, bed))

    def ice_at(self, xyz: F64, detail_m: float) -> tuple[F64, F64, F64] | None:
        """Ice margin distance, thickness and mass balance with margins refined to ``detail_m``.

        Like lakes, ice stays on the planet mesh, so every level refines the same
        margins. None where the planet has no ice sheets.
        """
        margin = self.ice_margin_m
        if self.ice is None or margin is None or not np.any(self.ice.thickness_m > 0):
            return None
        mesh = self.mesh if self.planet_mesh is None else self.planet_mesh
        return sample_ice(mesh, self.ice, margin, xyz, detail_m, self.settings.seed)

    def basin_at(self, xyz: F64, detail_m: float) -> F64 | None:
        """Sediment-basin depth (m) at unit vectors ``xyz``, its margin refined to ``detail_m``.

        Like lakes, basins stay on the planet mesh. Depth is sampled smoothly at
        points displaced by noise down to ``detail_m``, so a plain meets the
        mountains along a dissected front, with re-entrants up the valleys and
        spurs out into the plain, instead of along a contour that is straight
        within each planet triangle. Every level samples the same octaves down
        to its own detail, so finer levels only add detail. None without basins.
        """
        if self.basin_depth_m is None:
            return None
        mesh = self.mesh if self.planet_mesh is None else self.planet_mesh
        spacing = mesh.spacing_m
        moved = displace(
            xyz, mesh.radius_m,
            noise_octaves(
                BASIN_TOP_SPACINGS * spacing, BASIN_AMPLITUDE_SPACINGS * spacing, detail_m
            ),
            stage_seed(self.settings.seed, BASIN_MARGIN_STAGE),
        )
        return np.maximum(smooth_sampler(mesh, moved)(self.basin_depth_m), 0.0)

    def sample(self, xyz: F64, values: F64) -> F64:
        """Triangle-linear interpolation of a parent node field at unit vectors."""
        return sample_field(self.mesh, xyz, values)

    def smooth_sampler(self, xyz: F64) -> Callable[[F64], F64]:
        """Smooth (C1) interpolation of parent node fields at unit vectors ``xyz``."""
        return smooth_sampler(self.mesh, xyz)


def smooth_sampler(mesh: SphereMesh, xyz: F64) -> Callable[[F64], F64]:
    """Smooth (C1) interpolation of ``mesh`` node fields at unit vectors ``xyz``.

    Clough-Tocher cubics in a local azimuthal plane equal a field at mesh nodes
    but have no creases along mesh triangle edges, which regional relief seeded
    from triangle-linear fields keeps as straight lines. The plane and its
    triangulation are built once for every field sampled. Points outside the
    nodes' hull fall back to triangle-linear interpolation.
    """
    centre = xyz.mean(axis=0)
    centre /= np.linalg.norm(centre)
    reach = float(np.arccos(np.clip(xyz @ centre, -1, 1)).max())
    reach += 4 * mesh.spacing_m / mesh.radius_m
    near = np.flatnonzero(mesh.xyz @ centre >= np.cos(min(reach, np.pi)))
    if len(near) < 4:
        return partial(sample_field, mesh, xyz)
    lon = float(np.degrees(np.arctan2(centre[1], centre[0])))
    lat = float(np.degrees(np.arcsin(np.clip(centre[2], -1, 1))))
    # SciPy estimates the cubics' gradients to an absolute tolerance, so fields
    # are interpolated at unit scale on a plane measured in mesh spacings. In
    # metres, uplift (metres a year) kept almost no gradient, and its cubics
    # were worse than linear interpolation.
    unit_m = mesh.spacing_m
    triangulation = Delaunay(forward_aeqd(mesh.xyz[near], lon, lat, mesh.radius_m) / unit_m)
    plane = forward_aeqd(xyz, lon, lat, mesh.radius_m) / unit_m

    def sample(values: F64) -> F64:
        local = values[near]
        low, span = float(local.min()), float(np.ptp(local)) or 1.0
        unit = CloughTocher2DInterpolator(triangulation, (local - low) / span)(plane)
        cubic = low + span * np.asarray(unit)
        outside = ~np.isfinite(cubic)
        if outside.any():
            cubic[outside] = sample_field(mesh, xyz[outside], values)
        return cubic

    return sample


def parent_inflows(parent: RegionalParent, region: Region) -> F64:
    """Parent rivers crossing into the region become drainage-area sources."""
    pm = parent.mesh
    lon0, lat0 = region.centre
    centre = inverse_aeqd(np.zeros(1), np.zeros(1), lon0, lat0, pm.radius_m)[0]
    distance = pm.radius_m * np.arccos(np.clip(pm.xyz @ centre, -1, 1))
    outside = parent.land & (distance > region.radius_m) & (parent.receiver >= 0)
    receiver = parent.receiver[outside]
    sources = np.flatnonzero(outside)[distance[receiver] <= region.radius_m]
    inflow = np.zeros(region.mesh.size)
    if not len(sources):
        return inflow
    candidates = np.flatnonzero(~region.boundary)
    tree = KDTree(region.mesh.xyz[candidates])
    target = candidates[np.asarray(tree.query(pm.xyz[parent.receiver[sources]])[1])]
    np.add.at(inflow, target, parent.area_m2[sources])
    return inflow


@dataclass(frozen=True)
class RegionalResult:
    region: Region
    land: B
    elevation_m: F64
    run: EvolutionRun
    target_m: F64
    correction: F64
    history: tuple[dict[str, float], ...]


def enrich(
    parent: RegionalParent,
    region: Region,
    *,
    process_area_km2: float,
    iterations: int,
    seed: int,
    cancellation: CancellationToken | None = None,
) -> RegionalResult:
    mesh = region.mesh
    land = coastline(parent.world).contains(
        mesh.xyz, level_finest_m(region.spacing_m), parent.settings.seed
    )
    water = ~land
    # Volcanoes and craters are drawn on top of the regional relief, not eroded
    # from uplift (erosion would fill a crater).
    young = parent.young_m()
    # Fields that seed the relief are interpolated smoothly: triangle-linear ones
    # leave the parent's triangles as planar facets with straight creases.
    smoothly = parent.smooth_sampler(mesh.xyz)
    target = np.maximum(smoothly(parent.surface_m - young), 0.0)
    # Parent lakes are fixed water at their level: regional rivers end in them.
    # The level is held on the same surface without young landforms: windows add
    # a crater back on top, so a crater lake held at its full level would end up
    # a crater's depth below its own surface.
    lake_cover, lake_level, _ = parent.lakes_at(mesh.xyz, level_finest_m(region.spacing_m))
    lake = land & (lake_cover > LAKE_CORE_COVER)
    fixed = water | (region.boundary & land) | lake
    level = np.where(
        water, 0.0, np.where(lake, lake_level - parent.sample(mesh.xyz, young), target)
    )
    steady = np.maximum(smoothly(parent.steady_uplift), 0.0)
    pulse = np.maximum(smoothly(parent.pulse_uplift), 0.0)
    # Cubics overshoot a little at sharp steps; erodibility stays within the parent's.
    erodibility = np.clip(
        smoothly(parent.erodibility),
        float(parent.erodibility.min()),
        float(parent.erodibility.max()),
    ) * np.exp(
        FINE_TEXTURE
        * fbm3(mesh.xyz, seed + 31, 4, mesh.radius_m / (FINE_TEXTURE_SPACINGS * mesh.spacing_m))
    )
    basin_depth = parent.basin_at(mesh.xyz, level_finest_m(region.spacing_m))
    if basin_depth is not None:
        # Sediment-filled basins are deposition zones: the parent plain is kept
        # (no uplift, almost no erosion) instead of being re-dissected into hills.
        basin = np.clip(basin_depth / BASIN_FULL_M, 0, 1)
        steady, pulse = steady * (1 - basin), pulse * (1 - basin)
        erodibility = erodibility * (1 - 0.97 * basin)
    runoff = (
        None if parent.runoff_weight is None
        else np.maximum(smoothly(parent.runoff_weight), MIN_RUNOFF_WEIGHT)
    )
    # Parent drainage area is already weighted by the runoff upstream, where it
    # fell; the region's runoff where a river enters does not change it.
    inflow = parent_inflows(parent, region)
    settings = parent.settings
    rng = np.random.default_rng(seed)
    initial = np.maximum(target, 1.0) + 5 * rng.random(mesh.size)
    smoothing = parent.mesh.spacing_m
    correction = np.ones(mesh.size)
    previous: tuple[F64, F64] | None = None
    history: list[dict[str, float]] = []
    run: EvolutionRun | None = None
    for iteration in range(iterations + 1):
        check_cancelled(cancellation)
        forcing = Forcing(steady * correction, pulse * correction, erodibility, water)
        run = evolve(
            mesh, fixed, forcing, initial, steps=settings.steps, step_yr=settings.step_kyr * 1e3,
            area_exponent=settings.area_exponent, process_area_m2=process_area_km2 * 1e6,
            runoff=runoff, fixed_level=level, inflow_m2=inflow, cancellation=cancellation,
        )
        smooth = smooth_over_land(mesh, np.where(land, run.elevation, 0.0), land, smoothing)
        interior = land & ~fixed
        error = smooth[interior] - target[interior] if interior.any() else np.zeros(1)
        history.append({
            "iteration": float(iteration),
            "rms_vs_parent_m": float(np.sqrt(np.mean(error**2))),
            "mean_bias_m": float(np.mean(error)),
            "mean_m": float(np.mean(run.elevation[interior])) if interior.any() else 0.0,
        })
        if iteration == iterations:
            break
        # Ratio first; then a per-node secant on the correction -> smoothed-relief
        # response, which also accounts for fixed boundary base levels.
        proposal = correction * np.clip((target + 50.0) / (smooth + 50.0), 1 / 3, 3.0)
        if previous is not None:
            dc, ds = correction - previous[0], smooth - previous[1]
            slope = np.divide(ds, dc, out=np.zeros_like(ds), where=np.abs(dc) > 1e-6)
            usable = slope > 1.0
            secant = correction + (target - smooth) / np.where(usable, slope, 1.0)
            proposal = np.where(usable, secant, proposal)
        proposal = np.clip(proposal, correction / 3, correction * 3)
        previous = (correction, smooth)
        correction = np.maximum(
            smooth_over_land(mesh, np.where(land, proposal, correction), land, smoothing / 2),
            0.02,
        )
    assert run is not None
    return RegionalResult(region, land, run.elevation, run, target, correction, tuple(history))
