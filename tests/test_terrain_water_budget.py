"""Budget forecasts share real demand, preserve inputs, and never claim clearance."""

import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import box

from benchmarks.terrain import fixture
from map_maker.cli import main
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.adapters.project import load_terrain_project, save_terrain_project
from map_maker.terrain.application import water_budget as application
from map_maker.terrain.domain import TerrainBasin
from map_maker.terrain.pipeline import generate
from map_maker.terrain.pipeline.water import MetricBasin
from map_maker.terrain.pipeline.water_budget import WaterSamplingBudget, plan_water_sampling_budget
from map_maker.terrain.pipeline.water_sampling import SamplingDensity, SamplingGuide

EXAMPLES = Path(__file__).parents[1] / "examples" / "terrain"


@pytest.mark.parametrize("case,details", [
    ("flat", 5), ("flat", 6), ("outlet", 6), ("internal", 6), ("water", 6),
])
def test_forecast_matches_executed_profiles_and_marks_conditional_networks(
    case: str, details: int,
) -> None:
    coast, settings, constraints = fixture(case, 64, 42)
    settings = replace(settings, detail_levels=details)
    budget = generate.forecast_water_sampling(coast, settings, constraints=constraints)
    terrain = generate.generate_terrain(coast, settings, constraints=constraints)
    review = terrain.water.review
    assert (budget.grid_width, budget.grid_height) == (review.grid_width, review.grid_height)
    assert budget.sampling_algorithm_id == review.sampling_algorithm_id
    for planned, actual in zip(budget.basins, review.basins, strict=True):
        assert planned.intent_id == actual.intent_id
        assert planned.footprint_cell_count == actual.footprint_cell_count
        assert planned.wet_cell_count == actual.wet_cell_count
        if actual.shoreline is not None:
            assert planned.shoreline is not None
            profile = actual.shoreline.profile
            assert planned.shoreline.requested_sample_count == profile.requested_sample_count
            assert planned.shoreline.count_is_exact == (profile.status == "sampled")
        else:
            assert planned.shoreline is None
        for network, links in ((planned.wet_links, actual.wet_links),
                               (planned.dry_links, actual.dry_links)):
            if links is not None:
                assert network is not None
                assert network.requested_sample_count == links.requested_sample_count
                assert network.candidate_profile_count == links.candidate_link_count
                assert network.count_is_exact == (links.status == "sampled")
        assert (planned.wet_links is not None) == (actual.source.outlet is not None)
        assert (planned.dry_links is not None) == (actual.source.outlet is not None)
    if case == "flat":
        dry = next(b.dry_links for b in budget.basins if b.dry_links is not None)
        assert dry.requested_sample_count == (199_188 if details == 5 else 262_150)
        assert dry.count_is_exact == (details == 5)
        assert dry.limiting_budget == (None if details == 5 else "network")
        if details == 6:
            assert dry.visited_profile_count < dry.candidate_profile_count
    elif case == "internal":
        # A real internal barrier blocks dry collection even though its potential
        # demand can be planned without testing water connectivity.
        assert any(b.dry_links is None and p.dry_links is not None
                   for p, b in zip(budget.basins, review.basins, strict=True))


def test_forecast_uses_only_canonical_finished_ground_and_is_resolution_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coast, settings, constraints = fixture("flat", 64, 42)
    expected = generate.forecast_water_sampling(coast, settings, constraints=constraints)
    original = generate.PreparedTerrainField.evaluate
    shapes: list[tuple[int, ...]] = []
    def observed(
        self: generate.PreparedTerrainField,
        x: NDArray[np.float64], y: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
        shapes.append(x.shape)
        return original(self, x, y)
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Forecast must not evaluate fine profiles or generate delivered products.")
    monkeypatch.setattr(generate.PreparedTerrainField, "evaluate", observed)
    for name in ("resolve_basin_outflow", "review_drainage_routing", "water_products"):
        monkeypatch.setattr(generate, name, unexpected)
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.profile_positions", unexpected)
    actual = generate.forecast_water_sampling(
        coast, replace(settings, resolution_px=4096), constraints=tuple(reversed(constraints)))
    assert actual == expected
    assert shapes == [(expected.grid_height, expected.grid_width)]


@pytest.mark.parametrize("failure", ["network", "profile", "detail"])
def test_budget_failure_counts_without_allocating_any_profile_stations(
    failure: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TerrainBasin(((.25, .25), (.75, .25), (.75, .75), (.25, .75), (.25, .25)),
                          "lake", 10., (.25, .25))
    basin = MetricBasin(source, box(1., 1., 3., 3.), (1., 1.))
    axis = np.arange(5, dtype=np.float64)
    ground = np.broadcast_to(axis + 8., (5, 5)).copy()
    before = ground.copy()
    features: tuple[SamplingGuide, ...] = ()
    if failure == "profile":
        monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.MAX_PROFILE_SAMPLES", 4)
    else:
        limit = 1 if failure == "network" else 200
        monkeypatch.setattr("map_maker.terrain.pipeline.wet_links.MAX_WET_LINK_SAMPLES", limit)
        monkeypatch.setattr("map_maker.terrain.pipeline.dry_links.MAX_DRY_LINK_SAMPLES", limit)
        if failure == "detail":
            features = (SamplingDensity(.001),)
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Planning must not allocate sample positions or evaluate ground profiles.")
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.profile_positions", unexpected)
    monkeypatch.setattr(
        "map_maker.terrain.pipeline.water_sampling.sample_ground_positions", unexpected)
    result = plan_water_sampling_budget((basin,), ground, axis, axis, features).basins[0]
    for demand in (result.wet_links, result.dry_links):
        assert demand is not None and not demand.count_is_exact
        assert demand.status == "budget_exceeded"
        assert demand.limiting_budget == ("profile" if failure == "profile" else "network")
        assert demand.requested_sample_count >= demand.baseline_sample_count
        assert demand.visited_profile_count == (0 if failure == "network" else 1)
    np.testing.assert_array_equal(ground, before)


def test_empty_closed_dry_and_subgrid_footprints_have_explicit_scope() -> None:
    axis = np.arange(5, dtype=np.float64)
    ground = np.full((5, 5), 2., dtype=np.float64)
    assert plan_water_sampling_budget((), ground, axis, axis).basins == ()
    ring = ((.25, .25), (.75, .25), (.75, .75), (.25, .75), (.25, .25))
    for source in (TerrainBasin(ring, "lake", 10.), TerrainBasin(ring, "dry_basin")):
        basin = MetricBasin(source, box(1., 1., 3., 3.), None)
        result = plan_water_sampling_budget((basin,), ground, axis, axis).basins[0]
        assert result.wet_links is result.dry_links is None
        assert (result.shoreline is None) == (source.kind == "dry_basin")
    tiny = MetricBasin(TerrainBasin(ring, "lake", 10., (.25, .25)),
                       box(1.1, 1.1, 1.2, 1.2), (1.1, 1.1))
    result = plan_water_sampling_budget((tiny,), ground, axis, axis).basins[0]
    assert result.footprint_cell_count == result.wet_cell_count == 0
    for demand in (result.wet_links, result.dry_links):
        assert demand is not None and demand.count_is_exact
        assert demand.requested_sample_count == demand.candidate_profile_count == 0


@pytest.fixture
def saved_project(tmp_path: Path) -> Path:
    for name in ("coastline.svg", "flat-outlet.terrain.json"):
        shutil.copyfile(EXAMPLES / name, tmp_path / name)
    return tmp_path / "flat-outlet.terrain.json"


def test_cli_forecast_reports_excess_without_writing_inputs_or_builds(
    saved_project: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    loaded = load_terrain_project(saved_project)
    project = replace(loaded.project, settings=replace(loaded.project.settings, detail_levels=6))
    save_terrain_project(project, loaded.coastline_source, saved_project)
    before = {p.name: file_sha256(p) for p in saved_project.parent.iterdir()}
    assert main(["terrain", "water-budget", str(saved_project)]) == 0
    output = capsys.readouterr()
    assert not output.err
    for text in ("at least 262,150", "EXCEEDS network budget", "Potential dry network",
                 "65,536/wet network", "262,144/dry network", "not evaluated",
                 f"Project SHA-256: {file_sha256(saved_project)}", "Generator source SHA-256"):
        assert text in output.out
    assert {p.name: file_sha256(p) for p in saved_project.parent.iterdir()} == before


@pytest.mark.parametrize("changed", ["project", "coastline", "runtime"])
def test_forecast_rejects_inputs_changed_during_planning(
    changed: str, saved_project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = {"package_source_sha256": "before"}
    monkeypatch.setattr(application, "runtime_identity", lambda: dict(runtime))
    def forecast(*args: object, **kwargs: object) -> WaterSamplingBudget:
        if changed == "runtime":
            runtime["package_source_sha256"] = "after"
        else:
            path = (saved_project if changed == "project" else
                    saved_project.with_name("coastline.svg"))
            path.write_bytes(path.read_bytes() + b"\n")
        return WaterSamplingBudget("test", 5, 5, 65_536, 65_536, 262_144, ())
    monkeypatch.setattr(application, "forecast_water_sampling", forecast)
    with pytest.raises(ValueError, match="changed during the forecast"):
        application.forecast_project_water_budget(saved_project)


def test_forecast_checks_saved_coastline_identity_before_planning(
    saved_project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coast = saved_project.with_name("coastline.svg")
    coast.write_bytes(coast.read_bytes() + b"\n")
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Changed source must be rejected before expensive planning.")
    monkeypatch.setattr(application, "forecast_water_sampling", unexpected)
    with pytest.raises(ValueError, match=r"changed|hash|SHA"):
        application.forecast_project_water_budget(saved_project)


def test_cli_forecast_help_and_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as info:
        main(["terrain", "water-budget", "--help"])
    assert info.value.code == 0
    assert "without raster export" in capsys.readouterr().out
    assert main(["terrain", "water-budget", str(tmp_path / "missing.json")]) == 1
    output = capsys.readouterr()
    assert not output.out and "forecast failed" in output.err
