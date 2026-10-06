# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Young depressions and climate-balanced lakes on the final planet relief.

Erosion fills closed basins with sediment during the history, so the evolved
relief has no lakes. Lakes need depressions younger than that filling:

* **Rifts and subsiding basins.** From the geology recipe (rift, sedimentary
  basin), and procedurally as broad sags in continental interiors.
* **Glacial scour.** Small depressions in cold lowlands, where present-day
  temperatures imply recent ice cover.

Water then fills each depression from its catchment runoff, as in Fill-Spill-Merge
(Barnes et al.):

* If inflow exceeds open-water evaporation over the full depression, the lake
  rises to its spill point and the surplus flows on downstream.
* Otherwise a closed (endorheic) lake shrinks until evaporation balances inflow,
  and its water never reaches the sea.
* Closing an upstream basin reduces downstream inflow, so the balance iterates.

Dry-land flow is then routed on the water surface. Every receiver on land
strictly descends, and rivers end at the sea or at a closed lake.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from dmtools.terrain.pipeline.planet_evolution import FILL_EPS_M, FlowState
from dmtools.terrain.pipeline.planet_forcing import GeologyRegions, smooth_over_land
from dmtools.terrain.pipeline.planet_kernels import (
    accumulate_nonnegative,
    priority_flood,
    steepest_receivers,
)
from dmtools.terrain.pipeline.planet_mesh import SphereMesh
from dmtools.terrain.pipeline.planet_noise import fbm3

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

RIFT_DEPTH_M = 600.0
SUBSIDING_BASIN_DEPTH_M = 160.0
INTERIOR_SAG_DEPTH_M = 220.0
GLACIAL_SCOUR_DEPTH_M = 140.0
MIN_LAKE_NODES = 2
LAKE_ITERATIONS = 6
DEFAULT_RUNOFF_MM = 250.0
DEFAULT_LAKE_EVAPORATION_MM = 1000.0


def _smoothstep(x: F64, a: float, b: float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def young_depressions(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    regions: GeologyRegions | None,
    warm_season_c: F64 | None,
    elevation_m: F64,
    seed: int,
) -> F64:
    """Depth (m, >= 0) of depressions younger than the erosion history."""
    p = mesh.xyz
    depth = np.zeros(mesh.size)
    if regions is not None:
        setting = np.zeros(mesh.size)
        for index, name in enumerate(regions.settings):
            nodes = regions.region == index
            if name == "rift":
                setting[nodes] = RIFT_DEPTH_M
            elif name == "sedimentary-basin":
                setting[nodes] = SUBSIDING_BASIN_DEPTH_M
        # Deepest in region cores; smoothing keeps margins gentle.
        depth += smooth_over_land(mesh, setting, land, 120e3) * _smoothstep(coast_m, 20e3, 120e3)
    if regions is None:
        automatic = land
    else:
        unspecified = [i for i, name in enumerate(regions.settings) if name == "unspecified"]
        automatic = land & ((regions.region < 0) | np.isin(regions.region, unspecified))
    sag = _smoothstep(fbm3(p, seed + 606, 3, 4.0), 0.25, 0.55) * _smoothstep(coast_m, 300e3, 800e3)
    depth += np.where(automatic, INTERIOR_SAG_DEPTH_M * sag, 0.0)
    if warm_season_c is not None:
        # Recently de-glaciated lowlands: cool but ice-free summers, below 1,500 m.
        lowland = 1 - _smoothstep(elevation_m, 900, 1500)
        glaciated = _smoothstep(-warm_season_c, -19.0, -14.0) * lowland
        scour = np.maximum(0.0, fbm3(p, seed + 707, 3, 32.0) - 0.1) / 0.9
        depth += GLACIAL_SCOUR_DEPTH_M * glaciated * scour
    if warm_season_c is not None:
        # Land still under ice has no open water: its depressions hold ice, not lakes.
        depth *= _smoothstep(warm_season_c, -1.0, 2.0)
    # Coastal scour would make fjords (sea), not lakes; keep depressions inland.
    return np.where(land, depth * _smoothstep(coast_m, 30e3, 100e3), 0.0)


@dataclass(frozen=True, slots=True)
class Lakes:
    """Lake state on mesh nodes (water nodes are sea, never lake)."""

    lake: I64  # lake id per node, -1 if none
    level_m: F64  # lake surface per lake id
    endorheic: B  # per lake id: closed (water never reaches the sea)
    area_m2: F64  # per lake id
    inflow_m3_yr: F64  # per lake id
    ground_m: F64  # relief including young depressions (lake beds below levels)
    surface_m: F64  # water surface on lakes, ground elsewhere
    flow: FlowState  # routed on the water surface; closed lakes are sinks
    discharge_m3_s: F64  # net river discharge (runoff minus lake evaporation)


def _components(mesh: SphereMesh, nodes: B) -> tuple[int, I64]:
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    keep = nodes[src] & nodes[mesh.nbr]
    graph = coo_matrix(
        (np.ones(int(keep.sum())), (src[keep], mesh.nbr[keep])), shape=(mesh.size, mesh.size)
    )
    count, labels = connected_components(graph, directed=False)
    labels = np.where(nodes, labels, -1).astype(np.int64)
    return count, labels


def _groups(labels: I64) -> list[I64]:
    """Node indices per non-negative label, without a per-label full scan."""
    nodes = np.flatnonzero(labels >= 0)
    if not len(nodes):
        return []
    ordered = nodes[np.argsort(labels[nodes], kind="stable")]
    cuts = np.flatnonzero(np.diff(labels[ordered])) + 1
    return np.split(ordered, cuts)


def balance_lakes(
    mesh: SphereMesh,
    land: B,
    ground_m: F64,
    runoff_mm: F64 | None,
    lake_evaporation_mm: F64 | None,
) -> Lakes:
    water = ~land
    runoff = (
        np.full(mesh.size, DEFAULT_RUNOFF_MM) if runoff_mm is None else runoff_mm
    ) / 1000.0
    evaporation = (
        np.full(mesh.size, DEFAULT_LAKE_EVAPORATION_MM)
        if lake_evaporation_mm is None
        else np.maximum(lake_evaporation_mm, 50.0)
    ) / 1000.0
    closed = np.zeros(mesh.size, dtype=bool)  # nodes of closed lakes (internal sinks)
    closed_level = np.zeros(mesh.size)
    lake = np.full(mesh.size, -1, dtype=np.int64)
    levels: list[float] = []
    for iteration in range(LAKE_ITERATIONS + 1):
        final = iteration == LAKE_ITERATIONS
        sink = water | closed
        surface = np.where(closed, closed_level, ground_m)
        exact, _ = priority_flood(surface, sink, mesh.ptr, mesh.nbr, 0.0)
        depression = land & ~closed & (exact > surface + 1e-6)
        count, labels = _components(mesh, depression)
        filled, parent = priority_flood(surface, sink, mesh.ptr, mesh.nbr, FILL_EPS_M)
        receiver, _ = steepest_receivers(
            filled, sink, mesh.ptr, mesh.nbr, mesh.length_m, parent
        )
        order = np.flatnonzero(~sink)
        order = order[np.argsort(filled[order], kind="stable")]
        source = np.where(sink, 0.0, runoff * mesh.area_m2)
        inflow = accumulate_nonnegative(order, receiver, sink, source)
        new_closed = closed.copy()
        new_level = closed_level.copy()
        lake[:] = -1
        levels = []
        # Existing closed lakes keep their level.
        _, closed_labels = _components(mesh, closed)
        for nodes in _groups(closed_labels):
            lake[nodes] = len(levels)
            levels.append(float(closed_level[nodes[0]]))
        member = np.zeros(mesh.size, dtype=bool)
        for nodes in _groups(labels):
            if len(nodes) < MIN_LAKE_NODES:
                continue
            member[nodes] = True
            exits = nodes[~member[receiver[nodes]]] if len(nodes) else nodes
            member[nodes] = False
            # Water may leave a flat-rimmed depression at several nodes; sum them all.
            total = float(inflow[exits].sum()) if len(exits) else float(inflow[nodes].max())
            spill = float(exact[nodes].max())
            ranked = nodes[np.argsort(surface[nodes], kind="stable")]
            loss = np.cumsum(mesh.area_m2[ranked] * evaporation[ranked])
            if total >= loss[-1]:
                lake[nodes] = len(levels)  # open lake: full to the spill, surplus flows on
                levels.append(spill)
                continue
            k = int(np.searchsorted(loss, total))
            if k == 0:
                continue  # a dry closed pan
            if final:
                continue  # labels only; the closed set is frozen on the last pass
            submerged = ranked[:k]
            new_closed[submerged] = True
            new_level[submerged] = float(surface[ranked[min(k, len(ranked) - 1)]])
        if final or np.array_equal(new_closed, closed):
            break
        closed, closed_level = new_closed, new_level
    # Final routing on the water surface with closed lakes as sinks.
    level_by_lake = np.array(levels, dtype=np.float64)
    on_lake = lake >= 0
    surface = (
        np.where(on_lake, level_by_lake[np.maximum(lake, 0)], ground_m) if levels else ground_m
    )
    sink = water | closed
    filled, parent = priority_flood(surface, sink, mesh.ptr, mesh.nbr, FILL_EPS_M)
    receiver, distance = steepest_receivers(filled, sink, mesh.ptr, mesh.nbr, mesh.length_m, parent)
    order = np.flatnonzero(~sink)
    order = order[np.argsort(filled[order], kind="stable")]
    net = np.where(sink, 0.0, np.where(on_lake, -evaporation, runoff) * mesh.area_m2)
    discharge = accumulate_nonnegative(order, receiver, sink, net)
    gross = accumulate_nonnegative(order, receiver, sink, np.where(sink, 0.0, mesh.area_m2))
    count = len(levels)
    endorheic = np.zeros(count, dtype=bool)
    areas = np.zeros(count)
    inflows = np.zeros(count)
    for nodes in _groups(lake):
        lake_id = int(lake[nodes[0]])
        endorheic[lake_id] = bool(closed[nodes].all())
        areas[lake_id] = float(mesh.area_m2[nodes].sum())
        inflows[lake_id] = float(discharge[nodes].max())
    flow = FlowState(filled, receiver, distance, order, gross)
    return Lakes(
        lake, level_by_lake, endorheic, areas, inflows, ground_m, filled, flow,
        discharge / (365.25 * 86400),
    )
