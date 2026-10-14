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

from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.adapters.map_views import THEMES, theme_file
from map_maker.terrain.adapters.planet_natural import preview_images
from map_maker.terrain.adapters.planet_render import (
    FrameRaster,
    ice_covered,
    planet_rasters,
    river_threshold_m3_s,
)
from map_maker.terrain.adapters.world_geology import geology_document
from map_maker.terrain.adapters.world_project import world_project_document
from map_maker.terrain.domain.planet import PLANET_CLIMATE_ALGORITHM, PLANET_RELIEF_ALGORITHM
from map_maker.terrain.domain.seeds import SEED_POLICY_ID
from map_maker.terrain.pipeline.planet import PlanetResult
from map_maker.terrain.pipeline.planet_climate import BIOMES
from map_maker.terrain.pipeline.planet_koppen import KOPPEN, koppen_group_share
from map_maker.terrain.pipeline.planet_mesh import sample_field
from map_maker.terrain.pipeline.planet_volcanism import GUYOT_DEPTH_M, SEAMOUNT
from map_maker.terrain.pipeline.planet_volcanism import KINDS as VOLCANO_KINDS
from map_maker.terrain.pipeline.planet_volcanism import SETTINGS as VOLCANO_SETTINGS

PLANET_BUILD_SCHEMA = "map-maker.planet-build"
PREVIEW_FILES = {theme.label: theme_file(theme) for theme in THEMES}
PLANET_BUILD_VERSION = 1
MAX_RIVER_FEATURES = 200_000

type Verify = Callable[[], None]



# Kinds of aged wonders, by their archived index.
AGING_KINDS = ("crater", "chasm", "cliff", "tepui")


def paths_archive(
    name: str, paths: tuple[NDArray[np.float64], ...], profiles: tuple[NDArray[np.float64], ...]
) -> dict[str, NDArray[Any]]:
    """Paths and per-vertex profiles of any length, concatenated; offsets mark each start."""
    return {
        f"{name}_xyz": (np.vstack(paths) if paths else np.zeros((0, 3))).astype("<f8"),
        f"{name}_offsets": np.cumsum([0, *(len(path) for path in paths)]).astype("<i8"),
        f"{name}_profile": (np.concatenate(profiles) if profiles else np.zeros(0)).astype("<f8"),
    }

def planet_crs_wkt(radius_km: float) -> str:
    """Geographic CRS on the world's custom sphere; deliberately not Earth's datum."""
    radius = radius_km * 1000
    return (
        'GEOGCRS["Map Maker world sphere",DATUM["Map Maker custom sphere",'
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


def volcano_features(result: PlanetResult) -> dict[str, object]:
    """Volcanoes as points in world longitude/latitude with their setting and activity."""
    v = result.volcanoes
    features: list[dict[str, object]] = []
    if len(v):
        base = sample_field(result.mesh, v.xyz, result.elevation_m - result.volcanic_m)
        for k in range(len(v)):
            x, y, z = (float(c) for c in v.xyz[k])
            summit = float(base[k] + v.height_m[k])
            if v.kind[k] == SEAMOUNT:
                summit = min(summit, GUYOT_DEPTH_M)
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        round(float(np.degrees(np.arctan2(y, x))), 4),
                        round(float(np.degrees(np.arcsin(np.clip(z, -1, 1)))), 4),
                    ],
                },
                "properties": {
                    "kind": VOLCANO_KINDS[int(v.kind[k])],
                    "setting": VOLCANO_SETTINGS[int(v.setting[k])],
                    "active": bool(v.active[k]),
                    "age_myr": round(float(v.age_myr[k]), 2),
                    "summit_m": round(summit),
                    "edifice_height_m": round(float(v.height_m[k])),
                    "basal_radius_km": round(float(v.radius_m[k]) / 1000, 1),
                    "caldera_km": round(2 * float(v.caldera_radius_m[k]) / 1000, 1),
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

    save_bytes("input.world.json", canonical_json(world_project_document(result.world.project)))
    if result.geology is not None:
        save_bytes("input.geology.json", canonical_json(geology_document(result.geology)))
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
    if result.forcing.basin_depth_m is not None:
        arrays["basin_depth_m"] = result.forcing.basin_depth_m.astype("<f4")
    if result.forcing.flood_basalt is not None:
        arrays["flood_basalt"] = result.forcing.flood_basalt.astype("<f4")
    v = result.volcanoes
    arrays |= {
        "wonder_m": result.wonder_m.astype("<f4"),
        "crater_xyz": result.wonders.craters.xyz.astype("<f8"),
        "crater_radius_m": result.wonders.craters.radius_m.astype("<f8"),
        "crater_depth_m": result.wonders.craters.depth_m.astype("<f8"),
        **paths_archive("chasm", result.wonders.chasms.paths, result.wonders.chasms.depth_m),
        "chasm_width_m": result.wonders.chasms.width_m.astype("<f8"),
        **paths_archive("cliff", result.wonders.cliffs.paths, result.wonders.cliffs.trough_m),
        "cliff_height_m": result.wonders.cliffs.height_m.astype("<f8"),
        "tepui_xyz": result.wonders.tepuis.xyz.astype("<f8"),
        "tepui_radius_m": result.wonders.tepuis.radius_m.astype("<f8"),
        "tepui_height_m": result.wonders.tepuis.height_m.astype("<f8"),
        "tepui_aspect": result.wonders.tepuis.aspect.astype("<f8"),
        "tepui_azimuth": result.wonders.tepuis.azimuth.astype("<f8"),
        **paths_archive(
            "lava", result.wonders.eruptions.flows,
            tuple(np.zeros(len(flow)) for flow in result.wonders.eruptions.flows),
        ),
        "lava_width_m": result.wonders.eruptions.flow_width_m.astype("<f8"),
        "lava_fresh": result.wonders.eruptions.flow_fresh.astype("<f8"),
        "vent_xyz": result.wonders.eruptions.vent_xyz.astype("<f8"),
        "vent_radius_m": result.wonders.eruptions.vent_radius_m.astype("<f8"),
        "plume_azimuth": result.wonders.eruptions.plume_azimuth.astype("<f8"),
        "plume_length_m": result.wonders.eruptions.plume_length_m.astype("<f8"),
        "oasis_xyz": result.wonders.oases.xyz.astype("<f8"),
        "oasis_radius_m": result.wonders.oases.radius_m.astype("<f8"),
        "fork_split_xyz": result.wonders.forks.split_xyz.astype("<f8"),
        "fork_branch_xyz": result.wonders.forks.branch_xyz.astype("<f8"),
        "fork_discharge_m3_s": result.wonders.forks.discharge_m3_s.astype("<f8"),
        "fork_area_m2": result.wonders.forks.area_m2.astype("<f8"),
        **paths_archive(
            "aging", tuple(patch.xyz for patch in result.wonders.aging.patches),
            tuple(patch.relief_m for patch in result.wonders.aging.patches),
        ),
        "aging_centre": np.array(
            [patch.centre for patch in result.wonders.aging.patches], dtype="<f8"
        ).reshape(-1, 3),
        "aging_reach_m": np.array(
            [patch.reach_m for patch in result.wonders.aging.patches], dtype="<f8"
        ),
        "aging_kind": np.array(
            [AGING_KINDS.index(patch.kind) for patch in result.wonders.aging.patches], dtype="<i1"
        ),
        "aging_member_offsets": np.cumsum(
            [0, *(len(patch.members) for patch in result.wonders.aging.patches)]
        ).astype("<i8"),
        "aging_members": np.array(
            [m for patch in result.wonders.aging.patches for m in patch.members], dtype="<i8"
        ),
        "aging_spacing_m": np.array(
            [patch.spacing_m for patch in result.wonders.aging.patches], dtype="<f8"
        ),
        "aging_age_myr": np.array(
            [patch.age_myr for patch in result.wonders.aging.patches], dtype="<f8"
        ),
        "volcanic_m": result.volcanic_m.astype("<f4"),
        "volcano_xyz": v.xyz.astype("<f8"),
        "volcano_height_m": v.height_m.astype("<f4"),
        "volcano_radius_m": v.radius_m.astype("<f4"),
        "volcano_kind": v.kind.astype("<i1"),
        "volcano_setting": v.setting.astype("<i1"),
        "volcano_active": v.active,
        "volcano_age_myr": v.age_myr.astype("<f4"),
        "volcano_caldera_radius_m": v.caldera_radius_m.astype("<f4"),
        "volcano_caldera_depth_m": v.caldera_depth_m.astype("<f4"),
        "volcano_summit_m": v.summit_m.astype("<f4"),
        "volcano_emergent": v.emergent,
        "volcanic_island": result.islands,
    }
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
            "continentality": climate.continentality.astype("<f4"),
            "precipitation_warm_half_mm": climate.precip_warm_mm.astype("<f4"),
            "precipitation_cold_half_mm": climate.precip_cold_mm.astype("<f4"),
            "koppen": climate.koppen.astype("i1"),
            "ice_m": result.ice.thickness_m.astype("<f4"),
            "ice_balance_m": result.ice.balance_m.astype("<f4"),
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
    volcanoes = volcano_features(result)
    save_bytes("volcanoes.geojson", json.dumps(volcanoes, separators=(",", ":")).encode("utf-8"))
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
        "volcanoes": _volcano_summary(
            result, _pixel_area_km2(rasters.raster, rasters.islands_px)
        ),
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


def _pixel_area_km2(raster: FrameRaster, mask: NDArray[np.bool_]) -> float:
    """Area (km^2) of masked pixels on the world-frame raster."""
    rows, columns = raster.shape
    radius = raster.frame.radius_km
    cell = (2 * np.pi * radius / columns) * (np.pi * radius / rows) * np.cos(raster.latitude)
    return float((mask * cell[:, None]).sum())


def _volcano_summary(result: PlanetResult, island_area_km2: float) -> dict[str, object]:
    v = result.volcanoes
    on_land = 0
    if len(v):
        nearest = sample_field(result.mesh, v.xyz, result.land.astype(np.float64))
        on_land = int(np.sum(nearest > 0.5))
    return {
        "count": len(v),
        "active": int(v.active.sum()),
        "on_land": on_land,
        "islands": int(v.emergent.sum()),
        "island_area_km2": round(island_area_km2, 1),
        "by_kind": {name: int(np.sum(v.kind == k)) for k, name in enumerate(VOLCANO_KINDS)},
        "by_setting": {
            name: int(np.sum(v.setting == k)) for k, name in enumerate(VOLCANO_SETTINGS)
        },
    }


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
        "ice_sheet_share": round(float(weight[result.ice.thickness_m > 0].sum() / total), 4),
        "biome_share": {
            name: float(weight[climate.biome == k].sum() / total)
            for k, name in enumerate(BIOMES)
            if k > 0
        },
        "koppen_share": {
            name: round(float(weight[climate.koppen == k].sum() / total), 4)
            for k, name in enumerate(KOPPEN)
            if k > 0 and np.any(result.land & (climate.koppen == k))
        },
        "koppen_group_share": koppen_group_share(
            climate.koppen[result.land], result.mesh.area_m2[result.land]
        ),
    }
