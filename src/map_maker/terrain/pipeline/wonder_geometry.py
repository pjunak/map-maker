# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Geometry shared by the wonders: sites, rift axes, floor depths and noise.

Random sites come from continuous draws on the sphere, so builds at different
mesh resolutions find the same wonders.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import gaussian_filter1d, minimum_filter1d
from scipy.spatial import KDTree

from map_maker.terrain.pipeline.planet_mesh import SphereMesh
from map_maker.terrain.pipeline.planet_noise import fbm3

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

DRAW_BATCH = 256
MAX_DRAW_BATCHES = 400
SEGMENT_WIDTHS = 6.0  # rift segments, offset en echelon, in widths
# Land stays above sea level, so cut floors stay this high: a wonder runs
# shallower through lowland and may hold a lake where it is wet.
FLOOR_M = 100.0


def footprint(mesh: SphereMesh, xyz: F64, reach_m: F64) -> B:
    """Mesh nodes within ``reach_m`` of any of the unit vectors ``xyz``."""
    out = np.zeros(mesh.size, dtype=bool)
    if not len(xyz):
        return out
    tree = KDTree(mesh.xyz)
    for point, reach in zip(xyz, reach_m, strict=True):
        angle = float(reach) / mesh.radius_m
        out[tree.query_ball_point(point, 2 * np.sin(angle / 2))] = True
    return out


def local_frame(path: F64, i: int) -> tuple[F64, F64, F64]:
    """A vertex of ``path``, the unit tangent there and the unit normal to its left."""
    point = path[i]
    tangent = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
    tangent = tangent - (tangent @ point) * point
    tangent = tangent / max(float(np.linalg.norm(tangent)), 1e-12)
    return point, tangent, np.cross(point, tangent)


def draw_site(
    mesh: SphereMesh, weight: F64, ceiling: float, rng: np.random.Generator
) -> F64 | None:
    """A point on the sphere drawn in proportion to ``weight`` at its nearest node.

    Rejection sampling of continuous positions with a fixed ``ceiling`` (the
    largest possible weight) uses the same random draws at any mesh resolution,
    so a quick preview and the final build place landmarks in the same spots.
    """
    if not (weight > 0).any():
        return None
    tree = KDTree(mesh.xyz)
    for _ in range(MAX_DRAW_BATCHES):
        trial = rng.normal(size=(DRAW_BATCH, 3))
        trial /= np.linalg.norm(trial, axis=1)[:, None]
        node = np.asarray(tree.query(trial, workers=-1)[1], dtype=np.int64)
        accept = rng.random(DRAW_BATCH) * ceiling < weight[node]
        if accept.any():
            return trial[int(np.argmax(accept))]
    return None


def destination(start: F64, azimuth: float, angle: float) -> F64:
    """The point ``angle`` radians from ``start`` towards ``azimuth`` (from north)."""
    east = np.cross([0.0, 0.0, 1.0], start)
    east = east / np.linalg.norm(east) if np.linalg.norm(east) > 1e-9 else np.array([0.0, 1.0, 0.0])
    north = np.cross(start, east)
    heading = np.cos(azimuth) * north + np.sin(azimuth) * east
    return np.cos(angle) * start + np.sin(angle) * heading


def rift_axis(
    start: F64,
    end: F64,
    width_m: float,
    planet_radius_m: float,
    rng: np.random.Generator,
    wander: float = 0.3,
) -> F64:
    """A floor axis from ``start`` to ``end`` in straight segments, like a rift.

    Rifts grow as segments offset en echelon, so the axis follows the great
    circle in straight stretches of about ``SEGMENT_WIDTHS`` widths, each
    shifted sideways by up to a width and a bit, joined by diagonal jogs. A
    smoothed random walk of ``wander`` widths keeps stretches from repeating.
    The ends stay where they were put.
    """
    a, b = start / np.linalg.norm(start), end / np.linalg.norm(end)
    angle = float(np.arccos(np.clip(a @ b, -1, 1)))
    length = angle * planet_radius_m
    count = max(16, int(np.ceil(length / (width_m / 8))))
    t = np.linspace(0.0, 1.0, count)
    base = (np.sin((1 - t) * angle)[:, None] * a + np.sin(t * angle)[:, None] * b) / max(
        np.sin(angle), 1e-12
    )
    side = np.cross(a, b)
    side = side / max(float(np.linalg.norm(side)), 1e-12)
    segments = max(1, round(length / (SEGMENT_WIDTHS * width_m)))
    shifts = rng.uniform(-1.2, 1.2, segments) * width_m
    edges = (np.arange(1, segments) + rng.uniform(-0.25, 0.25, segments - 1)) / segments
    jog = 0.4 / segments
    offset = np.full(len(t), shifts[0])
    for edge, step in zip(edges, np.diff(shifts), strict=True):
        offset += step * smoothstep(t, edge - jog / 2, edge + jog / 2)
    walk = gaussian_filter1d(
        np.cumsum(rng.normal(size=len(t))), max(2.0, len(t) / 12), mode="nearest"
    )
    walk -= np.linspace(walk[0], walk[-1], len(t))
    offset += wander * width_m * walk / max(float(np.abs(walk).max()), 1e-9)
    offset *= np.sin(np.pi * t) ** 0.5
    axis = base + (offset / planet_radius_m)[:, None] * side
    return axis / np.linalg.norm(axis, axis=1)[:, None]


def floor_depth(path: F64, ground_m: F64, tree: KDTree, cap_m: float) -> F64:
    """Rim-to-floor depth along ``path``: up to ``cap_m``, floor above ``FLOOR_M``.

    The deepest cut follows the lowest ground within two widths either way and
    then eases along the path, so the floor neither steps nor dips to the sea.
    Paths are sampled every eighth of a width.
    """
    nodes = np.asarray(tree.query(path, workers=-1)[1], dtype=np.int64)
    room = np.clip(ground_m[nodes] - FLOOR_M, 0.0, cap_m)
    lowest = minimum_filter1d(room, 33, mode="nearest")
    return gaussian_filter1d(lowest, 8.0, mode="nearest")


def warp(points: F64, seed: int, amount: float, frequency: float, octaves: int) -> F64:
    """Unit vectors displaced by up to about ``amount`` radians of fractal noise."""
    shift = np.stack(
        [fbm3(points, seed + k, octaves, frequency, 0.55) for k in range(3)], axis=1
    )
    shift -= np.sum(shift * points, axis=1)[:, None] * points
    moved = points + amount * shift
    return moved / np.linalg.norm(moved, axis=1)[:, None]


def path_normals(path: F64) -> F64:
    """Unit vectors across ``path`` at each vertex, in the tangent plane."""
    ahead = np.gradient(path, axis=0)
    ahead -= np.sum(ahead * path, axis=1)[:, None] * path
    ahead /= np.maximum(np.linalg.norm(ahead, axis=1), 1e-12)[:, None]
    return np.cross(path, ahead)


def wall_noise(
    foot: F64,
    apart: F64,
    right: F64,
    seed: int,
    octaves: int,
    frequency: float,
    gain: float = 0.5,
) -> F64:
    """Noise along each wall: a function of the position along the axis and the wall.

    It is sampled ``apart`` to either side of the axis foot point, so the two
    walls vary independently, and blended by ``right`` (0 left, 1 right).
    """
    left_noise = fbm3(foot - apart, seed, octaves, frequency, gain)
    right_noise = fbm3(foot + apart, seed, octaves, frequency, gain)
    return right * right_noise + (1 - right) * left_noise


def smoothstep(x: F64, a: F64 | float, b: F64 | float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)
