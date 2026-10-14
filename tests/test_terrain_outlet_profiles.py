"""Full route budgets, vertex identity and cumulative downstream rises."""

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Point

from map_maker.terrain.pipeline.outlet_profiles import sample_downstream_profile
from map_maker.terrain.pipeline.water_sampling import SamplingFeature


def test_local_crest_is_measured_from_an_earlier_low_not_the_global_maximum() -> None:
    vertices = ((0., 0.), (1., 0.), (2., 0.))
    feature = SamplingFeature(Point(1.537, 0.), .001, .001)

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        base = np.interp(x, (0, 1, 2), (100, 50, 40))
        return (base + 30 * np.exp(-((x - 1.537) / .001) ** 2)).astype(np.float32)

    review = sample_downstream_profile(vertices, (100., 50., 40.), True, .25, ground, (feature,))
    assert review.profile.maximum_ground_m == 100
    assert review.maximum_uphill_excursion_m is not None and review.maximum_uphill_excursion_m > 29
    assert review.rise_from_sample_index is not None and review.rise_to_sample_index is not None
    assert review.rise_from_sample_index < review.rise_to_sample_index
    assert review.profile.positions_km[review.rise_to_sample_index] == pytest.approx((1.537, 0))
    assert review.maximum_uphill_excursion_m == (
        review.profile.ground_m[review.rise_to_sample_index]
        - review.profile.ground_m[review.rise_from_sample_index])
    assert tuple(review.profile.positions_km[i]
                 for i in review.path_vertex_sample_indices) == vertices
    assert sample_downstream_profile(vertices, (100., 50., 40.), True, .25, ground,
                                     (feature,)) == review


def test_entire_path_has_one_budget_even_if_every_edge_would_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.MAX_PROFILE_SAMPLES", 5)

    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("An over-budget route must not evaluate a prefix.")

    review = sample_downstream_profile(((0., 0.), (1., 0.), (2., 0.), (3., 0.)),
                                       (3., 2., 1., 0.), True, .25, unexpected)
    assert review.profile.status == "budget_exceeded"
    assert review.profile.requested_sample_count == 13
    assert review.profile.positions_km == review.profile.ground_m == ()
    assert review.path_vertex_sample_indices == ()
    assert review.maximum_uphill_excursion_m is None
    assert review.rise_from_sample_index is review.rise_to_sample_index is None
    assert review.reaches_terminal  # Topology and availability of ground evidence are separate.


@pytest.mark.parametrize("terminal", [True, False])
def test_single_node_profile_preserves_scope_and_has_no_climb(terminal: bool) -> None:
    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.full(x.shape, 1., dtype=np.float32)
    review = sample_downstream_profile(((0., 0.),), (1.,), terminal, .25, ground)
    assert review.reaches_terminal == terminal
    assert review.maximum_uphill_excursion_m == 0
    assert review.rise_from_sample_index is review.rise_to_sample_index is None
    assert review.path_vertex_sample_indices == (0,)


def test_sampler_cannot_disagree_with_the_canonical_field() -> None:
    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.zeros(x.shape, dtype=np.float32)
    with pytest.raises(ValueError, match="canonical Float32"):
        sample_downstream_profile(((0., 0.), (1., 0.)), (1., 0.), True, .25, ground)
