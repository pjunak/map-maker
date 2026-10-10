# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Topographic map: hypsometric tints, contour lines, soft hillshade and water.

Works on any regular grid of the display relief: the world frame (rows of
varying east-west pixel size) or a regional window (square pixels).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy.ndimage import gaussian_filter

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

LAND_TINTS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (166, 204, 160)),
    (200.0, (150, 192, 142)),
    (500.0, (190, 206, 150)),
    (1000.0, (228, 228, 178)),
    (1500.0, (226, 212, 160)),
    (2000.0, (206, 184, 130)),
    (3000.0, (176, 142, 102)),
    (4000.0, (152, 118, 92)),
    (5000.0, (212, 208, 204)),
    (6500.0, (250, 250, 250)),
)
SEA_TINTS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (-8000.0, (62, 112, 168)),
    (-5000.0, (92, 146, 200)),
    (-3000.0, (124, 178, 226)),
    (-1000.0, (160, 208, 244)),
    (-200.0, (186, 226, 252)),
    (0.0, (206, 236, 254)),
)
CONTOUR: tuple[int, int, int] = (128, 84, 48)
ISOBATH: tuple[int, int, int] = (70, 120, 180)
COAST: tuple[int, int, int] = (30, 70, 120)
WATER: tuple[int, int, int] = (150, 200, 240)
RIVER: tuple[int, int, int] = (40, 100, 200)
ICE: tuple[int, int, int] = (244, 248, 252)
PLAYA: tuple[int, int, int] = (238, 230, 210)
OUTSIDE: tuple[int, int, int] = (255, 255, 255)
NICE_INTERVALS_M = (10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0)
INDEX_EVERY = 5
CONTOUR_SMOOTH_PX = 1.5
LOCAL_TINT_SPAN_M = 3500.0  # local maps spread their height range over these tints


def contour_interval_m(pixel_m: float) -> float:
    """A conventional contour interval for a map of ``pixel_m`` ground pixels."""
    target = pixel_m / 12
    return min(NICE_INTERVALS_M, key=lambda step: abs(np.log(step / target)))


def topographic_image(
    elevation_m: F64,
    land: B,
    lakes: B,
    rivers: F64,
    light: F64,
    dy_m: float,
    dx_m: F64 | float,
    ice: B | None = None,
    *,
    local: bool = False,
    playa: B | None = None,
) -> Image.Image:
    """The map image; ``elevation_m`` may hold NaN outside the mapped area.

    ``local`` stretches the land tints over the map's own height range (as local
    topographic maps do), so a high plateau is not one flat brown; contours stay
    at true heights.
    """
    inside = np.isfinite(elevation_m)
    z = np.where(inside, elevation_m, 0.0)
    dx = np.broadcast_to(np.asarray(dx_m, dtype=np.float64).reshape(-1, 1), z.shape)
    pixel_m = float(np.sqrt(dy_m * np.median(dx)))
    tinted = z
    if local and (land & inside).any():
        low, high = np.percentile(z[land & inside], [2, 98])
        tinted = np.where(land, (z - low) / max(high - low, 50.0) * LOCAL_TINT_SPAN_M, z)
    tint = np.where(land[..., None], _ramp(tinted, LAND_TINTS), _ramp(z, SEA_TINTS))
    if ice is not None:
        tint = np.where((ice & land)[..., None], np.array(ICE, dtype=np.float64), tint)
    rgb = tint * (0.72 + 0.28 * np.clip(light, 0, 1.5))[..., None]
    interval = contour_interval_m(pixel_m)
    # Contours follow the landform, not sub-pixel texture: smooth over a few pixels.
    smooth = gaussian_filter(z, CONTOUR_SMOOTH_PX)
    rgb = _contours(rgb, smooth, land, interval, dy_m, dx, CONTOUR, 0.55)
    rgb = _contours(rgb, smooth, ~land, 2 * interval * INDEX_EVERY, dy_m, dx, ISOBATH, 0.35)
    rgb = np.where(lakes[..., None] & land[..., None], np.array(WATER, dtype=np.float64), rgb)
    if playa is not None:
        # Dry lake beds: pale ground inside a dashed shore.
        rgb = np.where(playa[..., None], np.array(PLAYA, dtype=np.float64), rgb)
        rows, columns = z.shape
        dashes = (np.arange(columns)[None, :] // 3 + np.arange(rows)[:, None] // 3) % 2 == 0
        rgb[_edges(playa) & dashes] = WATER
    coast = _edges(land & ~lakes)
    rgb[coast] = COAST
    alpha = (0.9 * np.clip(rivers, 0, 1))[..., None]
    rgb = rgb * (1 - alpha) + np.array(RIVER, dtype=np.float64) * alpha
    rgb = np.where(inside[..., None], rgb, np.array(OUTSIDE, dtype=np.float64))
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def _contours(
    rgb: F64,
    z: F64,
    mask: B,
    interval: float,
    dy_m: float,
    dx: F64,
    colour: tuple[int, int, int],
    strength: float,
) -> F64:
    """Anti-aliased contour lines; index contours (every INDEX_EVERY) are bolder."""
    gy = np.gradient(z, axis=0) / dy_m
    gx = (np.roll(z, -1, 1) - np.roll(z, 1, 1)) / (2 * dx)
    # Height change per pixel, so line width is measured in pixels.
    per_pixel = np.hypot(gx * dx, gy * dy_m) + 1e-6
    out = rgb
    for step, width, weight in ((interval, 0.6, 1.0), (interval * INDEX_EVERY, 1.0, 1.6)):
        offset = np.abs(((z / step) + 0.5) % 1.0 - 0.5) * step
        distance_px = offset / per_pixel
        line = np.clip(1 - distance_px / width, 0, 1)
        # Where lines crowd closer than ~3 pixels only index contours stay legible.
        spacing_px = step / per_pixel
        line *= np.clip((spacing_px - 1.5) / 2.0, 0, 1)
        alpha = (strength * min(weight, 1.6) * line * mask)[..., None]
        alpha = np.clip(alpha, 0, 0.9)
        out = out * (1 - alpha) + np.array(colour, dtype=np.float64) * alpha
    return out


def _ramp(z: F64, stops: tuple[tuple[float, tuple[int, int, int]], ...]) -> F64:
    knots = np.array([h for h, _ in stops])
    return np.stack([np.interp(z, knots, [c[k] for _, c in stops]) for k in range(3)], axis=-1)


def _edges(mask: B) -> B:
    edge = mask != np.roll(mask, -1, axis=1)
    edge[:-1] |= mask[:-1] != mask[1:]
    return edge
