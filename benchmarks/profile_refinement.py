"""Research-only midpoint refinement; an observed residual is not an error bound."""

from dataclasses import dataclass, replace
from hashlib import sha256
from math import isfinite
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from benchmarks.profile_convergence import (
    ProfileMetrics,
    ProfileTrial,
    ReferenceDifference,
    nested_stations,
    profile_metrics,
    reference_difference,
)
from map_maker.terrain.pipeline.water_sampling import (
    GroundSampler,
    GroundSamplingPlan,
    profile_positions,
    sample_ground_positions,
)

REFINEMENT_METHOD_ID = "midpoint-residual-research@1"


@dataclass(frozen=True, slots=True)
class AdaptiveProfile:
    method_id: str
    status: Literal["indicator_satisfied", "baseline_budget_exceeded", "budget_exceeded",
                    "depth_exhausted", "precision_exhausted"]
    tolerance_m: float
    max_depth: int
    sample_budget: int
    baseline_sample_count: int
    evaluated_sample_count: int
    requested_sample_count: int
    depth: int
    unresolved_interval_count: int
    maximum_leaf_residual_m: float | None = None
    maximum_gap_km: float | None = None
    positions_sha256: str | None = None
    ground_sha256: str | None = None
    metrics: ProfileMetrics | None = None
    reference: ProfileTrial | None = None
    baseline_difference_to_reference: ReferenceDifference | None = None
    difference_to_reference: ReferenceDifference | None = None
    reference_exceeds_tolerance: bool | None = None


def validate_refinement(
    tolerance_m: float, max_depth: int, max_samples: int, reference_budget: int,
) -> None:
    if isinstance(tolerance_m, bool) or not isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("Adaptive tolerance must be finite and positive.")
    if type(max_depth) is not int or not 1 <= max_depth <= 8:
        raise ValueError("Adaptive depth must be an integer from 1 to 8.")
    if type(max_samples) is not int or not 1 <= max_samples <= 65_536:
        raise ValueError("Adaptive sample budget must be an integer from 1 to 65536.")
    if type(reference_budget) is not int or not 1 <= reference_budget <= 262_144:
        raise ValueError("Reference budget must be an integer from 1 to 262144.")


def _positions(
    base: NDArray[np.float64], keys: NDArray[np.int64], factor: int,
) -> NDArray[np.float64]:
    if len(base) == 1:
        return np.repeat(base, len(keys), axis=0)
    segments = np.minimum(keys // factor, len(base) - 2)
    fractions = (keys - segments * factor).astype(np.float64) / factor
    positions = base[segments] + fractions[:, None] * (base[segments + 1] - base[segments])
    original = keys % factor == 0
    positions[original] = base[keys[original] // factor]
    return positions


def refine_profile(
    plan: GroundSamplingPlan, sample_ground: GroundSampler, water_level_m: float, *,
    tolerance_m: float = .01, max_depth: int = 7, max_samples: int = 65_536,
    reference_budget: int = 262_144,
) -> AdaptiveProfile:
    """Bisect complete waves where midpoint ground differs from the endpoint chord.

    Every production station survives. Integer dyadic keys locate new probes
    directly within original intervals, avoiding repeated interpolation drift.
    A complete next wave must fit before evaluation. Exhaustion has no accepted
    metrics or reference comparison; stopping on the indicator never certifies
    clearance. The independent finite reference is evaluated only afterwards.
    """
    validate_refinement(tolerance_m, max_depth, max_samples, reference_budget)
    if not isfinite(water_level_m):
        raise ValueError("The comparison level must be finite.")
    result = AdaptiveProfile(
        REFINEMENT_METHOD_ID, "baseline_budget_exceeded", tolerance_m, max_depth, max_samples,
        plan.requested_sample_count, 0, plan.requested_sample_count, 0,
        max(0, plan.requested_sample_count - 1),
    )
    if plan.status != "sampled" or plan.requested_sample_count > max_samples:
        return result
    base = profile_positions(plan)
    baseline_ground = sample_ground_positions(base, sample_ground)
    factor = 1 << (max_depth + 1)
    keys = np.arange(len(base), dtype=np.int64) * factor
    values = baseline_ground.copy()
    # Separate anchors can round to the same coordinate. Retain both original
    # stations, but a zero-length interval has no interior location to inspect.
    nonzero = np.any(base[:-1] != base[1:], axis=1)
    left, right = keys[:-1][nonzero], keys[1:][nonzero]
    maximum_leaf_residual = 0.
    for depth in range(1, max_depth + 1):
        if not left.size:
            break
        middle = (left + right) // 2
        result = replace(result, depth=depth, evaluated_sample_count=len(keys),
                         requested_sample_count=len(keys) + len(middle),
                         unresolved_interval_count=len(left))
        if result.requested_sample_count > max_samples:
            return replace(result, status="budget_exceeded")
        positions = _positions(base, middle, factor)
        if np.any(np.all(positions == _positions(base, left, factor), axis=1)
                  | np.all(positions == _positions(base, right, factor), axis=1)):
            return replace(result, status="precision_exhausted")
        midpoint_ground = sample_ground_positions(positions, sample_ground)
        endpoints = (values[np.searchsorted(keys, left)].astype(np.float64)
                     + values[np.searchsorted(keys, right)].astype(np.float64)) / 2
        residual = np.abs(midpoint_ground.astype(np.float64) - endpoints)
        needs_refinement = residual > tolerance_m
        maximum_leaf_residual = max(
            maximum_leaf_residual, float(np.max(residual[~needs_refinement], initial=0.)))
        order = np.argsort(np.concatenate((keys, middle)))
        keys = np.concatenate((keys, middle))[order]
        values = np.concatenate((values, midpoint_ground))[order]
        if not np.any(needs_refinement):
            left = np.empty(0, dtype=np.int64)
            break
        if depth == max_depth:
            return replace(result, status="depth_exhausted", evaluated_sample_count=len(keys),
                           unresolved_interval_count=int(np.count_nonzero(needs_refinement)))
        left = np.column_stack((left[needs_refinement], middle[needs_refinement])).ravel()
        right = np.column_stack((middle[needs_refinement], right[needs_refinement])).ravel()

    positions = _positions(base, keys, factor)
    metrics = profile_metrics(positions, values, water_level_m)
    reference_count = 1 + (len(base) - 1) * factor
    reference = ProfileTrial(factor, "aligned", "budget_exceeded", reference_count)
    result = replace(
        result, status="indicator_satisfied", evaluated_sample_count=len(keys),
        requested_sample_count=len(keys), unresolved_interval_count=0,
        maximum_leaf_residual_m=maximum_leaf_residual,
        maximum_gap_km=float(np.max(
            np.linalg.norm(np.diff(positions, axis=0), axis=1), initial=0.)),
        positions_sha256=sha256(positions.tobytes()).hexdigest(),
        ground_sha256=sha256(values.tobytes()).hexdigest(), metrics=metrics, reference=reference,
    )
    if reference_count > reference_budget:
        return result
    reference_positions, _indices = nested_stations(base, factor, False, factor)
    reference_ground = sample_ground_positions(reference_positions, sample_ground)
    if (positions.tobytes() != reference_positions[keys].tobytes()
            or values.tobytes() != reference_ground[keys].tobytes()):
        raise ValueError("Adaptive stations must retain exact shared positions and Float32 ground.")
    reference_metrics = profile_metrics(reference_positions, reference_ground, water_level_m)
    difference = reference_difference(metrics, reference_metrics)
    return replace(
        result,
        reference=replace(reference, status="sampled",
            maximum_gap_km=float(np.max(np.linalg.norm(
                np.diff(reference_positions, axis=0), axis=1), initial=0.)),
            positions_sha256=sha256(reference_positions.tobytes()).hexdigest(),
            ground_sha256=sha256(reference_ground.tobytes()).hexdigest(),
            metrics=reference_metrics),
        baseline_difference_to_reference=reference_difference(
            profile_metrics(base, baseline_ground, water_level_m), reference_metrics),
        difference_to_reference=difference,
        reference_exceeds_tolerance=max(difference.minimum_overestimate_m,
            difference.maximum_underestimate_m, difference.uphill_underestimate_m) > tolerance_m,
    )
