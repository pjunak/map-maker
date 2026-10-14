"""Publish independent parent-region artifacts and review images, never modify a parent."""

import os
from contextlib import closing
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import numpy as np
from PIL.PngImagePlugin import PngInfo

from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.adapters.parent import LoadedTerrainParent
from map_maker.terrain.adapters.project import project_snapshot_to_json
from map_maker.terrain.adapters.regional_review import render_parent_comparison
from map_maker.terrain.adapters.render import render_ground_map
from map_maker.terrain.domain.coordinates import Bounds, EndpointGrid, LocalMetricFrame
from map_maker.terrain.domain.regional import (
    DETAIL_CELL_LIMIT,
    DETAIL_PROBE_INTERVALS,
    REGIONAL_SAMPLE_LIMIT,
    RegionalDetailSettings,
)
from map_maker.terrain.domain.seeds import LOCAL_DETAIL_STAGE_ID, SEED_POLICY_ID, stage_seed
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.detail import LOCAL_DETAIL_ALGORITHM_ID, DetailedRegion
from map_maker.terrain.pipeline.parent import PARENT_REPLAY_ALGORITHM_ID, VerifiedTerrainParent
from map_maker.terrain.pipeline.regional import (
    REGIONAL_SAMPLING_ALGORITHM_ID,
    RegionalTerrainSamples,
)


def _json(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def write_parent_region_products(
    samples: RegionalTerrainSamples,
    parent: VerifiedTerrainParent,
    destination: Path,
    detail: DetailedRegion | None,
    *, cancellation: CancellationToken | None = None,
) -> dict[str, object]:
    check_cancelled(cancellation)
    arrays = {
        name: getattr(samples, name)
        for name in (
            "elevation_m",
            "land_mask",
            "x_km",
            "y_km",
            "water_surface_m",
            "basin_intent_ids",
        )
    }
    if detail is not None:
        arrays.update(
            {
                name: getattr(detail, name)
                for name in (
                    "reference_elevation_m",
                    "added_detail_m",
                    "cell_columns",
                    "cell_rows",
                    "cell_amplitude_m",
                    "reference_cell_mean_m",
                    "detailed_cell_mean_m",
                )
            }
        )
    with (destination / "samples.npz").open("xb") as stream:
        np.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    check_cancelled(cancellation)
    _json(destination / "inputs.json", project_snapshot_to_json(parent.data.project))
    rows, columns = samples.request.core_slices
    crop = (columns.start, rows.start, columns.stop, rows.stop)
    note = (
        "EXPERIMENTAL additive detail; hydrology unreviewed; no small-river readiness."
        if detail
        else "Verified parent field sampled more densely; no new detail or hydrology."
    )
    metadata = PngInfo()
    metadata.add_text("map-maker.parent_build_id", parent.data.build_id)
    metadata.add_text("map-maker.numeric_source_sha256", file_sha256(destination / "samples.npz"))
    metadata.add_text("map-maker.note", note)
    paths = [("samples.npz", "authoritative"), ("inputs.json", "input-snapshot")]
    with (
        closing(render_ground_map(
            samples.elevation_m,
            samples.land_mask,
            samples.request.grid(include_halo=True),
            samples.maximum_elevation_m, cancellation=cancellation,
        )) as buffered,
        closing(buffered.crop(crop)) as image,
    ):
        with (destination / "scientific.png").open("xb") as stream:
            image.save(stream, format="PNG", pnginfo=metadata)
        paths.append(("scientific.png", "derived"))
        check_cancelled(cancellation)
        if detail is not None:
            with (
                closing(render_ground_map(
                    detail.reference_elevation_m,
                    samples.land_mask,
                    samples.request.grid(include_halo=True),
                    samples.maximum_elevation_m, cancellation=cancellation,
                )) as reference_buffered,
                closing(reference_buffered.crop(crop)) as reference,
                closing(render_parent_comparison(
                    reference, image, detail.added_detail_m[rows, columns],
                    cancellation=cancellation,
                )) as review,
            ):
                for key, value in review.info.items():
                    metadata.add_text(str(key), str(value))
                with (destination / "comparison.png").open("xb") as stream:
                    review.save(stream, format="PNG", pnginfo=metadata)
            paths.append(("comparison.png", "derived"))
    return {
        name: {
            "sha256": file_sha256(destination / name),
            "bytes": (destination / name).stat().st_size,
            "role": role,
        }
        for name, role in paths
    }


def publish_parent_region_manifest(
    samples: RegionalTerrainSamples,
    loaded: LoadedTerrainParent,
    parent: VerifiedTerrainParent,
    destination: Path,
    *,
    bounds_km: Bounds,
    runtime: dict[str, object],
    outputs: dict[str, object],
    detail_settings: RegionalDetailSettings | None,
    detail: DetailedRegion | None,
) -> Path:
    request = samples.request
    rows, columns = request.core_slices

    def grid(value: EndpointGrid) -> dict[str, object]:
        return {
            **asdict(value),
            "x_spacing_km": value.x_spacing_km,
            "y_spacing_km": value.y_spacing_km,
        }

    products = {name: digest for name, _size, digest in loaded.products}
    document: dict[str, object] = {
        "schema": "map-maker.terrain-parent-region",
        "schema_version": 1,
        "status": "complete",
        "mode": "experimental-detail" if detail else "reference-samples",
        "parent": {
            "build_id": parent.data.build_id,
            "manifest_sha256": loaded.manifest_sha256,
            "elevation_sha256": products["elevation.npy"],
            "routing_sha256": products["routing.npz"],
            "input_snapshot_sha256": products["inputs.json"],
            "project_sha256": loaded.project_sha256,
            "svg_sha256": loaded.svg_sha256,
            "replay_algorithm": PARENT_REPLAY_ALGORITHM_ID,
            "verified_ground_nodes": parent.verified_ground_nodes,
            "verified_routing_nodes": parent.verified_routing_nodes,
        },
        "runtime": runtime,
        "algorithms": {
            "regional_sampling": REGIONAL_SAMPLING_ALGORITHM_ID,
            "local_detail": LOCAL_DETAIL_ALGORITHM_ID if detail else None,
            "seed_policy": SEED_POLICY_ID,
            "detail_stage_seed": stage_seed(
                parent.data.project.settings.seed, LOCAL_DETAIL_STAGE_ID
            )
            if detail
            else None,
        },
        "request": {
            "requested_bounds_km": bounds_km,
            "refinement": request.refinement,
            "window_inclusive": request.window,
            "halo_cells": request.halo_cells,
            "sample_window_inclusive": request.sample_window,
            "sample_limit": REGIONAL_SAMPLE_LIMIT,
        },
        "reference_grid": grid(request.reference_grid),
        "core_grid": grid(request.grid()),
        "sample_grid": grid(request.grid(include_halo=True)),
        "canonical_routing_grid": grid(samples.canonical_grid),
        "coordinates": {
            "model": LocalMetricFrame.model_id,
            "world_crs": None,
            "x_direction": "source-right",
            "y_direction": "source-down",
            "horizontal_units": "km",
            "elevation_units": "m",
            "registration": "endpoint-nodes",
            "nodata": "NaN outside land mask",
        },
        "core_slice": {"rows": [rows.start, rows.stop], "columns": [columns.start, columns.stop]},
        "detail": None
        if detail is None
        else {
            "settings": asdict(detail_settings) if detail_settings is not None else None,
            "evidence": asdict(detail.evidence),
            "cell_limit": DETAIL_CELL_LIMIT,
            "probe_intervals": DETAIL_PROBE_INTERVALS,
            "restriction": "zero-analytic-added-cell-mean; fixed-trapezoid-reference-moments",
            "acceptance": "experimental-not-accepted-for-cartographic-use",
        },
        "capabilities": {
            "verified_parent_replay": True,
            "adds_residual_detail": detail is not None,
            "refines_hydrology": False,
            "small_rivers_ready": False,
            "water": "unchanged-authored-level-samples-without-local-flow-review",
        },
        "outputs": outputs,
    }
    document["artifact_id"] = sha256(canonical_json(document)).hexdigest()
    pending = destination / ".manifest.pending"
    _json(pending, document)
    manifest = destination / "manifest.json"
    os.replace(pending, manifest)
    return manifest
