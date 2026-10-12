# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Opt-in fantastical landmarks beyond Earth's extremes (``PlanetSettings.wonders``).

The titan shield volcano lives with the other volcanoes (``planet_volcanism``).
Impact craters and great chasms are young: they are cut into the eroded relief
before lakes form, so the climate decides whether they hold lakes or stay dry.
Both are one overlay (``Wonders``) that maps redraw sharply at any scale.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import gaussian_filter1d, minimum_filter1d
from scipy.spatial import KDTree

from dmtools.terrain.pipeline.planet_mesh import SphereMesh
from dmtools.terrain.pipeline.planet_noise import fbm3

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

# Rim radius range: craters 180-300 km across, beyond Earth's largest preserved
# structures (Vredefort ~250 km, Chicxulub ~180 km, both buried or eroded flat).
CRATER_RADIUS_M = (90e3, 150e3)
# Rim crest to annular-trough floor as a share of the diameter (Earth's complex
# craters are shallow: ~1-2 km for 100-200 km).
CRATER_DEPTH_RATIO = 0.009
CRATER_LAND_PER_CRATER_M2 = 4e13  # one crater per this much land (at least one)
MAX_CRATERS = 3
CRATER_MIN_GROUND_M = 700.0  # preferred ground, so the floor stays above sea level
DRAW_BATCH = 256
MAX_DRAW_BATCHES = 400
# A great chasm: a rift canyon like a smaller Valles Marineris (Mars: 4,000 km
# long, up to 200 km wide, 7 km deep), with stepped walls and side canyons.
CHASM_LENGTH_M = (900e3, 2200e3)
CHASM_WIDTH_M = 60e3  # rim to rim, unless placed by hand
CHASM_DEPTH_M = 3000.0  # rim to floor, limited by the ground it is cut into
# Land stays above sea level, so the floor stays this high: a chasm runs
# shallower through lowland and may hold a long rift lake where it is wet.
CHASM_FLOOR_M = 100.0
CHASM_MIN_DEPTH_M = 1200.0  # mean depth along a randomly placed chasm
CHASM_FALLBACK_DEPTH_M = 300.0  # else the deepest trial, if it reaches this
# Rift shoulders: flexural uplift of the flanks (1-2 km along Earth's large
# rifts) as a share of the depth, falling away over two widths.
CHASM_SHOULDER = 0.3
CHASM_MIN_GROUND_M = 1000.0  # preferred ground for its first end
CHASM_SEGMENT_WIDTHS = 6.0  # rift segments, offset en echelon, in widths
CHASM_SIDE_CANYONS = (3, 7)
CHASM_TRIBUTARIES = (0, 3)  # per side canyon, branching near its head
CHASM_SPLAYS = (1, 3)  # smaller offset troughs where each end of the rift dies out
CHASM_PARALLEL = (1, 4)  # troughs alongside part of the chasm, like Valles Marineris's chasmata
# Domain warp: points are displaced by multi-scale noise before their distance
# to the axes is measured, so every outline is irregular without a pattern.
CHASM_WARP = 0.45  # of the widest path's width, at the coarsest scale
CHASM_TRIES = 120


@dataclass(frozen=True, slots=True)
class Craters:
    xyz: F64  # (k, 3) unit vectors of the centres
    radius_m: F64  # rim radius
    depth_m: F64  # rim crest to trough floor

    def __len__(self) -> int:
        return len(self.radius_m)

    @staticmethod
    def empty() -> Craters:
        return Craters(np.zeros((0, 3)), np.zeros(0), np.zeros(0))


def place_craters(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    ground_m: F64,
    rng: np.random.Generator,
    avoid: tuple[F64, F64] | None = None,
) -> Craters:
    """Fresh impact craters on land, wholly inland, on high ground where there is some.

    ``avoid`` (centres, radii) keeps craters off other landmarks. Land must
    stay above sea level (no below-sea-level basins yet), so each crater's depth
    is limited by the ground it is cut into.
    """
    land_area = float(mesh.area_m2[land].sum())
    count = int(np.clip(round(land_area / CRATER_LAND_PER_CRATER_M2), 1, MAX_CRATERS))
    centres: list[F64] = []
    radii: list[float] = []
    depths: list[float] = []
    blocked = np.zeros(mesh.size, dtype=bool)
    if avoid is not None:
        for xyz, radius in zip(*avoid, strict=True):
            blocked |= mesh.xyz @ xyz > np.cos(1.5 * radius / mesh.radius_m)
    for _ in range(count):
        radius = float(rng.uniform(*CRATER_RADIUS_M))
        ok = land & (coast_m > 2.0 * radius) & ~blocked
        if not ok.any():
            break
        # Eligibility, not a graded preference: graded weights would follow
        # relief details that differ between mesh resolutions.
        high = ok & (ground_m >= CRATER_MIN_GROUND_M)
        centre = draw_site(mesh, (high if high.any() else ok).astype(np.float64), 1.0, rng)
        if centre is None:
            break
        site = int(np.argmax(mesh.xyz @ centre))
        depth = min(CRATER_DEPTH_RATIO * 2 * radius, max(ground_m[site] - 50.0, 0.0) / 0.7)
        if depth < 300.0:
            continue
        centres.append(centre)
        radii.append(radius)
        depths.append(depth)
        blocked |= mesh.xyz @ centre > np.cos(4 * radius / mesh.radius_m)
    if not radii:
        return Craters.empty()
    return Craters(np.array(centres), np.array(radii), np.array(depths))


def authored_craters(
    mesh: SphereMesh,
    land: B,
    ground_m: F64,
    centres: F64,
    radii_m: F64,
    names: tuple[str, ...],
) -> Craters:
    """Hand-placed craters at unit vectors ``centres``; each must lie on land.

    Depth follows the same rule as placed craters: a share of the diameter,
    limited by the ground so the floor stays above sea level.
    """
    depths = []
    for xyz, radius, name in zip(centres, radii_m, names, strict=True):
        site = int(np.argmax(mesh.xyz @ xyz))
        if not land[site]:
            raise ValueError(f"{name} lies at sea; place a crater on land.")
        depths.append(min(CRATER_DEPTH_RATIO * 2 * radius, max(ground_m[site] - 50.0, 0.0) / 0.7))
    unit = centres / np.linalg.norm(centres, axis=1)[:, None]
    return Craters(unit, np.asarray(radii_m, dtype=np.float64), np.array(depths))


@dataclass(frozen=True, slots=True)
class Chasms:
    """Great chasms and their side canyons, each a floor axis on the sphere."""

    paths: tuple[F64, ...]  # (n, 3) unit vectors along each floor axis, end to end
    width_m: F64  # rim-to-rim width of each path
    depth_m: tuple[F64, ...]  # (n,) rim-to-floor depth at each vertex of each path

    def __len__(self) -> int:
        return len(self.paths)

    @staticmethod
    def empty() -> Chasms:
        return Chasms((), np.zeros(0), ())


@dataclass(frozen=True, slots=True)
class Wonders:
    """The young fantastical landforms cut into the eroded relief."""

    craters: Craters
    chasms: Chasms

    def __len__(self) -> int:
        return len(self.craters) + len(self.chasms)

    @staticmethod
    def empty() -> Wonders:
        return Wonders(Craters.empty(), Chasms.empty())


def wonder_relief(
    points: F64, planet_radius_m: float, wonders: Wonders, detail_m: float | None = None
) -> F64:
    """Height change (m) all wonders make at unit vectors ``points``.

    ``detail_m`` is the finest scale drawn (a map's pixel or level spacing);
    None draws the coarse shape that a planet mesh carries.
    """
    return crater_relief(points, planet_radius_m, wonders.craters) + chasm_relief(
        points, planet_radius_m, wonders.chasms, detail_m
    )


def wonder_zones(points: F64, planet_radius_m: float, wonders: Wonders) -> B:
    """Where a wonder's own lakes follow its sharp relief: crater interiors, chasm floors."""
    zone = np.zeros(len(points), dtype=bool)
    for xyz, radius in zip(wonders.craters.xyz, wonders.craters.radius_m, strict=True):
        zone |= points @ xyz > np.cos(1.05 * radius / planet_radius_m)
    chasms = wonders.chasms
    for path, width in zip(chasms.paths, chasms.width_m, strict=True):
        reach = 1.0 * width / planet_radius_m  # the widest basins and alcoves
        distance = np.asarray(
            KDTree(path).query(points, distance_upper_bound=2 * np.sin(reach / 2), workers=-1)[0]
        )
        zone |= np.isfinite(distance)
    return zone


def destination(start: F64, azimuth: float, angle: float) -> F64:
    """The point ``angle`` radians from ``start`` towards ``azimuth`` (from north)."""
    east = np.cross([0.0, 0.0, 1.0], start)
    east = east / np.linalg.norm(east) if np.linalg.norm(east) > 1e-9 else np.array([0.0, 1.0, 0.0])
    north = np.cross(start, east)
    heading = np.cos(azimuth) * north + np.sin(azimuth) * east
    return np.cos(angle) * start + np.sin(angle) * heading


def chasm_axis(
    start: F64,
    end: F64,
    width_m: float,
    planet_radius_m: float,
    rng: np.random.Generator,
    wander: float = 0.3,
) -> F64:
    """A floor axis from ``start`` to ``end`` in straight segments, like a rift.

    Rifts grow as segments offset en echelon, so the axis follows the great
    circle in straight stretches of about ``CHASM_SEGMENT_WIDTHS`` widths, each
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
    segments = max(1, round(length / (CHASM_SEGMENT_WIDTHS * width_m)))
    shifts = rng.uniform(-1.2, 1.2, segments) * width_m
    edges = (np.arange(1, segments) + rng.uniform(-0.25, 0.25, segments - 1)) / segments
    jog = 0.4 / segments
    offset = np.full(len(t), shifts[0])
    for edge, step in zip(edges, np.diff(shifts), strict=True):
        offset += step * _smooth(t, edge - jog / 2, edge + jog / 2)
    walk = gaussian_filter1d(
        np.cumsum(rng.normal(size=len(t))), max(2.0, len(t) / 12), mode="nearest"
    )
    walk -= np.linspace(walk[0], walk[-1], len(t))
    offset += wander * width_m * walk / max(float(np.abs(walk).max()), 1e-9)
    offset *= np.sin(np.pi * t) ** 0.5
    axis = base + (offset / planet_radius_m)[:, None] * side
    return axis / np.linalg.norm(axis, axis=1)[:, None]


def floor_depth(path: F64, ground_m: F64, tree: KDTree, cap_m: float) -> F64:
    """Rim-to-floor depth along ``path``: up to ``cap_m``, floor above ``CHASM_FLOOR_M``.

    The deepest cut follows the lowest ground within two widths either way and
    then eases along the path, so the floor neither steps nor dips to the sea.
    Paths are sampled every eighth of a width.
    """
    nodes = np.asarray(tree.query(path, workers=-1)[1], dtype=np.int64)
    room = np.clip(ground_m[nodes] - CHASM_FLOOR_M, 0.0, cap_m)
    lowest = minimum_filter1d(room, 33, mode="nearest")
    return gaussian_filter1d(lowest, 8.0, mode="nearest")


def chasm_with_canyons(
    start: F64,
    end: F64,
    width_m: float,
    depth_m: float,
    ground_m: F64,
    tree: KDTree,
    planet_radius_m: float,
    rng: np.random.Generator,
) -> Chasms:
    """A chasm system up to ``depth_m`` deep, from ``start`` to ``end``.

    Around the main chasm (the first path):
    - side canyons hang above the floor they join and grow shallower towards
      rounded heads; some fork near the head;
    - parallel troughs run alongside part of it, merging into basins or
      leaving plateau ridges between;
    - each end dies out in smaller troughs offset en echelon.

    ``tree`` indexes the mesh nodes that ``ground_m`` belongs to.
    """
    radius = planet_radius_m
    axis = chasm_axis(start, end, width_m, radius, rng)
    length = float(np.arccos(np.clip(axis[0] @ axis[-1], -1, 1))) * radius
    main_depth = floor_depth(axis, ground_m, tree, depth_m)
    paths, widths, depths = [axis], [width_m], [main_depth]

    def frame(path: F64, i: int) -> tuple[F64, F64, F64]:
        point = path[i]
        tangent = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
        tangent = tangent - (tangent @ point) * point
        tangent = tangent / max(float(np.linalg.norm(tangent)), 1e-12)
        return point, tangent, np.cross(point, tangent)

    def branch(path: F64, floor: F64, i: int, width: float, reach_m: float, hang: float) -> F64:
        point, tangent, normal = frame(path, i)
        heading = rng.choice((-1.0, 1.0)) * normal + rng.uniform(-1.2, 1.2) * tangent
        heading /= np.linalg.norm(heading)
        tip = np.cos(reach_m / radius) * point + np.sin(reach_m / radius) * heading
        axis = chasm_axis(point, tip, width, radius, rng, wander=1.0)
        cap = float(floor[i]) * hang
        paths.append(axis)
        widths.append(width)
        depths.append(floor_depth(axis, ground_m, tree, cap) * np.linspace(1.0, 0.35, len(axis)))
        return axis

    for _ in range(int(rng.integers(*CHASM_SIDE_CANYONS))):
        i = int(rng.integers(int(0.15 * len(axis)), int(0.85 * len(axis))))
        side_width = width_m * rng.uniform(0.3, 0.5)
        reach = rng.uniform(0.06, 0.18) * length
        side = branch(axis, main_depth, i, side_width, reach, rng.uniform(0.45, 0.7))
        side_floor = depths[-1]
        for _ in range(int(rng.integers(*CHASM_TRIBUTARIES))):
            k = int(rng.integers(int(0.35 * len(side)), int(0.85 * len(side))))
            branch(
                side, side_floor, k, side_width * rng.uniform(0.5, 0.7),
                reach * rng.uniform(0.3, 0.6), rng.uniform(0.6, 0.85),
            )
    normals = _path_normals(axis)
    for _ in range(int(rng.integers(*CHASM_PARALLEL))):
        # Its own segments and bends: it may merge with the chasm into a basin
        # or stand apart behind a plateau ridge.
        span = rng.uniform(0.25, 0.6) * len(axis)
        middle = rng.uniform(0.2, 0.8) * len(axis)
        a = int(max(0, middle - span / 2))
        b = int(min(len(axis) - 1, middle + span / 2))
        side = rng.choice((-1.0, 1.0))
        ends = [
            axis[k] + side * rng.uniform(1.0, 2.0) * width_m / radius * normals[k] for k in (a, b)
        ]
        trough_width = width_m * rng.uniform(0.5, 0.85)
        trough = chasm_axis(
            ends[0] / np.linalg.norm(ends[0]), ends[1] / np.linalg.norm(ends[1]),
            trough_width, radius, rng, wander=0.8,
        )
        paths.append(trough)
        widths.append(trough_width)
        cap = float(main_depth[(a + b) // 2]) * rng.uniform(0.6, 0.9)
        depths.append(floor_depth(trough, ground_m, tree, cap))
    for end_index, outward in ((0, -1), (len(axis) - 1, 1)):
        for _ in range(int(rng.integers(*CHASM_SPLAYS))):
            k = end_index - outward * int(rng.uniform(0.02, 0.08) * len(axis))
            point, tangent, normal = frame(axis, k)
            shift = rng.choice((-1.0, 1.0)) * rng.uniform(0.7, 1.3) * width_m / radius
            first = point + shift * normal
            first /= np.linalg.norm(first)
            heading = outward * tangent + rng.uniform(-0.25, 0.25) * normal
            heading -= (heading @ first) * first
            heading /= np.linalg.norm(heading)
            reach = rng.uniform(0.05, 0.12) * length / radius
            tip = np.cos(reach) * first + np.sin(reach) * heading
            splay_width = width_m * rng.uniform(0.35, 0.6)
            splay = chasm_axis(first, tip, splay_width, radius, rng, wander=0.5)
            paths.append(splay)
            widths.append(splay_width)
            depths.append(
                floor_depth(splay, ground_m, tree, float(main_depth[k]) * rng.uniform(0.4, 0.65))
            )
    return Chasms(tuple(paths), np.array(widths), tuple(depths))


def place_chasm(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    ground_m: F64,
    rng: np.random.Generator,
    avoid: tuple[F64, F64] | None = None,
) -> Chasms:
    """One great chasm wholly on land, away from the coast and other landmarks.

    It starts on high ground where there is some. The first trial deep enough
    on average is taken, or else the deepest. Trial sites and headings come
    from continuous random draws, so builds at different mesh resolutions find
    the same chasm.
    """
    width = CHASM_WIDTH_M
    radius_m = mesh.radius_m
    eligible = land & (coast_m > 2 * width)
    if avoid is not None:
        for xyz, reach in zip(*avoid, strict=True):
            eligible &= mesh.xyz @ xyz < np.cos(1.5 * reach / radius_m)
    high = eligible & (ground_m >= CHASM_MIN_GROUND_M)
    starts = (high if high.any() else eligible).astype(np.float64)
    tree = KDTree(mesh.xyz)
    best: tuple[float, F64, F64, Mapping[str, Any]] | None = None
    for _ in range(CHASM_TRIES):
        start = draw_site(mesh, starts, 1.0, rng)
        if start is None:
            break
        azimuth = rng.uniform(0, 2 * np.pi)
        length = rng.uniform(*CHASM_LENGTH_M)
        end = destination(start, azimuth, length / radius_m)
        state = rng.bit_generator.state
        axis = chasm_axis(start, end, width, radius_m, rng)
        nodes = np.asarray(tree.query(axis, workers=-1)[1], dtype=np.int64)
        if not eligible[nodes].all():
            continue
        depth = float(floor_depth(axis, ground_m, tree, CHASM_DEPTH_M).mean())
        if best is None or depth > best[0]:
            best = (depth, start, end, state)
        if depth >= CHASM_MIN_DEPTH_M:
            break
    if best is None or best[0] < CHASM_FALLBACK_DEPTH_M:
        return Chasms.empty()
    # Rebuild from the same draws so the chosen axis carries side canyons.
    _, start, end, rng.bit_generator.state = best
    return chasm_with_canyons(start, end, width, CHASM_DEPTH_M, ground_m, tree, radius_m, rng)


def authored_chasms(
    mesh: SphereMesh,
    land: B,
    ground_m: F64,
    ends: tuple[tuple[F64, F64], ...],
    widths_m: F64,
    names: tuple[str, ...],
    rng: np.random.Generator,
) -> Chasms:
    """Hand-placed chasms between unit-vector ``ends``; both ends must lie on land."""
    paths: list[F64] = []
    widths: list[float] = []
    depths: list[F64] = []
    tree = KDTree(mesh.xyz)
    for (start, end), width, name in zip(ends, widths_m, names, strict=True):
        start_node, end_node = (int(n) for n in np.asarray(tree.query(np.stack((start, end)))[1]))
        if not (land[start_node] and land[end_node]):
            raise ValueError(f"{name} reaches the sea; place both ends of a chasm on land.")
        chasm = chasm_with_canyons(
            start, end, float(width), CHASM_DEPTH_M, ground_m, tree, mesh.radius_m, rng
        )
        paths.extend(chasm.paths)
        widths.extend(chasm.width_m.tolist())
        depths.extend(chasm.depth_m)
    return Chasms(tuple(paths), np.array(widths), tuple(depths))


def chasm_relief(
    points: F64, planet_radius_m: float, chasms: Chasms, detail_m: float | None = None
) -> F64:
    """Height change (m) the chasms make at unit vectors ``points``.

    Each wall follows its own ragged rim, a fractal of bays and spurs that run
    across the wall because the rim noise depends only on the position along
    the axis. Walls lean like a half-graben whose
    master fault swaps sides along the rift, resistant layers crop out as
    patchy benches, talus and slumps raise the floor towards the walls, and
    gullies notch the uplifted shoulders. Ends stop at rounded headwalls. The
    floor lies about ``depth`` below the ground. Inside a chasm or side canyon
    the deeper floor wins; outside, the higher shoulder. Every point is first
    displaced by a domain warp, drawn down to ``detail_m`` (or to a few
    kilometres when it is None), which makes all outlines organically irregular.
    """
    radius = planet_radius_m
    out = np.zeros(len(points))
    if not len(chasms):
        return out
    widest = float(chasms.width_m.max())
    # Only points near some path are worked on, which keeps big maps fast.
    reach = (3.0 + CHASM_WARP) * widest / radius
    near = np.flatnonzero(
        np.isfinite(
            np.asarray(
                KDTree(np.vstack(chasms.paths)).query(
                    points, distance_upper_bound=2 * np.sin(reach / 2), workers=-1
                )[0]
            )
        )
    )
    if not len(near):
        return out
    octaves = 5 if detail_m is None else int(np.clip(np.log2(widest / detail_m), 3, 11))
    points = _warp(points[near], seed=9311, amount=CHASM_WARP * widest / radius,
                   frequency=radius / widest, octaves=octaves)
    low = np.zeros(len(points))
    high = np.zeros(len(points))
    for path, width, depth in zip(chasms.paths, chasms.width_m, chasms.depth_m, strict=True):
        half = width / 2
        reach = 6.0 * half / radius
        found = KDTree(path).query(points, distance_upper_bound=2 * np.sin(reach / 2), workers=-1)
        distance = np.asarray(found[0], dtype=np.float64)
        index = np.asarray(found[1], dtype=np.int64)
        hit = index < len(path)
        if not hit.any():
            continue
        p = points[hit]
        i = index[hit]
        last = len(path) - 1
        r = 2 * np.arcsin(np.clip(distance[hit] / 2, 0, 1)) * radius
        # The local frame at the nearest vertex: along the axis and across it.
        ahead = path[np.minimum(i + 1, last)] - path[np.maximum(i - 1, 0)]
        ahead -= np.sum(ahead * path[i], axis=1)[:, None] * path[i]
        ahead /= np.maximum(np.linalg.norm(ahead, axis=1), 1e-12)[:, None]
        across = np.cross(path[i], ahead)
        offset = p - path[i]
        # Which wall a point belongs to, blended across the axis so the two
        # walls meet without a seam beyond the ends.
        right = _smooth(np.sum(offset * across, axis=1) * radius, -0.25 * half, 0.25 * half)
        foot = path[i] + np.sum(offset * ahead, axis=1)[:, None] * ahead
        foot /= np.linalg.norm(foot, axis=1)[:, None]
        walls = partial(_wall_noise, foot, across * (3 * width / radius), right)
        per = radius / width  # noise frequencies are in cycles per width
        step = float(np.arccos(np.clip(path[0] @ path[min(1, last)], -1, 1))) * radius
        from_end = np.minimum(i, last - i) * step
        # Narrows and basins along the length. Each rim wanders on its own like
        # a fractal coastline: bays where the wall has retreated, spurs
        # between them and smaller scallops on both.
        along = np.clip(1 + 0.5 * fbm3(foot, 9303, 2, radius / (8 * width)), 0.6, 1.5)
        scallop = walls(9301, 5, per / 1.5, 0.6)
        alcove = _smooth(scallop, 0.15, 0.6)  # where the wall has retreated most
        blunt = 0.8 + 0.2 * _smooth(from_end, 0.0, 2 * width)
        s = r / (half * along * (1 + 0.2 * scallop) * blunt)
        # A half-graben: one wall gentler and its shoulder higher, swapping along the rift.
        tilt = fbm3(foot, 9305, 1, radius / (10 * width)) * (2 * right - 1)
        lean = np.clip(0.62 + 0.13 * tilt, 0.45, 0.75)
        u = _smooth(s, lean, 1.0)
        layers = 0.08 * _smooth(walls(9302, 2, per / 2), -0.1, 0.4)
        layers *= float(_smooth(np.array(width), 15e3, 45e3))
        shift = 2 * walls(9306, 1, per / 3)
        # Benches step the wall but leave the floor and the rim where they are.
        u = np.clip(u + layers * np.sin(4 * np.pi * u + shift) * 4 * u * (1 - u), 0, 1)
        floor = depth[i] * _smooth(from_end, -width, 0.3 * width)
        # Gullies notch the shoulder just behind the rim. The shoulder fades
        # with plain distance, so it ends inside the search reach.
        notch = 0.8 * alcove * (1 - _smooth(s, 1.0, 1.8))
        shoulder = CHASM_SHOULDER * floor * (1 + 0.6 * tilt) * (1 - notch)
        fall = 1 - _smooth(r / (half * along), 1.0, 4.0)
        # Talus and slumps (larger below alcoves) and hummocks on the floor.
        apron = 0.12 * _smooth(s, 0.2 * lean, lean) * (0.6 + 0.8 * alcove)
        hummocks = 0.04 * fbm3(p, 9307, 3, radius / (0.25 * width))
        height = (
            shoulder * fall
            - (floor * (1 - apron - hummocks) + shoulder * fall) * (1 - u)
        )
        low[hit] = np.minimum(low[hit], height)
        high[hit] = np.maximum(high[hit], height)
    out[near] = np.where(low < 0, low, high)
    return out


def _warp(points: F64, seed: int, amount: float, frequency: float, octaves: int) -> F64:
    """Unit vectors displaced by up to about ``amount`` radians of fractal noise."""
    shift = np.stack(
        [fbm3(points, seed + k, octaves, frequency, 0.55) for k in range(3)], axis=1
    )
    shift -= np.sum(shift * points, axis=1)[:, None] * points
    moved = points + amount * shift
    return moved / np.linalg.norm(moved, axis=1)[:, None]


def _path_normals(path: F64) -> F64:
    """Unit vectors across ``path`` at each vertex, in the tangent plane."""
    ahead = np.gradient(path, axis=0)
    ahead -= np.sum(ahead * path, axis=1)[:, None] * path
    ahead /= np.maximum(np.linalg.norm(ahead, axis=1), 1e-12)[:, None]
    return np.cross(path, ahead)


def _wall_noise(
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


def level_crater_floors(mesh: SphereMesh, ground_m: F64, craters: Craters) -> F64:
    """Ground with each crater's interior levelled to its mean height.

    An impact excavates and refills its whole interior at once (melt sheet,
    breccia lens), so a crater floor is level even where the land around it
    slopes; only then can a lake ring the central plateau evenly.
    """
    out = ground_m.copy()
    for xyz, radius in zip(craters.xyz, craters.radius_m, strict=True):
        s = np.arccos(np.clip(mesh.xyz @ xyz, -1, 1)) * mesh.radius_m / radius
        near = s < 1.2
        inside = s < 1.0
        if not inside.any():  # a coarse mesh may have no node inside the rim
            inside = s <= s.min()
        mean = float(np.average(out[inside], weights=mesh.area_m2[inside]))
        weight = 1 - _smooth(s[near], 0.85, 1.2)
        out[near] = out[near] * (1 - weight) + mean * weight
    return out


def crater_relief(points: F64, planet_radius_m: float, craters: Craters) -> F64:
    """Height change (m) the craters make at unit vectors ``points``.

    A large complex crater eroded a little, like Manicouagan: a central uplift
    plateau, an annular trough, terraced walls up to a raised rim, and an
    ejecta apron falling off as (r/R)^-3. The rim and the plateau are irregular;
    where the climate fills the trough to its lowest rim notch, a ring lake
    surrounds the central plateau.
    """
    out = np.zeros(len(points))
    if not len(craters):
        return out
    reach = 2.5 * float(craters.radius_m.max()) / planet_radius_m
    tree = KDTree(craters.xyz)
    found_distance, found_index = tree.query(
        points, k=min(3, len(craters)), distance_upper_bound=2 * np.sin(reach / 2), workers=-1
    )
    distance = np.asarray(found_distance, dtype=np.float64).reshape(len(points), -1)
    index = np.asarray(found_index, dtype=np.int64).reshape(len(points), -1)
    for column in range(index.shape[1]):
        hit = index[:, column] < len(craters)
        if not hit.any():
            continue
        c = index[hit, column]
        p = points[hit]
        r = 2 * np.arcsin(np.clip(distance[hit, column] / 2, 0, 1)) * planet_radius_m
        wobble = 1 + 0.05 * fbm3(p, 9201, 3, planet_radius_m / 60e3)
        s = r / (craters.radius_m[c] * wobble)
        depth = craters.depth_m[c]
        rim = 0.3 * depth * (1 + 0.6 * fbm3(p, 9202, 3, planet_radius_m / 40e3))
        # Trough floor to rim up walls slumped into irregular blocks.
        slump = 0.08 * fbm3(p, 9204, 3, planet_radius_m / 15e3)
        wall = _smooth(s, 0.55, 0.7) * np.sin(np.pi * np.clip(s, 0, 1))
        t = np.clip(_smooth(s, 0.62, 1.0) + slump * wall, 0, 1)
        inside = -0.7 * depth + (0.7 * depth + rim) * t
        plateau = depth * (1 - _smooth(s, 0.1, 0.34))
        plateau *= 1 + 0.25 * fbm3(p, 9203, 3, planet_radius_m / 25e3)
        apron = rim * np.clip(s, 1, None) ** -3 * (1 - _smooth(s, 1.8, 2.5))
        out[hit] += np.where(s < 1, inside + plateau, apron)
    return out


def _smooth(x: F64, a: F64 | float, b: F64 | float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)
