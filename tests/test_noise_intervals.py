"""Conservative noise bounds must cover unseen coordinates and fail as a whole."""

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from numpy.typing import NDArray

from benchmarks.noise_bounds import validate_controls
from benchmarks.noise_intervals import (
    FADE_ROUNDING_ERROR,
    LERP_ROUNDING_ERROR,
    BoundMethod,
    Interval,
    NoiseParameters,
    enclose_noise,
    fade_interval,
)
from benchmarks.terrain import ROOT
from map_maker.terrain.pipeline.noise import (
    _fade,  # pyright: ignore[reportPrivateUsage]
    fractal_value_noise,
)


@pytest.mark.parametrize(
    "a,b",
    [
        ((-0.7, 0.9), (-4.0, -1.0)),
        ((-0.0, 0.0), (1.0, 2.0)),
        ((1e100, 1e101), (-1e100, 1e100)),
        ((-1e-300, 1e-300), (-1e-20, 1e-20)),
        ((1.0, 1.0), (-1.0, -1.0)),
    ],
)
def test_interval_operations_enclose_exact_rational_corner_results(
    a: tuple[float, float],
    b: tuple[float, float],
) -> None:
    first, second = (
        Interval(np.asarray(a[0]), np.asarray(a[1])),
        Interval(np.asarray(b[0]), np.asarray(b[1])),
    )
    operations: tuple[tuple[Interval, Callable[[Fraction, Fraction], Fraction]], ...] = (
        (first.add(second), lambda x, y: x + y),
        (first.subtract(second), lambda x, y: x - y),
        (first.multiply(second), lambda x, y: x * y),
    )
    for result, operation in operations:
        for x in a:
            for y in b:
                exact = operation(Fraction(x), Fraction(y))
                assert Fraction(float(result.low)) <= exact <= Fraction(float(result.high))
    divided = first.divide_positive(0.7)
    for x in a:
        assert (
            Fraction(float(divided.low))
            <= Fraction(x) / Fraction(0.7)
            <= Fraction(float(divided.high))
        )


def test_fade_bounds_cover_values_next_to_lattice_boundaries_without_unit_clipping() -> None:
    values = np.concatenate(
        (
            np.linspace(0.0, 1.0, 10_001),
            np.arange(500, dtype=np.float64) * np.finfo(float).eps / 2,
            1.0 - np.arange(500, dtype=np.float64) * np.finfo(float).eps / 2,
        )
    )
    actual = _fade(values)
    interval = fade_interval(Interval.point(values))
    assert np.all(interval.low <= actual) and np.all(actual <= interval.high)
    # The runtime polynomial can slightly exceed one; clipping would be unsound.
    assert np.any(actual > 1.0)
    assert np.all(interval.high[actual > 1.0] > 1.0)


@pytest.mark.parametrize(
    "parameters",
    [
        NoiseParameters(seed=0, detail_levels=1),
        NoiseParameters(seed=42, detail_levels=6, roughness=0.25),
        NoiseParameters(seed=(1 << 64) - 1, detail_levels=12, roughness=0.9),
    ],
)
@pytest.mark.parametrize("method", ["natural", "monotone_cell"])
@pytest.mark.parametrize("amplitude,offset", [(1000.0, 2000.0), (-1700.0, -0.01), (0.0, 0.0)])
def test_noise_boxes_enclose_independent_interior_edge_and_corner_samples(
    parameters: NoiseParameters,
    amplitude: float,
    offset: float,
    method: BoundMethod,
) -> None:
    finest = parameters.largest_feature_km / (1 << (parameters.detail_levels - 1))
    boxes = (
        np.asarray(
            (
                (-1.2, -0.8, -0.7, 0.3),
                (-0.01, -0.01, 0.01, 0.01),
                (0.0, 0.0, 0.0, 0.0),
                (2.0, -2.0, 2.0, -2.0),
                (2.0 - finest, -finest, 2.0 + finest, finest),
            )
        )
        * finest
    )
    original = boxes.tobytes()
    result = enclose_noise(boxes, parameters, amplitude_m=amplitude, offset_m=offset, method=method)
    assert result.status == "bounded" and result.noise is not None and result.field_m is not None
    fractions = np.linspace(0.0, 1.0, 33)
    x_fraction, y_fraction = np.meshgrid(fractions, fractions)
    rng = np.random.default_rng(20260913)
    interior = rng.random((200, 2))
    points = np.concatenate((np.column_stack((x_fraction.ravel(), y_fraction.ravel())), interior))
    for index, box in enumerate(boxes):
        samples = box[:2] + points * (box[2:] - box[:2])
        noise = fractal_value_noise(samples[:, 0], samples[:, 1], **asdict(parameters))
        field = (offset + amplitude * noise).astype(np.float32)
        assert np.all((result.noise.low[index] <= noise) & (noise <= result.noise.high[index]))
        assert np.all((result.field_m.low[index] <= field) & (field <= result.field_m.high[index]))
    assert boxes.tobytes() == original


def test_large_cross_cell_box_is_covered_and_subdivision_tightens_global_extrema() -> None:
    parameters = NoiseParameters(detail_levels=4)
    coarse = enclose_noise(np.asarray(((-3.0, -0.2, 3.0, 0.8),)), parameters)
    corners = np.column_stack((np.linspace(-3.0, 3.0, 257), np.linspace(-0.2, 0.8, 257)))
    fine = enclose_noise(np.column_stack((corners[:-1], corners[1:])), parameters)
    assert coarse.status == fine.status == "bounded"
    assert coarse.field_m is not None and fine.field_m is not None
    assert np.min(fine.field_m.low) > coarse.field_m.low[0]
    assert np.max(fine.field_m.high) < coarse.field_m.high[0]
    points = corners[0] + np.linspace(0.0, 1.0, 65_537)[:, None] * (corners[-1] - corners[0])
    field = (
        2000.0 + 1000.0 * fractal_value_noise(points[:, 0], points[:, 1], **asdict(parameters))
    ).astype(np.float32)
    assert np.all((coarse.field_m.low[0] <= field) & (field <= coarse.field_m.high[0]))
    owners = np.minimum(np.arange(len(points)) // 256, 255)
    assert np.all((fine.field_m.low[owners] <= field) & (field <= fine.field_m.high[owners]))


def test_bound_identity_is_independent_of_box_order_and_batch_size() -> None:
    parameters = NoiseParameters()
    boxes = np.asarray(
        ((0.01, -0.15, 0.014, -0.14), (-0.031, 2.0, 0.001, 2.1), (-0.0, 0.0, 0.0, 0.0))
    )
    together = enclose_noise(boxes, parameters)
    reversed_result = enclose_noise(boxes[::-1], parameters)
    assert together.noise is not None and reversed_result.noise is not None
    for name in ("low", "high"):
        assert (
            getattr(together.noise, name).tobytes()
            == getattr(reversed_result.noise, name)[::-1].tobytes()
        )
    for index in range(len(boxes)):
        single = enclose_noise(boxes[index : index + 1], parameters)
        assert single.noise is not None
        assert single.noise.low[0] == together.noise.low[index]
        assert single.noise.high[0] == together.noise.high[index]


def test_cell_budget_counts_all_octaves_and_boxes_before_lattice_evaluation() -> None:
    parameters = NoiseParameters(detail_levels=4)
    boxes = np.asarray(((0.0, 0.0, 1.0, 1.0), (10.0, 10.0, 11.0, 11.0)))
    complete = enclose_noise(boxes, parameters)
    assert complete.requested_cell_count is not None
    with patch(
        "benchmarks.noise_intervals._lattice_values", side_effect=AssertionError("evaluated")
    ):
        failed = enclose_noise(boxes, parameters, max_cells=complete.requested_cell_count - 1)
    assert failed.status == "cell_budget_exceeded"
    assert failed.requested_cell_count == complete.requested_cell_count
    assert failed.evaluated_cell_count == 0 and failed.noise is failed.field_m is None
    boundary = enclose_noise(boxes, parameters, max_cells=complete.requested_cell_count)
    assert boundary.status == "bounded"


def test_huge_cell_count_does_not_overflow_or_allocate_a_prefix() -> None:
    with patch(
        "benchmarks.noise_intervals._lattice_values", side_effect=AssertionError("evaluated")
    ):
        result = enclose_noise(
            np.asarray(((-1e14, -1e14, 1e14, 1e14),)), NoiseParameters(detail_levels=1)
        )
    assert result.status == "cell_budget_exceeded"
    assert result.requested_cell_count is not None and result.requested_cell_count > 1 << 63
    assert result.evaluated_cell_count == 0 and result.noise is None


def test_unsupported_coordinate_range_cannot_return_earlier_octaves() -> None:
    with patch(
        "benchmarks.noise_intervals._lattice_values", side_effect=AssertionError("evaluated")
    ):
        result = enclose_noise(
            np.asarray(((1e14, 0.0, 1e14, 0.0),)), NoiseParameters(detail_levels=12)
        )
    assert result.status == "coordinate_range_exceeded"
    assert result.requested_cell_count is None and result.evaluated_cell_count == 0
    assert result.noise is result.field_m is None


def test_float32_enclosure_contains_rounding_at_half_ulp_and_subnormal_values() -> None:
    values = np.asarray(
        (0.0, np.nextafter(0.0, 1.0), 1.0 + 2.0**-24, -1.0 - 2.0**-24, 4000.0 + 2.0**-13)
    )
    result = Interval.point(values).float32()
    actual = values.astype(np.float32)
    assert np.all(result.low <= actual) and np.all(actual <= result.high)
    assert np.all(result.low <= values) and np.all(values <= result.high)


@pytest.mark.parametrize(
    "boxes",
    [
        np.empty((0, 4)),
        np.ones((1, 3)),
        np.asarray(((1.0, 0.0, 0.0, 1.0),)),
        np.asarray(((0.0, 0.0, np.nan, 1.0),)),
        np.zeros((65_537, 4)),
    ],
)
def test_invalid_boxes_fail_before_work(boxes: NDArray[np.float64]) -> None:
    with pytest.raises(ValueError, match="Noise boxes"):
        enclose_noise(boxes, NoiseParameters())


@pytest.mark.parametrize(
    "seed,feature,detail,roughness",
    [
        (-1, 2.0, 6, 0.55),
        (1 << 64, 2.0, 6, 0.55),
        (True, 2.0, 6, 0.55),
        (42, float("nan"), 6, 0.55),
        (42, 0.0, 6, 0.55),
        (42, 2.0, 13, 0.55),
        (42, 2.0, True, 0.55),
        (42, 2.0, 6, 1.0),
        (42, 2.0, 6, float("nan")),
        (42, float(np.nextafter(0.0, 1.0)), 12, 0.55),
    ],
)
def test_invalid_noise_settings(seed: int, feature: float, detail: int, roughness: float) -> None:
    with pytest.raises(ValueError, match="Noise"):
        NoiseParameters(seed, feature, detail, roughness)


@pytest.mark.parametrize(
    "divisions,budget,repeats",
    [
        ((0,), 20, 2),
        ((3,), 20, 2),
        ((16, 1), 20, 2),
        ((1, 1), 20, 2),
        ((16_384,), 20, 2),
        ((1,), 0, 2),
        ((1,), 262_145, 2),
        ((1,), 20, 0),
    ],
)
def test_invalid_runner_controls(divisions: tuple[int, ...], budget: int, repeats: int) -> None:
    with pytest.raises(ValueError, match="Noise"):
        validate_controls(divisions, budget, repeats)


def test_runner_repeats_evidence_and_never_overwrites_a_report(tmp_path: Path) -> None:
    output = tmp_path / "noise.json"
    command = [
        sys.executable,
        "-m",
        "benchmarks.noise_bounds",
        "--seed",
        "42",
        "--detail",
        "6",
        "--roughness",
        ".55",
        "--span",
        ".25",
        "--direction",
        "oblique",
        "--divisions",
        "1",
        "16",
        "--repeats",
        "2",
        "--output",
        str(output),
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["complete"] and report["method"]["complete_terrain_bound"] is False
    first, second = report["runs"]
    assert first["input_sha256"] == second["input_sha256"]
    assert first["evidence_sha256"] == second["evidence_sha256"]
    assert all(t["enclosure"]["reference_outside_count"] == 0 for t in first["evidence"]["trials"])
    trials = [t for t in first["evidence"]["trials"] if t["method"] in ("natural", "monotone_cell")]
    for natural, polynomial in zip(trials[::2], trials[1::2], strict=True):
        assert natural["method"] == "natural" and polynomial["method"] == "monotone_cell"
        assert natural["positions_sha256"] == polynomial["positions_sha256"]
        assert natural["samples_sha256"] == polynomial["samples_sha256"]
        assert natural["enclosure"]["bounds_sha256"] != polynomial["enclosure"]["bounds_sha256"]
        assert (
            polynomial["enclosure"]["maximum_interval_width_m"]
            < natural["enclosure"]["maximum_interval_width_m"]
        )
    original = output.read_bytes()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0 and output.read_bytes() == original


def test_invalid_cli_does_not_reserve_report(tmp_path: Path) -> None:
    output = tmp_path / "invalid.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.noise_bounds",
            "--roughness",
            "nan",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "Noise" in result.stderr and not output.exists()


def test_all_supported_noise_octaves_wrap_hashes_without_overflow_warnings() -> None:
    points = np.linspace(-2000.0, 2000.0, 101)
    parameters = NoiseParameters(seed=(1 << 64) - 1, detail_levels=12)
    with np.errstate(over="raise", invalid="raise"):
        together = fractal_value_noise(points, points[::-1], **asdict(parameters))
        separate = np.concatenate(
            [
                fractal_value_noise(
                    points[i : i + 1], points[::-1][i : i + 1], **asdict(parameters)
                )
                for i in range(len(points))
            ]
        )
    assert np.all(np.isfinite(together)) and together.tobytes() == separate.tobytes()


def test_fade_error_allowance_against_exact_rational_polynomial() -> None:
    rng = np.random.default_rng(991)
    values = np.concatenate(
        (
            rng.random(300),
            np.linspace(0.0, 1.0, 101),
            np.asarray((np.nextafter(0.0, 1.0), np.nextafter(1.0, 0.0)), dtype=np.float64),
        )
    )
    calculated = _fade(values)
    for value, actual in zip(values, calculated, strict=True):
        t = Fraction(float(value))
        exact = 6 * t**5 - 15 * t**4 + 10 * t**3
        assert abs(Fraction(float(actual)) - exact) <= Fraction(FADE_ROUNDING_ERROR)


def test_lerp_rounding_allowance_against_exact_rational_bilinear_value() -> None:
    rng = np.random.default_rng(993)
    cases = rng.uniform(-1.0, 1.0, (400, 6))
    cases[:, :2] *= 1.999
    cases = np.vstack(
        (
            cases,
            (1.0, 0.0, -1.0, 1.0, 1.0, -1.0),
            (np.nextafter(0.0, 1.0), 1.0, -1.0, -1.0, 1.0, 1.0),
        )
    )
    for tx, ty, a, b, c, d in cases:
        top, bottom = a + tx * (b - a), c + tx * (d - c)
        actual = top + ty * (bottom - top)
        u, v, p, q, r, s = (Fraction(float(value)) for value in (tx, ty, a, b, c, d))
        exact_top, exact_bottom = p + u * (q - p), r + u * (s - r)
        exact = exact_top + v * (exact_bottom - exact_top)
        assert abs(Fraction(float(actual)) - exact) <= Fraction(LERP_ROUNDING_ERROR)


def test_polynomial_enclosure_reduces_natural_extension_overestimation() -> None:
    boxes = np.asarray(((-0.5, 0.2, 0.8, 1.4),))
    parameters = NoiseParameters(detail_levels=6)
    natural = enclose_noise(boxes, parameters, method="natural")
    polynomial = enclose_noise(boxes, parameters, method="monotone_cell")
    assert natural.field_m is not None and polynomial.field_m is not None
    assert polynomial.field_m.low[0] > natural.field_m.low[0]
    assert polynomial.field_m.high[0] < natural.field_m.high[0]
    rng = np.random.default_rng(995)
    points = boxes[0, :2] + rng.random((20_000, 2)) * (boxes[0, 2:] - boxes[0, :2])
    actual = (
        2000.0 + 1000.0 * fractal_value_noise(points[:, 0], points[:, 1], **asdict(parameters))
    ).astype(np.float32)
    assert np.all((polynomial.field_m.low[0] <= actual) & (actual <= polynomial.field_m.high[0]))
