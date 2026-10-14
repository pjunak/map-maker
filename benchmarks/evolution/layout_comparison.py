"""Compare bounded automatic-guide relocation with unchanged construction controls."""

import argparse
from dataclasses import asdict, replace
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from benchmarks.evolution.constrained import FittedSurface
from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.network_comparison import routing
from benchmarks.evolution.network_fixture import FIXTURE_ID, fixture
from benchmarks.evolution.network_report import render, render_routes
from benchmarks.evolution.patch_comparison import inspect_surface
from benchmarks.evolution.patch_comparison import run as run_controls
from benchmarks.evolution.valley_layout import LAYOUT_MODEL_ID, GuideLayout, relocate_guides
from benchmarks.evolution.valley_patches import prepare_patches
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid


def run(output: Path, *, figures: bool = True) -> dict[str, Any]:
    original_identity = identity()
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    try:
        # Preserve both rejected native controls and the fresh fixed-guide case.
        # This is one existing comparison family, not a new quality framework.
        controls = run_controls(output / "fixed-guides", figures=figures)
        references = {row["case"]: row for row in controls["rows"]}
        rows: list[dict[str, Any]] = []
        delivered: dict[str, FittedSurface] = {}
        layouts: dict[str, GuideLayout] = {}
        for spacing, rotated in ((1000.0, False), (500.0, False), (250.0, False), (250.0, True)):
            label = f"dx{spacing:g}" + ("-rotated90" if rotated else "")
            directory = output / label
            directory.mkdir()
            f = fixture(spacing, rotate=rotated)
            source_hash = numeric_hash(f.source.ground_m)
            tick = perf_counter()
            layout = relocate_guides(f, movable_edges=f.network.required)
            candidate = replace(f, network=layout.network)
            patch = prepare_patches(candidate, f.source, mode="fresh")
            field = patch.deliver()
            repeated_layout = relocate_guides(f, movable_edges=f.network.required)
            repeated = prepare_patches(
                replace(f, network=repeated_layout.network), f.source, mode="fresh"
            ).deliver()
            if (
                layout.network.identity() != repeated_layout.network.identity()
                or not np.array_equal(field.ground_m, repeated.ground_m)
            ):
                raise RuntimeError(
                    "Repeated guide construction changed geometry or Float32 ground."
                )
            seconds = perf_counter() - tick
            original_count = len(f.network.receivers)
            routes: list[dict[str, Any]] = []
            for head in f.network.heads():
                original_route = f.network.route(int(head))
                route = layout.network.route(int(head))
                retained = route[route < original_count]
                owners = layout.original_edge_for_node[route[:-1]]
                collapsed = owners[np.concatenate(([True], owners[1:] != owners[:-1]))]
                if not np.array_equal(original_route, retained) or not np.array_equal(
                    original_route[:-1], collapsed
                ):
                    raise RuntimeError(
                        "Layout lost an original source, junction, reach or terminal."
                    )
                routes.append(
                    {
                        "head": int(head),
                        "terminal": int(original_route[-1]),
                        "original_nodes": original_route.tolist(),
                        "candidate_nodes": route.tolist(),
                        "matched_original_edges": collapsed.tolist(),
                    }
                )
            if not np.array_equal(
                f.network.coordinates_m, layout.network.coordinates_m[:original_count]
            ):
                raise RuntimeError("Layout moved a fixed original vertex.")
            local, local_field = inspect_surface(candidate, patch, patch.sample, rotated=rotated)
            raster, raster_field = inspect_surface(candidate, patch, field.sample, rotated=rotated)
            for metrics in (local, raster):
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
                    raise RuntimeError("Relocated construction violated a hard input or envelope.")
            reference = references["fresh-" + label]
            row: dict[str, Any] = {
                "case": label,
                "status": "constructed",
                "spacing_m": spacing,
                "rotated90": rotated,
                "source_hash": source_hash,
                "source_network_identity": layout.source_network_identity,
                "network_identity": layout.network.identity(),
                "layout_settings": asdict(layout.settings),
                "patch_settings": asdict(patch.settings),
                "moves": [asdict(move) for move in layout.moves],
                "search_candidates_checked": layout.candidates_checked,
                "original_node_count": original_count,
                "candidate_node_count": len(layout.network.receivers),
                "matched_routes": routes,
                "input_roles": {
                    "guides": "explicit automatic-edge mask; every original vertex stays fixed",
                    "hard_heights_divide_coast": "unchanged final/persistent requirements",
                    "relief": "same generated initial hypothesis",
                    "envelope": "unchanged fresh 600 m / 120 km3 construction; no fill",
                    "history": "no time evolution or simulated erosion",
                },
                "control_case": "fresh-" + label,
                "control": {scope: reference[scope] for scope in ("local", "delivery")},
                "local": local,
                "delivery": raster,
                "bank_probe_counts": {
                    "control": len(reference["local"]["bank_sections"]["rows"]),
                    "candidate": len(local["bank_sections"]["rows"]),
                },
                "coverage_scope": (
                    "same four heads, original vertices/reach ownership and terminals; "
                    "full common-grid coast/divide diagnostics, not prescribed catchment areas"
                ),
                "delivery_projection": field.diagnostics,
                "repeat_matches": True,
                "construction_seconds": seconds,
            }
            arrays = {
                "source_m": f.source.ground_m,
                "ground_m": field.ground_m,
                "local_common_ground_m": local_field.ground_m,
                "delivered_common_ground_m": raster_field.ground_m,
                "original_coordinates_m": f.network.coordinates_m,
                "original_receivers": f.network.receivers,
                "coordinates_m": layout.network.coordinates_m,
                "receivers": layout.network.receivers,
                "movable_original_edges": layout.original_movable_edges,
                "original_edge_for_node": layout.original_edge_for_node,
                "hard_points_m": f.hard.points_m,
                "hard_heights_m": f.hard.heights_m,
                "patch_segments_m": patch.segments_m,
                "patch_bed_heights_m": patch.bed_heights_m,
                "anchor_corrections_m": patch.anchor_corrections_m,
            }
            with (directory / "fields.npz").open("xb") as stream:
                np.savez_compressed(stream, allow_pickle=False, **arrays)
            row["numeric_hashes"] = {name: numeric_hash(a) for name, a in arrays.items()}
            if figures:
                render(
                    directory / "ground.png",
                    candidate,
                    {
                        "Relocated local valleys": patch.sample,
                        "Relocated Float32 raster": field.sample,
                    },
                    label,
                )
                render_routes(
                    directory / "local-delivery.png",
                    candidate,
                    {
                        "Local field at 125 m": (local_field, routing(local_field)),
                        "Delivered raster at 125 m": (raster_field, routing(raster_field)),
                    },
                    label,
                )
                with np.load(
                    output / "fixed-guides" / ("fresh-" + label) / "fields.npz", allow_pickle=False
                ) as saved:
                    common_grid = EvolutionGrid(f.source.grid.width_m, f.source.grid.height_m, 125)
                    previous = FittedSurface(common_grid, saved["delivered_common_ground_m"], {})
                render_routes(
                    directory / "before-after.png",
                    f,
                    {
                        "Original automatic guide": (previous, routing(previous)),
                        "Guide avoids the hard target": (raster_field, routing(raster_field)),
                    },
                    label,
                    networks={
                        "Original automatic guide": f.network,
                        "Guide avoids the hard target": layout.network,
                    },
                )
            row["artifact_hashes"] = {
                p.name: file_sha256(p) for p in sorted(directory.iterdir()) if p.is_file()
            }
            if source_hash != numeric_hash(f.source.ground_m):
                raise RuntimeError("Guide comparison mutated its initial relief.")
            write_json(directory / "result.json", row)
            rows.append(row)
            delivered[label] = field
            layouts[label] = layout
            print(
                f"Compared {label}: relocated delivery "
                f"{raster['common_routing']['heads_within_1000m_of_authored_outlet']}/4 heads",
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
        xy = layouts["dx250"].network.coordinates_m
        rotated_xy = np.stack((24000 - xy[:, 1], xy[:, 0]), axis=-1)
        geometry_rotation = float(
            np.max(np.abs(rotated_xy - layouts["dx250-rotated90"].network.coordinates_m))
        )
        failed = [
            f"{row['case']}: {scope}/{gate}"
            for row in rows
            for scope in ("local", "delivery")
            for gate, passed in row[scope]["quality_gates"].items()
            if not passed
        ]
        if rotation > 0.001 or geometry_rotation > 1e-6:
            failed.append("rotation exceeds the 1 mm height / 1 micrometre geometry gate")
        if identity() != original_identity:
            raise RuntimeError("Source/runtime identity changed during guide comparison.")
        report: dict[str, Any] = {
            "status": "complete",
            "model_id": LAYOUT_MODEL_ID,
            "fixture_id": FIXTURE_ID,
            "identity": original_identity,
            "rows": rows,
            "control_manifest_sha256": file_sha256(output / "fixed-guides" / "comparison.json"),
            "rotation_maximum_ground_difference_m": rotation,
            "rotation_maximum_geometry_difference_m": geometry_rotation,
            "quality_decision": {
                "status": "rejected" if failed else "passed-this-fixture-only",
                "production_eligible": False,
                "failed_gates": failed,
            },
            "seconds": perf_counter() - started,
            "peak_resident_bytes": peak_resident_bytes(),
        }
        entries: list[str] = []
        for row in rows:
            label = escape(row["case"])
            entries.append(
                f"<h2>{label}</h2><a href='{label}/result.json'>Complete measurements</a>"
                + (
                    f"<img src='{label}/before-after.png'><img src='{label}/local-delivery.png'>"
                    if figures
                    else ""
                )
            )
        (output / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Hard-target-aware valley layout</title>"
            "<style>body{font:16px system-ui;max-width:1300px;margin:24px auto}"
            "img{width:100%}</style>"
            "<h1>Automatic guide placement and hard height targets</h1>"
            "<p>Same source, hard targets, original vertices, terminal coverage "
            "and fresh envelope. "
            "Only explicitly automatic guides move within bounded corridors. "
            "Bank/profile and coarse-grid "
            "failures remain visible; this is not a production generator.</p>"
            "<p><a href='comparison.json'>Decision and provenance</a> | "
            "<a href='fixed-guides/index.html'>Unchanged fixed/native "
            "and fresh-guide controls</a></p>" + "".join(entries),
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
                "model_id": LAYOUT_MODEL_ID,
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
