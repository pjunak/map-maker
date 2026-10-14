"""Compare local connected valleys, hard controls and actual raster delivery."""

import argparse
from dataclasses import asdict, replace
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from benchmarks.evolution.constrained import FittedSurface, fit
from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.network_comparison import constraints, rerouted_numbers, routing
from benchmarks.evolution.network_fixture import FIXTURE_ID, NetworkFixture, fixture
from benchmarks.evolution.network_report import render, render_routes
from benchmarks.evolution.paths import Sampler, measure_paths
from benchmarks.evolution.reconstruction import summarize
from benchmarks.evolution.valley_comparison import bank_profiles
from benchmarks.evolution.valley_patches import (
    PATCH_MODEL_ID,
    ValleyPatches,
    prepare_patches,
)
from benchmarks.evolution.valley_support import prepare_support
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid


def inspect_surface(
    f: NetworkFixture, patch: ValleyPatches, sampler: Sampler, *, rotated: bool
) -> tuple[dict[str, Any], FittedSurface]:
    grid = EvolutionGrid(f.source.grid.width_m, f.source.grid.height_m, 125.0)
    y, x = np.indices(grid.shape, dtype=np.float64) * grid.spacing_m
    sampled = FittedSurface(grid, sampler(x, y), {})
    delta = f.source.sample(x, y).astype(np.float64) - sampled.ground_m
    quadrature = np.ones(grid.shape, dtype=np.float64)
    quadrature[[0, -1], :] *= 0.5
    quadrature[:, [0, -1]] *= 0.5
    volume = float(np.sum(np.maximum(delta, 0) * quadrature) * grid.spacing_m**2)
    pins = f.source.sample(*f.network.coordinates_m.T).astype(np.float64)
    profiles = {
        f"{step:g}m": measure_paths(f.network, sampler, pins, step) for step in (100.0, 25.0)
    }
    limits = constraints(f, sampler)
    actual = rerouted_numbers(f, sampled.ground_m, rotated=rotated, grid=grid)
    sections = bank_profiles(prepare_support(f.source.grid, f.network), sampler)
    cap_violations = int(np.count_nonzero(delta > patch.caps(x, y) + 0.01))
    gates = {
        "head_capture": actual["heads_within_1000m_of_authored_outlet"] == len(f.network.heads()),
        "no_interior_sinks": actual["internal_terminal_count"] == 0,
        "divide": actual["cross_divide_stations"] == 0 and limits["protected_change_samples"] == 0,
        "hard_heights": not limits["anchors"]["violated_indices"],
        "no_fill": limits["fill_samples"] == 0,
        "construction_cap": cap_violations == 0,
        "composition_volume": patch.mode == "fixed" or volume <= patch.settings.fresh_cut_volume_m3,
        "longitudinal_profiles": all(
            summarize(value)["unresolved_routes"] == 0 for value in profiles.values()
        ),
        "inward_bank_profiles": sections["inward_uphill_sections"] == 0,
        "bank_endpoint_support": sections["endpoint_violation_count"] == 0,
    }
    if patch.mode == "fixed":
        gates["native_limits"] = limits["cut_over_native_limit_samples"] == 0
    return {
        "profiles": profiles,
        "summaries": {name: summarize(value) for name, value in profiles.items()},
        "constraints": limits,
        "bank_sections": sections,
        "common_routing": actual,
        "construction_cap_violation_samples": cap_violations,
        "composition_cut_m3": volume,
        "composition_volume_scope": "125 m endpoint trapezoid quadrature; not simulated erosion",
        "quality_gates": gates,
    }, sampled


def run(output: Path, *, figures: bool = True) -> dict[str, Any]:
    original_identity = identity()
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    rows: list[dict[str, Any]] = []
    delivered: dict[str, FittedSurface] = {}
    try:
        for spacing, rotated in ((1000.0, False), (500.0, False), (250.0, False), (250.0, True)):
            f = fixture(spacing, rotate=rotated)
            source_hash = numeric_hash(f.source.ground_m)
            control = fit(
                f.source.grid,
                f.network,
                f.source.ground_m.astype(np.float64),
                f.limits_m,
                f.target_m,
                f.hard,
            )
            for mode in ("fixed", "fresh"):
                label = f"{mode}-dx{spacing:g}" + ("-rotated90" if rotated else "")
                directory = output / label
                directory.mkdir()
                tick = perf_counter()
                patch = prepare_patches(f, control, mode=mode)
                result = patch.deliver()
                repeated = prepare_patches(f, control, mode=mode).deliver()
                if not np.array_equal(result.ground_m, repeated.ground_m):
                    raise RuntimeError("Repeated patch construction changed Float32 delivery.")
                seconds = perf_counter() - tick
                local, local_field = inspect_surface(f, patch, patch.sample, rotated=rotated)
                raster, raster_field = inspect_surface(f, patch, result.sample, rotated=rotated)
                for metrics in (local, raster):
                    required = ["hard_heights", "no_fill", "construction_cap", "composition_volume"]
                    if mode == "fixed":
                        required.append("native_limits")
                    if (
                        any(not metrics["quality_gates"][key] for key in required)
                        or metrics["constraints"]["protected_change_samples"]
                    ):
                        raise RuntimeError("Constructed patch violated a hard input or envelope.")
                row: dict[str, Any] = {
                    "case": label,
                    "status": "constructed",
                    "mode": mode,
                    "process_spacing_m": spacing,
                    "rotated90": rotated,
                    "source_hash": source_hash,
                    "network_identity": f.network.identity(),
                    "settings": asdict(patch.settings),
                    "profile_segment_count": len(patch.segments_m),
                    "input_roles": {
                        "initial_relief": "fixed source"
                        if mode == "fixed"
                        else "generated hypothesis",
                        "height_pins": "final hard targets",
                        "divide_and_zero_coast": "persistent fixed boundaries",
                        "network": "same physical guides; automatic relocation not tested",
                        "cut_envelope": "native incision"
                        if mode == "fixed"
                        else "separate fresh construction",
                        "history": "no time evolution or geological erosion in this experiment",
                    },
                    "local": local,
                    "delivery": raster,
                    "delivery_projection": result.diagnostics,
                    "repeat_matches": True,
                    "construction_seconds": seconds,
                }
                arrays = {
                    "source_m": f.source.ground_m,
                    "control_m": control.ground_m,
                    "ground_m": result.ground_m,
                    "local_common_ground_m": local_field.ground_m,
                    "delivered_common_ground_m": raster_field.ground_m,
                    "conservative_native_limit_m": f.limits_m,
                    "hard_points_m": f.hard.points_m,
                    "hard_heights_m": f.hard.heights_m,
                    "coordinates_m": f.network.coordinates_m,
                    "receivers": f.network.receivers,
                    "patch_segments_m": patch.segments_m,
                    "patch_bed_heights_m": patch.bed_heights_m,
                    "anchor_corrections_m": patch.anchor_corrections_m,
                    "mouth_segments_m": patch.mouth_segments_m,
                    "mouth_heights_m": patch.mouth_heights_m,
                    "mouth_inward": patch.mouth_inward,
                }
                if mode == "fresh" and spacing == 250 and not rotated:
                    no_mouth = replace(
                        patch,
                        mouth_segments_m=np.empty((0, 2, 2)),
                        mouth_heights_m=np.empty(0),
                        mouth_inward=np.empty((0, 2)),
                    )
                    ablation, ablation_field = inspect_surface(
                        f, no_mouth, no_mouth.sample, rotated=False
                    )
                    row["without_mouth_transition"] = ablation
                    arrays["without_mouth_common_ground_m"] = ablation_field.ground_m
                    if figures:
                        render_routes(
                            directory / "mouth-ablation.png",
                            f,
                            {
                                "Same local patches without mouth transition": (
                                    ablation_field,
                                    routing(ablation_field),
                                ),
                                "Explicit mouth transition": (local_field, routing(local_field)),
                            },
                            label,
                        )
                with (directory / "fields.npz").open("xb") as stream:
                    np.savez_compressed(stream, allow_pickle=False, **arrays)
                row["numeric_hashes"] = {
                    name: numeric_hash(value) for name, value in arrays.items()
                }
                if figures:
                    render(
                        directory / "ground.png",
                        f,
                        {
                            "Fixed longitudinal control": control.sample,
                            "Local valley patches": patch.sample,
                            "Actual Float32 raster": result.sample,
                        },
                        label,
                    )
                    render_routes(
                        directory / "routing.png",
                        f,
                        {
                            "Local field sampled at 125 m": (local_field, routing(local_field)),
                            "Raster reconstructed at 125 m": (raster_field, routing(raster_field)),
                        },
                        label,
                    )
                row["artifact_hashes"] = {
                    p.name: file_sha256(p) for p in sorted(directory.iterdir()) if p.is_file()
                }
                if source_hash != numeric_hash(f.source.ground_m):
                    raise RuntimeError("Patch comparison mutated its source.")
                write_json(directory / "result.json", row)
                rows.append(row)
                delivered[label] = result
                local_heads = local["common_routing"]["heads_within_1000m_of_authored_outlet"]
                raster_heads = raster["common_routing"]["heads_within_1000m_of_authored_outlet"]
                print(
                    f"Compared {label}: local {local_heads}/4, delivery {raster_heads}/4 heads",
                    flush=True,
                )
        rotation = {
            mode: float(
                np.max(
                    np.abs(
                        delivered[f"{mode}-dx250"].ground_m.astype(np.float64)
                        - np.rot90(delivered[f"{mode}-dx250-rotated90"].ground_m)
                    )
                )
            )
            for mode in ("fixed", "fresh")
        }
        failed = [
            f"{row['case']}: {scope}/{name}"
            for row in rows
            for scope in ("local", "delivery")
            for name, passed in row[scope]["quality_gates"].items()
            if not passed
        ]
        failed.extend(
            f"{mode}: rotation exceeds 1 mm" for mode, value in rotation.items() if value > 0.001
        )
        if identity() != original_identity:
            raise RuntimeError("Source/runtime identity changed during patch comparison.")
        report: dict[str, Any] = {
            "status": "complete",
            "model_id": PATCH_MODEL_ID,
            "fixture_id": FIXTURE_ID,
            "identity": original_identity,
            "rows": rows,
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
            f"<h2>{escape(row['case'])}</h2><p><a href='{escape(row['case'])}/result.json'>"
            "Complete metrics and input roles</a></p>"
            + (
                f"<img src='{escape(row['case'])}/ground.png'>"
                f"<img src='{escape(row['case'])}/routing.png'>"
                if figures
                else ""
            )
            for row in rows
        ]
        if figures:
            entries.append(
                "<h2>Coastal transition ablation at 250 m</h2>"
                "<img src='fresh-dx250/mouth-ablation.png'>"
            )
        (output / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Connected valley patches</title>"
            "<style>body{font:16px system-ui;max-width:1300px;margin:24px auto}"
            "img{width:100%}</style>"
            "<h1>Connected valleys and actual raster delivery</h1>"
            "<p>Fixed control and separate fresh-construction envelope. "
            "Neither changes a completed map. "
            "Local-field routing is sampled evidence, not a continuous-flow proof. "
            "Hard targets, native-control failures and delivery losses remain visible.</p>"
            "<p><a href='comparison.json'>Summary, decision and provenance</a></p>"
            + "".join(entries),
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
                "model_id": PATCH_MODEL_ID,
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
