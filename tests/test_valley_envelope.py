"""Cell-interior cap protection and paired raster bank evidence."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from benchmarks.evolution.boundary_comparison import dense_banks
from benchmarks.evolution.evidence import numeric_hash
from benchmarks.evolution.network_fixture import fixture
from benchmarks.evolution.patch_comparison import inspect_surface
from benchmarks.evolution.valley_envelope import (
    CORNERS,
    ENVELOPE_MODEL_ID,
    audit_capacities,
    cell_safe_capacities,
    rectangle_cap,
)
from benchmarks.evolution.valley_layout import relocate_guides
from benchmarks.evolution.valley_patches import PatchSettings, prepare_patches
from benchmarks.evolution.valley_support import prepare_support
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid


@pytest.mark.parametrize(
    "bounds",
    [
        (1250.0, 750.0, 2750.0, 2250.0),
        (1337.0, 821.0, 2643.0, 2193.0),
        (2000.0, 0.0, 3000.0, 4000.0),
        (-500.0, -100.0, 1234.0, 2391.0),
        (1499.0, 1499.0, 1501.0, 1501.0),
    ],
)
def test_capacities_protect_unaligned_edges_corners_and_thin_footprints(
    bounds: tuple[float, float, float, float],
) -> None:
    grid = EvolutionGrid(4000, 4000, 250)
    env = cell_safe_capacities(grid, bounds, limit_m=600, transition_m=2400)
    audit = audit_capacities(grid, env.capacities_m, bounds, limit_m=600, transition_m=2400)
    assert audit["violation_count"] == 0
    assert audit["maximum_excess_m"] <= audit["roundoff_tolerance_m"]
    assert np.all(env.capacities_m >= 0)
    assert not env.capacities_m.flags.writeable
    assert not env.cell_error_m.flags.writeable
    assert not env.constant_cells.flags.writeable
    # Rotation is a separate coordinate transform, not a re-evaluation on
    # the same axes. Outside-domain and off-grid bounds rotate too.
    x0, y0, x1, y1 = bounds
    rotated = cell_safe_capacities(
        grid,
        (4000 - y1, x0, 4000 - y0, x1),
        limit_m=600,
        transition_m=2400,
    )
    np.testing.assert_allclose(env.capacities_m, np.rot90(rotated.capacities_m), atol=1e-10, rtol=0)


def test_clipping_negative_capacity_would_break_the_interior_bound() -> None:
    grid = EvolutionGrid(4000, 4000, 500)
    bounds = (2000.0, 0.0, 3000.0, 4000.0)
    env = cell_safe_capacities(grid, bounds, limit_m=600, transition_m=2400)
    y, x = np.indices(grid.shape, dtype=np.float64) * 500
    nodal = rectangle_cap(x, y, bounds, 600, 2400)
    clipped = nodal.copy()
    for corner in CORNERS:
        clipped[corner] = np.minimum(
            clipped[corner], np.maximum(nodal[corner] - env.cell_error_m, 0)
        )
    # Both alternatives are legal at nodes and fail strictly inside cells.
    for invalid in (nodal, clipped):
        assert np.all(invalid <= nodal)
        audit = audit_capacities(grid, invalid, bounds, limit_m=600, transition_m=2400)
        assert audit["violation_count"] > 0
        assert audit["maximum_excess_m"] > 0.01
    assert (
        audit_capacities(grid, env.capacities_m, bounds, limit_m=600, transition_m=2400)[
            "violation_count"
        ]
        == 0
    )
    assert env.constant_cells.any()
    np.testing.assert_array_equal(env.capacities_m[:, (x[0] >= 2000) & (x[0] <= 3000)], 0)


def test_flat_cap_is_exact_and_allowance_converges_quadratically() -> None:
    previous = None
    for spacing in (1000, 500, 250):
        grid = EvolutionGrid(8000, 4000, spacing)
        env = cell_safe_capacities(
            grid, (2000.0, 0.0, 3000.0, 4000.0), limit_m=600, transition_m=2400
        )
        np.testing.assert_array_equal(env.capacities_m[:, -1], 600)
        if previous is not None:
            assert env.cell_error_m.max() == pytest.approx(previous / 4)
        previous = float(env.cell_error_m.max())


@pytest.mark.parametrize(
    "limit,transition",
    [(0.0, 2400.0), (-1.0, 2400.0), (600.0, 0.0), (float("inf"), 2400.0), (600.0, float("nan"))],
)
def test_bad_scales_fail_before_construction(limit: float, transition: float) -> None:
    with pytest.raises(ValueError, match="physical scales"):
        cell_safe_capacities(
            EvolutionGrid(1000, 1000, 250),
            (0.0, 0.0, 500.0, 500.0),
            limit_m=limit,
            transition_m=transition,
        )


def test_unsupported_geometry_and_work_fail_explicitly() -> None:
    with pytest.raises(ValueError, match="rectangle"):
        cell_safe_capacities(
            EvolutionGrid(1000, 1000, 250), (500.0, 0.0, 0.0, 500.0), limit_m=600, transition_m=2400
        )
    with pytest.raises(ValueError, match="16,384"):
        cell_safe_capacities(
            EvolutionGrid(40000, 40000, 250),
            (0.0, 0.0, 500.0, 500.0),
            limit_m=600,
            transition_m=2400,
        )
    f = fixture(1000)
    with pytest.raises(ValueError, match="fresh"):
        prepare_patches(f, f.source).deliver(envelope="curvature")


def test_tighter_delivery_removes_large_head_artifact_without_relaxing_inputs() -> None:
    f = fixture(250)
    f = replace(f, network=relocate_guides(f, movable_edges=f.network.required).network)
    source = f.source.ground_m.copy()
    patch = prepare_patches(
        f, f.source, mode="fresh", settings=PatchSettings(boundary_model="head-mouth")
    )
    old, candidate = patch.deliver(), patch.deliver(envelope="curvature")
    assert candidate.diagnostics["delivery_envelope"]["model_id"] == ENVELOPE_MODEL_ID
    support = prepare_support(f.source.grid, f.network)
    before, _ = dense_banks(support, old.sample)
    after, _ = dense_banks(support, candidate.sample)
    assert before["maximum_inward_excursion_m"] > 10
    assert after["maximum_inward_excursion_m"] < 1
    assert 0 < after["inward_uphill_sections"] < before["inward_uphill_sections"]
    head = f.network.coordinates_m[f.network.heads()[0]]
    assert candidate.sample(*head) == patch.sample(*head)
    metrics, _ = inspect_surface(f, patch, candidate.sample, rotated=False)
    for gate in (
        "head_capture",
        "no_interior_sinks",
        "divide",
        "hard_heights",
        "no_fill",
        "construction_cap",
        "composition_volume",
        "longitudinal_profiles",
    ):
        assert metrics["quality_gates"][gate]
    assert not metrics["quality_gates"]["inward_bank_profiles"]
    assert not metrics["quality_gates"]["bank_endpoint_support"]
    np.testing.assert_array_equal(source, f.source.ground_m)
    np.testing.assert_array_equal(candidate.ground_m, patch.deliver(envelope="curvature").ground_m)


def test_comparison_saves_matched_inputs_proof_evidence_and_rejected_delivery(
    tmp_path: Path,
) -> None:
    from benchmarks.evolution.envelope_comparison import run

    out = tmp_path / "envelopes"
    report = run(out, figures=False)
    assert report["status"] == "complete"
    assert report["quality_decision"]["status"] == "rejected"
    assert not report["quality_decision"]["production_eligible"]
    assert report["rotation_maximum_ground_difference_m"] <= 0.001
    assert len(report["rows"]) == 4 and len(report["interior_controls"]) == 5
    assert report["interior_controls_sha256"] == file_sha256(out / "interior-controls.npz")
    with np.load(out / "interior-controls.npz", allow_pickle=False) as saved:
        for row in report["interior_controls"]:
            assert numeric_hash(saved[row["case"]]) == row["capacity_sha256"]
            assert row["audit"]["violation_count"] == 0
    for row in report["rows"]:
        assert row["repeat_matches"] and row["matched_bank_count"] == 575
        assert all(row["local"]["quality_gates"].values())
        assert not row["candidate"]["quality_gates"]["dense_inward_bank_profiles"]
        assert row["interior_audit"]["violation_count"] == 0
        assert row["interior_audit"]["sample_count"] > 200000
        for name, digest in row["artifact_hashes"].items():
            assert file_sha256(out / row["case"] / name) == digest
        with np.load(out / row["case"] / "fields.npz", allow_pickle=False) as saved:
            for name, digest in row["numeric_hashes"].items():
                assert numeric_hash(saved[name]) == digest
            assert saved["candidate_ground_m"].dtype == np.float32
            assert saved["candidate_dense_profiles_m"].shape[0] == 575
    assert not (out / "incomplete.json").exists()
    with pytest.raises(FileExistsError):
        run(out, figures=False)


def test_failed_interior_control_does_not_publish_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks.evolution import envelope_comparison

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("interior check failed")

    monkeypatch.setattr(envelope_comparison, "interior_controls", fail)
    with pytest.raises(RuntimeError, match="interior check"):
        envelope_comparison.run(tmp_path / "failed", figures=False)
    assert (tmp_path / "failed/incomplete.json").is_file()
    assert not (tmp_path / "failed/comparison.json").exists()
