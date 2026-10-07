# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Explainable annual climate v0 on the sphere mesh (provisional; not a GCM).

Every quantity follows a stated rule:

* **Temperature.** Sea-surface annual mean from latitude; on land, minus a lapse
  rate, colder high-latitude interiors and warmer clear-sky low-latitude land.
  The seasonal half-range grows with latitude, obliquity and continentality.
* **Wind.** Prevailing surface belts (trades, westerlies, polar easterlies), with
  equatorward/poleward components, shifted north and south for two seasons.
* **Moisture.** Semi-Lagrangian transport along the wind plus eddy mixing.
  - Ocean evaporation relaxes column moisture towards a temperature capacity
    (Clausius-Clapeyron, about 7 %/°C).
  - Storm tracks import moisture into land columns, fading inland.
  - Rain removes a share set by large-scale ascent (ITCZ wet, subtropical highs
    dry) plus orographic lift over the moisture scale height.
  - Supersaturation from cooling, such as ascent or poleward travel, rains out.
  - Land re-evaporates part of its rain.
  - Descending lee air warms and does not rain, which makes rain shadows.
* **Units.** Relative precipitation is scaled so the planetary land mean matches
  a declared target (mm/yr).
* **Runoff.** Budyko-Fu partition of precipitation and Hargreaves potential
  evapotranspiration.
* **Biomes.** Whittaker-style classes from temperature, warmest season and
  aridity (P / PET). Labels are provisional.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.sparse import csr_matrix
from scipy.spatial import KDTree

from dmtools.terrain.domain.planet import PlanetClimateSettings
from dmtools.terrain.pipeline.control import CancellationToken, check_cancelled
from dmtools.terrain.pipeline.planet_kernels import neighbour_mix
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, vertex_triangles

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]
type I8 = NDArray[np.int8]

MOISTURE_SCALE_HEIGHT_M = 2500.0
LAND_RECYCLING = 0.38
OCEAN_EVAPORATION = 0.25
BUDYKO_W = 2.6

# (|latitude| degrees, value) tables. Linear interpolation between knots.
ZONAL_WIND = (
    (0, 15, 28, 32, 45, 58, 62, 75, 90),
    (-0.8, -1.0, -0.3, 0.3, 1.0, 0.3, -0.3, -0.6, -0.2),
)
MERIDIONAL_WIND = ((0, 15, 30, 45, 60, 75, 90), (0.0, -0.35, 0.0, 0.25, 0.0, -0.25, 0.0))
ASCENT_PER_1000_KM = (
    (0, 8, 15, 22, 30, 42, 55, 65, 80, 90),
    (1.8, 1.5, 0.35, 0.04, 0.15, 1.0, 1.3, 0.9, 0.4, 0.25),
)
# Horizontal eddy diffusivity of moisture (m^2/s). Synoptic eddies mix moisture
# at 1e5-1e6 m^2/s, most strongly in the mid-latitude storm tracks. A physical
# diffusivity keeps climate boundaries independent of mesh density.
EDDY_DIFFUSIVITY = ((0, 20, 35, 50, 65, 90), (1.5e5, 1.5e5, 5e5, 7e5, 4.5e5, 2e5))
STORM_SUPPLY = ((0, 12, 18, 30, 36, 48, 62, 90), (0.01, 0.003, 0.0, 0.0, 0.02, 0.04, 0.025, 0.008))
STORM_INLAND_DECAY_M = 1.2e6
# Moisture travel per season: enough for steady state (16,000 km is within 6 % of
# 60,000 km in the 2026-10-06 convergence check), independent of mesh density.
MOISTURE_TRAVEL_M = 2.0e7


@dataclass(frozen=True, slots=True)
class Climate:
    temperature_c: F64
    warm_c: F64
    cold_c: F64
    wind_east: F64
    wind_north: F64
    precipitation_mm: F64
    pet_mm: F64
    runoff_mm: F64
    biome: I8


BIOMES = (
    "ocean", "ice", "tundra", "boreal forest", "cold desert", "temperate grassland",
    "temperate forest", "temperate rainforest", "hot desert", "savanna",
    "tropical seasonal forest", "tropical rainforest", "alpine", "mediterranean shrubland",
)


def _table(abs_lat_deg: F64, table: tuple[tuple[float, ...], tuple[float, ...]]) -> F64:
    return np.interp(abs_lat_deg, table[0], table[1])


def capacity(temp_c: F64) -> F64:
    """Relative column moisture capacity (Clausius-Clapeyron, ~7 %/°C)."""
    return np.exp(0.068 * (temp_c - 15.0))


def sea_temperature(lat: F64, s: PlanetClimateSettings) -> F64:
    return s.pole_sst_c + (s.equator_sst_c - s.pole_sst_c) * np.cos(lat) ** 1.3


def temperatures(
    mesh: SphereMesh, elevation: F64, land: B, coast_m: F64, s: PlanetClimateSettings
) -> tuple[F64, F64, F64]:
    lat = mesh.lat
    lapse = np.where(land, s.lapse_c_per_km * np.maximum(elevation, 0) / 1000, 0.0)
    continental = np.where(land, np.clip(coast_m / 1.5e6, 0, 1), 0.0)
    mean = (
        sea_temperature(lat, s)
        - lapse
        - 6 * continental * np.sin(np.abs(lat)) ** 2
        + np.where(land, 4.0 * (0.4 + 0.6 * continental) * np.cos(lat) ** 4, 0.0)
    )
    half_range = (2 + 22 * np.sin(np.abs(lat)) * s.obliquity_deg / 23.4) * (
        0.35 + 0.65 * continental
    )
    return mean, mean + half_range, mean - half_range


def prevailing_wind(
    lat: F64, s: PlanetClimateSettings, shift_deg: float = 0.0
) -> tuple[F64, F64]:
    """Surface wind (east, north) in m/s; ``shift_deg`` moves belts for a season."""
    lat_deg = np.rad2deg(lat) - shift_deg
    hemisphere = np.where(lat_deg >= 0, 1.0, -1.0)
    a = np.abs(lat_deg)
    zonal = _table(a, ZONAL_WIND) * s.wind_speed_m_s * (1 if s.prograde_rotation else -1)
    meridional = _table(a, MERIDIONAL_WIND) * s.wind_speed_m_s * hemisphere
    return zonal, meridional


def tangent_frame(xyz: F64) -> tuple[F64, F64]:
    up = np.array([0.0, 0.0, 1.0])
    east = np.cross(up, xyz)
    norm = np.linalg.norm(east, axis=1, keepdims=True)
    east = np.where(norm > 1e-9, east / np.maximum(norm, 1e-12), np.array([0.0, 1.0, 0.0]))
    return east, np.cross(xyz, east)


def departure_operator(
    mesh: SphereMesh, east: F64, north: F64, u: F64, v: F64, dt_s: float
) -> csr_matrix:
    """Sparse barycentric sampling of every node's upwind departure point."""
    displacement = (east * u[:, None] + north * v[:, None]) * (dt_s / mesh.radius_m)
    p = mesh.xyz - displacement
    p /= np.linalg.norm(p, axis=1, keepdims=True)
    nearest = np.asarray(KDTree(mesh.xyz).query(p, workers=-1)[1], dtype=np.int64)
    vt_ptr, vt_idx = vertex_triangles(mesh)
    tri, xyz, n = mesh.triangles, mesh.xyz, mesh.size
    counts = np.diff(vt_ptr)
    weights = np.zeros((n, 3))
    corners = np.zeros((n, 3), dtype=np.int64)
    found = np.zeros(n, dtype=bool)
    for k in range(int(counts.max())):
        ok = (counts[nearest] > k) & ~found
        if not ok.any():
            continue
        t = vt_idx[vt_ptr[nearest[ok]] + k]
        a, b, c = xyz[tri[t, 0]], xyz[tri[t, 1]], xyz[tri[t, 2]]
        q = p[ok]
        w = np.stack(
            (
                np.einsum("ij,ij->i", q, np.cross(b, c)),
                np.einsum("ij,ij->i", q, np.cross(c, a)),
                np.einsum("ij,ij->i", q, np.cross(a, b)),
            ),
            axis=1,
        )
        inside = np.all(w >= -1e-14, axis=1)
        idx = np.flatnonzero(ok)[inside]
        weights[idx] = w[inside] / w[inside].sum(axis=1, keepdims=True)
        corners[idx] = tri[t[inside]]
        found[idx] = True
    weights[~found] = (1.0, 0.0, 0.0)
    corners[~found, 0] = nearest[~found]
    rows = np.repeat(np.arange(n), 3)
    return csr_matrix((weights.ravel(), (rows, corners.ravel())), shape=(n, n))


def surface_gradient(mesh: SphereMesh, h: F64, east: F64, north: F64) -> tuple[F64, F64]:
    """Least-squares (east, north) gradient per node from its incident edges."""
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    d = mesh.xyz[mesh.nbr] - mesh.xyz[src]
    de = np.einsum("ij,ij->i", d, east[src]) * mesh.radius_m
    dn = np.einsum("ij,ij->i", d, north[src]) * mesh.radius_m
    dh = h[mesh.nbr] - h[src]
    gxx = np.bincount(src, de * de, mesh.size)
    gxy = np.bincount(src, de * dn, mesh.size)
    gyy = np.bincount(src, dn * dn, mesh.size)
    bx = np.bincount(src, de * dh, mesh.size)
    by = np.bincount(src, dn * dh, mesh.size)
    det = gxx * gyy - gxy * gxy
    det = np.where(det > 0, det, 1.0)
    return (gyy * bx - gxy * by) / det, (gxx * by - gxy * bx) / det


def potential_evapotranspiration(lat: F64, temp: F64, coast_m: F64) -> F64:
    """Hargreaves PET (mm/yr) with annual-mean radiation and continental diurnal range."""
    radiation = 14.8 * (0.42 + 0.58 * np.cos(lat) ** 1.5)  # mm/day equivalent
    diurnal = 8.0 + 6.0 * np.clip(coast_m / 1.5e6, 0, 1)
    pet = np.where(temp > -17.8, 365 * 0.0023 * radiation * (temp + 17.8) * np.sqrt(diurnal), 0)
    return np.where(temp > 0, pet, pet * np.clip(1 + temp / 10, 0, 1))


def simulate_climate(
    mesh: SphereMesh,
    elevation: F64,
    land: B,
    coast_m: F64,
    settings: PlanetClimateSettings | None = None,
    steps: int | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> Climate:
    s = settings or PlanetClimateSettings()
    lat = mesh.lat
    abs_lat = np.abs(np.rad2deg(lat))
    temp, warm, cold = temperatures(mesh, elevation, land, coast_m, s)
    east, north = tangent_frame(mesh.xyz)
    step_m = mesh.spacing_m
    dt = step_m / max(s.wind_speed_m_s, 1e-6)
    cap = capacity(temp)
    ground = np.where(land, np.maximum(elevation, 0), 0.0)
    grad_e, grad_n = surface_gradient(mesh, ground, east, north)
    # Per-step relaxation towards the neighbour mean is a diffusion with
    # D = w * spacing^2 / (4 dt); split it into stable substeps of w <= 0.5.
    mixing = 4 * _table(abs_lat, EDDY_DIFFUSIVITY) * dt / step_m**2
    substeps = max(1, int(np.ceil(float(mixing.max()) / 0.5)))
    mixing = mixing / substeps
    background = 0.6 * capacity(sea_temperature(lat, s))
    inland = np.exp(-coast_m / STORM_INLAND_DECAY_M)
    supply = np.where(land, _table(abs_lat, STORM_SUPPLY) * inland, 0.0)
    evaporation = np.where(land, 0.0, OCEAN_EVAPORATION)
    recycling = np.where(land, LAND_RECYCLING, 0.0)
    shift = 8.0 * s.obliquity_deg / 23.4
    count = steps or max(1, int(MOISTURE_TRAVEL_M / step_m))
    precip = np.zeros(mesh.size)
    u_mean = np.zeros(mesh.size)
    v_mean = np.zeros(mesh.size)
    for season in (-shift, shift):
        u, v = prevailing_wind(lat, s, season)
        u_mean += u / 2
        v_mean += v / 2
        advect = departure_operator(mesh, east, north, u, v, dt)
        lift = np.maximum(0.0, u * grad_e + v * grad_n) * dt  # forced ascent per step, m
        large = _table(np.abs(np.rad2deg(lat) - season), ASCENT_PER_1000_KM) * step_m / 1e6
        orographic = np.where(land, 0.5 * lift / MOISTURE_SCALE_HEIGHT_M, 0.0)
        rain_fraction = np.clip(large + orographic, 0, 0.9)
        q = cap.copy()
        seasonal = np.zeros(mesh.size)
        for step in range(count):
            if step % 64 == 0:
                check_cancelled(cancellation)
            q = advect @ q
            q = neighbour_mix(q, mesh.ptr, mesh.nbr, mixing, substeps)
            q = q + evaporation * np.maximum(cap - q, 0.0)
            q = q + supply * np.maximum(background - q, 0.0)
            excess = np.maximum(q - cap, 0.0)
            rain = rain_fraction * (q - excess) + excess
            q = q - rain + recycling * rain
            seasonal = 0.9 * seasonal + 0.1 * rain
        precip += seasonal / 2
    weight = mesh.area_m2 * land
    mean = float(np.sum(precip * weight) / np.sum(weight))
    precip_mm = precip * (s.mean_land_precip_mm / max(mean, 1e-12))
    pet = potential_evapotranspiration(lat, temp, coast_m)
    ratio = pet / np.maximum(precip_mm, 1e-6)
    actual = precip_mm * (1 + ratio - (1 + ratio**BUDYKO_W) ** (1 / BUDYKO_W))
    runoff = np.where(land, np.maximum(precip_mm - actual, 0.0), 0.0)
    biome = classify(temp, warm, precip_mm, pet, elevation, land)
    return Climate(temp, warm, cold, u_mean, v_mean, precip_mm, pet, runoff, biome)


def classify(temp: F64, warm: F64, precip: F64, pet: F64, elevation: F64, land: B) -> I8:
    """Whittaker-style labels from mean/warm-season temperature and aridity P/PET."""
    aridity = precip / np.maximum(pet, 1.0)
    tundra = warm < 10
    boreal = ~tundra & (temp < 3)
    temperate = ~tundra & ~boreal & (temp < 18)
    tropical = ~tundra & (temp >= 18)
    temperate_class = np.select(
        [aridity < 0.25, aridity < 0.6, (aridity < 1.0) & (warm > 22), aridity < 2.0],
        [4, 5, 13, 6],
        7,
    )
    tropical_class = np.select([aridity < 0.25, aridity < 0.75, aridity < 1.4], [8, 9, 10], 11)
    b = np.zeros(temp.shape, dtype=np.int8)
    b[tundra] = 2
    b[boreal] = np.where(aridity[boreal] < 0.35, 4, 3)
    b[temperate] = temperate_class[temperate]
    b[tropical] = tropical_class[tropical]
    b[warm < 0] = 1
    b[(elevation > 2500) & (warm < 6) & (warm >= 0)] = 12
    b[~land] = 0
    return b
