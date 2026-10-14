"""Cooperative stops keep numeric results and durable completion boundaries intact."""

from dataclasses import replace
from importlib import import_module
from pathlib import Path

import numpy as np
import pytest

from benchmarks.terrain import fixture
from map_maker.terrain.application import build as build_application
from map_maker.terrain.application import regional as regional_application
from map_maker.terrain.pipeline.control import (
    CancellationToken,
    GenerationCancelled,
    cancellable_progress,
)
from map_maker.terrain.pipeline.generate import generate_terrain

generation = import_module("map_maker.terrain.pipeline.generate")


def test_progress_checks_both_sides_of_callback_and_cancelled_tokens_stay_cancelled() -> None:
    token = CancellationToken()
    seen: list[str] = []

    def stop(_fraction: float, message: str) -> None:
        seen.append(message)
        token.cancel()

    report = cancellable_progress(stop, token)
    assert report is not None
    with pytest.raises(GenerationCancelled):
        report(0.5, "request stop")
    with pytest.raises(GenerationCancelled):
        report(1.0, "must not report completion")
    token.cancel()
    with pytest.raises(GenerationCancelled):
        token.checkpoint()
    assert seen == ["request stop"]
    assert not CancellationToken().is_cancelled


def test_cancelled_generation_rejects_before_preparing_a_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = CancellationToken()
    token.cancel()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("An already cancelled request must not prepare terrain.")

    monkeypatch.setattr(generation, "prepare_terrain_field", forbidden)
    coast, settings, _ = fixture("square", 65, 42)
    with pytest.raises(GenerationCancelled):
        generate_terrain(coast, settings, cancellation=token)


@pytest.mark.parametrize("stage", [
    "Preparing authored valley profiles", "Routing canonical drainage",
    "Preparing channel floor profiles", "Building elevation field",
    "Reviewing basin water and outlets", "Terrain ready",
])
def test_generation_can_stop_at_stage_callbacks(stage: str) -> None:
    token = CancellationToken()
    seen: list[str] = []
    coast, settings, constraints = fixture("square", 65, 42)

    def progress(_fraction: float, label: str) -> None:
        seen.append(label)
        if label == stage:
            token.cancel()

    with pytest.raises(GenerationCancelled):
        generate_terrain(coast, settings, progress, constraints=constraints, cancellation=token)
    assert seen[-1] == stage


@pytest.mark.parametrize("case", ["regional", "water"])
def test_uncancelled_token_preserves_all_delivered_arrays(case: str) -> None:
    coast, settings, constraints = fixture(case, 65, 42)
    settings = replace(settings, detail_levels=2)
    control = generate_terrain(coast, settings, constraints=constraints)
    actual = generate_terrain(coast, settings, constraints=constraints,
                              cancellation=CancellationToken())
    for before, after in (
        (control.elevation_m, actual.elevation_m), (control.land_mask, actual.land_mask),
        (control.water.surface_m, actual.water.surface_m),
        (control.routing.receivers, actual.routing.receivers),
        (control.routing_final_elevation_m, actual.routing_final_elevation_m),
    ):
        np.testing.assert_array_equal(before.view(np.uint8), after.view(np.uint8))


@pytest.mark.parametrize("regional", [False, True])
def test_precancelled_file_operations_do_not_load_or_create_output(
    tmp_path: Path, regional: bool,
) -> None:
    token = CancellationToken()
    token.cancel()
    output = tmp_path / "cancelled"
    with pytest.raises(GenerationCancelled):
        if regional:
            regional_application.sample_terrain_region(
                tmp_path / "missing.json", output, (0., 0., 100., 100.), 2,
                cancellation=token,
            )
        else:
            build_application.build_terrain_project(
                tmp_path / "missing.json", output, cancellation=token,
            )
    assert not output.exists()
