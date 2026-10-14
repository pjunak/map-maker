# pyright: reportPrivateUsage=false
"""Connected crest ownership, conflicting contacts and delivered-field invariants."""

from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import LineString, Point

from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    LandformSettings,
    TerrainRegion,
    TerrainSettings,
    TerrainStructure,
)
from map_maker.terrain.domain import StructureProfileKnot as Knot
from map_maker.terrain.pipeline.generate import generate_terrain, prepare_terrain_field
from map_maker.terrain.pipeline.ridge_crests import (
    CrestBlend,
    ProfileRidge,
    validate_ridge_contacts,
)

COAST = Coastline(((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.)), "crest-square")
SETTINGS = TerrainSettings(seed=42, object_scale_km=1000., resolution_px=65, coastal_rise_km=5.)
PLAIN = TerrainRegion(COAST.points, LandformSettings("plain", 450., 0., 150., 50.))
MAIN = TerrainStructure("ridge", ((.1, .5), (.9, .5)), 1800., 40., profile=(
    Knot(0., 700.), Knot(.25, 2800.), Knot(.5, 1400.), Knot(.75, 2400.), Knot(1., 600.)))
SPUR = TerrainStructure("ridge", ((.3, .5), (.28, .65), (.2, .8)), 1800., 60., profile=(
    Knot(0., 2800.), Knot(.5, 1300.), Knot(1., 550.)))


@pytest.mark.parametrize("scale,seed", [(500., 42), (1000., 43), (2000., 20260902)])
def test_joined_ridges_retain_each_crest_along_the_whole_profile(scale: float, seed: int) -> None:
    field = prepare_terrain_field(COAST, replace(SETTINGS, object_scale_km=scale, seed=seed),
                                  (PLAIN, MAIN, SPUR), None)
    for constraint, authored in zip(field.constraints, (MAIN, SPUR), strict=True):
        line = constraint.geometry
        assert isinstance(line, LineString)
        points = np.array([line.interpolate(k.position, normalized=True).coords[0]
                           for k in authored.profile])
        heights = field.sample_ground(points[:, 0], points[:, 1])
        np.testing.assert_allclose(heights, [k.elevation_m for k in authored.profile], atol=.002)
    # The pass must remain a crosswise crest, not a whole flat shelf.
    cross = field.sample_ground(np.full(3, .5*scale), np.array([.4, .5, .6])*scale)
    assert cross[1] > max(cross[0], cross[2]) + 100.


def test_close_parallel_crests_keep_distinct_targets_even_when_responses_round_to_one() -> None:
    first = replace(MAIN, profile=(Knot(0., 1000.), Knot(1., 1000.)))
    second = replace(first, points=((.1, .5000000000001), (.9, .5000000000001)),
                     profile=(Knot(0., 3000.), Knot(1., 3000.)))
    field = prepare_terrain_field(COAST, SETTINGS, (PLAIN, first, second), None)
    values = field.sample_ground(np.array([500., 500.]),
                                 np.array([first.points[0][1], second.points[0][1]])*1000.)
    np.testing.assert_array_equal(values, [1000., 3000.])


def test_blend_preserves_exact_shared_values_and_zero_response_without_nan() -> None:
    blend = CrestBlend(np.full(4, 450.))
    with np.errstate(all="raise"):
        blend.add(np.array([1., 1., .5, 0.]), np.full(4, 2000.), np.array([0., 2., 5., 0.]))
        blend.add(np.array([1., 1., .5, 0.]), np.array([2000., 1000., 1000., 1000.]),
                  np.array([0., 0., 5., 0.]))
        values = blend.apply(np.full(4, 450.))
    np.testing.assert_array_equal(values, [2000., 1000., 975., 450.])


def test_conflicting_join_reports_original_instruction_numbers_before_routing() -> None:
    conflict = replace(SPUR, profile=(Knot(0., 2200.), Knot(1., 550.)))
    with pytest.raises(ValueError, match=r"junction conflict: instructions 2 and 3.*2800.*2200"):
        prepare_terrain_field(COAST, SETTINGS, (PLAIN, MAIN, conflict), None)


def test_crossing_contacts_are_checked_and_separate_nearby_endpoints_stay_separate() -> None:
    main = ProfileRidge(1, LineString([(0., 0.), (10., 0.)]), (0., 10.), (1000., 1000.))
    crossing = ProfileRidge(2, LineString([(5., -5.), (5., 5.)]), (0., 10.), (2000., 1000.))
    with pytest.raises(ValueError, match=r"1500\.000"):
        validate_ridge_contacts((main, crossing))
    validate_ridge_contacts((main, replace(crossing, heights_m=(1000., 1000.))))
    separated = replace(crossing, line=LineString([(5., .001), (5., 5.)]))
    before = separated.line.wkb
    validate_ridge_contacts((main, separated))
    assert separated.line.wkb == before


@pytest.mark.parametrize("points,match", [
    ([(0., 0.), (10., 0.)], "overlap along a line"),
    ([(0., 0.), (5., 5.), (0., 5.), (5., 0.)], "simple, open line"),
    ([(0., 0.), (5., 5.), (10., 0.), (0., 0.)], "simple, open line"),
])
def test_ambiguous_profile_geometry_has_actionable_errors(
    points: list[tuple[float, float]], match: str,
) -> None:
    main = ProfileRidge(1, LineString([(0., 0.), (10., 0.)]), (0., 10.), (1000., 1000.))
    line = LineString(points)
    other = ProfileRidge(2, line, (0., line.length), (1000., 1000.))
    with pytest.raises(ValueError, match=match):
        validate_ridge_contacts((main, other))


def test_three_way_join_is_compatible_within_one_millimetre() -> None:
    ridges = tuple(ProfileRidge(i+1, LineString([(0., 0.), end]), (0., 10.),
                               (1000.+i*.0004, 500.))
                   for i, end in enumerate(((10., 0.), (0., 10.), (-10., 0.))))
    validate_ridge_contacts(ridges)
    assert ridges[1].height_at(Point(0., 0.)) == pytest.approx(1000.0004)


def test_reordering_resolution_chunks_points_valleys_and_coast_retain_their_contracts() -> None:
    point = ElevationPoint((.3, .5), 2300., 8.)
    valley = TerrainStructure("valley", ((.5, .2), (.5, .8)), 100., 15.,
                              profile=(Knot(0., 100.), Knot(1., 100.)))
    inputs = (PLAIN, MAIN, SPUR, valley, point)
    low = generate_terrain(COAST, SETTINGS, constraints=inputs)
    high = generate_terrain(COAST, replace(SETTINGS, resolution_px=129),
                            constraints=tuple(reversed(inputs)))
    np.testing.assert_array_equal(low.elevation_m, high.elevation_m[::2, ::2])
    np.testing.assert_array_equal(low.routing.receivers, high.routing.receivers)
    np.testing.assert_array_equal(low.elevation_m[[0, -1]], 0.)
    assert np.all(np.isfinite(low.elevation_m[low.land_mask]))
    assert np.all(low.routing.incision_m <= low.routing.incision_limit_m)
    field = prepare_terrain_field(COAST, SETTINGS, inputs, None)
    np.testing.assert_allclose(field.sample_ground(np.array([300.]), np.array([500.])),
                               [2300.], atol=.002)
    # A final hard point has broad support and can raise the nearby valley.
    valley_only = prepare_terrain_field(COAST, SETTINGS, inputs[:-1], None)
    np.testing.assert_allclose(valley_only.sample_ground(np.array([500.]), np.array([500.])),
                               [100.], atol=.002)
    x = np.linspace(180., 800., 31)
    y = np.linspace(480., 650., 31)
    np.testing.assert_array_equal(field.sample_ground(x, y), np.concatenate([
        field.sample_ground(x[:13], y[:13]), field.sample_ground(x[13:], y[13:])]))


def test_smoothing_preserves_authored_corner_junctions_and_inputs() -> None:
    main = replace(MAIN, points=((.2, .3), (.5, .6), (.8, .3)),
                   profile=(Knot(0., 2000.), Knot(1., 2000.)))
    branch = replace(SPUR, points=((.5, .6), (.5, .85)),
                     profile=(Knot(0., 2000.), Knot(1., 600.)))
    original = (main.points, branch.points)
    field = prepare_terrain_field(COAST, SETTINGS, (PLAIN, main, branch), None)
    root = Point(500., 600.)
    assert all(c.geometry.distance(root) == 0. for c in field.constraints)
    assert not field.constraints[1].taper_start
    np.testing.assert_allclose(field.sample_ground(np.array([500.]), np.array([600.])),
                               [2000.], atol=.002)
    assert (main.points, branch.points) == original
    reverse = replace(main, points=tuple(reversed(main.points)))
    reordered = prepare_terrain_field(COAST, SETTINGS, (branch, reverse, PLAIN), None)
    x, y = np.meshgrid(np.linspace(400., 600., 31), np.linspace(500., 700., 31))
    np.testing.assert_array_equal(field.sample_ground(x, y), reordered.sample_ground(x, y))
