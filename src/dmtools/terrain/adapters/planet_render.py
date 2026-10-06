# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Planet rasters aligned with the world SVG frame, and cartographic previews.

Columns and rows map linearly to the world frame (and therefore to longitude and
latitude), so a preview can sit directly under the source drawing. Land/sea is
the exact vector coastline rasterised at the output size. Land values are
interpolated from a field with sea level on water nodes, and sea values from a
field with zero depth on land nodes, so near-coast pixels never mix the two.
"""

from dataclasses import dataclass
from math import pi

import numpy as np
from affine import Affine
from numpy.typing import NDArray
from PIL import Image, ImageDraw
from rasterio import features
from scipy.spatial import KDTree
from shapely.geometry import Polygon, mapping

from dmtools.terrain.domain.world import WorldFrame
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.pipeline.planet_climate import BIOME_COLOURS
from dmtools.terrain.pipeline.planet_kernels import interpolate_to_lonlat
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, vertex_triangles
from dmtools.terrain.pipeline.world import WorldMap

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

LAND_STOPS = (
    (0, (88, 128, 74)), (200, (118, 152, 86)), (600, (170, 178, 112)), (1200, (204, 182, 128)),
    (2000, (176, 136, 96)), (3000, (140, 104, 80)), (4200, (190, 180, 176)),
    (5500, (250, 250, 250)),
)
SEA_STOPS = (
    (-6000, (16, 34, 66)), (-4000, (26, 56, 98)), (-2000, (40, 86, 136)),
    (-500, (62, 122, 170)), (-120, (92, 158, 196)), (0, (128, 186, 214)),
)
ROCK_STOPS = ((0, (0, 0, 0)), (1500, (0, 0, 0)), (3200, (150, 130, 115)), (5000, (245, 245, 245)))
RIVER_COLOUR = (52, 96, 160)
LAKE_COLOUR = (78, 130, 182)
SALT_LAKE_COLOUR = (150, 170, 176)
SECONDS_PER_YEAR = 365.25 * 86400


def raster_shape(frame: WorldFrame, width: int) -> tuple[int, int]:
    if type(width) is not int or not 64 <= width <= 16_384:
        raise ValueError("Planet raster width must be an integer from 64 to 16,384 pixels.")
    return max(32, round(width * frame.height / frame.width)), width


@dataclass(frozen=True, slots=True)
class FrameRaster:
    """Pixel centres of a world-frame raster and their mesh interpolation support."""

    frame: WorldFrame
    shape: tuple[int, int]
    latitude: F64  # radians per row
    queries: F64
    nearest: NDArray[np.int64]
    vt_ptr: NDArray[np.int64]
    vt_idx: NDArray[np.int64]

    @classmethod
    def build(cls, mesh: SphereMesh, frame: WorldFrame, width: int) -> FrameRaster:
        rows, columns = raster_shape(frame, width)
        centre = frame.central_meridian_deg
        lon = np.deg2rad(centre - 180 + (np.arange(columns) + 0.5) / columns * 360)
        lat = np.deg2rad(90 - (np.arange(rows) + 0.5) / rows * 180)
        glon, glat = np.meshgrid(lon, lat)
        q = np.stack(
            (np.cos(glat) * np.cos(glon), np.cos(glat) * np.sin(glon), np.sin(glat)), axis=-1
        ).reshape(-1, 3)
        nearest = np.asarray(KDTree(mesh.xyz).query(q, workers=-1)[1], dtype=np.int64)
        vt_ptr, vt_idx = vertex_triangles(mesh)
        return cls(frame, (rows, columns), lat, q, nearest, vt_ptr, vt_idx)

    def interpolate(self, mesh: SphereMesh, values: F64) -> F64:
        out = interpolate_to_lonlat(
            np.ascontiguousarray(values, dtype=np.float64), mesh.xyz, mesh.triangles,
            self.vt_ptr, self.vt_idx, mesh.ptr, mesh.nbr, self.nearest, self.queries,
        )
        return out.reshape(self.shape)

    def transform(self) -> Affine:
        """Pixel -> world SVG source coordinates."""
        rows, columns = self.shape
        x0, y0, _, _ = self.frame.bounds
        return Affine(self.frame.width / columns, 0, x0, 0, self.frame.height / rows, y0)

    def lonlat_transform(self) -> Affine:
        rows, columns = self.shape
        return Affine(360 / columns, 0, self.frame.central_meridian_deg - 180, 0, -180 / rows, 90)


def land_mask(world: WorldMap, raster: FrameRaster) -> B:
    shapes = [
        mapping(Polygon(c.exterior, c.holes)) for view in world.land for c in view.components
    ]
    burned = features.rasterize(
        ((shape, 1) for shape in shapes), out_shape=raster.shape, transform=raster.transform(),
        fill=0, dtype="uint8", all_touched=False,
    )
    return np.asarray(burned, dtype=np.uint8).astype(bool)


def elevation_raster(result: PlanetResult, raster: FrameRaster, land_px: B) -> F64:
    water = ~result.land
    on_land = raster.interpolate(result.mesh, np.where(water, 0.0, result.elevation_m))
    at_sea = raster.interpolate(result.mesh, np.where(water, result.elevation_m, 0.0))
    return np.where(land_px, np.maximum(on_land, 0.0), np.minimum(at_sea, 0.0))


def lake_raster(result: PlanetResult, raster: FrameRaster, land_px: B) -> NDArray[np.int64]:
    """Lake id per pixel (-1 none), from triangle-interpolated lake membership."""
    lakes = result.lakes
    on_lake = raster.interpolate(result.mesh, (lakes.lake >= 0).astype(np.float64)) > 0.5
    nearest = lakes.lake[raster.nearest.reshape(raster.shape)]
    return np.where(on_lake & land_px & (nearest >= 0), nearest, -1)


def paint_lakes(image: Image.Image, result: PlanetResult, lakes_px: NDArray[np.int64]) -> None:
    if not len(result.lakes.level_m):
        return
    rgb = np.asarray(image).copy()
    closed = result.lakes.endorheic[np.maximum(lakes_px, 0)] & (lakes_px >= 0)
    rgb[(lakes_px >= 0) & ~closed] = LAKE_COLOUR
    rgb[closed] = SALT_LAKE_COLOUR
    image.paste(Image.fromarray(rgb))


def _ramp(z: F64, stops: tuple[tuple[int, tuple[int, int, int]], ...]) -> F64:
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    return np.stack([np.interp(z, xs, [s[1][c] for s in stops]) for c in range(3)], axis=-1)


def hillshade(z: F64, latitude: F64, radius_m: float, exaggeration: float = 10.0) -> F64:
    rows, columns = z.shape
    dy = pi * radius_m / rows
    dx = 2 * pi * radius_m / columns * np.maximum(np.cos(latitude), 0.02)[:, None]
    gy = np.gradient(z, axis=0) / dy * exaggeration
    gx = (np.roll(z, -1, axis=1) - np.roll(z, 1, axis=1)) / (2 * dx) * exaggeration
    azimuth, altitude = np.deg2rad(315), np.deg2rad(40)
    lx = np.cos(altitude) * np.sin(azimuth)
    ly = np.cos(altitude) * np.cos(azimuth)
    lz = np.sin(altitude)
    return np.clip((-gx * lx + gy * ly + lz) / np.sqrt(gx * gx + gy * gy + 1), 0, 1)


def relief_image(z: F64, land_px: B, raster: FrameRaster) -> Image.Image:
    rgb = np.where(land_px[..., None], _ramp(z, LAND_STOPS), _ramp(z, SEA_STOPS))
    shade = hillshade(z, raster.latitude, raster.frame.radius_km * 1000, 12.0)
    factor = np.where(land_px, 0.55 + 0.65 * shade, 0.85 + 0.25 * shade)
    return Image.fromarray(np.clip(rgb * factor[..., None], 0, 255).astype(np.uint8))


def biome_rgb(result: PlanetResult, raster: FrameRaster) -> F64:
    assert result.climate is not None
    colours = np.asarray(BIOME_COLOURS, dtype=np.float64)[result.climate.biome.astype(np.int64)]
    # Fill water nodes with the nearest land colour so coastal pixels do not darken.
    land_index = np.flatnonzero(result.land)
    tree = KDTree(result.mesh.xyz[land_index])
    nearest_land = land_index[np.asarray(tree.query(result.mesh.xyz, workers=-1)[1])]
    colours = colours[nearest_land]
    return np.stack([raster.interpolate(result.mesh, colours[:, k]) for k in range(3)], axis=-1)


def atlas_image(z: F64, land_px: B, raster: FrameRaster, vegetation: F64) -> Image.Image:
    shade = hillshade(z, raster.latitude, raster.frame.radius_km * 1000, 10.0)
    rock_weight = np.clip((z - 1500) / 2500, 0, 1)[..., None]
    land_rgb = vegetation * (1 - rock_weight) + _ramp(z, ROCK_STOPS) * rock_weight
    rgb = np.where(land_px[..., None], land_rgb, _ramp(z, SEA_STOPS))
    factor = np.where(land_px, 0.55 + 0.6 * shade, 0.88 + 0.2 * shade)
    return Image.fromarray(np.clip(rgb * factor[..., None], 0, 255).astype(np.uint8))


def scalar_image(
    values: F64, land_px: B, low: float, high: float, colours: tuple[tuple[int, int, int], ...]
) -> Image.Image:
    t = np.clip((values - low) / (high - low), 0, 1)
    knots = np.linspace(0, 1, len(colours))
    rgb = np.stack([np.interp(t, knots, [c[k] for c in colours]) for k in range(3)], axis=-1)
    rgb[~land_px] = (36, 54, 82)
    return Image.fromarray(rgb.astype(np.uint8))


def river_threshold_m3_s(result: PlanetResult, area_km2: float) -> float:
    """Discharge equivalent to ``area_km2`` at the planet's mean land runoff."""
    land = result.land
    climate = result.climate
    runoff_mm = 250.0 if climate is None else float(
        np.average(climate.runoff_mm[land], weights=result.mesh.area_m2[land])
    )
    return area_km2 * 1e6 * runoff_mm / 1000 / SECONDS_PER_YEAR


def draw_rivers(
    image: Image.Image, result: PlanetResult, raster: FrameRaster, threshold_m3_s: float
) -> int:
    """Rivers whose net discharge exceeds ``threshold_m3_s``; none across lake surfaces."""
    rows, columns = raster.shape
    frame = raster.frame
    mesh, flow = result.mesh, result.flow
    discharge = result.lakes.discharge_m3_s
    on_lake = result.lakes.lake >= 0
    lon = np.rad2deg(mesh.lon)
    x = ((lon - frame.central_meridian_deg + 180) % 360) / 360 * columns
    y = (90 - np.rad2deg(mesh.lat)) / 180 * rows
    water = ~result.land
    nodes = np.flatnonzero(
        (~water) & ~on_lake & (flow.receiver >= 0) & (discharge >= threshold_m3_s)
    )
    if not len(nodes):
        return 0
    draw = ImageDraw.Draw(image)
    top = float(np.log(discharge[nodes].max() / threshold_m3_s)) or 1.0
    scale = max(1.0, columns / 2048)
    drawn = 0
    for i in nodes[np.argsort(discharge[nodes])].tolist():
        r = int(flow.receiver[i])
        x0, y0, x1, y1 = float(x[i]), float(y[i]), float(x[r]), float(y[r])
        if abs(x1 - x0) > columns / 2:
            continue
        strength = float(np.log(discharge[i] / threshold_m3_s)) / top
        width = max(1, round(scale * (1 + 2.2 * strength)))
        draw.line((x0, y0, x1, y1), fill=RIVER_COLOUR, width=width)
        drawn += 1
    return drawn


PREVIEW_LAYERS = ("Planet atlas", "Planet relief", "Planet rainfall", "Planet temperature")
RAIN_COLOURS = ((150, 90, 40), (230, 210, 140), (120, 190, 90), (30, 120, 160), (20, 40, 140))
TEMPERATURE_COLOURS = (
    (60, 40, 160), (90, 160, 220), (240, 240, 200), (240, 160, 60), (180, 40, 30)
)


@dataclass(frozen=True, slots=True)
class PlanetRasters:
    """Frame-aligned rasters shared by previews and exports."""

    raster: FrameRaster
    land_px: B
    elevation_m: F64
    lakes_px: NDArray[np.int64]


def planet_rasters(result: PlanetResult, width: int) -> PlanetRasters:
    raster = FrameRaster.build(result.mesh, result.world.project.frame, width)
    land_px = land_mask(result.world, raster)
    z = elevation_raster(result, raster, land_px)
    return PlanetRasters(raster, land_px, z, lake_raster(result, raster, land_px))


def preview_images(
    result: PlanetResult, rasters: PlanetRasters, threshold_m3_s: float
) -> dict[str, Image.Image]:
    """Named cartographic previews; climate layers only when climate exists."""
    raster, land_px, z, lakes_px = (
        rasters.raster, rasters.land_px, rasters.elevation_m, rasters.lakes_px
    )
    images: dict[str, Image.Image] = {}
    relief = relief_image(z, land_px, raster)
    paint_lakes(relief, result, lakes_px)
    draw_rivers(relief, result, raster, threshold_m3_s)
    climate = result.climate
    if climate is not None:
        atlas = atlas_image(z, land_px, raster, biome_rgb(result, raster))
        paint_lakes(atlas, result, lakes_px)
        draw_rivers(atlas, result, raster, threshold_m3_s)
        images["Planet atlas"] = atlas
    images["Planet relief"] = relief
    if climate is not None:
        mesh = result.mesh
        images["Planet rainfall"] = scalar_image(
            raster.interpolate(mesh, climate.precipitation_mm), land_px, 0.0, 2500.0, RAIN_COLOURS
        )
        images["Planet temperature"] = scalar_image(
            raster.interpolate(mesh, climate.temperature_c), land_px, -25.0, 30.0,
            TEMPERATURE_COLOURS,
        )
    return images


def render_previews(result: PlanetResult, width: int, river_km2: float) -> dict[str, Image.Image]:
    return preview_images(
        result, planet_rasters(result, width), river_threshold_m3_s(result, river_km2)
    )
