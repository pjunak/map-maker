# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false
"""Round-trip numeric and raw TIFF registration checks for local DEM exchange."""

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import rasterio
from PIL import Image, TiffImagePlugin

from benchmarks.terrain import fixture
from map_maker.terrain.adapters.geotiff import geotiff_metadata, write_terrain_geotiff
from map_maker.terrain.pipeline.generate import GeneratedTerrain, generate_terrain


@pytest.fixture(scope="module")
def terrain() -> GeneratedTerrain:
    coast, settings, constraints = fixture("square", 65, 42)
    base = generate_terrain(coast, settings, constraints=constraints)
    # Unequal spacing and a translated origin expose transposes, flips and half-cell errors.
    return replace(
        base,
        elevation_m=np.array([[0.0, 123.25, np.nan], [987.5, 3.0, 42.0]], dtype=np.float32),
        land_mask=np.array([[True, True, False], [True, True, True]]),
        x_km=np.array([10.0, 12.0, 14.0]),
        y_km=np.array([20.0, 23.0]),
    )


def test_geotiff_round_trip_preserves_surface_coordinates_and_embedded_mask(
    terrain: GeneratedTerrain,
    tmp_path: Path,
) -> None:
    path = tmp_path / "elevation.tif"
    write_terrain_geotiff(terrain, path, elevation_sha256="a" * 64)
    with cast(Any, rasterio.open(path)) as raster:
        assert raster.count == 1
        assert raster.dtypes == ("float32",)
        assert raster.units == ("m",)
        assert np.isnan(raster.nodata)
        assert raster.read(1).tobytes() == terrain.elevation_m.tobytes()
        np.testing.assert_array_equal(
            raster.read_masks(1), terrain.land_mask.astype(np.uint8) * 255
        )
        for row, y in enumerate(terrain.y_km):
            for column, x in enumerate(terrain.x_km):
                assert raster.xy(row, column) == pytest.approx((x * 1000, -y * 1000))
        assert tuple(raster.bounds) == (9000.0, -24500.0, 15000.0, -18500.0)
        assert raster.crs.to_epsg() is None
        assert not raster.crs.is_geographic
        assert not raster.crs.is_projected
        assert "metre" in raster.crs.to_wkt()
        tags = raster.tags()
        assert tags["AREA_OR_POINT"] == "Point"
        assert tags["manifest"] == "manifest.json"
        assert tags["numeric_source_sha256"] == "a" * 64
        assert tags["world_position"] == "unspecified"
        metadata = geotiff_metadata(terrain.grid)
        assert metadata["affine_m"] == list(raster.transform)[:6]
        assert metadata["bounds_m"] == list(raster.bounds)
    assert list(tmp_path.iterdir()) == [path]  # No external mask or PAM sidecars.


def test_raw_geotiff_keys_place_first_point_on_original_node(
    terrain: GeneratedTerrain,
    tmp_path: Path,
) -> None:
    # Writer options must not inherit a user's incompatible point convention.
    path = tmp_path / "elevation.tif"
    with rasterio.Env(GTIFF_POINT_GEO_IGNORE=True):
        write_terrain_geotiff(terrain, path, elevation_sha256="b" * 64)
    with Image.open(path) as raw:
        tiff = cast("TiffImagePlugin.TiffImageFile", raw)
        assert tiff.tag_v2[33550] == (2000.0, 3000.0, 0.0)
        assert tiff.tag_v2[33922] == (0.0, 0.0, 0.0, 10000.0, -20000.0, 0.0)
        keys = cast("tuple[int, ...]", tiff.tag_v2[34735])
        entries = [keys[i : i + 4] for i in range(4, len(keys), 4)]
        assert (1025, 0, 1, 2) in entries  # GTRasterTypeGeoKey = RasterPixelIsPoint.


def test_existing_geotiff_is_never_overwritten(terrain: GeneratedTerrain, tmp_path: Path) -> None:
    path = tmp_path / "elevation.tif"
    path.write_bytes(b"authored file")
    with pytest.raises(FileExistsError):
        write_terrain_geotiff(terrain, path, elevation_sha256="a" * 64)
    assert path.read_bytes() == b"authored file"


@pytest.mark.parametrize("fault", ["land_nan", "water_value", "infinity", "mask_shape", "axis"])
def test_invalid_surface_is_rejected_before_output_creation(
    terrain: GeneratedTerrain,
    tmp_path: Path,
    fault: str,
) -> None:
    elevation = terrain.elevation_m.copy()
    invalid = replace(terrain, elevation_m=elevation)
    if fault == "land_nan":
        elevation[0, 0] = np.nan
    elif fault == "water_value":
        elevation[0, 2] = 0.0
    elif fault == "infinity":
        elevation[1, 0] = np.inf
    elif fault == "mask_shape":
        invalid = replace(invalid, land_mask=np.ones((3, 3), dtype=np.bool_))
    else:
        invalid = replace(invalid, x_km=np.array([10.0, 11.0, 14.0]))
    path = tmp_path / "invalid.tif"
    with pytest.raises(ValueError):
        write_terrain_geotiff(invalid, path, elevation_sha256="a" * 64)
    assert not path.exists()
