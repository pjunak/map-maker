# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Eruptions of the giant active volcano: lava flows, an ash blanket and a glowing vent.

Lava runs from the summit down the flanks and, for the longest flows, out onto
the plain, ending in lobed fronts (as at Etna and Kilauea). Ash falls downwind of
the vent into an elongated blanket that greys the ground and thins vegetation
(as Mount St Helens' 1980 plume did over 400 km east). Maps draw these as cover
on the land colour, and lava tongues stand a few tens of metres proud of the
ground they cover.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from dmtools.terrain.pipeline.planet_noise import fbm3
from dmtools.terrain.pipeline.wonder_geometry import destination, smoothstep, warp

type F64 = NDArray[np.float64]

FLOWS = (5, 10)  # lava flows around one vent
FLOW_WIDTH_M = (3e3, 8e3)  # near the vent; flows widen into broad toes
FLOW_THICKNESS_M = 30.0
PLUME_LENGTH = (2.5, 5.0)  # ash blanket length in volcano radii
PLUME_WIDTH = 0.7  # half-width of the blanket at its widest, in volcano radii
GLOW = 0.045  # the lava lake in the vent, as a share of the volcano's radius


@dataclass(frozen=True, slots=True)
class Eruptions:
    """Lava flows and ash blankets of active wonder volcanoes."""

    flows: tuple[F64, ...]  # (n, 3) centreline of each flow, vent first
    flow_width_m: F64
    flow_fresh: F64  # 1 for fresh black lava, less for older, weathered flows
    vent_xyz: F64  # (k, 3) erupting vents
    vent_radius_m: F64  # radius of the volcano at each vent
    plume_azimuth: F64  # downwind direction at each vent, radians from north
    plume_length_m: F64

    def __len__(self) -> int:
        return len(self.vent_radius_m)

    @staticmethod
    def empty() -> Eruptions:
        z = np.zeros(0)
        return Eruptions((), z, z, np.zeros((0, 3)), z, z, z)


def erupt(
    vents: F64,
    radii_m: F64,
    wind_east: F64,
    wind_north: F64,
    planet_radius_m: float,
    rng: np.random.Generator,
) -> Eruptions:
    """Lava flows and an ash plume for each vent, with the annual wind at each vent."""
    flows: list[F64] = []
    widths: list[float] = []
    fresh: list[float] = []
    for vent, radius in zip(vents, radii_m, strict=True):
        for _ in range(int(rng.integers(*FLOWS))):
            flow = _flow(vent, float(radius), rng.uniform(0, 2 * np.pi), planet_radius_m, rng)
            width = float(rng.uniform(*FLOW_WIDTH_M))
            age = float(rng.uniform(0.45, 1.0))
            flows.append(flow)
            widths.append(width)
            fresh.append(age)
            # Flows split where they spill over levees or around obstacles.
            for _ in range(int(rng.integers(0, 3))):
                k = int(rng.integers(len(flow) // 4, 3 * len(flow) // 4))
                heading = _heading(flow, k) + rng.choice((-1.0, 1.0)) * rng.uniform(0.15, 0.45)
                branch = _flow(
                    flow[k], float(radius) * rng.uniform(0.25, 0.6), heading, planet_radius_m,
                    rng, start=0.0,
                )
                flows.append(branch)
                widths.append(width * rng.uniform(0.5, 0.8))
                fresh.append(age)
    azimuth = np.arctan2(wind_east, wind_north)  # the way the wind blows towards
    length = radii_m * rng.uniform(*PLUME_LENGTH, len(radii_m))
    return Eruptions(
        tuple(flows), np.array(widths), np.array(fresh), np.asarray(vents, dtype=np.float64),
        np.asarray(radii_m, dtype=np.float64), azimuth, length,
    )


def _heading(path: F64, k: int) -> float:
    """Azimuth (radians from north) of ``path`` at vertex ``k``."""
    here, there = path[k], path[min(k + 1, len(path) - 1)]
    east = np.cross([0.0, 0.0, 1.0], here)
    east = east / max(float(np.linalg.norm(east)), 1e-12)
    north = np.cross(here, east)
    step = there - here
    return float(np.arctan2(step @ east, step @ north))


def _flow(
    vent: F64,
    radius_m: float,
    azimuth: float,
    planet_radius_m: float,
    rng: np.random.Generator,
    start: float = 0.08,
) -> F64:
    """A flow from ``start`` radii out, straight down the flank, bending gently; source first."""
    reach = rng.uniform(0.6, 1.7) * radius_m
    count = max(24, int(reach / 1e3))
    distance = np.linspace(start * radius_m, reach, count)
    # Flows run downslope on the cone and bend gently where they meet older flows
    # and the plain.
    turn = np.cumsum(rng.normal(0, 0.012, count)) * np.linspace(0.2, 1.0, count)
    turn -= turn[0]
    return np.stack([
        destination(vent, azimuth + float(a), float(d) / planet_radius_m)
        for a, d in zip(turn, distance, strict=True)
    ])


def eruption_cover(
    points: F64, planet_radius_m: float, eruptions: Eruptions, detail_m: float | None = None
) -> tuple[F64, F64, F64]:
    """Fresh lava, ash and vent glow (0..1 each) at unit vectors ``points``."""
    zeros = np.zeros(len(points))
    if not len(eruptions):
        return zeros, zeros.copy(), zeros.copy()
    radius = planet_radius_m
    lava = _lava(points, radius, eruptions, detail_m)
    ash = np.zeros(len(points))
    glow = np.zeros(len(points))
    for vent, size, azimuth, length in zip(
        eruptions.vent_xyz, eruptions.vent_radius_m, eruptions.plume_azimuth,
        eruptions.plume_length_m, strict=True,
    ):
        close = np.flatnonzero(points @ vent > np.cos((length + size) / radius))
        if not len(close):
            continue
        p = points[close]
        east = np.cross([0.0, 0.0, 1.0], vent)
        east = east / max(float(np.linalg.norm(east)), 1e-12)
        north = np.cross(vent, east)
        downwind = np.cos(azimuth) * north + np.sin(azimuth) * east
        crosswind = np.cross(vent, downwind)
        x = (p @ downwind) * radius  # metres downwind
        y = (p @ crosswind) * radius
        # The blanket widens downwind and thins towards its far end and edges;
        # gusts and rain-out make it patchy.
        along = np.clip(x / length, -0.15, 1.0)
        half = PLUME_WIDTH * size * (0.35 + 0.65 * np.sqrt(np.clip(along, 0, 1)))
        patchy = 0.75 + 0.25 * fbm3(p, 9501, 3, radius / (0.3 * size))
        ash[close] = np.maximum(
            ash[close],
            (1 - smoothstep(along, 0.3, 1.0)) * (1 - smoothstep(np.abs(y), 0.5 * half, half))
            * smoothstep(x, -0.2 * size, 0.1 * size) * patchy,
        )
        r = np.arccos(np.clip(p @ vent, -1, 1)) * radius
        lake = GLOW * size * (1 + 0.35 * fbm3(p, 9503, 3, radius / (GLOW * size)))
        glow[close] = np.maximum(glow[close], 1 - smoothstep(r, 0.7 * lake, lake))
    return lava, np.clip(ash, 0, 1), glow


def lava_relief(
    points: F64, planet_radius_m: float, eruptions: Eruptions, detail_m: float | None = None
) -> F64:
    """Lava tongues standing ``FLOW_THICKNESS_M`` proud, with steep lobed margins."""
    return FLOW_THICKNESS_M * _lava(points, planet_radius_m, eruptions, detail_m)


def _lava(
    points: F64, planet_radius_m: float, eruptions: Eruptions, detail_m: float | None
) -> F64:
    out = np.zeros(len(points))
    if not eruptions.flows:
        return out
    radius = planet_radius_m
    widest = float(eruptions.flow_width_m.max())
    near = np.flatnonzero(
        np.isfinite(
            np.asarray(
                KDTree(np.vstack(eruptions.flows)).query(
                    points, distance_upper_bound=2 * np.sin(2.5 * widest / radius / 2),
                    workers=-1,
                )[0]
            )
        )
    )
    if not len(near):
        return out
    octaves = 4 if detail_m is None else int(np.clip(np.log2(4 * widest / detail_m), 3, 10))
    p_all = warp(points[near], 9502, 0.3 * widest / radius, radius / (2 * widest), octaves)
    cover = np.zeros(len(near))
    for flow, width, fresh in zip(
        eruptions.flows, eruptions.flow_width_m, eruptions.flow_fresh, strict=True
    ):
        found = KDTree(flow).query(
            p_all, distance_upper_bound=2 * np.sin(2.5 * width / radius / 2), workers=-1
        )
        index = np.asarray(found[1], dtype=np.int64)
        hit = index < len(flow)
        if not hit.any():
            continue
        r = 2 * np.arcsin(np.clip(np.asarray(found[0])[hit] / 2, 0, 1)) * radius
        t = index[hit] / max(len(flow) - 1, 1)
        # Narrow near the source, widening downslope into a broad toe whose
        # margins and front break into lobes, as pahoehoe and aa flows do.
        lobes = 1 + 0.35 * fbm3(p_all[hit], 9504, octaves, radius / (0.6 * width), 0.6)
        half = 0.5 * width * (0.6 + 1.1 * t) * lobes
        front = 1 - smoothstep(t, 0.9, 1.0) * smoothstep(fbm3(p_all[hit], 9505, 3,
                                                              radius / width), -0.2, 0.3)
        cover[hit] = np.maximum(
            cover[hit], fresh * front * (1 - smoothstep(r, 0.7 * half, half))
        )
    out[near] = cover
    return out
