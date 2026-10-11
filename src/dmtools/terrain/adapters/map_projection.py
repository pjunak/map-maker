# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Map projections of world-frame (equirectangular) map images.

Every map theme is rendered once on the world frame; globe and polar views
resample that image. Projections are pure functions of the image and the view,
so the same build and view always give the same picture.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy.ndimage import map_coordinates

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

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
GLOBE_DISC = 0.96  # globe diameter as a fraction of the view, leaving room for the halo


@dataclass(frozen=True, slots=True)
class MapProjection:
    """A view of the world.

    ``lon_deg``/``lat_deg`` centre a globe or a flat world. Polar views show the
    pole out to ``limit_deg`` of latitude (0 = the equator), with ``lon_deg`` at
    the bottom of a north-polar view and at the top of a south-polar one, east
    to the right as is usual.
    """

    kind: str = "equirectangular"
    lon_deg: float = 0.0
    lat_deg: float = 0.0
    limit_deg: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in PROJECTIONS:
            raise ValueError(f"Unknown projection {self.kind!r}; use one of {PROJECTIONS}.")
        if not (np.isfinite(self.lon_deg) and -90 <= self.lat_deg <= 90):
            raise ValueError("The view centre must be a finite longitude and a latitude in ±90°.")
        if not -60 <= self.limit_deg <= 80:
            raise ValueError("Polar views reach a latitude between -60° and 80°.")


def projected_lonlat(projection: MapProjection, size: int) -> tuple[F64, F64, B, F64]:
    """Longitude and latitude (degrees) of each pixel of a ``size`` square view.

    Returns (lon, lat, inside, limb) where ``limb`` is the cosine of the angle
    between the view direction and the surface normal on a globe (1 elsewhere).
    """
    centre = (np.arange(size) + 0.5) / size * 2 - 1
    x, y = np.meshgrid(centre, -centre)
    rho = np.hypot(x, y)
    inside = rho <= 1.0
    if projection.kind == "globe":
        lon0, lat0 = np.deg2rad(projection.lon_deg), np.deg2rad(projection.lat_deg)
        c = np.arcsin(np.clip(rho, 0, 1))
        safe = np.maximum(rho, 1e-12)
        lat = np.arcsin(
            np.clip(np.cos(c) * np.sin(lat0) + y * np.sin(c) * np.cos(lat0) / safe, -1, 1)
        )
        lon = lon0 + np.arctan2(
            x * np.sin(c), safe * np.cos(lat0) * np.cos(c) - y * np.sin(lat0) * np.sin(c)
        )
        return np.rad2deg(lon), np.rad2deg(lat), inside, np.cos(c)
    if projection.kind in ("north-polar", "south-polar"):
        # Azimuthal equidistant about the pole: distance from the centre is
        # proportional to the angle from the pole.
        sign = 1.0 if projection.kind == "north-polar" else -1.0
        span = 90.0 - sign * projection.limit_deg
        lat = sign * (90.0 - rho * span)
        lon = projection.lon_deg + np.rad2deg(np.arctan2(x, -sign * y))
        return lon, lat, inside, np.ones_like(rho)
    lon = projection.lon_deg + (np.arange(size * 2) + 0.5) / (size * 2) * 360 - 180
    lat = 90 - (np.arange(size) + 0.5) / size * 180
    glon, glat = np.meshgrid(lon, lat)
    return glon, glat, np.ones(glon.shape, dtype=bool), np.ones(glon.shape)


def displayed_lonlat(projection: MapProjection, size: int) -> tuple[F64, F64, B]:
    """Longitude, latitude and on-map mask of each pixel as ``reproject`` draws it."""
    lon, lat, inside, _ = projected_lonlat(projection, size)
    if projection.kind != "globe":
        return lon, lat, inside
    centre = (np.arange(size) + 0.5) / size * 2 - 1
    x, y = np.meshgrid(centre, centre)
    rows = np.clip(np.rint((y / GLOBE_DISC + 1) / 2 * size - 0.5), 0, size - 1).astype(np.intp)
    columns = np.clip(np.rint((x / GLOBE_DISC + 1) / 2 * size - 0.5), 0, size - 1).astype(np.intp)
    return lon[rows, columns], lat[rows, columns], np.hypot(x, y) <= GLOBE_DISC


def reproject(
    image: Image.Image,
    projection: MapProjection,
    size: int,
    *,
    central_meridian_deg: float = 0.0,
    graticule: bool = False,
) -> Image.Image:
    """Resample a world-frame image into ``projection``; ``size`` is the output height."""
    if size < 16:
        raise ValueError("Views need at least 16 pixels.")
    source = np.asarray(image.convert("RGB"), dtype=np.float64)
    rows, columns = source.shape[:2]
    lon, lat, inside, limb = projected_lonlat(projection, size)
    column = ((lon - central_meridian_deg + 180) % 360) / 360 * columns - 0.5
    row = np.clip((90 - lat) / 180 * rows - 0.5, 0, rows - 1)
    rgb = np.stack(
        [
            map_coordinates(source[..., k], (row, column), order=1, mode="grid-wrap")
            for k in range(3)
        ],
        axis=-1,
    )
    if graticule:
        rgb = _graticule(rgb, lon, lat)
    if projection.kind == "globe":
        # Gentle limb darkening and a thin atmosphere make the sphere read.
        rgb = rgb * (0.55 + 0.45 * np.sqrt(np.clip(limb, 0, 1)))[..., None]
        rgb = _with_halo(rgb, size)
    elif projection.kind != "equirectangular":
        rgb = np.where(inside[..., None], rgb, np.asarray(SPACE, dtype=np.float64))
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def _graticule(rgb: F64, lon: F64, lat: F64) -> F64:
    """Lines of latitude and longitude every GRATICULE_STEP_DEG, about a pixel wide."""
    step = GRATICULE_STEP_DEG
    d_lat = np.abs(lat - np.round(lat / step) * step)
    d_lon = np.abs(((lon + 180) % 360 - 180) - np.round(((lon + 180) % 360 - 180) / step) * step)
    # Degrees per pixel from the local gradients, so lines stay thin everywhere.
    lat_rows, lat_columns = np.gradient(lat)
    lon_rows, lon_columns = np.gradient((lon + 180) % 360)
    lat_px = np.hypot(lat_rows, lat_columns)
    lon_px = np.hypot(lon_rows, lon_columns)
    lon_px = np.where(lon_px > 90, np.nan, lon_px)  # wrap seam
    near_pole = np.abs(lat) > 89.0
    line = (d_lat < 0.6 * np.maximum(lat_px, 1e-6)) | (
        (d_lon < 0.6 * np.nan_to_num(lon_px, nan=0.0)) & ~near_pole
    )
    alpha = 0.45 * line[..., None]
    return rgb * (1 - alpha) + np.asarray(GRATICULE, dtype=np.float64) * alpha


def _with_halo(rgb: F64, size: int) -> F64:
    centre = (np.arange(size) + 0.5) / size * 2 - 1
    x, y = np.meshgrid(centre, centre)
    rho = np.hypot(x, y) / GLOBE_DISC
    glow = np.clip(1 - (rho - 1) / 0.04, 0, 1) * (rho > 1)
    space = np.asarray(SPACE, dtype=np.float64) + glow[..., None] * (
        np.asarray(HALO, dtype=np.float64) - np.asarray(SPACE, dtype=np.float64)
    ) * 0.6
    # Shrink the globe to GLOBE_DISC of the frame by resampling the disc.
    scale = 1 / GLOBE_DISC
    rows = np.clip(((y * scale) + 1) / 2 * size - 0.5, 0, size - 1)
    columns = np.clip(((x * scale) + 1) / 2 * size - 0.5, 0, size - 1)
    disc = np.stack(
        [map_coordinates(rgb[..., k], (rows, columns), order=1, mode="nearest") for k in range(3)],
        axis=-1,
    )
    within = rho <= 1.0
    return np.where(within[..., None], disc, space)
