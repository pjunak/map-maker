"""Measure fixed noise-band budgets and remaining whole-terrain restriction drift."""

import argparse
from dataclasses import asdict, replace
from hashlib import sha256
from math import fsum
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks import terrain as fixtures
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.pipeline.generate import (
    GENERATOR_ALGORITHM_ID,
    NOISE_ALGORITHM_ID,
    generate_terrain,
)
from map_maker.terrain.pipeline.noise import noise_band_amplitudes


def _cell_means(values: NDArray[np.float64], land: NDArray[np.bool_]) -> NDArray[np.float64]:
    """Trapezoidal averages over 16x16 central cells, each with 8x8 fine intervals."""
    row, column = (np.asarray(values.shape) - 129) // 2
    z = values[row:row + 129, column:column + 129]
    mask = land[row:row + 129, column:column + 129]
    quads = .25 * (z[:-1, :-1] + z[1:, :-1] + z[:-1, 1:] + z[1:, 1:])
    valid = mask[:-1, :-1] & mask[1:, :-1] & mask[:-1, 1:] & mask[1:, 1:]
    means = quads.reshape(16, 8, 16, 8).mean(axis=(1, 3))
    return np.where(valid.reshape(16, 8, 16, 8).all(axis=(1, 3)), means, np.nan)


def probe(case: str, seed: int) -> dict[str, Any]:
    coast, settings, constraints = fixtures.fixture(case, 257, seed)
    input_hash = sha256(canonical_json({
        "coastline": asdict(coast), "settings": asdict(settings),
        "constraints": [asdict(item) for item in constraints],
    })).hexdigest()
    baseline = generate_terrain(coast, replace(settings, detail_levels=2), constraints=constraints)
    mask = baseline.land_mask
    base = baseline.elevation_m.astype(np.float64)
    base_means = _cell_means(base, mask)
    results: list[dict[str, Any]] = []
    for count in (2, 6, 12):
        result = (baseline if count == 2 else generate_terrain(
            coast, replace(settings, detail_levels=count), constraints=constraints))
        np.testing.assert_array_equal(mask, result.land_mask)
        delta = result.elevation_m.astype(np.float64) - base
        restricted_delta = _cell_means(delta, mask)
        assert np.isfinite(restricted_delta).any()
        amplitudes = noise_band_amplitudes(count, settings.roughness)
        assert amplitudes[:2] == noise_band_amplitudes(2, settings.roughness)
        results.append({
            "detail_levels": count, "amplitudes": amplitudes,
            "resolved_amplitude_budget": fsum(amplitudes),
            "elevation_sha256": sha256(result.elevation_m.tobytes()).hexdigest(),
            "pointwise_rms_change_m": float(np.sqrt(np.mean(delta[mask] ** 2))),
            "pointwise_maximum_change_m": float(np.max(np.abs(delta[mask]))),
            "cell_mean_rms_change_m": float(np.sqrt(np.nanmean(restricted_delta ** 2))),
            "cell_mean_maximum_change_m": float(np.nanmax(np.abs(restricted_delta))),
            "changed_canonical_receivers": int(np.count_nonzero(
                result.routing.receivers != baseline.routing.receivers)),
        })
    return {"case": case, "seed": seed, "roughness": settings.roughness,
            "input_sha256": input_hash,
            "reference_detail_levels": 2, "reference_shape": base.shape,
            "x_spacing_km": baseline.grid.x_spacing_km,
            "y_spacing_km": baseline.grid.y_spacing_km,
            "interior_cell_count": int(np.count_nonzero(np.isfinite(base_means))),
            "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=fixtures.CASES, nargs="+",
                        default=["example", "regional", "authored", "water"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runtime = runtime_identity()
    source = file_sha256(Path(__file__))
    fixture_source = file_sha256(Path(fixtures.__file__))
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        cases: list[dict[str, Any]] = []
        for case in args.case:
            record = probe(case, args.seed)
            cases.append(record)
            print(canonical_json(record).decode(), end="", flush=True)
        if (runtime != runtime_identity() or source != file_sha256(Path(__file__))
                or fixture_source != file_sha256(Path(fixtures.__file__))):
            raise RuntimeError("Source/runtime changed during detail-band experiment")
        stream.write(canonical_json({
            "schema": "map-maker.detail-band-experiment", "schema_version": 1,
            "complete": True, "generator": GENERATOR_ALGORITHM_ID, "noise": NOISE_ALGORITHM_ID,
            "runtime": runtime, "benchmark_source_sha256": source,
            "fixture_source_sha256": fixture_source,
            "restriction": "central 16x16 cells; trapezoidal 8x8 fine-interval averages; land only",
            "parent_conditioning_implemented": False, "cases": cases,
        }).decode())


if __name__ == "__main__":
    main()
