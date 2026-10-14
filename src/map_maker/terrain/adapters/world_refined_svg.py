# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A world's refined coast exported as a source map (SVG) for a new world project.

Regional maps draw a world's coast with detail below the drawing's precision
(ADR-0090), and the planet works polar land in true distance (ADR-0094). This
export traces that coast down to a chosen detail into vector shapes, so it can
be edited and imported as a new source map:

* **Tracing.** The refined land is sampled in tiles on a grid a quarter of the
  detail wavelength wide, only near the coast; pixel steps are simplified away
  and rounded. Holes smaller than two grid cells (folds of the detail) are
  dropped; drawn inland water stays.
* **Ownership.** Every traced cell belongs to the drawn shape it lies in, or the
  nearest one (where the detail moved the coast outward, or the planet added
  land at a pole). These territories, simplified as one coverage, cut the
  traced land, so continents that share a land border stay apart and each
  shape keeps its continent and role (mainland or island).
* **Round trip.** The SVG keeps the source's view box and continent groups, and
  declares the detail it carries on its root, so importing it fills in the
  world's coast detail and zoomed maps add only finer detail.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from xml.sax.saxutils import escape, quoteattr

import numpy as np
import shapely
from affine import Affine
from numpy.typing import NDArray
from rasterio import features
from scipy.ndimage import distance_transform_edt
from shapely.geometry import MultiPolygon, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from map_maker.terrain.adapters.world_svg import (
    COAST_DETAIL_ATTRIBUTE,
    MAX_SVG_BYTES,
    MAX_WORLD_POINTS,
)
from map_maker.terrain.domain.world import WorldProject, WorldRole
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.planet_coast import coastline
from map_maker.terrain.pipeline.planet_poles import planet_world
from map_maker.terrain.pipeline.world import WorldMap, prepare_world_map

type F64 = NDArray[np.float64]

TILE_UNITS = 96.0  # tracing tile, in drawing units
GRID_PER_WAVELENGTH = 4  # grid cells per detail wavelength
DEFAULT_DETAIL_KM = 10.0


@dataclass(frozen=True, slots=True)
class RefinedShape:
    polygon: Polygon  # drawing units
    continent_id: str
    role: WorldRole


@dataclass(frozen=True, slots=True)
class RefinedCoast:
    project: WorldProject
    shapes: tuple[RefinedShape, ...]
    detail_km: float  # finest coast wavelength the shapes carry

    @property
    def points(self) -> int:
        return sum(
            len(s.polygon.exterior.coords) - 1 + sum(len(h.coords) - 1 for h in s.polygon.interiors)
            for s in self.shapes
        )


def _polygons(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [p for part in getattr(geometry, "geoms", []) for p in _polygons(part)]


def _chaikin(ring: F64, iterations: int = 2) -> F64:
    xy = np.asarray(ring, dtype=np.float64)[:-1]
    for _ in range(iterations):
        following = np.roll(xy, -1, axis=0)
        rounded = np.empty((2 * len(xy), 2))
        rounded[0::2] = 0.75 * xy + 0.25 * following
        rounded[1::2] = 0.25 * xy + 0.75 * following
        xy = rounded
    return np.vstack([xy, xy[:1]])


def _unit_vectors(world: WorldMap, x: F64, y: F64) -> F64:
    frame = world.project.frame
    lon = np.radians((x - frame.bounds[0]) / frame.width * 360 - 180 + frame.central_meridian_deg)
    lat = np.radians(90 - (y - frame.bounds[1]) / frame.height * 180)
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def refined_coast(
    project: WorldProject,
    master_seed: int,
    detail_km: float = DEFAULT_DETAIL_KM,
    progress: Callable[[float, str], None] | None = None,
    cancellation: CancellationToken | None = None,
) -> RefinedCoast:
    """The world's coast as regional maps draw it, down to ``detail_km``, as shapes."""
    if not detail_km > 0:
        raise ValueError("Coast detail must be a positive wavelength in km.")
    drawn = prepare_world_map(project)
    world = planet_world(drawn, master_seed)
    coast = coastline(world)
    frame = project.frame
    finest_m = detail_km * 1e3
    step = finest_m / GRID_PER_WAVELENGTH / coast.unit_m
    # How far the detail can move the coast, in drawing units (plus a cell).
    reach = np.sqrt(3) * sum(a for _, a in coast.octaves(finest_m)) / coast.unit_m + step
    boundary = coast.land.boundary
    shapely.prepare(boundary)
    views = drawn.land
    owners = [
        unary_union([Polygon(c.exterior, c.holes) for c in view.components]) for view in views
    ]
    tree = STRtree(owners)
    land_pieces: list[BaseGeometry] = []
    territory_pieces: dict[int, list[BaseGeometry]] = {}
    columns = ceil(frame.width / TILE_UNITS)
    rows = ceil(frame.height / TILE_UNITS)
    for j in range(rows):
        check_cancelled(cancellation)
        if progress is not None:
            progress(0.8 * j / rows, f"Tracing the refined coast: row {j + 1} of {rows}")
        y0 = frame.bounds[1] + j * TILE_UNITS
        y1 = min(y0 + TILE_UNITS, frame.bounds[3])
        # East-west units shrink towards the poles, so the reach widens there.
        edge = max(abs(90 - (y - frame.bounds[1]) / frame.height * 180) for y in (y0, y1))
        stretch = 1 / max(np.cos(np.radians(edge)), 0.02)
        for i in range(columns):
            x0 = frame.bounds[0] + i * TILE_UNITS
            x1 = min(x0 + TILE_UNITS, frame.bounds[2])
            near = box(x0 - reach * stretch, y0 - reach, x1 + reach * stretch, y1 + reach)
            coastal = boundary.intersects(near)
            if not coastal and not coast.land.contains(shapely.Point((x0 + x1) / 2, (y0 + y1) / 2)):
                continue
            width, height = round((x1 - x0) / step), round((y1 - y0) / step)
            transform = Affine((x1 - x0) / width, 0, x0, 0, (y1 - y0) / height, y0)
            if coastal:
                gx, gy = np.meshgrid(
                    x0 + (np.arange(width) + 0.5) * (x1 - x0) / width,
                    y0 + (np.arange(height) + 0.5) * (y1 - y0) / height,
                )
                land = coast.contains(
                    _unit_vectors(world, gx.ravel(), gy.ravel()), finest_m, master_seed
                ).reshape(height, width)
                if not land.any():
                    continue
            else:
                land = np.ones((height, width), dtype=bool)
            land_pieces.extend(
                shape(geometry)
                for geometry, value in features.shapes(
                    land.astype(np.uint8), mask=land, transform=transform
                )
                if value
            )
            labels = _territories(
                owners, tree, near, (height, width), transform, ceil(reach / step) + 1
            )
            for geometry, value in features.shapes(labels, transform=transform):
                territory_pieces.setdefault(int(value), []).append(shape(geometry))
    if progress is not None:
        progress(0.8, "Joining and rounding the coast")
    rounded = _rounded(unary_union(land_pieces), step)
    keys = sorted(territory_pieces)
    territories = shapely.coverage_simplify(
        np.array([unary_union(territory_pieces[k]) for k in keys], dtype=object), step * 0.5
    )
    shapes: list[RefinedShape] = []
    for key, territory in zip(keys, territories, strict=True):
        view = views[key]
        for polygon in _polygons(rounded.intersection(territory)):
            if polygon.area > (2 * step) ** 2:
                shapes.append(RefinedShape(polygon, view.continent_id, view.role))
    drawn_km = project.coast_detail_km
    carried = detail_km if drawn_km is None else min(detail_km, drawn_km)
    return RefinedCoast(project, tuple(shapes), carried)


def _territories(
    owners: list[BaseGeometry],
    tree: STRtree,
    near: Polygon,
    shape_: tuple[int, int],
    transform: Affine,
    margin: int,
) -> NDArray[np.int32]:
    """Index of the drawn shape each cell lies in, or of the nearest one.

    Shapes are painted with ``margin`` extra cells around the tile, so a shape
    just outside it still counts as nearest.
    """
    hits = [int(k) for k in tree.query(near, predicate="intersects")]
    painted = np.zeros((shape_[0] + 2 * margin, shape_[1] + 2 * margin), dtype=np.int32)
    if hits:
        padded = Affine(transform.a, 0, transform.c - margin * transform.a,
                        0, transform.e, transform.f - margin * transform.e)
        painted = np.asarray(
            features.rasterize(
                ((owners[k], k + 1) for k in hits), out_shape=painted.shape, transform=padded,
                fill=0, dtype="int32",
            ),
            dtype=np.int32,
        )
    if not painted.any():
        # No drawn shape nearby (land the planet added at a pole): the nearest one.
        x0, y0 = transform * (0, 0)
        x1, y1 = transform * (shape_[1], shape_[0])
        centre = shapely.Point((x0 + x1) / 2, (y0 + y1) / 2)
        return np.full(shape_, int(tree.query_nearest(centre, all_matches=False)[0]), np.int32)
    nearest = distance_transform_edt(painted == 0, return_distances=False, return_indices=True)
    rows, columns = np.asarray(nearest)
    filled = painted[rows, columns] - 1
    return np.ascontiguousarray(filled[margin:-margin, margin:-margin], dtype=np.int32)


def _rounded(land: BaseGeometry, step: float) -> BaseGeometry:
    """Pixel steps simplified within half a cell, then rounded with Chaikin."""
    polygons: list[Polygon] = []
    for polygon in _polygons(land):
        for part in _polygons(polygon.simplify(step * 0.5)):
            holes = [
                _chaikin(np.asarray(h.coords))
                for h in part.interiors
                if Polygon(h).area > (2 * step) ** 2
            ]
            smooth = shapely.make_valid(Polygon(_chaikin(np.asarray(part.exterior.coords)), holes))
            polygons.extend(p for p in _polygons(smooth) if p.area > (2 * step) ** 2)
    return unary_union(polygons)


def _slug(name: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "group"
    out, n = base, 1
    while out in used:
        out = f"{base}{n}"
        n += 1
    used.add(out)
    return out


def _path_data(polygon: Polygon) -> str:
    def ring(coords: object) -> str:
        points = np.asarray(coords)[:-1]
        return "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in points) + "Z"

    return " ".join([ring(polygon.exterior.coords), *(ring(h.coords) for h in polygon.interiors)])


def refined_coast_svg(coast: RefinedCoast, master_seed: int) -> str:
    """The shapes as an SVG source map, grouped by continent like the drawing."""
    project = coast.project
    if coast.points > MAX_WORLD_POINTS:
        raise ValueError(
            f"The refined coast has {coast.points:,} points; the importer reads at most "
            f"{MAX_WORLD_POINTS:,}. Choose coarser coast detail."
        )
    x0, y0, x1, y1 = project.source.suggested_bounds
    names = {c.id: c.name for c in project.continents}
    used: set[str] = set()
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg width="100%" height="100%" viewBox="{x0:g} {y0:g} {x1 - x0:g} {y1 - y0:g}" '
        f'{COAST_DETAIL_ATTRIBUTE}="{coast.detail_km:g}" version="1.1" '
        'xmlns="http://www.w3.org/2000/svg" xmlns:affinity="https://www.affinity.studio/" '
        'style="fill-rule:evenodd;clip-rule:evenodd;stroke-linejoin:round;">',
        f"    <!-- {escape(project.name)}: coast refined down to {coast.detail_km:g} km by DM "
        f"Tools from {escape(project.source.name)} (master seed {master_seed}). -->",
    ]
    by_continent: dict[str, dict[str, list[Polygon]]] = {}
    for item in coast.shapes:
        group = "mainland" if item.role == "mainland" else "islands"
        by_continent.setdefault(item.continent_id, {}).setdefault(group, []).append(item.polygon)
    for continent_id in sorted(by_continent, key=lambda c: names.get(c, c)):
        name = names.get(continent_id, continent_id)
        slug = _slug(name, used)
        lines.append(f"    <g id={quoteattr(slug)} affinity:id={quoteattr(name)}>")
        lines.append(
            f'        <g id="{_slug(slug + " Land Shapes", used)}" affinity:id="Land Shapes">'
        )
        for group in ("mainland", "islands"):
            polygons = by_continent[continent_id].get(group, [])
            if not polygons:
                continue
            lines.append(
                f'            <g id="{_slug(slug + " " + group, used)}" affinity:id="{group}">'
            )
            for k, polygon in enumerate(polygons):
                lines.append(
                    f'                <path id="{_slug(f"{slug} {group} {k}", used)}" '
                    f'd="{_path_data(polygon)}" style="fill:rgb(92,122,82);fill-rule:evenodd;'
                    f'stroke:rgb(30,20,8);stroke-width:{0.99 if group == "mainland" else 0.6}px;"/>'
                )
            lines.append("            </g>")
        lines.append("        </g>")
        lines.append("    </g>")
    lines.append("</svg>")
    text = "\n".join(lines) + "\n"
    if len(text.encode("utf-8")) > MAX_SVG_BYTES:
        raise ValueError(
            f"The refined coast SVG exceeds the importer's {MAX_SVG_BYTES // 2**20} MiB. "
            "Choose coarser coast detail."
        )
    return text
