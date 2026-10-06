"""Uplift + implicit stream-power evolution of all land on the sphere mesh.

The coast is the erosion base level: water nodes are held at sea level and land
nodes stay at least ``LAND_FLOOR_M`` above it, so authored coastlines cannot move.
Closed depressions are filled every step (sediment-filled basins), so every river
reaches the sea and every receiver strictly descends.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from dmtools.terrain.pipeline.control import CancellationToken, check_cancelled
from dmtools.terrain.pipeline.planet_forcing import (
    PLATEAU_PULSE_FRACTION,
    Forcing,
    GeologyRegions,
    build_forcing,
    measure_regions,
)
from dmtools.terrain.pipeline.planet_kernels import (
    accumulate,
    priority_flood,
    steepest_receivers,
    stream_power_implicit,
)
from dmtools.terrain.pipeline.planet_mesh import SphereMesh

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]
type StepCallback = Callable[[int, int], None]

LAND_FLOOR_M = 1.0
FILL_EPS_M = 1e-3


@dataclass(frozen=True, slots=True)
class FlowState:
    filled: F64
    receiver: I64  # -1 for water nodes
    distance_m: F64  # edge length to the receiver
    order: I64  # land nodes, downstream first
    area_m2: F64  # contributing (optionally runoff-weighted) area


@dataclass(frozen=True, slots=True)
class EvolutionRun:
    elevation: F64
    flow: FlowState
    mean_change_m_per_yr: float


def route(mesh: SphereMesh, h: F64, water: B, runoff: F64 | None = None) -> FlowState:
    filled, parent = priority_flood(h, water, mesh.ptr, mesh.nbr, FILL_EPS_M)
    receiver, distance = steepest_receivers(
        filled, water, mesh.ptr, mesh.nbr, mesh.length_m, parent
    )
    land_nodes = np.flatnonzero(~water)
    order = land_nodes[np.argsort(filled[land_nodes], kind="stable")]
    source = mesh.area_m2 if runoff is None else mesh.area_m2 * runoff
    area = accumulate(order, receiver, water, np.where(water, 0.0, source))
    return FlowState(filled, receiver, distance, order, area)


def evolve(
    mesh: SphereMesh,
    water: B,
    forcing: Forcing,
    initial: F64,
    *,
    steps: int,
    step_yr: float,
    area_exponent: float,
    process_area_m2: float,
    runoff: F64 | None = None,
    cancellation: CancellationToken | None = None,
    on_step: StepCallback | None = None,
) -> EvolutionRun:
    h = np.where(water, 0.0, np.maximum(initial, LAND_FLOOR_M))
    pulse_from = round(steps * (1 - PLATEAU_PULSE_FRACTION))
    pulsed = forcing.steady_uplift + forcing.pulse_uplift
    change = 0.0
    for step in range(steps):
        check_cancelled(cancellation)
        state = route(mesh, h, water, runoff)
        before = state.filled
        h = stream_power_implicit(
            before,
            state.order,
            state.receiver,
            state.distance_m,
            water,
            state.area_m2 + process_area_m2,
            forcing.erodibility,
            area_exponent,
            forcing.steady_uplift if step < pulse_from else pulsed,
            step_yr,
        )
        h = np.where(water, 0.0, np.maximum(h, LAND_FLOOR_M))
        if step == steps - 1:
            change = float(np.mean(np.abs(h[~water] - before[~water]))) / step_yr
        if on_step is not None:
            on_step(step + 1, steps)
    state = route(mesh, h, water, runoff)
    return EvolutionRun(state.filled, state, change)


@dataclass(frozen=True, slots=True)
class RegionRecord:
    name: str
    target_m: float | None
    measured_m: float | None
    scale: float


@dataclass(frozen=True, slots=True)
class CalibratedRelief:
    run: EvolutionRun
    forcing: Forcing
    iterations: tuple[tuple[RegionRecord, ...], ...]
    scale: F64  # final uplift multiplier per geology region


def calibrated_relief(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    regions: GeologyRegions | None,
    initial: F64,
    *,
    seed: int,
    erodibility: float,
    steps: int,
    step_yr: float,
    area_exponent: float,
    process_area_m2: float,
    iterations: int,
    runoff: F64 | None = None,
    scale: F64 | None = None,
    cancellation: CancellationToken | None = None,
    on_step: StepCallback | None = None,
) -> CalibratedRelief:
    """Evolve; rescale each authored region's uplift by target/measured; repeat.

    For n = 1 stream power the steady elevation is linear in uplift, so a few
    multiplicative corrections approach soft targets while erosion keeps shaping
    every valley and divide. Without authored regions one run suffices.
    """
    water = ~land
    count = len(regions.intents) if regions is not None else 0
    scale = np.ones(count) if scale is None else scale.astype(np.float64, copy=True)
    rounds = iterations if regions is not None and any(regions.intents) else 0
    records: list[tuple[RegionRecord, ...]] = []
    total = (rounds + 1) * steps
    for iteration in range(rounds + 1):
        forcing = build_forcing(
            mesh, land, coast_m, regions, scale, seed, erodibility, steps * step_yr
        )
        offset = iteration * steps

        def report(done: int, _: int, offset: int = offset) -> None:
            if on_step is not None:
                on_step(offset + done, total)

        run = evolve(
            mesh, water, forcing, initial, steps=steps, step_yr=step_yr,
            area_exponent=area_exponent, process_area_m2=process_area_m2, runoff=runoff,
            cancellation=cancellation, on_step=report,
        )
        if regions is None:
            return CalibratedRelief(run, forcing, (), scale)
        measured = measure_regions(run.elevation, regions)
        records.append(tuple(
            RegionRecord(name, None if intent is None else intent.target_m, value, float(s))
            for name, intent, value, s in zip(
                regions.names, regions.intents, measured, scale, strict=True
            )
        ))
        if iteration == rounds:
            return CalibratedRelief(run, forcing, tuple(records), scale)
        for k, (intent, value) in enumerate(zip(regions.intents, measured, strict=True)):
            if intent is not None and value is not None and value > 0:
                scale[k] *= float(np.clip(intent.target_m / value, 0.33, 3.0))
    raise AssertionError("unreachable")
