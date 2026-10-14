"""Measure regional, procedural and feature-tail sampling in actual finished terrain."""

import argparse
import inspect
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from unittest.mock import patch

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import Polygon

from benchmarks import profile_convergence, profile_refinement
from benchmarks.profile_convergence import DEFAULT_REFINEMENTS, compare_profile, validate_comparison
from benchmarks.profile_refinement import refine_profile, validate_refinement
from benchmarks.terrain import ROOT, numeric_hashes, peak_resident_bytes
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    LandformSettings,
    TerrainBasin,
    TerrainConstraint,
    TerrainRegion,
    TerrainSettings,
)
from map_maker.terrain.pipeline import generate
from map_maker.terrain.pipeline.water_sampling import (
    WATER_SAMPLING_ALGORITHM_ID,
    GroundSampler,
    SamplingFeature,
    SamplingGuide,
    plan_ground_profile,
)

CASES = ("regional", "procedural", "regional_detail", "tail", "overlap")
DIRECTIONS = ("horizontal", "diagonal", "oblique")


@dataclass(frozen=True, slots=True)
class ProfileScene:
    coastline: Coastline
    settings: TerrainSettings
    constraints: tuple[TerrainConstraint, ...]
    vertices_km: tuple[tuple[float, float], ...]
    water_level_m: float


def fixture(case: str, seed: int, scale_km: float, direction: str, resolution: int) -> ProfileScene:
    if case not in CASES or direction not in DIRECTIONS:
        raise ValueError("Unknown convergence case or direction.")
    settings = TerrainSettings(
        seed=seed,
        object_scale_km=scale_km,
        resolution_px=resolution,
        coastal_rise_km=1.0,
        largest_feature_km=2.0 if case == "procedural" else 450.0,
        variability=0.0 if case == "regional_detail" else 0.75,
    )
    ring = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))
    coastline = Coastline(ring, "public-convergence-square")
    start = np.asarray((0.25, 0.5 + 1 / 256)) * scale_km
    slope = {"horizontal": 0.0, "diagonal": 1.0, "oblique": .37}[direction]
    vector = np.asarray((1.0, slope)) * scale_km / 256
    axis = vector / np.linalg.norm(vector)
    normal = np.asarray((-axis[1], axis[0]))
    center = start + 0.375 * vector

    def point(position: NDArray[np.float64]) -> tuple[float, float]:
        return float(position[0] / scale_km), float(position[1] / scale_km)

    retained = TerrainBasin(
        ((0.15, 0.15), (0.85, 0.15), (0.85, 0.85), (0.15, 0.85), (0.15, 0.15)), "dry_basin"
    )
    plain = TerrainRegion(ring, LandformSettings("plain", 100.0, 0.0, 100.0, 1.0))
    constraints: tuple[TerrainConstraint, ...] = (
        (retained,) if case in ("procedural", "regional_detail") else (plain, retained)
    )
    level = (
        750.0
        if case == "regional"
        else 3100.0
        if case == "procedural"
        else 1800.0
        if case == "regional_detail"
        else 339.6
        if case == "tail"
        else 125.0
    )
    if case == "regional":
        # A fixed 1 km band is resolved differently on 400 and 4000 km objects.
        corners = tuple(
            point(center + along * 0.5 * axis + across * scale_km * 0.1 * normal)
            for along, across in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        )
        constraints += (
            TerrainRegion(
                (*corners, corners[0]), LandformSettings("plateau", 2000.0, 0.0, 100.0, 0.1)
            ),
        )
    elif case == "regional_detail":
        constraints += (TerrainRegion(
            ring, LandformSettings("hills", 1800., 1800., 2., 1., 31.)),)
    elif case == "tail":
        constraints += (ElevationPoint(point(center + normal), 2000.0, 0.1, "relative"),)
    elif case == "overlap":
        constraints += (
            ElevationPoint(point(center + 0.1 * normal), 150.0, 0.2, "relative"),
            ElevationPoint(point(center + 0.12 * axis - 0.08 * normal), -120.0, 0.25, "relative"),
        )
    vertices = tuple((float(p[0]), float(p[1])) for p in (start, start + vector))
    return ProfileScene(coastline, settings, constraints, vertices, level)


def probe(
    case: str,
    seed: int,
    scale_km: float,
    direction: str,
    resolution: int,
    refinements: tuple[int, ...],
    max_samples: int,
    *, adaptive_tolerances: tuple[float, ...] = (), adaptive_max_depth: int = 7,
    adaptive_max_samples: int = 65_536,
) -> dict[str, Any]:
    scene = fixture(case, seed, scale_km, direction, resolution)
    signature = inspect.signature(generate.resolve_basin_outflow)
    started = perf_counter()
    # Observe the existing call and run it unchanged. This repository-only seam
    # obtains the prepared pointwise field without a second terrain implementation.
    with patch.object(
        generate, "resolve_basin_outflow", wraps=generate.resolve_basin_outflow
    ) as observed:
        terrain = generate.generate_terrain(
            scene.coastline, scene.settings, constraints=scene.constraints
        )
    generation_seconds = perf_counter() - started
    if observed.call_count != 1 or observed.call_args is None:
        raise RuntimeError("Expected exactly one finished-ground review call.")
    bound = signature.bind(*observed.call_args.args, **observed.call_args.kwargs)
    sample = cast(GroundSampler, bound.arguments["sample_ground"])
    features = cast(tuple[SamplingGuide, ...], bound.arguments["features"])
    before = numeric_hashes(terrain)
    water_before = sha256(canonical_json(asdict(terrain.water.review))).hexdigest()
    x_km = cast(NDArray[np.float64], bound.arguments["x_km"])
    y_km = cast(NDArray[np.float64], bound.arguments["y_km"])
    spacing = min(float(x_km[1] - x_km[0]), float(y_km[1] - y_km[0])) / 4
    variants = {"current": features}
    geometry_only = tuple(replace(f, context_radius_km=None)
                          for f in features if isinstance(f, SamplingFeature))
    if geometry_only != features:
        variants["geometry_only"] = geometry_only
    without_regions = tuple(f for f in features
                            if not (isinstance(f, SamplingFeature)
                                    and isinstance(f.geometry, Polygon)))
    if len(without_regions) != len(features):
        variants["without_region_guidance"] = without_regions
    results: dict[str, Any] = {}
    started = perf_counter()
    for name, guides in variants.items():
        plan = plan_ground_profile(scene.vertices_km, spacing, guides)
        comparison = compare_profile(
            plan, sample, scene.water_level_m, refinements=refinements, max_samples=max_samples
        )
        results[name] = {"plan": asdict(plan), "comparison": asdict(comparison)}
        if name == "current" and adaptive_tolerances:
            results[name]["adaptive"] = [asdict(refine_profile(
                plan, sample, scene.water_level_m, tolerance_m=tolerance,
                max_depth=adaptive_max_depth, max_samples=adaptive_max_samples,
                reference_budget=max_samples,
            )) for tolerance in adaptive_tolerances]
    comparison_seconds = perf_counter() - started
    if (
        before != numeric_hashes(terrain)
        or water_before != sha256(canonical_json(asdict(terrain.water.review))).hexdigest()
    ):
        raise RuntimeError("Convergence inspection changed generated terrain or review evidence.")
    return {
        "case": case,
        "seed": seed,
        "scale_km": scale_km,
        "direction": direction,
        "resolution_px": resolution,
        "inputs": asdict(scene),
        "input_sha256": sha256(canonical_json(asdict(scene))).hexdigest(),
        "numeric_sha256": before,
        "water_review_sha256": water_before,
        "sampling_algorithm_id": WATER_SAMPLING_ALGORITHM_ID,
        "comparison_sha256": sha256(canonical_json(results)).hexdigest(),
        "generation_seconds": generation_seconds,
        "comparison_seconds": comparison_seconds,
        "process_peak_bytes": peak_resident_bytes(),
        "profiles": results,
    }


def source_identity() -> dict[str, str]:
    return {
        p.name: file_sha256(p)
        for p in (
            Path(__file__),
            Path(profile_convergence.__file__),
            Path(profile_refinement.__file__),
            ROOT / "benchmarks/terrain.py",
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, nargs="+", default=list(CASES))
    parser.add_argument("--seed", type=int, nargs="+", default=[42])
    parser.add_argument("--scale", type=float, nargs="+", default=[400.0, 4000.0])
    parser.add_argument("--direction", choices=DIRECTIONS, nargs="+", default=list(DIRECTIONS[:2]))
    parser.add_argument("--resolution", type=int, default=64)
    parser.add_argument("--refinements", type=int, nargs="+", default=list(DEFAULT_REFINEMENTS))
    parser.add_argument("--max-samples", type=int, default=262_144)
    parser.add_argument("--adaptive-tolerance", type=float, nargs="+", default=[],
                        help="Research midpoint residual thresholds in metres; not error bounds.")
    parser.add_argument("--adaptive-max-depth", type=int, default=7)
    parser.add_argument("--adaptive-max-samples", type=int, default=65_536)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        validate_comparison(tuple(args.refinements), args.max_samples)
        for tolerance in args.adaptive_tolerance or [.01]:
            validate_refinement(tolerance, args.adaptive_max_depth,
                                args.adaptive_max_samples, args.max_samples)
        if args.repeats < 1:
            raise ValueError("Repeats must be positive.")
        for seed in args.seed:
            for scale in args.scale:
                TerrainSettings(seed=seed, object_scale_km=scale, resolution_px=args.resolution)
    except ValueError as error:
        parser.error(str(error))
    if args.worker:
        print(
            canonical_json(
                probe(
                    args.case[0],
                    args.seed[0],
                    args.scale[0],
                    args.direction[0],
                    args.resolution,
                    tuple(args.refinements),
                    args.max_samples,
                    adaptive_tolerances=tuple(args.adaptive_tolerance),
                    adaptive_max_depth=args.adaptive_max_depth,
                    adaptive_max_samples=args.adaptive_max_samples,
                )
            ).decode(),
            end="",
        )
        return
    if args.output is None:
        parser.error("--output is required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        runtime, sources = runtime_identity(), source_identity()
        runs: list[dict[str, Any]] = []
        for case in args.case:
            for seed in args.seed:
                for scale in args.scale:
                    for direction in args.direction:
                        previous: dict[str, Any] | None = None
                        for _ in range(args.repeats):
                            command = [
                                sys.executable,
                                "-m",
                                "benchmarks.water_convergence",
                                "--worker",
                                "--case",
                                case,
                                "--seed",
                                str(seed),
                                "--scale",
                                str(scale),
                                "--direction",
                                direction,
                                "--resolution",
                                str(args.resolution),
                                "--max-samples",
                                str(args.max_samples),
                                "--refinements",
                                *(str(f) for f in args.refinements),
                            ]
                            if args.adaptive_tolerance:
                                command.extend([
                                    "--adaptive-tolerance",
                                    *(str(t) for t in args.adaptive_tolerance),
                                    "--adaptive-max-depth", str(args.adaptive_max_depth),
                                    "--adaptive-max-samples", str(args.adaptive_max_samples),
                                ])
                            done = subprocess.run(
                                command, cwd=ROOT, capture_output=True, text=True, check=True
                            )
                            run = json.loads(done.stdout)
                            if previous and any(
                                run[key] != previous[key]
                                for key in (
                                    "input_sha256",
                                    "numeric_sha256",
                                    "water_review_sha256",
                                    "comparison_sha256",
                                )
                            ):
                                raise RuntimeError(
                                    "Identical convergence inputs produced different evidence."
                                )
                            previous = run
                            runs.append(run)
                        print(f"{case} {scale:g} km {direction} seed={seed}: compared", flush=True)
        if runtime != runtime_identity() or sources != source_identity():
            raise RuntimeError("Generator, runtime or comparison source changed during inspection.")
        report = {
            "schema": "map-maker.water-profile-convergence",
            "schema_version": 2,
            "complete": True,
            "runtime": runtime,
            "comparison_source_sha256": sources,
            "method": {
                "fresh_process_per_run": True,
                "changes_terrain": False,
                "reference": "finite nested samples; not continuous ground truth",
                "head_model": "raw Float32 ground; no lake storage or discharge",
                "adaptive": {
                    "method_id": profile_refinement.REFINEMENT_METHOD_ID,
                    "tolerances_m": args.adaptive_tolerance,
                    "max_depth": args.adaptive_max_depth,
                    "sample_budget": args.adaptive_max_samples,
                    "reference_factor": 1 << (args.adaptive_max_depth + 1),
                    "continuous_error_bound": False,
                },
            },
            "runs": runs,
        }
        stream.write(canonical_json(report).decode())
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
