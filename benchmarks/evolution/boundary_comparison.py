"""Compare head/mouth construction with unchanged geometry and dense bank checks."""

import argparse
from dataclasses import asdict, replace
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.boundary_report import render_sections
from benchmarks.evolution.constrained import FittedSurface
from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.layout_comparison import run as run_controls
from benchmarks.evolution.network_comparison import routing
from benchmarks.evolution.network_fixture import FIXTURE_ID, fixture
from benchmarks.evolution.network_report import render_routes
from benchmarks.evolution.patch_comparison import inspect_surface
from benchmarks.evolution.paths import PROFILE_TOLERANCE_M, Sampler
from benchmarks.evolution.valley_boundaries import BOUNDARY_MODEL_ID
from benchmarks.evolution.valley_layout import relocate_guides
from benchmarks.evolution.valley_patches import PatchSettings, prepare_patches
from benchmarks.evolution.valley_support import ValleySupport, prepare_support
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import file_sha256


def dense_banks(
    support: ValleySupport, sampler: Sampler
) -> tuple[dict[str, Any], NDArray[np.float32]]:
    # Uniform fractions retain exact endpoints and every original bank/bed pair.
    # Every step is <=2.5 m for the existing <=500 m nearest-reach supports.
    intervals = max(1, int(np.ceil(float(support.distances_m.max()) / 2.5)))
    if intervals > 256 or len(support.banks_m) * (intervals + 1) > 1_000_000:
        raise ValueError("Dense bank comparison exceeds its bounded sampling budget.")
    t = np.linspace(0.0, 1.0, intervals + 1)
    xy = (
        support.banks_m[:, None, :]
        + t[None, :, None] * (support.beds_m - support.banks_m)[:, None, :]
    )
    values = sampler(xy[:, :, 0], xy[:, :, 1])
    z = values.astype(np.float64)
    excursion = np.max(z - np.minimum.accumulate(z, axis=1), axis=1)
    failures = np.flatnonzero(excursion > PROFILE_TOLERANCE_M)
    return {
        "section_count": len(values),
        "sample_count": values.size,
        "maximum_step_m": float(support.distances_m.max()) / intervals,
        "tolerance_m": PROFILE_TOLERANCE_M,
        "inward_uphill_sections": len(failures),
        "maximum_inward_excursion_m": float(excursion.max()),
        "failed_support_indices": failures.tolist(),
    }, values


def run(output: Path, *, figures: bool = True) -> dict[str, Any]:
    original_identity = identity()
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    try:
        controls = run_controls(output / "controls", figures=figures)
        rows: list[dict[str, Any]] = []
        delivered: dict[str, FittedSurface] = {}
        for reference in controls["rows"]:
            label = reference["case"]
            spacing, rotated = reference["spacing_m"], reference["rotated90"]
            directory = output / label
            directory.mkdir()
            f = fixture(spacing, rotate=rotated)
            source_hash = numeric_hash(f.source.ground_m)
            layout = relocate_guides(f, movable_edges=f.network.required)
            f = replace(f, network=layout.network)
            if f.network.identity() != reference["network_identity"]:
                raise RuntimeError("Boundary comparison changed the control guide geometry.")
            support = prepare_support(f.source.grid, f.network)
            control = prepare_patches(f, f.source, mode="fresh")
            settings = PatchSettings(boundary_model="head-mouth")
            tick = perf_counter()
            patch = prepare_patches(f, f.source, mode="fresh", settings=settings)
            field = patch.deliver()
            repeated = prepare_patches(f, f.source, mode="fresh", settings=settings)
            if not np.array_equal(field.ground_m, repeated.deliver().ground_m):
                raise RuntimeError("Repeated boundary construction changed Float32 delivery.")
            construction_seconds = perf_counter() - tick
            local, local_field = inspect_surface(f, patch, patch.sample, rotated=rotated)
            raster, raster_field = inspect_surface(f, patch, field.sample, rotated=rotated)
            dense: dict[str, Any] = {}
            profile_arrays: dict[str, NDArray[np.float32]] = {}
            for scope, sampler in (
                ("control", control.sample),
                ("local", patch.sample),
                ("delivery", field.sample),
            ):
                dense[scope], profile_arrays[scope] = dense_banks(support, sampler)
            for scope, metrics in (("local", local), ("delivery", raster)):
                metrics["dense_bank_sections"] = dense[scope]
                metrics["quality_gates"]["dense_inward_bank_profiles"] = (
                    dense[scope]["inward_uphill_sections"] == 0
                )
                if (
                    any(
                        not metrics["quality_gates"][name]
                        for name in (
                            "hard_heights",
                            "no_fill",
                            "construction_cap",
                            "composition_volume",
                        )
                    )
                    or metrics["constraints"]["protected_change_samples"]
                ):
                    raise RuntimeError("Boundary construction violated a hard input or envelope.")
            by_edge: dict[int, dict[str, Any]] = {}
            for section in reference["local"]["bank_sections"]["rows"]:
                if section["maximum_excursion_m"] <= PROFILE_TOLERANCE_M:
                    continue
                edge = int(support.requested_edges[section["support_index"]])
                if (
                    edge not in by_edge
                    or section["maximum_excursion_m"] > by_edge[edge]["maximum_excursion_m"]
                ):
                    by_edge[edge] = section
            witnesses = [
                row["support_index"]
                for row in sorted(by_edge.values(), key=lambda row: -row["maximum_excursion_m"])[:3]
            ]
            row: dict[str, Any] = {
                "case": label,
                "status": "constructed",
                "spacing_m": spacing,
                "rotated90": rotated,
                "source_hash": source_hash,
                "network_identity": f.network.identity(),
                "settings": asdict(settings),
                "head_transitions": [asdict(v) for v in patch.head_transitions],
                "matched_bank_count": len(support.banks_m),
                "physical_network_length_m": float(
                    np.linalg.norm(
                        f.network.coordinates_m[f.network.required]
                        - f.network.coordinates_m[f.network.receivers[f.network.required]],
                        axis=1,
                    ).sum()
                ),
                "input_roles": {
                    "guides": "identical admitted automatic layout; all original vertices retained",
                    "hard_heights_divide_coast": "unchanged final/persistent requirements",
                    "relief": "same generated hypothesis; no completed map edits",
                    "envelope": "unchanged fresh 600 m / 120 km3 construction; no fill",
                    "history": "no time evolution or simulated erosion",
                },
                "control": {key: reference[key] for key in ("local", "delivery")},
                "control_dense_bank_sections": dense["control"],
                "local": local,
                "delivery": raster,
                "bank_witnesses": [support.witness(i) for i in witnesses],
                "delivery_projection": field.diagnostics,
                "repeat_matches": True,
                "construction_seconds": construction_seconds,
            }
            arrays = {
                "source_m": f.source.ground_m,
                "ground_m": field.ground_m,
                "local_common_ground_m": local_field.ground_m,
                "delivered_common_ground_m": raster_field.ground_m,
                "coordinates_m": f.network.coordinates_m,
                "receivers": f.network.receivers,
                "bank_points_m": support.banks_m,
                "bed_points_m": support.beds_m,
                "requested_edges": support.requested_edges,
                "bed_edges": support.bed_edges,
                "hard_points_m": f.hard.points_m,
                "hard_heights_m": f.hard.heights_m,
                "patch_segments_m": patch.segments_m,
                "patch_bed_heights_m": patch.bed_heights_m,
                "control_bed_heights_m": control.bed_heights_m,
                "anchor_corrections_m": patch.anchor_corrections_m,
                **{name + "_dense_profiles_m": value for name, value in profile_arrays.items()},
            }
            with (directory / "fields.npz").open("xb") as stream:
                np.savez_compressed(stream, allow_pickle=False, **arrays)
            row["numeric_hashes"] = {key: numeric_hash(value) for key, value in arrays.items()}
            if figures:
                render_sections(
                    directory / "bank-sections.png",
                    support,
                    witnesses,
                    {
                        "Control local field": profile_arrays["control"],
                        "Candidate local field": profile_arrays["local"],
                        "Candidate Float32 raster": profile_arrays["delivery"],
                    },
                )
                render_routes(
                    directory / "local-delivery.png",
                    f,
                    {
                        "Local field, unchanged guides": (local_field, routing(local_field)),
                        "Actual Float32 raster": (raster_field, routing(raster_field)),
                    },
                    label,
                )
            row["artifact_hashes"] = {
                p.name: file_sha256(p) for p in sorted(directory.iterdir()) if p.is_file()
            }
            if source_hash != numeric_hash(f.source.ground_m):
                raise RuntimeError("Boundary comparison mutated its source.")
            write_json(directory / "result.json", row)
            rows.append(row)
            delivered[label] = field
            print(
                f"Compared {label}: {dense['local']['inward_uphill_sections']} dense local / "
                f"{dense['delivery']['inward_uphill_sections']} dense raster bank failures",
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
            f"{row['case']}: {scope}/{gate}"
            for row in rows
            for scope in ("local", "delivery")
            for gate, passed in row[scope]["quality_gates"].items()
            if not passed
        ]
        if rotation > 0.001:
            failed.append("rotation exceeds the 1 mm height gate")
        if identity() != original_identity:
            raise RuntimeError("Source/runtime identity changed during boundary comparison.")
        report: dict[str, Any] = {
            "status": "complete",
            "model_id": BOUNDARY_MODEL_ID,
            "fixture_id": FIXTURE_ID,
            "identity": original_identity,
            "rows": rows,
            "control_manifest_sha256": file_sha256(output / "controls/comparison.json"),
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
            f"<h2>{escape(row['case'])}</h2>"
            f"<p><a href='{escape(row['case'])}/result.json'>Measurements</a></p>"
            + (
                f"<img src='{escape(row['case'])}/bank-sections.png'>"
                f"<img src='{escape(row['case'])}/local-delivery.png'>"
                if figures
                else ""
            )
            for row in rows
        ]
        (output / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Head and mouth construction</title>"
            "<style>body{font:16px system-ui;max-width:1200px;margin:24px auto}"
            "img{width:100%}</style><h1>Head and mouth construction</h1>"
            "<p>Same 575 bank pairs, guide geometry, hard targets and fresh envelope. "
            "25 m profiles plus a separate dense check; no tolerance relaxation. "
            "Raster failures remain a production rejection.</p>"
            "<p><a href='comparison.json'>Decision and provenance</a> | "
            "<a href='controls/index.html'>Unchanged layout and fixed/native controls</a></p>"
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
                "model_id": BOUNDARY_MODEL_ID,
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
