# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Parent-conditioned regional enrichment of a planet on a fine local mesh (M6).

A circular region is regenerated with finer, physically eroded detail:

* **Mesh.** A jittered triangular lattice in a local azimuthal-equidistant plane,
  plus an even outer ring, mapped to the sphere. Planet kernels run unchanged.
* **Land** is the exact vector coastline at the finer spacing.
* **Boundary.** Ring land nodes are fixed at the parent surface. Parent rivers
  that cross into the region enter as drainage-area sources.
* **Forcing.** Parent uplift, erodibility and runoff are interpolated, with finer
  rock texture and a smaller process area, so smaller valleys resolve.
* **Consistency.** A per-node uplift correction (ratio, then secant) makes the
  regional relief, smoothed over the parent spacing, match the parent surface.
"""

from dataclasses import dataclass
from math import cos, pi, radians, sin

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import Delaunay, KDTree

from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.pipeline.control import CancellationToken, check_cancelled
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.pipeline.planet_evolution import EvolutionRun, evolve
from dmtools.terrain.pipeline.planet_forcing import Forcing, land_on_mesh, smooth_over_land
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, mesh_from_triangles, sample_field
from dmtools.terrain.pipeline.planet_noise import fbm3
from dmtools.terrain.pipeline.world import WorldMap

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

FINE_TEXTURE = 0.5
FINE_TEXTURE_WAVELENGTH_M = 40e3
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

    @classmethod
    def from_result(cls, result: PlanetResult) -> RegionalParent:
        climate = result.climate
        return cls(
            result.world, result.settings, result.mesh, result.land,
            np.where(result.land, result.lakes.surface_m, 0.0),
            result.forcing.steady_uplift, result.forcing.pulse_uplift, result.forcing.erodibility,
            result.runoff_weight, result.flow.receiver, result.flow.area_m2,
            None if climate is None else climate.temperature_c,
            None if climate is None else climate.precipitation_mm,
            None if climate is None else climate.biome,
            None if climate is None else climate.warm_c,
            result.coast_m,
            np.where(result.land, 0.0, result.elevation_m),
        )

    def sample(self, xyz: F64, values: F64) -> F64:
        """Triangle-linear interpolation of a parent node field at unit vectors."""
        return sample_field(self.mesh, xyz, values)


def inverse_aeqd(x: F64, y: F64, lon0: float, lat0: float, radius_m: float) -> F64:
    """Plane metres (x east, y north) about (lon0, lat0) to unit vectors on the sphere."""
    rho = np.hypot(x, y)
    c = rho / radius_m
    phi0, lam0 = radians(lat0), radians(lon0)
    safe = np.where(rho > 0, rho, 1.0)
    lat = np.arcsin(
        np.clip(
            np.cos(c) * sin(phi0) + np.where(rho > 0, y * np.sin(c) * cos(phi0) / safe, 0.0),
            -1,
            1,
        )
    )
    lon = lam0 + np.arctan2(x * np.sin(c), rho * cos(phi0) * np.cos(c) - y * sin(phi0) * np.sin(c))
    return np.stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)), axis=1)


@dataclass(frozen=True)
class Region:
    mesh: SphereMesh
    plane_m: F64
    boundary: B
    centre: tuple[float, float]
    radius_m: float


def regional_mesh(
    lon0: float, lat0: float, radius_km: float, spacing_km: float, planet_m: float, seed: int
) -> Region:
    s, r = spacing_km * 1e3, radius_km * 1e3
    rows = int(np.ceil(r / (s * np.sqrt(3) / 2))) + 1
    columns = int(np.ceil(r / s)) + 1
    jy, jx = np.mgrid[-rows : rows + 1, -columns : columns + 1]
    rng = np.random.default_rng(seed)
    x = (jx + 0.5 * (jy % 2)) * s + rng.normal(scale=0.2 * s, size=jx.shape)
    y = jy * s * np.sqrt(3) / 2 + rng.normal(scale=0.2 * s, size=jy.shape)
    interior = np.hypot(x, y) <= r - 0.6 * s
    ring = int(np.ceil(2 * pi * r / s))
    angle = np.arange(ring) * 2 * pi / ring
    px = np.concatenate([x[interior], r * np.cos(angle)])
    py = np.concatenate([y[interior], r * np.sin(angle)])
    plane = np.stack((px, py), axis=1)
    triangles = Delaunay(plane).simplices.astype(np.int64)
    mesh = mesh_from_triangles(inverse_aeqd(px, py, lon0, lat0, planet_m), triangles, planet_m)
    boundary = np.zeros(len(px), dtype=bool)
    boundary[-ring:] = True
    return Region(mesh, plane, boundary, (lon0, lat0), r)


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
    land = land_on_mesh(parent.world, mesh)
    water = ~land
    target = np.maximum(parent.sample(mesh.xyz, parent.surface_m), 0.0)
    fixed = water | (region.boundary & land)
    level = np.where(water, 0.0, target)
    steady = parent.sample(mesh.xyz, parent.steady_uplift)
    pulse = parent.sample(mesh.xyz, parent.pulse_uplift)
    erodibility = parent.sample(mesh.xyz, parent.erodibility) * np.exp(
        FINE_TEXTURE * fbm3(mesh.xyz, seed + 31, 4, mesh.radius_m / FINE_TEXTURE_WAVELENGTH_M)
    )
    runoff = (
        None if parent.runoff_weight is None
        else np.maximum(parent.sample(mesh.xyz, parent.runoff_weight), MIN_RUNOFF_WEIGHT)
    )
    inflow = parent_inflows(parent, region)
    if runoff is not None:
        inflow = inflow * runoff
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
