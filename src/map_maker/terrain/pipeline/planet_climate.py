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

from map_maker.terrain.domain.planet import PlanetClimateSettings
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.planet_kernels import neighbour_mix
from map_maker.terrain.pipeline.planet_koppen import classify_koppen
from map_maker.terrain.pipeline.planet_mesh import SphereMesh, sample_field, vertex_triangles

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
# Boundary currents: peak anomalies (°C), offshore reach and inland reach (m).
COLD_CURRENT_C = 5.0
WARM_CURRENT_C = 2.5
CURRENT_REACH_M = 700e3
COAST_INFLUENCE_M = 250e3
# Share of large-scale rain suppressed under the subsiding air of a full cold anomaly.
COLD_CURRENT_SUBSIDENCE = 0.85
# Mass elevation effect: summer warming per km of massif mean elevation above 1 km.
MASS_ELEVATION_C_PER_KM = 1.5
MASS_ELEVATION_REACH_M = 200e3
MASS_ELEVATION_PASSES = 300
# Land travel over which air loses its marine character (e-folding, m).
MARITIME_DECAY_M = 900e3
MARITIME_TRAVEL_M = 8e6
# Extra poleward shift (deg) of the summer rain belt over heated land, and its reach.
MONSOON_EXTRA_DEG = 10.0
MONSOON_REACH_M = 1.5e6


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
    continentality: F64  # 0 maritime .. 1 continental air (downwind distance from the sea)
    precip_warm_mm: F64  # warm-half-year rate (mm/yr)
    precip_cold_mm: F64  # cold-half-year rate (mm/yr)
    koppen: I8  # index into planet_koppen.KOPPEN


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


def boundary_currents(mesh: SphereMesh, land: B, coast_m: F64) -> F64:
    """Sea-surface (and coastal land) temperature anomaly of boundary currents (°C).

    Subtropical gyres carry cold water along the eastern side of each ocean basin
    (California, Humboldt, Canary, Benguela, West Australian currents) and warm
    water along the western side (Gulf Stream, Kuroshio, Agulhas, Brazil, East
    Australian). The direction to the nearest coast, -grad(coast distance),
    tells which side a node is on: open water whose nearest land lies to the
    east, and land whose nearest sea lies to the west, are on a cold coast.
    """
    east, north = tangent_frame(mesh.xyz)
    gradient_east, gradient_north = surface_gradient(mesh, coast_m, east, north)
    toward_east = -gradient_east / np.maximum(np.hypot(gradient_east, gradient_north), 1e-12)
    west_coast = np.where(land, -toward_east, toward_east)
    latitude = np.abs(np.rad2deg(mesh.lat))
    cold_band = _smooth(latitude, 8, 15) * (1 - _smooth(latitude, 32, 42))
    warm_band = _smooth(latitude, 12, 20) * (1 - _smooth(latitude, 40, 50))
    reach = np.exp(-np.maximum(coast_m, 0) / np.where(land, COAST_INFLUENCE_M, CURRENT_REACH_M))
    cold = COLD_CURRENT_C * _smooth(west_coast, 0.2, 0.7) * cold_band
    warm = WARM_CURRENT_C * _smooth(-west_coast, 0.2, 0.7) * warm_band
    return (warm - cold) * reach


def _smooth(x: F64, a: float, b: float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def temperatures(
    mesh: SphereMesh,
    elevation: F64,
    land: B,
    coast_m: F64,
    s: PlanetClimateSettings,
    continental: F64 | None = None,
) -> tuple[F64, F64, F64]:
    """Annual mean, warmest- and coldest-month temperature (deg C).

    ``continental`` (0..1) sets how continental the air is; without it, the
    distance from the coast stands in for it.
    """
    lat = mesh.lat
    lapse = np.where(land, s.lapse_c_per_km * np.maximum(elevation, 0) / 1000, 0.0)
    if continental is None:
        continental = np.clip(coast_m / 1.5e6, 0, 1)
    continental = np.where(land, continental, 0.0)
    mean = (
        sea_temperature(lat, s)
        + boundary_currents(mesh, land, coast_m)
        - lapse
        - 6 * continental * np.sin(np.abs(lat)) ** 2
        + np.where(land, 4.0 * (0.4 + 0.6 * continental) * np.cos(lat) ** 4, 0.0)
    )
    half_range = (2 + 22 * np.sin(np.abs(lat)) * s.obliquity_deg / 23.4) * (
        0.35 + 0.65 * continental
    )
    # Mass elevation effect: big high massifs heat the air above them in summer.
    massif = mass_elevation_warming(mesh, np.where(land, elevation, 0.0))
    return mean + massif / 2, mean + half_range + massif, mean - half_range


def mass_elevation_warming(mesh: SphereMesh, ground_m: F64) -> F64:
    """Summer warming (deg C) of large, high massifs (Massenerhebung).

    A plateau's surface heats the air above it, so its snowline and treeline
    sit far higher than free-air lapse rates suggest (Tibet is ~5-7 C warmer in
    summer than the free air at 4.5 km). Warming grows by MASS_ELEVATION_C_PER_KM
    per km of mean elevation above 1 km within ~MASS_ELEVATION_REACH_M.
    """
    reach = round((MASS_ELEVATION_REACH_M / mesh.spacing_m) ** 2)
    passes = min(MASS_ELEVATION_PASSES, max(1, reach))
    mean = neighbour_mix(ground_m, mesh.ptr, mesh.nbr, np.full(mesh.size, 0.5), passes)
    return MASS_ELEVATION_C_PER_KM * np.maximum(mean - 1000.0, 0.0) / 1000.0


def maritime_air(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    advect: list[csr_matrix],
    mixing: F64,
    substeps: int,
    steps: int,
) -> F64:
    """Continentality (0..1): how far air has travelled over land, downwind.

    Air leaves the sea maritime and loses its marine character over about
    MARITIME_DECAY_M of land travel. West coasts under the westerlies stay mild
    (Bergen, Vancouver); east coasts at the same latitude get continental air
    from the interior (Halifax, Vladivostok). Sea breezes keep a thin strip
    along every coast partly maritime.
    """
    decay = np.where(land, np.exp(-mesh.spacing_m / MARITIME_DECAY_M), 1.0)
    result = np.zeros(mesh.size)
    for operator in advect:
        m = np.where(land, 0.0, 1.0)
        for _ in range(steps):
            m = operator @ m
            m = neighbour_mix(m, mesh.ptr, mesh.nbr, mixing, substeps)
            m = np.where(land, m * decay, 1.0)
        result += m / len(advect)
    breeze = 0.5 * np.exp(-np.maximum(coast_m, 0.0) / 150e3)
    return np.where(land, 1.0 - np.maximum(result, breeze), 0.0)


def monsoon_shift(mesh: SphereMesh, land: B, s: PlanetClimateSettings) -> tuple[F64, F64]:
    """Seasonal latitude shift (degrees) of the wind and rain belts at each node.

    Over open ocean the ITCZ follows the sun only a few degrees. Summer heating of
    large low-latitude landmasses deepens a thermal low that pulls the rain belt
    and onshore winds far poleward over and around them (South Asia to ~25 N,
    the Sahel, northern Australia; Gadgil 2003). The extra shift grows with the
    share of heatable land (5-35 deg of the summer hemisphere) within ~1,500 km.
    Returns the (southern summer, northern summer) shifts.
    """
    base = 8.0 * s.obliquity_deg / 23.4
    latitude = np.rad2deg(mesh.lat)
    passes = max(1, round((MONSOON_REACH_M / mesh.spacing_m) ** 2))
    weight = np.full(mesh.size, 0.5)
    shifts = []
    for sign in (-1.0, 1.0):
        band = land & (sign * latitude > 5) & (sign * latitude < 35)
        heat = neighbour_mix(band.astype(np.float64), mesh.ptr, mesh.nbr, weight, passes)
        extra = MONSOON_EXTRA_DEG * np.clip(heat / 0.5, 0, 1) * s.obliquity_deg / 23.4
        shifts.append(sign * (base + extra))
    return shifts[0], shifts[1]


def snowline_m(
    mesh: SphereMesh, land: B, coast_m: F64, settings: PlanetClimateSettings | None = None
) -> F64:
    """Glacier equilibrium-line altitude (m): where the warm season reaches ~0 °C.

    Earth's ELA is ~4.5-5.5 km in the tropics, ~3 km at 45° and near sea level in
    the polar regions; the warm-season freezing level plus a few hundred metres
    follows it.
    """
    s = settings or PlanetClimateSettings()
    _, warm, _ = temperatures(mesh, np.zeros(mesh.size), land, coast_m, s)
    return np.maximum(warm, 0.0) / s.lapse_c_per_km * 1000 + 300.0


def prevailing_wind(
    lat: F64, s: PlanetClimateSettings, shift_deg: float | F64 = 0.0
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
    east, north = tangent_frame(mesh.xyz)
    step_m = mesh.spacing_m
    dt = step_m / max(s.wind_speed_m_s, 1e-6)
    # Per-step relaxation towards the neighbour mean is a diffusion with
    # D = w * spacing^2 / (4 dt); split it into stable substeps of w <= 0.5.
    mixing = 4 * _table(abs_lat, EDDY_DIFFUSIVITY) * dt / step_m**2
    substeps = max(1, int(np.ceil(float(mixing.max()) / 0.5)))
    mixing = mixing / substeps
    seasons = monsoon_shift(mesh, land, s)  # southern, then northern summer
    winds = [prevailing_wind(lat, s, season) for season in seasons]
    operators = [departure_operator(mesh, east, north, u, v, dt) for u, v in winds]
    continental = maritime_air(
        mesh, land, coast_m, operators, mixing, substeps,
        max(1, int(MARITIME_TRAVEL_M / step_m)),
    )
    temp, warm, cold = temperatures(mesh, elevation, land, coast_m, s, continental)
    # Air over cold currents subsides and is stable: coastal fog, little rain
    # (Atacama, Namib, Baja California).
    stable = np.clip(-boundary_currents(mesh, land, coast_m) / COLD_CURRENT_C, 0, 1)
    cap = capacity(temp)
    ground = np.where(land, np.maximum(elevation, 0), 0.0)
    grad_e, grad_n = surface_gradient(mesh, ground, east, north)
    background = 0.6 * capacity(sea_temperature(lat, s))
    inland = np.exp(-coast_m / STORM_INLAND_DECAY_M)
    supply = np.where(land, _table(abs_lat, STORM_SUPPLY) * inland, 0.0)
    evaporation = np.where(land, 0.0, OCEAN_EVAPORATION)
    recycling = np.where(land, LAND_RECYCLING, 0.0)
    count = steps or max(1, int(MOISTURE_TRAVEL_M / step_m))
    by_season: list[F64] = []
    u_mean = np.zeros(mesh.size)
    v_mean = np.zeros(mesh.size)
    for season, (u, v), advect in zip(seasons, winds, operators, strict=True):
        u_mean += u / 2
        v_mean += v / 2
        lift = np.maximum(0.0, u * grad_e + v * grad_n) * dt  # forced ascent per step, m
        large = _table(np.abs(np.rad2deg(lat) - season), ASCENT_PER_1000_KM) * step_m / 1e6
        large = large * (1 - COLD_CURRENT_SUBSIDENCE * stable)
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
        by_season.append(seasonal)
    north_summer = lat >= 0
    warm_rain = np.where(north_summer, by_season[1], by_season[0])
    cold_rain = np.where(north_summer, by_season[0], by_season[1])
    return _surface_climate(
        mesh, elevation, land, coast_m, s, (temp, warm, cold), u_mean, v_mean,
        (warm_rain, cold_rain), continental,
    )


def _surface_climate(
    mesh: SphereMesh,
    elevation: F64,
    land: B,
    coast_m: F64,
    s: PlanetClimateSettings,
    temperature: tuple[F64, F64, F64],
    wind_east: F64,
    wind_north: F64,
    seasonal_precip: tuple[F64, F64],
    continental: F64,
) -> Climate:
    """Scale precipitation to the land mean, then local PET, runoff, biomes and Koppen.

    ``seasonal_precip`` holds relative warm- and cold-half-year precipitation.
    """
    temp, warm, cold = temperature
    warm_rain, cold_rain = seasonal_precip
    precip = (warm_rain + cold_rain) / 2
    weight = mesh.area_m2 * land
    mean = float(np.sum(precip * weight) / np.sum(weight))
    scale = s.mean_land_precip_mm / max(mean, 1e-12)
    precip_mm = precip * scale
    pet = potential_evapotranspiration(mesh.lat, temp, coast_m)
    ratio = pet / np.maximum(precip_mm, 1e-6)
    actual = precip_mm * (1 + ratio - (1 + ratio**BUDYKO_W) ** (1 / BUDYKO_W))
    runoff = np.where(land, np.maximum(precip_mm - actual, 0.0), 0.0)
    biome = classify(temp, warm, precip_mm, pet, elevation, land)
    koppen = classify_koppen(temp, warm, cold, warm_rain * scale, cold_rain * scale, land)
    return Climate(
        temp, warm, cold, wind_east, wind_north, precip_mm, pet, runoff, biome,
        continental, warm_rain * scale, cold_rain * scale, koppen,
    )


def with_islands(
    climate: Climate,
    mesh: SphereMesh,
    land: B,
    islands: B,
    elevation: F64,
    coast_m: F64,
    settings: PlanetClimateSettings | None = None,
) -> Climate:
    """Climate on new volcanic islands: the sea-level fields there, lapse-corrected.

    Island nodes keep the simulated moisture of their ocean surroundings; their
    temperature falls with height, and PET, runoff, biome and Koppen class are
    recomputed as land.
    """
    if not islands.any():
        return climate
    s = settings or PlanetClimateSettings()
    lapse = np.where(islands, s.lapse_c_per_km * np.maximum(elevation, 0.0) / 1000, 0.0)
    temp, warm, cold = climate.temperature_c - lapse, climate.warm_c - lapse, climate.cold_c - lapse
    pet = np.where(islands, potential_evapotranspiration(mesh.lat, temp, coast_m), climate.pet_mm)
    precip = climate.precipitation_mm
    ratio = pet / np.maximum(precip, 1e-6)
    actual = precip * (1 + ratio - (1 + ratio**BUDYKO_W) ** (1 / BUDYKO_W))
    runoff = np.where(islands, np.maximum(precip - actual, 0.0), climate.runoff_mm)
    ground = land | islands
    return Climate(
        temp, warm, cold, climate.wind_east, climate.wind_north, precip, pet, runoff,
        classify(temp, warm, precip, pet, elevation, ground),
        climate.continentality, climate.precip_warm_mm, climate.precip_cold_mm,
        classify_koppen(temp, warm, cold, climate.precip_warm_mm, climate.precip_cold_mm, ground),
    )


def downscale_climate(
    coarse_mesh: SphereMesh,
    coarse: Climate,
    mesh: SphereMesh,
    elevation: F64,
    land: B,
    coast_m: F64,
    settings: PlanetClimateSettings | None = None,
) -> Climate:
    """Climate on a fine mesh from moisture transport solved on a coarse one.

    Precipitation and winds vary over hundreds of kilometres, so they are
    interpolated. Temperature (with its lapse rate), PET, runoff and biomes are
    local and are recomputed from the fine relief.
    """
    s = settings or PlanetClimateSettings()
    continental = np.clip(sample_field(coarse_mesh, mesh.xyz, coarse.continentality), 0, 1)
    temperature = temperatures(mesh, elevation, land, coast_m, s, continental)
    warm_rain = np.maximum(sample_field(coarse_mesh, mesh.xyz, coarse.precip_warm_mm), 0.0)
    cold_rain = np.maximum(sample_field(coarse_mesh, mesh.xyz, coarse.precip_cold_mm), 0.0)
    return _surface_climate(
        mesh, elevation, land, coast_m, s, temperature,
        sample_field(coarse_mesh, mesh.xyz, coarse.wind_east),
        sample_field(coarse_mesh, mesh.xyz, coarse.wind_north),
        (warm_rain, cold_rain),
        continental,
    )


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
