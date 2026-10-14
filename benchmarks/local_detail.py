"""Serial public-project evidence for verified parents and experimental local detail.

This runner records stage costs, not a before/after speedup. Generated parents,
children and comparisons stay beside the new result file under ignored artifacts.
"""

import argparse
import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from benchmarks import detail_metrics
from map_maker.terrain.adapters.build import file_sha256, runtime_identity
from map_maker.terrain.adapters.parent import load_terrain_parent
from map_maker.terrain.adapters.parent_region import (
    publish_parent_region_manifest,
    write_parent_region_products,
)
from map_maker.terrain.adapters.project import load_terrain_project, save_terrain_project
from map_maker.terrain.application.build import build_terrain_project
from map_maker.terrain.domain.regional import RegionalDetailSettings, RegionalSamplingRequest
from map_maker.terrain.pipeline.detail import LOCAL_DETAIL_ALGORITHM_ID, prepare_regional_detail
from map_maker.terrain.pipeline.parent import prepare_verified_parent

PROJECTS = {
    "example": "example.terrain.json",
    "regional": "landform-regions.terrain.json",
    "water": "basin-water.terrain.json",
}
ROOT = Path(__file__).parents[1]


def _measure(
    case: str, seed: int, destination: Path, runtime: dict[str, object]
) -> dict[str, object]:
    destination.mkdir()
    loaded_project = load_terrain_project(ROOT / "examples/terrain" / PROJECTS[case])
    project = replace(
        loaded_project.project,
        settings=replace(
            loaded_project.project.settings, seed=seed, resolution_px=65, detail_levels=2
        ),
    )
    path = destination / "project.terrain.json"
    save_terrain_project(project, loaded_project.coastline_source, path)
    start = perf_counter()
    parent_directory = destination / "parent"
    build_terrain_project(path, parent_directory)
    build_seconds = perf_counter() - start
    start = perf_counter()
    loaded = load_terrain_parent(parent_directory, runtime)
    load_seconds = perf_counter() - start
    start = perf_counter()
    parent = prepare_verified_parent(loaded.data)
    replay_seconds = perf_counter() - start
    settings = RegionalDetailSettings(40.0)
    start = perf_counter()
    field = prepare_regional_detail(parent, settings)
    protection_seconds = perf_counter() - start
    grid = parent.data.grid
    # Fixed geographic window, not chosen to maximize successful detail.
    left, top = int(0.35 * (grid.width - 1)), int(0.35 * (grid.height - 1))
    bounds = (
        float(parent.data.x_km[left]),
        float(parent.data.y_km[top]),
        float(parent.data.x_km[left + 8]),
        float(parent.data.y_km[top + 8]),
    )
    runs: list[dict[str, Any]] = []
    previous = None
    first = None
    for factor in (8, 16, 32):
        request = RegionalSamplingRequest(
            parent.data.build_id,
            grid,
            factor,
            (left * factor, top * factor, (left + 8) * factor, (top + 8) * factor),
            halo_cells=0,
        )
        start = perf_counter()
        detail = field.sample(request)
        generation_seconds = perf_counter() - start
        if first is None:
            first = detail
        common_equal = previous is None or np.array_equal(
            previous.samples.elevation_m, detail.samples.elevation_m[::2, ::2], equal_nan=True
        )
        if not common_equal:
            raise RuntimeError("Common coordinates changed across detail densities.")
        reference = parent.data.elevation_m[top : top + 9, left : left + 9]
        nodes_equal = np.array_equal(
            detail.samples.elevation_m[::factor, ::factor], reference, equal_nan=True
        )
        water_equal = np.array_equal(
            detail.samples.water_surface_m,
            parent.sampler.sample(request).water_surface_m,
            equal_nan=True,
        )
        if not nodes_equal or not water_equal:
            raise RuntimeError("Parent nodes or sampled water changed during detail generation.")
        result_directory = destination / f"detail-{factor}"
        result_directory.mkdir()
        start = perf_counter()
        outputs = write_parent_region_products(detail.samples, parent, result_directory, detail)
        loaded.verify_unchanged()
        if runtime_identity() != runtime:
            raise RuntimeError("Runtime changed during the experiment.")
        publish_parent_region_manifest(
            detail.samples,
            loaded,
            parent,
            result_directory,
            bounds_km=bounds,
            runtime=runtime,
            outputs=outputs,
            detail_settings=settings,
            detail=detail,
        )
        publication_seconds = perf_counter() - start
        runs.append(
            {
                "refinement": factor,
                "shape": detail.samples.elevation_m.shape,
                "generation_seconds": generation_seconds,
                "publication_seconds": publication_seconds,
                "evidence": asdict(detail.evidence),
                "spatial_metrics": detail_metrics.measure_detail(detail),
                "common_samples_exact": common_equal,
                "parent_nodes_exact": nodes_equal,
                "water_samples_exact": water_equal,
                "basin_samples": int(np.count_nonzero(detail.samples.basin_intent_ids)),
                "elevation_sha256": sha256(detail.samples.elevation_m.tobytes()).hexdigest(),
                "artifact_manifest_sha256": file_sha256(result_directory / "manifest.json"),
            }
        )
        previous = detail
    assert first is not None
    request = RegionalSamplingRequest(
        parent.data.build_id,
        grid,
        8,
        ((left + 2) * 8, (top + 1) * 8, (left + 10) * 8, (top + 9) * 8),
        halo_cells=1,
    )
    overlap = field.sample(request)
    _x, a, b = np.intersect1d(first.samples.x_km, overlap.samples.x_km, return_indices=True)
    _y, c, d = np.intersect1d(first.samples.y_km, overlap.samples.y_km, return_indices=True)
    overlap_equal = np.array_equal(
        first.samples.elevation_m[np.ix_(c, a)],
        overlap.samples.elevation_m[np.ix_(d, b)],
        equal_nan=True,
    )
    repeated = field.sample(first.samples.request)
    repeat_equal = np.array_equal(
        first.samples.elevation_m, repeated.samples.elevation_m, equal_nan=True
    )
    if not overlap_equal or not repeat_equal:
        raise RuntimeError("Overlap or repeat-visit samples changed.")
    loaded.verify_unchanged()
    return {
        "case": case,
        "seed": seed,
        "parent_build_id": parent.data.build_id,
        "project_sha256": file_sha256(path),
        "bounds_km": bounds,
        "build_seconds": build_seconds,
        "load_seconds": load_seconds,
        "replay_seconds": replay_seconds,
        "protection_seconds": protection_seconds,
        "verified_ground_nodes": parent.verified_ground_nodes,
        "verified_routing_nodes": parent.verified_routing_nodes,
        "overlap_exact": overlap_equal,
        "repeat_exact": repeat_equal,
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs="+", choices=list(PROJECTS), default=list(PROJECTS))
    parser.add_argument("--seed", type=int, nargs="+", default=[42, 7])
    parser.add_argument("--output", type=Path, required=True, help="New JSON results file.")
    args = parser.parse_args()
    output: Path = args.output
    products = output.with_suffix("")
    if output.exists() or products.exists():
        parser.error("Result file and corresponding products directory must both be new.")
    runtime = runtime_identity()
    runner_hash = file_sha256(Path(__file__))
    metrics_hash = file_sha256(Path(detail_metrics.__file__))
    products.mkdir(parents=True)
    cases: list[dict[str, object]] = []
    for case in args.case:
        for seed in args.seed:
            result = _measure(case, seed, products / f"{case}-{seed}", runtime)
            cases.append(result)
            print(f"{case}, seed {seed}: verified parent and three detail densities", flush=True)
    if (runtime_identity() != runtime or file_sha256(Path(__file__)) != runner_hash
            or file_sha256(Path(detail_metrics.__file__)) != metrics_hash):
        raise RuntimeError("Runtime or benchmark source changed; no result published.")
    document = {
        "algorithm": LOCAL_DETAIL_ALGORITHM_ID,
        "runtime": runtime,
        "benchmark_sha256": runner_hash,
        "metrics_sha256": metrics_hash,
        "cases": cases,
        "limits": [
            "Serial stage observations, not fresh-process speedup evidence.",
            "Experimental field and fixed moments, not accepted local hydrology.",
        ],
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
