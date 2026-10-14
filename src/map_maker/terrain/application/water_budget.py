"""Forecast saved-project water sampling without creating a terrain build."""

from dataclasses import dataclass
from pathlib import Path

from map_maker.terrain.adapters.build import file_sha256, runtime_identity
from map_maker.terrain.adapters.project import load_terrain_project
from map_maker.terrain.pipeline.generate import forecast_water_sampling
from map_maker.terrain.pipeline.water_budget import WaterSamplingBudget


@dataclass(frozen=True, slots=True)
class ProjectWaterBudget:
    project_path: Path
    project_sha256: str
    coastline_sha256: str
    runtime: dict[str, object]
    budget: WaterSamplingBudget


def forecast_project_water_budget(source: Path) -> ProjectWaterBudget:
    """Bind the forecast to unchanged saved inputs and installed generator source."""
    source = source.absolute()
    project_hash = file_sha256(source)
    loaded = load_terrain_project(source)
    runtime = runtime_identity()

    def verify_inputs() -> None:
        if (file_sha256(source) != project_hash
                or file_sha256(loaded.coastline_source.path) != loaded.coastline_source.sha256):
            raise ValueError("Project or coastline changed during the forecast; run it again.")

    verify_inputs()
    project = loaded.project
    budget = forecast_water_sampling(
        project.coastline, project.settings, constraints=project.constraints,
        world_context=project.world_context)
    verify_inputs()
    if runtime_identity() != runtime:
        raise ValueError("Generator source or runtime changed during the forecast; run it again.")
    return ProjectWaterBudget(source, project_hash, loaded.coastline_source.sha256, runtime, budget)
