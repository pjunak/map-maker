# pyright: reportArgumentType=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Compiled per-pixel kernels that show a world-frame image as a globe, polar or flat view.

A view is drawn in two passes. A projection pass gives every pixel the longitude
and latitude at its centre, how much of the pixel lies on the map (anti-aliased
rims) and a brightness. A sampling pass then reads the texture there. Like a
GPU, it takes the footprint of each pixel from the differences to its
neighbours, measures it on the sphere and blends the two mip levels that match
it, so coasts neither shimmer when far away nor alias near the limb or a pole.

The texture is an equirectangular pyramid (``latitude_prefilter`` and the
adapter's mip levels). Regional images can be draped over it: each is an
azimuthal equidistant square around its centre with its own pyramid, shown
inside its circle where the pixel footprint is finer than the world texture,
and the deepest wins. All kernels are deterministic: every pixel is computed
independently of the thread that computes it.
"""

from collections.abc import Callable
from math import asin, atan2, cos, floor, log2, nan, pi, sin, sqrt
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

type F64 = NDArray[np.float64]
type F32 = NDArray[np.float32]
type I64 = NDArray[np.int64]
type U8 = NDArray[np.uint8]

if TYPE_CHECKING:
    prange = range

    def njit[T: Callable[..., Any]](*_args: object, **_kwargs: object) -> Callable[[T], T]:
        return lambda function: function
else:
    from numba import njit, prange

DEG = 180.0 / pi
RIM = 0.999999  # rim pixels sample just inside the disc
# Box-filtered mip levels blended linearly blur more than they need to; sampling
# half a level finer is the usual compromise between softness and shimmer.
LEVEL_BIAS = 0.5
# A draped regional image fades into the map below it over this outer share of
# its radius.
DRAPE_FADE = 0.04
# Drapes appear where a pixel covers less than one world texel, where the world
# texture starts to be magnified, and replace it fully from half a texel. Coarser
# pixels skip them and are drawn exactly as without drapes.
DETAIL_START = 1.0
DETAIL_FULL = 0.5
# Columns of a drape's frame: its centre, east and north unit vectors, its
# angular radius and that radius's cosine, then the latitude range, central
# longitude and longitude half-width (degrees) of a box around its circle.
FRAME_COLUMNS = 15


@njit(cache=True, parallel=True, nogil=True)
def latitude_prefilter(image: U8) -> U8:
    """Blur each row east-west over the same ground distance as one row spans north-south.

    An equirectangular row at latitude φ holds 1/cos φ times more pixels per
    kilometre east-west than north-south. Averaging each pixel over a box
    1/cos φ pixels wide (exactly, as the integral of the piecewise-constant
    row, wrapping at the seam) makes the image equally sharp in both directions
    on the sphere, so one isotropic mip level per pixel suits it everywhere.
    """
    rows, columns, channels = image.shape
    out = np.empty_like(image)
    for row in prange(rows):
        lat = (0.5 - (row + 0.5) / rows) * pi
        width = min(float(columns), 1.0 / max(cos(lat), 1e-12))
        if width <= 1.0:
            out[row] = image[row]
            continue
        prefix = np.zeros((columns + 1, channels))
        for column in range(columns):
            for k in range(channels):
                prefix[column + 1, k] = prefix[column, k] + image[row, column, k]
        half = 0.5 * width
        for column in range(columns):
            centre = column + 0.5
            for k in range(channels):
                total = _integral(prefix, image, row, k, columns, centre + half) - _integral(
                    prefix, image, row, k, columns, centre - half
                )
                out[row, column, k] = _byte(total / width)
    return out


@njit(cache=True, inline="always")
def _integral(prefix: F64, image: U8, row: int, k: int, columns: int, x: float) -> float:
    """Integral of the periodic row from 0 to ``x`` (pixels)."""
    turns = floor(x / columns)
    t = x - turns * columns
    index = min(int(t), columns - 1)
    return (
        turns * prefix[columns, k] + prefix[index, k] + (t - index) * float(image[row, index, k])
    )


@njit(cache=True, parallel=True, nogil=True)
def fill_beyond_disc(image: U8) -> U8:
    """A square image with its corners outside the inscribed disc filled from inside.

    A regional window's image is a disc in a square. Every pixel at or beyond
    its outermost ring takes the colour a pixel and a half inside the rim on
    the same radius, so neither mip levels nor bilinear samples near the rim
    mix in the colour drawn outside.
    """
    size = image.shape[0]
    half = 0.5 * size
    inner = max(0.0, half - 1.5)
    out = image.copy()
    for i in prange(size):
        y = i + 0.5 - half
        for j in range(size):
            x = j + 0.5 - half
            rho = sqrt(x * x + y * y)
            if rho <= half - 1.0:
                continue
            scale = inner / rho
            source_i = min(size - 1, max(0, floor(half + y * scale)))
            source_j = min(size - 1, max(0, floor(half + x * scale)))
            out[i, j] = image[source_i, source_j]
    return out


@njit(cache=True, parallel=True, nogil=True)
def globe_points(
    width: int, height: int, radius: float, basis: F64,
    lon: F64, lat: F64, cover: F32, light: F32, glow: F32,
) -> None:
    """An orthographic globe of ``radius`` pixels centred in the view.

    ``basis`` rows are the world directions of the view's right, up and
    towards-the-viewer axes. The limb is darkened and a thin atmosphere glows
    outside the rim; both scale with the globe.
    """
    cx, cy = 0.5 * width, 0.5 * height
    for i in prange(height):
        for j in range(width):
            x = (j + 0.5 - cx) / radius
            y = (cy - (i + 0.5)) / radius
            rho = sqrt(x * x + y * y)
            cover[i, j] = min(1.0, max(0.0, (1.0 - rho) * radius + 0.5))
            glow[i, j] = min(1.0, max(0.0, 1.0 - (rho - 1.0) / 0.04)) if rho > 1.0 else 0.0
            if cover[i, j] <= 0.0:
                lon[i, j] = nan
                lat[i, j] = nan
                light[i, j] = 1.0
                continue
            if rho > RIM:
                x, y, rho = x * RIM / rho, y * RIM / rho, RIM
            z = sqrt(max(0.0, 1.0 - rho * rho))
            px = x * basis[0, 0] + y * basis[1, 0] + z * basis[2, 0]
            py = x * basis[0, 1] + y * basis[1, 1] + z * basis[2, 1]
            pz = x * basis[0, 2] + y * basis[1, 2] + z * basis[2, 2]
            lat[i, j] = asin(min(1.0, max(-1.0, pz))) * DEG
            lon[i, j] = atan2(py, px) * DEG
            light[i, j] = 0.55 + 0.45 * sqrt(z)


@njit(cache=True, parallel=True, nogil=True)
def polar_points(
    width: int, height: int, radius: float, sign: float, lon0: float, span: float,
    lon: F64, lat: F64, cover: F32, light: F32, glow: F32,
) -> None:
    """An azimuthal equidistant view of the north (``sign`` 1) or south (-1) pole.

    The pole is at the centre and ``span`` degrees from it at ``radius``
    pixels; ``lon0`` is the meridian below a north-polar and above a
    south-polar view, with east to the right.
    """
    cx, cy = 0.5 * width, 0.5 * height
    for i in prange(height):
        for j in range(width):
            x = (j + 0.5 - cx) / radius
            y = (cy - (i + 0.5)) / radius
            rho = sqrt(x * x + y * y)
            cover[i, j] = min(1.0, max(0.0, (1.0 - rho) * radius + 0.5))
            glow[i, j] = 0.0
            light[i, j] = 1.0
            if cover[i, j] <= 0.0:
                lon[i, j] = nan
                lat[i, j] = nan
                continue
            lat[i, j] = sign * (90.0 - min(rho, 1.0) * span)
            lon[i, j] = lon0 + atan2(x, -sign * y) * DEG


@njit(cache=True, parallel=True, nogil=True)
def sample_view(
    lon: F64, lat: F64, cover: F32, light: F32, glow: F32,
    data: U8, offsets: I64, widths: I64, heights: I64, west_deg: float,
    drape_data: U8, drape_offsets: I64, drape_sizes: I64, drape_levels: I64,
    drape_frames: F64,
    graticule_deg: float, colours: F64, out: U8,
) -> None:
    """Colour every pixel from the texture pyramid and drapes, with a graticule and background.

    ``west_deg`` is the longitude of the texture's left edge. Drape ``k`` has
    its square levels ``drape_levels[k, 0]`` onwards (``drape_levels[k, 1]`` of
    them) in ``drape_data``, laid out like the texture's, and its geometry in
    row ``k`` of ``drape_frames`` (``FRAME_COLUMNS``); later drapes lie over
    earlier ones. ``colours`` rows are the space, atmosphere and graticule
    colours. A ``graticule_deg`` of 0 draws no grid.
    """
    height, width = lon.shape
    top_level = offsets.size - 1.0
    texels_per_degree = heights[0] / 180.0
    drapes = drape_levels.shape[0]
    for i in prange(height):
        for j in range(width):
            c = cover[i, j]
            red = green = blue = 0.0
            if c > 0.0:
                lon_x, lat_x, has_x = _difference(lon, lat, cover, i, j, 0, 1)
                lon_y, lat_y, has_y = _difference(lon, lat, cover, i, j, 1, 0)
                if not has_x:
                    lon_x, lat_x = lon_y, lat_y
                if not has_y:
                    lon_y, lat_y = lon_x, lat_x
                phi = lat[i, j]
                cos_phi = cos(phi / DEG)
                ground_x = sqrt((lon_x * cos_phi) ** 2 + lat_x * lat_x)
                ground_y = sqrt((lon_y * cos_phi) ** 2 + lat_y * lat_y)
                ground = max(ground_x, ground_y)  # degrees of arc
                footprint = ground * texels_per_degree
                share = 0.0  # of the pixel shown by drapes
                if drapes > 0 and footprint < DETAIL_START:
                    red, green, blue, share = _drapes(
                        lon[i, j], phi, cos_phi, ground / DEG, drape_data, drape_offsets,
                        drape_sizes, drape_levels, drape_frames,
                    )
                    detail = min(1.0, (DETAIL_START - footprint) / (DETAIL_START - DETAIL_FULL))
                    red, green, blue, share = (
                        detail * red, detail * green, detail * blue, detail * share
                    )
                if share < 1.0:
                    level = 0.0
                    if footprint > 1.0:
                        level = min(max(0.0, log2(footprint) - LEVEL_BIAS), top_level)
                    u = ((lon[i, j] - west_deg) % 360.0) / 360.0
                    v = (90.0 - phi) / 180.0
                    r0, g0, b0 = _trilinear(data, offsets, widths, heights, 0, level, u, v, True)
                    rest = 1.0 - share
                    red += rest * r0
                    green += rest * g0
                    blue += rest * b0
                if graticule_deg > 0.0:
                    line = _graticule(lon[i, j], phi, lon_x, lon_y, lat_x, lat_y, graticule_deg)
                    red += (colours[2, 0] - red) * line
                    green += (colours[2, 1] - green) * line
                    blue += (colours[2, 2] - blue) * line
                shade = light[i, j]
                red, green, blue = red * shade, green * shade, blue * shade
            g = 0.6 * glow[i, j]
            out[i, j, 0] = _byte(c * red + (1.0 - c) * _space(colours, g, 0))
            out[i, j, 1] = _byte(c * green + (1.0 - c) * _space(colours, g, 1))
            out[i, j, 2] = _byte(c * blue + (1.0 - c) * _space(colours, g, 2))


@njit(cache=True, inline="always")
def _space(colours: F64, glow: float, k: int) -> float:
    return colours[0, k] + glow * (colours[1, k] - colours[0, k])


@njit(cache=True, inline="always")
def _byte(value: float) -> int:
    return min(255, max(0, floor(value + 0.5)))


@njit(cache=True, inline="always")
def _difference(
    lon: F64, lat: F64, cover: F32, i: int, j: int, di: int, dj: int
) -> tuple[float, float, bool]:
    """Change in longitude and latitude per pixel along one axis (wrapped at the seam)."""
    height, width = lon.shape
    sign = 1.0
    ni, nj = i + di, j + dj
    if ni >= height or nj >= width or cover[ni, nj] <= 0.0:
        ni, nj, sign = i - di, j - dj, -1.0
        if ni < 0 or nj < 0 or cover[ni, nj] <= 0.0:
            return 0.0, 0.0, False
    d_lon = (lon[ni, nj] - lon[i, j] + 180.0) % 360.0 - 180.0
    return sign * d_lon, sign * (lat[ni, nj] - lat[i, j]), True


@njit(cache=True, inline="always")
def _drape_weight(rho: float) -> float:
    """Opacity of a drape at ``rho`` times its radius from its centre (smoothstep fade)."""
    s = min(1.0, max(0.0, (1.0 - rho) / DRAPE_FADE))
    return s * s * (3.0 - 2.0 * s)


def drape_weights(rho: F64) -> F64:
    """``_drape_weight`` of an array, for drapes drawn outside the kernels (globe models)."""
    s = np.clip((1.0 - rho) / DRAPE_FADE, 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


@njit(cache=True, inline="always")
def _drapes(
    lon_deg: float, lat_deg: float, cos_lat: float, ground_rad: float,
    data: U8, offsets: I64, sizes: I64, levels: I64, frames: F64,
) -> tuple[float, float, float, float]:
    """Premultiplied colour and coverage of the drapes at a point, the last on top.

    The point's azimuthal equidistant position about a drape's centre picks
    the texel, as the regional window was drawn; ``ground_rad`` is the pixel's
    footprint on the sphere. Points outside a drape's box skip the
    trigonometry, so drapes cost little away from them.
    """
    px = py = pz = 0.0
    located = False
    red = green = blue = 0.0
    clear = 1.0  # share of the pixel no later drape covers
    # Rows are read element by element: slicing them would count references
    # to the shared arrays from every thread.
    for k in range(levels.shape[0] - 1, -1, -1):
        if lat_deg < frames[k, 11] or lat_deg > frames[k, 12]:
            continue
        east = lon_deg - frames[k, 13]
        if abs(east - 360.0 * floor(east / 360.0 + 0.5)) > frames[k, 14]:
            continue
        if not located:
            lam = lon_deg / DEG
            px, py, pz = cos_lat * cos(lam), cos_lat * sin(lam), sin(lat_deg / DEG)
            located = True
        cx, cy, cz = frames[k, 0], frames[k, 1], frames[k, 2]
        d = px * cx + py * cy + pz * cz
        if d <= frames[k, 10]:
            continue
        tx, ty, tz = px - d * cx, py - d * cy, pz - d * cz
        s = sqrt(tx * tx + ty * ty + tz * tz)
        theta = atan2(s, d)
        angle = frames[k, 9]
        weight = _drape_weight(theta / angle)
        if weight <= 0.0:
            continue
        x = y = 0.0
        if s > 0.0:
            x = theta * (tx * frames[k, 3] + ty * frames[k, 4] + tz * frames[k, 5]) / s
            y = theta * (tx * frames[k, 6] + ty * frames[k, 7] + tz * frames[k, 8]) / s
        first = levels[k, 0]
        texels = ground_rad * sizes[first] / (2.0 * angle)
        level = 0.0
        if texels > 1.0:
            level = min(max(0.0, log2(texels) - LEVEL_BIAS), levels[k, 1] - 1.0)
        r, g, b = _trilinear(
            data, offsets, sizes, sizes, first, level,
            0.5 * (1.0 + x / angle), 0.5 * (1.0 - y / angle), False,
        )
        a = clear * weight
        red += a * r
        green += a * g
        blue += a * b
        clear -= a
        if clear <= 0.0:
            break
    return red, green, blue, 1.0 - clear


@njit(cache=True, inline="always")
def _trilinear(
    data: U8, offsets: I64, widths: I64, heights: I64, first: int, level: float,
    u: float, v: float, wrap: bool,
) -> tuple[float, float, float]:
    """The blend of the two mip levels either side of ``level`` (counted from ``first``)."""
    low = first + int(level)
    fraction = level - int(level)
    red, green, blue = _bilinear(data, offsets[low], widths[low], heights[low], u, v, wrap)
    if fraction > 0.0:
        r1, g1, b1 = _bilinear(
            data, offsets[low + 1], widths[low + 1], heights[low + 1], u, v, wrap
        )
        red += fraction * (r1 - red)
        green += fraction * (g1 - green)
        blue += fraction * (b1 - blue)
    return red, green, blue


@njit(cache=True, inline="always")
def _bilinear(
    data: U8, offset: int, width: int, height: int, u: float, v: float, wrap: bool
) -> tuple[float, float, float]:
    """The bilinear sample of one level at (u, v); u wraps around if ``wrap``, v is clamped."""
    x = u * width - 0.5
    y = v * height - 0.5
    x0 = floor(x)
    y0 = floor(y)
    fx = x - x0
    fy = y - y0
    if wrap:
        c0 = int(x0) % width
        c1 = (c0 + 1) % width
    else:
        c0 = min(width - 1, max(0, int(x0)))
        c1 = min(width - 1, max(0, int(x0) + 1))
    r0 = min(height - 1, max(0, int(y0)))
    r1 = min(height - 1, max(0, int(y0) + 1))
    a = offset + (r0 * width + c0) * 3
    b = offset + (r0 * width + c1) * 3
    c = offset + (r1 * width + c0) * 3
    d = offset + (r1 * width + c1) * 3
    w_a, w_b = (1.0 - fx) * (1.0 - fy), fx * (1.0 - fy)
    w_c, w_d = (1.0 - fx) * fy, fx * fy
    return (
        w_a * data[a] + w_b * data[b] + w_c * data[c] + w_d * data[d],
        w_a * data[a + 1] + w_b * data[b + 1] + w_c * data[c + 1] + w_d * data[d + 1],
        w_a * data[a + 2] + w_b * data[b + 2] + w_c * data[c + 2] + w_d * data[d + 2],
    )


@njit(cache=True, inline="always")
def _graticule(
    lon: float, lat: float, lon_x: float, lon_y: float, lat_x: float, lat_y: float,
    step: float,
) -> float:
    """Opacity of an anti-aliased grid line about 1.2 pixels wide at this pixel."""
    lat_rate = sqrt(lat_x * lat_x + lat_y * lat_y)
    off = abs(lat - floor(lat / step + 0.5) * step)
    line = min(1.0, max(0.0, 1.1 - off / max(lat_rate, 1e-9)))
    lon_rate = sqrt(lon_x * lon_x + lon_y * lon_y)
    spacing = step / max(lon_rate, 1e-9)  # pixels between meridians here
    if spacing > 3.0:
        wrapped = (lon + 180.0) % 360.0 - 180.0
        off = abs(wrapped - floor(wrapped / step + 0.5) * step)
        meridian = min(1.0, max(0.0, 1.1 - off / max(lon_rate, 1e-9)))
        # Meridians fade out where they crowd together near a pole.
        line = max(line, meridian * min(1.0, (spacing - 3.0) / 3.0))
    return 0.45 * line
