"""Compare actual raster delivery under matched incident-cell and curvature caps."""

import argparse
from dataclasses import replace
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.boundary_comparison import dense_banks
from benchmarks.evolution.boundary_report import render_sections
from benchmarks.evolution.constrained import FittedSurface
from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.network_comparison import routing
from benchmarks.evolution.network_fixture import FIXTURE_ID, fixture
from benchmarks.evolution.network_report import render_routes
from benchmarks.evolution.patch_comparison import inspect_surface
from benchmarks.evolution.valley_envelope import (
    ENVELOPE_MODEL_ID,
    audit_capacities,
    cell_safe_capacities,
)
from benchmarks.evolution.valley_layout import relocate_guides
from benchmarks.evolution.valley_patches import PatchSettings, prepare_patches
from benchmarks.evolution.valley_support import prepare_support
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid


def interior_controls(output: Path) -> list[dict[str, Any]]:
    grid = EvolutionGrid(4000, 4000, 250)
    cases = {
        "aligned-corners": (1250.0, 750.0, 2750.0, 2250.0),
        "unaligned-corners": (1337.0, 821.0, 2643.0, 2193.0),
        "domain-spanning-slab": (2000.0, 0.0, 3000.0, 4000.0),
        "partly-outside-domain": (-500.0, -100.0, 1234.0, 2391.0),
        "thin-protected-footprint": (1499.0, 1499.0, 1501.0, 1501.0),
    }
    rows: list[dict[str, Any]] = []
    arrays: dict[str, NDArray[np.float64]] = {}
    for name, bounds in cases.items():
        envelope = cell_safe_capacities(grid, bounds, limit_m=600, transition_m=2400)
        audit = audit_capacities(
            grid,
            envelope.capacities_m,
            bounds,
            limit_m=600,
            transition_m=2400,
        )
        if audit["violation_count"]:
            raise RuntimeError("An independent envelope geometry violated its cap.")
        arrays[name] = envelope.capacities_m
        rows.append(
            {
                "case": name,
                "bounds_m": bounds,
                "grid": {"extent_m": [4000, 4000], "spacing_m": 250},
                "limit_m": 600,
                "transition_m": 2400,
                "audit": audit,
                "diagnostics": envelope.diagnostics(),
                "capacity_sha256": numeric_hash(envelope.capacities_m),
            }
        )
    with output.open("xb") as stream:
        np.savez_compressed(stream, allow_pickle=False, **arrays)
    return rows


def run(output: Path, *, figures: bool = True) -> dict[str, Any]:
    original_identity = identity()
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    try:
        controls = interior_controls(output / "interior-controls.npz")
        rows: list[dict[str, Any]] = []
        delivered: dict[str, FittedSurface] = {}
        for spacing, rotated in ((1000.0, False), (500.0, False), (250.0, False), (250.0, True)):
            label = f"dx{spacing:g}" + ("-rotated90" if rotated else "")
            directory = output / label
            directory.mkdir()
            f = fixture(spacing, rotate=rotated)
            f = replace(f, network=relocate_guides(f, movable_edges=f.network.required).network)
            source_hash = numeric_hash(f.source.ground_m)
            settings = PatchSettings(boundary_model="head-mouth")
            patch = prepare_patches(f, f.source, mode="fresh", settings=settings)
            grid = f.source.grid
            support = prepare_support(grid, f.network)
            control = patch.deliver()
            tick = perf_counter()
            candidate = patch.deliver(envelope="curvature")
            delivery_seconds = perf_counter() - tick
            if not np.array_equal(candidate.ground_m, patch.deliver(envelope="curvature").ground_m):
                raise RuntimeError("Repeated envelope delivery changed Float32 ground.")
            bound = cell_safe_capacities(
                grid,
                patch.protected_bounds_m,
                limit_m=settings.fresh_cut_limit_m,
                transition_m=settings.support_m,
            )
            cap_audit = audit_capacities(
                grid,
                bound.capacities_m,
                patch.protected_bounds_m,
                limit_m=settings.fresh_cut_limit_m,
                transition_m=settings.support_m,
            )
            actual_cut = f.source.ground_m.astype(np.float64) - candidate.ground_m
            if np.any(actual_cut < 0) or np.any(actual_cut > bound.capacities_m + 1e-9):
                raise RuntimeError("Delivered nodes violate the proved capacities.")
            if cap_audit["violation_count"]:
                raise RuntimeError("Envelope interior check failed.")
            metrics: dict[str, Any] = {}
            profiles: dict[str, NDArray[np.float32]] = {}
            common: dict[str, FittedSurface] = {}
            for scope, sampler in (
                ("local", patch.sample),
                ("control", control.sample),
                ("candidate", candidate.sample),
            ):
                metrics[scope], common[scope] = inspect_surface(f, patch, sampler, rotated=rotated)
                dense, profiles[scope] = dense_banks(support, sampler)
                metrics[scope]["dense_bank_sections"] = dense
                metrics[scope]["quality_gates"]["dense_inward_bank_profiles"] = (
                    dense["inward_uphill_sections"] == 0
                )
                if (
                    any(
                        not metrics[scope]["quality_gates"][name]
                        for name in (
                            "hard_heights",
                            "no_fill",
                            "construction_cap",
                            "composition_volume",
                        )
                    )
                    or metrics[scope]["constraints"]["protected_change_samples"]
                ):
                    raise RuntimeError("Envelope comparison violated a hard input or budget.")
            # Keep one worst section from each reach, rather than hiding all
            # witnesses on the same local head. Record candidate residuals too.
            witnesses: dict[str, list[int]] = {}
            for scope in ("control", "candidate"):
                z = profiles[scope].astype(np.float64)
                rises = np.max(z - np.minimum.accumulate(z, axis=1), axis=1)
                selected: list[int] = []
                seen: set[int] = set()
                for i in np.argsort(-rises, kind="stable"):
                    edge = int(support.bed_edges[i])
                    if edge not in seen:
                        selected.append(int(i))
                        seen.add(edge)
                    if len(selected) == 3:
                        break
                witnesses[scope] = selected
            arrays = {
                "source_m": f.source.ground_m,
                "control_ground_m": control.ground_m,
                "candidate_ground_m": candidate.ground_m,
                "capacities_m": bound.capacities_m,
                "cell_error_m": bound.cell_error_m,
                "constant_cells": bound.constant_cells,
                "coordinates_m": f.network.coordinates_m,
                "receivers": f.network.receivers,
                "hard_points_m": f.hard.points_m,
                "hard_heights_m": f.hard.heights_m,
                "bank_points_m": support.banks_m,
                "bed_points_m": support.beds_m,
                "requested_edges": support.requested_edges,
                "bed_edges": support.bed_edges,
                **{name + "_common_ground_m": field.ground_m for name, field in common.items()},
                **{name + "_dense_profiles_m": values for name, values in profiles.items()},
            }
            with (directory / "fields.npz").open("xb") as stream:
                np.savez_compressed(stream, allow_pickle=False, **arrays)
            if figures:
                render_sections(
                    directory / "bank-sections.png",
                    support,
                    witnesses["control"],
                    {
                        "Incident-cell raster": profiles["control"],
                        "Local construction": profiles["local"],
                        "Curvature-bound raster": profiles["candidate"],
                    },
                    title="Same bank sections: incident-cell versus curvature-bound delivery",
                )
                render_sections(
                    directory / "remaining-sections.png",
                    support,
                    witnesses["candidate"],
                    {
                        "Local construction": profiles["local"],
                        "Curvature-bound raster": profiles["candidate"],
                    },
                    title="Remaining raster defects: candidate-worst sections on distinct reaches",
                )
                render_routes(
                    directory / "delivery-routing.png",
                    f,
                    {
                        "Incident-cell raster": (common["control"], routing(common["control"])),
                        "Curvature-bound raster": (
                            common["candidate"],
                            routing(common["candidate"]),
                        ),
                    },
                    label,
                )
            row = {
                "case": label,
                "spacing_m": spacing,
                "rotated90": rotated,
                "network_identity": f.network.identity(),
                "source_hash": source_hash,
                "matched_bank_count": len(support.banks_m),
                "input_roles": "unchanged local field, guides, hard inputs and fresh budgets",
                "local": metrics["local"],
                "control": metrics["control"],
                "candidate": metrics["candidate"],
                "envelope": bound.diagnostics(),
                "interior_audit": cap_audit,
                "protected_bounds_m": patch.protected_bounds_m,
                "control_projection": control.diagnostics,
                "candidate_projection": candidate.diagnostics,
                "bank_witnesses": {
                    k: [support.witness(i) for i in v] for k, v in witnesses.items()
                },
                "repeat_matches": True,
                "delivery_seconds": delivery_seconds,
                "numeric_hashes": {key: numeric_hash(value) for key, value in arrays.items()},
                "artifact_hashes": {
                    p.name: file_sha256(p) for p in sorted(directory.iterdir()) if p.is_file()
                },
            }
            if source_hash != numeric_hash(f.source.ground_m):
                raise RuntimeError("Envelope comparison mutated its source.")
            write_json(directory / "result.json", row)
            rows.append(row)
            delivered[label] = candidate
            old_failures = metrics["control"]["dense_bank_sections"]["inward_uphill_sections"]
            new_failures = metrics["candidate"]["dense_bank_sections"]["inward_uphill_sections"]
            print(
                f"Compared {label}: {old_failures} -> {new_failures} dense failures",
                flush=True,
            )
        rotation = float(
            np.max(
                np.abs(
                    delivered["dx250"].ground_m.astype(np.float64)
                    - np.rot90(delivered["dx250-rotated90"].ground_m)
                )
            )
        )
        failed = [
            f"{r['case']}: {gate}"
            for r in rows
            for gate, passed in r["candidate"]["quality_gates"].items()
            if not passed
        ]
        if rotation > 0.001:
            failed.append("rotation exceeds the 1 mm height gate")
        if identity() != original_identity:
            raise RuntimeError("Source/runtime identity changed during envelope comparison.")
        report = {
            "status": "complete",
            "model_id": ENVELOPE_MODEL_ID,
            "fixture_id": FIXTURE_ID,
            "identity": original_identity,
            "rows": rows,
            "interior_controls": controls,
            "interior_controls_sha256": file_sha256(output / "interior-controls.npz"),
            "rotation_maximum_ground_difference_m": rotation,
            "quality_decision": {
                "status": "rejected" if failed else "passed-this-fixture-only",
                "production_eligible": False,
                "failed_gates": failed,
            },
            "seconds": perf_counter() - started,
            "peak_resident_bytes": peak_resident_bytes(),
        }
        entries = [
            f"<h2>{escape(r['case'])}</h2>"
            f"<a href='{escape(r['case'])}/result.json'>Measurements</a>"
            + (
                "".join(
                    f"<img src='{escape(r['case'])}/{name}.png'>"
                    for name in ("bank-sections", "remaining-sections", "delivery-routing")
                )
                if figures
                else ""
            )
            for r in rows
        ]
        (output / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Cell-safe terrain delivery</title>"
            "<style>body{font:16px system-ui;max-width:1200px;margin:24px auto}"
            "img{width:100%}</style>"
            "<h1>Cell-safe terrain delivery</h1><p>Matched fields and physical bank pairs. "
            "Tighter bounds retain cell-interior protection. "
            "Raster defects still reject production.</p>"
            "<a href='comparison.json'>Decision and provenance</a>" + "".join(entries),
            encoding="utf-8",
        )
        write_json(output / "comparison.json", report)
        return report
    except Exception as exc:
        write_json(
            output / "incomplete.json",
            {
                "status": "failed",
                "error": str(exc),
                "model_id": ENVELOPE_MODEL_ID,
                "identity": original_identity,
                "seconds": perf_counter() - started,
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New comparison directory")
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
