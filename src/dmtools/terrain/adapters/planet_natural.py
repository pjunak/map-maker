# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Natural-colour cartography for planet rasters (derived display, not authority).

The look follows natural-colour shaded-relief atlases rather than discrete
biome fills:

* **Display relief.** The triangle-interpolated planet surface plus sub-mesh
  eroded detail, scaled by local relief, faded at coasts and suppressed along
  large rivers.
* **Shading.** Multi-directional hillshade on that display relief.
* **Land colour.** Continuous colour from per-pixel climate:
  - aridity P/PET with soil patchiness sets desert, steppe, grass or forest;
  - temperature, lapse-corrected to the pixel's height, picks tropical,
    temperate or boreal forest, tundra and perennial snow;
  - slope exposes rock, and bare dryland hills read dark brown.
* **Ocean colour.** Depth-tinted, with subtly shaded abyssal texture.
* **Rivers.** Tapered with discharge, smoothed and anti-aliased.
"""

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter, gaussian_filter1d

from dmtools.terrain.adapters.planet_render import (
    FrameRaster,
    PlanetRasters,
    climate_images,
    ice_covered,
    planet_rasters,
    river_threshold_m3_s,
)
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.pipeline.planet_detail import carve_valleys, eroded_fbm
from dmtools.terrain.pipeline.planet_kernels import multi_source_distance, neighbour_mix

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]
type RGB = tuple[int, int, int]

DETAIL_SEED = 7
DETAIL_WAVELENGTH_M = 110e3
DETAIL_OCTAVES = 8
SEA_TEXTURE_M = 180.0
EXAGGERATION = 13.0
CARVE_ERODIBILITY = 0.3  # K * dt for display valley carving (m^0)
CARVE_STEPS = 4
# (radius m, weight, height scale m) of the multi-scale openness term.
OPENNESS_SCALES = ((8e3, 0.4, 120.0), (30e3, 0.35, 350.0), (120e3, 0.25, 800.0))
OPENNESS_GAIN = 0.3
# Moisture shift (in log aridity) between ridge crests and valley floors.
TERRAIN_MOISTURE = 0.5
ICE_BASAL_STRESS_PA = 1e5
ICE_BED_SMOOTHING_M = 150e3

DESERT_HOT: RGB = (208, 186, 146)
DESERT_COLD: RGB = (176, 166, 140)
DESERT_OCHRE: RGB = (186, 146, 106)
DESERT_GREY: RGB = (150, 136, 118)
STEPPE: RGB = (160, 152, 104)
GRASS_WARM: RGB = (128, 140, 80)
GRASS_COOL: RGB = (118, 136, 88)
FOREST_TROPICAL: RGB = (46, 82, 42)
FOREST_TEMPERATE: RGB = (68, 98, 56)
FOREST_BOREAL: RGB = (58, 78, 60)
TUNDRA: RGB = (150, 146, 124)
ROCK: RGB = (132, 122, 112)
BARE_DRYLAND: RGB = (124, 102, 80)
SNOW: RGB = (242, 244, 247)
LAKE: RGB = (62, 106, 146)
SALT_FLAT: RGB = (214, 210, 196)
RIVER: RGB = (62, 104, 150)
SEA_STOPS: tuple[tuple[float, RGB], ...] = (
    (0, (62, 110, 144)),
    (60, (55, 101, 137)),
    (160, (47, 91, 129)),
    (1000, (35, 73, 113)),
    (2500, (27, 59, 99)),
    (4500, (19, 44, 82)),
    (7000, (12, 30, 62)),
)
HYPSOMETRIC: tuple[tuple[float, RGB], ...] = (
    (0, (104, 136, 92)),
    (300, (138, 156, 106)),
    (800, (178, 172, 128)),
    (1500, (176, 150, 112)),
    (2500, (150, 128, 106)),
    (3500, (164, 156, 150)),
    (5000, (236, 236, 236)),
)


def _smooth(x: F64, a: float, b: float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _mix(base: F64, colour: RGB | F64, weight: F64) -> F64:
    target = np.asarray(colour, dtype=np.float64)
    return base * (1 - weight)[..., None] + target * weight[..., None]


def ramp(z: F64, stops: tuple[tuple[float, RGB], ...]) -> F64:
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    return np.stack([np.interp(z, xs, [s[1][k] for s in stops]) for k in range(3)], axis=-1)


@dataclass(frozen=True)
class DisplayFields:
    """Per-pixel fields shared by the natural and relief maps."""

    elevation_m: F64  # display relief: land with detail, sea with texture
    base_m: F64  # interpolated planet land surface (no detail)
    slope: F64  # display slope (m/m)
    light: F64  # multi-directional hillshade, 1.0 on flat ground
    position: F64  # -1 (valley floor) .. +1 (ridge crest), multi-scale openness


def display_fields(
    result: PlanetResult, raster: FrameRaster, land_px: B, base_land: F64, base_sea: F64
) -> DisplayFields:
    mesh = result.mesh
    radius = mesh.radius_m
    shape = raster.shape
    points = raster.queries
    coast = raster.interpolate(
        mesh, np.maximum(np.where(np.isfinite(result.coast_m), result.coast_m, 0), 0)
    )
    discharge = raster.interpolate(mesh, np.log1p(np.maximum(result.lakes.discharge_m3_s, 0.0)))
    ridged = _smooth(base_land, 500, 2200).ravel()
    detail = eroded_fbm(
        points, ridged, DETAIL_SEED, DETAIL_OCTAVES, radius / DETAIL_WAVELENGTH_M, 0.55, 0.12
    ).reshape(shape) - 0.17 * ridged.reshape(shape)
    rows, columns = shape
    dy = np.pi * radius / rows
    dx = 2 * np.pi * radius / columns * np.maximum(np.cos(raster.latitude), 0.05)[:, None]
    # Detail follows the mesh-scale relief: flat alluvial plains and plateau tops
    # stay smooth, as they look on Earth, while slopes get ridges and gullies.
    base_slope = np.hypot(
        np.gradient(base_land, axis=0) / dy,
        (np.roll(base_land, -1, 1) - np.roll(base_land, 1, 1)) / (2 * dx),
    )
    ruggedness = 0.2 + 0.8 * _smooth(gaussian_filter(base_slope, 2.0), 0.001, 0.012)
    amplitude = (
        (45 + 0.38 * base_land)
        * ruggedness
        * _smooth(coast, 0, 25e3)
        / (1 + np.sqrt(np.expm1(discharge)) / 12)
    )
    rough = np.where(land_px, base_land + amplitude * detail, 0.0)
    land = np.maximum(
        base_land + amplitude * detail - valley_depth(rough, raster, land_px, amplitude), 1.0
    )
    ice = ice_covered(result)
    if ice.any():
        surface = raster.interpolate(mesh, np.where(ice, ice_surface(result, ice), 0.0))
        covered = land_px & (raster.interpolate(mesh, ice.astype(np.float64)) > 0.5)
        land = np.where(covered, np.maximum(surface, land), land)
    hills = eroded_fbm(
        points, np.zeros(len(points)), DETAIL_SEED + 4, 5, radius / 60e3, 0.55, 0.0
    ).reshape(shape)
    sea = base_sea + _smooth(-base_sea, 500, 3000) * SEA_TEXTURE_M * hills
    z = np.where(land_px, land, np.minimum(sea, -1.0))
    gy = np.gradient(z, axis=0) / dy
    gx = (np.roll(z, -1, 1) - np.roll(z, 1, 1)) / (2 * dx)
    slope, light = shading(gx, gy, EXAGGERATION)
    position = openness(z, dy, dx[:, 0])
    light = light * (1 + OPENNESS_GAIN * position)
    return DisplayFields(z, base_land, slope, light, position)


def ice_surface(result: PlanetResult, ice: B) -> F64:
    """Display surface of ice sheets (m): Nye's perfectly plastic profile.

    Basal shear stress tau0 ~ 100 kPa gives a thickness h = sqrt(2 tau0 / (rho g) d)
    at a distance d from the ice margin: ~3.3 km at 500 km, as on Antarctica and
    Greenland. The ice rests on a smoothed bed, so it shades as a smooth dome;
    nunataks keep their own height where they rise above it.
    """
    mesh = result.mesh
    bed = np.where(result.land, np.maximum(result.elevation_m, 0.0), 0.0)
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    margin = np.flatnonzero(np.bincount(src, ice[src] & ~ice[mesh.nbr], mesh.size) > 0)
    if not len(margin):
        return bed
    inside = multi_source_distance(
        margin, np.zeros(margin.size), mesh.ptr, mesh.nbr, mesh.length_m
    )
    thickness = np.sqrt(2 * ICE_BASAL_STRESS_PA / (917.0 * 9.81) * inside)
    passes = max(1, round((ICE_BED_SMOOTHING_M / mesh.spacing_m) ** 2))
    smooth_bed = neighbour_mix(bed, mesh.ptr, mesh.nbr, np.full(mesh.size, 0.5), passes)
    return np.where(ice, np.maximum(smooth_bed + thickness, bed), bed)


def openness(z: F64, dy_m: float, dx_m: F64) -> F64:
    """Height above the local mean at several radii, squashed to -1..1.

    A cheap stand-in for texture shading (Brown 2010) and sky-view factor
    (Zakšek et al. 2011): ridges brighten and valleys darken at every scale, so
    the relief hierarchy reads even where the hillshade light runs along a ridge.
    ``dx_m`` is the east-west pixel width of each row; columns wrap around.
    """
    total = np.zeros_like(z)
    for radius_m, weight, scale_m in OPENNESS_SCALES:
        blurred = gaussian_filter1d(z, radius_m / dy_m, axis=0, mode="nearest")
        # Rows share a latitude-dependent east-west sigma; blur bands of rows
        # with similar sigma together.
        sigma = np.minimum(radius_m / dx_m, z.shape[1] / 4)
        bands = np.round(np.log(sigma) * 8).astype(np.int64)
        for band in np.unique(bands):
            rows = bands == band
            blurred[rows] = gaussian_filter1d(
                blurred[rows], float(np.median(sigma[rows])), axis=1, mode="wrap"
            )
        total += weight * np.tanh((z - blurred) / scale_m)
    return total


def valley_depth(rough: F64, raster: FrameRaster, land_px: B, amplitude: F64) -> F64:
    """Display-only valley incision below the mesh scale (see ``carve_valleys``).

    Stream power routed over the textured surface turns its hollows into
    branching valleys, so relief reads at Earth-like scale instead of as broad
    smooth ramps between mesh-scale rivers. Incision is capped at the local
    detail amplitude and faded on flats, which would carve grid-aligned grooves.
    """
    rows, columns = raster.shape
    radius = raster.frame.radius_km * 1000
    dy = np.pi * radius / rows
    dx = 2 * np.pi * radius / columns * np.maximum(np.cos(raster.latitude), 0.05)
    carved = carve_valleys(rough, ~land_px, dy, dx, CARVE_ERODIBILITY, 0.5, CARVE_STEPS, wrap=True)
    gy = np.gradient(rough, axis=0) / dy
    gx = np.gradient(rough, axis=1) / dx[:, None]
    steep = np.clip((gaussian_filter(np.hypot(gx, gy), 2.0) - 0.002) / 0.01, 0, 1)
    depth = np.clip(rough - carved, 0, amplitude) * steep
    return gaussian_filter(depth, (1.0, 1.0), mode=cast(Any, ("nearest", "wrap")))


def shading(gx: F64, gy: F64, exaggeration: float) -> tuple[F64, F64]:
    """Slope (m/m) and multi-directional hillshade normalised to 1 on flat ground.

    ``gx`` is the eastward and ``gy`` the southward (image-row) height gradient.
    """

    def shade(azimuth: float, altitude: float) -> F64:
        az, alt = np.deg2rad(azimuth), np.deg2rad(altitude)
        lx, ly, lz = np.cos(alt) * np.sin(az), np.cos(alt) * np.cos(az), np.sin(alt)
        sx, sy = gx * exaggeration, gy * exaggeration
        return (-sx * lx + sy * ly + lz) / np.sqrt(sx * sx + sy * sy + 1)

    combined = 0.62 * shade(315, 42) + 0.23 * shade(270, 50) + 0.15 * shade(355, 55)
    flat = (
        0.62 * np.sin(np.deg2rad(42))
        + 0.23 * np.sin(np.deg2rad(50))
        + 0.15 * np.sin(np.deg2rad(55))
    )
    return np.hypot(gx, gy), np.clip(combined, 0, None) / flat


@dataclass(frozen=True)
class PixelClimate:
    """Climate at each pixel, already lapse-corrected to the displayed height."""

    temperature_c: F64
    warm_season_c: F64
    precipitation_mm: F64
    pet_mm: F64


def land_colour(
    points: F64,
    radius_m: float,
    climate: PixelClimate,
    z: F64,
    slope: F64,
    light: F64,
    wet: F64 | None = None,
    position: F64 | None = None,
    fine_wavelength_m: float = 35e3,
) -> F64:
    """Continuous natural land colour (desert to forest, tundra, rock, snow), shaded.

    ``wet`` (0..1, blurred river coverage) greens river corridors in drylands.
    ``position`` (-1 valley floor .. +1 ridge crest) ties the vegetation mosaic
    to the terrain: valleys gather water and soil, ridges and steep slopes shed
    them. ``fine_wavelength_m`` sets the finest mosaic scale (smaller when zoomed).
    """
    shape = z.shape
    zeros = np.zeros(len(points))
    temperature, warm = climate.temperature_c, climate.warm_season_c
    # Soil, groundwater and local relief make vegetation boundaries ragged at
    # every scale; the fine octave also hides the parent mesh's straight edges.
    patch = eroded_fbm(points, zeros, 41, 5, radius_m / 300e3, 0.55, 0.0).reshape(shape)
    fine = eroded_fbm(points, zeros, 53, 4, radius_m / fine_wavelength_m, 0.55, 0.0).reshape(
        shape
    )
    terrain = (
        np.zeros(shape)
        if position is None
        else -TERRAIN_MOISTURE * position - 0.8 * _smooth(slope, 0.1, 0.5)
    )
    aridity = (
        climate.precipitation_mm
        / np.maximum(climate.pet_mm, 1.0)
        * np.exp(0.45 * patch + 0.3 * fine + terrain)
    )
    if wet is not None:
        # Only drylands show river corridors; humid land is green either way.
        aridity = aridity * (1 + 15 * wet * (1 - _smooth(aridity, 0.25, 0.9)))
    veg = _smooth(aridity, 0.04, 0.8)
    forest = _smooth(aridity, 0.6, 1.25) * _smooth(warm, 9, 14)
    desert = _mix(_fill(shape, DESERT_COLD), DESERT_HOT, _smooth(temperature, 5, 18))
    hue = eroded_fbm(points, zeros, 43, 4, radius_m / 450e3, 0.5, 0.0).reshape(shape)
    hue = hue + 0.6 * fine
    desert = _mix(desert, DESERT_OCHRE, _smooth(hue, 0.0, 0.5) * 0.55)
    desert = _mix(desert, DESERT_GREY, _smooth(-hue, 0.1, 0.6) * 0.5)
    grass = _mix(_fill(shape, GRASS_COOL), GRASS_WARM, _smooth(temperature, 8, 20))
    low = _mix(desert, STEPPE, _smooth(veg, 0, 0.35))
    low = _mix(low, grass, _smooth(veg, 0.35, 0.7))
    trees = _mix(_fill(shape, FOREST_BOREAL), FOREST_TEMPERATE, _smooth(temperature, 3, 9))
    trees = _mix(trees, FOREST_TROPICAL, _smooth(temperature, 17, 23))
    colour = _mix(low, trees, forest)
    colour = _mix(colour, TUNDRA, 1 - _smooth(warm, 4, 11))
    rocky = np.clip(_smooth(slope, 0.08, 0.3) * 0.75 + _smooth(z, 3000, 4500) * 0.25, 0, 0.8)
    colour = _mix(colour, ROCK, rocky)
    colour = _mix(colour, BARE_DRYLAND, (1 - veg) * _smooth(slope, 0.015, 0.09) * 0.6)
    # The snowline wanders with local climate and lies lower on shaded slopes;
    # steep faces shed snow and stay bare.
    wander = eroded_fbm(points, zeros, 47, 4, radius_m / 40e3, 0.55, 0.0).reshape(shape)
    shade = np.clip(1 - light, -0.5, 0.8)
    cold = -warm + 1.4 * wander + 2.5 * shade
    snow = _smooth(cold, -0.8, 1.0) * (1 - 0.7 * _smooth(slope, 0.3, 0.7))
    colour = _mix(colour, SNOW, snow)
    texture = eroded_fbm(points, zeros, 23, 4, radius_m / 25e3, 0.6, 0.0).reshape(shape)
    colour *= (1 + 0.045 * texture + 0.05 * patch)[..., None]
    return colour * (0.30 + 0.70 * np.clip(light, 0, 1.5))[..., None]


def _fill(shape: tuple[int, ...], colour: RGB) -> F64:
    return np.broadcast_to(np.asarray(colour, dtype=np.float64), (*shape, 3)).copy()


def natural_colour(
    result: PlanetResult, raster: FrameRaster, rivers: F64, fields: DisplayFields
) -> F64:
    climate = result.climate
    assert climate is not None
    mesh = result.mesh
    lapse = result.settings.climate.lapse_c_per_km
    lift = (fields.elevation_m - fields.base_m) / 1000
    pixel = PixelClimate(
        raster.interpolate(mesh, climate.temperature_c) - lapse * lift,
        raster.interpolate(mesh, climate.warm_c) - lapse * lift,
        raster.interpolate(mesh, climate.precipitation_mm),
        raster.interpolate(mesh, climate.pet_mm),
    )
    return land_colour(
        raster.queries,
        mesh.radius_m,
        pixel,
        fields.elevation_m,
        fields.slope,
        fields.light,
        0.6 * rivers,
        fields.position,
    )


def sea_depth_colour(depth_m: F64, light: F64) -> F64:
    sea = ramp(np.maximum(depth_m, 0), SEA_STOPS)
    return sea * (0.88 + 0.12 * np.clip(light, 0, 2) - 0.12)[..., None]


def sea_colour(fields: DisplayFields) -> F64:
    return sea_depth_colour(-fields.elevation_m, fields.light)


def relief_colour(fields: DisplayFields) -> F64:
    colour = ramp(fields.elevation_m, HYPSOMETRIC)
    return colour * (0.30 + 0.70 * np.clip(fields.light, 0, 1.5))[..., None]


def paint_water(rgb: F64, result: PlanetResult, lakes_px: NDArray[np.int64]) -> F64:
    """Lakes in water colour; only closed lakes in hot, arid basins read as dry salt pans."""
    out = rgb.copy()
    lakes = result.lakes
    if not len(lakes.level_m):
        return out
    salt = lakes.endorheic.copy()
    climate = result.climate
    if climate is not None:
        for lake in np.flatnonzero(salt):
            nodes = lakes.lake == lake
            aridity = np.mean(
                climate.precipitation_mm[nodes] / np.maximum(climate.pet_mm[nodes], 1)
            )
            salt[lake] = bool(np.mean(climate.temperature_c[nodes]) > 12.0 and aridity < 0.35)
    on_lake = lakes_px >= 0
    pan = salt[np.maximum(lakes_px, 0)] & on_lake
    # Soft shores; a playa grades from a bright centre into the surrounding ground.
    water = gaussian_filter((on_lake & ~pan).astype(np.float64), 0.7)[..., None]
    playa = np.clip(gaussian_filter(pan.astype(np.float64), 2.0) * 1.4 - 0.2, 0, 0.85)[..., None]
    out = out * (1 - water) + np.asarray(LAKE, dtype=np.float64) * water
    return out * (1 - playa) + np.asarray(SALT_FLAT, dtype=np.float64) * playa


def river_layer(
    result: PlanetResult, raster: FrameRaster, threshold_m3_s: float, supersample: int = 2
) -> F64:
    """Anti-aliased river coverage (0..1) on the world-frame raster."""
    mesh, flow = result.mesh, result.flow
    rows, columns = raster.shape
    frame = raster.frame
    discharge = result.lakes.discharge_m3_s
    stop = ~result.land | (result.lakes.lake >= 0)
    major = (~stop) & ~ice_covered(result) & (flow.receiver >= 0) & (discharge >= threshold_m3_s)
    lon = np.degrees(np.arctan2(mesh.xyz[:, 1], mesh.xyz[:, 0]))
    lat = np.degrees(np.arcsin(np.clip(mesh.xyz[:, 2], -1, 1)))
    x = ((lon - frame.central_meridian_deg + 180) % 360) / 360 * columns
    y = (90 - lat) / 180 * rows
    return river_coverage(
        x, y, flow.receiver, discharge, major, stop, (rows, columns), columns / 4800, supersample
    )


def river_coverage(
    x: F64,
    y: F64,
    receiver: NDArray[np.int64],
    discharge: F64,
    major: B,
    stop: B,
    shape: tuple[int, int],
    width_scale: float,
    supersample: int = 2,
) -> F64:
    """Tapered, Chaikin-smoothed, anti-aliased river lines for nodes at pixel (x, y)."""
    rows, columns = shape
    if not major.any():
        return np.zeros(shape)
    donors = np.zeros(len(receiver), dtype=np.int64)
    np.add.at(donors, receiver[major], 1)
    heads = np.flatnonzero(major & (donors == 0))
    peak = float(discharge[major].max())
    mask = Image.new("L", (columns * supersample, rows * supersample), 0)
    draw = ImageDraw.Draw(mask)
    visited = np.zeros(len(receiver), dtype=bool)
    for head in heads[np.argsort(-discharge[heads])].tolist():
        chain = [head]
        node = head
        while True:
            visited[node] = True
            nxt = int(receiver[node])
            if nxt < 0:
                break
            chain.append(nxt)
            if stop[nxt] or visited[nxt] or not major[nxt]:
                break
            node = nxt
        if len(chain) < 2:
            continue
        path = np.stack((x[chain], y[chain]), axis=1)
        if np.any(np.abs(np.diff(path[:, 0])) > columns / 2):
            continue
        for _ in range(2):
            a, b = path[:-1], path[1:]
            cut = np.empty((2 * len(a), 2))
            cut[0::2] = 0.75 * a + 0.25 * b
            cut[1::2] = 0.25 * a + 0.75 * b
            path = np.vstack((path[:1], cut, path[-1:]))
        flow_along = np.interp(
            np.linspace(0, 1, len(path)), np.linspace(0, 1, len(chain)), discharge[chain]
        )
        width = (0.4 + 1.6 * (flow_along / peak) ** 0.5) * width_scale * supersample
        for k in range(len(path) - 1):
            draw.line(
                (tuple(path[k] * supersample), tuple(path[k + 1] * supersample)),
                fill=255,
                width=max(1, round(float(width[k]))),
            )
    mask = mask.resize((columns, rows), Image.Resampling.LANCZOS)
    return np.asarray(mask, dtype=np.float64) / 255.0


def compose(
    land_rgb: F64,
    sea_rgb: F64,
    land_px: B,
    rivers: F64,
    result: PlanetResult,
    lakes_px: NDArray[np.int64],
) -> Image.Image:
    rgb = np.where(land_px[..., None], land_rgb, sea_rgb)
    rgb = paint_water(rgb, result, lakes_px)
    alpha = (0.9 * rivers)[..., None]
    rgb = rgb * (1 - alpha) + np.asarray(RIVER, dtype=np.float64) * alpha
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def preview_images(
    result: PlanetResult, rasters: PlanetRasters, threshold_m3_s: float
) -> dict[str, Image.Image]:
    """Natural-colour atlas, shaded relief and climate previews (derived display)."""
    land_px = rasters.land_px
    base_land = np.where(land_px, rasters.elevation_m, 0.0)
    base_sea = np.where(land_px, 0.0, rasters.elevation_m)
    fields = display_fields(result, rasters.raster, land_px, base_land, base_sea)
    rivers = river_layer(result, rasters.raster, threshold_m3_s)
    sea = sea_colour(fields)
    images: dict[str, Image.Image] = {}
    if result.climate is not None:
        images["Planet atlas"] = compose(
            natural_colour(result, rasters.raster, rivers, fields),
            sea,
            land_px,
            rivers,
            result,
            rasters.lakes_px,
        )
    images["Planet relief"] = compose(
        relief_colour(fields), sea, land_px, rivers, result, rasters.lakes_px
    )
    images |= climate_images(result, rasters)
    return images


def render_previews(result: PlanetResult, width: int, river_km2: float) -> dict[str, Image.Image]:
    return preview_images(
        result, planet_rasters(result, width), river_threshold_m3_s(result, river_km2)
    )
