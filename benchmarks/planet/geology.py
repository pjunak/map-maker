# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Authored geology recipes as erosion forcing with calibrated elevation intent.

Each resolved geology region (province or continent default) becomes an uplift
history and a rock erodibility. Its landform intent, explicit or implied by its
setting, becomes a soft elevation target. For n = 1 stream power the steady
elevation is linear in uplift, so a few multiplicative corrections bring each
region near its target while erosion still shapes every valley and divide.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

import numpy as np
import shapely
from numpy.typing import NDArray

from benchmarks.planet.evolve import FlowState, History, evolve
from benchmarks.planet.fields import Tectonics, default_tectonics
from benchmarks.planet.mesh import SphereMesh
from dmtools.terrain.domain.models import LandformSettings
from dmtools.terrain.domain.world_geology import GeologyProfile, WorldGeologyRecipe
from dmtools.terrain.pipeline.world import WorldMap
from dmtools.terrain.pipeline.world_geology import GeologyCoverage, resolve_geology

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

# Landform intent implied by a setting when the profile has no explicit landform:
# (character, base elevation m, relief m, transition km).
SETTING_INTENT: dict[str, tuple[str, float, float, float]] = {
    "active-belt": ("mountains", 900.0, 3200.0, 120.0),
    "volcanic": ("mountains", 700.0, 1800.0, 80.0),
    "stable-interior": ("plain", 380.0, 180.0, 150.0),
    "rift": ("hills", 250.0, 500.0, 60.0),
    "sedimentary-basin": ("plain", 120.0, 60.0, 120.0),
}
# Relative rock erodibility by setting (soft sediments erode fastest).
SETTING_ERODIBILITY = {
    "active-belt": 1.0,
    "volcanic": 0.8,
    "stable-interior": 0.5,
    "rift": 1.4,
    "sedimentary-basin": 2.5,
    "unspecified": 1.0,
}
OROGEN_DECAY_MYR = 120.0
PLATEAU_PULSE_FRACTION = 0.2


@dataclass(frozen=True, slots=True)
class RegionIntent:
    """Soft target for one geology region; ``None`` keeps procedural forcing."""

    name: str
    character: str
    target_m: float
    statistic: str  # mean, median or p90
    transition_km: float
    erodibility: float
    age_factor: float


@dataclass(frozen=True, slots=True)
class GeologyForcing:
    region: I64  # region index per node, -1 for water or unassigned land
    intents: tuple[RegionIntent | None, ...]
    names: tuple[str, ...]


def _intent(profile: GeologyProfile, name: str) -> RegionIntent | None:
    landform: LandformSettings | None = profile.landform
    if landform is None and profile.setting not in SETTING_INTENT:
        return None
    if landform is not None:
        character, base, relief, transition = (
            landform.character, landform.elevation_m, landform.relief_m, landform.transition_km
        )
    else:
        character, base, relief, transition = SETTING_INTENT[profile.setting]
    age = profile.rejuvenation_age_ma
    age_factor = 1.0
    if age is not None and character in ("mountains", "hills"):
        # Older mountain building leaves lower, smoother residual relief.
        age_factor = max(0.12, exp(-age / OROGEN_DECAY_MYR))
    relief *= age_factor
    statistic, target = {
        "plain": ("mean", base),
        "hills": ("mean", base + 0.4 * relief),
        "plateau": ("median", base),
        "mountains": ("p90", base + 0.75 * relief),
    }[character]
    erodibility = SETTING_ERODIBILITY.get(profile.setting, 1.0)
    if profile.crust_age_ma is not None and profile.crust_age_ma > 1000:
        erodibility *= 0.7
    return RegionIntent(name, character, target, statistic, transition, erodibility, age_factor)


def assign_regions(
    world: WorldMap, coverage: GeologyCoverage, mesh: SphereMesh, land: B
) -> I64:
    frame = world.project.frame
    lon, lat = np.rad2deg(mesh.lon), np.rad2deg(mesh.lat)
    x = frame.bounds[0] + ((lon - frame.central_meridian_deg + 180) % 360) / 360 * frame.width
    y = frame.bounds[1] + (90 - lat) / 180 * frame.height
    region = np.full(mesh.size, -1, dtype=np.int64)
    for index, item in enumerate(coverage.regions):
        geometry = item.geometry
        shapely.prepare(geometry)
        inside = land & (region < 0) & shapely.contains_xy(geometry, x, y)
        region[inside] = index
    # Land nodes on region boundaries take a neighbour's region.
    missing = np.flatnonzero(land & (region < 0))
    for _ in range(4):
        if not len(missing):
            break
        for i in missing:
            for k in range(mesh.ptr[i], mesh.ptr[i + 1]):
                if region[mesh.nbr[k]] >= 0:
                    region[i] = region[mesh.nbr[k]]
                    break
        missing = np.flatnonzero(land & (region < 0))
    return region


def geology_forcing(
    world: WorldMap, recipe: WorldGeologyRecipe, mesh: SphereMesh, land: B
) -> GeologyForcing:
    coverage = resolve_geology(world, recipe)
    region = assign_regions(world, coverage, mesh, land)
    intents = tuple(_intent(r.profile, r.name) for r in coverage.regions)
    return GeologyForcing(region, intents, tuple(r.name for r in coverage.regions))


def smooth(mesh: SphereMesh, values: F64, land: B, length_m: float) -> F64:
    """Graph diffusion over land with roughly ``length_m`` spreading distance."""
    steps = max(0, round((length_m / mesh.spacing_m) ** 2))
    out = values.copy()
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    valid = land[src] & land[mesh.nbr]
    degree = np.bincount(src[valid], minlength=mesh.size).astype(np.float64)
    for _ in range(min(steps, 400)):
        total = np.bincount(src[valid], weights=out[mesh.nbr[valid]], minlength=mesh.size)
        mean = np.divide(total, degree, out=out.copy(), where=degree > 0)
        out = np.where(land, 0.5 * out + 0.5 * mean, out)
    return out


@dataclass(frozen=True, slots=True)
class ForcingParts:
    """Per-node uplift parts that calibration rescales per region."""

    steady: F64  # m/yr for the whole history
    pulse: F64  # m/yr applied only in the final pulse window
    erodibility: F64
    procedural: B


def forcing_parts(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    forcing: GeologyForcing,
    scale: F64,
    seed: int,
    base_erodibility: float,
    duration_yr: float,
) -> ForcingParts:
    procedural_tectonics = default_tectonics(
        mesh, land, coast_m, seed, erodibility=base_erodibility
    )
    steady = np.zeros(mesh.size)
    pulse = np.zeros(mesh.size)
    erodibility_factor = np.ones(mesh.size)
    transition = np.zeros(mesh.size)
    procedural = land & (forcing.region < 0)
    texture = procedural_tectonics.erodibility / base_erodibility
    pulse_years = PLATEAU_PULSE_FRACTION * duration_yr
    for index, intent in enumerate(forcing.intents):
        nodes = forcing.region == index
        if intent is None:
            procedural |= nodes
            continue
        target = max(intent.target_m, 20.0)
        if intent.character == "plateau":
            steady[nodes] = 2e-5 * scale[index]
            pulse[nodes] = target / pulse_years * scale[index]
        else:
            # First guess: steady-state relief ~ 5 km per mm/yr at reference K.
            steady[nodes] = target / 5000.0 * 1e-3 * scale[index]
        erodibility_factor[nodes] = intent.erodibility
        transition[nodes] = intent.transition_km * 1e3
    steady = np.where(procedural, procedural_tectonics.uplift, steady)
    length = float(np.median(transition[land & ~procedural])) if np.any(land & ~procedural) else 0
    steady = smooth(mesh, steady, land, length / 2)
    pulse = smooth(mesh, pulse, land, length / 2)
    erodibility_factor = smooth(mesh, erodibility_factor, land, length / 2)
    erodibility = base_erodibility * erodibility_factor * texture
    return ForcingParts(steady, pulse, erodibility, procedural)


def measure(h: F64, forcing: GeologyForcing) -> list[float | None]:
    values: list[float | None] = []
    for index, intent in enumerate(forcing.intents):
        z = h[forcing.region == index]
        if intent is None or not len(z):
            values.append(None)
            continue
        values.append(
            float({"mean": np.mean, "median": np.median}[intent.statistic](z))
            if intent.statistic != "p90"
            else float(np.percentile(z, 90))
        )
    return values


def as_tectonics(parts: ForcingParts) -> Tectonics:
    zeros = np.zeros_like(parts.steady)
    return Tectonics(parts.steady, parts.erodibility, zeros, parts.procedural.astype(np.float64))


@dataclass(frozen=True, slots=True)
class CalibratedRun:
    elevation: F64
    state: FlowState
    history: History
    parts: ForcingParts
    records: tuple[dict[str, object], ...]


def calibrated_evolution(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    forcing: GeologyForcing,
    initial: F64,
    *,
    seed: int,
    erodibility: float,
    duration_yr: float,
    dt_yr: float,
    m: float,
    process_area_m2: float,
    iterations: int,
    log: bool = True,
) -> CalibratedRun:
    """Evolve, compare each region with its target, rescale its uplift, repeat."""
    water = ~land
    scale = np.ones(len(forcing.intents))
    targets = [None if i is None else i.target_m for i in forcing.intents]
    records: list[dict[str, object]] = []
    iteration = 0
    while True:
        parts = forcing_parts(
            mesh, land, coast_m, forcing, scale, seed, erodibility, duration_yr
        )
        h, state, history = evolve(
            mesh, water, as_tectonics(parts), initial,
            duration_yr=duration_yr, dt_yr=dt_yr, m=m, process_area_m2=process_area_m2,
            pulse=parts.pulse, pulse_start_yr=duration_yr * (1 - PLATEAU_PULSE_FRACTION),
            verbose=False,
        )
        measured = measure(h, forcing)
        records.append({
            "iteration": iteration,
            "regions": [
                {"name": n, "target_m": t, "measured_m": v, "scale": float(s)}
                for n, t, v, s in zip(forcing.names, targets, measured, scale, strict=True)
            ],
        })
        if log:
            print(f"calibration {iteration}: " + ", ".join(
                f"{n[:18]} {v:.0f}/{t:.0f}"
                for n, t, v in zip(forcing.names, targets, measured, strict=True)
                if t is not None and v is not None
            ), flush=True)
        if iteration >= iterations:
            return CalibratedRun(h, state, history, parts, tuple(records))
        for k, (t, v) in enumerate(zip(targets, measured, strict=True)):
            if t is not None and v is not None and v > 0:
                scale[k] *= float(np.clip(t / v, 0.33, 3.0))
        iteration += 1
