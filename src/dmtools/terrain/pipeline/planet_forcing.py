# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""World inputs on the sphere mesh and their conversion to erosion forcing.

* Land is the exact vector point-in-polygon of prepared world land at each node.
* Coast distance is graph distance from land/water edge midpoints.
* Without geology a procedural forcing places ridged orogenic belts, active
  margins and weak inland craton uplift.
* With a geology recipe each resolved region gets a setting erodibility and a
  soft elevation target, from its landform or a setting default. Calibration
  later rescales its uplift towards that target.
"""

from dataclasses import dataclass
from math import exp

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import Polygon
from shapely.ops import unary_union

from dmtools.terrain.domain.models import LandformSettings
from dmtools.terrain.domain.world import WorldFrame
from dmtools.terrain.domain.world_geology import GeologyProfile, WorldGeologyRecipe
from dmtools.terrain.pipeline.planet_climate import surface_gradient, tangent_frame
from dmtools.terrain.pipeline.planet_kernels import multi_source_distance
from dmtools.terrain.pipeline.planet_mesh import SphereMesh
from dmtools.terrain.pipeline.planet_noise import fbm3
from dmtools.terrain.pipeline.world import WorldMap
from dmtools.terrain.pipeline.world_geology import resolve_geology

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

# Setting -> (landform character, base elevation m, relief m, transition km) when
# a profile has no explicit landform. Unspecified settings stay procedural.
SETTING_INTENT: dict[str, tuple[str, float, float, float]] = {
    "active-belt": ("mountains", 900.0, 3200.0, 120.0),
    "volcanic": ("mountains", 700.0, 1800.0, 80.0),
    "stable-interior": ("plain", 380.0, 180.0, 150.0),
    "rift": ("hills", 250.0, 500.0, 60.0),
    "sedimentary-basin": ("plain", 120.0, 60.0, 120.0),
}
SETTING_ERODIBILITY = {
    "active-belt": 1.0,
    "volcanic": 0.8,
    "stable-interior": 0.5,
    "rift": 1.4,
    "sedimentary-basin": 2.5,
    "unspecified": 1.0,
}
OROGEN_DECAY_MYR = 120.0
OLD_CRUST_MA = 1000.0
OLD_CRUST_ERODIBILITY = 0.7
PLATEAU_PULSE_FRACTION = 0.2
UPLIFT_TEXTURE = 0.6
# Procedural uplift rates (m/yr) where no geology recipe applies. Active belts
# reach steady state; plateaus, swells and shields erode so slowly (see
# SHIELD_ERODIBILITY) that their height is mostly accumulated uplift.
BELT_UPLIFT = 2.2e-3
PLATEAU_UPLIFT = 3e-4
MINOR_UPLIFT = 1e-3
HILL_UPLIFT = 8e-5
MARGIN_UPLIFT = 1e-3
CRATON_UPLIFT = 5e-5
SWELL_UPLIFT = 8e-5
# Erodibility outside active belts. Shields and plateaus erode so slowly that
# uplift outpaces them: they stay smooth and high while rivers cut in from their
# edges (the African plateau, the Colorado Plateau), instead of dissecting into
# badlands at continental scale.
SHIELD_ERODIBILITY = 0.25
FOLD_WAVELENGTH_M = 45e3
REFERENCE_RELIEF_M_PER_MM_YR = 5000.0


def node_source_xy(frame: WorldFrame, mesh: SphereMesh) -> tuple[F64, F64]:
    """Node positions in the world SVG frame (respecting the central meridian)."""
    return source_xy(frame, mesh.xyz)


def source_xy(frame: WorldFrame, xyz: F64) -> tuple[F64, F64]:
    """Unit vectors to world SVG frame coordinates (respecting the central meridian)."""
    lon = np.rad2deg(np.arctan2(xyz[:, 1], xyz[:, 0]))
    lat = np.rad2deg(np.arcsin(np.clip(xyz[:, 2], -1, 1)))
    offset = (lon - frame.central_meridian_deg + 180) % 360
    return (
        frame.bounds[0] + offset / 360 * frame.width,
        frame.bounds[1] + (90 - lat) / 180 * frame.height,
    )


def land_on_mesh(world: WorldMap, mesh: SphereMesh) -> B:
    land = unary_union(
        [Polygon(c.exterior, c.holes) for view in world.land for c in view.components]
    )
    shapely.prepare(land)
    x, y = node_source_xy(world.project.frame, mesh)
    return np.asarray(shapely.contains_xy(land, x, y), dtype=bool)


def coast_distance(mesh: SphereMesh, land: B) -> F64:
    """Graph distance (m) from every node to the nearest land/water edge midpoint."""
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    crossing = land[src] != land[mesh.nbr]
    if not np.any(crossing):
        return np.full(mesh.size, np.inf)
    return multi_source_distance(
        src[crossing], mesh.length_m[crossing] / 2, mesh.ptr, mesh.nbr, mesh.length_m
    )


def _smoothstep(x: F64, a: float | F64, b: float | F64) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def cratonic_profile(coast_m: F64) -> F64:
    """Relative stable-continent uplift: marginal swell and a broad interior sag.

    Passive margins flex up into an escarpment 30-200 km inland (Wang and Willett
    2021) while old interiors subside into broad basins. Interior drainage
    therefore gathers into a few trunk rivers that breach the rim, instead of
    radiating from a central dome.
    """
    swell = np.exp(-(((coast_m - 150e3) / 150e3) ** 2))
    sag = _smoothstep(coast_m, 500e3, 1500e3)
    return np.maximum(0.15, 0.55 + 0.9 * swell - 0.35 * sag)


def signed_crest_distance(mesh: SphereMesh, field: F64) -> F64:
    """Approximate signed distance (m) to the zero line of a smooth field: f / |grad f|."""
    east, north = tangent_frame(mesh.xyz)
    gradient_east, gradient_north = surface_gradient(mesh, field, east, north)
    return field / np.maximum(np.hypot(gradient_east, gradient_north), 1e-12)


def crest_distance(mesh: SphereMesh, field: F64) -> F64:
    """Approximate distance (m) to the zero line of a smooth field: |f| / |grad f|."""
    return np.abs(signed_crest_distance(mesh, field))


def ridge_profile(distance_m: F64, half_width_m: F64) -> F64:
    """Uplift across a range: a broad axial zone falling to a defined front."""
    return 1 - _smoothstep(distance_m, 0.25 * half_width_m, half_width_m)


# Composite orogen across strike, in units of the main range's half-width:
# (offset, half-width, relative uplift, segment-gate seed offset). Real belts are
# several parallel ranges (Himalaya: Siwalik foothills, Lesser and Greater
# Himalaya, Tethyan ranges; Andes: Cordilleras Occidental and Oriental) with
# longitudinal valleys between them that carry rivers along strike.
OROGEN_RANGES = (
    (0.0, 1.0, 1.0, 0),  # main axis
    (1.35, 0.4, 0.55, 1),  # frontal range
    (2.1, 0.3, 0.25, 2),  # foothills
    (-1.7, 0.55, 0.7, 3),  # hinterland range
)


def orogen_profile(across_m: F64, half_width_m: F64, p: F64, seed: int) -> F64:
    """Parallel, en-echelon ranges of one orogen from the signed across-strike distance."""
    uplift = np.zeros_like(across_m)
    for offset, half, weight, gate_seed in OROGEN_RANGES:
        if gate_seed:
            # Subsidiary ranges wander, change height and come and go along strike
            # (en echelon segments) instead of running parallel like rails.
            wander = 1 + 0.5 * fbm3(p, seed + 1200 + gate_seed, 3, 9.0)
            strength = 0.5 + 0.5 * fbm3(p, seed + 1300 + gate_seed, 3, 6.0)
            gate = _smoothstep(fbm3(p, seed + 1100 + gate_seed, 3, 10.0), -0.2, 0.2)
        else:
            wander, strength, gate = np.ones_like(across_m), 1.0, 1.0
        centre = offset * half_width_m * wander
        profile = ridge_profile(np.abs(across_m - centre), half * half_width_m)
        uplift = np.maximum(uplift, weight * strength * gate * profile)
    return uplift


def strike_lithology(across_m: F64, half_width_m: F64, orogen: F64, phase: F64) -> F64:
    """Erodibility multiplier of rock bands parallel to an orogen's strike.

    A hard crystalline core with alternating weak and strong bands outward:
    rivers find the weak bands and run along strike before breaking through,
    and divides pin on the hard rock (Bernard et al. 2021).
    """
    core = 1 - 0.45 * (1 - _smoothstep(np.abs(across_m), 0.3 * half_width_m, 0.7 * half_width_m))
    bands = 1 + 0.3 * np.cos(2 * np.pi * across_m / (0.9 * half_width_m) + phase)
    return 1 + orogen * (core * bands - 1)


@dataclass(frozen=True, slots=True)
class ProceduralForcing:
    uplift: F64  # m/yr
    texture: F64  # dimensionless rock-erodibility variation (median ~1)
    uplift_texture: F64  # dimensionless uplift variation within regions (median ~1)


def procedural_forcing(mesh: SphereMesh, land: B, coast_m: F64, seed: int) -> ProceduralForcing:
    """Ridged-noise orogens, noise-gated active margins and weak inland cratons.

    Earth's continents carry structure at every scale: a few great orogens
    (1,000s of km), many minor ranges and old fold belts (100s of km) and hill
    country between them. Forcing with only continental-scale structure erodes
    into a handful of huge, uniform plains and plateaus.
    """
    p = mesh.xyz
    # Belts follow the zero lines of smooth noise, with explicit half-widths from
    # Earth's ranges: great orogens 60-175 km (Himalaya 150-350 km wide, Andes
    # ~200 km, Alps ~200 km), minor ranges and fold belts 20-60 km, broken into
    # segments 1,000-3,000 km long instead of one continent-spanning network.
    warp = np.stack([fbm3(p, seed + 300 + k, 3, 1.3) for k in range(3)], axis=1)
    major = fbm3(p + 0.35 * warp, seed + 101, 4, 1.4)
    major_half = 50e3 + 80e3 * _smoothstep(fbm3(p, seed + 141, 3, 3.0), -0.4, 0.4)
    # Signed distance across strike, positive towards the foreland side. Which
    # side faces the foreland changes along strike, as it does between orogens.
    across = signed_crest_distance(mesh, major) * np.sign(fbm3(p, seed + 191, 2, 1.0) + 1e-9)
    segments = _smoothstep(fbm3(p, seed + 151, 3, 3.5), -0.15, 0.25)
    inland_fade = _smoothstep(coast_m, 0.0, 150e3)
    belts = orogen_profile(across, major_half, p, seed) * segments * inland_fade
    # A few great orogens carry a high plateau on their hinterland side (Tibet
    # 1,000 km wide, Altiplano 350-400 km).
    plateau = (
        ridge_profile(np.abs(across + 2.2 * major_half), 2.6 * major_half)
        * segments
        * _smoothstep(fbm3(p, seed + 171, 3, 2.0), 0.05, 0.35)
        * _smoothstep(coast_m, 100e3, 400e3)
    )
    # Broad swells and basins (dynamic topography, old uplifted shields) lift
    # whole regions by hundreds of metres over 1,000-3,000 km.
    swell = _smoothstep(fbm3(p, seed + 181, 3, 2.0), -0.05, 0.45)
    fine_warp = np.stack([fbm3(p, seed + 310 + k, 3, 4.0) for k in range(3)], axis=1)
    minor_field = fbm3(p + 0.12 * fine_warp, seed + 111, 4, 4.5)
    minor_half = 20e3 + 40e3 * _smoothstep(fbm3(p, seed + 161, 3, 8.0), -0.4, 0.4)
    minor_across = signed_crest_distance(mesh, minor_field)
    # Some minor belts are fold-and-thrust belts: parallel ridges ~45 km apart
    # (Valley and Ridge, Zagros at a coarser scale) rather than a single ridge.
    folds = (0.5 + 0.5 * np.cos(2 * np.pi * minor_across / FOLD_WAVELENGTH_M)) ** 2
    folded = _smoothstep(fbm3(p, seed + 262, 3, 3.0), 0.0, 0.3)
    minor = (
        ridge_profile(np.abs(minor_across), 1.6 * minor_half * (1 + folded))
        * (1 - folded + folded * folds)
        * _smoothstep(fbm3(p, seed + 212, 3, 2.5), -0.1, 0.3)
        * _smoothstep(coast_m, 0.0, 80e3)
    )
    hill_ridged = 1 - np.abs(fbm3(p + 0.05 * fine_warp, seed + 121, 3, 12.0))
    hills = _smoothstep(hill_ridged, 0.65, 0.95) * _smoothstep(
        fbm3(p, seed + 222, 3, 3.5), -0.1, 0.4
    )
    gate = _smoothstep(fbm3(p, seed + 202, 3, 1.1), 0.05, 0.35)
    # Active-margin ranges are 100-300 km wide (Andes, Coast Mountains) and vary
    # along strike; a uniform coastal band erodes into a comb of identical valleys.
    strike = _smoothstep(fbm3(p, seed + 232, 3, 6.0), -0.4, 0.4)
    margins = (
        gate
        * (0.35 + 0.65 * strike)
        * _smoothstep(coast_m, 20e3, 60e3)
        * (1 - _smoothstep(coast_m, 120e3, 250e3))
    )
    # Uniform uplift erodes into a smooth dome with radial drainage. Inherited
    # structure (warps, faults, lithology) breaks that symmetry from 100 to 2000 km.
    uplift_texture = np.exp(UPLIFT_TEXTURE * fbm3(p, seed + 505, 6, 3.0, 0.6))
    # The marginal swell sits a varying distance inland, not on a ring.
    inland = coast_m * np.exp(0.4 * fbm3(p, seed + 606, 3, 4.0))
    craton = CRATON_UPLIFT * cratonic_profile(inland) * uplift_texture
    uplift = (
        craton
        + SWELL_UPLIFT * swell * uplift_texture
        + PLATEAU_UPLIFT * plateau
        + BELT_UPLIFT * belts
        + MINOR_UPLIFT * minor
        + HILL_UPLIFT * hills
        + MARGIN_UPLIFT * margins
    )
    active = np.clip(np.maximum(np.maximum(belts, minor), margins), 0.0, 1.0)
    # Lithology varies down to ~30 km; without it rivers run straight and parallel
    # down every uniform slope.
    lithology = np.exp(1.1 * fbm3(p, seed + 404, 7, 3.0, 0.6))
    orogen_zone = ridge_profile(np.abs(across), 3.0 * major_half) * segments * inland_fade
    texture = (
        lithology
        * strike_lithology(across, major_half, orogen_zone, 3.0 * fbm3(p, seed + 272, 3, 8.0))
        * (SHIELD_ERODIBILITY + (1 - SHIELD_ERODIBILITY) * active)
    )
    return ProceduralForcing(np.where(land, uplift, 0.0), texture, uplift_texture)


@dataclass(frozen=True, slots=True)
class RegionIntent:
    """Soft elevation target and rock behaviour for one resolved geology region."""

    name: str
    character: str
    target_m: float
    statistic: str  # "mean", "median" or "p90"
    transition_km: float
    erodibility: float
    age_factor: float


def region_intent(profile: GeologyProfile, name: str) -> RegionIntent | None:
    landform: LandformSettings | None = profile.landform
    if landform is not None:
        character, base, relief, transition = (
            landform.character, landform.elevation_m, landform.relief_m, landform.transition_km
        )
    elif profile.setting in SETTING_INTENT:
        character, base, relief, transition = SETTING_INTENT[profile.setting]
    else:
        return None
    age_factor = 1.0
    if profile.rejuvenation_age_ma is not None and character in ("mountains", "hills"):
        # Older mountain building leaves lower, smoother residual relief.
        age_factor = max(0.12, exp(-profile.rejuvenation_age_ma / OROGEN_DECAY_MYR))
    relief *= age_factor
    statistic, target = {
        "plain": ("mean", base),
        "hills": ("mean", base + 0.4 * relief),
        "plateau": ("median", base),
        "mountains": ("p90", base + 0.75 * relief),
    }[character]
    erodibility = SETTING_ERODIBILITY.get(profile.setting, 1.0)
    if profile.crust_age_ma is not None and profile.crust_age_ma > OLD_CRUST_MA:
        erodibility *= OLD_CRUST_ERODIBILITY
    return RegionIntent(name, character, target, statistic, transition, erodibility, age_factor)


@dataclass(frozen=True, slots=True)
class GeologyRegions:
    region: I64  # index per node; -1 for water or land outside every region
    intents: tuple[RegionIntent | None, ...]
    names: tuple[str, ...]
    ids: tuple[str, ...]
    settings: tuple[str, ...]


def geology_regions(
    world: WorldMap, recipe: WorldGeologyRecipe, mesh: SphereMesh, land: B
) -> GeologyRegions:
    coverage = resolve_geology(world, recipe)
    x, y = node_source_xy(world.project.frame, mesh)
    region = np.full(mesh.size, -1, dtype=np.int64)
    for index, item in enumerate(coverage.regions):
        shapely.prepare(item.geometry)
        inside = land & (region < 0) & np.asarray(shapely.contains_xy(item.geometry, x, y))
        region[inside] = index
    # Land nodes exactly on region boundaries take a neighbour's region.
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    for _ in range(4):
        missing = land & (region < 0)
        if not missing.any():
            break
        donor = np.full(mesh.size, -1, dtype=np.int64)
        candidate = missing[src] & (region[mesh.nbr] >= 0)
        donor[src[candidate]] = region[mesh.nbr[candidate]]
        region = np.where(missing & (donor >= 0), donor, region)
    return GeologyRegions(
        region,
        tuple(region_intent(r.profile, r.name) for r in coverage.regions),
        tuple(r.name for r in coverage.regions),
        tuple(r.id for r in coverage.regions),
        tuple(r.profile.setting for r in coverage.regions),
    )


def smooth_over_land(mesh: SphereMesh, values: F64, land: B, length_m: float) -> F64:
    """Graph diffusion over land, spreading roughly ``length_m``."""
    steps = min(400, max(0, round((length_m / mesh.spacing_m) ** 2)))
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    valid = land[src] & land[mesh.nbr]
    degree = np.bincount(src[valid], minlength=mesh.size).astype(np.float64)
    out = values.copy()
    for _ in range(steps):
        total = np.bincount(src[valid], weights=out[mesh.nbr[valid]], minlength=mesh.size)
        mean = np.divide(total, degree, out=out.copy(), where=degree > 0)
        out = np.where(land, 0.5 * out + 0.5 * mean, out)
    return out


@dataclass(frozen=True, slots=True)
class Forcing:
    """Per-node erosion forcing for one evolution (SI units)."""

    steady_uplift: F64  # m/yr over the whole history
    pulse_uplift: F64  # m/yr added in the final pulse window
    erodibility: F64
    procedural: B


def build_forcing(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    regions: GeologyRegions | None,
    scale: F64,
    seed: int,
    base_erodibility: float,
    duration_yr: float,
) -> Forcing:
    """Combine procedural and authored forcing; ``scale`` multiplies each region's uplift."""
    procedural = procedural_forcing(mesh, land, coast_m, seed)
    steady = np.zeros(mesh.size)
    pulse = np.zeros(mesh.size)
    factor = np.ones(mesh.size)
    transition = np.zeros(mesh.size)
    automatic = land.copy() if regions is None else land & (regions.region < 0)
    pulse_years = PLATEAU_PULSE_FRACTION * duration_yr
    for index, intent in enumerate(() if regions is None else regions.intents):
        assert regions is not None
        nodes = regions.region == index
        if intent is None:
            automatic |= nodes
            continue
        target = max(intent.target_m, 20.0)
        if intent.character == "plateau":
            # Late block uplift leaves a little-dissected surface with incised edges.
            steady[nodes] = 2e-5 * scale[index]
            pulse[nodes] = target / pulse_years * scale[index]
        else:
            steady[nodes] = target / REFERENCE_RELIEF_M_PER_MM_YR * 1e-3 * scale[index]
            if intent.character in ("plain", "hills"):
                steady[nodes] *= cratonic_profile(coast_m[nodes])
        factor[nodes] = intent.erodibility
        transition[nodes] = intent.transition_km * 1e3
    steady = np.where(automatic, procedural.uplift, steady * procedural.uplift_texture)
    authored = land & ~automatic
    if np.any(authored):
        half = float(np.median(transition[authored])) / 2
        steady = smooth_over_land(mesh, steady, land, half)
        pulse = smooth_over_land(mesh, pulse, land, half)
        factor = smooth_over_land(mesh, factor, land, half)
    erodibility = base_erodibility * factor * procedural.texture
    return Forcing(steady, pulse, erodibility, automatic)


def measure_regions(h: F64, regions: GeologyRegions) -> tuple[float | None, ...]:
    values: list[float | None] = []
    for index, intent in enumerate(regions.intents):
        z = h[regions.region == index]
        if intent is None or not len(z):
            values.append(None)
        elif intent.statistic == "p90":
            values.append(float(np.percentile(z, 90)))
        elif intent.statistic == "median":
            values.append(float(np.median(z)))
        else:
            values.append(float(np.mean(z)))
    return tuple(values)


def ocean_floor(mesh: SphereMesh, coast_m: F64, water: B, seed: int) -> F64:
    """Display bathymetry (m, negative).

    A continental shelf whose width varies along the coast (about 10-260 km), a
    sharp shelf break onto a steep slope, a continental rise into abyssal plains,
    and broad mid-ocean ridges and swells. A uniform shelf would draw an
    identical halo around every coast.
    """
    width = 10e3 + 250e3 * _smoothstep(fbm3(mesh.xyz, seed + 707, 4, 14.0), -0.3, 0.4) ** 1.5
    shelf = 20 + 120 * _smoothstep(coast_m, 0, width)
    slope = 3200 * _smoothstep(coast_m, width, width + 90e3)
    rise = 1000 * _smoothstep(coast_m, width + 90e3, width + 900e3)
    ridge = 1 - np.abs(fbm3(mesh.xyz, seed + 808, 3, 1.0))
    abyss = _smoothstep(coast_m, width + 300e3, width + 900e3)
    hills = fbm3(mesh.xyz, seed + 909, 5, 6.0)
    swell = abyss * (1300 * _smoothstep(ridge, 0.72, 0.97) - 250 * hills)
    return np.where(water, -(shelf + slope + rise - swell), 0.0)
