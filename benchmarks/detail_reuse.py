"""Compare uncached, bounded and eviction-pressure detail on completed public parents.

Preparation/replay, hashing and export are outside the timed sampling sequence.
Variants alternate order within one process; these are local stage observations.
"""

import argparse
from dataclasses import asdict, fields, replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.adapters.parent import load_terrain_parent
from map_maker.terrain.domain.regional import RegionalDetailSettings, RegionalSamplingRequest
from map_maker.terrain.pipeline.detail import (
    LOCAL_DETAIL_ALGORITHM_ID,
    DetailedRegion,
    prepare_regional_detail,
)
from map_maker.terrain.pipeline.parent import VerifiedTerrainParent, prepare_verified_parent


def result_identity(detail: DetailedRegion) -> str:
    """Hash every numeric array plus complete request metadata and deterministic evidence."""
    document: dict[str, object] = {}
    for prefix, value in (("detail", detail), ("samples", detail.samples)):
        for item in fields(value):
            member = getattr(value, item.name)
            if isinstance(member, np.ndarray):
                array = cast(NDArray[Any], member)
                document[f"{prefix}.{item.name}"] = {
                    "dtype": array.dtype.str, "shape": array.shape,
                    "sha256": sha256(array.tobytes()).hexdigest(),
                }
    document.update(
        evidence=asdict(detail.evidence), request=asdict(detail.samples.request),
        canonical_grid=asdict(detail.samples.canonical_grid),
        maximum_elevation_m=detail.samples.maximum_elevation_m,
    )
    return sha256(canonical_json(document)).hexdigest()


def requests(parent: VerifiedTerrainParent) -> list[tuple[str, RegionalSamplingRequest]]:
    grid = parent.data.grid
    if min(grid.width, grid.height) < 33:
        raise ValueError("The reuse workload requires at least 33 parent nodes on each axis.")
    left, top = int(0.35 * (grid.width - 1)), int(0.35 * (grid.height - 1))
    away = left + 12 if left + 20 < grid.width else left - 12
    return [
        (label, RegionalSamplingRequest(
            parent.data.build_id, grid, factor,
            (x * factor, y * factor, (x + 8) * factor, (y + 8) * factor), halo_cells=1,
        ))
        for label, x, y, factor in (
            ("cold", left, top, 8), ("zoom", left, top, 16),
            ("overlap", left + 1, top + 1, 8), ("repeat", left, top, 8),
            ("away", away, top, 8), ("revisit", left, top, 8),
        )
    ]


def measure(source: Path, repeats: int, runtime: dict[str, object]) -> dict[str, object]:
    loaded = load_terrain_parent(source, runtime)
    parent = prepare_verified_parent(loaded.data)
    prepared = prepare_regional_detail(parent, RegionalDetailSettings(40.0))
    sequence = requests(parent)
    expected: dict[str, str] = {}
    runs: list[dict[str, object]] = []
    for repeat in range(repeats):
        capacities = (0, 128, 4096) if repeat % 2 == 0 else (4096, 128, 0)
        for capacity in capacities:
            context = replace(prepared, cache_cells=capacity)
            steps: list[dict[str, object]] = []
            for label, request in sequence:
                before = context.cache_info()
                start = perf_counter()
                result = context.sample(request)
                elapsed = perf_counter() - start
                identity = result_identity(result)
                if identity != expected.setdefault(label, identity):
                    raise RuntimeError(f"Cache history changed numeric results/evidence: {label}")
                after = context.cache_info()
                if after.cells > capacity:
                    raise RuntimeError("Cell cache exceeded its budget.")
                steps.append({
                    "label": label, "seconds": elapsed, "identity": identity,
                    "evidence": asdict(result.evidence), "cache": asdict(after),
                    "new_hits": after.hits - before.hits,
                    "new_misses": after.misses - before.misses,
                    "new_evictions": after.evictions - before.evictions,
                })
            runs.append({"repeat": repeat, "capacity": capacity, "steps": steps})
    loaded.verify_unchanged()
    return {"parent_build_id": parent.data.build_id, "parent": str(source), "runs": runs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, nargs="+", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output: Path = args.output
    if output.exists() or output.is_symlink() or args.repeats < 1:
        parser.error("Use a new output file and at least one repeat.")
    if any(output.resolve().is_relative_to(p.resolve()) for p in args.parent):
        parser.error("The benchmark output must be outside every parent build.")
    runtime = runtime_identity()
    runner_hash = file_sha256(Path(__file__))
    cases: list[dict[str, object]] = []
    for source in args.parent:
        cases.append(measure(source, args.repeats, runtime))
        print(f"{source}: all reuse and eviction results match", flush=True)
    if runtime_identity() != runtime or file_sha256(Path(__file__)) != runner_hash:
        raise RuntimeError("Runtime or benchmark source changed; no report published.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(canonical_json({
            "algorithm": LOCAL_DETAIL_ALGORITHM_ID, "runtime": runtime,
            "benchmark_sha256": runner_hash, "cases": cases,
            "limits": [
                "Alternating serial sampling in one process; no full-build speed claim.",
                "Only scalar cell support is cached; prepared parents and output arrays excluded.",
            ],
        }))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
