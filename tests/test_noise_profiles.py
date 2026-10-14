"""Slab bounds must cover rounded paths, including grazing and reversed motion."""

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from numpy.typing import NDArray

from benchmarks.noise_intervals import Interval, NoiseParameters, enclose_noise
from benchmarks.noise_profiles import (
    NoisePath,
    enclose_noise_profile,
    ordered_rise_upper_bound,
    slab_fractions,
)
from benchmarks.terrain import ROOT
from map_maker.terrain.pipeline.noise import fractal_value_noise

PATHS = (
    NoisePath((-0.542, 0.386), (4.0, 4.0)),
    NoisePath((3.458, 4.386), (-4.0, -4.0)),
    NoisePath((-2.0, 1.0), (4.0, 0.0)),
    NoisePath((-1.0, -2.0), (0.0, 4.0)),
    NoisePath((1.0, 2.0), (-0.0, -4.0)),
    NoisePath((0.03, -0.17), (1.4, -0.7)),
    NoisePath((-0.0, 0.0), (0.0, 0.0)),
    NoisePath((2.0, -2.0), (0.0, -0.0)),
    NoisePath((1.0, 1.0), (2.0**-52, -(2.0**-53))),
    NoisePath((2.0**30, -(2.0**30)), (0.001, -0.01)),
    NoisePath((0.0, 0.0), (float(np.nextafter(0.0, 1.0)), -float(np.nextafter(0.0, 1.0)))),
)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("detail", [1, 6, 12])
def test_slab_bounds_include_dense_and_random_rounded_path_positions(path: NoisePath, detail: int):
    parameters = NoiseParameters(seed=20260914, detail_levels=detail, roughness=0.9)
    spans = np.asarray(((0.0, 0.13), (0.13, 0.50001), (0.50001, 0.7), (0.7, 1.0)))
    original = spans.tobytes()
    result = enclose_noise_profile(path, spans, parameters)
    assert result.status == "bounded" and result.noise is not None and result.field_m is not None
    rng = np.random.default_rng(191)
    for i, (low, high) in enumerate(spans):
        fractions = np.concatenate(
            (np.linspace(float(low), float(high), 4097), rng.uniform(low, high, 400))
        )
        points = np.asarray(path.start_km) + fractions[:, None] * np.asarray(path.delta_km)
        values = fractal_value_noise(points[:, 0], points[:, 1], **asdict(parameters))
        field = (2000.0 + 1000.0 * values).astype(np.float32)
        assert np.all((result.noise.low[i] <= values) & (values <= result.noise.high[i]))
        assert np.all((result.field_m.low[i] <= field) & (field <= result.field_m.high[i]))
    assert spans.tobytes() == original


@pytest.mark.parametrize(
    "start,delta,spacing",
    [
        (0.0, 4.0, 0.125),
        (4.0, -4.0, 0.125),
        (-1e6, 1e6, 0.125),
        (1e6, -1e6, 0.125),
        (2.0**40, 0.001, 0.01),
        (-(2.0**40), -0.001, 0.01),
        (np.nextafter(1.0, 0.0), 2.0**-52, 1.0),
        (1.0, -(2.0**-53), 1.0),
        (0.0, float(np.nextafter(0.0, 1.0)), 1.0),
        (1e300, -1e300, 1e300),
    ],
)
def test_inverse_slabs_preserve_actual_parameters_at_rounded_grid_contacts(
    start: float,
    delta: float,
    spacing: float,
):
    fractions = np.linspace(0.0, 1.0, 1001)
    with np.errstate(over="ignore", under="ignore"):
        crossings = (np.arange(-20.0, 21.0) * spacing - start) / delta
    crossings = crossings[np.isfinite(crossings) & (crossings >= 0.0) & (crossings <= 1.0)]
    crossings = np.concatenate(
        (crossings, np.nextafter(crossings, 0.0), np.nextafter(crossings, 1.0))
    )
    fractions = np.concatenate((fractions, crossings))
    indices = np.floor((start + fractions * delta) / spacing).astype(np.int64)
    with np.errstate(over="ignore", under="ignore"):
        clipped = slab_fractions(
            start,
            delta,
            spacing,
            indices,
            Interval(np.zeros(len(fractions)), np.ones(len(fractions))),
        )
    assert np.all(clipped.low <= fractions) and np.all(fractions <= clipped.high)


def test_diagonal_path_avoids_the_large_rectangle_cell_budget_failure() -> None:
    parameters = NoiseParameters(detail_levels=12, roughness=0.9)
    path = PATHS[0]
    rectangle = enclose_noise(np.asarray(((-0.542, 0.386, 3.458, 4.386),)), parameters)
    result = enclose_noise_profile(path, np.asarray(((0.0, 1.0),)), parameters)
    assert rectangle.status == "cell_budget_exceeded" and result.status == "bounded"
    assert result.requested_cell_count is not None and rectangle.requested_cell_count is not None
    assert result.requested_cell_count < rectangle.requested_cell_count // 100
    assert result.evaluated_cell_count == result.requested_cell_count
    assert result.field_m is not None
    fractions = np.linspace(0.0, 1.0, 65_537)
    points = np.asarray(path.start_km) + fractions[:, None] * np.asarray(path.delta_km)
    values = (
        2000.0 + 1000.0 * fractal_value_noise(points[:, 0], points[:, 1], **asdict(parameters))
    ).astype(np.float32)
    assert np.all((result.field_m.low[0] <= values) & (values <= result.field_m.high[0]))


def test_every_slab_and_cell_is_budgeted_before_any_noise_evaluation() -> None:
    parameters = NoiseParameters(detail_levels=6)
    spans = np.asarray(((0.0, 0.25), (0.25, 1.0)))
    result = enclose_noise_profile(PATHS[0], spans, parameters)
    assert result.requested_slab_count is not None and result.requested_cell_count is not None
    with patch("benchmarks.noise_profiles._cell_plan", side_effect=AssertionError("allocated")):
        slabs = enclose_noise_profile(
            PATHS[0], spans, parameters, max_slabs=result.requested_slab_count - 1
        )
    assert slabs.status == "slab_budget_exceeded"
    assert slabs.requested_slab_count == result.requested_slab_count
    assert slabs.requested_cell_count is None and slabs.evaluated_cell_count == 0
    assert slabs.field_m is slabs.noise is None
    with patch(
        "benchmarks.noise_intervals._lattice_values", side_effect=AssertionError("evaluated")
    ):
        cells = enclose_noise_profile(
            PATHS[0], spans, parameters, max_cells=result.requested_cell_count - 1
        )
    assert cells.status == "cell_budget_exceeded"
    assert cells.requested_cell_count == result.requested_cell_count
    assert cells.evaluated_cell_count == 0 and cells.noise is cells.field_m is None
    exact = enclose_noise_profile(
        PATHS[0],
        spans,
        parameters,
        max_slabs=result.requested_slab_count,
        max_cells=result.requested_cell_count,
    )
    assert exact.status == "bounded"


def test_huge_slab_preflight_does_not_allocate_a_prefix() -> None:
    with patch("benchmarks.noise_profiles._cell_plan", side_effect=AssertionError("allocated")):
        result = enclose_noise_profile(
            NoisePath((-1e12, -1e12), (2e12, 2e12)),
            np.asarray(((0.0, 1.0),)),
            NoiseParameters(detail_levels=1),
        )
    assert result.status == "slab_budget_exceeded"
    assert result.requested_slab_count is not None and result.requested_slab_count > 1e12
    assert result.requested_cell_count is None and result.evaluated_cell_count == 0
    unsupported = enclose_noise_profile(
        NoisePath((1e100, 0.0), (1.0, 1.0)), np.asarray(((0.0, 1.0),)), NoiseParameters()
    )
    assert unsupported.status == "coordinate_range_exceeded" and unsupported.noise is None


def test_profile_box_batching_does_not_change_bounds() -> None:
    spans = np.asarray(((0.0, 0.2), (0.2, 0.4), (0.4, 1.0)))
    parameters = NoiseParameters()
    all_bounds = enclose_noise_profile(PATHS[5], spans, parameters)
    reverse = enclose_noise_profile(PATHS[5], spans[::-1], parameters)
    assert all_bounds.field_m is not None and reverse.field_m is not None
    assert all_bounds.field_m.low.tobytes() == reverse.field_m.low[::-1].tobytes()
    assert all_bounds.field_m.high.tobytes() == reverse.field_m.high[::-1].tobytes()
    for i in range(len(spans)):
        one = enclose_noise_profile(PATHS[5], spans[i : i + 1], parameters)
        assert one.field_m is not None
        assert one.field_m.low[0] == all_bounds.field_m.low[i]
        assert one.field_m.high[0] == all_bounds.field_m.high[i]


def test_ordered_rise_uses_path_order_and_covers_hidden_rises_within_an_interval() -> None:
    descending = Interval(np.asarray((8.0, 4.0, 0.0)), np.asarray((9.0, 5.0, 1.0)))
    assert 1.0 <= ordered_rise_upper_bound(descending) <= np.nextafter(1.0, np.inf)
    ascending = Interval(descending.low[::-1], descending.high[::-1])
    assert 9.0 <= ordered_rise_upper_bound(ascending) <= np.nextafter(9.0, np.inf)
    hidden = Interval(np.asarray((0.0,)), np.asarray((20.0,)))
    assert ordered_rise_upper_bound(hidden) >= 20.0


def test_ordered_rise_encloses_dense_profile_excursions() -> None:
    parameters = NoiseParameters(detail_levels=12, roughness=0.9)
    fractions = np.linspace(0.0, 1.0, 65_537)
    points = np.asarray(PATHS[0].start_km) + fractions[:, None] * np.asarray(PATHS[0].delta_km)
    values = (
        (2000.0 + 1000.0 * fractal_value_noise(points[:, 0], points[:, 1], **asdict(parameters)))
        .astype(np.float32)
        .astype(np.float64)
    )
    reference = float(np.max(values - np.minimum.accumulate(values)))
    knots = np.linspace(0.0, 1.0, 257)
    result = enclose_noise_profile(PATHS[0], np.column_stack((knots[:-1], knots[1:])), parameters)
    assert result.field_m is not None
    assert ordered_rise_upper_bound(result.field_m) >= reference


@pytest.mark.parametrize(
    "spans",
    [
        np.empty((0, 2)),
        np.ones((1, 3)),
        np.asarray(((0.5, 0.4),)),
        np.asarray(((-0.01, 1.0),)),
        np.asarray(((0.0, 1.01),)),
        np.asarray(((0.0, np.nan),)),
        np.zeros((65_537, 2)),
    ],
)
def test_invalid_profile_spans_are_rejected(spans: NDArray[np.float64]) -> None:
    with pytest.raises(ValueError, match="Noise spans"):
        enclose_noise_profile(PATHS[0], spans, NoiseParameters())


@pytest.mark.parametrize("budget", [-1, True, 262_145])
def test_invalid_slab_budget_is_rejected(budget: int) -> None:
    with pytest.raises(ValueError, match="Noise slab budget"):
        enclose_noise_profile(
            PATHS[0], np.asarray(((0.0, 1.0),)), NoiseParameters(), max_slabs=budget
        )


def test_runner_selects_the_path_policy_and_exports_rise_uncertainty(tmp_path: Path) -> None:
    output = tmp_path / "profiles.json"
    command = [
        sys.executable,
        "-m",
        "benchmarks.noise_bounds",
        "--seed",
        "42",
        "--detail",
        "12",
        "--span",
        "2",
        "--roughness",
        ".9",
        "--direction",
        "diagonal",
        "--divisions",
        "1",
        "--repeats",
        "2",
        "--output",
        str(output),
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    data = json.loads(output.read_text())
    assert data["complete"] and data["schema_version"] == 3
    first, second = data["runs"]
    assert first["evidence_sha256"] == second["evidence_sha256"]
    natural, box, profile, hybrid = first["evidence"]["trials"]
    assert hybrid["method"] == "profile_hybrid" and hybrid["status"] == "bounded"
    assert natural["status"] == box["status"] == "cell_budget_exceeded"
    assert profile["method"] == "profile_slabs" and profile["status"] == "bounded"
    assert profile["requested_slab_count"] > 0
    assert (
        profile["enclosure"]["maximum_uphill_upper_bound_m"]
        >= first["evidence"]["reference_uphill_m"]
    )
