"""Numeric build products and a manifest for the existing local coordinate plane."""

import json
import os
import platform
import sys
from contextlib import closing
from dataclasses import asdict
from hashlib import file_digest, sha256
from importlib.metadata import version
from pathlib import Path

import numpy as np
import shapely

import map_maker
from map_maker.terrain.adapters.geotiff import (
    geotiff_metadata,
    rasterio_native_versions,
    write_terrain_geotiff,
)
from map_maker.terrain.adapters.project import (
    INPUT_SNAPSHOT_VERSION,
    PROJECT_SCHEMA_VERSION,
    project_snapshot_to_json,
    settings_to_json,
)
from map_maker.terrain.adapters.render import (
    render_drainage_review,
    render_height_map,
    save_height_map,
)
from map_maker.terrain.domain import LocalMetricFrame, TerrainProject
from map_maker.terrain.domain.seeds import (
    LANDFORM_STAGE_ID,
    RELIEF_STAGE_ID,
    SEED_POLICY_ID,
    stage_seed,
)
from map_maker.terrain.pipeline.generate import (
    AUTOMATIC_VALLEY_ALGORITHM_ID,
    GENERATOR_ALGORITHM_ID,
    NOISE_ALGORITHM_ID,
    GeneratedTerrain,
)
from map_maker.terrain.pipeline.landforms import LANDFORM_ALGORITHM_ID
from map_maker.terrain.pipeline.quality import TerrainQuality
from map_maker.terrain.pipeline.terrain_context import context_report

BUILD_SCHEMA_VERSION = 20


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def runtime_identity() -> dict[str, object]:
    """Fingerprint installed source, including editable changes, without Git."""
    package = Path(map_maker.__file__).parent
    sources = {
        path.relative_to(package).as_posix(): file_sha256(path)
        for path in sorted(package.rglob("*.py"))
    }
    gdal, proj = rasterio_native_versions()
    return {
        "map_maker_version": map_maker.__version__,
        "package_source_sha256": sha256(canonical_json(sources)).hexdigest(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
        "dependencies": {
            name: version(name)
            for name in ("numpy", "scipy", "Pillow", "shapely", "svgelements", "rasterio", "affine")
        },
        "geos": shapely.geos_version_string,
        "gdal": gdal,
        "proj": proj,
    }


def _write_json(path: Path, value: object) -> None:
    data = canonical_json(value)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def write_build_products(
    terrain: GeneratedTerrain,
    project: TerrainProject,
    quality: TerrainQuality,
    destination: Path,
) -> dict[str, object]:
    """Write to an exclusively reserved build directory; return file identities."""
    paths: list[tuple[str, str]] = []
    for name, array in (
        ("elevation.npy", terrain.elevation_m.astype("<f4", copy=False)),
        ("land-mask.npy", terrain.land_mask),
        ("x-km.npy", terrain.x_km.astype("<f8", copy=False)),
        ("y-km.npy", terrain.y_km.astype("<f8", copy=False)),
    ):
        with (destination / name).open("xb") as stream:
            np.save(stream, array, allow_pickle=False)
            stream.flush()
            os.fsync(stream.fileno())
        paths.append((name, "authoritative"))
    write_terrain_geotiff(
        terrain, destination / "elevation.tif",
        elevation_sha256=file_sha256(destination / "elevation.npy"),
    )
    paths.append(("elevation.tif", "authoritative"))
    routing = terrain.routing
    with (destination / "routing.npz").open("xb") as stream:
        np.savez_compressed(
            stream,
            x_km=np.linspace(terrain.grid.extent_km[0], terrain.grid.extent_km[2],
                             terrain.routing_grid.width),
            y_km=np.linspace(terrain.grid.extent_km[1], terrain.grid.extent_km[3],
                             terrain.routing_grid.height),
            land_mask=terrain.routing_land_mask,
            source_elevation_m=routing.source_elevation_m,
            filled_routing_elevation_m=routing.routing_elevation_m,
            final_elevation_m=terrain.routing_final_elevation_m,
            receivers=routing.receivers,
            accumulation_km2=routing.accumulation_km2,
            channel_mask=routing.channel_mask,
            channel_head_mask=routing.channel_head_mask,
            stream_order=routing.stream_order,
            outlet_mask=routing.outlet_mask,
            retention_terminal_mask=routing.retention_terminal_mask,
            incision_m=routing.incision_m,
            incision_limit_m=routing.incision_limit_m,
            channel_conflict_flags=terrain.routing_conflicts.flags,
            channel_rise_m=terrain.routing_conflicts.rise_m,
            receiver_cut_deficit_m=terrain.routing_conflicts.receiver_cut_deficit_m,
            final_adjustment_rise_m=terrain.routing_conflicts.final_adjustment_rise_m,
            final_fill_depth_m=terrain.routing_conflicts.final_fill_depth_m,
            conditioned_final_elevation_m=terrain.drainage.filled_elevation_m,
            conditioned_final_receivers=terrain.drainage.receivers,
            basin_labels=terrain.drainage.basin_labels,
            nonland_class=terrain.drainage.nonland_class,
            boundary_flags=terrain.drainage.boundary_flags,
            basin_intent_ids=terrain.water.routing_intent_ids,
        )
        stream.flush()
        os.fsync(stream.fileno())
    paths.append(("routing.npz", "derived"))
    with (destination / "water.npz").open("xb") as stream:
        np.savez_compressed(
            stream, surface_m=terrain.water.surface_m, intent_ids=terrain.water.intent_ids,
            depth_m=np.where(np.isfinite(terrain.water.surface_m),
                             np.maximum(terrain.water.surface_m - terrain.elevation_m, 0), 0),
        )
        stream.flush()
        os.fsync(stream.fileno())
    paths.append(("water.npz", "derived"))
    with (destination / "basin-flow.npz").open("xb") as stream:
        np.savez_compressed(stream, internal_receivers=terrain.basin_outflow.internal_receivers,
                            flat_rank=terrain.basin_outflow.flat_rank,
                            internal_path_uphill_m=terrain.basin_outflow.internal_path_uphill_m,
                            catchment_class=terrain.basin_outflow.catchment_class,
                            retained_km2=terrain.basin_outflow.retained_km2,
                            source_km2=terrain.basin_outflow.source_km2,
                            throughput_km2=terrain.basin_outflow.throughput_km2,
                            terminal_km2=terrain.basin_outflow.terminal_km2)
        stream.flush()
        os.fsync(stream.fileno())
    paths.append(("basin-flow.npz", "derived"))
    with closing(render_drainage_review(terrain)) as review:
        review.save(destination / "drainage.png")
    paths.append(("drainage.png", "derived"))
    _write_json(destination / "inputs.json", project_snapshot_to_json(project))
    paths.append(("inputs.json", "input-snapshot"))
    _write_json(
        destination / "diagnostics.json",
        {
            "delivered_surface_quality": asdict(quality),
            "world_context": context_report(project.world_context),
            "canonical_drainage": asdict(terrain.drainage.summary),
            "routing_agreement": asdict(terrain.routing_agreement),
            "channel_conflicts": asdict(terrain.routing_conflicts.summary),
            "authored_water": asdict(terrain.water.review),
            "basin_outflow": asdict(terrain.basin_outflow.summary),
            "basin_flow_sha256": file_sha256(destination / "basin-flow.npz"),
            "water_sha256": file_sha256(destination / "water.npz"),
            "routing_sha256": file_sha256(destination / "routing.npz"),
            "elevation_sha256": file_sha256(destination / "elevation.npy"),
        },
    )
    paths.append(("diagnostics.json", "derived"))
    for style in ("cartographic", "scientific"):
        name = f"{style}.png"
        with closing(render_height_map(terrain, style=style)) as image:
            save_height_map(image, terrain, destination / name)
        paths.append((name, "derived"))
    return {
        name: {
            "sha256": file_sha256(destination / name),
            "bytes": (destination / name).stat().st_size,
            "role": role,
        }
        for name, role in paths
    }


def publish_build_manifest(
    terrain: GeneratedTerrain,
    project: TerrainProject,
    destination: Path,
    *,
    project_sha256: str,
    svg_sha256: str,
    runtime: dict[str, object],
    outputs: dict[str, object],
) -> Path:
    """Publish completion last, after inputs and all products have been checked."""
    frame = LocalMetricFrame(project.coastline.bounds, project.settings.object_scale_km)
    grid, routing_grid = terrain.grid, terrain.routing_grid
    settings = project.settings
    relief_seed = stage_seed(settings.seed, RELIEF_STAGE_ID)
    algorithms: dict[str, object] = {
        "generator": GENERATOR_ALGORITHM_ID,
        "automatic_valleys": AUTOMATIC_VALLEY_ALGORITHM_ID,
        "noise": NOISE_ALGORITHM_ID,
        "drainage_diagnostics": terrain.drainage.summary.algorithm_id,
        "seed_policy": SEED_POLICY_ID,
        "landforms": LANDFORM_ALGORITHM_ID,
        "stage_seeds": {RELIEF_STAGE_ID: relief_seed,
                        LANDFORM_STAGE_ID: stage_seed(settings.seed, LANDFORM_STAGE_ID)},
    }
    warnings = [
        "Products use a local metric plane; these rasters do not encode a world CRS.",
        "Canonical drainage diagnostics use a separate grid, not the exported DEM grid.",
    ]
    document: dict[str, object] = {
        "schema": "map-maker.terrain-build",
        "schema_version": BUILD_SCHEMA_VERSION,
        "status": "complete",
        "inputs": {
            "project_sha256": project_sha256,
            "svg_sha256": svg_sha256,
            "project_schema_version": PROJECT_SCHEMA_VERSION,
            "snapshot_schema_version": INPUT_SNAPSHOT_VERSION,
        },
        "settings": settings_to_json(settings),
        "world_context": context_report(project.world_context),
        "runtime": runtime,
        "algorithms": algorithms,
        "coordinates": {
            "model": frame.model_id,
            "world_crs": None,
            "planetary_radius_m": None,
            "source_bounds": frame.source_bounds,
            "km_per_source_unit": frame.km_per_source_unit,
            "origin": "minimum source x and y",
            "x_direction": "source-right",
            "y_direction": "source-down",
            "registration": grid.registration,
            "horizontal_units": "km",
            "elevation_units": "m",
            "elevation_dtype": "float32",
            "nodata": "NaN outside land mask",
            "extent_km": list(grid.extent_km),
            "width": terrain.width,
            "height": terrain.height,
            "x_spacing_km": grid.x_spacing_km,
            "y_spacing_km": grid.y_spacing_km,
        },
        "geotiff": geotiff_metadata(grid),
        "routing_grid": {
            "width": routing_grid.width,
            "height": routing_grid.height,
            "x_spacing_km": routing_grid.x_spacing_km,
            "y_spacing_km": routing_grid.y_spacing_km,
        },
        "outputs": outputs,
        "warnings": warnings,
    }
    document["build_id"] = sha256(canonical_json(document)).hexdigest()
    pending = destination / ".manifest.pending"
    _write_json(pending, document)
    manifest = destination / "manifest.json"
    os.replace(pending, manifest)
    return manifest
