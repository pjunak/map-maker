# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Select physical land connected to a continent, including periodic world edges."""

from dataclasses import dataclass

from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.strtree import STRtree

from map_maker.terrain.domain.models import LandComponent
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.world import WorldMap


@dataclass(frozen=True, slots=True)
class WorldLandmass:
    requested_continent_id: str
    continent_ids: tuple[str, ...]
    feature_ids: tuple[str, ...]
    components: tuple[LandComponent, ...]


def select_landmass(
    world: WorldMap,
    continent_id: str,
    *,
    cancellation: CancellationToken | None = None,
) -> WorldLandmass:
    """A semantic border cannot become an artificial sea-level coastline.

    Start with every component owned by the requested continent, including its
    islands. Follow actual touching land transitively, not every distant island
    belonging to a newly encountered administrative neighbour.
    """
    check_cancelled(cancellation)
    if continent_id not in {c.id for c in world.project.continents}:
        raise ValueError("Choose a continent belonging to the current world.")
    records = [(land, part) for land in world.land for part in land.components]
    polygons = [Polygon(part.exterior, part.holes) for _, part in records]
    copies = list(polygons)
    owners = list(range(len(polygons)))
    frame = world.project.frame
    north: set[int] = set()
    south: set[int] = set()
    for i, polygon in enumerate(polygons):
        x0, y0, x1, y1 = polygon.bounds
        if x0 == frame.bounds[0]:
            copies.append(translate(polygon, xoff=frame.width))
            owners.append(i)
        if x1 == frame.bounds[2]:
            copies.append(translate(polygon, xoff=-frame.width))
            owners.append(i)
        if y0 == frame.bounds[1]:
            north.add(i)
        if y1 == frame.bounds[3]:
            south.add(i)
    tree = STRtree(copies)
    selected = {i for i, (land, _) in enumerate(records) if land.continent_id == continent_id}
    pending = list(sorted(selected))
    while pending:
        check_cancelled(cancellation)
        i = pending.pop()
        polygon = polygons[i]
        neighbours = {
            owners[int(j)] for j in tree.query(polygon) if polygon.intersects(copies[int(j)])
        }
        if i in north:
            neighbours.update(north)
        if i in south:
            neighbours.update(south)
        added = neighbours - selected
        selected.update(added)
        pending.extend(sorted(added))
    chosen = [records[i] for i in sorted(selected)]
    return WorldLandmass(
        continent_id,
        tuple(sorted({land.continent_id for land, _ in chosen})),
        tuple(sorted({land.feature_id for land, _ in chosen})),
        tuple(part for _, part in chosen),
    )
