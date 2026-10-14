from dataclasses import asdict

import numpy as np
import pytest

from map_maker.terrain.pipeline.quality import measure_terrain_quality


def test_directional_measurements_distinguish_equal_histograms_and_rotation() -> None:
    ramp = np.tile(np.arange(17, dtype=np.float64) * 10.0, (17, 1))
    shuffled = np.random.default_rng(42).permutation(ramp.ravel()).reshape(ramp.shape)
    reports = [
        measure_terrain_quality(
            field,
            np.ones_like(field, dtype=np.bool_),
            x_spacing_km=1.0,
            y_spacing_km=1.0,
            distances_km=(4.0,),
        )
        for field in (ramp, ramp.T, shuffled)
    ]
    assert reports[0].mean_m == reports[2].mean_m
    assert reports[0].standard_deviation_m == pytest.approx(reports[2].standard_deviation_m)
    assert reports[0].directional[0].semivariance_m2 == 800.0
    assert reports[0].directional[1].semivariance_m2 == 0.0
    assert reports[1].directional[0].semivariance_m2 == 0.0
    assert reports[1].directional[1].semivariance_m2 == 800.0
    assert reports[2].directional[1].semivariance_m2 != 0.0


def test_masked_gaps_never_bridge_islands_and_values_are_not_mutated() -> None:
    elevations = np.array([[0.0, 10.0, np.nan, 30.0, 40.0]], dtype=np.float32)
    original = elevations.copy()
    mask = np.isfinite(elevations)
    result = measure_terrain_quality(
        elevations, mask, x_spacing_km=1, y_spacing_km=2, distances_km=(1.0, 4.0)
    )
    assert result.directional[0].pair_count == 2
    assert result.directional[0].semivariance_m2 == 50.0
    assert result.directional[1].pair_count == 0
    assert result.directional[1].semivariance_m2 is None
    assert result.directional[2].pair_count == 0
    assert np.array_equal(elevations, original, equal_nan=True)


def test_physical_lags_round_and_report_effective_spacing_per_axis() -> None:
    field = np.zeros((5, 5))
    result = measure_terrain_quality(
        field,
        np.ones_like(field, dtype=np.bool_),
        x_spacing_km=2,
        y_spacing_km=4,
        distances_km=(5.0,),
    )
    assert result.directional[0].lag_intervals == 3
    assert result.directional[0].effective_distance_km == 6.0
    assert result.directional[1].lag_intervals == 1
    assert result.directional[1].effective_distance_km == 4.0
    assert result.directional[0].pair_count == 10
    assert result.directional[1].pair_count == 20
    assert result.directional[0].semivariance_m2 == 0.0
    assert asdict(result)["algorithm_id"] == "masked-axis-semivariance@1"


@pytest.mark.parametrize("spacing", [0.0, -1.0, float("nan"), float("inf")])
def test_quality_rejects_invalid_spacing(spacing: float) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        measure_terrain_quality(
            np.zeros((2, 2)), np.ones((2, 2), dtype=np.bool_), x_spacing_km=spacing, y_spacing_km=1
        )


def test_quality_rejects_nonfinite_land_and_empty_land() -> None:
    for field, mask in (
        (np.full((2, 2), np.nan), np.ones((2, 2), dtype=np.bool_)),
        (np.zeros((2, 2)), np.zeros((2, 2), dtype=np.bool_)),
    ):
        with pytest.raises(ValueError, match="finite elevations on nonempty land"):
            measure_terrain_quality(field, mask, x_spacing_km=1, y_spacing_km=1)
