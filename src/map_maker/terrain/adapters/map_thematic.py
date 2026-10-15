# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Thematic world maps: tectonic plates, drainage basins, geology and sea-floor age.

Each is drawn on the world frame over soft hillshade so the relief stays
readable; they are derived display, not new generation.
"""

from __future__ import annotations

import colorsys

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation

from map_maker.terrain.adapters.planet_render import FrameRaster, PlanetRasters
from map_maker.terrain.domain.planet import PLANET_FORCING_STAGE_ID
from map_maker.terrain.pipeline.planet import PlanetResult
from map_maker.terrain.pipeline.planet_forcing import plate_sea_floor_age_myr, sea_floor_age_myr
from map_maker.terrain.pipeline.planet_tectonics import Tectonics
from map_maker.terrain.pipeline.planet_volcanism import SEAMOUNT

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]
type I64 = NDArray[np.int64]

OCEAN: tuple[int, int, int] = (62, 92, 132)
LAND_GREY: tuple[int, int, int] = (196, 190, 178)
COAST: tuple[int, int, int] = (40, 40, 40)
CONVERGENT: tuple[int, int, int] = (215, 40, 30)
DIVERGENT: tuple[int, int, int] = (30, 110, 230)
TRANSFORM: tuple[int, int, int] = (245, 200, 30)
DIVIDE: tuple[int, int, int] = (70, 60, 50)
RIVER: tuple[int, int, int] = (30, 80, 170)
BOUNDARY_RATE_M_YR = 0.005  # opening or closing faster than this is not a transform

# Geological provinces (colours follow geological-map conventions).
PROVINCES = (
    ("Shield and platform", (232, 178, 170)),
    ("Old fold belt", (216, 160, 98)),
    ("Active mountain belt", (176, 86, 70)),
    ("Sedimentary basin", (242, 222, 140)),
    ("Rift", (150, 170, 90)),
    ("Flood basalt", (120, 82, 122)),
    ("Volcanic rock", (218, 64, 52)),
)
SHIELD, OLD_BELT, ACTIVE_BELT, BASIN, RIFT, BASALT, VOLCANIC = range(len(PROVINCES))
AGE_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (200, 30, 30)),
    (10.0, (240, 120, 40)),
    (25.0, (245, 220, 70)),
    (50.0, (120, 200, 90)),
    (80.0, (60, 180, 200)),
    (120.0, (50, 90, 200)),
    (180.0, (90, 50, 150)),
)


def plates_image(
    result: PlanetResult, rasters: PlanetRasters, light: F64, plates: Tectonics
) -> Image.Image:
    """Plates in distinct colours, boundaries by type, and plate-motion arrows."""
    raster = rasters.raster
    node = raster.nearest.reshape(raster.shape)
    plate = plates.plate[node]
    count = int(plates.plate.max()) + 1
    palette = np.array([_hue_colour(k, count) for k in range(count)], dtype=np.float64)
    colour = palette[plate]
    colour = np.where(
        rasters.land_px[..., None], 0.7 * colour + 0.3 * 255, 0.45 * colour + 0.55 * np.array(OCEAN)
    )
    rgb = _shaded(colour, light)
    edge = _edges(plate)
    rate = plates.convergence[node]
    width = max(1, round(raster.shape[1] / 2000))
    for kind, colour_of in (
        (rate > BOUNDARY_RATE_M_YR, CONVERGENT),
        (rate < -BOUNDARY_RATE_M_YR, DIVERGENT),
        (np.abs(rate) <= BOUNDARY_RATE_M_YR, TRANSFORM),
    ):
        mask = np.asarray(binary_dilation(edge & kind, iterations=width), dtype=bool)
        rgb[mask] = colour_of
    rgb = _coastline(rgb, rasters.land_px)
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    _motion_arrows(image, raster, plates)
    return image


def _motion_arrows(image: Image.Image, raster: FrameRaster, plates: Tectonics) -> None:
    rows, columns = raster.shape
    draw = ImageDraw.Draw(image)
    step = max(12, columns // 36)
    speed_scale = step * 0.8 / 0.08  # 8 cm/yr draws most of a cell
    node = raster.nearest.reshape(raster.shape)
    for row in range(step // 2, rows, step):
        latitude = raster.latitude[row]
        if abs(latitude) > np.deg2rad(70):  # arrows stretch too far near the poles
            continue
        for column in range(step // 2, columns, step):
            k = node[row, column]
            east = float(plates.velocity_east[k])
            north = float(plates.velocity_north[k])
            dx = east * speed_scale / max(float(np.cos(latitude)), 0.2)
            dy = -north * speed_scale
            if np.hypot(dx, dy) < 2:
                continue
            tip = (column + dx, row + dy)
            line = max(1, step // 24)
            draw.line(((float(column), float(row)), tip), fill=(20, 20, 20), width=line)
            angle = float(np.arctan2(dy, dx))
            head = max(3.0, step * 0.12)
            for side in (2.6, -2.6):
                barb = (tip[0] + head * np.cos(angle + side), tip[1] + head * np.sin(angle + side))
                draw.line((tip, barb), fill=(20, 20, 20), width=line)


def basins_image(
    result: PlanetResult, rasters: PlanetRasters, light: F64, rivers: F64
) -> Image.Image:
    """Each drainage basin in its own colour; closed basins hatched grey; divides drawn."""
    raster = rasters.raster
    root = drainage_roots(result.lakes.flow.receiver)
    land = result.land
    area = np.bincount(root[land], result.mesh.area_m2[land], result.mesh.size)
    closed = land[root]  # the basin ends on land: an endorheic sink
    node = raster.nearest.reshape(raster.shape)
    basin = root[node]
    big = area[basin] > 1e11  # 100,000 km^2: the great rivers stand out
    hashed = (basin.astype(np.uint64) * np.uint64(2654435761)) % np.uint64(997)
    hue = hashed.astype(np.float64) / 997
    colour = np.stack(_hsv(hue, np.where(big, 0.45, 0.18), np.where(big, 0.92, 0.88)), axis=-1)
    hatch = ((np.arange(raster.shape[0])[:, None] + np.arange(raster.shape[1])) // 3) % 4 == 0
    colour = np.where(
        (closed[basin] & hatch)[..., None], np.array([150.0, 140.0, 125.0]), colour
    )
    colour = np.where(rasters.land_px[..., None], colour, np.array(OCEAN, dtype=np.float64))
    rgb = _shaded(colour, light)
    divides = _edges(np.where(rasters.land_px, basin, -1)) & rasters.land_px
    rgb[divides & big] = DIVIDE
    rgb = rgb * (1 - 0.9 * rivers[..., None]) + np.array(RIVER) * 0.9 * rivers[..., None]
    rgb = _coastline(rgb, rasters.land_px)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def drainage_roots(receiver: I64) -> I64:
    """The node each node finally drains to: a sea node, or a closed-basin sink."""
    root = np.where(receiver < 0, np.arange(len(receiver)), receiver)
    while True:
        nxt = root[root]
        if np.array_equal(nxt, root):
            return root
        root = nxt


def geology_provinces(result: PlanetResult) -> I64:
    """Geological province per node (index into PROVINCES); -1 at sea."""
    land = result.land
    forcing = result.forcing
    uplift = forcing.steady_uplift + forcing.pulse_uplift
    high = np.quantile(uplift[land], 0.85) if land.any() else 0.0
    moderate = np.quantile(uplift[land], 0.6) if land.any() else 0.0
    province = np.full(result.mesh.size, SHIELD, dtype=np.int64)
    province[uplift > moderate] = OLD_BELT
    plates = forcing.tectonics
    if plates is not None:
        active = (uplift > high) | (
            (plates.convergence > BOUNDARY_RATE_M_YR) & (plates.boundary_m < 300e3)
            & (uplift > moderate)
        )
        province[active] = ACTIVE_BELT
        province[(plates.convergence < -BOUNDARY_RATE_M_YR) & (plates.boundary_m < 120e3)] = RIFT
    if forcing.basin_depth_m is not None:
        province[forcing.basin_depth_m > 150.0] = BASIN
    if forcing.flood_basalt is not None:
        province[forcing.flood_basalt > 0.5] = BASALT
    province[result.volcanic_m > 300.0] = VOLCANIC
    return np.where(land, province, -1)


def geology_image(result: PlanetResult, rasters: PlanetRasters, light: F64) -> Image.Image:
    raster = rasters.raster
    province = geology_provinces(result)[raster.nearest.reshape(raster.shape)]
    palette = np.array([colour for _, colour in PROVINCES], dtype=np.float64)
    colour = palette[np.maximum(province, 0)]
    # Volcanoes are drawn at their sharp size, not the mesh's widened cones.
    v = result.volcanoes
    if len(v):
        from map_maker.terrain.pipeline.planet_volcanism import edifice_height

        cones = edifice_height(raster.queries, result.mesh.radius_m, v.subset(v.kind != SEAMOUNT))
        colour[(cones.reshape(raster.shape) > 300.0)] = PROVINCES[VOLCANIC][1]
    colour = np.where(rasters.land_px[..., None], colour, np.array(OCEAN, dtype=np.float64))
    rgb = _coastline(_shaded(colour, light), rasters.land_px)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def sea_floor_age_image(
    result: PlanetResult, rasters: PlanetRasters, light: F64, plates: Tectonics
) -> Image.Image:
    """Ocean crust coloured by age (red young at the ridges, violet oldest); land grey."""
    water = ~result.land
    spreading = plate_sea_floor_age_myr(
        result.mesh, water, result.coast_m, plates, result.stage_seeds[PLANET_FORCING_STAGE_ID]
    )
    age = sea_floor_age_myr(result.mesh, result.land) if spreading is None else spreading[0]
    raster = rasters.raster
    pixel_age = raster.interpolate(result.mesh, np.where(water, age, 0.0))
    knots = np.array([a for a, _ in AGE_STOPS])
    colour = np.stack(
        [np.interp(pixel_age, knots, [c[k] for _, c in AGE_STOPS]) for k in range(3)], axis=-1
    )
    colour = np.where(rasters.land_px[..., None], np.array(LAND_GREY, dtype=np.float64), colour)
    rgb = _coastline(_shaded(colour, light), rasters.land_px)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def _hue_colour(index: int, count: int) -> tuple[float, float, float]:
    # Golden-ratio hue steps keep neighbouring ids distinct.
    hue = (index * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.42, 0.9)
    return (255 * r, 255 * g, 255 * b)


def _hsv(h: F64, s: F64, v: F64) -> tuple[F64, F64, F64]:
    i = np.floor(h * 6).astype(np.int64) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return 255 * r, 255 * g, 255 * b


def _shaded(colour: F64, light: F64) -> F64:
    return colour * (0.62 + 0.38 * np.clip(light, 0, 1.4))[..., None]


def _edges(labels: NDArray[np.int64]) -> B:
    """Pixels whose right or lower neighbour has a different label (wrapping east-west)."""
    edge = labels != np.roll(labels, -1, axis=1)
    edge[:-1] |= labels[:-1] != labels[1:]
    return edge


def _coastline(rgb: F64, land_px: B) -> F64:
    coast = _edges(land_px.astype(np.int64))
    out = rgb.copy()
    out[coast] = 0.6 * out[coast] + 0.4 * np.array(COAST)
    return out
