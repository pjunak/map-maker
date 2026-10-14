"""A deterministic sample geology recipe for a synthetic world (development fixture).

The two largest continents get old stable interiors with a young active belt, a
plateau and a sedimentary basin placed around their spherical centroids; the
remaining continents stay unspecified, so they use procedural forcing.
"""

from __future__ import annotations

import argparse
from math import cos, radians, sin
from pathlib import Path

import numpy as np

from map_maker.terrain.adapters.world_geology import write_geology
from map_maker.terrain.adapters.world_project import read_world_project
from map_maker.terrain.application.world import open_world
from map_maker.terrain.domain.models import LandformSettings, Point2D
from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_geology import (
    ContinentGeology,
    GeologyProfile,
    GeologyProvince,
    WorldGeologyRecipe,
)
from map_maker.terrain.pipeline.world import WorldMap


def _centroid(world: WorldMap, continent_id: str) -> tuple[float, float]:
    frame = world.project.frame
    vectors: list[np.ndarray[tuple[int], np.dtype[np.float64]]] = []
    for view in world.land:
        if view.continent_id != continent_id:
            continue
        for component in view.components:
            for x, y in component.exterior:
                lon, lat = map(radians, frame.source_to_lonlat((x, y)))
                vectors.append(np.array([cos(lat) * cos(lon), cos(lat) * sin(lon), sin(lat)]))
    v = np.sum(vectors, axis=0)
    v /= np.linalg.norm(v)
    return float(np.degrees(np.arctan2(v[1], v[0]))), float(np.degrees(np.arcsin(v[2])))


def _ellipse(
    frame: WorldFrame, centre: tuple[float, float], a_deg: float, b_deg: float, angle_deg: float
) -> tuple[Point2D, ...]:
    lon0, lat0 = centre
    points: list[Point2D] = []
    anchor = frame.lonlat_to_source((lon0, lat0))
    for k in range(24):
        t = 2 * np.pi * k / 24
        u, v = a_deg * np.cos(t), b_deg * np.sin(t)
        c, s = cos(radians(angle_deg)), sin(radians(angle_deg))
        dlon = (u * c - v * s) / max(cos(radians(lat0)), 0.2)
        dlat = u * s + v * c
        lat = float(np.clip(lat0 + dlat, -89.0, 89.0))
        x, y = frame.lonlat_to_source((lon0 + dlon, lat), wrap=False)
        # Keep the polygon unwrapped around its anchor so seam crossings stay valid.
        points.append((anchor[0] + (x - anchor[0]), y))
    return tuple(points)


def sample_recipe(world_path: Path) -> WorldGeologyRecipe:
    project = read_world_project(world_path)
    world = open_world(world_path)
    frame = project.frame
    ranked = sorted(world.continents, key=lambda c: -c.area_km2)
    old = GeologyProfile("stable-interior", crust_age_ma=2200.0)
    defaults = tuple(
        ContinentGeology(c.id, old if i < 2 else GeologyProfile()) for i, c in enumerate(ranked)
    )
    provinces: list[GeologyProvince] = []
    for i, continent in enumerate(ranked[:2]):
        lon, lat = _centroid(world, continent.id)
        tag = f"c{i}"
        provinces.append(GeologyProvince(
            f"province-{tag}-belt", f"{continent.name} young belt",
            _ellipse(frame, (lon - 12, lat), 22, 3.0, 25 + 40 * i), 20,
            GeologyProfile("active-belt", 1500.0, rejuvenation_age_ma=15.0),
        ))
        provinces.append(GeologyProvince(
            f"province-{tag}-old-belt", f"{continent.name} worn belt",
            _ellipse(frame, (lon + 14, lat + 4), 16, 2.5, -30), 15,
            GeologyProfile("active-belt", 1800.0, rejuvenation_age_ma=320.0),
        ))
        provinces.append(GeologyProvince(
            f"province-{tag}-plateau", f"{continent.name} plateau",
            _ellipse(frame, (lon + 2, lat - 6), 6, 4, 0), 30,
            GeologyProfile(
                "stable-interior", 2000.0,
                landform=LandformSettings("plateau", 2200.0, 200.0, 200.0, 60.0),
            ),
        ))
        provinces.append(GeologyProvince(
            f"province-{tag}-basin", f"{continent.name} basin",
            _ellipse(frame, (lon + 4, lat + 9), 7, 5, 10), 10,
            GeologyProfile("sedimentary-basin"),
        ))
    return WorldGeologyRecipe(project, defaults, tuple(provinces))


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("world", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_geology(sample_recipe(args.world), args.output, None)
    print(args.output)


if __name__ == "__main__":
    main()
