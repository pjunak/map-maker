"""Validated world-map open/save and explicit proposed continent assignments."""

from hashlib import sha256
from pathlib import Path

from map_maker.terrain.adapters.world_project import read_world_project, write_world_project
from map_maker.terrain.adapters.world_refined_svg import (
    DEFAULT_DETAIL_KM,
    RefinedCoast,
    refined_coast,
    refined_coast_svg,
)
from map_maker.terrain.adapters.world_svg import drawn_coast_detail_km, parse_world_svg
from map_maker.terrain.domain.world import (
    WorldAssignment,
    WorldContinent,
    WorldProject,
    WorldSource,
)
from map_maker.terrain.pipeline.control import CancellationToken, ProgressCallback
from map_maker.terrain.pipeline.world import WorldMap, prepare_world_map


def open_world(path: Path) -> WorldMap:
    return prepare_world_map(read_world_project(path))


def save_world(project: WorldProject, path: Path) -> WorldMap:
    if parse_world_svg(project.source.svg, project.source.name) != project.source:
        raise ValueError("World source snapshot and inspection geometry disagree; import again.")
    result = prepare_world_map(project)
    write_world_project(project, path)
    return result


def export_refined_coast(
    world_path: Path,
    destination: Path,
    *,
    master_seed: int,
    detail_km: float = DEFAULT_DETAIL_KM,
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> RefinedCoast:
    """Write the world's coast as zoomed maps draw it into a new SVG source map.

    The coast depends on the planet's master seed. The SVG imports as a world
    whose coast already carries ``detail_km``; the destination must not exist.
    """
    if destination.suffix.lower() != ".svg":
        raise ValueError("Export the refined coast to an .svg file.")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refined coast destination already exists: {destination}")
    coast = refined_coast(
        read_world_project(world_path), master_seed, detail_km, progress, cancellation
    )
    text = refined_coast_svg(coast, master_seed)
    # The export is only useful if it imports: check before writing.
    parse_world_svg(text, destination.name)
    if drawn_coast_detail_km(text) != coast.detail_km:
        raise ValueError("The refined coast SVG lost its coast detail declaration.")
    pending = destination.with_name(f".{destination.name}.pending")
    pending.write_text(text, encoding="utf-8")
    if destination.exists():
        pending.unlink()
        raise FileExistsError(f"Refined coast destination already exists: {destination}")
    pending.replace(destination)
    return coast


def continent_from_name(name: str) -> WorldContinent:
    name = name.strip()
    return WorldContinent("continent-" + sha256(name.encode("utf-8")).hexdigest()[:20], name)


def propose_group_assignments(
    source: WorldSource,
) -> tuple[tuple[WorldContinent, ...], tuple[WorldAssignment, ...]]:
    """User-invoked suggestion only; unnamed/unclassified shapes remain unresolved."""
    continents: dict[str, WorldContinent] = {}
    assignments: list[WorldAssignment] = []

    def normalized(value: str) -> str:
        return "".join(c for c in value.casefold() if c.isalnum())

    explicit_land = any("landshapes" in tuple(map(normalized, f.groups)) for f in source.features)
    for feature in source.features:
        groups = tuple(map(normalized, feature.groups))
        if "mapfurniture" in groups or (explicit_land and "landshapes" not in groups):
            assignments.append(WorldAssignment(feature.id, None, "exclude"))
            continue
        if feature.issue or not feature.groups:
            continue
        # The continent owns the Land Shapes layer. Named/anonymous wrappers
        # inside that layer organize geometry; they cannot create new owners.
        ancestors = (
            feature.groups[: groups.index("landshapes")]
            if "landshapes" in groups
            else feature.groups
        )
        names = [name for name in ancestors if normalized(name) not in {"islands", "mainland"}]
        if not names:
            continue
        name = names[-1]
        continent = continent_from_name(name)
        continents[continent.id] = continent
        role = "island" if "islands" in groups else "mainland"
        assignments.append(WorldAssignment(feature.id, continent.id, role))
    return tuple(sorted(continents.values(), key=lambda c: c.id)), tuple(assignments)
