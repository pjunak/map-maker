"""Finer wet connectivity, alternate paths and atomic sampling budgets."""

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Point, box

from map_maker.terrain.pipeline.hydrology import D8_NEIGHBOURS
from map_maker.terrain.pipeline.water_sampling import (
    SamplingDensity,
    SamplingFeature,
    SamplingGuide,
)
from map_maker.terrain.pipeline.wet_links import review_wet_links


def _graph(bypass: bool = False) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    nodes = np.asarray([11, 12, 13, 16, 17] if bypass else [11, 12, 13], dtype=np.int64)
    lookup = {int(node): i for i, node in enumerate(nodes)}
    neighbours = np.full((len(nodes), 8), -1, dtype=np.int64)
    for i, node in enumerate(nodes):
        row, col = divmod(int(node), 5)
        for direction, (dr, dc) in enumerate(D8_NEIGHBOURS):
            neighbours[i, direction] = lookup.get((row+dr)*5+col+dc, -1)
    return nodes, neighbours


@pytest.mark.parametrize("regional", [False, True])
@pytest.mark.parametrize("height,bypass", [(20., False), (20., True), (9., False), (10.005, False)])
def test_water_links_use_water_level_and_clear_alternate_paths(
    height: float, bypass: bool, regional: bool,
) -> None:
    nodes, neighbours = _graph(bypass)
    before = neighbours.copy()
    ground = np.full((5, 5), 2., dtype=np.float64)
    axis = np.arange(5, dtype=np.float64)
    geometry = box(1.370, 1.99, 1.372, 2.01) if regional else Point(1.371, 2.)
    feature = SamplingFeature(geometry, .001, .001)
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.where(np.hypot(x-1.371, y-2.) < .001, height, 2.).astype(np.float32)
    args = (nodes, neighbours, np.ones(len(nodes), dtype=np.bool_), 11, ground, axis, axis, 10.)
    baseline, reachable = review_wet_links(*args, sampler)
    assert baseline.blocked_link_count == 0 and reachable.all()
    review, reachable = review_wet_links(*args, sampler, (feature,))
    blocked = height > 10.01
    assert review.blocked_link_count == int(blocked)
    assert reachable.all() == (bypass or not blocked)
    assert review.contact_reachable_wet_cell_count == int(reachable.sum())
    assert review.requested_sample_count == sum(link.sample_count for link in review.links)
    if blocked:
        link = next(link for link in review.links if link.blocked)
        assert (link.first_flat_index, link.second_flat_index) == (11, 12)
        assert np.hypot(link.maximum_position_km[0]-1.371,
                        link.maximum_position_km[1]-2.) <= .001 + 1e-12
        assert link.maximum_ground_m == height
    repeated, again = review_wet_links(*args, sampler, (feature,))
    assert repeated == review
    np.testing.assert_array_equal(again, reachable)
    np.testing.assert_array_equal(neighbours, before)
    np.testing.assert_array_equal(ground, 2.)


@pytest.mark.parametrize("limit", ["network", "profile", "refinement", "detail"])
def test_budget_failure_keeps_no_accepted_prefix(
    limit: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes, neighbours = _graph()
    ground = np.full((5, 5), 2., dtype=np.float64)
    axis = np.arange(5, dtype=np.float64)
    features: tuple[SamplingGuide, ...] = ()
    if limit == "profile":
        monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.MAX_PROFILE_SAMPLES", 4)
    else:
        monkeypatch.setattr("map_maker.terrain.pipeline.wet_links.MAX_WET_LINK_SAMPLES",
                            9 if limit == "network" else 10)
        if limit == "refinement":
            features = (SamplingFeature(Point(1.371, 2.), .001, .001),)
        elif limit == "detail":
            features = (SamplingDensity(.01),)
    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("No ground evaluation is allowed for an excessive whole-network plan.")
    review, reachable = review_wet_links(nodes, neighbours, np.ones(3, dtype=np.bool_), 11,
                                        ground, axis, axis, 10., unexpected, features)
    assert review.status == "budget_exceeded"
    assert review.candidate_link_count == 2
    assert review.requested_sample_count >= 10
    assert review.links == () and not reachable.any()
    assert review.blocked_link_count is review.contact_reachable_wet_cell_count is None


def test_endpoint_identity_and_batched_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes, neighbours = _graph()
    ground = np.full((5, 5), 2., dtype=np.float64)
    axis = np.arange(5, dtype=np.float64)
    sizes: list[int] = []
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.SAMPLE_BATCH_SIZE", 3)
    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        sizes.append(len(x))
        return np.full(x.shape, 2., dtype=np.float32)
    args = (nodes, neighbours, np.ones(3, dtype=np.bool_), 11, ground, axis, axis, 10.)
    review, connected = review_wet_links(*args, sampler)
    # Two complete five-station links share one exact endpoint evaluation.
    assert sizes == [3, 3, 3]
    assert review.requested_sample_count == 10 and connected.all()
    ground[2, 1] = 3
    with pytest.raises(ValueError, match="canonical Float32"):
        review_wet_links(*args, sampler)


def test_a_dry_node_cannot_join_two_wet_pools() -> None:
    nodes, neighbours = _graph()
    ground = np.full((5, 5), 2., dtype=np.float64)
    axis = np.arange(5, dtype=np.float64)
    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("There are no direct wet links to sample.")
    review, reachable = review_wet_links(
        nodes, neighbours, np.asarray([True, False, True], dtype=np.bool_),
        11, ground, axis, axis, 10., unexpected)
    assert review.status == "sampled" and review.requested_sample_count == 0
    assert review.contact_reachable_wet_cell_count == 1
    np.testing.assert_array_equal(reachable, [True, False, False])
