"""Measure source water-piece graph cost in a fresh process per resolution."""

import argparse
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import numpy as np

from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.application.world import open_world
from map_maker.terrain.domain.world_context import SphericalContextGrid, WorldContextSettings
from map_maker.terrain.pipeline.world_context import source_water_connectivity

DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "examples/world/four-shores.world.json"


def measure(source: Path, rows: int) -> dict[str, object]:
    runtime = runtime_identity()
    source_hash = file_sha256(source)
    start = perf_counter()
    world = open_world(source)
    prepared_seconds = perf_counter() - start
    grid = SphericalContextGrid(world.project.frame, WorldContextSettings(rows))
    repeats: list[dict[str, object]] = []
    identity = None
    for _ in range(2):
        start = perf_counter()
        graph = source_water_connectivity(world, grid, checkpoint=lambda: None)
        elapsed = perf_counter() - start
        digest = sha256()
        for name, value in graph.arrays().items():
            digest.update(name.encode())
            digest.update(value.astype(value.dtype.newbyteorder("<"), copy=False).tobytes())
        fingerprint = digest.hexdigest()
        if identity is not None and identity != fingerprint:
            raise RuntimeError("Repeated graph changed numeric arrays.")
        identity = fingerprint
        cell_area = np.array([grid.cell_area_km2(r) for r in range(rows)])
        by_cell = np.bincount(
            np.repeat(np.arange(rows * rows * 2), np.diff(graph.cell_offsets)),
            weights=graph.area_km2,
            minlength=rows * rows * 2,
        ).reshape(grid.shape)
        excess = float(np.maximum(by_cell - cell_area[:, None], 0).max(initial=0))
        error = float(graph.area_km2.sum() + world.land_area_km2 - grid.frame.surface_area_km2)
        if abs(error) > max(grid.frame.surface_area_km2 * 1e-9, 1e-8) or excess > 1e-6:
            raise RuntimeError("Graph failed sphere or cell-area bounds.")
        repeats.append(
            {
                "seconds": elapsed,
                "process_peak_bytes": peak_resident_bytes(),
                "pieces": len(graph.water_body),
                "links": len(graph.link_nodes),
                "components": graph.component_count,
                "fragmented_bodies": graph.fragmented_bodies,
                "split_cells": graph.split_cells,
                "array_bytes": sum(a.nbytes for a in graph.arrays().values())
                + graph.component.nbytes
                + graph.incident_links.nbytes,
                "sphere_area_error_km2": error,
                "cell_water_excess_km2": excess,
                "arrays_sha256": fingerprint,
            }
        )
        del graph
    if runtime != runtime_identity() or source_hash != file_sha256(source):
        raise RuntimeError("Inputs or runtime changed during graph measurement.")
    return {
        "runtime": runtime,
        "source_sha256": source_hash,
        "latitude_cells": rows,
        "source_preparation_seconds": prepared_seconds,
        "repeats": repeats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--rows", type=int, nargs="+", default=[90, 180, 360])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    for count in args.rows:
        WorldContextSettings(count)
    if args.worker:
        print(json.dumps(measure(args.source, args.rows[0])))
        return 0
    if args.output.exists() or args.output.is_symlink():
        parser.error("Choose a new results file.")
    runtime = runtime_identity()
    runner_hash = file_sha256(Path(__file__))
    rows: list[dict[str, object]] = []
    for resolution in args.rows:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.world_connectivity",
                "--worker",
                "--source",
                str(args.source),
                "--rows",
                str(resolution),
                "--output",
                str(args.output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        record = json.loads(completed.stdout)
        if record["runtime"] != runtime:
            raise RuntimeError("Worker runtime differs from controller.")
        rows.append(record)
        print(f"{resolution} rows: repeated graph identity matched", flush=True)
    if runtime_identity() != runtime or file_sha256(Path(__file__)) != runner_hash:
        raise RuntimeError("Runtime changed; no report published.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(
            canonical_json(
                {
                    "runs": rows,
                    "benchmark_sha256": runner_hash,
                    "limits": [
                        "Fresh process per resolution; two serial graph constructions.",
                        "Graph timings include vector union/topology; exclude source preparation, "
                        "shore distance, exposure, rendering, hashing and serialization.",
                        "Process peak includes imports, source geometry and allocator retention; "
                        "it is not graph-only memory or a worst-case guarantee.",
                    ],
                }
            )
        )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
