"""Authored narrow cores cannot disappear solely through regular probe alignment."""

from dataclasses import replace
from itertools import pairwise

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import LineString, Point

from map_maker.terrain.pipeline.water_sampling import SamplingFeature, sample_ground_profile


def _flat(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
    return np.full(x.shape, 20., dtype=np.float32)


@pytest.mark.parametrize("radius", [.02, .002, .0002])
@pytest.mark.parametrize("offset", [0., .75])
def test_subspacing_points_and_near_misses_receive_core_samples(
    radius: float, offset: float,
) -> None:
    center = .437
    feature = SamplingFeature(Point(center, offset * radius), radius, radius)

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        distance = np.hypot(x - center, y - offset * radius)
        return (20 - 20 * np.exp(-np.log(2) * (distance / radius) ** 2)).astype(np.float32)

    vertices = ((0., 0.), (1., 0.))
    baseline = sample_ground_profile(vertices, .25, ground)
    assert baseline.minimum_ground_m is not None and baseline.minimum_ground_m > 19
    profile = sample_ground_profile(vertices, .25, ground, (feature,))
    assert profile.minimum_ground_m is not None and profile.minimum_ground_m < 7
    assert profile.feature_spacing_limit_km == radius / 4
    assert profile.feature_sample_count == len(profile.ground_m) - len(baseline.ground_m)
    assert set(baseline.positions_km) <= set(profile.positions_km)
    assert profile.positions_km[int(np.argmin(profile.ground_m))] == pytest.approx((center, 0))
    # A far-away feature does not refine this profile or move its baseline stations.
    far = replace(feature, geometry=Point(center, 3 * radius))
    assert sample_ground_profile(vertices, .25, ground, (far,)) == baseline


def test_multiple_line_crossings_corners_and_overlaps_are_deterministic() -> None:
    line = LineString(((.113, -.1), (.113, .1), (.437, .1), (.437, -.1),
                       (.863, -.1), (.863, .1)))
    feature = SamplingFeature(line, .002, .0006)
    point = SamplingFeature(Point(.437, 0.), .001, .001)
    vertices = ((0., 0.), (1., 0.), (1., 1.))

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        d = np.minimum.reduce([np.abs(x - c) for c in (.113, .437, .863)])
        return (20 + 30 * np.exp(-(d / .0005) ** 2)).astype(np.float32)

    baseline = sample_ground_profile(vertices, .25, ground)
    profile = sample_ground_profile(vertices, .25, ground, (feature, point))
    assert set(baseline.positions_km) <= set(profile.positions_km)
    for c in (.113, .437, .863):
        assert any(abs(x - c) < 1e-14 and y == 0 for x, y in profile.positions_km)
    assert profile.maximum_ground_m == 50
    # Reordering, redrawing a line backwards, and duplicate guidance cannot spend extra budget.
    backwards = replace(feature, geometry=LineString(tuple(reversed(line.coords))))
    assert sample_ground_profile(vertices, .25, ground, (point, backwards, point)) == profile
    positions = np.asarray(profile.positions_km)
    assert np.all(np.linalg.norm(np.diff(positions, axis=0), axis=1) > 0)
    assert np.all(np.linalg.norm(np.diff(positions, axis=0), axis=1) <= .25 + 1e-12)


@pytest.mark.parametrize("coordinates", [((.2, .001), (.8, .001)),
                                          ((.2, 0.), (.8, 0.)),
                                          ((.4, -.5), (.42, .5))])
def test_parallel_collinear_and_oblique_cores_keep_local_spacing(
    coordinates: tuple[tuple[float, float], ...],
) -> None:
    feature = SamplingFeature(LineString(coordinates), .002, .001)
    profile = sample_ground_profile(((0., 0.), (1., 0.)), .25, _flat, (feature,))
    assert profile.status == "sampled"
    points = np.asarray(profile.positions_km)
    for a, b in pairwise(points):
        if feature.geometry.distance(Point((a + b) / 2)) < .002:
            assert np.linalg.norm(b - a) <= .001 / 4 + 1e-12


def test_feature_budget_is_checked_before_sampling_and_overlaps_do_not_inflate_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature = SamplingFeature(LineString(((0., 0.), (10., 0.))), .0001, .0001)

    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("No prefix may be evaluated or mistaken for complete evidence.")

    profile = sample_ground_profile(((0., 0.), (10., 0.)), .25, unexpected, (feature, feature))
    assert profile.status == "budget_exceeded"
    assert profile.requested_sample_count > 400_000
    assert profile.feature_sample_count is None
    assert profile.feature_spacing_limit_km == .000025
    assert profile.positions_km == profile.ground_m == ()
    assert profile.minimum_ground_m is profile.maximum_ground_m is None
    assert sample_ground_profile(((0., 0.), (10., 0.)), .25, unexpected, (feature,)) == profile
    # Exact budget acceptance on a small, overlapping feature plan.
    small = replace(feature, influence_radius_km=.1, minimum_radius_km=.1)
    clear = sample_ground_profile(((0., 0.), (1., 0.)), .25, _flat, (small,))
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.MAX_PROFILE_SAMPLES",
                        clear.requested_sample_count)
    assert sample_ground_profile(((0., 0.), (1., 0.)), .25, _flat, (small, small)) == clear


@pytest.mark.parametrize("radius,minimum", [(0., 0.), (1., -1.), (1., 2.),
                                            (float("inf"), 1.), (1., float("nan"))])
def test_invalid_sampling_feature_radii_are_rejected(radius: float, minimum: float) -> None:
    with pytest.raises(ValueError, match="positive radii"):
        SamplingFeature(Point(0., 0.), radius, minimum)
