"""Repeatable terrain probes in fresh processes, without new dependencies."""

import argparse
import ctypes
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from statistics import median
from time import perf_counter, process_time
from typing import Any

import numpy as np

from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.adapters.project import load_terrain_project
from map_maker.terrain.adapters.render import render_height_map
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    LandComponent,
    TerrainBasin,
    TerrainBrushStroke,
    TerrainConstraint,
    TerrainSettings,
    TerrainStructure,
)
from map_maker.terrain.pipeline.generate import GeneratedTerrain, generate_terrain
from map_maker.terrain.pipeline.quality import measure_terrain_quality

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ("example", "square", "archipelago", "authored", "regional", "water", "outlet",
                 "flat", "shoreline", "narrow", "downstream", "internal", "dry")
SCALING_CASES = ("lakes_small", "lakes", "lakes_broad")
CASES = (*DEFAULT_CASES, *SCALING_CASES)


def _ring(x: float, y: float, rx: float, ry: float, count: int) -> tuple[tuple[float, float], ...]:
    angles = np.arange(count, dtype=np.float64) * (2.0 * np.pi / count)
    radius = 1.0 + 0.07 * np.sin(11.0 * angles) + 0.035 * np.cos(23.0 * angles)
    points = tuple(
        (float(px), float(py))
        for px, py in zip(
            x + rx * radius * np.cos(angles), y + ry * radius * np.sin(angles), strict=True
        )
    )
    return (*points, points[0])



def _lake_fixture(
    case: str, resolution: int, seed: int,
) -> tuple[Coastline, TerrainSettings, tuple[TerrainConstraint, ...]]:
    """Distributed retention footprints and point guides, including broad overlap.

    Potential networks deliberately include lakes whose full outlet review can
    reject the connection. These are workload inputs, not plausible lake levels.
    """
    settings = TerrainSettings(resolution_px=resolution, seed=seed, detail_levels=5)
    coast = Coastline(((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.)), case)
    side = 2 if case == "lakes_small" else 4
    constraints: list[TerrainConstraint] = []
    for row in range(side):
        for column in range(side):
            ring = _ring(.15 + .7 * column / (side-1), .15 + .7 * row / (side-1),
                         .1 / side, .13 / side, 16)
            constraints.append(TerrainBasin(
                ring, "lake", 1500., ring[0] if (row + column) % 2 == 0 else None))
    point_side = 2 * side
    radius = 2000. if case == "lakes_broad" else 12.
    for row in range(point_side):
        for column in range(point_side):
            constraints.append(ElevationPoint(
                (.08 + .84 * column / (point_side-1), .08 + .84 * row / (point_side-1)),
                60. if (row + column) % 2 else -60., radius, "relative"))
    return coast, settings, tuple(constraints)


def fixture(
    case: str, resolution: int, seed: int
) -> tuple[Coastline, TerrainSettings, tuple[TerrainConstraint, ...]]:
    """Public or synthetic inputs only; no private map or authored file changes."""
    if case in SCALING_CASES:
        return _lake_fixture(case, resolution, seed)
    settings = TerrainSettings(resolution_px=resolution, seed=seed)
    constraints: tuple[TerrainConstraint, ...] = ()
    if case in ("example", "regional", "water", "outlet", "flat", "shoreline", "narrow",
                "downstream", "internal", "dry"):
        name = {"example": "example", "regional": "landform-regions",
                "water": "basin-water", "outlet": "connected-outlet", "flat": "flat-outlet",
                "shoreline": "shoreline-gap", "narrow": "narrow-shoreline-gap",
                "downstream": "downstream-barrier", "internal": "internal-water-barrier",
                "dry": "dry-collection-barrier"}[case]
        project = load_terrain_project(ROOT / f"examples/terrain/{name}.terrain.json").project
        return (
            project.coastline,
            replace(project.settings, resolution_px=resolution, seed=seed),
            project.constraints,
        )
    if case not in CASES:
        raise ValueError(f"Unknown benchmark case: {case}")
    coastline = Coastline(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)), "square")
    if case == "archipelago":
        coastline = Coastline(
            _ring(0.36, 0.5, 0.30, 0.43, 768),
            "synthetic-archipelago",
            holes=(_ring(0.35, 0.5, 0.045, 0.06, 48),),
            additional_components=tuple(
                LandComponent(_ring(0.88, y, 0.07, 0.075, 48)) for y in (0.2, 0.5, 0.8)
            ),
        )
    elif case == "authored":
        constraints = (
            TerrainStructure("ridge", ((0.2, 0.35), (0.8, 0.35)), 1800.0, 160.0),
            ElevationPoint((0.35, 0.35), 2200.0, 120.0),
            ElevationPoint((0.55, 0.35), 1000.0, 120.0),
            TerrainStructure("valley", ((0.4, 0.6), (0.8, 0.8)), 300.0, 100.0, "relative"),
            TerrainBrushStroke(((0.2, 0.65), (0.3, 0.75)), -100.0, 150.0, 0.5, "relative"),
        )
    return coastline, settings, constraints


class StageTimer:
    """Group existing progress labels; no timing state enters the terrain engine."""

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}
        self._label = "before-first-progress"
        self._since = perf_counter()

    def __call__(self, _fraction: float, label: str) -> None:
        now = perf_counter()
        self.seconds[self._label] = self.seconds.get(self._label, 0.0) + now - self._since
        self._label = label
        self._since = now

    def finish(self) -> None:
        self(1.0, "finished")


def peak_resident_bytes() -> int | None:
    """Lifetime process high-water mark, including native allocations and imports."""
    if sys.platform == "win32":

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("faults", ctypes.c_ulong),
                ("peak", ctypes.c_size_t),
                ("working", ctypes.c_size_t),
                ("peak_paged", ctypes.c_size_t),
                ("paged", ctypes.c_size_t),
                ("peak_nonpaged", ctypes.c_size_t),
                ("nonpaged", ctypes.c_size_t),
                ("pagefile", ctypes.c_size_t),
                ("peak_pagefile", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.peak)
    if sys.platform in ("linux", "darwin"):
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    return None


def numeric_hashes(terrain: GeneratedTerrain) -> dict[str, str]:
    """One identity inventory shared by timing and read-only sampling probes."""
    return {
        name: sha256(array.tobytes()).hexdigest()
        for name, array in (
            ("elevation", terrain.elevation_m),
            ("land_mask", terrain.land_mask),
            ("x_km", terrain.x_km),
            ("y_km", terrain.y_km),
            ("routing_receivers", terrain.routing.receivers),
            ("routing_accumulation", terrain.routing.accumulation_km2),
            ("retention_terminals", terrain.routing.retention_terminal_mask),
            ("routing_channels", terrain.routing.channel_mask),
            ("routing_incision", terrain.routing.incision_m),
            ("routing_incision_limit", terrain.routing.incision_limit_m),
            ("routing_final_elevation", terrain.routing_final_elevation_m),
            ("channel_conflicts", terrain.routing_conflicts.flags),
            ("basin_labels", terrain.drainage.basin_labels),
            ("water_surface", terrain.water.surface_m),
            ("basin_internal_receivers", terrain.basin_outflow.internal_receivers),
            ("basin_flat_rank", terrain.basin_outflow.flat_rank),
            ("basin_internal_path_uphill", terrain.basin_outflow.internal_path_uphill_m),
            ("basin_catchment_class", terrain.basin_outflow.catchment_class),
            ("basin_retained_area", terrain.basin_outflow.retained_km2),
            ("outflow_sources", terrain.basin_outflow.source_km2),
            ("outflow_throughput", terrain.basin_outflow.throughput_km2),
            ("outflow_terminals", terrain.basin_outflow.terminal_km2),
            ("water_intent_ids", terrain.water.intent_ids),
            ("routing_intent_ids", terrain.water.routing_intent_ids),
            ("conditioned_final_receivers", terrain.drainage.receivers),
            ("nonland_class", terrain.drainage.nonland_class),
            ("boundary_flags", terrain.drainage.boundary_flags),
        )
    }


def probe(case: str, resolution: int, seed: int) -> dict[str, Any]:
    load_start = perf_counter()
    coast, settings, constraints = fixture(case, resolution, seed)
    load_seconds = perf_counter() - load_start
    inputs = {
        "coastline": asdict(coast),
        "settings": asdict(settings),
        "constraints": [asdict(item) for item in constraints],
    }
    timer = StageTimer()
    start, cpu_start = perf_counter(), process_time()
    terrain = generate_terrain(coast, settings, timer, constraints=constraints)
    generation_seconds, cpu_seconds = perf_counter() - start, process_time() - cpu_start
    timer.finish()
    generation_peak = peak_resident_bytes()
    start = perf_counter()
    quality = measure_terrain_quality(
        terrain.elevation_m,
        terrain.land_mask,
        x_spacing_km=terrain.grid.x_spacing_km,
        y_spacing_km=terrain.grid.y_spacing_km,
    )
    quality_seconds = perf_counter() - start
    render_seconds: dict[str, float] = {}
    for style in ("cartographic", "scientific"):
        start = perf_counter()
        with render_height_map(terrain, style=style):
            pass
        render_seconds[style] = perf_counter() - start
    products_peak = peak_resident_bytes()
    # Hash after memory sampling so comparison bookkeeping is not charged to generation.
    output_hashes = numeric_hashes(terrain)
    return {
        "case": case,
        "resolution_px": resolution,
        "seed": seed,
        "input_sha256": sha256(canonical_json(inputs)).hexdigest(),
        "output_sha256": output_hashes,
        "shape": list(terrain.elevation_m.shape),
        "land_fraction": float(np.mean(terrain.land_mask)),
        "boundary_vertices": coast.boundary_point_count,
        "constraint_count": len(constraints),
        "fixture_load_seconds": load_seconds,
        "generation_seconds": generation_seconds,
        "generation_cpu_seconds": cpu_seconds,
        "generation_stages_seconds": timer.seconds,
        "quality_seconds": quality_seconds,
        "render_seconds": render_seconds,
        "generation_process_peak_bytes": generation_peak,
        "products_process_peak_bytes": products_peak,
        "drainage": asdict(terrain.drainage.summary),
        "routing_agreement": asdict(terrain.routing_agreement),
        "channel_conflicts": asdict(terrain.routing_conflicts.summary),
        "authored_water": asdict(terrain.water.review),
        "basin_outflow": asdict(terrain.basin_outflow.summary),
        "quality": asdict(quality),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, nargs="+", default=list(DEFAULT_CASES))
    parser.add_argument("--resolution", type=int, nargs="+", default=[768])
    parser.add_argument("--seed", type=int, nargs="+", default=[20260902])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    try:
        for resolution in args.resolution:
            for seed in args.seed:
                TerrainSettings(resolution_px=resolution, seed=seed)
    except ValueError as error:
        parser.error(str(error))
    if args.worker:
        print(
            canonical_json(probe(args.case[0], args.resolution[0], args.seed[0])).decode(), end=""
        )
        return
    if args.output is None:
        parser.error("--output is required")
    # Reserve before running any children; preserve an incomplete report on failure.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        runtime = runtime_identity()
        benchmark_hash = file_sha256(Path(__file__))
        runs: list[dict[str, Any]] = []
        for case in args.case:
            for resolution in args.resolution:
                for seed in args.seed:
                    batch: list[dict[str, Any]] = []
                    for _ in range(args.repeats):
                        start = perf_counter()
                        completed = subprocess.run(
                            [
                                sys.executable,
                                "-m",
                                "benchmarks.terrain",
                                "--worker",
                                "--case",
                                case,
                                "--resolution",
                                str(resolution),
                                "--seed",
                                str(seed),
                            ],
                            cwd=ROOT,
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        run = json.loads(completed.stdout)
                        run["worker_wall_seconds"] = perf_counter() - start
                        if batch and any(
                            run[key] != batch[0][key]
                            for key in ("input_sha256", "output_sha256", "drainage",
                                        "routing_agreement", "channel_conflicts",
                                        "authored_water", "basin_outflow", "quality")
                        ):
                            raise RuntimeError(
                                "Identical benchmark inputs produced different results"
                            )
                        runs.append(run)
                        batch.append(run)
                    print(
                        f"{case} {resolution}px seed={seed}: "
                        f"{median(run['generation_seconds'] for run in batch):.3f}s generation",
                        flush=True,
                    )
        if runtime != runtime_identity():
            raise RuntimeError("Generator source/runtime changed during benchmark")
        if benchmark_hash != file_sha256(Path(__file__)):
            raise RuntimeError("Benchmark source changed during benchmark")
        report = {
            "schema": "map-maker.terrain-benchmark",
            "schema_version": 1,
            "complete": True,
            "runtime": runtime,
            "benchmark_source_sha256": benchmark_hash,
            "method": {
                "fresh_process_per_run": True,
                "warmups": 0,
                "memory": "process lifetime peak resident bytes, including imports",
                "timed_file_export": False,
            },
            "runs": runs,
        }
        stream.write(canonical_json(report).decode())
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
