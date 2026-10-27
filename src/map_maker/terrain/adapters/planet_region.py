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
    map_coordinates,
    maximum,
    sum_labels,
)
from scipy.spatial import KDTree

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
    RiverLine,
    blend_coast,
    draw_river_lines,
    erg_cover,
    ice_surface,
    ice_undulation,
    land_colour,
    paint_falls,
    parchment_inputs,
    ramp,
    river_lines,
    sea_depth_colour,
    shading,
    vegetation,
)
from map_maker.terrain.adapters.planet_render import edge_coverage
from map_maker.terrain.domain.planet import REGIONAL_ALGORITHM, RegionalSettings
from map_maker.terrain.domain.seeds import stage_seed
from map_maker.terrain.pipeline.planet_climate import potential_evapotranspiration
from map_maker.terrain.pipeline.planet_coast import (
    Coastline,
    coastline,
    level_finest_m,
    window_finest_m,
)
from map_maker.terrain.pipeline.planet_detail import eroded_fbm, graph_carve, graph_flow
from map_maker.terrain.pipeline.planet_grid import GridCells, WorldGrid, cell_marks
from map_maker.terrain.pipeline.planet_mesh import fibonacci_nodes, mesh_from_triangles
from map_maker.terrain.pipeline.planet_patch import forward_aeqd, inverse_aeqd
from map_maker.terrain.pipeline.planet_regional import (
    LAKE_CORE_COVER,
    RegionalParent,
    RegionalResult,
)
from map_maker.terrain.pipeline.planet_tiles import ReliefWarp, TileGrid, TileSurface, blend
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
ROUTE_GRID_STAGE = "planet.route-grid"  # the jitter of the world's routing cells
WALL_CELLS = 2.0  # a ring this many cells wide beyond the routing reach holds its walls
RIVER_MARK_SEED = 47  # route cells' marks, which fix river bends to the place
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
    valleys_m: F64  # how deep display valleys cut the rough relief (``display_valleys``)
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
    """A regional window: relief and colour on its pixels, waters from the world's cells.

    Steepest descent depends on where cells lie, so rivers, lakes and ponds are
    worked out on cells fixed to the sphere (``window_hydrology``) and drawn into
    the window's pixels: windows that share a cell size draw the same waters
    where they overlap. Drainage has to start somewhere, so it is routed over
    ``pad`` times the radius, which keeps that start outside the visible map.
    The tiles' blend is sampled where ``relief`` moves each point
    (``ReliefWarp.for_window``).
    """
    radius_m = radius_km * 1e3
    planet_m = parent.mesh.radius_m
    points, inside = window_points(*centre, radius_m, pixels, planet_m)
    pixel_m = 2 * radius_m / pixels
    finest = window_finest_m(spacing_m, pixel_m)
    coast = coastline(parent.world)
    ground = window_relief(parent, grid, tiles, relief, coast, points, inside, finest)
    elevation, land, islands = ground.elevation, ground.land, ground.islands
    climate = regional_climate(parent, points, elevation, land)

    def on_land(row: F64, column: F64) -> B:
        sub = inverse_aeqd(column * pixel_m - radius_m, radius_m - row * pixel_m, *centre, planet_m)
        own = islands[np.floor(row).astype(np.intp), np.floor(column).astype(np.intp)]
        return own | coast.contains(sub, finest, parent.settings.seed)

    # The share of land in each pixel, so coasts are drawn anti-aliased.
    land_cover = edge_coverage(ground.drawn | islands, on_land)
    ice_surface, ice_balance = window_ice(parent, points, elevation, land, pixel_m, spacing_m)
    hydrology = window_hydrology(
        parent, grid, tiles, relief, coast, centre, radius_m, pad * radius_m, pixel_m,
        river_km2, spacing_m,
    )
    network = hydrology.network
    coverage = draw_river_lines(
        network.lines, network.links, river_widths(network.discharge, pixel_m, pixels),
        (pixels, pixels),
    )
    lakes, salt, playa = hydrology.drawn.at(points, elevation, land)
    cover = (
        None
        if parent.wonders is None
        or (found := wonder_cover(points, planet_m, parent.wonders, finest)) is None
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
    # Display valleys are carved on the routing cells, once per window.
    valleys = np.zeros((pixels, pixels))
    if land.any():
        rough = display_rough(
            elevation, land, points, pixel_m, spacing_m, parent.settings.seed, planet_m
        ).rough
        valleys = display_valleys(rough, land, hydrology.cells, centre, radius_m, pixel_m)
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
        ground.volcanic,
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
        valleys,
        spacing_m,
        parent.settings.seed,
        cover,
        ice_surface,
        ice_balance,
    )


@dataclass(frozen=True)
class WindowRelief:
    """The relief of a window's cells: the tiles' blend and what the window draws on it."""

    elevation: F64  # NaN outside the window
    blended: F64  # the tiles' blend alone (0 outside)
    land: B  # land inside the window, volcanic islands included
    drawn: B  # the authored land
    islands: B  # volcanic islands beyond the authored coast
    volcanic: F64  # 0..1 cover of young volcanic edifices near summits


def window_relief(
    parent: RegionalParent,
    grid: TileGrid,
    tiles: dict[int, TileSurface],
    relief: ReliefWarp,
    coast: Coastline,
    points: F64,
    inside: B,
    finest_m: float,
) -> WindowRelief:
    """The tiles' blend at ``points`` (cells shaped like ``inside``), with volcanoes,
    crater floors and wonders drawn on it and the sea floor around it."""
    shape = inside.shape
    planet_m = parent.mesh.radius_m
    drawn = coast.contains(points, finest_m, parent.settings.seed).reshape(shape)
    land = drawn & inside
    floor = parent.sea_floor_m
    if floor is None:
        floor = np.where(parent.land, 0.0, -2000.0)
    sea = parent.sample(points, floor).reshape(shape)
    blended = np.zeros(inside.size)
    blended[inside.ravel()] = blend(grid, tiles, relief(points[inside.ravel()], planet_m))
    elevation = blended = blended.reshape(shape)
    volcanic = np.zeros(shape)
    if parent.volcanoes is not None and parent.volcanic_m is not None:
        # Draw volcanoes sharply at pixel scale on the regional relief and sea floor.
        sharp = edifice_height(points, planet_m, parent.volcanoes).reshape(shape)
        floor_only = sea - parent.sample(
            points, np.where(parent.land, 0.0, parent.volcanic_m)
        ).reshape(shape)
        sea = sea_floor_with_volcanoes(
            points, planet_m, parent.volcanoes, floor_only.ravel()
        ).reshape(shape)
        elevation = np.where(land, elevation + sharp, elevation)
        # Opt-in volcanic islands rise from the sea floor beyond the authored coast.
        islands = inside & ~land & (sea > 0)
        land = land | islands
        # Lava and ash cover summits. An island's cone rises from the sea floor,
        # so its summit share is its height above the sea, not above that floor.
        above = np.where(islands, sea, sharp)
        volcanic = np.where(land, np.clip((above - 300.0) / 2200.0, 0.0, 1.0) ** 2, 0.0)
    else:
        islands = np.zeros(shape, dtype=bool)
    wonders = parent.wonders
    floors = parent.crater_floor_m
    if floors is not None and np.any(floors != 0):
        # Tiles carry the ground without wonders (ADR-0097): level crater floors
        # as the planet did before drawing the craters on top.
        elevation = np.where(
            land, elevation + parent.sample(points, floors).reshape(shape), elevation
        )
    if wonders is not None and len(wonders):
        elevation = np.where(
            land,
            elevation + wonder_relief(points, planet_m, wonders, finest_m).reshape(shape),
            elevation,
        )
    elevation = np.where(land, np.maximum(elevation, 1.0), np.minimum(sea, -5.0))
    elevation = np.where(islands, sea, elevation)
    elevation = np.where(inside, elevation, np.nan)
    return WindowRelief(elevation, blended, land, drawn, islands, volcanic)


@dataclass(frozen=True)
class WindowWaters:
    """Drainage, lakes and ponds on a window's cells."""

    flow: WindowFlow  # routed through open lakes, ending in closed ones
    lakes: B  # parent lakes standing on the relief
    salt: B  # closed parent lakes
    ponds: B  # hollows of the drawn relief that hold water or a playa
    spills: B  # ponds that overflow
    depth: F64  # how far ground lies below its hollow's spill level
    level: F64  # the parent's lake level at each cell


def window_waters(
    parent: RegionalParent,
    centre: tuple[float, float],
    reach_m: float,
    cells: GridCells,
    ground: WindowRelief,
    inside: B,
    river_km2: float,
    spacing_m: float,
    climate: PixelClimate | None,
) -> WindowWaters:
    """Drainage, lakes and ponds on ``cells`` within ``reach_m`` of ``centre`` (``inside``)."""
    land = ground.land
    flow = window_flow(parent, centre, reach_m, cells, ground.elevation, land, inside, river_km2)
    # Lakes fill the regional relief up to the parent lake level, so shores
    # follow the fine terrain (and a crater's sharp trough) instead of the
    # coarse parent mesh.
    cover, level, closed = parent.lakes_at(cells.xyz, level_finest_m(spacing_m))
    lakes = lake_water(cells, flow.z, land & inside, flow.filled, cover > LAKE_CORE_COVER, level)
    salt = lakes & closed
    # Hollows of the tiles' blend are filled plains; only the relief drawn on
    # top of the tiles holds ponds (``drawn_hollows``).
    tiles_z = np.where(land, np.maximum(ground.blended, 1.0), flow.z)
    flow, depth = lake_flow(flow, lakes, salt, level, tiles_z)
    # Deep hollows (crater troughs, chasm floors, calderas) hold water or a
    # playa, and rivers end there; rivers cross the others on a filled flat.
    ponds, spills = window_ponds(flow, depth, land & inside & ~lakes, climate)
    return WindowWaters(flow, lakes, salt, ponds, spills, depth, level)


@dataclass(frozen=True)
class WaterCells:
    """Cells under standing water or a playa bed, and how high each holds it."""

    cells: GridCells
    lake: B  # lakes: parent lakes, and ponds that overflow or are wet enough
    salt: B  # lake cells of closed salt lakes
    playa: B  # dry closed basins' ephemeral lake beds
    top_m: F64  # at lake and playa cells: ground up to this height is water or bed

    def at(self, points: F64, elevation: F64, ground: B) -> tuple[B, B, B]:
        """Lakes, salt lakes and playas at ``points`` (shaped like ``ground``).

        A point is water, or a playa bed, where the nearest wet cell lies within
        a cell spacing and the point's ground is no higher than that cell's top,
        so shores follow the points' own relief.
        """
        shape = ground.shape
        wet = np.flatnonzero(self.lake | self.playa)
        found = [np.zeros(shape, dtype=bool) for _ in range(3)]
        at = np.flatnonzero(ground.ravel())
        if not len(wet) or not len(at):
            return found[0], found[1], found[2]
        chord, near = KDTree(self.cells.xyz[wet]).query(points[at], workers=-1)
        cell = wet[np.asarray(near, dtype=np.intp)]
        held = (np.asarray(chord) * self.cells.planet_m <= self.cells.cell_m) & (
            elevation.ravel()[at] <= self.top_m[cell]
        )
        for out, kind in zip(found, (self.lake, self.salt, self.playa), strict=True):
            out.ravel()[at[held & kind[cell]]] = True
        return found[0], found[1], found[2]


@dataclass(frozen=True)
class WindowHydrology:
    """A window's waters on the world's cells, and its rivers as lines in its pixels."""

    cells: GridCells
    waters: WindowWaters
    network: RiverNetwork  # lines in the window's pixel units
    drawn: WaterCells  # the cells whose water the window draws


def window_hydrology(
    parent: RegionalParent,
    grid: TileGrid,
    tiles: dict[int, TileSurface],
    relief: ReliefWarp,
    coast: Coastline,
    centre: tuple[float, float],
    radius_m: float,
    reach_m: float,
    pixel_m: float,
    river_km2: float,
    spacing_m: float,
) -> WindowHydrology:
    """Rivers, lakes and ponds within ``reach_m`` of ``centre``, on cells fixed to the sphere.

    A window's own pixels lie where its centre puts them, and steepest descent
    across gentle ground follows the cells it runs on: windows routed on their
    own pixels put 1-8 % of their river pixels apart. The cells here belong to
    the planet (``WorldGrid``, the size of the ladder nearest the window's
    pixels), so windows that share a cell size work out the same drainage,
    lakes and ponds wherever they overlap, and bends are fixed to the cells'
    marks (``river_network``). Rivers come back as lines in the window's pixels
    (``radius_m`` and ``pixel_m``), lakes as cells the window draws from.
    """
    planet_m = parent.mesh.radius_m
    world = WorldGrid.for_pixels(
        pixel_m, planet_m, stage_seed(parent.settings.seed, ROUTE_GRID_STAGE)
    )
    middle = inverse_aeqd(np.zeros(1), np.zeros(1), *centre, planet_m)[0]
    # A ring of cells beyond the reach holds the routing rim's walls.
    cells = world.disc(middle, reach_m + WALL_CELLS * world.cell_m)
    inside = cells.xyz @ middle >= np.cos(reach_m / planet_m)
    ground = window_relief(
        parent, grid, tiles, relief, coast, cells.xyz, inside,
        window_finest_m(spacing_m, world.cell_m),
    )
    climate = None
    if ground.land.any():
        # Only hollows need the climate, to tell which overflow; the rest stays 0.
        at = ground.land
        found = regional_climate(parent, cells.xyz[at], ground.elevation[at], at[at])
        if found is not None:
            precipitation, pet = np.zeros(cells.size), np.zeros(cells.size)
            precipitation[at], pet[at] = found.precipitation_mm, found.pet_mm
            unused = np.zeros(cells.size)
            climate = PixelClimate(unused, unused, precipitation, pet)
    waters = window_waters(
        parent, centre, reach_m, cells, ground, inside, river_km2, spacing_m, climate
    )
    flow, depth = waters.flow, waters.depth
    # Closed ponds hold lakes where it is wet enough and playas where it is dry.
    # A wet or overflowing basin fills to its spill level; a dry closed one
    # keeps only an ephemeral lake bed in its lowest part, flat and bright (a
    # playa or salar).
    dry = np.zeros(cells.size, dtype=bool)
    if climate is not None:
        dry = climate.precipitation_mm / np.maximum(climate.pet_mm, 1.0) < POND_LAKE_ARIDITY
    spill = flow.z + depth
    closed = waters.ponds & ~waters.spills
    floor = playa_floor(cells, closed, depth)
    playa = closed & dry & (depth >= floor)
    lake = waters.lakes | (waters.ponds & (waters.spills | ~dry))
    salt = waters.salt | (closed & ~dry)
    top = np.full(cells.size, -np.inf)
    top[waters.lakes] = waters.level[waters.lakes] + LAKE_SHORE_M
    held = waters.ponds & lake
    top[held] = spill[held] - POND_DEPTH_M
    top[playa] = spill[playa] - np.maximum(floor[playa], POND_DEPTH_M)
    x, y = forward_aeqd(cells.xyz, *centre, planet_m).T
    marks = cell_marks(cells.rank, parent.settings.seed + RIVER_MARK_SEED)
    network = river_network(
        flow, waters.lakes | waters.ponds, river_km2,
        np.stack(((x + radius_m) / pixel_m, (radius_m - y) / pixel_m), axis=1), pixel_m, marks,
    )
    return WindowHydrology(cells, waters, network, WaterCells(cells, lake, salt, playa, top))


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
    """Cells of closed hollows that hold water or a playa, and those that overflow.

    ``depth`` is how far ``ground`` lies below its hollow's spill level. Each
    hollow gathers the runoff and sediment of its catchment, the drainage area
    where it spills. It overflows when that water exceeds what its area at the
    spill level evaporates (open-water PET less precipitation), so its river
    runs on. An overflowing hollow that the river's sediment fills within
    HOLLOW_AGE_YR is a plain the river crosses, not a lake, such as a shallow
    crater on a big river's course. Cells deeper than POND_DEPTH_M in the
    remaining hollows hold water or a playa: crater troughs, chasm floors and
    calderas, deep for their catchments. ``depth`` measures only hollows drawn
    on the tiles (``drawn_hollows``).
    """
    labels, count = flow.cells.label(ground & (depth > 0))
    ponds = ground & (depth > POND_DEPTH_M)
    if not count:
        return ponds, np.zeros_like(ponds)
    ids = np.arange(1, count + 1)
    cell_m2 = flow.cells.area_m2
    volume = np.asarray(sum_labels(depth * cell_m2, labels, ids), dtype=np.float64)
    catchment = np.asarray(maximum(flow.area_m2, labels, ids), dtype=np.float64)
    evaporation = np.zeros(count)
    if climate is not None:
        net_m = np.maximum(climate.pet_mm - climate.precipitation_mm, 0.0) / 1000
        evaporation = np.asarray(sum_labels(net_m * cell_m2, labels, ids), dtype=np.float64)
    spills = np.zeros(count + 1, dtype=bool)
    spills[1:] = catchment * MEAN_RUNOFF_M_YR > evaporation
    alluvial = np.zeros(count + 1, dtype=bool)
    alluvial[1:] = spills[1:] & (volume < catchment * SEDIMENT_YIELD_M_YR * HOLLOW_AGE_YR)
    ponds = ponds & ~alluvial[labels]
    return ponds, ponds & spills[labels]


def playa_floor(cells: GridCells, ponds: B, depth: F64) -> F64:
    """How deep in each closed basin its ephemeral lake bed starts (inf off the basins).

    The bed is the lowest part of the basin: PLAYA_SHARE of its depth, within
    PLAYA_MIN_M to PLAYA_MAX_M, above its deepest point.
    """
    floor = np.full(cells.size, np.inf)
    labels, count = cells.label(ponds)
    if not count:
        return floor
    deepest = np.zeros(count + 1)
    deepest[1:] = np.asarray(maximum(depth, labels, np.arange(1, count + 1)), dtype=np.float64)
    bed = np.clip(PLAYA_SHARE * deepest, PLAYA_MIN_M, PLAYA_MAX_M)
    floor[ponds] = (deepest - bed)[labels[ponds]]
    return floor


@dataclass(frozen=True)
class WindowFlow:
    """Drainage routed on a window's cells."""

    cells: GridCells
    z: F64  # routed relief: elevation within the routing reach, walls beyond it
    outlet: B  # sea and the cells beyond the reach
    receiver: NDArray[np.int64]  # cell indices, -1 at outlets
    area_m2: F64  # drainage area, with the water entering from beyond the reach
    filled: F64  # relief with closed depressions filled to their spill level
    links: tuple[tuple[int, int], ...]  # splitting rivers: (split cell, branch cell)
    inflow_m2: F64  # drainage area entering at each cell from beyond the reach

    @classmethod
    def route(
        cls,
        cells: GridCells,
        z: F64,
        outlet: B,
        inflow_m2: F64,
        links: tuple[tuple[int, int], ...] = (),
    ) -> WindowFlow:
        receiver, area, filled = graph_flow(
            cells.ptr, cells.nbr, cells.step_m, cells.rank, cells.area_m2, z, outlet, inflow_m2
        )
        return cls(cells, z, outlet, receiver, area, filled, links, inflow_m2)

    def rerouted(self, z: F64, outlet: B) -> WindowFlow:
        """The same water routed over other relief and outlets."""
        return WindowFlow.route(self.cells, z, outlet, self.inflow_m2, self.links)


def window_flow(
    parent: RegionalParent,
    centre: tuple[float, float],
    reach_m: float,
    cells: GridCells,
    elevation: F64,
    land: B,
    inside: B,
    river_km2: float,
) -> WindowFlow:
    """One drainage network over ``cells`` within ``reach_m`` of ``centre`` (``inside``).

    Parent rivers that cross into that circle bring their upstream area in
    near where they cross (``river_crossings``, ``entry_cells``). Beyond the
    circle the ground is a wall at the highest neighbouring height inside, so
    a rim cell drains along the relief: water leaves only where a valley
    reaches the rim, and a river entering on the rim flows in. Ground at the
    sea floor or at zero beyond the rim drained every rim cell straight out,
    inherited rivers included. Where a river of ``river_km2`` or more flows in,
    no water leaves (``entry_walls``).
    """
    planet_m = parent.mesh.radius_m
    ground = np.where(inside, np.nan_to_num(elevation, nan=0.0), -np.inf)
    wall = cells.neighbour_max(ground)
    z = np.where(inside, ground, np.where(np.isfinite(wall), wall, 0.0))
    outlet = ~inside | ~land
    inflow = np.zeros(cells.size)
    entries, area = river_crossings(parent, centre, reach_m)
    if len(area):
        spread_m = max(parent.mesh.spacing_m, 2 * cells.cell_m)
        entry_xyz = inverse_aeqd(entries[:, 0], entries[:, 1], *centre, planet_m)
        exits, out_area = river_crossings(parent, centre, reach_m, outward=True)
        exit_xyz = inverse_aeqd(exits[:, 0], exits[:, 1], *centre, planet_m)
        big = area >= river_km2 * 1e6
        leave = out_area >= river_km2 * 1e6
        walls = entry_walls(cells, entry_xyz[big], exit_xyz[leave], inside, spread_m)
        z = np.where(walls, float(ground.max()) + ENTRY_WALL_M, z)
        dry = WindowFlow.route(cells, z, outlet, np.zeros(cells.size))
        target = entry_cells(
            cells, entry_xyz, downstream_steps(dry.receiver), inside & land, spread_m
        )
        entered = target >= 0
        np.add.at(inflow, target[entered], area[entered])
    # A splitting river's branch starts with its share of the river's water.
    links: list[tuple[int, int]] = []
    forks = None if parent.wonders is None else parent.wonders.forks
    if forks is not None and len(forks):
        tree = KDTree(cells.xyz)
        for a, b, carried in zip(forks.split_xyz, forks.branch_xyz, forks.area_m2, strict=True):
            (gap_a, at_a), (gap_b, at_b) = tree.query(a), tree.query(b)
            if max(float(gap_a), float(gap_b)) * planet_m <= cells.cell_m:
                inflow[int(at_b)] += carried
                links.append((int(at_a), int(at_b)))
    return WindowFlow.route(cells, z, outlet, inflow, tuple(links))


def river_crossings(
    parent: RegionalParent,
    centre: tuple[float, float],
    radius_m: float,
    *,
    outward: bool = False,
) -> tuple[F64, F64]:
    """Where parent rivers cross into a window's routing circle, and their area.

    Every parent river step that crosses into the circle of ``radius_m`` about
    ``centre`` gives its crossing (in metres in the centre's azimuthal
    equidistant plane) and its upstream area, so each inherited river enters
    once and nothing enters where rivers leave. With ``outward``, the steps
    that cross out of the circle.
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
    return crossing, parent.area_m2[nodes[crosses]]


def entry_walls(
    cells: GridCells, entries: F64, exits: F64, inside: B, spread_m: float
) -> B:
    """Cells beyond the rim near where parent rivers cross in, not where they leave.

    ``entries`` and ``exits`` are crossings (unit vectors). A parent river flows
    in at an entry, so beyond the rim lies its valley upstream, rising away
    from the window. Water does not leave there: a hollow that a river enters
    fills and spills onward, not back out past the river's entry. Tile
    blending can leave the window's relief a few metres off the parent's
    within one parent spacing (``spread_m``) of where it puts the river; a rim
    draining there sent a province window's 160,000 km2 river straight back
    out. The rim stays open nearer an exit than an entry, so a river crossing a
    window smaller than the parent's spacing still leaves where it should.
    """
    if not len(entries):
        return np.zeros_like(inside)
    entering = nearest_distance(cells, entries)
    leaving = nearest_distance(cells, exits) if len(exits) else np.full(cells.size, np.inf)
    return ~inside & (entering <= spread_m) & (entering < leaving)


def nearest_distance(cells: GridCells, points: F64) -> F64:
    """Distance (metres) from each cell's node to the nearest of ``points``."""
    chord = np.asarray(KDTree(points).query(cells.xyz, workers=-1)[0], dtype=np.float64)
    return 2 * cells.planet_m * np.arcsin(np.minimum(chord / 2, 1.0))


def downstream_steps(receiver: NDArray[np.int64]) -> NDArray[np.int64]:
    """How many steps water takes from each cell to an outlet (0 at outlets)."""
    jump = np.where(receiver >= 0, receiver, np.arange(len(receiver)))
    steps = (receiver >= 0).astype(np.int64)
    # Pointer doubling: each pass doubles the stretch of path each cell has counted.
    while not np.array_equal(jump[jump], jump):
        steps = steps + steps[jump]
        jump = jump[jump]
    return steps


def entry_cells(
    cells: GridCells, entries: F64, reach: NDArray[np.int64], ground: B, spread_m: float
) -> NDArray[np.intp]:
    """Cells where inherited rivers enter a window (-1: they reach its sea).

    A parent places its rivers only to within its spacing (``spread_m``), and
    the window's finer relief can put the valley a little to one side. A river
    enters at its crossing if the window's water runs inward from there for at
    least ``spread_m`` (``reach``, in steps of about a cell). Otherwise it
    enters at the nearest ``ground`` cell within ``spread_m`` where the water
    does, or failing that where it runs furthest, so it joins the window's own
    valley instead of leaving down a side valley at once. With no ground that
    near, the river has reached the sea.
    """
    targets = np.full(len(entries), -1, dtype=np.intp)
    if not len(entries):
        return targets
    steps = spread_m / cells.cell_m
    tree = KDTree(cells.xyz)
    chord = 2 * np.sin(spread_m / cells.planet_m / 2)
    for k, point in enumerate(entries):
        near = np.asarray(tree.query_ball_point(point, chord), dtype=np.intp)
        near = near[ground[near]]
        if not len(near):
            continue
        gap = np.linalg.norm(cells.xyz[near] - point, axis=1)
        runs = reach[near]
        inward = runs >= steps
        best = (
            np.argmin(np.where(inward, gap, np.inf))
            if inward.any()
            else np.lexsort((gap, -runs))[0]
        )
        targets[k] = int(near[best])
    return targets


def lake_water(cells: GridCells, z: F64, land: B, filled: F64, core: B, level: F64) -> B:
    """Parent lakes as water standing on the regional relief at the lake level.

    Water covers ground up to ``level`` (plus LAKE_SHORE_M) that is connected to
    a lake's ``core`` (where the tiles hold the parent lake) and lies in a basin
    that spills no lower than the level, so it does not run out down the outlet
    valley. Shores are contours of the fine relief, not of the parent's lake
    cover, which is linear, so straight, inside each parent triangle.
    """
    wet = land & (z <= level + LAKE_SHORE_M) & (filled >= level - LAKE_SHORE_M)
    labels, count = cells.label(wet)
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
    depth = drawn_hollows(flow.cells, flow.z, sinks, tiles)
    if not lakes.any():
        return flow, depth
    inward = WindowFlow.route(flow.cells, flow.z, sinks, np.zeros(flow.cells.size)).receiver
    routed = lake_outflows(flow, inward, lakes & ~closed, level)
    return flow.rerouted(routed, flow.outlet | (lakes & closed)), depth


def drawn_hollows(cells: GridCells, z: F64, sinks: B, tiles: F64 | None) -> F64:
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
    no_inflow = np.zeros(cells.size)

    def filled(surface: F64) -> F64:
        return WindowFlow.route(cells, surface, sinks, no_inflow).filled

    if tiles is not None:
        z = z + filled(tiles) - tiles
    return filled(z) - z


def lake_outflows(flow: WindowFlow, inward: NDArray[np.int64], lakes: B, level: F64) -> F64:
    """Routed relief with each lake's outflow lowered to the lake's level.

    A lake's routed path out, from its last-filled cell, may cross the filled
    basin to a pour point above the lake's level, where the tiles do not hold
    the parent's outflow. Drainage would then cross that flat towards the pour
    point instead of entering the lake. The outflow is lowered to the level
    along the basin's floor from the lake up to the pour point (``inward``,
    receivers with every lake a sink, leads down that floor into the lake),
    then along the routed path until the filled relief is down to the lake's
    shore. The basin then drains into the lake and the lake out over the pour
    point. Only routing uses this relief.
    """
    ids, count = flow.cells.label(lakes)
    if not count:
        return flow.z
    relief, filled, outlet = flow.z, flow.filled, flow.outlet
    z = relief.copy()
    # Each lake's lowest filled cell, ties to the lower rank.
    held = np.flatnonzero(ids)
    held = held[np.lexsort((flow.cells.rank[held], filled[held], ids[held]))]
    starts = held[np.r_[True, np.diff(ids[held]) != 0]]
    for lake, start in enumerate(starts.tolist(), start=1):
        top = float(level[start])
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
    return z


@dataclass(frozen=True)
class RiverNetwork:
    """River lines on a flow's cells, in the drawing's pixel units."""

    lines: list[RiverLine]
    links: list[tuple[F64, F64, int]]  # splitting rivers' branches (start, end, end cell)
    discharge: F64  # m^3/s at each cell


def river_network(
    flow: WindowFlow,
    water: B,
    river_km2: float,
    xy_px: F64,
    pixel_m: float,
    marks: F64 | None = None,
) -> RiverNetwork:
    """The rivers of ``flow`` drawn as lines; rivers end in ``water``.

    ``xy_px`` places each cell in the drawing, whose pixels are ``pixel_m``
    across. ``marks`` (0..1 per cell) fix their bends to the place
    (``meander``); without them bends follow the cells' indices.
    """
    z, receiver, area = flow.z, flow.receiver, flow.area_m2
    stop = flow.outlet | water
    major = ~stop & (receiver >= 0) & (area >= river_km2 * 1e6)
    # Hydraulic geometry: channel width ~4.8 sqrt(Q) m (Leopold and Maddock
    # 1953), meander wavelength ~11 widths; rivers meander on gentle ground.
    discharge = area * MEAN_RUNOFF_M_YR / 3.156e7
    wavelength = 11 * CHANNEL_WIDTH_PER_ROOT_Q * np.sqrt(discharge) / pixel_m
    xyz = flow.cells.xyz
    target = np.maximum(receiver, 0)
    drop = z - z[target]
    chord = np.linalg.norm(xyz - xyz[target], axis=1)
    run = 2 * flow.cells.planet_m * np.arcsin(np.minimum(chord / 2, 1.0))
    gentle = 1 - np.clip((drop / np.maximum(run, 1.0) - 0.0005) / 0.0025, 0, 1)
    lines, links = river_lines(
        xy_px[:, 0], xy_px[:, 1], receiver, area, major, stop,
        meander_px=np.where(gentle > 0.3, wavelength * gentle, 0.0), meander_scale_px=wavelength,
        marks=marks, links=flow.links, rank=flow.cells.rank,
    )
    return RiverNetwork(lines, links, discharge)


def river_widths(discharge: F64, pixel_m: float, pixels: int) -> F64:
    """Drawn river widths (pixels) on an image of ``pixels`` pixels of ``pixel_m``.

    A river is drawn at least as wide as its channel. Narrower ones get a
    visible width tapered by discharge against a fixed reference, not against
    the largest river in the window, so other rivers do not change it.
    """
    channel_px = CHANNEL_WIDTH_PER_ROOT_Q * np.sqrt(discharge) / pixel_m
    shown = (0.4 + 1.6 * np.sqrt(np.clip(discharge / RIVER_DISPLAY_Q_M3_S, 0, 1))) * pixels / 1100
    return np.maximum(channel_px, shown)


def window_rivers(flow: WindowFlow, water: B, river_km2: float, shape: tuple[int, int]) -> F64:
    """River coverage of a flow on raster cells (``GridCells.raster``) of ``shape``."""
    columns = shape[1]
    flat = np.arange(flow.cells.size)
    xy = np.stack((flat % columns + 0.5, flat // columns + 0.5), axis=1).astype(np.float64)
    network = river_network(flow, water, river_km2, xy, flow.cells.cell_m)
    return draw_river_lines(
        network.lines, network.links,
        river_widths(network.discharge, flow.cells.cell_m, shape[0]), shape,
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


@dataclass(frozen=True)
class DisplayRough:
    """A window's relief roughened below its mesh, before valleys are carved into it."""

    rough: F64  # beyond the window's disc, held at the nearest height inside it
    amplitude: F64  # the detail's height, which caps valley incision
    tile_slope: F64  # slope of the relief without detail, smoothed over a few pixels


def display_rough(
    elevation_m: F64, land: B, points: F64, pixel_m: float, spacing_m: float, seed: int,
    planet_m: float,
) -> DisplayRough:
    """Window relief (NaN beyond its disc) plus ridged sub-tile detail, for display only.

    The 5 km tile mesh cannot resolve hillslopes, so mountains would shade as
    smooth domes. Ridged, slope-damped noise scaled with height adds roughness.
    """
    z = np.nan_to_num(elevation_m, nan=-200.0)
    base = np.where(land, z, 0.0)
    inside = np.isfinite(elevation_m)
    tile_slope = gaussian_filter(np.hypot(*np.gradient(np.where(inside, z, 0.0), pixel_m)), 3.0)
    # Flat plains and plateau tops stay smooth; slopes get ridges and gullies.
    # Ridged noise creases into sharp lines, so it too needs relief, not height.
    ruggedness = 0.15 + 0.85 * np.clip((tile_slope - 0.002) / 0.018, 0, 1)
    ridged = (np.clip((base - 300) / 1500, 0, 1) * ruggedness).ravel()
    # Detail stands in for the relief the level's mesh cannot resolve: its
    # wavelength follows the mesh spacing and its height shrinks with it. It is
    # anchored to the world (planet seed, world positions, a fixed zero), so
    # overlapping windows draw the same hills.
    level = spacing_m / REGION_DETAIL_SPACING_M
    wavelength = REGION_DETAIL_WAVELENGTH_M * level
    noise_seed = seed + REGION_DETAIL_SEED
    detail = eroded_fbm(points, ridged, noise_seed, 5, planet_m / wavelength, 0.5, 0.1).reshape(
        z.shape
    )
    detail -= detail_offset(noise_seed, planet_m / wavelength, ridged).reshape(z.shape)
    amplitude = (
        (REGION_DETAIL_FLOOR_M + REGION_DETAIL_SHARE * base)
        * ruggedness
        * level**REGION_DETAIL_EXPONENT
    )
    rough = np.where(land, z + amplitude * detail, z)
    # Outside the window circle, hold each pixel at the nearest inside height so
    # the rim is not a base level that every border valley would cut down to.
    nearest = cast(
        NDArray[np.intp],
        distance_transform_edt(~inside, return_distances=False, return_indices=True),
    )
    return DisplayRough(rough[nearest[0], nearest[1]], amplitude, tile_slope)


def display_valleys(
    rough: F64, land: B, cells: GridCells, centre: tuple[float, float], radius_m: float,
    pixel_m: float,
) -> F64:
    """How deep valleys cut a window's rough relief at each pixel (display only).

    A few stream-power steps routed over the rough relief carve it into a
    connected, branching valley network. Routed over the window's pixels,
    steepest descent stepped in eight directions and cut straight grooves at 0,
    45 and 90 degrees down smooth slopes; on the world's routing ``cells`` it
    has no preferred directions. The relief is sampled at the cells, sea and the
    ground beyond the disc hold their height, and the incision comes back to the
    pixels from the four nearest cells.
    """
    x, y = forward_aeqd(cells.xyz, *centre, cells.planet_m).T
    row = (radius_m - y) / pixel_m - 0.5
    column = (x + radius_m) / pixel_m - 0.5
    z = map_coordinates(rough, (row, column), order=1, mode="nearest")
    sea = map_coordinates(land.astype(np.float64), (row, column), order=1, mode="nearest") < 0.5
    held = sea | (np.hypot(x, y) > radius_m)
    carved = graph_carve(
        cells.ptr, cells.nbr, cells.step_m, cells.rank, cells.area_m2, z, held,
        REGION_CARVE_ERODIBILITY, 0.5, REGION_CARVE_STEPS,
    )
    incision = np.maximum(z - carved, 0.0)
    pixels = rough.shape[0]
    centres = (np.arange(pixels) + 0.5) * pixel_m - radius_m
    gx, gy = np.meshgrid(centres, -centres)
    distance, nearest = KDTree(np.stack((x, y), axis=1)).query(
        np.stack((gx.ravel(), gy.ravel()), axis=1), k=4, workers=-1
    )
    weight = 1.0 / np.maximum(distance, 1e-3 * pixel_m) ** 2
    return (np.sum(weight * incision[nearest], axis=1) / np.sum(weight, axis=1)).reshape(
        rough.shape
    )


def display_relief(window: RegionWindow) -> F64:
    """Elevation plus sub-tile ridges and valleys for shading only (never exported).

    The roughened relief (``display_rough``) is cut by the valleys the window
    carved on its routing cells (``display_valleys``), at most as deep as the
    local detail amplitude, so the tile relief keeps its shape.
    """
    z = np.nan_to_num(window.elevation_m, nan=-200.0)
    land = window.land
    if not land.any():
        return z
    found = display_rough(
        window.elevation_m, land, window.points, window.pixel_m, window.detail_spacing_m,
        window.seed, window.planet_m,
    )
    rough, tile_slope = found.rough, found.tile_slope
    # Flats and plateaus stay smooth at this scale, so incision follows the tile
    # relief's slope.
    steep = np.clip((tile_slope - 0.006) / 0.024, 0, 1)
    # Blurring the incision widens one-cell channels into valleys.
    depth = gaussian_filter(np.clip(window.valleys_m, 0, found.amplitude) * steep, 1.3)
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
                window_position(relief, window.pixel_m, np.isfinite(window.elevation_m)),
                REGION_SLOPE_SCALE,
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
