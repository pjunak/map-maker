# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Plausibility metrics that give "looks like real terrain" numbers.

These compare generators and resolutions; they are measurements, not targets
that a run must hit.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from benchmarks.planet.evolve import FlowState
from benchmarks.planet.kernels import flow_length
from benchmarks.planet.mesh import SphereMesh

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]
type I64 = NDArray[np.int64]


def hypsometry(h: F64, land: B, area: F64) -> dict[str, float]:
    z, w = h[land], area[land]
    order = np.argsort(z)
    cdf = np.cumsum(w[order]) / w.sum()
    ranked = z[order]
    out = {f"p{p}": float(ranked[np.searchsorted(cdf, p / 100)]) for p in (5, 25, 50, 75, 95, 99)}
    out["max"] = float(z.max())
    out["mean"] = float(np.average(z, weights=w))
    for km in (1, 2, 3, 4):
        out[f"above_{km}km"] = float(w[z > km * 1000].sum() / w.sum())
    return out


def direction_isotropy(
    mesh: SphereMesh, receiver: I64, land: B, bins: int = 32
) -> dict[str, float]:
    """Histogram of flow azimuths in the local tangent frame.

    A D8 raster concentrates flow in 8 azimuths; an unbiased mesh is flat.
    Reports max/min bin ratio and the share in the 8 compass +-5.6 deg sectors.
    """
    i = np.flatnonzero(land & (receiver >= 0))
    p, q = mesh.xyz[i], mesh.xyz[receiver[i]]
    up = np.array([0.0, 0.0, 1.0])
    east = np.cross(up, p)
    norm = np.linalg.norm(east, axis=1, keepdims=True)
    keep = norm[:, 0] > 1e-6
    east = east[keep] / norm[keep]
    north = np.cross(p[keep], east)
    d = (q - p)[keep]
    azimuth = np.arctan2(np.einsum("ij,ij->i", d, east), np.einsum("ij,ij->i", d, north))
    hist, _ = np.histogram(azimuth, bins=bins, range=(-np.pi, np.pi))
    compass = np.mod(azimuth + np.pi / 8 / 2, np.pi / 4) < np.pi / 32 * 2
    return {
        "max_min_bin_ratio": float(hist.max() / max(hist.min(), 1)),
        "compass_sector_share": float(compass.mean()),  # 0.25 when isotropic
    }


def hack_exponent(state: FlowState, water: B, min_cells: float, cell_m2: float) -> float:
    length: F64 = flow_length(state.order, state.receiver, water, state.distance)
    area_m2 = state.area
    sel = (~water) & (area_m2 > min_cells * cell_m2) & (length > 0)
    if sel.sum() < 10:
        return float("nan")
    slope, _ = np.polyfit(np.log(area_m2[sel]), np.log(length[sel]), 1)
    return float(slope)


def uphill_edges(h: F64, receiver: I64, water: B) -> int:
    i = np.flatnonzero((~water) & (receiver >= 0))
    r = receiver[i]
    hr = np.where(water[r], 0.0, h[r])
    return int(np.sum(hr >= h[i]))


def summarize(mesh: SphereMesh, h: F64, water: B, state: FlowState) -> dict[str, object]:
    land = ~water
    return {
        "hypsometry_m": hypsometry(h, land, mesh.area_m2),
        "isotropy": direction_isotropy(mesh, state.receiver, land),
        "hack_exponent": hack_exponent(state, water, 20, float(np.mean(mesh.area_m2))),
        "uphill_receiver_edges": uphill_edges(h, state.receiver, water),
    }
