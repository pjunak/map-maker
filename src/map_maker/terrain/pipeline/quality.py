"""Read-only spatial measurements of the delivered numeric terrain."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np
from numpy.typing import NDArray

QUALITY_ALGORITHM_ID = "masked-axis-semivariance@1"


@dataclass(frozen=True, slots=True)
class DirectionalMeasure:
    axis: Literal["x", "y"]
    requested_distance_km: float
    lag_intervals: int
    effective_distance_km: float
    pair_count: int
    mean_absolute_height_difference_m: float | None
    semivariance_m2: float | None


@dataclass(frozen=True, slots=True)
class TerrainQuality:
    algorithm_id: str
    land_sample_count: int
    total_sample_count: int
    minimum_m: float
    maximum_m: float
    mean_m: float
    standard_deviation_m: float
    x_spacing_km: float
    y_spacing_km: float
    directional: tuple[DirectionalMeasure, ...]


def measure_terrain_quality(
    elevation_m: NDArray[np.float32] | NDArray[np.float64],
    land_mask: NDArray[np.bool_],
    *,
    x_spacing_km: float,
    y_spacing_km: float,
    distances_km: tuple[float, ...] = (25.0, 100.0, 400.0),
) -> TerrainQuality:
    """Measure raw heights at physical lags, excluding paths across water/nodata.

    Samples are equally weighted, not estimates of cell-integrated land area.
    Distances round to the nearest interval (half upward), with at least one
    interval. Unsupported lags retain null measurements and zero pair counts.
    No detrending, interpolation, repair or rotation normalization is applied.
    """
    if elevation_m.ndim != 2 or elevation_m.shape != land_mask.shape:
        raise ValueError("Elevation and land mask must be matching two-dimensional grids.")
    if land_mask.dtype != np.bool_:
        raise ValueError("The land mask must contain boolean values.")
    if any(not isfinite(v) or v <= 0 for v in (x_spacing_km, y_spacing_km, *distances_km)):
        raise ValueError("Spacing and measurement distances must be positive and finite.")
    land_values = elevation_m[land_mask].astype(np.float64)
    if not land_values.size or not np.all(np.isfinite(land_values)):
        raise ValueError("Quality measurements require finite elevations on nonempty land.")

    measurements: list[DirectionalMeasure] = []
    for axis, spacing in (("x", x_spacing_km), ("y", y_spacing_km)):
        values = elevation_m if axis == "x" else elevation_m.T
        mask = land_mask if axis == "x" else land_mask.T
        # Prefix counts reject any masked sample along a pair's full segment,
        # including endpoints: separate islands must not contribute a pair.
        invalid_prefix = np.pad(np.cumsum(~mask, axis=1, dtype=np.int64), ((0, 0), (1, 0)))
        for distance in distances_km:
            ratio = distance / spacing
            if not isfinite(ratio):
                raise ValueError("Measurement distance is too large for the grid spacing.")
            lag = max(1, int(np.floor(ratio + 0.5)))
            count = 0
            mean_difference: float | None = None
            semivariance: float | None = None
            if lag < values.shape[1]:
                valid = (invalid_prefix[:, lag + 1 :] - invalid_prefix[:, : -(lag + 1)]) == 0
                count = int(np.count_nonzero(valid))
                if count:
                    delta = values[:, lag:][valid].astype(np.float64) - values[:, :-lag][
                        valid
                    ].astype(np.float64)
                    mean_difference = float(np.mean(np.abs(delta)))
                    semivariance = float(np.mean(delta * delta) / 2.0)
            measurements.append(
                DirectionalMeasure(
                    "x" if axis == "x" else "y",
                    distance,
                    lag,
                    lag * spacing,
                    count,
                    mean_difference,
                    semivariance,
                )
            )
    return TerrainQuality(
        QUALITY_ALGORITHM_ID,
        int(land_values.size),
        int(elevation_m.size),
        float(land_values.min()),
        float(land_values.max()),
        float(land_values.mean()),
        float(land_values.std()),
        x_spacing_km,
        y_spacing_km,
        tuple(measurements),
    )
