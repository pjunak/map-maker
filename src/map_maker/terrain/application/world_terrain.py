"""Create a usable terrain project from physical land in a retained world."""

from dataclasses import dataclass, replace
from pathlib import Path

from map_maker.terrain.adapters.project import (
    LoadedTerrainProject,
    save_terrain_project,
)
from map_maker.terrain.adapters.svg import load_svg_coastline_source
from map_maker.terrain.adapters.world_context_sampling import bind_world_context
from map_maker.terrain.adapters.world_landforms import compile_landforms
from map_maker.terrain.adapters.world_projection import project_landmass
from map_maker.terrain.adapters.world_terrain_source import MAX_SOURCE_BYTES, source_svg
from map_maker.terrain.application.world_context import WorldContextRun
from map_maker.terrain.application.world_geology import resolve_for_world
from map_maker.terrain.domain import TerrainProject, TerrainSettings
from map_maker.terrain.domain.world import WorldProject
from map_maker.terrain.domain.world_geology import WorldGeologyRecipe
from map_maker.terrain.domain.world_terrain import WorldTerrainSource
from map_maker.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled
from map_maker.terrain.pipeline.world import prepare_world_map
from map_maker.terrain.pipeline.world_landmass import select_landmass


@dataclass(frozen=True, slots=True)
class WorldTerrainCreated:
    loaded: LoadedTerrainProject
    source: WorldTerrainSource


def create_world_terrain_project(
    world: WorldProject,
    continent_id: str,
    output: Path,
    *,
    settings: TerrainSettings | None = None,
    geology: WorldGeologyRecipe | None = None,
    context: WorldContextRun | None = None,
    cancellation: CancellationToken | None = None,
    progress: ProgressCallback | None = None,
) -> WorldTerrainCreated:
    """Publish initial terrain inputs with optional context; climate and aging follow later."""

    def report(fraction: float, text: str) -> None:
        check_cancelled(cancellation)
        if progress:
            progress(fraction, text)
        check_cancelled(cancellation)

    target = output.absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError("Choose a new terrain project folder; existing files are preserved.")
    report(0.05, "Validating world geography…")
    prepared = prepare_world_map(world)
    report(0.2, "Collecting connected land and islands…")
    land = select_landmass(prepared, continent_id, cancellation=cancellation)
    report(0.4, "Projecting coastlines into metres…")
    source = project_landmass(prepared, land, cancellation=cancellation)
    settings = replace(
        settings or TerrainSettings(resolution_px=257), object_scale_km=source.object_scale_km
    )
    constraints = ()
    if geology is not None:
        report(0.65, "Transferring geological landform guidance…")
        coverage = resolve_for_world(geology, prepared, cancellation)
        constraints = compile_landforms(
            coverage, land, source, maximum_elevation_m=settings.maximum_elevation_m,
            cancellation=cancellation,
        )
        source = replace(source, geology=coverage.recipe)
    report(0.75, "Binding geographic context to metric terrain…")
    bound_context = None if context is None else bind_world_context(
        source, context.context, context.runtime, cancellation=cancellation,
    )
    report(0.8, "Preparing the terrain project…")
    encoded = source_svg(source)
    if len(encoded) > MAX_SOURCE_BYTES:
        raise ValueError("World-derived terrain source exceeds 64 MiB.")
    check_cancelled(cancellation)
    target.mkdir(parents=True, exist_ok=False)
    coastline_path = target / "coastline.svg"
    with coastline_path.open("xb") as stream:
        stream.write(encoded)
    verified = load_svg_coastline_source(coastline_path)
    if verified.coastline != source.coastline:
        raise RuntimeError("World-to-terrain transfer changed projected coastlines.")
    report(0.95, "Saving the terrain project…")
    project = TerrainProject(verified.coastline, settings, constraints,
                             world_context=bound_context)
    path = target / "terrain.terrain.json"
    # Completion is the current project file. Failed or cancelled preparation
    # leaves only source material in this new directory, never a usable project.
    save_terrain_project(project, verified, path)
    loaded = LoadedTerrainProject(project, verified, path.resolve())
    if verified.world_terrain is None:
        raise RuntimeError("Prepared source lost its world identity.")
    return WorldTerrainCreated(loaded, verified.world_terrain)
