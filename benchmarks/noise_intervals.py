"""Research-only enclosures of the existing value-noise component.

Natural and polynomial-aware intervals follow the runtime expression, including rounding.
These are not bounds for the complete terrain evaluator or water clearance.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np
from numpy.typing import NDArray

# Inspect the existing lattice primitive without promoting a research API.
from map_maker.terrain.pipeline.noise import (
    _lattice_values,  # pyright: ignore[reportPrivateUsage]
    noise_band_amplitudes,
)

METHOD_ID = "rounded-cell-value-noise@2"
type BoundMethod = Literal["natural", "monotone_cell"]
METHODS: tuple[BoundMethod, ...] = ("natural", "monotone_cell")
# Absolute bounds derived for the current seven-op fade and nine-op lerp tree.
FADE_ROUNDING_ERROR = 2.0**-47  # 64u; the operation ledger requires at most 56u.
LERP_ROUNDING_ERROR = 2.0**-46  # 128u; the operation ledger requires at most 108u.
MAX_CELLS = 262_144
MAX_BOXES = 65_536
# Keep floor indices and their next integer exactly representable as binary64.
MAX_SCALED_COORDINATE = float(1 << 50)


@dataclass(frozen=True, slots=True)
class NoiseParameters:
    seed: int = 42
    largest_feature_km: float = 2.0
    detail_levels: int = 6
    roughness: float = 0.55

    def __post_init__(self) -> None:
        if type(self.seed) is not int or not 0 <= self.seed < 1 << 64:
            raise ValueError("Noise seed must be an unsigned 64-bit integer.")
        if (
            type(self.largest_feature_km) not in (int, float)
            or not isfinite(self.largest_feature_km)
            or self.largest_feature_km <= 0
        ):
            raise ValueError("Noise feature size must be finite and positive.")
        if type(self.detail_levels) is not int or not 1 <= self.detail_levels <= 12:
            raise ValueError("Noise detail levels must be an integer from 1 to 12.")
        if type(self.roughness) not in (int, float) or not 0 < self.roughness < 1:
            raise ValueError("Noise roughness must be between zero and one.")
        if self.largest_feature_km / float(1 << (self.detail_levels - 1)) == 0.0:
            raise ValueError("Noise octave spacing must remain representable.")


@dataclass(frozen=True, slots=True)
class Interval:
    low: NDArray[np.float64]
    high: NDArray[np.float64]

    @classmethod
    def point(cls, value: NDArray[np.float64] | float) -> Interval:
        array = np.asarray(value, dtype=np.float64)
        return cls(array, array)

    def add(self, other: Interval) -> Interval:
        return Interval(
            np.nextafter(self.low + other.low, -np.inf),
            np.nextafter(self.high + other.high, np.inf),
        )

    def subtract(self, other: Interval) -> Interval:
        return Interval(
            np.nextafter(self.low - other.high, -np.inf),
            np.nextafter(self.high - other.low, np.inf),
        )

    def multiply(self, other: Interval) -> Interval:
        products = np.broadcast_arrays(
            self.low * other.low,
            self.low * other.high,
            self.high * other.low,
            self.high * other.high,
        )
        return Interval(
            np.nextafter(np.minimum.reduce(products), -np.inf),
            np.nextafter(np.maximum.reduce(products), np.inf),
        )

    def divide_positive(self, divisor: float) -> Interval:
        if not isfinite(divisor) or divisor <= 0:
            raise ValueError("Interval divisor must be finite and positive.")
        return Interval(
            np.nextafter(self.low / divisor, -np.inf), np.nextafter(self.high / divisor, np.inf)
        )

    def float32(self) -> Interval:
        # Include conversion at the final field boundary, not just binary64 error.
        return Interval(
            np.nextafter(self.low.astype(np.float32), np.float32(-np.inf)).astype(np.float64),
            np.nextafter(self.high.astype(np.float32), np.float32(np.inf)).astype(np.float64),
        )


def fade_interval(value: Interval) -> Interval:
    """Enclose the seven operations of noise._fade in their original order.

    Repeated occurrences of t lose correlation. This deliberately measures the
    natural extension before selecting a tighter polynomial enclosure.
    """
    inside = value.multiply(Interval.point(6.0)).subtract(Interval.point(15.0))
    inside = value.multiply(inside).add(Interval.point(10.0))
    return value.multiply(value).multiply(value).multiply(inside)


def monotone_fade_interval(value: Interval) -> Interval:
    """Use f'(t)=30*t**2*(1-t)**2 >= 0 on [0,1], with runtime roundoff.

    Endpoint natural extensions enclose the real polynomial at those points.
    64u covers the runtime expression's absolute error anywhere in [0,1];
    see the operation-by-operation derivation in the dated research report.
    """
    low = fade_interval(Interval.point(value.low)).low
    high = fade_interval(Interval.point(value.high)).high
    return Interval(
        np.nextafter(low - FADE_ROUNDING_ERROR, -np.inf),
        np.nextafter(high + FADE_ROUNDING_ERROR, np.inf),
    )


def _bilinear(
    tx: Interval, ty: Interval, v00: Interval, v10: Interval, v01: Interval, v11: Interval
) -> Interval:
    top = v00.add(tx.multiply(v10.subtract(v00)))
    bottom = v01.add(tx.multiply(v11.subtract(v01)))
    return top.add(ty.multiply(bottom.subtract(top)))


def cell_interval(
    tx: Interval, ty: Interval, v00: Interval, v10: Interval, v01: Interval, v11: Interval
) -> Interval:
    """Bilinear extrema occur at rectangle corners, plus runtime roundoff.

    Only use with point lattice values in [-1,1] and faded fractions of [0,1].
    These domain conditions bound the lerp tree's absolute error by 128u.
    """
    corners = _bilinear(
        Interval.point(np.stack((tx.low, tx.low, tx.high, tx.high))),
        Interval.point(np.stack((ty.low, ty.high, ty.low, ty.high))),
        v00,
        v10,
        v01,
        v11,
    )
    return Interval(
        np.nextafter(np.min(corners.low, axis=0) - LERP_ROUNDING_ERROR, -np.inf),
        np.nextafter(np.max(corners.high, axis=0) + LERP_ROUNDING_ERROR, np.inf),
    )


@dataclass(frozen=True, slots=True)
class NoiseEnclosure:
    status: Literal[
        "bounded", "cell_budget_exceeded", "coordinate_range_exceeded", "slab_budget_exceeded"
    ]
    requested_cell_count: int | None
    evaluated_cell_count: int
    noise: Interval | None = None
    field_m: Interval | None = None
    requested_slab_count: int | None = None
    rectangle_plan_count: int | None = None
    clipped_plan_count: int | None = None


@dataclass(frozen=True, slots=True)
class OctavePlan:
    x: Interval
    y: Interval
    first: NDArray[np.int64]
    last: NDArray[np.int64]
    cell_count: int
    owners: NDArray[np.int64]


def _octave_interval(
    plan: OctavePlan, seed: int, octave: int, box_count: int, method: BoundMethod
) -> Interval:
    cells = np.asarray(
        [
            (owner, column, row)
            for owner, (first, last) in enumerate(zip(plan.first, plan.last, strict=True))
            for row in range(int(first[1]), int(last[1]) + 1)
            for column in range(int(first[0]), int(last[0]) + 1)
        ],
        dtype=np.int64,
    )
    owners, columns, rows = cells.T

    def fraction(axis: Interval, indices: NDArray[np.int64]) -> Interval:
        origins = indices.astype(np.float64)
        local = Interval(
            np.maximum(axis.low[owners], origins), np.minimum(axis.high[owners], origins + 1.0)
        ).subtract(Interval.point(origins))
        # The runtime subtracts floor(q); its rounded fraction is in [0, 1].
        return Interval(np.maximum(0.0, local.low), np.minimum(1.0, local.high))

    fade = fade_interval if method == "natural" else monotone_fade_interval
    tx = fade(fraction(plan.x, columns))
    ty = fade(fraction(plan.y, rows))
    v00 = Interval.point(_lattice_values(columns, rows, seed=seed, octave=octave))
    v10 = Interval.point(_lattice_values(columns + 1, rows, seed=seed, octave=octave))
    v01 = Interval.point(_lattice_values(columns, rows + 1, seed=seed, octave=octave))
    v11 = Interval.point(_lattice_values(columns + 1, rows + 1, seed=seed, octave=octave))
    interpolate = _bilinear if method == "natural" else cell_interval
    values = interpolate(tx, ty, v00, v10, v01, v11)
    low, high = np.full(box_count, np.inf), np.full(box_count, -np.inf)
    np.minimum.at(low, plan.owners[owners], values.low)
    np.maximum.at(high, plan.owners[owners], values.high)
    return Interval(low, high)


def validate_bound_controls(amplitude_m: float, offset_m: float, max_cells: int) -> None:
    if type(max_cells) is not int or not 1 <= max_cells <= MAX_CELLS:
        raise ValueError("Noise cell budget must be an integer from 1 to 262144.")
    if (
        type(amplitude_m) not in (int, float)
        or type(offset_m) not in (int, float)
        or not isfinite(amplitude_m)
        or not isfinite(offset_m)
        or abs(amplitude_m) > 1e20
        or abs(offset_m) > 1e20
    ):
        raise ValueError("Noise field amplitude and offset must be finite and at most 1e20 metres.")


def enclose_noise(
    boxes_km: NDArray[np.float64],
    parameters: NoiseParameters,
    *,
    amplitude_m: float = 1000.0,
    offset_m: float = 2000.0,
    max_cells: int = MAX_CELLS,
    method: BoundMethod = "monotone_cell",
) -> NoiseEnclosure:
    """Bound noise and Float32(offset + amplitude * noise) over closed boxes.

    Boxes have columns xmin, ymin, xmax, ymax and contain supplied binary64
    coordinates. Every octave/cell is counted before any lattice evaluation.
    Unsupported coordinates or a full-request budget failure return no prefix.
    This experiment assumes ordinary IEEE binary64 operations with gradual
    underflow; it does not support fast-math or a different noise implementation.
    """
    if method not in METHODS:
        raise ValueError("Unknown noise bound method.")
    boxes = np.asarray(boxes_km, dtype=np.float64)
    if (
        boxes.ndim != 2
        or boxes.shape[1] != 4
        or not 1 <= len(boxes) <= MAX_BOXES
        or not np.all(np.isfinite(boxes))
        or np.any(boxes[:, :2] > boxes[:, 2:])
    ):
        raise ValueError("Noise boxes must be 1-65536 finite ordered xmin/ymin/xmax/ymax rows.")
    validate_bound_controls(amplitude_m, offset_m, max_cells)

    plans: list[OctavePlan] = []
    with np.errstate(over="ignore", under="ignore"):
        for octave in range(parameters.detail_levels):
            spacing = parameters.largest_feature_km / float(1 << octave)
            x = Interval(boxes[:, 0], boxes[:, 2]).divide_positive(spacing)
            y = Interval(boxes[:, 1], boxes[:, 3]).divide_positive(spacing)
            extrema = np.column_stack((x.low, y.low, x.high, y.high))
            if not np.all(np.isfinite(extrema)) or np.any(np.abs(extrema) > MAX_SCALED_COORDINATE):
                return NoiseEnclosure("coordinate_range_exceeded", None, 0)
            first = np.floor(extrema[:, :2]).astype(np.int64)
            last = np.floor(extrema[:, 2:]).astype(np.int64)
            # Python integers prevent overflow for a large, rejected rectangle.
            count = sum(
                (int(b[0]) - int(a[0]) + 1) * (int(b[1]) - int(a[1]) + 1)
                for a, b in zip(first, last, strict=True)
            )
            plans.append(
                OctavePlan(x, y, first, last, count, np.arange(len(boxes), dtype=np.int64))
            )
    return enclose_plans(
        plans,
        parameters,
        len(boxes),
        amplitude_m=amplitude_m,
        offset_m=offset_m,
        max_cells=max_cells,
        method=method,
    )


def enclose_plans(
    plans: list[OctavePlan],
    parameters: NoiseParameters,
    interval_count: int,
    *,
    amplitude_m: float,
    offset_m: float,
    max_cells: int,
    method: BoundMethod = "monotone_cell",
) -> NoiseEnclosure:
    """Evaluate complete prepared cell plans; both geometry policies share this kernel."""
    requested = sum(plan.cell_count for plan in plans)
    if requested > max_cells:
        return NoiseEnclosure("cell_budget_exceeded", requested, 0)

    result = Interval.point(np.zeros(interval_count, dtype=np.float64))
    amplitudes = noise_band_amplitudes(parameters.detail_levels, parameters.roughness)
    for octave, plan in enumerate(plans):
        value = _octave_interval(plan, parameters.seed, octave, interval_count, method)
        # Bound the runtime operations using its exact rounded band coefficients.
        result = result.add(Interval.point(amplitudes[octave]).multiply(value))
    field = Interval.point(offset_m).add(Interval.point(amplitude_m).multiply(result)).float32()
    return NoiseEnclosure("bounded", requested, requested, result, field)
