"""Run a bounded regional sampling request from a saved project."""

from pathlib import Path

from map_maker.terrain.adapters.build import file_sha256, runtime_identity
from map_maker.terrain.adapters.project import load_terrain_project
from map_maker.terrain.adapters.regional import publish_regional_manifest, write_regional_products
from map_maker.terrain.domain import EndpointGrid, LocalMetricFrame
from map_maker.terrain.domain.coordinates import Bounds
from map_maker.terrain.domain.regional import RegionalSamplingRequest
from map_maker.terrain.pipeline.control import (
    CancellationToken,
    cancellable_progress,
    check_cancelled,
)
from map_maker.terrain.pipeline.generate import ProgressCallback
from map_maker.terrain.pipeline.regional import prepare_regional_sampler, sampling_source_id


def sample_terrain_region(
    source: Path, destination: Path, bounds_km: Bounds, refinement: int, *,
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> Path:
    """Reserve a fresh result directory after validating the halo-inclusive request budget."""
    check_cancelled(cancellation)
    progress = cancellable_progress(progress, cancellation)
    target = destination.absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Regional destination already exists: {target}")
    project_hash = file_sha256(source)
    loaded = load_terrain_project(source)
    project = loaded.project
    frame = LocalMetricFrame(project.coastline.bounds, project.settings.object_scale_km)
    grid = EndpointGrid.for_extent(frame.extent_km, project.settings.resolution_px)
    request = RegionalSamplingRequest.for_bounds(
        sampling_source_id(project.coastline, project.settings, project.constraints,
                           world_context=project.world_context),
        grid, bounds_km, refinement,
    )
    runtime = runtime_identity()

    def verify_inputs() -> None:
        if (file_sha256(source) != project_hash
                or file_sha256(loaded.coastline_source.path) != loaded.coastline_source.sha256):
            raise ValueError("Project or coastline changed during regional sampling; retry.")

    verify_inputs()
    check_cancelled(cancellation)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    sampler = prepare_regional_sampler(project.coastline, project.settings,
                                       constraints=project.constraints, progress=progress,
                                       world_context=project.world_context)
    samples = sampler.sample(request, progress)
    check_cancelled(cancellation)
    outputs = write_regional_products(samples, project, target)
    verify_inputs()
    if runtime_identity() != runtime:
        raise ValueError("Generator source or runtime changed during regional sampling; retry.")
    check_cancelled(cancellation)
    return publish_regional_manifest(
        samples, project, target, requested_bounds_km=bounds_km, project_sha256=project_hash,
        svg_sha256=loaded.coastline_source.sha256, runtime=runtime, outputs=outputs,
    )
