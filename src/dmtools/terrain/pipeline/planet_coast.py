# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Coastline detail below the drawing's precision for regional levels (ADR-0090).

The authored coast is exact at planet scale. Zoomed in, its traced corners and
smooth curves show far below the precision it was drawn at, so regional levels
see a refined coast:

* **Smoothing.** Each ring is smoothed along its length over a fraction of one
  drawing unit, so tracing corners do not survive into every zoom.
* **Detail.** Points are displaced by a sum of rotated noise octaves before the
  inside test (a domain warp). Each octave's amplitude follows a power law of
  its wavelength, capped at a fixed share of it, so the coast looks rugged at
  every scale. Displacement stays within about one drawing unit.
* **Nesting.** A level includes every octave down to a finest wavelength. Finer
  levels only add octaves, so each level refines the coast of the level above,
  and the result depends only on the position, the world and the seed.
"""

from dataclasses import dataclass
from functools import lru_cache
from math import pi

import numpy as np
import shapely
from numpy.typing import NDArray
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from dmtools.terrain.domain.seeds import stage_seed
from dmtools.terrain.pipeline.planet_forcing import source_xy
from dmtools.terrain.pipeline.planet_noise import value_noise3
from dmtools.terrain.pipeline.world import WorldMap

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

COAST_STAGE = "planet.coast"
# Lengths in drawing units (one unit of the world SVG frame at the equator).
SMOOTHING_UNITS = 0.3
TOP_WAVELENGTH_UNITS = 8.0
TOP_AMPLITUDE_UNITS = 0.6
# Amplitude ~ wavelength^HURST, capped at STEEPNESS x wavelength: below about one
# drawing unit the coast is self-similar instead of ever rougher.
HURST = 0.4
STEEPNESS = 0.25


def level_finest_m(spacing_m: float) -> float:
    """Finest coast wavelength a level's mesh resolves: twice its node spacing."""
    return 2.0 * spacing_m


def window_finest_m(spacing_m: float, pixel_m: float) -> float:
    """A window draws coast detail down to three pixels, and never less than its level."""
    return min(3.0 * pixel_m, level_finest_m(spacing_m))


def _smooth_ring(ring: tuple[tuple[float, float], ...], sigma: float) -> F64:
    xy = np.asarray(ring, dtype=np.float64)
    if not np.array_equal(xy[0], xy[-1]):
        xy = np.vstack([xy, xy[:1]])
    lengths = np.hypot(*np.diff(xy, axis=0).T)
    perimeter = float(lengths.sum())
    if perimeter < 8 * sigma:
        return xy  # islets keep their drawn shape
    count = int(np.ceil(perimeter / (sigma / 4)))
    along = np.concatenate([[0.0], np.cumsum(lengths)])
    t = np.arange(count) * perimeter / count
    even = np.stack([np.interp(t, along, xy[:, 0]), np.interp(t, along, xy[:, 1])], axis=1)
    return gaussian_filter1d(even, sigma * count / perimeter, axis=0, mode="wrap")


def _rotation(seed: int) -> F64:
    a, b, c, d = (q := np.random.default_rng(seed).normal(size=4)) / np.linalg.norm(q)
    return np.array([
        [a * a + b * b - c * c - d * d, 2 * (b * c - a * d), 2 * (b * d + a * c)],
        [2 * (b * c + a * d), a * a - b * b + c * c - d * d, 2 * (c * d - a * b)],
        [2 * (b * d - a * c), 2 * (c * d + a * b), a * a - b * b - c * c + d * d],
    ])


def noise_octaves(top_m: float, amplitude_m: float, finest_m: float) -> list[tuple[float, float]]:
    """(wavelength, amplitude) in metres, coarsest first, from ``top_m`` down to ``finest_m``.

    Amplitude follows a power law of wavelength from ``amplitude_m`` at the top,
    capped at STEEPNESS x wavelength. Octaves depend only on the top, so a finer
    ``finest_m`` only adds octaves.
    """
    out: list[tuple[float, float]] = []
    wavelength = top_m
    while wavelength >= finest_m:
        out.append(
            (wavelength, min(amplitude_m * (wavelength / top_m) ** HURST, STEEPNESS * wavelength))
        )
        wavelength /= 2
    return out


def displace(xyz: F64, radius_m: float, octaves: list[tuple[float, float]], seed: int) -> F64:
    """Unit vectors moved along the sphere by rotated noise ``octaves`` (a domain warp)."""
    offset = np.zeros_like(xyz)
    for k, (wavelength, amplitude) in enumerate(octaves):
        p = np.ascontiguousarray((xyz @ _rotation(seed + k)) * (radius_m / wavelength))
        for axis in range(3):
            offset[:, axis] += amplitude * value_noise3(p, seed + 97 * k + axis)
    offset -= np.sum(offset * xyz, axis=1, keepdims=True) * xyz
    moved = xyz + offset / radius_m
    return moved / np.linalg.norm(moved, axis=1, keepdims=True)


@dataclass(frozen=True, eq=False)
class Coastline:
    """A world's land, smoothed once, ready for refined inside tests."""

    world: WorldMap
    land: BaseGeometry
    unit_m: float

    def octaves(self, finest_m: float) -> list[tuple[float, float]]:
        """(wavelength, amplitude) in metres, coarsest first, down to ``finest_m``."""
        return noise_octaves(
            TOP_WAVELENGTH_UNITS * self.unit_m, TOP_AMPLITUDE_UNITS * self.unit_m, finest_m
        )

    def displaced(self, xyz: F64, finest_m: float, seed: int) -> F64:
        radius_m = self.world.project.frame.radius_km * 1e3
        return displace(xyz, radius_m, self.octaves(finest_m), seed)

    def contains(self, xyz: F64, finest_m: float, master_seed: int) -> B:
        """Land at unit vectors ``xyz`` with coast detail down to ``finest_m`` metres."""
        moved = self.displaced(xyz, finest_m, stage_seed(master_seed, COAST_STAGE))
        x, y = source_xy(self.world.project.frame, moved)
        return np.asarray(shapely.contains_xy(self.land, x, y), dtype=bool)


@lru_cache(maxsize=2)
def coastline(world: WorldMap) -> Coastline:
    """The world's refined coast, built once per world and process."""
    frame = world.project.frame
    components = [c for view in world.land for c in view.components]
    sigma = SMOOTHING_UNITS
    smoothed = unary_union([
        shapely.make_valid(
            Polygon(_smooth_ring(c.exterior, sigma), [_smooth_ring(h, sigma) for h in c.holes])
        )
        for c in components
    ])
    # Within a few smoothing widths of the frame edges (the antimeridian seam and
    # the poles) the drawn coast is kept, so land cut by the frame stays joined.
    x0, y0, x1, y1 = frame.bounds
    margin = 3 * sigma
    inner = box(x0 + margin, y0 + margin, x1 - margin, y1 - margin)
    drawn = unary_union([Polygon(c.exterior, c.holes) for c in components])
    land = unary_union([smoothed.intersection(inner), drawn.difference(inner)])
    shapely.prepare(land)
    return Coastline(world, land, 2 * pi * frame.radius_km * 1e3 / frame.width)
