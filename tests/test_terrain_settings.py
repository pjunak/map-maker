"""Invalid direct Python inputs fail before reaching numeric generation."""

from dataclasses import replace

import pytest

from map_maker.terrain.domain import TerrainSettings


@pytest.mark.parametrize("field", ["object_scale_km", "maximum_elevation_m",
                                   "largest_feature_km", "coastal_rise_km",
                                   "roughness", "variability"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_settings_reject_nonfinite_values(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        replace(TerrainSettings(), **{field: value})


@pytest.mark.parametrize("field", ["resolution_px", "detail_levels"])
@pytest.mark.parametrize("value", [True, 65.5, 2.5, float("nan"), float("inf")])
def test_settings_require_integer_sample_and_octave_counts(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        replace(TerrainSettings(), **{field: value})
