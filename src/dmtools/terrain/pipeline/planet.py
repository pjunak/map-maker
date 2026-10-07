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
from dmtools.terrain.pipeline.planet_climate import (
    Climate,
    downscale_climate,
    simulate_climate,
    snowline_m,
)
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
from dmtools.terrain.pipeline.planet_lakes import Lakes, balance_lakes, young_depressions
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, build_mesh, sample_field
from dmtools.terrain.pipeline.planet_metrics import relief_metrics
from dmtools.terrain.pipeline.planet_noise import fbm3
from dmtools.terrain.pipeline.world import WorldMap

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

RUNOFF_WEIGHT_FLOOR = 0.05
CALIBRATION_NODES = 100_000
# Moisture transport varies over hundreds of kilometres and its explicit eddy
# diffusion costs grow faster than the node count, so it runs on at most this
# many nodes; local climate fields are recomputed on the full mesh.
CLIMATE_NODES = 200_000
COUPLING_NODES = 800_000
INITIAL_RELIEF_M = 300.0
# Gentle rise of the inherited surface away from the coast (0.2 m/km).
INITIAL_COAST_SLOPE = 2e-4


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
    lakes: Lakes  # lake state and the final routing on the water surface
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
        # An inherited, multi-scale land surface: slowly eroding shields keep its
        # drainage, so a smooth dome would leave straight radial rivers.
        texture = fbm3(mesh.xyz, seeds[PLANET_INITIAL_STAGE_ID], 7, 4.0, 0.6)
        inherited = INITIAL_RELIEF_M * (1 + texture)
        initial = (
            1 + 5 * rng.random(mesh.size) + INITIAL_COAST_SLOPE * coast
            + np.where(land, inherited, 0.0)
        )
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
    # Climate coupling passes only feed runoff to the next pass, so they run on at
    # most COUPLING_NODES; only the final relief uses the full mesh.
    passes = settings.climate_passes
    coupling = sample(COUPLING_NODES) if passes > 0 and settings.nodes > COUPLING_NODES else None
    climate_inputs = (
        sample(CLIMATE_NODES) if passes > 0 and settings.nodes > CLIMATE_NODES else None
    )

    def on_mesh(target: _MeshInputs, field: tuple[SphereMesh, F64] | None) -> F64 | None:
        """A node field carried over to another mesh (triangle-linear interpolation)."""
        if field is None:
            return None
        source, values = field
        return values if source is target.mesh else sample_field(source, target.mesh.xyz, values)

    def simulate(inputs: _MeshInputs, elevation: F64) -> Climate:
        if climate_inputs is None:
            return simulate_climate(
                inputs.mesh, elevation, inputs.land, inputs.coast_m, settings.climate,
                cancellation=cancellation,
            )
        target, coarse_mesh = inputs.mesh, climate_inputs.mesh
        nearest = np.asarray(
            KDTree(coarse_mesh.xyz).query(target.xyz, workers=-1)[1],  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            dtype=np.int64,
        )
        # Area-weighted mean of the land relief around each coarse node.
        weight = target.area_m2 * inputs.land
        total = np.bincount(nearest, weight * elevation, coarse_mesh.size)
        share = np.bincount(nearest, weight, coarse_mesh.size)
        coarse_elevation = np.where(climate_inputs.land, total / np.maximum(share, 1e-9), 0.0)
        transport = simulate_climate(
            coarse_mesh, coarse_elevation, climate_inputs.land, climate_inputs.coast_m,
            settings.climate, cancellation=cancellation,
        )
        return downscale_climate(
            coarse_mesh, transport, target, elevation, inputs.land, inputs.coast_m,
            settings.climate,
        )

    check_cancelled(cancellation)
    phases = passes + 1
    relief_share, climate_share = (0.9, 0.0) if passes == 0 else (0.7, 0.2)
    climate: Climate | None = None
    runoff_field: tuple[SphereMesh, F64] | None = None
    scale: F64 | None = None
    calibration: tuple[tuple[RegionRecord, ...], ...] = ()
    result = None
    runoff: F64 | None = None

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
            runoff=runoff, scale=scale,
            snowline_m=snowline_m(inputs.mesh, inputs.land, inputs.coast_m, settings.climate),
            cancellation=cancellation, on_step=on_step,
        )

    for phase in range(phases):
        start = 0.05 + (relief_share + climate_share) * phase / phases
        label = "" if phases == 1 else f" ({phase + 1}/{phases})"
        final = phase == phases - 1
        inputs = fine if final or coupling is None else coupling
        runoff = on_mesh(inputs, runoff_field)

        def on_step(done: int, total: int, start: float = start, label: str = label) -> None:
            if done % 10 == 0 or done == total:
                say(
                    start + relief_share / phases * done / total,
                    f"Eroding relief{label}: step {done:,} of {total:,}",
                )

        if coarse is not None:
            tuned = relief(
                coarse, settings.calibration_iterations, on_mesh(coarse, runoff_field), scale,
                None,
            )
            scale = tuned.scale
            say(start + relief_share / phases * 0.3, f"Calibrated geology targets{label}")

            def fine_step(done: int, total: int, on: StepCallback = on_step) -> None:
                on(round(0.3 * total + 0.7 * done), total)

            result = relief(inputs, 0, runoff, scale, fine_step)
            calibration = (*tuned.iterations[:-1], *result.iterations)
        else:
            result = relief(inputs, settings.calibration_iterations, runoff, scale, on_step)
            scale = result.scale
            calibration = result.iterations
        if passes == 0:
            break
        say(start + relief_share / phases, "Simulating climate")
        climate = simulate(inputs, np.where(inputs.land, result.run.elevation, 0.0))
        if final:
            break
        weights = inputs.mesh.area_m2[inputs.land]
        mean_runoff = float(np.average(climate.runoff_mm[inputs.land], weights=weights))
        # Relative runoff weights drainage area; a floor keeps rare floods in deserts.
        runoff_field = (
            inputs.mesh,
            np.maximum(climate.runoff_mm / max(mean_runoff, 1e-9), RUNOFF_WEIGHT_FLOOR),
        )
    assert result is not None
    say(0.94, "Filling lakes")
    evolved = result.run.elevation
    depressions = young_depressions(
        mesh, land, coast, regions, None if climate is None else climate.warm_c, evolved,
        seeds[PLANET_FORCING_STAGE_ID],
    )
    # Land stays at least 1 m above sea level (no below-sea-level basins yet).
    lakes = balance_lakes(
        mesh, land, np.where(land, np.maximum(evolved - depressions, 1.0), 0.0),
        None if climate is None else climate.runoff_mm,
        None if climate is None else climate.pet_mm,
    )
    say(0.97, "Measuring relief")
    bathymetry = ocean_floor(mesh, coast, water, seeds[PLANET_FORCING_STAGE_ID])
    elevation = np.where(water, bathymetry, lakes.ground_m)
    metrics = relief_metrics(mesh, lakes.surface_m, water | (lakes.lake >= 0), lakes.flow)
    metrics["lakes"] = {
        "count": len(lakes.level_m),
        "endorheic": int(lakes.endorheic.sum()),
        "area_share_of_land": float(lakes.area_m2.sum() / mesh.area_m2[land].sum()),
    }
    check_cancelled(cancellation)
    say(1.0, "Planet relief ready")
    return PlanetResult(
        world, settings, geology, mesh, land, coast, elevation, lakes.flow, result.forcing,
        regions, calibration, climate, runoff, lakes, seeds, metrics,
    )

