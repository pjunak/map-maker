# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Water wonders: desert oases and a river that splits to reach the sea two ways.

An oasis is a spring-fed pond with a ring of palms and gardens in a hot desert,
fed by groundwater rather than rain (Siwa, Ubari, Huacachina). A splitting river
divides on a low, swampy divide and sends part of its water to the sea by
another basin, like the Casiquiare, which joins the Orinoco to the Amazon.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from dmtools.terrain.pipeline.planet_lakes import Lakes
from dmtools.terrain.pipeline.planet_mesh import SphereMesh
from dmtools.terrain.pipeline.planet_noise import fbm3
from dmtools.terrain.pipeline.wonder_geometry import draw_site, smoothstep, warp

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]
type I64 = NDArray[np.int64]

OASES = (2, 6)  # random oases across the deserts
OASIS_RADIUS_M = (4e3, 14e3)  # the green ring around the spring
OASIS_POND = 0.3  # spring pond radius as a share of the oasis
OASIS_DEPTH_M = 25.0  # the hollow the spring pond lies in
OASIS_APART_M = 300e3
DESERT_ARIDITY = 0.15  # precipitation over potential evapotranspiration
DESERT_WARM_C = 14.0
FORK_SHARE = (0.25, 0.45)  # share of the river's water that takes the other way
FORK_DIVIDE_M = 300.0  # the divide it crosses is at most this high above the river
FORK_REACH_M = 300e3  # a hand-placed fork snaps to a river within this distance
FORK_MIN_SHARE_OF_PEAK = 0.02  # rivers that may fork: this share of the largest
FORK_INLAND_M = 150e3  # a split near the coast would be a delta, not a wonder
FORK_MOUTHS_APART_M = 400e3  # the two courses reach the sea at least this far apart


@dataclass(frozen=True, slots=True)
class Oases:
    """Spring-fed oases: centres and the radius of their green ring."""

    xyz: F64
    radius_m: F64

    def __len__(self) -> int:
        return len(self.radius_m)

    @staticmethod
    def empty() -> Oases:
        return Oases(np.zeros((0, 3)), np.zeros(0))


@dataclass(frozen=True, slots=True)
class Forks:
    """Rivers that split: where, the first node across the divide, and how much goes."""

    split_xyz: F64  # (k, 3) where the river divides
    branch_xyz: F64  # (k, 3) where the branch crosses the divide into the other basin
    discharge_m3_s: F64  # water the branch takes
    area_m2: F64  # drainage area the branch carries (its share of the river's)

    def __len__(self) -> int:
        return len(self.discharge_m3_s)

    @staticmethod
    def empty() -> Forks:
        z = np.zeros(0)
        return Forks(np.zeros((0, 3)), np.zeros((0, 3)), z, z)


def deserts(land: B, precipitation_mm: F64, pet_mm: F64, temperature_c: F64) -> B:
    """Hot deserts, where an oasis is a wonder."""
    aridity = precipitation_mm / np.maximum(pet_mm, 1.0)
    return land & (aridity < DESERT_ARIDITY) & (temperature_c > DESERT_WARM_C)


def place_oases(
    mesh: SphereMesh,
    eligible: B,
    rng: np.random.Generator,
) -> Oases:
    """A few oases scattered across the ``eligible`` (desert) nodes, well apart."""
    sites: list[F64] = []
    radii: list[float] = []
    for _ in range(int(rng.integers(*OASES))):
        site = draw_site(mesh, eligible.astype(np.float64), 1.0, rng)
        radius = float(rng.uniform(*OASIS_RADIUS_M))
        if site is None:
            break
        if any(float(site @ other) > np.cos(OASIS_APART_M / mesh.radius_m) for other in sites):
            continue
        sites.append(site)
        radii.append(radius)
    if not sites:
        return Oases.empty()
    return Oases(np.array(sites), np.array(radii))


def authored_oases(
    mesh: SphereMesh, land: B, centres: F64, radii_m: F64, names: tuple[str, ...]
) -> Oases:
    """Hand-placed oases at unit vectors ``centres``; each must lie on land."""
    tree = KDTree(mesh.xyz)
    for xyz, name in zip(centres, names, strict=True):
        if not land[int(tree.query(xyz)[1])]:
            raise ValueError(f"{name} lies at sea; place an oasis on land.")
    return Oases(
        centres / np.linalg.norm(centres, axis=1)[:, None], np.asarray(radii_m, dtype=np.float64)
    )


def _oasis_distance(
    points: F64, planet_radius_m: float, oases: Oases, detail_m: float | None
) -> tuple[F64, F64]:
    """Each point's warped distance to the nearest oasis, in its radii, and that radius."""
    radius = planet_radius_m
    out = np.full(len(points), np.inf)
    size = np.ones(len(points))
    if not len(oases):
        return out, size
    widest = float(oases.radius_m.max())
    found = KDTree(oases.xyz).query(
        points, distance_upper_bound=2 * np.sin(2.0 * widest / radius / 2), workers=-1
    )
    index = np.asarray(found[1], dtype=np.int64)
    near = np.flatnonzero(index < len(oases))
    if not len(near):
        return out, size
    octaves = 4 if detail_m is None else int(np.clip(np.log2(widest / detail_m), 2, 9))
    p = warp(points[near], 9701, 0.35 * widest / radius, radius / widest, octaves)
    centre = oases.xyz[index[near]]
    size[near] = oases.radius_m[index[near]]
    out[near] = np.arccos(np.clip(np.sum(p * centre, axis=1), -1, 1)) * radius / size[near]
    return out, size


def oasis_relief(
    points: F64, planet_radius_m: float, oases: Oases, detail_m: float | None = None
) -> F64:
    """The hollow each spring pond lies in (metres, negative)."""
    s, _ = _oasis_distance(points, planet_radius_m, oases, detail_m)
    return -OASIS_DEPTH_M * (1 - smoothstep(s, 0.6 * OASIS_POND, 1.6 * OASIS_POND))


def oasis_cover(
    points: F64, planet_radius_m: float, oases: Oases, detail_m: float | None = None
) -> tuple[F64, F64]:
    """Gardens and palms (0..1) and the spring pond (0..1) at unit vectors ``points``."""
    s, _ = _oasis_distance(points, planet_radius_m, oases, detail_m)
    patchy = 0.8 + 0.2 * fbm3(points, 9702, 3, planet_radius_m / 3e3)
    green = np.clip((1 - smoothstep(s, 0.55, 1.0)) * patchy, 0, 1)
    pond = 1 - smoothstep(s, 0.8 * OASIS_POND, OASIS_POND)
    return green, pond


def find_fork(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    elevation_m: F64,
    lakes: Lakes,
    rng: np.random.Generator,
    near: F64 | None = None,
) -> tuple[int, int] | None:
    """A river node and its neighbour across a low divide that reaches the sea another way.

    The split lies well inland and the two courses reach the sea far apart, as
    the Orinoco and the Amazon do, so it is a divided river and not a delta.

    With ``near`` (a unit vector) the fork is the best one within
    ``FORK_REACH_M`` of it; otherwise one of the best few, drawn at random.
    """
    receiver = lakes.flow.receiver
    discharge = lakes.discharge_m3_s
    outlet = _outlets(receiver)
    to_sea = ~land[outlet]
    # Large rivers well inland.
    river = land & (lakes.lake < 0) & to_sea & (coast_m > FORK_INLAND_M) & (
        discharge >= FORK_MIN_SHARE_OF_PEAK * float(discharge[land].max(initial=0.0))
    )
    if near is not None:
        close = mesh.xyz @ near > np.cos(FORK_REACH_M / mesh.radius_m)
        river &= close
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    dst = mesh.nbr
    ok = (
        river[src] & land[dst] & (lakes.lake[dst] < 0) & to_sea[dst]
        & (outlet[dst] != outlet[src])
        & (elevation_m[dst] - elevation_m[src] < FORK_DIVIDE_M)
    )
    mouths = np.sum(mesh.xyz[outlet[src]] * mesh.xyz[outlet[dst]], axis=1)
    ok &= mouths < np.cos(FORK_MOUTHS_APART_M / mesh.radius_m)
    if not ok.any():
        return None
    u, v = src[ok], dst[ok]
    score = discharge[u] * np.exp(-np.maximum(elevation_m[v] - elevation_m[u], 0.0) / 150.0)
    order = np.argsort(-score)
    pick = 0 if near is not None else int(rng.integers(0, min(5, len(order))))
    return int(u[order[pick]]), int(v[order[pick]])


def split_river(
    mesh: SphereMesh, lakes: Lakes, split: int, branch: int, share: float
) -> tuple[Lakes, Forks]:
    """Lakes whose rivers send ``share`` of the river at ``split`` down ``branch``.

    Discharge and drainage area move from the river's own course below the
    split to the branch's course to the sea, so maps at every scale draw the
    branch and the thinner main stem.
    """
    receiver = lakes.flow.receiver
    discharge = lakes.discharge_m3_s.copy()
    area = lakes.flow.area_m2.copy()
    water = share * float(discharge[split])
    drained = share * float(area[split])
    for start, sign in ((int(receiver[split]), -1.0), (branch, 1.0)):
        node = start
        for _ in range(mesh.size):
            if node < 0:
                break
            discharge[node] = max(discharge[node] + sign * water, 0.0)
            area[node] = max(area[node] + sign * drained, 0.0)
            node = int(receiver[node])
    forks = Forks(mesh.xyz[[split]], mesh.xyz[[branch]], np.array([water]), np.array([drained]))
    flow = replace(lakes.flow, area_m2=area)
    return replace(lakes, discharge_m3_s=discharge, flow=flow), forks


def _outlets(receiver: I64) -> I64:
    """The node each node finally drains to (a sea node, or a closed basin's sink)."""
    target = np.where(receiver >= 0, receiver, np.arange(len(receiver)))
    for _ in range(64):
        jumped = target[target]
        if np.array_equal(jumped, target):
            break
        target = jumped
    return target
