# pyright: reportArgumentType=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Compiled graph kernels for flow routing and landscape evolution on any mesh.

All kernels take CSR adjacency (``ptr``, ``nbr``) so the same code serves the
irregular sphere mesh and later regional meshes or rasters. Kernels are compiled
by Numba on first use and cached beside the package.
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


@njit(cache=True)
def priority_flood(h: F64, water: B, ptr: I64, nbr: I64, eps: float) -> tuple[F64, I64]:
    """Fill land depressions from the water boundary (Barnes et al. 2014).

    Returns the filled surface (land >= every flood path; each step up by at
    least ``eps``) and the flood parent of every land node (-1 for water and
    for land unreachable from any water).
    """
    n = h.size
    filled = h.copy()
    parent = np.full(n, -1, np.int64)
    closed = water.copy()
    heap = [(0.0, np.int64(0))]
    heap.pop()
    for i in range(n):
        if water[i]:
            for k in range(ptr[i], ptr[i + 1]):
                if not water[nbr[k]]:
                    heapq.heappush(heap, (0.0, np.int64(i)))
                    break
    while heap:
        level, c = heapq.heappop(heap)
        for k in range(ptr[c], ptr[c + 1]):
            j = nbr[k]
            if closed[j]:
                continue
            closed[j] = True
            parent[j] = c
            floor = level + eps
            if filled[j] < floor:
                filled[j] = floor
            heapq.heappush(heap, (filled[j], j))
    return filled, parent


@njit(cache=True)
def steepest_receivers(
    z: F64, water: B, ptr: I64, nbr: I64, length: F64, parent: I64
) -> tuple[I64, F64]:
    """Steepest strictly-descending neighbour on ``z``; water nodes are sea level."""
    n = z.size
    receiver = np.full(n, -1, np.int64)
    distance = np.zeros(n)
    for i in range(n):
        if water[i]:
            continue
        best = 0.0
        for k in range(ptr[i], ptr[i + 1]):
            j = nbr[k]
            zj = 0.0 if water[j] else z[j]
            slope = (z[i] - zj) / length[k]
            if slope > best:
                best = slope
                receiver[i] = j
                distance[i] = length[k]
        if receiver[i] < 0 and parent[i] >= 0:
            receiver[i] = parent[i]
            for k in range(ptr[i], ptr[i + 1]):
                if nbr[k] == parent[i]:
                    distance[i] = length[k]
    return receiver, distance


@njit(cache=True)
def accumulate(order: I64, receiver: I64, water: B, source: F64) -> F64:
    """Sum ``source`` downstream; ``order`` lists land nodes upstream-last."""
    total = source.copy()
    for idx in range(order.size - 1, -1, -1):
        i = order[idx]
        r = receiver[i]
        if r >= 0 and not water[r]:
            total[r] += total[i]
    return total


@njit(cache=True)
def accumulate_nonnegative(order: I64, receiver: I64, sink: B, source: F64) -> F64:
    """Like ``accumulate`` but losses (negative sources) cannot pass negative flow on."""
    total = source.copy()
    for idx in range(order.size - 1, -1, -1):
        i = order[idx]
        if total[i] < 0:
            total[i] = 0.0
        r = receiver[i]
        if r >= 0 and not sink[r]:
            total[r] += total[i]
    return total


@njit(cache=True)
def stream_power_implicit(
    h: F64,
    order: I64,
    receiver: I64,
    distance: F64,
    water: B,
    flux: F64,
    k_eff: F64,
    m: float,
    uplift: F64,
    dt: float,
) -> F64:
    """Braun & Willett (2013) implicit step for n = 1, downstream nodes first.

    ``flux`` is the discharge proxy (area or runoff-weighted area, m^2).
    ``k_eff`` has units making K * flux^m / distance a rate (1/yr).
    """
    out = h.copy()
    for idx in range(order.size):
        i = order[idx]
        r = receiver[i]
        base = 0.0 if (r < 0 or water[r]) else out[r]
        if r < 0:
            out[i] = h[i] + dt * uplift[i]
            continue
        f = dt * k_eff[i] * flux[i] ** m / distance[i]
        out[i] = (h[i] + dt * uplift[i] + f * base) / (1 + f)
    return out


@njit(cache=True, parallel=True)
def laplacian(
    h: F64, water: B, ptr: I64, nbr: I64, weight: F64, area: F64, sea_level: float
) -> F64:
    """Cotangent Laplacian (1/m); water neighbours are held at ``sea_level``."""
    n = h.size
    out = np.zeros(n)
    for i in prange(n):
        if water[i]:
            continue
        acc = 0.0
        for k in range(ptr[i], ptr[i + 1]):
            j = nbr[k]
            hj = sea_level if water[j] else h[j]
            acc += weight[k] * (hj - h[i])
        out[i] = acc / area[i]
    return out


@njit(cache=True)
def diffuse(
    h: F64,
    water: B,
    ptr: I64,
    nbr: I64,
    weight: F64,
    area: F64,
    diffusivity: F64,
    dt: float,
    max_rate: int,
) -> F64:
    """Explicit hillslope diffusion with automatic stable substeps."""
    # Stability: dt_sub * D * sum(w) / A < 0.5 at every node.
    worst = 0.0
    n = h.size
    for i in range(n):
        if water[i]:
            continue
        s = 0.0
        for k in range(ptr[i], ptr[i + 1]):
            s += weight[k]
        rate = diffusivity[i] * s / area[i]
        if rate > worst:
            worst = rate
    if worst <= 0:
        return h.copy()
    steps = max(1, int(np.ceil(dt * worst / 0.45)))
    steps = min(steps, max_rate)
    sub = dt / steps
    out = h.copy()
    for _ in range(steps):
        lap = laplacian(out, water, ptr, nbr, weight, area, 0.0)
        for i in range(n):
            if not water[i]:
                out[i] += sub * diffusivity[i] * lap[i]
    return out


@njit(cache=True)
def multi_source_distance(
    seeds: I64, seed_distance: F64, ptr: I64, nbr: I64, length: F64
) -> F64:
    """Dijkstra graph distance from many seeds (metres along mesh edges)."""
    n = ptr.size - 1
    dist = np.full(n, np.inf)
    heap = [(0.0, np.int64(0))]
    heap.pop()
    for s in range(seeds.size):
        i = seeds[s]
        if seed_distance[s] < dist[i]:
            dist[i] = seed_distance[s]
            heapq.heappush(heap, (dist[i], i))
    while heap:
        d, c = heapq.heappop(heap)
        if d > dist[c]:
            continue
        for k in range(ptr[c], ptr[c + 1]):
            j = nbr[k]
            nd = d + length[k]
            if nd < dist[j]:
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    return dist


@njit(cache=True, parallel=True)
def interpolate_to_lonlat(
    values: F64,
    xyz: F64,
    tri: I64,
    vt_ptr: I64,
    vt_idx: I64,
    nbr_ptr: I64,
    nbr: I64,
    nearest: I64,
    queries: F64,
) -> F64:
    """Barycentric interpolation of node values at query unit vectors.

    ``nearest`` is the closest node for each query; its incident triangles and
    those of its neighbours are searched for the containing spherical triangle.
    """
    m = queries.shape[0]
    out = np.empty(m)
    for q in prange(m):
        px, py, pz = queries[q, 0], queries[q, 1], queries[q, 2]
        found = False
        start = nearest[q]
        for ring in range(2):
            lo = nbr_ptr[start] if ring == 1 else 0
            hi = nbr_ptr[start + 1] if ring == 1 else 1
            for c in range(lo, hi):
                v = start if ring == 0 else nbr[c]
                for t in range(vt_ptr[v], vt_ptr[v + 1]):
                    a, b, cc = tri[vt_idx[t], 0], tri[vt_idx[t], 1], tri[vt_idx[t], 2]
                    # Signed volumes: the ray hits the triangle if all are >= 0.
                    wa = (
                        px * (xyz[b, 1] * xyz[cc, 2] - xyz[b, 2] * xyz[cc, 1])
                        + py * (xyz[b, 2] * xyz[cc, 0] - xyz[b, 0] * xyz[cc, 2])
                        + pz * (xyz[b, 0] * xyz[cc, 1] - xyz[b, 1] * xyz[cc, 0])
                    )
                    wb = (
                        px * (xyz[cc, 1] * xyz[a, 2] - xyz[cc, 2] * xyz[a, 1])
                        + py * (xyz[cc, 2] * xyz[a, 0] - xyz[cc, 0] * xyz[a, 2])
                        + pz * (xyz[cc, 0] * xyz[a, 1] - xyz[cc, 1] * xyz[a, 0])
                    )
                    wc = (
                        px * (xyz[a, 1] * xyz[b, 2] - xyz[a, 2] * xyz[b, 1])
                        + py * (xyz[a, 2] * xyz[b, 0] - xyz[a, 0] * xyz[b, 2])
                        + pz * (xyz[a, 0] * xyz[b, 1] - xyz[a, 1] * xyz[b, 0])
                    )
                    if wa >= -1e-14 and wb >= -1e-14 and wc >= -1e-14:
                        s = wa + wb + wc
                        out[q] = (wa * values[a] + wb * values[b] + wc * values[cc]) / s
                        found = True
                        break
                if found:
                    break
            if found:
                break
        if not found:
            out[q] = values[start]
    return out


@njit(cache=True)
def flow_length(order: I64, receiver: I64, water: B, distance: F64) -> F64:
    """Longest upstream flow path (m) ending at each node (Hack's L)."""
    length = np.zeros(receiver.size)
    for idx in range(order.size - 1, -1, -1):
        i = order[idx]
        r = receiver[i]
        if r >= 0 and not water[r]:
            candidate = length[i] + distance[i]
            if candidate > length[r]:
                length[r] = candidate
    return length
