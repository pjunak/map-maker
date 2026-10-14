"""Run explicitly in the isolated reference environment; optional in the base suite."""

from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from benchmarks.evolution.metrics import measure
from benchmarks.evolution.reference import EvolutionBudgetExceeded, LandlabReference, evolve
from benchmarks.evolution.scenarios import EvolutionFields, scenario
from map_maker.terrain.domain.evolution import (
    EvolutionBudget,
    EvolutionEpoch,
    EvolutionGrid,
    EvolutionHistory,
)

pytest.importorskip("landlab", reason="Isolated scientific reference environment required")


def flat_fields(height: float = 10.) -> EvolutionFields:
    grid = EvolutionGrid(400., 400., 100.)
    ones = np.ones(grid.shape)
    return EvolutionFields(grid, height * ones, ones, ones, ones)


def test_no_forcing_and_exact_uplift_with_epoch_boundaries() -> None:
    fields = flat_fields()
    history = EvolutionHistory((EvolutionEpoch("first", 100., .2, 0., 0., 0.),
                                EvolutionEpoch("second", 50., .1, 0., 0., 0.)))
    result = evolve(fields, history, EvolutionBudget(maximum_step_years=40.))
    assert [s.time_years for s in result.snapshots] == [0., 100., 150.]
    expected = fields.initial_m.copy()
    expected[fields.core] += 25.
    np.testing.assert_array_equal(result.snapshots[-1].elevation_m, expected)
    assert result.balance_residual_m3 == pytest.approx(0., abs=1.e-8)
    assert np.all(fields.initial_m == 10.)
    assert not result.snapshots[-1].elevation_m.flags.writeable
    quiet = EvolutionHistory((EvolutionEpoch("quiet", 150., 0., 0., 0., 0.),))
    unchanged = evolve(fields, quiet, EvolutionBudget(maximum_step_years=40.))
    np.testing.assert_array_equal(unchanged.snapshots[-1].elevation_m, fields.initial_m)


@pytest.mark.parametrize("runoff", [1., 2.])
def test_one_link_implicit_incision_and_discharge_units(runoff: float) -> None:
    fields = flat_fields(0.)
    z = fields.initial_m.copy()
    z[1, 1] = 100.
    fields = replace(fields, initial_m=z)
    epoch = EvolutionEpoch("incision", 100., 0., runoff, 1., 0.)
    history = EvolutionHistory((epoch,), reference_discharge_m3_per_year=10_000.)
    engine = LandlabReference(fields, history)
    engine.set_epoch(epoch)
    change = engine.step(epoch, 100., lambda: None)
    # This isolated core node has one 10,000 m2 control area and a 100 m link.
    assert engine.grid.at_node["surface_water__discharge"][6] == 10_000. * runoff
    assert engine.z[6] == pytest.approx(100. / (1. + np.sqrt(runoff)))
    assert change.incision_m[6] == pytest.approx(100. - engine.z[6])
    assert change.boundary_export_m3 == 0.


def test_zero_runoff_disables_even_zero_exponent_incision() -> None:
    fields = scenario(EvolutionGrid(spacing_m=5000.), 42)
    epoch = EvolutionEpoch("dry", 100., 0., 0., 1., 0.)
    h = EvolutionHistory((epoch,), discharge_exponent=0.)
    result = evolve(fields, h, EvolutionBudget())
    np.testing.assert_array_equal(result.snapshots[-1].elevation_m, fields.initial_m)
    assert not np.any(result.incision_m)


def test_diffusion_boundary_flux_closes_volume_ledger() -> None:
    fields = flat_fields(0.)
    z = fields.initial_m.copy()
    z[1:-1, 1:-1] = 100.
    fields = replace(fields, initial_m=z)
    epoch = EvolutionEpoch("diffuse", 10_000., 0., 0., 0., 1.)
    engine = LandlabReference(fields, EvolutionHistory((epoch,)))
    engine.set_epoch(epoch)
    before = float(np.dot(engine.z, engine.area))
    change = engine.step(epoch, 10_000., lambda: None)
    after = float(np.dot(engine.z, engine.area))
    assert change.boundary_export_m3 > 0.
    assert before - after == pytest.approx(change.boundary_export_m3, rel=1.e-12)
    assert not np.any(change.incision_m)


def test_pit_routing_preserves_ground_and_exports_all_runoff() -> None:
    fields = flat_fields(0.)
    z = fields.initial_m.copy()
    z[1:-1, 1:-1] = 100.
    z[2, 2] = 10.
    fields = replace(fields, initial_m=z)
    epoch = EvolutionEpoch("wet", 10., 0., .4, .1, 0.)
    engine = LandlabReference(fields, EvolutionHistory((epoch,)))
    engine.set_epoch(epoch)
    engine.route()
    s = engine.snapshot("pit", 0.)
    np.testing.assert_array_equal(s.elevation_m, fields.initial_m)
    assert s.depression_depth_m[2, 2] == 90.
    m = measure(s, fields, channel_area_km2=.01)
    assert m["area_reaching_perimeter_fraction"] == 1.
    assert m["outlet_discharge_m3_per_year"] == pytest.approx(.4*fields.grid.contributing_area_m2)
    engine.step(epoch, 10., lambda: None)
    assert engine.z.reshape(fields.grid.shape)[2, 2] == 10.


def test_rejected_trials_are_rolled_back_and_reproducible() -> None:
    fields = flat_fields(0.)
    z = fields.initial_m.copy()
    z[1, 1] = 100.
    fields = replace(fields, initial_m=z)
    epoch = EvolutionEpoch("incision", 100., .01, 1., 1., 0.)
    h = EvolutionHistory((epoch,), reference_discharge_m3_per_year=10_000.)
    budget = EvolutionBudget(maximum_step_years=100., step_error_m=.1)
    first = evolve(fields, h, budget)
    second = evolve(fields, h, budget)
    assert first.rejected_trials > 0
    assert max(float(s["step_error_m"]) for s in first.steps) <= .1
    np.testing.assert_array_equal(first.snapshots[-1].elevation_m, second.snapshots[-1].elevation_m)
    np.testing.assert_allclose(first.uplift_m[fields.core], 1., atol=1.e-12)
    assert abs(first.balance_residual_m3) < .0001
    with pytest.raises(EvolutionBudgetExceeded, match="step/trial"):
        evolve(fields, h, replace(budget, maximum_steps=1, maximum_trials=1))
    with pytest.raises(EvolutionBudgetExceeded, match="wall-time"):
        evolve(fields, h, replace(budget, maximum_seconds=1.e-9))


def test_smaller_steps_converge_towards_single_link_exact_solution() -> None:
    fields = flat_fields(0.)
    z = fields.initial_m.copy()
    z[1, 1] = 100.
    fields = replace(fields, initial_m=z)
    epoch = EvolutionEpoch("incision", 100., 0., 1., 1., 0.)
    history = EvolutionHistory((epoch,), reference_discharge_m3_per_year=10_000.)
    errors: list[float] = []
    for dt in (100., 50., 25., 12.5):
        engine = LandlabReference(fields, history)
        engine.set_epoch(epoch)
        for _ in range(round(100./dt)):
            engine.step(epoch, dt, lambda: None)
        errors.append(abs(float(engine.z[6]) - 100.*np.exp(-1.)))
    assert all(b < a for a, b in pairwise(errors))
    assert errors[-1] < .2*errors[0]


def test_steady_profile_and_moving_knickpoint_refine() -> None:
    from benchmarks.evolution.controls import controls

    result = controls()
    assert result["steady_slope_mean_error_m"] < 1.e-10
    for name in ("knickpoint_spatial_refinement", "knickpoint_temporal_refinement"):
        errors = [row["mean_absolute_error_m"] for row in result[name]]
        assert all(b < a for a, b in pairwise(errors))


def test_spatial_runoff_accumulates_in_float64_at_physical_scale() -> None:
    fields = scenario(EvolutionGrid(spacing_m=1250.), 42)
    weights = 1. + np.linspace(0., .37, fields.grid.shape[1])[None, :]
    fields = replace(fields, runoff_weight=np.broadcast_to(weights, fields.grid.shape))
    epoch = EvolutionEpoch("wet", 1., 0., .4, 0., 0.)
    engine = LandlabReference(fields, EvolutionHistory((epoch,)))
    engine.set_epoch(epoch)
    engine.route()
    snapshot = engine.snapshot("routed", 0.)
    expected = .4 * fields.grid.spacing_m**2 * np.sum(fields.runoff_weight[fields.core])
    actual = np.sum(snapshot.discharge_m3_per_year[snapshot.receiver < 0])
    assert actual == pytest.approx(float(expected), rel=1.e-14)


def test_failed_command_never_publishes_completion_or_overwrites(tmp_path: Path) -> None:
    from argparse import Namespace

    from benchmarks.evolution.__main__ import run

    output = tmp_path / "exhausted"
    args = Namespace(output=output, spacing_m=[5000.], seeds=[42], cases=["two-epoch"],
                     angle_deg=25., extent_scale=1., maximum_seconds=1.e-9,
                     maximum_step_years=25000., step_error_m=.5)
    assert run(args) == 1
    assert (output / "incomplete.json").exists()
    assert not (output / "comparison.json").exists()
    assert not list(output.glob("*/result.json"))
    assert len(list(output.glob("*/failure.json"))) == 1
    with pytest.raises(FileExistsError):
        run(args)


def test_steady_slope_area_channel_is_preserved() -> None:
    from importlib import import_module

    package = import_module("landlab")
    components = import_module("landlab.components")
    grid = package.RasterModelGrid((3, 31), xy_spacing=100.)
    grid.set_closed_boundaries_at_grid_edges(True, True, False, True)
    x = np.asarray(grid.x_of_node, dtype=np.float64)
    z = grid.add_field("topographic__elevation", x.copy(), at="node")
    router = components.FlowAccumulator(grid, flow_director="D8", runoff_rate=.4)
    router.run_one_step()
    receiver = np.asarray(grid.at_node["flow__receiver_node"], dtype=np.int64)
    q = np.asarray(grid.at_node["surface_water__discharge"], dtype=np.float64)
    core = np.asarray(grid.status_at_node) == 0
    for node in np.asarray(grid.at_node["flow__upstream_node_order"], dtype=np.int64):
        if core[node]:
            z[node] = z[receiver[node]] + .01*100. / (.001*(q[node]/1.e6)**.5)
    original = np.asarray(z, dtype=np.float64).copy()
    z[core] += .01*1000.
    router.run_one_step()
    eroder = components.FastscapeEroder(grid, K_sp=.001/1000., m_sp=.5, n_sp=1.,
                                       discharge_field="surface_water__discharge")
    eroder.run_one_step(1000.)
    np.testing.assert_allclose(np.asarray(z, dtype=np.float64)[core], original[core],
                               rtol=1.e-13, atol=1.e-10)
