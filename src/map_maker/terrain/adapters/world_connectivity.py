"""Bounded graph decoding with source-derived incidence verification."""

from collections.abc import Callable, Mapping

import numpy as np

from map_maker.terrain.adapters.numeric import read_numeric_archive
from map_maker.terrain.domain.world_context import SphericalContextGrid
from map_maker.terrain.pipeline.world import WorldMap
from map_maker.terrain.pipeline.world_connectivity import (
    CONNECTIVITY_ALGORITHM,
    MAX_WATER_LINKS,
    MAX_WATER_PIECES,
    WaterConnectivity,
)
from map_maker.terrain.pipeline.world_context import source_water_connectivity


def read_water_connectivity(
    data: bytes,
    metadata: Mapping[str, object],
    world: WorldMap,
    grid: SphericalContextGrid,
    *,
    checkpoint: Callable[[], None],
) -> WaterConnectivity:
    """Hashes alone cannot establish whether a rehashed edge crosses land.

    Regenerate only the source incidence, not shoreline/exposure fields. Compare
    every ordered array before accepting stored links or computing adjacency from
    them. Different geometry runtimes may require generating a fresh context.
    """
    if metadata.get("algorithm") != CONNECTIVITY_ALGORITHM:
        raise ValueError("Unsupported water connectivity algorithm; generate context again.")
    counts: list[int] = []
    for key, maximum in (("pieces", MAX_WATER_PIECES), ("links", MAX_WATER_LINKS)):
        value = metadata.get(key)
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"Invalid or oversized water connectivity count: {key}.")
        counts.append(value)
    nodes, links = counts
    rows, columns = grid.shape
    stored = read_numeric_archive(
        data,
        {
            "cell_offsets": ((rows * columns + 1,), "<i4"),
            "water_body": ((nodes,), "<i4"),
            "area_km2": ((nodes,), "<f8"),
            "sample_uv": ((nodes, 2), "<f8"),
            "link_nodes": ((links, 2), "<i4"),
            "link_axis": ((links,), "u1"),
            "link_interval": ((links, 2), "<f8"),
            "link_width_km": ((links,), "<f8"),
        },
    )
    checkpoint()
    graph = source_water_connectivity(world, grid, checkpoint=checkpoint)
    for name, expected in graph.arrays().items():
        if not np.array_equal(stored[name], expected):
            raise ValueError(
                f"Water connectivity disagrees with source geometry: {name}; "
                "generate context again."
            )
    return graph
