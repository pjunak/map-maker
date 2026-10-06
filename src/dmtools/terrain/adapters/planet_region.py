# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Tile cache and regional window products for planet detail (experimental M6)."""

import json
import os
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import numpy as np
import rasterio
import shapely
from affine import Affine
from numpy.typing import NDArray
from PIL import Image, ImageDraw
from rasterio.crs import CRS
from shapely.geometry import Polygon
from shapely.ops import unary_union

from dmtools.terrain.adapters.build import canonical_json, file_sha256
from dmtools.terrain.adapters.planet_render import LAND_STOPS, RIVER_COLOUR, SEA_STOPS
from dmtools.terrain.domain.planet import REGIONAL_ALGORITHM, RegionalSettings
from dmtools.terrain.pipeline.planet_climate import (
    BIOME_COLOURS,
    classify,
    potential_evapotranspiration,
)
from dmtools.terrain.pipeline.planet_forcing import source_xy
from dmtools.terrain.pipeline.planet_mesh import mesh_from_triangles
from dmtools.terrain.pipeline.planet_regional import RegionalParent, RegionalResult, inverse_aeqd
from dmtools.terrain.pipeline.planet_tiles import TileGrid, TileSurface

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

REGION_SCHEMA = "dmtools.planet-region"
REGION_VERSION = 1


@dataclass(frozen=True)
class TileRivers:
    receiver: NDArray[np.int64]
    area_m2: F64


class TileStore:
    """Tiles for one parent and one set of regional settings, written atomically."""

    def __init__(self, root: Path, parent_sha256: str, settings: RegionalSettings) -> None:
        key = sha256(
            canonical_json(
                {
                    "parent": parent_sha256,
                    "algorithm": REGIONAL_ALGORITHM,
                    "settings": asdict(settings),
                }
            )
        ).hexdigest()[:24]
        self.directory = root / key
        self.key = key

    def path(self, tile: int) -> Path:
        return self.directory / f"tile-{tile:05d}.npz"

    def has(self, tile: int) -> bool:
        return self.path(tile).is_file()

    def save(self, tile: int, result: RegionalResult) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        pending = self.directory / f".tile-{tile:05d}-{os.getpid()}.npz"
        with pending.open("wb") as stream:
            np.savez_compressed(
                stream,
                allow_pickle=False,
                xyz=result.region.mesh.xyz.astype("<f8"),
                triangles=result.region.mesh.triangles.astype("<i4"),
                elevation_m=np.where(result.land, result.elevation_m, 0.0).astype("<f8"),
                receiver=result.run.flow.receiver.astype("<i4"),
                area_m2=result.run.flow.area_m2.astype("<f8"),
            )
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(self.path(tile))

    def load(self, tile: int, radius_m: float) -> tuple[TileSurface, TileRivers]:
        with np.load(self.path(tile), allow_pickle=False) as data:
            mesh = mesh_from_triangles(
                data["xyz"].astype(np.float64), data["triangles"].astype(np.int64), radius_m
            )
            surface = TileSurface(mesh, data["elevation_m"].astype(np.float64))
            rivers = TileRivers(
                data["receiver"].astype(np.int64), data["area_m2"].astype(np.float64)
            )
        return surface, rivers


def forward_aeqd(xyz: F64, lon0: float, lat0: float, radius_m: float) -> F64:
    """Unit vectors to local plane metres (x east, y north) about (lon0, lat0)."""
    centre = inverse_aeqd(np.zeros(1), np.zeros(1), lon0, lat0, 1.0)[0]
    east = np.cross([0.0, 0.0, 1.0], centre)
    east = (
        east / np.linalg.norm(east) if np.linalg.norm(east) > 1e-12 else np.array([0.0, 1.0, 0.0])
    )
    north = np.cross(centre, east)
    distance = radius_m * np.arccos(np.clip(xyz @ centre, -1, 1))
    tangent = xyz - np.outer(xyz @ centre, centre)
    norm = np.linalg.norm(tangent, axis=1)
    norm = np.where(norm > 1e-15, norm, 1.0)
    return np.stack(
        (distance * (tangent @ east) / norm, distance * (tangent @ north) / norm), axis=1
    )


@dataclass(frozen=True)
class RegionWindow:
    centre: tuple[float, float]
    radius_m: float
    pixels: int
    elevation_m: F64  # (pixels, pixels); NaN outside the window circle
    land: B
    vegetation_rgb: F64 | None
    rivers: list[tuple[float, float, float, float, float]]  # x0, y0, x1, y1, strength
    tiles: tuple[int, ...]

    @property
    def pixel_m(self) -> float:
        return 2 * self.radius_m / self.pixels


def window_points(
    lon: float, lat: float, radius_m: float, pixels: int, planet_m: float
) -> tuple[F64, B]:
    centres = (np.arange(pixels) + 0.5) / pixels * 2 * radius_m - radius_m
    gx, gy = np.meshgrid(centres, -centres)
    return inverse_aeqd(gx.ravel(), gy.ravel(), lon, lat, planet_m), np.hypot(gx, gy) <= radius_m


def window_land(parent: RegionalParent, points: F64) -> B:
    land = unary_union(
        [Polygon(c.exterior, c.holes) for view in parent.world.land for c in view.components]
    )
    shapely.prepare(land)
    x, y = source_xy(parent.world.project.frame, points)
    return np.asarray(shapely.contains_xy(land, x, y), dtype=bool)


def compose_window(
    parent: RegionalParent,
    grid: TileGrid,
    tiles: dict[int, tuple[TileSurface, TileRivers]],
    centre: tuple[float, float],
    radius_km: float,
    pixels: int,
    river_km2: float,
) -> RegionWindow:
    planet_m = parent.mesh.radius_m
    radius_m = radius_km * 1e3
    points, inside = window_points(*centre, radius_m, pixels, planet_m)
    from dmtools.terrain.pipeline.planet_tiles import blend

    surfaces = {tile: surface for tile, (surface, _) in tiles.items()}
    land = window_land(parent, points).reshape(pixels, pixels) & inside
    sea = parent.sample(points, np.where(parent.land, 0.0, -2000.0)).reshape(pixels, pixels)
    elevation = np.zeros(pixels * pixels)
    elevation[inside.ravel()] = blend(grid, surfaces, points[inside.ravel()])
    elevation = elevation.reshape(pixels, pixels)
    elevation = np.where(land, np.maximum(elevation, 1.0), np.minimum(sea, -20.0))
    elevation = np.where(inside, elevation, np.nan)
    vegetation = (
        regional_vegetation(parent, points, elevation, land) if parent.biome is not None else None
    )
    # Rivers: each tile draws only segments it owns (largest blend weight there).
    rivers: list[tuple[float, float, float, float, float]] = []
    threshold = river_km2 * 1e6
    top = 1.0
    for tile, (surface, flow) in tiles.items():
        mesh = surface.mesh
        major = (flow.receiver >= 0) & (flow.area_m2 >= threshold)
        nodes = np.flatnonzero(major)
        if not len(nodes):
            continue
        ids, weights = grid.weights(mesh.xyz[nodes])
        owner = ids[np.arange(len(nodes)), np.argmax(weights, axis=1)] == tile
        nodes = nodes[owner]
        plane_a = forward_aeqd(mesh.xyz[nodes], *centre, planet_m)
        plane_b = forward_aeqd(mesh.xyz[flow.receiver[nodes]], *centre, planet_m)
        keep = (np.hypot(*plane_a.T) < radius_m) & (np.hypot(*plane_b.T) < radius_m)
        for (ax, ay), (bx, by), area in zip(
            plane_a[keep], plane_b[keep], flow.area_m2[nodes][keep], strict=True
        ):
            strength = float(np.log(area / threshold))
            top = max(top, strength)
            rivers.append((float(ax), float(ay), float(bx), float(by), strength))
    rivers = [(a, b, c, d, s / top) for a, b, c, d, s in rivers]
    return RegionWindow(
        centre, radius_m, pixels, elevation, land, vegetation, rivers, tuple(sorted(tiles))
    )


def regional_vegetation(parent: RegionalParent, points: F64, elevation: F64, land: B) -> F64:
    """Biome colours re-derived per pixel: parent climate, lapse-corrected to fine relief."""
    assert parent.temperature_c is not None and parent.precipitation_mm is not None
    shape = elevation.shape
    z = np.where(land, elevation, 0.0).ravel()
    lift = (z - parent.sample(points, parent.surface_m)) / 1000
    lapse = parent.settings.climate.lapse_c_per_km
    temperature = parent.sample(points, parent.temperature_c) - lapse * lift
    warm_source = parent.warm_season_c if parent.warm_season_c is not None else parent.temperature_c
    warm = parent.sample(points, warm_source) - lapse * lift
    precipitation = np.maximum(parent.sample(points, parent.precipitation_mm), 0.0)
    coast = (
        np.zeros(len(points))
        if parent.coast_m is None
        else np.maximum(parent.sample(points, np.maximum(parent.coast_m, 0.0)), 0.0)
    )
    latitude = np.arcsin(np.clip(points[:, 2], -1, 1))
    pet = potential_evapotranspiration(latitude, temperature, coast)
    biome = classify(temperature, warm, precipitation, pet, z, land.ravel())
    return np.asarray(BIOME_COLOURS, dtype=np.float64)[biome.astype(np.int64)].reshape(*shape, 3)


def _ramp(z: F64, stops: tuple[tuple[int, tuple[int, int, int]], ...]) -> F64:
    xs = np.array([k for k, _ in stops], dtype=np.float64)
    return np.stack([np.interp(z, xs, [c[i] for _, c in stops]) for i in range(3)], axis=-1)


def window_image(window: RegionWindow, *, atlas: bool) -> Image.Image:
    z = np.nan_to_num(window.elevation_m, nan=-200.0)
    gy, gx = np.gradient(z, window.pixel_m)
    gx, gy = gx * 6.0, -gy * 6.0
    az, alt = np.deg2rad(315), np.deg2rad(40)
    light = (np.cos(alt) * np.sin(az), np.cos(alt) * np.cos(az), np.sin(alt))
    shade = np.clip(
        (-gx * light[0] - gy * light[1] + light[2]) / np.sqrt(gx * gx + gy * gy + 1), 0, 1
    )
    land = window.land
    if atlas and window.vegetation_rgb is not None:
        rock = np.clip((z - 1500) / 2500, 0, 1)[..., None]
        land_rgb = (
            window.vegetation_rgb * (1 - rock)
            + _ramp(
                z,
                (
                    (0, (0, 0, 0)),
                    (1500, (0, 0, 0)),
                    (3200, (150, 130, 115)),
                    (5000, (245, 245, 245)),
                ),
            )
            * rock
        )
    else:
        land_rgb = _ramp(z, LAND_STOPS)
    rgb = np.where(land[..., None], land_rgb, _ramp(z, SEA_STOPS))
    rgb = rgb * np.where(land, 0.55 + 0.65 * shade, 0.95)[..., None]
    rgb[~np.isfinite(window.elevation_m)] = (36, 54, 82)
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    scale = window.pixels / (2 * window.radius_m)
    for x0, y0, x1, y1, strength in window.rivers:
        draw.line(
            (
                (x0 + window.radius_m) * scale,
                (window.radius_m - y0) * scale,
                (x1 + window.radius_m) * scale,
                (window.radius_m - y1) * scale,
            ),
            fill=RIVER_COLOUR,
            width=max(1, round(1 + 2 * strength)),
        )
    return image


def aeqd_crs_wkt(lon0: float, lat0: float, radius_m: float) -> str:
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat0!r} +lon_0={lon0!r} +R={radius_m!r} +units=m +no_defs"
    ).to_wkt()


def write_region(
    window: RegionWindow,
    parent_sha256: str,
    settings: RegionalSettings,
    store_key: str,
    destination: Path,
    planet_m: float,
) -> Path:
    target = destination.absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Region destination already exists: {target}")
    target.mkdir(parents=True)
    names = []
    lon0, lat0 = window.centre
    transform = Affine(window.pixel_m, 0, -window.radius_m, 0, -window.pixel_m, window.radius_m)
    with (target / "elevation.tif").open("xb"):
        pass
    with (
        rasterio.Env(GDAL_PAM_ENABLED=False, GDAL_NUM_THREADS="1"),
        rasterio.open(
            target / "elevation.tif",
            "w",
            driver="GTiff",
            width=window.pixels,
            height=window.pixels,
            count=1,
            dtype="float32",
            crs=cast(Any, CRS.from_wkt(aeqd_crs_wkt(lon0, lat0, planet_m))),
            transform=transform,
            nodata=float("nan"),
            compress="deflate",
            predictor=3,
        ) as dataset,
    ):
        dataset.write(window.elevation_m.astype(np.float32), 1)
        dataset.set_band_unit(1, "m")
    names.append("elevation.tif")
    window_image(window, atlas=False).save(target / "relief.png")
    names.append("relief.png")
    if window.vegetation_rgb is not None:
        window_image(window, atlas=True).save(target / "atlas.png")
        names.append("atlas.png")
    manifest: dict[str, object] = {
        "schema": REGION_SCHEMA,
        "version": REGION_VERSION,
        "status": "experimental",
        "algorithm": REGIONAL_ALGORITHM,
        "parent_build_sha256": parent_sha256,
        "centre_lonlat_deg": [lon0, lat0],
        "radius_km": window.radius_m / 1000,
        "pixels": window.pixels,
        "settings": asdict(settings),
        "tile_store": store_key,
        "tiles": list(window.tiles),
        "crs_wkt": aeqd_crs_wkt(lon0, lat0, planet_m),
        "outputs": {
            name: {"sha256": file_sha256(target / name), "bytes": (target / name).stat().st_size}
            for name in names
        },
    }
    manifest["region_sha256"] = sha256(canonical_json(manifest)).hexdigest()
    pending = target / "manifest.pending"
    pending.write_bytes(canonical_json(manifest))
    pending.replace(target / "manifest.json")
    return target / "manifest.json"


__all__ = ["RegionWindow", "TileStore", "compose_window", "json", "window_image", "write_region"]
