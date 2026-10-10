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

from dmtools.terrain.adapters.map_thematic import thematic_images
from dmtools.terrain.adapters.map_topographic import topographic_image
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
from dmtools.terrain.pipeline.planet_volcanism import GUYOT_DEPTH_M, SEAMOUNT, edifice_height
from dmtools.terrain.pipeline.planet_wonders import crater_relief

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
ERG_HOT: RGB = (226, 178, 114)
ERG_COLD: RGB = (214, 190, 146)
REG: RGB = (156, 132, 106)
STEPPE: RGB = (160, 152, 104)
GRASS_WARM: RGB = (128, 140, 80)
GRASS_COOL: RGB = (118, 136, 88)
FOREST_TROPICAL: RGB = (46, 82, 42)
FOREST_TEMPERATE: RGB = (68, 98, 56)
FOREST_BOREAL: RGB = (58, 78, 60)
TUNDRA: RGB = (150, 146, 124)
# Local spread of the effective summer warmth that places treeline and tundra (C).
ECOTONE_C = 3.0
WETLAND: RGB = (92, 98, 70)
ROCK: RGB = (132, 122, 112)
BARE_DRYLAND: RGB = (124, 102, 80)
SNOW: RGB = (242, 244, 247)
VOLCANIC_ROCK: RGB = (82, 74, 70)
BASALT_SOIL: RGB = (96, 86, 72)
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
    base_m: F64  # surface the climate fields refer to (no detail, no volcanoes)
    slope: F64  # display slope (m/m)
    light: F64  # multi-directional hillshade, 1.0 on flat ground
    position: F64  # -1 (valley floor) .. +1 (ridge crest), multi-scale openness
    volcanic: F64  # 0..1 cover of young volcanic edifices


def display_fields(
    result: PlanetResult,
    raster: FrameRaster,
    land_px: B,
    base_land: F64,
    base_sea: F64,
    islands_px: B | None = None,
) -> DisplayFields:
    mesh = result.mesh
    radius = mesh.radius_m
    shape = raster.shape
    points = raster.queries
    coast = raster.interpolate(
        mesh, np.maximum(np.where(np.isfinite(result.coast_m), result.coast_m, 0), 0)
    )
    discharge = raster.interpolate(mesh, np.log1p(np.maximum(result.lakes.discharge_m3_s, 0.0)))
    # The mesh carries volcanoes widened to its resolution; redraw them sharply.
    sharp = edifice_height(points, radius, result.volcanoes).reshape(shape)
    coarse = raster.interpolate(mesh, result.volcanic_m)
    islands = np.zeros(shape, dtype=bool) if islands_px is None else islands_px
    # Island pixels already carry their sharp volcano surface.
    base_land = np.where(land_px & ~islands, base_land - coarse + sharp, base_land)
    # Craters too are redrawn at pixel scale.
    cut = crater_relief(points, radius, result.craters).reshape(shape)
    base_land = np.where(
        land_px & ~islands, base_land - raster.interpolate(mesh, result.crater_m) + cut, base_land
    )
    sea_floor = base_sea - coarse
    base_sea = np.where(
        land_px, base_sea, np.minimum(sea_floor + sharp, np.maximum(sea_floor, GUYOT_DEPTH_M))
    )
    # Fresh lava and ash show near summits; lower flanks weather like their surroundings.
    volcanic = np.where(land_px, _smooth(sharp, 300.0, 2500.0), 0.0)
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
        * (1 - 0.6 * volcanic)  # young cones have smooth, little-dissected flanks
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
    # The surface the climate fields refer to: mesh land without its volcanoes
    # (they rise after the climate is simulated, so whole edifices are
    # lapse-corrected), or a volcanic island's coarse mesh height (its
    # temperatures are lapse-corrected to that height).
    base = np.where(
        islands,
        raster.interpolate(mesh, np.where(result.islands, result.elevation_m, 0.0)),
        base_land - sharp - cut,
    )
    return DisplayFields(z, base, slope, light, position, volcanic)


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
    # Warm-half-year rate (mm/yr): vegetation follows growing-season water, so
    # summer-dry Mediterranean land browns and summer-wet monsoon land greens.
    growing_mm: F64 | None = None


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
    volcanic: F64 | None = None,
    slope_scale: float = 1.0,
    basalt: F64 | None = None,
) -> F64:
    """Continuous natural land colour (desert to forest, tundra, rock, snow), shaded.

    ``wet`` (0..1, blurred river coverage) greens river corridors in drylands.
    ``position`` (-1 valley floor .. +1 ridge crest) ties the vegetation mosaic
    to the terrain: valleys gather water and soil, ridges and steep slopes shed
    them. ``fine_wavelength_m`` sets the finest mosaic scale (smaller when zoomed).
    ``slope_scale`` raises the slope thresholds for bare rock: slopes measured on
    fine pixels are steeper than the same terrain averaged over coarse ones.
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
    water = (
        climate.precipitation_mm
        if climate.growing_mm is None
        else 0.45 * climate.precipitation_mm + 0.55 * climate.growing_mm
    )
    aridity = (
        water
        / np.maximum(climate.pet_mm, 1.0)
        * np.exp(0.45 * patch + 0.3 * fine + terrain)
    )
    if wet is not None:
        # Only drylands show river corridors; humid land is green either way.
        aridity = aridity * (1 + 15 * wet * (1 - _smooth(aridity, 0.25, 0.9)))
    veg = _smooth(aridity, 0.04, 0.8)
    # The polar treeline is no line of latitude: forest-tundra is a mosaic
    # 100-300 km wide, forest reaches poleward in sheltered valleys and along
    # rivers (Mackenzie, Lena) and gives way early on exposed uplands.
    sheltered = 0.0 if position is None else -1.2 * position
    riparian = 0.0 if wet is None else 4.0 * wet
    summer = warm + ECOTONE_C * (0.7 * patch + 0.5 * fine) + sheltered + riparian
    forest = _smooth(aridity, 0.6, 1.25) * _smooth(summer, 9, 14)
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
    erg = erg_cover(points, radius_m, climate, slope, position, slope_scale)
    # Outside the sand seas, hyper-arid ground is stony plain (reg, hamada):
    # gravel and desert varnish darker than sand.
    hyperarid = 1 - _smooth(climate.precipitation_mm / np.maximum(climate.pet_mm, 1.0), 0.04, 0.15)
    colour = _mix(colour, REG, 0.35 * hyperarid * (1 - erg))
    sand = _mix(_fill(shape, ERG_COLD), ERG_HOT, _smooth(temperature, 6, 18))
    colour = _mix(colour, sand, 0.9 * erg)
    # Treeline near the 10 C warmest-month isotherm (Koppen ET).
    colour = _mix(colour, TUNDRA, 1 - _smooth(summer, 7.5, 10.5))
    # Flat, cool, humid lowlands drain badly into bogs and fens (West Siberian
    # Plain, Hudson Bay Lowlands): dark mottled olive and brown peatland.
    flat = 1 - _smooth(slope, 0.003 * slope_scale, 0.015 * slope_scale)
    low_ground = 1.0 if position is None else _smooth(-position, -0.3, 0.4)
    boggy = _smooth(aridity, 0.9, 1.6) * (1 - _smooth(summer, 14, 20)) * _smooth(summer, 5, 8)
    mottle = _smooth(0.6 * patch + fine, -0.1, 0.4)
    colour = _mix(colour, WETLAND, 0.7 * flat * low_ground * boggy * mottle)
    steep = _smooth(slope, 0.08 * slope_scale, 0.3 * slope_scale)
    rocky = np.clip(steep * 0.75 + _smooth(z, 3000, 4500) * 0.25, 0, 0.8)
    colour = _mix(colour, ROCK, rocky)
    if volcanic is not None:
        # Young lava and ash are dark; vegetation soon covers them in wet climates.
        colour = _mix(colour, VOLCANIC_ROCK, volcanic * (0.45 - 0.35 * forest))
    if basalt is not None:
        # Weathered flood basalt gives dark clay soils (the Deccan's black
        # cotton soil); forest hides them.
        colour = _mix(colour, BASALT_SOIL, basalt * (0.45 - 0.3 * forest))
    hills = _smooth(slope, 0.015 * slope_scale, 0.09 * slope_scale)
    colour = _mix(colour, BARE_DRYLAND, (1 - veg) * hills * 0.6)
    # Perennial snow and glaciers need snowfall as well as cold: the summer
    # temperature at the equilibrium line rises with precipitation (Ohmura et al.
    # 1992), so wet coastal ranges carry ice low and dry plateaus stay bare. The
    # snowline also wanders with local climate, lies lower on shaded slopes and
    # in hollows, and steep faces shed snow.
    wander = eroded_fbm(points, zeros, 47, 4, radius_m / 40e3, 0.55, 0.0).reshape(shape)
    shade = np.clip(1 - light, -0.5, 0.8)
    hollow = 0.0 if position is None else -0.8 * position
    cold = equilibrium_line_c(climate.precipitation_mm) - warm + 1.4 * wander + 2.5 * shade + hollow
    # Steep faces and wind-scoured crests show rock between snowfields.
    exposed = 0.0 if position is None else 0.5 * _smooth(position, 0.3, 0.8)
    shed = np.clip(0.85 * _smooth(slope, 0.3, 0.7) + exposed, 0.0, 0.9)
    snow = _smooth(cold, -0.8, 1.0) * (1 - shed)
    colour = _mix(colour, SNOW, snow)
    texture = eroded_fbm(points, zeros, 23, 4, radius_m / 25e3, 0.6, 0.0).reshape(shape)
    colour *= (1 + 0.045 * texture + 0.05 * patch)[..., None]
    return colour * (0.30 + 0.70 * np.clip(light, 0, 1.5))[..., None]


def erg_cover(
    points: F64,
    radius_m: float,
    climate: PixelClimate,
    slope: F64,
    position: F64 | None,
    slope_scale: float = 1.0,
) -> F64:
    """0..1 cover of sand seas (ergs).

    Wind-blown sand gathers in the flattest, driest low ground of deserts: the
    Rub' al Khali, the Saharan ergs, the Taklamakan. Elsewhere deserts are stony
    plains (regs) and rock. About a fifth to a third of hot desert is erg.
    """
    shape = slope.shape
    arid = 1 - _smooth(climate.precipitation_mm / np.maximum(climate.pet_mm, 1.0), 0.05, 0.14)
    flat = 1 - _smooth(slope, 0.004 * slope_scale, 0.02 * slope_scale)
    low = 1.0 if position is None else _smooth(-position, -0.4, 0.3)
    zeros = np.zeros(len(points))
    patches = eroded_fbm(points, zeros, 61, 4, radius_m / 500e3, 0.5, 0.0).reshape(shape)
    return arid * flat * low * _smooth(patches, -0.05, 0.1)


def equilibrium_line_c(precipitation_mm: F64) -> F64:
    """Summer air temperature (deg C) at a glacier's equilibrium line.

    Inverts Ohmura et al. (1992), P = 645 + 296 T + 9 T^2 (P in mm/yr, T the
    summer mean at the ELA): about -2 C for 100 mm, +1 C for 1,000 mm and +4 C
    for 2,000 mm of precipitation.
    """
    p = np.clip(precipitation_mm, 0.0, 6000.0)
    return (-296.0 + np.sqrt(np.maximum(296.0**2 - 36.0 * (645.0 - p), 0.0))) / 18.0


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
        raster.interpolate(mesh, climate.precip_warm_mm),
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
        volcanic=fields.volcanic,
        basalt=(
            None
            if result.forcing.flood_basalt is None
            else raster.interpolate(mesh, result.forcing.flood_basalt)
        ),
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


MIN_MEANDER_PX = 4.0


def meander(path: F64, wavelength_px: F64, seed: int, anchors: F64 | None = None) -> F64:
    """Wind a river path into meanders of the given (per-point) wavelength.

    Meanders follow the sine-generated curve of Langbein and Leopold (1966): the
    channel's direction swings as theta = omega sin(2 pi s / lambda), with the
    swing omega varying from bend to bend (0.6-1.6 rad), which gives the rounded,
    uneven loops of alluvial rivers. A slower wander of the whole meander belt
    (about six wavelengths) is added. The lateral displacement tapers to zero at
    both ends and at ``anchors`` (fractions of the path length, such as
    tributary junctions) so junctions and mouths stay connected.
    """
    step = np.hypot(*np.diff(path, axis=0).T)
    along = np.concatenate(([0.0], np.cumsum(step)))
    total = float(along[-1])
    if total < 2.0:
        return path
    s = np.linspace(0.0, total, max(2, int(total)))
    ds = s[1] - s[0] if len(s) > 1 else 1.0
    resampled = np.stack((np.interp(s, along, path[:, 0]), np.interp(s, along, path[:, 1])), 1)
    wave = np.maximum(
        np.interp(s / total, np.linspace(0, 1, len(wavelength_px)), wavelength_px), 1e-6
    )
    rng = np.random.default_rng(seed)
    knots = max(4, int(total / max(float(wave.mean()), 1.0)) + 2)
    swing = np.interp(s, np.linspace(0, total, knots), rng.uniform(0.6, 1.6, knots))
    stretch = 1 + 0.3 * np.interp(s, np.linspace(0, total, knots), rng.uniform(-1, 1, knots))
    phase = np.cumsum(2 * np.pi * ds / (wave * stretch)) + rng.uniform(0, 2 * np.pi)
    lateral = np.cumsum(np.sin(swing * np.sin(phase))) * ds
    belt = np.cumsum(2 * np.pi * ds / (6 * wave)) + rng.uniform(0, 2 * np.pi)
    lateral = lateral + 0.6 * wave * np.sin(belt)
    # Remove the drift so the river keeps its course, then taper the ends.
    lateral -= np.interp(s, [0.0, total], [lateral[0], lateral[-1]])
    pins = np.concatenate(([0.0, total], [] if anchors is None else np.asarray(anchors) * total))
    nearest = np.min(np.abs(s[:, None] - pins[None, :]), axis=1)
    taper = np.clip(nearest / np.maximum(wave, 1.0), 0, 1)
    tangent = np.gradient(resampled, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1), 1e-9)[:, None]
    normal = np.stack((-tangent[:, 1], tangent[:, 0]), 1)
    return resampled + normal * (lateral * taper)[:, None]


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
    meander_px: F64 | None = None,
) -> F64:
    """Tapered, Chaikin-smoothed, anti-aliased river lines for nodes at pixel (x, y).

    ``meander_px`` (per node, pixels; 0 for straight reaches) adds meanders of
    that wavelength, as alluvial rivers wind on gentle ground.
    """
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
        if meander_px is not None and float(meander_px[chain].max()) > MIN_MEANDER_PX:
            # Tributaries join at nodes with several major donors: pin the bends there.
            nodes_xy = np.stack((x[chain], y[chain]), axis=1)
            reach = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(nodes_xy, axis=0).T))))
            joins = np.flatnonzero(donors[chain] > 1)
            path = meander(path, np.interp(
                np.linspace(0, 1, len(path)), np.linspace(0, 1, len(chain)), meander_px[chain]
            ), head, reach[joins] / max(float(reach[-1]), 1e-9))
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
    fields = display_fields(
        result, rasters.raster, land_px, base_land, base_sea, rasters.islands_px
    )
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
    if "Planet atlas" in images and len(result.volcanoes):
        images["Planet volcanoes"] = volcano_markers(images["Planet atlas"], result, rasters.raster)
    images |= climate_images(result, rasters)
    rows, columns = land_px.shape
    radius = result.mesh.radius_m
    covered = rasters.raster.interpolate(result.mesh, ice_covered(result).astype(np.float64)) > 0.5
    images["Planet topographic"] = topographic_image(
        fields.elevation_m, land_px, rasters.lakes_px >= 0, rivers, fields.light,
        np.pi * radius / rows,
        2 * np.pi * radius / columns * np.maximum(np.cos(rasters.raster.latitude), 0.05),
        covered,
    )
    images |= thematic_images(result, rasters, fields.light, rivers)
    return images


def volcano_markers(atlas: Image.Image, result: PlanetResult, raster: FrameRaster) -> Image.Image:
    """The atlas with land volcanoes marked: red for active, dark for extinct."""
    marked = atlas.copy()
    draw = ImageDraw.Draw(marked)
    rows, columns = raster.shape
    frame = raster.frame
    v = result.volcanoes
    size = max(3, round(columns / 960))
    for k in np.flatnonzero(v.kind != SEAMOUNT):
        x, y, z = (float(c) for c in v.xyz[k])
        lon = np.degrees(np.arctan2(y, x))
        lat = np.degrees(np.arcsin(np.clip(z, -1, 1)))
        px = ((lon - frame.central_meridian_deg + 180) % 360) / 360 * columns
        py = (90 - lat) / 180 * rows
        colour = (235, 50, 20) if v.active[k] else (45, 35, 35)
        draw.polygon(
            [(px, py - size), (px - size, py + size), (px + size, py + size)],
            outline=colour, width=max(1, size // 3),
        )
    return marked


def render_previews(result: PlanetResult, width: int, river_km2: float) -> dict[str, Image.Image]:
    return preview_images(
        result, planet_rasters(result, width), river_threshold_m3_s(result, river_km2)
    )
