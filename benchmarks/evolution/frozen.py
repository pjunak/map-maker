"""Verify completed history artifacts before reconstructing their frozen graph.

The first experiment saved Float64-snapshot routing, not delivery-rerouted links.
That distinction is recorded explicitly: both new samplers use the saved graph
and the same Float32 nodes, without rerunning or importing the scientific engine.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.evidence import numeric_hash
from benchmarks.evolution.surface import validate_graph
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid

GRAPH_ROLE = "saved final Float64-snapshot receivers; not Float32-rerouted delivery receivers"
CHANNEL_AREA_M2 = 25_000_000.0


@dataclass(frozen=True, slots=True)
class FrozenCase:
    result_path: Path
    record: dict[str, Any]
    grid: EvolutionGrid
    ground_m: NDArray[np.float64]
    receivers: NDArray[np.int64]
    required: NDArray[np.bool_]
    hashes: dict[str, str]

    def verify_unchanged(self) -> None:
        for name, expected in self.hashes.items():
            if file_sha256(self.result_path.parent / name) != expected:
                raise ValueError(f"Frozen input changed during comparison: {name}")


def load_case(path: Path) -> FrozenCase:
    path = path.resolve(strict=True)
    state_path = path.parent / "states.npz"
    hashes = {path.name: file_sha256(path), "states.npz": file_sha256(state_path)}
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if record.get("status") != "complete":
        raise ValueError("Only completed evolution cases can be compared.")
    if record["artifacts"]["states.npz"] != hashes["states.npz"]:
        raise ValueError("Frozen state container hash does not match its result.")
    g = record["grid"]
    grid = EvolutionGrid(g["width_m"], g["height_m"], g["spacing_m"])
    if (
        g["shape"] != list(grid.shape)
        or g["origin_m"] != [0.0, 0.0]
        or g["axes"] != "x right, y down"
    ):
        raise ValueError("Frozen coordinates do not match the declared process grid.")
    last = len(record["snapshots"]) - 1
    if last < 0:
        raise ValueError("A completed case needs a final snapshot.")
    names = ("delivered_elevation_m", f"elevation_{last}_m", f"receiver_{last}", f"area_{last}_m2")
    with np.load(state_path, allow_pickle=False) as stored:
        arrays = [stored[name] for name in names]
    for name, values in zip(names, arrays, strict=True):
        if numeric_hash(values) != record["numeric_hashes"][name]:
            raise ValueError(f"Frozen numeric hash does not match: {name}")
        if values.shape != grid.shape or not np.all(np.isfinite(values)):
            raise ValueError(f"Frozen array is nonfinite or does not match the grid: {name}")
    delivered, raw, receivers, area = arrays
    if (
        delivered.dtype != np.float32
        or raw.dtype != np.float64
        or receivers.dtype != np.int64
        or area.dtype != np.float64
        or not np.array_equal(delivered, raw.astype(np.float32))
        or np.any(area < 0)
    ):
        raise ValueError("Frozen arrays do not follow the declared delivery/graph contract.")
    validate_graph(receivers, grid.shape)
    core = np.zeros(grid.shape, dtype=np.bool_)
    core[1:-1, 1:-1] = True
    if np.any(receivers[~core] != -1):
        raise ValueError("This experiment requires terminal perimeter nodes.")
    required = core & (receivers >= 0) & (area >= CHANNEL_AREA_M2)
    ground = delivered.astype(np.float64)
    for a in (ground, receivers, required):
        a.flags.writeable = False
    result = FrozenCase(path, record, grid, ground, receivers, required, hashes)
    result.verify_unchanged()
    return result


def discover(sources: list[Path]) -> tuple[list[Path], list[dict[str, str]]]:
    """Inspect only explicit roots and immediate worker children, including failures."""
    results: set[Path] = set()
    omissions: list[dict[str, str]] = []
    for source in sources:
        source = source.resolve(strict=True)
        if (source / "result.json").is_file():
            children = [source]
        else:
            children = sorted(p for p in source.iterdir() if p.is_dir())
        found = False
        for child in children:
            if (child / "result.json").is_file():
                results.add(child / "result.json")
                found = True
            elif (child / "failure.json").is_file():
                omissions.append({"source": str(child), "reason": "failed evolution worker"})
                found = True
            elif (child / "request.json").is_file():
                omissions.append({"source": str(child), "reason": "unfinished evolution worker"})
                found = True
        if not found:
            raise ValueError(f"No completed or failed evolution cases found in {source}")
    if not results or len(results) > 64:
        raise ValueError("Select 1-64 completed cases for one reconstruction comparison.")
    return sorted(results), omissions
