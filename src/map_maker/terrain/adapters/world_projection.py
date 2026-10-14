# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Project retained spherical land through PROJ; never run terrain in page degrees."""

from math import atan2, degrees, hypot, pi

import numpy as np
from shapely import normalize
from shapely.geometry import Polygon
from shapely.ops import unary_union

from map_maker.terrain.adapters.world_geometry_projection import project_components
from map_maker.terrain.domain.models import Coastline, LandComponent
from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_terrain import (
    WorldTerrainProjection,
    WorldTerrainSource,
)
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.world import WorldMap, component_area_km2, components_from_geometry
from map_maker.terrain.pipeline.world_landmass import WorldLandmass


def _centre(parts: tuple[LandComponent, ...], frame: WorldFrame) -> tuple[float, float]:
    vectors = []
    for part in parts:
        centroid = Polygon(part.exterior, part.holes).centroid
        lon, lat = np.radians(frame.source_to_lonlat((centroid.x, centroid.y)))
        area = component_area_km2(part, frame)
        vectors.append(
            area * np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
        )
    vector = np.sum(vectors, axis=0)
    if not np.all(np.isfinite(vector)) or np.linalg.norm(vector) < 1e-8:
        raise ValueError("This land selection needs separate regional projection domains.")
    lon = (degrees(atan2(vector[1], vector[0])) + 180) % 360 - 180
    lat = degrees(atan2(vector[2], hypot(vector[0], vector[1])))
    return lon, lat


def project_landmass(
    world: WorldMap,
    land: WorldLandmass,
    *,
    cancellation: CancellationToken | None = None,
) -> WorldTerrainSource:
    check_cancelled(cancellation)
    frame = world.project.frame
    # Ownership partitions must not change the physical projection. Dissolve
    # before finding its centre; remove only exactly redundant collinear vertices
    # and normalize ring order so a split border cannot perturb the sampled coast.
    physical = normalize(
        unary_union([Polygon(p.exterior, p.holes) for p in land.components])
        .simplify(0.0, preserve_topology=True)
    )
    physical_parts = components_from_geometry(physical)
    total_area = sum(component_area_km2(p, frame) for p in physical_parts)
    if total_area >= 2 * pi * frame.radius_km**2:
        raise ValueError("A hemisphere-sized land selection needs separate regional domains.")
    lon, lat = _centre(physical_parts, frame)
    initial = WorldTerrainProjection(frame.radius_km, lon, lat, 0.0, 1.0)
    components, projection = project_components(
        physical_parts, frame, initial, cancellation=cancellation,
    )
    first = components[0]
    name = next(c.name for c in world.project.continents if c.id == land.requested_continent_id)
    coastline = Coastline(first.exterior, name, first.holes, components[1:])
    return WorldTerrainSource(
        world.project,
        land.requested_continent_id,
        land.continent_ids,
        land.feature_ids,
        coastline,
        projection,
    )
