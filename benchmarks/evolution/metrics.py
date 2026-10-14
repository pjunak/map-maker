"""Common physical-scale measures; finite samples do not certify river hydraulics."""

from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.channel_profiles import measure_channels
from benchmarks.evolution.reference import Snapshot
from benchmarks.evolution.scenarios import EvolutionFields, FloatArray
from map_maker.terrain.domain.evolution import EvolutionGrid


def sample_grid(
    height: FloatArray, grid: EvolutionGrid, x_m: FloatArray, y_m: FloatArray,
) -> NDArray[np.float32]:
    """An explicit bilinear research reconstruction, not the accepted parent field."""
    x, y = np.broadcast_arrays(x_m / grid.spacing_m, y_m / grid.spacing_m)
    if (not np.all(np.isfinite(x)) or not np.all(np.isfinite(y))
            or np.any(x < 0) or np.any(y < 0)
            or np.any(x > grid.shape[1]-1) or np.any(y > grid.shape[0]-1)):
        raise ValueError("Research samples must lie inside the process grid.")
    column = np.minimum(x.astype(np.int64), grid.shape[1]-2)
    row = np.minimum(y.astype(np.int64), grid.shape[0]-2)
    tx, ty = x-column, y-row
    value = ((1-ty)*((1-tx)*height[row, column] + tx*height[row, column+1])
             + ty*((1-tx)*height[row+1, column] + tx*height[row+1, column+1]))
    return value.astype(np.float32)


def terminal_labels(receivers: NDArray[np.int64]) -> NDArray[np.int64]:
    """Resolve each unique terminal in linear total path work; reject cycles."""
    flow = receivers.ravel()
    if np.any(flow < -1) or np.any(flow >= flow.size):
        raise ValueError("Receiver index is outside the domain.")
    labels = np.full(flow.size, -2, dtype=np.int64)
    for start in range(flow.size):
        if labels[start] >= 0:
            continue
        path: list[int] = []
        node = start
        while labels[node] == -2:
            labels[node] = -3
            path.append(node)
            receiver = int(flow[node])
            if receiver == -1:
                labels[node] = node
                break
            node = receiver
        if labels[node] == -3:
            raise ValueError("Receiver graph contains a cycle.")
        terminal = labels[node]
        labels[path] = terminal
    return labels.reshape(receivers.shape)


def measure(
    snapshot: Snapshot, fields: EvolutionFields, *, channel_area_km2: float = 25.,
) -> dict[str, Any]:
    grid, core = fields.grid, fields.core
    z = snapshot.elevation_m
    labels = terminal_labels(snapshot.receiver)
    boundary = ~core
    terminals = snapshot.receiver < 0
    expected_flow = float(np.sum(snapshot.discharge_m3_per_year[boundary & terminals]))
    receiver = snapshot.receiver.ravel()
    selected = core.ravel() & (receiver >= 0) & (snapshot.area_m2.ravel() >= channel_area_km2*1.e6)
    nodes = np.flatnonzero(selected)
    targets = receiver[nodes]
    sy, sx = np.divmod(nodes, grid.shape[1])
    ty, tx = np.divmod(targets, grid.shape[1])
    dx, dy = tx-sx, ty-sy
    length = np.hypot(dx, dy)*grid.spacing_m
    direction = (np.rint(np.arctan2(dy, dx)/(np.pi/4)).astype(np.int64) % 4)
    direction_length = np.bincount(direction, weights=length, minlength=4)
    gy, gx = np.gradient(z, grid.spacing_m)
    slope = np.hypot(gx, gy)[core]
    stations = measure_channels(
        np.arange(grid.shape[1], dtype=np.float64)*grid.spacing_m,
        np.arange(grid.shape[0], dtype=np.float64)*grid.spacing_m,
        snapshot.receiver, selected.reshape(grid.shape),
        lambda x, y: sample_grid(z, grid, x, y), stations=17,
    )
    return {
        "height_min_m": float(z[core].min()), "height_max_m": float(z[core].max()),
        "height_mean_m": float(z[core].mean()),
        "height_percentiles_m": np.percentile(z[core], [5, 50, 95]).tolist(),
        "slope_percentiles": np.percentile(slope, [50, 95, 99]).tolist(),
        "contributing_area_m2": grid.contributing_area_m2,
        "outlet_discharge_m3_per_year": expected_flow,
        "area_reaching_perimeter_fraction": float(np.mean(boundary.ravel()[labels[core]])),
        "internal_terminal_count": int(np.count_nonzero(core & terminals)),
        "depression_node_fraction": float(np.mean(snapshot.depression_depth_m[core] > .001)),
        "maximum_depression_depth_m": float(snapshot.depression_depth_m[core].max()),
        "selected_channel_area_threshold_km2": channel_area_km2,
        "selected_channel_length_km": float(length.sum()/1000.),
        "selected_channel_density_km_per_km2": float(length.sum()*1000./grid.contributing_area_m2),
        "longest_constant_direction_run_km": longest_straight_run(
            snapshot.receiver, selected.reshape(grid.shape), grid.spacing_m)/1000.,
        "direction_bins": ["horizontal", "down-diagonal", "vertical", "up-diagonal"],
        "direction_length_fractions": (direction_length/length.sum()).tolist()
        if length.size else [0., 0., 0., 0.],
        "reconstruction": "bilinear-process-grid; no authored-point preservation claim",
        "sampled_channel_profiles": stations,
    }


def main_profile(snapshot: Snapshot, grid: EvolutionGrid) -> dict[str, list[float]]:
    """Follow the largest contributing donor of the largest outlet for a longitudinal plot."""
    terminal_labels(snapshot.receiver)
    receiver = snapshot.receiver.ravel()
    area = snapshot.area_m2.ravel()
    terminals = np.flatnonzero(receiver < 0)
    outlet = int(terminals[np.argmax(area[terminals])])
    donors: dict[int, list[int]] = {}
    for node, target in enumerate(receiver):
        if target >= 0:
            donors.setdefault(int(target), []).append(node)
    route = [outlet]
    while route[-1] in donors:
        route.append(max(donors[route[-1]], key=lambda node: (area[node], -node)))
    indices = np.asarray(route, dtype=np.int64)
    rows, columns = np.divmod(indices, grid.shape[1])
    steps = np.hypot(np.diff(rows), np.diff(columns))*grid.spacing_m
    distance = np.concatenate((np.array([0.]), np.cumsum(steps)))
    return {"distance_from_outlet_km": (distance/1000.).tolist(),
            "ground_m": snapshot.elevation_m.ravel()[indices].tolist()}


def longest_straight_run(
    receiver: NDArray[np.int64], selected: NDArray[np.bool_], spacing_m: float,
) -> float:
    """Maximum connected run of one D8 heading, including aligned junctions."""
    terminal_labels(receiver)
    flow = receiver.ravel()
    nodes = np.flatnonzero(selected.ravel() & (flow >= 0))
    targets = flow[nodes]
    sy, sx = np.divmod(nodes, receiver.shape[1])
    ty, tx = np.divmod(targets, receiver.shape[1])
    if np.any(np.maximum(np.abs(ty-sy), np.abs(tx-sx)) != 1):
        raise ValueError("Straight-run measurement requires D8 neighbours.")
    longest = 0.
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            heading = nodes[(ty-sy == dy) & (tx-sx == dx)]
            active = set(int(n) for n in heading)
            starts = active - set(int(n) for n in flow[heading])
            for start in starts:
                count, node = 0, start
                while node in active:
                    count += 1
                    node = int(flow[node])
                longest = max(longest, count*float(np.hypot(dx, dy))*spacing_m)
    return longest
