"""Research-only complete-budget refinement of rounded noise-path bounds."""

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from benchmarks.noise_intervals import MAX_CELLS, Interval, NoiseParameters, validate_bound_controls
from benchmarks.noise_profiles import (
    MAX_SLABS,
    NoisePath,
    ProfileGeometry,
    enclose_noise_profile,
    ordered_rise_upper_bound,
)
from map_maker.terrain.pipeline.noise import fractal_value_noise

REFINEMENT_METHOD_ID = "bounded-noise-profile-refinement@1"
MAX_SAMPLES = 65_536
MAX_DEPTH = 16

type RefinementStrategy = Literal["adaptive", "uniform"]
type RefinementStatus = Literal[
    "tolerance_met",
    "cell_budget_exceeded",
    "slab_budget_exceeded",
    "sample_budget_exceeded",
    "depth_exhausted",
    "precision_exhausted",
    "coordinate_range_exceeded",
]


@dataclass(frozen=True, slots=True)
class RefinementControls:
    tolerance_m: float
    geometry: ProfileGeometry = "hybrid"
    strategy: RefinementStrategy = "adaptive"
    max_cells: int = MAX_CELLS
    max_slabs: int = MAX_SLABS
    max_samples: int = MAX_SAMPLES
    max_depth: int = MAX_DEPTH

    def __post_init__(self) -> None:
        if type(self.tolerance_m) not in (int, float) or not isfinite(self.tolerance_m):
            raise ValueError("Noise tolerance must be finite and positive.")
        if self.tolerance_m <= 0:
            raise ValueError("Noise tolerance must be finite and positive.")
        for name, value, low, high in (
            ("cells", self.max_cells, 1, MAX_CELLS),
            ("slabs", self.max_slabs, 0, MAX_SLABS),
            ("samples", self.max_samples, 2, MAX_SAMPLES),
            ("depth", self.max_depth, 0, MAX_DEPTH),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Noise {name} limit must be an integer from {low} to {high}.")
        if self.geometry not in ("slabs", "hybrid") or self.strategy not in ("adaptive", "uniform"):
            raise ValueError("Unknown noise refinement policy.")


@dataclass(frozen=True, slots=True)
class RangeMetrics:
    maximum_local_gap_m: float
    maximum_extremum_gap_m: float
    maximum_interval_width_m: float
    uphill_gap_m: float
    uphill_upper_bound_m: float
    sampled_uphill_lower_bound_m: float


@dataclass(frozen=True, slots=True)
class RefinedProfile:
    fractions: NDArray[np.float64]
    samples_m: NDArray[np.float32]
    field_m: Interval
    depths: NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class RefinementWave:
    interval_count: int
    maximum_depth: int
    evaluated_cell_count: int
    allocated_slab_count: int
    evaluated_sample_count: int
    rectangle_plan_count: int
    clipped_plan_count: int
    metrics: RangeMetrics


@dataclass(frozen=True, slots=True)
class RefinementResult:
    status: RefinementStatus
    evaluated_cell_count: int
    allocated_slab_count: int
    evaluated_sample_count: int
    required_cell_count: int | None
    required_slab_count: int | None
    required_sample_count: int
    waves: tuple[RefinementWave, ...]
    # Only tolerance_met publishes an accepted complete profile.
    profile: RefinedProfile | None = None


def path_positions(path: NoisePath, fractions: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.asarray(path.start_km) + fractions[:, None] * np.asarray(path.delta_km)


def sample_path(
    path: NoisePath,
    fractions: NDArray[np.float64],
    parameters: NoiseParameters,
    *,
    amplitude_m: float,
    offset_m: float,
) -> NDArray[np.float32]:
    points = path_positions(path, fractions)
    noise = fractal_value_noise(points[:, 0], points[:, 1], **asdict(parameters))
    return (offset_m + amplitude_m * noise).astype(np.float32)


def profile_uncertainty(
    profile: RefinedProfile, tolerance_m: float
) -> tuple[RangeMetrics, NDArray[np.bool_]]:
    """Bound local endpoint-envelope and global ordered-rise uncertainty.

    Prefix lows identify possible later highs; suffix highs also mark their
    earlier low intervals, so refinement does not chase just one side of a rise.
    """
    low, high = profile.field_m.low, profile.field_m.high
    values = profile.samples_m.astype(np.float64)
    endpoint_low, endpoint_high = (
        np.minimum(values[:-1], values[1:]),
        np.maximum(values[:-1], values[1:]),
    )
    local = np.maximum(
        np.nextafter(endpoint_low - low, np.inf), np.nextafter(high - endpoint_high, np.inf)
    )
    sampled_rise = max(
        0.0, float(np.max(np.nextafter(values - np.minimum.accumulate(values), -np.inf)))
    )
    rise_upper = ordered_rise_upper_bound(profile.field_m)
    uphill_gap = float(np.nextafter(rise_upper - sampled_rise, np.inf))
    global_gap = max(
        0.0,
        float(np.nextafter(np.max(high) - np.max(values), np.inf)),
        float(np.nextafter(np.min(values) - np.min(low), np.inf)),
    )
    metrics = RangeMetrics(
        max(0.0, float(np.max(local))),
        global_gap,
        float(np.max(np.nextafter(high - low, np.inf))),
        uphill_gap,
        rise_upper,
        sampled_rise,
    )
    possible_high = np.nextafter(high - np.minimum.accumulate(low), np.inf)
    possible_low = np.nextafter(np.maximum.accumulate(high[::-1])[::-1] - low, np.inf)
    selected = local > tolerance_m
    # Use the same rounded global decision before marking its contributors.
    if uphill_gap > tolerance_m:
        selected |= np.nextafter(possible_high - sampled_rise, np.inf) > tolerance_m
        selected |= np.nextafter(possible_low - sampled_rise, np.inf) > tolerance_m
    return metrics, selected


def refine_noise_profile(
    path: NoisePath,
    parameters: NoiseParameters,
    controls: RefinementControls,
    *,
    amplitude_m: float = 1000.0,
    offset_m: float = 2000.0,
) -> RefinementResult:
    """Refine whole pending waves with cumulative budgets and no accepted prefix.

    Original global dyadic parameters are retained; no subpath is reconstructed
    from rounded anchors. Reference probes never participate in the decisions.
    """
    validate_bound_controls(amplitude_m, offset_m, controls.max_cells)
    profile: RefinedProfile | None = None
    pending = np.asarray(((0.0, 1.0),))
    new_fractions = np.asarray((0.0, 1.0))
    cells = slabs = samples = rectangles = clipped = 0
    waves: list[RefinementWave] = []
    required_cells: int | None = None
    required_slabs: int | None = None
    required_samples = 2

    def finish(status: RefinementStatus) -> RefinementResult:
        return RefinementResult(
            status,
            cells,
            slabs,
            samples,
            required_cells,
            required_slabs,
            required_samples,
            tuple(waves),
            profile if status == "tolerance_met" else None,
        )

    while True:
        required_samples = samples + len(new_fractions)
        required_cells = required_slabs = None
        if required_samples > controls.max_samples:
            return finish("sample_budget_exceeded")
        enclosure = enclose_noise_profile(
            path,
            pending,
            parameters,
            amplitude_m=amplitude_m,
            offset_m=offset_m,
            max_cells=controls.max_cells - cells,
            max_slabs=controls.max_slabs - slabs,
            geometry=controls.geometry,
        )
        if enclosure.requested_slab_count is not None:
            required_slabs = slabs + enclosure.requested_slab_count
        if enclosure.requested_cell_count is not None:
            required_cells = cells + enclosure.requested_cell_count
            # A complete cell count means all selected strip arrays were prepared.
            slabs += enclosure.requested_slab_count or 0
        if enclosure.status != "bounded":
            return finish(enclosure.status)
        assert enclosure.field_m is not None
        cells += enclosure.evaluated_cell_count
        rectangles += enclosure.rectangle_plan_count or 0
        clipped += enclosure.clipped_plan_count or 0
        new_values = sample_path(
            path, new_fractions, parameters, amplitude_m=amplitude_m, offset_m=offset_m
        )
        samples += len(new_values)
        if profile is None:
            profile = RefinedProfile(
                new_fractions, new_values, enclosure.field_m, np.zeros(1, dtype=np.int64)
            )
        else:
            fractions = np.sort(np.concatenate((profile.fractions, new_fractions)))
            values = np.empty(len(fractions), dtype=np.float32)
            values[np.searchsorted(fractions, profile.fractions)] = profile.samples_m
            values[np.searchsorted(fractions, new_fractions)] = new_values
            owners = np.searchsorted(profile.fractions, fractions[:-1], side="right") - 1
            low, high = profile.field_m.low[owners].copy(), profile.field_m.high[owners].copy()
            depths = profile.depths[owners].copy()
            replaced = np.searchsorted(fractions, pending[:, 0])
            low[replaced], high[replaced] = enclosure.field_m.low, enclosure.field_m.high
            depths[replaced] += 1
            profile = RefinedProfile(fractions, values, Interval(low, high), depths)
        metrics, selected = profile_uncertainty(profile, controls.tolerance_m)
        waves.append(
            RefinementWave(
                len(profile.depths),
                int(np.max(profile.depths)),
                cells,
                slabs,
                samples,
                rectangles,
                clipped,
                metrics,
            )
        )
        if (
            metrics.maximum_local_gap_m <= controls.tolerance_m
            and metrics.uphill_gap_m <= controls.tolerance_m
        ):
            return finish("tolerance_met")
        if controls.strategy == "uniform":
            selected = np.ones(len(profile.depths), dtype=np.bool_)
        assert np.any(selected), "Unresolved uncertainty must select a contributing interval."
        required_cells = required_slabs = None
        required_samples = samples + int(np.count_nonzero(selected))
        if np.any(profile.depths[selected] >= controls.max_depth):
            return finish("depth_exhausted")
        low_t, high_t = profile.fractions[:-1][selected], profile.fractions[1:][selected]
        new_fractions = low_t + (high_t - low_t) * 0.5
        if np.any((new_fractions <= low_t) | (new_fractions >= high_t)) or np.any(
            np.all(path_positions(path, low_t) == path_positions(path, high_t), axis=1)
        ):
            return finish("precision_exhausted")
        pending = np.empty((2 * len(new_fractions), 2), dtype=np.float64)
        pending[::2, 0], pending[::2, 1] = low_t, new_fractions
        pending[1::2, 0], pending[1::2, 1] = new_fractions, high_t
