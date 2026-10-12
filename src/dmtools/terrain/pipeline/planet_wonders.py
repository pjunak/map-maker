# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Opt-in fantastical landmarks beyond Earth's extremes (``PlanetSettings.wonders``).

The titan shield volcano lives with the other volcanoes (``planet_volcanism``),
and great cliffs and tepuis in ``planet_scarps``. Wonders are young: they are
cut into, or raised on, the eroded relief before lakes form, so the climate
decides whether they hold lakes or stay dry. They form one overlay (``Wonders``)
that maps redraw sharply at any scale.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from dmtools.terrain.pipeline.planet_eruptions import Eruptions, eruption_cover, lava_relief
from dmtools.terrain.pipeline.planet_mesh import SphereMesh
from dmtools.terrain.pipeline.planet_noise import fbm3
from dmtools.terrain.pipeline.planet_scarps import (
    CLIFF_BACK,
    Cliffs,
    Tepuis,
    authored_cliffs,
    authored_tepuis,
    cliff_relief,
    place_cliff,
    tepui_group,
    tepui_relief,
)
from dmtools.terrain.pipeline.wonder_geometry import (
    destination,
    draw_site,
    floor_depth,
    footprint,
    local_frame,
    path_normals,
    rift_axis,
    smoothstep,
    wall_noise,
    warp,
)

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
# A great chasm: a rift canyon like a smaller Valles Marineris (Mars: 4,000 km
# long, up to 200 km wide, 7 km deep), with stepped walls and side canyons.
CHASM_LENGTH_M = (900e3, 2200e3)
CHASM_WIDTH_M = 60e3  # rim to rim, unless placed by hand
CHASM_DEPTH_M = 3000.0  # rim to floor, limited by the ground it is cut into
CHASM_MIN_DEPTH_M = 1200.0  # mean depth along a randomly placed chasm
CHASM_FALLBACK_DEPTH_M = 300.0  # else the deepest trial, if it reaches this
# Rift shoulders: flexural uplift of the flanks (1-2 km along Earth's large
# rifts) as a share of the depth, falling away over two widths.
CHASM_SHOULDER = 0.3
CHASM_MIN_GROUND_M = 1000.0  # preferred ground for its first end
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
    blocked: B | None = None,
) -> Craters:
    """Fresh impact craters on land, wholly inland, on high ground where there is some.

    ``blocked`` nodes (other wonders) are kept clear. Land must stay above sea
    level (no below-sea-level basins yet), so each crater's depth is limited by
    the ground it is cut into.
    """
    land_area = float(mesh.area_m2[land].sum())
    count = int(np.clip(round(land_area / CRATER_LAND_PER_CRATER_M2), 1, MAX_CRATERS))
    centres: list[F64] = []
    radii: list[float] = []
    depths: list[float] = []
    taken = np.zeros(mesh.size, dtype=bool) if blocked is None else blocked.copy()
    for _ in range(count):
        radius = float(rng.uniform(*CRATER_RADIUS_M))
        ok = land & (coast_m > 2.0 * radius) & ~taken
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
        taken |= mesh.xyz @ centre > np.cos(4 * radius / mesh.radius_m)
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
    """The young fantastical landforms cut into, or raised on, the eroded relief."""

    craters: Craters
    chasms: Chasms
    cliffs: Cliffs
    tepuis: Tepuis
    eruptions: Eruptions  # of the giant active volcano, which is in the volcano list

    def __len__(self) -> int:
        return (
            len(self.craters) + len(self.chasms) + len(self.cliffs) + len(self.tepuis)
            + len(self.eruptions)
        )

    @staticmethod
    def empty() -> Wonders:
        return Wonders(
            Craters.empty(), Chasms.empty(), Cliffs.empty(), Tepuis.empty(), Eruptions.empty()
        )


@dataclass(frozen=True, slots=True)
class WonderCover:
    """What wonders lay on the land at each point, 0..1 each, for map colours."""

    lava: F64  # fresh, bare lava
    ash: F64  # an ash blanket
    glow: F64  # molten rock in an erupting vent

    def reshape(self, shape: tuple[int, ...]) -> WonderCover:
        return WonderCover(*(field.reshape(shape) for field in self.fields()))

    def crop(self, rows: slice) -> WonderCover:
        return WonderCover(*(field[rows, rows] for field in self.fields()))

    def fields(self) -> tuple[F64, F64, F64]:
        return self.lava, self.ash, self.glow


def wonder_cover(
    points: F64, planet_radius_m: float, wonders: Wonders, detail_m: float | None = None
) -> WonderCover | None:
    """The wonders' cover at unit vectors ``points``, or None where there is none."""
    if not len(wonders.eruptions):
        return None
    return WonderCover(*eruption_cover(points, planet_radius_m, wonders.eruptions, detail_m))


@dataclass(frozen=True, slots=True)
class PlacedWonder:
    """A hand-placed wonder on the sphere; ``size_m`` is what its kind's size measures."""

    kind: str
    xyz: F64
    end: F64 | None
    size_m: float
    name: str


def place_wonders(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    ground_m: F64,
    kinds: tuple[str, ...],
    placed: tuple[PlacedWonder, ...],
    blocked: B,
    seed: int,
) -> Wonders:
    """Hand-placed wonders, and random ones of ``kinds`` where none is placed by hand.

    Each kind has its own random stream, and each is kept clear of the wonders
    placed before it (and of the ``blocked`` nodes, such as a titan).
    """
    blocked = blocked.copy()

    def mine(kind: str) -> tuple[PlacedWonder, ...]:
        return tuple(p for p in placed if p.kind == kind)

    def stream(code: int) -> np.random.Generator:
        return np.random.default_rng([seed, code])

    def ends(items: tuple[PlacedWonder, ...]) -> tuple[tuple[F64, F64], ...]:
        return tuple((p.xyz, p.xyz if p.end is None else p.end) for p in items)

    craters = Craters.empty()
    if items := mine("crater"):
        craters = authored_craters(
            mesh, land, ground_m, np.array([p.xyz for p in items]),
            np.array([p.size_m / 2 for p in items]), tuple(p.name for p in items),
        )
    elif "crater" in kinds:
        craters = place_craters(mesh, land, coast_m, ground_m, stream(9090), blocked)
    blocked |= footprint(mesh, craters.xyz, 2.0 * craters.radius_m)
    chasms = Chasms.empty()
    if items := mine("chasm"):
        chasms = authored_chasms(
            mesh, land, ground_m, ends(items), np.array([p.size_m for p in items]),
            tuple(p.name for p in items), stream(9191),
        )
    elif "chasm" in kinds:
        chasms = place_chasm(mesh, land, coast_m, ground_m, stream(9191), blocked)
    for path, width in zip(chasms.paths, chasms.width_m, strict=True):
        blocked |= footprint(mesh, path[::8], np.full(len(path[::8]), 1.5 * width))
    cliffs = Cliffs.empty()
    if items := mine("cliff"):
        cliffs = authored_cliffs(
            mesh, land, ground_m, ends(items), np.array([p.size_m for p in items]),
            tuple(p.name for p in items), stream(9292),
        )
    elif "cliff" in kinds:
        cliffs = place_cliff(mesh, land, coast_m, ground_m, stream(9292), blocked)
    for path, height in zip(cliffs.paths, cliffs.height_m, strict=True):
        blocked |= footprint(mesh, path[::4], np.full(len(path[::4]), 0.5 * CLIFF_BACK * height))
    tepuis = Tepuis.empty()
    if items := mine("tepui"):
        tepuis = authored_tepuis(
            mesh, land, np.array([p.xyz for p in items]),
            np.array([p.size_m / 2 for p in items]), tuple(p.name for p in items), stream(9393),
        )
    elif "tepui" in kinds:
        tepuis = tepui_group(mesh, land, coast_m, stream(9393), blocked)
    return Wonders(craters, chasms, cliffs, tepuis, Eruptions.empty())


def wonder_relief(
    points: F64, planet_radius_m: float, wonders: Wonders, detail_m: float | None = None
) -> F64:
    """Height change (m) all wonders make at unit vectors ``points``.

    ``detail_m`` is the finest scale drawn (a map's pixel or level spacing);
    None draws the coarse shape that a planet mesh carries.
    """
    return (
        crater_relief(points, planet_radius_m, wonders.craters)
        + chasm_relief(points, planet_radius_m, wonders.chasms, detail_m)
        + cliff_relief(points, planet_radius_m, wonders.cliffs, detail_m)
        + tepui_relief(points, planet_radius_m, wonders.tepuis, detail_m)
        + lava_relief(points, planet_radius_m, wonders.eruptions, detail_m)
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
    axis = rift_axis(start, end, width_m, radius, rng)
    length = float(np.arccos(np.clip(axis[0] @ axis[-1], -1, 1))) * radius
    main_depth = floor_depth(axis, ground_m, tree, depth_m)
    paths, widths, depths = [axis], [width_m], [main_depth]

    def branch(path: F64, floor: F64, i: int, width: float, reach_m: float, hang: float) -> F64:
        point, tangent, normal = local_frame(path, i)
        heading = rng.choice((-1.0, 1.0)) * normal + rng.uniform(-1.2, 1.2) * tangent
        heading /= np.linalg.norm(heading)
        tip = np.cos(reach_m / radius) * point + np.sin(reach_m / radius) * heading
        axis = rift_axis(point, tip, width, radius, rng, wander=1.0)
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
    normals = path_normals(axis)
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
        trough = rift_axis(
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
            point, tangent, normal = local_frame(axis, k)
            shift = rng.choice((-1.0, 1.0)) * rng.uniform(0.7, 1.3) * width_m / radius
            first = point + shift * normal
            first /= np.linalg.norm(first)
            heading = outward * tangent + rng.uniform(-0.25, 0.25) * normal
            heading -= (heading @ first) * first
            heading /= np.linalg.norm(heading)
            reach = rng.uniform(0.05, 0.12) * length / radius
            tip = np.cos(reach) * first + np.sin(reach) * heading
            splay_width = width_m * rng.uniform(0.35, 0.6)
            splay = rift_axis(first, tip, splay_width, radius, rng, wander=0.5)
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
    blocked: B | None = None,
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
    if blocked is not None:
        eligible &= ~blocked
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
        axis = rift_axis(start, end, width, radius_m, rng)
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
    points = warp(points[near], seed=9311, amount=CHASM_WARP * widest / radius,
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
        right = smoothstep(np.sum(offset * across, axis=1) * radius, -0.25 * half, 0.25 * half)
        foot = path[i] + np.sum(offset * ahead, axis=1)[:, None] * ahead
        foot /= np.linalg.norm(foot, axis=1)[:, None]
        walls = partial(wall_noise, foot, across * (3 * width / radius), right)
        per = radius / width  # noise frequencies are in cycles per width
        step = float(np.arccos(np.clip(path[0] @ path[min(1, last)], -1, 1))) * radius
        from_end = np.minimum(i, last - i) * step
        # Narrows and basins along the length. Each rim wanders on its own like
        # a fractal coastline: bays where the wall has retreated, spurs
        # between them and smaller scallops on both.
        along = np.clip(1 + 0.5 * fbm3(foot, 9303, 2, radius / (8 * width)), 0.6, 1.5)
        scallop = walls(9301, 5, per / 1.5, 0.6)
        alcove = smoothstep(scallop, 0.15, 0.6)  # where the wall has retreated most
        blunt = 0.8 + 0.2 * smoothstep(from_end, 0.0, 2 * width)
        s = r / (half * along * (1 + 0.2 * scallop) * blunt)
        # A half-graben: one wall gentler and its shoulder higher, swapping along the rift.
        tilt = fbm3(foot, 9305, 1, radius / (10 * width)) * (2 * right - 1)
        lean = np.clip(0.62 + 0.13 * tilt, 0.45, 0.75)
        u = smoothstep(s, lean, 1.0)
        layers = 0.08 * smoothstep(walls(9302, 2, per / 2), -0.1, 0.4)
        layers *= float(smoothstep(np.array(width), 15e3, 45e3))
        shift = 2 * walls(9306, 1, per / 3)
        # Benches step the wall but leave the floor and the rim where they are.
        u = np.clip(u + layers * np.sin(4 * np.pi * u + shift) * 4 * u * (1 - u), 0, 1)
        floor = depth[i] * smoothstep(from_end, -width, 0.3 * width)
        # Gullies notch the shoulder just behind the rim. The shoulder fades
        # with plain distance, so it ends inside the search reach.
        notch = 0.8 * alcove * (1 - smoothstep(s, 1.0, 1.8))
        shoulder = CHASM_SHOULDER * floor * (1 + 0.6 * tilt) * (1 - notch)
        fall = 1 - smoothstep(r / (half * along), 1.0, 4.0)
        # Talus and slumps (larger below alcoves) and hummocks on the floor.
        apron = 0.12 * smoothstep(s, 0.2 * lean, lean) * (0.6 + 0.8 * alcove)
        hummocks = 0.04 * fbm3(p, 9307, 3, radius / (0.25 * width))
        height = (
            shoulder * fall
            - (floor * (1 - apron - hummocks) + shoulder * fall) * (1 - u)
        )
        low[hit] = np.minimum(low[hit], height)
        high[hit] = np.maximum(high[hit], height)
    out[near] = np.where(low < 0, low, high)
    return out


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
        weight = 1 - smoothstep(s[near], 0.85, 1.2)
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
        wall = smoothstep(s, 0.55, 0.7) * np.sin(np.pi * np.clip(s, 0, 1))
        t = np.clip(smoothstep(s, 0.62, 1.0) + slump * wall, 0, 1)
        inside = -0.7 * depth + (0.7 * depth + rim) * t
        plateau = depth * (1 - smoothstep(s, 0.1, 0.34))
        plateau *= 1 + 0.25 * fbm3(p, 9203, 3, planet_radius_m / 25e3)
        apron = rim * np.clip(s, 1, None) ** -3 * (1 - smoothstep(s, 1.8, 2.5))
        out[hit] += np.where(s < 1, inside + plateau, apron)
    return out


