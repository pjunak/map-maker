# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Landform scale metrics of a planet build, for comparison with Earth.

Measures the sizes the eye judges on a world map: continent areas, river
main-stem length against basin area (Hack's law), how much of a continent its
largest basin drains, mountain-belt widths and the spacing of river mouths
along the coast. Lengths follow mesh edges, so they include the mesh's own
path sinuosity (about 5-10 %).

Usage::

    python -m benchmarks.planet.scale_metrics BUILD_FOLDER [--json OUT]
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import KDTree

from dmtools.terrain.pipeline.planet_kernels import flow_length, multi_source_distance
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, mesh_from_triangles

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

KM2 = 1e6


@dataclass(frozen=True)
class Build:
    mesh: SphereMesh
    land: B
    elevation_m: F64
    receiver: I64
    area_m2: F64


def load(folder: Path) -> Build:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    radius_m = float(manifest["world_frame"]["radius_km"]) * 1000
    with np.load(folder / "planet.npz", allow_pickle=False) as data:
        mesh = mesh_from_triangles(
            data["xyz"].astype(np.float64), data["triangles"].astype(np.int64), radius_m
        )
        return Build(
            mesh,
            data["land"].astype(bool),
            data["elevation_m"].astype(np.float64),
            data["receiver"].astype(np.int64),
            data["contributing_area_m2"].astype(np.float64),
        )


def components(mesh: SphereMesh, mask: B) -> I64:
    """Connected-component label per node of ``mask`` (-1 elsewhere)."""
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    keep = mask[src] & mask[mesh.nbr]
    graph = coo_matrix(
        (np.ones(int(keep.sum())), (src[keep], mesh.nbr[keep])), shape=(mesh.size, mesh.size)
    )
    _, labels = connected_components(graph, directed=False)
    return np.where(mask, labels, -1).astype(np.int64)


def receiver_distance(mesh: SphereMesh, receiver: I64) -> F64:
    valid = receiver >= 0
    target = np.where(valid, receiver, np.arange(mesh.size))
    cosine = np.clip(np.einsum("ij,ij->i", mesh.xyz, mesh.xyz[target]), -1, 1)
    return np.where(valid, mesh.radius_m * np.arccos(cosine), 0.0)


def downstream_first(receiver: I64, land: B) -> I64:
    """Land nodes ordered so that every receiver precedes its donors."""
    valid = land & (receiver >= 0) & land[np.maximum(receiver, 0)]
    donors = np.flatnonzero(valid)
    targets = receiver[donors]
    sort = np.argsort(targets, kind="stable")
    ptr = np.searchsorted(targets[sort], np.arange(receiver.size + 1))
    children = donors[sort]
    order = list(np.flatnonzero(land & ~valid))
    head = 0
    while head < len(order):
        node = order[head]
        head += 1
        order.extend(children[ptr[node] : ptr[node + 1]].tolist())
    return np.asarray(order, dtype=np.int64)


def rivers(build: Build, continent: I64) -> dict[str, object]:
    mesh, land = build.mesh, build.land
    receiver = build.receiver
    distance = receiver_distance(mesh, receiver)
    upstream = flow_length(downstream_first(receiver, land), receiver, ~land, distance)
    mouths = np.flatnonzero(land & (receiver >= 0) & ~land[np.maximum(receiver, 0)])
    area_km2 = build.area_m2[mouths] / KM2
    length_km = (upstream[mouths] + distance[mouths]) / 1e3
    big = area_km2 >= 1e4
    slope, intercept = np.polyfit(np.log10(area_km2[big]), np.log10(length_km[big]), 1)
    continent_area = np.bincount(
        continent[land], mesh.area_m2[land], int(continent.max()) + 1
    ) / KM2
    top = np.argsort(-area_km2)[:12]
    return {
        "hack_fit_A_ge_1e4_km2": {"exponent": float(slope), "coefficient": float(10**intercept)},
        "rivers_longer_than_km": {
            str(limit): int(np.sum(length_km > limit)) for limit in (500, 1000, 2000, 3000)
        },
        "largest_basins": [
            {
                "area_km2": round(float(area_km2[i])),
                "main_stem_km": round(float(length_km[i])),
                "L_over_sqrtA": round(float(length_km[i] / np.sqrt(area_km2[i])), 2),
                "share_of_continent": round(
                    float(area_km2[i] / continent_area[continent[mouths[i]]]), 3
                ),
            }
            for i in top
        ],
    }


def mountains(build: Build, continent: I64) -> dict[str, object]:
    """Belts of high or rugged ground; half-width from the distance to their edge."""
    mesh, land, z = build.mesh, build.land, build.elevation_m
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    high = np.full(mesh.size, -np.inf)
    low = np.full(mesh.size, np.inf)
    np.maximum.at(high, src, z[mesh.nbr])
    np.minimum.at(low, src, z[mesh.nbr])
    local_range = np.maximum(high, z) - np.minimum(low, z)
    mountain = land & ((z > 1500) | ((z > 1000) & (local_range > 300)))
    seeds = np.flatnonzero(~mountain)
    inside = multi_source_distance(
        seeds, np.zeros(seeds.size), mesh.ptr, mesh.nbr, mesh.length_m
    )
    label = components(mesh, mountain)
    belts: list[dict[str, int]] = []
    for value in np.unique(label[label >= 0]):
        nodes = label == value
        area = float(mesh.area_m2[nodes].sum() / KM2)
        if area < 2e4:
            continue
        mean_inside = float(np.average(inside[nodes], weights=mesh.area_m2[nodes]))
        width = 4 * mean_inside / 1e3  # a strip of width w has mean edge distance w / 4
        belts.append(
            {
                "area_km2": round(area),
                "width_km": round(width),
                "max_half_width_km": round(float(inside[nodes].max()) / 1e3),
                "length_km": round(area / max(width, 1e-6)),
            }
        )
    belts.sort(key=lambda belt: -belt["area_km2"])
    # Valley spacing: mountain area over the length of valleys draining at least
    # ``threshold`` (parallel valleys s apart have drainage density 1 / s).
    distance = receiver_distance(mesh, build.receiver)
    spacing = {}
    for threshold in (500, 2_500, 10_000):
        channel = mountain & (build.area_m2 >= threshold * KM2)
        length = float(distance[channel].sum())
        spacing[str(threshold)] = round(float(mesh.area_m2[mountain].sum()) / max(length, 1) / 1e3)
    widths = np.array([b["width_km"] for b in belts], dtype=float)
    weights = np.array([b["area_km2"] for b in belts], dtype=float)
    return {
        "mountain_share_of_land": round(
            float(mesh.area_m2[mountain].sum() / mesh.area_m2[land].sum()), 3
        ),
        "belts": len(belts),
        "area_weighted_width_km": round(float(np.average(widths, weights=weights)))
        if belts
        else None,
        "valley_spacing_km_by_min_area_km2": spacing,
        "largest_belts": belts[:10],
    }


def mouth_spacing(build: Build, minimum_km2: float) -> float:
    """Median distance (km) from each river mouth to its nearest neighbour mouth."""
    mesh, land, receiver = build.mesh, build.land, build.receiver
    mouths = np.flatnonzero(
        land
        & (receiver >= 0)
        & ~land[np.maximum(receiver, 0)]
        & (build.area_m2 >= minimum_km2 * KM2)
    )
    _, found = KDTree(mesh.xyz[mouths]).query(mesh.xyz[mouths], k=2)
    nearest = np.asarray(found, dtype=np.int64)[:, 1]
    chord = np.linalg.norm(mesh.xyz[mouths] - mesh.xyz[mouths[nearest]], axis=1)
    return float(np.median(2 * np.arcsin(chord / 2) * mesh.radius_m / 1e3))


def report(build: Build) -> dict[str, object]:
    mesh, land = build.mesh, build.land
    continent = components(mesh, land)
    areas = np.bincount(continent[land], mesh.area_m2[land]) / KM2
    return {
        "mesh_spacing_km": round(mesh.spacing_m / 1e3, 1),
        "continents_km2": sorted((round(float(a)) for a in areas if a > 1e6), reverse=True),
        "rivers": rivers(build, continent),
        "mountains": mountains(build, continent),
        "mouth_spacing_km": {
            str(limit): round(mouth_spacing(build, limit)) for limit in (2_500, 10_000, 50_000)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Landform scale metrics of a planet build.")
    parser.add_argument("build", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = report(load(args.build))
    text = json.dumps(result, indent=2)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
