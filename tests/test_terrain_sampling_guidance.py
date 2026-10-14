# pyright: reportPrivateUsage=false
"""Scale and shoulder guidance preserve the field, baseline probes and complete budgets."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from benchmarks.water_convergence import probe
from map_maker.terrain.domain import LandformSettings, TerrainRegion, TerrainSettings
from map_maker.terrain.pipeline.generate import _constraint_weight, _water_sampling_guides
from map_maker.terrain.pipeline.landforms import MetricRegion
from map_maker.terrain.pipeline.water_sampling import (
    SamplingDensity,
    SamplingFeature,
    plan_ground_profile,
    profile_positions,
    sample_ground_profile,
)


def _flat(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
    return np.zeros(x.shape, np.float32)


def test_global_detail_preserves_stations_and_bounds_each_physical_gap() -> None:
    vertices = ((-0., 0.), (.13, .27), (1., 1.))
    baseline = profile_positions(plan_ground_profile(vertices, .25))
    guide = SamplingDensity(.03125)
    plan = plan_ground_profile(vertices, .25, (guide, guide))
    positions = profile_positions(plan)
    assert {(float(x), float(y)) for x, y in baseline} <= {
        (float(x), float(y)) for x, y in positions}
    assert positions[0].tobytes() == baseline[0].tobytes()
    assert np.max(np.linalg.norm(np.diff(positions, axis=0), axis=1)) <= guide.spacing_km + 1e-12
    assert plan.feature_spacing_limit_km == guide.spacing_km
    assert plan == plan_ground_profile(vertices, .25, (guide,))
    assert plan_ground_profile(vertices, .25, (SamplingDensity(1.),)) == (
        plan_ground_profile(vertices, .25))


def test_regional_density_is_local_and_keeps_disconnected_crossings() -> None:
    vertices = ((0., 0.), (1., 0.))
    polygons = box(.11, -.1, .19, .1).union(box(.73, -.1, .81, .1))
    assert isinstance(polygons, MultiPolygon)
    guide = SamplingDensity(.01, polygons)
    plan = plan_ground_profile(vertices, .25, (guide,))
    x = profile_positions(plan)[:, 0]
    for low, high in ((.11, .19), (.73, .81)):
        inside = x[(x >= low) & (x <= high)]
        assert len(inside) >= 9 and np.max(np.diff(inside)) <= .01 + 1e-12
    assert x[(x > .25) & (x < .73)].tolist() == [.5]
    reverse = replace(guide, geometry=polygons.reverse())
    assert plan == plan_ground_profile(vertices, .25, (reverse,))
    far = replace(guide, geometry=box(10, 10, 11, 11))
    assert plan_ground_profile(vertices, .25, (far,)) == plan_ground_profile(vertices, .25)



@pytest.mark.parametrize("hole", [False, True])
def test_regional_density_keeps_tangent_contacts_in_otherwise_covered_paths(hole: bool) -> None:
    outer = ((-1., -1.), (2., -1.), (2., 2.), (-1., 2.))
    polygon = (Polygon(outer, holes=[((.437, 0.), (.537, .1), (.337, .1))]) if hole else
               Polygon(((-1., -1.), (2., -1.), (2., 2.), (.537, 2.),
                        (.437, 0.), (.337, 2.), (-1., 2.))))
    vertices = ((0., 0.), (1., 0.))
    assert polygon.covers(LineString(vertices))
    profile = sample_ground_profile(vertices, .25, _flat, (SamplingDensity(.13, polygon),))
    # The boundary contact splits the contained intervals despite having no gap.
    assert (.437, 0.) in profile.positions_km
    assert profile.requested_sample_count == 10
    assert set(sample_ground_profile(vertices, .25, _flat).positions_km) <= (
        set(profile.positions_km))

def test_detail_budget_does_not_evaluate_or_return_a_prefix() -> None:
    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("The complete detail budget must be accepted before evaluation.")
    result = sample_ground_profile(((0., 0.), (10., 0.)), .25, unexpected,
                                   (SamplingDensity(.00001),))
    assert result.status == "budget_exceeded" and result.requested_sample_count > 65536
    assert result.positions_km == result.ground_m == ()


@pytest.mark.parametrize("spacing", [0., -.1, float("nan"), float("inf")])
def test_invalid_density_is_rejected(spacing: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        SamplingDensity(spacing)


@pytest.mark.parametrize("distance", [.2, 1.01, 1.99, 2.01])
def test_broad_context_adds_a_closest_approach_even_when_no_finer_spacing_is_needed(
    distance: float,
) -> None:
    feature = SamplingFeature(Point(.437, distance), .001, .001, 1.)
    vertices = ((0., 0.), (1., 0.))
    baseline = sample_ground_profile(vertices, .25, _flat)
    profile = sample_ground_profile(vertices, .25, _flat, (feature,))
    if distance <= 2:
        assert profile.requested_sample_count == baseline.requested_sample_count + 1
        assert (.437, 0.) in profile.positions_km
    else:
        assert profile == baseline
    assert set(baseline.positions_km) <= set(profile.positions_km)


def test_narrow_context_and_reversed_polyline_are_deterministic() -> None:
    line = LineString(((.113, .01), (.437, .02), (.863, .01)))
    guide = SamplingFeature(line, .001, .001, .02)
    profile = sample_ground_profile(((0., 0.), (1., 0.)), .25, _flat, (guide,))
    assert profile.feature_spacing_limit_km == .005
    assert profile.requested_sample_count > 5
    reverse = replace(guide, geometry=LineString(list(reversed(line.coords))))
    assert sample_ground_profile(((0., 0.), (1., 0.)), .25, _flat, (reverse, reverse)) == profile


def test_density_preparation_uses_active_local_recipe_and_minimum_two_macro_octaves() -> None:
    polygon = box(0, 0, 100, 100)
    ring = ((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.))
    source = TerrainRegion(ring, LandformSettings("hills", 100., 100., 2., 1.))
    region = MetricRegion(polygon, source.settings, polygon)
    settings = TerrainSettings(detail_levels=1, variability=0.)
    guides = _water_sampling_guides((), (region,), settings)
    densities = [g for g in guides if isinstance(g, SamplingDensity)]
    assert len(densities) == 1 and densities[0].spacing_km == .5
    assert densities[0].geometry is not None and densities[0].geometry.equals(polygon)
    flat = replace(region, settings=replace(source.settings, relief_m=0.))
    flat_guides = _water_sampling_guides((), (flat,), settings)
    assert not any(isinstance(g, SamplingDensity) for g in flat_guides)
    global_guides = _water_sampling_guides(
        (), (), replace(settings, variability=.75, detail_levels=6))
    assert global_guides == (SamplingDensity(450 / 64),)


@pytest.mark.parametrize("structure,brush,attached,factors", [
    (True, False, False, (3., .8, .32)), (False, True, False, (1.75, .3, .18)),
    (False, False, True, (1.25, .15, .04)), (False, False, False, (2., .35, .12)),
])
def test_context_scale_extraction_preserves_the_exact_existing_weight(
    structure: bool, brush: bool, attached: bool, factors: tuple[float, float, float],
) -> None:
    distances = np.asarray([0., .01, 1., 15., 300., 1000.])
    radius = 12.3
    r_factor, l_factor, share = factors
    context = max(r_factor * radius, l_factor * 450.)
    expected = ((1-share)*np.exp(-np.log(2.)*(distances/radius)**2)
                + share*np.exp(-np.log(2.)*(distances/context)**2))
    actual = _constraint_weight(distances, radius, 450., is_structure=structure,
                                is_brush=brush, attached_point=attached)
    assert expected.tobytes() == actual.tobytes()


@pytest.mark.parametrize("case,limit",
                         [("procedural", 10.), ("regional_detail", 10.), ("tail", .001)])
def test_real_finished_field_gains_from_detail_or_context_guidance(case: str, limit: float) -> None:
    result = probe(case, 42, 4000., "horizontal", 64, (1, 2, 4, 8), 262144)
    comparison = result["profiles"]["current"]["comparison"]
    baseline = comparison["trials"][0]
    assert comparison["status"] == "sampled"
    assert baseline["difference_to_reference"]["maximum_underestimate_m"] < limit
    assert not baseline["difference_to_reference"]["missed_above_level"]
    assert "geometry_only" in result["profiles"]
