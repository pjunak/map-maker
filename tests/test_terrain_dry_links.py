# pyright: reportPrivateUsage=false
"""Dry terrain barriers, conservative alternatives and composed collection heads."""

from math import ceil, hypot

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Point, Polygon

from map_maker.terrain.domain import TerrainBasin
from map_maker.terrain.pipeline.basin_flow import _collect_basin
from map_maker.terrain.pipeline.dry_links import route_dry_links
from map_maker.terrain.pipeline.hydrology import D8_NEIGHBOURS
from map_maker.terrain.pipeline.water import MetricBasin
from map_maker.terrain.pipeline.water_sampling import SamplingFeature


def _graph(values: list[int]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    nodes = np.asarray(values, dtype=np.int64)
    lookup = {int(node): i for i, node in enumerate(nodes)}
    graph = np.full((len(nodes), 8), -1, dtype=np.int64)
    for i, node in enumerate(nodes):
        row, col = divmod(int(node), 6)
        for d, (dr, dc) in enumerate(D8_NEIGHBOURS):
            graph[i, d] = lookup.get((row+dr)*6+col+dc, -1)
    return nodes, graph


def _terminal(receivers: NDArray[np.int64], start: int) -> int:
    seen: set[int] = set()
    while receivers[start] >= 0:
        assert start not in seen
        seen.add(start)
        start = int(receivers[start])
    return start


@pytest.mark.parametrize("bypass,flat",
                         [(False, False), (True, False), (False, True), (True, True)])
def test_narrow_barrier_removes_link_and_allows_clear_alternatives(
    bypass: bool, flat: bool,
) -> None:
    nodes, graph = _graph([13, 14, 15, 19, 20] if bypass else [13, 14, 15])
    original = graph.copy()
    axis = np.arange(6, dtype=np.float64)
    wet = nodes == 15
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        base = np.interp(x, [1, 2, 3], [10, 10, 2] if flat else [30, 20, 2])
        return (base + np.where(np.hypot(x-1.371, y-2) < .001, 40, 0)).astype(np.float32)
    ground = sampler(*np.meshgrid(axis, axis)).astype(np.float64)
    args = (nodes, graph, wet, ground, axis, axis, 10., sampler)
    baseline = route_dry_links(*args)
    assert _terminal(baseline.routing.receivers, 0) == 2
    result = route_dry_links(*args, (SamplingFeature(Point(1.371, 2.), .001, .001),))
    assert result.review.blocked_link_count == 1
    assert (_terminal(result.routing.receivers, 0) == 2) == bypass
    assert result.routing.receivers[0] != 1
    blocked = next(link for link in result.review.links if link.blocked)
    assert (blocked.source_flat_index, blocked.target_flat_index) == (13, 14)
    assert blocked.maximum_uphill_excursion_m > 35
    assert blocked.feature_sample_count > 0
    assert np.hypot(blocked.crest_position_km[0]-1.371, blocked.crest_position_km[1]-2) <= .001
    again = route_dry_links(*args, (SamplingFeature(Point(1.371, 2.), .001, .001),))
    assert again.review == result.review
    np.testing.assert_array_equal(again.routing.receivers, result.routing.receivers)
    np.testing.assert_array_equal(graph, original)
    np.testing.assert_array_equal(ground, sampler(*np.meshgrid(axis, axis)))


def test_equal_head_link_must_pass_both_directions() -> None:
    nodes, graph = _graph([13, 14, 15])
    axis = np.arange(6, dtype=np.float64)
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.interp(x, [1, 1.25, 1.5, 1.75, 2, 3],
                         [10, 10.008, 10, 9.992, 10, 2]).astype(np.float32)
    ground = sampler(*np.meshgrid(axis, axis)).astype(np.float64)
    result = route_dry_links(nodes, graph, nodes == 15, ground, axis, axis, 10., sampler)
    assert result.review.blocked_link_count == 1
    assert result.review.links[0].maximum_uphill_excursion_m == pytest.approx(.016, abs=1e-6)
    assert result.review.links[0].low_position_km == (1.75, 2.)
    assert result.review.links[0].crest_position_km == (1.25, 2.)
    assert result.routing.receivers[0] == -1


def test_complete_path_rejects_combined_small_rises_without_losing_valid_suffix() -> None:
    nodes, graph = _graph([13, 14, 15, 16])
    axis = np.arange(6, dtype=np.float64)
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.interp(x, [1, 1.5, 2, 2.5, 3, 4],
                         [10, 9.992, 10, 10.008, 10, 2]).astype(np.float32)
    ground = sampler(*np.meshgrid(axis, axis)).astype(np.float64)
    result = route_dry_links(nodes, graph, nodes == 16, ground, axis, axis, 10., sampler)
    assert result.review.blocked_link_count == 0
    np.testing.assert_array_equal(result.routing.receivers, [1, 2, 3, -1])
    np.testing.assert_allclose(result.path_uphill_m, [.016, .008, 0, 0], atol=1e-6, rtol=0)
    assert result.review.cumulative_uphill_cell_count == 1
    barrier, = result.review.path_barriers
    assert barrier.source_flat_index == 13
    assert barrier.low_position_km == (1.5, 2.) and barrier.crest_position_km == (2.5, 2.)
    inside = np.zeros((6, 6), dtype=np.bool_)
    inside.ravel()[nodes] = True
    wet = np.zeros_like(inside)
    wet.ravel()[16] = True
    source = TerrainBasin(((.18, .38), (.82, .38), (.82, .42), (.18, .42), (.18, .38)),
                          "lake", 10.)
    basin = MetricBasin(source, Polygon(((.9, 1.9), (4.1, 1.9), (4.1, 2.1), (.9, 2.1))), None)
    collection = _collect_basin(basin, inside, wet, 16, ground, axis, axis, sampler, ())
    np.testing.assert_array_equal(collection.connected, [False, True, True, True])
    np.testing.assert_array_equal(collection.path_uphill_m, result.path_uphill_m)


@pytest.mark.parametrize("bed", [-50., 2.])
def test_water_surface_head_preserves_a_preferred_lower_closed_pit(bed: float) -> None:
    nodes, graph = _graph([13, 14, 21])
    axis = np.arange(6, dtype=np.float64)
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.where(y <= 2, 12+1.5*(x-2), 12+(bed-12)*(y-2)).astype(np.float32)
    ground = sampler(*np.meshgrid(axis, axis)).astype(np.float64)
    result = route_dry_links(nodes, graph, nodes == 21, ground, axis, axis, 10., sampler)
    assert result.review.blocked_link_count == 0
    assert result.routing.receivers[1] == 0  # 1.5 m/km to the pit beats 2/sqrt(2) to water.
    assert _terminal(result.routing.receivers, 1) == 0


def test_submerged_bed_rise_is_clipped_only_on_a_water_attachment() -> None:
    nodes, graph = _graph([13, 14])
    axis = np.arange(6, dtype=np.float64)
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.interp(x, [1, 1.25, 1.5, 1.75, 2], [12, 9, 1, 8, 2]).astype(np.float32)
    ground = sampler(*np.meshgrid(axis, axis)).astype(np.float64)
    water = route_dry_links(nodes, graph, nodes == 14, ground, axis, axis, 10., sampler)
    dry = route_dry_links(nodes, graph, np.zeros(2, dtype=np.bool_),
                          ground, axis, axis, 0., sampler)
    assert water.routing.receivers[0] == 1 and water.review.blocked_link_count == 0
    assert dry.routing.receivers[0] == -1 and dry.review.blocked_link_count == 1
    assert dry.review.links[0].maximum_uphill_excursion_m == 7


@pytest.mark.parametrize("limit", ["network", "profile", "refinement"])
def test_excessive_network_has_no_evaluation_or_accepted_dry_prefix(
    limit: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes, graph = _graph([13, 14, 15])
    axis = np.arange(6, dtype=np.float64)
    ground = np.full((6, 6), 10., dtype=np.float64)
    features: tuple[SamplingFeature, ...] = ()
    if limit == "profile":
        monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.MAX_PROFILE_SAMPLES", 4)
    else:
        monkeypatch.setattr("map_maker.terrain.pipeline.dry_links.MAX_DRY_LINK_SAMPLES",
                            9 if limit == "network" else 10)
        if limit == "refinement":
            features = (SamplingFeature(Point(1.371, 2.), .001, .001),)
    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("An excessive network cannot evaluate ground.")
    result = route_dry_links(nodes, graph, nodes == 15, ground, axis, axis,
                             10., unexpected, features)
    assert result.review.status == "budget_exceeded" and result.review.requested_sample_count >= 10
    assert result.review.links == () and result.review.path_barriers == ()
    assert result.review.blocked_link_count is result.review.cumulative_uphill_cell_count is None
    np.testing.assert_array_equal(result.routing.receivers, -1)
    assert not result.routing.flat_rank.any() and not result.path_uphill_m.any()


def test_endpoint_identity_and_bounded_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes, graph = _graph([13, 14, 15])
    axis = np.arange(6, dtype=np.float64)
    ground = np.full((6, 6), 10., dtype=np.float64)
    sizes: list[int] = []
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.SAMPLE_BATCH_SIZE", 3)
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        sizes.append(len(x))
        return np.full(x.shape, 10., dtype=np.float32)
    result = route_dry_links(nodes, graph, nodes == 15, ground, axis, axis, 10., sampler)
    # Two complete five-station links share one exact endpoint evaluation.
    assert sizes == [3, 3, 3] and result.review.requested_sample_count == 10
    assert result.routing.receivers[0] == 1
    ground[2, 1] = 11
    with pytest.raises(ValueError, match="canonical Float32"):
        route_dry_links(nodes, graph, nodes == 15, ground, axis, axis, 10., sampler)


@pytest.mark.parametrize("seed", [3, 13, 29])
def test_composed_summaries_match_independently_sampled_complete_paths(seed: int) -> None:
    nodes, graph = _graph(list(range(36)))
    # Avoid linear-index wraparound at the crop sides in this full-grid fixture.
    for node in range(36):
        for d, (dr, dc) in enumerate(D8_NEIGHBOURS):
            r, c = node // 6 + dr, node % 6 + dc
            graph[node, d] = r*6+c if 0 <= r < 6 and 0 <= c < 6 else -1
    axis = np.arange(6, dtype=np.float64)
    canonical = np.random.default_rng(seed).integers(10, 14, (6, 6)).astype(np.float64)
    canonical[-1, -1] = 2
    wet = nodes == 35
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        col = np.clip(np.floor(x).astype(np.intp), 0, 4)
        row = np.clip(np.floor(y).astype(np.intp), 0, 4)
        tx, ty = x-col, y-row
        values = ((canonical[row, col]*(1-tx)+canonical[row, col+1]*tx)*(1-ty)
                  + (canonical[row+1, col]*(1-tx)+canonical[row+1, col+1]*tx)*ty)
        return (values+.006*np.sin(np.pi*x)*np.sin(np.pi*y)).astype(np.float32)
    ground = sampler(*np.meshgrid(axis, axis)).astype(np.float64)
    result = route_dry_links(nodes, graph, wet, ground, axis, axis, 10., sampler)
    for source in nodes:
        node = int(source)
        profile = [10. if wet[node] else ground.ravel()[node]]
        visited: set[int] = set()
        while result.routing.receivers[node] >= 0:
            assert node not in visited
            visited.add(node)
            target = int(result.routing.receivers[node])
            x0, y0, x1, y1 = node % 6, node // 6, target % 6, target // 6
            count = 1 + max(2, ceil(hypot(x1-x0, y1-y0)/.25))
            heights = sampler(np.linspace(x0, x1, count), np.linspace(y0, y1, count))
            if wet[target]:
                heights = np.maximum(heights, 10.)
            profile.extend(float(h) for h in heights[1:])
            node = target
        values = np.asarray(profile)
        expected = float(np.max(values - np.minimum.accumulate(values)))
        assert result.path_uphill_m[source] == pytest.approx(expected, abs=1e-6)


def test_no_dry_candidates_need_no_sampling() -> None:
    nodes, graph = _graph([13, 14])
    axis = np.arange(6, dtype=np.float64)
    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("There are no candidate dry paths.")
    result = route_dry_links(nodes, graph, np.ones(2, dtype=np.bool_),
                             np.full((6, 6), 2.), axis, axis, 10., unexpected)
    assert result.review.status == "sampled" and result.review.requested_sample_count == 0
    assert result.review.candidate_link_count == 0
    assert np.all(result.routing.receivers == -1)
