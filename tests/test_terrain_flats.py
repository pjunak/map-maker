"""Exact flats gain acyclic routes only through actual, permitted graph exits."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Polygon

from map_maker.terrain.domain import TerrainBasin
from map_maker.terrain.pipeline.flat_routing import FlatRouting, route_flats
from map_maker.terrain.pipeline.hydrology import D8_NEIGHBOURS
from map_maker.terrain.pipeline.link_planning import basin_neighbours
from map_maker.terrain.pipeline.water import MetricBasin, basin_intent_ids


def _graph(shape: tuple[int, int]) -> NDArray[np.int64]:
    height, width = shape
    neighbours = np.full((height * width, 8), -1, dtype=np.int64)
    for row in range(height):
        for col in range(width):
            for direction, (dr, dc) in enumerate(D8_NEIGHBOURS):
                r, c = row + dr, col + dc
                if 0 <= r < height and 0 <= c < width:
                    neighbours[row * width + col, direction] = r * width + c
    return neighbours


def _route(head: NDArray[np.float64], terminals: tuple[int, ...] = ()) -> FlatRouting:
    mask = np.zeros(head.size, dtype=np.bool_)
    mask[list(terminals)] = True
    return route_flats(head.ravel(), _graph(head.shape), mask,
                       x_spacing_km=1., y_spacing_km=1.)


def _roots(routing: FlatRouting, head: NDArray[np.float64]) -> NDArray[np.int64]:
    """Independently follow every path and reject cycles, climbing and rank stalls."""
    receivers = routing.receivers
    heights = head.ravel()
    roots = np.full(receivers.size, -1, dtype=np.int64)
    for source in range(receivers.size):
        node = source
        visited: set[int] = set()
        while receivers[node] >= 0:
            assert node not in visited
            visited.add(node)
            target = int(receivers[node])
            assert heights[target] <= heights[node]
            if heights[target] == heights[node]:
                assert routing.flat_rank[node] > routing.flat_rank[target]
            node = target
        roots[source] = node
    return roots


def test_flat_with_an_exit_drains_without_modifying_heads() -> None:
    head = np.full((9, 9), 20., dtype=np.float64)
    head[1:8, 1:8] = 10
    head[8, 4] = 9
    before = head.copy()
    result = _route(head, (76,))
    roots = _roots(result, head).reshape(head.shape)
    np.testing.assert_array_equal(roots[1:8, 1:8], 76)
    assert np.count_nonzero(result.flat_rank) > 30
    # At equal exit distance, proximity to the high side raises the routing rank.
    assert result.flat_rank[4 * 9 + 1] > result.flat_rank[4 * 9 + 4]
    np.testing.assert_array_equal(head, before)


def test_closed_flat_does_not_invent_a_crop_boundary_exit() -> None:
    head = np.full((7, 9), 10., dtype=np.float64)
    result = _route(head)
    np.testing.assert_array_equal(result.receivers, -1)
    np.testing.assert_array_equal(result.flat_rank, 0)


def test_multiple_exits_include_paths_that_end_in_a_lower_closed_pit() -> None:
    head = np.full((9, 11), 20., dtype=np.float64)
    head[1:8, 1:10] = 10
    head[4, 2] = 8
    head[4, 10] = 9
    result = _route(head, (54,))
    roots = _roots(result, head).reshape(head.shape)
    assert set(np.unique(roots[1:8, 1:10])) == {46, 54}
    assert roots[4, 1] == 46
    assert roots[4, 9] == 54


def test_terminal_at_equal_water_head_can_receive_a_flat() -> None:
    head = np.full((1, 11), 10., dtype=np.float64)
    result = _route(head, (10,))
    np.testing.assert_array_equal(_roots(result, head), 10)
    assert result.receivers[10] == -1
    assert result.flat_rank[10] == 0
    assert np.all(result.flat_rank[:-1] > 0)


def test_nearly_equal_ground_is_not_flattened_over_a_real_barrier() -> None:
    head = np.array([[10., 10., float(np.nextafter(np.float32(10), np.float32(11))), 9.]])
    result = _route(head, (3,))
    np.testing.assert_array_equal(result.receivers[:2], -1)
    np.testing.assert_array_equal(result.flat_rank[:2], 0)
    assert result.receivers[2] == 3


@pytest.mark.parametrize("seed", [7, 31, 99])
def test_quantized_terrain_routes_acyclically_and_independently_of_node_order(seed: int) -> None:
    rng = np.random.default_rng(seed)
    head = rng.integers(0, 6, (13, 17)).astype(np.float64)
    neighbours = _graph(head.shape)
    terminals = np.zeros(head.size, dtype=np.bool_)
    terminals[-1] = True
    original_neighbours = neighbours.copy()
    result = route_flats(head.ravel(), neighbours, terminals, x_spacing_km=2., y_spacing_km=3.)
    _roots(result, head)
    order = rng.permutation(head.size)
    inverse = np.argsort(order)
    remapped = np.where(neighbours[order] >= 0, inverse[np.maximum(neighbours[order], 0)], -1)
    other = route_flats(head.ravel()[order], remapped, terminals[order],
                        x_spacing_km=2., y_spacing_km=3.)
    np.testing.assert_array_equal(other.flat_rank[inverse], result.flat_rank)
    targets = other.receivers[inverse]
    np.testing.assert_array_equal(np.where(targets >= 0, order[np.maximum(targets, 0)], -1),
                                  result.receivers)
    np.testing.assert_array_equal(neighbours, original_neighbours)


def test_strict_downhill_choice_uses_metric_spacing() -> None:
    head = np.full((3, 3), 30., dtype=np.float64)
    head[1, 1], head[0, 1], head[1, 2] = 20, 10, 5
    terminals = np.zeros(9, dtype=np.bool_)
    terminals[[1, 5]] = True
    north = route_flats(head.ravel(), _graph(head.shape), terminals,
                        x_spacing_km=2., y_spacing_km=1.)
    east = route_flats(head.ravel(), _graph(head.shape), terminals,
                       x_spacing_km=1., y_spacing_km=2.)
    assert north.receivers[4] == 1
    assert east.receivers[4] == 5
    assert north.flat_rank[4] == east.flat_rank[4] == 0


def test_vector_gap_between_samples_is_not_a_flat_link() -> None:
    # The notch lies between sampled rows and separates two equal-height arms.
    polygon = Polygon(((0, 0), (4, 0), (4, 1.4), (.4, 1.4),
                       (.4, 1.6), (4, 1.6), (4, 3), (0, 3)))
    source = TerrainBasin(tuple((x / 4, y / 3) for x, y in polygon.exterior.coords), 'lake', 10)
    basin = MetricBasin(source, polygon, None)
    x, y = np.arange(5, dtype=np.float64), np.arange(4, dtype=np.float64)
    xx, yy = np.meshgrid(x, y)
    ids = basin_intent_ids(xx, yy, (basin,))
    nodes, neighbours = basin_neighbours(basin, ids > 0, x, y)
    head = np.full(nodes.size, 10., dtype=np.float64)
    head[nodes == 10] = 11  # The only contained neck is higher than either arm.
    terminals = nodes == 19
    result = route_flats(head, neighbours, terminals, x_spacing_km=1., y_spacing_km=1.)
    roots = _roots(result, head)
    assert np.all(~terminals[roots[nodes < 10]])
    # Restoring a traversable neck permits the upper arm to reach the same outlet.
    head[nodes == 10] = 10
    open_result = route_flats(head, neighbours, terminals, x_spacing_km=1., y_spacing_km=1.)
    assert np.all(terminals[_roots(open_result, head)])
    diagonal = neighbours[nodes == 7, 7]
    assert diagonal[0] == -1
    # The vector geometry, not just the sample membership, owns every link.
    convex = replace(basin, geometry=Polygon(((0, 0), (4, 0), (4, 3), (0, 3))))
    _, convex_neighbours = basin_neighbours(convex, ids > 0, x, y)
    assert convex_neighbours[nodes == 7, 7][0] >= 0

    # A rejected steep diagonal must not hide an available contained descent.
    sloping_head = np.full(nodes.size, 20., dtype=np.float64)
    sloping_head[nodes == 7], sloping_head[nodes == 8], sloping_head[nodes == 13] = 10, 9, 0
    strict = route_flats(sloping_head, neighbours, (nodes == 8) | (nodes == 13),
                         x_spacing_km=1., y_spacing_km=1.)
    assert nodes[strict.receivers[nodes == 7]][0] == 8
    assert strict.flat_rank[nodes == 7][0] == 0


def test_empty_graph_and_invalid_geometry_arrays() -> None:
    empty = route_flats(np.empty(0), np.empty((0, 8), dtype=np.int64), np.empty(0, dtype=np.bool_),
                        x_spacing_km=1., y_spacing_km=1.)
    assert empty.receivers.size == empty.flat_rank.size == 0
    head = np.array([10., 10.])
    neighbours = _graph((1, 2))
    terminals = np.zeros(2, dtype=np.bool_)
    with pytest.raises(ValueError, match='finite heads'):
        route_flats(np.array([np.nan, 10.]), neighbours, terminals,
                    x_spacing_km=1., y_spacing_km=1.)
    with pytest.raises(ValueError, match='spacing'):
        route_flats(head, neighbours, terminals, x_spacing_km=float('inf'), y_spacing_km=1.)
    neighbours[0, 4] = 2
    with pytest.raises(ValueError, match='local node indices'):
        route_flats(head, neighbours, terminals, x_spacing_km=1., y_spacing_km=1.)
    neighbours[0, 4] = -1
    with pytest.raises(ValueError, match='symmetric'):
        route_flats(head, neighbours, terminals, x_spacing_km=1., y_spacing_km=1.)


@pytest.mark.parametrize("seed", [3, 17, 89])
def test_sparse_symmetric_links_keep_exact_flats_acyclic(seed: int) -> None:
    rng = np.random.default_rng(seed)
    head = rng.integers(0, 3, (15, 15)).astype(np.float64)
    graph = _graph(head.shape)
    for node in range(head.size):
        for d, target in enumerate(graph[node]):
            if target > node and rng.random() < .45:
                graph[node, d] = graph[target, 7-d] = -1
    wet = np.zeros(head.size, dtype=np.bool_)
    wet[-1] = True
    result = route_flats(head.ravel(), graph, wet, x_spacing_km=1., y_spacing_km=2.)
    _roots(result, head)
    # Every component with a real exit resolves, including exits to closed pits.
    seen: set[int] = set()
    for start in range(head.size):
        if start in seen:
            continue
        component = [start]
        seen.add(start)
        for node in component:
            for target in graph[node]:
                if (target >= 0 and target not in seen
                        and head.ravel()[target] == head.ravel()[start]):
                    component.append(int(target))
                    seen.add(int(target))
        has_exit = any(wet[n] or any(t >= 0 and head.ravel()[t] < head.ravel()[n]
                                     for t in graph[n]) for n in component)
        if has_exit:
            assert all(wet[n] or result.receivers[n] >= 0 for n in component)
        else:
            assert all(result.receivers[n] == -1 for n in component)
