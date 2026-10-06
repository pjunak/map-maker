# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Write a planet build: mesh archive, world-aligned GeoTIFF, rivers, previews, manifest.

The manifest is written last via an atomic rename, so a failed or cancelled
export never looks complete. The authoritative relief is the node elevation on
the sphere mesh; triangle-linear interpolation defines values between nodes.
Rasters and images are derived products.
"""

import json
import os
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.crs import CRS

from dmtools.terrain.adapters.build import canonical_json, file_sha256
from dmtools.terrain.adapters.planet_render import (
    FrameRaster,
    atlas_image,
    biome_rgb,
    draw_rivers,
    elevation_raster,
    land_mask,
    relief_image,
    scalar_image,
)
from dmtools.terrain.adapters.world_geology import geology_document
from dmtools.terrain.adapters.world_project import world_project_document
from dmtools.terrain.domain.planet import PLANET_CLIMATE_ALGORITHM, PLANET_RELIEF_ALGORITHM
from dmtools.terrain.domain.seeds import SEED_POLICY_ID
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.pipeline.planet_climate import BIOMES

PLANET_BUILD_SCHEMA = "dmtools.planet-build"
PLANET_BUILD_VERSION = 1
MAX_RIVER_FEATURES = 200_000

type Verify = Callable[[], None]


def planet_crs_wkt(radius_km: float) -> str:
    """Geographic CRS on the world's custom sphere; deliberately not Earth's datum."""
    radius = radius_km * 1000
    return (
        'GEOGCRS["DM Tools world sphere",DATUM["DM Tools custom sphere",'
        f'ELLIPSOID["sphere",{radius!r},0,LENGTHUNIT["metre",1]]],'
        'PRIMEM["Reference meridian",0,ANGLEUNIT["degree",0.0174532925199433]],'
        'CS[ellipsoidal,2],AXIS["longitude",east,ORDER[1],ANGLEUNIT["degree",0.0174532925199433]],'
        'AXIS["latitude",north,ORDER[2],ANGLEUNIT["degree",0.0174532925199433]]]'
    )


def _write_geotiff(
    path: Path, values: NDArray[np.float32], raster: FrameRaster, tags: dict[str, str]
) -> None:
    rows, columns = raster.shape
    with path.open("xb"):
        pass
    with (
        rasterio.Env(GDAL_PAM_ENABLED=False, GDAL_NUM_THREADS="1"),
        rasterio.open(
            path, "w", driver="GTiff", width=columns, height=rows, count=1, dtype="float32",
            crs=cast(Any, CRS.from_wkt(planet_crs_wkt(raster.frame.radius_km))),
            transform=raster.lonlat_transform(), tiled=True, blockxsize=256, blockysize=256,
            compress="deflate", predictor=3, zlevel=6, num_threads=1, bigtiff="IF_SAFER",
        ) as dataset,
    ):
        dataset.write(values, 1)
        dataset.set_band_description(1, "Planet elevation (land relief and display bathymetry)")
        dataset.set_band_unit(1, "m")
        dataset.update_tags(AREA_OR_POINT="Area", **tags)
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def river_features(result: PlanetResult, threshold_m2: float) -> dict[str, object]:
    """River polylines in world longitude/latitude, one chain per tributary segment."""
    flow, mesh = result.flow, result.mesh
    water = ~result.land
    major = (~water) & (flow.receiver >= 0) & (flow.area_m2 >= threshold_m2)
    donors = np.zeros(mesh.size, dtype=np.int64)
    np.add.at(donors, flow.receiver[major], 1)
    lon = np.rad2deg(mesh.lon)
    lat = np.rad2deg(mesh.lat)
    visited = np.zeros(mesh.size, dtype=bool)
    features: list[dict[str, object]] = []
    heads = np.flatnonzero(major & (donors == 0))
    for head in heads[np.argsort(-flow.area_m2[heads])].tolist():
        chain = [head]
        node = head
        while True:
            visited[node] = True
            nxt = int(flow.receiver[node])
            chain.append(nxt)
            if water[nxt] or visited[nxt] or not major[nxt]:
                break
            node = nxt
        if len(features) >= MAX_RIVER_FEATURES:
            raise ValueError("Too many river features; raise the river threshold.")
        parts: list[list[list[float]]] = [[]]
        previous: float | None = None
        for n in chain:
            x = float(lon[n])
            if previous is not None and abs(x - previous) > 180:
                parts.append([])
            parts[-1].append([round(x, 5), round(float(lat[n]), 5)])
            previous = x
        lines = [p for p in parts if len(p) >= 2]
        if not lines:
            continue
        end = chain[-2]
        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": lines},
            "properties": {
                "contributing_area_km2": round(float(flow.area_m2[end]) / 1e6, 1),
                "reaches_sea": bool(water[chain[-1]]),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def write_planet_build(
    result: PlanetResult,
    runtime: dict[str, object],
    inputs: dict[str, str | None],
    destination: Path,
    *,
    width: int,
    river_km2: float,
    verify: Verify,
) -> Path:
    verify()
    target = destination.absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Planet destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    names: list[str] = []

    def save_bytes(name: str, data: bytes) -> None:
        with (target / name).open("xb") as stream:
            stream.write(data)
        names.append(name)

    save_bytes("world.dmworld.json", canonical_json(world_project_document(result.world.project)))
    if result.geology is not None:
        save_bytes("geology.dmgeology.json", canonical_json(geology_document(result.geology)))
    verify()
    mesh, flow, climate = result.mesh, result.flow, result.climate
    arrays: dict[str, NDArray[Any]] = {
        "xyz": mesh.xyz.astype("<f8"),
        "triangles": mesh.triangles.astype("<i4"),
        "land": result.land,
        "elevation_m": result.elevation_m.astype("<f4"),
        "coast_distance_m": np.where(np.isfinite(result.coast_m), result.coast_m, -1).astype("<f4"),
        "receiver": flow.receiver.astype("<i4"),
        "contributing_area_m2": flow.area_m2.astype("<f8"),
        "uplift_m_per_yr": (
            result.forcing.steady_uplift + result.forcing.pulse_uplift
        ).astype("<f4"),
        "erodibility": result.forcing.erodibility.astype("<f4"),
    }
    if result.regions is not None:
        arrays["geology_region"] = result.regions.region.astype("<i4")
    if climate is not None:
        arrays |= {
            "temperature_c": climate.temperature_c.astype("<f4"),
            "warm_season_c": climate.warm_c.astype("<f4"),
            "cold_season_c": climate.cold_c.astype("<f4"),
            "precipitation_mm": climate.precipitation_mm.astype("<f4"),
            "potential_evapotranspiration_mm": climate.pet_mm.astype("<f4"),
            "runoff_mm": climate.runoff_mm.astype("<f4"),
            "biome": climate.biome.astype("i1"),
            "wind_east_m_s": climate.wind_east.astype("<f4"),
            "wind_north_m_s": climate.wind_north.astype("<f4"),
        }
    with (target / "planet.npz").open("xb") as stream:
        np.savez_compressed(stream, allow_pickle=False, **arrays)
    names.append("planet.npz")
    verify()
    raster = FrameRaster.build(mesh, result.world.project.frame, width)
    land_px = land_mask(result.world, raster)
    z = elevation_raster(result, raster, land_px)
    _write_geotiff(
        target / "elevation.tif", z.astype(np.float32), raster,
        {"manifest": "manifest.json", "authority": "planet.npz node elevation (derived raster)"},
    )
    names.append("elevation.tif")
    verify()
    threshold = river_km2 * 1e6
    image = relief_image(z, land_px, raster)
    draw_rivers(image, result, raster, threshold)
    image.save(target / "relief.png")
    names.append("relief.png")
    if climate is not None:
        verify()
        atlas = atlas_image(z, land_px, raster, biome_rgb(result, raster))
        draw_rivers(atlas, result, raster, threshold)
        atlas.save(target / "atlas.png")
        names.append("atlas.png")
        for name, values, low, high, colours in (
            ("precipitation.png", climate.precipitation_mm, 0.0, 2500.0,
             ((150, 90, 40), (230, 210, 140), (120, 190, 90), (30, 120, 160), (20, 40, 140))),
            ("temperature.png", climate.temperature_c, -25.0, 30.0,
             ((60, 40, 160), (90, 160, 220), (240, 240, 200), (240, 160, 60), (180, 40, 30))),
        ):
            scalar_image(raster.interpolate(mesh, values), land_px, low, high, colours).save(
                target / name
            )
            names.append(name)
    verify()
    rivers = river_features(result, threshold)
    save_bytes("rivers.geojson", json.dumps(rivers, separators=(",", ":")).encode("utf-8"))
    outputs = {
        name: {"sha256": file_sha256(target / name), "bytes": (target / name).stat().st_size}
        for name in names
    }
    rows, columns = raster.shape
    frame = result.world.project.frame
    manifest: dict[str, object] = {
        "schema": PLANET_BUILD_SCHEMA,
        "version": PLANET_BUILD_VERSION,
        "status": "experimental",
        "algorithms": {"relief": PLANET_RELIEF_ALGORITHM, "climate": (
            None if climate is None else PLANET_CLIMATE_ALGORITHM
        )},
        "settings": asdict(result.settings),
        "seed_policy": SEED_POLICY_ID,
        "stage_seeds": result.stage_seeds,
        "inputs": inputs,
        "runtime": runtime,
        "compiled_kernels": {name: version(name) for name in ("numba", "llvmlite")},
        "world_frame": {
            "bounds": list(frame.bounds),
            "radius_km": frame.radius_km,
            "central_meridian_deg": frame.central_meridian_deg,
        },
        "mesh": {
            "nodes": mesh.size,
            "triangles": len(mesh.triangles),
            "spacing_km": mesh.spacing_m / 1000,
            "authority": "node elevation_m; triangle-linear between nodes",
        },
        "raster": {
            "width": columns,
            "height": rows,
            "registration": "PixelIsArea",
            "maps_to": "world source frame bounds; columns linear in longitude, rows in latitude",
            "crs_wkt": planet_crs_wkt(frame.radius_km),
        },
        "calibration": [
            [asdict(record) for record in iteration] for iteration in result.calibration
        ],
        "metrics": result.metrics,
        "climate": None if climate is None else _climate_summary(result),
        "rivers": {"threshold_km2": river_km2, "features": len(rivers["features"])},  # type: ignore[arg-type]
        "outputs": outputs,
    }
    manifest["build_sha256"] = sha256(canonical_json(manifest)).hexdigest()
    verify()
    pending = target / "manifest.pending"
    with pending.open("xb") as stream:
        stream.write(canonical_json(manifest))
        stream.flush()
        os.fsync(stream.fileno())
    verify()
    complete = target / "manifest.json"
    pending.replace(complete)
    return complete


def _climate_summary(result: PlanetResult) -> dict[str, object]:
    climate = result.climate
    assert climate is not None
    weight = result.mesh.area_m2 * result.land
    total = float(weight.sum())
    return {
        "provisional": True,
        "settings": asdict(result.settings.climate),
        "land_mean_precipitation_mm": float(np.sum(climate.precipitation_mm * weight) / total),
        "land_mean_runoff_mm": float(np.sum(climate.runoff_mm * weight) / total),
        "biome_share": {
            name: float(weight[climate.biome == k].sum() / total)
            for k, name in enumerate(BIOMES)
            if k > 0
        },
    }
