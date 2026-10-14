"""Compare one constrained range/valley/lowland surface in the base environment."""

import argparse
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.constrained import FittedSurface, HardHeights, InfeasibleSurface, fit
from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.metrics import terminal_labels
from benchmarks.evolution.network_fixture import FIXTURE_ID, NetworkFixture, fixture
from benchmarks.evolution.network_report import render, render_routes
from benchmarks.evolution.paths import Sampler, anchor_residuals, measure_paths
from benchmarks.evolution.physical import prepare
from benchmarks.evolution.physical_comparison import matched_gates
from benchmarks.evolution.reconstruction import summarize
from benchmarks.evolution.sensitivity import compare_graphs
from benchmarks.evolution.surface import FlowAlignedSurface
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid
from map_maker.terrain.pipeline.hydrology import receiver_contributing_area, steepest_flow_receivers
from map_maker.terrain.pipeline.landforms import regional_incision_budget


def routing(field: FittedSurface) -> NDArray[np.int64]:
    return steepest_flow_receivers(
        field.ground_m.astype(np.float64),
        np.ones(field.grid.shape, dtype=np.bool_),
        x_spacing_km=field.grid.spacing_m / 1000,
        y_spacing_km=field.grid.spacing_m / 1000,
        terminal_mask=field.ground_m == 0,
    )[0]


def rerouted_numbers(
    f: NetworkFixture, z: NDArray[np.float32], *, rotated: bool, grid: EvolutionGrid | None = None
) -> dict[str, Any]:
    field = FittedSurface(f.source.grid if grid is None else grid, z, {})
    grid = field.grid
    r = routing(field)
    labels = terminal_labels(r)
    flat_z = z.ravel()
    y, x = np.indices(grid.shape, dtype=np.float64) * grid.spacing_m
    original_x = y if rotated else x
    terminal_x = (labels // grid.shape[1] if rotated else labels % grid.shape[1]) * grid.spacing_m
    interior = np.ones(grid.shape, dtype=np.bool_)
    interior[[0, -1]] = False
    interior[:, [0, -1]] = False
    away = interior & (np.abs(original_x - 16000) > 1000)
    across = away & ((original_x - 16000) * (terminal_x - 16000) < 0)
    heads: list[dict[str, Any]] = []
    for head in f.network.heads():
        point = f.network.coordinates_m[head]
        col, row = np.rint(point / grid.spacing_m).astype(int)
        end = int(labels[row, col])
        end_y, end_x = divmod(end, grid.shape[1])
        target = f.network.coordinates_m[f.network.route(int(head))[-1]]
        distance = float(
            np.hypot(end_x * grid.spacing_m - target[0], end_y * grid.spacing_m - target[1])
        )
        heads.append(
            {
                "head": int(head),
                "sampled_node": int(row * grid.shape[1] + col),
                "terminal": end,
                "terminal_m": [end_x * grid.spacing_m, end_y * grid.spacing_m],
                "outlet_error_m": distance,
                "coast_reached": bool(flat_z[end] == 0),
            }
        )
    return {
        "internal_terminal_count": int(np.count_nonzero(interior & (r < 0))),
        "interior_stations_not_reaching_coast": int(
            np.count_nonzero(interior & (flat_z[labels] > 0))
        ),
        "interior_station_count": int(interior.sum()),
        "cross_divide_stations": int(across.sum()),
        "tested_divide_stations": int(away.sum()),
        "heads": heads,
        "heads_within_1000m_of_authored_outlet": sum(
            h["coast_reached"] and h["outlet_error_m"] <= 1000 for h in heads
        ),
        "evaluation_spacing_m": grid.spacing_m,
        "scope": "raw D8 routing of actual Float32 ground; no fill or imposed network receivers",
        "head_sampling": (
            "nearest process node, with 1000 m outlet tolerance; not exact streamline tracing"
        ),
    }


def constraints(f: NetworkFixture, sampler: Sampler) -> dict[str, Any]:
    grid = f.source.grid
    x, y = np.meshgrid(
        np.arange(0, grid.width_m + 1, 125.0), np.arange(0, grid.height_m + 1, 125.0)
    )
    baseline, current = f.source.sample(x, y), sampler(x, y)
    delta = baseline.astype(np.float64) - current
    cap = regional_incision_budget(x / 1000, y / 1000, f.global_limit_m, f.regions)
    x0, y0, x1, y1 = f.protected_divide_km.bounds
    protected = (x >= x0 * 1000) & (x <= x1 * 1000) & (y >= y0 * 1000) & (y <= y1 * 1000)
    anchors = anchor_residuals(sampler, f.hard.points_m, f.hard.heights_m)
    return {
        "sample_spacing_m": 125.0,
        "sample_count": int(x.size),
        "cut_over_native_limit_samples": int(np.count_nonzero(delta > cap + 0.01)),
        "fill_samples": int(np.count_nonzero(delta < -0.01)),
        "protected_change_samples": int(np.count_nonzero(np.abs(delta[protected]) > 0.01)),
        "maximum_cut_m": float(delta.max()),
        "maximum_fill_m": max(0.0, -float(delta.min())),
        "maximum_protected_change_m": float(np.abs(delta[protected]).max()),
        "anchors": anchors,
    }


def incompatible(f: NetworkFixture) -> HardHeights:
    points = f.network.coordinates_m
    upper = f.source.sample(*points.T).astype(np.float64)
    lower = (
        FittedSurface(f.source.grid, (f.source.ground_m - f.limits_m).astype(np.float32), {})
        .sample(*points.T)
        .astype(np.float64)
    )
    for a in np.flatnonzero(f.network.required):
        b = int(f.network.receivers[a])
        if lower[a] + 2 < upper[b] - 2:
            return HardHeights(points[[int(a), b]], np.array([lower[a] + 1, upper[b] - 1]))
    raise ValueError("Fixture has no individually admissible uphill hard-height pair.")


def run(output: Path) -> dict[str, Any]:
    original_identity = identity()
    output.mkdir(parents=True, exist_ok=False)
    start = perf_counter()
    rows: list[dict[str, Any]] = []
    fitted: list[FittedSurface] = []
    try:
        for spacing, rotated in ((1000.0, False), (500.0, False), (250.0, False), (500.0, True)):
            label = f"dx{spacing:g}" + ("-rotated90" if rotated else "")
            directory = output / label
            directory.mkdir()
            t = perf_counter()
            f = fixture(spacing, rotate=rotated)
            source = f.source.ground_m.astype(np.float64)
            source_hash = numeric_hash(source)
            receivers = routing(f.source)
            area = receiver_contributing_area(
                source,
                np.ones(source.shape, dtype=np.bool_),
                receivers,
                cell_area_km2=(spacing / 1000) ** 2,
            )
            required = (receivers >= 0) & (area >= 25.0)
            triangle = FlowAlignedSurface(f.source.grid, source, receivers, required)
            physical = prepare(triangle)
            candidate = fit(f.source.grid, f.network, source, f.limits_m, f.target_m, f.hard)
            fitted.append(candidate)
            prep_seconds = perf_counter() - t
            samplers = {
                "source": f.source.sample,
                "triangle": triangle.sample,
                "physical": physical.sample,
                "constrained": candidate.sample,
            }
            result: dict[str, Any] = {
                "case": label,
                "fixture_id": FIXTURE_ID,
                "spacing_m": spacing,
                "rotated90": rotated,
                "preparation_seconds": prep_seconds,
                "source_hash": source_hash,
                "network_identity": f.network.identity(),
                "candidate_hash": numeric_hash(candidate.ground_m),
                "solver": candidate.diagnostics,
                "profiles": {},
                "summaries": {},
                "constraints": {},
                "rerouted": {},
                "common_grid_rerouted": {},
                "gates": {},
            }
            nodal = f.source.sample(*f.network.coordinates_m.T).astype(np.float64)
            for stations in (100.0, 25.0):
                key = f"{stations:g}m"
                measured = {
                    name: measure_paths(f.network, sampler, nodal, stations)
                    for name, sampler in samplers.items()
                }
                result["profiles"][key] = measured
                result["summaries"][key] = {name: summarize(m) for name, m in measured.items()}
                result["gates"][key] = matched_gates(measured["source"], measured["constrained"])
            yy, xx = np.indices(f.source.grid.shape, dtype=np.float64) * spacing
            for name, sampler in samplers.items():
                result["constraints"][name] = constraints(f, sampler)
                result["rerouted"][name] = rerouted_numbers(f, sampler(xx, yy), rotated=rotated)
            common_grid = EvolutionGrid(candidate.grid.width_m, candidate.grid.height_m, 125.0)
            cy, cx = np.indices(common_grid.shape, dtype=np.float64) * common_grid.spacing_m
            common_fields: dict[str, tuple[FittedSurface, NDArray[np.int64]]] = {}
            for name, sampler in samplers.items():
                field = FittedSurface(common_grid, sampler(cx, cy), {})
                result["common_grid_rerouted"][name] = rerouted_numbers(
                    f, field.ground_m, rotated=rotated, grid=common_grid
                )
                if name in ("source", "constrained"):
                    common_fields[name] = (field, routing(field))
            actual = result["common_grid_rerouted"]["constrained"]
            control = result["common_grid_rerouted"]["source"]
            limits = result["constraints"]["constrained"]
            result["quality_gates"] = {
                "all_required_profiles_descend": all(
                    result["summaries"][key]["constrained"]["unresolved_routes"] == 0
                    for key in ("100m", "25m")
                ),
                "sampled_native_cut_no_fill_and_divide": all(
                    limits[key] == 0
                    for key in (
                        "cut_over_native_limit_samples",
                        "fill_samples",
                        "protected_change_samples",
                    )
                ),
                "hard_height_residual_within_1cm": not limits["anchors"]["violated_indices"],
                "all_heads_reach_authored_outlets": (
                    actual["heads_within_1000m_of_authored_outlet"] == len(f.network.heads())
                ),
                "no_additional_internal_terminals": (
                    actual["internal_terminal_count"] <= control["internal_terminal_count"]
                ),
                "no_geographic_divide_crossing": actual["cross_divide_stations"] == 0,
            }
            # Reject an impossible ordering even though each height individually fits its local cap.
            conflict = incompatible(f)
            try:
                fit(f.source.grid, f.network, source, f.limits_m, f.target_m, conflict)
            except InfeasibleSurface as exc:
                result["incompatible_route"] = {
                    "status": "rejected",
                    "reason": str(exc),
                    "points_m": conflict.points_m.tolist(),
                    "heights_m": conflict.heights_m.tolist(),
                }
            else:
                raise ValueError("Incompatible hard-height route was incorrectly admitted.")
            repeated = fit(f.source.grid, f.network, source, f.limits_m, f.target_m, f.hard)
            if not np.array_equal(candidate.ground_m, repeated.ground_m):
                raise ValueError("Repeated surface fit is not deterministic in this runtime.")
            result["repeat_hash_matches"] = True
            result["routing_change"] = compare_graphs(
                f.source.grid, receivers, candidate.grid, routing(candidate)
            )
            with (directory / "fields.npz").open("xb") as stream:
                np.savez_compressed(
                    stream,
                    source_m=f.source.ground_m,
                    ground_m=candidate.ground_m,
                    conservative_limit_m=f.limits_m,
                    target_m=f.target_m,
                    coordinates_m=f.network.coordinates_m,
                    receivers=f.network.receivers,
                    hard_points_m=f.hard.points_m,
                    hard_heights_m=f.hard.heights_m,
                )
            render(directory / "comparison.png", f, samplers, label)
            render_routes(directory / "routing.png", f, common_fields, label)
            result["artifacts"] = {
                name: file_sha256(directory / name)
                for name in ("fields.npz", "comparison.png", "routing.png")
            }
            if numeric_hash(source) != source_hash:
                raise ValueError("A comparison mutated its source ground.")
            write_json(directory / "result.json", result)
            rows.append({k: v for k, v in result.items() if k != "profiles"})
            uphill = result["summaries"]["25m"]["constrained"]["unresolved_routes"]
            captured = result["rerouted"]["constrained"]["heads_within_1000m_of_authored_outlet"]
            print(
                f"Compared {label}: {uphill} uphill routes; "
                f"{captured}/4 raw-routing heads reach their outlet",
                flush=True,
            )

        sensitivity: list[dict[str, Any]] = []
        for other in (fitted[0], fitted[2]):
            sensitivity.append(
                {
                    "baseline_spacing_m": 500.0,
                    "other_spacing_m": other.grid.spacing_m,
                    **compare_graphs(
                        fitted[1].grid, routing(fitted[1]), other.grid, routing(other)
                    ),
                }
            )
        rotation_error = float(
            np.abs(fitted[1].ground_m.astype(np.float64) - np.rot90(fitted[3].ground_m)).max()
        )
        if identity() != original_identity:
            raise ValueError("Source/runtime identity changed during the comparison.")
        failed = [
            f"{row['case']}: {name}"
            for row in rows
            for name, passed in row["quality_gates"].items()
            if not passed
        ]
        if rotation_error > 0.001:
            failed.append("rotation: ground difference exceeds 1 mm")
        result = {
            "status": "complete",
            "quality_decision": {
                "status": "rejected" if failed else "passed-this-fixture-only",
                "production_eligible": False,
                "failed_gates": failed,
            },
            "fixture_id": FIXTURE_ID,
            "identity": original_identity,
            "rows": rows,
            "fitted_routing_sensitivity": sensitivity,
            "rotation_maximum_ground_difference_m": rotation_error,
            "seconds": perf_counter() - start,
            "peak_resident_bytes": peak_resident_bytes(),
            "acceptance": (
                "one public constrained fixture; research-only, not production acceptance"
            ),
        }
        body = "".join(
            f"<h2>{escape(row['case'])}</h2><p><a href='{row['case']}/result.json'>"
            f"Full evidence</a></p><img src='{row['case']}/comparison.png'>"
            f"<img src='{row['case']}/routing.png'>"
            for row in rows
        )
        (output / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Constrained river terrain</title>"
            "<style>body{font:16px system-ui;max-width:1300px;margin:24px auto}"
            "img{width:100%}</style>"
            "<h1>Constrained range/valley/lowland comparison</h1><p>Research fixture. "
            "Downhill river guides and hard-height/budget admission are separate from actual "
            "rerouted catchments. All four panels show the same authored physical network. "
            "Blue ground tint is elevation, not water. No depression filling was used for "
            "the rerouting diagnostics.</p><a href='comparison.json'>Summary and provenance</a>"
            + "<h2>Quality decision: "
            + escape(result["quality_decision"]["status"])
            + "</h2><ul>"
            + "".join(f"<li>{escape(item)}</li>" for item in failed)
            + "</ul>"
            + body,
            encoding="utf-8",
        )
        write_json(output / "comparison.json", result)
        return result
    except Exception as exc:
        write_json(
            output / "incomplete.json", {"status": "failed", "error": str(exc), "rows": rows}
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New comparison directory")
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
