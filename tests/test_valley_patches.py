"""Physical patch gains cannot hide authoring or raster-delivery regressions."""

from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pytest
from shapely.geometry import box

from benchmarks.evolution.constrained import FittedSurface, HardHeights, InfeasibleSurface, fit
from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.network_comparison import routing
from benchmarks.evolution.network_fixture import NetworkFixture, fixture
from benchmarks.evolution.patch_comparison import inspect_surface
from benchmarks.evolution.valley_patches import (
    PatchSettings,
    prepare_patches,
    project_hard_heights,
    swept_profile,
)
from map_maker.terrain.domain.evolution import EvolutionGrid


@pytest.fixture(scope="module")
def prepared() -> tuple[NetworkFixture, FittedSurface]:
    f = fixture(250)
    return f, fit(
        f.source.grid,
        f.network,
        f.source.ground_m.astype(np.float64),
        f.limits_m,
        f.target_m,
        f.hard,
    )


@pytest.mark.parametrize("section", ["rounded", "sharp"])
@pytest.mark.parametrize("upstream", [10.0, 80.0])
def test_swept_section_matches_independent_dense_minimization(
    section: Literal["rounded", "sharp"],
    upstream: float,
) -> None:
    settings = PatchSettings(cross_section=section)
    p, q = np.array([20.0, 30.0]), np.array([820.0, 630.0])
    xy = np.array([[0.0, 40.0], [500.0, 400.0], [850.0, 800.0]])
    actual, _ = swept_profile(xy, p, q, np.array([upstream, 0.0]), settings)
    t = np.linspace(0.0, 1.0, 100001)
    path = p + t[:, None] * (q - p)
    power = 2 if section == "rounded" else 1
    expected_values: list[float] = []
    for point in xy:
        offsets: np.ndarray[Any, np.dtype[np.float64]] = point - path
        distance = np.linalg.norm(offsets, axis=1)
        values = (
            upstream * (1 - t)
            + settings.bank_rise_m * (distance / settings.floor_radius_m) ** power
        )
        expected_values.append(float(np.min(values)))
    expected = np.array(expected_values)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-5)


def test_patch_geometry_has_fixed_physical_support_and_owned_arrays(
    prepared: tuple[NetworkFixture, FittedSurface],
) -> None:
    f, control = prepared
    candidate = prepare_patches(f, control, mode="fresh")
    coarse = fixture(500)
    other = prepare_patches(coarse, coarse.source, mode="fresh")
    np.testing.assert_array_equal(candidate.segments_m, other.segments_m)
    np.testing.assert_allclose(candidate.bed_heights_m, other.bed_heights_m, atol=1e-4, rtol=0)
    assert len(candidate.segments_m) == 249
    assert candidate.settings == other.settings
    for a in (candidate.segments_m, candidate.bed_heights_m, candidate.anchor_corrections_m):
        assert not a.flags.writeable
    before = f.source.ground_m.copy()
    candidate.deliver()
    np.testing.assert_array_equal(f.source.ground_m, before)


def test_fixed_patch_preserves_native_caps_divide_coast_and_off_grid_heights(
    prepared: tuple[NetworkFixture, FittedSurface],
) -> None:
    f, control = prepared
    patch = prepare_patches(f, control)
    result = patch.deliver()
    assert np.all(result.ground_m <= f.source.ground_m)
    assert np.all(result.ground_m.astype(np.float64) >= f.source.ground_m - f.limits_m)
    np.testing.assert_array_equal(
        result.ground_m[f.limits_m == 0], f.source.ground_m[f.limits_m == 0]
    )
    for sampler in (patch.sample, result.sample):
        np.testing.assert_allclose(sampler(*f.hard.points_m.T), f.hard.heights_m, atol=1e-4, rtol=0)
    np.testing.assert_array_equal(result.ground_m[-1], np.zeros(result.ground_m.shape[1]))
    np.testing.assert_array_equal(result.ground_m, prepare_patches(f, control).deliver().ground_m)


def test_local_capture_does_not_mask_raster_loss_at_a_hard_height(
    prepared: tuple[NetworkFixture, FittedSurface],
) -> None:
    f, control = prepared
    patch = prepare_patches(f, control, mode="fresh")
    result = patch.deliver()
    local, _ = inspect_surface(f, patch, patch.sample, rotated=False)
    delivered, _ = inspect_surface(f, patch, result.sample, rotated=False)
    assert local["common_routing"]["heads_within_1000m_of_authored_outlet"] == 4
    assert local["common_routing"]["internal_terminal_count"] == 0
    assert local["quality_gates"]["hard_heights"]
    assert delivered["quality_gates"]["hard_heights"]
    assert not delivered["quality_gates"]["head_capture"]
    assert result.diagnostics["maximum_delivery_pin_correction_m"] > 100
    assert not all(delivered["quality_gates"].values())


def test_delivery_caps_cover_cell_interiors_and_pins_correct_the_admitted_local_field(
    prepared: tuple[NetworkFixture, FittedSurface],
) -> None:
    f, control = prepared
    fresh = prepare_patches(f, control, mode="fresh")
    result = fresh.deliver()
    y, x = np.indices((193, 257), dtype=np.float64) * 125.0
    delta = f.source.sample(x, y).astype(np.float64) - result.sample(x, y)
    assert np.all(delta <= fresh.caps(x, y) + 0.01)
    forced = FittedSurface(f.source.grid, np.zeros(f.source.grid.shape, dtype=np.float32), {})
    pinned = prepare_patches(f, forced)
    np.testing.assert_allclose(
        pinned.sample(*f.hard.points_m.T), f.hard.heights_m, rtol=0, atol=1e-4
    )


def test_manufactured_straight_valley_reaches_the_declared_zero_coast() -> None:
    grid = EvolutionGrid(4000, 4000, 250)
    y, x = np.indices(grid.shape, dtype=np.float64) * 250
    z = ((4000 - y) / 4000) ** 1.3 * (200 + 0.00004 * (x - 2000) ** 2)
    source = FittedSurface(grid, z.astype(np.float32), {})
    network = RiverNetwork(
        np.array([[2000.0, 1000.0], [2000.0, 3000.0], [2000.0, 4000.0]]),
        np.array([1, 2, -1], dtype=np.int64),
    )
    f = NetworkFixture(
        source,
        network,
        (),
        box(15000, 0, 16000, 24000),
        np.full(grid.shape, 100.0),
        z,
        HardHeights(np.empty((0, 2)), np.empty(0)),
        100.0,
    )
    patch = prepare_patches(f, source, mode="fresh")
    output = patch.deliver()
    receivers = routing(output)
    assert not np.any(receivers[1:-1, 1:-1] < 0)
    np.testing.assert_array_equal(output.ground_m[-1], source.ground_m[-1])
    node = 4 * grid.shape[1] + 8
    for _ in range(receivers.size):
        if receivers.flat[node] < 0:
            break
        node = int(receivers.flat[node])
    assert node == 16 * grid.shape[1] + 8


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), True])
def test_invalid_scales_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        PatchSettings(profile_spacing_m=value)


def test_work_and_sample_budgets_fail_before_large_preparation(
    prepared: tuple[NetworkFixture, FittedSurface],
) -> None:
    f, control = prepared
    with pytest.raises(ValueError, match="2,048"):
        prepare_patches(f, control, settings=PatchSettings(profile_spacing_m=1e-300))
    patch = prepare_patches(f, control)
    with pytest.raises(ValueError, match="work budget"):
        patch.sample(np.zeros(1_000_001), np.zeros(1))
    with pytest.raises(ValueError, match="inside"):
        patch.sample(np.array([-1.0]), np.array([0.0]))


def test_pin_conflict_is_distinct_from_unsupported_overlapping_support() -> None:
    grid = EvolutionGrid(4000, 4000, 1000)
    source = FittedSurface(grid, np.full(grid.shape, 100, dtype=np.float32), {})
    lower, upper = np.full(25, 50.0), np.full(25, 100.0)
    hard = HardHeights(np.array([[250.0, 250.0]]), np.array([110.0]))
    with pytest.raises(InfeasibleSurface, match="construction envelope"):
        project_hard_heights(source, source.ground_m, lower, upper, hard)
    hard = HardHeights(np.array([[250.0, 250.0], [500.0, 500.0]]), np.array([70.0, 80.0]))
    with pytest.raises(ValueError, match="overlapping"):
        project_hard_heights(source, source.ground_m, lower, upper, hard)


def test_pin_projection_never_silently_accepts_unrepresentable_float32() -> None:
    grid = EvolutionGrid(4000, 4000, 1000)
    source = FittedSurface(grid, np.full(grid.shape, 100000, dtype=np.float32), {})
    hard = HardHeights(np.array([[1000.0, 1000.0]]), np.array([99999.003]))
    with pytest.raises(RuntimeError, match="Float32 delivery"):
        project_hard_heights(source, source.ground_m, np.zeros(25), np.full(25, 100000.0), hard)


def test_conflicting_local_pin_and_unsupported_mouth_reject_explicitly(
    prepared: tuple[NetworkFixture, FittedSurface],
) -> None:
    f, control = prepared
    hard = HardHeights(f.hard.points_m, f.hard.heights_m + 10000)
    with pytest.raises(InfeasibleSurface):
        prepare_patches(replace(f, hard=hard), control)
    xy = f.network.coordinates_m.copy()
    xy[6, 1] -= 10
    with pytest.raises(ValueError, match="straight zero-height coast"):
        prepare_patches(replace(f, network=RiverNetwork(xy, f.network.receivers)), control)


def test_report_retains_surface_and_delivery_failures_with_complete_provenance(
    tmp_path: Path,
) -> None:
    from benchmarks.evolution.patch_comparison import run

    output = tmp_path / "patches"
    report = run(output, figures=False)
    assert report["status"] == "complete"
    assert report["quality_decision"]["status"] == "rejected"
    assert not report["quality_decision"]["production_eligible"]
    assert len(report["rows"]) == 8
    assert all(value <= 0.001 for value in report["rotation_maximum_ground_difference_m"].values())
    assert all(row["repeat_matches"] for row in report["rows"])
    for row in report["rows"]:
        assert "history" in row["input_roles"]
        for stage in ("local", "delivery"):
            assert row[stage]["quality_gates"]["construction_cap"]
            assert row[stage]["quality_gates"]["hard_heights"]
            assert "bank_endpoint_support" in row[stage]["quality_gates"]
        with np.load(output / row["case"] / "fields.npz", allow_pickle=False) as saved:
            assert saved["ground_m"].dtype == np.float32
            assert "local_common_ground_m" in saved
        assert row["artifact_hashes"] and row["numeric_hashes"]
    assert not (output / "incomplete.json").exists()
    with pytest.raises(FileExistsError):
        run(output, figures=False)


def test_execution_failure_cannot_publish_a_completed_experiment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks.evolution import patch_comparison

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("invalid numeric execution")

    monkeypatch.setattr(patch_comparison, "prepare_patches", fail)
    with pytest.raises(RuntimeError, match="invalid numeric execution"):
        patch_comparison.run(tmp_path / "failed", figures=False)
    assert (tmp_path / "failed" / "incomplete.json").is_file()
    assert not (tmp_path / "failed" / "comparison.json").exists()
