"""Numeric regional samples and completion-last provenance publication."""

import os
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import numpy as np
from PIL.PngImagePlugin import PngInfo

from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.adapters.project import PROJECT_SCHEMA_VERSION, settings_to_json
from map_maker.terrain.adapters.render import render_ground_map
from map_maker.terrain.domain import EndpointGrid, LocalMetricFrame, TerrainProject
from map_maker.terrain.domain.coordinates import Bounds
from map_maker.terrain.domain.regional import REGIONAL_SAMPLE_LIMIT
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
)
from map_maker.terrain.pipeline.landforms import LANDFORM_ALGORITHM_ID
from map_maker.terrain.pipeline.regional import (
    REGIONAL_SAMPLING_ALGORITHM_ID,
    RegionalTerrainSamples,
)

REGIONAL_SCHEMA_VERSION = 3


def _write_json(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def write_regional_products(
    samples: RegionalTerrainSamples, project: TerrainProject, destination: Path,
) -> dict[str, object]:
    """Export the buffered numeric samples and a ground preview cropped after shading."""
    with (destination / "samples.npz").open("xb") as stream:
        np.savez_compressed(
            stream, elevation_m=samples.elevation_m.astype("<f4", copy=False),
            land_mask=samples.land_mask, x_km=samples.x_km.astype("<f8", copy=False),
            y_km=samples.y_km.astype("<f8", copy=False),
            water_surface_m=samples.water_surface_m.astype("<f4", copy=False),
            basin_intent_ids=samples.basin_intent_ids.astype("<u4", copy=False),
        )
        stream.flush()
        os.fsync(stream.fileno())
    _write_json(destination / "inputs.json", asdict(project))
    with render_ground_map(samples.elevation_m, samples.land_mask,
                           samples.request.grid(include_halo=True),
                           samples.maximum_elevation_m) as buffered:
        rows, columns = samples.request.core_slices
        with buffered.crop((columns.start, rows.start, columns.stop, rows.stop)) as image:
            metadata = PngInfo()
            for key, value in buffered.info.items():
                metadata.add_text(str(key), str(value))
            metadata.add_text("map-maker.sampling_algorithm", REGIONAL_SAMPLING_ALGORITHM_ID)
            metadata.add_text("map-maker.source_field_id", samples.request.source_id)
            metadata.add_text("map-maker.numeric_source_sha256",
                              file_sha256(destination / "samples.npz"))
            metadata.add_text("map-maker.note", "Denser unchanged-field ground samples. "
                              "No new detail bands or refined hydrology.")
            with (destination / "scientific.png").open("xb") as stream:
                image.save(stream, format="PNG", pnginfo=metadata)
                stream.flush()
                os.fsync(stream.fileno())
    return {
        name: {"sha256": file_sha256(destination / name),
               "bytes": (destination / name).stat().st_size, "role": role}
        for name, role in (("samples.npz", "authoritative"), ("inputs.json", "input-snapshot"),
                           ("scientific.png", "derived"))
    }


def _grid(grid: EndpointGrid) -> dict[str, object]:
    return {**asdict(grid), "x_spacing_km": grid.x_spacing_km, "y_spacing_km": grid.y_spacing_km}


def publish_regional_manifest(
    samples: RegionalTerrainSamples, project: TerrainProject, destination: Path, *,
    requested_bounds_km: Bounds, project_sha256: str, svg_sha256: str,
    runtime: dict[str, object], outputs: dict[str, object],
) -> Path:
    """Describe this sampling experiment without presenting it as a complete terrain build."""
    request = samples.request
    frame = LocalMetricFrame(project.coastline.bounds, project.settings.object_scale_km)
    rows, columns = request.core_slices
    document: dict[str, object] = {
        "schema": "map-maker.terrain-regional-samples", "schema_version": REGIONAL_SCHEMA_VERSION,
        "status": "complete",
        "source": {"kind": "input-defined-field", "field_id": request.source_id,
                   "project_sha256": project_sha256, "svg_sha256": svg_sha256,
                   "project_schema_version": PROJECT_SCHEMA_VERSION},
        "settings": settings_to_json(project.settings), "runtime": runtime,
        "algorithms": {
            "regional_sampling": REGIONAL_SAMPLING_ALGORITHM_ID,
            "generator": GENERATOR_ALGORITHM_ID, "automatic_valleys": AUTOMATIC_VALLEY_ALGORITHM_ID,
            "noise": NOISE_ALGORITHM_ID, "landforms": LANDFORM_ALGORITHM_ID,
            "seed_policy": SEED_POLICY_ID,
            "stage_seeds": {stage: stage_seed(project.settings.seed, stage)
                            for stage in (RELIEF_STAGE_ID, LANDFORM_STAGE_ID)},
        },
        "request": {"requested_bounds_km": requested_bounds_km, "refinement": request.refinement,
                    "window_inclusive": request.window, "halo_cells": request.halo_cells,
                    "sample_window_inclusive": request.sample_window,
                    "sample_limit": REGIONAL_SAMPLE_LIMIT},
        "coordinates": {"model": frame.model_id, "world_crs": None,
                        "source_bounds": frame.source_bounds,
                        "km_per_source_unit": frame.km_per_source_unit,
                        "origin": "minimum source x and y", "x_direction": "source-right",
                        "y_direction": "source-down", "registration": "endpoint-nodes",
                        "horizontal_units": "km", "elevation_units": "m",
                        "elevation_dtype": "float32", "nodata": "NaN outside land mask"},
        "reference_grid": _grid(request.reference_grid), "core_grid": _grid(request.grid()),
        "sample_grid": _grid(request.grid(include_halo=True)),
        "canonical_routing_grid": _grid(samples.canonical_grid),
        "core_slice": {"rows": [rows.start, rows.stop], "columns": [columns.start, columns.stop]},
        "capabilities": {"adds_detail_bands": False, "conditions_on_parent_dem": False,
                         "refines_hydrology": False,
                         "water": "authored-level-samples-without-local-flow-review"},
        "outputs": outputs,
    }
    document["artifact_id"] = sha256(canonical_json(document)).hexdigest()
    pending = destination / ".manifest.pending"
    _write_json(pending, document)
    manifest = destination / "manifest.json"
    os.replace(pending, manifest)
    return manifest
