"""Automatic layout may avoid hard heights; it cannot rewrite authored geometry."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from shapely.affinity import scale
from shapely.geometry import LineString, Point, box

from benchmarks.evolution.constrained import HardHeights, InfeasibleSurface
from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.network_fixture import fixture
from benchmarks.evolution.patch_comparison import inspect_surface
from benchmarks.evolution.valley_layout import LayoutSettings, NoAdmissibleLayout, relocate_guides
from benchmarks.evolution.valley_patches import prepare_patches
from map_maker.terrain.adapters.build import file_sha256


def test_relocation_preserves_vertices_topology_and_each_original_reach() -> None:
    f = fixture(250)
    source = f.source.ground_m.copy()
    mask = f.network.required.copy()
    result = relocate_guides(f, movable_edges=mask)
    original_count = len(f.network.receivers)
    np.testing.assert_array_equal(
        result.network.coordinates_m[:original_count], f.network.coordinates_m
    )
    np.testing.assert_array_equal(result.network.heads(), f.network.heads())
    np.testing.assert_array_equal(
        np.flatnonzero(result.network.receivers < 0), np.flatnonzero(f.network.receivers < 0)
    )
    for head in f.network.heads():
        route = result.network.route(int(head))
        original = f.network.route(int(head))
        np.testing.assert_array_equal(route[route < original_count], original)
        owners = result.original_edge_for_node[route[:-1]]
        collapsed = owners[np.concatenate(([True], owners[1:] != owners[:-1]))]
        np.testing.assert_array_equal(collapsed, original[:-1])
    np.testing.assert_array_equal(source, f.source.ground_m)
    assert result.source_network_identity == f.network.identity()
    assert result.network.identity() != f.network.identity()
    mask[:] = False
    assert result.original_movable_edges.any()
    assert not result.original_movable_edges.flags.writeable
    assert not result.original_edge_for_node.flags.writeable
    assert len(result.moves) == 1
    assert result.candidates_checked <= 4096


def test_actual_segments_respect_pin_clearance_corridor_divide_and_length() -> None:
    f = fixture(250)
    result = relocate_guides(f, movable_edges=f.network.required)
    divide = scale(f.protected_divide_km, xfact=1000, yfact=1000, origin=(0, 0))
    domain = box(0, 0, f.source.grid.width_m, f.source.grid.height_m)
    for move in result.moves:
        edge = move.original_edge
        next_original = int(f.network.receivers[edge])
        nodes = [edge]
        while nodes[-1] != next_original:
            nodes.append(int(result.network.receivers[nodes[-1]]))
        geometry = LineString(result.network.coordinates_m[nodes])
        original = LineString(f.network.coordinates_m[[edge, next_original]])
        assert (
            min(geometry.distance(Point(pin)) for pin in f.hard.points_m)
            >= result.settings.clearance_m
        )
        assert domain.covers(geometry)
        assert not geometry.intersects(divide)
        assert geometry.length <= original.length * result.settings.maximum_length_ratio
        # Exact segment-to-point distance includes locations between guide nodes.
        assert original.buffer(result.settings.corridor_m + 1e-6).covers(geometry)


def test_layout_is_independent_of_process_spacing_and_rotation() -> None:
    layouts = [
        relocate_guides(fixture(dx), movable_edges=fixture(dx).network.required)
        for dx in (1000, 500, 250)
    ]
    for layout in layouts[1:]:
        np.testing.assert_array_equal(
            layout.network.coordinates_m, layouts[0].network.coordinates_m
        )
        np.testing.assert_array_equal(layout.network.receivers, layouts[0].network.receivers)
    rotated = fixture(250, rotate=True)
    other = relocate_guides(rotated, movable_edges=rotated.network.required)
    xy = layouts[-1].network.coordinates_m
    np.testing.assert_allclose(
        other.network.coordinates_m,
        np.stack((24000 - xy[:, 1], xy[:, 0]), axis=-1),
        rtol=0,
        atol=1e-8,
    )
    np.testing.assert_array_equal(other.network.receivers, layouts[-1].network.receivers)


def test_fixed_guides_and_endpoint_conflicts_are_never_silently_relocated() -> None:
    f = fixture(250)
    with pytest.raises(NoAdmissibleLayout, match="fixed guide") as caught:
        relocate_guides(f, movable_edges=np.zeros(len(f.network.receivers), dtype=np.bool_))
    assert not isinstance(caught.value, InfeasibleSurface)
    assert caught.value.edge == 0
    pinned = replace(f, hard=HardHeights(f.network.coordinates_m[[0]], np.array([800.0])))
    with pytest.raises(NoAdmissibleLayout, match="endpoints"):
        relocate_guides(pinned, movable_edges=f.network.required)


def test_search_exhaustion_is_not_a_global_infeasibility_claim() -> None:
    f = fixture(250)
    with pytest.raises(NoAdmissibleLayout, match="bounded guide family") as caught:
        relocate_guides(
            f, movable_edges=f.network.required, settings=LayoutSettings(corridor_m=400)
        )
    assert caught.value.rejected["pin_clearance"] > 0
    assert relocate_guides(f, movable_edges=f.network.required).moves


def test_candidate_intersections_with_other_reaches_are_rejected() -> None:
    f = fixture(250)
    coords = np.vstack((f.network.coordinates_m, [[11350.0, 3500.0], [11350.0, 5000.0]]))
    receivers = np.concatenate((f.network.receivers, np.array([18, -1], dtype=np.int64)))
    crowded = replace(f, network=RiverNetwork(coords, receivers))
    baseline = relocate_guides(f, movable_edges=f.network.required)
    baseline_route = baseline.network.route(0)
    baseline_route = baseline_route[: int(np.flatnonzero(baseline_route == 1)[0]) + 1]
    obstacle = LineString(coords[-2:])
    assert LineString(baseline.network.coordinates_m[baseline_route]).intersects(obstacle)
    result = relocate_guides(crowded, movable_edges=crowded.network.required)
    route = result.network.route(0)
    route = route[: int(np.flatnonzero(route == 1)[0]) + 1]
    assert LineString(result.network.coordinates_m[route]).disjoint(obstacle)
    assert result.moves[0].amplitude_m > baseline.moves[0].amplitude_m


def test_clear_guides_keep_exact_identity_without_a_special_migration_path() -> None:
    f = fixture(250)
    f = replace(f, hard=HardHeights(np.empty((0, 2)), np.empty(0)))
    result = relocate_guides(f, movable_edges=np.zeros(len(f.network.receivers), dtype=np.bool_))
    assert result.network.identity() == f.network.identity()
    assert not result.moves and result.candidates_checked == 0


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True])
def test_layout_scales_reject_invalid_values(bad: float) -> None:
    with pytest.raises(ValueError):
        LayoutSettings(clearance_m=bad)


def test_mask_and_candidate_work_bounds_are_explicit() -> None:
    f = fixture(250)
    with pytest.raises(ValueError, match="boolean"):
        relocate_guides(f, movable_edges=np.ones(2, dtype=np.bool_))
    with pytest.raises(ValueError, match="boolean"):
        relocate_guides(f, movable_edges=np.ones(len(f.network.receivers), dtype=np.bool_))
    with pytest.raises(ValueError, match="32 amplitudes"):
        LayoutSettings(amplitude_step_m=1)
    with pytest.raises(ValueError, match="256 network nodes"):
        relocate_guides(
            f, movable_edges=f.network.required, settings=LayoutSettings(station_spacing_m=1e-200)
        )
    outside = f.network.coordinates_m.copy()
    outside[0, 1] = -1
    with pytest.raises(ValueError, match="inside the domain"):
        relocate_guides(
            replace(f, network=RiverNetwork(outside, f.network.receivers)),
            movable_edges=f.network.required,
        )


def test_target_avoidance_restores_delivered_capture_without_claiming_bank_acceptance() -> None:
    f = fixture(250)
    layout = relocate_guides(f, movable_edges=f.network.required)
    candidate = replace(f, network=layout.network)
    patch = prepare_patches(candidate, f.source, mode="fresh")
    delivered = patch.deliver()
    for sampler in (patch.sample, delivered.sample):
        metrics, _ = inspect_surface(candidate, patch, sampler, rotated=False)
        assert metrics["common_routing"]["heads_within_1000m_of_authored_outlet"] == 4
        assert metrics["common_routing"]["internal_terminal_count"] == 0
        assert metrics["common_routing"]["interior_stations_not_reaching_coast"] == 0
        for gate in (
            "hard_heights",
            "no_fill",
            "construction_cap",
            "composition_volume",
            "divide",
            "longitudinal_profiles",
        ):
            assert metrics["quality_gates"][gate]
        assert not metrics["quality_gates"]["inward_bank_profiles"]
        assert not all(metrics["quality_gates"].values())


def test_complete_report_preserves_rejected_controls_and_real_geometry(tmp_path: Path) -> None:
    from benchmarks.evolution.layout_comparison import run

    result = run(tmp_path / "layout", figures=False)
    assert result["status"] == "complete"
    assert result["quality_decision"]["status"] == "rejected"
    assert not result["quality_decision"]["production_eligible"]
    assert result["rotation_maximum_ground_difference_m"] <= 0.001
    assert result["rotation_maximum_geometry_difference_m"] <= 1e-6
    assert len(result["rows"]) == 4
    assert result["control_manifest_sha256"] == file_sha256(
        tmp_path / "layout/fixed-guides/comparison.json"
    )
    for row in result["rows"]:
        assert row["repeat_matches"]
        assert len(row["matched_routes"]) == 4
        assert row["bank_probe_counts"]["control"] != row["bank_probe_counts"]["candidate"]
        for name, digest in row["artifact_hashes"].items():
            assert file_sha256(tmp_path / "layout" / row["case"] / name) == digest
        with np.load(tmp_path / "layout" / row["case"] / "fields.npz", allow_pickle=False) as saved:
            assert saved["ground_m"].dtype == np.float32
            assert saved["original_edge_for_node"].dtype == np.int64
    assert not (tmp_path / "layout/incomplete.json").exists()
    with pytest.raises(FileExistsError):
        run(tmp_path / "layout", figures=False)


def test_failed_comparison_has_no_completion_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.evolution import layout_comparison

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("reference execution failed")

    monkeypatch.setattr(layout_comparison, "run_controls", fail)
    with pytest.raises(RuntimeError, match="execution failed"):
        layout_comparison.run(tmp_path / "failed", figures=False)
    assert (tmp_path / "failed/incomplete.json").is_file()
    assert not (tmp_path / "failed/comparison.json").exists()
