# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
"""Compare selective sampling against the original rectangular evaluation path."""

from dataclasses import replace
from typing import Any

import numpy as np
import pytest
import shapely
from numpy.typing import NDArray
from shapely.geometry import Polygon

from benchmarks.terrain import fixture
from map_maker.terrain.domain import Coastline, TerrainRegion, TerrainSettings, TerrainStructure
from map_maker.terrain.pipeline import generate as generation
from map_maker.terrain.pipeline.terrain_context import PreparedWorldContext


def _dense_samples(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    polygon: Any,
    boundary: Any,
    settings: TerrainSettings,
    constraints: Any,
    valleys: Any,
    regions: Any = (),
    world_context: PreparedWorldContext | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    mask = np.asarray(shapely.intersects_xy(polygon, x, y), dtype=np.bool_)
    elevation = generation._evaluate_land_samples(
        x, y, boundary, settings, constraints, valleys, regions, world_context,
    )
    return np.where(mask, elevation, 0.0), mask


@pytest.mark.parametrize(
    "case", ["example", "archipelago", "archipelago-authored", "authored", "square", "regions"]
)
@pytest.mark.parametrize("seed", [42, 20260902])
def test_selective_generation_matches_dense_reference(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    seed: int,
) -> None:
    coast, settings, constraints = fixture(
        "archipelago" if case == "regions" else case.removesuffix("-authored"), 65, seed,
    )
    if case == "archipelago-authored":
        constraints = (
            TerrainStructure("ridge", ((0.25, 0.25), (0.45, 0.25)), 1800.0, 100.0),
            TerrainStructure("valley", ((0.25, 0.7), (0.4, 0.8)), 300.0, 80.0, "relative"),
        )
    if case == "regions":
        constraints = (TerrainRegion(((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.))),)
    selective = generation.generate_terrain(coast, settings, constraints=constraints)
    monkeypatch.setattr(generation, "_evaluate_elevation_samples", _dense_samples)
    dense = generation.generate_terrain(coast, settings, constraints=constraints)
    assert selective.elevation_m.tobytes() == dense.elevation_m.tobytes()
    np.testing.assert_array_equal(selective.land_mask, dense.land_mask)
    assert selective.drainage.summary == dense.drainage.summary
    assert selective.routing_grid_shape == dense.routing_grid_shape
    assert selective.constraints == constraints


def test_water_only_chunk_skips_field_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Water-only chunks must not evaluate noise or geometry distances")

    monkeypatch.setattr(generation, "_evaluate_land_samples", forbidden)
    polygon = Polygon(((0, 0), (1, 0), (1, 1), (0, 1)))
    x, y = np.meshgrid(np.array([2.0, 3.0]), np.array([2.0, 3.0]))
    unused_valleys: Any = None
    elevation, mask = generation._evaluate_elevation_samples(
        x,
        y,
        polygon,
        polygon.boundary,
        TerrainSettings(),
        (),
        unused_valleys,
    )
    np.testing.assert_array_equal(elevation, np.zeros((2, 2)))
    assert not mask.any()


def test_selective_samples_preserve_holes_and_nested_coordinates() -> None:
    coastline = Coastline(
        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)),
        "hole",
        holes=(((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75), (0.25, 0.25)),),
    )
    settings = TerrainSettings(resolution_px=65, seed=17)
    coarse = generation.generate_terrain(coastline, settings)
    fine = generation.generate_terrain(coastline, replace(settings, resolution_px=129))
    np.testing.assert_array_equal(coarse.elevation_m, fine.elevation_m[::2, ::2])
    np.testing.assert_array_equal(coarse.land_mask, fine.land_mask[::2, ::2])
    assert np.isnan(coarse.elevation_m[32, 32])
    assert coarse.elevation_m[16, 32] == 0.0
    assert coarse.drainage.summary == fine.drainage.summary
