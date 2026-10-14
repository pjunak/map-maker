"""Provenance, failure and repeatability controls without the optional engine."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from benchmarks.evolution.evidence import numeric_hash, write_json
from benchmarks.evolution.frozen import GRAPH_ROLE, discover, load_case
from benchmarks.evolution.reconstruction import run
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.domain.evolution import EvolutionGrid


@pytest.fixture
def frozen_worker(tmp_path: Path) -> Path:
    worker = tmp_path / "inputs" / "public-case"
    worker.mkdir(parents=True)
    grid = EvolutionGrid(4000.0, 4000.0, 1000.0)
    ground = np.full(grid.shape, 200.0, dtype=np.float64)
    ground.flat[6], ground.flat[12] = 100.0, 90.0
    receivers = np.full(grid.shape, -1, dtype=np.int64)
    receivers.flat[6] = 12
    arrays = {
        "delivered_elevation_m": ground.astype(np.float32),
        "elevation_0_m": ground,
        "receiver_0": receivers,
        "area_0_m2": np.full(grid.shape, 25_000_000.0),
    }
    state = worker / "states.npz"
    with state.open("xb") as stream:
        np.savez_compressed(stream, allow_pickle=False, **arrays)
    write_json(
        worker / "result.json",
        {
            "status": "complete",
            "id": "public-control",
            "identity": {"engine": "synthetic-test"},
            "snapshots": [{"name": "final"}],
            "grid": {
                **asdict(grid),
                "shape": list(grid.shape),
                "origin_m": [0.0, 0.0],
                "axes": "x right, y down",
            },
            "artifacts": {"states.npz": file_sha256(state)},
            "numeric_hashes": {name: numeric_hash(value) for name, value in arrays.items()},
        },
    )
    return worker


def rewrite_record(worker: Path, record: dict[str, Any]) -> None:
    (worker / "result.json").write_text(json.dumps(record), encoding="utf-8")


def test_loader_keeps_graph_role_and_readonly_input_ownership(frozen_worker: Path) -> None:
    case = load_case(frozen_worker / "result.json")
    assert case.required.sum() == 1
    assert case.receivers.flat[6] == 12
    assert case.ground_m.flat[6] == 100.0
    assert not case.ground_m.flags.writeable
    case.verify_unchanged()
    with (frozen_worker / "states.npz").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="changed"):
        case.verify_unchanged()
    with pytest.raises(ValueError, match="container hash"):
        load_case(frozen_worker / "result.json")


@pytest.mark.parametrize("change", ["incomplete", "numeric", "origin", "delivery"])
def test_loader_rejects_invalid_evidence(frozen_worker: Path, change: str) -> None:
    path = frozen_worker / "result.json"
    record = json.loads(path.read_text())
    if change == "incomplete":
        record["status"] = "failed"
    elif change == "numeric":
        record["numeric_hashes"]["delivered_elevation_m"] = "0" * 64
    elif change == "origin":
        record["grid"]["origin_m"] = [1.0, 0.0]
    else:
        state = frozen_worker / "states.npz"
        with np.load(state, allow_pickle=False) as loaded:
            arrays = {name: loaded[name] for name in loaded.files}
        arrays["delivered_elevation_m"].flat[6] = 999.0
        with state.open("wb") as stream:
            np.savez_compressed(stream, allow_pickle=False, **arrays)
        record["artifacts"]["states.npz"] = file_sha256(state)
        record["numeric_hashes"]["delivered_elevation_m"] = numeric_hash(
            arrays["delivered_elevation_m"]
        )
    rewrite_record(frozen_worker, record)
    with pytest.raises(ValueError):
        load_case(path)


def test_discovery_retains_failed_workers_in_coverage(frozen_worker: Path) -> None:
    failed = frozen_worker.parent / "budget-stop"
    failed.mkdir()
    (failed / "failure.json").write_text('{"status":"failed"}')
    paths, omissions = discover([frozen_worker.parent, frozen_worker])
    assert paths == [(frozen_worker / "result.json").resolve()]
    assert len(omissions) == 1
    assert omissions[0]["reason"] == "failed evolution worker"


def test_complete_repeat_keeps_profiles_sources_and_refuses_overwrite(
    frozen_worker: Path,
    tmp_path: Path,
) -> None:
    first = run([frozen_worker], tmp_path / "first")
    second = run([frozen_worker], tmp_path / "second")
    assert first["status"] == "complete"
    assert first["graph_role"] == GRAPH_ROLE
    a, b = first["rows"][0], second["rows"][0]
    assert a["source_hashes"] == b["source_hashes"]
    assert a["summaries"] == b["summaries"]
    for pair in a["summaries"].values():
        assert pair["bilinear"]["unresolved_routes"] == 1
        assert pair["flow_aligned"]["unresolved_routes"] == 0
        assert pair["bilinear"]["routes"] == pair["flow_aligned"]["routes"] == 1
    assert (tmp_path / "first" / "index.html").is_file()
    assert (tmp_path / "first" / "case-00" / "comparison.png").is_file()
    with pytest.raises(FileExistsError):
        run([frozen_worker], tmp_path / "first")


def test_failed_report_never_publishes_complete_comparison(
    frozen_worker: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("deliberate rendering failure")

    monkeypatch.setattr("benchmarks.evolution.reconstruction.render_pair", fail)
    output = tmp_path / "failure"
    with pytest.raises(RuntimeError, match="deliberate"):
        run([frozen_worker], output)
    assert (output / "incomplete.json").is_file()
    assert not (output / "comparison.json").exists()


def test_source_mutation_during_comparison_blocks_completion(
    frozen_worker: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mutate(*args: object, **kwargs: object) -> None:
        with (frozen_worker / "states.npz").open("ab") as stream:
            stream.write(b"changed")

    monkeypatch.setattr("benchmarks.evolution.reconstruction.render_pair", mutate)
    with pytest.raises(ValueError, match="changed"):
        run([frozen_worker], tmp_path / "mutation")
    assert not (tmp_path / "mutation" / "comparison.json").exists()


def test_crossing_candidate_is_rejected_without_losing_required_coverage(
    frozen_worker: Path,
    tmp_path: Path,
) -> None:
    record = json.loads((frozen_worker / "result.json").read_text())
    state = frozen_worker / "states.npz"
    with np.load(state, allow_pickle=False) as loaded:
        arrays = {name: loaded[name] for name in loaded.files}
    arrays["receiver_0"].flat[7] = 11
    with state.open("wb") as stream:
        np.savez_compressed(stream, allow_pickle=False, **arrays)
    record["artifacts"]["states.npz"] = file_sha256(state)
    record["numeric_hashes"]["receiver_0"] = numeric_hash(arrays["receiver_0"])
    rewrite_record(frozen_worker, record)
    result = run([frozen_worker], tmp_path / "crossing")
    row = result["rows"][0]
    assert row["status"] == "rejected-topology"
    assert row["conflicting_cells"] == (5,)
    assert row["required_edge_count"] == row["required_head_count"] == 2
    assert not (tmp_path / "crossing" / "case-00" / "comparison.png").exists()


def test_changed_measurement_identity_blocks_completion(
    frozen_worker: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def changed_identity() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"source": calls}

    monkeypatch.setattr("benchmarks.evolution.reconstruction.identity", changed_identity)
    with pytest.raises(ValueError, match="Source/runtime identity changed"):
        run([frozen_worker], tmp_path / "source-change")
    assert not (tmp_path / "source-change" / "comparison.json").exists()


def test_physical_comparison_records_constraint_failures_and_retains_every_route(
    frozen_worker: Path, tmp_path: Path,
) -> None:
    from benchmarks.evolution.physical_comparison import run as run_physical

    output = tmp_path / "physical"
    result = run_physical([frozen_worker], output)
    assert result["status"] == "complete"
    assert result["acceptance"] == "research-only; no production promotion"
    row = result["rows"][0]
    assert row["matched_gates"]["25m"]["complete_matched_coverage"]
    assert row["constraints"]["physical"]["anchor_count"] == 0
    assert not row["constraints"]["physical"]["passes_sampled_constraints"]
    assert "cut_violations" in row["failed_gates"]
    assert (output / "comparison.json").is_file()
    assert (output / "case-00" / "geometry.npz").is_file()
    assert (output / "case-00" / "comparison.png").is_file()
    assert not (output / "incomplete.json").exists()
    repeated = run_physical([frozen_worker], tmp_path / "repeated-physical")
    assert row["geometry_array_sha256"] == repeated["rows"][0]["geometry_array_sha256"]
    assert row["summaries"] == repeated["rows"][0]["summaries"]
    with pytest.raises(FileExistsError):
        run_physical([frozen_worker], output)


def test_physical_coverage_compares_identities_not_just_counts() -> None:
    from copy import deepcopy

    from benchmarks.evolution.physical_comparison import matched_gates

    control: dict[str, Any] = {
        "edges": [{"source": 6, "target": 12}],
        "routes": [{"head": 6, "terminal": 12, "maximum_excursion_m": 0.0}],
    }
    candidate = deepcopy(control)
    candidate["routes"][0]["head"] = 7
    assert not matched_gates(control, candidate)["complete_matched_coverage"]
    candidate = deepcopy(control)
    candidate["edges"][0]["target"] = 13
    assert not matched_gates(control, candidate)["complete_matched_coverage"]
    candidate = deepcopy(control)
    candidate["routes"][0]["maximum_excursion_m"] = 11.0
    assert matched_gates(control, candidate)["new_rises_over_10m"] == 1
