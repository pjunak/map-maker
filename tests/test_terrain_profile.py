import numpy as np
import pytest

from map_maker.terrain.pipeline.profile import shape_preserving_profile


def test_shape_preserving_profile_interpolates_without_interval_overshoot() -> None:
    positions = np.array([0.0, 100.0, 250.0, 400.0], dtype=np.float64)
    elevations = np.array([2_000.0, 3_400.0, 2_400.0, 3_200.0], dtype=np.float64)
    queries = np.linspace(0.0, 400.0, 401, dtype=np.float64)

    profile = shape_preserving_profile(positions, elevations, queries)

    assert profile[0] == pytest.approx(2_000.0)
    assert profile[100] == pytest.approx(3_400.0)
    assert profile[250] == pytest.approx(2_400.0)
    assert profile[400] == pytest.approx(3_200.0)
    assert np.min(profile[:101]) >= 2_000.0
    assert np.max(profile[:101]) <= 3_400.0
    assert np.min(profile[100:251]) >= 2_400.0
    assert np.max(profile[100:251]) <= 3_400.0
    assert np.min(profile[250:]) >= 2_400.0
    assert np.max(profile[250:]) <= 3_200.0


def test_shape_preserving_profile_requires_increasing_positions() -> None:
    with pytest.raises(ValueError, match="must increase"):
        shape_preserving_profile(
            np.array([0.0, 100.0, 100.0], dtype=np.float64),
            np.array([2_000.0, 2_500.0, 3_000.0], dtype=np.float64),
            np.array([50.0], dtype=np.float64),
        )
