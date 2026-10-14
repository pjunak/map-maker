"""Measure coupled physical channel paths against verified frozen controls."""

import argparse
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.frozen import GRAPH_ROLE, discover, load_case
from benchmarks.evolution.paths import PROFILE_TOLERANCE_M, ChannelPaths, measure_paths
from benchmarks.evolution.physical import (
    PHYSICAL_PATH_ID,
    PathSettings,
    constraint_samples,
    geometry_numbers,
    grid_points,
    prepare,
)
from benchmarks.evolution.physical_report import render, write_index
from benchmarks.evolution.reconstruction import STATION_SPACINGS_M, summarize
from benchmarks.evolution.sensitivity import sensitivity_pairs
from benchmarks.evolution.surface import FlowAlignedSurface
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import file_sha256


def matched_gates(control: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Coverage cannot be inferred from equal counts or equal sample counts."""
    before = {(r["head"], r["terminal"]): r for r in control["routes"]}
    after = {(r["head"], r["terminal"]): r for r in candidate["routes"]}

    def edges(result: dict[str, Any]) -> set[tuple[int, int]]:
        return {(r["source"], r["target"]) for r in result["edges"]}

    complete = (
        before.keys() == after.keys()
        and edges(control) == edges(candidate)
        and len(edges(control)) == len(control["edges"]) == len(candidate["edges"])
        and len(before) == len(control["routes"]) == len(after) == len(candidate["routes"])
    )
    regressions: list[dict[str, Any]] = []
    for key in before.keys() & after.keys():
        if (
            before[key]["maximum_excursion_m"] <= PROFILE_TOLERANCE_M
            and after[key]["maximum_excursion_m"] > PROFILE_TOLERANCE_M
        ):
            regressions.append(
                {
                    "head": key[0],
                    "terminal": key[1],
                    "maximum_excursion_m": after[key]["maximum_excursion_m"],
                }
            )
    return {
        "complete_matched_coverage": complete,
        "newly_uphill_routes": regressions,
        "new_rises_over_10m": sum(r["maximum_excursion_m"] > 10 for r in regressions),
    }


def run(
    sources: list[Path],
    output: Path,
    *,
    settings: PathSettings | None = None,
    maximum_cut_m: float = 30.0,
    maximum_fill_m: float = 0.0,
) -> dict[str, Any]:
    start = perf_counter()
    settings = settings or PathSettings()
    paths, omissions = discover(sources)
    cases = [load_case(p) for p in paths]
    original_identity = identity()
    output.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    try:
        maximum_m = max(1.0, *(float(case.ground_m.max()) for case in cases))
        for index, case in enumerate(cases):
            t = perf_counter()
            directory = output / f"case-{index:02d}"
            directory.mkdir()
            field = FlowAlignedSurface(case.grid, case.ground_m, case.receivers, case.required)
            network = ChannelPaths(case.grid, case.receivers, case.required)
            candidate = prepare(field, settings)
            result: dict[str, Any] = {
                "label": f"{case.result_path.parent.parent.name} / {case.record['id']}",
                "folder": directory.name,
                "status": "compared",
                "model_id": PHYSICAL_PATH_ID,
                "source_result": str(case.result_path),
                "source_hashes": case.hashes,
                "source_identity": case.record["identity"],
                "measurement_identity": original_identity,
                "grid": case.record["grid"],
                "settings": asdict(settings),
                "graph_role": GRAPH_ROLE,
                "profiles": {},
                "summaries": {},
                "matched_gates": {},
                "seconds": {},
                "graph_identity": network.identity(),
                "geometry_identity": candidate.paths.identity(),
                "geometry": {
                    "control": geometry_numbers(network),
                    "candidate": geometry_numbers(candidate.paths),
                },
            }
            original = grid_points(field)
            delta = np.linalg.norm(candidate.paths.coordinates_m - original, axis=-1)
            result["geometry"].update(
                moved_nodes=int(np.count_nonzero(delta)),
                maximum_displacement_m=float(delta.max()),
                minimum_fan_area_ratio=float(
                    candidate.determinants_m2.min() / (case.grid.spacing_m**2 * 0.5)
                ),
                fixed_heads_junctions_and_terminals=True,
                effective_corridor_m=min(settings.displacement_m, case.grid.spacing_m * 0.24),
            )
            result["seconds"]["preparation"] = perf_counter() - t
            for spacing in STATION_SPACINGS_M:
                key = f"{spacing:g}m"
                result["profiles"][key], result["summaries"][key] = {}, {}
                for name, geometry, sampler in (
                    ("bilinear", network, field.bilinear),
                    ("triangle", network, field.sample),
                    ("physical", candidate.paths, candidate.sample),
                ):
                    t = perf_counter()
                    measured = measure_paths(geometry, sampler, case.ground_m, spacing)
                    result["profiles"][key][name] = measured
                    result["summaries"][key][name] = summarize(measured)
                    result["seconds"][f"{name}_{key}"] = perf_counter() - t
                pair = result["profiles"][key]
                result["matched_gates"][key] = matched_gates(pair["triangle"], pair["physical"])
                if not result["matched_gates"][key]["complete_matched_coverage"]:
                    raise ValueError("Candidate lost required edges or matched route endpoints.")
            # Same fixed coordinates for both surfaces, plus displaced path vertices.
            centres = (original[:-1, :-1] + original[1:, 1:]) * 0.5
            points = np.concatenate(
                (
                    original.reshape(-1, 2),
                    centres.reshape(-1, 2),
                    candidate.paths.coordinates_m.reshape(-1, 2)[case.required.ravel()],
                )
            )
            result["constraints"] = {}
            for name, sampler in (("triangle", field.sample), ("physical", candidate.sample)):
                result["constraints"][name] = constraint_samples(
                    sampler,
                    field.bilinear,
                    points,
                    maximum_cut_m=maximum_cut_m,
                    maximum_fill_m=maximum_fill_m,
                    anchors_m=np.empty((0, 2)),
                    anchor_heights_m=np.empty(0),
                )
            result["constraint_sampling"] = (
                "all original grid vertices, original cell centres, "
                "and displaced required vertices; "
                "not a continuous field bound; no authored anchors supplied by this cohort"
            )
            failed_gates: list[str] = []
            result["failed_gates"] = failed_gates
            if any(g["newly_uphill_routes"] for g in result["matched_gates"].values()):
                failed_gates.append("new uphill routes")
            for name in ("cut_violations", "fill_violations"):
                if result["constraints"]["physical"][name]:
                    failed_gates.append(name)
            if (
                result["geometry"]["candidate"]["d8_length_fraction"]
                >= result["geometry"]["control"]["d8_length_fraction"]
            ):
                failed_gates.append("no measured reduction in D8 alignment")
            t = perf_counter()
            render(directory / "comparison.png", result["label"], candidate, maximum_m)
            result["seconds"]["render"] = perf_counter() - t
            coordinates = candidate.paths.coordinates_m
            with (directory / "geometry.npz").open("xb") as stream:
                np.savez_compressed(stream, coordinates_m=coordinates)
            result["geometry_array_sha256"] = numeric_hash(coordinates)
            result["artifacts"] = {
                name: file_sha256(directory / name) for name in ("comparison.png", "geometry.npz")
            }
            case.verify_unchanged()
            write_json(directory / "result.json", result)
            rows.append(
                {k: v for k, v in result.items() if k not in ("profiles", "source_identity")}
            )
            print(f"Compared {result['label']}; failed gates: {result['failed_gates']}", flush=True)
        for case in cases:
            case.verify_unchanged()
        if identity() != original_identity:
            raise ValueError("Source/runtime identity changed during the comparison.")
        result = {
            "status": "complete",
            "model_id": PHYSICAL_PATH_ID,
            "identity": original_identity,
            "rows": rows,
            "frozen_graph_sensitivity": sensitivity_pairs(cases),
            "sensitivity_role": (
                "same domain, seed, history and orientation; original frozen receivers only; "
                "not rerouting the physical candidate or identifying continuous catchments"
            ),
            "source_workers_without_completed_states": omissions,
            "seconds": perf_counter() - start,
            "process_lifetime_peak_bytes": peak_resident_bytes(),
            "memory_scope": "whole serial comparison, inputs, profiles and rendering",
            "acceptance": "research-only; no production promotion",
            "limits": [
                "fixed graph topology is not unchanged geographic catchments/divides",
                "bed node heights retained, including existing nodal uphill",
                "cut/fill and anchors require independent whole-field admission",
                "C0 mesh creases and coarse polyline corners remain",
                "lower D8 alignment alone is not a realism or rotation acceptance score",
                "no lake storage, erosion ledger or physical water-validity claim",
            ],
        }
        write_index(output, rows)
        write_json(output / "comparison.json", result)
        return result
    except Exception as exc:
        write_json(
            output / "incomplete.json", {"status": "failed", "error": str(exc), "rows": rows}
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True, help="New comparison directory")
    parser.add_argument("--maximum-cut-m", type=float, default=30.0)
    parser.add_argument("--maximum-fill-m", type=float, default=0.0)
    args = parser.parse_args()
    run(
        args.source,
        args.output,
        maximum_cut_m=args.maximum_cut_m,
        maximum_fill_m=args.maximum_fill_m,
    )


if __name__ == "__main__":
    main()
