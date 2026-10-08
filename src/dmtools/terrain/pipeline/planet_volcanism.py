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

from dmtools.terrain.pipeline.planet_mesh import SphereMesh
from dmtools.terrain.pipeline.planet_noise import fbm3
from dmtools.terrain.pipeline.planet_tectonics import Tectonics, plume_track

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

KINDS = ("stratovolcano", "shield volcano", "caldera", "seamount")
SETTINGS = ("subduction arc", "hotspot", "continental rift", "intraplate")
STRATO, SHIELD, CALDERA, SEAMOUNT = range(4)
ARC, HOTSPOT, RIFT, INTRAPLATE = range(4)

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

    @classmethod
    def empty(cls) -> Volcanoes:
        z = np.zeros(0)
        i = np.zeros(0, dtype=np.int64)
        return cls(np.zeros((0, 3)), z, z, i, i, np.zeros(0, dtype=bool), z, z, z)

    def __len__(self) -> int:
        return len(self.height_m)


def place_volcanoes(
    mesh: SphereMesh, land: B, coast_m: F64, plates: Tectonics, seed: int, ground_m: F64
) -> Volcanoes:
    """Volcanoes for this world; ``ground_m`` is the eroded land surface they stand on."""
    rng = np.random.default_rng([seed, 5150])
    radius = mesh.radius_m
    parts: list[Volcanoes] = []

    # Subduction arcs: a band inland of leading-edge coasts, broken where the
    # slab is flat (along-arc gaps, as in central Peru).
    arc_weight = (
        land
        * np.clip((plates.leading - 0.5) / 0.4, 0, 1)
        * np.exp(-(((coast_m - ARC_FRONT_M) / 40e3) ** 2))
        * (fbm3(mesh.xyz, seed + 5201, 3, 8.0) > 0.0)
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

    parts.append(_hotspots(mesh, land, plates, rng))

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
    volcanoes = _concat(parts)
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
    return Volcanoes(
        volcanoes.xyz, height, radius, volcanoes.kind, volcanoes.setting,
        volcanoes.active, volcanoes.age_myr,
        np.minimum(volcanoes.caldera_radius_m, CALDERA_SHARE * radius),
        volcanoes.caldera_depth_m * scale,
    )


def _hotspots(mesh: SphereMesh, land: B, plates: Tectonics, rng: np.random.Generator) -> Volcanoes:
    radius = mesh.radius_m
    tree = KDTree(mesh.xyz)
    xyz: list[F64] = []
    heights: list[float] = []
    kinds: list[int] = []
    actives: list[bool] = []
    ages: list[float] = []
    for index in range(len(plates.plumes)):
        speed = float(plates.plume_speed_m_yr[index])
        if speed < 1e-4:
            continue
        length = min(HOTSPOT_TRACK_MAX_MYR * 1e6 * speed, 4000e3)
        steps = int(length // HOTSPOT_TRACK_SPACING_M)
        track = plume_track(
            plates, index, np.arange(steps + 1, dtype=np.float64) * HOTSPOT_TRACK_SPACING_M, radius
        )
        for k, point in enumerate(track):
            age = k * HOTSPOT_TRACK_SPACING_M / speed / 1e6
            on_land = bool(land[int(tree.query(point)[1])])
            fresh = np.exp(-age / (8.0 if on_land else 40.0))
            height = (2500.0 if on_land else 4500.0) * (0.35 + 0.65 * fresh)
            xyz.append(point)
            heights.append(height * float(rng.uniform(0.8, 1.2)))
            if on_land:
                kinds.append(CALDERA if k == 0 and rng.random() < 0.5 else SHIELD)
            else:
                kinds.append(SEAMOUNT)
            actives.append(k == 0)
            ages.append(age)
    if not xyz:
        return Volcanoes.empty()
    return _build(
        np.array(xyz), np.array(heights), np.array(kinds), HOTSPOT, np.array(actives), rng,
        age_myr=np.array(ages),
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
    )


def _concat(parts: list[Volcanoes]) -> Volcanoes:
    parts = [p for p in parts if len(p)]
    if not parts:
        return Volcanoes.empty()
    return Volcanoes(
        np.concatenate([p.xyz for p in parts]),
        *(np.concatenate([getattr(p, f) for p in parts]) for f in (
            "height_m", "radius_m", "kind", "setting", "active", "age_myr",
            "caldera_radius_m", "caldera_depth_m",
        )),
    )


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
    reach = float(radius.max()) / planet_radius_m
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
        s = np.clip(r / radius[v], 0, 1)
        kind = volcanoes.kind[v]
        # Concave stratovolcano and seamount flanks; broad convex shields.
        profile = np.where(kind == SHIELD, (1 - s**2) ** 0.7, (1 - s) ** 1.8)
        profile = np.where(kind == CALDERA, (1 - s) ** 1.3, profile)
        h = height[v] * profile
        # Calderas: the summit collapsed into a flat-floored basin below its rim.
        rim = volcanoes.caldera_radius_m[v]
        inside = r < rim
        rim_height = height[v] * (1 - np.clip(rim / radius[v], 0, 1)) ** 1.3
        floor = rim_height - volcanoes.caldera_depth_m[v] * (1 - (r / np.maximum(rim, 1)) ** 8)
        h = np.where(inside, np.minimum(h, floor), h)
        out[hit] = np.maximum(out[hit], h)
    return out
