"""Bathymetry scenarios consume verified geography and publish independent products."""

from dataclasses import dataclass, replace
from pathlib import Path

from map_maker.terrain.adapters.build import file_sha256, runtime_identity
from map_maker.terrain.adapters.world_bathymetry import (
    read_world_bathymetry,
    write_world_bathymetry,
)
from map_maker.terrain.adapters.world_bathymetry_inputs import (
    read_bathymetry_inputs,
    write_bathymetry_inputs,
)
from map_maker.terrain.adapters.world_geology import world_fingerprint
from map_maker.terrain.application.world_context import WorldContextRun, generate_context
from map_maker.terrain.domain.world_bathymetry import BathymetryInputs
from map_maker.terrain.domain.world_context import WorldContextSettings
from map_maker.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled
from map_maker.terrain.pipeline.world_bathymetry import WorldBathymetry, generate_world_bathymetry


@dataclass(frozen=True, slots=True)
class BathymetryRun:
    result: WorldBathymetry
    runtime: dict[str, object]


@dataclass(frozen=True, slots=True)
class BathymetryFile:
    inputs: BathymetryInputs
    path: Path
    sha256: str


def match_context(inputs: BathymetryInputs, context: WorldContextRun) -> BathymetryInputs:
    if world_fingerprint(inputs.world) != world_fingerprint(context.context.world.project):
        raise ValueError(
            "Bathymetry inputs belong to a different world source, frame or ownership."
        )
    if not set(inputs.ocean_ids) <= {b.id for b in context.context.water_bodies}:
        raise ValueError("Selected ocean IDs are absent from this world's geographic context.")
    return replace(inputs, world=context.context.world.project)


def open_bathymetry_inputs(
    path: Path, context: WorldContextRun, *, cancellation: CancellationToken | None = None
) -> BathymetryFile:
    check_cancelled(cancellation)
    inputs, digest = read_bathymetry_inputs(path)
    result = BathymetryFile(match_context(inputs, context), path, digest)
    check_cancelled(cancellation)
    return result


def save_bathymetry_inputs(
    inputs: BathymetryInputs,
    context: WorldContextRun,
    path: Path,
    expected_hash: str | None = None,
) -> BathymetryFile:
    inputs = match_context(inputs, context)
    return BathymetryFile(inputs, path, write_bathymetry_inputs(inputs, path, expected_hash))


def generate_bathymetry(
    inputs: BathymetryInputs,
    context: WorldContextRun | None = None,
    progress: ProgressCallback | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> BathymetryRun:
    check_cancelled(cancellation)
    runtime = runtime_identity()
    if context is not None:
        inputs = match_context(inputs, context)
    if (
        context is None
        or context.runtime != runtime
        or context.context.grid.shape[0] != inputs.settings.latitude_cells
    ):
        if progress:
            progress(0, "Generating geography with the current producer and requested resolution")

        def geographic_progress(fraction: float, label: str) -> None:
            if progress:
                progress(fraction * 0.8, label)

        context = generate_context(
            inputs.world,
            WorldContextSettings(inputs.settings.latitude_cells),
            geographic_progress,
            cancellation=cancellation,
        )

    def floor_progress(fraction: float, label: str) -> None:
        if progress:
            progress(0.8 + fraction * 0.2, label)

    result = generate_world_bathymetry(
        context.context, inputs, floor_progress, cancellation=cancellation
    )
    if runtime_identity() != runtime:
        raise ValueError("Software changed during bathymetry generation; generate again.")
    check_cancelled(cancellation)
    return BathymetryRun(result, runtime)


def export_bathymetry(
    run: BathymetryRun,
    destination: Path,
    *,
    cancellation: CancellationToken | None = None,
) -> Path:
    def verify() -> None:
        check_cancelled(cancellation)
        if runtime_identity() != run.runtime:
            raise ValueError("Software changed after bathymetry generation; generate again.")

    return write_world_bathymetry(run.result, run.runtime, destination, verify=verify)


def open_bathymetry(
    source: Path, *, cancellation: CancellationToken | None = None
) -> BathymetryRun:
    result, runtime = read_world_bathymetry(
        source, checkpoint=lambda: check_cancelled(cancellation)
    )
    return BathymetryRun(result, runtime)


def build_bathymetry(source: Path, destination: Path) -> Path:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Bathymetry destination already exists: {destination}")
    inputs, digest = read_bathymetry_inputs(source)
    run = generate_bathymetry(inputs)

    def verify() -> None:
        if file_sha256(source) != digest:
            raise ValueError("Bathymetry inputs changed during generation; start again.")
        if runtime_identity() != run.runtime:
            raise ValueError("Software changed during bathymetry generation; start again.")

    return write_world_bathymetry(run.result, run.runtime, destination, verify=verify)
