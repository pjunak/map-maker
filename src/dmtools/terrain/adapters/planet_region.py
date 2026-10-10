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
from PIL import Image
from rasterio.crs import CRS
from scipy.ndimage import binary_erosion, distance_transform_edt, gaussian_filter
from shapely.geometry import Polygon
from shapely.ops import unary_union

from dmtools.terrain.adapters.build import canonical_json, file_sha256
from dmtools.terrain.adapters.planet_natural import (
    HYPSOMETRIC,
    LAKE,
    RIVER,
    SALT_FLAT,
    PixelClimate,
    erg_cover,
    land_colour,
    ramp,
    river_coverage,
    sea_depth_colour,
    shading,
)
from dmtools.terrain.domain.planet import REGIONAL_ALGORITHM, RegionalSettings
from dmtools.terrain.pipeline.planet_climate import potential_evapotranspiration
from dmtools.terrain.pipeline.planet_detail import carve_valleys, eroded_fbm, grid_flow
from dmtools.terrain.pipeline.planet_forcing import source_xy
from dmtools.terrain.pipeline.planet_mesh import mesh_from_triangles
from dmtools.terrain.pipeline.planet_regional import RegionalParent, RegionalResult, inverse_aeqd
from dmtools.terrain.pipeline.planet_tiles import TileGrid, TileSurface
from dmtools.terrain.pipeline.planet_volcanism import edifice_height, sea_floor_with_volcanoes

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

REGION_SCHEMA = "dmtools.planet-region"
REGION_VERSION = 1
# Display-only regional relief (never exported). Regional pixels are a few
# hundred metres, far below the 5 km tile mesh, so mountains need sub-tile
# ridges and valleys; slopes need far less exaggeration than the world preview.
REGION_EXAGGERATION = 1.3
REGION_MOSAIC_WAVELENGTH_M = 8e3
MEANDER_RUNOFF_M_YR = 0.3  # assumed runoff for discharge from drainage area
DUNE_SPACING_M = 2500.0
DUNE_HEIGHT_M = 45.0
TRAP_STEP_M = 150.0  # thickness of the lava-flow packages that form benches
LAKE_SHORE_M = 2.0  # lake pixels lie at most this far above the lake level
# Pixel slopes at ~0.5 km are ~4x those of the same terrain on ~7 km world pixels.
REGION_SLOPE_SCALE = 3.5
REGION_DETAIL_SEED = 17
REGION_DETAIL_WAVELENGTH_M = 30e3
REGION_DETAIL_FLOOR_M = 70.0
REGION_DETAIL_SHARE = 0.6  # detail amplitude per metre of tile height
REGION_CARVE_ERODIBILITY = 0.4  # K * dt for valley carving (m^0)
REGION_CARVE_STEPS = 4


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
            )
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(self.path(tile))

    def load(self, tile: int, radius_m: float) -> TileSurface:
        with np.load(self.path(tile), allow_pickle=False) as data:
            mesh = mesh_from_triangles(
                data["xyz"].astype(np.float64), data["triangles"].astype(np.int64), radius_m
            )
            return TileSurface(mesh, data["elevation_m"].astype(np.float64))


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
    climate: PixelClimate | None
    rivers: F64  # anti-aliased river coverage 0..1
    points: F64  # pixel unit vectors (pixels * pixels, 3)
    tiles: tuple[int, ...]
    planet_m: float
    lapse_c_per_km: float
    volcanic: F64  # 0..1 cover of young volcanic edifices near summits
    lakes: B  # lake water (parent lakes with shores on the regional relief)
    salt: B  # dry salt pans of hot, arid closed lakes
    basalt: F64  # 0..1 flood-basalt cover
    wind: F64 | None  # (pixels, pixels, 2) annual mean wind (east, north) in m/s

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
    tiles: dict[int, TileSurface],
    centre: tuple[float, float],
    radius_km: float,
    pixels: int,
    river_km2: float,
) -> RegionWindow:
    planet_m = parent.mesh.radius_m
    radius_m = radius_km * 1e3
    points, inside = window_points(*centre, radius_m, pixels, planet_m)
    from dmtools.terrain.pipeline.planet_tiles import blend

    surfaces = tiles
    land = window_land(parent, points).reshape(pixels, pixels) & inside
    floor = parent.sea_floor_m
    if floor is None:
        floor = np.where(parent.land, 0.0, -2000.0)
    sea = parent.sample(points, floor).reshape(pixels, pixels)
    elevation = np.zeros(pixels * pixels)
    elevation[inside.ravel()] = blend(grid, surfaces, points[inside.ravel()])
    elevation = elevation.reshape(pixels, pixels)
    volcanic = np.zeros((pixels, pixels))
    if parent.volcanoes is not None and parent.volcanic_m is not None:
        # Draw volcanoes sharply at pixel scale on the regional relief and sea floor.
        sharp = edifice_height(points, planet_m, parent.volcanoes).reshape(pixels, pixels)
        floor_only = sea - parent.sample(
            points, np.where(parent.land, 0.0, parent.volcanic_m)
        ).reshape(pixels, pixels)
        sea = sea_floor_with_volcanoes(
            points, planet_m, parent.volcanoes, floor_only.ravel()
        ).reshape(pixels, pixels)
        elevation = np.where(land, elevation + sharp, elevation)
        # Opt-in volcanic islands rise from the sea floor beyond the authored coast.
        islands = inside & ~land & (sea > 0)
        land = land | islands
        volcanic = np.where(land, np.clip((sharp - 300.0) / 2200.0, 0.0, 1.0) ** 2, 0.0)
    else:
        islands = np.zeros((pixels, pixels), dtype=bool)
    elevation = np.where(land, np.maximum(elevation, 1.0), np.minimum(sea, -5.0))
    elevation = np.where(islands, sea, elevation)
    # Lakes fill the regional relief up to the parent lake level, so shores
    # follow the fine terrain instead of the coarse parent mesh.
    cover, level, closed = parent.lakes_at(points)
    lakes = (
        land
        & inside
        & (cover.reshape(pixels, pixels) > 0.15)
        & (elevation <= level.reshape(pixels, pixels) + LAKE_SHORE_M)
    )
    salt = lakes & closed.reshape(pixels, pixels)
    elevation = np.where(inside, elevation, np.nan)
    climate = regional_climate(parent, points, elevation, land)
    coverage = window_rivers(
        parent, points, elevation, land, lakes, inside, river_km2, 2 * radius_m / pixels
    )
    coverage = np.where(land & ~lakes, coverage, 0.0)
    return RegionWindow(
        centre,
        radius_m,
        pixels,
        elevation,
        land,
        climate,
        coverage,
        points,
        tuple(sorted(tiles)),
        planet_m,
        parent.settings.climate.lapse_c_per_km,
        volcanic,
        lakes,
        salt,
        (
            np.zeros((pixels, pixels))
            if parent.flood_basalt is None
            else np.clip(parent.sample(points, parent.flood_basalt), 0, 1).reshape(pixels, pixels)
        ),
        (
            None
            if parent.wind_east is None or parent.wind_north is None
            else np.stack(
                (parent.sample(points, parent.wind_east), parent.sample(points, parent.wind_north)),
                axis=-1,
            ).reshape(pixels, pixels, 2)
        ),
    )


def window_rivers(
    parent: RegionalParent,
    points: F64,
    elevation: F64,
    land: B,
    lakes: B,
    inside: B,
    river_km2: float,
    pixel_m: float,
) -> F64:
    """River coverage routed on the window's blended relief.

    One drainage network over the whole window follows the drawn valleys and
    has no seams between tiles. Rivers entering from outside the window carry
    the parent's upstream area, spread over the rim pixels the parent river
    crosses.
    """
    pixels = elevation.shape[0]
    z = np.where(inside, np.nan_to_num(elevation, nan=0.0), 0.0)
    outlet = ~inside | ~land
    # Parent drainage area at the rim: rivers entering from beyond the window.
    rim = inside & ~np.asarray(binary_erosion(inside), dtype=bool)
    upstream = parent.sample(points, parent.area_m2).reshape(pixels, pixels)
    inflow = np.where(rim & land, upstream * pixel_m / parent.mesh.spacing_m, 0.0)
    receiver, area = grid_flow(z, outlet, pixel_m, inflow)
    flat = np.arange(pixels * pixels)
    x = (flat % pixels + 0.5).astype(np.float64)
    y = (flat // pixels + 0.5).astype(np.float64)
    stop = (outlet | lakes).ravel()
    major = ~stop & (receiver >= 0) & (area >= river_km2 * 1e6)
    # Hydraulic geometry: channel width ~4.8 sqrt(Q) m (Leopold and Maddock
    # 1953), meander wavelength ~11 widths; rivers meander on gentle ground.
    discharge = area * MEANDER_RUNOFF_M_YR / 3.156e7
    wavelength = 11 * 4.8 * np.sqrt(discharge) / pixel_m
    target = np.maximum(receiver, 0)
    drop = z.ravel() - z.ravel()[target]
    run = np.hypot(flat % pixels - target % pixels, flat // pixels - target // pixels) * pixel_m
    gentle = 1 - np.clip((drop / np.maximum(run, 1.0) - 0.0005) / 0.0025, 0, 1)
    return river_coverage(
        x, y, receiver, area, major, stop, (pixels, pixels), pixels / 1100,
        meander_px=np.where(gentle > 0.3, wavelength * gentle, 0.0),
    )


def regional_climate(
    parent: RegionalParent, points: F64, elevation: F64, land: B
) -> PixelClimate | None:
    """Parent climate at each pixel, lapse-corrected to the fine relief."""
    if parent.temperature_c is None or parent.precipitation_mm is None:
        return None
    shape = elevation.shape
    z = np.where(land, np.nan_to_num(elevation, nan=0.0), 0.0).ravel()
    # Volcanoes rise after the climate is simulated: lapse-correct whole edifices.
    surface = parent.surface_m
    if parent.volcanic_m is not None:
        surface = surface - np.where(parent.land, parent.volcanic_m, 0.0)
    lift = (z - parent.sample(points, surface)) / 1000
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
    growing = (
        None
        if parent.precip_warm_mm is None
        else np.maximum(parent.sample(points, parent.precip_warm_mm), 0.0).reshape(shape)
    )
    return PixelClimate(
        temperature.reshape(shape),
        warm.reshape(shape),
        precipitation.reshape(shape),
        pet.reshape(shape),
        growing,
    )


def display_relief(window: RegionWindow) -> F64:
    """Elevation plus sub-tile ridges and valleys for shading only (never exported).

    The 5 km tile mesh cannot resolve hillslopes, so mountains would shade as
    smooth domes. Ridged, slope-damped noise scaled with height adds roughness,
    and a few stream-power steps routed over that rough surface carve it into a
    connected, branching valley network. Carving depth is capped at the local
    detail amplitude, so the tile relief keeps its shape.
    """
    z = np.nan_to_num(window.elevation_m, nan=-200.0)
    land = window.land
    if not land.any():
        return z
    base = np.where(land, z, 0.0)
    inside = np.isfinite(window.elevation_m)
    tile_slope = gaussian_filter(
        np.hypot(*np.gradient(np.where(inside, z, 0.0), window.pixel_m)), 3.0
    )
    # Flat plains and plateau tops stay smooth; slopes get ridges and gullies.
    # Ridged noise creases into sharp lines, so it too needs relief, not height.
    ruggedness = 0.15 + 0.85 * np.clip((tile_slope - 0.002) / 0.018, 0, 1)
    ridged = (np.clip((base - 300) / 1500, 0, 1) * ruggedness).ravel()
    detail = eroded_fbm(
        window.points,
        ridged,
        REGION_DETAIL_SEED,
        5,
        window.planet_m / REGION_DETAIL_WAVELENGTH_M,
        0.5,
        0.1,
    ).reshape(z.shape)
    detail -= detail[land].mean()
    amplitude = (REGION_DETAIL_FLOOR_M + REGION_DETAIL_SHARE * base) * ruggedness
    rough = np.where(land, z + amplitude * detail, z)
    # Outside the window circle, hold each cell at the nearest inside height so
    # the rim is not a base level that every border valley would cut down to.
    nearest = cast(
        NDArray[np.intp],
        distance_transform_edt(~inside, return_distances=False, return_indices=True),
    )
    rough = rough[nearest[0], nearest[1]]
    carved = carve_valleys(
        rough,
        ~land,
        window.pixel_m,
        np.full(z.shape[0], window.pixel_m),
        REGION_CARVE_ERODIBILITY,
        0.5,
        REGION_CARVE_STEPS,
    )
    # Flats and plateaus carve into straight grid-aligned grooves, and real ones
    # stay smooth at this scale, so incision follows the tile relief's slope.
    steep = np.clip((tile_slope - 0.006) / 0.024, 0, 1)
    # Blurring the incision widens one-pixel D8 channels into valleys.
    depth = gaussian_filter(np.clip(rough - carved, 0, amplitude) * steep, 1.3)
    relief = gaussian_filter(rough - depth, 0.5)
    # Linear (seif) dunes run along the resultant wind in sand seas, ~2 km apart
    # and tens of metres high; they break up and wander along their length.
    climate = window.climate
    if climate is not None and window.wind is not None:
        erg = np.where(
            land,
            erg_cover(
                window.points, window.planet_m, climate, tile_slope,
                window_position(relief, window.pixel_m), REGION_SLOPE_SCALE,
            ),
            0.0,
        )
        if erg.max() > 0.05:
            wind = gaussian_filter(window.wind, (6, 6, 0))
            speed = np.maximum(np.hypot(wind[..., 0], wind[..., 1]), 1e-6)
            rows, columns = np.mgrid[0 : z.shape[0], 0 : z.shape[1]] * window.pixel_m
            # Distance across the wind: east is +column, north is -row.
            across = (columns * -wind[..., 1] + (-rows) * wind[..., 0]) / speed
            # Spacing and phase wander, so ridges merge in Y-junctions and fan out.
            warp = 0.6 * DUNE_SPACING_M * eroded_fbm(
                window.points, np.zeros(len(window.points)), 71, 4,
                window.planet_m / 25e3, 0.55, 0.0,
            ).reshape(z.shape)
            spacing = DUNE_SPACING_M * (1 + 0.3 * eroded_fbm(
                window.points, np.zeros(len(window.points)), 72, 3,
                window.planet_m / 60e3, 0.5, 0.0,
            ).reshape(z.shape))
            crest = (0.5 + 0.5 * np.cos(2 * np.pi * (across + warp) / spacing)) ** 1.5
            breakup = _smooth_step(
                eroded_fbm(
                    window.points, np.zeros(len(window.points)), 73, 3,
                    window.planet_m / 12e3, 0.5, 0.0,
                ).reshape(z.shape),
                -0.3, 0.2,
            )
            relief = relief + DUNE_HEIGHT_M * erg * breakup * crest
    # Flood basalts weather into stepped escarpments: each resistant lava flow
    # holds a bench (the "trap" stairs of the Deccan and Columbia River plateaus).
    if window.basalt.any():
        level = np.floor(relief / TRAP_STEP_M) * TRAP_STEP_M
        riser = np.clip((relief - level) / TRAP_STEP_M, 0, 1)
        benches = level + TRAP_STEP_M * np.clip((riser - 0.7) / 0.3, 0, 1) ** 2
        relief = relief + (benches - relief) * 0.8 * window.basalt
    return np.where(land, np.maximum(relief, 1.0), z)


def _smooth_step(x: F64, a: float, b: float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def window_position(z: F64, pixel_m: float) -> F64:
    """Valley (-1) to ridge (+1) position from height above the local mean at 3-15 km."""
    total = np.zeros_like(z)
    for radius_m, weight, scale_m in ((3e3, 0.5, 80.0), (15e3, 0.5, 300.0)):
        total += weight * np.tanh((z - gaussian_filter(z, radius_m / pixel_m)) / scale_m)
    return total


def window_image(window: RegionWindow, *, atlas: bool) -> Image.Image:
    """Natural-colour (atlas) or shaded hypsometric view of a regional window."""
    z = display_relief(window)
    gy = np.gradient(z, axis=0) / window.pixel_m
    gx = np.gradient(z, axis=1) / window.pixel_m
    slope, light = shading(gx, gy, REGION_EXAGGERATION)
    land = window.land
    climate = window.climate
    if atlas and climate is not None:
        lapse = window.lapse_c_per_km * (z - np.nan_to_num(window.elevation_m)) / 1000
        shown = PixelClimate(
            climate.temperature_c - lapse,
            climate.warm_season_c - lapse,
            climate.precipitation_mm,
            climate.pet_mm,
            climate.growing_mm,
        )
        wet = 0.6 * gaussian_filter(window.rivers, 2.0)
        land_rgb = land_colour(
            window.points, window.planet_m, shown, z, slope, light, wet,
            window_position(z, window.pixel_m), REGION_MOSAIC_WAVELENGTH_M,
            window.volcanic,
            REGION_SLOPE_SCALE,
            window.basalt,
        )
    else:
        land_rgb = ramp(z, HYPSOMETRIC) * (0.30 + 0.70 * np.clip(light, 0, 1.5))[..., None]
    rgb = np.where(land[..., None], land_rgb, sea_depth_colour(-z, light))
    if window.lakes.any():
        pan = window.salt
        if climate is not None:
            # Closed lakes in hot, arid basins dry to salt pans; others stay saline lakes.
            arid = climate.precipitation_mm / np.maximum(climate.pet_mm, 1.0) < 0.35
            pan = pan & arid & (climate.temperature_c > 12.0)
        else:
            pan = np.zeros_like(pan)
        rgb[window.lakes & ~pan] = LAKE
        rgb[pan] = SALT_FLAT
    alpha = (0.9 * window.rivers)[..., None]
    rgb = rgb * (1 - alpha) + np.asarray(RIVER, dtype=np.float64) * alpha
    rgb[~np.isfinite(window.elevation_m)] = (36, 54, 82)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


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
    if window.climate is not None:
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
