import json
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Literal

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from map_maker.terrain.adapters import (
    elevation_legend_colours,
    elevation_palette_rgb,
    render_height_map,
    save_height_map,
)
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    LandComponent,
    TerrainBrushStroke,
    TerrainSettings,
    TerrainStructure,
)
from map_maker.terrain.pipeline import generate_terrain
from map_maker.terrain.pipeline.noise import fractal_value_noise


@pytest.fixture
def uniform_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measure authored geometry independently of random relief and flank detail."""
    def zero_noise(
        x: NDArray[np.float64], y: NDArray[np.float64], **settings: object,
    ) -> NDArray[np.float64]:
        return np.zeros(np.broadcast_shapes(x.shape, y.shape), dtype=np.float64)

    monkeypatch.setattr(
        "map_maker.terrain.pipeline.generate.fractal_value_noise", zero_noise,
    )


def _square() -> Coastline:
    return Coastline(
        points=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)),
        source_name="square.svg",
    )


def _mainland_and_island() -> Coastline:
    return Coastline(
        points=(
            (0.0, 0.0),
            (60.0, 0.0),
            (60.0, 100.0),
            (0.0, 100.0),
            (0.0, 0.0),
        ),
        source_name="mainland-and-island.svg",
        additional_components=(
            LandComponent(
                exterior=(
                    (80.0, 40.0),
                    (100.0, 40.0),
                    (100.0, 60.0),
                    (80.0, 60.0),
                    (80.0, 40.0),
                ),
            ),
        ),
    )


def _land_with_inland_water() -> Coastline:
    return Coastline(
        points=(
            (0.0, 0.0),
            (100.0, 0.0),
            (100.0, 100.0),
            (0.0, 100.0),
            (0.0, 0.0),
        ),
        source_name="land-with-inland-water.svg",
        holes=(
            (
                (40.0, 40.0),
                (60.0, 40.0),
                (60.0, 60.0),
                (40.0, 60.0),
                (40.0, 40.0),
            ),
        ),
    )


def _settings(**changes: object) -> TerrainSettings:
    baseline = TerrainSettings(
        seed=42,
        object_scale_km=1_000.0,
        resolution_px=65,
        maximum_elevation_m=3_000.0,
        largest_feature_km=250.0,
        detail_levels=4,
        roughness=0.55,
        coastal_rise_km=80.0,
        variability=0.7,
    )
    return replace(baseline, **changes)


def test_same_inputs_produce_identical_terrain() -> None:
    first = generate_terrain(_square(), _settings())
    second = generate_terrain(_square(), _settings())

    np.testing.assert_array_equal(first.land_mask, second.land_mask)
    np.testing.assert_array_equal(first.elevation_m, second.elevation_m)


def test_seed_changes_inland_elevation() -> None:
    first = generate_terrain(_square(), _settings(seed=1))
    second = generate_terrain(_square(), _settings(seed=2))

    assert np.any(first.elevation_m[first.land_mask] != second.elevation_m[second.land_mask])


def test_nested_resolution_preserves_existing_samples() -> None:
    coarse = generate_terrain(_square(), _settings(resolution_px=65))
    fine = generate_terrain(_square(), _settings(resolution_px=129))

    np.testing.assert_array_equal(coarse.land_mask, fine.land_mask[::2, ::2])
    np.testing.assert_array_equal(coarse.elevation_m, fine.elevation_m[::2, ::2])
    assert coarse.drainage.summary == fine.drainage.summary


def test_generates_mainland_and_island_in_one_shared_grid() -> None:
    terrain = generate_terrain(
        _mainland_and_island(),
        _settings(resolution_px=101),
    )

    assert terrain.land_mask[50, 30]
    assert not terrain.land_mask[50, 70]
    assert terrain.land_mask[50, 90]
    assert terrain.elevation_m[50, 80] == np.float32(0.0)


def test_constraint_on_island_is_accepted_but_cross_ocean_line_is_rejected() -> None:
    island_peak = ElevationPoint((0.9, 0.5), 1_500.0, 30.0)
    terrain = generate_terrain(
        _mainland_and_island(),
        _settings(resolution_px=101),
        constraints=(island_peak,),
    )

    assert terrain.elevation_m[50, 90] == np.float32(1_500.0)

    crossing_ridge = TerrainStructure(
        "ridge",
        ((0.5, 0.5), (0.9, 0.5)),
        1_500.0,
        30.0,
    )
    with pytest.raises(ValueError, match="outside the coastline"):
        generate_terrain(
            _mainland_and_island(),
            _settings(resolution_px=101),
            constraints=(crossing_ridge,),
        )


def test_enclosed_water_is_excluded_and_acts_as_a_coastline() -> None:
    terrain = generate_terrain(
        _land_with_inland_water(),
        _settings(resolution_px=101),
    )

    assert terrain.land_mask[20, 50]
    assert not terrain.land_mask[50, 50]
    assert terrain.land_mask[40, 50]
    assert terrain.elevation_m[40, 50] == np.float32(0.0)


def test_authored_height_point_sets_its_target_elevation() -> None:
    point = ElevationPoint(
        position=(0.5, 0.5),
        elevation_m=750.0,
        influence_radius_km=120.0,
    )

    terrain = generate_terrain(_square(), _settings(), constraints=(point,))

    assert terrain.elevation_m[32, 32] == np.float32(750.0)
    assert terrain.constraints == (point,)


def test_ridges_raise_and_valleys_cut_the_base_surface() -> None:
    baseline = generate_terrain(_square(), _settings())
    ridge = TerrainStructure(
        kind="ridge",
        points=((0.25, 0.5), (0.75, 0.5)),
        elevation_m=3_000.0,
        influence_radius_km=100.0,
    )
    valley = TerrainStructure(
        kind="valley",
        points=((0.5, 0.25), (0.5, 0.75)),
        elevation_m=100.0,
        influence_radius_km=80.0,
    )

    ridged = generate_terrain(_square(), _settings(), constraints=(ridge,))
    valleyed = generate_terrain(_square(), _settings(), constraints=(valley,))

    assert ridged.elevation_m[32, 24] == np.float32(3_000.0)
    assert ridged.elevation_m[32, 24] > baseline.elevation_m[32, 24]
    assert valleyed.elevation_m[24, 32] <= np.float32(100.0)
    assert valleyed.elevation_m[24, 32] < baseline.elevation_m[24, 32]


def test_structure_response_has_a_broad_falloff_beyond_its_core_width() -> None:
    baseline = generate_terrain(_square(), _settings())
    ridge = TerrainStructure(
        kind="ridge",
        points=((0.25, 0.5), (0.75, 0.5)),
        elevation_m=3_000.0,
        influence_radius_km=50.0,
    )

    ridged = generate_terrain(_square(), _settings(), constraints=(ridge,))

    assert ridged.elevation_m[40, 32] > baseline.elevation_m[40, 32]


@pytest.mark.parametrize("kind", ("ridge", "valley"))
@pytest.mark.usefixtures("uniform_noise")
def test_connected_structure_segments_do_not_pinch_at_their_junction(
    kind: Literal["ridge", "valley"],
) -> None:
    settings = _settings(
        maximum_elevation_m=6_000.0,
        variability=0.0,
        coastal_rise_km=1.0,
    )
    whole = TerrainStructure(
        kind,
        ((0.2, 0.5), (0.8, 0.5)),
        800.0,
        80.0,
        "relative",
    )
    west = replace(whole, points=((0.2, 0.5), (0.5, 0.5)))
    east = replace(whole, points=((0.5, 0.5), (0.8, 0.5)))

    continuous = generate_terrain(_square(), settings, constraints=(whole,))
    segmented = generate_terrain(_square(), settings, constraints=(west, east))
    reordered = generate_terrain(_square(), settings, constraints=(east, west))

    # Junction width is an authored-surface invariant. Small differences away
    # from the join can now change drainage, so compare final terrain below.
    np.testing.assert_array_equal(
        segmented.routing.source_elevation_m[:, 128],
        continuous.routing.source_elevation_m[:, 128],
    )
    np.testing.assert_allclose(
        segmented.routing.source_elevation_m,
        continuous.routing.source_elevation_m,
        rtol=0.0,
        atol=3.0,
    )
    np.testing.assert_allclose(segmented.elevation_m[:, 32], continuous.elevation_m[:, 32],
                               rtol=0.0, atol=3.0)
    np.testing.assert_array_equal(segmented.elevation_m, reordered.elevation_m)


def test_authored_ridge_branch_keeps_a_full_width_root() -> None:
    settings = _settings(maximum_elevation_m=6_000.0, variability=0.0)
    main = TerrainStructure(
        "ridge",
        ((0.2, 0.45), (0.8, 0.45)),
        800.0,
        80.0,
        "relative",
    )
    branch = TerrainStructure(
        "ridge",
        ((0.5, 0.45), (0.5, 0.8)),
        800.0,
        80.0,
        "relative",
    )

    baseline = generate_terrain(_square(), settings)
    isolated_branch = generate_terrain(_square(), settings, constraints=(branch,))
    branched = generate_terrain(_square(), settings, constraints=(main, branch))
    reordered = generate_terrain(_square(), settings, constraints=(branch, main))
    root_shoulder = (34, 36)
    isolated_relief = float(
        isolated_branch.elevation_m[root_shoulder]
        - baseline.elevation_m[root_shoulder]
    )
    connected_relief = float(
        branched.elevation_m[root_shoulder] - baseline.elevation_m[root_shoulder]
    )

    assert connected_relief > isolated_relief + 100.0
    np.testing.assert_array_equal(branched.elevation_m, reordered.elevation_m)


def test_authored_features_do_not_raise_the_coastline() -> None:
    ridge = TerrainStructure(
        kind="ridge",
        points=((0.25, 0.05), (0.75, 0.05)),
        elevation_m=3_000.0,
        influence_radius_km=200.0,
    )

    terrain = generate_terrain(_square(), _settings(), constraints=(ridge,))

    assert terrain.land_mask[0, 32]
    assert terrain.elevation_m[0, 32] == np.float32(0.0)


def test_nearby_height_point_bends_structure_profile() -> None:
    ridge = TerrainStructure(
        kind="ridge",
        points=((0.2, 0.5), (0.8, 0.5)),
        elevation_m=2_000.0,
        influence_radius_km=40.0,
    )
    peak = ElevationPoint(
        position=(0.5, 0.5),
        elevation_m=2_800.0,
        influence_radius_km=30.0,
    )

    ridge_only = generate_terrain(_square(), _settings(), constraints=(ridge,))
    anchored = generate_terrain(_square(), _settings(), constraints=(ridge, peak))

    assert anchored.elevation_m[32, 36] > ridge_only.elevation_m[32, 36]
    assert anchored.elevation_m[32, 32] == np.float32(2_800.0)


@pytest.mark.usefixtures("uniform_noise")
def test_peak_and_pass_anchors_form_a_shape_preserving_ridge_profile() -> None:
    ridge = TerrainStructure(
        kind="ridge",
        points=((0.125, 0.5), (0.875, 0.5)),
        elevation_m=2_200.0,
        influence_radius_km=55.0,
    )
    west_peak = ElevationPoint((0.25, 0.5), 3_400.0, 35.0)
    mountain_pass = ElevationPoint((0.5, 0.5), 2_400.0, 35.0)
    east_peak = ElevationPoint((0.75, 0.5), 3_200.0, 35.0)

    settings = _settings(maximum_elevation_m=5_000.0, variability=1.0)
    baseline = generate_terrain(_square(), settings)
    # A ridge-profile fixture requires surrounding land below its lowest crest.
    assert np.nanmax(baseline.elevation_m) < ridge.elevation_m
    terrain = generate_terrain(
        _square(),
        settings,
        constraints=(ridge, west_peak, mountain_pass, east_peak),
    )
    centreline = terrain.elevation_m[32]

    assert centreline[16] == np.float32(3_400.0)
    assert centreline[32] == np.float32(2_400.0)
    assert centreline[48] == np.float32(3_200.0)
    assert np.max(centreline[16:33]) <= np.float32(3_400.0)
    assert np.min(centreline[16:33]) >= np.float32(2_400.0)
    assert np.max(centreline[32:49]) <= np.float32(3_200.0)
    assert np.min(centreline[32:49]) >= np.float32(2_400.0)

    assert centreline[28] > centreline[32]
    assert centreline[36] > centreline[32]
    assert terrain.elevation_m[28, 32] < centreline[32]
    assert terrain.elevation_m[36, 32] < centreline[32]

    reordered = generate_terrain(
        _square(),
        settings,
        constraints=(east_peak, mountain_pass, ridge, west_peak),
    )
    finer = generate_terrain(
        _square(),
        replace(settings, resolution_px=129),
        constraints=(ridge, west_peak, mountain_pass, east_peak),
    )
    np.testing.assert_array_equal(terrain.elevation_m, reordered.elevation_m)
    np.testing.assert_array_equal(terrain.elevation_m, finer.elevation_m[::2, ::2])


def test_conflicting_height_anchors_on_one_structure_are_rejected() -> None:
    ridge = TerrainStructure("ridge", ((0.2, 0.5), (0.8, 0.5)), 2_000.0, 50.0)
    first = ElevationPoint((0.5, 0.5), 2_400.0, 40.0)
    conflicting = ElevationPoint((0.5, 0.5), 2_800.0, 40.0)

    with pytest.raises(ValueError, match="Conflicting height points"):
        generate_terrain(_square(), _settings(), constraints=(ridge, first, conflicting))


def test_terrain_brush_softly_guides_the_base_surface() -> None:
    baseline = generate_terrain(_square(), _settings())
    weak_brush = TerrainBrushStroke(
        points=((0.3, 0.5), (0.7, 0.5)),
        elevation_m=3_000.0,
        influence_radius_km=100.0,
        intensity=0.25,
    )
    strong_brush = replace(weak_brush, intensity=0.75)

    weak = generate_terrain(_square(), _settings(), constraints=(weak_brush,))
    strong = generate_terrain(_square(), _settings(), constraints=(strong_brush,))

    assert baseline.elevation_m[32, 32] < weak.elevation_m[32, 32]
    assert weak.elevation_m[32, 32] < strong.elevation_m[32, 32]
    assert strong.elevation_m[32, 32] < np.float32(3_000.0)


def test_terrain_brush_can_lower_terrain_without_moving_the_coastline() -> None:
    baseline = generate_terrain(_square(), _settings())
    brush = TerrainBrushStroke(
        points=((0.3, 0.5), (0.7, 0.5)),
        elevation_m=100.0,
        influence_radius_km=120.0,
        intensity=0.8,
    )

    painted = generate_terrain(_square(), _settings(), constraints=(brush,))

    assert painted.elevation_m[32, 32] < baseline.elevation_m[32, 32]
    assert painted.elevation_m[0, 32] == np.float32(0.0)


def test_relative_brush_adds_a_soft_offset_to_existing_terrain() -> None:
    baseline = generate_terrain(_square(), _settings(maximum_elevation_m=5_000.0))
    brush = TerrainBrushStroke(
        points=((0.3, 0.5), (0.7, 0.5)),
        elevation_m=600.0,
        influence_radius_km=100.0,
        intensity=0.5,
        elevation_mode="relative",
    )

    painted = generate_terrain(
        _square(),
        _settings(maximum_elevation_m=5_000.0),
        constraints=(brush,),
    )
    lowered = generate_terrain(
        _square(),
        _settings(maximum_elevation_m=5_000.0),
        constraints=(replace(brush, elevation_m=-600.0),),
    )

    assert float(painted.elevation_m[32, 32] - baseline.elevation_m[32, 32]) == pytest.approx(
        300.0,
        abs=0.001,
    )
    assert float(lowered.elevation_m[32, 32] - baseline.elevation_m[32, 32]) == pytest.approx(
        -300.0,
        abs=0.001,
    )


def test_relative_peak_builds_on_relative_ridge_and_preserves_background_relief() -> None:
    settings = _settings(maximum_elevation_m=6_000.0)
    baseline = generate_terrain(_square(), settings)
    ridge = TerrainStructure(
        "ridge",
        ((0.2, 0.5), (0.8, 0.5)),
        800.0,
        80.0,
        "relative",
    )
    peak = ElevationPoint((0.5, 0.5), 600.0, 70.0, "relative")

    ridge_only = generate_terrain(_square(), settings, constraints=(ridge,))
    combined = generate_terrain(_square(), settings, constraints=(ridge, peak))

    assert float(ridge_only.elevation_m[32, 32] - baseline.elevation_m[32, 32]) == pytest.approx(
        800.0,
        abs=0.001,
    )
    assert float(combined.elevation_m[32, 32] - ridge_only.elevation_m[32, 32]) == pytest.approx(
        600.0,
        abs=0.001,
    )


def test_relative_points_shape_a_relative_ridge_without_profile_overshoot() -> None:
    settings = _settings(
        maximum_elevation_m=6_000.0,
        variability=0.0,
    )
    ridge = TerrainStructure(
        "ridge",
        ((0.125, 0.5), (0.875, 0.5)),
        800.0,
        55.0,
        "relative",
    )
    west_peak = ElevationPoint((0.25, 0.5), 400.0, 35.0, "relative")
    mountain_pass = ElevationPoint((0.5, 0.5), -500.0, 35.0, "relative")
    east_peak = ElevationPoint((0.75, 0.5), 300.0, 35.0, "relative")
    constraints = (ridge, west_peak, mountain_pass, east_peak)

    baseline = generate_terrain(_square(), settings)
    terrain = generate_terrain(_square(), settings, constraints=constraints)
    centreline_relief = terrain.elevation_m[32] - baseline.elevation_m[32]

    assert centreline_relief[16] == pytest.approx(1_200.0, abs=0.001)
    assert centreline_relief[32] == pytest.approx(300.0, abs=0.001)
    assert centreline_relief[48] == pytest.approx(1_100.0, abs=0.001)
    assert np.max(centreline_relief[16:33]) <= 1_200.001
    assert np.min(centreline_relief[16:33]) >= 299.999
    assert np.max(centreline_relief[32:49]) <= 1_100.001
    assert np.min(centreline_relief[32:49]) >= 299.999
    assert centreline_relief[28] > centreline_relief[32]
    assert centreline_relief[36] > centreline_relief[32]
    assert terrain.elevation_m[28, 32] < terrain.elevation_m[32, 32]
    assert terrain.elevation_m[36, 32] < terrain.elevation_m[32, 32]

    reordered = generate_terrain(
        _square(),
        settings,
        constraints=(east_peak, mountain_pass, ridge, west_peak),
    )
    finer = generate_terrain(
        _square(),
        replace(settings, resolution_px=129),
        constraints=constraints,
    )
    np.testing.assert_array_equal(terrain.elevation_m, reordered.elevation_m)
    np.testing.assert_array_equal(terrain.elevation_m, finer.elevation_m[::2, ::2])


def test_relative_valley_keeps_the_elevation_difference_of_its_surroundings() -> None:
    settings = _settings(
        maximum_elevation_m=6_000.0,
        variability=0.0,
        coastal_rise_km=1.0,
    )
    baseline = generate_terrain(_square(), settings)
    valley = TerrainStructure(
        "valley",
        ((0.2, 0.5), (0.8, 0.5)),
        500.0,
        80.0,
        "relative",
    )

    cut = generate_terrain(_square(), settings, constraints=(valley,))

    for column in (26, 32, 38):
        incision = float(baseline.elevation_m[32, column] - cut.elevation_m[32, column])
        assert incision == pytest.approx(
            500.0,
            abs=0.001,
        )


def test_relative_points_shape_relative_valley_depth() -> None:
    settings = _settings(
        maximum_elevation_m=6_000.0,
        variability=0.0,
        coastal_rise_km=1.0,
    )
    baseline = generate_terrain(_square(), settings)
    valley = TerrainStructure(
        "valley",
        ((0.125, 0.5), (0.875, 0.5)),
        700.0,
        55.0,
        "relative",
    )
    shallow = ElevationPoint((0.25, 0.5), 400.0, 35.0, "relative")
    deep = ElevationPoint((0.75, 0.5), -200.0, 35.0, "relative")

    terrain = generate_terrain(
        _square(),
        settings,
        constraints=(valley, shallow, deep),
    )
    centreline_depth = baseline.elevation_m[32] - terrain.elevation_m[32]

    assert centreline_depth[16] == pytest.approx(300.0, abs=0.001)
    assert centreline_depth[48] == pytest.approx(900.0, abs=0.001)
    assert np.max(centreline_depth[16:49]) <= 900.001
    assert np.min(centreline_depth[16:49]) >= 299.999


def test_relative_valley_floor_never_rises_toward_its_authored_outlet() -> None:
    settings = _settings(maximum_elevation_m=6_000.0, variability=0.0)
    baseline = generate_terrain(_square(), settings)
    valley = TerrainStructure(
        "valley",
        ((0.2, 0.5), (0.5, 0.5)),
        500.0,
        60.0,
        "relative",
    )

    terrain = generate_terrain(_square(), settings, constraints=(valley,))
    centreline = terrain.elevation_m[32, 13:33]
    baseline_centreline = baseline.elevation_m[32, 13:33]

    assert np.all(np.diff(centreline) <= 0.001)
    assert np.all(baseline_centreline - centreline >= 499.999)
    assert centreline[0] > 2_500.0


def test_relative_valley_keeps_requested_depth_with_residual_detail() -> None:
    settings = _settings(
        resolution_px=129,
        maximum_elevation_m=6_000.0,
        variability=0.8,
    )
    valley = TerrainStructure(
        "valley",
        ((0.25, 0.5), (0.5, 0.5)),
        500.0,
        45.0,
        "relative",
    )

    baseline = generate_terrain(_square(), settings)
    terrain = generate_terrain(_square(), settings, constraints=(valley,))
    baseline_centreline = baseline.elevation_m[64, 32:65]
    centreline = terrain.elevation_m[64, 32:65]

    assert np.min(baseline_centreline - centreline) >= 499.0
    assert np.all(np.diff(centreline) <= 0.001)


def test_absolute_valley_connects_non_rising_floor_anchors_to_its_outlet() -> None:
    settings = _settings(
        maximum_elevation_m=6_000.0,
        variability=0.0,
        coastal_rise_km=1.0,
    )
    valley = TerrainStructure(
        "valley",
        ((0.125, 0.5), (0.875, 0.5)),
        500.0,
        55.0,
        "absolute",
    )
    head = ElevationPoint((0.25, 0.5), 2_500.0, 35.0)
    middle = ElevationPoint((0.5, 0.5), 1_700.0, 35.0)
    lower = ElevationPoint((0.75, 0.5), 900.0, 35.0)
    constraints = (valley, head, middle, lower)

    terrain = generate_terrain(_square(), settings, constraints=constraints)
    centreline = terrain.elevation_m[32, 8:57]

    assert terrain.elevation_m[32, 16] == np.float32(2_500.0)
    assert terrain.elevation_m[32, 32] == np.float32(1_700.0)
    assert terrain.elevation_m[32, 48] == np.float32(900.0)
    assert terrain.elevation_m[32, 56] <= np.float32(500.01)
    assert np.all(np.diff(centreline) <= 0.001)

    reordered = generate_terrain(
        _square(),
        settings,
        constraints=(lower, middle, valley, head),
    )
    finer = generate_terrain(
        _square(),
        replace(settings, resolution_px=129),
        constraints=constraints,
    )
    np.testing.assert_array_equal(terrain.elevation_m, reordered.elevation_m)
    np.testing.assert_array_equal(terrain.elevation_m, finer.elevation_m[::2, ::2])


def test_absolute_valley_rejects_a_floor_anchor_that_rises_downstream() -> None:
    valley = TerrainStructure(
        "valley",
        ((0.2, 0.5), (0.8, 0.5)),
        500.0,
        60.0,
        "absolute",
    )
    upstream = ElevationPoint((0.3, 0.5), 1_000.0, 30.0)
    downstream = ElevationPoint((0.6, 0.5), 1_500.0, 30.0)

    with pytest.raises(ValueError, match="must not rise downstream"):
        generate_terrain(
            _square(),
            _settings(maximum_elevation_m=3_000.0),
            constraints=(valley, upstream, downstream),
        )


@pytest.mark.parametrize(
    ("kind", "structure_value", "point_value"),
    (("ridge", 400.0, -500.0), ("valley", 400.0, 500.0)),
)
def test_relative_point_cannot_reverse_attached_structure(
    kind: Literal["ridge", "valley"],
    structure_value: float,
    point_value: float,
) -> None:
    structure = TerrainStructure(
        kind,
        ((0.2, 0.5), (0.8, 0.5)),
        structure_value,
        50.0,
        "relative",
    )
    point = ElevationPoint((0.5, 0.5), point_value, 40.0, "relative")

    with pytest.raises(ValueError, match=f"would reverse the {kind}"):
        generate_terrain(_square(), _settings(), constraints=(structure, point))


def test_ambiguous_relative_point_attachment_is_order_independent() -> None:
    south_ridge = TerrainStructure(
        "ridge",
        ((0.2, 0.45), (0.8, 0.45)),
        600.0,
        80.0,
        "relative",
    )
    north_ridge = TerrainStructure(
        "ridge",
        ((0.2, 0.55), (0.8, 0.55)),
        1_000.0,
        80.0,
        "relative",
    )
    point = ElevationPoint((0.5, 0.5), 400.0, 40.0, "relative")

    first = generate_terrain(
        _square(),
        _settings(maximum_elevation_m=6_000.0),
        constraints=(south_ridge, north_ridge, point),
    )
    reordered = generate_terrain(
        _square(),
        _settings(maximum_elevation_m=6_000.0),
        constraints=(point, north_ridge, south_ridge),
    )

    np.testing.assert_array_equal(first.elevation_m, reordered.elevation_m)


def test_overlapping_terrain_brushes_are_order_independent() -> None:
    high = TerrainBrushStroke(((0.25, 0.5), (0.6, 0.5)), 2_500.0, 90.0, 0.4)
    low = TerrainBrushStroke(((0.4, 0.5), (0.75, 0.5)), 500.0, 110.0, 0.6)

    first = generate_terrain(_square(), _settings(), constraints=(high, low))
    second = generate_terrain(_square(), _settings(), constraints=(low, high))

    np.testing.assert_array_equal(first.elevation_m, second.elevation_m)


def test_authored_constraints_preserve_nested_resolution_samples() -> None:
    constraints = (
        TerrainBrushStroke(
            ((0.3, 0.4), (0.7, 0.4)),
            350.0,
            100.0,
            0.5,
            "relative",
        ),
        ElevationPoint((0.5, 0.5), 1_250.0, 130.0),
        TerrainStructure(
            "ridge",
            ((0.2, 0.7), (0.8, 0.7)),
            700.0,
            90.0,
            "relative",
        ),
    )

    coarse = generate_terrain(_square(), _settings(resolution_px=65), constraints=constraints)
    fine = generate_terrain(_square(), _settings(resolution_px=129), constraints=constraints)

    np.testing.assert_array_equal(coarse.land_mask, fine.land_mask[::2, ::2])
    np.testing.assert_array_equal(coarse.elevation_m, fine.elevation_m[::2, ::2])


def test_noise_is_independent_of_query_shape_and_order() -> None:
    x = np.array([12.5, 98.0, 301.25], dtype=np.float64)
    y = np.array([44.0, 72.5, 19.0], dtype=np.float64)
    together = fractal_value_noise(
        x,
        y,
        seed=99,
        largest_feature_km=300.0,
        detail_levels=6,
        roughness=0.6,
    )
    separately = np.array(
        [
            fractal_value_noise(
                np.array([x_value]),
                np.array([y_value]),
                seed=99,
                largest_feature_km=300.0,
                detail_levels=6,
                roughness=0.6,
            )[0]
            for x_value, y_value in zip(x, y, strict=True)
        ]
    )

    np.testing.assert_array_equal(together, separately)


def test_render_is_transparent_outside_and_png_records_settings(tmp_path: Path) -> None:
    point = ElevationPoint((0.5, 0.5), 1_200.0, 75.0)
    brush = TerrainBrushStroke(((0.3, 0.6), (0.7, 0.6)), 900.0, 60.0, 0.4)
    terrain = generate_terrain(_square(), _settings(), constraints=(point, brush))
    image = render_height_map(terrain)
    alpha = np.asarray(image)[..., 3]

    np.testing.assert_array_equal(alpha > 0, terrain.land_mask)
    destination = tmp_path / "terrain.png"
    save_height_map(image, terrain, destination)

    with Image.open(destination) as exported:
        assert exported.mode == "RGBA"
        assert exported.info["map-maker.source"] == "square.svg"
        assert exported.info["map-maker.render_style"] == "cartographic"
        assert exported.info["map-maker.colour_palette"] == "map-maker-cartographic-relief@3"
        assert exported.info["map-maker.colour_scale_maximum_m"] == "10000"
        assert '"seed": 42' in exported.info["map-maker.settings"]
        drainage = json.loads(exported.info["map-maker.drainage_diagnostics"])
        assert drainage["algorithm_id"] == "canonical-d8-priority-flood-diagnostics@4"
        assert drainage["grid_width"] == 257
        assert drainage["land_cell_count"] > 0
        assert drainage["basin_candidate_count"] == len(
            drainage["basin_candidates"]
        )
        constraints = json.loads(exported.info["map-maker.constraints"])
        assert constraints == [
            {
                "elevation_m": 1_200.0,
                "elevation_mode": "absolute",
                "influence_radius_km": 75.0,
                "position": [0.5, 0.5],
                "type": "elevation_point",
            },
            {
                "elevation_m": 900.0,
                "elevation_mode": "absolute",
                "influence_radius_km": 60.0,
                "intensity": 0.4,
                "points": [[0.3, 0.6], [0.7, 0.6]],
                "type": "terrain_brush",
            },
        ]


def test_scientific_elevation_palette_is_ordered_by_lightness() -> None:
    normalized = np.linspace(0.0, 1.0, 1_025)
    rgb = elevation_palette_rgb(normalized, style="scientific")
    linear_rgb = np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )
    relative_luminance = linear_rgb @ np.array([0.2126, 0.7152, 0.0722])

    assert np.all(np.diff(relative_luminance) > 0.0)
    assert rgb[0, 1] > rgb[0, 0] * 2.0
    assert rgb[0, 1] > rgb[0, 2] * 2.0
    assert np.all(rgb[-1] > 0.89)


def test_cartographic_palette_reserves_red_and_white_for_extreme_summits() -> None:
    rgb = elevation_palette_rgb(
        np.array([0.0, 0.60, 0.65, 0.70, 0.75, 0.82, 0.90, 0.96, 1.0])
    )

    np.testing.assert_allclose(rgb[0], np.array([54, 95, 55]) / 255.0)
    np.testing.assert_allclose(rgb[1], np.array([124, 75, 48]) / 255.0)
    np.testing.assert_allclose(rgb[2], np.array([124, 71, 50]) / 255.0)
    np.testing.assert_allclose(rgb[3], np.array([126, 67, 54]) / 255.0)
    np.testing.assert_allclose(rgb[4], np.array([137, 65, 57]) / 255.0)
    np.testing.assert_allclose(rgb[5], np.array([155, 74, 65]) / 255.0)
    np.testing.assert_allclose(rgb[6], np.array([198, 112, 96]) / 255.0)
    np.testing.assert_allclose(rgb[7], np.array([231, 182, 168]) / 255.0)
    np.testing.assert_allclose(rgb[8], np.array([247, 246, 242]) / 255.0)


def test_cartographic_colours_use_fixed_world_elevations() -> None:
    terrain = generate_terrain(_square(), _settings(maximum_elevation_m=4_500.0))
    differently_ranged = replace(
        terrain,
        settings=replace(terrain.settings, maximum_elevation_m=10_000.0),
    )

    np.testing.assert_array_equal(
        np.asarray(render_height_map(terrain)),
        np.asarray(render_height_map(differently_ranged)),
    )


def test_elevation_legends_match_each_palette_from_high_to_low() -> None:
    legend = elevation_legend_colours()
    scientific = elevation_legend_colours(style="scientific")

    assert legend[0] == "#f7f6f2"
    assert legend[-1] == "#365f37"
    assert scientific[0] == "#fdfde6"
    assert scientific[-1] == "#1a4c00"
    with pytest.raises(ValueError, match="at least two"):
        elevation_legend_colours(1)


def test_scientific_render_records_its_display_contract() -> None:
    terrain = generate_terrain(_square(), _settings())

    image = render_height_map(terrain, style="scientific")

    assert image.info["map-maker.render_style"] == "scientific"
    assert image.info["map-maker.colour_palette"] == "oleron-land@scm-8.0"
    assert image.info["map-maker.colour_scale_maximum_m"] == "3000"


def test_progress_announces_sampling_before_chunk_completion() -> None:
    events: list[tuple[float, str]] = []
    generate_terrain(_square(), _settings(),
                     progress=lambda value, label: events.append((value, label)))
    sampling = [value for value, label in events if label == "Building elevation field"]
    assert sampling[0] == 0.08
    assert len(sampling) >= 2
    assert sampling[-1] == pytest.approx(0.90)
    assert all(a[0] <= b[0] for a, b in pairwise(events))
    assert events[-1] == (1.0, "Terrain ready")
