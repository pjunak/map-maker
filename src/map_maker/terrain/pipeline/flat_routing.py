"""D8 routing over exact flats using separate integer gradients, never DEM edits."""

from collections import deque
from dataclasses import dataclass
from math import hypot, isfinite

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.hydrology import D8_NEIGHBOURS

FLAT_ROUTING_ALGORITHM_ID = "masked-barnes-d8-flat-routing@1"


@dataclass(frozen=True, slots=True)
class FlatRouting:
    receivers: NDArray[np.int64]
    flat_rank: NDArray[np.uint32]


def route_flats(
    head_m: NDArray[np.float64], neighbours: NDArray[np.int64],
    terminal_mask: NDArray[np.bool_], *, x_spacing_km: float, y_spacing_km: float,
) -> FlatRouting:
    """Route a compact, symmetric D8 graph with -1 for absent neighbours.

    Real downhill receivers take precedence. Only nodes without one may gain
    an equal-height edge. Separate gradients toward exits and away from higher
    ground follow Barnes/Lehman/Mulla (2014), adapted to a bounded graph. All
    downhill exits participate, even if their later path ends in another pit.
    """
    count = head_m.size
    if (head_m.ndim != 1 or terminal_mask.shape != head_m.shape
            or neighbours.shape != (count, 8) or not np.all(np.isfinite(head_m))):
        raise ValueError("Flat routing requires finite heads and matching node/edge arrays.")
    if not all(isfinite(value) and value > 0 for value in (x_spacing_km, y_spacing_km)):
        raise ValueError("Flat routing grid spacing must be finite and positive.")
    if np.any((neighbours < -1) | (neighbours >= count)):
        raise ValueError("Flat routing neighbours must be local node indices or -1.")
    nodes = np.arange(count, dtype=np.int64)
    for direction in range(8):
        valid = neighbours[:, direction] >= 0
        targets = neighbours[valid, direction]
        if np.any(targets == nodes[valid]) or np.any(
            neighbours[targets, 7 - direction] != nodes[valid]
        ):
            raise ValueError("Flat routing links must be symmetric and cannot point to themselves.")
    receivers = np.full(count, -1, dtype=np.int64)
    ranks = np.zeros(count, dtype=np.uint32)
    if not count:
        return FlatRouting(receivers, ranks)
    distances = tuple(hypot(dc * x_spacing_km, dr * y_spacing_km) for dr, dc in D8_NEIGHBOURS)
    best_slope = np.zeros(count, dtype=np.float64)
    higher = np.zeros(count, dtype=np.bool_)
    for direction, distance in enumerate(distances):
        targets = neighbours[:, direction]
        valid = targets >= 0
        drops = head_m - head_m[np.maximum(targets, 0)]
        higher |= valid & (drops < 0)
        slopes = drops / distance
        better = valid & ~terminal_mask & (drops > 0) & (slopes > best_slope)
        receivers[better] = targets[better]
        best_slope[better] = slopes[better]

    # A terminal may join a dry flat at the same head; mark components independently.
    labelled = np.zeros(count, dtype=np.bool_)
    low_distance = np.full(count, -1, dtype=np.int64)
    high_distance = np.full(count, -1, dtype=np.int64)
    for start in np.flatnonzero((receivers < 0) & ~terminal_mask):
        if labelled[start]:
            continue
        level = head_m[start]
        component = [int(start)]
        labelled[start] = True
        for node in component:
            for neighbour in neighbours[node]:
                target = int(neighbour)
                if target >= 0 and not labelled[target] and head_m[target] == level:
                    labelled[target] = True
                    component.append(target)
        members = np.asarray(component, dtype=np.int64)
        exits = members[(receivers[members] >= 0) | terminal_mask[members]]
        if not exits.size:
            continue
        queue = deque(int(node) for node in exits)
        low_distance[exits] = 0
        while queue:
            node = queue.popleft()
            for neighbour in neighbours[node]:
                target = int(neighbour)
                if target >= 0 and head_m[target] == level and low_distance[target] < 0:
                    low_distance[target] = low_distance[node] + 1
                    queue.append(target)
        high_edges = members[higher[members] & (receivers[members] < 0) & ~terminal_mask[members]]
        queue = deque(int(node) for node in high_edges)
        high_distance[high_edges] = 0
        maximum_high_distance = 0
        while queue:
            node = queue.popleft()
            maximum_high_distance = max(maximum_high_distance, int(high_distance[node]))
            for neighbour in neighbours[node]:
                target = int(neighbour)
                if (target >= 0 and head_m[target] == level and high_distance[target] < 0
                        and receivers[target] < 0 and not terminal_mask[target]):
                    high_distance[target] = high_distance[node] + 1
                    queue.append(target)
        pending = members[(receivers[members] < 0) & ~terminal_mask[members]]
        away = np.where(high_distance[pending] >= 0,
                        maximum_high_distance - high_distance[pending], 0)
        ranks[pending] = (2 * low_distance[pending] + away).astype(np.uint32)
        for node in pending:
            best = 0.
            for direction, neighbour in enumerate(neighbours[node]):
                target = int(neighbour)
                if target < 0 or head_m[target] != level:
                    continue
                drop = int(ranks[node]) - int(ranks[target])
                slope = drop / distances[direction]
                if slope > best:
                    best = slope
                    receivers[node] = target
            if receivers[node] < 0:
                raise RuntimeError("A resolved flat must have a strictly decreasing rank path.")
    return FlatRouting(receivers, ranks)
