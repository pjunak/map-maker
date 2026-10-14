"""Frozen-graph sensitivity at identical physical coordinates, without rerouting."""

from itertools import combinations
from math import isclose
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.frozen import FrozenCase
from benchmarks.evolution.metrics import terminal_labels
from benchmarks.evolution.surface import validate_graph
from map_maker.terrain.domain.evolution import EvolutionGrid


def compare_graphs(
    first_grid: EvolutionGrid,
    first_receivers: NDArray[np.int64],
    second_grid: EvolutionGrid,
    second_receivers: NDArray[np.int64],
) -> dict[str, Any]:
    if first_grid.width_m != second_grid.width_m or first_grid.height_m != second_grid.height_m:
        raise ValueError("Sensitivity requires the same physical domain.")
    spacing = max(first_grid.spacing_m, second_grid.spacing_m)
    for grid, receivers in ((first_grid, first_receivers), (second_grid, second_receivers)):
        if not isclose(
            spacing / grid.spacing_m, round(spacing / grid.spacing_m), rel_tol=0, abs_tol=1.0e-10
        ):
            raise ValueError("Sensitivity requires nested physical grid stations.")
        validate_graph(receivers, grid.shape)
    x, y = np.meshgrid(
        np.arange(1, round(first_grid.width_m / spacing)) * spacing,
        np.arange(1, round(first_grid.height_m / spacing)) * spacing,
    )
    points = np.stack((x.ravel(), y.ravel()), axis=-1)
    endpoints: list[NDArray[np.float64]] = []
    directions: list[NDArray[np.int64]] = []
    sides: list[NDArray[np.int8]] = []
    for grid, receivers in ((first_grid, first_receivers), (second_grid, second_receivers)):
        cols, rows = np.rint(points / grid.spacing_m).astype(np.int64).T
        terminals = terminal_labels(receivers)[rows, cols]
        ty, tx = np.divmod(terminals, grid.shape[1])
        endpoints.append(np.stack((tx, ty), axis=-1) * grid.spacing_m)
        side = (
            (ty == 0).astype(np.int8)
            + 2 * (tx == grid.shape[1] - 1).astype(np.int8)
            + 4 * (ty == grid.shape[0] - 1).astype(np.int8)
            + 8 * (tx == 0).astype(np.int8)
        )
        sides.append(side)
        targets = receivers[rows, cols]
        ry, rx = np.divmod(np.maximum(targets, 0), grid.shape[1])
        steps = np.stack((rx - cols, ry - rows), axis=-1)
        steps[targets < 0] = 0
        directions.append(steps)
    shifts = np.linalg.norm(endpoints[1] - endpoints[0], axis=-1)
    return {
        "shared_station_count": len(points),
        "shared_spacing_m": spacing,
        "station_domain": "all interior nodes of the coarser grid; no nearest-node snapping",
        "receiver_direction_change_fraction": float(
            np.mean(np.any(directions[0] != directions[1], axis=-1))
        ),
        "terminal_shift_rms_m": float(np.sqrt(np.mean(shifts**2))),
        "terminal_shift_max_m": float(shifts.max()),
        "terminal_shift_over_coarse_cell_fraction": float(np.mean(shifts > spacing)),
        "terminal_boundary_side_change_fraction": float(
            np.count_nonzero(sides[0] != sides[1]) / len(points)
        ),
    }


def sensitivity_pairs(cases: list[FrozenCase]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    keys = ("case", "seed", "angle_deg", "history")
    for first, second in combinations(cases, 2):
        if any(
            k not in first.record or k not in second.record or first.record[k] != second.record[k]
            for k in keys
        ):
            continue
        if first.grid.width_m != second.grid.width_m or first.grid.height_m != second.grid.height_m:
            continue
        a, b = first.record.get("budget", {}), second.record.get("budget", {})
        result.append(
            {
                "first_source": str(first.result_path),
                "second_source": str(second.result_path),
                "first_spacing_m": first.grid.spacing_m,
                "second_spacing_m": second.grid.spacing_m,
                "first_solver_budget": a,
                "second_solver_budget": b,
                "measurements": compare_graphs(
                    first.grid, first.receivers, second.grid, second.receivers
                ),
            }
        )
    return result
