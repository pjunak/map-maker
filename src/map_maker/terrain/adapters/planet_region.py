# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Tile cache and regional window products for planet detail (experimental M6)."""

import json
import os
from dataclasses import asdict, dataclass
from functools import cache, partial
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import numpy as np
import rasterio
from affine import Affine
from numpy.typing import NDArray
from PIL import Image
from rasterio.crs import CRS
from scipy.ndimage import (
    distance_transform_edt,
    gaussian_filter,
    label,
    map_coordinates,
    maximum,
    maximum_filter,
    minimum_position,
    sum_labels,
)

from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.adapters.map_parchment import parchment_image
from map_maker.terrain.adapters.map_topographic import topographic_image
from map_maker.terrain.adapters.planet_natural import (
    HYPSOMETRIC,
    ICE_SMOOTHING_SPACINGS,
    ICE_UNDULATION_FINEST_M,
    LAKE,
    REGION_FALLS_SLOPE,
    RIVER,
    SALT_FLAT,
    IcePixels,
    PixelClimate,
    blend_coast,
    erg_cover,
    ice_surface,
    ice_undulation,
    land_colour,
    paint_falls,
    parchment_inputs,
    ramp,
    river_coverage,
    sea_depth_colour,
    shading,
    vegetation,
)
from map_maker.terrain.adapters.planet_render import edge_coverage
from map_maker.terrain.domain.planet import REGIONAL_ALGORITHM, RegionalSettings
from map_maker.terrain.pipeline.planet_climate import potential_evapotranspiration
from map_maker.terrain.pipeline.planet_coast import coastline, level_finest_m, window_finest_m
from map_maker.terrain.pipeline.planet_detail import carve_valleys, eroded_fbm, grid_flow
from map_maker.terrain.pipeline.planet_mesh import fibonacci_nodes, mesh_from_triangles
from map_maker.terrain.pipeline.planet_patch import forward_aeqd, inverse_aeqd
from map_maker.terrain.pipeline.planet_regional import (
    LAKE_CORE_COVER,
    RegionalParent,
    RegionalResult,
)
from map_maker.terrain.pipeline.planet_tiles import ReliefWarp, TileGrid, TileSurface
from map_maker.terrain.pipeline.planet_volcanism import edifice_height, sea_floor_with_volcanoes
from map_maker.terrain.pipeline.planet_wonders import (
    WonderCover,
    wonder_cover,
    wonder_relief,
)

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

REGION_SCHEMA = "map-maker.planet-region"
REGION_VERSION = 1
# Display-only regional relief (never exported). Regional pixels are a few
# hundred metres, far below the 5 km tile mesh, so mountains need sub-tile
# ridges and valleys; slopes need far less exaggeration than the world preview.
# Hillshade sees slopes scaled to level 1 (``window_shading``), so this is level
# 1's exaggeration; in effect provinces get 1.3 and local windows 0.58.
REGION_EXAGGERATION = 2.9
REGION_MOSAIC_WAVELENGTH_M = 8e3
MEAN_RUNOFF_M_YR = 0.3  # assumed runoff: discharge per m^2 of drainage area
CHANNEL_WIDTH_PER_ROOT_Q = 4.8  # bankfull width (m) per sqrt(discharge in m^3/s)
RIVER_DISPLAY_Q_M3_S = 10_000.0  # discharge drawn at full display width
DUNE_SPACING_M = 2500.0
DUNE_HEIGHT_M = 45.0
DUNE_LENGTH_M = 30e3  # linear dunes run tens of kilometres along the wind
DUNE_SEED = 71
DUNE_STREAK_STD = 0.12  # spread of dune noise averaged along the wind (measured: 0.11-0.14)
DUNE_CREST_WIDTH = 0.45  # crest half-width, in streak spreads about a zero contour
TRAP_STEP_M = 150.0  # thickness of the lava-flow packages that form benches
ROUTE_PAD = 1.25  # rivers are routed over this multiple of a window's radius
ENTRY_WALL_M = 1e4  # beyond the rim where parent rivers enter: above any spill
POND_DEPTH_M = 10.0  # filled depressions deeper than this hold water or a playa
# A river fills a hollow on its course with sediment unless the hollow holds more
# than its catchment delivers while a lake lasts. The global mean yield, about
# 170 t/km2 a year (Milliman and Farnsworth 2011), is 0.1 mm a year of deposit
# over the catchment; lakes on rivers are young, about the Holocene's 10 kyr.
SEDIMENT_YIELD_M_YR = 1e-4
HOLLOW_AGE_YR = 1e4
PLAYA_SHARE = 0.25  # a playa bed spans this share of its basin's depth
PLAYA_MIN_M = 20.0
PLAYA_MAX_M = 400.0
POND_LAKE_ARIDITY = 0.65  # ponds hold standing water above this P/PET
LAKE_SHORE_M = 2.0  # lake pixels lie at most this far above the lake level
# Pixel slopes at ~0.5 km are ~4x those of the same terrain on ~7 km world pixels.
REGION_SLOPE_SCALE = 3.5
# Finer levels resolve steeper slopes: over shared Aethelara ground the median
# slope grew 1.9x from region to province and 2.1x from province to local (mean
# 2.2x and 2.7x), but only 1.1x when a window of the same level had pixels half
# as wide. Colour thresholds were set on level-1 windows, so colour and hillshade
# see every window's slopes scaled to that 5 km mesh, as spacing^0.5. The same
# ground then keeps its rock, vegetation and shading at every level, and finer
# levels add forms.
REGION_SLOPE_SPACING_M = 5000.0
REGION_SLOPE_EXPONENT = 0.5
REGION_DETAIL_SEED = 17
REGION_DETAIL_WAVELENGTH_M = 30e3  # at level 1 (5 km mesh); scales with spacing
REGION_DETAIL_SPACING_M = 5000.0
REGION_DETAIL_EXPONENT = 1.2  # how fast unresolved relief shrinks with finer meshes
DETAIL_MEAN_SAMPLES = 20_000
REGION_DETAIL_FLOOR_M = 70.0
REGION_DETAIL_SHARE = 0.6  # detail amplitude per metre of tile height
REGION_CARVE_ERODIBILITY = 0.4  # K * dt for valley carving (m^0)
REGION_CARVE_STEPS = 4


class TileStore:
    """Tiles for one parent and one set of regional settings, written atomically."""

    def __init__(
        self, root: Path, parent_sha256: str, settings: RegionalSettings, level: int = 1
    ) -> None:
        key = sha256(
            canonical_json(
                {
                    "parent": parent_sha256,
                    "algorithm": REGIONAL_ALGORITHM,
                    "level": level,
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


@dataclass(frozen=True)
class RegionWindow:
    centre: tuple[float, float]
    radius_m: float
    pixels: int
    elevation_m: F64  # (pixels, pixels); NaN outside the window circle
    land: B
    land_cover: F64  # share of each pixel on land, for anti-aliased coasts
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
    playa: B  # dry closed basins of the regional relief (ephemeral lakes)
    detail_spacing_m: float = 5000.0  # node spacing of the detail level shown
    seed: int = 0  # planet master seed: display detail belongs to the world
    cover: WonderCover | None = None  # lava, ash and glow of the wonders
    ice_surface_m: F64 | None = None  # ice-sheet surface (ADR-0093); NaN off the ice
    ice_balance_m: F64 | None = None  # its surface mass balance (m of ice a year)

    @property
    def pixel_m(self) -> float:
        return 2 * self.radius_m / self.pixels


def window_points(
    lon: float, lat: float, radius_m: float, pixels: int, planet_m: float
) -> tuple[F64, B]:
    centres = (np.arange(pixels) + 0.5) / pixels * 2 * radius_m - radius_m
    gx, gy = np.meshgrid(centres, -centres)
    return inverse_aeqd(gx.ravel(), gy.ravel(), lon, lat, planet_m), np.hypot(gx, gy) <= radius_m


def compose_window(
    parent: RegionalParent,
    grid: TileGrid,
    tiles: dict[int, TileSurface],
    centre: tuple[float, float],
    radius_km: float,
    pixels: int,
    river_km2: float,
    *,
    relief: ReliefWarp,
    spacing_m: float = 5000.0,
    pad: float = ROUTE_PAD,
) -> RegionWindow:
    """A regional window, composed over a padded square and cropped to its circle.

    River routing has to start somewhere, and where it starts depends on the
    window. Routing over ``pad`` times the radius keeps that start outside the
    visible map: rivers inside follow the tile surface, which does not depend
    on the window, so overlapping windows draw the same rivers. The tiles'
    blend is sampled where ``relief`` moves each pixel (``ReliefWarp.for_window``).
    """
    extra = round(pixels * (pad - 1) / 2)
    size = pixels + 2 * extra
    padded = _compose(
        parent, grid, tiles, centre, radius_km * 1e3 * size / pixels, size, river_km2,
        spacing_m, relief,
    )
    return crop_window(padded, extra, pixels)


def crop_window(window: RegionWindow, extra: int, pixels: int) -> RegionWindow:
    """The central ``pixels`` square of a padded window, masked to its circle."""
    if extra == 0:
        return window
    rows = slice(extra, extra + pixels)
    radius_m = window.pixel_m * pixels / 2
    centres = (np.arange(pixels) + 0.5) * window.pixel_m - radius_m
    gx, gy = np.meshgrid(centres, -centres)
    circle = np.hypot(gx, gy) <= radius_m

    def cut[T: np.generic](values: NDArray[T]) -> NDArray[T]:
        return values[rows, rows]

    climate = window.climate
    if climate is not None:
        climate = PixelClimate(
            cut(climate.temperature_c), cut(climate.warm_season_c),
            cut(climate.precipitation_mm), cut(climate.pet_mm),
            None if climate.growing_mm is None else cut(climate.growing_mm),
        )
    size = window.pixels
    return RegionWindow(
        window.centre,
        radius_m,
        pixels,
        np.where(circle, cut(window.elevation_m), np.nan),
        cut(window.land) & circle,
        cut(window.land_cover),
        climate,
        np.where(circle, cut(window.rivers), 0.0),
        window.points.reshape(size, size, 3)[rows, rows].reshape(-1, 3),
        window.tiles,
        window.planet_m,
        window.lapse_c_per_km,
        cut(window.volcanic),
        cut(window.lakes) & circle,
        cut(window.salt) & circle,
        cut(window.basalt),
        None if window.wind is None else window.wind[rows, rows],
        cut(window.playa) & circle,
        window.detail_spacing_m,
        window.seed,
        None if window.cover is None else window.cover.crop(rows),
        (
            None
            if window.ice_surface_m is None
            else np.where(circle, cut(window.ice_surface_m), np.nan)
        ),
        None if window.ice_balance_m is None else cut(window.ice_balance_m),
    )


def _compose(
    parent: RegionalParent,
    grid: TileGrid,
    tiles: dict[int, TileSurface],
    centre: tuple[float, float],
    radius_m: float,
    pixels: int,
    river_km2: float,
    spacing_m: float,
    relief: ReliefWarp,
) -> RegionWindow:
    planet_m = parent.mesh.radius_m
    points, inside = window_points(*centre, radius_m, pixels, planet_m)
    from map_maker.terrain.pipeline.planet_tiles import blend

    surfaces = tiles
    finest = window_finest_m(spacing_m, 2 * radius_m / pixels)
    coast = coastline(parent.world)
    drawn = coast.contains(points, finest, parent.settings.seed).reshape(pixels, pixels)
    land = drawn & inside
    floor = parent.sea_floor_m
    if floor is None:
        floor = np.where(parent.land, 0.0, -2000.0)
    sea = parent.sample(points, floor).reshape(pixels, pixels)
    blended = np.zeros(pixels * pixels)
    blended[inside.ravel()] = blend(grid, surfaces, relief(points[inside.ravel()], planet_m))
    elevation = blended = blended.reshape(pixels, pixels)
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
        # Lava and ash cover summits. An island's cone rises from the sea floor,
        # so its summit share is its height above the sea, not above that floor.
        above = np.where(islands, sea, sharp)
        volcanic = np.where(land, np.clip((above - 300.0) / 2200.0, 0.0, 1.0) ** 2, 0.0)
    else:
        islands = np.zeros((pixels, pixels), dtype=bool)
    wonders = parent.wonders
    floors = parent.crater_floor_m
    if floors is not None and np.any(floors != 0):
        # Tiles carry the ground without wonders (ADR-0097): level crater floors
        # as the planet did before drawing the craters on top.
        elevation = np.where(
            land, elevation + parent.sample(points, floors).reshape(pixels, pixels), elevation
        )
    if wonders is not None and len(wonders):
        elevation = np.where(
            land,
            elevation + wonder_relief(points, planet_m, wonders, finest).reshape(pixels, pixels),
            elevation,
        )
    elevation = np.where(land, np.maximum(elevation, 1.0), np.minimum(sea, -5.0))
    elevation = np.where(islands, sea, elevation)
    elevation = np.where(inside, elevation, np.nan)
    climate = regional_climate(parent, points, elevation, land)
    pixel_m = 2 * radius_m / pixels

    def on_land(row: F64, column: F64) -> B:
        sub = inverse_aeqd(column * pixel_m - radius_m, radius_m - row * pixel_m, *centre, planet_m)
        own = islands[np.floor(row).astype(np.intp), np.floor(column).astype(np.intp)]
        return own | coast.contains(sub, finest, parent.settings.seed)

    # The share of land in each pixel, so coasts are drawn anti-aliased.
    land_cover = edge_coverage(drawn | islands, on_land)
    ice_surface, ice_balance = window_ice(parent, points, elevation, land, pixel_m, spacing_m)
    flow = window_flow(parent, centre, points, elevation, land, inside, pixel_m, river_km2)
    # Lakes fill the regional relief up to the parent lake level, so shores
    # follow the fine terrain (and a crater's sharp trough) instead of the
    # coarse parent mesh.
    cover, level, closed = parent.lakes_at(points, level_finest_m(spacing_m))
    lakes = lake_water(
        flow.z, land & inside, flow.filled,
        cover.reshape(pixels, pixels) > LAKE_CORE_COVER, level.reshape(pixels, pixels),
    )
    salt = lakes & closed.reshape(pixels, pixels)
    # Hollows of the tiles' blend are filled plains; only the relief drawn on
    # top of the tiles holds ponds (``drawn_hollows``).
    tiles_z = np.where(land, np.maximum(blended, 1.0), flow.z)
    flow, basin_depth = lake_flow(flow, lakes, salt, level.reshape(pixels, pixels), tiles_z)
    # Deep hollows (crater troughs, chasm floors, calderas) hold water or a
    # playa, and rivers end there; rivers cross the others on a filled flat.
    ponds, spills = window_ponds(flow, basin_depth, land & inside & ~lakes, climate)
    depth = np.where(ponds, basin_depth, 0.0)
    coverage = window_rivers(flow, lakes | ponds, river_km2)
    # Closed ponds hold lakes where it is wet enough and playas where it is dry.
    dry = np.zeros_like(ponds)
    if climate is not None:
        dry = (
            climate.precipitation_mm / np.maximum(climate.pet_mm, 1.0) < POND_LAKE_ARIDITY
        )
    # A wet or overflowing basin fills to its spill level; a dry closed one
    # keeps only an ephemeral lake bed in its lowest part, flat and bright (a
    # playa or salar).
    closed = ponds & ~spills
    playa = closed & dry & playa_beds(closed, depth)
    lakes = lakes | (ponds & (spills | ~dry))
    salt = salt | (closed & ~dry)
    cover = (
        None
        if wonders is None
        or (found := wonder_cover(points, planet_m, wonders, finest)) is None
        else found.reshape((pixels, pixels))
    )
    if cover is not None:
        # An erupting vent holds molten rock, never water.
        molten = cover.glow > 0.2
        lakes, salt, playa = lakes & ~molten, salt & ~molten, playa & ~molten
    if ice_surface is not None:
        # Ice sheets hold no open water; their meltwater runs beneath them.
        iced = ice_surface > elevation
        lakes, salt, playa = lakes & ~iced, salt & ~iced, playa & ~iced
        coverage = np.where(iced, 0.0, coverage)
    coverage = np.where(land & ~lakes, coverage, 0.0)
    return RegionWindow(
        centre,
        radius_m,
        pixels,
        elevation,
        land,
        land_cover,
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
        playa,
        spacing_m,
        parent.settings.seed,
        cover,
        ice_surface,
        ice_balance,
    )


def window_ice(
    parent: RegionalParent, points: F64, elevation: F64, land: B, pixel_m: float, spacing_m: float
) -> tuple[F64 | None, F64 | None]:
    """Ice-sheet surface (NaN off the ice) and mass balance of a window, or Nones.

    The planet's ice rests on the window's bed smoothed over the planet's mesh
    spacing: thick ice does not follow small bed relief. Its margin is refined
    down to the level's detail, like lake outlines.
    """
    found = parent.ice_at(points, level_finest_m(spacing_m))
    if found is None:
        return None, None
    shape = elevation.shape
    margin, thickness, balance = (v.reshape(shape) for v in found)
    if not np.any(land & (margin > 0)):
        return None, None
    mesh = parent.mesh if parent.planet_mesh is None else parent.planet_mesh
    sigma = ICE_SMOOTHING_SPACINGS * mesh.spacing_m / pixel_m
    bed = np.where(land, np.nan_to_num(elevation, nan=0.0), 0.0)
    waves = ice_undulation(
        points, mesh.radius_m, max(2 * pixel_m, ICE_UNDULATION_FINEST_M)
    ).reshape(shape)
    on_ice, surface = ice_surface(
        margin, thickness, bed, partial(_wide_blur, sigma=sigma), waves
    )
    return np.where(land & on_ice, surface, np.nan), balance


def _wide_blur(values: F64, sigma: float) -> F64:
    """Gaussian blur that stays cheap for sigmas of hundreds of pixels."""
    step = max(1, int(sigma / 4))
    if step == 1:
        return gaussian_filter(values, sigma, mode="nearest")
    coarse = gaussian_filter(values[::step, ::step], sigma / step, mode="nearest")
    rows, columns = values.shape
    # Coarse sample k lies on fine pixel k * step.
    r = np.clip(np.arange(rows) / step, 0, (rows - 1) // step)
    c = np.clip(np.arange(columns) / step, 0, (columns - 1) // step)
    return map_coordinates(coarse, np.meshgrid(r, c, indexing="ij"), order=1, mode="nearest")


def window_ponds(
    flow: WindowFlow, depth: F64, ground: B, climate: PixelClimate | None
) -> tuple[B, B]:
    """Pixels of closed hollows that hold water or a playa, and those that overflow.

    ``depth`` is how far ``ground`` lies below its hollow's spill level. Each
    hollow gathers the runoff and sediment of its catchment, the drainage area
    where it spills. It overflows when that water exceeds what its area at the
    spill level evaporates (open-water PET less precipitation), so its river
    runs on. An overflowing hollow that the river's sediment fills within
    HOLLOW_AGE_YR is a plain the river crosses, not a lake, such as a shallow
    crater on a big river's course. Pixels deeper than POND_DEPTH_M in the
    remaining hollows hold water or a playa: crater troughs, chasm floors and
    calderas, deep for their catchments. ``depth`` measures only hollows drawn
    on the tiles (``drawn_hollows``).
    """
    found = cast(tuple[NDArray[np.int32], int], label(ground & (depth > 0)))
    labels, count = np.asarray(found[0], dtype=np.int64), int(found[1])
    ponds = ground & (depth > POND_DEPTH_M)
    if not count:
        return ponds, np.zeros_like(ponds)
    ids = np.arange(1, count + 1)
    cell_m2 = flow.pixel_m**2
    volume = np.asarray(sum_labels(depth, labels, ids), dtype=np.float64) * cell_m2
    catchment = np.asarray(
        maximum(flow.area_m2.reshape(labels.shape), labels, ids), dtype=np.float64
    )
    evaporation = np.zeros(count)
    if climate is not None:
        net_m = np.maximum(climate.pet_mm - climate.precipitation_mm, 0.0) / 1000
        evaporation = np.asarray(sum_labels(net_m, labels, ids), dtype=np.float64) * cell_m2
    spills = np.zeros(count + 1, dtype=bool)
    spills[1:] = catchment * MEAN_RUNOFF_M_YR > evaporation
    alluvial = np.zeros(count + 1, dtype=bool)
    alluvial[1:] = spills[1:] & (volume < catchment * SEDIMENT_YIELD_M_YR * HOLLOW_AGE_YR)
    ponds = ponds & ~alluvial[labels]
    return ponds, ponds & spills[labels]


def playa_beds(ponds: B, depth: F64) -> B:
    """The lowest part of each closed basin, where an ephemeral lake bed lies."""
    found = cast(tuple[NDArray[np.int32], int], label(ponds))
    labels, count = np.asarray(found[0], dtype=np.int64), int(found[1])
    if not count:
        return np.zeros_like(ponds)
    deepest = np.zeros(count + 1)
    deepest[1:] = np.asarray(maximum(depth, labels, np.arange(1, count + 1)), dtype=np.float64)
    bed = np.clip(PLAYA_SHARE * deepest, PLAYA_MIN_M, PLAYA_MAX_M)
    return ponds & (depth >= deepest[labels] - bed[labels])


@dataclass(frozen=True)
class WindowFlow:
    """Drainage routed on a window's blended relief."""

    z: F64  # routed relief: elevation inside the window, 0 outside
    outlet: B  # sea and the area outside the window
    receiver: NDArray[np.int64]  # flat indices, -1 at outlets
    area_m2: F64  # drainage area, with the water entering from beyond the window
    filled: F64  # relief with closed depressions filled to their spill level
    links: tuple[tuple[int, int], ...]  # splitting rivers: (split pixel, branch pixel)
    inflow_m2: F64  # drainage area entering at each pixel from beyond the window
    pixel_m: float

    @classmethod
    def route(
        cls,
        z: F64,
        outlet: B,
        pixel_m: float,
        inflow_m2: F64,
        links: tuple[tuple[int, int], ...] = (),
    ) -> WindowFlow:
        receiver, area, filled = grid_flow(z, outlet, pixel_m, inflow_m2)
        return cls(z, outlet, receiver, area, filled, links, inflow_m2, pixel_m)

    def rerouted(self, z: F64, outlet: B) -> WindowFlow:
        """The same water routed over other relief and outlets."""
        return WindowFlow.route(z, outlet, self.pixel_m, self.inflow_m2, self.links)


def window_flow(
    parent: RegionalParent,
    centre: tuple[float, float],
    points: F64,
    elevation: F64,
    land: B,
    inside: B,
    pixel_m: float,
    river_km2: float,
) -> WindowFlow:
    """One drainage network over the whole window, with no seams between tiles.

    Parent rivers that cross into the window bring their upstream area in near
    where they cross (``river_crossings``, ``entry_pixels``). Beyond the window
    circle the ground is a wall at the highest neighbouring height inside, so a
    rim pixel drains along the window's relief: water leaves only where a valley
    reaches the rim, and a river entering on the rim flows in. Ground at the sea
    floor or at zero beyond the rim drained every rim pixel straight out,
    inherited rivers included. Where a river of ``river_km2`` or more flows in,
    no water leaves (``entry_walls``).
    """
    pixels = elevation.shape[0]
    ground = np.where(inside, np.nan_to_num(elevation, nan=0.0), -np.inf)
    wall = np.asarray(maximum_filter(ground, size=3), dtype=np.float64)
    z = np.where(inside, ground, np.where(np.isfinite(wall), wall, 0.0))
    outlet = ~inside | ~land
    inflow = np.zeros(pixels * pixels)
    rows, columns, area = river_crossings(parent, centre, pixel_m * pixels / 2, pixel_m)
    if len(area):
        spread = max(parent.mesh.spacing_m / pixel_m, 2.0)
        big = area >= river_km2 * 1e6
        out_rows, out_columns, out_area = river_crossings(
            parent, centre, pixel_m * pixels / 2, pixel_m, outward=True
        )
        leave = out_area >= river_km2 * 1e6
        walls = entry_walls(
            (rows[big], columns[big]), (out_rows[leave], out_columns[leave]), inside, spread
        )
        z = np.where(walls, float(ground.max()) + ENTRY_WALL_M, z)
        dry = WindowFlow.route(z, outlet, pixel_m, np.zeros((pixels, pixels)))
        reach = downstream_steps(dry.receiver).reshape(pixels, pixels)
        target = entry_pixels(rows, columns, reach, inside & land, spread)
        entered = target >= 0
        np.add.at(inflow, target[entered], area[entered])
    inflow = inflow.reshape(pixels, pixels)
    # A splitting river's branch starts with its share of the river's water.
    links: list[tuple[int, int]] = []
    forks = None if parent.wonders is None else parent.wonders.forks
    if forks is not None and len(forks):
        for a, b, carried in zip(forks.split_xyz, forks.branch_xyz, forks.area_m2, strict=True):
            ends = [int(np.argmax(points @ end)) for end in (a, b)]
            if all(points[k] @ end > np.cos(pixel_m / parent.mesh.radius_m)
                   for k, end in zip(ends, (a, b), strict=True)):
                inflow.ravel()[ends[1]] += carried
                links.append((ends[0], ends[1]))
    return WindowFlow.route(z, outlet, pixel_m, inflow, tuple(links))


def river_crossings(
    parent: RegionalParent,
    centre: tuple[float, float],
    radius_m: float,
    pixel_m: float,
    *,
    outward: bool = False,
) -> tuple[F64, F64, F64]:
    """Where parent rivers cross into a window's routing circle, and their area.

    Every parent river step that crosses into the circle of ``radius_m`` about
    ``centre`` gives its crossing (pixel row and column, fractional) and its
    upstream area, so each inherited river enters once and nothing enters where
    rivers leave. With ``outward``, the steps that cross out of the circle.
    """
    mesh = parent.mesh
    planet_m = mesh.radius_m
    middle = inverse_aeqd(np.zeros(1), np.zeros(1), *centre, planet_m)[0]
    distance = planet_m * np.arccos(np.clip(mesh.xyz @ middle, -1, 1))
    step_m = float(mesh.length_m.max())
    nodes = np.flatnonzero(
        parent.land
        & (parent.receiver >= 0)
        & (outward | (distance > radius_m))
        & (distance < radius_m + step_m)
    )
    start = forward_aeqd(mesh.xyz[nodes], *centre, planet_m)
    step = forward_aeqd(mesh.xyz[parent.receiver[nodes]], *centre, planet_m) - start
    # Where each step meets the circle, |start + t step| = radius_m: the first
    # root going in, the second going out.
    a = np.einsum("ij,ij->i", step, step)
    b = np.einsum("ij,ij->i", start, step)
    c = np.einsum("ij,ij->i", start, start) - radius_m**2
    root = b**2 - a * c
    sign = 1.0 if outward else -1.0
    t = (-b + sign * np.sqrt(np.maximum(root, 0.0))) / np.maximum(a, 1e-9)
    crosses = (root >= 0) & (t >= 0) & (t <= 1)
    crossing = start[crosses] + t[crosses, None] * step[crosses]
    row = (radius_m - crossing[:, 1]) / pixel_m
    column = (crossing[:, 0] + radius_m) / pixel_m
    return row, column, parent.area_m2[nodes[crosses]]


def entry_walls(
    entries: tuple[F64, F64], exits: tuple[F64, F64], inside: B, spread_px: float
) -> B:
    """Ground beyond the rim near where parent rivers cross in, not where they leave.

    ``entries`` and ``exits`` are crossings (pixel rows and columns). A parent
    river flows in at an entry, so beyond the rim lies its valley upstream,
    rising away from the window. Water does not leave there: a hollow that a
    river enters fills and spills onward, not back out past the river's entry.
    Tile blending can leave the window's relief a few metres off the parent's
    within one parent spacing (``spread_px``) of where it puts the river; a rim
    draining there sent a province window's 160,000 km2 river straight back
    out. The rim stays open nearer an exit than an entry, so a river crossing a
    window smaller than the parent's spacing still leaves where it should.
    """
    entering = rim_distance(entries, inside.shape)
    if entering is None:
        return np.zeros_like(inside)
    leaving = rim_distance(exits, inside.shape)
    nearer = np.ones_like(inside) if leaving is None else entering < leaving
    return ~inside & (entering <= spread_px) & nearer


def rim_distance(crossings: tuple[F64, F64], shape: tuple[int, ...]) -> F64 | None:
    """Distance in pixels from the nearest of ``crossings`` (None without any)."""
    rows, columns = crossings
    if not len(rows):
        return None
    marks = np.ones(shape, dtype=bool)
    marks[
        np.clip(np.floor(rows).astype(np.intp), 0, shape[0] - 1),
        np.clip(np.floor(columns).astype(np.intp), 0, shape[1] - 1),
    ] = False
    return np.asarray(distance_transform_edt(marks), dtype=np.float64)


def downstream_steps(receiver: NDArray[np.int64]) -> NDArray[np.int64]:
    """How many steps water takes from each cell to an outlet (0 at outlets)."""
    jump = np.where(receiver >= 0, receiver, np.arange(len(receiver)))
    steps = (receiver >= 0).astype(np.int64)
    # Pointer doubling: each pass doubles the stretch of path each cell has counted.
    while not np.array_equal(jump[jump], jump):
        steps = steps + steps[jump]
        jump = jump[jump]
    return steps


def entry_pixels(
    rows: F64, columns: F64, reach: NDArray[np.int64], ground: B, spread_px: float
) -> NDArray[np.intp]:
    """Flat pixels where inherited rivers enter a window (-1: they reach its sea).

    A parent places its rivers only to within its spacing (``spread_px``), and
    the window's finer relief can put the valley a little to one side. A river
    enters at its crossing if the window's water runs inward from there for at
    least ``spread_px`` steps (``reach``). Otherwise it enters at the nearest
    ``ground`` pixel within ``spread_px`` where the water does, or failing that
    where it runs furthest, so it joins the window's own valley instead of
    leaving down a side valley at once. With no ground that near, the river has
    reached the sea.
    """
    size = ground.shape[0]
    radius = int(np.ceil(spread_px))
    targets = np.full(len(rows), -1, dtype=np.intp)
    for k, (row, column) in enumerate(zip(rows, columns, strict=True)):
        r0, c0 = int(np.floor(row)), int(np.floor(column))
        top, left = max(r0 - radius, 0), max(c0 - radius, 0)
        bottom, right = min(r0 + radius + 1, size), min(c0 + radius + 1, size)
        if top >= bottom or left >= right:
            continue
        r, c = np.mgrid[top:bottom, left:right]
        gap = (r + 0.5 - row) ** 2 + (c + 0.5 - column) ** 2
        near = ground[top:bottom, left:right] & (gap <= spread_px**2)
        if not near.any():
            continue
        runs = reach[top:bottom, left:right]
        inward = near & (runs >= spread_px)
        best = (
            np.argmin(np.where(inward, gap, np.inf))
            if inward.any()
            else np.argmax(np.where(near, runs, -1))
        )
        targets[k] = int(r.ravel()[best]) * size + int(c.ravel()[best])
    return targets


def lake_water(z: F64, land: B, filled: F64, core: B, level: F64) -> B:
    """Parent lakes as water standing on the regional relief at the lake level.

    Water covers ground up to ``level`` (plus LAKE_SHORE_M) that is connected to
    a lake's ``core`` (where the tiles hold the parent lake) and lies in a basin
    that spills no lower than the level, so it does not run out down the outlet
    valley. Shores are contours of the fine relief, not of the parent's lake
    cover, which is linear, so straight, inside each parent triangle.
    """
    wet = land & (z <= level + LAKE_SHORE_M) & (filled >= level - LAKE_SHORE_M)
    found = cast(tuple[NDArray[np.int32], int], label(wet))
    labels, count = np.asarray(found[0], dtype=np.int64), int(found[1])
    keep = np.zeros(count + 1, dtype=bool)
    keep[labels[wet & core]] = True
    keep[0] = False
    return keep[labels]


def lake_flow(
    flow: WindowFlow, lakes: B, closed: B, level: F64, tiles: F64 | None = None
) -> tuple[WindowFlow, F64]:
    """Drainage with the window's lakes, and the depth of its closed depressions.

    Routing fills each depression up to wherever the window lets it spill. For
    a lake's basin that can lie above the lake's level, so depressions are
    measured with every lake as a sink: the ground between a lake and its
    basin's spill is no pond. Depressions of the tiles' blend count as filled
    (``drawn_hollows``; ``tiles`` is the routed relief without what the window
    draws on the tiles, None: every depression counts). Closed lakes are where
    their basin's water ends. Rivers route through open lakes, so outflows keep
    their upstream area, over an outflow lowered to the lake's level
    (``lake_outflows``).
    """
    sinks = flow.outlet | lakes
    depth = drawn_hollows(flow.z, sinks, flow.pixel_m, tiles)
    if not lakes.any():
        return flow, depth
    inward, _, _ = grid_flow(flow.z, sinks, flow.pixel_m, np.zeros_like(flow.z))
    routed = lake_outflows(flow, inward, lakes & ~closed, level)
    return flow.rerouted(routed, flow.outlet | (lakes & closed)), depth


def drawn_hollows(z: F64, sinks: B, pixel_m: float, tiles: F64 | None) -> F64:
    """How far ground lies below where its hollow spills, in hollows drawn on the tiles.

    Every tile fills its depressions as it erodes, so a hollow in the tiles'
    blend is one that blending closed: overlapping tiles drain a plain through
    valleys a few kilometres apart, and their weighted mean half fills each
    valley with the other tile's flank, so the blend's sill stands above both
    tiles' plains. Like the tiles' own hollows, sediment fills these, and rivers
    cross them on the fill. Only relief the window draws on top of the tiles
    (craters, chasm floors, calderas, volcanoes damming a valley) holds hollows:
    their depth is measured over the tiles' blend with its hollows filled.
    ``tiles`` is ``z`` without that relief (None: ``z`` is all drawn).
    """
    no_inflow = np.zeros_like(z)
    if tiles is not None:
        z = z + grid_flow(tiles, sinks, pixel_m, no_inflow)[2] - tiles
    return grid_flow(z, sinks, pixel_m, no_inflow)[2] - z


def lake_outflows(flow: WindowFlow, inward: NDArray[np.int64], lakes: B, level: F64) -> F64:
    """Routed relief with each lake's outflow lowered to the lake's level.

    A lake's routed path out, from its last-filled pixel, may cross the filled
    basin to a pour point above the lake's level, where the tiles do not hold
    the parent's outflow. Drainage would then cross that flat towards the pour
    point instead of entering the lake. The outflow is lowered to the level
    along the basin's floor from the lake up to the pour point (``inward``,
    receivers with every lake a sink, leads down that floor into the lake),
    then along the routed path until the filled relief is down to the lake's
    shore. The basin then drains into the lake and the lake out over the pour
    point. Only routing uses this relief.
    """
    found = cast(tuple[NDArray[np.int32], int], label(lakes))
    labels, count = np.asarray(found[0], dtype=np.int64), int(found[1])
    if not count:
        return flow.z
    relief, filled, outlet = flow.z.ravel(), flow.filled.ravel(), flow.outlet.ravel()
    z, ids, columns = relief.copy(), labels.ravel(), flow.z.shape[1]
    starts = minimum_position(flow.filled, labels, np.arange(1, count + 1))
    for lake, (row, column) in enumerate(cast(list[tuple[int, int]], starts), start=1):
        start = row * columns + column
        top = float(level.ravel()[start])
        path: list[int] = []
        node = int(flow.receiver[start])
        while node >= 0 and not outlet[node] and filled[node] > top + LAKE_SHORE_M:
            path.append(node)
            node = int(flow.receiver[node])
        if not path:
            continue
        # The pour point is where the path leaves the filled basin.
        crest = int(np.argmin(filled[path] > relief[path]))
        floor: list[int] = []
        node = path[crest - 1] if crest else -1
        while node >= 0 and ids[node] != lake:
            floor.append(node)
            node = int(inward[node])
        # Where the floor does not lead back to this lake, keep the routed path.
        channel = path[crest:] + (floor if node >= 0 else path[:crest])
        z[channel] = np.minimum(z[channel], top)
    return z.reshape(flow.z.shape)


def window_rivers(flow: WindowFlow, water: B, river_km2: float) -> F64:
    """River coverage on the window's drainage; rivers end in ``water``."""
    z, receiver, area, pixel_m = flow.z, flow.receiver, flow.area_m2, flow.pixel_m
    pixels = z.shape[0]
    flat = np.arange(pixels * pixels)
    x = (flat % pixels + 0.5).astype(np.float64)
    y = (flat // pixels + 0.5).astype(np.float64)
    stop = (flow.outlet | water).ravel()
    major = ~stop & (receiver >= 0) & (area >= river_km2 * 1e6)
    # Hydraulic geometry: channel width ~4.8 sqrt(Q) m (Leopold and Maddock
    # 1953), meander wavelength ~11 widths; rivers meander on gentle ground.
    discharge = area * MEAN_RUNOFF_M_YR / 3.156e7
    channel_px = CHANNEL_WIDTH_PER_ROOT_Q * np.sqrt(discharge) / pixel_m
    wavelength = 11 * channel_px
    # A river is drawn at least as wide as its channel. Narrower ones get a
    # visible width tapered by discharge against a fixed reference, not against
    # the largest river in the window, so other rivers do not change it.
    shown = (0.4 + 1.6 * np.sqrt(np.clip(discharge / RIVER_DISPLAY_Q_M3_S, 0, 1))) * pixels / 1100
    width_px = np.maximum(channel_px, shown)
    target = np.maximum(receiver, 0)
    drop = z.ravel() - z.ravel()[target]
    run = np.hypot(flat % pixels - target % pixels, flat // pixels - target // pixels) * pixel_m
    gentle = 1 - np.clip((drop / np.maximum(run, 1.0) - 0.0005) / 0.0025, 0, 1)
    return river_coverage(
        x, y, receiver, area, major, stop, (pixels, pixels), width_px,
        meander_px=np.where(gentle > 0.3, wavelength * gentle, 0.0), links=flow.links,
    )


def regional_climate(
    parent: RegionalParent, points: F64, elevation: F64, land: B
) -> PixelClimate | None:
    """Parent climate at each pixel, lapse-corrected to the fine relief."""
    shape = elevation.shape
    z = np.where(land, np.nan_to_num(elevation, nan=0.0), 0.0).ravel()
    temperatures = parent.temperatures_at(points, z)
    if temperatures is None or parent.precipitation_mm is None:
        return None
    temperature, warm = temperatures
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


@cache
def _detail_means(seed: int, frequency: float) -> tuple[float, float]:
    """Mean display detail over the whole sphere, without and with ridging."""
    points = fibonacci_nodes(DETAIL_MEAN_SAMPLES, seed=0, jitter=0.0)
    plain = eroded_fbm(points, np.zeros(len(points)), seed, 5, frequency, 0.5, 0.1)
    ridged = eroded_fbm(points, np.ones(len(points)), seed, 5, frequency, 0.5, 0.1)
    return float(plain.mean()), float(ridged.mean())


def detail_offset(seed: int, frequency: float, ridged: F64) -> F64:
    """The world-wide mean of display detail, so it is zero-mean everywhere."""
    plain, full = _detail_means(seed, frequency)
    return plain + (full - plain) * ridged


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
    # Detail stands in for the relief the level's mesh cannot resolve: its
    # wavelength follows the mesh spacing and its height shrinks with it. It is
    # anchored to the world (planet seed, world positions, a fixed zero), so
    # overlapping windows draw the same hills.
    level = window.detail_spacing_m / REGION_DETAIL_SPACING_M
    wavelength = REGION_DETAIL_WAVELENGTH_M * level
    seed = window.seed + REGION_DETAIL_SEED
    detail = eroded_fbm(
        window.points, ridged, seed, 5, window.planet_m / wavelength, 0.5, 0.1
    ).reshape(z.shape)
    detail -= detail_offset(seed, window.planet_m / wavelength, ridged).reshape(z.shape)
    amplitude = (
        (REGION_DETAIL_FLOOR_M + REGION_DETAIL_SHARE * base)
        * ruggedness
        * level**REGION_DETAIL_EXPONENT
    )
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
                window.points, window.planet_m, climate,
                tile_slope * slope_factor(window.detail_spacing_m),
                window_position(relief, window.pixel_m, inside), REGION_SLOPE_SCALE,
            ),
            0.0,
        )
        if erg.max() > 0.05:
            crest = dune_crests(
                window.points, window.planet_m, gaussian_filter(window.wind, (6, 6, 0)),
                window.pixel_m, erg > 0.05,
            )
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
    if window.ice_surface_m is not None:
        # Ice fills the relief up to its surface; nunataks rise through it.
        relief = np.fmax(relief, window.ice_surface_m)
    return np.where(land, np.maximum(relief, 1.0), z)


def dune_crests(points: F64, planet_m: float, wind: F64, pixel_m: float, where: B) -> F64:
    """Linear (seif) dune crests (0..1) that run along the resultant ``wind``.

    Noise at the dune spacing, anchored to the world, is averaged along the wind
    over DUNE_LENGTH_M (line integral convolution, Cabral and Leedom 1993), and
    crests stand along the zero contours of the result. They run with the wind
    wherever it turns, join in Y-junctions and leave flat corridors between them,
    and a place has the same dunes in every window. A phase measured across the
    wind from the window's corner had drawn rings and whorls wherever the wind or
    the spacing varied. Dunes fade out on maps too coarse to resolve their
    spacing. Only ``where`` pixels are computed.
    """
    out = np.zeros(where.shape)
    resolved = float(_smooth_step(np.array(DUNE_SPACING_M / pixel_m), 2.0, 4.0))
    if not where.any() or resolved <= 0:
        return out
    noise = eroded_fbm(
        points, np.zeros(len(points)), DUNE_SEED, 2, planet_m / DUNE_SPACING_M, 0.5, 0.0
    ).reshape(where.shape)
    rows, columns = (v.astype(np.float64) for v in np.nonzero(where))
    east = wind[..., 0][where]
    north = wind[..., 1][where]
    speed = np.maximum(np.hypot(east, north), 1e-9)
    half = 0.5 * DUNE_LENGTH_M / pixel_m
    step = max(1.0, half / 16)
    # East is +column, north is -row.
    dc, dr = east / speed * step, -north / speed * step
    count = max(1, int(half / step))
    total, weights = np.zeros(len(rows)), 0.0
    for k in range(-count, count + 1):
        weight = np.cos(0.5 * np.pi * k / (count + 1)) ** 2
        total += weight * map_coordinates(
            noise, (rows + k * dr, columns + k * dc), order=1, mode="nearest"
        )
        weights += weight
    streak = total / weights / DUNE_STREAK_STD
    out[where] = resolved * (1 - _smooth_step(np.abs(streak), 0.0, DUNE_CREST_WIDTH)) ** 2
    return out


def window_ice_cover(window: RegionWindow, relief: F64) -> F64:
    """Anti-aliased ice cover (0..1) of a window's display relief."""
    if window.ice_surface_m is None:
        return np.zeros(relief.shape)
    covered = window.land & (relief <= np.nan_to_num(window.ice_surface_m, nan=-1e9) + 0.01)
    return gaussian_filter(covered.astype(np.float64), 0.6)


def _smooth_step(x: F64, a: float, b: float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def masked_mean(values: F64, mask: B, sigma: float) -> F64:
    """Gaussian mean of ``values`` over ``mask`` only, normalised by the kernel's share in it."""
    held = gaussian_filter(np.where(mask, values, 0.0), sigma)
    return held / np.maximum(gaussian_filter(mask.astype(np.float64), sigma), 1e-9)


def window_position(z: F64, pixel_m: float, inside: B) -> F64:
    """Valley (-1) to ridge (+1) position from height above the local mean at 3-15 km.

    Means are taken over the window's disc (``inside``) only: a 15 km mean reaches
    across most of a 30 km window, and the ground outside it has no relief.
    """
    total = np.zeros_like(z)
    for radius_m, weight, scale_m in ((3e3, 0.5, 80.0), (15e3, 0.5, 300.0)):
        mean = masked_mean(z, inside, radius_m / pixel_m)
        total += weight * np.tanh((z - mean) / scale_m)
    return total


def display_lift(z: F64, surface_m: F64, land: B, spacing_px: float) -> F64:
    """Height of display relief ``z`` above the ground's ``surface_m``, as colour sees it.

    Display relief stands in for relief the level's mesh cannot resolve, so only
    its departure from its own mean over a mesh spacing (``spacing_px``) counts.
    Its mean is no height: valley carving lowers it everywhere, level-1 display
    relief by about 750 m on steep Aethelara ground, and lapse-correcting that
    drew the region's mountains 5 C warmer than the tiles under them.
    """
    offset = np.where(land, z - surface_m, 0.0)
    return np.where(land, offset - masked_mean(offset, land, spacing_px), 0.0)


def display_climate(window: RegionWindow, climate: PixelClimate, z: F64) -> PixelClimate:
    """The window's ``climate`` lapse-corrected to its display relief ``z``.

    The climate holds at the tile relief. An ice sheet's surface is real height
    above it, so its whole thickness cools; display detail cools only about its
    own mean.
    """
    ground = np.nan_to_num(window.elevation_m)
    surface = ground if window.ice_surface_m is None else np.fmax(ground, window.ice_surface_m)
    lift = (surface - ground) + display_lift(
        z, surface, window.land, window.detail_spacing_m / window.pixel_m
    )
    cooling = window.lapse_c_per_km * lift / 1000
    return PixelClimate(
        climate.temperature_c - cooling, climate.warm_season_c - cooling,
        climate.precipitation_mm, climate.pet_mm, climate.growing_mm,
    )


def slope_factor(spacing_m: float) -> float:
    """Slopes of a level with mesh ``spacing_m`` times this are as level 1 would make them."""
    return (spacing_m / REGION_SLOPE_SPACING_M) ** REGION_SLOPE_EXPONENT


def window_shading(window: RegionWindow, z: F64) -> tuple[F64, F64]:
    """Slope and hillshade of display relief ``z``, scaled to the level-1 mesh."""
    scale = slope_factor(window.detail_spacing_m) / window.pixel_m
    return shading(
        np.gradient(z, axis=1) * scale, np.gradient(z, axis=0) * scale, REGION_EXAGGERATION
    )


def window_image(window: RegionWindow, *, atlas: bool) -> Image.Image:
    """Natural-colour (atlas) or shaded hypsometric view of a regional window."""
    z = display_relief(window)
    slope, light = window_shading(window, z)
    land = window.land
    climate = window.climate
    if atlas and climate is not None:
        shown = display_climate(window, climate, z)
        wet = 0.6 * gaussian_filter(window.rivers, 2.0)
        land_rgb = land_colour(
            window.points, window.planet_m, shown, z, slope, light, wet,
            window_position(z, window.pixel_m, np.isfinite(window.elevation_m)),
            REGION_MOSAIC_WAVELENGTH_M,
            window.volcanic,
            REGION_SLOPE_SCALE,
            window.basalt,
            window.cover,
            (
                None
                if window.ice_balance_m is None
                else IcePixels(window_ice_cover(window, z), window.ice_balance_m)
            ),
        )
    else:
        land_rgb = ramp(z, HYPSOMETRIC) * (0.30 + 0.70 * np.clip(light, 0, 1.5))[..., None]
    rgb = blend_coast(land_rgb, sea_depth_colour(-z, light), land, window.land_cover)
    if window.lakes.any():
        pan = window.salt
        if climate is not None:
            # Closed lakes in hot, arid basins dry to salt pans; others stay saline lakes.
            arid = climate.precipitation_mm / np.maximum(climate.pet_mm, 1.0) < 0.35
            pan = pan & arid & (climate.temperature_c > 12.0)
        else:
            pan = np.zeros_like(pan)
        rgb = _paint_soft(rgb, window.lakes & ~pan, LAKE)
        rgb = _paint_soft(rgb, pan, SALT_FLAT)
    rgb = _paint_soft(rgb, window.playa, SALT_FLAT)
    alpha = (0.9 * window.rivers)[..., None]
    rgb = rgb * (1 - alpha) + np.asarray(RIVER, dtype=np.float64) * alpha
    rgb = paint_falls(rgb, window.rivers * land, slope, REGION_FALLS_SLOPE)
    rgb[~np.isfinite(window.elevation_m)] = (36, 54, 82)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def _paint_soft(rgb: F64, mask: B, colour: tuple[int, int, int]) -> F64:
    """``colour`` over ``mask`` with soft, anti-aliased shores, as the world map draws lakes."""
    if not mask.any():
        return rgb
    alpha = gaussian_filter(mask.astype(np.float64), 0.7)[..., None]
    return rgb * (1 - alpha) + np.asarray(colour, dtype=np.float64) * alpha


def window_topographic(window: RegionWindow) -> Image.Image:
    """Topographic view of a regional window: tints, contours, hillshade and water."""
    z = display_relief(window)
    _, light = window_shading(window, z)
    shown = np.where(np.isfinite(window.elevation_m), z, np.nan)
    return topographic_image(
        shown, window.land, window.lakes, window.rivers, light, window.pixel_m, window.pixel_m,
        window_ice_cover(window, z) > 0.5, local=True, playa=window.playa,
    )


def window_parchment(window: RegionWindow, seed: int = 0) -> Image.Image | None:
    """A regional window as a hand-drawn map (needs climate for vegetation)."""
    climate = window.climate
    if climate is None:
        return None
    z = display_relief(window)
    slope, light = window_shading(window, z)
    shown = display_climate(window, climate, z)
    wet = 0.6 * gaussian_filter(window.rivers, 2.0)
    cover = vegetation(
        window.points, window.planet_m, shown, slope,
        window_position(z, window.pixel_m, np.isfinite(window.elevation_m)), wet,
        REGION_MOSAIC_WAVELENGTH_M, REGION_SLOPE_SCALE,
    )
    inputs = parchment_inputs(
        shown, cover, np.where(np.isfinite(window.elevation_m), z, np.nan), window.land,
        window.lakes | window.playa, window.rivers, light, window_ice_cover(window, z) > 0.5,
    )
    return parchment_image(inputs, seed, float(np.clip(window.pixels / 45, 12, 30)), framed=False)


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
    level: int = 1,
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
    window_topographic(window).save(target / "topographic.png")
    names.append("topographic.png")
    parchment = window_parchment(window)
    if parchment is not None:
        parchment.save(target / "parchment.png")
        names.append("parchment.png")
    manifest: dict[str, object] = {
        "schema": REGION_SCHEMA,
        "version": REGION_VERSION,
        "status": "experimental",
        "algorithm": REGIONAL_ALGORITHM,
        "parent_build_sha256": parent_sha256,
        "centre_lonlat_deg": [lon0, lat0],
        "radius_km": window.radius_m / 1000,
        "level": level,
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
