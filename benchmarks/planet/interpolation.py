# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Do curves rebuild eroded relief better than straight lines? (T22)

A truth surface is sampled at the nodes of a coarser sphere mesh and rebuilt on
a raster in each window's azimuthal plane by each interpolant:

- ``linear``: triangle-linear, the planet's authoritative surface (ADR-0085);
- ``cubic``: the Clough-Tocher cubics regional tiles are seeded with
  (``smooth_sampler``), held within each triangle's corner values;
- ``cubic-free``: the same cubics without that clip;
- ``twist`` and ``cubic-twist``: ``linear`` and ``cubic`` sampled along an
  area-preserving flow (``swirl``) with ADR-0106's recipe: octaves from two
  coarse spacings down to one, each 0.15 of its wavelength.

Each rebuild is scored against the truth on the window's land at least one
coarse spacing from the sea: height and slope error, likeness of the world
map's hillshade, creases along coarse triangle edges, straight contours, false
hollows, overshoot, and rivers routed over each surface.

The truth is a planet build's own surface (a finer mesh), or an Earth DEM in
geographic coordinates (NOAA ETOPO 2022), read as data. Usage::

    python -m benchmarks.planet.interpolation planet BUILD --output OUT.json
    python -m benchmarks.planet.interpolation dem DEM.tif --output OUT.json
"""

import argparse
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray
from PIL import Image
from scipy.interpolate import CloughTocher2DInterpolator
from scipy.ndimage import distance_transform_edt, laplace, map_coordinates, minimum_filter
from scipy.spatial import Delaunay, KDTree

from map_maker.terrain.adapters.build import file_sha256, runtime_identity
from map_maker.terrain.adapters.planet_load import verified_build
from map_maker.terrain.adapters.planet_natural import EXAGGERATION, shading
from map_maker.terrain.pipeline.planet_coast import swirl
from map_maker.terrain.pipeline.planet_detail import grid_flow
from map_maker.terrain.pipeline.planet_kernels import interpolate_to_lonlat
from map_maker.terrain.pipeline.planet_mesh import (
    SphereMesh,
    build_mesh,
    mesh_from_triangles,
    vertex_triangles,
)
from map_maker.terrain.pipeline.planet_patch import forward_aeqd, inverse_aeqd
from map_maker.terrain.pipeline.planet_regional import smooth_sampler

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

VARIANTS = ("linear", "cubic", "cubic-free", "twist", "cubic-twist")
CURVED = ("cubic", "cubic-free")
TWISTED = ("twist", "cubic-twist")
PIXELS_PER_SPACING = 8
WINDOW_RADIUS_M = 600e3
COARSE_SEED = 20261019  # jitter of the coarse meshes; no build uses it for its own mesh
TWIST_SEED = 20261020
TWIST_TOP_SPACINGS = 2.0  # ADR-0106: from two spacings down to one
TWIST_STEEPNESS = 0.15
EDGE_BAND_PX = 1.0  # pixels this close to a coarse triangle edge are on it
STRAIGHT_RADIUS_SPACINGS = 10.0  # contours straighter than this radius count as straight
MIN_CONTOUR_SLOPE = 0.002  # flatter pixels have no meaningful contour direction
RIVER_AREA_SPACINGS2 = 5.0  # river cells drain at least this many coarse node areas
RIVER_MATCH_PX = 2.0
STRAIGHT_RIVER_STEPS = 8
EARTH_RADIUS_M = 6_371_000.0
PLANET_WINDOWS = 8
PLANET_WINDOW_COAST_M = 250e3  # planet window centres lie this far inland

# Earth windows: high ranges, two controls with real straight ridges, a desert
# massif, a lowland basin, a glaciated coast and a rift.
EARTH_WINDOWS: dict[str, tuple[float, float]] = {
    "alps": (10.5, 46.3),
    "himalaya": (85.0, 28.5),
    "central-andes": (-67.5, -20.0),
    "appalachians": (-78.5, 39.5),
    "zagros": (52.0, 30.0),
    "tibesti": (18.0, 21.0),
    "amazon": (-62.0, -5.0),
    "norway": (8.0, 62.0),
    "east-african-rift": (36.5, 0.5),
}
CONTROLS = ("appalachians", "zagros")


@dataclass(frozen=True)
class Truth:
    """Heights (m, sea at 0) and land at unit vectors on a sphere of ``radius_m``."""

    radius_m: float
    sample: Callable[[F64], tuple[F64, B]]
    identity: dict[str, object]


@dataclass(frozen=True)
class Window:
    name: str
    lon: float
    lat: float


class LinearSampler:
    """Triangle-linear interpolation of node fields, with its search support built once."""

    def __init__(self, mesh: SphereMesh) -> None:
        self.mesh = mesh
        self.tree = KDTree(mesh.xyz)
        self.vt_ptr, self.vt_idx = vertex_triangles(mesh)

    def __call__(self, xyz: F64, values: F64) -> F64:
        mesh = self.mesh
        nearest = np.asarray(self.tree.query(xyz, workers=-1)[1], dtype=np.int64)
        return interpolate_to_lonlat(
            np.ascontiguousarray(values, dtype=np.float64), mesh.xyz, mesh.triangles,
            self.vt_ptr, self.vt_idx, mesh.ptr, mesh.nbr, nearest, np.ascontiguousarray(xyz),
        )


def planet_truth(path: Path) -> tuple[Truth, list[Window]]:
    """A planet build's land relief (sea at 0) and windows spread over its interiors."""
    folder, manifest = verified_build(path, ("planet.npz",))
    radius_m = float(manifest["world_frame"]["radius_km"]) * 1000
    with np.load(folder / "planet.npz", allow_pickle=False) as data:
        mesh = mesh_from_triangles(
            data["xyz"].astype(np.float64), data["triangles"].astype(np.int64), radius_m
        )
        land = data["land"].astype(bool)
        height = np.where(land, np.maximum(data["elevation_m"].astype(np.float64), 0.0), 0.0)
        coast = data["coast_distance_m"].astype(np.float64)
    linear = LinearSampler(mesh)
    land_share = land.astype(np.float64)

    def sample(xyz: F64) -> tuple[F64, B]:
        return linear(xyz, height), linear(xyz, land_share) >= 0.5

    identity: dict[str, object] = {
        "kind": "planet",
        "build_sha256": manifest["build_sha256"],
        "nodes": mesh.size,
        "spacing_km": round(mesh.spacing_m / 1e3, 2),
        "relief_algorithm": manifest.get("algorithms", {}).get("relief"),
    }
    return Truth(radius_m, sample, identity), planet_windows(mesh, land, coast, height)


def planet_windows(
    mesh: SphereMesh, land: B, coast_m: F64, height_m: F64, count: int = PLANET_WINDOWS
) -> list[Window]:
    """Window centres far inland: the highest such node, then each farthest from the rest."""
    candidates = np.flatnonzero(land & (coast_m >= PLANET_WINDOW_COAST_M))
    if not len(candidates):
        raise ValueError("The planet has no land far enough from the sea for windows.")
    chosen = [int(candidates[np.argmax(height_m[candidates])])]
    nearest = np.arccos(np.clip(mesh.xyz[candidates] @ mesh.xyz[chosen[0]], -1, 1))
    while len(chosen) < count:
        pick = int(candidates[np.argmax(nearest)])
        if nearest.max() * mesh.radius_m < 2 * WINDOW_RADIUS_M:
            break  # no more windows that do not overlap
        chosen.append(pick)
        angle = np.arccos(np.clip(mesh.xyz[candidates] @ mesh.xyz[pick], -1, 1))
        nearest = np.minimum(nearest, angle)
    windows: list[Window] = []
    for k, node in enumerate(chosen):
        x, y, z = mesh.xyz[node]
        lon, lat = math.degrees(math.atan2(y, x)), math.degrees(math.asin(z))
        windows.append(Window(f"w{k + 1}", round(lon, 3), round(lat, 3)))
    return windows


def dem_truth(path: Path) -> tuple[Truth, list[Window]]:
    """A geographic DEM (land above 0 m) on a sphere of Earth's mean radius."""
    with rasterio.open(path) as dataset:
        transform, height, width = dataset.transform, dataset.height, dataset.width
        crs = str(dataset.crs)

    def sample(xyz: F64) -> tuple[F64, B]:
        lon = np.degrees(np.arctan2(xyz[:, 1], xyz[:, 0]))
        lat = np.degrees(np.arcsin(np.clip(xyz[:, 2], -1, 1)))
        column = (lon - transform.c) / transform.a - 0.5
        row = (lat - transform.f) / transform.e - 0.5
        c0 = max(int(np.floor(column.min())) - 2, 0)
        r0 = max(int(np.floor(row.min())) - 2, 0)
        c1 = min(int(np.ceil(column.max())) + 3, width)
        r1 = min(int(np.ceil(row.max())) + 3, height)
        if c1 - c0 > width // 2:
            raise ValueError("DEM windows may not cross the antimeridian.")
        with rasterio.open(path) as dataset:
            block = dataset.read(1, window=((r0, r1), (c0, c1)))
        z = map_coordinates(
            block.astype(np.float64), np.stack((row - r0, column - c0)), order=1, mode="nearest"
        )
        return np.maximum(z, 0.0), z > 0

    identity: dict[str, object] = {
        "kind": "dem",
        "file": path.name,
        "sha256": file_sha256(path),
        "shape": [height, width],
        "pixel_deg": [abs(transform.a), abs(transform.e)],
        "crs": crs,
        "radius_km": EARTH_RADIUS_M / 1e3,
    }
    windows = [Window(name, lon, lat) for name, (lon, lat) in EARTH_WINDOWS.items()]
    return Truth(EARTH_RADIUS_M, sample, identity), windows


def free_cubic(mesh: SphereMesh, linear: LinearSampler, xyz: F64) -> Callable[[F64], F64]:
    """``smooth_sampler`` without holding each sample within its triangle's corner values."""
    centre = xyz.mean(axis=0)
    centre /= np.linalg.norm(centre)
    reach = float(np.arccos(np.clip(xyz @ centre, -1, 1)).max())
    reach += 4 * mesh.spacing_m / mesh.radius_m
    near = np.flatnonzero(mesh.xyz @ centre >= np.cos(min(reach, np.pi)))
    if len(near) < 4:
        return partial(linear, xyz)
    lon = float(np.degrees(np.arctan2(centre[1], centre[0])))
    lat = float(np.degrees(np.arcsin(np.clip(centre[2], -1, 1))))
    unit_m = mesh.spacing_m
    triangulation = Delaunay(forward_aeqd(mesh.xyz[near], lon, lat, mesh.radius_m) / unit_m)
    plane = forward_aeqd(xyz, lon, lat, mesh.radius_m) / unit_m

    def sample(values: F64) -> F64:
        local = values[near]
        low, span = float(local.min()), float(np.ptp(local)) or 1.0
        unit = CloughTocher2DInterpolator(triangulation, (local - low) / span)(plane)
        cubic = low + span * np.asarray(unit)
        outside = ~np.isfinite(cubic)
        if outside.any():
            cubic[outside] = linear(xyz[outside], values)
        return cubic

    return sample


def twist_octaves(spacing_m: float) -> list[tuple[float, float]]:
    """ADR-0106's flow octaves for a mesh of ``spacing_m``: two spacings down to one."""
    octaves: list[tuple[float, float]] = []
    wavelength = TWIST_TOP_SPACINGS * spacing_m
    while wavelength >= spacing_m * (1 - 1e-9):
        octaves.append((wavelength, TWIST_STEEPNESS * wavelength))
        wavelength /= 2
    return octaves


@dataclass(frozen=True)
class Grid:
    """A north-up square raster about a window centre in its azimuthal plane."""

    window: Window
    radius_m: float  # sphere radius
    pixel_m: float
    size: int
    plane: F64  # (n*n, 2) plane metres, x east, y north
    xyz: F64

    @classmethod
    def build(cls, window: Window, radius_m: float, pixel_m: float, extent_m: float) -> Grid:
        half = math.ceil(extent_m / pixel_m)
        axis = np.arange(-half, half + 1, dtype=np.float64) * pixel_m
        x, y = np.meshgrid(axis, axis[::-1])
        plane = np.stack((x.ravel(), y.ravel()), axis=1)
        xyz = inverse_aeqd(plane[:, 0], plane[:, 1], window.lon, window.lat, radius_m)
        return cls(window, radius_m, pixel_m, len(axis), plane, xyz)

    def shape(self, values: F64 | B) -> NDArray[np.generic]:
        return np.asarray(values).reshape(self.size, self.size)


@dataclass(frozen=True)
class Support:
    """Where each pixel lies among the coarse triangles: edge band and corner range."""

    on_edge: B
    corner_low: F64
    corner_high: F64


def support(grid: Grid, mesh: SphereMesh, near: I64, values: F64) -> Support:
    """Coarse triangles over the grid in its plane (as ``smooth_sampler`` builds them)."""
    w = grid.window
    nodes = forward_aeqd(mesh.xyz[near], w.lon, w.lat, mesh.radius_m)
    triangulation = Delaunay(nodes)
    simplex = triangulation.find_simplex(grid.plane)
    if np.any(simplex < 0):
        raise ValueError("The coarse nodes do not cover the window.")
    corners = triangulation.simplices[simplex]
    p = grid.plane
    distance = np.full(len(p), np.inf)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a, b = nodes[corners[:, i]], nodes[corners[:, j]]
        edge = b - a
        cross = edge[:, 0] * (p[:, 1] - a[:, 1]) - edge[:, 1] * (p[:, 0] - a[:, 0])
        distance = np.minimum(distance, np.abs(cross) / np.linalg.norm(edge, axis=1))
    at = values[near][corners]
    return Support(
        grid.shape(distance <= EDGE_BAND_PX * grid.pixel_m).astype(bool),
        grid.shape(at.min(axis=1)).astype(np.float64),
        grid.shape(at.max(axis=1)).astype(np.float64),
    )


def gradients(z: F64, pixel_m: float) -> tuple[F64, F64]:
    """Eastward and southward (image-row) height gradients."""
    return np.gradient(z, pixel_m, axis=1), np.gradient(z, pixel_m, axis=0)


def straight_river_share(receiver: I64, river: B) -> float:
    """Share of river cells whose next STRAIGHT_RIVER_STEPS steps keep one grid direction."""
    flow = receiver.ravel()
    cells = np.flatnonzero(river.ravel() & (flow >= 0))
    if not len(cells):
        return math.nan
    step = flow[cells] - cells
    here, straight = cells, np.ones(len(cells), dtype=bool)
    for _ in range(STRAIGHT_RIVER_STEPS):
        nxt = flow[here]
        straight &= (nxt >= 0) & (nxt - here == step)
        here = np.where(nxt >= 0, nxt, here)
    return float(straight.mean())


def distance_to(cells: B) -> F64:
    """Distance (pixels) from every pixel to the nearest of ``cells``; inf if there are none."""
    if not cells.any():
        return np.full(cells.shape, np.inf)
    return np.asarray(distance_transform_edt(~cells), dtype=np.float64)


def near_share(cells: B, target: B, pixels: float) -> float:
    """Share of ``cells`` within ``pixels`` of a ``target`` cell."""
    if not cells.any():
        return math.nan
    if not target.any():
        return 0.0
    return float((distance_to(target)[cells] <= pixels).mean())




@dataclass(frozen=True)
class Scene:
    """What every surface of one window is scored against."""

    spacing_m: float
    pixel_m: float
    inner: B  # land at least one coarse spacing from the sea, inside the window circle
    outlet: B  # sea and the raster's rim
    support: Support
    truth_z: F64
    truth_gx: F64
    truth_gy: F64
    truth_light: F64
    truth_river: B


def surface_metrics(z: F64, scene: Scene, *, bounded: bool) -> tuple[dict[str, float], F64]:
    """Scores of one surface, and its hillshade.

    ``bounded`` surfaces are sampled at the pixels themselves, so their overshoot
    beyond the corner values of each pixel's coarse triangle is measured too (the
    truth's own is the reference: real ground rises between nodes).
    """
    inner, s, p = scene.inner, scene.spacing_m, scene.pixel_m
    gx, gy = gradients(z, p)
    slope, light = shading(gx, gy, EXAGGERATION)
    true_slope = np.hypot(scene.truth_gx, scene.truth_gy)
    bend = np.abs(laplace(z) / (p * p))
    on_edge = scene.support.on_edge & inner
    interior = ~scene.support.on_edge & inner
    # Planform curvature: how fast contour directions turn (1/m).
    unit = np.where(slope > 0, slope, 1.0)
    curvature = np.abs(np.gradient(gx / unit, p, axis=1) + np.gradient(gy / unit, p, axis=0))
    sloped = inner & (slope > MIN_CONTOUR_SLOPE)
    ring = np.ones((3, 3), dtype=bool)
    ring[1, 1] = False
    pits = inner & (z < minimum_filter(z, footprint=ring, mode="nearest"))
    receiver, drained, filled = grid_flow(z, scene.outlet, p, np.zeros(z.shape))
    river = inner & (drained.reshape(z.shape) >= RIVER_AREA_SPACINGS2 * s * s)
    precision = near_share(river, scene.truth_river, RIVER_MATCH_PX)
    recall = near_share(scene.truth_river, river, RIVER_MATCH_PX)
    error = (z - scene.truth_z)[inner]
    slope_error = np.hypot(gx - scene.truth_gx, gy - scene.truth_gy)[inner]
    metrics = {
        "height_rmse_m": float(np.sqrt(np.mean(error**2))),
        "height_bias_m": float(error.mean()),
        "slope_rmse": float(np.sqrt(np.mean(slope_error**2))),
        "slope_median_ratio": float(np.median(slope[inner]) / np.median(true_slope[inner])),
        "slope_p90_ratio": float(
            np.percentile(slope[inner], 90) / np.percentile(true_slope[inner], 90)
        ),
        "shade_correlation": float(np.corrcoef(light[inner], scene.truth_light[inner])[0, 1]),
        "crease_ratio": float(bend[on_edge].mean() / bend[interior].mean()),
        "straight_contour_share": float(
            (curvature[sloped] < 1 / (STRAIGHT_RADIUS_SPACINGS * s)).mean()
        ),
        "pits_per_10k_km2": float(pits.sum() / (inner.sum() * p * p / 1e10)),
        "filled_share": float(((filled - z) > 0.1)[inner].mean()),
        "river_precision": precision,
        "river_recall": recall,
        "river_f1": (
            2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
        ),
        "straight_river_share": straight_river_share(receiver.reshape(z.shape), river),
    }
    if bounded:
        support = scene.support
        excess = np.maximum(np.maximum(z - support.corner_high, support.corner_low - z), 0.0)
        metrics["overshoot_p99_m"] = float(np.percentile(excess[inner], 99))
        metrics["overshoot_max_m"] = float(excess[inner].max())
    return metrics, light


@dataclass(frozen=True)
class WindowScores:
    window: Window
    facts: dict[str, object]
    truth: dict[str, float]
    variants: dict[str, dict[str, float]]

    def score(self, who: str, key: str) -> float | None:
        value = (self.truth if who == "truth" else self.variants[who]).get(key)
        return value if value is not None and math.isfinite(value) else None

    def as_json(self) -> dict[str, object]:
        w = self.window
        return {
            "window": w.name, "lon": w.lon, "lat": w.lat, **self.facts,
            "truth": self.truth, "variants": self.variants,
        }


def evaluate(
    truth: Truth,
    mesh: SphereMesh,
    linear: LinearSampler,
    window: Window,
    *,
    window_radius_m: float = WINDOW_RADIUS_M,
    crops: Path | None = None,
) -> WindowScores | None:
    """Every variant's scores, and the truth's own, for one window and coarse mesh.

    None where the window holds too little land far enough from the sea.
    """
    s = mesh.spacing_m
    grid = Grid.build(window, truth.radius_m, s / PIXELS_PER_SPACING, window_radius_m)
    p = grid.pixel_m
    centre = grid.xyz[len(grid.xyz) // 2]
    reach = (math.sqrt(2) * window_radius_m + 12 * s) / mesh.radius_m
    near = np.flatnonzero(mesh.xyz @ centre >= math.cos(reach))
    values = np.zeros(mesh.size)
    values[near] = truth.sample(mesh.xyz[near])[0]
    truth_flat, land_flat = truth.sample(grid.xyz)
    truth_z = grid.shape(truth_flat).astype(np.float64)
    land = grid.shape(land_flat).astype(bool)
    rim = np.zeros(land.shape, dtype=bool)
    rim[[0, -1], :] = True
    rim[:, [0, -1]] = True
    from_centre = grid.shape(np.hypot(grid.plane[:, 0], grid.plane[:, 1])).astype(np.float64)
    inner = (distance_to(~land) * p >= s) & (from_centre <= window_radius_m - 2 * p)
    if inner.sum() < 100:
        return None
    gx, gy = gradients(truth_z, p)
    _, truth_light = shading(gx, gy, EXAGGERATION)
    outlet = ~land | rim
    _, drained, _ = grid_flow(truth_z, outlet, p, np.zeros(truth_z.shape))
    scene = Scene(
        s, p, inner, outlet, support(grid, mesh, near, values), truth_z, gx, gy, truth_light,
        inner & (drained.reshape(truth_z.shape) >= RIVER_AREA_SPACINGS2 * s * s),
    )
    moved = swirl(grid.xyz, mesh.radius_m, twist_octaves(s), TWIST_SEED)
    surfaces = {
        "linear": linear(grid.xyz, values),
        "cubic": smooth_sampler(mesh, grid.xyz)(values),
        "cubic-free": free_cubic(mesh, linear, grid.xyz)(values),
        "twist": linear(moved, values),
        "cubic-twist": smooth_sampler(mesh, moved)(values),
    }
    truth_scores, _ = surface_metrics(truth_z, scene, bounded=True)
    scores: dict[str, dict[str, float]] = {}
    lights = {"truth": truth_light}
    for name in VARIANTS:
        rebuilt = grid.shape(surfaces[name]).astype(np.float64)
        z = np.where(land, np.maximum(rebuilt, 0.0), 0.0)
        scores[name], lights[name] = surface_metrics(z, scene, bounded=name not in TWISTED)
    if crops is not None:
        save_crops(crops / f"{window.name}-{mesh.size}.png", lights, land)
    relief = truth_z[inner]
    moved_m = mesh.radius_m * np.arccos(np.clip(np.einsum("ij,ij->i", moved, grid.xyz), -1, 1))
    facts: dict[str, object] = {
        "pixel_km": round(p / 1e3, 3),
        "inner_km2": round(float(inner.sum() * p * p / 1e6)),
        "mean_height_m": round(float(relief.mean())),
        "height_p5_p95_m": [round(float(v)) for v in np.percentile(relief, [5, 95])],
        "twist_mean_move_km": round(float(moved_m.mean()) / 1e3, 2),
    }
    return WindowScores(window, facts, truth_scores, scores)


def save_crops(path: Path, lights: dict[str, F64], land: B) -> None:
    """The truth's and every variant's hillshade side by side, sea in blue."""
    panels: list[NDArray[np.uint8]] = []
    gap = np.full((land.shape[0], 4, 3), 255, dtype=np.uint8)
    for name in ("truth", *VARIANTS):
        grey = np.clip(lights[name] / 1.6, 0, 1) * 255
        rgb = np.stack([grey] * 3, axis=-1)
        rgb[~land] = (40, 70, 110)
        panels.extend((rgb.astype(np.uint8), gap))
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.concatenate(panels[:-1], axis=1)).save(path)


SUMMARY_KEYS = (
    "height_rmse_m",
    "slope_rmse",
    "slope_median_ratio",
    "shade_correlation",
    "crease_ratio",
    "straight_contour_share",
    "pits_per_10k_km2",
    "filled_share",
    "river_f1",
    "straight_river_share",
    "overshoot_p99_m",
)


def medians(rows: Sequence[WindowScores]) -> dict[str, dict[str, float | None]]:
    """Median over windows of every summary score, for the truth and each variant."""
    out: dict[str, dict[str, float | None]] = {}
    for who in ("truth", *VARIANTS):
        out[who] = {}
        for key in SUMMARY_KEYS:
            found = [v for row in rows if (v := row.score(who, key)) is not None]
            out[who][key] = float(np.median(found)) if found else None
    return out


def rules(
    rows: Sequence[WindowScores], controls: Sequence[str] = ()
) -> dict[str, dict[str, bool | None]]:
    """The pre-registered rules (T22) for each curved variant, on medians over windows."""
    med = medians(rows)

    def get(who: str, key: str) -> float:
        value = med[who][key]
        if value is None:
            raise ValueError(f"No {key} for {who}.")
        return value

    def closes_half(name: str, key: str) -> bool:
        """At least half of the way from linear's median to the truth's."""
        lin, tru, got = get("linear", key), get("truth", key), get(name, key)
        return (lin - got) / (lin - tru) >= 0.5 if lin != tru else got == tru

    out: dict[str, dict[str, bool | None]] = {}
    for name in CURVED:
        kept = [
            abs(got - want) <= 0.2 * want
            for row in rows
            if row.window.name in controls
            and (got := row.score(name, "straight_contour_share")) is not None
            and (want := row.score("truth", "straight_contour_share")) is not None
        ]
        no_harm = (
            get(name, "height_rmse_m") <= 1.02 * get("linear", "height_rmse_m")
            and get(name, "pits_per_10k_km2")
            <= 1.1 * max(get("linear", "pits_per_10k_km2"), get("truth", "pits_per_10k_km2"))
            and get(name, "river_f1") >= get("linear", "river_f1") - 0.02
        )
        if name == "cubic-free":
            # Real ground also rises above its triangle's corners between nodes.
            no_harm = no_harm and (
                get(name, "overshoot_p99_m") <= get("truth", "overshoot_p99_m") + 50.0
            )
        out[name] = {
            "looks_closer": (
                get(name, "shade_correlation") - get("linear", "shade_correlation") >= 0.02
                and get(name, "slope_rmse") <= 0.95 * get("linear", "slope_rmse")
            ),
            "fewer_mesh_lines": (
                closes_half(name, "crease_ratio") and closes_half(name, "straight_contour_share")
            ),
            "no_harm": no_harm,
            "controls_keep_straight_ridges": all(kept) if kept else None,
        }
    return out


def finite(value: object) -> object:
    """``value`` with NaN and infinities as None, for strict JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list | tuple):
        return [finite(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def run(
    truth: Truth,
    windows: Sequence[Window],
    nodes: Sequence[int],
    *,
    window_radius_m: float = WINDOW_RADIUS_M,
    crops: Path | None = None,
    controls: Sequence[str] = (),
    progress: Callable[[str], None] = print,
) -> list[dict[str, object]]:
    """One entry per coarse mesh size: medians, rules and every window's scores."""
    runs: list[dict[str, object]] = []
    for count in nodes:
        mesh = build_mesh(count, truth.radius_m, COARSE_SEED)
        linear = LinearSampler(mesh)
        rows: list[WindowScores] = []
        skipped: list[str] = []
        for window in windows:
            progress(f"{count:,} nodes: {window.name}")
            scores = evaluate(
                truth, mesh, linear, window, window_radius_m=window_radius_m, crops=crops
            )
            if scores is None:
                skipped.append(window.name)
            else:
                rows.append(scores)
        runs.append({
            "nodes": count,
            "spacing_km": round(mesh.spacing_m / 1e3, 2),
            "skipped": skipped,
            "medians": medians(rows),
            "rules": rules(rows, controls),
            "windows": [row.as_json() for row in rows],
        })
    return runs


def settings(windows: Sequence[Window], controls: Sequence[str]) -> dict[str, object]:
    return {
        "window_radius_km": WINDOW_RADIUS_M / 1e3,
        "pixels_per_spacing": PIXELS_PER_SPACING,
        "coarse_seed": COARSE_SEED,
        "twist_seed": TWIST_SEED,
        "twist_top_spacings": TWIST_TOP_SPACINGS,
        "twist_steepness": TWIST_STEEPNESS,
        "edge_band_px": EDGE_BAND_PX,
        "straight_radius_spacings": STRAIGHT_RADIUS_SPACINGS,
        "min_contour_slope": MIN_CONTOUR_SLOPE,
        "river_area_spacings2": RIVER_AREA_SPACINGS2,
        "river_match_px": RIVER_MATCH_PX,
        "controls": list(controls),
        "windows": [[w.name, w.lon, w.lat] for w in windows],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score curved against straight interpolation.")
    parser.add_argument("kind", choices=("planet", "dem"))
    parser.add_argument("source", type=Path, help="Planet build folder, or a geographic DEM.")
    parser.add_argument("--nodes", type=int, nargs="+", default=[200_000, 800_000],
                        help="Coarse sphere mesh sizes.")
    parser.add_argument("--output", type=Path, required=True, help="New JSON report.")
    parser.add_argument("--crops", type=Path, help="Folder for side-by-side hillshade crops.")
    args = parser.parse_args()
    output: Path = args.output
    if output.exists():
        raise SystemExit(f"{output} already exists.")
    start = runtime_identity()
    if args.kind == "planet":
        truth, windows = planet_truth(args.source)
        controls: tuple[str, ...] = ()
    else:
        truth, windows = dem_truth(args.source)
        controls = CONTROLS
    runs = run(truth, windows, args.nodes, crops=args.crops, controls=controls)
    if runtime_identity() != start:
        raise SystemExit("Sources changed during the run; its results are discarded.")
    report = {
        "truth": truth.identity,
        "settings": settings(windows, controls),
        "runtime": start,
        "runs": runs,
    }
    partial_path = output.with_name(output.name + ".partial")
    partial_path.write_text(json.dumps(finite(report), indent=2, allow_nan=False), "utf-8")
    partial_path.replace(output)
    for entry in runs:
        print(json.dumps({"nodes": entry["nodes"], "rules": entry["rules"]}))


if __name__ == "__main__":
    main()
