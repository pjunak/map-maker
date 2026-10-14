"""Compare complete regional artifact writes with independent calls and reusable sessions."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.adapters.parent import load_terrain_parent
from map_maker.terrain.application.parent_region import ParentRegionSession, sample_parent_region
from map_maker.terrain.application.region_cache import DEFAULT_RESULT_CACHE_BYTES
from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.domain.coordinates import Bounds
from map_maker.terrain.domain.regional import RegionalDetailSettings


def workload(grid: EndpointGrid) -> list[tuple[str, Bounds, int]]:
    if min(grid.width, grid.height) < 33:
        raise ValueError("The session workload requires at least 33 parent nodes on each axis.")
    left, top = int(.35 * (grid.width - 1)), int(.35 * (grid.height - 1))
    away = left + 12 if left + 20 < grid.width else left - 12
    dx, dy = grid.x_spacing_km, grid.y_spacing_km
    return [
        (label, (x * dx, y * dy, (x + 8) * dx, (y + 8) * dy), factor)
        for label, x, y, factor in (
            ("cold", left, top, 8), ("zoom", left, top, 16),
            ("overlap", left + 1, top + 1, 8), ("repeat", left, top, 8),
            ("away", away, top, 8), ("revisit", left, top, 8),
        )
    ]


def artifact_identity(manifest: Path) -> str:
    document: dict[str, Any] = json.loads(manifest.read_bytes())
    for name, record in document["outputs"].items():
        if file_sha256(manifest.parent / name) != record["sha256"]:
            raise RuntimeError(f"Regional artifact failed hash verification: {name}")
    return file_sha256(manifest)


def measure(
    source: Path, destination: Path, repeats: int, runtime: dict[str, object],
) -> dict[str, object]:
    loaded = load_terrain_parent(source, runtime)
    sequence = workload(loaded.data.grid)
    parent_id = loaded.data.build_id
    del loaded
    expected: dict[str, str] = {}
    runs: list[dict[str, object]] = []
    settings = RegionalDetailSettings(40.)
    for repeat in range(repeats):
        variants = ["independent", "prepared-only", "prepared-and-results"]
        if repeat % 2:
            variants.reverse()
        for variant in variants:
            start = perf_counter()
            session = None if variant == "independent" else ParentRegionSession(
                source, result_cache_bytes=(
                    0 if variant == "prepared-only" else DEFAULT_RESULT_CACHE_BYTES
                ),
            )
            setup_seconds = perf_counter() - start
            steps: list[dict[str, object]] = []
            try:
                for label, bounds, factor in sequence:
                    target = destination / f"{repeat}-{variant}-{label}"
                    start = perf_counter()
                    manifest = (
                        sample_parent_region(
                            source, target, bounds, factor, detail_settings=settings
                        )
                        if session is None else
                        session.write(target, bounds, factor, detail_settings=settings)
                    )
                    seconds = perf_counter() - start
                    identity = artifact_identity(manifest)
                    if identity != expected.setdefault(label, identity):
                        raise RuntimeError(
                            f"Session state changed published artifact bytes: {label}"
                        )
                    steps.append({
                        "label": label, "seconds": seconds, "manifest_sha256": identity,
                        "cache": asdict(session.cache_info()) if session is not None else None,
                    })
            finally:
                start = perf_counter()
                if session is not None:
                    session.close()
                close_seconds = perf_counter() - start
            runs.append({
                "repeat": repeat, "variant": variant, "setup_seconds": setup_seconds,
                "close_seconds": close_seconds, "steps": steps,
                "released_bytes": session.cache_info().retained_bytes if session else 0,
            })
            print(f"{source.parent.name}, repeat {repeat + 1}: {variant} matched", flush=True)
    return {"parent_build_id": parent_id, "source": str(source), "runs": runs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, nargs="+", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output: Path = args.output
    products = output.with_suffix("")
    if output.exists() or output.is_symlink() or products.exists() or args.repeats < 1:
        parser.error("Choose a new result file/products directory and at least one repeat.")
    if any(
        path.resolve().is_relative_to(parent.resolve())
        for path in (output, products) for parent in args.parent
    ):
        parser.error("Benchmark results must remain outside every parent build.")
    runtime = runtime_identity()
    runner_hash = file_sha256(Path(__file__))
    products.mkdir(parents=True)
    cases = [
        measure(parent, products / str(index), args.repeats, runtime)
        for index, parent in enumerate(args.parent)
    ]
    if runtime_identity() != runtime or file_sha256(Path(__file__)) != runner_hash:
        raise RuntimeError("Runtime or benchmark source changed; no report published.")
    with output.open("xb") as stream:
        stream.write(canonical_json({
            "runtime": runtime, "benchmark_sha256": runner_hash, "cases": cases,
            "limits": [
                "Alternating serial variants in one process, not fresh-process measurements.",
                "Times include session setup/close, verification, generation and artifact export.",
                "Cache bytes count retained numeric allocations, not total process memory.",
            ],
        }))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
