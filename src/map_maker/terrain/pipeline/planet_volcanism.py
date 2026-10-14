# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Volcanoes from plate tectonics: arcs, hotspot tracks, rifts and seamounts.

Volcanoes are young constructional landforms, so they are added on top of the
eroded relief instead of being eroded from uplift:

* **Arc volcanoes** (stratovolcanoes) stand in a line ~100-200 km inland of
  coasts on a plate's leading edge, above the subducting slab, typically 50-70
  km apart (de Bremond d'Ars et al. 1995): the Andes, the Cascades, Japan.
* **Hotspots** are fixed mantle plumes under moving plates (Wilson 1963). The
  active volcano sits over the plume and older, extinct ones trail away in the
  direction of plate motion, ageing and subsiding along the track: shield
  volcanoes and calderas on land (Yellowstone, Tibesti), seamount and guyot
  chains at sea (Hawaii-Emperor).
* **Rift volcanoes** line continental rifts (Kilimanjaro, Kenya, Eifel).
* **Seamounts** dot the ocean floor (roughly one large seamount per
  ~300,000 km^2; Wessel et al. 2010).

The authored coastline stays authoritative: volcanoes at sea never break the
surface (their summits stop at GUYOT_DEPTH_M, like drowned, wave-planed guyots).
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from map_maker.terrain.pipeline.planet_mesh import SphereMesh
from map_maker.terrain.pipeline.planet_noise import fbm3, value_noise3
from map_maker.terrain.pipeline.planet_tectonics import Tectonics, plume_track
from map_maker.terrain.pipeline.wonder_geometry import draw_site, warp

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

KINDS = ("stratovolcano", "shield volcano", "caldera", "seamount", "shattered volcano")
SETTINGS = ("subduction arc", "hotspot", "continental rift", "intraplate", "titan", "wonder")
STRATO, SHIELD, CALDERA, SEAMOUNT, SHATTERED = range(5)
ARC, HOTSPOT, RIFT, INTRAPLATE, TITAN, WONDER = range(6)
# Wonder kinds (domain.wonders) that are volcanoes, placed with the others.
VOLCANO_WONDERS = ("titan", "shattered", "active")

# Opt-in fantastical landmark: one giant shield, an Earth-sized Olympus Mons
# (Mars: 22 km high, 600 km across, 5 deg flanks, a basal cliff up to 8 km).
TITAN_HEIGHT_M = 10_000.0
TITAN_RADIUS_M = 280e3
TITAN_CALDERA_RADIUS_M = 30e3
TITAN_CALDERA_DEPTH_M = 2_500.0
TITAN_SCARP = 0.88  # share of the basal radius where the flank breaks into the cliff
TITAN_MIN_COAST_M = 350e3
TITAN_VALLEYS = 32  # radial valleys around the flanks
TITAN_VALLEY_DEPTH = 0.12  # share of the summit height at mid-flank

# A shattered volcano: a stratovolcano that blew itself apart. Its flank slid
# away in a giant landslide and the summit blew out (Mount St Helens 1980,
# Bezymianny 1956, Socompa's 600 km^2 debris field), leaving a horseshoe
# amphitheatre open on one side and a hummocky debris field beyond it.
SHATTERED_HEIGHT_M = (3500.0, 5000.0)
SHATTERED_RADIUS_M = (25e3, 45e3)
SHATTERED_COAST_M = 120e3
# A giant active stratovolcano, taller than any on Earth (Ojos del Salado 6.9 km
# above sea level, Kilimanjaro 4.9 km above its base), erupting.
FIRE_HEIGHT_M = (6500.0, 8500.0)
FIRE_ASPECT = (0.1, 0.13)
FIRE_COAST_M = 200e3

ARC_SPACING_M = 70e3
ARC_FRONT_M = 130e3  # typical distance of the volcanic front inland of the coast
RIFT_SPACING_M = 120e3
HOTSPOT_TRACK_SPACING_M = 140e3
HOTSPOT_TRACK_MAX_MYR = 70.0
SEAMOUNT_AREA_M2 = 3e11  # ocean floor per random intraplate seamount
MAX_SUMMIT_M = 6600.0
MIN_EDIFICE_M = 500.0
CALDERA_SHARE = 0.45  # caldera radius at most this share of the basal radius
GUYOT_DEPTH_M = -150.0  # sea volcanoes stop below the surface (authored coastline)
# Opt-in volcanic islands.
ISLAND_SUMMIT_M = 4200.0  # summit of a fresh ocean-island shield (Mauna Kea 4.2 km)
ISLAND_DECAY_MYR = 10.0
ISLAND_VENT_SUMMIT_M = 1500.0  # islands above this gain satellite shield vents
ISLAND_DROWN_M = 600.0  # subsidence and wave erosion that drown old islands to guyots
ISLAND_SHIELD_ASPECT = 0.09
ISLAND_ARC_ASPECT = 0.12
ISLAND_ARC_OFFSET_M = 160e3  # arc front behind the trench, on the overriding plate
ISLAND_ARC_SPACING_M = 90e3
LOBE_AMPLITUDE = 0.35  # outline irregularity of shields and islands (share of radius)


@dataclass(frozen=True, slots=True)
class Volcanoes:
    xyz: F64  # (k, 3) unit vectors
    height_m: F64  # edifice height above its base
    radius_m: F64  # basal radius
    kind: I64  # index into KINDS
    setting: I64  # index into SETTINGS
    active: B
    age_myr: F64
    caldera_radius_m: F64  # 0 without a caldera
    caldera_depth_m: F64
    summit_m: F64  # planned summit above sea level if it may emerge as an island; NaN never
    emergent: B  # stands above sea level as a volcanic island

    @classmethod
    def empty(cls) -> Volcanoes:
        z = np.zeros(0)
        i = np.zeros(0, dtype=np.int64)
        b = np.zeros(0, dtype=bool)
        return cls(np.zeros((0, 3)), z, z, i, i, b, z, z, z, z, b)

    def __len__(self) -> int:
        return len(self.height_m)

    def subset(self, mask: B) -> Volcanoes:
        return Volcanoes(*(getattr(self, name)[mask] for name in _FIELDS))


def place_volcanoes(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    plates: Tectonics,
    seed: int,
    ground_m: F64,
    islands: bool = False,
) -> Volcanoes:
    """Volcanoes for this world; ``ground_m`` is the eroded land surface they stand on.

    With ``islands``, young hotspot volcanoes at sea are planned to break the
    surface and island arcs rise behind ocean-ocean trenches (see ``emerge``).
    Wonder volcanoes are separate (``wonder_volcanoes``, ``placed_volcano``).
    """
    rng = np.random.default_rng([seed, 5150])
    radius = mesh.radius_m
    parts: list[Volcanoes] = []

    # Subduction arcs: a band inland of leading-edge coasts, broken where the
    # slab is flat (along-arc gaps, as in central Peru).
    arc_weight = (
        land
        * np.clip((plates.leading - 0.6) / 0.3, 0, 1)
        * np.exp(-(((coast_m - ARC_FRONT_M) / 40e3) ** 2))
        * (fbm3(mesh.xyz, seed + 5201, 3, 8.0) > 0.08)
    )
    arc = _poisson(mesh.xyz, arc_weight, ARC_SPACING_M / radius, rng)
    if len(arc):
        height = np.clip(rng.lognormal(np.log(2300.0), 0.35, len(arc)), 900, 4800)
        kind = np.where(rng.random(len(arc)) < 0.12, CALDERA, STRATO)
        parts.append(_build(mesh.xyz[arc], height, kind, ARC, rng.random(len(arc)) < 0.7, rng))

    # Continental rifts: volcanoes on the rift floor and shoulders.
    near_rift = (plates.convergence < -0.006) & (plates.boundary_m < 70e3)
    rift = _poisson(
        mesh.xyz, (land & near_rift & (coast_m > 30e3)).astype(np.float64),
        RIFT_SPACING_M / radius, rng,
    )
    if len(rift):
        height = np.clip(rng.lognormal(np.log(2000.0), 0.45, len(rift)), 700, 5200)
        kind = np.where(rng.random(len(rift)) < 0.35, SHIELD, STRATO)
        parts.append(
            _build(mesh.xyz[rift], height, kind, RIFT, rng.random(len(rift)) < 0.55, rng)
        )

    parts.append(_hotspots(mesh, land, plates, rng, islands))

    # Random intraplate seamounts on the ocean floor.
    ocean = np.flatnonzero(~land & (coast_m > 150e3))
    count = int(mesh.area_m2[ocean].sum() / SEAMOUNT_AREA_M2)
    if count and len(ocean):
        chosen = rng.choice(ocean, size=min(count, len(ocean)), replace=False)
        height = np.clip(rng.lognormal(np.log(1800.0), 0.4, len(chosen)), 800, 4000)
        kind = np.full(len(chosen), SEAMOUNT)
        parts.append(
            _build(
                mesh.xyz[chosen], height, kind, INTRAPLATE, np.zeros(len(chosen), bool), rng,
                age_myr=rng.uniform(5, 100, len(chosen)),
            )
        )
    if islands:
        parts.append(_island_arcs(mesh, land, coast_m, plates, seed, rng))
    volcanoes = join_volcanoes(parts)
    if not len(volcanoes):
        return volcanoes
    # Earth's highest volcanoes reach ~6-7 km (Ojos del Salado 6.9 km): edifices
    # on high ground are smaller, as eruption columns and lava need a pressure head.
    base = ground_m[np.asarray(KDTree(mesh.xyz).query(volcanoes.xyz)[1], dtype=np.int64)]
    on_land = volcanoes.kind != SEAMOUNT
    ceiling = MAX_SUMMIT_M * rng.uniform(0.8, 1.05, len(volcanoes))
    room = np.maximum(ceiling - np.maximum(base, 0.0), MIN_EDIFICE_M)
    height = np.where(on_land, np.minimum(volcanoes.height_m, room), volcanoes.height_m)
    scale = height / volcanoes.height_m
    radius = volcanoes.radius_m * scale
    volcanoes = Volcanoes(
        volcanoes.xyz, height, radius, volcanoes.kind, volcanoes.setting,
        volcanoes.active, volcanoes.age_myr,
        np.minimum(volcanoes.caldera_radius_m, CALDERA_SHARE * radius),
        volcanoes.caldera_depth_m * scale,
        volcanoes.summit_m, volcanoes.emergent,
    )
    return volcanoes


def wonder_volcanoes(
    mesh: SphereMesh, land: B, coast_m: F64, seed: int, kinds: tuple[str, ...]
) -> Volcanoes:
    """Fantastical volcanoes of ``kinds`` placed at random deep inland.

    A ``titan`` shield, a ``shattered`` volcano and an ``active`` giant. Each has
    its own random stream: earlier placements vary with mesh resolution, and so
    would anything drawn after them.
    """
    volcanoes = Volcanoes.empty()
    if "titan" in kinds:
        volcanoes = _titan(mesh, land, coast_m, np.random.default_rng([seed, 7070]))
    for kind, code, coast, build in (
        ("shattered", 7171, SHATTERED_COAST_M, shattered_volcano),
        ("active", 7272, FIRE_COAST_M, fire_mountain),
    ):
        if kind not in kinds:
            continue
        rng = np.random.default_rng([seed, code])
        taken = np.zeros(mesh.size, dtype=bool)
        for xyz, reach in zip(volcanoes.xyz, volcanoes.radius_m, strict=True):
            taken |= mesh.xyz @ xyz > np.cos(2 * reach / mesh.radius_m)
        site = draw_site(
            mesh, (land & (coast_m >= coast) & ~taken).astype(np.float64), 1.0, rng
        )
        if site is not None:
            volcanoes = join_volcanoes([volcanoes, build(site, None, rng)])
    return volcanoes


def _titan(mesh: SphereMesh, land: B, coast_m: F64, rng: np.random.Generator) -> Volcanoes:
    """One giant shield deep inside a continent, beyond the ceiling of real volcanoes."""
    site = draw_site(mesh, (land & (coast_m >= TITAN_MIN_COAST_M)).astype(np.float64), 1.0, rng)
    if site is None:
        site = mesh.xyz[int(np.argmax(np.where(land, coast_m, -1.0)))]
    return titan_volcano(site, TITAN_RADIUS_M * rng.uniform(0.9, 1.1), rng)


def placed_volcano(kind: str, site: F64, radius_m: float, seed: int) -> Volcanoes:
    """A hand-placed wonder volcano of ``kind`` at unit vector ``site``.

    Its shape is drawn from its own ``seed`` (ADR-0097), so other wonders do not
    change it.
    """
    code, build = {
        "titan": (7071, _titan_at),
        "shattered": (7172, shattered_volcano),
        "active": (7273, fire_mountain),
    }[kind]
    return build(site, radius_m, np.random.default_rng([seed, code]))


def _titan_at(site: F64, radius_m: float | None, rng: np.random.Generator) -> Volcanoes:
    return titan_volcano(site, TITAN_RADIUS_M if radius_m is None else radius_m, rng)


def shattered_volcano(site: F64, radius_m: float | None, rng: np.random.Generator) -> Volcanoes:
    """A blown-apart stratovolcano at ``site``; None draws its size."""
    if radius_m is None:
        radius = float(rng.uniform(*SHATTERED_RADIUS_M))
        height = float(rng.uniform(*SHATTERED_HEIGHT_M))
    else:
        radius = radius_m
        height = float(np.clip(0.12 * radius, 2500.0, 6000.0)) * rng.uniform(0.9, 1.1)
    return _wonder_volcano(site, height, radius, SHATTERED, False, 0.25 * radius, 0.18 * height)


def fire_mountain(site: F64, radius_m: float | None, rng: np.random.Generator) -> Volcanoes:
    """A giant active stratovolcano at ``site``; None draws its size."""
    aspect = float(rng.uniform(*FIRE_ASPECT))
    if radius_m is None:
        height = float(rng.uniform(*FIRE_HEIGHT_M))
        radius = height / aspect
    else:
        radius = radius_m
        height = float(np.clip(radius * aspect, 3000.0, 9000.0))
    return _wonder_volcano(site, height, radius, STRATO, True, 0.06 * radius, 400.0)


def _wonder_volcano(
    site: F64, height: float, radius: float, kind: int, active: bool, crater: float, deep: float
) -> Volcanoes:
    return Volcanoes(
        (site / np.linalg.norm(site))[None, :],
        np.array([height]),
        np.array([radius]),
        np.array([kind]),
        np.array([WONDER]),
        np.array([active]),
        np.array([0.0]),
        np.array([crater]),
        np.array([deep]),
        np.array([np.nan]),
        np.array([False]),
    )


def breach_azimuth(xyz: F64) -> F64:
    """The direction a shattered volcano's amphitheatre opens, fixed by its position."""
    return np.pi * (1 + value_noise3(1e3 * np.atleast_2d(xyz), 9601))


def titan_volcano(site: F64, radius_m: float, rng: np.random.Generator) -> Volcanoes:
    """A titan shield at ``site`` whose height and caldera scale with its radius."""
    scale = radius_m / TITAN_RADIUS_M
    return Volcanoes(
        (site / np.linalg.norm(site))[None, :],
        np.array([TITAN_HEIGHT_M * float(np.clip(scale, 0.6, 1.4)) * rng.uniform(0.9, 1.1)]),
        np.array([radius_m]),
        np.array([SHIELD]),
        np.array([TITAN]),
        np.array([True]),
        np.array([0.0]),
        np.array([TITAN_CALDERA_RADIUS_M * scale]),
        np.array([TITAN_CALDERA_DEPTH_M]),
        np.array([np.nan]),
        np.array([False]),
    )


def _island_arcs(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    plates: Tectonics,
    seed: int,
    rng: np.random.Generator,
) -> Volcanoes:
    """Intra-oceanic island arcs: volcanoes ~100-200 km behind ocean-ocean trenches.

    Where two oceanic plates converge, the down-going slab melts at ~100 km
    depth under the overriding plate, building a curved chain of volcanic
    islands (Marianas, Aleutians, Lesser Antilles, Tonga).
    """
    closing = np.clip((plates.convergence - 0.02) / 0.03, 0, 1)
    behind = np.exp(-(((plates.across_m + ISLAND_ARC_OFFSET_M) / 35e3) ** 2))
    open_sea = (~land) & (coast_m > 150e3)
    gaps = fbm3(mesh.xyz, seed + 5301, 3, 9.0) > 0.1
    weight = closing * behind * open_sea * gaps
    chosen = _poisson(mesh.xyz, weight, ISLAND_ARC_SPACING_M / mesh.radius_m, rng)
    if not len(chosen):
        return Volcanoes.empty()
    summit = np.clip(rng.lognormal(np.log(900.0), 0.5, len(chosen)), 150, 3000)
    placeholder = np.full(len(chosen), 3000.0)
    kind = np.full(len(chosen), STRATO)
    return _build(
        mesh.xyz[chosen], placeholder, kind, ARC, rng.random(len(chosen)) < 0.6, rng,
        summit_m=summit,
    )


def _hotspots(
    mesh: SphereMesh, land: B, plates: Tectonics, rng: np.random.Generator, islands: bool
) -> Volcanoes:
    radius = mesh.radius_m
    tree = KDTree(mesh.xyz)
    xyz: list[F64] = []
    heights: list[float] = []
    kinds: list[int] = []
    actives: list[bool] = []
    ages: list[float] = []
    summits: list[float] = []
    for index in range(len(plates.plumes)):
        speed = float(plates.plume_speed_m_yr[index])
        if speed < 1e-4:
            continue
        length = min(HOTSPOT_TRACK_MAX_MYR * 1e6 * speed, 4000e3)
        steps = int(length // HOTSPOT_TRACK_SPACING_M)
        # Volcanoes along a track are unevenly spaced and step off its axis.
        along = np.concatenate(
            ([0.0], np.cumsum(HOTSPOT_TRACK_SPACING_M * rng.uniform(0.7, 1.3, steps)))
        )
        track = plume_track(plates, index, along, radius)
        side = np.cross(plates.plumes[index], plates.plume_heading[index])
        side /= max(float(np.linalg.norm(side)), 1e-12)
        track = track + side * rng.uniform(-25e3, 25e3, (len(track), 1)) / radius
        track /= np.linalg.norm(track, axis=1)[:, None]
        for k, point in enumerate(track):
            age = along[k] / speed / 1e6
            on_land = bool(land[int(tree.query(point)[1])])
            fresh = np.exp(-age / (8.0 if on_land else 40.0))
            height = (2500.0 if on_land else 4500.0) * (0.35 + 0.65 * fresh)
            # Ocean islands build to ~4 km above sea level over the plume, then
            # subside and erode as the plate carries them away, drowning to
            # guyots within ~15-20 Myr (Hawaii to Midway and the Emperor chain).
            emerges = islands and not on_land
            summit = (
                ISLAND_SUMMIT_M * np.exp(-age / ISLAND_DECAY_MYR) - ISLAND_DROWN_M
                if emerges
                else np.nan
            )
            # Young ocean islands coalesce from several shield vents.
            vents = [(point, summit)]
            if emerges and summit > ISLAND_VENT_SUMMIT_M:
                for _ in range(2):
                    angle = rng.uniform(0, 2 * np.pi)
                    offset = rng.uniform(40e3, 75e3) / radius
                    east = np.cross([0.0, 0.0, 1.0], point)
                    east /= max(float(np.linalg.norm(east)), 1e-12)
                    north = np.cross(point, east)
                    shifted = point + offset * (np.cos(angle) * east + np.sin(angle) * north)
                    vents.append(
                        (shifted / np.linalg.norm(shifted), summit * rng.uniform(0.45, 0.8))
                    )
            for number, (where, top) in enumerate(vents):
                xyz.append(where)
                heights.append(height * float(rng.uniform(0.8, 1.2)))
                if on_land:
                    kinds.append(CALDERA if k == 0 and rng.random() < 0.5 else SHIELD)
                else:
                    kinds.append(SEAMOUNT)
                actives.append(k == 0 and number == 0)
                ages.append(age)
                summits.append(top)
    if not xyz:
        return Volcanoes.empty()
    return _build(
        np.array(xyz), np.array(heights), np.array(kinds), HOTSPOT, np.array(actives), rng,
        age_myr=np.array(ages), summit_m=np.array(summits),
    )


def _build(
    xyz: F64,
    height: F64,
    kind: I64,
    setting: int,
    active: B,
    rng: np.random.Generator,
    *,
    age_myr: F64 | None = None,
    summit_m: F64 | None = None,
) -> Volcanoes:
    n = len(height)
    # Flank slope: stratovolcanoes ~0.2-0.3 (11-17 deg mean), shields ~0.06-0.1,
    # seamounts ~0.15 (Smith 1988).
    aspect = np.select(
        [kind == SHIELD, kind == SEAMOUNT], [rng.uniform(0.06, 0.1, n), rng.uniform(0.12, 0.2, n)],
        rng.uniform(0.18, 0.3, n),
    )
    caldera = kind == CALDERA
    if age_myr is None:
        age_myr = np.where(active, 0.0, rng.uniform(0.1, 3.0, n))
    return Volcanoes(
        xyz / np.linalg.norm(xyz, axis=1)[:, None],
        height,
        height / aspect,
        kind.astype(np.int64),
        np.full(n, setting, dtype=np.int64),
        active.astype(bool),
        age_myr,
        np.where(caldera, rng.uniform(4e3, 15e3, n), 0.0),
        np.where(caldera, rng.uniform(300, 800, n), 0.0),
        np.full(n, np.nan) if summit_m is None else np.asarray(summit_m, dtype=np.float64),
        np.zeros(n, dtype=bool),
    )


_FIELDS = (
    "xyz", "height_m", "radius_m", "kind", "setting", "active", "age_myr",
    "caldera_radius_m", "caldera_depth_m", "summit_m", "emergent",
)


def join_volcanoes(parts: list[Volcanoes]) -> Volcanoes:
    """Several volcano lists as one."""
    parts = [p for p in parts if len(p)]
    if not parts:
        return Volcanoes.empty()
    return Volcanoes(*(np.concatenate([getattr(p, f) for p in parts]) for f in _FIELDS))


def emerge(volcanoes: Volcanoes, mesh: SphereMesh, water: B, floor_m: F64) -> Volcanoes:
    """Raise volcanoes with a planned positive summit above the sea as islands.

    The edifice spans from the local sea floor to the planned summit; ocean
    islands are broad shields (Hawaii's flanks average ~5 deg), arc islands
    steeper composite cones on a wide submarine base.
    """
    if not len(volcanoes):
        return volcanoes
    node = np.asarray(KDTree(mesh.xyz).query(volcanoes.xyz)[1], dtype=np.int64)
    at_sea = water[node]
    summit = volcanoes.summit_m
    rises = at_sea & np.isfinite(summit) & (summit > 0)
    if not rises.any():
        return volcanoes
    depth = np.maximum(-floor_m[node], 0.0)
    height = np.where(rises, depth + np.nan_to_num(summit), volcanoes.height_m)
    hotspot = volcanoes.setting == HOTSPOT
    kind = np.where(rises & hotspot, SHIELD, volcanoes.kind)
    aspect = np.where(hotspot, ISLAND_SHIELD_ASPECT, ISLAND_ARC_ASPECT)
    radius = np.where(rises, height / aspect, volcanoes.radius_m)
    return Volcanoes(
        volcanoes.xyz, height, radius, kind.astype(np.int64), volcanoes.setting,
        volcanoes.active, volcanoes.age_myr, volcanoes.caldera_radius_m,
        volcanoes.caldera_depth_m, volcanoes.summit_m, rises,
    )


def sea_floor_with_volcanoes(
    points: F64, radius_m: float, volcanoes: Volcanoes, floor_m: F64, minimum_radius_m: float = 0.0
) -> F64:
    """Sea floor (m) with seamounts (stopped below the surface) and emergent islands."""
    drowned = volcanoes.subset(~volcanoes.emergent)
    surface = np.minimum(
        floor_m + edifice_height(points, radius_m, drowned, minimum_radius_m),
        np.maximum(floor_m, GUYOT_DEPTH_M),
    )
    if volcanoes.emergent.any():
        islands = volcanoes.subset(volcanoes.emergent)
        surface = np.maximum(
            surface, floor_m + edifice_height(points, radius_m, islands, minimum_radius_m)
        )
    return surface


def _poisson(xyz: F64, weight: F64, spacing: float, rng: np.random.Generator) -> I64:
    """Nodes at least ``spacing`` (radians) apart, preferring high ``weight``."""
    candidates = np.flatnonzero(weight > 0.05)
    if not len(candidates):
        return np.zeros(0, dtype=np.int64)
    # Thin to a manageable pool, then accept greedily in random, weight-biased order.
    pool = candidates[rng.random(len(candidates)) < min(1.0, 20000 / len(candidates))]
    priority = rng.random(len(pool)) ** (1.0 / np.maximum(weight[pool], 1e-6))
    order = pool[np.argsort(-priority)]
    cell = spacing
    grid: dict[tuple[int, int, int], list[int]] = {}
    accepted: list[int] = []
    limit = 2 * np.sin(spacing / 2)
    for node in order.tolist():
        p = xyz[node]
        key = (int(p[0] // cell), int(p[1] // cell), int(p[2] // cell))
        clash = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for other in grid.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                        if np.linalg.norm(xyz[other] - p) < limit:
                            clash = True
                            break
                    if clash:
                        break
                if clash:
                    break
            if clash:
                break
        if not clash:
            grid.setdefault(key, []).append(node)
            accepted.append(node)
    return np.array(accepted, dtype=np.int64)


def _shattered(
    p: F64, centre: F64, reached: F64, intact: F64, height: F64, planet_radius_m: float
) -> F64:
    """A shattered volcano's surface: its intact cone breached by a horseshoe
    amphitheatre, and a hummocky debris lobe beyond the breach.

    In the frame of the breach (``x`` towards it, ``y`` across, both in basal
    radii, after a domain warp that makes every edge organic) the amphitheatre
    has a rounded head at the summit crater and widens to its mouth at the
    base; its floor ramps down to the plain. The debris lobe starts on the lower
    flanks inside the mouth and ends in a lobed front about 2.6 radii out.
    """
    arc = np.arccos(np.clip(np.einsum("ij,ij->i", p, centre), -1, 1))
    per_radius = np.where(arc > 1e-12, reached / np.maximum(arc, 1e-12), 0.0)
    scale = float(np.median(per_radius[arc > 1e-12])) if (arc > 1e-12).any() else 1.0
    span = 1.0 / scale  # radians per basal radius
    q = warp(p, 9604, 0.08 * span, 1 / (0.35 * span), 4)
    east = np.cross([0.0, 0.0, 1.0], centre)
    east /= np.maximum(np.linalg.norm(east, axis=1), 1e-12)[:, None]
    north = np.cross(centre, east)
    azimuth = breach_azimuth(centre)
    ahead = np.cos(azimuth)[:, None] * north + np.sin(azimuth)[:, None] * east
    aside = np.cross(centre, ahead)
    x = np.einsum("ij,ij->i", q - centre, ahead) * scale
    y = np.einsum("ij,ij->i", q - centre, aside) * scale
    # A rounded head at x = -0.05, widening to the mouth at the base.
    along = np.clip(x, -0.05, 1.1)
    half = 0.17 + 0.2 * np.clip((along + 0.05) / 1.15, 0, 1)
    gap = np.hypot(x - along, y)  # distance from the amphitheatre's axis
    inside = 1 - _smooth(gap, half, half + 0.08)
    floor = 0.42 * height * (1 - np.clip((x + 0.2) / 1.3, 0, 1)) ** 1.3
    cone = np.where(reached <= 1, intact * (1 - inside) + np.minimum(intact, floor) * inside, 0.0)
    # Debris: an elliptical lobe beyond the mouth with a lobed front and hummocks.
    lobe = np.hypot((x - 1.45) / 1.15, y / (0.75 + 0.25 * np.clip(x - 0.5, 0, 1)))
    sheet = _smooth(x, 0.45, 0.75) * (1 - _smooth(lobe, 0.75, 1.0))
    hummocks = np.clip(0.35 + fbm3(p, 9602, 4, planet_radius_m / 4e3), 0.0, None)
    debris = height * sheet * (0.015 + 0.05 * hummocks)
    return np.maximum(cone, debris)


def _smooth(x: F64, a: F64 | float, b: F64 | float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def edifice_height(
    points: F64, planet_radius_m: float, volcanoes: Volcanoes, minimum_radius_m: float = 0.0
) -> F64:
    """Height (m) of the volcanic edifices at unit vectors ``points``.

    ``minimum_radius_m`` widens cones that a coarse grid could not resolve
    (keeping their volume), so the mesh carries them without aliasing.
    """
    out = np.zeros(len(points))
    if not len(volcanoes):
        return out
    radius = np.maximum(volcanoes.radius_m, minimum_radius_m)
    height = volcanoes.height_m * (volcanoes.radius_m / radius) ** 2
    # Shields and volcanic islands spread along rift zones and coalesce from
    # several vents (Hawaii's Big Island is five), so their outlines are lobed.
    irregular = volcanoes.emergent | (volcanoes.kind == SHIELD)
    lobes = (
        LOBE_AMPLITUDE
        * (
            fbm3(points, 9101, 3, planet_radius_m / 80e3)
            + 0.5 * fbm3(points, 9102, 3, planet_radius_m / 25e3)
        )
        if irregular.any()
        else np.zeros(len(points))
    )
    # A shattered volcano's debris field runs out to 2.6 radii beyond its centre.
    spread = np.where(volcanoes.kind == SHATTERED, 2.6, 1 + 1.5 * LOBE_AMPLITUDE)
    reach = float((radius * spread).max()) / planet_radius_m
    tree = KDTree(volcanoes.xyz)
    found_distance, found_index = tree.query(
        points, k=min(4, len(volcanoes)), distance_upper_bound=2 * np.sin(reach / 2),
        workers=-1,
    )
    distance = np.asarray(found_distance, dtype=np.float64).reshape(len(points), -1)
    index = np.asarray(found_index, dtype=np.int64).reshape(len(points), -1)
    for column in range(index.shape[1]):
        hit = index[:, column] < len(volcanoes)
        if not hit.any():
            continue
        v = index[hit, column]
        r = 2 * np.arcsin(np.clip(distance[hit, column] / 2, 0, 1)) * planet_radius_m
        stretch = np.where(irregular[v], 1 + lobes[hit], 1.0)
        reached = r / (radius[v] * stretch)
        s = np.clip(reached, 0, 1)
        kind = volcanoes.kind[v]
        # Concave stratovolcano and seamount flanks; broad convex shields.
        profile = np.where(kind == SHIELD, (1 - s**2) ** 0.7, (1 - s) ** 1.8)
        profile = np.where(kind == CALDERA, (1 - s) ** 1.3, profile)
        # A titan's flanks end in a cliff around its base (Olympus Mons).
        titan = volcanoes.setting[v] == TITAN
        scarp = 1 - np.clip((s - TITAN_SCARP) / (1 - TITAN_SCARP), 0, 1) ** 2
        profile = np.where(titan, profile * scarp, profile)
        if titan.any():
            # Glaciers and rivers cut its flanks into radial valleys and ridges
            # (Mount Kenya, Kohala), deepest at mid-flank.
            centre = volcanoes.xyz[v]
            east = np.cross([0.0, 0.0, 1.0], centre)
            east /= np.maximum(np.linalg.norm(east, axis=1), 1e-12)[:, None]
            north = np.cross(centre, east)
            p = points[hit]
            theta = np.arctan2(np.einsum("ij,ij->i", p, north), np.einsum("ij,ij->i", p, east))
            # Uneven spacing, valleys that wander downslope and vary in depth.
            wander = 4.0 * fbm3(p, 9103, 3, planet_radius_m / 150e3) + (0.5 + 2.0 * s) * fbm3(
                p, 9104, 3, planet_radius_m / 50e3
            )
            ridges = np.abs(np.sin(0.5 * TITAN_VALLEYS * theta + wander))
            depth = 0.4 + 0.6 * np.clip(0.5 + fbm3(p, 9105, 2, planet_radius_m / 120e3), 0, 1)
            cut = TITAN_VALLEY_DEPTH * depth * (1 - ridges) ** 3 * 4 * s * (1 - s)
            profile = np.where(titan & (r > volcanoes.caldera_radius_m[v]), profile - cut, profile)
        h = height[v] * profile
        shattered = kind == SHATTERED
        if shattered.any():
            h = np.where(shattered, _shattered(points[hit], volcanoes.xyz[v], reached, h,
                                               height[v], planet_radius_m), h)
        # Calderas: the summit collapsed into a flat-floored basin below its rim.
        rim = volcanoes.caldera_radius_m[v]
        inside = r < rim
        rim_height = height[v] * (1 - np.clip(rim / radius[v], 0, 1)) ** 1.3
        floor = rim_height - volcanoes.caldera_depth_m[v] * (1 - (r / np.maximum(rim, 1)) ** 8)
        h = np.where(inside, np.minimum(h, floor), h)
        out[hit] = np.maximum(out[hit], h)
    return out
