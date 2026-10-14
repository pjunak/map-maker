"""Sample frozen context with conservative distance bounds and no coastline editing."""

import json
from dataclasses import asdict
from hashlib import sha256
from typing import Any

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.domain.terrain_context import (
    CONTEXT_SAMPLE_FIELDS,
    TERRAIN_CONTEXT_MODEL,
    TerrainWorldContext,
)


def context_metadata(context: TerrainWorldContext) -> dict[str, Any]:
    data = asdict(context)
    for name, _dtype, _channels in CONTEXT_SAMPLE_FIELDS:
        del data[name]
    return {"model": TERRAIN_CONTEXT_MODEL, **data}


def context_identity(context: TerrainWorldContext) -> str:
    digest = sha256(json.dumps(context_metadata(context), sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode("utf-8"))
    for name, _dtype, _channels in CONTEXT_SAMPLE_FIELDS:
        digest.update(getattr(context, name))
    return digest.hexdigest()


def context_arrays(context: TerrainWorldContext) -> dict[str, NDArray[Any]]:
    arrays: dict[str, NDArray[Any]] = {}
    for name, dtype, channels in CONTEXT_SAMPLE_FIELDS:
        shape = context.grid.shape if channels == 1 else (channels, *context.grid.shape)
        arrays[name] = np.frombuffer(getattr(context, name), dtype=dtype).reshape(shape)
    if any(not np.all(np.isfinite(value)) for value in arrays.values()):
        raise ValueError("Terrain context contains non-finite samples.")
    lower, upper = arrays["shore_lower_km"], arrays["shore_upper_km"]
    if np.any(lower < 0) or np.any(upper < lower):
        raise ValueError("Terrain context shoreline bounds are invalid.")
    for name in ("land_fraction", "water_exposure", "exposure_mixed_support"):
        if np.any((arrays[name] < 0) | (arrays[name] > 1)):
            raise ValueError(f"Terrain context {name} must be between zero and one.")
    if (np.any(np.abs(arrays["latitude_deg"]) > 90)
            or np.any((arrays["longitude_deg"] < -180) | (arrays["longitude_deg"] >= 180))
            or np.any(arrays["support_flags"] > 15)):
        raise ValueError("Terrain context coordinates or support flags are invalid.")
    water_ids = {0, *(b.id for b in context.water_bodies)}
    if not set(np.unique(arrays["water_body"]).tolist()) <= water_ids:
        raise ValueError("Terrain context water labels refer to an unknown body.")
    return arrays


class PreparedWorldContext:
    def __init__(self, context: TerrainWorldContext) -> None:
        self.context = context
        self.arrays = context_arrays(context)

    def shore_bounds(
        self, x: NDArray[np.float64], y: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Distance-to-set is 1-Lipschitz; AEQD planar distance bounds spherical distance."""
        grid = self.context.grid
        a, b, c, d = grid.extent_km
        if (np.any(~np.isfinite(x)) or np.any(~np.isfinite(y))
                or np.any(x < a-1e-9) or np.any(x > c+1e-9)
                or np.any(y < b-1e-9) or np.any(y > d+1e-9)):
            raise ValueError("Terrain sampling extends outside its retained world context.")
        fx = (np.clip(x, a, c)-a) / grid.x_spacing_km
        fy = (np.clip(y, b, d)-b) / grid.y_spacing_km
        ix = np.minimum(np.floor(fx).astype(np.int64), grid.width-2)
        iy = np.minimum(np.floor(fy).astype(np.int64), grid.height-2)
        tx, ty = fx-ix, fy-iy
        lower = np.zeros(x.shape, dtype=np.float64)
        upper = np.zeros(x.shape, dtype=np.float64)
        for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            px, py = a+(ix+ox)*grid.x_spacing_km, b+(iy+oy)*grid.y_spacing_km
            distance = np.hypot(x-px, y-py) + 1e-8
            weight = (tx if ox else 1-tx) * (ty if oy else 1-ty)
            lower += weight*(self.arrays["shore_lower_km"][iy+oy, ix+ox]-distance)
            upper += weight*(self.arrays["shore_upper_km"][iy+oy, ix+ox]+distance)
        lower = np.maximum(lower, 0)
        if np.any(lower > upper+1e-7):
            raise ValueError("Terrain context has inconsistent shoreline-distance bounds.")
        return lower, np.maximum(lower, upper)

    def coastal_distance(
        self, x: NDArray[np.float64], y: NDArray[np.float64], local_distance: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        # The upper bound avoids inventing a zero-height strip where context is coarse.
        # Exact vector distance still makes every source coastline zero.
        _lower, upper = self.shore_bounds(x, y)
        return np.minimum(local_distance, upper)


def context_report(context: TerrainWorldContext | None) -> dict[str, object] | None:
    if context is None:
        return None
    return {
        **context_metadata(context), "binding_sha256": context_identity(context),
        "status": "experimental-rough-terrain",
        "consumed": ["shore_upper_km", "metric_projection", "source_identity"],
        "retained": ["shore_lower_km", "latitude_deg", "longitude_deg", "land_fraction",
                     "water_body", "support_flags", "water_exposure", "exposure_mixed_support",
                     "water_bodies", "fragmented_water_bodies", "geology_sha256"],
        "unsupported": ["climate", "runoff", "aging", "bathymetry-coupling",
                        "water-transport-graph"],
        "coastal_operation": "min(local-vector-distance, conservative-geographic-upper-bound)",
        "land_mask": "projected-vector-coastline-only",
        "water_labels": "nearest-source-cell-display-id; not point membership",
        "exposure": "all-water geographic exposure; not rainfall or ocean fetch",
        "support": "mixed-exposure fraction is quadrature support, not an error bound",
    }
