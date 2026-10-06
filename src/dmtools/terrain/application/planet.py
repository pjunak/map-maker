"""Generate and publish whole-planet relief from a saved world (experimental M2)."""

from pathlib import Path

from dmtools.terrain.adapters.build import file_sha256, runtime_identity
from dmtools.terrain.adapters.planet_build import write_planet_build
from dmtools.terrain.adapters.world_geology import read_geology
from dmtools.terrain.application.world import open_world
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled
from dmtools.terrain.pipeline.planet import PlanetResult, generate_planet

DEFAULT_RASTER_WIDTH = 4096
DEFAULT_RIVER_KM2 = 25_000.0


def generate_planet_from_files(
    world_path: Path,
    geology_path: Path | None,
    settings: PlanetSettings,
    progress: ProgressCallback | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> PlanetResult:
    world = open_world(world_path)
    recipe = None
    if geology_path is not None:
        recipe, _ = read_geology(geology_path)
        if recipe.world != world.project:
            raise ValueError("The geology recipe belongs to a different world; open its world.")
    return generate_planet(world, settings, recipe, progress, cancellation=cancellation)


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
    inputs: dict[str, str | None] = {
        "world_sha256": file_sha256(world_path),
        "geology_sha256": None if geology_path is None else file_sha256(geology_path),
    }
    runtime = runtime_identity()
    result = generate_planet_from_files(
        world_path, geology_path, settings or PlanetSettings(), progress, cancellation=cancellation
    )

    def verify() -> None:
        check_cancelled(cancellation)
        if runtime_identity() != runtime:
            raise ValueError("Software changed during planet generation; generate again.")
        for path, key in ((world_path, "world_sha256"), (geology_path, "geology_sha256")):
            if path is not None and file_sha256(path) != inputs[key]:
                raise ValueError(f"{path.name} changed during planet generation; generate again.")

    return write_planet_build(
        result, runtime, inputs, destination, width=width, river_km2=river_km2, verify=verify
    )
