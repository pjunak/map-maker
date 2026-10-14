"""Connected depression extents and representative conditioned escape routes."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.hydrology import D8_NEIGHBOURS

# Non-land classification and overlapping land-boundary flags are diagnostic.
EXTERIOR_WATER = 1
ENCLOSED_WATER = 2
GRID_EDGE = 1
EXTERIOR_BOUNDARY = 2
ENCLOSED_BOUNDARY = 4


@dataclass(frozen=True, slots=True)
class BasinOutlet:
    """First extent exit on the deepest node's conditioned D8 route.

    The spill is the highest original terrain node from this exit to its
    terminal, choosing the nearest on exact ties. It is a route candidate,
    not a unique lake outlet or a nested-depression relationship.
    """

    source_flat_index: int
    receiver_flat_index: int
    spill_flat_index: int
    spill_elevation_m: float
    terminal_flat_index: int
    boundary_flags: int


@dataclass(frozen=True, slots=True)
class DrainageBasinCandidate:
    """One ranked, eight-connected region needing significant filling."""

    basin_id: int
    normalized_x: float
    normalized_y: float
    deepest_flat_index: int
    floor_flat_index: int
    cell_count: int
    area_km2: float
    floor_elevation_m: float
    maximum_fill_depth_m: float
    fill_volume_km3: float
    terminal_cell_count: int
    exit_edge_count: int
    outlet: BasinOutlet


def connected_components(mask: NDArray[np.bool_]) -> list[NDArray[np.int64]]:
    height, width = mask.shape
    remaining = mask.copy()
    components: list[NDArray[np.int64]] = []
    for start_value in np.flatnonzero(remaining):
        start = int(start_value)
        if not remaining.flat[start]:
            continue
        remaining.flat[start] = False
        stack = [start]
        component: list[int] = []
        while stack:
            index = stack.pop()
            component.append(index)
            row, column = divmod(index, width)
            for dr, dc in D8_NEIGHBOURS:
                nr, nc = row + dr, column + dc
                if 0 <= nr < height and 0 <= nc < width and remaining[nr, nc]:
                    remaining[nr, nc] = False
                    stack.append(nr * width + nc)
        components.append(np.asarray(component, dtype=np.int64))
    return components


def boundary_context(
    land_mask: NDArray[np.bool_],
) -> tuple[NDArray[np.uint8], NDArray[np.uint8]]:
    """Classify raster non-land topology without changing routing boundary rules."""
    edge = np.zeros_like(land_mask)
    edge[[0, -1], :] = True
    edge[:, [0, -1]] = True
    water = np.zeros(land_mask.shape, dtype=np.uint8)
    for component in connected_components(~land_mask):
        kind = EXTERIOR_WATER if np.any(edge.ravel()[component]) else ENCLOSED_WATER
        water.ravel()[component] = kind
    flags = np.where(edge & land_mask, GRID_EDGE, 0).astype(np.uint8)
    height, width = land_mask.shape
    for dr, dc in D8_NEIGHBOURS:
        rows = slice(max(0, -dr), min(height, height - dr))
        columns = slice(max(0, -dc), min(width, width - dc))
        neighbours = water[max(0, dr):min(height, height + dr),
                           max(0, dc):min(width, width + dc)]
        flags[rows, columns] |= np.where(neighbours == EXTERIOR_WATER,
                                        EXTERIOR_BOUNDARY, 0).astype(np.uint8)
        flags[rows, columns] |= np.where(neighbours == ENCLOSED_WATER,
                                        ENCLOSED_BOUNDARY, 0).astype(np.uint8)
    flags[~land_mask] = 0
    return water, flags


def basin_candidates(
    elevation_m: NDArray[np.float64],
    fill_depth_m: NDArray[np.float64],
    significant_fill: NDArray[np.bool_],
    potential_sinks: NDArray[np.bool_],
    receivers: NDArray[np.int64],
    ascending: NDArray[np.int64],
    boundary_flags: NDArray[np.uint8],
    *,
    cell_area_km2: float,
) -> tuple[tuple[DrainageBasinCandidate, ...], NDArray[np.uint32]]:
    """Retain extents and a deterministic representative route per component.

    Receivers and ascending order must describe a strictly descending land DAG.
    The caller owns conditioning/validation. Downstream peaks and terminals are
    shared once across components, avoiding repeated walks to the boundary.
    """
    height, width = elevation_m.shape
    flat_elevation, flat_depth = elevation_m.ravel(), fill_depth_m.ravel()
    flat_receivers = receivers.ravel()
    peaks = np.arange(elevation_m.size, dtype=np.int64)
    terminals = np.full(elevation_m.size, -1, dtype=np.int64)
    for value in ascending:
        index = int(value)
        receiver = int(flat_receivers[index])
        if receiver < 0:
            terminals[index] = index
        else:
            terminals[index] = terminals[receiver]
            peak = int(peaks[receiver])
            if flat_elevation[peak] > flat_elevation[index]:
                peaks[index] = peak

    components = connected_components(significant_fill)
    ranked: list[tuple[float, float, int, NDArray[np.int64]]] = []
    for component in components:
        depths = flat_depth[component]
        maximum = float(np.max(depths))
        deepest = int(np.min(component[depths == maximum]))
        volume = float(np.sum(depths)) * cell_area_km2 / 1_000.0
        ranked.append((maximum, volume, deepest, component))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    labels = np.zeros(elevation_m.shape, dtype=np.uint32)
    for basin_id, (_, _, _, component) in enumerate(ranked, start=1):
        labels.ravel()[component] = basin_id

    candidates: list[DrainageBasinCandidate] = []
    for basin_id, (maximum, volume, deepest, component) in enumerate(ranked, start=1):
        floor = int(np.min(component[flat_elevation[component]
                                     == np.min(flat_elevation[component])]))
        source = deepest
        receiver = int(flat_receivers[source])
        while receiver >= 0 and labels.flat[receiver] == basin_id:
            source = receiver
            receiver = int(flat_receivers[source])
        if receiver < 0:
            raise RuntimeError("A significant depression must have a conditioned extent exit.")
        peak, terminal = int(peaks[source]), int(terminals[source])
        targets = flat_receivers[component]
        if np.any(targets < 0) or terminal < 0 or not boundary_flags.flat[terminal]:
            raise RuntimeError("A depression escape route must reach a drainage boundary.")
        exit_count = int(np.count_nonzero(labels.ravel()[targets] != basin_id))
        row, column = divmod(deepest, width)
        candidates.append(DrainageBasinCandidate(
            basin_id=basin_id,
            normalized_x=column / max(1, width - 1),
            normalized_y=row / max(1, height - 1),
            deepest_flat_index=deepest,
            floor_flat_index=floor,
            cell_count=int(component.size),
            area_km2=component.size * cell_area_km2,
            floor_elevation_m=float(flat_elevation[floor]),
            maximum_fill_depth_m=maximum,
            fill_volume_km3=volume,
            terminal_cell_count=int(np.count_nonzero(potential_sinks.ravel()[component])),
            exit_edge_count=exit_count,
            outlet=BasinOutlet(source, receiver, peak, float(flat_elevation[peak]),
                               terminal, int(boundary_flags.flat[terminal])),
        ))
    return tuple(candidates), labels
