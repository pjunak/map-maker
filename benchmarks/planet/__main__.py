# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Whole-planet relief experiment: python -m benchmarks.planet --world W --output DIR."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from benchmarks.planet.evolve import evolve
from benchmarks.planet.fields import coast_distance, default_tectonics, land_on_mesh, ocean_floor
from benchmarks.planet.geology import calibrated_evolution, geology_forcing
from benchmarks.planet.mesh import build_mesh
from benchmarks.planet.metrics import summarize
from benchmarks.planet.render import Rasterizer, draw_rivers, relief_image
from dmtools.terrain.adapters.world_geology import read_geology
from dmtools.terrain.application.world import open_world


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--geology", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nodes", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration-myr", type=float, default=30.0)
    parser.add_argument("--dt-kyr", type=float, default=100.0)
    parser.add_argument("--erodibility", type=float, default=4e-6)
    parser.add_argument("--m", type=float, default=0.45)
    parser.add_argument("--process-km2", type=float, default=10_000.0)
    parser.add_argument("--calibrate", type=int, default=3, help="Geology target iterations.")
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--river-km2", type=float, default=40_000.0)
    args = parser.parse_args()
    out: Path = args.output
    out.mkdir(parents=True, exist_ok=False)

    t0 = time.perf_counter()
    world = open_world(args.world)
    radius = world.project.frame.radius_km * 1000
    mesh = build_mesh(args.nodes, radius, seed=args.seed)
    t_mesh = time.perf_counter() - t0
    land = land_on_mesh(world, mesh)
    water = ~land
    coast = coast_distance(mesh, land)
    duration = args.duration_myr * 1e6
    t_fields = time.perf_counter() - t0 - t_mesh
    print(
        f"mesh {mesh.size:,} nodes, spacing {mesh.spacing_m / 1e3:.1f} km, "
        f"{t_mesh:.1f}s; fields {t_fields:.1f}s; land {land.mean():.1%}",
        flush=True,
    )
    rng = np.random.default_rng(args.seed)
    initial = 1 + 5 * rng.random(mesh.size) + 0.002 * coast
    run = {
        "duration_yr": duration,
        "dt_yr": args.dt_kyr * 1e3,
        "m": args.m,
        "process_area_m2": args.process_km2 * 1e6,
    }
    calibration: tuple[dict[str, object], ...] = ()
    if args.geology is None:
        tect = default_tectonics(mesh, land, coast, args.seed, erodibility=args.erodibility)
        h, state, history = evolve(mesh, water, tect, initial, **run)
        forcing_image = tect.belts
        uplift = tect.uplift
    else:
        recipe, _ = read_geology(args.geology)
        forcing = geology_forcing(world, recipe, mesh, land)
        result = calibrated_evolution(
            mesh, land, coast, forcing, initial, seed=args.seed, erodibility=args.erodibility,
            iterations=args.calibrate, **run,
        )
        h, state, history = result.elevation, result.state, result.history
        calibration = result.records
        uplift = result.parts.steady + result.parts.pulse
        forcing_image = uplift / max(float(uplift.max()), 1e-12)
    elevation = np.where(water, ocean_floor(coast, water, mesh, args.seed), h)

    t1 = time.perf_counter()
    raster = Rasterizer(mesh, args.width)
    z = raster(elevation)
    land_px = raster.nearest_values(land).astype(bool)
    image = relief_image(z, land_px, raster.lat, radius)
    rivers = draw_rivers(image, mesh, state.receiver, state.area, water, args.river_km2 * 1e6)
    image.save(out / "relief.png")
    belts = raster(forcing_image)
    Image.fromarray((np.clip(belts, 0, 1) * 255).astype(np.uint8)).save(out / "forcing.png")
    t_render = time.perf_counter() - t1
    np.savez_compressed(
        out / "mesh-state.npz", xyz=mesh.xyz, elevation=elevation, land=land,
        receiver=state.receiver, area=state.area, uplift=uplift,
    )
    report = {
        "world": str(args.world),
        "geology": None if args.geology is None else str(args.geology),
        "nodes": mesh.size,
        "spacing_km": mesh.spacing_m / 1e3,
        "seed": args.seed,
        "duration_myr": args.duration_myr,
        "dt_kyr": args.dt_kyr,
        "erodibility": args.erodibility,
        "m": args.m,
        "process_km2": args.process_km2,
        "land_fraction_nodes": float(land.mean()),
        "rivers_drawn": rivers,
        "metrics": summarize(mesh, h, water, state),
        "calibration": calibration,
        "seconds": {
            "mesh": t_mesh, "fields": t_fields, "evolve_last": history.seconds,
            "render": t_render, "total": time.perf_counter() - t0,
        },
        "history": {
            "t_myr": [t / 1e6 for t in history.times_yr],
            "mean_m": history.mean_m,
            "max_m": history.max_m,
            "change_mm_per_yr": [c * 1e3 for c in history.change_m_per_yr],
        },
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=1))


if __name__ == "__main__":
    main()
