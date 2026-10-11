"""Regional planet detail from cached blended tiles, at nested levels (experimental M6).

Level 1 tiles are enriched from the planet (ADR-0086). Level-n tiles are enriched
from a level parent built from cached level n-1 tiles (ADR-0088). Coarser tiles
are generated first, recursively, and every level is cached by its settings.
"""

import os
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from dmtools.terrain.adapters.planet_load import LoadedPlanet, read_planet_parent
from dmtools.terrain.adapters.planet_region import (
    RegionWindow,
    TileStore,
    compose_window,
    write_region,
)
from dmtools.terrain.domain.planet import (
    REGION_LEVEL_MAX_RADIUS_KM,
    REGION_LEVELS,
    RegionalSettings,
)
from dmtools.terrain.domain.seeds import stage_seed
from dmtools.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled
from dmtools.terrain.pipeline.planet_levels import level_parent
from dmtools.terrain.pipeline.planet_regional import RegionalParent
from dmtools.terrain.pipeline.planet_tiles import TileGrid, TileSurface, generate_tile

DEFAULT_REGION_PIXELS = 1024
DEFAULT_REGION_RIVER_KM2 = 2_000.0
MIN_REGION_RADIUS_KM = 2.0


def default_cache(planet: Path) -> Path:
    """Tiles live beside the immutable planet build, never inside it."""
    folder = planet if planet.is_dir() else planet.parent
    return folder.parent / f"{folder.name}.tiles"


def default_workers() -> int:
    return max(1, min(8, (os.cpu_count() or 2) - 1))


@dataclass(frozen=True)
class _LevelJob:
    """What a tile process needs to generate tiles of one level."""

    planet: RegionalParent
    level: int
    grid: TileGrid
    settings: RegionalSettings
    store: TileStore
    coarse_grid: TileGrid | None  # the level above (None at level 1)
    coarse_settings: RegionalSettings | None
    coarse_store: TileStore | None

    def generate(self, tile: int, cancellation: CancellationToken | None = None) -> None:
        self.store.save(
            tile,
            generate_tile(
                self.tile_parent(tile), self.grid, tile, self.settings, level=self.level,
                cancellation=cancellation,
            ),
        )

    def tile_parent(self, tile: int) -> RegionalParent:
        if self.coarse_grid is None or self.coarse_store is None or self.coarse_settings is None:
            return self.planet
        centre = self.grid.lonlat(tile)
        reach = self.grid.support_m + self.grid.halo_m
        needed = self.coarse_grid.tiles_near(centre, reach * 1.3)
        radius_m = self.planet.mesh.radius_m
        coarse = {t: self.coarse_store.load(t, radius_m) for t in needed}
        seed = stage_seed(self.planet.settings.seed, f"planet.level-parent.l{self.level}.{tile}")
        return level_parent(
            self.planet, self.coarse_grid, coarse, centre, reach,
            self.coarse_settings.spacing_km, seed,
        )


_worker_job: _LevelJob | None = None


def _start_worker(job: _LevelJob) -> None:
    global _worker_job
    _worker_job = job


def _generate(tile: int) -> int:
    assert _worker_job is not None
    _worker_job.generate(tile)
    return tile


def _run_jobs(
    job: _LevelJob,
    missing: list[int],
    total: int,
    done: int,
    *,
    workers: int,
    progress: Callable[[int, int], None] | None,
    cancellation: CancellationToken | None,
) -> None:
    if missing and workers <= 1:
        for tile in missing:
            check_cancelled(cancellation)
            job.generate(tile, cancellation)
            done += 1
            if progress is not None:
                progress(done, total)
    elif missing:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(missing)), initializer=_start_worker, initargs=(job,)
        ) as pool:
            pending: set[Future[int]] = {pool.submit(_generate, tile) for tile in missing}
            while pending:
                finished, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for future in finished:
                    future.result()
                    done += 1
                    if progress is not None:
                        progress(done, total)
                if cancellation is not None and cancellation.is_cancelled:
                    for future in pending:
                        future.cancel()
                    check_cancelled(cancellation)


def ensure_level_tiles(
    planet: RegionalParent,
    parent_sha256: str,
    cache: Path,
    level: int,
    tiles: tuple[int, ...],
    levels: tuple[RegionalSettings, ...],
    *,
    workers: int,
    progress: Callable[[int, int, int], None] | None = None,
    cancellation: CancellationToken | None = None,
) -> tuple[TileGrid, dict[int, TileSurface]]:
    """Level ``level`` tiles, generating any missing ones and the coarser tiles they need.

    ``progress(level, done, total)`` reports each level as it is generated.
    """
    radius_m = planet.mesh.radius_m
    settings = levels[level - 1]
    grid = TileGrid.for_planet(radius_m, settings)
    store = TileStore(cache, parent_sha256, settings, level)
    missing = [tile for tile in tiles if not store.has(tile)]
    coarse_grid = coarse_settings = coarse_store = None
    if missing and level > 1:
        coarse_settings = levels[level - 2]
        coarse_grid = TileGrid.for_planet(radius_m, coarse_settings)
        coarse_store = TileStore(cache, parent_sha256, coarse_settings, level - 1)
        reach = (grid.support_m + grid.halo_m) * 1.3
        coarse_needed = sorted({
            t for tile in missing for t in coarse_grid.tiles_near(grid.lonlat(tile), reach)
        })
        ensure_level_tiles(
            planet, parent_sha256, cache, level - 1, tuple(coarse_needed), levels,
            workers=workers, progress=progress, cancellation=cancellation,
        )
    job = _LevelJob(
        planet, level, grid, settings, store, coarse_grid, coarse_settings, coarse_store
    )

    def report(done: int, total: int) -> None:
        if progress is not None:
            progress(level, done, total)

    report(len(tiles) - len(missing), len(tiles))
    _run_jobs(
        job, missing, len(tiles), len(tiles) - len(missing), workers=workers,
        progress=report, cancellation=cancellation,
    )
    check_cancelled(cancellation)
    return grid, {tile: store.load(tile, radius_m) for tile in tiles}


def ensure_tiles(
    parent: RegionalParent,
    store: TileStore,
    grid: TileGrid,
    settings: RegionalSettings,
    tiles: tuple[int, ...],
    *,
    workers: int,
    progress: Callable[[int, int], None] | None = None,
    cancellation: CancellationToken | None = None,
) -> dict[int, TileSurface]:
    """Level-1 tiles of ``parent`` in ``store`` (generated when missing)."""
    job = _LevelJob(parent, 1, grid, settings, store, None, None, None)
    missing = [tile for tile in tiles if not store.has(tile)]
    if progress is not None:
        progress(len(tiles) - len(missing), len(tiles))
    _run_jobs(
        job, missing, len(tiles), len(tiles) - len(missing), workers=workers,
        progress=progress, cancellation=cancellation,
    )
    check_cancelled(cancellation)
    return {tile: store.load(tile, parent.mesh.radius_m) for tile in tiles}


@dataclass(frozen=True)
class RegionRun:
    window: RegionWindow
    parent_sha256: str
    settings: RegionalSettings
    store_key: str
    planet_m: float
    level: int = 1


def detail_levels(settings: RegionalSettings | None) -> tuple[RegionalSettings, ...]:
    """The nested level settings, with ``settings`` replacing level 1 when given."""
    return (settings or REGION_LEVELS[0], *REGION_LEVELS[1:])


def region_window(
    parent: RegionalParent,
    parent_sha256: str,
    cache: Path,
    centre: tuple[float, float],
    radius_km: float,
    settings: RegionalSettings | None = None,
    *,
    level: int = 1,
    levels: tuple[RegionalSettings, ...] | None = None,
    pixels: int = DEFAULT_REGION_PIXELS,
    river_km2: float = DEFAULT_REGION_RIVER_KM2,
    workers: int | None = None,
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> RegionRun:
    """A window of nested detail ``level`` (1 region, 2 province, 3 local)."""
    levels = levels or detail_levels(settings)
    if type(level) is not int or not 1 <= level <= len(levels):
        raise ValueError(f"Detail level must be from 1 to {len(levels)}.")
    limit = REGION_LEVEL_MAX_RADIUS_KM[min(level, len(REGION_LEVEL_MAX_RADIUS_KM)) - 1]
    if not MIN_REGION_RADIUS_KM <= radius_km <= limit:
        raise ValueError(
            f"Level {level} windows need a radius from {MIN_REGION_RADIUS_KM:g} to {limit:,.0f} km."
        )
    if type(pixels) is not int or not 64 <= pixels <= 8192:
        raise ValueError("Region images need 64-8,192 pixels per side.")
    planet_m = parent.mesh.radius_m
    workers = workers or default_workers()
    grid = TileGrid.for_planet(planet_m, levels[level - 1])
    needed = grid.tiles_near(centre, radius_km * 1e3)

    def tile_progress(at: int, done: int, total: int) -> None:
        if progress is not None:
            share = (at - 1 + done / max(total, 1)) / level
            progress(0.9 * share, f"Level {at} detail tiles: {done} of {total}")

    grid, tiles = ensure_level_tiles(
        parent, parent_sha256, cache, level, needed, levels, workers=workers,
        progress=tile_progress, cancellation=cancellation,
    )
    window_parent = parent
    if level > 1:
        coarse_settings = levels[level - 2]
        coarse_grid = TileGrid.for_planet(planet_m, coarse_settings)
        coarse_needed = coarse_grid.tiles_near(centre, radius_km * 1e3 * 1.3)
        _, coarse = ensure_level_tiles(
            parent, parent_sha256, cache, level - 1, coarse_needed, levels, workers=workers,
            cancellation=cancellation,
        )
        if progress is not None:
            progress(0.91, "Preparing the coarser level")
        window_parent = level_parent(
            parent, coarse_grid, coarse, centre, radius_km * 1e3,
            coarse_settings.spacing_km,
            stage_seed(parent.settings.seed, f"planet.level-window.l{level}"),
        )
    if progress is not None:
        progress(0.92, "Blending tiles")
    window = compose_window(
        window_parent, grid, tiles, centre, radius_km, pixels, river_km2,
        spacing_m=levels[level - 1].spacing_km * 1e3,
    )
    check_cancelled(cancellation)
    store = TileStore(cache, parent_sha256, levels[level - 1], level)
    return RegionRun(window, parent_sha256, levels[level - 1], store.key, planet_m, level)


def build_region(
    planet: Path,
    destination: Path,
    centre: tuple[float, float],
    radius_km: float,
    settings: RegionalSettings | None = None,
    *,
    level: int = 1,
    cache: Path | None = None,
    pixels: int = DEFAULT_REGION_PIXELS,
    river_km2: float = DEFAULT_REGION_RIVER_KM2,
    workers: int | None = None,
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> Path:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Region destination already exists: {destination}")
    loaded: LoadedPlanet = read_planet_parent(planet)
    run = region_window(
        loaded.parent, loaded.build_sha256, cache or default_cache(loaded.path), centre,
        radius_km, settings, level=level, pixels=pixels, river_km2=river_km2,
        workers=workers, progress=progress, cancellation=cancellation,
    )
    return export_region(run, destination)


def export_region(run: RegionRun, destination: Path) -> Path:
    return write_region(
        run.window, run.parent_sha256, run.settings, run.store_key, destination, run.planet_m,
        run.level,
    )
