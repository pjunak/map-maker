# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Research harness: parent-conditioned regional enrichment of a planet (M6).

A circular region of the planet is regenerated on a finer mesh:

* nodes: jittered triangular lattice in a local azimuthal-equidistant plane,
  mapped back to the sphere (same kernels as the planet);
* land: the exact vector coastline at the finer spacing;
* boundary: land nodes on the region edge are fixed at the parent's surface;
  rivers that enter the region in the parent enter as point inflows;
* forcing: parent uplift, erodibility and runoff, plus finer rock texture and a
  smaller process area, so smaller valleys resolve;
* consistency: local uplift is corrected so the regional relief, smoothed to the
  parent spacing, matches the parent surface (multiplicative, smoothed, iterated).

    python -m benchmarks.planet.regional WORLD [--geology G] --lon L --lat P --output DIR
"""

import argparse
import json
import time
from dataclasses import dataclass
from math import cos, pi, radians, sin
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy.spatial import Delaunay, KDTree

from dmtools.terrain.adapters.planet_render import LAND_STOPS, SEA_STOPS
from dmtools.terrain.adapters.world_geology import read_geology
from dmtools.terrain.application.world import open_world
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.pipeline.planet import PlanetResult, generate_planet
from dmtools.terrain.pipeline.planet_evolution import EvolutionRun, evolve
from dmtools.terrain.pipeline.planet_forcing import Forcing, land_on_mesh, smooth_over_land
from dmtools.terrain.pipeline.planet_kernels import interpolate_to_lonlat
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, mesh_from_triangles, vertex_triangles
from dmtools.terrain.pipeline.planet_metrics import compass_share, non_descending_receivers
from dmtools.terrain.pipeline.planet_noise import fbm3

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]


def inverse_aeqd(x: F64, y: F64, lon0: float, lat0: float, radius_m: float) -> F64:
    """Plane metres (x east, y north) about (lon0, lat0) to unit vectors on the sphere."""
    rho = np.hypot(x, y)
    c = rho / radius_m
    phi0, lam0 = radians(lat0), radians(lon0)
    safe = np.where(rho > 0, rho, 1.0)
    lat = np.arcsin(
        np.clip(
            np.cos(c) * sin(phi0) + np.where(rho > 0, y * np.sin(c) * cos(phi0) / safe, 0),
            -1,
            1,
        )
    )
    lon = lam0 + np.arctan2(x * np.sin(c), rho * cos(phi0) * np.cos(c) - y * sin(phi0) * np.sin(c))
    return np.stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)), axis=1)


@dataclass(frozen=True)
class Region:
    mesh: SphereMesh
    plane_m: F64  # (n, 2)
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
    x = (jx + 0.5 * (jy % 2)) * s
    y = jy * s * np.sqrt(3) / 2
    rng = np.random.default_rng(seed)
    x = x + rng.normal(scale=0.2 * s, size=x.shape)
    y = y + rng.normal(scale=0.2 * s, size=y.shape)
    keep = np.hypot(x, y) <= r
    # A clean outer ring keeps the boundary convex and evenly sampled.
    ring = int(np.ceil(2 * pi * r / s))
    angle = np.arange(ring) * 2 * pi / ring
    interior = keep & (np.hypot(x, y) <= r - 0.6 * s)
    px = np.concatenate([x[interior], r * np.cos(angle)])
    py = np.concatenate([y[interior], r * np.sin(angle)])
    plane = np.stack((px, py), axis=1)
    triangles = Delaunay(plane).simplices.astype(np.int64)
    xyz = inverse_aeqd(px, py, lon0, lat0, planet_m)
    mesh = mesh_from_triangles(xyz, triangles, planet_m)
    boundary = np.zeros(len(px), dtype=bool)
    boundary[-ring:] = True
    return Region(mesh, plane, boundary, (lon0, lat0), r)


def sample_parent(parent: PlanetResult, xyz: F64, values: F64) -> F64:
    mesh = parent.mesh
    nearest = np.asarray(KDTree(mesh.xyz).query(xyz, workers=-1)[1], dtype=np.int64)
    vt_ptr, vt_idx = vertex_triangles(mesh)
    return interpolate_to_lonlat(
        np.ascontiguousarray(values, dtype=np.float64), mesh.xyz, mesh.triangles, vt_ptr,
        vt_idx, mesh.ptr, mesh.nbr, nearest, xyz,
    )


def parent_inflows(parent: PlanetResult, region: Region) -> F64:
    """Parent rivers crossing into the region become area sources at entry nodes."""
    pm = parent.mesh
    flow = parent.flow
    centre = inverse_aeqd(np.zeros(1), np.zeros(1), *region.centre, pm.radius_m)[0]
    distance = pm.radius_m * np.arccos(np.clip(pm.xyz @ centre, -1, 1))
    outside = parent.land & (distance > region.radius_m) & (flow.receiver >= 0)
    receiver = flow.receiver[outside]
    entering = distance[receiver] <= region.radius_m
    sources = np.flatnonzero(outside)[entering]
    inflow = np.zeros(region.mesh.size)
    if not len(sources):
        return inflow
    # Credit the regional interior land node nearest each parent receiver.
    candidates = np.flatnonzero(~region.boundary)
    tree = KDTree(region.mesh.xyz[candidates])
    target = candidates[np.asarray(tree.query(pm.xyz[flow.receiver[sources]])[1])]
    np.add.at(inflow, target, flow.area_m2[sources])
    return inflow


@dataclass(frozen=True)
class RegionalResult:
    region: Region
    land: B
    elevation_m: F64
    run: EvolutionRun
    target_m: F64
    correction: F64
    history: list[dict[str, float]]


def enrich(
    parent: PlanetResult,
    region: Region,
    *,
    process_area_km2: float,
    iterations: int,
    seed: int,
    texture: float = 0.5,
) -> RegionalResult:
    mesh = region.mesh
    land = land_on_mesh(parent.world, mesh)
    water = ~land
    parent_water = ~parent.land
    surface = np.where(parent.land, parent.lakes.surface_m, 0.0)
    target = np.maximum(sample_parent(parent, mesh.xyz, surface), 0.0)
    fixed = water | (region.boundary & land)
    level = np.where(water, 0.0, target)
    steady = sample_parent(parent, mesh.xyz, parent.forcing.steady_uplift)
    pulse = sample_parent(parent, mesh.xyz, parent.forcing.pulse_uplift)
    erodibility = sample_parent(parent, mesh.xyz, parent.forcing.erodibility)
    erodibility *= np.exp(texture * fbm3(mesh.xyz, seed + 31, 4, mesh.radius_m / 40e3))
    runoff = (
        None if parent.runoff_weight is None
        else np.maximum(sample_parent(parent, mesh.xyz, parent.runoff_weight), 0.05)
    )
    inflow = parent_inflows(parent, region)
    if runoff is not None:
        inflow = inflow * np.where(inflow > 0, runoff, 1.0)
    settings: PlanetSettings = parent.settings
    rng = np.random.default_rng(seed)
    initial = np.maximum(target, 1.0) + 5 * rng.random(mesh.size)
    smoothing = parent.mesh.spacing_m
    correction = np.ones(mesh.size)
    previous: tuple[F64, F64] | None = None
    history: list[dict[str, float]] = []
    run = None
    for iteration in range(iterations + 1):
        forcing = Forcing(steady * correction, pulse * correction, erodibility, water)
        run = evolve(
            mesh, fixed, forcing, initial, steps=settings.steps, step_yr=settings.step_kyr * 1e3,
            area_exponent=settings.area_exponent, process_area_m2=process_area_km2 * 1e6,
            runoff=runoff, fixed_level=level, inflow_m2=inflow,
        )
        smooth = smooth_over_land(mesh, np.where(land, run.elevation, 0.0), land, smoothing)
        interior = land & ~fixed
        error = smooth[interior] - target[interior]
        history.append({
            "iteration": iteration,
            "rms_vs_parent_m": float(np.sqrt(np.mean(error**2))),
            "mean_bias_m": float(np.mean(error)),
            "mean_m": float(np.mean(run.elevation[interior])),
            "max_m": float(np.max(run.elevation[interior])),
        })
        print(json.dumps(history[-1]), flush=True)
        if iteration == iterations:
            break
        # First step: ratio. Later: per-node secant on the (correction -> smoothed
        # relief) response, which also accounts for fixed boundary base levels.
        ratio = np.clip((target + 50.0) / (smooth + 50.0), 1 / 3, 3.0)
        proposal = correction * ratio
        if previous is not None:
            dc = correction - previous[0]
            ds = smooth - previous[1]
            slope = np.divide(ds, dc, out=np.zeros_like(ds), where=np.abs(dc) > 1e-6)
            usable = slope > 1.0  # metres of smoothed relief per unit correction
            secant = correction + (target - smooth) / np.where(usable, slope, 1.0)
            proposal = np.where(usable, secant, proposal)
        proposal = np.clip(proposal, correction / 3, correction * 3)
        previous = (correction, smooth)
        correction = np.maximum(
            smooth_over_land(mesh, np.where(land, proposal, correction), land, smoothing / 2),
            0.02,
        )
    assert run is not None
    del parent_water
    return RegionalResult(region, land, run.elevation, run, target, correction, history)


def plane_raster(region: Region, mesh_values: F64, pixels: int) -> tuple[F64, B]:
    r = region.radius_m
    centres = (np.arange(pixels) + 0.5) / pixels * 2 * r - r
    gx, gy = np.meshgrid(centres, -centres)
    inside = np.hypot(gx, gy) <= r
    q = inverse_aeqd(gx.ravel(), gy.ravel(), *region.centre, region.mesh.radius_m)
    mesh = region.mesh
    nearest = np.asarray(KDTree(mesh.xyz).query(q, workers=-1)[1], dtype=np.int64)
    vt_ptr, vt_idx = vertex_triangles(mesh)
    out = interpolate_to_lonlat(
        np.ascontiguousarray(mesh_values), mesh.xyz, mesh.triangles, vt_ptr, vt_idx, mesh.ptr,
        mesh.nbr, nearest, q,
    ).reshape(pixels, pixels)
    return out, inside


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("world", type=Path)
    parser.add_argument("--geology", type=Path)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--radius-km", type=float, default=700.0)
    parser.add_argument("--spacing-km", type=float, default=5.0)
    parser.add_argument("--process-km2", type=float, default=600.0)
    parser.add_argument("--parent-nodes", type=int, default=200_000)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out: Path = args.output
    out.mkdir(parents=True, exist_ok=False)
    world = open_world(args.world)
    recipe = None if args.geology is None else read_geology(args.geology)[0]
    started = time.perf_counter()
    parent = generate_planet(world, PlanetSettings(seed=args.seed, nodes=args.parent_nodes), recipe)
    parent_seconds = time.perf_counter() - started
    region = regional_mesh(
        args.lon, args.lat, args.radius_km, args.spacing_km, parent.mesh.radius_m, args.seed
    )
    started = time.perf_counter()
    result = enrich(
        parent, region, process_area_km2=args.process_km2, iterations=args.iterations,
        seed=args.seed,
    )
    regional_seconds = time.perf_counter() - started
    pixels = 1200
    fine, inside = plane_raster(region, np.where(result.land, result.elevation_m, -200.0), pixels)
    coarse, _ = plane_raster(region, result.target_m, pixels)
    land_px = (fine > -100) & inside
    pixel_m = 2 * region.radius_m / pixels
    canvas = Image.new("RGB", (pixels * 2 + 20, pixels), "white")
    canvas.paste(plane_relief(np.where(land_px, coarse, -200.0), land_px, pixel_m), (0, 0))
    canvas.paste(plane_relief(fine, land_px, pixel_m), (pixels + 20, 0))
    canvas.save(out / "parent-vs-regional.png")
    receiver = result.run.flow.receiver
    report = {
        "nodes": region.mesh.size,
        "spacing_km": region.mesh.spacing_m / 1e3,
        "parent_nodes": parent.mesh.size,
        "seconds": {"parent": parent_seconds, "regional": regional_seconds},
        "history": result.history,
        "non_descending_receivers": non_descending_receivers(
            result.run.elevation, receiver, ~result.land | region.boundary
        ),
        "compass_sector_share": compass_share(
            region.mesh, receiver, result.land & ~region.boundary
        ),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "history"}, indent=1))


def _ramp(z: F64, stops: tuple[tuple[int, tuple[int, int, int]], ...]) -> F64:
    xs = np.array([k for k, _ in stops], dtype=np.float64)
    return np.stack([np.interp(z, xs, [c[i] for _, c in stops]) for i in range(3)], axis=-1)


def plane_relief(z: F64, land_px: B, pixel_m: float, exaggeration: float = 6.0) -> Image.Image:
    gy, gx = np.gradient(z, pixel_m)
    gx, gy = gx * exaggeration, -gy * exaggeration
    az, alt = np.deg2rad(315), np.deg2rad(40)
    light = (np.cos(alt) * np.sin(az), np.cos(alt) * np.cos(az), np.sin(alt))
    shade = np.clip(
        (-gx * light[0] - gy * light[1] + light[2]) / np.sqrt(gx * gx + gy * gy + 1), 0, 1
    )
    rgb = np.where(land_px[..., None], _ramp(z, LAND_STOPS), _ramp(z, SEA_STOPS))
    factor = np.where(land_px, 0.55 + 0.65 * shade, 0.95)
    return Image.fromarray(np.clip(rgb * factor[..., None], 0, 255).astype(np.uint8))


if __name__ == "__main__":
    main()
