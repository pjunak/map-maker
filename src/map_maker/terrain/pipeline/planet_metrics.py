"""Plausibility measurements for planet relief (comparisons, not pass/fail targets)."""

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.planet_evolution import FlowState
from map_maker.terrain.pipeline.planet_kernels import flow_length
from map_maker.terrain.pipeline.planet_mesh import SphereMesh

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]
type I64 = NDArray[np.int64]


def hypsometry(h: F64, land: B, area: F64) -> dict[str, float]:
    """Area-weighted land elevation percentiles, mean and shares above 1-4 km."""
    z, w = h[land], area[land]
    order = np.argsort(z)
    ranked = z[order]
    cdf = np.cumsum(w[order]) / w.sum()
    out = {f"p{p}": float(ranked[np.searchsorted(cdf, p / 100)]) for p in (5, 25, 50, 75, 95, 99)}
    out["max"] = float(z.max())
    out["mean"] = float(np.average(z, weights=w))
    for km in (1, 2, 3, 4):
        out[f"above_{km}km"] = float(w[z > km * 1000].sum() / w.sum())
    return out


def compass_share(mesh: SphereMesh, receiver: I64, land: B) -> float:
    """Share of flow azimuths within ±5.6° of the 8 compass directions (0.25 = unbiased)."""
    i = np.flatnonzero(land & (receiver >= 0))
    p, q = mesh.xyz[i], mesh.xyz[receiver[i]]
    east = np.cross(np.array([0.0, 0.0, 1.0]), p)
    norm = np.linalg.norm(east, axis=1, keepdims=True)
    keep = norm[:, 0] > 1e-6
    east = east[keep] / norm[keep]
    north = np.cross(p[keep], east)
    d = (q - p)[keep]
    along_east: F64 = np.einsum("ij,ij->i", d, east)
    along_north: F64 = np.einsum("ij,ij->i", d, north)
    azimuth = np.arctan2(along_east, along_north)
    return float(np.mean(np.mod(azimuth + np.pi / 32, np.pi / 4) < np.pi / 16))


def hack_exponent(flow: FlowState, water: B, min_area_m2: float) -> float:
    length = flow_length(flow.order, flow.receiver, water, flow.distance_m)
    selected = (~water) & (flow.area_m2 > min_area_m2) & (length > 0)
    if int(selected.sum()) < 10:
        return float("nan")
    slope, _ = np.polyfit(np.log(flow.area_m2[selected]), np.log(length[selected]), 1)
    return float(slope)


def non_descending_receivers(h: F64, receiver: I64, water: B) -> int:
    i = np.flatnonzero((~water) & (receiver >= 0))
    r = receiver[i]
    return int(np.sum(np.where(water[r], 0.0, h[r]) >= h[i]))


def relief_metrics(mesh: SphereMesh, h: F64, water: B, flow: FlowState) -> dict[str, object]:
    land = ~water
    return {
        "hypsometry_m": hypsometry(h, land, mesh.area_m2),
        "compass_sector_share": compass_share(mesh, flow.receiver, land),
        "hack_exponent": hack_exponent(flow, water, 20 * float(np.mean(mesh.area_m2))),
        "non_descending_receivers": non_descending_receivers(h, flow.receiver, water),
    }
