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


def wonder_relief(points: F64, planet_radius_m: float, wonders: Wonders) -> F64:
    """Height change (m) all wonders make at unit vectors ``points``."""
    return crater_relief(points, planet_radius_m, wonders.craters) + chasm_relief(
        points, planet_radius_m, wonders.chasms
    )


def wonder_zones(points: F64, planet_radius_m: float, wonders: Wonders) -> B:
    """Where a wonder's own lakes follow its sharp relief: crater interiors, chasm floors."""
    zone = np.zeros(len(points), dtype=bool)
    for xyz, radius in zip(wonders.craters.xyz, wonders.craters.radius_m, strict=True):
        zone |= points @ xyz > np.cos(1.05 * radius / planet_radius_m)
    chasms = wonders.chasms
    for path, width in zip(chasms.paths, chasms.width_m, strict=True):
        reach = 0.85 * width / planet_radius_m  # the widest basins
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
    start: F64, end: F64, width_m: float, planet_radius_m: float, rng: np.random.Generator
) -> F64:
    """A floor axis from ``start`` to ``end`` in straight segments, like a rift.

    Rifts grow as segments offset en echelon, so the axis follows the great
    circle in straight stretches of about ``CHASM_SEGMENT_WIDTHS`` widths, each
    shifted sideways by up to a width and a bit, joined by diagonal jogs. The
    ends stay where they were put.
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
    phase = rng.uniform(0, 2 * np.pi)
    offset += 0.1 * width_m * np.sin(2 * np.pi * length / (5 * width_m) * t + phase)
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
    """A chasm up to ``depth_m`` deep with narrower, shallower side canyons.

    ``tree`` indexes the mesh nodes that ``ground_m`` belongs to.
    """
    axis = chasm_axis(start, end, width_m, planet_radius_m, rng)
    length = float(np.arccos(np.clip(axis[0] @ axis[-1], -1, 1))) * planet_radius_m
    paths, widths, depths = [axis], [width_m], [floor_depth(axis, ground_m, tree, depth_m)]
    for _ in range(int(rng.integers(*CHASM_SIDE_CANYONS))):
        i = int(rng.integers(int(0.15 * len(axis)), int(0.85 * len(axis))))
        point = axis[i]
        tangent = axis[min(i + 1, len(axis) - 1)] - axis[max(i - 1, 0)]
        tangent -= (tangent @ point) * point
        tangent /= max(float(np.linalg.norm(tangent)), 1e-12)
        normal = np.cross(point, tangent)
        heading = rng.choice((-1.0, 1.0)) * normal + rng.uniform(-0.6, 0.6) * tangent
        heading /= np.linalg.norm(heading)
        reach = rng.uniform(0.06, 0.18) * length / planet_radius_m
        tip = np.cos(reach) * point + np.sin(reach) * heading
        branch_width = width_m * rng.uniform(0.3, 0.5)
        branch = chasm_axis(point, tip, branch_width, planet_radius_m, rng)
        paths.append(branch)
        widths.append(branch_width)
        # A side canyon hangs above the main floor where it joins and grows
        # shallower towards its head.
        cap = float(depths[0][i]) * rng.uniform(0.45, 0.7)
        head = np.linspace(1.0, 0.35, len(branch))
        depths.append(floor_depth(branch, ground_m, tree, cap) * head)
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


def chasm_relief(points: F64, planet_radius_m: float, chasms: Chasms) -> F64:
    """Height change (m) the chasms make at unit vectors ``points``.

    A flat floor, steep walls stepped by resistant layers and slumped into
    spurs, uplifted shoulders that fall away from the rim, and ends that pinch
    out. The floor lies ``depth`` below the ground and the rim stands the
    shoulder above it. Inside a chasm or side canyon the deeper floor wins;
    outside, the higher shoulder.
    """
    low = np.zeros(len(points))
    high = np.zeros(len(points))
    for path, width, depth in zip(chasms.paths, chasms.width_m, chasms.depth_m, strict=True):
        half = width / 2
        reach = 6.0 * half / planet_radius_m
        found = KDTree(path).query(points, distance_upper_bound=2 * np.sin(reach / 2), workers=-1)
        distance = np.asarray(found[0], dtype=np.float64)
        index = np.asarray(found[1], dtype=np.int64)
        hit = index < len(path)
        if not hit.any():
            continue
        p = points[hit]
        r = 2 * np.arcsin(np.clip(distance[hit] / 2, 0, 1)) * planet_radius_m
        t = index[hit] / max(len(path) - 1, 1)
        floor = depth[index[hit]]
        taper = _smooth(t, 0.0, 0.1) * _smooth(1 - t, 0.0, 0.1)
        # Narrows and basins along the length, and spurs along the walls.
        along = np.clip(1 + 0.5 * fbm3(path[index[hit]], 9303, 2, planet_radius_m / (8 * width)),
                        0.6, 1.5)
        wobble = 1 + 0.15 * fbm3(p, 9301, 3, planet_radius_m / (3 * width))
        s = r / (half * along * wobble * (0.35 + 0.65 * taper))
        # Two benches where resistant layers crop out of the walls.
        u = _smooth(s, 0.6, 1.0)
        u = np.clip(u + 0.07 * np.sin(4 * np.pi * u) * (1 + fbm3(p, 9302, 2, 50.0)), 0, 1)
        shoulder = CHASM_SHOULDER * floor * taper
        height = shoulder * (1 - _smooth(s, 1.0, 4.0)) - (floor * taper + shoulder) * (1 - u)
        low[hit] = np.minimum(low[hit], height)
        high[hit] = np.maximum(high[hit], height)
    return np.where(low < 0, low, high)


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


def _smooth(x: F64, a: float, b: float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)
