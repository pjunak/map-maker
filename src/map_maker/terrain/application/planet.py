"""Generate, preview and publish whole-planet relief from a world (experimental M2).

A planet is a base planet without wonders plus a wonder pass (ADR-0097). A run
keeps its base, so changed wonders are applied without eroding the planet again.
A run draws only the map its caller shows first; the others are drawn the first
time they are asked for (``PlanetRun.maps``).
"""

import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.adapters.planet_build import write_planet_build
from map_maker.terrain.adapters.planet_maps import PlanetMaps
from map_maker.terrain.adapters.world_geology import geology_document, read_geology
from map_maker.terrain.adapters.world_project import read_world_project, world_project_document
from map_maker.terrain.adapters.world_svg import parse_world_svg
from map_maker.terrain.adapters.world_wonders import read_wonders, wonders_sha256
from map_maker.terrain.domain.planet import PlanetSettings
from map_maker.terrain.domain.wonders import WonderSettings
from map_maker.terrain.domain.world import WorldProject
from map_maker.terrain.domain.world_geology import WorldGeologyRecipe
from map_maker.terrain.domain.world_wonders import WorldWonders
from map_maker.terrain.pipeline.control import (
    CancellationToken,
    ProgressCallback,
    check_cancelled,
    progress_part,
)
from map_maker.terrain.pipeline.planet import (
    BASE_SHARE,
    PlanetBase,
    PlanetResult,
    finish_planet,
    generate_base,
    has_wonders,
)
from map_maker.terrain.pipeline.world import prepare_world_map

DEFAULT_RASTER_WIDTH = 4096
DEFAULT_PREVIEW_WIDTH = 2048
DEFAULT_RIVER_KM2 = 25_000.0


@dataclass(frozen=True)
class PlanetRun:
    """A generated planet with the identities needed to publish it unchanged."""

    base: PlanetBase
    result: PlanetResult
    runtime: dict[str, object]
    inputs: dict[str, str | None]  # world, geology and wonder document hashes
    maps: PlanetMaps  # the map themes at preview width, drawn when first asked for
    base_sha256: str  # identity of the planet without wonders; tiles are cached under it


def input_identity(
    project: WorldProject, geology: WorldGeologyRecipe | None
) -> dict[str, str | None]:
    """Hashes of the canonical input documents of the base planet."""
    return {
        "world_sha256": sha256(canonical_json(world_project_document(project))).hexdigest(),
        "geology_sha256": None if geology is None
        else sha256(canonical_json(geology_document(geology))).hexdigest(),
    }


def base_identity(
    project: WorldProject,
    geology: WorldGeologyRecipe | None,
    settings: PlanetSettings,
    runtime: dict[str, object] | None = None,
) -> str:
    """Identity of a planet without wonders: its inputs, settings and runtime."""
    return sha256(
        canonical_json({
            "inputs": input_identity(project, geology),
            "settings": asdict(settings),
            "runtime": runtime_identity() if runtime is None else runtime,
        })
    ).hexdigest()


def planet_identity(run: PlanetRun) -> str:
    """Identity of an in-memory planet: its base and its wonders."""
    return sha256(
        canonical_json({
            "base": run.base_sha256,
            "wonder_settings": asdict(run.result.wonder_settings),
            "wonders_sha256": run.inputs["wonders_sha256"],
        })
    ).hexdigest()


def user_tile_cache() -> Path:
    """Per-user cache for regional detail tiles of planets that were not exported."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "map-maker" / "planet-tiles"


def _check_wonders(project: WorldProject, wonders: WorldWonders | None) -> None:
    if wonders is not None and wonders.world != project:
        raise ValueError("The wonders belong to a different world; open their world.")


def generate_planet_run(
    project: WorldProject,
    geology: WorldGeologyRecipe | None,
    settings: PlanetSettings,
    progress: ProgressCallback | None = None,
    *,
    wonder_settings: WonderSettings | None = None,
    wonders: WorldWonders | None = None,
    shown: Sequence[str] = (),
    preview_width: int = DEFAULT_PREVIEW_WIDTH,
    river_km2: float = DEFAULT_RIVER_KM2,
    cancellation: CancellationToken | None = None,
) -> PlanetRun:
    """Generate a planet from a world.

    ``shown`` lists map theme labels by preference: the first one the planet has is
    drawn before returning, for the caller to show at once. The other maps are drawn
    when first asked for (``PlanetRun.maps``).
    """
    check_cancelled(cancellation)
    runtime = runtime_identity()
    if parse_world_svg(project.source.svg, project.source.name) != project.source:
        raise ValueError("World source snapshot and geometry disagree; import again.")
    if geology is not None and geology.world != project:
        raise ValueError("The geology recipe belongs to a different world; open its world.")
    wonder_settings = wonder_settings or WonderSettings()
    _check_wonders(project, wonders)
    world = prepare_world_map(project)
    share = BASE_SHARE if has_wonders(wonder_settings, wonders) else 1.0
    base = generate_base(
        world, settings, geology, progress_part(progress, 0.0, share), cancellation=cancellation
    )
    result = finish_planet(
        base, wonder_settings, wonders, progress_part(progress, share, 1.0),
        cancellation=cancellation,
    )
    maps = PlanetMaps(result, preview_width, river_km2)
    _draw_shown(maps, shown, progress)
    if runtime_identity() != runtime:
        raise ValueError("Software changed during planet generation; generate again.")
    check_cancelled(cancellation)
    return PlanetRun(
        base, result, runtime,
        {
            **input_identity(project, geology),
            "wonders_sha256": None if wonders is None else wonders_sha256(wonders),
        },
        maps, base_identity(project, geology, settings, runtime),
    )


def apply_wonders(
    run: PlanetRun,
    wonder_settings: WonderSettings,
    wonders: WorldWonders | None,
    progress: ProgressCallback | None = None,
    *,
    shown: Sequence[str] = (),
    preview_width: int = DEFAULT_PREVIEW_WIDTH,
    river_km2: float = DEFAULT_RIVER_KM2,
    cancellation: CancellationToken | None = None,
) -> PlanetRun:
    """``run``'s base planet with these wonders: the wonder pass only (ADR-0097).

    ``shown`` is as for ``generate_planet_run``.
    """
    if runtime_identity() != run.runtime:
        raise ValueError("Software changed since the planet was generated; generate again.")
    _check_wonders(run.result.world.project, wonders)
    result = finish_planet(run.base, wonder_settings, wonders, progress, cancellation=cancellation)
    maps = PlanetMaps(result, preview_width, river_km2)
    _draw_shown(maps, shown, progress)
    check_cancelled(cancellation)
    return PlanetRun(
        run.base, result, run.runtime,
        {**run.inputs, "wonders_sha256": None if wonders is None else wonders_sha256(wonders)},
        maps, run.base_sha256,
    )


def _draw_shown(
    maps: PlanetMaps, shown: Sequence[str], progress: ProgressCallback | None
) -> None:
    label = next((label for label in shown if label in maps.labels), None)
    if label is not None:
        if progress is not None:
            progress(1.0, "Drawing the map")
        maps.draw(label)


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
        run.result, run.runtime, run.inputs, destination, base=run.base.planet,
        base_sha256=run.base_sha256, width=width, river_km2=river_km2, verify=verify,
    )


def build_planet(
    world_path: Path,
    destination: Path,
    geology_path: Path | None = None,
    settings: PlanetSettings | None = None,
    *,
    wonders_path: Path | None = None,
    wonder_settings: WonderSettings | None = None,
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
        path: file_sha256(path)
        for path in (world_path, geology_path, wonders_path) if path is not None
    }
    run = generate_planet_run(
        read_world_project(world_path),
        None if geology_path is None else read_geology(geology_path)[0],
        settings or PlanetSettings(), progress,
        wonder_settings=wonder_settings,
        wonders=None if wonders_path is None else read_wonders(wonders_path)[0],
        river_km2=river_km2, cancellation=cancellation,
    )
    for path, digest in files.items():
        if file_sha256(path) != digest:
            raise ValueError(f"{path.name} changed during planet generation; generate again.")
    return export_planet(
        run, destination, width=width, river_km2=river_km2, cancellation=cancellation
    )
