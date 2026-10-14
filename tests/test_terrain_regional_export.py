# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false
"""Regional artifacts retain source provenance and never publish partial completion."""

import json
import shutil
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator, ValidationError, validate
from PIL import Image
from referencing import Registry, Resource

from map_maker.cli import main
from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.adapters.project import load_terrain_project, save_terrain_project
from map_maker.terrain.adapters.render import render_ground_map
from map_maker.terrain.application import regional as application
from map_maker.terrain.domain.regional import RegionalSamplingRequest
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled
from map_maker.terrain.pipeline.regional import prepare_regional_sampler

ROOT = Path(__file__).parents[1]
BOUNDS = (100., 100., 200., 200.)


@pytest.fixture
def saved_project(tmp_path: Path) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("coastline.svg", "basin-water.terrain.json"):
        shutil.copyfile(ROOT / "examples" / "terrain" / name, inputs / name)
    path = inputs / "basin-water.terrain.json"
    loaded = load_terrain_project(path)
    save_terrain_project(replace(loaded.project,
                                settings=replace(loaded.project.settings, resolution_px=65)),
                         loaded.coastline_source, path)
    return path


def test_regional_cli_publishes_repeatable_hashed_products(
    saved_project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    inputs_before = {p.name: file_sha256(p) for p in saved_project.parent.iterdir()}
    first, second = tmp_path / "first", tmp_path / "second"
    assert main(["terrain", "sample-region", str(saved_project), "--output", str(first),
                 "--bounds-km", *map(str, BOUNDS), "--refine", "8"]) == 0
    output = capsys.readouterr()
    assert "Regional samples complete" in output.out and not output.err
    application.sample_terrain_region(saved_project, second, BOUNDS, 8)
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    document: dict[str, Any] = json.loads((first / "manifest.json").read_text())
    schemas: list[dict[str, Any]] = [json.loads(p.read_text())
                                    for p in (ROOT / "schemas" / "terrain").glob("*.schema.json")]
    for item in schemas:
        Draft202012Validator.check_schema(item)
    registry = Registry[Any]().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in schemas)
    schema = next(
        s for s in schemas if s["$id"] == "urn:map-maker:schema:terrain-regional-samples:3")
    validate(document, schema, cls=Draft202012Validator, registry=registry)
    for key in ("adds_detail_bands", "conditions_on_parent_dem", "refines_hydrology"):
        assert document["capabilities"][key] is False
        with pytest.raises(ValidationError):
            validate({**document, "capabilities": {**document["capabilities"], key: True}},
                     schema, cls=Draft202012Validator, registry=registry)
    with pytest.raises(ValidationError):
        validate({**document, "outputs": {}}, schema, cls=Draft202012Validator, registry=registry)
    artifact_id = document.pop("artifact_id")
    assert sha256(canonical_json(document)).hexdigest() == artifact_id
    for name, product in document["outputs"].items():
        assert file_sha256(first / name) == product["sha256"]
        assert (first / name).stat().st_size == product["bytes"]
        assert (first / name).read_bytes() == (second / name).read_bytes()
    project = load_terrain_project(saved_project).project
    sampler = prepare_regional_sampler(project.coastline, project.settings,
                                       constraints=project.constraints)
    request = RegionalSamplingRequest.for_bounds(
        sampler.source_id, sampler.reference_grid, BOUNDS, 8)
    samples = sampler.sample(request)
    with np.load(first / "samples.npz", allow_pickle=False) as numeric:
        for key in ("elevation_m", "land_mask", "x_km", "y_km",
                    "water_surface_m", "basin_intent_ids"):
            np.testing.assert_array_equal(numeric[key], getattr(samples, key))
        assert numeric["elevation_m"].dtype == np.dtype("<f4")
        assert numeric["x_km"].dtype == np.dtype("<f8")
        assert numeric["basin_intent_ids"].dtype == np.dtype("<u4")
    rows, columns = request.core_slices
    assert document["core_slice"] == {"rows": [rows.start, rows.stop],
                                      "columns": [columns.start, columns.stop]}
    assert document["request"]["requested_bounds_km"] == list(BOUNDS)
    with (Image.open(first / "scientific.png") as preview,
          render_ground_map(samples.elevation_m, samples.land_mask, request.grid(include_halo=True),
                            samples.maximum_elevation_m) as buffered):
        assert preview.size == (request.grid().width, request.grid().height)
        np.testing.assert_array_equal(np.asarray(preview), np.asarray(buffered)[rows, columns])
        assert preview.info["map-maker.numeric_source_sha256"] == file_sha256(first / "samples.npz")
        assert preview.info["map-maker.water_visibility"] == "none"
    assert {p.name: file_sha256(p) for p in saved_project.parent.iterdir()} == inputs_before


@pytest.mark.parametrize("bounds,refine", [(BOUNDS, 65536),
                                         ((-1., 0., 10., 10.), 2), (BOUNDS, 3),
                                         ((0., 0., float("nan"), 10.), 2)])
def test_invalid_request_rejected_before_global_preparation_or_output(
    bounds: tuple[float, float, float, float], refine: int, saved_project: Path,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Invalid regional requests must fail before expensive work")
    monkeypatch.setattr(application, "prepare_regional_sampler", unexpected)
    destination = tmp_path / "invalid"
    with pytest.raises(ValueError):
        application.sample_terrain_region(saved_project, destination, bounds, refine)
    assert not destination.exists()


@pytest.mark.parametrize("file", [False, True])
def test_existing_destination_is_preserved(
    file: bool, saved_project: Path, tmp_path: Path,
) -> None:
    destination = tmp_path / "existing"
    if file:
        destination.write_text("keep")
    else:
        destination.mkdir()
        (destination / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        application.sample_terrain_region(saved_project, destination, BOUNDS, 2)
    assert (destination if file else destination / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize("changed", ["project", "coastline", "runtime"])
def test_changed_sources_prevent_completion(
    changed: str, saved_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = {"package_source_sha256": "before"}
    monkeypatch.setattr(application, "runtime_identity", lambda: dict(runtime))
    mutated = False
    def progress(_fraction: float, _label: str) -> None:
        nonlocal mutated
        if mutated:
            return
        mutated = True
        if changed == "runtime":
            runtime["package_source_sha256"] = "after"
        else:
            path = (saved_project if changed == "project"
                    else saved_project.with_name("coastline.svg"))
            path.write_bytes(path.read_bytes() + b"\n")
    destination = tmp_path / "changed"
    with pytest.raises(ValueError, match="changed during regional sampling"):
        application.sample_terrain_region(saved_project, destination, BOUNDS, 2, progress=progress)
    assert destination.is_dir() and not (destination / "manifest.json").exists()


def test_failed_export_cannot_publish_completion(
    saved_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_export(*_args: object, **_kwargs: object) -> None:
        raise OSError("Simulated disk failure")
    monkeypatch.setattr(application, "write_regional_products", fail_export)
    destination = tmp_path / "failed"
    with pytest.raises(OSError, match="disk failure"):
        application.sample_terrain_region(saved_project, destination, BOUNDS, 2)
    assert destination.is_dir() and not (destination / "manifest.json").exists()


def test_changed_coastline_rejected_before_output(saved_project: Path, tmp_path: Path) -> None:
    coast = saved_project.with_name("coastline.svg")
    coast.write_bytes(coast.read_bytes() + b"\n")
    destination = tmp_path / "invalid-source"
    with pytest.raises(ValueError, match=r"changed|hash|SHA"):
        application.sample_terrain_region(saved_project, destination, BOUNDS, 2)
    assert not destination.exists()


def test_regional_help_and_error_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["terrain", "sample-region", "--help"])
    assert info.value.code == 0
    assert "adds no detail bands or fine rivers" in capsys.readouterr().out
    assert main(["terrain", "sample-region", str(tmp_path / "missing.json"),
                 "--output", str(tmp_path / "result"), "--bounds-km", "0", "0", "1", "1",
                 "--refine", "2"]) == 1
    output = capsys.readouterr()
    assert "Regional sampling failed" in output.err and not output.out


def test_cancel_after_export_does_not_publish_completion(
    saved_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = CancellationToken()
    writer = application.write_regional_products

    def stop(*args: Any, **kwargs: Any) -> dict[str, object]:
        outputs = writer(*args, **kwargs)
        token.cancel()
        return outputs

    monkeypatch.setattr(application, "write_regional_products", stop)
    destination = tmp_path / "cancelled-export"
    with pytest.raises(GenerationCancelled):
        application.sample_terrain_region(saved_project, destination, BOUNDS, 2, cancellation=token)
    assert destination.is_dir()
    assert not (destination / "manifest.json").exists()
