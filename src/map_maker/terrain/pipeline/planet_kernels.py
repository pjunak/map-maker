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
    """Fill land depressions from fixed boundary nodes (Barnes et al. 2014).

    ``water`` marks fixed nodes (sea, lakes, regional boundaries); their ``h`` is
    their base level and is never changed.

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
                    heapq.heappush(heap, (h[i], np.int64(i)))
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
def graded_flood(
    h: F64, water: B, ptr: I64, nbr: I64, length: F64, slope: F64, eps: float
) -> F64:
    """Fill land depressions so that filled ground falls towards where it spills.

    As ``priority_flood``, but a node raised from its flood parent stands at
    least its ``slope`` times the edge ``length`` above it (and at least
    ``eps``), so a filled plain rises away from its outlet at that gradient
    instead of lying level.
    """
    n = h.size
    filled = h.copy()
    closed = water.copy()
    heap = [(0.0, np.int64(0))]
    heap.pop()
    for i in range(n):
        if water[i]:
            for k in range(ptr[i], ptr[i + 1]):
                if not water[nbr[k]]:
                    heapq.heappush(heap, (h[i], np.int64(i)))
                    break
    while heap:
        level, c = heapq.heappop(heap)
        for k in range(ptr[c], ptr[c + 1]):
            j = nbr[k]
            if closed[j]:
                continue
            closed[j] = True
            floor = level + max(eps, slope[j] * length[k])
            if filled[j] < floor:
                filled[j] = floor
            heapq.heappush(heap, (filled[j], j))
    return filled


@njit(cache=True)
def priority_breach(h: F64, water: B, ptr: I64, nbr: I64, eps: float) -> F64:
    """Lower land sills so that every land node descends to a fixed node.

    The dual of ``priority_flood``: flooding from fixed nodes in the same order, a
    node no higher than the node it is reached from lies in a depression, and
    instead of raising it, its flood path back over the lowest pass is lowered to
    just below it (each step down by at least ``eps``). Where that path would have
    to cut a fixed node, the depression fills up to that node instead; elsewhere
    the result is nowhere above ``h``.
    """
    n = h.size
    out = h.copy()
    parent = np.full(n, -1, np.int64)
    closed = water.copy()
    heap = [(0.0, np.int64(0))]
    heap.pop()
    for i in range(n):
        if water[i]:
            for k in range(ptr[i], ptr[i + 1]):
                if not water[nbr[k]]:
                    heapq.heappush(heap, (h[i], np.int64(i)))
                    break
    while heap:
        _, c = heapq.heappop(heap)
        for k in range(ptr[c], ptr[c + 1]):
            j = nbr[k]
            if closed[j]:
                continue
            closed[j] = True
            parent[j] = c
            if out[j] <= out[c]:
                # Walk towards the outlet until the path is already low enough.
                bottom = out[j]
                node, steps = c, 1
                while not water[node] and out[node] > bottom - steps * eps:
                    node, steps = parent[node], steps + 1
                if water[node] and out[node] > bottom - steps * eps:
                    bottom = out[node] + steps * eps
                    out[j] = bottom
                node, steps = c, 1
                while not water[node] and out[node] > bottom - steps * eps:
                    out[node] = bottom - steps * eps
                    node, steps = parent[node], steps + 1
            heapq.heappush(heap, (out[j], j))
    return out


@njit(cache=True, parallel=True)
def steepest_receivers(
    z: F64, water: B, ptr: I64, nbr: I64, length: F64, parent: I64
) -> tuple[I64, F64]:
    """Steepest strictly-descending neighbour on ``z``; fixed nodes keep their own ``z``."""
    n = z.size
    receiver = np.full(n, -1, np.int64)
    distance = np.zeros(n)
    for i in prange(n):
        if water[i]:
            continue
        best = 0.0
        for k in range(ptr[i], ptr[i + 1]):
            j = nbr[k]
            zj = z[j]
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
def downstream_sum(order: I64, receiver: I64, values: F64, floor: F64) -> F64:
    """Sum ``values`` down each node's drainage path, never below ``floor``.

    ``order`` lists land nodes downstream first. A node outside it (water, or a
    node draining nowhere) keeps its own value, which ends every path through it.
    A node in it stands ``values`` above its receiver's total, or at its ``floor``
    (-inf for none) where that is higher, as erosion holds a deposit.
    """
    total = values.copy()
    for idx in range(order.size):
        i = order[idx]
        r = receiver[i]
        if r >= 0:
            total[i] += total[r]
        if total[i] < floor[i]:
            total[i] = floor[i]
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
        base = h[i] if r < 0 else out[r]
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


@njit(cache=True, parallel=True)
def neighbour_mix(values: F64, ptr: I64, nbr: I64, weight: F64, substeps: int) -> F64:
    """Explicit diffusion: ``substeps`` relaxations towards the neighbour mean.

    Each substep moves every node by ``weight`` (at most 0.5 for stability) of
    the way to the mean of its neighbours.
    """
    n = values.size
    current = values.copy()
    following = np.empty(n)
    for _ in range(substeps):
        for i in prange(n):
            total = 0.0
            for k in range(ptr[i], ptr[i + 1]):
                total += current[nbr[k]]
            mean = total / (ptr[i + 1] - ptr[i])
            following[i] = (1.0 - weight[i]) * current[i] + weight[i] * mean
        current, following = following, current
    return current


@njit(cache=True)
def downstream_order(receiver: I64, water: B) -> I64:
    """Land nodes ordered so every receiver precedes its donors (O(n) tree walk).

    Land nodes that drain to no water (an unfilled pit) are left out.
    """
    n = receiver.size
    count = np.zeros(n + 1, np.int64)
    for i in range(n):
        r = receiver[i]
        if not water[i] and r >= 0:
            count[r + 1] += 1
    for i in range(n):
        count[i + 1] += count[i]
    donors = np.empty(count[n], np.int64)
    fill = count[:n].copy()
    for i in range(n):
        r = receiver[i]
        if not water[i] and r >= 0:
            donors[fill[r]] = i
            fill[r] += 1
    order = np.empty(n, np.int64)
    size = 0
    for i in range(n):
        r = receiver[i]
        if not water[i] and r >= 0 and water[r]:
            order[size] = i
            size += 1
    head = 0
    while head < size:
        node = order[head]
        head += 1
        for k in range(count[node], count[node + 1]):
            order[size] = donors[k]
            size += 1
    return order[:size]



@njit(cache=True)
def multi_source_nearest(
    seeds: I64, labels: I64, ptr: I64, nbr: I64, length: F64
) -> tuple[F64, I64]:
    """Dijkstra distance (m) to the nearest seed and that seed's label."""
    n = ptr.size - 1
    dist = np.full(n, np.inf)
    owner = np.full(n, -1, np.int64)
    heap = [(0.0, np.int64(0))]
    heap.pop()
    for s in range(seeds.size):
        i = seeds[s]
        if dist[i] > 0.0:
            dist[i] = 0.0
            owner[i] = labels[s]
            heapq.heappush(heap, (0.0, i))
    while heap:
        d, c = heapq.heappop(heap)
        if d > dist[c]:
            continue
        for k in range(ptr[c], ptr[c + 1]):
            j = nbr[k]
            nd = d + length[k]
            if nd < dist[j]:
                dist[j] = nd
                owner[j] = owner[c]
                heapq.heappush(heap, (nd, j))
    return dist, owner


@njit(cache=True)
def draining_to(receiver: I64, water: B, sinks: I64) -> B:
    """Land nodes whose steepest-descent path ends at one of ``sinks`` (pits)."""
    n = receiver.size
    count = np.zeros(n + 1, np.int64)
    for i in range(n):
        r = receiver[i]
        if not water[i] and r >= 0:
            count[r + 1] += 1
    for i in range(n):
        count[i + 1] += count[i]
    donors = np.empty(count[n], np.int64)
    fill = count[:n].copy()
    for i in range(n):
        r = receiver[i]
        if not water[i] and r >= 0:
            donors[fill[r]] = i
            fill[r] += 1
    inside = np.zeros(n, np.bool_)
    stack = np.empty(n, np.int64)
    size = 0
    for s in range(sinks.size):
        inside[sinks[s]] = True
        stack[size] = sinks[s]
        size += 1
    while size:
        size -= 1
        node = stack[size]
        for k in range(count[node], count[node + 1]):
            donor = donors[k]
            if not inside[donor]:
                inside[donor] = True
                stack[size] = donor
                size += 1
    return inside


@njit(cache=True)
def erosion_step(
    h: F64,
    order: I64,
    receiver: I64,
    distance: F64,
    water: B,
    area: F64,
    process_area: float,
    erodibility: F64,
    m: float,
    uplift: F64,
    dt: float,
    snowline: F64,
    glacial: tuple[float, float, float],
    base: F64,
    floor: float,
    deposit: F64,
) -> F64:
    """One fused implicit stream-power step (Braun and Willett 2013, n = 1).

    Drainage area includes the process area; erodibility rises above the
    ``snowline`` (empty to disable) as 1 + boost * (z - ELA) / scale, capped.
    Fixed (water) nodes take ``base``; land stays at least ``floor``. Land never
    erodes below ``deposit`` (empty to disable), a plain that sediment keeps at
    its level; it holds inside the sweep, so each node grades to its receiver's
    held height.
    """
    boost, scale, cap = glacial
    glaciers = snowline.size > 0
    held = deposit.size > 0
    out = h.copy()
    for idx in range(order.size):
        i = order[idx]
        r = receiver[i]
        if r < 0:
            out[i] = h[i] + dt * uplift[i]
            continue
        k = erodibility[i]
        if glaciers:
            above = (h[i] - snowline[i]) / scale
            if above > 0.0:
                k *= min(1.0 + boost * above, cap)
        f = dt * k * (area[i] + process_area) ** m / distance[i]
        out[i] = (h[i] + dt * uplift[i] + f * out[r]) / (1 + f)
        if held and out[i] < deposit[i]:
            out[i] = deposit[i]
    for i in range(h.size):
        if water[i]:
            out[i] = base[i]
        elif out[i] < floor:
            out[i] = floor
    return out
