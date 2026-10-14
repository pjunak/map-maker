"""Bank support does not silently become an accepted drainage field."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from benchmarks.evolution.constrained import FittedSurface, HardHeights, InfeasibleSurface, fit
from benchmarks.evolution.metrics import terminal_labels
from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.network_comparison import routing
from benchmarks.evolution.network_fixture import fixture
from benchmarks.evolution.valley_comparison import bank_profiles, pinned_bank_conflict
from benchmarks.evolution.valley_support import prepare_support
from map_maker.terrain.domain.evolution import EvolutionGrid


def test_support_has_fixed_physical_scale_and_accounts_for_junctions_and_coast() -> None:
    coarse, fine = fixture(1000), fixture(250)
    a = prepare_support(coarse.source.grid, coarse.network)
    b = prepare_support(fine.source.grid, fine.network)
    np.testing.assert_array_equal(a.banks_m, b.banks_m)
    np.testing.assert_array_equal(a.beds_m, b.beds_m)
    assert len(a.banks_m) == 525
    assert a.outside_domain_count == 3
    assert np.count_nonzero(a.requested_edges != a.bed_edges) > 0
    assert set(a.requested_edges) == set(np.flatnonzero(coarse.network.required))
    assert not a.banks_m.flags.writeable and not a.beds_m.flags.writeable
    assert np.all(a.drops_m[a.remaining_to_mouth_m == 0] == 0)
    assert np.all(a.drops_m <= a.minimum_slope * a.distances_m)
    rotated = fixture(250, rotate=True)
    c = prepare_support(rotated.source.grid, rotated.network)
    expected = np.stack((24000 - b.banks_m[:, 1], b.banks_m[:, 0]), axis=-1)
    np.testing.assert_allclose(c.banks_m, expected, rtol=0, atol=1e-8)
    expected = np.stack((24000 - b.beds_m[:, 1], b.beds_m[:, 0]), axis=-1)
    np.testing.assert_allclose(c.beds_m, expected, rtol=0, atol=1e-8)
    np.testing.assert_allclose(c.drops_m, b.drops_m, rtol=0, atol=1e-10)


@pytest.mark.parametrize(
    "spacing,kind", [(1000.0, "bank-local-bounds"), (500.0, "joint-constraints")]
)
def test_incompatible_banks_report_the_conflict_without_a_relaxed_surface(
    spacing: float, kind: str
) -> None:
    f = fixture(spacing)
    support = prepare_support(f.source.grid, f.network)
    before = f.source.ground_m.copy()
    hard = f.hard
    if kind == "joint-constraints":
        hard, _ = pinned_bank_conflict(f, support)
        fit(f.source.grid, f.network, before.astype(np.float64), f.limits_m, f.target_m, hard)
    with pytest.raises(InfeasibleSurface) as caught:
        fit(
            f.source.grid,
            f.network,
            before.astype(np.float64),
            f.limits_m,
            f.target_m,
            hard,
            valley=support,
        )
    diagnostic = caught.value.diagnostics
    assert diagnostic["kind"] == kind
    assert diagnostic["witnesses"]
    if kind == "bank-local-bounds":
        assert diagnostic["maximum_unavoidable_shortfall_m"] > 0.5
        assert all(w["unavoidable_shortfall_m"] > 0 for w in diagnostic["witnesses"])
    else:
        assert diagnostic["minimum_common_bank_shortfall_m"] > 0.01
        assert diagnostic["diagnostic_only"] is True
        assert all(w["dual_weight"] > 0 for w in diagnostic["witnesses"])
    np.testing.assert_array_equal(f.source.ground_m, before)


def test_a_manufactured_valley_preserves_capture_and_a_fixed_coastal_mouth() -> None:
    grid = EvolutionGrid(4000, 4000, 500)
    network = RiverNetwork(
        np.array([[2000.0, 500.0], [2000.0, 2000.0], [2000.0, 4000.0]]),
        np.array([1, 2, -1], dtype=np.int64),
    )
    y, x = np.indices(grid.shape, dtype=np.float64) * grid.spacing_m
    source = (4000 - y) / 1000 * (40 + 15 * np.abs(x - 2000) / 1000)
    limits = np.full(grid.shape, 20.0)
    limits[source == 0] = 0
    support = prepare_support(grid, network)
    assert np.count_nonzero(support.remaining_to_mouth_m == 0) == 2
    hard = HardHeights(np.array([[2000.0, 500.0]]), np.array([140.0]))
    result = fit(grid, network, source, limits, source, hard, valley=support)
    receivers = routing(result)
    labels = terminal_labels(receivers)
    assert int(labels[1, 4]) == 8 * grid.shape[1] + 4
    assert not np.any(receivers[1:-1, 1:-1] < 0)
    assert bank_profiles(support, result.sample)["endpoint_violation_count"] == 0
    np.testing.assert_array_equal(result.ground_m[-1], source[-1])


def test_finer_support_preserves_hard_inputs_but_does_not_certify_inward_profiles() -> None:
    f = fixture(250)
    support = prepare_support(f.source.grid, f.network)
    result = fit(
        f.source.grid,
        f.network,
        f.source.ground_m.astype(np.float64),
        f.limits_m,
        f.target_m,
        f.hard,
        valley=support,
    )
    assert result.diagnostics["maximum_bank_residual_m"] <= 0.0001
    assert np.all(result.ground_m <= f.source.ground_m)
    assert np.all(result.ground_m >= f.source.ground_m - f.limits_m)
    np.testing.assert_allclose(
        result.sample(*f.hard.points_m.T), f.hard.heights_m, atol=1e-4, rtol=0
    )
    numbers = bank_profiles(support, result.sample)
    assert numbers["endpoint_violation_count"] == 0
    assert numbers["inward_uphill_sections"] > 0


def test_bank_section_metric_detects_a_hidden_hump_despite_a_lower_endpoint() -> None:
    grid = EvolutionGrid(4000, 4000, 1000)
    network = RiverNetwork(
        np.array([[2000.0, 1000.0], [2000.0, 4000.0]]), np.array([1, -1], dtype=np.int64)
    )
    v = prepare_support(grid, network)
    v = replace(
        v,
        banks_m=np.array([[1000.0, 1000.0]]),
        beds_m=np.array([[2000.0, 2000.0]]),
        requested_edges=np.array([0], dtype=np.int64),
        bed_edges=np.array([0], dtype=np.int64),
        remaining_to_mouth_m=np.array([2000.0]),
    )
    z = np.full(grid.shape, 200, dtype=np.float32)
    z[1, 1], z[2, 2] = 100, 90
    m = bank_profiles(v, FittedSurface(grid, z, {}).sample)
    assert m["endpoint_violation_count"] == 0
    assert m["inward_uphill_sections"] == 1
    assert m["maximum_inward_excursion_m"] > 40


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), True, 1e-300])
def test_invalid_or_unbounded_support_is_rejected(value: float) -> None:
    f = fixture()
    with pytest.raises(ValueError):
        prepare_support(f.source.grid, f.network, station_spacing_m=value)


def test_support_cannot_be_reused_for_another_network() -> None:
    f = fixture(250)
    support = prepare_support(f.source.grid, f.network)
    other = RiverNetwork(f.network.coordinates_m + np.array([0.1, 0.0]), f.network.receivers)
    with pytest.raises(ValueError, match="different physical network"):
        fit(
            f.source.grid,
            other,
            f.source.ground_m.astype(np.float64),
            f.limits_m,
            f.target_m,
            f.hard,
            valley=support,
        )


def test_report_retains_rejections_and_never_publishes_a_relaxed_ground(tmp_path: Path) -> None:
    from benchmarks.evolution.valley_comparison import run

    output = tmp_path / "valleys"
    result = run(output)
    assert result["status"] == "complete"
    assert result["quality_decision"]["status"] == "rejected"
    assert result["quality_decision"]["production_eligible"] is False
    assert result["rotation_maximum_ground_difference_m"] <= 0.001
    assert all(row["repeat_matches"] for row in result["rows"])
    for row in result["rows"]:
        with np.load(output / row["case"] / "fields.npz", allow_pickle=False) as saved:
            assert ("ground_m" in saved) == (row["status"] == "constructed")
        if row["status"] == "constructed":
            assert row["quality_gates"]["bank_endpoint_support"]
            assert not row["quality_gates"]["inward_bank_profiles"]
    assert (output / "comparison.json").is_file()
    assert not (output / "incomplete.json").exists()
    with pytest.raises(FileExistsError):
        run(output)


def test_solver_error_is_not_relabelled_as_infeasible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.evolution import valley_comparison

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("solver unavailable")

    monkeypatch.setattr(valley_comparison, "fit", fail)
    with pytest.raises(RuntimeError, match="solver unavailable"):
        valley_comparison.run(tmp_path / "failed")
    assert (tmp_path / "failed" / "incomplete.json").is_file()
    assert not (tmp_path / "failed" / "comparison.json").exists()


def test_invalid_numeric_delivery_is_an_incomplete_run_not_infeasible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.evolution import constrained, valley_comparison

    def invalid_result(fun: Any, x0: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            success=True, x=np.full_like(x0, -100000.0), nit=1, message="Converged"
        )

    monkeypatch.setattr(constrained.optimize, "minimize", invalid_result)
    output = tmp_path / "invalid-delivery"
    with pytest.raises(RuntimeError, match="Float32 delivery"):
        valley_comparison.run(output)
    assert (output / "incomplete.json").is_file()
    assert not (output / "comparison.json").exists()
