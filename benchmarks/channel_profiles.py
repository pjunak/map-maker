# pyright: reportPrivateUsage=false
"""Finite channel-interior measurements; not a continuous drainage certificate."""

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks import terrain as terrain_benchmark
from benchmarks.terrain import CASES, fixture
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.pipeline import generate as generation

type FloatArray = NDArray[np.float64]
type GroundSampler = Callable[[FloatArray, FloatArray], NDArray[np.float32]]


def measure_channels(
    x: FloatArray,
    y: FloatArray,
    receivers: NDArray[np.int64],
    channels: NDArray[np.bool_],
    sample_ground: GroundSampler,
    *,
    stations: int = 65,
    batch_edges: int = 256,
) -> dict[str, Any]:
    """Sample every selected edge with bounded temporary point-array allocation."""
    if not 3 <= stations <= 1025 or not 1 <= batch_edges <= 1024:
        raise ValueError("Use 3-1025 stations and batches of 1-1024 edges.")
    if receivers.shape != channels.shape or channels.shape != (len(y), len(x)):
        raise ValueError("Routing arrays must share the axis grid.")
    sources = np.flatnonzero(channels.ravel() & (receivers.ravel() >= 0))
    targets = receivers.ravel()[sources]
    if np.any(targets >= receivers.size):
        raise ValueError("A selected receiver is outside the grid.")
    source_row, source_column = np.divmod(sources, len(x))
    target_row, target_column = np.divmod(targets, len(x))
    diagonal = (source_row != target_row) & (source_column != target_column)
    finite = np.zeros(sources.size, dtype=np.bool_)
    descending = np.zeros_like(finite)
    excursion = np.zeros(sources.size, dtype=np.float64)
    fractions = np.linspace(0., 1., stations)[None, :]
    profile_hash = sha256()
    for start in range(0, sources.size, batch_edges):
        part = slice(start, start + batch_edges)
        qx = (x[source_column[part], None]*(1-fractions)
              + x[target_column[part], None]*fractions)
        qy = (y[source_row[part], None]*(1-fractions)
              + y[target_row[part], None]*fractions)
        ground = sample_ground(qx, qy)
        if ground.shape != qx.shape:
            raise ValueError("Ground sampler returned the wrong shape.")
        # Promote delivered Float32 heights before subtraction, like water review.
        heights = ground.astype(np.float64)
        profile_hash.update(ground.astype('<f4').tobytes())
        valid = np.all(np.isfinite(heights), axis=1)
        finite[part] = valid
        descending[part] = valid & (heights[:, 0] > heights[:, -1] + .01)
        excursion[part] = np.where(
            valid, np.max(heights - np.minimum.accumulate(heights, axis=1), axis=1), 0.,
        )

    def summary(mask: NDArray[np.bool_]) -> dict[str, Any]:
        values = excursion[mask]
        return {
            "edge_count": int(np.count_nonzero(mask)),
            "uphill_edge_count": int(np.count_nonzero(values > .01)),
            "excursion_threshold_counts": {
                str(threshold): int(np.count_nonzero(values > threshold))
                for threshold in (1, 10, 50, 100)
            },
            "mean_excursion_m": float(values.mean()) if values.size else None,
            "p95_excursion_m": float(np.quantile(values, .95)) if values.size else None,
            "maximum_excursion_m": float(values.max()) if values.size else None,
        }

    order = sorted(np.flatnonzero(descending), key=lambda i: (-excursion[i], sources[i]))[:10]
    return {
        "station_count_per_edge": stations,
        "maximum_batch_edges": batch_edges,
        "requested_sample_count": int(sources.size * stations),
        "selected_edge_count": int(sources.size),
        "nonfinite_profile_count": int(np.count_nonzero(~finite)),
        "excursion_tolerance_m": .01,
        "profile_sha256": profile_hash.hexdigest(),
        "all_finite": summary(finite),
        "descending": summary(descending),
        "diagonal_descending": summary(descending & diagonal),
        "cardinal_descending": summary(descending & ~diagonal),
        "worst_descending_edges": [
            {"source_flat_index": int(sources[i]), "receiver_flat_index": int(targets[i]),
             "maximum_excursion_m": float(excursion[i])} for i in order
        ],
    }


def probe(case: str, seed: int, stations: int) -> dict[str, Any]:
    coast, settings, constraints = fixture(case, 257, seed)
    input_hash = sha256(canonical_json({
        "coastline": asdict(coast), "settings": asdict(settings),
        "constraints": [asdict(item) for item in constraints],
    })).hexdigest()
    field = generation.prepare_terrain_field(coast, settings, constraints, None)
    valley = field.automatic_valleys
    routing = valley.drainage
    return {
        "case": case, "seed": seed, "input_sha256": input_hash,
        "generator": generation.GENERATOR_ALGORITHM_ID,
        "automatic_valleys": generation.AUTOMATIC_VALLEY_ALGORITHM_ID,
        "canonical_sha256": {
            name: sha256(array.tobytes()).hexdigest() for name, array in (
                ("receivers", routing.receivers), ("channels", routing.channel_mask),
                ("incision", routing.incision_m), ("limits", routing.incision_limit_m),
                ("suppression", routing.detail_suppression), ("x", valley.x_km), ("y", valley.y_km),
            )
        },
        "profiles": measure_channels(valley.x_km, valley.y_km, routing.receivers,
                                     routing.channel_mask, field.sample_ground, stations=stations),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, nargs="+",
                        default=["example", "regional", "authored", "outlet"])
    parser.add_argument("--seed", type=int, nargs="+", default=[42, 20260902])
    parser.add_argument("--stations", type=int, default=65)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 3 <= args.stations <= 1025:
        parser.error("--stations must be between 3 and 1025")
    runtime = runtime_identity()
    harness_hash = file_sha256(Path(__file__))
    fixture_hash = file_sha256(Path(terrain_benchmark.__file__))
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        results: list[dict[str, Any]] = []
        for case in args.case:
            for seed in args.seed:
                result = probe(case, seed, args.stations)
                results.append(result)
                print(json.dumps({"case": case, "seed": seed,
                                  "descending": result["profiles"]["descending"]}), flush=True)
        if (runtime != runtime_identity() or harness_hash != file_sha256(Path(__file__))
                or fixture_hash != file_sha256(Path(terrain_benchmark.__file__))):
            raise RuntimeError("Source/runtime changed during channel-profile measurement")
        stream.write(canonical_json({
            "schema": "map-maker.channel-profile-experiment", "schema_version": 2,
            "complete": True, "continuous_clearance_certified": False,
            "runtime": runtime, "benchmark_source_sha256": harness_hash,
            "fixture_source_sha256": fixture_hash, "cases": results,
        }).decode())


if __name__ == "__main__":
    main()
