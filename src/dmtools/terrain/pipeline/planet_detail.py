# pyright: reportArgumentType=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Sub-mesh relief detail for display: derivative-damped ("eroded") fractal noise.

The planet mesh resolves landforms down to its process scale (tens of km). A map
drawn at a few km per pixel needs texture below that scale, or slopes between
rivers look like smooth ramps. This noise is a *display* field:

* coordinate-hashed on unit vectors, so it is resolution- and window-independent;
* damped by its accumulated slope (as in derivative fBm), which leaves
  sharp ridges and smooth valley floors, the look of eroded terrain;
* blended from soft rolling noise in lowlands to ridged noise in mountains.

It never changes the authoritative mesh relief.
"""

import heapq
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

if TYPE_CHECKING:
    prange = range

    def njit[T: Callable[..., Any]](*_args: object, **_kwargs: object) -> Callable[[T], T]:
        return lambda function: function
else:
    from numba import njit, prange


@njit(cache=True, inline="always")
def _hash(seed: int, x: int, y: int, z: int) -> float:
    h = np.uint64(seed) * np.uint64(0x9E3779B97F4A7C15)
    for c in (x, y, z):
        h ^= np.uint64(c & 0xFFFFFFFF) * np.uint64(0xBF58476D1CE4E5B9)
        h = (h ^ (h >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        h = (h ^ (h >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        h ^= h >> np.uint64(31)
    return float(h >> np.uint64(11)) / 9007199254740992.0 * 2.0 - 1.0


@njit(cache=True, inline="always")
def _noise(seed: int, x: float, y: float, z: float) -> tuple[float, float, float, float]:
    """Value noise in [-1, 1] and its gradient (quintic interpolation)."""
    ix, iy, iz = int(np.floor(x)), int(np.floor(y)), int(np.floor(z))
    fx, fy, fz = x - ix, y - iy, z - iz
    ux = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
    uy = fy * fy * fy * (fy * (fy * 6 - 15) + 10)
    uz = fz * fz * fz * (fz * (fz * 6 - 15) + 10)
    dux = 30 * fx * fx * (fx * (fx - 2) + 1)
    duy = 30 * fy * fy * (fy * (fy - 2) + 1)
    duz = 30 * fz * fz * (fz * (fz - 2) + 1)
    a = _hash(seed, ix, iy, iz)
    b = _hash(seed, ix + 1, iy, iz)
    c = _hash(seed, ix, iy + 1, iz)
    d = _hash(seed, ix + 1, iy + 1, iz)
    e = _hash(seed, ix, iy, iz + 1)
    f = _hash(seed, ix + 1, iy, iz + 1)
    g = _hash(seed, ix, iy + 1, iz + 1)
    h = _hash(seed, ix + 1, iy + 1, iz + 1)
    k1, k2, k3 = b - a, c - a, e - a
    k4, k5, k6 = a - b - c + d, a - c - e + g, a - b - e + f
    k7 = -a + b + c - d + e - f - g + h
    value = (
        a
        + k1 * ux
        + k2 * uy
        + k3 * uz
        + k4 * ux * uy
        + k5 * uy * uz
        + k6 * uz * ux
        + k7 * ux * uy * uz
    )
    gx = dux * (k1 + k4 * uy + k6 * uz + k7 * uy * uz)
    gy = duy * (k2 + k5 * uz + k4 * ux + k7 * uz * ux)
    gz = duz * (k3 + k6 * ux + k5 * uy + k7 * ux * uy)
    return value, gx, gy, gz


@njit(cache=True, parallel=True)
def eroded_fbm(
    xyz: F64,
    ridged: F64,
    seed: int,
    octaves: int,
    base_frequency: float,
    gain: float,
    damping: float,
) -> F64:
    """Derivative-damped fBm on unit vectors; ``ridged`` (0..1) blends in ridged noise.

    ``base_frequency`` is in cycles per planet radius. Output is roughly zero-mean,
    within [-1, 1] and continuous.
    """
    n = xyz.shape[0]
    out = np.empty(n)
    for i in prange(n):
        px, py, pz = xyz[i, 0], xyz[i, 1], xyz[i, 2]
        total, norm, amplitude, frequency = 0.0, 0.0, 1.0, base_frequency
        sx, sy, sz = 0.0, 0.0, 0.0
        r = ridged[i]
        # Finer octaves are damped by a continuous slope: the ridged slope's
        # root-mean-square magnitude over the two sides of a crest. The ridged
        # gradient itself flips sign at every zero crossing, which stepped all
        # finer octaves there and drew sharp scarps along the value-noise
        # lattice (straight north-south and east-west lines).
        steepness = np.sqrt(1.0 - 2.0 * r + 5.0 * r * r)
        for octave in range(octaves):
            v, gx, gy, gz = _noise(
                seed + 1013 * octave, px * frequency, py * frequency, pz * frequency
            )
            # Ridged variant: sharp crests where the noise crosses zero.
            value = (1.0 - r) * v + r * (1.0 - 2.0 * abs(v))
            slope = steepness * amplitude
            sx += slope * gx
            sy += slope * gy
            sz += slope * gz
            total += amplitude * value / (1.0 + damping * (sx * sx + sy * sy + sz * sz))
            norm += amplitude
            amplitude *= gain
            frequency *= 2.03
        out[i] = total / norm
    return out


@njit(cache=True)
def _route(
    h: F64, fixed: B, dy: float, dx: F64, wrap: bool, source: F64
) -> tuple[F64, I64, int, I64, F64, F64]:
    """Priority-Flood fill, receivers and accumulation on a pixel grid.

    Returns the filled surface, cells in downstream-first order (and their
    count), flat receiver indices (-1 at outlets), receiver distances and the
    accumulated ``source`` (per-cell area plus any inflow).
    """
    rows, columns = h.shape
    n = rows * columns
    # Priority-Flood (Barnes et al. 2014) fills pits with a 1 mm gradient and
    # pops cells in non-decreasing water level: downstream cells first. Within
    # a depression, where the level is the spill height, cells pop lowest
    # ground first, so the flood runs down the hollow's thalweg and then
    # spreads uphill. Fill cells drain to the cell they were flooded from. On
    # the 1 mm fill gradient itself, steepest descent ran straight across the
    # fill in rings from the spill point; carving cut those straight grid
    # lines (0, 45 and 90 degrees) into every filled hollow.
    filled = h.copy()
    closed = fixed.copy()
    parent = np.full(n, -1, np.int64)
    parent_step = np.ones(n)
    order = np.empty(n, np.int64)
    count = 0
    heap = [(0.0, 0.0, np.int64(0))]
    heap.pop()
    for r in range(rows):
        for c in range(columns):
            if not fixed[r, c]:
                continue
            edge = False
            for dr in range(-1, 2):
                rr = r + dr
                if rr < 0 or rr >= rows:
                    continue
                for dc in range(-1, 2):
                    cc = c + dc
                    if cc < 0 or cc >= columns:
                        if not wrap:
                            continue
                        cc %= columns
                    if not fixed[rr, cc]:
                        edge = True
            if edge:
                heapq.heappush(heap, (h[r, c], h[r, c], np.int64(r * columns + c)))
    while heap:
        level, _, index = heapq.heappop(heap)
        r, c = index // columns, index % columns
        if not fixed[r, c]:
            order[count] = index
            count += 1
        for dr in range(-1, 2):
            rr = r + dr
            if rr < 0 or rr >= rows:
                continue
            for dc in range(-1, 2):
                cc = c + dc
                if cc < 0 or cc >= columns:
                    if not wrap:
                        continue
                    cc %= columns
                if closed[rr, cc]:
                    continue
                closed[rr, cc] = True
                j = rr * columns + cc
                parent[j] = index
                parent_step[j] = np.sqrt((dx[rr] * dc) ** 2 + (dy * dr) ** 2)
                if filled[rr, cc] < filled[r, c] + 1e-3:
                    filled[rr, cc] = filled[r, c] + 1e-3
                heapq.heappush(heap, (max(h[rr, cc], level), h[rr, cc], np.int64(j)))
    # Fill cells drain to their flood parent; others by steepest descent.
    receiver = np.full(n, -1, np.int64)
    distance = np.ones(n)
    for idx in range(count):
        i = order[idx]
        r, c = i // columns, i % columns
        if filled[r, c] > h[r, c]:
            receiver[i] = parent[i]
            distance[i] = parent_step[i]
            continue
        best = 0.0
        for dr in range(-1, 2):
            rr = r + dr
            if rr < 0 or rr >= rows:
                continue
            for dc in range(-1, 2):
                if dr == 0 and dc == 0:
                    continue
                cc = c + dc
                if cc < 0 or cc >= columns:
                    if not wrap:
                        continue
                    cc %= columns
                step = np.sqrt((dx[r] * dc) ** 2 + (dy * dr) ** 2)
                slope = (filled[r, c] - filled[rr, cc]) / step
                if slope > best:
                    best = slope
                    receiver[i] = rr * columns + cc
                    distance[i] = step
    area = source.copy()
    for idx in range(count - 1, -1, -1):
        i = order[idx]
        j = receiver[i]
        if j >= 0 and not fixed[j // columns, j % columns]:
            area[j] += area[i]
    return filled, order, count, receiver, distance, area


@njit(cache=True)
def _carve(h: F64, fixed: B, dy: float, dx: F64, k: float, m: float, steps: int, wrap: bool) -> F64:
    rows, columns = h.shape
    cells = np.empty(rows * columns)
    for i in range(rows * columns):
        cells[i] = dx[i // columns] * dy
    for _ in range(steps):
        filled, order, count, receiver, distance, area = _route(h, fixed, dy, dx, wrap, cells)
        # Implicit stream power (Braun and Willett 2013, n = 1), downstream first.
        for idx in range(count):
            i = order[idx]
            j = receiver[i]
            if j < 0:
                continue
            f = k * area[i] ** m / distance[i]
            ri, ci = i // columns, i % columns
            filled[ri, ci] = (filled[ri, ci] + f * filled[j // columns, j % columns]) / (1 + f)
        h = filled
    return h


def grid_flow(
    z: F64, outlet: B, cell_m: float, inflow_m2: F64
) -> tuple[NDArray[np.int64], F64, F64]:
    """Steepest-descent receivers (flat indices, -1 at outlets), drainage area (m^2)
    and the filled surface.

    Depressions are filled to their spill level first, so every cell drains to
    an ``outlet``. ``inflow_m2`` adds area entering from beyond the grid.
    """
    rows, columns = z.shape
    source = np.full(rows * columns, cell_m * cell_m) + np.ascontiguousarray(
        inflow_m2, dtype=np.float64
    ).ravel()
    filled, _, _, receiver, _, area = _route(
        np.ascontiguousarray(z, dtype=np.float64), np.ascontiguousarray(outlet), float(cell_m),
        np.full(rows, float(cell_m)), False, source,
    )
    return receiver, area, filled.reshape(rows, columns)


def carve_valleys(
    z: F64,
    outlet: B,
    dy_m: float,
    dx_m: F64,
    erodibility: float,
    area_exponent: float,
    steps: int,
    *,
    wrap: bool = False,
) -> F64:
    """Display-only valley carving: implicit stream power over a pixel grid.

    Fractal detail has the right roughness but no drainage network. A few
    implicit stream-power steps (Braun and Willett 2013, n = 1) routed over the
    detailed surface itself turn its hollows into connected, branching valleys
    with concave long profiles. ``outlet`` cells (sea, outside the map) are the
    base level. Rows may have their own east-west cell width ``dx_m`` (as on a
    longitude-latitude raster), and ``wrap`` joins the first and last columns.
    ``erodibility`` is K * dt in m^(1 - 2m).
    """
    return _carve(
        np.ascontiguousarray(z, dtype=np.float64),
        np.ascontiguousarray(outlet),
        float(dy_m),
        np.ascontiguousarray(dx_m, dtype=np.float64),
        float(erodibility),
        float(area_exponent),
        int(steps),
        bool(wrap),
    )
