# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Equirectangular rasters, shaded relief and river overlays from mesh fields."""

from __future__ import annotations

from math import pi

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw
from scipy.spatial import KDTree

from benchmarks.planet.kernels import interpolate_to_lonlat
from benchmarks.planet.mesh import SphereMesh, vertex_triangles

type F64 = NDArray[np.float64]

LAND_STOPS = (
    (0, (88, 128, 74)),
    (200, (118, 152, 86)),
    (600, (170, 178, 112)),
    (1200, (204, 182, 128)),
    (2000, (176, 136, 96)),
    (3000, (140, 104, 80)),
    (4200, (190, 180, 176)),
    (5500, (250, 250, 250)),
)
SEA_STOPS = (
    (-6000, (16, 34, 66)),
    (-4000, (26, 56, 98)),
    (-2000, (40, 86, 136)),
    (-500, (62, 122, 170)),
    (-120, (92, 158, 196)),
    (0, (128, 186, 214)),
)


class Rasterizer:
    """Reusable interpolation from mesh nodes to a lon/lat pixel grid."""

    def __init__(self, mesh: SphereMesh, width: int) -> None:
        height = width // 2
        lon = (np.arange(width) + 0.5) / width * 2 * pi - pi
        lat = pi / 2 - (np.arange(height) + 0.5) / height * pi
        glon, glat = np.meshgrid(lon, lat)
        q = np.stack(
            (np.cos(glat) * np.cos(glon), np.cos(glat) * np.sin(glon), np.sin(glat)), axis=-1
        ).reshape(-1, 3)
        nearest = np.asarray(KDTree(mesh.xyz).query(q, workers=-1)[1], dtype=np.int64)
        self.mesh = mesh
        self.shape = (height, width)
        self.queries = q
        self.nearest = nearest.astype(np.int64)
        self.vt = vertex_triangles(mesh)
        self.lat = lat

    def __call__(self, values: F64) -> F64:
        m = self.mesh
        out = interpolate_to_lonlat(
            values, m.xyz, m.triangles, self.vt[0], self.vt[1], m.ptr, m.nbr,
            self.nearest, self.queries,
        )
        return out.reshape(self.shape)

    def nearest_values(self, values: NDArray[np.generic]) -> NDArray[np.generic]:
        return values[self.nearest].reshape(self.shape)


def _ramp(z: F64, stops: tuple[tuple[int, tuple[int, int, int]], ...]) -> F64:
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    out = np.empty((*z.shape, 3))
    for c in range(3):
        out[..., c] = np.interp(z, xs, [s[1][c] for s in stops])
    return out


def hillshade(z: F64, lat: F64, radius_m: float, exaggeration: float = 12.0) -> F64:
    height, width = z.shape
    dy = pi * radius_m / height
    dx = 2 * pi * radius_m / width * np.maximum(np.cos(lat), 0.02)[:, None]
    gy = np.gradient(z, axis=0) / dy * exaggeration
    gx = (np.roll(z, -1, axis=1) - np.roll(z, 1, axis=1)) / (2 * dx) * exaggeration
    azimuth, altitude = np.deg2rad(315), np.deg2rad(40)
    lx = np.cos(altitude) * np.sin(azimuth)
    ly = np.cos(altitude) * np.cos(azimuth)
    lz = np.sin(altitude)
    norm = np.sqrt(gx * gx + gy * gy + 1)
    # Image rows increase southward, so north-facing slope is +gy.
    return np.clip((-gx * lx + gy * ly + lz) / norm, 0, 1)


def relief_image(
    elevation: F64,
    land: NDArray[np.bool_],
    lat: F64,
    radius_m: float,
) -> Image.Image:
    rgb = np.where(land[..., None], _ramp(elevation, LAND_STOPS), _ramp(elevation, SEA_STOPS))
    shade = hillshade(elevation, lat, radius_m)
    land_shade = 0.55 + 0.65 * shade
    sea_shade = 0.85 + 0.25 * shade
    rgb = rgb * np.where(land, land_shade, sea_shade)[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def draw_rivers(
    image: Image.Image,
    mesh: SphereMesh,
    receiver: NDArray[np.int64],
    discharge: F64,
    water: NDArray[np.bool_],
    threshold_m2: float,
    colour: tuple[int, int, int] = (40, 90, 170),
) -> int:
    width, height = image.size
    draw = ImageDraw.Draw(image)
    lon, lat = mesh.lon, mesh.lat
    x = (lon + pi) / (2 * pi) * width
    y = (pi / 2 - lat) / pi * height
    nodes = np.flatnonzero((~water) & (receiver >= 0) & (discharge >= threshold_m2))
    drawn = 0
    top = float(np.max(discharge[nodes])) if len(nodes) else 1.0
    for i in nodes[np.argsort(discharge[nodes])].tolist():
        r = int(receiver[i])
        x0, y0, x1, y1 = float(x[i]), float(y[i]), float(x[r]), float(y[r])
        if abs(x1 - x0) > width / 2:
            continue
        strength = np.log(discharge[i] / threshold_m2) / max(np.log(top / threshold_m2), 1e-9)
        w = 1 + round(2.2 * float(strength))
        draw.line((x0, y0, x1, y1), fill=colour, width=w)
        drawn += 1
    return drawn
