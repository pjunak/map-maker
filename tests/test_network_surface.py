"""Whole-cell descent, native bounds and fixed geography for network-led terrain."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from benchmarks.evolution.constrained import (
    HardHeights,
    InfeasibleSurface,
    channel_constraints,
    fit,
    weights,
)
from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.network_fixture import fixture, valley_target
from benchmarks.evolution.paths import FloatArray, measure_paths
from map_maker.terrain.domain import LandformSettings
from map_maker.terrain.domain.evolution import EvolutionGrid
from map_maker.terrain.pipeline.landforms import regional_incision_budget, regional_incision_limit


@pytest.mark.parametrize("spacing", [1000.0, 500.0, 250.0])
def test_native_limits_anchors_coast_divide_and_full_route_descent(spacing: float) -> None:
    f = fixture(spacing)
    source = f.source.ground_m.astype(np.float64)
    result = fit(f.source.grid, f.network, source, f.limits_m, f.target_m, f.hard)
    assert not result.ground_m.flags.writeable
    assert np.all(result.ground_m <= source)
    assert np.all(result.ground_m >= source - f.limits_m)
    np.testing.assert_array_equal(result.ground_m[f.limits_m == 0], source[f.limits_m == 0])
    xy = f.hard.points_m
    np.testing.assert_allclose(
        result.sample(xy[:, 0], xy[:, 1]), f.hard.heights_m, rtol=0, atol=1.0e-4
    )
    nodal = f.source.sample(*f.network.coordinates_m.T).astype(np.float64)
    for stations in (100.0, 25.0, 3.0):
        profiles = measure_paths(f.network, result.sample, nodal, stations)
        assert profiles["required_edge_count"] == 15
        assert profiles["head_route_count"] == 4
        assert all(r["maximum_excursion_m"] <= 0.01 for r in profiles["routes"])
    # Native blended cap, not just the conservative cell cap, at off-grid points.
    x, y = np.random.default_rng(912).uniform((0, 0), (32000, 24000), (10000, 2)).T
    cap = regional_incision_budget(x / 1000, y / 1000, f.global_limit_m, f.regions)
    change = f.source.sample(x, y).astype(np.float64) - result.sample(x, y)
    assert np.all(change >= 0)
    assert np.all(change <= cap + 0.0001)
    # Query ordering, crops and repeated preparation must not perturb coordinates.
    np.testing.assert_array_equal(result.sample(x, y)[::7], result.sample(x[::7], y[::7]))
    repeated = fit(f.source.grid, f.network, source, f.limits_m, f.target_m, f.hard)
    np.testing.assert_array_equal(result.ground_m, repeated.ground_m)


def test_rotated_problem_and_unchanged_parent_at_shared_coordinates() -> None:
    first, rotated = fixture(), fixture(rotate=True)
    a = fit(
        first.source.grid,
        first.network,
        first.source.ground_m.astype(np.float64),
        first.limits_m,
        first.target_m,
        first.hard,
    )
    b = fit(
        rotated.source.grid,
        rotated.network,
        rotated.source.ground_m.astype(np.float64),
        rotated.limits_m,
        rotated.target_m,
        rotated.hard,
    )
    np.testing.assert_allclose(a.ground_m, np.rot90(b.ground_m), atol=0.001, rtol=0)
    x, y = np.array([1375.0, 14325.0, 26750.0]), np.array([4375.0, 8765.0, 17312.0])
    for spacing in (1000.0, 250.0):
        np.testing.assert_array_equal(
            first.source.sample(x, y), fixture(spacing).source.sample(x, y)
        )


def test_cell_derivative_constraints_detect_a_hidden_bilinear_hump() -> None:
    grid = EvolutionGrid(4000, 4000, 1000)
    network = RiverNetwork(
        np.array([[1000.0, 1000.0], [2000.0, 2000.0]]), np.array([1, -1], dtype=np.int64)
    )
    z = np.full(grid.shape, 200.0)
    z[1, 1], z[2, 2] = 100.0, 90.0
    rows, lengths = channel_constraints(grid, network, 0.0)
    slopes = np.asarray(rows @ z.ravel()).ravel() / lengths
    assert len(slopes) == 2
    assert slopes[0] > 0 and slopes[1] < 0
    # A wide cut bound allows a genuine ground construction with a monotone channel.
    result = fit(
        grid,
        network,
        z,
        np.full(grid.shape, 120.0),
        z,
        HardHeights(network.coordinates_m, np.array([100.0, 90.0])),
    )
    line = np.linspace(1000.0, 2000.0, 20001)
    assert np.all(np.diff(result.sample(line, line)) <= 0)


def test_incompatible_route_is_rejected_without_lowering_its_hard_heights() -> None:
    grid = EvolutionGrid(4000, 4000, 1000)
    network = RiverNetwork(
        np.array([[1000.0, 1000.0], [2000.0, 2000.0]]), np.array([1, -1], dtype=np.int64)
    )
    z = np.full(grid.shape, 100.0)
    hard = HardHeights(network.coordinates_m, np.array([70.0, 90.0]))
    # Both target heights individually respect [60,100]; their ordering is impossible.
    with pytest.raises(InfeasibleSurface, match="incompatible"):
        fit(grid, network, z, np.full(grid.shape, 40.0), z, hard)
    np.testing.assert_array_equal(hard.heights_m, [70.0, 90.0])
    with pytest.raises(InfeasibleSurface, match="local cut/no-fill"):
        fit(grid, network, z, np.full(grid.shape, 5.0), z, hard)


def test_network_crossings_cycles_and_invalid_values_are_explicit_failures() -> None:
    with pytest.raises(ValueError, match="junction"):
        RiverNetwork(
            np.array([[0.0, 0.0], [2.0, 2.0], [0.0, 2.0], [2.0, 0.0]]),
            np.array([1, -1, 3, -1], dtype=np.int64),
        )
    with pytest.raises(ValueError, match="cycle"):
        RiverNetwork(np.array([[0.0, 0.0], [2.0, 2.0]]), np.array([1, 0], dtype=np.int64))
    with pytest.raises(ValueError, match="inside"):
        weights(EvolutionGrid(4000, 4000, 1000), np.array([[float("nan"), 0.0]]))
    with pytest.raises(ValueError, match="Hard heights"):
        HardHeights(np.array([[0.0, 0.0]]), np.array(1.0))


def test_no_cut_protected_region_cannot_be_silently_carved() -> None:
    f = fixture()
    points = f.hard.points_m[[1]]
    heights = f.hard.heights_m[[1]] - 1.0
    with pytest.raises(InfeasibleSurface, match="local cut/no-fill"):
        fit(
            f.source.grid,
            f.network,
            f.source.ground_m.astype(np.float64),
            f.limits_m,
            f.target_m,
            HardHeights(points, heights),
        )


def test_solver_incomplete_and_nonfinite_inputs_do_not_publish_a_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks.evolution import constrained

    f = fixture()

    class Incomplete:
        status = 1
        success = False
        message = "time limit reached"

    def fail(*args: Any, **kwargs: Any) -> Incomplete:
        return Incomplete()

    monkeypatch.setattr(constrained.optimize, "linprog", fail)
    with pytest.raises(RuntimeError, match="did not complete"):
        fit(
            f.source.grid,
            f.network,
            f.source.ground_m.astype(np.float64),
            f.limits_m,
            f.target_m,
            f.hard,
        )
    with pytest.raises(ValueError, match="finite"):
        fit(
            f.source.grid,
            f.network,
            np.full(f.source.grid.shape, np.nan),
            f.limits_m,
            f.target_m,
            f.hard,
        )


def test_native_region_limit_has_one_owner_and_remains_globally_capped() -> None:
    for kind, ratio in (("plain", 0.15), ("hills", 0.40), ("plateau", 0.25), ("mountains", 0.25)):
        settings = replace(LandformSettings(), character=kind)  # type: ignore[arg-type]
        assert regional_incision_limit(1000.0, settings) == ratio * 100
        assert regional_incision_limit(10.0, settings) == 10.0


def test_coastal_valley_target_has_compact_physical_support() -> None:
    f = fixture()
    y, x = np.indices(f.source.grid.shape, dtype=np.float64) * f.source.grid.spacing_m
    xy = np.stack((x.ravel(), y.ravel()), axis=-1)
    distance: FloatArray = np.full(len(xy), np.inf, dtype=np.float64)
    for a in np.flatnonzero(f.network.required):
        b = f.network.receivers[a]
        origin, end = f.network.coordinates_m[[a, b]]
        d = end - origin
        t = np.clip(((xy - origin) @ d) / np.dot(d, d), 0, 1)
        offset: FloatArray = xy - origin - t[:, None] * d
        distance = np.minimum(distance, np.sqrt(np.sum(offset**2, axis=1)))
    outside = distance.reshape(x.shape) >= 2400.0
    assert np.count_nonzero(outside) > x.size / 3
    target = valley_target(f.source, f.network, f.limits_m)
    np.testing.assert_array_equal(target[outside], f.source.ground_m[outside])


def test_quadratic_solver_failure_and_budget_exhaustion_reject_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks.evolution import constrained

    f = fixture()

    class Incomplete:
        success = False
        message = "iteration limit reached"

    def fail(*args: Any, **kwargs: Any) -> Incomplete:
        return Incomplete()

    monkeypatch.setattr(constrained.optimize, "minimize", fail)
    args = (
        f.source.grid,
        f.network,
        f.source.ground_m.astype(np.float64),
        f.limits_m,
        f.target_m,
        f.hard,
    )
    with pytest.raises(RuntimeError, match="iteration limit"):
        fit(*args)
    ticks = iter((0.0, 21.0))
    monkeypatch.setattr(constrained, "perf_counter", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="time budget"):
        fit(*args)


def test_comparison_rejects_failed_capture_despite_descending_profiles(tmp_path: Path) -> None:
    from benchmarks.evolution.network_comparison import run

    result = run(tmp_path / "comparison")
    assert result["status"] == "complete"
    assert result["quality_decision"]["status"] == "rejected"
    assert result["quality_decision"]["production_eligible"] is False
    assert result["rotation_maximum_ground_difference_m"] <= 0.001
    for row in result["rows"]:
        assert row["quality_gates"]["all_required_profiles_descend"]
        assert row["quality_gates"]["sampled_native_cut_no_fill_and_divide"]
        assert row["quality_gates"]["hard_height_residual_within_1cm"]
        assert not row["quality_gates"]["all_heads_reach_authored_outlets"]
        assert row["common_grid_rerouted"]["constrained"]["evaluation_spacing_m"] == 125.0
        assert row["repeat_hash_matches"]
        assert row["incompatible_route"]["status"] == "rejected"
        assert (tmp_path / "comparison" / row["case"] / "routing.png").is_file()
    assert not (tmp_path / "comparison" / "incomplete.json").exists()
    saved = json.loads((tmp_path / "comparison" / "comparison.json").read_text(encoding="utf-8"))
    assert saved["quality_decision"] == result["quality_decision"]
    with pytest.raises(FileExistsError):
        run(tmp_path / "comparison")


def test_failed_comparison_has_no_completion_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.evolution import network_comparison

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ValueError("fixture unavailable")

    monkeypatch.setattr(network_comparison, "fixture", fail)
    output = tmp_path / "failed"
    with pytest.raises(ValueError, match="fixture unavailable"):
        network_comparison.run(output)
    assert not (output / "comparison.json").exists()
    assert (
        json.loads((output / "incomplete.json").read_text(encoding="utf-8"))["status"] == "failed"
    )


def test_fully_fixed_feasible_ground_needs_no_solver(monkeypatch: pytest.MonkeyPatch) -> None:
    from benchmarks.evolution import constrained

    grid = EvolutionGrid(4000, 4000, 1000)
    network = RiverNetwork(
        np.array([[1000.0, 1000.0], [2000.0, 2000.0]]), np.array([1, -1], dtype=np.int64)
    )
    y, _ = np.indices(grid.shape, dtype=np.float64)
    z = 200.0 - 10 * y

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("A fully fixed solution must not start an optimizer.")

    monkeypatch.setattr(constrained.optimize, "linprog", fail)
    result = fit(grid, network, z, np.zeros_like(z), z, HardHeights(np.empty((0, 2)), np.empty(0)))
    np.testing.assert_array_equal(result.ground_m, z)
    assert result.diagnostics["free_constrained_node_count"] == 0
