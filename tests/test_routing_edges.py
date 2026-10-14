# pyright: reportPrivateUsage=false
"""Crest-aware routing must observe barriers without changing authored terrain."""

import weakref
from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import box

from benchmarks.channel_profiles import measure_channels
from benchmarks.terrain import fixture
from map_maker.terrain.domain import LandformSettings
from map_maker.terrain.domain.seeds import LANDFORM_STAGE_ID, stage_seed
from map_maker.terrain.pipeline import generate as generation
from map_maker.terrain.pipeline import routing_edges
from map_maker.terrain.pipeline.hydrology import (
    D8_NEIGHBOURS,
    automatic_incision_budget,
    land_outlet_mask,
    multiple_flow_accumulation,
    priority_flood_surface,
    steepest_flow_accumulation,
    steepest_flow_receivers,
)
from map_maker.terrain.pipeline.landforms import MetricRegion, regional_incision_budget

type FloatArray = NDArray[np.float64]


def _set_edge(
    peaks: FloatArray, first: tuple[int, int], last: tuple[int, int], level: float,
) -> None:
    direction = D8_NEIGHBOURS.index((last[0]-first[0], last[1]-first[1]))
    peaks[direction, *first] = peaks[7-direction, *last] = level


def test_flood_relaxes_a_late_lower_pass_and_both_flow_models_respect_it() -> None:
    ground = np.zeros((5, 5))
    land = np.ones_like(ground, dtype=np.bool_)
    peaks = np.full((8, 5, 5), 1000.)
    _set_edge(peaks, (0, 2), (1, 2), 0.)
    _set_edge(peaks, (1, 2), (2, 2), 100.)  # discovered first, but not cheapest
    _set_edge(peaks, (2, 0), (2, 1), 5.)
    _set_edge(peaks, (2, 1), (2, 2), 10.)
    routed = priority_flood_surface(ground, land, edge_barriers_m=peaks)
    assert routed[2, 2] == 10.  # marking visited on discovery would keep 100
    receivers, _slope = steepest_flow_receivers(
        routed, land, x_spacing_km=2., y_spacing_km=3., edge_barriers_m=peaks)
    assert receivers[2, 2] == 11
    sources = np.flatnonzero(receivers.ravel() >= 0)
    assert np.all(routed.ravel()[sources] > routed.ravel()[receivers.ravel()[sources]])
    assert np.all(land_outlet_mask(land)[receivers < 0])
    for accumulate in (multiple_flow_accumulation, steepest_flow_accumulation):
        area, _slope = accumulate(routed, land, x_spacing_km=2., y_spacing_km=3.,
                                  edge_barriers_m=peaks)
        assert np.sum(area[receivers < 0]) == pytest.approx(25*6)
    np.testing.assert_array_equal(ground, np.zeros((5, 5)))
    assert peaks[1, 2, 2] == 100.


def test_barrier_blocks_mfd_leakage_to_a_lower_node() -> None:
    ground = np.full((3, 3), 30.)
    ground[1] = [0., 10., 5.]
    peaks = np.full((8, 3, 3), 1000.)
    _set_edge(peaks, (1, 1), (1, 0), 20.)
    _set_edge(peaks, (1, 1), (1, 2), 10.)
    land = np.ones((3, 3), dtype=np.bool_)
    area, _ = multiple_flow_accumulation(ground, land, x_spacing_km=1., y_spacing_km=1.,
                                         edge_barriers_m=peaks)
    assert area[1, 0] == 1. and area[1, 2] == 2.
    receivers, _ = steepest_flow_receivers(ground, land, x_spacing_km=1., y_spacing_km=1.,
                                          edge_barriers_m=peaks)
    assert receivers[1, 1] == 5
    terminal = np.zeros_like(land)
    terminal[1, 1] = True
    for accumulate in (multiple_flow_accumulation, steepest_flow_accumulation):
        retained, _ = accumulate(ground, land, x_spacing_km=1., y_spacing_km=1.,
                                 edge_barriers_m=peaks, terminal_mask=terminal)
        assert retained[1, 2] == 1.
    flooded = priority_flood_surface(ground, land, terminal_mask=terminal, edge_barriers_m=peaks)
    assert flooded[1, 1] == ground[1, 1]


@pytest.mark.parametrize("fault", ["shape", "nan", "asymmetric"])
def test_invalid_edge_observations_are_rejected(fault: str) -> None:
    ground, land = np.zeros((3, 3)), np.ones((3, 3), dtype=np.bool_)
    peaks = np.zeros((8, 3, 3))
    if fault == "shape":
        peaks = peaks[:7]
    elif fault == "nan":
        peaks[4, 1, 1] = np.nan
    else:
        peaks[4, 1, 1] = 10.
    with pytest.raises(ValueError, match="barriers"):
        priority_flood_surface(ground, land, edge_barriers_m=peaks)


def _region() -> MetricRegion:
    polygon = box(0., 0., 2., 2.)
    return MetricRegion(polygon, LandformSettings(character="mountains", relief_m=500.), polygon)


def _linear_carrier(
    x: FloatArray, y: FloatArray, controls: LandformSettings, seed: int,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    return x, y, x-.5


def test_crest_sampling_is_shared_symmetric_bounded_and_batch_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routing_edges, "regional_noise_basis", _linear_carrier)
    axis, ground, land = np.arange(3, dtype=np.float64), np.full((3, 3), 100.), np.ones(
        (3, 3), dtype=np.bool_)
    calls: list[int] = []
    def sample(x: FloatArray, y: FloatArray) -> FloatArray:
        calls.append(x.size)
        return 100.+40.*np.maximum(1.-np.abs(x-.5)/.5, 0.)
    first = routing_edges.sample_mountain_barriers(
        axis, axis, ground, land, (_region(),), 42, sample, batch_edges=2)
    assert first is not None and not first.flags.writeable
    assert first[4, 0, 0] == first[3, 0, 1] == 140.
    assert first[6, 0, 0] == 100.  # no carrier crossing on vertical connections
    assert sum(calls) == 7*7 and max(calls) <= 2*7
    calls.clear()
    duplicate = routing_edges.sample_mountain_barriers(
        axis, axis, ground, land, (_region(), _region()), 42, sample, batch_edges=1)
    np.testing.assert_array_equal(first, duplicate)
    assert sum(calls) == 7*7 and max(calls) == 7
    np.testing.assert_array_equal(ground, np.full((3, 3), 100.))


def test_no_mountain_or_no_interior_rise_does_not_change_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routing_edges, "regional_noise_basis", _linear_carrier)
    axis, ground, land = np.arange(3, dtype=np.float64), np.full((3, 3), 100.), np.ones(
        (3, 3), dtype=np.bool_)
    def unused(x: FloatArray, y: FloatArray) -> FloatArray:
        raise AssertionError("No mountain regions should require no interior probes")
    assert routing_edges.sample_mountain_barriers(axis, axis, ground, land, (), 42, unused) is None
    assert routing_edges.sample_mountain_barriers(
        axis, axis, ground, land, (_region(),), 42, lambda x, y: np.full_like(x, 100.)) is None
    land[:] = False
    assert routing_edges.sample_mountain_barriers(
        axis, axis, ground, land, (_region(),), 42, unused) is None


@pytest.mark.parametrize("fault", ["nan", "shape"])
def test_bad_crest_samples_cannot_be_silently_treated_as_clear(
    fault: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routing_edges, "regional_noise_basis", _linear_carrier)
    def sample(x: FloatArray, y: FloatArray) -> FloatArray:
        return np.full_like(x, np.nan) if fault == "nan" else x[:, 0]
    with pytest.raises(ValueError, match="finite heights"):
        routing_edges.sample_mountain_barriers(
            np.arange(3, dtype=np.float64), np.arange(3, dtype=np.float64),
            np.full((3, 3), 100.), np.ones((3, 3), dtype=np.bool_), (_region(),), 42, sample)


@pytest.mark.parametrize("seed", [104729, 20260902])
def test_regional_crest_routes_improve_with_unchanged_source_and_budget_policy(
    seed: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coast, settings, constraints = fixture("regional", 257, seed)
    revised = generation.prepare_terrain_field(coast, settings, constraints, None)
    def no_observations(*args: object, **kwargs: object) -> None:
        return None
    with monkeypatch.context() as patch:
        patch.setattr(generation, "sample_mountain_barriers", no_observations)
        baseline = generation.prepare_terrain_field(coast, settings, constraints, None)
    old, new = baseline.automatic_valleys, revised.automatic_valleys
    np.testing.assert_array_equal(old.drainage.source_elevation_m, new.drainage.source_elevation_m)
    np.testing.assert_array_equal(old.land_mask, new.land_mask)
    assert np.any(old.drainage.receivers != new.drainage.receivers)
    xx, yy = np.meshgrid(new.x_km, new.y_km)
    budget = regional_incision_budget(xx, yy, automatic_incision_budget(
        settings.maximum_elevation_m, settings.variability), revised.regions)
    assert np.all(new.drainage.incision_m <= new.drainage.incision_limit_m)
    assert np.all(new.drainage.incision_limit_m <= budget)
    def profiles(field: generation.PreparedTerrainField) -> dict[str, object]:
        valley = field.automatic_valleys
        return measure_channels(valley.x_km, valley.y_km, valley.drainage.receivers,
                                valley.drainage.channel_mask, field.sample_ground, stations=65)
    before, after = profiles(baseline), profiles(revised)
    # Compare finite measured profiles; this is not a continuous river guarantee.
    assert before["nonfinite_profile_count"] == after["nonfinite_profile_count"] == 0
    before_desc, after_desc = before["descending"], after["descending"]
    assert isinstance(before_desc, dict) and isinstance(after_desc, dict)
    assert before_desc["maximum_excursion_m"] > 200.
    assert after_desc["maximum_excursion_m"] < 90.


def test_region_count_does_not_accumulate_live_carrier_grids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carriers: list[weakref.ReferenceType[FloatArray]] = []
    def carrier(
        x: FloatArray, y: FloatArray, controls: LandformSettings, seed: int,
    ) -> tuple[FloatArray, FloatArray, FloatArray]:
        assert sum(reference() is not None for reference in carriers) <= 1
        broad = x-.5
        if x.shape == (65, 65):
            carriers.append(weakref.ref(broad))
        return x, y, broad
    monkeypatch.setattr(routing_edges, "regional_noise_basis", carrier)
    axis = np.linspace(0., 2., 65)
    ground, land = np.full((65, 65), 100.), np.ones((65, 65), dtype=np.bool_)
    region = _region()
    regions = tuple(replace(region, settings=replace(
        region.settings, feature_size_km=150.+i)) for i in range(24))
    barriers = routing_edges.sample_mountain_barriers(
        axis, axis, ground, land, regions, 42, lambda x, y: np.full_like(x, 140.))
    assert barriers is not None and len(carriers) == 24
    assert all(reference() is None for reference in carriers)


@pytest.mark.parametrize("kind", ["crossing", "paired", "tangent"])
def test_refined_sampling_observes_off_station_and_same_sign_crests(
    kind: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # All extrema are away from the regular eighth-edge stations. In the paired
    # and tangent cases endpoint signs agree, so the previous policy saw none.
    def signal(x: FloatArray) -> FloatArray:
        if kind == "paired":
            return (x-.31)*(x-.69)
        if kind == "tangent":
            return (x-.31)**2
        return x-.31

    def carrier(x: FloatArray, y: FloatArray, controls: LandformSettings,
                seed: int) -> tuple[FloatArray, FloatArray, FloatArray]:
        return x, y, signal(x)

    monkeypatch.setattr(routing_edges, "regional_noise_basis", carrier)
    region = _region()
    region = replace(region, settings=replace(
        region.settings, feature_size_km=1.))
    axis = np.arange(3, dtype=np.float64)
    land = np.ones((3, 3), dtype=np.bool_)
    ground = np.broadcast_to(100.+40.*(1.-np.minimum(np.abs(signal(axis)), 1.)), (3, 3)).copy()
    calls: list[int] = []
    def sample(x: FloatArray, y: FloatArray) -> FloatArray:
        calls.append(x.size)
        return 100.+40.*(1.-np.minimum(np.abs(signal(x)), 1.))

    barriers = routing_edges.sample_mountain_barriers(
        axis, axis, ground, land, (region,), 42, sample, batch_edges=1)
    assert barriers is not None
    assert max(calls) <= 7
    assert barriers[4, 0, 0] == pytest.approx(140., abs=.001)
    assert barriers[4, 0, 0] == barriers[3, 0, 1]
    repeated = routing_edges.sample_mountain_barriers(
        axis, axis, ground, land, (region, region), 42, sample, batch_edges=4096)
    np.testing.assert_array_equal(barriers, repeated)
    regular = sample(np.arange(1., 8.)[None, :]/8., np.zeros((1, 7)))
    assert barriers[4, 0, 0] > np.max(regular)+.1


def test_observed_paired_roots_are_both_sampled(monkeypatch: pytest.MonkeyPatch) -> None:
    def carrier(x: FloatArray, y: FloatArray, controls: LandformSettings,
                seed: int) -> tuple[FloatArray, FloatArray, FloatArray]:
        return x, y, (x-.31)*(x-.69)
    monkeypatch.setattr(routing_edges, "regional_noise_basis", carrier)
    controls = LandformSettings(character="mountains", feature_size_km=1.)
    zero, one = np.zeros(1), np.ones(1)
    observed, edges, fractions = routing_edges._crest_locations(
        zero, zero, one, zero, np.full(1, .31*.69), np.full(1, .31*.69), controls, 42)
    assert observed.tolist() == [True] and edges.tolist() == [0, 0]
    np.testing.assert_allclose(fractions, [.31, .69], rtol=0., atol=1/65536)



def test_rotated_carriers_and_overlaps_are_batch_and_order_independent() -> None:
    region = _region()
    regions = tuple(replace(region, settings=replace(
        region.settings, feature_size_km=size, orientation_deg=angle))
        for size, angle in ((.8, 37.), (1.3, 84.)))
    x = np.array([0., .04, .27, .41, .68, 1.2, 1.7, 2.])
    y = np.linspace(0., 2., 7)
    xx, yy = np.meshgrid(x, y)
    calls: list[int] = []
    land = np.ones_like(xx, dtype=np.bool_)
    land[3, 3] = False
    # Use the same named seed in the actual procedural source and observer.
    named_seed = stage_seed(81, LANDFORM_STAGE_ID)
    def macro(qx: FloatArray, qy: FloatArray) -> FloatArray:
        calls.append(qx.size)
        result = np.full_like(qx, 100.)
        for item in regions:
            _, _, broad = routing_edges.regional_noise_basis(
                qx, qy, item.settings, named_seed)
            result += 40.*(1.-np.abs(broad))**3
        return result
    ground = macro(xx, yy)
    ground[~land] = np.nan
    original = ground.copy()
    calls.clear()
    first = routing_edges.sample_mountain_barriers(
        x, y, ground, land, regions, 81, macro, batch_edges=2)
    assert first is not None and max(calls) <= 14
    second = routing_edges.sample_mountain_barriers(
        x, y, ground, land, regions[::-1], 81, macro)
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(ground, original)
    for index in range(8):
        r, c = np.nonzero(np.isfinite(first[index]))
        dy, dx = D8_NEIGHBOURS[index]
        assert np.all(land[r, c] & land[r+dy, c+dx])
        np.testing.assert_array_equal(first[index, r, c], first[7-index, r+dy, c+dx])
        assert np.all(first[index, r, c] >= np.maximum(ground[r, c], ground[r+dy, c+dx]))


def test_same_sign_screen_without_observed_extrema_avoids_macro_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def carrier(x: FloatArray, y: FloatArray, controls: LandformSettings,
                seed: int) -> tuple[FloatArray, FloatArray, FloatArray]:
        return x, y, .001+.001*x
    def unused(x: FloatArray, y: FloatArray) -> FloatArray:
        raise AssertionError("The monotone positive carrier has no observed crest")
    monkeypatch.setattr(routing_edges, "regional_noise_basis", carrier)
    axis = np.arange(3, dtype=np.float64)
    assert routing_edges.sample_mountain_barriers(
        axis, axis, np.full((3, 3), 100.), np.ones((3, 3), dtype=np.bool_),
        (_region(),), 42, unused) is None


def test_crest_probes_follow_mountain_support_into_neighboring_recipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routing_edges, "regional_noise_basis", _linear_carrier)
    axis = np.arange(4, dtype=np.float64)
    ground, land = np.full((4, 4), 100.), np.ones((4, 4), dtype=np.bool_)
    # The observed crest at x=.5 is outside the mountain polygon and beyond
    # the old one-cell screening buffer, but inside its blending support.
    domain = box(0., 0., 4., 4.)
    mountain = MetricRegion(box(2.6, 0., 4., 4.), replace(
        _region().settings, transition_km=3.), domain)
    def sample(x: FloatArray, y: FloatArray) -> FloatArray:
        return 100.+40.*np.maximum(1.-np.abs(x-.5)/.5, 0.)
    narrow = replace(mountain, settings=replace(mountain.settings, transition_km=.1))
    barrier = routing_edges.sample_mountain_barriers(
        axis, axis, ground, land, (narrow, mountain), 42, sample,
    )
    assert barrier is not None
    assert barrier[4, 1, 0] == barrier[3, 1, 1] == 140.
