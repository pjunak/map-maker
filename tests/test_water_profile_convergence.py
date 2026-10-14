"""Convergence evidence must preserve shared stations and expose finite limits."""

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Point

from benchmarks.profile_convergence import compare_profile, validate_comparison
from benchmarks.terrain import ROOT
from benchmarks.water_convergence import CASES, fixture
from map_maker.terrain.pipeline.water_sampling import SamplingFeature, plan_ground_profile


def test_shifted_probes_find_a_barrier_missed_by_the_baseline() -> None:
    plan = plan_ground_profile(((0., 0.), (1., 0.)), .25)

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return (20 * np.maximum(0., 1 - np.abs(x - .375) / .04)).astype(np.float32)

    result = compare_profile(plan, ground, 10., refinements=(1, 2, 4))
    assert result.status == "sampled"
    assert result.reference is not None and result.reference.metrics is not None
    baseline, shifted = result.trials[:2]
    assert baseline.metrics is not None and baseline.difference_to_reference is not None
    assert shifted.metrics is not None and shifted.difference_to_reference is not None
    assert baseline.requested_sample_count == 5 and shifted.requested_sample_count == 9
    assert baseline.metrics.maximum_ground_m == 0
    assert baseline.difference_to_reference.missed_above_level
    assert baseline.difference_to_reference.missed_uphill
    assert shifted.metrics.maximum_ground_m == 20
    assert shifted.metrics.maximum_position_km == (.375, 0.)
    assert shifted.difference_to_reference.maximum_underestimate_m == 0
    assert result == compare_profile(plan, ground, 10., refinements=(1, 2, 4))


def test_nested_probes_preserve_irregular_feature_stations_corners_and_signed_zero() -> None:
    plan = plan_ground_profile(((-0., 0.), (.73, .31), (.73, .31), (.1, 2.)), .23,
                               (SamplingFeature(Point(.31, .1), .09, .03),))

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.copysign(x + y, x).astype(np.float32)

    result = compare_profile(plan, ground, 1., refinements=(1, 2, 8))
    assert result.status == "sampled"
    for trial in result.trials:
        assert trial.status == "sampled" and trial.difference_to_reference is not None
        difference = trial.difference_to_reference
        assert difference.minimum_overestimate_m >= 0
        assert difference.maximum_underestimate_m >= 0
        assert difference.uphill_underestimate_m >= 0


def test_single_station_and_exact_tolerance() -> None:
    plan = plan_ground_profile(((0., 0.),), 1.)
    result = compare_profile(plan, lambda x, y: np.zeros(x.shape, np.float32), -.01)
    for trial in result.trials:
        assert trial.requested_sample_count == 1 and trial.maximum_gap_km == 0
        assert trial.metrics is not None
        assert not trial.metrics.above_level and not trial.metrics.uphill


def test_budget_failure_never_evaluates_a_partial_profile() -> None:
    plan = plan_ground_profile(((0., 0.), (1., 0.)), .25)
    calls: list[int] = []

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        calls.append(x.size)
        return x.astype(np.float32)

    result = compare_profile(plan, ground, .5, max_samples=3)
    assert result.status == "baseline_budget_exceeded" and not calls
    assert not result.trials and result.reference is None
    result = compare_profile(plan, ground, .5, refinements=(1, 2, 4), max_samples=10)
    assert result.status == "reference_budget_exceeded"
    assert result.reference is not None and result.reference.status == "budget_exceeded"
    assert result.reference.requested_sample_count == 33
    assert max(calls) <= 10
    for trial in result.trials:
        assert trial.difference_to_reference is None
        if trial.status == "budget_exceeded":
            assert trial.metrics is trial.ground_sha256 is trial.positions_sha256 is None


@pytest.mark.parametrize("refinements", [(), (2,), (1, 3), (1, 2, 2), (1, 4, 2), (1, 512)])
def test_invalid_refinement_series_is_rejected(refinements: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="powers of two"):
        validate_comparison(refinements, 100)


@pytest.mark.parametrize("budget", [0, -1, 262145, True, 3.5])
def test_invalid_sample_budget_is_rejected(budget: object) -> None:
    with pytest.raises(ValueError, match="sample budget"):
        validate_comparison((1, 2), cast(int, budget))


def test_nonpointwise_or_nonfinite_ground_is_rejected() -> None:
    plan = plan_ground_profile(((0., 0.), (1., 0.)), .25)
    with pytest.raises(ValueError, match="Shared reference"):
        compare_profile(plan, lambda x, y: np.full(x.shape, x.size, np.float32), 1.)
    with pytest.raises(ValueError, match="finite ground"):
        compare_profile(plan, lambda x, y: np.full(x.shape, np.nan, np.float32), 1.)
    with pytest.raises(ValueError, match="level must be finite"):
        compare_profile(plan, lambda x, y: x.astype(np.float32), float("nan"))


def test_fixtures_keep_physical_feature_size_and_explicit_inputs() -> None:
    for case in CASES:
        scene = fixture(case, 17, 4000., "diagonal", 65)
        assert scene.settings.seed == 17 and scene.settings.resolution_px == 65
        assert scene.settings.object_scale_km == 4000.
        assert len(scene.vertices_km) == 2
    with pytest.raises(ValueError, match="Unknown"):
        fixture("unknown", 42, 4000., "horizontal", 64)


def test_fresh_process_report_is_repeatable_and_finds_real_regional_barrier(tmp_path: Path) -> None:
    output = tmp_path / "convergence.json"
    command = [sys.executable, "-m", "benchmarks.water_convergence", "--case", "regional",
               "--direction", "horizontal", "--scale", "4000", "--refinements", "1", "2", "4",
               "--repeats", "2", "--output", str(output)]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["complete"] and data["method"]["fresh_process_per_run"]
    first, second = data["runs"]
    for key in ("input_sha256", "numeric_sha256", "water_review_sha256", "comparison_sha256"):
        assert first[key] == second[key]
    comparison = first["profiles"]["current"]["comparison"]
    assert comparison["reference"]["metrics"]["maximum_ground_m"] == 1050.
    assert comparison["trials"][0]["metrics"]["maximum_ground_m"] == 1050.
    control = first["profiles"]["without_region_guidance"]["comparison"]
    assert control["trials"][0]["metrics"]["maximum_ground_m"] == 100.
    assert control["trials"][0]["difference_to_reference"]["missed_above_level"]
    original = output.read_bytes()
    failed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert failed.returncode != 0 and output.read_bytes() == original
