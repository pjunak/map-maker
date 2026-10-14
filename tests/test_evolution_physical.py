"""Topology, actual-ground and deterministic controls for physical channel paths."""

from dataclasses import replace

import numpy as np
import pytest

from benchmarks.evolution.paths import ChannelPaths, measure_paths
from benchmarks.evolution.physical import (
    PathSettings,
    PhysicalSurface,
    constraint_samples,
    geometry_numbers,
    grid_points,
    prepare,
)
from benchmarks.evolution.surface import FlowAlignedSurface
from map_maker.terrain.domain.evolution import EvolutionGrid


def zigzag() -> FlowAlignedSurface:
    grid = EvolutionGrid(6000.0, 6000.0, 1000.0)
    y, _ = np.indices(grid.shape, dtype=np.float64) * grid.spacing_m
    ground = 100.0 - y * 0.01
    receivers = np.full(grid.shape, -1, dtype=np.int64)
    # Two sources join, then alternate diagonal/cardinal steps to the perimeter.
    for a, b in ((8, 16), (10, 16), (16, 24), (24, 31), (31, 39), (39, 46)):
        receivers.flat[a] = b
    return FlowAlignedSurface(grid, ground, receivers, receivers >= 0)


def test_paths_and_ground_move_together_without_changing_connections_or_endpoints() -> None:
    field = zigzag()
    candidate = prepare(field)
    paths = candidate.paths
    original = ChannelPaths(field.grid, field.receivers, field.required)
    assert paths.identity() != original.identity()
    np.testing.assert_array_equal(paths.heads(), original.heads())
    for head in original.heads():
        np.testing.assert_array_equal(paths.route(int(head)), original.route(int(head)))
    origin = grid_points(field)
    moved = np.linalg.norm(paths.coordinates_m - origin, axis=-1)
    assert 0 < moved.max() <= 125.0
    assert np.all(moved.ravel()[[8, 10, 16, 46]] == 0.0)
    assert np.all(moved[~field.required] == 0.0)
    assert geometry_numbers(paths)["d8_length_fraction"] < 1.0
    assert np.all(candidate.determinants_m2 > 0.0)
    x, y = paths.coordinates_m[..., 0], paths.coordinates_m[..., 1]
    np.testing.assert_array_equal(candidate.sample(x, y), field.ground_m.astype(np.float32))
    for spacing in (100.0, 25.0, 3.0):
        measured = measure_paths(paths, candidate.sample, field.ground_m, spacing)
        assert measured["required_edge_count"] == int(field.required.sum())
        assert measured["head_route_count"] == 2
        assert all(r["maximum_excursion_m"] == 0.0 for r in measured["routes"])
    # Same displaced river lines over the untouched ground do climb in other
    # fixtures: an overlay alone is never the delivered physical sampler.
    x, y = origin[..., 0], origin[..., 1]
    assert np.any(candidate.sample(x, y) != field.sample(x, y))


def test_readonly_preparation_repeat_and_shared_coordinate_queries() -> None:
    field = zigzag()
    candidate = prepare(field)
    again = prepare(field)
    assert candidate.paths.identity() == again.paths.identity()
    for values in (
        candidate.paths.coordinates_m,
        candidate.active,
        candidate.corners_m,
        candidate.centres_m,
        candidate.determinants_m2,
    ):
        assert not values.flags.writeable
    x, y = np.random.default_rng(44).uniform(0, 6000, (2, 2000))
    full = candidate.sample(x, y)
    np.testing.assert_array_equal(full[::7], candidate.sample(x[::7], y[::7]))
    np.testing.assert_array_equal(full[::-1], candidate.sample(x[::-1], y[::-1]))
    np.testing.assert_array_equal(full, again.sample(x, y))
    for boundary in (0.0, 6000.0):
        q = np.linspace(0, 6000, 501)
        fixed = np.full(q.shape, boundary)
        np.testing.assert_array_equal(candidate.sample(q, fixed), field.sample(q, fixed))
        np.testing.assert_array_equal(candidate.sample(fixed, q), field.sample(fixed, q))


def test_nodal_climbs_remain_visible_and_cannot_be_removed_from_coverage() -> None:
    field = zigzag()
    ground = field.ground_m.copy()
    ground.flat[31] = ground.flat[24] + 15.0
    field = replace(field, ground_m=ground)
    candidate = prepare(field)
    measured = measure_paths(candidate.paths, candidate.sample, ground, 25.0)
    assert measured["required_edge_count"] == 6
    assert all(row["maximum_excursion_m"] >= 15.0 for row in measured["routes"])


def test_terrain_penalty_changes_geometry_and_straight_planar_routes_stay_straight() -> None:
    field = zigzag()
    soft = prepare(field, PathSettings(terrain_scale_m=100.0))
    stiff = prepare(field, PathSettings(terrain_scale_m=0.01))
    assert soft.paths.identity() != stiff.paths.identity()
    receivers = np.full(field.grid.shape, -1, dtype=np.int64)
    for source in (10, 17, 24, 31, 38):
        receivers.flat[source] = source + 7
    straight = replace(field, receivers=receivers, required=receivers >= 0)
    candidate = prepare(straight)
    np.testing.assert_array_equal(candidate.paths.coordinates_m, grid_points(straight))
    assert not np.any(candidate.active)


def test_rotation_of_the_same_physical_problem_rotates_the_result() -> None:
    field = zigzag()
    ids = np.arange(49).reshape(7, 7)
    mapping = (ids % 7) * 7 + 6 - ids // 7
    receivers = np.full((7, 7), -1, dtype=np.int64)
    sources = np.flatnonzero(field.required)
    receivers.flat[mapping.flat[sources]] = mapping.flat[field.receivers.flat[sources]]
    rotated = FlowAlignedSurface(
        field.grid, np.rot90(field.ground_m, -1), receivers, receivers >= 0
    )
    a, b = prepare(field), prepare(rotated)
    rotated_points = a.paths.coordinates_m.reshape(-1, 2).copy()
    rotated_points = np.stack((6000.0 - rotated_points[:, 1], rotated_points[:, 0]), axis=-1)
    np.testing.assert_allclose(
        b.paths.coordinates_m.reshape(-1, 2)[mapping.ravel()], rotated_points, atol=1.0e-9, rtol=0
    )
    x, y = np.random.default_rng(11).uniform(0, 6000, (2, 1000))
    np.testing.assert_allclose(a.sample(x, y), b.sample(6000.0 - y, x), atol=8.0e-6, rtol=0)


def test_no_fold_corridor_boundary_and_endpoint_guards() -> None:
    field = zigzag()
    original = grid_points(field)
    for node in (0, 8, 16, 46):
        changed = original.copy().reshape(-1, 2)
        changed[node, 0] += 1.0
        with pytest.raises(ValueError, match="endpoints"):
            PhysicalSurface(field, changed.reshape(original.shape))
    changed = original.copy().reshape(-1, 2)
    changed[24, 0] += 241.0
    with pytest.raises(ValueError, match="corridor"):
        PhysicalSurface(field, changed.reshape(original.shape))
    candidate = prepare(field)
    for bad in (-1.0, 6001.0, float("nan")):
        with pytest.raises(ValueError, match="inside"):
            candidate.sample(np.array([bad]), np.array([1000.0]))


def test_budget_and_authored_anchor_conflicts_are_reported_without_patching() -> None:
    field = zigzag()
    candidate = prepare(field)
    original = grid_points(field).reshape(-1, 2)
    queries = candidate.paths.coordinates_m.reshape(-1, 2)
    anchor = np.vstack((original[24], original[24] + np.array([85.0, -65.0])))
    target = field.sample(anchor[:, 0], anchor[:, 1]).astype(np.float64)
    before = candidate.paths.identity()
    result = constraint_samples(
        candidate.sample,
        field.bilinear,
        queries,
        maximum_cut_m=0.0,
        maximum_fill_m=0.0,
        anchors_m=anchor,
        anchor_heights_m=target,
    )
    assert not result["passes_sampled_constraints"]
    assert result["cut_violations"] + result["fill_violations"] > 0
    assert result["anchors"]["violated_indices"] == [0, 1]
    assert candidate.paths.identity() == before
    with pytest.raises(ValueError, match="budgets"):
        constraint_samples(
            candidate.sample,
            field.bilinear,
            queries,
            maximum_cut_m=-1,
            maximum_fill_m=0,
            anchors_m=anchor,
            anchor_heights_m=target,
        )


def test_continuity_on_warped_cell_edges_and_fan_centres() -> None:
    candidate = prepare(zigzag())
    coords = candidate.paths.coordinates_m
    points = 0.35 * coords[2:5, 2:5] + 0.65 * coords[3:6, 2:5]
    x, y = points[..., 0], points[..., 1]
    np.testing.assert_allclose(
        candidate.sample(x - 1.0e-6, y), candidate.sample(x + 1.0e-6, y), atol=8.0e-6, rtol=0
    )
    centre = candidate.centres_m
    np.testing.assert_allclose(
        candidate.sample(centre[..., 0], centre[..., 1]),
        candidate.sample(centre[..., 0] + 1.0e-6, centre[..., 1]),
        atol=8.0e-6,
        rtol=0,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"iterations": 0},
        {"iterations": True},
        {"displacement_m": float("inf")},
        {"terrain_scale_m": 0},
    ],
)
def test_invalid_preparation_settings_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        PathSettings(**kwargs)  # type: ignore[arg-type]


def test_frozen_graph_sensitivity_uses_common_physical_stations() -> None:
    from benchmarks.evolution.sensitivity import compare_graphs

    coarse = EvolutionGrid(6000.0, 6000.0, 1000.0)
    fine = EvolutionGrid(6000.0, 6000.0, 500.0)

    def south(grid: EvolutionGrid) -> np.ndarray[tuple[int, int], np.dtype[np.int64]]:
        r = np.full(grid.shape, -1, dtype=np.int64)
        ids = np.arange(r.size).reshape(r.shape)
        r[1:-1, 1:-1] = ids[1:-1, 1:-1] + r.shape[1]
        return r

    a, b = south(coarse), south(fine)
    same = compare_graphs(coarse, a, fine, b)
    assert same["shared_station_count"] == 25
    assert same["receiver_direction_change_fraction"] == 0.0
    assert same["terminal_shift_max_m"] == 0.0
    # Move one coarse receiver sideways: its physical outlet changes by 1 km.
    a[1, 1] += 1
    changed = compare_graphs(coarse, a, fine, b)
    assert changed["receiver_direction_change_fraction"] == 1 / 25
    assert changed["terminal_shift_max_m"] == 1000.0
    assert changed["terminal_boundary_side_change_fraction"] == 0.0
    # Change the route to exit north instead of south.
    a[1, 1] = 1
    changed = compare_graphs(coarse, a, fine, b)
    assert changed["terminal_boundary_side_change_fraction"] == 1 / 25
    with pytest.raises(ValueError, match="same physical"):
        compare_graphs(coarse, a, EvolutionGrid(8000, 6000, 1000), a)
    with pytest.raises(ValueError, match="nested"):
        compare_graphs(coarse, a, EvolutionGrid(6000, 6000, 750), a)
