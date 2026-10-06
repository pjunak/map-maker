"""Whole-planet generation: mesh -> forcing -> erosion -> climate coupling.

The world coastline is a hard boundary. Geology recipes are soft intent:
calibrated uplift targets shaped by erosion. Climate is provisional and only
weights erosion by relative runoff. Every random stream comes from a named stage
seed, so results do not depend on stage order.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree  # pyright: ignore[reportMissingTypeStubs]

from dmtools.terrain.domain.planet import (
    PLANET_FORCING_STAGE_ID,
    PLANET_INITIAL_STAGE_ID,
    PLANET_MESH_STAGE_ID,
    PlanetSettings,
)
from dmtools.terrain.domain.seeds import stage_seed
from dmtools.terrain.domain.world_geology import WorldGeologyRecipe
from dmtools.terrain.pipeline.control import (
    CancellationToken,
    ProgressCallback,
    cancellable_progress,
    check_cancelled,
)
from dmtools.terrain.pipeline.planet_climate import Climate, simulate_climate
from dmtools.terrain.pipeline.planet_evolution import (
    CalibratedRelief,
    FlowState,
    RegionRecord,
    StepCallback,
    calibrated_relief,
)
from dmtools.terrain.pipeline.planet_forcing import (
    Forcing,
    GeologyRegions,
    coast_distance,
    geology_regions,
    land_on_mesh,
    ocean_floor,
)
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, build_mesh
from dmtools.terrain.pipeline.planet_metrics import relief_metrics
from dmtools.terrain.pipeline.world import WorldMap

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

RUNOFF_WEIGHT_FLOOR = 0.05
CALIBRATION_NODES = 100_000


@dataclass(frozen=True, slots=True)
class _MeshInputs:
    mesh: SphereMesh
    land: B
    coast_m: F64
    regions: GeologyRegions | None
    initial: F64


@dataclass(frozen=True, slots=True)
class PlanetResult:
    world: WorldMap
    settings: PlanetSettings
    geology: WorldGeologyRecipe | None
    mesh: SphereMesh
    land: B
    coast_m: F64
    elevation_m: F64  # land relief; water nodes hold display bathymetry
    flow: FlowState
    forcing: Forcing
    regions: GeologyRegions | None
    calibration: tuple[tuple[RegionRecord, ...], ...]
    climate: Climate | None
    runoff_weight: F64 | None
    stage_seeds: dict[str, int]
    metrics: dict[str, object]


def generate_planet(
    world: WorldMap,
    settings: PlanetSettings,
    geology: WorldGeologyRecipe | None = None,
    progress: ProgressCallback | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> PlanetResult:
    report = cancellable_progress(progress, cancellation)

    def say(fraction: float, message: str) -> None:
        if report is not None:
            report(min(max(fraction, 0.0), 1.0), message)

    check_cancelled(cancellation)
    seeds = {
        stage: stage_seed(settings.seed, stage)
        for stage in (PLANET_MESH_STAGE_ID, PLANET_FORCING_STAGE_ID, PLANET_INITIAL_STAGE_ID)
    }
    radius_m = world.project.frame.radius_km * 1000

    def sample(nodes: int) -> _MeshInputs:
        mesh = build_mesh(nodes, radius_m, seeds[PLANET_MESH_STAGE_ID])
        land = land_on_mesh(world, mesh)
        if not land.any() or land.all():
            raise ValueError("The world needs both land and water for planet relief.")
        regions = None if geology is None else geology_regions(world, geology, mesh, land)
        rng = np.random.default_rng(seeds[PLANET_INITIAL_STAGE_ID])
        coast = coast_distance(mesh, land)
        initial = 1 + 5 * rng.random(mesh.size) + 0.002 * coast
        return _MeshInputs(mesh, land, coast, regions, initial)

    say(0.0, f"Building a {settings.nodes:,}-node sphere mesh")
    fine = sample(settings.nodes)
    mesh, land, coast, regions = fine.mesh, fine.land, fine.coast_m, fine.regions
    water = ~land
    calibrating = (
        regions is not None and any(regions.intents) and settings.calibration_iterations > 0
    )
    # Relief statistics converge with mesh density, so region uplift can be calibrated
    # on a coarser mesh and applied once at full resolution.
    coarse = (
        sample(CALIBRATION_NODES) if calibrating and settings.nodes > CALIBRATION_NODES else None
    )
    to_coarse = (
        None if coarse is None
        else np.asarray(
            KDTree(mesh.xyz).query(coarse.mesh.xyz, workers=-1)[1],  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            dtype=np.int64,
        )
    )
    check_cancelled(cancellation)
    passes = settings.climate_passes
    phases = passes + 1
    relief_share, climate_share = (0.9, 0.0) if passes == 0 else (0.7, 0.2)
    climate: Climate | None = None
    runoff: F64 | None = None
    scale: F64 | None = None
    calibration: tuple[tuple[RegionRecord, ...], ...] = ()
    result = None

    def relief(
        inputs: _MeshInputs,
        iterations: int,
        runoff: F64 | None,
        scale: F64 | None,
        on_step: StepCallback | None,
    ) -> CalibratedRelief:
        return calibrated_relief(
            inputs.mesh, inputs.land, inputs.coast_m, inputs.regions, inputs.initial,
            seed=seeds[PLANET_FORCING_STAGE_ID], erodibility=settings.erodibility,
            steps=settings.steps, step_yr=settings.step_kyr * 1e3,
            area_exponent=settings.area_exponent,
            process_area_m2=settings.process_area_km2 * 1e6, iterations=iterations,
            runoff=runoff, scale=scale, cancellation=cancellation, on_step=on_step,
        )

    for phase in range(phases):
        start = 0.05 + (relief_share + climate_share) * phase / phases
        label = "" if phases == 1 else f" ({phase + 1}/{phases})"

        def on_step(done: int, total: int, start: float = start, label: str = label) -> None:
            if done % 10 == 0 or done == total:
                say(
                    start + relief_share / phases * done / total,
                    f"Eroding relief{label}: step {done:,} of {total:,}",
                )

        if coarse is not None and to_coarse is not None:
            coarse_runoff = None if runoff is None else runoff[to_coarse]
            tuned = relief(coarse, settings.calibration_iterations, coarse_runoff, scale, None)
            scale = tuned.scale
            say(start + relief_share / phases * 0.3, f"Calibrated geology targets{label}")

            def fine_step(done: int, total: int, on: StepCallback = on_step) -> None:
                on(round(0.3 * total + 0.7 * done), total)

            result = relief(fine, 0, runoff, scale, fine_step)
            calibration = (*tuned.iterations[:-1], *result.iterations)
        else:
            result = relief(fine, settings.calibration_iterations, runoff, scale, on_step)
            scale = result.scale
            calibration = result.iterations
        if passes == 0:
            break
        say(start + relief_share / phases, "Simulating climate")
        climate = simulate_climate(
            mesh, np.where(water, 0.0, result.run.elevation), land, coast, settings.climate,
            cancellation=cancellation,
        )
        if phase == phases - 1:
            break
        mean_runoff = float(np.average(climate.runoff_mm[land], weights=mesh.area_m2[land]))
        # Relative runoff weights drainage area; a floor keeps rare floods in deserts.
        runoff = np.maximum(climate.runoff_mm / max(mean_runoff, 1e-9), RUNOFF_WEIGHT_FLOOR)
    assert result is not None
    say(0.96, "Measuring relief")
    bathymetry = ocean_floor(mesh, coast, water, seeds[PLANET_FORCING_STAGE_ID])
    elevation = np.where(water, bathymetry, result.run.elevation)
    metrics = relief_metrics(mesh, result.run.elevation, water, result.run.flow)
    check_cancelled(cancellation)
    say(1.0, "Planet relief ready")
    return PlanetResult(
        world, settings, geology, mesh, land, coast, elevation, result.run.flow, result.forcing,
        regions, calibration, climate, runoff, seeds, metrics,
    )

