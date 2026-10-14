"""Regional guidance samples physical transitions without global width proxies."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely import contains_xy
from shapely.geometry import Polygon, box

from map_maker.terrain.pipeline.water_sampling import (
    SamplingFeature,
    plan_ground_profile,
    profile_positions,
    sample_ground_profile,
)


def _flat(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
    return np.zeros(x.shape, np.float32)


@pytest.mark.parametrize("width,transition", [(.02, .002), (.0002, .1), (.000002, 10.)])
def test_thin_crossed_regions_receive_interior_probes(width: float, transition: float) -> None:
    polygon = box(.371 - width / 2, -10, .371 + width / 2, 10)
    feature = SamplingFeature(polygon, transition, transition)

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.where(contains_xy(polygon, x, y), 20., 0.).astype(np.float32)

    vertices = ((0., 0.), (1., 0.))
    baseline = sample_ground_profile(vertices, .25, ground)
    profile = sample_ground_profile(vertices, .25, ground, (feature,))
    assert baseline.maximum_ground_m == 0 and profile.maximum_ground_m == 20
    assert profile.status == "sampled" and profile.requested_sample_count < 100
    assert set(baseline.positions_km) <= set(profile.positions_km)
    inside = np.asarray([x for x, _y in profile.positions_km
                         if .371 - width / 2 <= x <= .371 + width / 2])
    assert len(inside) >= 5
    midpoints = (inside[:-1] + inside[1:]) / 2
    boundary_distance = width / 2 - np.abs(midpoints - .371)
    near = boundary_distance <= 2 * transition
    assert np.max(np.diff(inside)[near]) <= min(width, transition) / 4 + 1e-12


def test_deep_interiors_and_distant_regions_do_not_request_more_samples() -> None:
    vertices = ((0., 0.), (1., 0.))
    baseline = plan_ground_profile(vertices, .25)
    for polygon in (box(-10, -10, 10, 10), box(10, 10, 11, 11)):
        feature = SamplingFeature(polygon, .1, .1)
        assert plan_ground_profile(vertices, .25, (feature,)) == baseline
    # Even near a broad transition, a fully contained canonical edge needs no
    # denser probes when both the transition and crossed length already fit.
    feature = SamplingFeature(box(-10, -10, 10, 10), 10., 10.)
    assert plan_ground_profile(vertices, .25, (feature,)) == baseline


def test_concave_multiple_crossings_holes_and_equivalent_rings() -> None:
    polygon = Polygon(((.1, -.1), (.1, .2), (.9, .2), (.9, -.1), (.88, -.1),
                       (.88, .1), (.12, .1), (.12, -.1)))
    feature = SamplingFeature(polygon, .001, .001)
    vertices = ((0., 0.), (1., 0.))
    profile = sample_ground_profile(vertices, .25, _flat, (feature,))
    positions = np.asarray(profile.positions_km)
    assert np.any((positions[:, 0] > .1) & (positions[:, 0] < .12))
    assert np.any((positions[:, 0] > .88) & (positions[:, 0] < .9))
    ring = list(polygon.exterior.coords)[:-1]
    for points in (ring[3:] + ring[:3], list(reversed(ring))):
        equivalent = replace(feature, geometry=Polygon(points))
        assert sample_ground_profile(vertices, .25, _flat, (equivalent, equivalent)) == profile
    hole = Polygon(((-1, -1), (2, -1), (2, 1), (-1, 1)),
                   holes=[((.35, -.1), (.39, -.1), (.39, .1), (.35, .1))])
    plan = plan_ground_profile(vertices, .25, (SamplingFeature(hole, .01, .01),))
    assert plan.requested_sample_count > 5 and plan.status == "sampled"


def test_redundant_close_vertices_do_not_define_a_global_sampling_radius() -> None:
    polygon = Polygon(((.36, -1), (.36, -1 + 1e-12), (.36, 1), (.38, 1), (.38, -1)))
    assert polygon.minimum_clearance < 1e-10
    plan = plan_ground_profile(((0., 0.), (1., 0.)), .25,
                               (SamplingFeature(polygon, .01, .01),))
    assert plan.status == "sampled" and plan.requested_sample_count < 100
    assert plan.feature_spacing_limit_km == .0025


def test_tangent_region_has_finite_bounded_evidence() -> None:
    triangle = Polygon(((.371, 0.), (.3, .1), (.4, .1)))
    plan = plan_ground_profile(((0., 0.), (1., 0.)), .25,
                               (SamplingFeature(triangle, .01, .01),))
    positions = profile_positions(plan)
    assert np.isfinite(positions).all() and 5 < len(positions) < 100
    assert np.all(np.diff(positions[:, 0]) > 0)


def test_long_parallel_region_budget_never_evaluates_an_accepted_prefix() -> None:
    feature = SamplingFeature(box(0, 0, 10, 10), .00001, .00001)

    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("An excessive regional profile must not sample a prefix.")

    result = sample_ground_profile(((0., 0.), (10., 0.)), .25, unexpected, (feature,))
    assert result.status == "budget_exceeded" and result.requested_sample_count > 65536
    assert result.positions_km == result.ground_m == ()
