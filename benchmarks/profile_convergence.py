"""Read-only refinement comparisons against a finite, nested sampled reference."""

from dataclasses import dataclass, replace
from hashlib import sha256
from math import isfinite
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.water_sampling import (
    GroundSampler,
    GroundSamplingPlan,
    profile_positions,
    sample_ground_positions,
)

DEFAULT_REFINEMENTS = (1, 2, 4, 8, 16, 32, 64)
HEAD_TOLERANCE_M = 0.01


@dataclass(frozen=True, slots=True)
class ProfileMetrics:
    minimum_ground_m: float
    maximum_ground_m: float
    maximum_uphill_m: float
    minimum_position_km: tuple[float, float]
    maximum_position_km: tuple[float, float]
    rise_from_km: tuple[float, float]
    rise_to_km: tuple[float, float]
    above_level: bool
    below_level: bool
    uphill: bool


@dataclass(frozen=True, slots=True)
class ReferenceDifference:
    minimum_overestimate_m: float
    maximum_underestimate_m: float
    uphill_underestimate_m: float
    missed_above_level: bool
    missed_below_level: bool
    missed_uphill: bool


@dataclass(frozen=True, slots=True)
class ProfileTrial:
    factor: int
    phase: Literal["aligned", "half_shifted"]
    status: Literal["sampled", "budget_exceeded"]
    requested_sample_count: int
    maximum_gap_km: float | None = None
    positions_sha256: str | None = None
    ground_sha256: str | None = None
    metrics: ProfileMetrics | None = None
    difference_to_reference: ReferenceDifference | None = None


@dataclass(frozen=True, slots=True)
class ProfileConvergence:
    status: Literal["sampled", "baseline_budget_exceeded", "reference_budget_exceeded"]
    water_level_m: float
    tolerance_m: float
    sample_budget: int
    baseline_sample_count: int
    reference: ProfileTrial | None
    trials: tuple[ProfileTrial, ...]


def validate_comparison(refinements: tuple[int, ...], max_samples: int) -> None:
    if (
        not refinements
        or refinements[0] != 1
        or tuple(sorted(set(refinements))) != refinements
        or any(
            type(f) is not int or f < 1 or f > 256 or f & (f - 1)
            for f in refinements
        )
    ):
        raise ValueError("Refinements must be increasing powers of two, starting at 1, up to 256.")
    if (
        type(max_samples) is not int
        or not 1 <= max_samples <= 262_144
    ):
        raise ValueError("Comparison sample budget must be an integer from 1 to 262144.")


def nested_stations(
    base: NDArray[np.float64],
    factor: int,
    shifted: bool,
    reference_factor: int,
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    fractions = (
        (np.arange(factor, dtype=np.float64) + 0.5) / factor
        if shifted
        else np.arange(1, factor + 1, dtype=np.float64) / factor
    )
    if shifted:
        fractions = np.append(fractions, 1.0)
    points = (
        base[:-1, None, :] + fractions[None, :, None] * (base[1:] - base[:-1])[:, None, :]
    ).reshape(-1, 2)
    positions = np.concatenate((base[:1], points))
    # Retain every original station exactly, including signed zero and corners.
    positions[fractions.size :: fractions.size] = base[1:]
    indices = np.concatenate(
        (
            np.zeros(1, dtype=np.int64),
            (np.arange(len(base) - 1)[:, None] * reference_factor + fractions * reference_factor)
            .astype(np.int64)
            .ravel(),
        )
    )
    return positions, indices


def profile_metrics(
    positions: NDArray[np.float64],
    ground: NDArray[np.float32],
    level_m: float,
) -> ProfileMetrics:
    values = ground.astype(np.float64)
    rises = values - np.minimum.accumulate(values)
    minimum, maximum, crest = int(np.argmin(values)), int(np.argmax(values)), int(np.argmax(rises))
    low = int(np.argmin(values[: crest + 1]))

    def position(index: int) -> tuple[float, float]:
        return float(positions[index, 0]), float(positions[index, 1])

    return ProfileMetrics(
        float(values[minimum]),
        float(values[maximum]),
        float(rises[crest]),
        position(minimum),
        position(maximum),
        position(low),
        position(crest),
        bool(values[maximum] > level_m + HEAD_TOLERANCE_M),
        bool(values[minimum] < level_m - HEAD_TOLERANCE_M),
        bool(rises[crest] > HEAD_TOLERANCE_M),
    )


def reference_difference(actual: ProfileMetrics, reference: ProfileMetrics) -> ReferenceDifference:
    """Compare extrema and ordered rise on nested finite station sets."""
    return ReferenceDifference(
        actual.minimum_ground_m - reference.minimum_ground_m,
        reference.maximum_ground_m - actual.maximum_ground_m,
        reference.maximum_uphill_m - actual.maximum_uphill_m,
        reference.above_level and not actual.above_level,
        reference.below_level and not actual.below_level,
        reference.uphill and not actual.uphill,
    )


def compare_profile(
    plan: GroundSamplingPlan,
    sample_ground: GroundSampler,
    water_level_m: float,
    *,
    refinements: tuple[int, ...] = DEFAULT_REFINEMENTS,
    max_samples: int = 65_536,
) -> ProfileConvergence:
    """Keep the production stations; densify intervals and shift interior probes.

    The reference splits each baseline interval twice as finely as the largest
    trial factor, so it contains every aligned and shifted station. Differences
    are relative to that finite sample set, never bounds on continuous terrain.
    Raw ground climbs are measured; no lake/pool head or discharge is simulated.
    """
    validate_comparison(refinements, max_samples)
    if not isfinite(water_level_m):
        raise ValueError("The comparison level must be finite.")
    if plan.status != "sampled" or plan.requested_sample_count > max_samples:
        return ProfileConvergence(
            "baseline_budget_exceeded",
            water_level_m,
            HEAD_TOLERANCE_M,
            max_samples,
            plan.requested_sample_count,
            None,
            (),
        )
    base = profile_positions(plan)
    reference_factor = 2 * refinements[-1]

    def evaluate(
        factor: int, shifted: bool
    ) -> tuple[
        ProfileTrial,
        NDArray[np.float64] | None,
        NDArray[np.float32] | None,
        NDArray[np.int64] | None,
    ]:
        count = 1 + (len(base) - 1) * (factor + int(shifted))
        phase = "half_shifted" if shifted else "aligned"
        if count > max_samples:
            return ProfileTrial(factor, phase, "budget_exceeded", count), None, None, None
        positions, indices = nested_stations(base, factor, shifted, reference_factor)
        values = sample_ground_positions(positions, sample_ground)
        trial = ProfileTrial(
            factor,
            phase,
            "sampled",
            count,
            float(np.max(np.linalg.norm(np.diff(positions, axis=0), axis=1), initial=0)),
            sha256(positions.tobytes()).hexdigest(),
            sha256(values.tobytes()).hexdigest(),
            profile_metrics(positions, values, water_level_m),
        )
        return trial, positions, values, indices

    reference, reference_positions, reference_values, _ = evaluate(reference_factor, False)
    trials: list[ProfileTrial] = []
    baseline_values: NDArray[np.float32] | None = None
    for factor in refinements:
        for shifted in (False, True):
            trial, positions, values, indices = evaluate(factor, shifted)
            if values is not None:
                stride = factor + int(shifted)
                if baseline_values is None:
                    baseline_values = values.copy()
                if values[::stride].tobytes() != baseline_values.tobytes():
                    raise ValueError("Shared baseline stations must retain exact Float32 ground.")
            if (
                reference_values is not None
                and reference_positions is not None
                and values is not None
                and positions is not None
                and indices is not None
            ):
                if (
                    positions.tobytes() != reference_positions[indices].tobytes()
                    or values.tobytes() != reference_values[indices].tobytes()
                ):
                    raise ValueError(
                        "Shared reference stations must retain exact positions/ground."
                    )
                a, b = trial.metrics, reference.metrics
                assert a is not None and b is not None
                trial = replace(
                    trial,
                    difference_to_reference=reference_difference(a, b),
                )
            trials.append(trial)
    status = "sampled" if reference.status == "sampled" else "reference_budget_exceeded"
    return ProfileConvergence(
        status,
        water_level_m,
        HEAD_TOLERANCE_M,
        max_samples,
        plan.requested_sample_count,
        reference,
        tuple(trials),
    )
