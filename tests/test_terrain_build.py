# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false
import json
import shutil
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import rasterio
from jsonschema import Draft202012Validator, ValidationError, validate
from numpy.typing import NDArray
from PIL import Image
from referencing import Registry, Resource

from map_maker.cli import main
from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.adapters.project import load_terrain_project, save_terrain_project
from map_maker.terrain.application import build as build_module
from map_maker.terrain.domain.seeds import RELIEF_STAGE_ID, SEED_POLICY_ID, stage_seed
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled
from map_maker.terrain.pipeline.generate import generate_terrain

EXAMPLES = Path(__file__).parents[1] / "examples" / "terrain"


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("coastline.svg", "example.terrain.json"):
        shutil.copyfile(EXAMPLES / name, inputs / name)
    path = inputs / "example.terrain.json"
    loaded = load_terrain_project(path)
    project = replace(
        loaded.project,
        settings=replace(loaded.project.settings, resolution_px=64),
    )
    save_terrain_project(project, loaded.coastline_source, path)
    return path


def test_headless_build_preserves_dem_and_has_repeatable_verified_products(
    project_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_project = project_path.read_bytes()
    loaded = load_terrain_project(project_path)
    original_svg = loaded.coastline_source.path.read_bytes()
    expected = generate_terrain(
        loaded.project.coastline, loaded.project.settings, constraints=loaded.project.constraints
    )
    first, second = tmp_path / "first", tmp_path / "second"
    assert main(["terrain", "build", str(project_path), "--output", str(first)]) == 0
    assert "Terrain build complete" in capsys.readouterr().out
    build_module.build_terrain_project(project_path, second)
    document: dict[str, Any] = json.loads((first / "manifest.json").read_text())
    schema_dir = EXAMPLES.parents[1] / "schemas" / "terrain"
    assert document["schema_version"] == 20
    assert document["inputs"]["project_schema_version"] == 9
    assert document["algorithms"]["seed_policy"] == SEED_POLICY_ID
    resolved_seed = stage_seed(loaded.project.settings.seed, RELIEF_STAGE_ID)
    assert document["algorithms"]["stage_seeds"] == {
        RELIEF_STAGE_ID: resolved_seed,
        "terrain.landforms": stage_seed(loaded.project.settings.seed, "terrain.landforms"),
    }
    schemas: list[dict[str, Any]] = [
        json.loads(path.read_text()) for path in sorted(schema_dir.glob("*.schema.json"))
    ]
    for item in schemas:
        Draft202012Validator.check_schema(item)
    registry = Registry[Any]().with_resources(
        (item["$id"], Resource.from_contents(item)) for item in schemas
    )
    schema = next(
        item for item in schemas
        if item["$id"] == "urn:map-maker:schema:terrain-build:20"
    )
    validate(document, schema, cls=Draft202012Validator, registry=registry)
    invalid = {**document, "coordinates": {**document["coordinates"], "world_crs": "EPSG:4326"}}
    with pytest.raises(ValidationError):
        validate(invalid, schema, cls=Draft202012Validator, registry=registry)
    missing_dem = {
        **document,
        "outputs": {
            key: value for key, value in document["outputs"].items() if key != "elevation.npy"
        },
    }
    with pytest.raises(ValidationError):
        validate(missing_dem, schema, cls=Draft202012Validator, registry=registry)
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    build_id = document.pop("build_id")
    assert sha256(canonical_json(document)).hexdigest() == build_id
    assert document["status"] == "complete"
    for name, product in document["outputs"].items():
        assert file_sha256(first / name) == product["sha256"]
        assert (first / name).stat().st_size == product["bytes"]
        assert (first / name).read_bytes() == (second / name).read_bytes()
    elevation = np.load(first / "elevation.npy", allow_pickle=False)
    assert elevation.dtype == np.dtype("<f4")
    assert np.array_equal(elevation, expected.elevation_m, equal_nan=True)
    assert np.array_equal(np.load(first / "land-mask.npy"), expected.land_mask)
    assert np.array_equal(np.load(first / "x-km.npy"), expected.x_km)
    assert np.array_equal(np.load(first / "y-km.npy"), expected.y_km)
    assert np.isnan(elevation[~expected.land_mask]).all()
    with cast(Any, rasterio.open(first / "elevation.tif")) as raster:
        assert raster.read(1).tobytes() == elevation.tobytes()
        assert raster.tags()["numeric_source_sha256"] == file_sha256(first / "elevation.npy")
        assert document["geotiff"]["affine_m"] == list(raster.transform)[:6]
        assert document["geotiff"]["bounds_m"] == list(raster.bounds)
    assert document["runtime"]["gdal"]
    assert document["runtime"]["proj"]
    missing_tiff = {
        **document,
        "outputs": {key: value for key, value in document["outputs"].items()
                    if key != "elevation.tif"},
    }
    with pytest.raises(ValidationError):
        validate(missing_tiff, schema, cls=Draft202012Validator, registry=registry)

    assert document["coordinates"]["world_crs"] is None
    assert document["coordinates"]["registration"] == "endpoint-nodes"
    assert document["routing_grid"]["width"] == expected.routing_grid_shape[1]
    assert document["routing_grid"]["width"] != document["coordinates"]["width"]
    diagnostics: dict[str, Any] = json.loads((first / "diagnostics.json").read_text())
    assert diagnostics["elevation_sha256"] == file_sha256(first / "elevation.npy")
    assert diagnostics["delivered_surface_quality"]["land_sample_count"] == int(
        expected.land_mask.sum()
    )
    with np.load(first / "routing.npz", allow_pickle=False) as routing:
        np.testing.assert_array_equal(routing["receivers"], expected.routing.receivers)
        np.testing.assert_array_equal(routing["source_elevation_m"],
                                      expected.routing.source_elevation_m)
        np.testing.assert_array_equal(routing["final_elevation_m"],
                                      expected.routing_final_elevation_m)
        np.testing.assert_array_equal(routing["land_mask"], expected.routing_land_mask)
        np.testing.assert_array_equal(routing["incision_limit_m"],
                                      expected.routing.incision_limit_m)
        assert np.all(routing["incision_m"] <= routing["incision_limit_m"])
        for key, value in (
            ("channel_conflict_flags", expected.routing_conflicts.flags),
            ("channel_rise_m", expected.routing_conflicts.rise_m),
            ("receiver_cut_deficit_m", expected.routing_conflicts.receiver_cut_deficit_m),
            ("final_adjustment_rise_m", expected.routing_conflicts.final_adjustment_rise_m),
            ("final_fill_depth_m", expected.routing_conflicts.final_fill_depth_m),
            ("conditioned_final_elevation_m", expected.drainage.filled_elevation_m),
            ("conditioned_final_receivers", expected.drainage.receivers),
            ("basin_labels", expected.drainage.basin_labels),
            ("nonland_class", expected.drainage.nonland_class),
            ("boundary_flags", expected.drainage.boundary_flags),
        ):
            np.testing.assert_array_equal(routing[key], value)
        assert routing["x_km"].size == expected.routing_grid.width
    assert diagnostics["channel_conflicts"]["algorithm_id"] == "planned-channel-context@1"
    assert diagnostics["channel_conflicts"]["uphill_edge_count"] == (
        expected.routing_agreement.uphill_channel_edge_count
    )
    canonical = diagnostics["canonical_drainage"]
    assert canonical["algorithm_id"] == "canonical-d8-priority-flood-diagnostics@4"
    assert canonical["grid_width"] == expected.routing_grid.width
    assert canonical["grid_height"] == expected.routing_grid.height
    for candidate, record in zip(expected.drainage.summary.basin_candidates,
                                 canonical["basin_candidates"], strict=True):
        assert record["basin_id"] == candidate.basin_id
        assert record["outlet"]["spill_flat_index"] == candidate.outlet.spill_flat_index
        assert record["outlet"]["spill_elevation_m"] == candidate.outlet.spill_elevation_m
    assert diagnostics["routing_sha256"] == file_sha256(first / "routing.npz")
    assert diagnostics["routing_agreement"]["algorithm_id"] == "planned-final-d8-agreement@2"
    for missing_name in ("routing.npz", "drainage.png", "water.npz", "basin-flow.npz"):
        incomplete = {**document, "outputs": {
            key: value for key, value in document["outputs"].items() if key != missing_name
        }}
        with pytest.raises(ValidationError):
            validate(incomplete, schema, cls=Draft202012Validator, registry=registry)
    with Image.open(first / "drainage.png") as review:
        assert review.width > 2 * expected.routing_grid.width
        assert review.height > expected.routing_grid.height
    with Image.open(first / "scientific.png") as preview:
        assert preview.size == (expected.width, expected.height)
        assert preview.info["map-maker.render_style"] == "scientific"
    assert project_path.read_bytes() == original_project
    assert loaded.coastline_source.path.read_bytes() == original_svg


def test_existing_destination_is_rejected_without_generation_or_changes(
    project_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "authored.txt"
    sentinel.write_text("keep")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Existing output should be rejected before generation.")

    monkeypatch.setattr(build_module, "generate_terrain", forbidden)
    with pytest.raises(FileExistsError):
        build_module.build_terrain_project(project_path, output)
    assert sentinel.read_text() == "keep"
    assert list(output.iterdir()) == [sentinel]


def test_failed_export_never_publishes_completion(
    project_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_export(*args: object, **kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(build_module, "write_build_products", fail_export)
    output = tmp_path / "failed"
    with pytest.raises(OSError, match="simulated disk failure"):
        build_module.build_terrain_project(project_path, output)
    assert output.is_dir()
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("edited_input", ["project", "svg"])
def test_mid_build_input_edit_rejects_completion(
    project_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edited_input: str,
) -> None:
    original_writer = build_module.write_build_products
    edited_path = (
        project_path
        if edited_input == "project"
        else load_terrain_project(project_path).coastline_source.path
    )

    def mutate(*args: Any, **kwargs: Any) -> dict[str, object]:
        result = original_writer(*args, **kwargs)
        with edited_path.open("a") as stream:
            stream.write("\n")
        return result

    monkeypatch.setattr(build_module, "write_build_products", mutate)
    output = tmp_path / "changed"
    with pytest.raises(ValueError, match="changed during the build"):
        build_module.build_terrain_project(project_path, output)
    assert not (output / "manifest.json").exists()


def test_source_identity_change_rejects_completion(
    project_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def identity() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"source_revision": calls}

    monkeypatch.setattr(build_module, "runtime_identity", identity)
    output = tmp_path / "source-changed"
    with pytest.raises(ValueError, match="Generator source or runtime changed"):
        build_module.build_terrain_project(project_path, output)
    assert not (output / "manifest.json").exists()


def test_manifest_publication_failure_leaves_only_pending_manifest(
    project_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from map_maker.terrain.adapters import build as artifact_module

    def fail_publish(source: Path, target: Path) -> None:
        raise OSError("simulated publication failure")

    monkeypatch.setattr(artifact_module.os, "replace", fail_publish)
    output = tmp_path / "publication-failed"
    with pytest.raises(OSError, match="simulated publication failure"):
        build_module.build_terrain_project(project_path, output)
    assert (output / ".manifest.pending").is_file()
    assert not (output / "manifest.json").exists()


def test_cli_build_reports_missing_input_without_completion(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "output"
    assert main(["terrain", "build", str(tmp_path / "missing.json"), "--output", str(output)]) == 1
    assert "Terrain build failed" in capsys.readouterr().err
    assert not output.exists()


def test_geotiff_failure_cannot_publish_a_completed_build(
    project_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from map_maker.terrain.adapters import build as artifact_module

    def fail_geotiff(*args: object, **kwargs: object) -> None:
        raise OSError("simulated GeoTIFF failure")

    monkeypatch.setattr(artifact_module, "write_terrain_geotiff", fail_geotiff)
    output = tmp_path / "failed-tiff"
    with pytest.raises(OSError, match="simulated GeoTIFF failure"):
        build_module.build_terrain_project(project_path, output)
    assert (output / "elevation.npy").exists()
    assert not (output / "manifest.json").exists()


def test_authored_water_build_keeps_ground_and_water_separate_and_repeatable(
    tmp_path: Path,
) -> None:
    loaded = load_terrain_project(EXAMPLES / "basin-water.terrain.json")
    project = replace(loaded.project, settings=replace(loaded.project.settings, resolution_px=65))
    path = tmp_path / "water.terrain.json"
    save_terrain_project(project, loaded.coastline_source, path)
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output in outputs:
        build_module.build_terrain_project(path, output)
    first, second = outputs
    assert (first / "water.npz").read_bytes() == (second / "water.npz").read_bytes()
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    bed = np.load(first / "elevation.npy", allow_pickle=False)
    with np.load(first / "water.npz", allow_pickle=False) as water:
        wet = np.isfinite(water["surface_m"])
        assert wet.any()
        np.testing.assert_array_equal(water["surface_m"][wet], 750)
        np.testing.assert_array_equal(water["depth_m"][wet], 750 - bed[wet])
        np.testing.assert_array_equal(water["depth_m"][~wet], 0)
        assert np.all(water["intent_ids"][wet] > 0)
        assert np.all(bed[wet] < 750)
    diagnostics = json.loads((first / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["water_sha256"] == file_sha256(first / "water.npz")
    assert diagnostics["basin_flow_sha256"] == file_sha256(first / "basin-flow.npz")
    assert (first / "basin-flow.npz").read_bytes() == (second / "basin-flow.npz").read_bytes()
    assert abs(diagnostics["basin_outflow"]["area_balance_error_km2"]) < 1e-6
    with np.load(first / "basin-flow.npz", allow_pickle=False) as flow:
        assert not flow["source_km2"].any()
        assert not flow["throughput_km2"].any()
        assert not flow["terminal_km2"].any()
        assert not flow["flat_rank"].any()
        np.testing.assert_array_equal(flow["internal_receivers"], -1)
        classes: NDArray[np.uint8] = flow["catchment_class"]
        assert classes.dtype == np.uint8
        assert set(np.unique(classes)) == {0, 1}
        assert flow["retained_km2"].sum() == pytest.approx(
            diagnostics["basin_outflow"]["retained_area_km2"])
    records = diagnostics["authored_water"]["basins"]
    assert len(records) == 2
    with np.load(first / "routing.npz", allow_pickle=False) as routing:
        retained = routing["basin_intent_ids"] > 0
        assert retained.any()
        np.testing.assert_array_equal(routing["retention_terminal_mask"], retained)
        np.testing.assert_array_equal(routing["receivers"][retained], -1)
        assert all(record["planned_exit_edge_count"] == 0 for record in records)
        assert all(record["retained_contributing_area_km2"] > 0 for record in records)
        np.testing.assert_array_equal(routing["incision_m"][retained], 0)
        np.testing.assert_array_equal(routing["incision_limit_m"][retained], 0)


@pytest.mark.parametrize("example", ["connected-outlet", "flat-outlet"])
def test_connected_outlet_build_exports_conserved_source_and_terminal_area(
    tmp_path: Path, example: str,
) -> None:
    loaded = load_terrain_project(EXAMPLES / f"{example}.terrain.json")
    project = replace(loaded.project, settings=replace(loaded.project.settings, resolution_px=65))
    path = tmp_path / "outlet.terrain.json"
    save_terrain_project(project, loaded.coastline_source, path)
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output in outputs:
        build_module.build_terrain_project(path, output)
    first, second = outputs
    for name in ("manifest.json", "basin-flow.npz", "diagnostics.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    diagnostics = json.loads((first / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["basin_outflow"]["connected_outlet_count"] == 1
    assert diagnostics["basin_flow_sha256"] == file_sha256(first / "basin-flow.npz")
    with np.load(first / "basin-flow.npz", allow_pickle=False) as flow:
        amount = flow["source_km2"].sum()
        assert amount > 0
        assert flow["terminal_km2"].sum() == pytest.approx(amount)
        assert flow["source_km2"].dtype == np.float64
        assert np.count_nonzero(flow["terminal_km2"]) == 1
        assert np.count_nonzero(flow["throughput_km2"]) > 2
        assert set(flow.files) == {"internal_receivers", "flat_rank", "internal_path_uphill_m",
                                   "catchment_class",
                                   "retained_km2", "source_km2", "throughput_km2", "terminal_km2"}
        assert flow["internal_receivers"].dtype == np.int64
        assert flow["flat_rank"].dtype == np.uint32
        assert flow["internal_path_uphill_m"].dtype == np.float64
        assert np.isfinite(flow["internal_path_uphill_m"]).all()
        assert np.all(flow["internal_path_uphill_m"][flow["catchment_class"] >= 2] <= .01)
        if example == "flat-outlet":
            assert np.count_nonzero(flow["flat_rank"]) > 100
        assert np.all(flow["internal_receivers"][flow["flat_rank"] > 0] >= 0)
        classes: NDArray[np.uint8] = flow["catchment_class"]
        assert classes.dtype == np.uint8
        assert set(np.unique(classes)) == {0, 1, 2, 3}
        with np.load(first / "routing.npz", allow_pickle=False) as routing:
            inside = routing["basin_intent_ids"] > 0
            np.testing.assert_array_equal(classes > 0, inside)
            np.testing.assert_array_equal(flow["retained_km2"] + flow["source_km2"],
                np.where(inside, routing["accumulation_km2"], 0.))
        np.testing.assert_array_equal(flow["source_km2"] > 0, classes >= 2)
        np.testing.assert_array_equal(flow["retained_km2"] > 0, classes == 1)
        assert flow["retained_km2"].sum() == pytest.approx(
            diagnostics["basin_outflow"]["retained_area_km2"])
    lake = next(record for record in diagnostics["authored_water"]["basins"]
                if record["source"]["kind"] == "lake")
    assert lake["outlet_ground_minus_water_m"] == pytest.approx(
        lake["outlet_elevation_m"] - lake["source"]["water_level_m"])
    assert lake["outlet_ground_minus_water_m"] < 0
    assert "outlet_below_water" in lake["issues"]
    shoreline = lake["shoreline"]
    assert shoreline["profile"]["status"] == "sampled"
    assert len(shoreline["profile"]["positions_km"]) > 1000
    assert len(shoreline["profile"]["ground_m"]) == len(shoreline["profile"]["positions_km"])
    assert shoreline["uncontrolled_low_sample_count"] == 0
    assert diagnostics["authored_water"]["sampling_algorithm_id"] == (
        "feature-guided-float32-water-checks@4")
    for profile in (shoreline["profile"], lake["outlet_route"]["connection_profile"]):
        assert 0 < profile["feature_sample_count"] < profile["requested_sample_count"]
        assert 0 < profile["feature_spacing_limit_km"] < profile["spacing_limit_km"]
    connection = lake["outlet_route"]["connection_profile"]
    assert connection["status"] == "sampled"
    assert connection["maximum_ground_m"] == max(connection["ground_m"])
    assert connection["maximum_ground_m"] <= lake["source"]["water_level_m"] + .01
    maximum_index = connection["ground_m"].index(connection["maximum_ground_m"])
    assert connection["positions_km"][maximum_index] == connection["maximum_position_km"]
    downstream = lake["outlet_route"]["downstream"]
    assert downstream["reaches_terminal"]
    assert downstream["maximum_uphill_excursion_m"] == 0
    assert downstream["rise_from_sample_index"] is downstream["rise_to_sample_index"] is None
    profile = downstream["profile"]
    assert profile["status"] == "sampled"
    nodes = lake["outlet_route"]["path_flat_indices"]
    samples = downstream["path_vertex_sample_indices"]
    assert len(profile["positions_km"]) > len(nodes) == len(samples)
    with np.load(first / "routing.npz", allow_pickle=False) as routing:
        width = routing["final_elevation_m"].shape[1]
        for node, sample in zip(nodes, samples, strict=True):
            row, column = divmod(node, width)
            assert profile["positions_km"][sample] == [
                routing["x_km"][column], routing["y_km"][row]]
            assert profile["ground_m"][sample] == routing["final_elevation_m"][row, column]
    links = lake["wet_links"]
    assert links["status"] == "sampled"
    assert links["contact_reachable_wet_cell_count"] == lake["wet_cell_count"]
    assert links["candidate_link_count"] == len(links["links"]) > 0
    assert links["requested_sample_count"] == sum(link["sample_count"] for link in links["links"])
    with np.load(first / "routing.npz", allow_pickle=False) as routing:
        for link in links["links"]:
            assert link["first_flat_index"] < link["second_flat_index"]
            for node in (link["first_flat_index"], link["second_flat_index"]):
                assert routing["basin_intent_ids"].ravel()[node] == lake["intent_id"]
                assert routing["final_elevation_m"].ravel()[node] < lake["source"]["water_level_m"]

    dry = lake["dry_links"]
    assert dry["status"] == "sampled"
    assert dry["candidate_link_count"] == len(dry["links"]) > 1000
    assert dry["requested_sample_count"] == sum(link["sample_count"] for link in dry["links"])
    assert dry["blocked_link_count"] == sum(link["blocked"] for link in dry["links"]) > 0
    with np.load(first / "basin-flow.npz", allow_pickle=False) as flow:
        selected = flow["internal_receivers"].ravel()
        for link in dry["links"]:
            a, b = link["source_flat_index"], link["target_flat_index"]
            if link["blocked"]:
                assert selected[a] != b and selected[b] != a


def test_cancel_after_export_does_not_publish_completion(
    project_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = CancellationToken()
    writer = build_module.write_build_products

    def stop(*args: Any, **kwargs: Any) -> dict[str, object]:
        outputs = writer(*args, **kwargs)
        token.cancel()
        return outputs

    monkeypatch.setattr(build_module, "write_build_products", stop)
    destination = tmp_path / "cancelled-export"
    with pytest.raises(GenerationCancelled):
        build_module.build_terrain_project(project_path, destination, cancellation=token)
    assert destination.is_dir()
    assert not (destination / "manifest.json").exists()
