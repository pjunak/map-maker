# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""Analytic sphere controls for geographic exposure, independent of climate models."""

import warnings
from math import atan2, cos, exp, pi, sin

import numpy as np
import pytest
from shapely.affinity import affine_transform
from shapely.geometry import GeometryCollection, box
from shapely.geometry.base import BaseGeometry

from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_context import (
    MIXED_COAST,
    SphericalContextGrid,
    WorldContextSettings,
    exposure_range_km,
    exposure_steps,
    shore_spacing_km,
)
from map_maker.terrain.pipeline import world_exposure as stage
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled


def grid(rows: int = 24, radius: float = 1000, meridian: float = 0) -> SphericalContextGrid:
    return SphericalContextGrid(
        WorldFrame((0, 0, 360, 180), radius, meridian), WorldContextSettings(rows)
    )


@pytest.mark.parametrize("rows", [12, 36])
def test_equator_is_the_only_shore_of_a_polar_hemisphere(rows: int) -> None:
    g = grid(rows)
    distance, support = stage.measure_shore_distance(box(0, 0, 360, 90), g)
    true = np.abs(np.deg2rad([g.latitude_deg(r) for r in range(rows)]))[:, None] * 1000
    assert np.all(distance >= true - 1e-9)
    assert np.all(distance <= true + support.max_error_km + 1e-9)
    assert 0 < support.max_error_km <= shore_spacing_km(g) / 2
    assert not distance.flags.writeable
    # False shores along the seam or collapsed polar edge would fail this.
    assert distance[0].min() > 1000


def test_seam_mismatch_is_a_real_shore_and_inland_lake_counts() -> None:
    g = grid()
    distance, support = stage.measure_shore_distance(box(0, 0, 180, 180), g)
    lon, lat = np.meshgrid(
        np.deg2rad([g.longitude_deg(c) for c in range(48)]),
        np.deg2rad([g.latitude_deg(r) for r in range(24)]),
    )
    true = np.arcsin(np.abs(np.cos(lat) * np.sin(lon))) * 1000
    assert np.all(distance >= true - 1e-8)
    assert np.all(distance <= true + support.max_error_km + 1e-8)
    lake = box(0, 0, 360, 180).difference(box(165, 75, 195, 105))
    distance, _ = stage.measure_shore_distance(lake, g)
    assert distance[11, 23] < 300


@pytest.mark.parametrize("land", [box(0, 0, 360, 180), GeometryCollection()])
def test_world_without_shoreline_has_explicit_nodata(land: BaseGeometry) -> None:
    distance, support = stage.measure_shore_distance(land, grid())
    assert np.isnan(distance).all()
    assert support.sample_count == 0 and support.max_error_km == 0


def test_source_scaling_rotation_and_radius_keep_spherical_meaning() -> None:
    land = box(40, 30, 280, 140)
    original, bound = stage.measure_shore_distance(land, grid())
    g = SphericalContextGrid(
        WorldFrame((17.3, -11.1, 125.3, 42.9), 1000, 135), WorldContextSettings(24)
    )
    transformed, changed_bound = stage.measure_shore_distance(
        affine_transform(land, (0.3, 0, 0, 0.3, 17.3, -11.1)), g
    )
    np.testing.assert_allclose(original, transformed, atol=1e-9)
    assert changed_bound.max_error_km == pytest.approx(bound.max_error_km)
    doubled, support = stage.measure_shore_distance(land, grid(radius=2000))
    assert np.max(np.abs(doubled - 2 * original)) <= 2 * bound.max_error_km + support.max_error_km


def test_shore_sample_admission_and_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage, "MAX_SHORE_SAMPLES", 10)
    with pytest.raises(ValueError, match="samples"):
        stage.measure_shore_distance(box(10, 10, 350, 170), grid())
    cancellation = CancellationToken()
    cancellation.cancel()
    with pytest.raises(GenerationCancelled):
        stage.measure_shore_distance(box(1, 1, 2, 2), grid(), cancellation=cancellation)


@pytest.mark.parametrize("fraction,flag", [(0.0, 0), (1.0, 0), (0.25, MIXED_COAST)])
def test_constant_worlds_and_mixed_support_are_normalized(fraction: float, flag: int) -> None:
    g = grid(12)
    result, support = stage.measure_water_exposure(
        g, np.full(g.shape, fraction), np.full(g.shape, flag, dtype=np.uint8)
    )
    np.testing.assert_allclose(result, 1 - fraction, atol=1e-7)
    np.testing.assert_allclose(support, float(flag != 0), atol=1e-7)
    assert not result.flags.writeable and not support.flags.writeable


def test_island_and_continental_interior_differ_at_the_same_latitude() -> None:
    g = grid(36, radius=6000)
    island = np.zeros(g.shape)
    continent = np.zeros(g.shape)
    island[17:19, 35:37] = 1
    continent[8:28, 20:52] = 1
    flags = np.zeros(g.shape, dtype=np.uint8)
    a, _ = stage.measure_water_exposure(g, island, flags)
    b, _ = stage.measure_water_exposure(g, continent, flags)
    assert float(a[:, 18, 36].mean()) > 0.4
    assert float(b[:, 18, 36].max()) == 0


def test_ray_bearings_reverse_and_longitude_seam_wraps() -> None:
    g = grid(24)
    land = np.zeros(g.shape)
    land[7:18, 4:20] = 1
    flags = np.zeros(g.shape, dtype=np.uint8)
    result, _ = stage.measure_water_exposure(g, land, flags)
    mirrored, _ = stage.measure_water_exposure(g, land[:, ::-1], flags)
    np.testing.assert_allclose(result, mirrored[[0, 7, 6, 5, 4, 3, 2, 1], :, ::-1], atol=1e-7)
    shifted, _ = stage.measure_water_exposure(
        grid(24, meridian=75), np.roll(land, 33, axis=1), flags
    )
    np.testing.assert_allclose(np.roll(result, 33, axis=2), shifted, atol=1e-7)


def test_northward_ray_crosses_pole_into_opposite_longitude() -> None:
    g = grid(24)
    land = np.zeros(g.shape)
    land[:, :24] = 1
    result, _ = stage.measure_water_exposure(g, land, np.zeros(g.shape, dtype=np.uint8))
    assert result[0, 0, 12] > 0.8  # Water after crossing the north pole.
    assert result[4, 0, 12] == 0  # South remains within the dry hemisphere.


def test_midpoint_exposure_converges_to_analytic_meridian_crossing() -> None:
    errors: list[float] = []
    for rows, row, column in ((24, 11, 18), (72, 34, 55)):
        g = grid(rows)
        land = np.zeros(g.shape)
        land[:, :rows] = 1
        result, _ = stage.measure_water_exposure(g, land, np.zeros(g.shape, dtype=np.uint8))
        lon, lat = np.deg2rad([g.longitude_deg(column), g.latitude_deg(row)])
        crossing = atan2(-cos(lat) * sin(lon), (-sin(lat) * sin(lon) + cos(lon)) / 2**0.5) * 1000
        exact = (exp(-3 * crossing / exposure_range_km(g)) - exp(-3)) / (1 - exp(-3))
        errors.append(abs(float(result[1, row, column]) - exact))
    assert errors[1] < 0.01
    assert errors[1] < errors[0]


def test_exposure_work_cap_and_mid_run_cancellation() -> None:
    g = grid(360, radius=1000)
    assert exposure_steps(g) == 256
    assert exposure_range_km(g) == pi * 500
    g = grid(12)
    cancellation = CancellationToken()
    with pytest.raises(GenerationCancelled):
        stage.measure_water_exposure(
            g,
            np.zeros(g.shape),
            np.zeros(g.shape, dtype=np.uint8),
            lambda _f, _m: cancellation.cancel(),
            cancellation=cancellation,
        )


@pytest.mark.parametrize("radius", [1e20, 1e100])
def test_huge_valid_planet_rejects_sample_work_before_integer_overflow(radius: float) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(ValueError, match="500,000 samples"):
            stage.measure_shore_distance(box(0, 0, 360, 90), grid(radius=radius))
