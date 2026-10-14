# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Scarp wonders: great cliffs and tepuis, raised above the eroded relief.

A great cliff is a fault scarp kilometres high whose raised block tilts back
gently from its edge, like the Sierra Nevada's eastern face or Verona Rupes on
Miranda. A tepui is a table mountain walled by sheer cliffs on every side, like
Roraima and Auyan-tepui in the Guiana Highlands. Both are domain-warped so their
outlines are irregular, and both stand on the land after erosion, so their
faces keep their sharpness.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from map_maker.terrain.pipeline.planet_mesh import SphereMesh
from map_maker.terrain.pipeline.planet_noise import fbm3
from map_maker.terrain.pipeline.wonder_geometry import (
    destination,
    draw_site,
    floor_depth,
    path_normals,
    rift_axis,
    smoothstep,
    warp,
)

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]
type I64 = NDArray[np.int64]

CLIFF_LENGTH_M = (300e3, 1200e3)
CLIFF_HEIGHT_M = (1500.0, 3500.0)  # random cliffs; Earth's tallest fault scarps are ~3 km
CLIFF_SEGMENT_M = 30e3  # nominal width that sets its segments and jogs
CLIFF_BACK = 35.0  # the raised block tilts back over this many scarp heights
CLIFF_FACE = 0.6  # horizontal width of the face per metre of height (about 60 degrees)
CLIFF_TROUGH = 0.12  # a trough along the foot, as a share of the height
CLIFF_COAST_M = 80e3
CLIFF_TRIES = 120
TEPUI_RADIUS_M = (12e3, 40e3)
TEPUI_GROUP = (2, 6)  # tepuis in a random group, like the Gran Sabana's
TEPUI_COAST_M = 150e3


@dataclass(frozen=True, slots=True)
class Cliffs:
    """Great escarpments: the foot of each scarp, with its high side to the left."""

    paths: tuple[F64, ...]  # (n, 3) unit vectors along each foot, end to end
    height_m: F64  # scarp height of each path
    trough_m: tuple[F64, ...]  # (n,) depth of the trough along each foot

    def __len__(self) -> int:
        return len(self.paths)

    @staticmethod
    def empty() -> Cliffs:
        return Cliffs((), np.zeros(0), ())


@dataclass(frozen=True, slots=True)
class Tepuis:
    """Sheer-walled table mountains."""

    xyz: F64  # (k, 3) unit vectors of their centres
    radius_m: F64  # mean radius
    height_m: F64  # wall height above the plain
    aspect: F64  # long axis over short axis
    azimuth: F64  # direction of the long axis, radians from north

    def __len__(self) -> int:
        return len(self.radius_m)

    @staticmethod
    def empty() -> Tepuis:
        z = np.zeros(0)
        return Tepuis(np.zeros((0, 3)), z, z, z, z)


def tepui_height_m(radius_m: float) -> float:
    """A wall height for a tepui of this size: larger ones stand higher."""
    return float(np.clip(1000.0 + 24.0 * radius_m / 1e3, 1000.0, 2800.0))


def cliff_with_trough(
    start: F64,
    end: F64,
    height_m: float,
    ground_m: F64,
    tree: KDTree,
    planet_radius_m: float,
    rng: np.random.Generator,
) -> Cliffs:
    """A scarp from ``start`` to ``end`` (high side to the left) with a trough at its foot."""
    axis = rift_axis(start, end, CLIFF_SEGMENT_M, planet_radius_m, rng, wander=0.4)
    trough = floor_depth(axis, ground_m, tree, CLIFF_TROUGH * height_m)
    return Cliffs((axis,), np.array([height_m]), (trough,))


def place_cliff(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    ground_m: F64,
    rng: np.random.Generator,
    blocked: B | None = None,
) -> Cliffs:
    """One great cliff wholly on land, raised on the side whose ground is higher.

    Escarpments face the lower country, as the Great Escarpment faces the coast,
    so the scarp's high side is the side that already stands higher.
    """
    eligible = land & (coast_m > CLIFF_COAST_M)
    if blocked is not None:
        eligible &= ~blocked
    tree = KDTree(mesh.xyz)
    radius_m = mesh.radius_m
    for _ in range(CLIFF_TRIES):
        start = draw_site(mesh, eligible.astype(np.float64), 1.0, rng)
        if start is None:
            break
        end = destination(start, rng.uniform(0, 2 * np.pi), rng.uniform(*CLIFF_LENGTH_M) / radius_m)
        height = float(rng.uniform(*CLIFF_HEIGHT_M))
        coin = rng.random() < 0.5
        state = rng.bit_generator.state
        axis = rift_axis(start, end, CLIFF_SEGMENT_M, radius_m, rng, wander=0.4)
        nodes = np.asarray(tree.query(axis, workers=-1)[1], dtype=np.int64)
        if not eligible[nodes].all():
            continue
        # Compare the mean ground half a back slope to either side along the
        # scarp; a near tie is settled by a coin, so meshes agree on the side.
        reach = 0.5 * CLIFF_BACK * height / radius_m
        normals = path_normals(axis[::8])
        means = [
            float(ground_m[np.asarray(tree.query(
                np.cos(reach) * axis[::8] + sign * np.sin(reach) * normals
            )[1], dtype=np.int64)].mean())
            for sign in (1, -1)
        ]
        rng.bit_generator.state = state
        left_high = means[0] > means[1] + 50.0 or (abs(means[0] - means[1]) <= 50.0 and coin)
        if not left_high:
            start, end = end, start
        return cliff_with_trough(start, end, height, ground_m, tree, radius_m, rng)
    return Cliffs.empty()


def authored_cliffs(
    mesh: SphereMesh,
    land: B,
    ground_m: F64,
    ends: tuple[tuple[F64, F64], ...],
    heights_m: F64,
    names: tuple[str, ...],
    rng: np.random.Generator,
) -> Cliffs:
    """Hand-placed cliffs between unit-vector ``ends``, high side to the left."""
    tree = KDTree(mesh.xyz)
    paths: list[F64] = []
    troughs: list[F64] = []
    for (start, end), height, name in zip(ends, heights_m, names, strict=True):
        nodes = np.asarray(tree.query(np.stack((start, end)))[1], dtype=np.int64)
        if not land[nodes].all():
            raise ValueError(f"{name} reaches the sea; place both ends of a cliff on land.")
        cliff = cliff_with_trough(start, end, float(height), ground_m, tree, mesh.radius_m, rng)
        paths.extend(cliff.paths)
        troughs.extend(cliff.trough_m)
    return Cliffs(tuple(paths), np.asarray(heights_m, dtype=np.float64), tuple(troughs))


def cliff_relief(
    points: F64, planet_radius_m: float, cliffs: Cliffs, detail_m: float | None = None
) -> F64:
    """Height change (m) the cliffs make at unit vectors ``points``.

    The raised block stands the full height at the edge and tilts back to the
    plain over ``CLIFF_BACK`` heights. The face is steep and cut by buttresses
    and gullies, talus heaps below it, and a trough runs along the foot. The
    scarp dies out over the last sixth of its length at each end.
    """
    radius = planet_radius_m
    out = np.zeros(len(points))
    if not len(cliffs):
        return out
    tallest = float(cliffs.height_m.max())
    back = CLIFF_BACK * tallest
    near = _near(points, cliffs.paths, (back + 20e3) / radius)
    if not len(near):
        return out
    octaves = 5 if detail_m is None else int(np.clip(np.log2(40e3 / detail_m), 3, 11))
    p_all = warp(points[near], 9411, 8e3 / radius, radius / 40e3, octaves)
    total = np.zeros(len(near))
    for path, height, trough in zip(cliffs.paths, cliffs.height_m, cliffs.trough_m, strict=True):
        found = KDTree(path).query(
            p_all, distance_upper_bound=2 * np.sin((back + 20e3) / radius / 2), workers=-1
        )
        index = np.asarray(found[1], dtype=np.int64)
        hit = index < len(path)
        if not hit.any():
            continue
        i = index[hit]
        p = p_all[hit]
        last = len(path) - 1
        ahead = path[np.minimum(i + 1, last)] - path[np.maximum(i - 1, 0)]
        ahead -= np.sum(ahead * path[i], axis=1)[:, None] * path[i]
        ahead /= np.maximum(np.linalg.norm(ahead, axis=1), 1e-12)[:, None]
        left = np.cross(path[i], ahead)
        offset = p - path[i]
        across = np.sum(offset * left, axis=1) * radius  # metres, positive on the high side
        foot = path[i] + np.sum(offset * ahead, axis=1)[:, None] * ahead
        foot /= np.linalg.norm(foot, axis=1)[:, None]
        step = float(np.arccos(np.clip(path[0] @ path[min(1, last)], -1, 1))) * radius
        from_end = np.minimum(i, last - i) * step
        length = last * step
        taper = smoothstep(from_end, 0.0, length / 6)
        rise = float(height) * taper
        face = np.maximum(CLIFF_FACE * rise, 300.0)
        # Buttresses and gullies: the face line shifts with the position along it.
        groove = fbm3(foot, 9412, octaves, radius / 6e3, 0.6)
        edge = across + 0.6 * face * groove
        block = rise * smoothstep(edge, -0.5 * face, 0.5 * face) * (
            1 - smoothstep(edge, 0.5 * face, CLIFF_BACK * rise + face)
        )
        below = 1 - smoothstep(edge, -0.5 * face, 0.5 * face)
        talus = 0.12 * rise * (1 - smoothstep(-edge, 0.5 * face, 3 * face)) * below
        sink = trough[i] * taper * np.exp(-(((edge + 4 * face) / (2.5 * face)) ** 2))
        total[hit] += block + talus - sink
    out[near] = total
    return out


def tepui_group(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    rng: np.random.Generator,
    blocked: B | None = None,
) -> Tepuis:
    """A group of tepuis inland, a few of their widths apart."""
    eligible = land & (coast_m > TEPUI_COAST_M)
    if blocked is not None:
        eligible &= ~blocked
    centre = draw_site(mesh, eligible.astype(np.float64), 1.0, rng)
    if centre is None:
        return Tepuis.empty()
    tree = KDTree(mesh.xyz)
    sites: list[F64] = []
    radii: list[float] = []
    for _ in range(int(rng.integers(*TEPUI_GROUP))):
        radius = float(rng.uniform(*TEPUI_RADIUS_M))
        site = centre if not sites else destination(
            centre, rng.uniform(0, 2 * np.pi), rng.uniform(2.5, 7.0) * radius / mesh.radius_m
        )
        if not eligible[int(tree.query(site)[1])]:
            continue
        if any(float(site @ other) > np.cos(2.2 * (radius + r) / mesh.radius_m)
               for other, r in zip(sites, radii, strict=True)):
            continue
        sites.append(site)
        radii.append(radius)
    if not sites:
        return Tepuis.empty()
    heights = [tepui_height_m(r) * rng.uniform(0.85, 1.15) for r in radii]
    return Tepuis(
        np.array(sites), np.array(radii), np.array(heights),
        rng.uniform(1.0, 2.2, len(sites)), rng.uniform(0, np.pi, len(sites)),
    )


def authored_tepuis(
    mesh: SphereMesh,
    land: B,
    centres: F64,
    radii_m: F64,
    names: tuple[str, ...],
    rng: np.random.Generator,
) -> Tepuis:
    """Hand-placed tepuis at unit vectors ``centres``; each must stand on land."""
    tree = KDTree(mesh.xyz)
    for xyz, name in zip(centres, names, strict=True):
        if not land[int(tree.query(xyz)[1])]:
            raise ValueError(f"{name} lies at sea; place a tepui on land.")
    unit = centres / np.linalg.norm(centres, axis=1)[:, None]
    radii = np.asarray(radii_m, dtype=np.float64)
    return Tepuis(
        unit, radii, np.array([tepui_height_m(float(r)) for r in radii]),
        rng.uniform(1.0, 2.2, len(radii)), rng.uniform(0, np.pi, len(radii)),
    )


def tepui_relief(
    points: F64, planet_radius_m: float, tepuis: Tepuis, detail_m: float | None = None
) -> F64:
    """Height change (m) the tepuis make at unit vectors ``points``.

    An elongated plan, a nearly flat, slightly rough summit, sheer walls whose
    outline lobes into embayments and crenulates at every scale, and talus
    slopes below the walls.
    """
    radius = planet_radius_m
    out = np.zeros(len(points))
    if not len(tepuis):
        return out
    widest = float((tepuis.radius_m * np.sqrt(tepuis.aspect)).max())
    near = np.flatnonzero(
        np.isfinite(
            np.asarray(
                KDTree(tepuis.xyz).query(
                    points, distance_upper_bound=2 * np.sin(2.0 * widest / radius / 2),
                    workers=-1,
                )[0]
            )
        )
    )
    if not len(near):
        return out
    octaves = 5 if detail_m is None else int(np.clip(np.log2(widest / detail_m), 3, 11))
    total = np.zeros(len(near))
    for xyz, size, height, aspect, azimuth in zip(
        tepuis.xyz, tepuis.radius_m, tepuis.height_m, tepuis.aspect, tepuis.azimuth, strict=True
    ):
        long = size * np.sqrt(aspect)
        close = np.flatnonzero(points[near] @ xyz > np.cos(2.0 * long / radius))
        if not len(close):
            continue
        p = warp(points[near][close], 9421, 0.65 * size / radius, radius / size, octaves)
        # Distance in the tepui's own frame, stretched along its long axis.
        east = np.cross([0.0, 0.0, 1.0], xyz)
        east = east / max(float(np.linalg.norm(east)), 1e-12)
        north = np.cross(xyz, east)
        along = np.cos(azimuth) * north + np.sin(azimuth) * east
        across = np.cross(xyz, along)
        u = (p @ along) * radius / np.sqrt(aspect)
        v = (p @ across) * radius * np.sqrt(aspect)
        r = np.hypot(u, v)
        face = max(CLIFF_FACE * height, 300.0)
        edge = (size - r) / face  # in face widths, positive on the summit
        wall = smoothstep(edge, -0.5, 0.5)
        summit = 0.04 * height * fbm3(p, 9422, 3, radius / (0.3 * size))
        talus = 0.15 * height * (1 - smoothstep(-edge, 0.5, 4.0)) * (1 - wall)
        total[close] += height * wall + summit * wall + talus
    out[near] = total
    return out


def _near(points: F64, paths: tuple[F64, ...], reach: float) -> I64:
    """Indices of ``points`` within ``reach`` radians of any vertex of ``paths``."""
    found = KDTree(np.vstack(paths)).query(
        points, distance_upper_bound=2 * np.sin(reach / 2), workers=-1
    )[0]
    return np.flatnonzero(np.isfinite(np.asarray(found)))
