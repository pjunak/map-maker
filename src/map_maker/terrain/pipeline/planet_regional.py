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
  basins keep their plain, which erosion cannot lower below the parent's; their
  margins are refined down to the spacing.
* **Consistency.** An uplift correction makes the regional relief, smoothed over
  the parent spacing, match the parent surface smoothed alike (ADR-0108). It is
  fitted to the height each node's uplift builds above where it drains, starting
  from the steady state of the starting surface (ADR-0109).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cached_property, partial
from math import log, sqrt

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
from map_maker.terrain.pipeline.planet_evolution import (
    FILL_EPS_M,
    LAND_FLOOR_M,
    EvolutionRun,
    FlowState,
    evolve,
    route,
)
from map_maker.terrain.pipeline.planet_forcing import (
    PLATEAU_PULSE_FRACTION,
    Forcing,
    land_smoother,
)
from map_maker.terrain.pipeline.planet_ice import (
    IceSheets,
    ice_sheet_nodes,
    margin_distance,
    sample_ice,
)
from map_maker.terrain.pipeline.planet_kernels import downstream_sum, priority_breach
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
# Bankfull channel depth 0.27 Q^0.39 m for discharge Q in m^3/s (Moody and
# Troutman 2002), with Q from CHANNEL_RUNOFF_M_YR of runoff over the drainage area.
CHANNEL_DEPTH_COEFFICIENT = 0.27
CHANNEL_DEPTH_EXPONENT = 0.39
CHANNEL_RUNOFF_M_YR = 0.3
# Uplift calibration (ADR-0109). A correction is fitted over CALIBRATION_VALLEYS
# valley spacings, the square root of the process area, and never less than half
# the parent spacing: fitted finer, it chased divides that jump between valleys
# from one erosion run to the next. Ground standing less than CALIBRATION_RELIEF_M
# above where it drains barely answers its uplift, so the fit holds back there.
CALIBRATION_VALLEYS = 2.0
CALIBRATION_RELIEF_M = 50.0
CALIBRATION_STEP = 3.0  # largest change of the correction in one iteration (factor)
CORRECTION_RANGE = (0.02, 10.0)
# Uplift at a node lifts all ground upstream of it. Where the last prediction of
# the smoothed relief held to within TRUSTED_MISS of its change, the fit counts
# that lift along the drainage; from DISTRUSTED_MISS on, divides moved more than
# the drainage model knows, and the fit stays local.
TRUSTED_MISS = 0.2
DISTRUSTED_MISS = 0.7
COUPLING_PASSES = 2


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
    temperature_c: F64 | None = None  # at surface_m without young landforms
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
    plain_m: F64 | None = None  # planet surface without young landforms, on the planet mesh

    def young_m(self) -> F64:
        """Height that volcanoes and wonders added on land after erosion and climate."""
        young = np.zeros(self.mesh.size)
        for added in (self.volcanic_m, self.wonder_m, self.crater_floor_m):
            if added is not None:
                young = young + added
        return np.where(self.land, young, 0.0)

    def temperatures_at(self, xyz: F64, height_m: F64) -> tuple[F64, F64] | None:
        """Annual and warm-season temperature (C) at unit vectors ``xyz`` and ``height_m``.

        The parent's temperatures hold at its surface without young landforms
        (volcanoes and wonders form after the climate is simulated), so they are
        lapse-corrected from there. None without a climate.
        """
        if self.temperature_c is None:
            return None
        lift_km = (height_m - self.sample(xyz, self.surface_m - self.young_m())) / 1000
        cooling = self.settings.climate.lapse_c_per_km * lift_km
        warm = self.temperature_c if self.warm_season_c is None else self.warm_season_c
        return self.sample(xyz, self.temperature_c) - cooling, self.sample(xyz, warm) - cooling

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

    def plain_at(self, xyz: F64) -> F64 | None:
        """The planet's surface without young landforms at unit vectors ``xyz``.

        Basins hold the planet's plain at every level. A level parent's own
        surface is the coarser level's relief, so the plain stays on the planet
        mesh. None for the planet itself, whose surface it is.
        """
        if self.plain_m is None:
            return None
        assert self.planet_mesh is not None
        return np.maximum(smooth_sampler(self.planet_mesh, xyz)(self.plain_m), 0.0)

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
    from triangle-linear fields keeps as straight lines. Each sample stays
    within the values at the corners of its triangle, as a linear one does. The
    plane and its triangulation are built once for every field sampled. Points
    outside the nodes' hull fall back to triangle-linear interpolation.
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
    # Cubics overshoot at steep steps. Across a mountain front on Aethelara they
    # fell up to 1,100 m below the lowest corner of their triangle; tile rings
    # held there at sea level drained a 160,000 km2 river to them.
    corners = triangulation.simplices[np.maximum(triangulation.find_simplex(plane), 0)]

    def sample(values: F64) -> F64:
        local = values[near]
        low, span = float(local.min()), float(np.ptp(local)) or 1.0
        unit = CloughTocher2DInterpolator(triangulation, (local - low) / span)(plane)
        cubic = low + span * np.asarray(unit)
        at = local[corners]
        cubic = np.clip(cubic, at.min(axis=1), at.max(axis=1))
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


def channel_depth_m(area_m2: F64) -> F64:
    """Bankfull depth of the channel of a river draining ``area_m2`` (runoff-weighted)."""
    discharge = area_m2 * CHANNEL_RUNOFF_M_YR / 3.156e7
    return CHANNEL_DEPTH_COEFFICIENT * discharge**CHANNEL_DEPTH_EXPONENT


def parent_channels(parent: RegionalParent, region: Region, process_area_m2: float) -> F64:
    """Depth of the parent rivers' channels at each region node, 0 off them.

    Each parent river link draining at least the process area is traced over the
    region mesh, a neighbour at a time towards its receiver, and its bankfull
    depth is cut along that connected path: through gaps between nodes merely
    near a link, water left the channel sideways on a flat plain. Channels a
    fraction of their depth deep, as much as a narrow channel lowers a coarse
    cell on average, were lost among the plain's centimetre differences once
    the next level resampled them. The boundary is cut only where a river
    leaves; cut where it enters too, a channel on a flat plain drained back out
    there.
    """
    pm, mesh = parent.mesh, region.mesh
    lon0, lat0 = region.centre
    centre = inverse_aeqd(np.zeros(1), np.zeros(1), lon0, lat0, pm.radius_m)[0]
    reach = (region.radius_m + 2 * pm.spacing_m) / pm.radius_m
    rivers = np.flatnonzero(
        parent.land & (parent.receiver >= 0) & (parent.area_m2 >= process_area_m2)
        & (pm.xyz @ centre >= np.cos(min(reach, np.pi)))
    )
    depth = np.zeros(mesh.size)
    if not len(rivers):
        return depth
    receivers = parent.receiver[rivers]
    tree = KDTree(mesh.xyz)
    starts = np.asarray(tree.query(pm.xyz[rivers], workers=-1)[1])
    ends = np.asarray(tree.query(pm.xyz[receivers], workers=-1)[1])
    leaves = pm.xyz[receivers] @ centre < np.cos(region.radius_m / pm.radius_m)
    cuts = channel_depth_m(parent.area_m2[rivers])
    for node, end, leaving, cut in zip(starts, ends, leaves, cuts, strict=True):
        goal = mesh.xyz[end]
        while True:
            if leaving or not region.boundary[node]:
                depth[node] = max(depth[node], cut)
            if node == end:
                break
            around = mesh.nbr[mesh.ptr[node] : mesh.ptr[node + 1]]
            step = around[np.argmax(mesh.xyz[around] @ goal)]
            if mesh.xyz[step] @ goal <= mesh.xyz[node] @ goal:
                break  # no neighbour nearer: the receiver lies beyond the mesh
            node = step
    return depth


def entry_walls(parent: RegionalParent, region: Region, process_area_m2: float) -> B:
    """Boundary nodes near where parent rivers flow in, which let no water out.

    Beyond the boundary there lies such a river's valley upstream. On a held
    flat basin plain a boundary node there was as low as the river's way on,
    and a province parent drained a 160,000 km2 river straight back out beside
    where it entered. As on window rims, boundary nodes near where a river
    draining at least the process area crosses in, and nearer there than to
    where any leaves, are walls: within the longest parent step, since a river
    enters at its first parent node inside, up to a step in.
    """
    pm = parent.mesh
    lon0, lat0 = region.centre
    centre = inverse_aeqd(np.zeros(1), np.zeros(1), lon0, lat0, pm.radius_m)[0]
    distance = pm.radius_m * np.arccos(np.clip(pm.xyz @ centre, -1, 1))
    step_m = float(pm.length_m.max())
    rivers = np.flatnonzero(
        parent.land & (parent.receiver >= 0) & (parent.area_m2 >= process_area_m2)
        & (distance < region.radius_m + step_m)
    )
    inside = distance <= region.radius_m
    start = forward_aeqd(pm.xyz[rivers], lon0, lat0, pm.radius_m)
    step = forward_aeqd(pm.xyz[parent.receiver[rivers]], lon0, lat0, pm.radius_m) - start
    # Where each step meets the circle |start + t step| = radius.
    a = np.maximum(np.einsum("ij,ij->i", step, step), 1e-9)
    b = np.einsum("ij,ij->i", start, step)
    c = np.einsum("ij,ij->i", start, start) - region.radius_m**2
    root = np.sqrt(np.maximum(b**2 - a * c, 0.0))
    entering = ~inside[rivers] & inside[parent.receiver[rivers]]
    leaving = inside[rivers] & ~inside[parent.receiver[rivers]]
    walls = np.zeros(region.mesh.size, dtype=bool)
    if not entering.any():
        return walls
    entries = start + ((-b - root) / a)[:, None] * step
    exits = start + ((-b + root) / a)[:, None] * step
    boundary = np.flatnonzero(region.boundary)
    near_entry = np.asarray(KDTree(entries[entering]).query(region.plane_m[boundary])[0])
    near_exit = (
        np.asarray(KDTree(exits[leaving]).query(region.plane_m[boundary])[0])
        if leaving.any() else np.full(len(boundary), np.inf)
    )
    walls[boundary] = (near_entry <= step_m) & (near_entry < near_exit)
    return walls


def uplift_steps(
    flow: FlowState,
    steady: F64,
    pulse: F64,
    *,
    erodibility: F64,
    interior: B,
    area_exponent: float,
    process_area_m2: float,
    steps: int,
    step_yr: float,
) -> F64:
    """Each interior node's height above its receiver that its uplift builds.

    Implicit stream power (n = 1) settles a node U dx / (K (A + A0)^m) above its
    receiver within its response time dx / (K (A + A0)^m). Nodes slower than the
    run, or than the final pulse for pulse uplift, stand proportionally lower.
    """
    rate = erodibility * (flow.area_m2 + process_area_m2) ** area_exponent
    drains = interior & (flow.receiver >= 0) & (rate > 0)
    response = np.divide(flow.distance_m, rate, out=np.zeros(rate.size), where=drains)
    lag = np.maximum(response, 1e-9)
    # As ``evolve`` times it, the pulse adds to the last steps.
    pulse_yr = (steps - round(steps * (1 - PLATEAU_PULSE_FRACTION))) * step_yr
    height = response * (
        steady * -np.expm1(-steps * step_yr / lag) + pulse * -np.expm1(-pulse_yr / lag)
    )
    return np.where(drains, height, 0.0)


@dataclass(frozen=True)
class UpliftCalibration:
    """Fits a tile's uplift correction to the parent smoothed alike (ADR-0109).

    Eroded to steady state, a node stands the sum of the heights its uplift and
    that of the nodes below it build down its drainage path, from where the path
    ends or a deposit holds it. A relative change of the correction raises it by
    that built height, so the change is fitted by least squares weighted by the
    height: ground that uplift has raised far decides. Where the drainage model
    is trusted, the fit also counts the lift from corrections downstream.
    """

    interior: B
    level: F64  # heights where drainage paths end (fixed nodes)
    floor: F64  # deposits erosion holds land at, -inf where none
    wanted: F64  # the parent surface smoothed over the parent spacing
    smooth: Callable[[F64], F64]  # over land, across the parent spacing
    fit: Callable[[F64], F64]  # over land, across the width a correction is fitted on

    def settled(self, flow: FlowState, steps: F64) -> F64:
        """The steady surface that node ``steps`` above their receivers build."""
        values = np.where(self.interior, steps, self.level)
        return downstream_sum(flow.order, flow.receiver, values, self.floor)

    def built(self, flow: FlowState, steps: F64) -> F64:
        """Smoothed height that ``steps`` build above path ends and deposits."""
        bare = self.settled(flow, np.zeros_like(steps))
        return np.where(self.interior, self.smooth(self.settled(flow, steps) - bare), 0.0)

    def rise(self, flow: FlowState, steps: F64, change: F64) -> F64:
        """Smoothed rise of the steady surface when ``steps`` grow by ``change``."""
        grown = self.settled(flow, steps * (1 + change)) - self.settled(flow, steps)
        return np.where(self.interior, self.smooth(grown), 0.0)

    def trust(self, change: F64, predicted: F64) -> F64:
        """1 where the smoothed relief changed as ``predicted``, 0 where it missed widely."""
        miss = np.where(self.interior, change - predicted, 0.0)
        seen = np.where(self.interior, change, 0.0)
        relative = np.sqrt(self.fit(miss**2) / (self.fit(seen**2) + 1.0e2))
        span = DISTRUSTED_MISS - TRUSTED_MISS
        return np.where(self.interior, np.clip((DISTRUSTED_MISS - relative) / span, 0, 1), 0.0)

    def factor(self, error: F64, flow: FlowState, steps: F64, trust: F64 | None) -> F64:
        """Multiplier of the correction that removes ``error`` (wanted minus relief).

        ``steps`` are what the current correction builds above each receiver.
        """
        built = self.built(flow, steps)
        error = np.where(self.interior, error, 0.0)
        scale = self.fit(built**2) + CALIBRATION_RELIEF_M**2
        change = self.fit(built * error) / scale
        if trust is not None:
            for _ in range(COUPLING_PASSES):
                # The fit takes each node to rise with its own correction alone;
                # the drainage adds the lift from corrections below it.
                lift = trust * (self.rise(flow, steps, change) - built * change)
                change = self.fit(built * (error - lift)) / scale
        return np.exp(np.clip(change, -log(CALIBRATION_STEP), log(CALIBRATION_STEP)))


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
    # Parent rivers keep their bankfull channels below the parent surface. On a
    # held basin plain the channel is all that tells a tile, and the level below,
    # where a river runs: on the flat plain, rivers that entered by the ring left
    # again beside where they came in, and finer levels lost them.
    channels = np.where(land & ~lake, parent_channels(parent, region, process_area_km2 * 1e6), 0)
    level = np.where(
        water, 0.0,
        np.where(lake, lake_level - parent.sample(mesh.xyz, young), target - channels),
    )
    # Sampled between parent nodes, the parent surface has sills where a river
    # runs between two nodes and a higher third corner weighs in. Tiles start
    # from it with those sills breached, as the parent drains: behind a sill the
    # ground would first fill like a lake, and on a basin plain, which erodes at
    # 3 % of the rate, the fill would stay.
    drained = priority_breach(level, fixed, mesh.ptr, mesh.nbr, FILL_EPS_M)
    steady = np.maximum(smoothly(parent.steady_uplift), 0.0)
    pulse = np.maximum(smoothly(parent.pulse_uplift), 0.0)
    erodibility = smoothly(parent.erodibility) * np.exp(
        FINE_TEXTURE
        * fbm3(mesh.xyz, seed + 31, 4, mesh.radius_m / (FINE_TEXTURE_SPACINGS * mesh.spacing_m))
    )
    basin_depth = parent.basin_at(mesh.xyz, level_finest_m(region.spacing_m))
    floor, rough = None, 1.0
    if basin_depth is not None:
        # A river's floodplain is a deposit too: the refined margin's spurs stop
        # at the banks of a parent river crossing the planet's plain. Spurs that
        # rose across its channel turned the river aside differently in each
        # tile, and finer levels lost it.
        unrefined = parent.basin_at(mesh.xyz, np.inf)
        assert unrefined is not None
        basin_depth = np.where(channels > 0, np.maximum(basin_depth, unrefined), basin_depth)
        # Sediment-filled basins are deposition zones: the parent plain is kept
        # (no uplift, almost no erosion) instead of being re-dissected into hills.
        basin = np.clip(basin_depth / BASIN_FULL_M, 0, 1)
        steady, pulse = steady * (1 - basin), pulse * (1 - basin)
        erodibility = erodibility * (1 - 0.97 * basin)
        # The planet fills its basins to their spill level after erosion, which
        # a tile cannot see: eroding the plain, big inherited rivers cut it down
        # to whichever ring node is lowest, differently in each tile. Sediment
        # holds it at the planet's plain instead, drained and with the channels
        # cut, less (1 - basin) * BASIN_FULL_M toward the margin, so rivers cross
        # it on the plain and fronts grade to it. Every level holds the planet's
        # plain rather than the level above, so a coarse level's broad channel
        # fills back up around a finer level's narrower one instead of the two
        # adding up. It starts without the random roughness that breaks ties
        # elsewhere: a plain eroding at 3 % of the rate keeps it, and each level
        # stacked its own few metres on the plain of the level above.
        planet_plain = parent.plain_at(mesh.xyz)
        held = drained if planet_plain is None else priority_breach(
            np.where(fixed, level, planet_plain - channels), fixed, mesh.ptr, mesh.nbr,
            FILL_EPS_M,
        )
        floor = np.where(basin_depth > 0, held - (1 - basin) * BASIN_FULL_M, -np.inf)
        rough = 1 - basin
    runoff = (
        None if parent.runoff_weight is None
        else np.maximum(smoothly(parent.runoff_weight), MIN_RUNOFF_WEIGHT)
    )
    # Parent drainage area is already weighted by the runoff upstream, where it
    # fell; the region's runoff where a river enters does not change it.
    inflow = parent_inflows(parent, region)
    settings = parent.settings
    rng = np.random.default_rng(seed)
    initial = np.maximum(drained, 1.0) + 5 * rough * rng.random(mesh.size)
    smoothing = parent.mesh.spacing_m
    process_area_m2 = process_area_km2 * 1e6
    interior = land & ~fixed
    smooth = land_smoother(mesh, land, smoothing)
    # The relief keeps the parent's height at the parent spacing, so both are
    # smoothed alike before they are compared. Matching the parent itself would
    # demand relief standing above it wherever smoothing lowers peaks.
    calibration = UpliftCalibration(
        interior, level, np.full(mesh.size, -np.inf) if floor is None else floor,
        smooth(np.where(land, target, 0.0)), smooth,
        land_smoother(
            mesh, land, max(smoothing / 2, CALIBRATION_VALLEYS * sqrt(process_area_m2))
        ),
    )
    steps_of = partial(
        uplift_steps, erodibility=erodibility, interior=interior,
        area_exponent=settings.area_exponent, process_area_m2=process_area_m2,
        steps=settings.steps, step_yr=settings.step_kyr * 1e3,
    )
    # The first correction fits the steady state that the starting surface's
    # drainage settles to, without an erosion run. Level parents carry the
    # planet's uplift, which builds finer levels two to three times too high.
    surface = np.where(fixed, level, np.maximum(initial, LAND_FLOOR_M))
    start = route(mesh, surface, fixed, runoff, inflow)
    first = steps_of(start, steady, pulse)
    correction = np.clip(
        calibration.factor(
            calibration.wanted - smooth(calibration.settled(start, first)), start, first, None
        ),
        *CORRECTION_RANGE,
    )
    reference = smooth(np.where(land, surface, 0.0))
    predicted = smooth(calibration.settled(start, first * correction)) - reference
    history: list[dict[str, float]] = []
    run: EvolutionRun | None = None
    for iteration in range(iterations + 1):
        check_cancelled(cancellation)
        forcing = Forcing(steady * correction, pulse * correction, erodibility, water)
        run = evolve(
            mesh, fixed, forcing, initial, steps=settings.steps, step_yr=settings.step_kyr * 1e3,
            area_exponent=settings.area_exponent, process_area_m2=process_area_m2,
            runoff=runoff, fixed_level=level, inflow_m2=inflow, floor_m=floor,
            cancellation=cancellation,
        )
        relief = smooth(np.where(land, run.elevation, 0.0))
        error = (relief - calibration.wanted)[interior] if interior.any() else np.zeros(1)
        history.append({
            "iteration": float(iteration),
            "rms_vs_parent_m": float(np.sqrt(np.mean(error**2))),
            "mean_bias_m": float(np.mean(error)),
            "mean_m": float(np.mean(run.elevation[interior])) if interior.any() else 0.0,
        })
        if iteration == iterations:
            break
        trust = calibration.trust(relief - reference, predicted)
        steps = steps_of(run.flow, steady * correction, pulse * correction)
        factor = calibration.factor(calibration.wanted - relief, run.flow, steps, trust)
        updated = np.clip(correction * factor, *CORRECTION_RANGE)
        predicted = calibration.rise(run.flow, steps, updated / correction - 1)
        reference, correction = relief, updated
    assert run is not None
    return RegionalResult(region, land, run.elevation, run, target, correction, tuple(history))
