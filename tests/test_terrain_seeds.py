# pyright: reportPrivateUsage=false
"""Portable seed vectors and current generation/settings boundaries."""

import tkinter as tk
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pytest
from numpy.typing import NDArray

from benchmarks.terrain import fixture
from map_maker.terrain.domain import TerrainSettings
from map_maker.terrain.domain.seeds import RELIEF_STAGE_ID, stage_seed
from map_maker.terrain.pipeline import generate as generation
from map_maker.terrain.pipeline.generate import generate_terrain
from map_maker.terrain.ui import _CONTROLS, TerrainApp


# Independently calculated using .NET SHA256, ASCII and big-endian UInt32.
@pytest.mark.parametrize(
    ("master", "stage", "expected"),
    [
        (0, "terrain.relief", 1845932015),
        (0, "test.rainfall", 1509020038),
        (42, "terrain.relief", 2355644248),
        (42, "test.rainfall", 3354607557),
        (20260902, "terrain.relief", 3486507418),
        (20260902, "test.rainfall", 3681552239),
        (4294967295, "terrain.relief", 380401938),
        (4294967295, "test.rainfall", 377551747),
    ],
)
def test_portable_seed_vectors(master: int, stage: str, expected: int) -> None:
    assert stage_seed(master, stage) == expected


def test_unrelated_stage_insertion_and_order_do_not_change_existing_streams() -> None:
    before = {
        name: stage_seed(42, name) for name in (RELIEF_STAGE_ID, "test.rainfall")
    }
    after = {
        name: stage_seed(42, name)
        for name in ("test.rainfall", "test.new-stage", RELIEF_STAGE_ID)
    }
    assert before == {name: after[name] for name in before}
    assert before[RELIEF_STAGE_ID] != before["test.rainfall"]


@pytest.mark.parametrize("seed", [-1, 4294967296, True, 1.5, "42"])
def test_invalid_master_seed_is_rejected_at_domain_boundary(seed: object) -> None:
    with pytest.raises(ValueError, match="Seed must be an integer"):
        TerrainSettings(seed=cast("int", seed))
    with pytest.raises(ValueError, match="Seed must be an integer"):
        stage_seed(cast("int", seed), RELIEF_STAGE_ID)


@pytest.mark.parametrize("name", ["", "Terrain.relief", "a\x00b", "a/b", "é", "a" * 129])
def test_invalid_stage_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="Stage identifier"):
        stage_seed(42, name)


def test_generation_uses_derived_seed_for_macro_and_full_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = generation.fractal_value_noise
    seeds: set[int] = set()
    levels: set[int] = set()

    def inspect_noise(*args: Any, **kwargs: Any) -> NDArray[np.float64]:
        seeds.add(kwargs["seed"])
        levels.add(kwargs["detail_levels"])
        return original(*args, **kwargs)

    monkeypatch.setattr(generation, "fractal_value_noise", inspect_noise)
    coast, settings, constraints = fixture("authored", 65, 42)
    terrain = generate_terrain(coast, settings, constraints=constraints)
    assert seeds == {2355644248}
    assert levels == {2, settings.detail_levels}
    assert np.isfinite(terrain.elevation_m[terrain.land_mask]).all()


def test_named_policy_preserves_nested_samples_and_determinism() -> None:
    coast, settings, constraints = fixture("square", 65, 42)
    coarse = generate_terrain(coast, settings, constraints=constraints)
    fine = generate_terrain(coast, replace(settings, resolution_px=129), constraints=constraints)
    repeated = generate_terrain(coast, settings, constraints=constraints)
    np.testing.assert_array_equal(coarse.elevation_m, fine.elevation_m[::2, ::2])
    assert coarse.elevation_m.tobytes() == repeated.elevation_m.tobytes()
    assert coarse.drainage.summary == fine.drainage.summary == repeated.drainage.summary


def test_workbench_settings_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tcl variables exercise settings persistence without needing a display.
    interpreter = tk.Tcl()
    app = TerrainApp.__new__(TerrainApp)
    app._coastline_source = None
    app._variables = {spec.key: tk.DoubleVar(interpreter, value=spec.default) for spec in _CONTROLS}
    def refresh_value(key: str) -> None:
        pass

    monkeypatch.setattr(app, "_refresh_value", refresh_value)
    expected = TerrainSettings(seed=42, resolution_px=129)
    app._apply_settings(expected)
    assert app._read_settings() == expected
