# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Opt-in fantastical landmarks beyond Earth's extremes (``PlanetSettings.wonders``).

The titan shield volcano lives with the other volcanoes (``planet_volcanism``).
Impact craters are young: they are cut into the eroded relief before lakes form,
so the climate decides whether a crater holds a ring lake or stays a dry basin.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
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
