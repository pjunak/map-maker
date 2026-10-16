# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Polar land for the planet: coasts in true distance, and land that covers a pole.

A world drawn on a plate carrée frame breaks down near the poles. One drawing
unit east-west shrinks to a few hundred metres, so traced stair-steps become
radial streaks, and shapes that look ordinary on the flat drawing become thin
radial fingers. Land that reaches a pole along only part of the frame's edge
becomes a wedge whose tip sits exactly on the pole. The planet therefore sees
its drawn world with three polar changes (ADR-0094, ADR-0100):

* **East-west smoothing.** Along each latitude circle, the land share is smoothed
  by a Gaussian whose true width grows from nothing at ``POLAR_ZONE_DEG`` to
  ``POLAR_EAST_WEST_UNITS`` at the pole; land is where the share is at least a
  half. North-south positions stay as drawn, so do coasts the smoothing barely
  moves, and so do islets it would delete.

The other two are worked in a polar azimuthal-equidistant plane, in metres:

* **Smoothing.** Poleward of ``POLAR_ZONE_DEG``, land and water narrower than
  half a drawing unit in true distance (the drawing's north-south precision)
  are removed by an opening and a closing, so traced streaks disappear and
  corners round. Islets that would vanish keep their drawn shape.
* **Covering a pole.** If drawn land touches a pole, a cap of about
  ``POLE_CAP_DEG`` around it joins that land. Its outline has a few broad
  lobes plus a domain warp, so it reads as coast rather than a circle, and
  pockets are filled only where it meets the drawn land.

The authored world and its prepared land are unchanged. The result is a world
map with the same features and continents, and a ``pole_cover`` adjustment
for each covered pole.
"""

from functools import lru_cache
from math import pi, radians

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.affinity import translate
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from map_maker.terrain.domain.seeds import stage_seed
from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.pipeline.planet_noise import value_noise3
from map_maker.terrain.pipeline.world import (
    WorldAdjustment,
    WorldLandView,
    WorldMap,
    component_area_km2,
    components_from_geometry,
    world_from_land,
)

type F64 = NDArray[np.float64]

POLES_STAGE = "planet.poles"
POLAR_ZONE_DEG = 55.0
POLAR_MARGIN_DEG = 3.0  # extra latitude worked so the zone edge sees real coast
POLAR_SMOOTHING_UNITS = 0.25  # opening/closing radius in drawing units (at the equator)
# East-west smoothing: a Gaussian along each latitude circle whose true width grows
# from 0 at the zone edge to this many drawing units (at the equator) at the pole.
POLAR_EAST_WEST_UNITS = 4.0
POLAR_ROW_UNITS = 0.125  # scan-line spacing of the east-west smoothing
POLAR_CELL_UNITS = 0.25  # east-west cell of the smoothed land share
POLE_CAP_DEG = 4.0
CAP_LOBES = 8  # broad outline modes, amplitude ~ 1 / mode^1.3
CAP_LOBE_RANGE = 0.4  # largest log-radius excursion of the lobes
CAP_WARP_TOP = 0.5  # top warp wavelength, as a share of the cap radius
CAP_WARP_STEEPNESS = 0.25  # warp amplitude per octave, as a share of its wavelength
CAP_WARP_FINEST_M = 8_000.0
CAP_FILLET = 0.5  # pocket-filling radius where the cap meets drawn land, x cap radius


def _polygons(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty or geometry.area <= 0 else [geometry]
    if isinstance(geometry, (MultiPolygon, GeometryCollection)):
        return [p for part in geometry.geoms for p in _polygons(part)]
    return []


class _PolarPlane:
    """One pole's azimuthal-equidistant plane (metres) and the world frame."""

    def __init__(self, frame: WorldFrame, south: bool) -> None:
        self.frame = frame
        self.sign = -1.0 if south else 1.0
        self.radius_m = frame.radius_km * 1e3
        self.pole_y = frame.bounds[3] if south else frame.bounds[1]

    def lonlat(self, x: F64, y: F64) -> tuple[F64, F64]:
        f = self.frame
        lon = (x - f.bounds[0]) / f.width * 360 - 180 + f.central_meridian_deg
        return np.radians(lon), 90 - (y - f.bounds[1]) / f.height * 180

    def to_plane(self, x: F64, y: F64) -> F64:
        lon, lat = self.lonlat(x, y)
        rho = self.radius_m * np.radians(90 - self.sign * lat)
        return np.column_stack([rho * np.sin(lon), -self.sign * rho * np.cos(lon)])

    def ring_to_frame(self, xy: F64, around_pole: bool) -> Polygon:
        """A plane ring as a frame polygon; one around the pole is closed along its edge."""
        f = self.frame
        rho = np.hypot(xy[:, 0], xy[:, 1])
        lon = np.unwrap(np.arctan2(xy[:, 0], -self.sign * xy[:, 1]))
        x = f.bounds[0] + (np.degrees(lon) - f.central_meridian_deg + 180) / 360 * f.width
        y = f.bounds[1] + (90 - self.sign * (90 - np.degrees(rho / self.radius_m))) / 180 * (
            f.height
        )
        points = list(zip(x.tolist(), y.tolist(), strict=True))
        if around_pole:
            points += [(float(x[-1]), self.pole_y), (float(x[0]), self.pole_y)]
        return Polygon(points)

    def to_frame(self, polygon: Polygon) -> BaseGeometry:
        pole = Point(0.0, 0.0)
        exterior = shapely.make_valid(
            self.ring_to_frame(np.asarray(polygon.exterior.coords), polygon.contains(pole))
        )
        for hole in polygon.interiors:
            ring = np.asarray(hole.coords)
            exterior = exterior.difference(
                shapely.make_valid(self.ring_to_frame(ring, Polygon(ring).contains(pole)))
            )
        f = self.frame
        window = box(*f.bounds)
        return unary_union(
            [translate(exterior, xoff=k * f.width).intersection(window) for k in (-1, 0, 1)]
        )


def _cap(radius_m: float, seed: int) -> Polygon:
    """A pole cap of about ``radius_m`` with lobes and a warped, coast-like outline."""
    rng = np.random.default_rng(seed)
    phi = np.linspace(0, 2 * pi, 2048, endpoint=False)
    modes = np.arange(1, CAP_LOBES + 1)
    lobes = (
        (rng.normal(size=CAP_LOBES) / modes**1.3)[None, :]
        * np.cos(modes[None, :] * phi[:, None] + rng.uniform(0, 2 * pi, CAP_LOBES)[None, :])
    ).sum(axis=1)
    r = radius_m * np.exp(CAP_LOBE_RANGE * lobes / np.abs(lobes).max())
    outline = Polygon(np.column_stack([r * np.sin(phi), r * np.cos(phi)])).segmentize(
        CAP_WARP_FINEST_M / 8
    )
    xy = np.asarray(outline.exterior.coords)
    offset = np.zeros_like(xy)
    wavelength, octave = CAP_WARP_TOP * radius_m, 0
    while wavelength >= CAP_WARP_FINEST_M:
        q = np.column_stack([xy / wavelength, np.full(len(xy), 0.37 + octave)])
        for axis in range(2):
            offset[:, axis] += (
                CAP_WARP_STEEPNESS * wavelength * value_noise3(q, seed + 7 * octave + axis + 1)
            )
        wavelength /= 2
        octave += 1
    cap = max(_polygons(shapely.make_valid(Polygon(xy + offset))), key=lambda p: p.area)
    return Polygon(cap.exterior)


def _polar_strip(plane: _PolarPlane, zone_deg: float = POLAR_ZONE_DEG) -> Polygon:
    f = plane.frame
    edge_y = f.bounds[1] + (90 - plane.sign * zone_deg) / 180 * f.height
    return box(f.bounds[0], min(edge_y, plane.pole_y), f.bounds[2], max(edge_y, plane.pole_y))


def _touches_pole_partly(drawn: BaseGeometry, plane: _PolarPlane) -> bool:
    """Land meets the pole's frame edge, but not all along it (so the pole is a wedge tip)."""
    f = plane.frame
    edge = LineString([(f.bounds[0], plane.pole_y), (f.bounds[2], plane.pole_y)])
    touching = drawn.intersection(edge).length
    return f.geometry_tolerance < touching < f.width - f.geometry_tolerance


def _smoothed(land: BaseGeometry, radius_m: float) -> BaseGeometry:
    """Opening then closing: removes land and water narrower than twice ``radius_m``.

    Islets the opening would delete entirely keep their drawn shape.
    """
    smooth = land.buffer(-radius_m).buffer(radius_m).buffer(radius_m).buffer(-radius_m)
    shapely.prepare(smooth)
    kept = [p for p in _polygons(land) if not smooth.intersects(p)]
    return unary_union([smooth, *kept])


def _ring_edges(land: BaseGeometry) -> F64:
    """Every ring edge of ``land`` as rows of (x0, y0, x1, y1)."""
    edges = [
        np.column_stack([xy[:-1], xy[1:]])
        for polygon in _polygons(land)
        for xy in (np.asarray(ring.coords) for ring in (polygon.exterior, *polygon.interiors))
    ]
    return np.concatenate(edges) if edges else np.zeros((0, 4))


def _row_share(edges: F64, y: float, x0: float, cell: float, columns: int) -> F64:
    """Share of land in each cell along the line at height ``y`` (exact, even-odd rule)."""
    crossing = (edges[:, 1] <= y) != (edges[:, 3] <= y)
    e = edges[crossing]
    x = np.sort(e[:, 0] + (y - e[:, 1]) * (e[:, 2] - e[:, 0]) / (e[:, 3] - e[:, 1]))
    starts = np.clip((x[0::2] - x0) / cell, 0, columns)
    ends = np.clip((x[1::2] - x0) / cell, 0, columns)
    bounds = np.arange(columns + 1, dtype=np.float64)

    def ramps(points: F64) -> F64:
        # Sum of max(bound - point, 0) over the (sorted) points, at every cell bound.
        below = np.searchsorted(points, bounds)
        return bounds * below - np.concatenate(([0.0], np.cumsum(points)))[below]

    return np.diff(ramps(starts) - ramps(ends))


def _land_runs(share: F64, x0: float, cell: float) -> list[tuple[float, float]]:
    """Where a periodic row of cell shares is at least a half, as (start, end) x runs.

    Shares are linear between cell centres; a run may end past the row's end (wraps).
    """
    columns = len(share)
    up = share >= 0.5
    if up.all():
        return [(x0, x0 + columns * cell)]
    if not up.any():
        return []
    change = np.flatnonzero(up != np.roll(up, -1))
    after = np.roll(share, -1)[change]
    x = x0 + (change + 0.5 + (share[change] - 0.5) / (share[change] - after)) * cell
    rising = ~up[change]
    first = int(np.argmax(rising))
    x, rising = np.roll(x, -first), np.roll(rising, -first)
    width = columns * cell
    return [(s, e if e > s else e + width) for s, e in zip(x[0::2], x[1::2], strict=True)]


def _east_west_smoothed(land: BaseGeometry, plane: _PolarPlane) -> BaseGeometry:
    """Polar land with east-west detail smoothed in true distance.

    A drawing unit east-west is cos(latitude) of a unit north-south, so shapes that
    look ordinary on the flat drawing become thin radial fingers near a pole. Along
    each latitude circle the land share is smoothed by a Gaussian whose true width
    grows from nothing at the polar zone edge to POLAR_EAST_WEST_UNITS at the pole,
    and land is where the share is at least a half. North-south positions stay as
    drawn, and so does the drawn coast wherever smoothing moves it by less than a
    scan line. Islets that smoothing would delete keep their drawn shape.
    """
    f = plane.frame
    x0, x1 = f.bounds[0], f.bounds[2]
    width, row = f.width, POLAR_ROW_UNITS
    columns = round(width / POLAR_CELL_UNITS)
    cell = width / columns
    y0, y1 = sorted(_polar_strip(plane, POLAR_ZONE_DEG).bounds[1::2])
    ys = np.arange(y0 + row / 2, y1, row)
    lat = np.abs(90 - (ys - f.bounds[1]) / f.height * 180)
    cos = np.maximum(np.cos(np.radians(lat)), 1e-9)
    true_units = POLAR_EAST_WEST_UNITS * (1 - cos / np.cos(np.radians(POLAR_ZONE_DEG)))
    sigma = true_units / cos / cell  # in cells along each row
    smoothed = sigma >= 1.0
    if not smoothed.any():
        return land
    edges = _ring_edges(land)
    frequency = np.fft.rfftfreq(columns)
    boxes: list[Polygon] = []
    for y, s in zip(ys[smoothed], sigma[smoothed], strict=True):
        share = _row_share(edges, float(y), x0, cell, columns)
        blurred = np.fft.irfft(
            np.fft.rfft(share) * np.exp(-2 * (np.pi * s * frequency) ** 2), n=columns
        )
        for start, end in _land_runs(blurred, x0, cell):
            if start >= x1:
                start, end = start - width, end - width
            spans = [(start, min(end, x1))] + ([(x0, end - width)] if end > x1 else [])
            boxes += [box(a, y - row / 2, b, y + row / 2) for a, b in spans if b > a]
    band = box(x0, float(ys[smoothed].min() - row / 2), x1, float(ys[smoothed].max() + row / 2))
    inside = land.intersection(band)
    smooth = unary_union(boxes).intersection(band)
    # Keep the drawn coast within a scan line of the smoothed one; replace it elsewhere.
    kept = inside.intersection(smooth.buffer(row))
    added = smooth.difference(inside.buffer(row)).buffer(row).intersection(smooth)
    reshaped = unary_union([kept, added])
    islets = [p for p in _polygons(inside) if not reshaped.intersects(p)]
    return unary_union([land.difference(band), reshaped, *islets])


def _polar_land(
    drawn: BaseGeometry, plane: _PolarPlane, seed: int
) -> tuple[BaseGeometry, BaseGeometry | None]:
    """Drawn land poleward of the zone edge, smoothed and covering a touched pole.

    Returns the land and, for a covered pole, the land the cover adds (frame
    coordinates).
    """
    f = plane.frame
    # Work a little beyond the zone so its edge sees real coast, not a cut.
    reach = _polar_strip(plane, POLAR_ZONE_DEG - POLAR_MARGIN_DEG)
    reshaped = _east_west_smoothed(drawn.intersection(reach), plane)
    parts = [
        shapely.make_valid(
            Polygon(
                plane.to_plane(*np.asarray(p.exterior.coords).T),
                [plane.to_plane(*np.asarray(h.coords).T) for h in p.interiors],
            )
        )
        for p in _polygons(reshaped.segmentize(0.2))
    ]
    land = _smoothed(unary_union(parts), POLAR_SMOOTHING_UNITS * 2 * pi * plane.radius_m / f.width)
    added: BaseGeometry | None = None
    if _touches_pole_partly(drawn, plane):
        radius = plane.radius_m * radians(POLE_CAP_DEG)
        cap = _cap(radius, seed)
        joined = unary_union([land, cap])
        fillet = CAP_FILLET * radius
        # Pockets are filled only near the cap, where it meets drawn land.
        near = cap.buffer(radius)
        local = joined.intersection(near.buffer(2 * fillet))
        pockets = local.buffer(fillet).buffer(-fillet).difference(joined)
        pockets = pockets.intersection(land.buffer(0.6 * fillet)).intersection(near)
        capped = unary_union([joined, pockets])
        added = _to_frame(capped.difference(land), plane)
        land = capped
    return _to_frame(land, plane), added


def _to_frame(land: BaseGeometry, plane: _PolarPlane) -> BaseGeometry:
    framed = [plane.to_frame(p) for p in _polygons(land.segmentize(2_000.0))]
    return unary_union(framed).intersection(_polar_strip(plane))


@lru_cache(maxsize=2)
def planet_world(world: WorldMap, master_seed: int) -> WorldMap:
    """The world the planet sees: drawn land with true-distance polar coasts and covered poles."""
    f = world.project.frame
    drawn = unary_union([_union(view) for view in world.land])
    seed = stage_seed(master_seed, POLES_STAGE)
    land, strips = drawn, list[Polygon]()
    covered: list[tuple[str, _PolarPlane, BaseGeometry]] = []
    for south in (True, False):
        plane = _PolarPlane(f, south)
        strip = _polar_strip(plane)
        if drawn.intersection(strip).is_empty:
            continue
        polar, added = _polar_land(drawn, plane, seed + int(south))
        land = unary_union([land.difference(strip), polar])
        strips.append(strip)
        if added is not None:
            covered.append(("south" if south else "north", plane, added))
    if not strips:
        return world
    views = _assign(world, land, drawn, strips)
    adjustments = list(world.adjustments)
    for pole, plane, added in covered:
        km2 = sum(component_area_km2(c, f) for c in components_from_geometry(added))
        edge = LineString([(f.bounds[0], plane.pole_y), (f.bounds[2], plane.pole_y)])
        owners = tuple(v.feature_id for v in views if _union(v).intersects(edge))
        adjustments.append(
            WorldAdjustment(
                "pole_cover",
                owners,
                float(added.area),
                f"Land reaching the {pole} pole covers it on the planet ({km2:,.0f} km² added).",
            )
        )
    return world_from_land(world.project, views, tuple(adjustments))


def _union(view: WorldLandView) -> BaseGeometry:
    return unary_union([Polygon(c.exterior, c.holes) for c in view.components])


def _assign(
    world: WorldMap, land: BaseGeometry, drawn: BaseGeometry, strips: list[Polygon]
) -> tuple[WorldLandView, ...]:
    """Features in the polar strips keep their remaining land and take adjoining added land."""
    spans = [(strip.bounds[1], strip.bounds[3]) for strip in strips]

    def in_strips(view: WorldLandView) -> bool:
        for component in view.components:
            ys = [y for _, y in component.exterior]
            if any(min(ys) < y1 and max(ys) > y0 for y0, y1 in spans):
                return True
        return False

    touched = [i for i, view in enumerate(world.land) if in_strips(view)]
    geometries = [_union(world.land[i]) for i in touched]
    kept = {i: g.intersection(land) for i, g in zip(touched, geometries, strict=True)}
    extra: dict[int, list[BaseGeometry]] = {i: [] for i in touched}
    pieces = _polygons(land.difference(drawn))
    if pieces:
        zones = unary_union(strips)
        local = [g.intersection(zones) for g in geometries]
        tree = STRtree(local)
        # Smoothing leaves thousands of thin slivers beside their own coast; a point
        # finds their feature. The few large pieces (the cap) are matched whole.
        probes = [p if p.area > 1.0 else p.representative_point() for p in pieces]
        nearest = tree.query_nearest(probes, all_matches=False)
        owner = dict(zip(nearest[0].tolist(), nearest[1].tolist(), strict=True))
        for k, piece in enumerate(pieces):
            extra[touched[owner[k]]].append(piece)
    return tuple(
        WorldLandView(
            v.feature_id,
            v.continent_id,
            v.role,
            components_from_geometry(unary_union([kept[i], *extra[i]])),
        )
        if i in kept
        else v
        for i, v in enumerate(world.land)
    )
