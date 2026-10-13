"""Ice sheets grown from surface mass balance by shallow-ice flow (ADR-0093).

* **Mass balance.** Snowfall minus melt at the ice surface. Melt follows the
  precipitation that balances a glacier at its equilibrium line, Ohmura et al.
  (1992): P = 645 + 296 T + 9 T^2 (mm/yr, T the warmest-month air temperature),
  so ice survives where snowfall outweighs that melt.
* **Feedbacks.** The ice surface is colder by the lapse rate and drier by about
  7 % per degree of cooling (Clausius-Clapeyron), as on the polar plateaus.
  Large ice sheets also cool their summers by reflecting sunlight: up to
  ALBEDO_COOLING_C where ice covers the surroundings within ALBEDO_REACH_M.
* **Regional climate.** The zonal climate model has no stationary waves or
  sea-ice patterns, so its summer isotherms run along parallels on broad plains,
  and so would every margin there. Summers wander by about 1.6 deg C (one
  standard deviation) over 250-1,000 km (stage ``planet.ice``), as warmest-month
  temperatures do between longitudes at 70 deg N on Earth, so equilibrium lines
  meander and margins form lobes, as the Laurentide and Scandinavian sheets did.
* **Flow.** The shallow-ice approximation, dH/dt = b + div(D grad s) with
  D = 2A (rho g)^3 H^5 |grad s|^2 / 5 (Glen's flow law, n = 3; Mahaffy 1976),
  on the mesh's cotangent weights. Ice flows out of a node only from the ice it
  holds and calves where it reaches the sea. Integrated explicitly from no ice
  for ICE_YEARS, close to a steady state.
* **Resolution.** Diffusivity is capped so steps stay near STEP_YR. The cap
  binds only on steep, thick mountain ice that the mesh does not resolve.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numba import njit, prange
from numpy.typing import NDArray

from dmtools.terrain.domain.seeds import stage_seed
from dmtools.terrain.pipeline.planet_coast import displace, noise_octaves
from dmtools.terrain.pipeline.planet_kernels import multi_source_distance, neighbour_mix
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, sample_field
from dmtools.terrain.pipeline.planet_noise import fbm3

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

ICE_DENSITY = 917.0
RATE_FACTOR_PA3_YR = 1e-16  # Glen's A for cold ice (EISMINT)
GAMMA = 2 * RATE_FACTOR_PA3_YR * (ICE_DENSITY * 9.81) ** 3 / 5  # m^-3 yr^-1
SNOW_DRYING_PER_C = 0.07
ALBEDO_COOLING_C = 5.0
ALBEDO_REACH_M = 300e3
ICE_YEARS = 100e3
STEP_YR = 10.0
BALANCE_INTERVAL_YR = 500.0
ALBEDO_INTERVAL_YR = 5000.0
ICE_MIN_M = 10.0  # thinner ice counts as seasonal snow, not an ice sheet
ICE_STAGE = "planet.ice"
ICE_WANDER_C = 6.0  # noise amplitude; about 1.6 deg C standard deviation
ICE_WANDER_WAVELENGTH_M = 1000e3
# Ice bodies are drawn as ice sheets, with their own smooth surface, when they
# are large and bury their bed: mean thickness at least ICE_SHEET_BURIAL times
# the bed's relief within about ICE_RELIEF_SCALE_M (its local standard
# deviation). On Aethelara that ratio is about 10 for the polar sheet and under 3
# for icefields on mountain ranges, at 800k and 3.2M nodes alike. The mesh does
# not resolve mountain icefields, so they are drawn as snow and glaciers.
ICE_SHEET_MIN_KM2 = 100_000.0
ICE_SHEET_BURIAL = 4.0
ICE_RELIEF_SCALE_M = 50e3
# Below this warmest-month temperature (deg C) the Ohmura melt curve reaches zero.
MELT_FLOOR_C = -2.35
# Margins are refined below the mesh spacing like lake outlines (ADR-0092).
ICE_OUTLINE_STAGE = "planet.ice-outline"
# Ice margins wander more than lake shores: lobes and tongues tens of
# kilometres across where ice follows lowlands and valleys.
ICE_TOP_SPACINGS = 6.0
ICE_AMPLITUDE_SPACINGS = 0.6
# Perfectly plastic profile near a margin (Nye 1952): h = sqrt(NYE_M * distance).
NYE_M = 2 * 1e5 / (ICE_DENSITY * 9.81)


@dataclass(frozen=True, slots=True)
class IceSheets:
    """Ice-sheet state on mesh nodes."""

    thickness_m: F64  # 0 where ice-free
    balance_m: F64  # surface mass balance (m of ice a year) on land, on the ice where iced

    @classmethod
    def none(cls, size: int) -> IceSheets:
        return cls(np.zeros(size), np.zeros(size))


def melt_mm(summer_c: F64) -> F64:
    """Yearly melt (mm water) at warmest-month temperature ``summer_c`` (Ohmura et al. 1992)."""
    t = np.maximum(summer_c, MELT_FLOOR_C)
    return np.where(summer_c > MELT_FLOOR_C, 645.0 + 296.0 * t + 9.0 * t * t, 0.0)


def equilibrium_line_c(precipitation_mm: F64) -> F64:
    """Warmest-month temperature (deg C) at which ``melt_mm`` balances the precipitation.

    About -2 C for 100 mm, +1 C for 1,000 mm and +4 C for 2,000 mm a year.
    """
    p = np.clip(precipitation_mm, 0.0, 6000.0)
    return (-296.0 + np.sqrt(np.maximum(296.0**2 - 36.0 * (645.0 - p), 0.0))) / 18.0


def surface_balance(
    warm_c: F64, precipitation_mm: F64, lift_m: F64, lapse_c_per_km: float, albedo_c: F64
) -> F64:
    """Surface mass balance (m of ice a year) at ``lift_m`` above the climate's surface."""
    cooling = lapse_c_per_km * lift_m / 1000.0
    snow = precipitation_mm * np.exp(-SNOW_DRYING_PER_C * np.maximum(cooling, 0.0))
    return (snow - melt_mm(warm_c - cooling - albedo_c)) / ICE_DENSITY


@njit(cache=True, parallel=True)
def _flow(
    thickness: F64,
    bed: F64,
    water: B,
    ptr: I64,
    nbr: I64,
    weight: F64,
    length: F64,
    area: F64,
    cap: F64,
    active: I64,
    divergence: F64,
) -> None:
    """Shallow-ice flux divergence (m/yr) at ``active`` nodes; the sea is open water."""
    for idx in prange(active.size):
        i = active[idx]
        si = bed[i] + thickness[i]
        total = 0.0
        for k in range(ptr[i], ptr[i + 1]):
            j = nbr[k]
            hj = 0.0 if water[j] else thickness[j]
            sj = 0.0 if water[j] else bed[j] + hj
            # Ice moves only out of a node that holds it.
            if (thickness[i] if si >= sj else hj) <= 0.0:
                continue
            mean = 0.5 * (thickness[i] + hj)
            gradient = (sj - si) / length[k]
            d = min(GAMMA * mean**5 * gradient * gradient, cap[i], cap[j])
            total += d * weight[k] * (sj - si)
        divergence[i] = total / area[i]


@njit(cache=True)
def _dilate(mask: B, ptr: I64, nbr: I64, rings: int) -> B:
    """``mask`` grown by ``rings`` edges."""
    out = mask.copy()
    for _ in range(rings):
        grown = out.copy()
        for i in range(out.size):
            if out[i]:
                continue
            for k in range(ptr[i], ptr[i + 1]):
                if out[nbr[k]]:
                    grown[i] = True
                    break
        out = grown
    return out


def ice_sheets(
    mesh: SphereMesh,
    land: B,
    bed_m: F64,
    climate_surface_m: F64,
    warm_c: F64,
    precipitation_mm: F64,
    lapse_c_per_km: float,
    seed: int,
    check: Callable[[], None] | None = None,
) -> IceSheets:
    """Ice grown from no ice on land ``bed_m`` over ICE_YEARS.

    ``warm_c`` and ``precipitation_mm`` hold at ``climate_surface_m``; ground
    that rose since (volcanoes, wonders) and the ice itself are lapse-corrected.
    ``seed`` is the planet's master seed.
    """
    bed = np.where(land, np.maximum(bed_m, 0.0), 0.0)
    young = np.where(land, bed - np.maximum(climate_surface_m, 0.0), 0.0)
    wander = ICE_WANDER_C * fbm3(
        mesh.xyz, stage_seed(seed, ICE_STAGE), 3, mesh.radius_m / ICE_WANDER_WAVELENGTH_M
    )
    summer = warm_c + wander
    water = ~land
    thickness = np.zeros(mesh.size)
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    spread = np.bincount(src, mesh.weight, mesh.size)
    # Stable explicit steps: dt * D * sum(weights) / area < 0.4 at every node.
    cap = 0.4 * mesh.area_m2 / (np.maximum(spread, 1e-12) * STEP_YR)
    reach = max(1, round((ALBEDO_REACH_M / mesh.spacing_m) ** 2))
    half = np.full(mesh.size, 0.5)
    divergence = np.zeros(mesh.size)
    balance = np.zeros(mesh.size)
    share = np.zeros(mesh.size)
    active = np.zeros(0, dtype=np.int64)
    t = 0.0
    next_balance = next_albedo = 0.0
    while t < ICE_YEARS:
        if t >= next_albedo:
            if check is not None:
                check()
            covered = (thickness > ICE_MIN_M).astype(np.float64)
            share = neighbour_mix(covered, mesh.ptr, mesh.nbr, half, reach)
            next_albedo += ALBEDO_INTERVAL_YR
        if t >= next_balance:
            balance = np.where(
                land,
                surface_balance(
                    summer, precipitation_mm, young + thickness, lapse_c_per_km,
                    ALBEDO_COOLING_C * share,
                ),
                0.0,
            )
            # Ice can reach a node within three edges of ice or of positive balance.
            near = _dilate((thickness > 0) | (balance > 0), mesh.ptr, mesh.nbr, 3)
            active = np.flatnonzero(near & land)
            next_balance += BALANCE_INTERVAL_YR
        if not active.size:
            break
        divergence[active] = 0.0
        _flow(
            thickness, bed, water, mesh.ptr, mesh.nbr, mesh.weight, mesh.length_m,
            mesh.area_m2, cap, active, divergence,
        )
        dt = min(STEP_YR, ICE_YEARS - t)
        thickness[active] = np.maximum(
            thickness[active] + dt * (balance[active] + divergence[active]), 0.0
        )
        t += dt
    ice = thickness > ICE_MIN_M
    return IceSheets(np.where(ice, thickness, 0.0), balance)


def local_relief(mesh: SphereMesh, values: F64, scale_m: float) -> F64:
    """Standard deviation of ``values`` within about ``scale_m`` of each node.

    Unlike differences between neighbouring nodes, which shrink on finer meshes,
    it does not change with the mesh once the mesh resolves ``scale_m``.
    """
    passes = max(1, round((scale_m / mesh.spacing_m) ** 2))
    half = np.full(mesh.size, 0.5)
    mean = neighbour_mix(values, mesh.ptr, mesh.nbr, half, passes)
    square = neighbour_mix(values * values, mesh.ptr, mesh.nbr, half, passes)
    return np.sqrt(np.maximum(square - mean * mean, 0.0))


def ice_sheet_nodes(mesh: SphereMesh, thickness_m: F64, bed_m: F64) -> B:
    """Nodes of the ice bodies drawn as ice sheets (see ICE_SHEET_BURIAL).

    ``bed_m`` is the land surface, 0 at sea.
    """
    ice = thickness_m > 0
    if not ice.any():
        return ice
    body = _bodies(ice, mesh.ptr, mesh.nbr)
    relief = local_relief(mesh, bed_m, ICE_RELIEF_SCALE_M)
    on = body[ice]
    area = np.bincount(on, mesh.area_m2[ice])
    buried = np.bincount(on, thickness_m[ice]) >= ICE_SHEET_BURIAL * np.bincount(on, relief[ice])
    sheet = (area >= ICE_SHEET_MIN_KM2 * 1e6) & buried
    return ice & sheet[np.maximum(body, 0)]


@njit(cache=True)
def _bodies(ice: B, ptr: I64, nbr: I64) -> I64:
    """Connected ice body of each node, -1 off the ice."""
    body = np.full(ice.size, -1, np.int64)
    stack = np.empty(ice.size, np.int64)
    count = 0
    for start in range(ice.size):
        if not ice[start] or body[start] >= 0:
            continue
        body[start] = count
        stack[0] = start
        top = 1
        while top:
            top -= 1
            i = stack[top]
            for k in range(ptr[i], ptr[i + 1]):
                j = nbr[k]
                if ice[j] and body[j] < 0:
                    body[j] = count
                    stack[top] = j
                    top += 1
        count += 1
    return body


def margin_distance(mesh: SphereMesh, ice: B) -> F64:
    """Signed distance (m) to the ice margin: positive on ice, zero halfway between nodes.

    The margin lies midway along each edge from an ice node to an ice-free one,
    so the zero contour of the interpolated distance is that margin.
    """
    if not ice.any():
        return np.full(mesh.size, -1e9)
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    border = ice[src] != ice[mesh.nbr]
    inner = np.unique(src[border & ice[src]])
    outer = np.unique(src[border & ~ice[src]])
    to_free = multi_source_distance(outer, np.zeros(outer.size), mesh.ptr, mesh.nbr, mesh.length_m)
    to_ice = multi_source_distance(inner, np.zeros(inner.size), mesh.ptr, mesh.nbr, mesh.length_m)

    def beyond_midpoint(distance: F64) -> F64:
        # Half an edge lies on the other side of the margin.
        return distance - 0.5 * np.minimum(distance, mesh.spacing_m)

    # Without an ice-free node (or without ice) a side is infinitely far.
    signed = np.where(ice, beyond_midpoint(to_free), -beyond_midpoint(to_ice))
    return np.clip(np.nan_to_num(signed, nan=0.0, posinf=1e9, neginf=-1e9), -1e9, 1e9)


def sample_ice(
    mesh: SphereMesh, ice: IceSheets, margin_m: F64, xyz: F64, detail_m: float, seed: int
) -> tuple[F64, F64, F64]:
    """Margin distance, thickness and mass balance at unit vectors ``xyz``.

    Fields are sampled at points displaced by noise down to ``detail_m``, so
    the margin bends below the mesh spacing; finer maps only add detail.
    """
    spacing = mesh.spacing_m
    moved = displace(
        xyz, mesh.radius_m,
        noise_octaves(ICE_TOP_SPACINGS * spacing, ICE_AMPLITUDE_SPACINGS * spacing, detail_m),
        stage_seed(seed, ICE_OUTLINE_STAGE),
    )
    return (
        sample_field(mesh, moved, margin_m),
        sample_field(mesh, moved, ice.thickness_m),
        sample_field(mesh, moved, ice.balance_m),
    )


def nye_thickness(margin_m: F64) -> F64:
    """Ice thickness (m) at ``margin_m`` inside a margin on a perfectly plastic profile.

    About 150 m at 1 km and 470 m at 10 km, so ice rises steeply from its margin.
    """
    return np.sqrt(NYE_M * np.maximum(margin_m, 0.0))
