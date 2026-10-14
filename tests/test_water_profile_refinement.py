"""Residual convergence must expose hidden extrema and explicit exhaustion."""

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Point

from benchmarks.profile_refinement import refine_profile, validate_refinement
from benchmarks.terrain import ROOT
from map_maker.terrain.pipeline.water_sampling import (
    GroundSamplingPlan,
    SamplingFeature,
    plan_ground_profile,
    profile_positions,
)


def test_midpoint_residual_can_be_zero_while_a_peak_is_missed() -> None:
    plan = plan_ground_profile(((0., 0.), (1., 0.)), .25)
    def hidden(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return (20 * np.maximum(0., 1 - np.abs(x - .0625) / .015625)).astype(np.float32)
    result = refine_profile(plan, hidden, 10.)
    assert result.status == "indicator_satisfied" and result.maximum_leaf_residual_m == 0.
    assert result.evaluated_sample_count == 9
    assert result.metrics is not None and result.metrics.maximum_ground_m == 0.
    assert result.reference is not None and result.reference.metrics is not None
    assert result.reference.metrics.maximum_ground_m == 20.
    assert result.difference_to_reference is not None
    assert result.difference_to_reference.missed_above_level
    assert result.reference_exceeds_tolerance is True


def test_refinement_reduces_a_resolved_curved_peak_and_preserves_ground() -> None:
    plan = plan_ground_profile(((0., 0.), (1., 0.)), .25)
    def curved(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return (10 - 20 * (x - .371) ** 2).astype(np.float32)
    loose = refine_profile(plan, curved, 9.99, tolerance_m=.1)
    tight = refine_profile(plan, curved, 9.99, tolerance_m=.001)
    assert tight.status == loose.status == "indicator_satisfied"
    assert tight.maximum_leaf_residual_m is not None and tight.maximum_leaf_residual_m <= .001
    assert tight.evaluated_sample_count > loose.evaluated_sample_count > plan.requested_sample_count
    assert tight.difference_to_reference is not None
    assert tight.baseline_difference_to_reference is not None
    assert tight.difference_to_reference.maximum_underestimate_m < .001
    assert tight.baseline_difference_to_reference.maximum_underestimate_m > .1
    assert refine_profile(plan, curved, 9.99, tolerance_m=.001) == tight


def test_irregular_stations_corners_retraces_and_signed_zero_share_exact_reference() -> None:
    plan = plan_ground_profile(((-0., 0.), (.37, .2), (.91, -.13), (.37, .2)), .3,
                               (SamplingFeature(Point(.271, .12), .005, .005),))
    original = profile_positions(plan).tobytes()
    def linear(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return (3*x + 2*y).astype(np.float32)
    result = refine_profile(plan, linear, 5.)
    assert result.status == "indicator_satisfied"
    assert result.reference is not None and result.reference.status == "sampled"
    assert result.reference_exceeds_tolerance is False
    assert profile_positions(plan).tobytes() == original
    assert refine_profile(plan, linear, 5.) == result


@pytest.mark.parametrize("budget,expected_evaluations", [(4, []), (8, [5]), (10, [5, 4])])
def test_complete_wave_budget_failure_has_no_accepted_prefix(
    budget: int, expected_evaluations: list[int],
) -> None:
    calls: list[int] = []
    def curved(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        calls.append(len(x))
        return (x*x).astype(np.float32)
    result = refine_profile(plan_ground_profile(((0., 0.), (1., 0.)), .25), curved, 1.,
                            tolerance_m=1e-6, max_samples=budget)
    assert result.status == ("baseline_budget_exceeded" if budget == 4 else "budget_exceeded")
    assert calls == expected_evaluations
    assert result.evaluated_sample_count == sum(calls)
    assert result.requested_sample_count > budget
    assert result.metrics is result.reference is result.positions_sha256 is None


def test_excessive_production_plan_never_evaluates_a_prefix() -> None:
    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("An excessive production plan must not be evaluated.")
    plan = plan_ground_profile(((0., 0.), (100_000., 0.)), .25)
    result = refine_profile(plan, unexpected, 10.)
    assert result.status == "baseline_budget_exceeded" and result.evaluated_sample_count == 0


def test_depth_exhaustion_is_not_indicator_satisfaction() -> None:
    def curved(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return (x*x).astype(np.float32)
    result = refine_profile(plan_ground_profile(((0., 0.), (1., 0.)), .25), curved, 1.,
                            tolerance_m=1e-6, max_depth=1)
    assert result.status == "depth_exhausted" and result.unresolved_interval_count == 4
    assert result.metrics is result.reference is result.maximum_leaf_residual_m is None


def test_reference_budget_failure_leaves_difference_unknown() -> None:
    calls: list[int] = []
    def flat(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        calls.append(len(x))
        return np.zeros_like(x, dtype=np.float32)
    result = refine_profile(plan_ground_profile(((0., 0.), (1., 0.)), .25), flat, 1.,
                            reference_budget=100)
    assert result.status == "indicator_satisfied" and calls == [5, 4]
    assert result.reference is not None and result.reference.status == "budget_exceeded"
    assert result.difference_to_reference is result.reference_exceeds_tolerance is None


def test_coincident_anchors_survive_without_refining_a_zero_length_interval() -> None:
    close = float(np.nextafter(.5, 1.))
    plan = GroundSamplingPlan(
        ((100., 100.), (101., 101.)), 1., 2, 4, None,
        (((0., .5, 1), (.5, close, 1), (close, 1., 1)),), "sampled",
    )
    original = profile_positions(plan)
    assert np.array_equal(original[1], original[2])
    result = refine_profile(plan, lambda x, y: x.astype(np.float32), 200.)
    assert result.status == "indicator_satisfied"
    assert result.baseline_sample_count == 4 and result.evaluated_sample_count == 6
    assert result.reference is not None and result.reference.status == "sampled"
    assert result.reference_exceeds_tolerance is False
    assert profile_positions(plan).tobytes() == original.tobytes()


def test_unrepresentable_midpoint_does_not_loop_or_report_convergence() -> None:
    def flat(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.zeros_like(x, dtype=np.float32)
    start = 1e16
    end = float(np.nextafter(start, np.inf))
    result = refine_profile(plan_ground_profile(((start, 0.), (end, 0.)), 1.), flat, 1.)
    assert result.status == "precision_exhausted" and result.metrics is None


def test_zero_length_profile_keeps_its_signed_zero_station() -> None:
    def flat(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.zeros_like(x, dtype=np.float32)
    plan = plan_ground_profile(((-0., 0.), (-0., 0.)), .25)
    result = refine_profile(plan, flat, 1.)
    assert result.status == "indicator_satisfied" and result.evaluated_sample_count == 1
    assert result.positions_sha256 == sha256(profile_positions(plan).tobytes()).hexdigest()


@pytest.mark.parametrize("tolerance,depth,budget,reference", [
    (0., 7, 65_536, 262_144), (float("nan"), 7, 65_536, 262_144),
    (True, 7, 65_536, 262_144), (.01, 0, 65_536, 262_144),
    (.01, 9, 65_536, 262_144), (.01, 7, 65_537, 262_144), (.01, 7, 65_536, 0),
])
def test_invalid_refinement_controls_fail_before_work(
    tolerance: float, depth: int, budget: int, reference: int,
) -> None:
    with pytest.raises(ValueError):
        validate_refinement(tolerance, depth, budget, reference)


def test_nonpointwise_or_nonfinite_ground_is_rejected() -> None:
    plan = plan_ground_profile(((0., 0.), (1., 0.)), .25)
    with pytest.raises(ValueError, match="exact shared positions and Float32 ground"):
        refine_profile(plan, lambda x, y: np.full(x.shape, x.size, np.float32), 1.,
                       tolerance_m=10.)
    with pytest.raises(ValueError, match="finite ground"):
        refine_profile(plan, lambda x, y: np.full(x.shape, np.nan, np.float32), 1.)
    with pytest.raises(ValueError, match="level must be finite"):
        refine_profile(plan, lambda x, y: x.astype(np.float32), float("nan"))


@pytest.mark.parametrize("options", [
    ("--adaptive-tolerance", "nan"), ("--adaptive-max-depth", "9"),
    ("--adaptive-max-samples", "65537"),
])
def test_invalid_cli_controls_do_not_reserve_an_output(
    tmp_path: Path, options: tuple[str, str],
) -> None:
    output = tmp_path / "invalid.json"
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.water_convergence", *options,
         "--output", str(output)], cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0 and "Adaptive" in result.stderr
    assert not output.exists()


def test_fresh_process_runner_records_and_repeats_adaptive_evidence(tmp_path: Path) -> None:
    output = tmp_path / "adaptive.json"
    command = [sys.executable, "-m", "benchmarks.water_convergence", "--case", "overlap",
               "--scale", "400", "--direction", "oblique", "--refinements", "1", "2",
               "--adaptive-tolerance", ".1", ".01", "--adaptive-max-depth", "5",
               "--repeats", "2", "--output", str(output)]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["complete"] and data["schema_version"] == 2
    assert data["method"]["adaptive"]["continuous_error_bound"] is False
    first, second = data["runs"]
    for key in ("input_sha256", "numeric_sha256", "water_review_sha256", "comparison_sha256"):
        assert first[key] == second[key]
    adaptive = first["profiles"]["current"]["adaptive"]
    assert [a["tolerance_m"] for a in adaptive] == [.1, .01]
    assert all(a["max_depth"] == 5 for a in adaptive)
    original = output.read_bytes()
    again = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert again.returncode != 0 and output.read_bytes() == original
