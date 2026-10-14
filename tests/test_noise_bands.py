"""Added detail must retain the coefficients of every existing noise band."""

from dataclasses import replace
from math import fsum
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import box

from map_maker.terrain.domain import LandformKind, TerrainRegion, TerrainSettings, landform_preset
from map_maker.terrain.pipeline import noise
from map_maker.terrain.pipeline.generate import (
    _base_elevation_fields,  # pyright: ignore[reportPrivateUsage]
)
from map_maker.terrain.pipeline.landforms import prepare_regions


@pytest.mark.parametrize("roughness", [.01, .25, .55, .9, np.nextafter(1., 0.)])
def test_amplitudes_keep_exact_prefix_and_reserve_the_uncomputed_tail(roughness: float) -> None:
    complete = noise.noise_band_amplitudes(12, roughness)
    for levels in range(1, 13):
        prefix = noise.noise_band_amplitudes(levels, roughness)
        assert prefix == complete[:levels]
        assert all(value > 0 for value in prefix)
        assert fsum(prefix) <= 1. + 2e-16
        assert fsum(prefix) == pytest.approx(1 - roughness**levels, abs=2e-16)


@pytest.mark.parametrize("roughness", [.25, .55, .9])
def test_runtime_isolated_band_amplitude_never_depends_on_selected_detail(
    roughness: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = 0
    def lattice(x: NDArray[np.int64], y: NDArray[np.int64], *,
                seed: int, octave: int) -> NDArray[np.float64]:
        return np.full(x.shape, float(octave == selected))
    monkeypatch.setattr(noise, "_lattice_values", lattice)
    x = np.asarray((-.217, 0., .392, 10.75))
    amplitudes = noise.noise_band_amplitudes(12, roughness)
    for selected in range(12):
        for levels in (selected + 1, 12):
            result = noise.fractal_value_noise(x, x[::-1], seed=42, largest_feature_km=3.,
                                               detail_levels=levels, roughness=roughness)
            np.testing.assert_array_equal(result, np.full_like(x, amplitudes[selected]))


def test_real_band_tail_is_additive_and_has_a_finite_amplitude_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = np.random.default_rng(7851)
    x, y = rng.uniform(-4000., 4000., (2, 1024))
    coarse = noise.fractal_value_noise(x, y, seed=42, detail_levels=2,
                                       largest_feature_km=450., roughness=.55)
    fine = noise.fractal_value_noise(x, y, seed=42, detail_levels=12,
                                     largest_feature_km=450., roughness=.55)
    selected_tail = noise.fractal_value_noise(x, y, seed=42, detail_levels=12,
                                              start_band=2, largest_feature_km=450., roughness=.55)
    original = noise._lattice_values  # pyright: ignore[reportPrivateUsage]
    def tail_lattice(x: NDArray[np.int64], y: NDArray[np.int64], *,
                     seed: int, octave: int) -> NDArray[np.float64]:
        return (original(x, y, seed=seed, octave=octave) if octave >= 2
                else np.zeros(x.shape, dtype=np.float64))
    monkeypatch.setattr(noise, "_lattice_values", tail_lattice)
    tail = noise.fractal_value_noise(x, y, seed=42, detail_levels=12,
                                     largest_feature_km=450., roughness=.55)
    np.testing.assert_array_equal(tail, selected_tail)
    # Regrouping twelve additions changes binary64 rounding, not band weights.
    np.testing.assert_allclose(fine, coarse + tail, rtol=0,
                               atol=12 * np.finfo(np.float64).eps)
    assert np.max(np.abs(tail)) <= fsum(noise.noise_band_amplitudes(12, .55)[2:]) + 2e-16
    assert np.max(np.abs(fine)) <= 1.


@pytest.mark.parametrize("levels", [0, -1, 13, True, 2.0])
def test_band_budget_rejects_unsupported_counts(levels: object) -> None:
    with pytest.raises(ValueError, match="detail levels"):
        noise.noise_band_amplitudes(cast(int, levels), .55)


@pytest.mark.parametrize("roughness", [0., 1., -1., float("nan"), float("inf"), True])
def test_band_budget_rejects_invalid_roughness(roughness: float) -> None:
    with pytest.raises(ValueError, match="roughness"):
        noise.noise_band_amplitudes(6, roughness)


@pytest.mark.parametrize("kind", [None, "plain", "hills", "plateau", "mountains"])
def test_finer_bands_keep_the_base_macro_field_fixed(kind: LandformKind | None) -> None:
    settings = TerrainSettings(seed=42, object_scale_km=1000., maximum_elevation_m=6000.,
                               detail_levels=2)
    ring = ((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.))
    authored = () if kind is None else (TerrainRegion(ring, landform_preset(kind)),)
    regions = prepare_regions(authored, 1000., 1000., box(0, 0, 1000, 1000), 6000.)
    x, y = np.meshgrid(np.linspace(150., 850., 19), np.linspace(150., 850., 17))
    distance = np.full_like(x, 500.)
    coarse, macro, _ = _base_elevation_fields(x, y, distance, settings, regions)
    np.testing.assert_array_equal(coarse, macro)
    for levels in (6, 12):
        fine, fine_macro, _ = _base_elevation_fields(
            x, y, distance, replace(settings, detail_levels=levels), regions)
        np.testing.assert_array_equal(macro, fine_macro)
        assert np.isfinite(fine).all() and np.max(np.abs(fine - coarse)) > .01


@pytest.mark.parametrize("start", [-1, 7, True, 1.5])
def test_band_selection_rejects_invalid_start(start: object) -> None:
    with pytest.raises(ValueError, match="start band"):
        noise.fractal_value_noise(np.zeros(1), np.zeros(1), seed=42, largest_feature_km=1.,
                                   detail_levels=6, roughness=.55, start_band=cast(int, start))


def test_empty_band_tail_is_zero() -> None:
    x = np.asarray((0., .5, 1.))
    values = noise.fractal_value_noise(x, x, seed=42, largest_feature_km=1.,
                                       detail_levels=2, roughness=.55, start_band=2)
    np.testing.assert_array_equal(values, np.zeros_like(x))
