"""Connected canonical channel reaches with unique contributing-area hierarchy."""

from dataclasses import dataclass
from itertools import pairwise
from math import hypot

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.pipeline.hydrology import DrainageIncision, receiver_contributing_area

CHANNEL_NETWORK_ID = "canonical-d8-connected-reaches@1"
type Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class ChannelReach:
    """One directed path between a head, junction or terminal; no invented bends."""

    nodes: tuple[int, ...]
    points_km: tuple[Point, ...]
    downstream: int | None
    contributing_area_km2: float
    length_km: float
    stream_order: int


@dataclass(frozen=True, slots=True)
class ChannelNetwork:
    grid: EndpointGrid
    reaches: tuple[ChannelReach, ...]

    @property
    def edge_count(self) -> int:
        return sum(len(reach.nodes) - 1 for reach in self.reaches)


def build_channel_network(
    drainage: DrainageIncision, land_mask: NDArray[np.bool_], grid: EndpointGrid,
) -> ChannelNetwork:
    """Partition every selected edge exactly once, retaining exact junction nodes.

    Use unique D8 catchment area, not distributed MFD capture. A reach's area is
    measured at its last donor, before any other tributaries join its endpoint.
    It cannot exceed the next reach's area, so an area threshold preserves every
    selected path downstream. Geometry remains on the canonical routing grid.
    """
    receivers = drainage.receivers
    channels = drainage.channel_mask
    surface = drainage.routing_elevation_m
    if any(values.shape != grid.shape for values in (
        receivers, channels, surface, land_mask, drainage.stream_order,
    )):
        raise ValueError("Channel network arrays must match the routing grid.")
    if (np.any(receivers < -1) or np.any(receivers >= land_mask.size)
            or np.any(channels & ~land_mask) or np.any(~np.isfinite(surface[land_mask]))):
        raise ValueError("Channel network needs finite land and valid receiver indices.")
    linked = land_mask & (receivers >= 0)
    sources = np.flatnonzero(linked)
    targets = receivers.ravel()[sources]
    if (np.any(~land_mask.ravel()[targets])
            or np.any(surface.ravel()[targets] >= surface.ravel()[sources])):
        raise ValueError("Channel receivers must descend through land without cycles.")
    source_row, source_column = np.divmod(sources, grid.width)
    target_row, target_column = np.divmod(targets, grid.width)
    if np.any(np.maximum(abs(target_row-source_row), abs(target_column-source_column)) != 1):
        raise ValueError("Canonical channel receivers must be D8 neighbours.")
    if np.any(channels.ravel()[sources] & ~channels.ravel()[targets]):
        raise ValueError("Selected channels must stay connected downstream.")
    area = receiver_contributing_area(
        surface, land_mask, receivers, cell_area_km2=grid.x_spacing_km*grid.y_spacing_km,
    ).ravel()
    edges = (linked & channels).ravel()
    donor_count = np.zeros(land_mask.size, dtype=np.int32)
    np.add.at(donor_count, receivers.ravel()[edges], 1)
    starts = np.flatnonzero(edges & (donor_count != 1))
    reach_ids = {int(node): index for index, node in enumerate(starts)}
    paths: list[ChannelReach] = []
    flat_receivers = receivers.ravel()
    for node in starts:
        nodes = [int(node)]
        current = int(node)
        while True:
            current = int(flat_receivers[current])
            nodes.append(current)
            if not edges[current] or donor_count[current] != 1:
                break
        points = tuple((grid.extent_km[0] + (index % grid.width)*grid.x_spacing_km,
                        grid.extent_km[1] + (index // grid.width)*grid.y_spacing_km)
                       for index in nodes)
        paths.append(ChannelReach(
            tuple(nodes), points, reach_ids.get(current), float(area[nodes[-2]]),
            sum(hypot(b[0]-a[0], b[1]-a[1]) for a, b in pairwise(points)),
            int(drainage.stream_order.ravel()[node]),
        ))
    network = ChannelNetwork(grid, tuple(paths))
    if network.edge_count != int(np.count_nonzero(edges)):
        raise ValueError("Channel reaches did not cover every selected edge.")
    return network
