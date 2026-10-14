"""Absolute height points must interpolate their targets even under broad overlap."""

from dataclasses import replace

import numpy as np
import pytest

from benchmarks.terrain import fixture
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    TerrainBrushStroke,
    TerrainConstraint,
    TerrainSettings,
    TerrainStructure,
)
from map_maker.terrain.pipeline.generate import (
    PreparedTerrainField,
    generate_terrain,
    prepare_terrain_field,
)


def _coast() -> Coastline:
    return Coastline(((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.)), "square")


def _settings() -> TerrainSettings:
    return TerrainSettings(seed=42, object_scale_km=1000., resolution_px=65,
                           maximum_elevation_m=4500., largest_feature_km=250.)


def _points() -> tuple[ElevationPoint, ...]:
    return (ElevationPoint((.4375, .5), 0., 150.),
            ElevationPoint((.5, .5), 1700.123456, 210.),
            ElevationPoint((.5625, .5), 4500., 280.))


def _constraints() -> tuple[TerrainConstraint, ...]:
    return (TerrainBrushStroke(((.3, .4), (.7, .6)), 400., 200., .6, "relative"),
            TerrainStructure("valley", ((.2, .5), (.8, .5)), 200., 80., "relative"),
            *_points())


@pytest.fixture(scope="module")
def field() -> PreparedTerrainField:
    return prepare_terrain_field(_coast(), _settings(), _constraints(), None)


def test_overlapping_centres_retain_authored_float32_heights_in_field_and_dem(
    field: PreparedTerrainField,
) -> None:
    points = _points()
    x = np.array([p.position[0] * field.width_km for p in points])
    y = np.array([p.position[1] * field.height_km for p in points])
    targets = np.array([p.elevation_m for p in points], dtype=np.float32)
    np.testing.assert_array_equal(field.sample_ground(x, y), targets)
    terrain = generate_terrain(_coast(), _settings(), constraints=_constraints())
    np.testing.assert_array_equal(terrain.elevation_m[32, [28, 32, 36]], targets)
    assert terrain.constraints == _constraints()
    np.testing.assert_array_equal(terrain.elevation_m[[0, -1]], 0.)
    np.testing.assert_array_equal(terrain.elevation_m[:, [0, -1]], 0.)


def test_values_approach_each_authored_height_without_an_isolated_centre_patch(
    field: PreparedTerrainField,
) -> None:
    angles = np.arange(8)*np.pi/4
    radii = np.array([1e-2, 1e-4, 1e-6])[:, None]
    for point in _points():
        x = point.position[0]*field.width_km + radii*np.cos(angles)
        y = point.position[1]*field.height_km + radii*np.sin(angles)
        error = np.abs(field.sample_ground(x, y).astype(np.float64)-np.float32(point.elevation_m))
        assert float(error[-1].max()) <= .001
        assert float(error[-1].max()) <= float(error[0].max())
        assert float(error[1].max()) <= float(error[0].max())


def test_point_order_and_query_density_shape_or_batch_do_not_change_values(
    field: PreparedTerrainField,
) -> None:
    authored = _constraints()
    reordered = prepare_terrain_field(_coast(), _settings(),
                                      authored[:2] + tuple(reversed(authored[2:])), None)
    axis = np.linspace(350., 650., 257)
    x, y = np.meshgrid(axis, axis)
    dense = field.sample_ground(x, y)
    np.testing.assert_array_equal(reordered.sample_ground(x, y), dense)
    for stride in (2, 4):
        coarse = field.sample_ground(x[::stride, ::stride], y[::stride, ::stride])
        np.testing.assert_array_equal(coarse, dense[::stride, ::stride])
    indices = np.random.default_rng(7).permutation(x.size)
    pieces = [field.sample_ground(x.ravel()[part], y.ravel()[part])
              for part in np.array_split(indices, 17)]
    np.testing.assert_array_equal(np.concatenate(pieces), dense.ravel()[indices])


@pytest.mark.parametrize("seed", [42, 7])
@pytest.mark.parametrize("detail", [2, 6])
def test_public_lake_fixture_retains_every_absolute_height(seed: int, detail: int) -> None:
    coast, settings, constraints = fixture("water", 65, seed)
    prepared = prepare_terrain_field(
        coast, replace(settings, detail_levels=detail), constraints, None)
    points = [c for c in constraints if isinstance(c, ElevationPoint)]
    x = np.array([p.position[0]*prepared.width_km for p in points])
    y = np.array([p.position[1]*prepared.height_km for p in points])
    targets = np.array([p.elevation_m for p in points], dtype=np.float32)
    np.testing.assert_array_equal(prepared.sample_ground(x, y), targets)


def test_coincident_conflicting_absolute_heights_fail_before_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_routing(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Conflicting exact points must be rejected before global routing")
    monkeypatch.setattr(
        "map_maker.terrain.pipeline.generate._prepare_automatic_valley_field", no_routing)
    points = (ElevationPoint((.5, .5), 500., 20.), ElevationPoint((.5, .5), 501., 90.))
    with pytest.raises(ValueError, match="Conflicting height points"):
        prepare_terrain_field(_coast(), _settings(), points, None)


def test_equal_coincident_heights_with_different_radii_remain_valid() -> None:
    points = (ElevationPoint((.5, .5), 500., 20.), ElevationPoint((.5, .5), 500., 90.),
              ElevationPoint((.55, .5), 2000., 180.))
    prepared = prepare_terrain_field(_coast(), _settings(), points, None)
    values = prepared.sample_ground(np.array([500., 550.]), np.array([500., 500.]))
    np.testing.assert_array_equal(values, np.array([500., 2000.], dtype=np.float32))


def test_very_close_distinct_points_remain_finite_and_retain_their_heights() -> None:
    points = (ElevationPoint((.5, .5), 0., 100.),
              ElevationPoint((.5 + 2.**-40, .5), 4500., 100.))
    prepared = prepare_terrain_field(_coast(), _settings(), points, None)
    x = np.array([p.position[0]*prepared.width_km for p in points])
    np.testing.assert_array_equal(prepared.sample_ground(x, np.full(x.shape, 500.)), [0., 4500.])
    near = np.linspace(float(x[0])-1e-6, float(x[-1])+1e-6, 17)
    values = prepared.sample_ground(near, np.full(near.shape, 500.))
    assert np.isfinite(values).all()
    assert values.min() >= 0 and values.max() <= 4500.


@pytest.mark.parametrize("position", [(0., .5), (.5, 0.), (1., .5), (.5, 1.)])
def test_positive_absolute_height_on_sea_level_boundary_is_rejected(
    position: tuple[float, float],
) -> None:
    with pytest.raises(ValueError, match="sea-level boundary"):
        prepare_terrain_field(_coast(), _settings(), (ElevationPoint(position, 10., 30.),), None)


def test_zero_absolute_height_on_boundary_remains_valid() -> None:
    prepared = prepare_terrain_field(_coast(), _settings(),
                                     (ElevationPoint((0., .5), 0., 30.),), None)
    np.testing.assert_array_equal(prepared.sample_ground(np.array([0.]), np.array([500.])), [0.])
