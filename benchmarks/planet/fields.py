# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""World inputs sampled on the sphere mesh: land, coast distance, tectonic forcing."""

from __future__ import annotations

from dataclasses import dataclass
from math import pi

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import Polygon
from shapely.ops import unary_union

from benchmarks.planet.kernels import multi_source_distance
from benchmarks.planet.mesh import SphereMesh
from benchmarks.planet.synthetic_world import fbm3
from dmtools.terrain.pipeline.world import WorldMap

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]


def land_on_mesh(world: WorldMap, mesh: SphereMesh) -> B:
    frame = world.project.frame
    polygons = [
        Polygon(c.exterior, c.holes) for view in world.land for c in view.components
    ]
    land = unary_union(polygons)
    shapely.prepare(land)
    lon = np.rad2deg(mesh.lon)
    lat = np.rad2deg(mesh.lat)
    offset = (lon - frame.central_meridian_deg + 180) % 360
    x = frame.bounds[0] + offset / 360 * frame.width
    y = frame.bounds[1] + (90 - lat) / 180 * frame.height
    return shapely.contains_xy(land, x, y)


def coast_distance(mesh: SphereMesh, land: B) -> F64:
    """Graph distance (m) to the nearest land/water edge midpoint, for all nodes."""
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    crossing = land[src] != land[mesh.nbr]
    seeds = src[crossing]
    seed_distance = mesh.length_m[crossing] / 2
    return multi_source_distance(seeds, seed_distance, mesh.ptr, mesh.nbr, mesh.length_m)


@dataclass(frozen=True, slots=True)
class Tectonics:
    """Prescribed forcing for one erosion history (SI units: m/yr, m, 1/yr)."""

    uplift: F64
    erodibility: F64
    diffusivity: F64
    belts: F64  # 0..1 orogen intensity, for inspection


def _smoothstep(x: F64, a: float, b: float) -> F64:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def default_tectonics(
    mesh: SphereMesh,
    land: B,
    coast_m: F64,
    seed: int,
    *,
    craton_uplift: float = 2e-5,
    belt_uplift: float = 1.2e-3,
    margin_uplift: float = 6e-4,
    erodibility: float = 2e-6,
    diffusivity: float = 0.0,
) -> Tectonics:
    """Procedural forcing when no geology recipe exists.

    Orogenic belts are narrow ridged-noise bands; active margins are noise-gated
    coastal strips. Rock erodibility varies by a factor of about 3.
    """
    p = mesh.xyz
    warp = np.stack([fbm3(p, seed + 300 + k, 3, 1.3) for k in range(3)], axis=1)
    q = p + 0.35 * warp
    ridged = 1 - np.abs(fbm3(q, seed + 101, 4, 1.4, 0.5))
    belts = _smoothstep(ridged, 0.80, 0.97)
    # Fade belts within ~100 km of the coast so they do not stand in the sea.
    inland = _smoothstep(coast_m, 0.0, 150e3)
    gate = _smoothstep(fbm3(p, seed + 202, 3, 1.1), 0.05, 0.35)
    margin_band = _smoothstep(coast_m, 30e3, 120e3) * (1 - _smoothstep(coast_m, 250e3, 500e3))
    margins = gate * margin_band
    interior = _smoothstep(coast_m, 0.0, 600e3)
    uplift = (
        craton_uplift * (1 + 2 * interior)
        + belt_uplift * belts * inland
        + margin_uplift * margins
    )
    uplift = np.where(land, uplift, 0.0)
    lithology = fbm3(p, seed + 404, 5, 3.0)
    k = erodibility * np.exp(1.1 * lithology)
    d = np.full(mesh.size, diffusivity)
    return Tectonics(uplift, k, d, np.maximum(belts * inland, margins) * land)


def ocean_floor(coast_m: F64, water: B, mesh: SphereMesh, seed: int) -> F64:
    """Shelf/slope/abyss profile on coast distance with mild abyssal relief (m, negative)."""
    shelf = _smoothstep(coast_m, 0, 120e3)
    slope = _smoothstep(coast_m, 120e3, 450e3)
    depth = 150 * shelf + 3800 * slope
    hills = fbm3(mesh.xyz, seed + 909, 6, 6.0)
    ridge = 1 - np.abs(fbm3(mesh.xyz, seed + 808, 3, 1.0))
    depth -= slope * (900 * _smoothstep(ridge, 0.75, 0.98) - 250 * hills)
    return np.where(water, -depth, 0.0)


def latitude_deg(mesh: SphereMesh) -> F64:
    return np.rad2deg(mesh.lat)


def km(value_m: F64) -> F64:
    return value_m / 1000


__all__ = ["Tectonics", "coast_distance", "default_tectonics", "land_on_mesh", "ocean_floor", "pi"]
