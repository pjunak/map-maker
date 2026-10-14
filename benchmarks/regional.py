"""Measure bounded unchanged-field windows against complete finer sampling."""

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

import numpy as np

from benchmarks import terrain as fixtures
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.domain.regional import RegionalSamplingRequest
from map_maker.terrain.pipeline.regional import (
    REGIONAL_SAMPLING_ALGORITHM_ID,
    RegionalTerrainSamples,
    prepare_regional_sampler,
)

ARRAYS = ("elevation_m", "land_mask", "water_surface_m", "basin_intent_ids", "x_km", "y_km")


def _digest(samples: RegionalTerrainSamples) -> str:
    result = sha256()
    for name in ARRAYS:
        result.update(getattr(samples, name).tobytes())
    return result.hexdigest()


def probe(case: str, seed: int, repeats: int) -> dict[str, Any]:
    coastline, settings, constraints = fixtures.fixture(case, 65, seed)
    started = perf_counter()
    sampler = prepare_regional_sampler(coastline, settings, constraints=constraints)
    preparation = perf_counter() - started
    grid = sampler.reference_grid
    left, top = (grid.width - 17) // 2, (grid.height - 17) // 2
    levels: list[dict[str, Any]] = []
    results: list[RegionalTerrainSamples] = []
    for factor in (4, 8, 16):
        request = RegionalSamplingRequest(sampler.source_id, grid, factor,
                                          (left * factor, top * factor,
                                           (left + 16) * factor, (top + 16) * factor))
        timings: list[float] = []
        result = None
        for _ in range(repeats):
            started = perf_counter()
            result = sampler.sample(request)
            timings.append(perf_counter() - started)
        assert result is not None
        results.append(result)
        levels.append({"refinement": factor, "core_grid": asdict(request.grid()),
                       "buffered_sample_count": result.elevation_m.size,
                       "seconds": timings, "median_seconds": median(timings),
                       "numeric_sha256": _digest(result)})
    # Revisit coarse windows after finer work; comparison includes water and halo.
    for result in reversed(results):
        assert _digest(sampler.sample(result.request)) == _digest(result)
    for coarse, fine in pairwise(results):
        for name in ARRAYS[:4]:
            coarse_core = getattr(coarse, name)[coarse.request.core_slices]
            fine_core = getattr(fine, name)[fine.request.core_slices]
            np.testing.assert_array_equal(coarse_core, fine_core[::2, ::2])
    full_request = RegionalSamplingRequest(sampler.source_id, grid, 16,
                                           (0, 0, (grid.width - 1) * 16, (grid.height - 1) * 16))
    started = perf_counter()
    full = sampler.sample(full_request)
    full_seconds = perf_counter() - started
    fine = results[-1]
    x0, y0, x1, y1 = fine.request.sample_window
    for name in ARRAYS[:4]:
        np.testing.assert_array_equal(
            getattr(fine, name), getattr(full, name)[y0:y1 + 1, x0:x1 + 1])
    return {"case": case, "seed": seed, "source_id": sampler.source_id,
            "preparation_seconds": preparation, "levels": levels,
            "full_fine_grid": asdict(full_request.grid()), "full_seconds": full_seconds,
            "full_sample_count": full.elevation_m.size, "full_numeric_sha256": _digest(full),
            "nested_repeat_and_full_comparisons": "exact", "adds_detail": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs="+", choices=fixtures.CASES,
                        default=["regional", "authored", "water", "archipelago"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be between 1 and 20")
    runtime = runtime_identity()
    harness = file_sha256(Path(__file__))
    fixture_hash = file_sha256(Path(fixtures.__file__))
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        results: list[dict[str, Any]] = []
        for case in args.case:
            result = probe(case, args.seed, args.repeats)
            results.append(result)
            print(json.dumps(result), flush=True)
        if (runtime != runtime_identity() or harness != file_sha256(Path(__file__))
                or fixture_hash != file_sha256(Path(fixtures.__file__))):
            raise RuntimeError("Source/runtime changed during regional measurement")
        stream.write(canonical_json({"schema": "map-maker.regional-sampling-experiment",
                                     "schema_version": 1, "complete": True, "runtime": runtime,
                                     "algorithm": REGIONAL_SAMPLING_ALGORITHM_ID,
                                     "harness_sha256": harness, "fixture_sha256": fixture_hash,
                                     "cases": results}).decode())


if __name__ == "__main__":
    main()
