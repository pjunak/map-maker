# pyright: reportPrivateUsage=false
"""Prepared guide bounds must preserve every geometric sampling decision."""

from dataclasses import replace
from fractions import Fraction
from math import inf, nextafter
from unittest.mock import patch

import numpy as np
import pytest
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from map_maker.terrain.pipeline import water_sampling as sampling
from map_maker.terrain.pipeline.water_sampling import (
    SamplingDensity,
    SamplingFeature,
    SamplingGuide,
    plan_ground_profile,
    profile_positions,
)


def test_disjoint_guides_skip_expensive_geometry_work() -> None:
    guides: tuple[SamplingGuide, ...] = (
        SamplingFeature(Point(20., 20.), .1, .1, .5),
        SamplingFeature(box(30., 30., 31., 31.), .1, .1),
        SamplingDensity(.01, box(40., 40., 41., 41.)),
    )
    vertices = ((0., 0.), (1., 1.))
    expected = plan_ground_profile(vertices, .25)
    with (
        patch.object(sampling, "_context_windows", side_effect=AssertionError("distant context")),
        patch.object(sampling, "_corridor_windows", side_effect=AssertionError("distant core")),
        patch.object(sampling, "_contained_intervals", side_effect=AssertionError("far region")),
    ):
        assert plan_ground_profile(vertices, .25, guides) == expected


def test_bounds_preserve_mixed_guides_corners_holes_and_grazing_contacts() -> None:
    guides: tuple[SamplingGuide, ...] = (
        SamplingFeature(Point(0., 0.), .05, .05, .4),
        SamplingFeature(LineString(((-1., .2), (0., .2), (.8, .7), (-.2, .5))), .12, .05, .6),
        SamplingFeature(Polygon(box(-.6, -.6, .6, .6).exterior,
                                [box(-.2, -.2, .2, .2).exterior]), .08, .08),
        SamplingDensity(.02, MultiPolygon([box(1., 1., 2., 2.), box(-2., -2., -1., -1.)])),
        SamplingDensity(.09),
    )
    random = np.random.default_rng(20260913)
    paths = [tuple((float(x), float(y)) for x, y in random.uniform(-3., 3., (3, 2)))
             for _ in range(36)]
    paths += [((-2., y), (2., y)) for y in (.1, nextafter(.1, inf), .6, .8, nextafter(.8, inf))]
    paths += [((-2., -.2), (-.2, -.2), (.2, -.2), (2., -.2)),
              ((-0., 0.), (0., 0.), (1., 1.), (-0., 0.)), ((-2., -2.), (2., 2.))]
    with patch.object(sampling, "_bounds_overlap", return_value=True):
        references = [plan_ground_profile(path, .25, guides) for path in paths]
    for path, reference in zip(paths, references, strict=True):
        actual = plan_ground_profile(path, .25, guides)
        assert actual == reference
        assert profile_positions(actual).tobytes() == profile_positions(reference).tobytes()


@pytest.mark.parametrize("spacing", [.01, .25, 2.])
def test_broad_context_and_contained_region_are_never_discarded(spacing: float) -> None:
    guides: tuple[SamplingGuide, ...] = (
        SamplingFeature(Point(.5, 1.), .01, .01, 1.),
        SamplingFeature(box(-100., -100., 100., 100.), .001, .001),
        SamplingDensity(.02, box(-100., -100., 100., 100.)),
    )
    path = ((0., 0.), (1., 0.))
    with patch.object(sampling, "_bounds_overlap", return_value=True):
        reference = plan_ground_profile(path, spacing, guides)
    assert plan_ground_profile(path, spacing, guides) == reference
    assert reference.requested_sample_count > 2


def test_edited_guides_rebuild_their_own_bounds() -> None:
    point = SamplingFeature(Point(10., 10.), .1, .1, .2)
    moved = replace(point, geometry=Point(.5, .5), context_radius_km=2.)
    assert point.bounds_km != moved.bounds_km
    assert moved.bounds_km[0] < -3.5 and moved.bounds_km[2] > 4.5
    local = SamplingDensity(.1, box(10., 10., 11., 11.))
    global_density = replace(local, geometry=None)
    assert local.bounds_km is not None and global_density.bounds_km is None
    assert replace(local, geometry=box(20., 20., 21., 21.)).bounds_km != local.bounds_km


@pytest.mark.parametrize("coordinate,radius", [(1., .1), (1e16, .1), (1e-10, 1e8), (-1e16, 3.)])
def test_prepared_bounds_round_outward(coordinate: float, radius: float) -> None:
    guide = SamplingFeature(Point(coordinate, coordinate), radius, radius)
    exact_low = Fraction(coordinate) - 2 * Fraction(radius)
    exact_high = Fraction(coordinate) + 2 * Fraction(radius)
    assert Fraction(guide.bounds_km[0]) <= exact_low
    assert Fraction(guide.bounds_km[1]) <= exact_low
    assert Fraction(guide.bounds_km[2]) >= exact_high
    assert Fraction(guide.bounds_km[3]) >= exact_high


def test_bounds_leave_excessive_complete_profiles_unresolved() -> None:
    guides = (SamplingDensity(1e-5), SamplingFeature(Point(100., 100.), .1, .1))
    with patch.object(sampling, "_bounds_overlap", return_value=True):
        reference = plan_ground_profile(((0., 0.), (1., 0.)), .25, guides)
    actual = plan_ground_profile(((0., 0.), (1., 0.)), .25, guides)
    assert actual == reference and actual.status == "budget_exceeded" and not actual.spans
