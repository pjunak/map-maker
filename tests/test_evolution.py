"""Dependency-free contracts for the bounded landscape-evolution experiment."""

from dataclasses import replace

import numpy as np
import pytest

from benchmarks.evolution.metrics import sample_grid, terminal_labels
from benchmarks.evolution.scenarios import EvolutionFields, history, scenario
from map_maker.terrain.domain.evolution import (
    EvolutionBudget,
    EvolutionEpoch,
    EvolutionGrid,
    EvolutionHistory,
)


@pytest.mark.parametrize("spacing", [0., -1., float("nan"), float("inf"), 700.])
def test_process_grid_rejects_invalid_spacing(spacing: float) -> None:
    with pytest.raises(ValueError):
        EvolutionGrid(spacing_m=spacing)


def test_process_area_excludes_fixed_boundary_nodes() -> None:
    grid = EvolutionGrid(400., 600., 100.)
    assert grid.shape == (7, 5)
    assert grid.contributing_area_m2 == 150_000.
    with pytest.raises(ValueError, match="limited"):
        EvolutionGrid(1000., 1000., 1.)


def test_history_and_budget_reject_unbounded_values() -> None:
    epoch = EvolutionEpoch("active", 10., .1)
    with pytest.raises(ValueError, match="unique"):
        EvolutionHistory((epoch, epoch))
    with pytest.raises(ValueError, match="finite"):
        replace(epoch, duration_years=float("inf"))
    with pytest.raises(ValueError, match="nonnegative"):
        replace(epoch, diffusivity_m2_per_year=-1.)
    with pytest.raises(ValueError, match="Minimum"):
        EvolutionBudget(maximum_step_years=.001)
    with pytest.raises(ValueError, match="Trial"):
        EvolutionBudget(maximum_trials=1)
    with pytest.raises(ValueError, match="exponents"):
        EvolutionHistory((epoch,), discharge_exponent=2.)


def test_initial_fields_agree_at_shared_physical_coordinates() -> None:
    coarse = scenario(EvolutionGrid(spacing_m=1250.), 42)
    fine = scenario(EvolutionGrid(spacing_m=625.), 42)
    for name in ("initial_m", "uplift_weight", "resistance", "runoff_weight"):
        np.testing.assert_array_equal(getattr(coarse, name), getattr(fine, name)[::2, ::2])
        assert not getattr(coarse, name).flags.writeable
    assert coarse.hashes() == scenario(coarse.grid, 42).hashes()
    assert coarse.hashes()["initial_m"] != scenario(coarse.grid, 7).hashes()["initial_m"]


def test_fields_own_copies_and_validate_materials() -> None:
    grid = EvolutionGrid(400., 400., 100.)
    values = np.ones(grid.shape)
    fields = EvolutionFields(grid, values, values, values, values)
    values[:] = 0.
    assert np.all(fields.initial_m == 1.)
    with pytest.raises(ValueError, match="resistance"):
        replace(fields, resistance=values)
    with pytest.raises(ValueError, match="match"):
        replace(fields, initial_m=np.ones((2, 2)))


def test_control_histories_match_integrated_forcing() -> None:
    for case in ("two-epoch", "constant", "reversed"):
        h = history(case)
        assert h.duration_years == 6_000_000.
        assert sum(e.duration_years * e.uplift_m_per_year for e in h.epochs) == 1200.
        assert sum(e.duration_years * e.runoff_m_per_year for e in h.epochs) == 2_400_000.
    assert history("reversed").epochs == tuple(reversed(history("two-epoch").epochs))


def test_reconstruction_is_float32_and_query_independent() -> None:
    grid = EvolutionGrid(400., 400., 100.)
    yy, xx = np.indices(grid.shape, dtype=np.float64)
    height = xx * 5. + yy * 3.
    x, y = np.array([0., 125., 400.]), np.array([400., 75., 0.])
    result = sample_grid(height, grid, x, y)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result, .05*x + .03*y)
    np.testing.assert_array_equal(result[1:], sample_grid(height, grid, x[1:], y[1:]))
    with pytest.raises(ValueError, match="inside"):
        sample_grid(height, grid, np.array([401.]), np.array([0.]))


def test_terminal_labels_reject_cycles_and_outside_receivers() -> None:
    np.testing.assert_array_equal(terminal_labels(np.array([1, -1, 1, 2])), [1, 1, 1, 1])
    with pytest.raises(ValueError, match="cycle"):
        terminal_labels(np.array([1, 0]))
    with pytest.raises(ValueError, match="outside"):
        terminal_labels(np.array([-2]))


def test_long_straight_runs_keep_naturally_straight_valleys() -> None:
    from benchmarks.evolution.metrics import longest_straight_run

    flow = np.full((5, 5), -1, dtype=np.int64)
    flow[2, :4] = np.array([11, 12, 13, 14])
    selected = flow >= 0
    assert longest_straight_run(flow, selected, 100.) == 400.
    flow[2, 2] = 18
    assert longest_straight_run(flow, selected, 100.) == 200.
