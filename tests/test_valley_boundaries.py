"""Head/mouth improvements retain matched controls and expose raster losses."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from shapely.geometry import box

from benchmarks.evolution.boundary_comparison import dense_banks
from benchmarks.evolution.constrained import FittedSurface, HardHeights
from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.network_fixture import NetworkFixture, fixture
from benchmarks.evolution.patch_comparison import inspect_surface
from benchmarks.evolution.paths import FloatArray
from benchmarks.evolution.valley_boundaries import BOUNDARY_MODEL_ID, head_transitions
from benchmarks.evolution.valley_comparison import bank_profiles
from benchmarks.evolution.valley_layout import relocate_guides
from benchmarks.evolution.valley_patches import PatchSettings, ValleyPatches, prepare_patches
from benchmarks.evolution.valley_support import ValleySupport, prepare_support
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid


@pytest.fixture(scope="module")
def prepared() -> tuple[NetworkFixture, ValleyPatches]:
    f = fixture(250)
    f = replace(f, network=relocate_guides(f, movable_edges=f.network.required).network)
    return f, prepare_patches(
        f, f.source, mode="fresh", settings=PatchSettings(boundary_model="head-mouth")
    )


def test_head_lift_uses_physical_distance_and_stops_at_first_confluence() -> None:
    coords = np.array([[1000.0, 0.0], [0.0, 0.0], [1000.0, 2000.0], [1000.0, 4000.0]])
    receivers = np.array([2, 2, 3, -1], dtype=np.int64)
    bed = np.array([100.0, 100.0, 50.0, 0.0])
    lower = np.array([110.0, 0.0])
    network = RiverNetwork(coords, receivers)
    edges = np.flatnonzero(network.required)
    pieces = coords[np.column_stack((edges, receivers[edges]))]
    heights = bed[np.column_stack((edges, receivers[edges]))]
    fitted, transitions = head_transitions(network, edges, pieces, heights, lower, 10.0)
    np.testing.assert_array_equal(fitted, [[120.0, 50.0], [100.0, 50.0], [50.0, 0.0]])
    assert len(transitions) == 1
    assert transitions[0].head == 0 and transitions[0].stop_node == 2
    assert transitions[0].length_m == 2000
    np.testing.assert_array_equal(heights, [[100.0, 50.0], [100.0, 50.0], [50.0, 0.0]])
    subdivided = RiverNetwork(
        np.vstack((coords, [[1000.0, 1000.0]])), np.array([4, 2, 3, -1, 2], dtype=np.int64)
    )
    edges = np.flatnonzero(subdivided.required)
    pairs = np.column_stack((edges, subdivided.receivers[edges]))
    fitted, other = head_transitions(
        subdivided,
        edges,
        subdivided.coordinates_m[pairs],
        np.append(bed, 75.0)[pairs],
        lower,
        10.0,
    )
    assert other == transitions
    np.testing.assert_array_equal(fitted, [[120.0, 85.0], [100.0, 50.0], [50.0, 0.0], [85.0, 50.0]])


def test_full_local_sections_pass_without_promoting_the_raster(
    prepared: tuple[NetworkFixture, ValleyPatches],
) -> None:
    f, patch = prepared
    source = f.source.ground_m.copy()
    support = prepare_support(f.source.grid, f.network)
    local, _ = inspect_surface(f, patch, patch.sample, rotated=False)
    dense, _ = dense_banks(support, patch.sample)
    assert all(local["quality_gates"].values())
    assert dense["maximum_step_m"] <= 2.5
    assert dense["inward_uphill_sections"] == 0
    assert dense["maximum_inward_excursion_m"] <= dense["tolerance_m"]
    assert len(support.banks_m) == 575
    assert len(patch.head_transitions) == 1
    assert patch.head_transitions[0].stop_node == 2
    assert not patch.bed_heights_m.flags.writeable
    output = patch.deliver()
    delivered, _ = inspect_surface(f, patch, output.sample, rotated=False)
    assert output.diagnostics["model_id"] == BOUNDARY_MODEL_ID
    assert delivered["quality_gates"]["head_capture"]
    assert delivered["quality_gates"]["hard_heights"]
    assert delivered["quality_gates"]["construction_cap"]
    assert not delivered["quality_gates"]["inward_bank_profiles"]
    assert not delivered["quality_gates"]["bank_endpoint_support"]
    assert not all(delivered["quality_gates"].values())
    np.testing.assert_array_equal(f.source.ground_m, source)
    np.testing.assert_allclose(
        patch.sample(*f.hard.points_m.T), f.hard.heights_m, atol=1e-4, rtol=0
    )


def test_mouth_wedge_is_continuous_and_keeps_the_actual_coast(
    prepared: tuple[NetworkFixture, ValleyPatches],
) -> None:
    f, patch = prepared
    for segment in patch.mouth_segments_m:
        p: FloatArray = segment[0]
        q: FloatArray = segment[1]
        tangent: FloatArray = (p - q) / np.linalg.norm(p - q)
        normal = np.array([-tangent[1], tangent[0]])
        if normal[1] > 0:
            normal *= -1
        bank = q + 500 * normal
        points = bank + np.array([-1e-6, 0.0, 1e-6])[:, None] * tangent
        heights = patch.sample(*points.T)
        assert np.all(heights > 0)
        assert float(np.ptp(heights)) < 1e-4
    x = np.linspace(0, f.source.grid.width_m, 1025)
    np.testing.assert_array_equal(patch.sample(x, np.full_like(x, f.source.grid.height_m)), 0.0)


def test_independent_oblique_mouth_has_inward_banks() -> None:
    grid = EvolutionGrid(4000, 4000, 250)
    y, x = np.indices(grid.shape, dtype=np.float64) * 250
    z = ((4000 - y) / 4000) ** 1.3 * (300 + 0.00004 * (x - 2000) ** 2)
    source = FittedSurface(grid, z.astype(np.float32), {})
    network = RiverNetwork(
        np.array([[1000.0, 1000.0], [2500.0, 4000.0]]), np.array([1, -1], dtype=np.int64)
    )
    f = NetworkFixture(
        source,
        network,
        (),
        box(15, 0, 16, 24),
        np.full(grid.shape, 100.0),
        z,
        HardHeights(np.empty((0, 2)), np.empty(0)),
        100.0,
    )
    patch = prepare_patches(
        f, source, mode="fresh", settings=PatchSettings(boundary_model="head-mouth")
    )
    support = prepare_support(grid, network)
    assert dense_banks(support, patch.sample)[0]["inward_uphill_sections"] == 0
    assert not patch.head_transitions
    output = patch.deliver()
    assert np.all(output.ground_m <= source.ground_m)
    np.testing.assert_array_equal(output.ground_m[-1], 0.0)


def test_dense_check_detects_a_between_station_hump() -> None:
    support = ValleySupport(
        "a" * 64,
        np.array([[0.0, 0.0]]),
        np.array([[500.0, 0.0]]),
        np.array([0], dtype=np.int64),
        np.array([0], dtype=np.int64),
        np.array([1000.0]),
        250.0,
        500.0,
        0.0001,
        0,
    )

    def sampler(x: FloatArray, y: FloatArray) -> np.ndarray[Any, np.dtype[np.float32]]:
        return (10 - 0.0001 * x + 0.02 * np.maximum(1 - np.abs(x - 112.5) / 12.5, 0)).astype(
            np.float32
        )

    assert bank_profiles(support, sampler)["inward_uphill_sections"] == 0
    assert dense_banks(support, sampler)[0]["inward_uphill_sections"] == 1
    with pytest.raises(ValueError, match="sampling budget"):
        dense_banks(replace(support, beds_m=np.array([[10000.0, 0.0]])), sampler)


def test_boundary_model_rejects_unsupported_fixed_or_sharp_modes() -> None:
    f = fixture(1000)
    with pytest.raises(ValueError, match="fresh"):
        prepare_patches(f, f.source, settings=PatchSettings(boundary_model="head-mouth"))
    with pytest.raises(ValueError):
        PatchSettings(boundary_model="head-mouth", cross_section="sharp")


def test_comparison_preserves_controls_dense_evidence_and_delivery_rejection(
    tmp_path: Path,
) -> None:
    from benchmarks.evolution.boundary_comparison import run

    output = tmp_path / "boundaries"
    report = run(output, figures=False)
    assert report["status"] == "complete"
    assert report["quality_decision"]["status"] == "rejected"
    assert not report["quality_decision"]["production_eligible"]
    assert len(report["rows"]) == 4
    assert report["rotation_maximum_ground_difference_m"] <= 0.001
    assert report["control_manifest_sha256"] == file_sha256(output / "controls/comparison.json")
    for row in report["rows"]:
        assert row["repeat_matches"]
        assert row["matched_bank_count"] == 575
        assert all(row["local"]["quality_gates"].values())
        assert not row["delivery"]["quality_gates"]["dense_inward_bank_profiles"]
        assert row["control_dense_bank_sections"]["inward_uphill_sections"] > 0
        assert len(row["bank_witnesses"]) == 3
        for name, digest in row["artifact_hashes"].items():
            assert file_sha256(output / row["case"] / name) == digest
        with np.load(output / row["case"] / "fields.npz", allow_pickle=False) as saved:
            assert saved["ground_m"].dtype == np.float32
            assert saved["local_dense_profiles_m"].shape[0] == row["matched_bank_count"]
    assert not (output / "incomplete.json").exists()
    with pytest.raises(FileExistsError):
        run(output, figures=False)


def test_failed_boundary_comparison_cannot_publish_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks.evolution import boundary_comparison

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("reference failed")

    monkeypatch.setattr(boundary_comparison, "run_controls", fail)
    with pytest.raises(RuntimeError, match="reference failed"):
        boundary_comparison.run(tmp_path / "failed", figures=False)
    assert (tmp_path / "failed/incomplete.json").is_file()
    assert not (tmp_path / "failed/comparison.json").exists()
