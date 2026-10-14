"""Build a saved terrain project without starting the desktop workbench."""

from pathlib import Path

from map_maker.terrain.adapters.build import (
    file_sha256,
    publish_build_manifest,
    runtime_identity,
    write_build_products,
)
from map_maker.terrain.adapters.project import load_terrain_project
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.generate import ProgressCallback, generate_terrain
from map_maker.terrain.pipeline.quality import measure_terrain_quality


def build_terrain_project(
    source: Path,
    destination: Path,
    progress: ProgressCallback | None = None,
    *, cancellation: CancellationToken | None = None,
) -> Path:
    """Reserve a fresh directory and publish its manifest only on success.

    Failed builds deliberately retain partial products without a manifest.
    Existing destinations are never overwritten, reused, or recursively removed.
    """
    check_cancelled(cancellation)
    target = destination.absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Build destination already exists: {target}")
    project_hash = file_sha256(source)
    loaded = load_terrain_project(source)
    runtime = runtime_identity()

    def verify_inputs() -> None:
        if (
            file_sha256(source) != project_hash
            or file_sha256(loaded.coastline_source.path) != loaded.coastline_source.sha256
        ):
            raise ValueError("Project or coastline changed during the build; start a new build.")

    verify_inputs()
    check_cancelled(cancellation)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()  # Exclusive reservation also handles competing builders.
    project = loaded.project
    terrain = generate_terrain(
        project.coastline, project.settings, progress, constraints=project.constraints,
        cancellation=cancellation, world_context=project.world_context,
    )
    check_cancelled(cancellation)
    quality = measure_terrain_quality(
        terrain.elevation_m,
        terrain.land_mask,
        x_spacing_km=terrain.grid.x_spacing_km,
        y_spacing_km=terrain.grid.y_spacing_km,
    )
    check_cancelled(cancellation)
    outputs = write_build_products(terrain, project, quality, target)
    verify_inputs()
    if runtime_identity() != runtime:
        raise ValueError("Generator source or runtime changed during the build; start a new build.")
    check_cancelled(cancellation)
    return publish_build_manifest(
        terrain,
        project,
        target,
        project_sha256=project_hash,
        svg_sha256=loaded.coastline_source.sha256,
        runtime=runtime,
        outputs=outputs,
    )
