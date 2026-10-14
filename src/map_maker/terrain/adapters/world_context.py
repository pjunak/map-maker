"""Portable context products with a last-published, hash-addressed manifest."""

import os
from collections.abc import Callable, Mapping
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import numpy as np

from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.adapters.world_context_render import CONTEXT_LAYERS, context_image
from map_maker.terrain.adapters.world_project import world_project_document
from map_maker.terrain.adapters.world_svg import WORLD_IMPORTER
from map_maker.terrain.domain.world import WORLD_PREPARATION
from map_maker.terrain.domain.world_context import (
    EXPOSURE_BEARINGS,
    WORLD_CONTEXT_ALGORITHM,
    exposure_range_km,
    exposure_steps,
)
from map_maker.terrain.pipeline.world_connectivity import CONNECTIVITY_ALGORITHM
from map_maker.terrain.pipeline.world_context import WorldContext

CONTEXT_SCHEMA = "map-maker.world-context"
CONTEXT_VERSION = 4
CONTEXT_PREVIEWS = (
    "land.png",
    "water.png",
    "support.png",
    "gateways.png",
    "shore-distance.png",
    "exposure-north.png",
    "exposure-support-north.png",
    "connectivity.png",
)
CONTEXT_OUTPUTS = (
    "input.world.json",
    "geography.npz",
    "exposure.npz",
    "connectivity.npz",
    *CONTEXT_PREVIEWS,
)
MAX_CONTEXT_MANIFEST_BYTES = 4 * 1024 * 1024


def context_input_sha256(context: WorldContext) -> str:
    return sha256(
        canonical_json(
            {
                "world": world_project_document(context.world.project),
                "settings": asdict(context.grid.settings),
                "algorithm": WORLD_CONTEXT_ALGORITHM,
            }
        )
    ).hexdigest()


def context_document(
    context: WorldContext,
    runtime: dict[str, object],
    outputs: Mapping[str, object],
) -> dict[str, object]:
    """Single manifest contract for writing and verifying stored metadata."""
    rows, columns = context.grid.shape
    frame = context.grid.frame
    document: dict[str, object] = {
        "schema": CONTEXT_SCHEMA,
        "version": CONTEXT_VERSION,
        "algorithm": WORLD_CONTEXT_ALGORITHM,
        "importer": WORLD_IMPORTER,
        "preparation": WORLD_PREPARATION,
        "input_sha256": context_input_sha256(context),
        "runtime": runtime,
        "settings": asdict(context.grid.settings),
        "grid": {
            "rows": rows,
            "columns": columns,
            "registration": "cell-centre",
            "projection": "spherical-plate-carree",
            "longitude_periodic": True,
            "pole_policy": "finite-edge-gateways; no point-contact water links",
            "angular_step_deg": context.grid.angular_step_deg,
            "north_south_spacing_km": context.grid.north_south_spacing_km,
            "frame": {
                "bounds": [float(value) for value in frame.bounds],
                "radius_km": float(frame.radius_km),
                "central_meridian_deg": float(frame.central_meridian_deg),
            },
        },
        "areas_km2": {
            "sphere": frame.surface_area_km2,
            "land": context.land_area_km2,
            "water": sum(b.area_km2 for b in context.water_bodies),
            "land_conservation_error": context.area_error_km2,
        },
        "support": {
            "mixed_cells": context.mixed_cells,
            "split_water_cells": context.split_water_cells,
            "land_without_centre": context.subcell_land_cells,
            "water_without_centre": context.subcell_water_cells,
        },
        "water_bodies": [asdict(body) for body in context.water_bodies],
        "gateways": {
            "measurement": "longest-continuous-shared-edge-water-interval",
            "units": "km",
            "east_seam": "last-column-to-first; both-sides-open",
            "south_pole": "zero-width; no-polar-links",
            "positive_east_faces": int(np.count_nonzero(context.east_opening_km)),
            "positive_south_faces": int(np.count_nonzero(context.south_opening_km)),
        },
        "shore_distance": {
            "measurement": "cell-centre-to-nearest-sampled-shore",
            "units": "km",
            "includes_inland_water": True,
            "no_shoreline": "nan",
            **asdict(context.shore_sampling),
        },
        "exposure": {
            "measurement": "great-circle-weighted-water-fraction",
            "bearings": list(EXPOSURE_BEARINGS),
            "range_km": exposure_range_km(context.grid),
            "distance_samples": exposure_steps(context.grid),
            "sample_step_km": exposure_range_km(context.grid) / exposure_steps(context.grid),
            "weight": "exp(-3*distance/range); normalized-midpoints",
            "mixed_support": "quadrature-weight-on-mixed-cells; not-error-bound",
            "land_blocks_rays": False,
            "preview_bearing": "N",
        },
        "connectivity": {
            "algorithm": CONNECTIVITY_ALGORITHM,
            "pieces": len(context.connectivity.water_body),
            "links": len(context.connectivity.link_nodes),
            "components": context.connectivity.component_count,
            "fragmented_bodies": list(context.connectivity.fragmented_bodies),
            "fragmentation_policy": "retain-pieces; no-inferred-links; transport-unsupported",
            "split_cells": context.connectivity.split_cells,
            "registration": "row-major-cell-offsets; zero-based-piece-indices",
            "links_policy": "undirected-positive-intervals; east-and-south-once; periodic-east",
            "interval_coordinates": "unit-face; east-north-to-south; south-west-to-east",
            "sample_coordinates": "unit-source-frame; interior-sites-not-flow-paths",
            "area_units": "km2",
            "width_units": "km",
        },
        "outputs": outputs,
    }
    document["context_sha256"] = sha256(canonical_json(document)).hexdigest()
    return document


def write_world_context(
    context: WorldContext,
    runtime: dict[str, object],
    destination: Path,
    *,
    verify: Callable[[], None],
) -> Path:
    """Reserve a new directory. A failed/cancelled export has no completion manifest."""
    verify()
    target = destination.absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Context destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    snapshot = canonical_json(world_project_document(context.world.project))
    (target / "input.world.json").write_bytes(snapshot)
    verify()
    rows, columns = context.grid.shape
    np.savez_compressed(
        target / "geography.npz",
        allow_pickle=False,
        land_fraction=context.land_fraction.astype("<f8", copy=False),
        water_body=context.water_body.astype("<i4", copy=False),
        support_flags=context.support_flags,
        cell_area_km2=context.cell_area_km2.astype("<f8", copy=False),
        east_opening_km=context.east_opening_km.astype("<f8", copy=False),
        south_opening_km=context.south_opening_km.astype("<f8", copy=False),
        latitude_deg=np.array([context.grid.latitude_deg(r) for r in range(rows)], dtype="<f8"),
        longitude_deg=np.array(
            [context.grid.longitude_deg(c) for c in range(columns)], dtype="<f8"
        ),
    )
    verify()
    np.savez_compressed(
        target / "exposure.npz",
        allow_pickle=False,
        shore_distance_km=context.shore_distance_km.astype("<f8", copy=False),
        water_exposure=context.water_exposure.astype("<f4", copy=False),
        exposure_mixed_support=context.exposure_mixed_support.astype("<f4", copy=False),
    )
    verify()
    np.savez_compressed(
        target / "connectivity.npz",
        allow_pickle=False,
        **{
            name: value.astype(value.dtype.newbyteorder("<"), copy=False)
            for name, value in context.connectivity.arrays().items()
        },
    )
    names = ["input.world.json", "geography.npz", "exposure.npz", "connectivity.npz"]
    for layer, name in zip(CONTEXT_LAYERS, CONTEXT_PREVIEWS, strict=True):
        verify()
        with context_image(context, layer) as image:
            image.save(target / name)
        names.append(name)
    outputs = {
        name: {"sha256": file_sha256(target / name), "bytes": (target / name).stat().st_size}
        for name in names
    }
    manifest = context_document(context, runtime, outputs)
    verify()
    pending = target / "manifest.pending"
    with pending.open("xb") as stream:
        encoded = canonical_json(manifest)
        if len(encoded) > MAX_CONTEXT_MANIFEST_BYTES:
            raise ValueError("Context manifest exceeds 4 MiB; reduce source complexity.")
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    verify()
    complete = target / "context.json"
    pending.replace(complete)
    return complete
