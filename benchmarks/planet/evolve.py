# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Uplift + stream-power + hillslope evolution of all land on the sphere mesh.

The coast is the base level: water nodes stay at sea level for erosion and land
nodes stay strictly above it, so authored coastlines are invariant. Closed
depressions are filled each step (sediment-filled basins), which keeps every
river connected to the sea by construction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from benchmarks.planet.fields import Tectonics
from benchmarks.planet.kernels import (
    accumulate,
    diffuse,
    priority_flood,
    steepest_receivers,
    stream_power_implicit,
)
from benchmarks.planet.mesh import SphereMesh

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

LAND_FLOOR_M = 1.0
FILL_EPS_M = 1e-3


@dataclass(slots=True)
class FlowState:
    filled: F64
    receiver: NDArray[np.int64]
    distance: F64
    order: NDArray[np.int64]
    area: F64


@dataclass(slots=True)
class History:
    times_yr: list[float] = field(default_factory=list)
    mean_m: list[float] = field(default_factory=list)
    max_m: list[float] = field(default_factory=list)
    change_m_per_yr: list[float] = field(default_factory=list)
    seconds: float = 0.0


def route(mesh: SphereMesh, h: F64, water: B, runoff: F64 | None = None) -> FlowState:
    filled, parent = priority_flood(h, water, mesh.ptr, mesh.nbr, FILL_EPS_M)
    receiver, distance = steepest_receivers(
        filled, water, mesh.ptr, mesh.nbr, mesh.length_m, parent
    )
    land_nodes = np.flatnonzero(~water)
    order = land_nodes[np.argsort(filled[land_nodes], kind="stable")]
    source = mesh.area_m2 * (1.0 if runoff is None else runoff)
    area = accumulate(order, receiver, water, np.where(water, 0.0, source))
    return FlowState(filled, receiver, distance, order, area)


def evolve(
    mesh: SphereMesh,
    water: B,
    tectonics: Tectonics,
    initial: F64,
    *,
    duration_yr: float,
    dt_yr: float,
    m: float = 0.45,
    runoff: F64 | None = None,
    process_area_m2: float = 0.0,
    pulse: F64 | None = None,
    pulse_start_yr: float = 0.0,
    log_every: int = 20,
    verbose: bool = True,
) -> tuple[F64, FlowState, History]:
    h = np.where(water, 0.0, np.maximum(initial, LAND_FLOOR_M))
    steps = round(duration_yr / dt_yr)
    history = History()
    started = time.perf_counter()
    state = route(mesh, h, water, runoff)
    uplift = tectonics.uplift
    for step in range(steps):
        state = route(mesh, h, water, runoff)
        h = state.filled
        before = h
        h = stream_power_implicit(
            h,
            state.order,
            state.receiver,
            state.distance,
            water,
            state.area + process_area_m2,
            tectonics.erodibility,
            m,
            uplift if (pulse is None or (step + 1) * dt_yr <= pulse_start_yr) else uplift + pulse,
            dt_yr,
        )
        if np.any(tectonics.diffusivity > 0):
            h = diffuse(
                h, water, mesh.ptr, mesh.nbr, mesh.weight, mesh.area_m2,
                tectonics.diffusivity, dt_yr, 200,
            )
        h = np.where(water, 0.0, np.maximum(h, LAND_FLOOR_M))
        if step % log_every == 0 or step == steps - 1:
            land = ~water
            change = float(np.mean(np.abs(h[land] - before[land]))) / dt_yr
            history.times_yr.append((step + 1) * dt_yr)
            history.mean_m.append(float(np.mean(h[land])))
            history.max_m.append(float(np.max(h[land])))
            history.change_m_per_yr.append(change)
            if verbose:
                print(
                    f"  step {step + 1:4d}/{steps}  t={(step + 1) * dt_yr / 1e6:6.2f} Myr  "
                    f"mean={history.mean_m[-1]:7.1f} m  max={history.max_m[-1]:7.1f} m  "
                    f"|dh/dt|={change * 1e3:.4f} mm/yr  {time.perf_counter() - started:6.1f}s",
                    flush=True,
                )
    state = route(mesh, h, water, runoff)
    history.seconds = time.perf_counter() - started
    return state.filled, state, history
