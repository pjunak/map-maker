"""Deterministic regular-grid primitives for drainage-guided terrain shaping."""

from dataclasses import dataclass
from heapq import heappop, heappush
from math import hypot, inf, nextafter

import numpy as np
from numpy.typing import NDArray

D8_NEIGHBOURS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


@dataclass(frozen=True, slots=True)
class DrainageIncision:
    """Canonical automatic-valley products derived from one routing surface."""

    source_elevation_m: NDArray[np.float64]
    routing_elevation_m: NDArray[np.float64]
    receivers: NDArray[np.int64]
    outlet_mask: NDArray[np.bool_]
    retention_terminal_mask: NDArray[np.bool_]
    incision_m: NDArray[np.float64]
    incision_limit_m: NDArray[np.float64]
    accumulation_km2: NDArray[np.float64]
    detail_suppression: NDArray[np.float64]
    channel_mask: NDArray[np.bool_]
    channel_head_mask: NDArray[np.bool_]
    stream_order: NDArray[np.uint16]
    floor_correction_m: NDArray[np.float64]  # Signed net cut change, including steepness.
    steepness_correction_m: NDArray[np.float64]
    unresolved_uphill_channel_edge_count: int
    unresolved_steepening_edge_count: int
    maximum_downstream_steepening_ratio: float


def land_outlet_mask(land_mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    padded = np.pad(land_mask, 1, mode="constant", constant_values=False)
    surrounded_by_land = land_mask.copy()
    for row_offset, column_offset in D8_NEIGHBOURS:
        row_slice = slice(1 + row_offset, 1 + row_offset + land_mask.shape[0])
        column_slice = slice(
            1 + column_offset,
            1 + column_offset + land_mask.shape[1],
        )
        surrounded_by_land &= padded[row_slice, column_slice]
    return land_mask & ~surrounded_by_land


def _terminal_cells(
    land_mask: NDArray[np.bool_], terminal_mask: NDArray[np.bool_] | None,
) -> NDArray[np.bool_]:
    if terminal_mask is None:
        return np.zeros_like(land_mask)
    if terminal_mask.shape != land_mask.shape or np.any(terminal_mask & ~land_mask):
        raise ValueError("Retention terminals must share the grid and lie on land.")
    return terminal_mask


def _validate_edge_barriers(
    barriers: NDArray[np.float64] | None, land: NDArray[np.bool_],
) -> None:
    if barriers is None:
        return
    if barriers.shape != (8, *land.shape):
        raise ValueError("Edge barriers must have one D8 plane per land-grid cell.")
    ny, nx = land.shape
    for index in range(4, 8):
        dy, dx = D8_NEIGHBOURS[index]
        source = (slice(0, ny-dy), slice(max(0, -dx), nx-max(0, dx)))
        target = (slice(dy, ny), slice(max(0, dx), nx-max(0, -dx)))
        valid = land[source] & land[target]
        forward, reverse = barriers[index][source][valid], barriers[7-index][target][valid]
        if not np.all(np.isfinite(forward)) or not np.array_equal(forward, reverse):
            raise ValueError("Land edge barriers must be finite and symmetric.")


def priority_flood_surface(
    elevation_m: NDArray[np.float64],
    land_mask: NDArray[np.bool_],
    *,
    terminal_mask: NDArray[np.bool_] | None = None,
    edge_barriers_m: NDArray[np.float64] | None = None,
) -> NDArray[np.float64]:
    """Return a routing surface reaching a coast or an authored retention terminal.

    The returned surface is a temporary hydrology product. It fills accidental
    depressions but never replaces the authored/generated elevation surface.
    Raised cells receive the smallest representable downstream grade so flats
    have a deterministic route toward their spill point. Observed interior edge
    crests also bound passage; these require relaxation until a node is popped.
    """

    if elevation_m.shape != land_mask.shape or elevation_m.ndim != 2:
        raise ValueError("Elevation and land mask must be equally shaped 2D arrays.")
    if np.any(land_mask & ~np.isfinite(elevation_m)):
        raise ValueError("Land elevations must be finite before drainage routing.")

    _validate_edge_barriers(edge_barriers_m, land_mask)
    height, width = elevation_m.shape
    filled = np.where(land_mask, np.inf, elevation_m)
    visited = np.zeros_like(land_mask)
    queue: list[tuple[float, int, int]] = []
    settle_on_pop = edge_barriers_m is not None

    terminals = _terminal_cells(land_mask, terminal_mask)
    for row, column in np.argwhere(land_outlet_mask(land_mask) | terminals):
        filled[row, column] = elevation_m[row, column]
        visited[row, column] = not settle_on_pop
        heappush(queue, (float(filled[row, column]), int(row), int(column)))

    if np.any(land_mask) and not queue:
        raise ValueError("Land mask has no edge or coastline outlet.")

    while queue:
        current_height, row, column = heappop(queue)
        if settle_on_pop:
            if visited[row, column]:
                continue
            visited[row, column] = True
        # The same scalar successor applies to every outward edge of this node.
        next_height = nextafter(current_height, inf)
        for edge_index, (row_offset, column_offset) in enumerate(D8_NEIGHBOURS):
            neighbour_row = row + row_offset
            neighbour_column = column + column_offset
            if not (
                0 <= neighbour_row < height
                and 0 <= neighbour_column < width
                and land_mask[neighbour_row, neighbour_column]
                and not visited[neighbour_row, neighbour_column]
            ):
                continue
            if not settle_on_pop:
                # With node heights only, first discovery is already optimal.
                visited[neighbour_row, neighbour_column] = True
            original_height = float(elevation_m[neighbour_row, neighbour_column])
            barrier = (float(edge_barriers_m[edge_index, row, column])
                       if edge_barriers_m is not None else original_height)
            routed_height = max(original_height, barrier, next_height)
            # An edge crest can make first discovery non-optimal. Settle only
            # when popped, so a later lower-saddle path can still relax this node.
            if routed_height < filled[neighbour_row, neighbour_column]:
                filled[neighbour_row, neighbour_column] = routed_height
                heappush(queue, (routed_height, neighbour_row, neighbour_column))

    if np.any(land_mask & ~visited):
        raise RuntimeError("Priority-Flood left land disconnected from every outlet.")
    return filled


def multiple_flow_accumulation(
    routing_elevation_m: NDArray[np.float64],
    land_mask: NDArray[np.bool_],
    *,
    x_spacing_km: float,
    y_spacing_km: float,
    exponent: float = 1.1,
    terminal_mask: NDArray[np.bool_] | None = None,
    edge_barriers_m: NDArray[np.float64] | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return MFD contributing area in km2 and maximum local downslope grade.

    Flow is divided among lower D8 neighbours reachable over the observed edge
    crests in proportion to ``slope**exponent``. Stable descending ordering and a
    fixed neighbour order make ties reproducible without introducing a mutable random stream.
    """

    if routing_elevation_m.shape != land_mask.shape or routing_elevation_m.ndim != 2:
        raise ValueError("Routing elevation and land mask must be equally shaped 2D arrays.")
    if x_spacing_km <= 0.0 or y_spacing_km <= 0.0 or exponent <= 0.0:
        raise ValueError("Grid spacing and MFD exponent must be positive.")

    _validate_edge_barriers(edge_barriers_m, land_mask)
    height, width = routing_elevation_m.shape
    cell_area_km2 = x_spacing_km * y_spacing_km
    accumulation = np.where(land_mask, cell_area_km2, 0.0).astype(np.float64)
    maximum_slope = np.zeros_like(routing_elevation_m)
    flat_indices = np.flatnonzero(land_mask)
    order = flat_indices[
        np.argsort(-routing_elevation_m.ravel()[flat_indices], kind="stable")
    ]

    terminals = _terminal_cells(land_mask, terminal_mask).ravel()
    neighbours = tuple(
        (index, dy, dx, hypot(dx*x_spacing_km, dy*y_spacing_km))
        for index, (dy, dx) in enumerate(D8_NEIGHBOURS)
    )
    for flat_index in order:
        if terminals[flat_index]:
            continue
        row, column = divmod(int(flat_index), width)
        current_height = float(routing_elevation_m[row, column])
        recipients: list[tuple[int, int, float, float, float]] = []
        largest_slope = 0.0
        for edge_index, row_offset, column_offset, distance_km in neighbours:
            neighbour_row = row + row_offset
            neighbour_column = column + column_offset
            if not (
                0 <= neighbour_row < height
                and 0 <= neighbour_column < width
                and land_mask[neighbour_row, neighbour_column]
            ):
                continue
            if (edge_barriers_m is not None
                    and edge_barriers_m[edge_index, row, column] > current_height):
                continue
            drop_m = current_height - float(
                routing_elevation_m[neighbour_row, neighbour_column]
            )
            if drop_m <= 0.0:
                continue
            slope = drop_m / (1_000.0 * distance_km)
            recipients.append((neighbour_row, neighbour_column, slope**exponent,
                               drop_m, distance_km))
            largest_slope = max(largest_slope, slope)
        maximum_slope[row, column] = largest_slope
        if not recipients:
            continue
        total_weight = sum(weight for _row, _column, weight, _drop, _distance in recipients)
        if total_weight == 0.0:
            # Priority-Flood steps near zero can underflow when converted to
            # slope or raised to an exponent. Relative drops retain their ratios.
            scale = max(drop for _row, _column, _weight, drop, _distance in recipients)
            recipients = [(row, column, ((drop / scale) / distance) ** exponent, drop, distance)
                          for row, column, _weight, drop, distance in recipients]
            total_weight = sum(weight for _row, _column, weight, _drop, _distance in recipients)
        source_area = accumulation[row, column]
        for neighbour_row, neighbour_column, weight, _drop, _distance in recipients:
            accumulation[neighbour_row, neighbour_column] += source_area * weight / total_weight

    return accumulation, maximum_slope


def steepest_flow_accumulation(
    routing_elevation_m: NDArray[np.float64],
    land_mask: NDArray[np.bool_],
    *,
    x_spacing_km: float,
    y_spacing_km: float,
    terminal_mask: NDArray[np.bool_] | None = None,
    edge_barriers_m: NDArray[np.float64] | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return D8 contributing area and receiver slope for a unique flow tree."""

    receivers, receiver_slope = steepest_flow_receivers(
        routing_elevation_m,
        land_mask,
        x_spacing_km=x_spacing_km,
        y_spacing_km=y_spacing_km,
        terminal_mask=terminal_mask,
        edge_barriers_m=edge_barriers_m,
    )

    accumulation = receiver_contributing_area(
        routing_elevation_m,
        land_mask,
        receivers,
        cell_area_km2=x_spacing_km * y_spacing_km,
    )
    return accumulation, receiver_slope


def receiver_contributing_area(
    routing_elevation_m: NDArray[np.float64],
    land_mask: NDArray[np.bool_],
    receivers: NDArray[np.int64],
    *,
    cell_area_km2: float,
) -> NDArray[np.float64]:
    """Accumulate cell area through an already computed receiver tree."""

    accumulation = np.where(land_mask, cell_area_km2, 0.0).astype(np.float64)
    flat_indices = np.flatnonzero(land_mask)
    order = flat_indices[
        np.argsort(-routing_elevation_m.ravel()[flat_indices], kind="stable")
    ]
    flat_receivers = receivers.ravel()
    flat_accumulation = accumulation.ravel()
    for flat_index in order:
        receiver = int(flat_receivers[flat_index])
        if receiver >= 0:
            flat_accumulation[receiver] += flat_accumulation[flat_index]
    return accumulation


def steepest_flow_receivers(
    routing_elevation_m: NDArray[np.float64],
    land_mask: NDArray[np.bool_],
    *,
    x_spacing_km: float,
    y_spacing_km: float,
    terminal_mask: NDArray[np.bool_] | None = None,
    edge_barriers_m: NDArray[np.float64] | None = None,
) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """Return the steepest lower D8 receiver reachable over the observed crest."""

    if routing_elevation_m.shape != land_mask.shape or routing_elevation_m.ndim != 2:
        raise ValueError("Routing elevation and land mask must be equally shaped 2D arrays.")
    if x_spacing_km <= 0.0 or y_spacing_km <= 0.0:
        raise ValueError("Grid spacing must be positive.")

    _validate_edge_barriers(edge_barriers_m, land_mask)
    height, width = routing_elevation_m.shape
    receivers = np.full(routing_elevation_m.shape, -1, dtype=np.int64)
    receiver_slope = np.zeros_like(routing_elevation_m)
    terminals = _terminal_cells(land_mask, terminal_mask)
    indices = np.arange(land_mask.size, dtype=np.int64).reshape(land_mask.shape)
    receiver_drop = np.zeros_like(routing_elevation_m)
    receiver_distance = np.ones_like(routing_elevation_m)

    # Nodes choose independently. Sweep directions in the original order so
    # exact ties still retain the first neighbour, including subnormal grades.
    for edge_index, (dy, dx) in enumerate(D8_NEIGHBOURS):
        source = (slice(max(0, -dy), height-max(0, dy)),
                  slice(max(0, -dx), width-max(0, dx)))
        target = (slice(max(0, dy), height-max(0, -dy)),
                  slice(max(0, dx), width-max(0, -dx)))
        active = land_mask[source] & ~terminals[source] & land_mask[target]
        if edge_barriers_m is not None:
            active &= edge_barriers_m[edge_index][source] <= routing_elevation_m[source]
        drop = np.subtract(routing_elevation_m[source], routing_elevation_m[target],
                           out=np.zeros_like(routing_elevation_m[source]), where=active)
        active &= drop > 0.0
        if not np.any(active):
            continue
        distance = hypot(dx*x_spacing_km, dy*y_spacing_km)
        previous_slope = receiver_slope[source]
        previous_drop = receiver_drop[source]
        previous_distance = receiver_distance[source]
        with np.errstate(under="ignore"):
            slope = drop / (1_000.0 * distance)
            better = active & (slope > previous_slope)
            underflow = active & (slope == 0.0) & (previous_slope == 0.0)
            if np.any(underflow):
                scale = np.maximum(drop[underflow], previous_drop[underflow])
                better[underflow] = (drop[underflow]/scale)/distance > (
                    previous_drop[underflow]/scale)/previous_distance[underflow]
        receivers[source][better] = indices[target][better]
        previous_slope[better] = slope[better]
        previous_drop[better] = drop[better]
        previous_distance[better] = distance

    return receivers, receiver_slope


def _masked_smooth(
    values: NDArray[np.float64],
    land_mask: NDArray[np.bool_],
    iterations: int,
) -> NDArray[np.float64]:
    result = np.where(land_mask, values, 0.0)
    weights = land_mask.astype(np.float64)
    for _ in range(iterations):
        padded_values = np.pad(result, 1, mode="constant")
        padded_weights = np.pad(weights, 1, mode="constant")
        value_sum = 4.0 * padded_values[1:-1, 1:-1]
        weight_sum = 4.0 * padded_weights[1:-1, 1:-1]
        for row_offset, column_offset in D8_NEIGHBOURS:
            neighbour_weight = 1.0 if row_offset == 0 or column_offset == 0 else 0.7
            row_slice = slice(1 + row_offset, 1 + row_offset + values.shape[0])
            column_slice = slice(
                1 + column_offset,
                1 + column_offset + values.shape[1],
            )
            value_sum += neighbour_weight * padded_values[row_slice, column_slice]
            weight_sum += neighbour_weight * padded_weights[row_slice, column_slice]
        result = np.divide(
            value_sum,
            weight_sum,
            out=np.zeros_like(value_sum),
            where=weight_sum > 0.0,
        )
        result = np.where(land_mask, result, 0.0)
    return result


def _connected_channel_network(
    initiation_mask: NDArray[np.bool_],
    receivers: NDArray[np.int64],
    land_mask: NDArray[np.bool_],
) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """Trace every initiated channel downstream and identify network heads."""

    if initiation_mask.shape != land_mask.shape or receivers.shape != land_mask.shape:
        raise ValueError("Channel initiation, receivers, and land must share a shape.")
    flat_channel = (initiation_mask & land_mask).ravel().copy()
    flat_receivers = receivers.ravel()
    for starting_index_value in np.flatnonzero(flat_channel):
        current = int(starting_index_value)
        while True:
            receiver = int(flat_receivers[current])
            if receiver < 0 or flat_channel[receiver]:
                break
            flat_channel[receiver] = True
            current = receiver

    has_channel_donor = np.zeros(flat_channel.shape, dtype=np.bool_)
    for donor_value in np.flatnonzero(flat_channel):
        receiver = int(flat_receivers[int(donor_value)])
        if receiver >= 0 and flat_channel[receiver]:
            has_channel_donor[receiver] = True
    channel_heads = flat_channel & ~has_channel_donor
    return (
        flat_channel.reshape(land_mask.shape),
        channel_heads.reshape(land_mask.shape),
    )


def strahler_stream_order(
    channel_mask: NDArray[np.bool_],
    receivers: NDArray[np.int64],
    routing_surface_m: NDArray[np.float64],
) -> NDArray[np.uint16]:
    """Return deterministic Horton-Strahler order for a routed channel tree.

    First-order reaches begin at channel heads. Equal-order tributaries raise
    the downstream order by one; a lower-order tributary joining a larger
    reach leaves the larger order unchanged.
    """

    if (
        channel_mask.ndim != 2
        or receivers.shape != channel_mask.shape
        or routing_surface_m.shape != channel_mask.shape
    ):
        raise ValueError("Channel order arrays must share an equally shaped 2D grid.")
    if np.any(channel_mask & ~np.isfinite(routing_surface_m)):
        raise ValueError("Selected-channel routing elevations must be finite.")

    flat_channel = channel_mask.ravel()
    flat_receivers = receivers.ravel()
    flat_routing_surface_m = routing_surface_m.ravel()
    channel_indices = np.flatnonzero(flat_channel)
    upstream_first = channel_indices[
        np.argsort(-flat_routing_surface_m[channel_indices], kind="stable")
    ]
    order = np.zeros(flat_channel.shape, dtype=np.uint16)
    largest_donor_order = np.zeros(flat_channel.shape, dtype=np.uint16)
    largest_donor_count = np.zeros(flat_channel.shape, dtype=np.uint16)

    for channel_index_value in upstream_first:
        channel_index = int(channel_index_value)
        donor_order = int(largest_donor_order[channel_index])
        if donor_order == 0:
            current_order = 1
        else:
            current_order = donor_order + int(largest_donor_count[channel_index] >= 2)
        if current_order > np.iinfo(np.uint16).max:
            raise OverflowError("Channel hierarchy exceeds the supported stream order.")
        order[channel_index] = current_order

        receiver = int(flat_receivers[channel_index])
        if receiver < 0:
            continue
        if receiver >= flat_channel.size:
            raise ValueError("Channel receiver index falls outside the grid.")
        if not flat_channel[receiver]:
            continue
        if flat_routing_surface_m[receiver] >= flat_routing_surface_m[channel_index]:
            raise ValueError("Channel receivers must descend on the routing surface.")
        if current_order > largest_donor_order[receiver]:
            largest_donor_order[receiver] = current_order
            largest_donor_count[receiver] = 1
        elif current_order == largest_donor_order[receiver]:
            largest_donor_count[receiver] += 1

    return order.reshape(channel_mask.shape)


def condition_channel_floors(
    source_elevation_m: NDArray[np.float64],
    incision_m: NDArray[np.float64],
    maximum_incision_m: NDArray[np.float64],
    channel_mask: NDArray[np.bool_],
    receivers: NDArray[np.int64],
    routing_surface_m: NDArray[np.float64],
    *,
    minimum_drop_m: float = 0.01,
) -> tuple[NDArray[np.float64], NDArray[np.float64], int]:
    """Fit cuts to the selected network's attainable nodal floor intervals.

    Carry downstream lower bounds upstream before lowering receivers. Feasible
    intervals yield descending nodes; conflicts remain bounded and reported.
    Returned corrections are signed incision changes, negative for recovered
    cuts. No node is filled above its source, and receivers stay unchanged.
    """
    shape = source_elevation_m.shape
    if source_elevation_m.ndim != 2 or any(values.shape != shape for values in (
        incision_m, maximum_incision_m, channel_mask, receivers, routing_surface_m,
    )):
        raise ValueError("Channel-floor conditioning arrays must share a 2D shape.")
    if not np.isfinite(minimum_drop_m) or minimum_drop_m < 0.:
        raise ValueError("Minimum downstream drop must be finite and nonnegative.")
    if any(np.any(~np.isfinite(values[channel_mask])) for values in (
        source_elevation_m, incision_m, maximum_incision_m, routing_surface_m,
    )) or np.any(channel_mask & ((incision_m < 0.) | (incision_m > maximum_incision_m))):
        raise ValueError("Channel floors need finite sources and cuts within their limits.")

    selected = channel_mask.ravel()
    indices = np.flatnonzero(selected)
    receiver = receivers.ravel()
    if np.any((receiver[indices] < -1) | (receiver[indices] >= selected.size)):
        raise ValueError("Channel receiver index falls outside the grid.")
    links = indices[receiver[indices] >= 0]
    links = links[selected[receiver[links]]]
    routing = routing_surface_m.ravel()
    if np.any(routing[links] <= routing[receiver[links]]):
        raise ValueError("Channel receivers must descend on the routing surface.")
    upstream_first = indices[np.argsort(-routing[indices], kind="stable")]

    conditioned = incision_m.copy()
    source = source_elevation_m.ravel()
    maximum = maximum_incision_m.ravel()
    floor = (source_elevation_m-incision_m).ravel()
    lowest = source-maximum
    required = lowest.copy()
    # Every node has one receiver, so reverse topological order carries the
    # complete downstream cut limit to each tributary without repeated passes.
    for value in upstream_first[::-1]:
        donor = int(value)
        target = int(receiver[donor])
        if target >= 0 and selected[target]:
            required[donor] = max(required[donor], required[target]+minimum_drop_m)
    floor[indices] = np.minimum(source[indices], np.maximum(floor[indices], required[indices]))

    # At a junction the lowest incoming floor constrains the receiver. Its
    # local cut ceiling still wins when the complete path cannot descend.
    for value in upstream_first:
        donor = int(value)
        target = int(receiver[donor])
        if target >= 0 and selected[target]:
            floor[target] = max(lowest[target], min(floor[target], floor[donor]-minimum_drop_m))
    conditioned.ravel()[indices] = np.clip(source[indices]-floor[indices], 0., maximum[indices])
    correction = np.zeros_like(incision_m)
    correction.ravel()[indices] = conditioned.ravel()[indices]-incision_m.ravel()[indices]
    final_floor = source-conditioned.ravel()
    unresolved = np.count_nonzero(
        final_floor[receiver[links]] > final_floor[links]-minimum_drop_m+1e-9)
    return conditioned, correction, int(unresolved)


def _normalized_downstream_steepening_ratio(
    flat_floor_m: NDArray[np.float64],
    flat_accumulation_km2: NDArray[np.float64],
    donor: int,
    middle: int,
    downstream: int,
    *,
    width: int,
    x_spacing_km: float,
    y_spacing_km: float,
    reference_concavity: float,
) -> tuple[float, float, float]:
    donor_row, donor_column = divmod(donor, width)
    middle_row, middle_column = divmod(middle, width)
    downstream_row, downstream_column = divmod(downstream, width)
    upstream_distance_km = hypot(
        (donor_column - middle_column) * x_spacing_km,
        (donor_row - middle_row) * y_spacing_km,
    )
    downstream_distance_km = hypot(
        (middle_column - downstream_column) * x_spacing_km,
        (middle_row - downstream_row) * y_spacing_km,
    )
    minimum_slope = np.finfo(np.float64).eps
    upstream_slope = max(
        (flat_floor_m[donor] - flat_floor_m[middle])
        / (1_000.0 * upstream_distance_km),
        minimum_slope,
    )
    downstream_slope = max(
        (flat_floor_m[middle] - flat_floor_m[downstream])
        / (1_000.0 * downstream_distance_km),
        minimum_slope,
    )
    upstream_steepness = upstream_slope * (
        flat_accumulation_km2[donor] ** reference_concavity
    )
    downstream_steepness = downstream_slope * (
        flat_accumulation_km2[middle] ** reference_concavity
    )
    return (
        downstream_steepness / upstream_steepness,
        upstream_distance_km,
        downstream_distance_km,
    )


def condition_downstream_channel_steepness(
    source_elevation_m: NDArray[np.float64],
    incision_m: NDArray[np.float64],
    maximum_incision_m: NDArray[np.float64],
    channel_mask: NDArray[np.bool_],
    receivers: NDArray[np.int64],
    routing_surface_m: NDArray[np.float64],
    accumulation_km2: NDArray[np.float64],
    *,
    x_spacing_km: float,
    y_spacing_km: float,
    reference_concavity: float = 0.45,
    maximum_steepening_ratio: float = 8.0,
    maximum_passes: int = 16,
) -> tuple[NDArray[np.float64], NDArray[np.float64], int, float]:
    """Limit only extreme generated-channel steepening toward the outlet."""

    shape = source_elevation_m.shape
    if any(
        values.shape != shape
        for values in (
            incision_m,
            maximum_incision_m,
            channel_mask,
            receivers,
            routing_surface_m,
            accumulation_km2,
        )
    ):
        raise ValueError("Channel-steepness conditioning arrays must share a shape.")
    if x_spacing_km <= 0.0 or y_spacing_km <= 0.0:
        raise ValueError("Grid spacing must be positive.")
    if not 0.0 < reference_concavity < 1.0:
        raise ValueError("Reference concavity must be between zero and one.")
    if maximum_steepening_ratio <= 1.0 or maximum_passes < 1:
        raise ValueError("Steepening ratio and pass count must exceed one and zero.")
    if any(
        np.any(channel_mask & ~np.isfinite(values))
        for values in (
            source_elevation_m,
            incision_m,
            maximum_incision_m,
            routing_surface_m,
        )
    ):
        raise ValueError("Selected-channel profile values must be finite.")
    if np.any(
        channel_mask
        & (
            (incision_m < 0.0)
            | (maximum_incision_m + 1e-12 < incision_m)
        )
    ):
        raise ValueError("Selected-channel incision must be nonnegative and within its cap.")
    if np.any(
        channel_mask
        & (
            ~np.isfinite(accumulation_km2)
            | (accumulation_km2 <= 0.0)
        )
    ):
        raise ValueError("Selected channels must have positive finite accumulation.")

    conditioned = np.minimum(incision_m, maximum_incision_m).copy()
    flat_source = source_elevation_m.ravel()
    flat_conditioned = conditioned.ravel()
    flat_maximum = maximum_incision_m.ravel()
    flat_channel = channel_mask.ravel()
    flat_receivers = receivers.ravel()
    flat_accumulation = accumulation_km2.ravel()
    flat_floor = flat_source - flat_conditioned
    channel_indices = np.flatnonzero(flat_channel)
    upstream_first = channel_indices[
        np.argsort(-routing_surface_m.ravel()[channel_indices], kind="stable")
    ]
    width = shape[1]

    for _ in range(maximum_passes):
        changed = False
        for donor_value in upstream_first:
            donor = int(donor_value)
            middle = int(flat_receivers[donor])
            if middle < 0 or not flat_channel[middle]:
                continue
            downstream = int(flat_receivers[middle])
            if downstream < 0 or not flat_channel[downstream]:
                continue
            ratio, upstream_distance_km, downstream_distance_km = (
                _normalized_downstream_steepening_ratio(
                    flat_floor,
                    flat_accumulation,
                    donor,
                    middle,
                    downstream,
                    width=width,
                    x_spacing_km=x_spacing_km,
                    y_spacing_km=y_spacing_km,
                    reference_concavity=reference_concavity,
                )
            )
            if ratio <= maximum_steepening_ratio * (1.0 + 1e-12):
                continue
            slope_factor = maximum_steepening_ratio * (
                flat_accumulation[donor] / flat_accumulation[middle]
            ) ** reference_concavity
            maximum_middle_floor_m = (
                slope_factor * downstream_distance_km * flat_floor[donor]
                + upstream_distance_km * flat_floor[downstream]
            ) / (
                upstream_distance_km
                + slope_factor * downstream_distance_km
            )
            required_incision_m = flat_source[middle] - maximum_middle_floor_m
            revised_incision_m = min(
                flat_maximum[middle],
                max(flat_conditioned[middle], required_incision_m),
            )
            if revised_incision_m <= flat_conditioned[middle] + 1e-9:
                continue
            flat_conditioned[middle] = revised_incision_m
            flat_floor[middle] = flat_source[middle] - revised_incision_m
            changed = True
        if not changed:
            break

    unresolved = 0
    largest_ratio = 0.0
    for donor_value in channel_indices:
        donor = int(donor_value)
        middle = int(flat_receivers[donor])
        if middle < 0 or not flat_channel[middle]:
            continue
        downstream = int(flat_receivers[middle])
        if downstream < 0 or not flat_channel[downstream]:
            continue
        ratio, _upstream_distance_km, _downstream_distance_km = (
            _normalized_downstream_steepening_ratio(
                flat_floor,
                flat_accumulation,
                donor,
                middle,
                downstream,
                width=width,
                x_spacing_km=x_spacing_km,
                y_spacing_km=y_spacing_km,
                reference_concavity=reference_concavity,
            )
        )
        largest_ratio = max(largest_ratio, ratio)
        if ratio > maximum_steepening_ratio * (1.0 + 1e-6):
            unresolved += 1
    return (
        conditioned,
        np.maximum(conditioned - incision_m, 0.0),
        unresolved,
        largest_ratio,
    )


def automatic_incision_budget(maximum_elevation_m: float, variability: float) -> float:
    """Global depth plus downstream correction reserve, in metres."""
    return maximum_elevation_m * (0.035 + 0.085 * variability) + 0.02 * maximum_elevation_m


def drainage_incision(
    elevation_m: NDArray[np.float64],
    land_mask: NDArray[np.bool_],
    distance_to_coast_km: NDArray[np.float64],
    *,
    x_spacing_km: float,
    y_spacing_km: float,
    maximum_elevation_m: float,
    variability: float,
    drainage_density: float = 1.0,
    residual_detail_m: NDArray[np.float64] | None = None,
    incision_budget_m: NDArray[np.float64] | None = None,
    retention_terminal_mask: NDArray[np.bool_] | None = None,
    edge_barriers_m: NDArray[np.float64] | None = None,
) -> DrainageIncision:
    """Derive broad valley incision and contributing area from a terrain surface."""

    if not 0.25 <= drainage_density <= 2.0:
        raise ValueError("Drainage density must be between 0.25 and 2.")
    global_budget_m = automatic_incision_budget(maximum_elevation_m, variability)
    if incision_budget_m is None:
        budget_m = np.full_like(elevation_m, global_budget_m)
    else:
        if incision_budget_m.shape != elevation_m.shape:
            raise ValueError("Incision budget must share the elevation grid shape.")
        if np.any(land_mask & (~np.isfinite(incision_budget_m) | (incision_budget_m < 0))):
            raise ValueError("Land incision budget must be finite and non-negative.")
        budget_m = np.where(land_mask, np.minimum(incision_budget_m, global_budget_m), 0.0)
    terminals = _terminal_cells(land_mask, retention_terminal_mask)
    budget_m = np.where(terminals, 0.0, budget_m)
    budget_scale = budget_m / global_budget_m
    if residual_detail_m is not None:
        if residual_detail_m.shape != elevation_m.shape:
            raise ValueError("Residual detail must share the elevation grid shape.")
        if np.any(land_mask & ~np.isfinite(residual_detail_m)):
            raise ValueError("Land residual detail must be finite.")
    routing_surface = priority_flood_surface(
        elevation_m, land_mask, terminal_mask=terminals, edge_barriers_m=edge_barriers_m)
    accumulation_km2, _mfd_slope = multiple_flow_accumulation(
        routing_surface,
        land_mask,
        x_spacing_km=x_spacing_km,
        y_spacing_km=y_spacing_km,
        terminal_mask=terminals,
        edge_barriers_m=edge_barriers_m,
    )
    receivers, slope = steepest_flow_receivers(
        routing_surface,
        land_mask,
        x_spacing_km=x_spacing_km,
        y_spacing_km=y_spacing_km,
        terminal_mask=terminals,
        edge_barriers_m=edge_barriers_m,
    )
    cell_area_km2 = x_spacing_km * y_spacing_km
    tree_accumulation_km2 = receiver_contributing_area(
        routing_surface,
        land_mask,
        receivers,
        cell_area_km2=cell_area_km2,
    )
    land_area_km2 = float(np.count_nonzero(land_mask)) * cell_area_km2
    channel_threshold_km2 = max(12.0 * cell_area_km2, 0.0015 * land_area_km2)
    minimum_source_area_km2 = max(4.0 * cell_area_km2, 0.00025 * land_area_km2)
    initiation_slope = _masked_smooth(slope, land_mask, iterations=1)
    initiation_sample = (
        land_mask & ~terminals
        & (tree_accumulation_km2 >= minimum_source_area_km2)
        & (initiation_slope > 0.0)
    )
    initiation_reference_slope = (
        max(float(np.percentile(initiation_slope[initiation_sample], 65.0)), 0.001)
        if np.any(initiation_sample)
        else 0.001
    )
    local_threshold_km2 = channel_threshold_km2 * np.clip(
        np.square(
            initiation_reference_slope
            / np.maximum(initiation_slope, np.finfo(np.float64).eps)
        ),
        0.35,
        4.0,
    )
    initiation_index = tree_accumulation_km2 / local_threshold_km2
    # Keep the slope reference independent of density: raising density must only
    # add candidates, never remove an existing downstream path. The multiplier
    # controls initiation, not terrain heights, flow receivers or incision caps.
    initiation_mask = (
        land_mask & ~terminals & (initiation_slope > 0.0)
        & (tree_accumulation_km2 >= minimum_source_area_km2 / drainage_density)
        & (initiation_index * drainage_density >= 1.0)
    )
    channel, channel_heads = _connected_channel_network(
        initiation_mask,
        receivers,
        land_mask,
    )
    stream_order = strahler_stream_order(channel, receivers, routing_surface)
    largest_area_km2 = max(
        float(np.max(tree_accumulation_km2, initial=channel_threshold_km2)),
        channel_threshold_km2 * 1.01,
    )
    established_progress = np.clip(
        np.log(
            np.maximum(tree_accumulation_km2, channel_threshold_km2)
            / channel_threshold_km2
        )
        / np.log(largest_area_km2 / channel_threshold_km2),
        0.0,
        1.0,
    )
    headwater_progress = 0.08 * np.clip(
        np.log(
            np.maximum(tree_accumulation_km2, minimum_source_area_km2)
            / minimum_source_area_km2
        )
        / np.log(channel_threshold_km2 / minimum_source_area_km2),
        0.0,
        1.0,
    )
    log_progress = np.maximum(established_progress, headwater_progress)
    channel_slopes = slope[channel]
    reference_slope = (
        max(float(np.percentile(channel_slopes, 90.0)), 0.001)
        if channel_slopes.size
        else 0.001
    )
    slope_factor = np.sqrt(np.clip(slope / reference_slope, 0.0, 1.0))
    stream_power_shape = np.where(
        channel,
        log_progress * (0.45 + 0.55 * slope_factor),
        0.0,
    )
    largest_mfd_area_km2 = max(
        float(np.max(accumulation_km2, initial=channel_threshold_km2)),
        channel_threshold_km2 * 1.01,
    )
    mfd_progress = np.clip(
        np.log(
            np.maximum(accumulation_km2, channel_threshold_km2)
            / channel_threshold_km2
        )
        / np.log(largest_mfd_area_km2 / channel_threshold_km2),
        0.0,
        1.0,
    )
    convergence_shape = np.power(mfd_progress, 2.5) * (
        0.45
        + 0.55 * np.sqrt(np.clip(_mfd_slope / reference_slope, 0.0, 1.0))
    )
    near_shoulders = _masked_smooth(stream_power_shape, land_mask, iterations=2)
    trunk_source = stream_power_shape * np.power(log_progress, 1.4)
    trunk_shoulders = _masked_smooth(trunk_source, land_mask, iterations=7)
    valley_shape = np.clip(
        0.56 * stream_power_shape
        + 0.30 * near_shoulders
        + 0.28 * trunk_shoulders
        + 0.04 * convergence_shape,
        0.0,
        1.0,
    )
    maximum_depth_m = maximum_elevation_m * (0.035 + 0.085 * variability)
    incision_m = maximum_depth_m * budget_scale * valley_shape
    coastal_gate = np.clip(
        distance_to_coast_km / max(2.0 * max(x_spacing_km, y_spacing_km), 1e-9),
        0.0,
        1.0,
    )
    incision_m *= coastal_gate
    incision_m = np.minimum(incision_m, 0.55 * np.maximum(elevation_m, 0.0))
    floor_control = np.where(channel, 0.35 + 0.60 * log_progress, 0.0)
    floor_shoulders = _masked_smooth(floor_control, land_mask, iterations=2)
    detail_suppression = np.clip(
        0.68 * floor_control
        + 0.22 * floor_shoulders
        + 0.22 * trunk_shoulders,
        0.0,
        0.92,
    )
    detail_suppression *= coastal_gate
    detail_suppression[terminals] = 0.0
    retained_detail_m = (
        np.zeros_like(elevation_m)
        if residual_detail_m is None
        else residual_detail_m * (1.0 - detail_suppression)
    )
    source_elevation_m = elevation_m + retained_detail_m
    maximum_incision_m = np.maximum(
        incision_m,
        np.minimum(
            0.60 * np.maximum(source_elevation_m, 0.0),
            incision_m + 0.02 * maximum_elevation_m,
        ),
    )
    # Corrections can use the remaining local budget, but cannot exceed it.
    maximum_incision_m = np.minimum(maximum_incision_m, budget_m)
    incision_m, floor_correction_m, unresolved_uphill_edges = (
        condition_channel_floors(
            source_elevation_m,
            incision_m,
            maximum_incision_m,
            channel,
            receivers,
            routing_surface,
        )
    )
    (
        incision_m,
        steepness_correction_m,
        unresolved_steepening_edges,
        maximum_downstream_steepening_ratio,
    ) = condition_downstream_channel_steepness(
        source_elevation_m,
        incision_m,
        maximum_incision_m,
        channel,
        receivers,
        routing_surface,
        tree_accumulation_km2,
        x_spacing_km=x_spacing_km,
        y_spacing_km=y_spacing_km,
    )
    floor_correction_m += steepness_correction_m
    return DrainageIncision(
        source_elevation_m=elevation_m.copy(),
        routing_elevation_m=routing_surface,
        receivers=receivers,
        outlet_mask=land_mask & (receivers < 0),
        retention_terminal_mask=terminals.copy(),
        incision_m=np.where(land_mask, incision_m, 0.0),
        incision_limit_m=np.where(land_mask, maximum_incision_m, 0.0),
        accumulation_km2=accumulation_km2,
        detail_suppression=np.where(land_mask, detail_suppression, 0.0),
        channel_mask=channel,
        channel_head_mask=channel_heads,
        stream_order=stream_order,
        floor_correction_m=np.where(land_mask, floor_correction_m, 0.0),
        steepness_correction_m=np.where(land_mask, steepness_correction_m, 0.0),
        unresolved_uphill_channel_edge_count=unresolved_uphill_edges,
        unresolved_steepening_edge_count=unresolved_steepening_edges,
        maximum_downstream_steepening_ratio=maximum_downstream_steepening_ratio,
    )
