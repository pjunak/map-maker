# pyright: reportPrivateUsage=false
"""Shared recipe seams, background cutouts and compact sampling invariants."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.affinity import rotate
from shapely.geometry import Polygon, box

from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    LandformSettings,
    TerrainRegion,
    TerrainSettings,
)
from map_maker.terrain.pipeline.generate import _water_sampling_guides, generate_terrain
from map_maker.terrain.pipeline.landform_weights import regional_weights
from map_maker.terrain.pipeline.landforms import (
    prepare_regions,
    regional_elevation_fields,
    regional_incision_budget,
)
from map_maker.terrain.pipeline.water_sampling import SamplingDensity

SETTINGS = TerrainSettings(seed=42, object_scale_km=1000., coastal_rise_km=5.)
LAND = box(0., 0., 1000., 1000.)
PLAIN = LandformSettings("plain", 250., 0., 150., 70.)
PLATEAU = LandformSettings("plateau", 2200., 0., 200., 100.)
type FloatArray = NDArray[np.float64]


def region(geometry: Polygon, controls: LandformSettings) -> TerrainRegion:
    return TerrainRegion(
        tuple((x / 1000., y / 1000.) for x, y in geometry.exterior.coords), controls,
        tuple(tuple((x / 1000., y / 1000.) for x, y in h.coords) for h in geometry.interiors),
    )


def evaluate(
    inputs: tuple[TerrainRegion, ...], x: FloatArray, y: FloatArray, background: float = 4000.,
) -> FloatArray:
    prepared = prepare_regions(inputs, 1000., 1000., LAND, 6000.)
    base = np.full_like(x, background)
    return regional_elevation_fields(
        x, y, np.full_like(x, 500.), base, base, SETTINGS, prepared,
    )[0]


@pytest.mark.parametrize("angle", [0., 37.])
def test_adjacent_recipes_blend_without_background_ridge_or_trough(angle: float) -> None:
    inputs = tuple(region(rotate(p, angle, origin=(500., 500.)), c) for p, c in (
        (box(200., 200., 500., 800.), PLAIN),
        (box(500., 200., 800., 800.), PLATEAU),
    ))
    axis = np.linspace(-150., 150., 601)
    x, y = 500. + axis*np.cos(np.deg2rad(angle)), 500. + axis*np.sin(np.deg2rad(angle))
    high, low = (evaluate(inputs, x, y, background=b) for b in (4000., 0.))
    np.testing.assert_allclose(high, low, atol=1e-10)
    np.testing.assert_allclose(high[[0, 300, -1]], [250., 1225., 2200.], atol=1e-9)
    assert np.all(np.diff(high) >= -1e-9)
    assert np.max(np.abs(np.diff(high))) < 25.
    x0, y0 = np.array([500.-1e-7, 500., 500.+1e-7]), np.full(3, 500.)
    if angle == 0.:
        assert np.ptp(evaluate(inputs, x0, y0)) < 1e-4


def test_three_way_junction_has_full_convex_coverage() -> None:
    inputs = (
        region(box(200., 200., 500., 800.), PLAIN),
        region(box(500., 200., 800., 500.), PLATEAU),
        region(box(500., 500., 800., 800.), replace(PLAIN, elevation_m=1000.)),
    )
    x, y = np.meshgrid(500. + np.array([-1e-6, 0., 1e-6]),
                       500. + np.array([-1e-6, 0., 1e-6]))
    values = evaluate(inputs, x, y)
    np.testing.assert_allclose(values, 1150., atol=1e-4)
    total = np.zeros_like(x)
    for _, selected, weight in regional_weights(
        x, y, prepare_regions(inputs, 1000., 1000., LAND, 6000.),
    ):
        assert np.all((weight >= 0.) & (weight <= 1.))
        total[selected] += weight
    np.testing.assert_allclose(total, 1., atol=1e-15)


def test_nested_override_core_and_blank_hole_remain_authoritative() -> None:
    inner = box(400., 400., 600., 600.)
    outer = region(Polygon(box(100., 100., 900., 900.).exterior.coords,
                           [inner.exterior.coords]),
                   replace(PLATEAU, transition_km=200.))
    override = region(inner, replace(PLAIN, transition_km=20.))
    x = np.array([400.-1e-7, 400., 400.+1e-7, 450., 500., 600.])
    y = np.full_like(x, 500.)
    filled = evaluate((outer, override), x, y)
    np.testing.assert_allclose(filled[:3], 1225., atol=1e-4)
    np.testing.assert_allclose(filled[3:5], 250.)
    empty = evaluate((outer,), x, y)
    np.testing.assert_allclose(empty, 4000., atol=1e-9)
    assert len(outer.holes) == 1


@pytest.mark.parametrize("point_contact", [False, True])
def test_disconnected_or_point_touching_regions_do_not_leak(point_contact: bool) -> None:
    first = region(box(100., 100., 500., 500.), PLAIN)
    other = box(500., 500., 900., 900.) if point_contact else box(501., 100., 900., 500.)
    second = region(other, replace(PLATEAU, transition_km=200.))
    x = np.array([430., 450., 480., 500., 500.5])
    y = np.full_like(x, 300.)
    np.testing.assert_array_equal(evaluate((first, second), x, y), evaluate((first,), x, y))


def test_identical_partitions_and_duplicates_are_dissolved_before_blending() -> None:
    controls = replace(PLATEAU, relief_m=200.)
    whole = region(box(100., 100., 900., 900.), controls)
    split = (region(box(100., 100., 500., 900.), controls),
             region(box(500., 100., 900., 900.), controls))
    x, y = np.meshgrid(np.linspace(0., 1000., 71), np.linspace(0., 1000., 63))
    np.testing.assert_array_equal(evaluate((whole,), x, y), evaluate((*split, split[0]), x, y))


def test_overlaps_chunks_and_input_order_preserve_sampling() -> None:
    inputs = (
        region(box(100., 100., 600., 900.), replace(PLAIN, relief_m=100.)),
        region(box(400., 100., 900., 900.), replace(PLATEAU, relief_m=200.)),
    )
    x = np.linspace(0., 1000., 409)
    y = np.full_like(x, 500.)
    full = evaluate(inputs, x, y)
    np.testing.assert_array_equal(full, evaluate(tuple(reversed(inputs)), x, y))
    chunks = np.concatenate([evaluate(inputs, a, b) for a, b in zip(
        np.array_split(x, 7), np.array_split(y, 7), strict=True,
    )])
    np.testing.assert_array_equal(full, chunks)
    near = np.array([400.-1e-7, 400., 400.+1e-7])
    assert np.ptp(evaluate(inputs, near, np.full_like(near, 500.))) < 1e-4


def test_incision_budget_uses_the_same_shared_seam_weights() -> None:
    inputs = (
        region(box(100., 100., 500., 900.), replace(PLAIN, relief_m=100.)),
        region(box(500., 100., 900., 900.), replace(PLATEAU, relief_m=200.)),
    )
    x = np.array([300., 500., 700.])
    budget = regional_incision_budget(
        x, np.full_like(x, 500.), 600., prepare_regions(inputs, 1000., 1000., LAND, 6000.),
    )
    np.testing.assert_allclose(budget, [15., 32.5, 50.])


def test_adjacent_regions_keep_hard_heights_coast_and_shared_resolution_samples() -> None:
    inputs = (
        region(box(100., 100., 500., 900.), replace(PLAIN, relief_m=100.)),
        region(box(500., 100., 900., 900.), replace(PLATEAU, relief_m=200.)),
        ElevationPoint((.5, .5), 1800., 35.),
    )
    coast = Coastline(((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.)), "shared-seam")
    first = generate_terrain(coast, replace(SETTINGS, resolution_px=65), constraints=inputs)
    finer = generate_terrain(coast, replace(SETTINGS, resolution_px=129), constraints=inputs)
    np.testing.assert_array_equal(first.elevation_m, finer.elevation_m[::2, ::2])
    np.testing.assert_array_equal(first.land_mask, finer.land_mask[::2, ::2])
    np.testing.assert_array_equal(first.routing.receivers, finer.routing.receivers)
    assert first.elevation_m[32, 32] == 1800.
    np.testing.assert_array_equal(first.elevation_m[[0, -1]], 0.)
    np.testing.assert_array_equal(first.elevation_m[:, [0, -1]], 0.)


def test_water_density_probes_include_cross_border_relief_support() -> None:
    inputs = (
        region(box(100., 100., 500., 900.), PLAIN),
        region(box(500., 100., 900., 900.), replace(PLATEAU, relief_m=200.)),
    )
    regions = prepare_regions(inputs, 1000., 1000., LAND, 6000.)
    guides = _water_sampling_guides((), regions, replace(SETTINGS, variability=0.))
    densities = [g for g in guides if isinstance(g, SamplingDensity)]
    assert len(densities) == 1
    geometry = densities[0].geometry
    assert geometry is not None
    from shapely.geometry import Point
    assert geometry.covers(Point(460., 500.))
    assert not geometry.covers(Point(50., 500.))
