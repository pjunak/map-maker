# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false
"""Float32 GeoTIFF products in an explicitly local metric frame."""

import os
from pathlib import Path
from typing import Any, cast

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS

from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.pipeline.generate import GeneratedTerrain

LOCAL_CRS_WKT = (
    'LOCAL_CS["Map Maker source-local metric plane",UNIT["metre",1],'
    'AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
)
GEOTIFF_MODEL_ID = "local-metric-geotiff@1"


def rasterio_native_versions() -> tuple[str, str]:
    return cast("str", rasterio.__gdal_version__), rasterio.__proj_version__


def geotiff_transform(grid: EndpointGrid) -> Affine:
    """Place endpoint samples at pixel centers, with local northing = -source y."""
    x0, y0, _x1, _y1 = grid.extent_km
    dx, dy = grid.x_spacing_km * 1000.0, grid.y_spacing_km * 1000.0
    return Affine(dx, 0.0, x0 * 1000.0 - dx / 2.0, 0.0, -dy, -y0 * 1000.0 + dy / 2.0)


def geotiff_metadata(grid: EndpointGrid) -> dict[str, object]:
    """Describe the raster coordinate mapping independently of any world CRS."""
    transform = geotiff_transform(grid)
    west, north = transform @ (0, 0)
    east, south = transform @ (grid.width, grid.height)
    return {
        "model": GEOTIFF_MODEL_ID,
        "crs_wkt": LOCAL_CRS_WKT,
        "affine_m": list(transform)[:6],
        "bounds_m": [west, south, east, north],
        "horizontal_units": "m",
        "x_direction": "source-right",
        "y_direction": "source-up",
        "registration": "PixelIsPoint",
    }


def write_terrain_geotiff(
    terrain: GeneratedTerrain,
    destination: Path,
    *,
    elevation_sha256: str,
) -> None:
    """Write one self-contained raster; leave partial output uncompleted on failure."""
    grid = terrain.grid
    if (
        terrain.elevation_m.shape != terrain.land_mask.shape
        or not np.isfinite(terrain.elevation_m[terrain.land_mask]).all()
        or not np.isnan(terrain.elevation_m[~terrain.land_mask]).all()
    ):
        raise ValueError("GeoTIFF needs finite land elevations and NaN outside the land mask.")
    expected_x = np.linspace(grid.extent_km[0], grid.extent_km[2], grid.width)
    expected_y = np.linspace(grid.extent_km[1], grid.extent_km[3], grid.height)
    if not (np.array_equal(terrain.x_km, expected_x) and np.array_equal(terrain.y_km, expected_y)):
        raise ValueError("GeoTIFF requires uniform endpoint-node coordinate vectors.")
    if len(elevation_sha256) != 64 or any(c not in "0123456789abcdef" for c in elevation_sha256):
        raise ValueError("Numeric source hash must be a lowercase SHA-256 digest.")
    # Reserve this product before GDAL opens it; existing files are never replaced.
    with destination.open("xb"):
        pass
    with (
        rasterio.Env(
            GDAL_PAM_ENABLED=False,
            GDAL_TIFF_INTERNAL_MASK=True,
            GTIFF_POINT_GEO_IGNORE=False,
            GDAL_NUM_THREADS="1",
        ),
        rasterio.open(
            destination,
            "w",
            driver="GTiff",
            width=grid.width,
            height=grid.height,
            count=1,
            dtype="float32",
            crs=cast(Any, CRS.from_wkt(LOCAL_CRS_WKT)),
            transform=geotiff_transform(grid),
            nodata=float("nan"),
            tiled=True,
            blockxsize=256,
            blockysize=256,
            compress="deflate",
            predictor=3,
            zlevel=6,
            num_threads=1,
            bigtiff="IF_SAFER",
        ) as dataset,
    ):
        dataset.write(terrain.elevation_m, 1)
        dataset.write_mask(terrain.land_mask.astype(np.uint8) * 255)
        dataset.set_band_description(1, "Terrain elevation")
        dataset.set_band_unit(1, "m")
        dataset.update_tags(
            AREA_OR_POINT="Point",
            coordinate_model=GEOTIFF_MODEL_ID,
            world_position="unspecified",
            manifest="manifest.json",
            numeric_source="elevation.npy",
            numeric_source_sha256=elevation_sha256,
            axis_mapping="easting_m = x_km * 1000; northing_m = -y_km * 1000",
        )
    with destination.open("r+b") as stream:
        os.fsync(stream.fileno())
