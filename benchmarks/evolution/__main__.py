"""Run: python -m benchmarks.evolution --output artifacts/evolution-example."""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np

from benchmarks.evolution.evidence import (
    delivered_snapshot,
    grid_metadata,
    identity,
    save_arrays,
    snapshot_metadata,
    volume_ledger,
    write_json,
)
from benchmarks.evolution.metrics import main_profile, measure
from benchmarks.evolution.reference import evolve
from benchmarks.evolution.scenarios import CASES, HistoryCase, history, scenario, scenario_identity
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EVOLUTION_MODEL_ID, EvolutionBudget, EvolutionGrid


def worker(path: Path) -> None:
    job: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    initial_identity = identity()
    if initial_identity != job["identity"]:
        raise RuntimeError("Reference runtime/source changed before the worker started.")
    budget = EvolutionBudget(**job["budget"])
    grid = EvolutionGrid(**job["grid"])
    fields = scenario(grid, job["seed"], job["angle_deg"])
    case = job["case"]
    if case == "uniform-rock":
        fields = replace(fields, resistance=np.ones(grid.shape))
    started = perf_counter()
    result = None
    baseline_inputs = None
    h = history(cast(HistoryCase, case if case != "current-generator" else "two-epoch"))
    if case == "current-generator":
        from benchmarks.evolution.baseline import baseline

        state, baseline_inputs = baseline(fields, job["seed"], job["angle_deg"])
        snapshots = (state,)
    else:
        def progress(row: dict[str, float | str]) -> None:
            print(f'{job["id"]}: {float(row["time_years"])/1.e6:.3f} Myr', flush=True)

        result = evolve(fields, h, budget, progress=progress)
        snapshots = result.snapshots
    solver_seconds = perf_counter()-started
    epoch = h.epochs[-1]
    delivered = delivered_snapshot(snapshots[-1], fields, epoch, h)
    measured = measure(delivered, fields)
    expected_discharge = float(np.sum(fields.runoff_weight[fields.core])
                               * grid.spacing_m**2 * epoch.runoff_m_per_year)
    if not np.isclose(measured["outlet_discharge_m3_per_year"], expected_discharge, rtol=1.e-10):
        raise RuntimeError("Final outlet discharge does not balance the declared input runoff.")
    ledger = volume_ledger(result, fields) if result is not None else None
    if ledger is not None and ledger["relative_residual"] > 1.e-10:
        raise RuntimeError("Evolution failed its independent volume ledger.")
    arrays = save_arrays(path.parent / "states.npz", snapshots, fields, result)
    row: dict[str, Any] = {
        "status": "complete", "id": job["id"], "case": case, "seed": job["seed"],
        "angle_deg": job["angle_deg"], "model_id": EVOLUTION_MODEL_ID,
        "grid": grid_metadata(fields), "budget": asdict(budget),
        "history": asdict(h) if result is not None else None,
        "scenario_sha256": scenario_identity(fields, job["seed"], job["angle_deg"]),
        "input_field_hashes": fields.hashes(), "numeric_hashes": arrays,
        "baseline_inputs": baseline_inputs,
        "snapshots": [{**snapshot_metadata(s), "metrics": measure(s, fields),
                       "main_profile": main_profile(s, grid)} for s in snapshots],
        "final_metrics": measured,
        "float32_maximum_quantization_m": float(np.max(np.abs(
            delivered.elevation_m - snapshots[-1].elevation_m))),
        "ledger": ledger, "solver_seconds": solver_seconds,
        "stage_seconds": result.stage_seconds if result is not None else {},
        "accepted_steps": len(result.steps) if result is not None else 0,
        "trials": result.trials if result is not None else 0,
        "rejected_trials": result.rejected_trials if result is not None else 0,
        "steps": result.steps if result is not None else (),
        "expected_outlet_discharge_m3_per_year": expected_discharge,
        "peak_resident_bytes": peak_resident_bytes(),
        "memory_scope": "fresh worker lifetime, including scientific imports and measurement",
        "identity": initial_identity,
    }
    if initial_identity != identity():
        raise RuntimeError("Reference runtime/source changed during the worker.")
    row["artifacts"] = {"states.npz": file_sha256(path.parent / "states.npz")}
    # Completion is published only after numerical checks and artifacts succeed.
    write_json(path.parent / "result.json", row)


def run(args: argparse.Namespace) -> int:
    budget = EvolutionBudget(maximum_seconds=args.maximum_seconds,
                             maximum_step_years=args.maximum_step_years,
                             step_error_m=args.step_error_m)
    jobs: list[dict[str, Any]] = []
    initial_identity = identity()
    for spacing in args.spacing_m:
        grid = EvolutionGrid(80_000.*args.extent_scale, 60_000.*args.extent_scale, spacing)
        for seed in args.seeds:
            scenario(grid, seed, args.angle_deg)  # Validate before creating any output.
            for case in args.cases:
                identifier = f"{case}-seed{seed}-dx{spacing:g}"
                jobs.append({"id": identifier, "case": case, "seed": seed,
                             "angle_deg": args.angle_deg, "grid": asdict(grid),
                             "budget": asdict(budget), "identity": initial_identity})
    if len({j["id"] for j in jobs}) != len(jobs):
        raise ValueError("Repeated cases, spacings or seeds would overwrite a result.")
    output: Path = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "request.json", {"model_id": EVOLUTION_MODEL_ID, "jobs": jobs})
    rows: list[dict[str, Any]] = []
    for job in jobs:
        directory = output / job["id"]
        directory.mkdir()
        path = directory / "request.json"
        write_json(path, job)
        started = perf_counter()
        error = ""
        try:
            with (directory / "worker.log").open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    [sys.executable, "-m", "benchmarks.evolution", "--worker", str(path)],
                    stdout=log, stderr=subprocess.STDOUT, check=False,
                    timeout=budget.maximum_seconds+30.,
                )
            if completed.returncode:
                error = f"Worker exited {completed.returncode}; see {job['id']}/worker.log"
        except subprocess.TimeoutExpired:
            error = "Worker exceeded solver budget plus 30 s startup/measurement allowance."
        if error:
            row = {"id": job["id"], "status": "incomplete", "error": error}
            write_json(directory / "failure.json", row)
        else:
            row = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        row["worker_wall_seconds"] = perf_counter()-started
        rows.append(row)
        print(f'{job["id"]}: {row["status"]} ({row["worker_wall_seconds"]:.2f} s)', flush=True)
    if identity() != initial_identity:
        write_json(output / "failure.json", {"error": "Runtime/source changed during comparison"})
        return 1
    if any(r["status"] == "complete" for r in rows):
        from benchmarks.evolution.report import render_report

        render_report(output, rows)
    complete = all(r["status"] == "complete" for r in rows)
    manifest = {"status": "complete" if complete else "incomplete", "rows": rows,
                "identity": initial_identity,
                "purpose": "reference experiment; not an application terrain build"}
    write_json(output / ("comparison.json" if complete else "incomplete.json"), manifest)
    return 0 if complete else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded landscape-evolution reference comparison")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help="New, never overwritten report directory")
    parser.add_argument("--cases", nargs="+", choices=(*CASES, "current-generator"),
                        default=["two-epoch", "constant", "reversed", "current-generator"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[42])
    parser.add_argument("--spacing-m", nargs="+", type=float, default=[625.])
    parser.add_argument("--angle-deg", type=float, default=25.)
    parser.add_argument("--extent-scale", type=float, default=1.)
    parser.add_argument("--maximum-seconds", type=float, default=60.)
    parser.add_argument("--maximum-step-years", type=float, default=25_000.)
    parser.add_argument("--step-error-m", type=float, default=.5)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return 0
    if args.output is None:
        parser.error("--output is required")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
