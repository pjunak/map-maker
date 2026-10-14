"""Test physical valley banks against constraints and actual drainage capture."""

import argparse
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.constrained import (
    FittedSurface,
    HardHeights,
    InfeasibleSurface,
    fit,
    weights,
)
from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.network_comparison import constraints, rerouted_numbers, routing
from benchmarks.evolution.network_fixture import FIXTURE_ID, NetworkFixture, fixture
from benchmarks.evolution.network_report import render_banks, render_routes
from benchmarks.evolution.paths import PROFILE_TOLERANCE_M, Sampler, measure_paths, profile_numbers
from benchmarks.evolution.reconstruction import summarize
from benchmarks.evolution.valley_support import VALLEY_SUPPORT_ID, ValleySupport, prepare_support
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid


def bank_profiles(support: ValleySupport, sampler: Sampler) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    samples = 0
    for i, distance in enumerate(support.distances_m):
        stations = np.unique(np.concatenate((np.arange(0, distance, 25.0), [distance])))
        fraction = stations / distance if distance > 0 else np.zeros(1)
        xy = support.banks_m[i] + fraction[:, None] * (support.beds_m[i] - support.banks_m[i])
        z = sampler(xy[:, 0], xy[:, 1])
        numbers = profile_numbers(stations, z)
        numbers["endpoint_shortfall_m"] = float(support.drops_m[i] - (float(z[0]) - float(z[-1])))
        rows.append({"support_index": i, **numbers})
        samples += len(stations)
    return {
        "station_spacing_m": 25.0,
        "sample_count": samples,
        "endpoint_violation_count": sum(r["endpoint_shortfall_m"] > 0.0001 for r in rows),
        "inward_uphill_sections": sum(r["maximum_excursion_m"] > PROFILE_TOLERANCE_M for r in rows),
        "maximum_inward_excursion_m": max(r["maximum_excursion_m"] for r in rows),
        "rows": rows,
    }


def measure(
    f: NetworkFixture, field: FittedSurface, support: ValleySupport, rotated: bool
) -> tuple[dict[str, Any], FittedSurface]:
    common = EvolutionGrid(field.grid.width_m, field.grid.height_m, 125.0)
    y, x = np.indices(common.shape, dtype=np.float64) * common.spacing_m
    sampled = FittedSurface(common, field.sample(x, y), {})
    nodal = f.source.sample(*f.network.coordinates_m.T).astype(np.float64)
    profiles = {
        f"{step:g}m": measure_paths(f.network, field.sample, nodal, step) for step in (100.0, 25.0)
    }
    return {
        "profiles": profiles,
        "summaries": {name: summarize(value) for name, value in profiles.items()},
        "constraints": constraints(f, field.sample),
        "process_routing": rerouted_numbers(f, field.ground_m, rotated=rotated),
        "common_routing": rerouted_numbers(f, sampled.ground_m, rotated=rotated, grid=common),
        "bank_sections": bank_profiles(support, field.sample),
    }, sampled


def pinned_bank_conflict(f: NetworkFixture, support: ValleySupport) -> tuple[HardHeights, int]:
    source = f.source.ground_m.ravel().astype(np.float64)
    beds = np.asarray(weights(f.source.grid, support.beds_m) @ source).ravel()
    banks = np.asarray(weights(f.source.grid, support.banks_m) @ source).ravel()
    choices = np.flatnonzero(banks - beds < support.drops_m - 1.0)
    if not len(choices):
        raise ValueError("Fixture has no bank/height conflict control.")
    i = int(choices[0])
    hard = HardHeights(
        np.vstack((f.hard.points_m, support.beds_m[i])),
        np.concatenate((f.hard.heights_m, [beds[i]])),
    )
    return hard, i


def run(output: Path) -> dict[str, Any]:
    original_identity = identity()
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    rows: list[dict[str, Any]] = []
    accepted: dict[str, FittedSurface] = {}
    try:
        for spacing, rotated in ((1000.0, False), (500.0, False), (250.0, False), (250.0, True)):
            label = f"dx{spacing:g}" + ("-rotated90" if rotated else "")
            directory = output / label
            directory.mkdir()
            f = fixture(spacing, rotate=rotated)
            support = prepare_support(f.source.grid, f.network)
            source = f.source.ground_m.astype(np.float64)
            source_hash = numeric_hash(source)
            args = (f.source.grid, f.network, source, f.limits_m, f.target_m, f.hard)
            baseline = fit(*args)
            baseline_metrics, baseline_common = measure(f, baseline, support, rotated)
            pinned_diagnostic: dict[str, Any] | None = None
            if spacing == 500.0:
                pinned, bank_index = pinned_bank_conflict(f, support)
                # The added author height alone is feasible; its combination
                # with required bank support is not. Never lower the hard pin.
                fit(f.source.grid, f.network, source, f.limits_m, f.target_m, pinned)
                try:
                    fit(
                        f.source.grid,
                        f.network,
                        source,
                        f.limits_m,
                        f.target_m,
                        pinned,
                        valley=support,
                    )
                except InfeasibleSurface as exc:
                    pinned_diagnostic = {
                        "status": "rejected",
                        "support_index": bank_index,
                        "hard_points_m": pinned.points_m.tolist(),
                        "hard_heights_m": pinned.heights_m.tolist(),
                        "reason": str(exc),
                        "diagnostics": exc.diagnostics,
                    }
                else:
                    raise ValueError("A contradictory author-height/bank pair was admitted.")
            row: dict[str, Any] = {
                "case": label,
                "spacing_m": spacing,
                "rotated90": rotated,
                "source_hash": source_hash,
                "network_identity": f.network.identity(),
                "support": {
                    "model_id": VALLEY_SUPPORT_ID,
                    "bank_count": len(support.banks_m),
                    "station_spacing_m": support.station_spacing_m,
                    "offset_m": support.offset_m,
                    "minimum_lateral_slope": support.minimum_slope,
                    "reassigned_bank_count": int(
                        np.count_nonzero(support.requested_edges != support.bed_edges)
                    ),
                    "outside_domain_count": support.outside_domain_count,
                    "outlet_taper_m": support.offset_m,
                },
                "control": baseline_metrics,
                "control_hash": numeric_hash(baseline.ground_m),
                "pinned_bank_conflict": pinned_diagnostic,
            }
            fields = {"Longitudinal control": baseline}
            arrays: dict[str, NDArray[Any]] = {
                "source_m": f.source.ground_m,
                "control_m": baseline.ground_m,
                "conservative_limit_m": f.limits_m,
                "target_m": f.target_m,
                "banks_m": support.banks_m,
                "beds_m": support.beds_m,
                "requested_edges": support.requested_edges,
                "bed_edges": support.bed_edges,
                "remaining_to_mouth_m": support.remaining_to_mouth_m,
                "coordinates_m": f.network.coordinates_m,
                "receivers": f.network.receivers,
                "hard_points_m": f.hard.points_m,
                "hard_heights_m": f.hard.heights_m,
            }
            t = perf_counter()
            try:
                candidate = fit(*args, valley=support)
            except InfeasibleSurface as exc:
                row.update(status="infeasible", reason=str(exc), conflicts=exc.diagnostics)
                row["fit_seconds"] = perf_counter() - t
                # A rejected constraint set is a completed comparison result,
                # never a substitute surface or a solver-error fallback.
                try:
                    fit(*args, valley=support)
                except InfeasibleSurface as repeated:
                    if str(repeated) != str(exc) or repeated.diagnostics != exc.diagnostics:
                        raise ValueError(
                            "Repeated valley rejection changed its diagnosis."
                        ) from repeated
                else:
                    raise ValueError("Repeated valley fit changed feasibility.") from exc
                row["repeat_matches"] = True
                fields["Infeasible: source and reported support"] = f.source
            else:
                row["fit_seconds"] = perf_counter() - t
                repeated = fit(*args, valley=support)
                if not np.array_equal(candidate.ground_m, repeated.ground_m):
                    raise ValueError("Repeated valley fitting changed delivered ground.")
                row.update(
                    status="constructed",
                    repeat_matches=True,
                    solver=candidate.diagnostics,
                    candidate_hash=numeric_hash(candidate.ground_m),
                )
                metrics, common = measure(f, candidate, support, rotated)
                row["candidate"] = metrics
                fields["Bank-constrained candidate"] = candidate
                arrays["ground_m"] = candidate.ground_m
                accepted[label] = candidate
                actual = metrics["common_routing"]
                limits = metrics["constraints"]
                source_routing = rerouted_numbers(
                    f,
                    f.source.sample(
                        *np.meshgrid(
                            np.arange(common.grid.shape[1], dtype=np.float64) * 125.0,
                            np.arange(common.grid.shape[0], dtype=np.float64) * 125.0,
                        )
                    ),
                    rotated=rotated,
                    grid=common.grid,
                )
                row["quality_gates"] = {
                    "longitudinal_profiles": all(
                        s["unresolved_routes"] == 0 for s in metrics["summaries"].values()
                    ),
                    "bank_endpoint_support": metrics["bank_sections"]["endpoint_violation_count"]
                    == 0,
                    "inward_bank_profiles": metrics["bank_sections"]["inward_uphill_sections"] == 0,
                    "native_limits": all(
                        limits[k] == 0
                        for k in (
                            "fill_samples",
                            "cut_over_native_limit_samples",
                            "protected_change_samples",
                        )
                    ),
                    "hard_heights": not limits["anchors"]["violated_indices"],
                    "head_capture": actual["heads_within_1000m_of_authored_outlet"]
                    == len(f.network.heads()),
                    "no_new_sinks": actual["internal_terminal_count"]
                    <= source_routing["internal_terminal_count"],
                    "protected_divide": actual["cross_divide_stations"] == 0,
                }
                render_routes(
                    directory / "routing.png",
                    f,
                    {
                        "Longitudinal control": (baseline_common, routing(baseline_common)),
                        "Bank-constrained candidate": (common, routing(common)),
                    },
                    label,
                )
            conflict_indices = [
                int(w["support_index"]) for w in row.get("conflicts", {}).get("witnesses", [])
            ]
            render_banks(directory / "support.png", f, support, fields, conflict_indices, label)
            with (directory / "fields.npz").open("xb") as stream:
                np.savez_compressed(stream, allow_pickle=False, **arrays)
            row["artifact_hashes"] = {
                p.name: file_sha256(p) for p in sorted(directory.iterdir()) if p.is_file()
            }
            if numeric_hash(source) != source_hash:
                raise ValueError("Valley comparison modified its source.")
            write_json(directory / "result.json", row)
            rows.append(row)
            print(f"Compared {label}: {row['status']}", flush=True)
        rotation = (
            float(
                np.max(
                    np.abs(
                        accepted["dx250"].ground_m.astype(np.float64)
                        - np.rot90(accepted["dx250-rotated90"].ground_m)
                    )
                )
            )
            if "dx250" in accepted and "dx250-rotated90" in accepted
            else None
        )
        failed = [
            f"{row['case']}: infeasible bank constraints"
            for row in rows
            if row["status"] == "infeasible"
        ]
        failed.extend(
            f"{row['case']}: {name}"
            for row in rows
            for name, passed in row.get("quality_gates", {}).items()
            if not passed
        )
        if rotation is None or rotation > 0.001:
            failed.append("rotation: unverified or difference exceeds 1 mm")
        if identity() != original_identity:
            raise ValueError("Source/runtime identity changed during the valley comparison.")
        result: dict[str, Any] = {
            "status": "complete",
            "fixture_id": FIXTURE_ID,
            "model_id": VALLEY_SUPPORT_ID,
            "identity": original_identity,
            "quality_decision": {
                "status": "rejected" if failed else "passed-this-fixture-only",
                "production_eligible": False,
                "failed_gates": failed,
            },
            "rotation_maximum_ground_difference_m": rotation,
            "rows": rows,
            "seconds": perf_counter() - started,
            "peak_resident_bytes": peak_resident_bytes(),
        }
        entries: list[str] = []
        for row in rows:
            name = escape(row["case"])
            entries.append(
                f"<h2>{name}: {escape(row['status'])}</h2><p>"
                f"<a href='{name}/result.json'>Complete evidence</a></p>"
                f"<img src='{name}/support.png'>"
            )
            if row["status"] == "constructed":
                entries.append(f"<img src='{name}/routing.png'>")
        (output / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Valley capture comparison</title>"
            "<style>body{font:16px system-ui;max-width:1300px;margin:24px auto}"
            "img{width:100%}</style>"
            "<h1>Valley-bank feasibility and actual capture</h1><p>Same source, native cut limits, "
            "heights, divide and physical river network. No fill or automatic relaxation. "
            "Grey bank probes refer to the nearest reach, including across junctions. "
            "A feasible endpoint pair does not guarantee an inward-sloping bank "
            "or river capture.</p>"
            "<p><a href='comparison.json'>Summary and provenance</a></p><h2>Quality decision: "
            + escape(result["quality_decision"]["status"])
            + "</h2><ul>"
            + "".join(f"<li>{escape(item)}</li>" for item in failed)
            + "</ul>"
            + "".join(entries),
            encoding="utf-8",
        )
        write_json(output / "comparison.json", result)
        return result
    except Exception as exc:
        write_json(output / "incomplete.json", {"status": "failed", "error": str(exc)})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New comparison directory")
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
