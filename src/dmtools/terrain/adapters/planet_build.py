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
import rasterio.features
from numpy.typing import NDArray
from rasterio.crs import CRS

from dmtools.terrain.adapters.build import canonical_json, file_sha256
from dmtools.terrain.adapters.planet_render import (
    FrameRaster,
    ice_covered,
    planet_rasters,
    preview_images,
    river_threshold_m3_s,
)
from dmtools.terrain.adapters.world_geology import geology_document
from dmtools.terrain.adapters.world_project import world_project_document
from dmtools.terrain.domain.planet import PLANET_CLIMATE_ALGORITHM, PLANET_RELIEF_ALGORITHM
from dmtools.terrain.domain.seeds import SEED_POLICY_ID
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.pipeline.planet_climate import BIOMES

PLANET_BUILD_SCHEMA = "dmtools.planet-build"
PREVIEW_FILES = {
    "Planet atlas": "atlas.png",
    "Planet relief": "relief.png",
    "Planet rainfall": "precipitation.png",
    "Planet temperature": "temperature.png",
}
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


def river_features(result: PlanetResult, threshold_m3_s: float) -> dict[str, object]:
    """River polylines in world longitude/latitude, one chain per tributary segment."""
    flow, mesh = result.flow, result.mesh
    discharge = result.lakes.discharge_m3_s
    on_lake = result.lakes.lake >= 0
    water = ~result.land | on_lake
    major = (~water) & ~ice_covered(result) & (flow.receiver >= 0) & (
        discharge >= threshold_m3_s
    )
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
                "discharge_m3_s": round(float(discharge[end]), 2),
                "mouth": (
                    "lake" if bool(on_lake[chain[-1]])
                    else "sea" if not bool(result.land[chain[-1]])
                    else "inland"
                ),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def lake_features(
    result: PlanetResult, raster: FrameRaster, lakes_px: NDArray[np.int64]
) -> dict[str, object]:
    """Lake polygons in world longitude/latitude from the lake raster."""
    lakes = result.lakes
    features: list[dict[str, object]] = []
    if len(lakes.level_m):
        for geometry, value in rasterio.features.shapes(
            lakes_px.astype(np.int32), mask=lakes_px >= 0, transform=raster.lonlat_transform()
        ):
            lake_id = int(value)
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "lake": lake_id,
                    "surface_m": round(float(lakes.level_m[lake_id]), 1),
                    "endorheic": bool(lakes.endorheic[lake_id]),
                    "area_km2": round(float(lakes.area_m2[lake_id]) / 1e6, 1),
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
        "erodibility": result.forcing.erodibility.astype("<f8"),
        "steady_uplift_m_per_yr": result.forcing.steady_uplift.astype("<f8"),
        "pulse_uplift_m_per_yr": result.forcing.pulse_uplift.astype("<f8"),
        "lake": result.lakes.lake.astype("<i4"),
        "lake_level_m": result.lakes.level_m.astype("<f4"),
        "lake_endorheic": result.lakes.endorheic,
        "water_surface_m": np.where(
            result.land, result.lakes.surface_m, result.elevation_m
        ).astype("<f4"),
        "discharge_m3_s": result.lakes.discharge_m3_s.astype("<f4"),
    }
    if result.regions is not None:
        arrays["geology_region"] = result.regions.region.astype("<i4")
    if result.runoff_weight is not None:
        arrays["runoff_weight"] = result.runoff_weight.astype("<f8")
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
    rasters = planet_rasters(result, width)
    raster, z, lakes_px = rasters.raster, rasters.elevation_m, rasters.lakes_px
    _write_geotiff(
        target / "elevation.tif", z.astype(np.float32), raster,
        {"manifest": "manifest.json", "authority": "planet.npz node elevation (derived raster)"},
    )
    names.append("elevation.tif")
    verify()
    threshold = river_threshold_m3_s(result, river_km2)
    for layer, image in preview_images(result, rasters, threshold).items():
        verify()
        name = PREVIEW_FILES[layer]
        image.save(target / name)
        names.append(name)
    verify()
    rivers = river_features(result, threshold)
    save_bytes("rivers.geojson", json.dumps(rivers, separators=(",", ":")).encode("utf-8"))
    lakes = lake_features(result, raster, lakes_px)
    save_bytes("lakes.geojson", json.dumps(lakes, separators=(",", ":")).encode("utf-8"))
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
        "rivers": {
            "threshold_km2": river_km2,
            "threshold_m3_s": threshold,
            "features": len(cast(list[object], rivers["features"])),
        },
        "lakes": {
            "count": len(result.lakes.level_m),
            "endorheic": int(result.lakes.endorheic.sum()),
            "features": len(cast(list[object], lakes["features"])),
        },
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
