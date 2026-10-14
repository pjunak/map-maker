"""Measure conservative component bounds against independent finite noise probes."""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from benchmarks import noise_intervals, noise_profiles, noise_refinement
from benchmarks.noise_intervals import (
    MAX_CELLS,
    METHOD_ID,
    METHODS,
    BoundMethod,
    NoiseParameters,
    enclose_noise,
)
from benchmarks.noise_profiles import (
    HYBRID_METHOD_ID,
    MAX_SLABS,
    PROFILE_METHOD_ID,
    NoisePath,
    ProfileGeometry,
    enclose_noise_profile,
    ordered_rise_upper_bound,
)
from benchmarks.noise_refinement import (
    MAX_DEPTH,
    MAX_SAMPLES,
    REFINEMENT_METHOD_ID,
    RefinementControls,
    RefinementResult,
    RefinementStrategy,
    refine_noise_profile,
)
from benchmarks.terrain import ROOT, peak_resident_bytes
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.pipeline.noise import fractal_value_noise

type ComparisonMethod = BoundMethod | Literal["profile_slabs", "profile_hybrid"]
COMPARISON_METHODS: tuple[ComparisonMethod, ...] = (*METHODS, "profile_slabs", "profile_hybrid")

REFINEMENT_POLICIES: tuple[tuple[RefinementStrategy, ProfileGeometry], ...] = (
    ("uniform", "hybrid"),
    ("adaptive", "slabs"),
    ("adaptive", "hybrid"),
)

DIRECTIONS = {"horizontal": 0.0, "diagonal": 1.0, "oblique": 0.37}
REFERENCE_INTERVALS = 65_536
AMPLITUDE_M, OFFSET_M = 1000.0, 2000.0


def source_identity() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): file_sha256(path)
        for path in (
            Path(__file__),
            Path(noise_intervals.__file__),
            Path(noise_profiles.__file__),
            Path(noise_refinement.__file__),
        )
    }


def validate_controls(
    divisions: tuple[int, ...], max_cells: int, repeats: int, max_slabs: int = MAX_SLABS
) -> None:
    if (
        not divisions
        or tuple(sorted(set(divisions))) != divisions
        or any(type(n) is not int or not 1 <= n <= 8192 or n & (n - 1) for n in divisions)
    ):
        raise ValueError("Noise divisions must be increasing powers of two up to 8192.")
    if type(max_cells) is not int or not 1 <= max_cells <= MAX_CELLS:
        raise ValueError("Noise cell budget must be an integer from 1 to 262144.")
    if type(max_slabs) is not int or not 1 <= max_slabs <= MAX_SLABS:
        raise ValueError("Noise slab budget must be an integer from 1 to 262144.")
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("Noise repeats must be an integer from 1 to 10.")


def _field(positions: NDArray[np.float64], parameters: NoiseParameters) -> NDArray[np.float32]:
    values = fractal_value_noise(positions[:, 0], positions[:, 1], **asdict(parameters))
    return (OFFSET_M + AMPLITUDE_M * values).astype(np.float32)


def refinement_evidence(
    result: RefinementResult,
    reference: NDArray[np.float32],
    reference_rise: float,
    tolerance: float,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": result.status,
        "evaluated_cell_count": result.evaluated_cell_count,
        "allocated_slab_count": result.allocated_slab_count,
        "evaluated_sample_count": result.evaluated_sample_count,
        "required_cell_count": result.required_cell_count,
        "required_slab_count": result.required_slab_count,
        "required_sample_count": result.required_sample_count,
        "waves": [asdict(w) for w in result.waves],
        "accepted": None,
    }
    profile = result.profile
    if profile is None:
        return report
    indices = (profile.fractions * REFERENCE_INTERVALS).astype(np.int64)
    if not np.array_equal(indices / REFERENCE_INTERVALS, profile.fractions):
        raise RuntimeError("Refined fractions no longer belong to the independent reference grid.")
    if profile.samples_m.tobytes() != reference[indices].tobytes():
        raise RuntimeError("Refined noise changed at shared binary64 positions.")
    positions = np.linspace(0.0, 1.0, REFERENCE_INTERVALS + 1)
    owners = np.minimum(
        np.searchsorted(profile.fractions, positions, side="right") - 1,
        len(profile.fractions) - 2,
    )
    low, high = profile.field_m.low, profile.field_m.high
    if not np.all((low[owners] <= reference) & (reference <= high[owners])):
        raise RuntimeError("A refined bound excluded an independent reference probe.")
    reference_min, reference_max = np.full(len(low), np.inf), np.full(len(low), -np.inf)
    np.minimum.at(reference_min, owners, reference)
    np.maximum.at(reference_max, owners, reference)
    samples = profile.samples_m.astype(np.float64)
    local_miss = max(
        0.0,
        float(np.max(reference_max - np.maximum(samples[:-1], samples[1:]))),
        float(np.max(np.minimum(samples[:-1], samples[1:]) - reference_min)),
    )
    metrics = result.waves[-1].metrics
    if local_miss > tolerance or reference_rise - metrics.sampled_uphill_lower_bound_m > tolerance:
        raise RuntimeError("Accepted refinement missed its tolerance against finite reference.")
    if metrics.uphill_upper_bound_m < reference_rise:
        raise RuntimeError("A refined ordered bound excluded a finite reference excursion.")
    report["accepted"] = {
        "interval_count": len(low),
        "fractions_sha256": sha256(profile.fractions.tobytes()).hexdigest(),
        "samples_sha256": sha256(profile.samples_m.tobytes()).hexdigest(),
        "bounds_sha256": sha256(low.tobytes() + high.tobytes()).hexdigest(),
        "reference_outside_count": 0,
        "reference_maximum_local_miss_m": local_miss,
        "reference_uphill_miss_m": reference_rise - metrics.sampled_uphill_lower_bound_m,
        "metrics": asdict(metrics),
    }
    return report


def probe(
    parameters: NoiseParameters,
    span: float,
    direction: str,
    divisions: tuple[int, ...],
    max_cells: int,
    max_slabs: int = MAX_SLABS,
    *,
    adaptive_tolerances: tuple[float, ...] = (),
    adaptive_max_samples: int = MAX_SAMPLES,
    adaptive_max_depth: int = MAX_DEPTH,
) -> dict[str, Any]:
    validate_controls(divisions, max_cells, 1, max_slabs)
    for tolerance in adaptive_tolerances:
        RefinementControls(
            tolerance,
            max_cells=max_cells,
            max_slabs=max_slabs,
            max_samples=adaptive_max_samples,
            max_depth=adaptive_max_depth,
        )
    if direction not in DIRECTIONS or not np.isfinite(span) or not 0 < span <= 16:
        raise ValueError("Noise profile direction/span is unsupported.")
    start = np.asarray((-0.271, 0.193)) * parameters.largest_feature_km
    vector = np.asarray((1.0, DIRECTIONS[direction])) * (span * parameters.largest_feature_km)
    fractions = np.linspace(0.0, 1.0, REFERENCE_INTERVALS + 1)
    path = NoisePath((float(start[0]), float(start[1])), (float(vector[0]), float(vector[1])))
    positions = start + fractions[:, None] * vector
    reference_start = perf_counter()
    reference = _field(positions, parameters)
    reference_seconds = perf_counter() - reference_start
    reference_values = reference.astype(np.float64)
    reference_rise = float(np.max(reference_values - np.minimum.accumulate(reference_values)))
    trials: list[dict[str, Any]] = []
    timings: list[dict[str, Any]] = []
    for count in divisions:
        # Fixed dyadic stations, chosen without inspecting any reference heights.
        indices = np.arange(count + 1) * (REFERENCE_INTERVALS // count)
        anchors = positions[indices]
        boxes = np.column_stack(
            (np.minimum(anchors[:-1], anchors[1:]), np.maximum(anchors[:-1], anchors[1:]))
        )
        sample_start = perf_counter()
        samples = _field(anchors, parameters)
        sample_seconds = perf_counter() - sample_start
        if samples.tobytes() != reference[indices].tobytes():
            raise RuntimeError("Noise component changed at shared binary64 positions.")
        sample_values = samples.astype(np.float64)
        sample_rise = float(np.max(sample_values - np.minimum.accumulate(sample_values)))
        spans = np.column_stack((fractions[indices[:-1]], fractions[indices[1:]]))
        for method in COMPARISON_METHODS:
            bound_start = perf_counter()
            if method in ("profile_slabs", "profile_hybrid"):
                result = enclose_noise_profile(
                    path,
                    spans,
                    parameters,
                    amplitude_m=AMPLITUDE_M,
                    offset_m=OFFSET_M,
                    max_cells=max_cells,
                    max_slabs=max_slabs,
                    geometry="hybrid" if method == "profile_hybrid" else "slabs",
                )
            else:
                result = enclose_noise(
                    boxes,
                    parameters,
                    amplitude_m=AMPLITUDE_M,
                    offset_m=OFFSET_M,
                    max_cells=max_cells,
                    method=method,
                )
            bound_seconds = perf_counter() - bound_start
            trial: dict[str, Any] = {
                "method": method,
                "divisions": count,
                "box_count": len(boxes),
                "status": result.status,
                "requested_cell_count": result.requested_cell_count,
                "requested_slab_count": result.requested_slab_count,
                "rectangle_plan_count": result.rectangle_plan_count,
                "clipped_plan_count": result.clipped_plan_count,
                "evaluated_cell_count": result.evaluated_cell_count,
                "sample_count": len(samples),
                "positions_sha256": sha256(anchors.tobytes()).hexdigest(),
                "samples_sha256": sha256(samples.tobytes()).hexdigest(),
                "sampled_uphill_m": sample_rise,
                "missed_reference_uphill_m": reference_rise - sample_rise,
                "sampled_minimum_m": float(np.min(samples)),
                "sampled_maximum_m": float(np.max(samples)),
                "missed_reference_peak_m": float(np.max(reference)) - float(np.max(samples)),
                "missed_reference_trough_m": float(np.min(samples)) - float(np.min(reference)),
                "enclosure": None,
            }
            if result.field_m is not None and result.noise is not None:
                field = result.field_m
                owners = np.minimum(
                    np.arange(REFERENCE_INTERVALS + 1) * count // REFERENCE_INTERVALS, count - 1
                )
                if not np.all((field.low[owners] <= reference) & (reference <= field.high[owners])):
                    raise RuntimeError("A component bound excluded an independent finite probe.")
                rise_bound = ordered_rise_upper_bound(field)
                if rise_bound < reference_rise:
                    raise RuntimeError(
                        "An ordered-rise bound excluded a finite reference excursion."
                    )
                trial["enclosure"] = {
                    "maximum_uphill_upper_bound_m": rise_bound,
                    "uphill_gap_m": rise_bound - sample_rise,
                    "uphill_excess_over_finite_reference_m": rise_bound - reference_rise,
                    "minimum_lower_bound_m": float(np.min(field.low)),
                    "maximum_upper_bound_m": float(np.max(field.high)),
                    "maximum_interval_width_m": float(np.max(field.high - field.low)),
                    "maximum_extremum_gap_m": max(
                        float(np.max(field.high) - np.max(samples)),
                        float(np.min(samples) - np.min(field.low)),
                    ),
                    "upper_excess_over_finite_reference_m": float(
                        np.max(field.high) - np.max(reference)
                    ),
                    "lower_excess_over_finite_reference_m": float(
                        np.min(reference) - np.min(field.low)
                    ),
                    "bounds_sha256": sha256(
                        b"".join(
                            a.tobytes()
                            for a in (result.noise.low, result.noise.high, field.low, field.high)
                        )
                    ).hexdigest(),
                    "reference_outside_count": 0,
                }
            trials.append(trial)
            timings.append(
                {
                    "method": method,
                    "divisions": count,
                    "bound_seconds": bound_seconds,
                    "point_sample_seconds": sample_seconds,
                }
            )
    refinement_trials: list[dict[str, Any]] = []
    refinement_timings: list[dict[str, Any]] = []
    for tolerance in adaptive_tolerances:
        for strategy, geometry in REFINEMENT_POLICIES:
            controls = RefinementControls(
                tolerance,
                geometry=geometry,
                strategy=strategy,
                max_cells=max_cells,
                max_slabs=max_slabs,
                max_samples=adaptive_max_samples,
                max_depth=adaptive_max_depth,
            )
            begin = perf_counter()
            refined = refine_noise_profile(path, parameters, controls)
            seconds = perf_counter() - begin
            refinement_trials.append(
                {
                    "controls": asdict(controls),
                    **refinement_evidence(refined, reference, reference_rise, tolerance),
                }
            )
            refinement_timings.append({"controls": asdict(controls), "seconds": seconds})
    inputs = {
        "noise": asdict(parameters),
        "span_in_largest_features": span,
        "direction": direction,
        "start_km": start.tolist(),
        "vector_km": vector.tolist(),
        "amplitude_m": AMPLITUDE_M,
        "offset_m": OFFSET_M,
        "divisions": divisions,
        "max_cells": max_cells,
        "methods": COMPARISON_METHODS,
        "max_slabs": max_slabs,
        "adaptive_tolerances": adaptive_tolerances,
        "adaptive_max_samples": adaptive_max_samples,
        "adaptive_max_depth": adaptive_max_depth,
    }
    evidence = {
        "reference_count": len(reference),
        "reference_positions_sha256": sha256(positions.tobytes()).hexdigest(),
        "reference_values_sha256": sha256(reference.tobytes()).hexdigest(),
        "reference_uphill_m": reference_rise,
        "reference_minimum_m": float(np.min(reference)),
        "reference_maximum_m": float(np.max(reference)),
        "trials": trials,
        "refinement_trials": refinement_trials,
    }
    return {
        "input": inputs,
        "input_sha256": sha256(canonical_json(inputs)).hexdigest(),
        "evidence": evidence,
        "evidence_sha256": sha256(canonical_json(evidence)).hexdigest(),
        "timing": {
            "reference_seconds": reference_seconds,
            "trials": timings,
            "refinement_trials": refinement_timings,
        },
        "peak_resident_bytes": peak_resident_bytes(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", nargs="+", type=int, default=[42])
    parser.add_argument("--detail", nargs="+", type=int, default=[1, 6, 12])
    parser.add_argument("--roughness", nargs="+", type=float, default=[0.55])
    parser.add_argument("--span", nargs="+", type=float, default=[0.25, 2.0])
    parser.add_argument(
        "--direction", nargs="+", choices=DIRECTIONS, default=["horizontal", "oblique"]
    )
    parser.add_argument("--divisions", nargs="+", type=int, default=[1, 16, 256])
    parser.add_argument("--max-cells", type=int, default=MAX_CELLS)
    parser.add_argument("--max-slabs", type=int, default=MAX_SLABS)
    parser.add_argument("--adaptive-tolerance", nargs="+", type=float, default=[])
    parser.add_argument("--adaptive-max-samples", type=int, default=MAX_SAMPLES)
    parser.add_argument("--adaptive-max-depth", type=int, default=MAX_DEPTH)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        validate_controls(tuple(args.divisions), args.max_cells, args.repeats, args.max_slabs)
        for tolerance in args.adaptive_tolerance or (1.0,):
            RefinementControls(
                tolerance,
                max_cells=args.max_cells,
                max_slabs=args.max_slabs,
                max_samples=args.adaptive_max_samples,
                max_depth=args.adaptive_max_depth,
            )
        for seed in args.seed:
            for detail in args.detail:
                for roughness in args.roughness:
                    NoiseParameters(seed=seed, detail_levels=detail, roughness=roughness)
        if any(not np.isfinite(s) or not 0 < s <= 16 for s in args.span):
            raise ValueError(
                "Noise spans must be finite, positive and at most 16 largest features."
            )
    except ValueError as error:
        parser.error(str(error))
    if args.worker:
        result = probe(
            NoiseParameters(
                seed=args.seed[0], detail_levels=args.detail[0], roughness=args.roughness[0]
            ),
            args.span[0],
            args.direction[0],
            tuple(args.divisions),
            args.max_cells,
            args.max_slabs,
            adaptive_tolerances=tuple(args.adaptive_tolerance),
            adaptive_max_samples=args.adaptive_max_samples,
            adaptive_max_depth=args.adaptive_max_depth,
        )
        print(canonical_json(result).decode())
        return
    if args.output is None:
        parser.error("--output is required.")
    runtime, sources = runtime_identity(), source_identity()
    runs: list[dict[str, Any]] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        for seed in args.seed:
            for detail in args.detail:
                for roughness in args.roughness:
                    for span in args.span:
                        for direction in args.direction:
                            previous: dict[str, Any] | None = None
                            for _ in range(args.repeats):
                                command = [
                                    sys.executable,
                                    "-m",
                                    "benchmarks.noise_bounds",
                                    "--worker",
                                    "--seed",
                                    str(seed),
                                    "--detail",
                                    str(detail),
                                    "--roughness",
                                    str(roughness),
                                    "--span",
                                    str(span),
                                    "--direction",
                                    direction,
                                    "--max-cells",
                                    str(args.max_cells),
                                    "--max-slabs",
                                    str(args.max_slabs),
                                    "--adaptive-max-samples",
                                    str(args.adaptive_max_samples),
                                    "--adaptive-max-depth",
                                    str(args.adaptive_max_depth),
                                    "--divisions",
                                    *(str(n) for n in args.divisions),
                                ]
                                if args.adaptive_tolerance:
                                    command.extend(
                                        [
                                            "--adaptive-tolerance",
                                            *(str(t) for t in args.adaptive_tolerance),
                                        ]
                                    )
                                done = subprocess.run(
                                    command, cwd=ROOT, capture_output=True, text=True, check=True
                                )
                                run = json.loads(done.stdout)
                                if previous and any(
                                    run[key] != previous[key]
                                    for key in ("input_sha256", "evidence_sha256")
                                ):
                                    raise RuntimeError(
                                        "Identical noise inputs produced different bounds."
                                    )
                                previous = run
                                runs.append(run)
                            print(
                                f"seed={seed} detail={detail} roughness={roughness} "
                                f"span={span} {direction}: compared",
                                flush=True,
                            )
        if runtime != runtime_identity() or sources != source_identity():
            raise RuntimeError("Generator, runtime or bound source changed during inspection.")
        report = {
            "schema": "map-maker.noise-component-bounds",
            "schema_version": 3,
            "complete": True,
            "runtime": runtime,
            "comparison_source_sha256": sources,
            "method": {
                "method_id": METHOD_ID,
                "policies": COMPARISON_METHODS,
                "profile_method_id": PROFILE_METHOD_ID,
                "hybrid_method_id": HYBRID_METHOD_ID,
                "refinement_method_id": REFINEMENT_METHOD_ID,
                "refinement_budget_scope": "cumulative per trial, including superseded waves",
                "refinement_stop_rule": "local extrema and ordered-rise gaps <= tolerance",
                "slab_budget": args.max_slabs,
                "fresh_process_per_run": True,
                "changes_terrain": False,
                "complete_terrain_bound": False,
                "scope": "Float32(offset + amplitude * existing fractal value noise)",
                "reference": "65537 independent finite probes; not an inclusion proof",
                "rounding": "outward binary64 elementary operations and final binary32 conversion",
                "cell_budget": args.max_cells,
            },
            "runs": runs,
        }
        stream.write(canonical_json(report).decode())
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
