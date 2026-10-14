"""Numerical controls for the frozen-graph reconstruction experiment."""

from dataclasses import replace
from typing import cast

import numpy as np
import pytest

from benchmarks.evolution.paths import (
    ChannelPaths,
    FloatArray,
    Sampler,
    anchor_residuals,
    measure_paths,
    profile_numbers,
    station_distances,
)
from benchmarks.evolution.surface import FlowAlignedSurface, SurfaceTopologyConflict
from map_maker.terrain.domain.evolution import EvolutionGrid


def branching_surface() -> FlowAlignedSurface:
    grid = EvolutionGrid(4000.0, 4000.0, 1000.0)
    z = np.full(grid.shape, 200.0)
    r = np.full(grid.shape, -1, dtype=np.int64)
    for source, target, height in ((6, 12, 100.0), (8, 12, 120.0), (12, 18, 90.0), (18, 24, 80.0)):
        r.flat[source] = target
        z.flat[source] = height
    z.flat[24] = 70.0
    return FlowAlignedSurface(grid, z, r, r >= 0)


def test_required_diagonal_removes_real_bilinear_hump_without_changing_nodes() -> None:
    field = branching_surface()
    x = np.linspace(1000.0, 2000.0, 1001)
    delivered = field.sample(x, x)
    assert field.bilinear(x, x).max() > 147.0
    np.testing.assert_array_equal(delivered, (110.0 - x * 0.01).astype(np.float32))
    assert np.all(np.diff(delivered) <= 0.0)
    y, x = np.indices(field.grid.shape, dtype=np.float64) * 1000.0
    np.testing.assert_array_equal(field.sample(x, y), field.ground_m.astype(np.float32))


def test_opposite_diagonal_cardinals_and_cell_borders_are_continuous() -> None:
    field = branching_surface()
    t = np.linspace(0.0, 1.0, 1001)
    np.testing.assert_array_equal(
        field.sample(3000.0 - t * 1000.0, 1000.0 + t * 1000.0),
        (120.0 - 30.0 * t).astype(np.float32),
    )
    for row in range(5):
        x, y = t * 4000.0, np.full(t.shape, row * 1000.0)
        np.testing.assert_array_equal(field.sample(x, y), field.bilinear(x, y))
        np.testing.assert_array_equal(field.sample(y, x), field.bilinear(y, x))
    np.testing.assert_allclose(
        field.sample(np.full(t.shape, 2000.0 - 1.0e-6), t * 4000.0),
        field.sample(np.full(t.shape, 2000.0 + 1.0e-6), t * 4000.0),
        atol=2.0e-5,
    )


def test_owned_surface_stays_within_corner_envelope_and_preserves_untouched_cells() -> None:
    field = branching_surface()
    original = field.ground_m.copy()
    replacement = replace(field, ground_m=original)
    original[:] = -10.0
    np.testing.assert_array_equal(field.ground_m, replacement.ground_m)
    for values in (field.ground_m, field.receivers, field.required, field.diagonals):
        assert not values.flags.writeable
    rng = np.random.default_rng(123)
    x, y = rng.uniform(0.0, 4000.0, (2, 10000))
    z = field.sample(x, y)
    c, r = (x / 1000.0).astype(int), (y / 1000.0).astype(int)
    corners = np.stack(
        [
            field.ground_m[r, c],
            field.ground_m[r + 1, c],
            field.ground_m[r, c + 1],
            field.ground_m[r + 1, c + 1],
        ]
    )
    assert np.all(z >= corners.min(axis=0))
    assert np.all(z <= corners.max(axis=0))
    unselected = field.diagonals[r, c] == 0
    np.testing.assert_array_equal(z[unselected], field.bilinear(x, y)[unselected])
    np.testing.assert_array_equal(z[::-7], field.sample(x[::-7], y[::-7]))


def test_rotation_preserves_same_physical_surface_and_graph() -> None:
    field = branching_surface()
    # Clockwise 90 degrees: (row, col) -> (col, 4-row).
    ids = np.arange(25).reshape(5, 5)
    mapping = (ids % 5) * 5 + 4 - ids // 5
    rotated = np.full((5, 5), -1, dtype=np.int64)
    sources = np.flatnonzero(field.receivers >= 0)
    rotated.flat[mapping.flat[sources]] = mapping.flat[field.receivers.flat[sources]]
    other = FlowAlignedSurface(field.grid, np.rot90(field.ground_m, -1), rotated, rotated >= 0)
    x, y = np.random.default_rng(321).uniform(0.0, 4000.0, (2, 1000))
    np.testing.assert_array_equal(field.sample(x, y), other.sample(4000.0 - y, x))


def test_crossing_required_edges_are_explicit_conflicts() -> None:
    field = branching_surface()
    receivers = field.receivers.copy()
    receivers.flat[7] = 11
    with pytest.raises(SurfaceTopologyConflict) as error:
        replace(field, receivers=receivers, required=receivers >= 0)
    assert error.value.cells == (5,)
    # A crossing not included in the declared requirement cannot erase that edge.
    replace(field, receivers=receivers)


@pytest.mark.parametrize("target, message", [(6, "cycle"), (24, "D8"), (25, "outside")])
def test_invalid_graph_is_rejected(target: int, message: str) -> None:
    field = branching_surface()
    receivers = field.receivers.copy()
    receivers.flat[6] = target
    with pytest.raises(ValueError, match=message):
        replace(field, receivers=receivers)


def test_disconnected_required_network_is_rejected() -> None:
    field = branching_surface()
    required = field.required.copy()
    required.flat[12] = False
    with pytest.raises(ValueError, match="connected"):
        ChannelPaths(field.grid, field.receivers, required)


def test_full_route_measures_keep_every_head_and_shared_reach() -> None:
    field = branching_surface()
    paths = ChannelPaths(field.grid, field.receivers, field.required)
    np.testing.assert_array_equal(paths.heads(), [6, 8])
    np.testing.assert_array_equal(paths.route(6), [6, 12, 18, 24])
    bad = measure_paths(paths, field.bilinear, field.ground_m, 25.0)
    good = measure_paths(paths, field.sample, field.ground_m, 25.0)
    assert bad["path_identity"] == good["path_identity"]
    assert bad["sample_count"] == good["sample_count"]
    assert good["required_edge_count"] == good["sampled_edge_count"] == 4
    assert good["head_route_count"] == 2
    assert good["unique_network"]["length_m"] == pytest.approx(4000.0 * np.sqrt(2))
    assert bad["unique_network"]["uphill_ascent_m"] > 100.0
    assert good["unique_network"]["uphill_ascent_m"] == 0.0
    assert all(row["maximum_excursion_m"] == 0.0 for row in good["routes"])
    assert (
        good["profile_sha256"]
        == measure_paths(paths, field.sample, field.ground_m, 25.0)["profile_sha256"]
    )
    coarse = measure_paths(paths, field.sample, field.ground_m, 100.0)
    assert coarse["unique_network"] == good["unique_network"]


def test_nodal_uphill_cannot_be_hidden_by_reconstruction() -> None:
    field = branching_surface()
    ground = field.ground_m.copy()
    ground.flat[12] = 110.0
    field = replace(field, ground_m=ground)
    rows = measure_paths(
        ChannelPaths(field.grid, field.receivers, field.required), field.sample, ground, 25.0
    )["routes"]
    assert not rows[0]["nodally_nonascending"]
    assert rows[0]["maximum_excursion_m"] == 10.0
    assert rows[1]["nodally_nonascending"]
    assert rows[1]["maximum_excursion_m"] == 0.0


def test_hard_off_grid_anchor_conflict_is_reported_and_never_patched() -> None:
    field = branching_surface()
    points = np.array([[1000.0, 1000.0], [1500.0, 1500.0]])
    targets = field.bilinear(points[:, 0], points[:, 1]).astype(np.float64)
    assert anchor_residuals(field.bilinear, points, targets)["violated_indices"] == []
    report = anchor_residuals(field.sample, points, targets)
    assert report["violated_indices"] == [1]
    assert report["residuals_m"] == [0.0, -52.5]
    assert field.sample(points[1:, 0], points[1:, 1])[0] == 95.0


def test_reconstruction_integral_is_separate_from_erosion_ledger() -> None:
    field = branching_surface()
    # Midpoint quadrature has O(spacing squared) error in diagonal cells.
    axis = (np.arange(800, dtype=np.float64) + 0.5) * 5.0
    x, y = np.meshgrid(axis, axis)
    delta = field.sample(x, y).astype(np.float64) - field.bilinear(x, y)
    report = field.composition()
    assert float(report["signed_volume_change_m3"]) == pytest.approx(
        float(delta.sum() * 25.0), rel=6.0e-5
    )
    assert float(report["absolute_volume_change_m3"]) == pytest.approx(
        float(np.abs(delta).sum() * 25.0), rel=6.0e-5
    )
    assert np.abs(delta).max() <= float(report["maximum_absolute_point_change_bound_m"]) + 1.0e-4


@pytest.mark.parametrize("height", [0.0, 50.0])
def test_flat_and_planar_fields_are_not_bent(height: float) -> None:
    field = branching_surface()
    y, x = np.indices(field.grid.shape, dtype=np.float64)
    field = replace(field, ground_m=height * (x + y))
    qx, qy = np.random.default_rng(55).uniform(0.0, 4000.0, (2, 1000))
    np.testing.assert_allclose(field.sample(qx, qy), field.bilinear(qx, qy), atol=1.0e-5)
    assert field.composition()["absolute_volume_change_m3"] == 0.0


def test_physical_stations_retain_vertices_with_bounded_gaps() -> None:
    result = station_distances(np.array([0.0, 3.0, 3.0]), np.array([0.0, 4.0, 9.0]), 3.0)
    np.testing.assert_array_equal(result, [0.0, 3.0, 5.0, 6.0, 9.0, 10.0])
    assert np.diff(result).max() <= 3.0


@pytest.mark.parametrize("spacing", [0.0, -1.0, float("nan"), 1.0e-320])
def test_invalid_or_unbounded_profile_requests_fail_before_allocation(spacing: float) -> None:
    field = branching_surface()
    paths = ChannelPaths(field.grid, field.receivers, field.required)
    with pytest.raises(ValueError):
        station_distances(np.array([0.0, 1000.0]), np.array([0.0, 0.0]), spacing)
    with pytest.raises(ValueError):
        measure_paths(paths, field.sample, field.ground_m, spacing)


def test_finite_sampler_and_explicit_work_budget_are_required() -> None:
    field = branching_surface()
    paths = ChannelPaths(field.grid, field.receivers, field.required)
    with pytest.raises(ValueError, match="budget"):
        measure_paths(paths, field.sample, field.ground_m, 25.0, maximum_samples=10)
    with pytest.raises(ValueError, match="finite Float32"):
        anchor_residuals(
            lambda x, y: np.full(x.shape, np.nan, dtype=np.float32),
            np.array([[1000.0, 1000.0]]),
            np.array([100.0]),
        )

    def wrong_dtype(x: FloatArray, y: FloatArray) -> FloatArray:
        return np.zeros(x.shape, dtype=np.float64)

    with pytest.raises(ValueError, match="finite Float32"):
        measure_paths(paths, cast(Sampler, wrong_dtype), field.ground_m, 25.0)
    with pytest.raises(ValueError, match="inside"):
        field.sample(np.array([-1.0]), np.array([0.0]))


def test_gentle_uphill_length_does_not_vanish_when_sampling_more_densely() -> None:
    for spacing in (100.0, 25.0, 1.0):
        stations = np.arange(0.0, 1000.0 + spacing, spacing)
        heights = (100.0 + stations * 0.000156).astype(np.float32)
        result = profile_numbers(stations, heights)
        assert result["affected_length_m"] == 1000.0
        assert result["maximum_excursion_m"] == pytest.approx(0.156, abs=1.0e-5)
    # Sub-tolerance noise is still measured as ascent, but not counted as length.
    small = profile_numbers(
        np.array([0.0, 1.0, 2.0]), np.array([0.0, 0.001, 0.0], dtype=np.float32)
    )
    assert small["uphill_ascent_m"] > 0.0
    assert small["affected_length_m"] == 0.0
