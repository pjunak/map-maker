# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Aging: erode each wonder for its age on its own fixed patch of mesh (ADR-0091).

Wonders are drawn fresh, as if they formed just now. Aging gives one a history:
the wonder and the ground around it are eroded on a patch of mesh fixed to the
wonder, with a share of the planet's erodibility, its runoff and no uplift.
Rivers cut gullies into its walls and carry them back, and creep rounds its
rims. Hollows fill with sediment only gradually: the erosion model fills every
closed hollow to its spill level at once, so only a growing share of that fill
is kept (half after about 35 Myr). The change from the fresh shape is stored
with the build; every map adds it to the fresh shape it draws, so all scales
agree.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from map_maker.terrain.pipeline.control import CancellationToken
from map_maker.terrain.pipeline.planet_evolution import evolve
from map_maker.terrain.pipeline.planet_forcing import Forcing
from map_maker.terrain.pipeline.planet_mesh import SphereMesh
from map_maker.terrain.pipeline.planet_patch import regional_mesh

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

AGING_NODES = 120_000  # at most about this many patch nodes
AGING_MIN_SPACING_M = 1000.0
AGING_STEP_MYR = 0.1
AGING_STEPS = (10, 100)
# Creep at map scale: an effective diffusivity that rounds rims over a few
# kilometres in tens of millions of years (sqrt(0.5 m^2/yr x 30 Myr) ~ 4 km).
# Soil creep alone is ~0.01 m^2/yr; landslides act faster on steep walls.
AGING_DIFFUSIVITY_M2_YR = 0.5
AGING_RATE = 0.25  # share of the planet's erodibility; it was tuned against uplift
INFILL_MYR = 50.0  # hollows keep 1 - exp(-age / INFILL_MYR) of their fill
MAX_AGE_MYR = 500.0


@dataclass(frozen=True, slots=True)
class AgedPatch:
    """An aged wonder: its eroded relief on its patch's nodes, and which wonder it is."""

    xyz: F64  # (n, 3) unit vectors of the patch nodes
    relief_m: F64  # the aged wonder's height change over the ground, at each node
    spacing_m: float
    age_myr: float
    centre: F64  # unit vector at the patch centre
    reach_m: float  # patch radius
    kind: str  # the wonder's catalog kind
    members: tuple[int, ...]  # its entries (craters, tepuis) or paths (chasms, cliffs)


@dataclass(frozen=True, slots=True)
class Aging:
    patches: tuple[AgedPatch, ...]

    def __len__(self) -> int:
        return len(self.patches)

    @staticmethod
    def empty() -> Aging:
        return Aging(())


@dataclass(frozen=True)
class AgingSetup:
    """What aging needs from the planet: its default age, ground, erodibility and runoff."""

    default_age_myr: float
    ground: Callable[[F64], F64]
    erodibility: Callable[[F64], F64]
    runoff: Callable[[F64], F64] | None
    area_exponent: float
    seed: int
    cancellation: CancellationToken | None = None

    def patch(
        self,
        centre: F64,
        reach_m: float,
        planet_radius_m: float,
        relief: Callable[[F64, float], F64],
        age_myr: float,
        index: int,
        kind: str,
        members: tuple[int, ...],
        resistance: float = 1.0,
    ) -> AgedPatch:
        """``resistance`` divides the erodibility: caprock and hard layers wear slowly."""

        def erodibility(points: F64) -> F64:
            return self.erodibility(points) / resistance

        return age_wonder(
            centre, reach_m, planet_radius_m, relief, self.ground, erodibility, self.runoff,
            age_myr=age_myr, area_exponent=self.area_exponent, seed=self.seed + 97 * index,
            kind=kind, members=members, cancellation=self.cancellation,
        )


def patch_spacing_m(reach_m: float) -> float:
    """Node spacing that keeps a patch of radius ``reach_m`` near ``AGING_NODES`` nodes."""
    per_node = float(np.sqrt(2 * np.pi / (np.sqrt(3) * AGING_NODES)))
    return max(AGING_MIN_SPACING_M, reach_m * per_node)


def age_wonder(
    centre: F64,
    reach_m: float,
    planet_radius_m: float,
    relief: Callable[[F64, float], F64],
    ground: Callable[[F64], F64],
    erodibility: Callable[[F64], F64],
    runoff: Callable[[F64], F64] | None,
    *,
    age_myr: float,
    area_exponent: float,
    seed: int,
    kind: str = "",
    members: tuple[int, ...] = (),
    cancellation: CancellationToken | None = None,
) -> AgedPatch:
    """Erode one wonder for ``age_myr`` on a patch of radius ``reach_m`` around ``centre``.

    ``relief`` gives the fresh wonder's height change at unit vectors drawn
    down to a spacing, ``ground`` the eroded land it stands on, ``erodibility``
    and ``runoff`` the planet's at those points.
    """
    spacing = patch_spacing_m(reach_m)
    lon = float(np.degrees(np.arctan2(centre[1], centre[0])))
    lat = float(np.degrees(np.arcsin(np.clip(centre[2], -1, 1))))
    region = regional_mesh(lon, lat, reach_m / 1e3, spacing / 1e3, planet_radius_m, seed)
    mesh = region.mesh
    fresh = relief(mesh.xyz, spacing)
    start = np.maximum(ground(mesh.xyz), 1.0) + fresh
    fixed = region.boundary
    zeros = np.zeros(mesh.size)
    forcing = Forcing(
        zeros, zeros, AGING_RATE * erodibility(mesh.xyz), np.zeros(mesh.size, dtype=bool)
    )
    steps = int(np.clip(round(age_myr / AGING_STEP_MYR), *AGING_STEPS))
    run = evolve(
        mesh, fixed, forcing, start, steps=steps, step_yr=age_myr * 1e6 / steps,
        area_exponent=area_exponent, process_area_m2=(2 * spacing) ** 2,
        runoff=None if runoff is None else runoff(mesh.xyz), fixed_level=start,
        cancellation=cancellation,
    )
    change = run.elevation - start
    change = np.where(change > 0, (1 - np.exp(-age_myr / INFILL_MYR)) * change, change)
    aged = creep(mesh, start + change, fixed, AGING_DIFFUSIVITY_M2_YR * age_myr * 1e6)
    change = np.where(fixed, 0.0, aged - start)
    return AgedPatch(mesh.xyz, fresh + change, spacing, age_myr, centre, reach_m, kind, members)


def creep(mesh: SphereMesh, h: F64, fixed: B, diffusion_m2: float) -> F64:
    """Linear hillslope diffusion of ``diffusion_m2`` (diffusivity x time); fixed nodes hold."""
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    total_weight = np.bincount(src, mesh.weight, mesh.size)
    worst = float((total_weight / mesh.area_m2)[~fixed].max(initial=0.0))
    if worst <= 0 or diffusion_m2 <= 0:
        return h.copy()
    steps = int(np.ceil(diffusion_m2 * worst / 0.45))  # stable explicit substeps
    step = diffusion_m2 / steps
    out = h.copy()
    for _ in range(steps):
        flux = mesh.weight * (out[mesh.nbr] - out[src])
        out = np.where(fixed, out, out + step * np.bincount(src, flux, mesh.size) / mesh.area_m2)
    return out


def patch_weight(points: F64, planet_radius_m: float, patch: AgedPatch) -> F64:
    """How fully the aged surface replaces the fresh one: 1 inside, fading at the rim."""
    distance = np.arccos(np.clip(points @ patch.centre, -1, 1)) * planet_radius_m
    t = np.clip((distance / patch.reach_m - 0.8) / 0.18, 0, 1)
    return 1 - t * t * (3 - 2 * t)


def aged_relief(points: F64, patch: AgedPatch, planet_radius_m: float) -> F64:
    """The aged wonder's relief at unit vectors ``points``, smoothly interpolated.

    A Gaussian kernel over a dozen nearest nodes: weights fade smoothly, so the
    surface has no seams where the nearest nodes change (inverse-distance
    weighting of three nodes drew straight lines in hillshade).
    """
    sigma = 0.8 * patch.spacing_m / planet_radius_m  # radians
    found = KDTree(patch.xyz).query(
        points, k=12, distance_upper_bound=2 * np.sin(1.5 * sigma), workers=-1
    )
    distance = np.asarray(found[0], dtype=np.float64).reshape(len(points), -1)
    index = np.asarray(found[1], dtype=np.int64).reshape(len(points), -1)
    valid = index < len(patch.xyz)
    weight = np.where(valid, np.exp(-0.5 * (np.where(valid, distance, 0.0) / sigma) ** 2), 0.0)
    total = np.maximum(weight.sum(axis=1), 1e-30)
    values = patch.relief_m[np.where(valid, index, 0)]
    return (weight * values).sum(axis=1) / total
