"""Generate, preview and publish whole-planet relief from a world (experimental M2)."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from PIL import Image

from dmtools.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from dmtools.terrain.adapters.planet_build import write_planet_build
from dmtools.terrain.adapters.planet_render import render_previews
from dmtools.terrain.adapters.world_geology import geology_document, read_geology
from dmtools.terrain.adapters.world_project import read_world_project, world_project_document
from dmtools.terrain.adapters.world_svg import parse_world_svg
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.domain.world import WorldProject
from dmtools.terrain.domain.world_geology import WorldGeologyRecipe
from dmtools.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled
from dmtools.terrain.pipeline.planet import PlanetResult, generate_planet
from dmtools.terrain.pipeline.world import prepare_world_map

DEFAULT_RASTER_WIDTH = 4096
DEFAULT_PREVIEW_WIDTH = 2048
DEFAULT_RIVER_KM2 = 25_000.0


@dataclass(frozen=True)
class PlanetRun:
    """A generated planet with the identities needed to publish it unchanged."""

    result: PlanetResult
    runtime: dict[str, object]
    inputs: dict[str, str | None]
    previews: dict[str, Image.Image]


def input_identity(
    project: WorldProject, geology: WorldGeologyRecipe | None
) -> dict[str, str | None]:
    """Hashes of the canonical input documents (independent of file formatting)."""
    return {
        "world_sha256": sha256(canonical_json(world_project_document(project))).hexdigest(),
        "geology_sha256": None if geology is None
        else sha256(canonical_json(geology_document(geology))).hexdigest(),
    }


def generate_planet_run(
    project: WorldProject,
    geology_path: Path | None,
    settings: PlanetSettings,
    progress: ProgressCallback | None = None,
    *,
    preview_width: int = DEFAULT_PREVIEW_WIDTH,
    river_km2: float = DEFAULT_RIVER_KM2,
    cancellation: CancellationToken | None = None,
) -> PlanetRun:
    check_cancelled(cancellation)
    runtime = runtime_identity()
    if parse_world_svg(project.source.svg, project.source.name) != project.source:
        raise ValueError("World source snapshot and geometry disagree; import again.")
    recipe = None
    if geology_path is not None:
        recipe, _ = read_geology(geology_path)
        if recipe.world != project:
            raise ValueError("The geology recipe belongs to a different world; open its world.")
    world = prepare_world_map(project)
    result = generate_planet(world, settings, recipe, progress, cancellation=cancellation)
    previews = render_previews(result, preview_width, river_km2) if preview_width else {}
    if runtime_identity() != runtime:
        raise ValueError("Software changed during planet generation; generate again.")
    check_cancelled(cancellation)
    return PlanetRun(result, runtime, input_identity(project, recipe), previews)


def export_planet(
    run: PlanetRun,
    destination: Path,
    *,
    width: int = DEFAULT_RASTER_WIDTH,
    river_km2: float = DEFAULT_RIVER_KM2,
    cancellation: CancellationToken | None = None,
) -> Path:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Planet destination already exists: {destination}")
    if not river_km2 > 0:
        raise ValueError("River threshold must be a positive area in km².")

    def verify() -> None:
        check_cancelled(cancellation)
        if runtime_identity() != run.runtime:
            raise ValueError("Software changed after planet generation; generate again.")

    return write_planet_build(
        run.result, run.runtime, run.inputs, destination, width=width, river_km2=river_km2,
        verify=verify,
    )


def build_planet(
    world_path: Path,
    destination: Path,
    geology_path: Path | None = None,
    settings: PlanetSettings | None = None,
    *,
    width: int = DEFAULT_RASTER_WIDTH,
    river_km2: float = DEFAULT_RIVER_KM2,
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> Path:
    """Generate and publish a new planet build; the destination must not exist."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Planet destination already exists: {destination}")
    if not river_km2 > 0:
        raise ValueError("River threshold must be a positive area in km².")
    check_cancelled(cancellation)
    files = {
        path: file_sha256(path) for path in (world_path, geology_path) if path is not None
    }
    run = generate_planet_run(
        read_world_project(world_path), geology_path, settings or PlanetSettings(), progress,
        preview_width=0, river_km2=river_km2, cancellation=cancellation,
    )
    for path, digest in files.items():
        if file_sha256(path) != digest:
            raise ValueError(f"{path.name} changed during planet generation; generate again.")
    return export_planet(
        run, destination, width=width, river_km2=river_km2, cancellation=cancellation
    )
