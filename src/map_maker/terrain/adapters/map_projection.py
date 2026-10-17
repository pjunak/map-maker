"""Map projections of world-frame (equirectangular) map images.

Every map theme is rendered once on the world frame; flat, globe and polar views
resample that image. ``MapTexture`` prepares an image once (latitude prefilter
and mip levels) and ``render`` draws any view of it at any size with compiled
kernels (``pipeline.sphere_views``), fast enough to turn a globe interactively.
Projections are pure functions of the image and the view, so the same build and
view always give the same picture.

The screen functions (``screen_lonlat``, ``lonlat_screen``, ``grab``, ``zoomed``)
use the same geometry analytically, so hover read-outs, overlays and dragging
agree with the drawn pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import acos, asin, atan2, cos, degrees, hypot, pi, radians, sin, sqrt

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from map_maker.terrain.pipeline.sphere_views import (
    globe_points,
    latitude_prefilter,
    polar_points,
    sample_view,
)

type F64 = NDArray[np.float64]
type Size = tuple[int, int]
type Point = tuple[float, float]

PROJECTIONS = ("equirectangular", "globe", "north-polar", "south-polar")
PROJECTION_LABELS = {
    "equirectangular": "Flat world",
    "globe": "Globe",
    "north-polar": "North polar",
    "south-polar": "South polar",
}
SPACE: tuple[int, int, int] = (10, 14, 24)
HALO: tuple[int, int, int] = (110, 160, 230)
GRATICULE: tuple[int, int, int] = (235, 235, 225)
GRATICULE_STEP_DEG = 30.0
GLOBE_DISC = 0.96  # globe diameter at zoom 1 as a fraction of the view, leaving room for the halo
MAX_GLOBE_ZOOM = 16.0
SMALLEST_LEVEL_ROWS = 4


@dataclass(frozen=True, slots=True)
class MapProjection:
    """A view of the world.

    ``lon_deg``/``lat_deg`` centre a globe or a flat world, with north up. A
    globe's ``zoom`` enlarges it beyond the whole disc (1). Polar views show the
    pole out to ``limit_deg`` of latitude (0 = the equator), with ``lon_deg`` at
    the bottom of a north-polar view and at the top of a south-polar one, east
    to the right as is usual.
    """

    kind: str = "equirectangular"
    lon_deg: float = 0.0
    lat_deg: float = 0.0
    limit_deg: float = 0.0
    zoom: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in PROJECTIONS:
            raise ValueError(f"Unknown projection {self.kind!r}; use one of {PROJECTIONS}.")
        if not (np.isfinite(self.lon_deg) and -90 <= self.lat_deg <= 90):
            raise ValueError("The view centre must be a finite longitude and a latitude in ±90°.")
        if not -60 <= self.limit_deg <= 80:
            raise ValueError("Polar views reach a latitude between -60° and 80°.")
        if not 1 <= self.zoom <= MAX_GLOBE_ZOOM or (self.kind != "globe" and self.zoom != 1):
            raise ValueError(f"Only a globe zooms, from 1 to {MAX_GLOBE_ZOOM:g} times.")

    @property
    def polar_sign(self) -> float:
        return 1.0 if self.kind == "north-polar" else -1.0

    @property
    def polar_span_deg(self) -> float:
        """Angle from the pole to the edge of a polar view."""
        return 90.0 - self.polar_sign * self.limit_deg


@dataclass(frozen=True, slots=True, eq=False)
class MapTexture:
    """A world-frame image prepared for views: filtered for latitude and mip-mapped.

    ``data`` packs every level (RGB rows, largest first); level ``i`` starts at
    ``offsets[i]``. ``west_deg`` is the longitude of the image's left edge.
    """

    data: NDArray[np.uint8]
    offsets: NDArray[np.int64]
    widths: NDArray[np.int64]
    heights: NDArray[np.int64]
    west_deg: float

    @staticmethod
    def from_image(image: Image.Image, central_meridian_deg: float = 0.0) -> MapTexture:
        rgb = np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))
        level = Image.fromarray(latitude_prefilter(rgb))
        levels = [level]
        while level.height > SMALLEST_LEVEL_ROWS:
            level = level.reduce(2)
            levels.append(level)
        arrays = [np.asarray(level, dtype=np.uint8).ravel() for level in levels]
        offsets = np.cumsum([0, *(array.size for array in arrays[:-1])], dtype=np.int64)
        return MapTexture(
            np.concatenate(arrays), offsets,
            np.array([level.width for level in levels], dtype=np.int64),
            np.array([level.height for level in levels], dtype=np.int64),
            central_meridian_deg - 180.0,
        )


def view_radius(projection: MapProjection, size: Size) -> float:
    """Pixels from the centre of a globe or polar view to its rim."""
    short = float(min(size))
    if projection.kind == "globe":
        return GLOBE_DISC / 2 * short * projection.zoom
    return short / 2


def render(
    texture: MapTexture, projection: MapProjection, size: Size, *, graticule: bool = False
) -> Image.Image:
    """``texture`` drawn in ``projection`` on a view of ``size`` (width, height) pixels."""
    width, height = size
    if width < 1 or height < 1:
        raise ValueError("Views need at least one pixel.")
    lon = np.empty((height, width))
    lat = np.empty((height, width))
    cover = np.ones((height, width), dtype=np.float32)
    light = np.ones((height, width), dtype=np.float32)
    glow = np.zeros((height, width), dtype=np.float32)
    if projection.kind == "globe":
        globe_points(width, height, view_radius(projection, size), _basis(projection),
                     lon, lat, cover, light, glow)
    elif projection.kind != "equirectangular":
        polar_points(width, height, view_radius(projection, size), projection.polar_sign,
                     projection.lon_deg, projection.polar_span_deg, lon, lat, cover, light, glow)
    else:
        lon[:] = projection.lon_deg + (np.arange(width) + 0.5) / width * 360 - 180
        lat[:] = (90 - (np.arange(height) + 0.5) / height * 180)[:, None]
    out = np.empty((height, width, 3), dtype=np.uint8)
    colours = np.array((SPACE, HALO, GRATICULE), dtype=np.float64)
    sample_view(lon, lat, cover, light, glow, texture.data, texture.offsets, texture.widths,
                texture.heights, texture.west_deg, GRATICULE_STEP_DEG if graticule else 0.0,
                colours, out)
    return Image.fromarray(out)


def reproject(
    image: Image.Image,
    projection: MapProjection,
    size: int,
    *,
    central_meridian_deg: float = 0.0,
    graticule: bool = False,
) -> Image.Image:
    """A world-frame image shown in ``projection``; ``size`` is the output height.

    Globe and polar views are square; a flat world is twice as wide as high.
    """
    if size < 16:
        raise ValueError("Views need at least 16 pixels.")
    width = 2 * size if projection.kind == "equirectangular" else size
    texture = MapTexture.from_image(image, central_meridian_deg)
    return render(texture, projection, (width, size), graticule=graticule)


def screen_lonlat(projection: MapProjection, size: Size, x: float, y: float) -> Point | None:
    """Longitude and latitude (degrees) at view position (x, y), or None off the map.

    Positions are in pixels from the view's top-left corner; pixel centres are
    at half-pixel positions.
    """
    width, height = size
    if projection.kind == "equirectangular":
        if not (0 <= x <= width and 0 <= y <= height):
            return None
        return _wrap(projection.lon_deg + x / width * 360 - 180), 90 - y / height * 180
    radius = view_radius(projection, size)
    sx, sy = (x - width / 2) / radius, (height / 2 - y) / radius
    rho = hypot(sx, sy)
    if rho > 1:
        return None
    if projection.kind == "globe":
        sz = sqrt(max(0.0, 1 - rho * rho))
        right, up, toward = _basis(projection)
        vector = sx * right + sy * up + sz * toward
        return (_wrap(degrees(atan2(vector[1], vector[0]))),
                degrees(asin(max(-1.0, min(1.0, float(vector[2]))))))
    sign = projection.polar_sign
    lat = sign * (90 - rho * projection.polar_span_deg)
    return _wrap(projection.lon_deg + degrees(atan2(sx, -sign * sy))), lat


def lonlat_screen(projection: MapProjection, size: Size, lon: float, lat: float) -> Point | None:
    """View position of a longitude and latitude, or None where the view hides it."""
    width, height = size
    if projection.kind == "equirectangular":
        return ((lon - projection.lon_deg + 180) % 360 / 360 * width,
                (90 - lat) / 180 * height)
    radius = view_radius(projection, size)
    if projection.kind == "globe":
        right, up, toward = _basis(projection)
        point = _unit(lon, lat)
        if float(point @ toward) < 0:
            return None
        return width / 2 + float(point @ right) * radius, height / 2 - float(point @ up) * radius
    sign = projection.polar_sign
    rho = (90 - sign * lat) / projection.polar_span_deg
    if rho > 1:
        return None
    theta = radians(lon - projection.lon_deg)
    return width / 2 + rho * sin(theta) * radius, height / 2 + sign * rho * cos(theta) * radius


def grab(
    projection: MapProjection, size: Size, lonlat: Point, x: float, y: float
) -> MapProjection | None:
    """The view that puts ``lonlat`` under view position (x, y), north up, same zoom.

    Dragging uses it so the ground under the cursor follows the cursor. A globe
    turns about its centre (the nearest of the up to four solutions); a polar
    view turns about the pole. None where no such view exists, such as a pole
    dragged sideways on a north-up globe.
    """
    width, height = size
    if projection.kind == "equirectangular":
        return None
    radius = view_radius(projection, size)
    sx, sy = (x - width / 2) / radius, (height / 2 - y) / radius
    if hypot(sx, sy) > 1:
        return None
    lam, phi = radians(lonlat[0]), radians(lonlat[1])
    if projection.kind != "globe":
        sign = projection.polar_sign
        return replace(projection, lon_deg=_wrap(lonlat[0] - degrees(atan2(sx, -sign * sy))))
    # Screen x = cos φ sin(λ - λ0) and y = sin φ cos φ0 - cos φ cos(λ - λ0) sin φ0.
    lam0, phi0 = radians(projection.lon_deg), radians(projection.lat_deg)
    if cos(phi) < 1e-9:
        if abs(sx) > 1e-9:
            return None
        turns = [lam - lam0]
    else:
        s = sx / cos(phi)
        if abs(s) > 1:
            return None
        turns = [asin(s), pi - asin(s)]
    best: tuple[float, float, float] | None = None
    for turn in turns:
        a, b = sin(phi), cos(phi) * cos(turn)
        r = hypot(a, b)
        if r < 1e-12 or abs(sy) > r:
            continue
        offset = atan2(b, a)
        for branch in (acos(sy / r), -acos(sy / r)):
            centre_lat = (branch - offset + pi) % (2 * pi) - pi
            if abs(centre_lat) > pi / 2 + 1e-12:
                continue
            facing = cos(centre_lat) * b + sin(centre_lat) * a
            if facing < -1e-9:
                continue
            centre_lon = lam - turn
            moved = _angle(lam0, phi0, centre_lon, centre_lat)
            if best is None or moved < best[0]:
                best = (moved, centre_lon, centre_lat)
    if best is None:
        return None
    return replace(projection, lon_deg=_wrap(degrees(best[1])),
                   lat_deg=max(-90.0, min(90.0, degrees(best[2]))))


def zoomed(
    projection: MapProjection, size: Size, factor: float, x: float, y: float
) -> MapProjection:
    """``projection`` zoomed in by ``factor`` (below 1 zooms out).

    A globe keeps the ground under (x, y) in place; a polar view zooms about
    its pole, between 30° and 150° from it.
    """
    if projection.kind == "globe":
        zoom = min(MAX_GLOBE_ZOOM, max(1.0, projection.zoom * factor))
        target = replace(projection, zoom=zoom)
        under = screen_lonlat(projection, size, x, y)
        moved = None if under is None else grab(target, size, under, x, y)
        return moved or target
    if projection.kind == "equirectangular":
        return projection
    span = min(150.0, max(30.0, projection.polar_span_deg / factor))
    return replace(projection, limit_deg=projection.polar_sign * (90.0 - span))


def _basis(projection: MapProjection) -> F64:
    """World directions of a globe view's right, up and towards-the-viewer axes."""
    lam, phi = radians(projection.lon_deg), radians(projection.lat_deg)
    return np.array((
        (-sin(lam), cos(lam), 0.0),
        (-sin(phi) * cos(lam), -sin(phi) * sin(lam), cos(phi)),
        (cos(phi) * cos(lam), cos(phi) * sin(lam), sin(phi)),
    ))


def _unit(lon: float, lat: float) -> F64:
    lam, phi = radians(lon), radians(lat)
    return np.array((cos(phi) * cos(lam), cos(phi) * sin(lam), sin(phi)))


def _angle(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    """Great-circle angle between two points given in radians."""
    c = sin(lat_a) * sin(lat_b) + cos(lat_a) * cos(lat_b) * cos(lon_a - lon_b)
    return acos(max(-1.0, min(1.0, c)))


def _wrap(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0
