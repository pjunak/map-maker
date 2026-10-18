# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Planet rasters aligned with the world SVG frame, and cartographic previews.

Columns and rows map linearly to the world frame (and therefore to longitude and
latitude), so a preview can sit directly under the source drawing. Land/sea is
the exact vector coastline rasterised at the output size; coast pixels are
supersampled for the share of land that anti-aliases drawn coasts. Land values are
interpolated from a field with sea level on water nodes, and sea values from a
field with zero depth on land nodes, so near-coast pixels never mix the two.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from affine import Affine
from numpy.typing import NDArray
from PIL import Image
from rasterio import features
from scipy.spatial import KDTree
from shapely import contains_xy, prepare
from shapely.geometry import Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.pipeline.planet import PlanetResult
from map_maker.terrain.pipeline.planet_kernels import interpolate_to_lonlat
from map_maker.terrain.pipeline.planet_koppen import KOPPEN_COLOURS
from map_maker.terrain.pipeline.planet_lakes import refined_lake_cover
from map_maker.terrain.pipeline.planet_mesh import SphereMesh, vertex_triangles
from map_maker.terrain.pipeline.planet_volcanism import edifice_height
from map_maker.terrain.pipeline.planet_wonders import wonder_relief, wonder_zones
from map_maker.terrain.pipeline.world import WorldMap

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

SECONDS_PER_YEAR = 365.25 * 86400
# Refined lake outlines stay within this many mesh spacings of a lake node.
LAKE_REACH_SPACINGS = 2.0


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


def _land_polygons(world: WorldMap) -> list[Polygon]:
    return [Polygon(c.exterior, c.holes) for view in world.land for c in view.components]


def land_mask(world: WorldMap, raster: FrameRaster) -> B:
    burned = features.rasterize(
        ((mapping(shape), 1) for shape in _land_polygons(world)), out_shape=raster.shape,
        transform=raster.transform(), fill=0, dtype="uint8", all_touched=False,
    )
    return np.asarray(burned, dtype=np.uint8).astype(bool)


def neighbour_sum(values: F64, *, wrap: bool = False) -> F64:
    """Sum over each pixel's 3 x 3 neighbourhood (itself included).

    Rows repeat their edge values; columns wrap around when ``wrap`` (a world
    raster's east and west edges meet), else repeat theirs too.
    """
    padded = np.pad(values, ((1, 1), (0, 0)), mode="edge")
    padded = np.pad(padded, ((0, 0), (1, 1)), mode="wrap" if wrap else "edge")
    rows, columns = values.shape
    return sum(
        (padded[r : r + rows, c : c + columns] for r in range(3) for c in range(3)),
        start=np.zeros(values.shape),
    )


def edge_coverage(
    mask: B, inside: Callable[[F64, F64], B], *, samples: int = 4, wrap: bool = False
) -> F64:
    """Share (0..1) of each pixel inside a region whose pixel-centre test is ``mask``.

    Only pixels whose 3 x 3 neighbourhood holds both sides are supersampled, with
    ``samples`` x ``samples`` points per pixel tested by ``inside(row, column)``
    (fractional pixel coordinates, pixel centres at k + 0.5). The rest keep
    their mask value.
    """
    cover = mask.astype(np.float64)
    count = neighbour_sum(cover, wrap=wrap)
    rows, columns = np.nonzero((count > 0) & (count < 9))
    if not len(rows):
        return cover
    offsets = (np.arange(samples) + 0.5) / samples
    dr, dc = (grid.ravel() for grid in np.meshgrid(offsets, offsets, indexing="ij"))
    hits = inside((rows[:, None] + dr).ravel(), (columns[:, None] + dc).ravel())
    cover[rows, columns] = hits.reshape(len(rows), -1).mean(axis=1)
    return cover


@lru_cache(maxsize=2)
def _drawn_land(world: WorldMap) -> BaseGeometry:
    """The world's land as one prepared geometry, built once per world and process."""
    land = unary_union(_land_polygons(world))
    prepare(land)
    return land


def land_cover(world: WorldMap, raster: FrameRaster, land_px: B, islands_px: B) -> F64:
    """Share of each pixel on land: the drawn coast anti-aliased, islands whole pixels."""
    coast = _drawn_land(world)
    transform = raster.transform()

    def inside(row: F64, column: F64) -> B:
        x = transform.c + column * transform.a
        y = transform.f + row * transform.e
        own = islands_px[np.floor(row).astype(np.intp), np.floor(column).astype(np.intp)]
        return own | np.asarray(contains_xy(coast, x, y), dtype=bool)

    return edge_coverage(land_px, inside, wrap=True)


def elevation_raster(result: PlanetResult, raster: FrameRaster, land_px: B) -> F64:
    water = ~result.land
    on_land = raster.interpolate(result.mesh, np.where(water, 0.0, result.elevation_m))
    at_sea = raster.interpolate(result.mesh, np.where(water, result.elevation_m, 0.0))
    return np.where(land_px, np.maximum(on_land, 0.0), np.minimum(at_sea, 0.0))


def lake_raster(result: PlanetResult, raster: FrameRaster, land_px: B) -> NDArray[np.int64]:
    """Lake id per pixel (-1 none), with outlines refined below the mesh spacing.

    Lake membership is linear inside each mesh triangle, so its outlines would be
    straight. As regional maps do, it is sampled at noise-displaced points with
    detail down to two pixels (``refined_lake_cover``).
    """
    lakes = result.lakes
    mesh = result.mesh
    ids = np.full(raster.shape, -1, dtype=np.int64)
    nodes = np.flatnonzero(lakes.lake >= 0)
    if len(nodes):
        candidates = np.flatnonzero(land_px.ravel())
        # Only pixels near a lake node can lie inside a refined outline.
        found = KDTree(mesh.xyz[nodes]).query(
            raster.queries[candidates], distance_upper_bound=LAKE_REACH_SPACINGS
            * mesh.spacing_m / mesh.radius_m, workers=-1,
        )
        near = candidates[np.isfinite(np.asarray(found[0]))]
        detail_m = 2 * 2 * np.pi * mesh.radius_m / raster.shape[1]
        cover, nearest = refined_lake_cover(
            mesh, lakes.lake, result.settings.seed, raster.queries[near], detail_m
        )
        ids.ravel()[near] = np.where(cover > 0.5, nearest, -1)
    wonders = result.wonders
    if not len(wonders):
        return ids
    # A lake in a crater or chasm fills its sharp relief to the lake level, so it
    # can ring a central plateau or run along a chasm floor narrower than the mesh.
    mesh = result.mesh
    zone = wonder_zones(raster.queries, mesh.radius_m, wonders).reshape(raster.shape)
    ids = np.where(zone, -1, ids)
    owners = np.flatnonzero(
        wonder_zones(mesh.xyz, mesh.radius_m, wonders) & result.land & (lakes.lake >= 0)
    )
    if not len(owners) or not zone.any():
        return ids
    pixels = raster.queries[zone.ravel()]
    # Each pixel takes the lake of a nearby node, so a lake in one part of a
    # long chasm does not spread to lower ground elsewhere along it.
    found = np.asarray(
        KDTree(mesh.xyz[owners]).query(
            pixels, distance_upper_bound=3 * mesh.spacing_m / mesh.radius_m, workers=-1
        )[1]
    )
    near = found < len(owners)
    lake = np.full(len(pixels), -1)
    lake[near] = lakes.lake[owners[found[near]]]
    ground = raster.interpolate(
        mesh, np.where(result.land, result.elevation_m - result.wonder_m, 0.0)
    )[zone] + wonder_relief(
        pixels, mesh.radius_m, wonders, 2 * np.pi * mesh.radius_m / raster.shape[1]
    )
    wet = near & land_px[zone] & (ground < lakes.level_m[np.maximum(lake, 0)])
    ids[zone] = np.where(wet, lake, -1)
    return ids


def scalar_image(
    values: F64, land_px: B, low: float, high: float, colours: tuple[tuple[int, int, int], ...]
) -> Image.Image:
    t = np.clip((values - low) / (high - low), 0, 1)
    knots = np.linspace(0, 1, len(colours))
    rgb = np.stack([np.interp(t, knots, [c[k] for c in colours]) for k in range(3)], axis=-1)
    rgb[~land_px] = (36, 54, 82)
    return Image.fromarray(rgb.astype(np.uint8))


def ice_covered(result: PlanetResult) -> B:
    """Nodes under an ice sheet (no surface rivers or lakes are drawn there)."""
    return result.ice.thickness_m > 0


def river_threshold_m3_s(result: PlanetResult, area_km2: float) -> float:
    """Discharge equivalent to ``area_km2`` at the planet's mean land runoff."""
    land = result.land
    climate = result.climate
    runoff_mm = 250.0 if climate is None else float(
        np.average(climate.runoff_mm[land], weights=result.mesh.area_m2[land])
    )
    return area_km2 * 1e6 * runoff_mm / 1000 / SECONDS_PER_YEAR


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
    islands_px: B  # volcanic islands beyond the authored coastline (opt-in)
    land_cover: F64  # share of each pixel on land, for anti-aliased coasts


def planet_rasters(result: PlanetResult, width: int) -> PlanetRasters:
    raster = FrameRaster.build(result.mesh, result.world.project.frame, width)
    authored = land_mask(result.world, raster)
    islands_px, island_z = island_pixels(result, raster, authored)
    land_px = authored | islands_px
    z = np.where(islands_px, island_z, elevation_raster(result, raster, land_px))
    return PlanetRasters(
        raster, land_px, z, lake_raster(result, raster, land_px), islands_px,
        land_cover(result.world, raster, land_px, islands_px),
    )


def island_pixels(result: PlanetResult, raster: FrameRaster, authored: B) -> tuple[B, F64]:
    """Pixels of emergent volcanic islands and their surface height (m).

    The mesh resolves islands coarsely; their coastlines are drawn from the
    volcano shapes at pixel resolution on the volcano-free sea floor.
    """
    v = result.volcanoes
    if not len(v) or not v.emergent.any():
        return np.zeros(raster.shape, dtype=bool), np.zeros(raster.shape)
    water = ~result.land
    floor = raster.interpolate(
        result.mesh, np.where(water, result.elevation_m - result.volcanic_m, 0.0)
    )
    islands = v.subset(v.emergent)
    sharp = edifice_height(raster.queries, result.mesh.radius_m, islands).reshape(raster.shape)
    surface = floor + sharp
    return ~authored & (surface > 0), surface


def koppen_image(koppen: NDArray[np.int8], raster: FrameRaster, land_px: B) -> Image.Image:
    """Koppen-Geiger classes in their standard map colours (categorical: nearest node)."""
    palette = np.asarray(KOPPEN_COLOURS, dtype=np.uint8)
    classes = koppen[raster.nearest].reshape(raster.shape)
    rgb = palette[np.where(land_px, classes, 0)]
    return Image.fromarray(rgb)
