"""Experiment identities and numerical artifacts; never a terrain-build manifest."""

from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

import numpy as np

from benchmarks.evolution.reference import EvolutionResult, LandlabReference, Snapshot
from benchmarks.evolution.scenarios import EvolutionFields, FloatArray
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.domain.evolution import EvolutionEpoch, EvolutionHistory

ROOT = Path(__file__).resolve().parents[2]


def identity() -> dict[str, Any]:
    benchmark_sources = {p.relative_to(ROOT).as_posix(): file_sha256(p)
                         for p in sorted((ROOT / "benchmarks").rglob("*.py"))}
    return {"runtime": runtime_identity(),
            "benchmark_source_sha256": sha256(canonical_json(benchmark_sources)).hexdigest(),
            "installed_packages": {d.metadata["Name"].lower(): d.version for d in distributions()}}


def write_json(path: Path, data: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json(data))


def numeric_hash(values: np.ndarray[Any, Any]) -> str:
    header = {"shape": list(values.shape), "dtype": values.dtype.str}
    return sha256(canonical_json(header) + values.tobytes(order="C")).hexdigest()


def delivered_snapshot(final: Snapshot, fields: EvolutionFields, epoch: EvolutionEpoch,
                       history: EvolutionHistory) -> Snapshot:
    from dataclasses import replace

    quantized: FloatArray = final.elevation_m.astype(np.float32).astype(np.float64)
    engine = LandlabReference(replace(fields, initial_m=quantized), history)
    engine.set_epoch(epoch)
    engine.route()
    return engine.snapshot("float32-delivery", final.time_years)


def save_arrays(path: Path, snapshots: tuple[Snapshot, ...], fields: EvolutionFields,
                result: EvolutionResult | None) -> dict[str, str]:
    arrays: dict[str, np.ndarray[Any, Any]] = {
        "uplift_weight": fields.uplift_weight, "resistance": fields.resistance,
        "runoff_weight": fields.runoff_weight,
        "delivered_elevation_m": snapshots[-1].elevation_m.astype(np.float32),
    }
    for index, s in enumerate(snapshots):
        arrays[f"elevation_{index}_m"] = s.elevation_m
        arrays[f"receiver_{index}"] = s.receiver
        arrays[f"area_{index}_m2"] = s.area_m2
        arrays[f"discharge_{index}_m3_per_year"] = s.discharge_m3_per_year
        arrays[f"depression_{index}_m"] = s.depression_depth_m
    if result is not None:
        arrays.update(uplift_m=result.uplift_m, incision_m=result.incision_m,
                      diffusion_change_m=result.diffusion_change_m)
    with path.open("xb") as stream:
        np.savez_compressed(stream, allow_pickle=False, **arrays)
    return {name: numeric_hash(a) for name, a in arrays.items()}


def volume_ledger(result: EvolutionResult, fields: EvolutionFields) -> dict[str, float]:
    area = fields.grid.spacing_m**2
    uplift = float(np.sum(result.uplift_m[fields.core])*area)
    incision = float(np.sum(result.incision_m[fields.core])*area)
    initial = float(np.sum(fields.initial_m[fields.core])*area)
    final = float(np.sum(result.snapshots[-1].elevation_m[fields.core])*area)
    scale = max(1., uplift + incision + abs(result.diffusion_boundary_export_m3))
    return {"initial_m3": initial, "final_m3": final, "uplift_m3": uplift,
            "incision_export_m3": incision,
            "hillslope_boundary_export_m3": result.diffusion_boundary_export_m3,
            "residual_m3": result.balance_residual_m3,
            "relative_residual": abs(result.balance_residual_m3)/scale}


def snapshot_metadata(s: Snapshot) -> dict[str, Any]:
    return {"name": s.name, "time_years": s.time_years}


def grid_metadata(fields: EvolutionFields) -> dict[str, Any]:
    return {**asdict(fields.grid), "shape": list(fields.grid.shape),
            "contributing_area_m2": fields.grid.contributing_area_m2,
            "origin_m": [0., 0.], "axes": "x right, y down",
            "boundary": "fixed perimeter; zero contributing area at perimeter nodes"}
