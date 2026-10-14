# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Deterministic fractal test worlds for whole-planet development.

The public examples are a few hand-placed polygons. Whole-world terrain needs
inputs with realistic coast complexity, a seam-crossing continent, a polar
landmass, inland seas and many islands. This writes such a world as an SVG in
the importer's Plate Carree convention plus a reviewed ``.world.json``.

Generated worlds are development fixtures, not authored canon.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from math import pi
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from rasterio import features
from scipy import ndimage
from shapely.geometry import MultiPolygon, Polygon, shape

from map_maker.terrain.adapters.world_svg import parse_world_svg
from map_maker.terrain.application.world import propose_group_assignments, save_world
from map_maker.terrain.domain.world import WorldFrame, WorldProject

type Array = NDArray[np.float64]

# SVG source frame: 0.1 degree per unit, so 3600 x 1800 covers the full sphere.
WIDTH, HEIGHT = 3600.0, 1800.0
NAMES = (
    "Aldmark", "Brennhal", "Corvane", "Dunmere", "Eskarra", "Fenwold",
    "Galtrea", "Hollin", "Istrand", "Jorvale",
)


def _hash01(seed: int, *coords: NDArray[np.int64]) -> Array:
    """Stateless lattice hash in [0, 1) (splitmix-style mixing)."""
    with np.errstate(over="ignore"):
        h: NDArray[np.uint64] = np.full(coords[0].shape, seed, dtype=np.uint64) * np.uint64(
            0x9E3779B97F4A7C15
        )
        for i, c in enumerate(coords):
            salt = (0xBF58476D1CE4E5B9 + 0x94D049BB133111EB * i) & 0xFFFFFFFFFFFFFFFF
            h = h ^ (c.astype(np.uint64) * np.uint64(salt))
            h = (h ^ (h >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
            h = (h ^ (h >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
            h = h ^ (h >> np.uint64(31))
    return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def value_noise3(p: Array, seed: int) -> Array:
    """Smooth 3D value noise in [-1, 1]; ``p`` has shape (..., 3)."""
    base = np.floor(p)
    f = p - base
    i = base.astype(np.int64)
    u = f * f * f * (f * (f * 6 - 15) + 10)
    out = np.zeros(p.shape[:-1])
    for dx in (0, 1):
        wx = u[..., 0] if dx else 1 - u[..., 0]
        for dy in (0, 1):
            wy = u[..., 1] if dy else 1 - u[..., 1]
            for dz in (0, 1):
                wz = u[..., 2] if dz else 1 - u[..., 2]
                v = _hash01(seed, i[..., 0] + dx, i[..., 1] + dy, i[..., 2] + dz)
                out += wx * wy * wz * (2 * v - 1)
    return out


def fbm3(p: Array, seed: int, octaves: int, frequency: float, gain: float = 0.5) -> Array:
    total = np.zeros(p.shape[:-1])
    amplitude, norm = 1.0, 0.0
    for octave in range(octaves):
        total += amplitude * value_noise3(p * frequency * 2**octave, seed + 1013 * octave)
        norm += amplitude
        amplitude *= gain
    return total / norm


def unit_vectors(lon: Array, lat: Array) -> Array:
    return np.stack(
        (np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)), axis=-1
    )


@dataclass(frozen=True, slots=True)
class WorldSpec:
    seed: int = 7
    columns: int = 2048
    land_fraction: float = 0.3
    continents: int = 6
    min_island_cells: int = 6
    radius_km: float = 6371.0


def land_mask(spec: WorldSpec) -> NDArray[np.bool_]:
    rows = spec.columns // 2
    lon = (np.arange(spec.columns) + 0.5) / spec.columns * 2 * pi - pi
    lat = pi / 2 - (np.arange(rows) + 0.5) / rows * pi
    p = unit_vectors(*np.meshgrid(lon, lat))
    warp = np.stack([fbm3(p, spec.seed + 50 + k, 4, 1.7) for k in range(3)], axis=-1)
    q = p + 0.45 * warp
    # Continental scale plus coastal detail; the warp creates peninsulas and gulfs.
    field = fbm3(q, spec.seed, 9, 1.25, 0.52)
    weights = np.cos(lat)[:, None] * np.ones((1, spec.columns))
    order = np.argsort(field, axis=None)[::-1]
    cumulative = np.cumsum(weights.ravel()[order]) / weights.sum()
    threshold = field.ravel()[order][np.searchsorted(cumulative, spec.land_fraction)]
    return field > threshold


def _wrapped_labels(mask: NDArray[np.bool_]) -> tuple[NDArray[np.int64], int]:
    result: tuple[NDArray[np.int32], int] = ndimage.label(  # pyright: ignore[reportAssignmentType]
        mask, structure=np.ones((3, 3))
    )
    labels, count = result
    # Merge components that touch across the longitude seam.
    parent = list(range(count + 1))

    def root(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    left, right = labels[:, 0], labels[:, -1]
    for r in range(len(left)):
        for rr in (r - 1, r, r + 1):
            if 0 <= rr < len(right) and left[r] and right[rr]:
                a, b = root(int(left[r])), root(int(right[rr]))
                if a != b:
                    parent[max(a, b)] = min(a, b)
    remap = np.array([root(i) for i in range(count + 1)], dtype=np.int64)
    return remap[labels], count


def _chaikin(ring: Array, iterations: int = 2) -> Array:
    for _ in range(iterations):
        a, b = ring[:-1], np.roll(ring[:-1], -1, axis=0)
        new = np.empty((2 * len(a), 2))
        new[0::2] = 0.75 * a + 0.25 * b
        new[1::2] = 0.25 * a + 0.75 * b
        ring = np.vstack((new, new[:1]))
    return ring


def _smooth_polygon(polygon: Polygon, scale: float, tolerance: float) -> Polygon | None:
    def ring(coords: object) -> Array:
        array = np.asarray(coords, dtype=np.float64) * scale
        return _chaikin(array)

    exterior = ring(polygon.exterior.coords)
    holes = [ring(h.coords) for h in polygon.interiors if Polygon(h).area * scale * scale > 4]
    # Polar and seam edges must stay on the frame: snap near-edge vertices.
    for array in (exterior, *holes):
        array[:, 0] = np.where(array[:, 0] < 0.6, 0.0, array[:, 0])
        array[:, 0] = np.where(array[:, 0] > WIDTH - 0.6, WIDTH, array[:, 0])
        array[:, 1] = np.where(array[:, 1] < 0.6, 0.0, array[:, 1])
        array[:, 1] = np.where(array[:, 1] > HEIGHT - 0.6, HEIGHT, array[:, 1])
    result = Polygon(exterior, holes).simplify(tolerance, preserve_topology=True)
    if not result.is_valid:
        result = result.buffer(0)
    if isinstance(result, MultiPolygon):
        result = max(result.geoms, key=lambda g: g.area)
    return result if isinstance(result, Polygon) and not result.is_empty else None


def _path(polygon: Polygon) -> str:
    def ring(coords: object) -> str:
        points = np.asarray(coords)[:-1]
        body = " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)
        return f"M {body} Z"

    return " ".join([ring(polygon.exterior.coords), *(ring(h.coords) for h in polygon.interiors)])


def world_svg(spec: WorldSpec) -> str:
    mask = land_mask(spec)
    labels, _ = _wrapped_labels(mask)
    rows = mask.shape[0]
    scale = WIDTH / spec.columns
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    ranked = [int(i) for i in np.argsort(sizes)[::-1] if sizes[i] > 0]
    mainland = ranked[: spec.continents]
    # Area-weighted centroids on the sphere decide island ownership.
    lat = pi / 2 - (np.arange(rows) + 0.5) / rows * pi
    lon = (np.arange(spec.columns) + 0.5) / spec.columns * 2 * pi - pi
    vectors = unit_vectors(*np.meshgrid(lon, lat))
    centroids = {}
    for label in ranked:
        selected = labels == label
        v = vectors[selected].sum(axis=0)
        centroids[label] = v / np.linalg.norm(v)
    owner = {}
    for label in ranked:
        if sizes[label] < spec.min_island_cells and label not in mainland:
            continue
        owner[label] = (
            label
            if label in mainland
            else max(mainland, key=lambda m: float(centroids[m] @ centroids[label]))
        )
    groups: dict[int, tuple[list[str], list[str]]] = {m: ([], []) for m in mainland}
    shape_id = 0
    shapes = features.shapes(labels.astype(np.int32), mask=labels > 0, connectivity=8)
    for geometry, value in shapes:
        label = int(value)
        if label not in owner:
            continue
        outline = shape(geometry)
        if not isinstance(outline, Polygon):
            continue
        polygon = _smooth_polygon(outline, scale, tolerance=0.35)
        if polygon is None or polygon.area < 1.0:
            continue
        shape_id += 1
        path = f'<path id="land-{shape_id:04d}" d="{_path(polygon)}"/>'
        main, islands = groups[owner[label]]
        (main if label in mainland else islands).append(path)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:serif="http://www.serif.com/" '
        f'width="{WIDTH:g}" height="{HEIGHT:g}" viewBox="0 0 {WIDTH:g} {HEIGHT:g}">'
    ]
    for index, label in enumerate(mainland):
        name = NAMES[index % len(NAMES)]
        main, islands = groups[label]
        parts.append(f'<g id="{name}"><g id="land-shapes-{index}" serif:id="Land Shapes">')
        parts.extend(main)
        if islands:
            parts.append(f'<g id="islands-{index}" serif:id="islands">')
            parts.extend(islands)
            parts.append("</g>")
        parts.append("</g></g>")
    parts.append("</svg>")
    return "\n".join(parts)


def build_world(spec: WorldSpec, directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    svg = world_svg(spec)
    svg_path = directory / f"{name}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    source = parse_world_svg(svg, svg_path.name)
    continents, assignments = propose_group_assignments(source)
    project = WorldProject(
        name.replace("-", " ").title(),
        source,
        WorldFrame(source.suggested_bounds, spec.radius_km),
        continents,
        assignments,
    )
    destination = directory / f"{name}.world.json"
    save_world(project, destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--columns", type=int, default=2048)
    parser.add_argument("--land-fraction", type=float, default=0.3)
    parser.add_argument("--continents", type=int, default=6)
    parser.add_argument("--radius-km", type=float, default=6371.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", default="fractal-world")
    args = parser.parse_args()
    spec = WorldSpec(
        args.seed, args.columns, args.land_fraction, args.continents, radius_km=args.radius_km
    )
    path = build_world(spec, args.output, args.name)
    print(path)


if __name__ == "__main__":
    main()
