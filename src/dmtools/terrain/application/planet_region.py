"""Regional planet detail from cached blended tiles (experimental M6)."""

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
from dmtools.terrain.domain.planet import RegionalSettings
from dmtools.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled
from dmtools.terrain.pipeline.planet_regional import RegionalParent
from dmtools.terrain.pipeline.planet_tiles import TileGrid, TileSurface, generate_tile

DEFAULT_REGION_PIXELS = 1024
DEFAULT_REGION_RIVER_KM2 = 2_000.0


def default_cache(planet: Path) -> Path:
    """Tiles live beside the immutable planet build, never inside it."""
    folder = planet if planet.is_dir() else planet.parent
    return folder.parent / f"{folder.name}.tiles"


def default_workers() -> int:
    return max(1, min(8, (os.cpu_count() or 2) - 1))


_worker_state: tuple[RegionalParent, TileGrid, RegionalSettings, TileStore] | None = None


def _start_worker(
    parent: RegionalParent, grid: TileGrid, settings: RegionalSettings, store: TileStore
) -> None:
    global _worker_state
    _worker_state = (parent, grid, settings, store)


def _generate(tile: int) -> int:
    assert _worker_state is not None
    parent, grid, settings, store = _worker_state
    store.save(tile, generate_tile(parent, grid, tile, settings))
    return tile


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
    missing = [tile for tile in tiles if not store.has(tile)]
    done = len(tiles) - len(missing)
    if progress is not None:
        progress(done, len(tiles))
    if missing and workers <= 1:
        for tile in missing:
            check_cancelled(cancellation)
            store.save(tile, generate_tile(parent, grid, tile, settings, cancellation=cancellation))
            done += 1
            if progress is not None:
                progress(done, len(tiles))
    elif missing:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(missing)),
            initializer=_start_worker,
            initargs=(parent, grid, settings, store),
        ) as pool:
            pending: set[Future[int]] = {pool.submit(_generate, tile) for tile in missing}
            while pending:
                finished, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for future in finished:
                    future.result()
                    done += 1
                    if progress is not None:
                        progress(done, len(tiles))
                if cancellation is not None and cancellation.is_cancelled:
                    for future in pending:
                        future.cancel()
                    check_cancelled(cancellation)
    check_cancelled(cancellation)
    return {tile: store.load(tile, parent.mesh.radius_m) for tile in tiles}


@dataclass(frozen=True)
class RegionRun:
    window: RegionWindow
    parent_sha256: str
    settings: RegionalSettings
    store_key: str
    planet_m: float


def region_window(
    parent: RegionalParent,
    parent_sha256: str,
    cache: Path,
    centre: tuple[float, float],
    radius_km: float,
    settings: RegionalSettings | None = None,
    *,
    pixels: int = DEFAULT_REGION_PIXELS,
    river_km2: float = DEFAULT_REGION_RIVER_KM2,
    workers: int | None = None,
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> RegionRun:
    settings = settings or RegionalSettings()
    if not 10 <= radius_km <= 5000:
        raise ValueError("Region radius must be from 10 to 5,000 km.")
    if type(pixels) is not int or not 64 <= pixels <= 8192:
        raise ValueError("Region images need 64-8,192 pixels per side.")
    planet_m = parent.mesh.radius_m
    grid = TileGrid.for_planet(planet_m, settings)
    store = TileStore(cache, parent_sha256, settings)
    needed = grid.tiles_near(centre, radius_km * 1e3)

    def tile_progress(done: int, total: int) -> None:
        if progress is not None:
            progress(0.9 * done / max(total, 1), f"Detail tiles: {done} of {total}")

    tiles = ensure_tiles(
        parent, store, grid, settings, needed, workers=workers or default_workers(),
        progress=tile_progress, cancellation=cancellation,
    )
    if progress is not None:
        progress(0.92, "Blending tiles")
    window = compose_window(parent, grid, tiles, centre, radius_km, pixels, river_km2)
    check_cancelled(cancellation)
    return RegionRun(window, parent_sha256, settings, store.key, planet_m)


def build_region(
    planet: Path,
    destination: Path,
    centre: tuple[float, float],
    radius_km: float,
    settings: RegionalSettings | None = None,
    *,
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
        radius_km, settings, pixels=pixels, river_km2=river_km2, workers=workers,
        progress=progress, cancellation=cancellation,
    )
    return export_region(run, destination)


def export_region(run: RegionRun, destination: Path) -> Path:
    return write_region(
        run.window, run.parent_sha256, run.settings, run.store_key, destination, run.planet_m
    )
