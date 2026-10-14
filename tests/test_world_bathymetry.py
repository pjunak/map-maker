# pyright: reportUnknownMemberType=false
"""Physical margin invariants, real water membership and portable scenario contracts."""

import json
from collections.abc import Callable
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from numpy.typing import NDArray
from PIL import Image
from referencing import Registry, Resource

from map_maker.cli import main
from map_maker.terrain.adapters import world_bathymetry as bundle_files
from map_maker.terrain.adapters import world_bathymetry_inputs as input_files
from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.adapters.world_bathymetry_render import BATHYMETRY_LAYERS, render_bathymetry
from map_maker.terrain.adapters.world_svg import parse_world_svg
from map_maker.terrain.application import world_bathymetry as app
from map_maker.terrain.application.world_context import WorldContextRun
from map_maker.terrain.domain.world import WorldAssignment, WorldContinent, WorldFrame, WorldProject
from map_maker.terrain.domain.world_bathymetry import BathymetryInputs, BathymetrySettings
from map_maker.terrain.domain.world_context import WorldContextSettings
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled
from map_maker.terrain.pipeline.world import prepare_world_map
from map_maker.terrain.pipeline.world_bathymetry import (
    bathymetry_values,
    generate_world_bathymetry,
    margin_depth_m,
    sample_water_centres,
)
from map_maker.terrain.pipeline.world_context import generate_world_context
from map_maker.terrain.viewport import MapViewport

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/world/four-shores.bathy.json"


def world(
    body: str = '<path d="M0 90 H360 V180 H0 Z"/>', scale: float = 1, offset: float = 0
) -> WorldProject:
    source = parse_world_svg(
        f'<svg viewBox="{offset} {offset} {360 * scale} {180 * scale}">'
        f'<g transform="translate({offset},{offset}) scale({scale})">{body}</g></svg>',
        "coast.svg",
    )
    return WorldProject(
        "Test coast",
        source,
        WorldFrame((offset, offset, offset + 360 * scale, offset + 180 * scale), 1000),
        (WorldContinent("land", "Land"),),
        tuple(WorldAssignment(f.id, "land", "mainland") for f in source.features),
    )


def test_margin_endpoints_smooth_joins_monotonicity_and_basin_bound() -> None:
    settings = BathymetrySettings()
    x = np.linspace(0, 1000, 10001)
    depth = margin_depth_m(x, settings)
    assert np.all(np.diff(depth) >= 0)
    assert depth.min() == 0 and depth.max() == 4000
    assert margin_depth_m(np.array([0.0, 100.0, 300.0, 1000.0]), settings).tolist() == [
        0,
        200,
        4000,
        4000,
    ]
    for point in (0, 100, 300):
        near = np.array([max(0, point - 1e-5), point, point + 1e-5])
        assert np.max(np.abs(np.diff(margin_depth_m(near, settings)))) < 1e-8
    with pytest.raises(ValueError, match="nonnegative"):
        margin_depth_m(np.array([-1.0]), settings)


@pytest.mark.parametrize("scale,offset", [(1, 0), (0.01, -20), (100, 25000)])
def test_analytic_equatorial_coast_envelope_source_units_seam_and_poles(
    scale: float, offset: float
) -> None:
    project = world(scale=scale, offset=offset)
    context = generate_world_context(prepare_world_map(project), WorldContextSettings(12))
    settings = BathymetrySettings(12, 100, 201.12345, 1000, 4001.654321)
    result = generate_world_bathymetry(context, BathymetryInputs(project, (1,), settings))
    distances = np.deg2rad(np.array([context.grid.latitude_deg(r) for r in range(6)])) * 1000
    analytic = margin_depth_m(distances, settings)[:, None]
    depth = -result.bed_elevation_m[:6].astype(np.float64)
    error = result.distance_depth_error_m[:6].astype(np.float64)
    assert np.all(np.abs(depth - analytic) <= error + 1e-8)
    assert np.all(depth <= analytic + 0.001)  # Float32 rounding only, never false precision.
    assert np.array_equal(result.bed_elevation_m[:6, 0], result.bed_elevation_m[:6, -1])
    assert np.all(np.isnan(result.bed_elevation_m[6:]))
    assert result.sampled_cells == 144 and not result.unsampled_ocean_ids
    for array in (result.centre_water_body, result.bed_elevation_m, result.distance_depth_error_m):
        assert not array.flags.writeable
    again = generate_world_bathymetry(context, result.inputs)
    np.testing.assert_array_equal(again.bed_elevation_m, result.bed_elevation_m)
    assert context.world.project == project


def test_radius_changes_physical_depth_instead_of_using_page_units() -> None:
    settings = BathymetrySettings(12, 1000, 200, 2000, 4000)
    depths: list[float] = []
    for radius in (1000, 2000):
        project = world()
        project = replace(project, frame=replace(project.frame, radius_km=radius))
        context = generate_world_context(prepare_world_map(project), WorldContextSettings(12))
        run = generate_world_bathymetry(context, BathymetryInputs(project, (1,), settings))
        depths.append(float(-run.bed_elevation_m[2, 5]))
    assert depths[1] > depths[0]


@pytest.mark.parametrize("hole", [False, True])
def test_dominant_ocean_cell_never_assigns_depth_to_land_or_another_water(hole: bool) -> None:
    body = (
        '<path fill-rule="evenodd" d="M149 50 H166 V85 H149 Z'
        + (" M156 66 H159 V69 H156 Z" if hole else "")
        + '"/>'
    )
    project = world(body)
    context = generate_world_context(prepare_world_map(project), WorldContextSettings(4))
    assert context.water_body[1, 3] == 1  # Largest area, not point membership.
    inputs = BathymetryInputs(project, (1,), BathymetrySettings(4))
    result = generate_world_bathymetry(context, inputs)
    assert result.centre_water_body[1, 3] == (2 if hole else 0)
    assert np.isnan(result.bed_elevation_m[1, 3])
    if hole:
        lake = generate_world_bathymetry(context, replace(inputs, ocean_ids=(2,)))
        assert np.isfinite(lake.bed_elevation_m[1, 3])
        assert lake.sampled_cells == 1


def test_unsampled_selected_water_is_reported_without_inventing_depths() -> None:
    project = world(
        '<path fill-rule="evenodd" d="M149 50 H166 V85 H149 Z M151 51 H152 V52 H151 Z"/>'
    )
    context = generate_world_context(prepare_world_map(project), WorldContextSettings(4))
    result = generate_world_bathymetry(
        context, BathymetryInputs(project, (2,), BathymetrySettings(4))
    )
    assert result.unsampled_ocean_ids == (2,) and result.sampled_cells == 0
    assert np.isnan(result.bed_elevation_m).all()


@pytest.mark.parametrize("value", [True, 0, -1, float("inf"), float("nan"), 100001, "100"])
def test_invalid_physical_settings_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        BathymetrySettings(shelf_width_km=cast(float, value))
    with pytest.raises(ValueError):
        BathymetrySettings(basin_depth_m=cast(float, value))


@pytest.mark.parametrize("ids", [(), (1, 1), (2, 1), (0,), (-1,), (True,), (2**31,)])
def test_ocean_selection_requires_explicit_distinct_sorted_ids(ids: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        BathymetryInputs(world(), ids)


def test_context_admission_and_cancellation() -> None:
    project = world()
    context = generate_world_context(prepare_world_map(project), WorldContextSettings(4))
    inputs = BathymetryInputs(project, (1,), BathymetrySettings(4))
    for invalid in (
        replace(inputs, world=replace(project, name="Other")),
        replace(inputs, settings=BathymetrySettings(8)),
        replace(inputs, ocean_ids=(99,)),
    ):
        with pytest.raises(ValueError):
            generate_world_bathymetry(context, invalid)
    token = CancellationToken()

    def progress(_fraction: float, _label: str) -> None:
        token.cancel()

    with pytest.raises(GenerationCancelled):
        generate_world_bathymetry(context, inputs, progress, cancellation=token)
    with pytest.raises(GenerationCancelled):
        sample_water_centres(context.world, context.grid, checkpoint=token.checkpoint)


def test_depth_error_is_outward_rounded_and_shore_is_zero() -> None:
    settings = BathymetrySettings(shelf_depth_m=200.123456, basin_depth_m=4000.123456)
    shore = np.linspace(0, 320, 20001)
    selected = np.ones(shore.shape, dtype=np.bool_)
    bed, error = bathymetry_values(shore, 12.5, selected, settings)
    lower = margin_depth_m(np.maximum(0, shore - 12.5), settings)
    upper = margin_depth_m(shore, settings)
    assert np.all(np.abs(-bed.astype(np.float64) - lower) <= error)
    assert np.all(np.abs(-bed.astype(np.float64) - upper) <= error)
    assert np.all(bed[shore <= 12.5] == 0)
    for invalid in (-1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            bathymetry_values(shore, invalid, selected, settings)


@pytest.fixture
def run() -> app.BathymetryRun:
    inputs, _ = input_files.read_bathymetry_inputs(EXAMPLE)
    return app.generate_bathymetry(
        replace(inputs, settings=replace(inputs.settings, latitude_cells=8))
    )


@pytest.fixture
def bundle(run: app.BathymetryRun, tmp_path: Path) -> Path:
    return app.export_bathymetry(run, tmp_path / "ocean")


def rehash(path: Path, name: str | None = None) -> None:
    document = json.loads(path.read_bytes())
    if name:
        file = path.parent / name
        document["outputs"][name] = {"bytes": file.stat().st_size, "sha256": file_sha256(file)}
    document.pop("bathymetry_sha256")
    document["bathymetry_sha256"] = sha256(canonical_json(document)).hexdigest()
    path.write_bytes(canonical_json(document))


def test_roundtrip_bundle_schemas_cli_and_rendering(
    bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    loaded = app.open_bathymetry(bundle.parent)
    assert loaded.result.sampled_cells > 0
    assert not loaded.result.bed_elevation_m.flags.writeable
    for layer in BATHYMETRY_LAYERS:
        with render_bathymetry(loaded.result, MapViewport(), (600, 320), layer) as image:
            assert image.size == (600, 320) and image.mode == "RGB"
    schemas = [json.loads(p.read_bytes()) for p in (ROOT / "schemas/world").glob("*.schema.json")]
    registry = Registry[Any]().with_resources(
        [(s["$id"], Resource.from_contents(s)) for s in schemas]
    )
    for name, data in (
        ("bathymetry-inputs-v1", EXAMPLE.read_bytes()),
        ("bathymetry-v1", bundle.read_bytes()),
    ):
        schema = json.loads((ROOT / f"schemas/world/{name}.schema.json").read_bytes())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, registry=registry).validate(json.loads(data))
    assert main(["world", "inspect-bathymetry", str(bundle)]) == 0
    assert "Verified ocean-depth hypothesis" in capsys.readouterr().out
    assert main(["world", "inspect-bathymetry", str(bundle.parent / "absent")]) == 1


def test_inputs_atomic_save_reopen_and_external_edit_guard(
    run: app.BathymetryRun, tmp_path: Path
) -> None:
    context = WorldContextRun(run.result.context, run.runtime)
    path = tmp_path / "ocean.bathy.json"
    saved = app.save_bathymetry_inputs(run.result.inputs, context, path)
    assert app.open_bathymetry_inputs(path, context) == saved
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="outside"):
        app.save_bathymetry_inputs(saved.inputs, context, path, saved.sha256)
    assert not list(tmp_path.glob(".bathy-*"))
    with pytest.raises(ValueError, match="extension"):
        app.save_bathymetry_inputs(saved.inputs, context, tmp_path / "world.json")
    foreign = replace(saved.inputs, world=replace(saved.inputs.world, name="Other"))
    with pytest.raises(ValueError, match="different world"):
        app.save_bathymetry_inputs(foreign, context, tmp_path / "foreign.bathy.json")
    token = CancellationToken()
    token.cancel()
    with pytest.raises(GenerationCancelled):
        app.open_bathymetry_inputs(path, context, cancellation=token)


INPUT_EDITS: list[Callable[[dict[str, Any]], None]] = [
    lambda d: d.update(version=True),
    lambda d: d.update(version=2),
    lambda d: d.update(extra=1),
    lambda d: d.update(world_sha256="0" * 64),
    lambda d: d.update(ocean_ids=[True]),
    lambda d: d.update(ocean_ids=[2, 1]),
    lambda d: d["settings"].update(latitude_cells=True),
    lambda d: d["settings"].update(basin_depth_m=50),
    lambda d: d["settings"].update(shelf_width_km=True),
]


@pytest.mark.parametrize("edit", INPUT_EDITS)
def test_invalid_input_contract(edit: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(EXAMPLE.read_bytes())
    edit(data)
    with pytest.raises(ValueError):
        input_files.inputs_from_bytes(canonical_json(data))


def test_duplicate_and_oversized_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        input_files.inputs_from_bytes(b'{"version":1,"version":1}')
    monkeypatch.setattr(input_files, "MAX_BATHYMETRY_INPUT_BYTES", 10)
    with pytest.raises(ValueError, match="40 MiB"):
        input_files.inputs_from_bytes(EXAMPLE.read_bytes())


@pytest.mark.parametrize(
    "field", ["centre_water_body", "bed_elevation_m", "distance_depth_error_m", "extra"]
)
def test_rehashed_numeric_payload_cannot_disagree_with_source(bundle: Path, field: str) -> None:
    path = bundle.parent / "bathymetry.npz"
    with np.load(path, allow_pickle=False) as archive:
        arrays: dict[str, NDArray[Any]] = {name: archive[name] for name in archive.files}
    if field == "extra":
        arrays[field] = np.zeros((8, 16))
    else:
        arrays[field].flat[0] = 99999
    np.savez_compressed(path, allow_pickle=False, **arrays)
    rehash(bundle, path.name)
    with pytest.raises(ValueError):
        app.open_bathymetry(bundle)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sampled_cells", True),
        ("sampled_cells", 0),
        ("deepest_sample_m", -100),
        ("unknown", 1),
        ("error_scope", "all-uncertainty"),
    ],
)
def test_rehashed_metadata_rejected(bundle: Path, field: str, value: object) -> None:
    document = json.loads(bundle.read_bytes())
    document[field] = value
    bundle.write_bytes(canonical_json(document))
    rehash(bundle)
    with pytest.raises(ValueError, match="metadata"):
        app.open_bathymetry(bundle)


def test_nested_geography_corruption_and_oversized_preview_rejected(bundle: Path) -> None:
    path = bundle.parent / "geography/geography.npz"
    original = path.read_bytes()
    path.write_bytes(b"broken")
    with pytest.raises(ValueError, match="hash"):
        app.open_bathymetry(bundle)
    path.write_bytes(original)
    with Image.new("RGB", (3, 4)) as image:
        image.save(bundle.parent / "bed.png")
    rehash(bundle, "bed.png")
    with pytest.raises(ValueError, match="dimensions"):
        app.open_bathymetry(bundle)


def test_failed_export_never_publishes_complete_manifest(
    run: app.BathymetryRun, tmp_path: Path
) -> None:
    target = tmp_path / "interrupted"

    def verify() -> None:
        if (target / "manifest.pending").exists():
            raise GenerationCancelled()

    with pytest.raises(GenerationCancelled):
        bundle_files.write_world_bathymetry(run.result, run.runtime, target, verify=verify)
    assert not (target / "bathymetry.json").exists()
    with pytest.raises(FileExistsError):
        app.export_bathymetry(run, target)


def test_old_producer_must_regenerate_geography_and_cli_build(
    run: app.BathymetryRun, tmp_path: Path
) -> None:
    old = dict(run.runtime, package_source_sha256="f" * 64)
    context = WorldContextRun(run.result.context, old)
    new = app.generate_bathymetry(run.result.inputs, context)
    assert new.runtime == run.runtime and new.result.context is not context.context
    with pytest.raises(ValueError, match="Software changed"):
        app.export_bathymetry(replace(run, runtime=old), tmp_path / "relabelled")
    source = tmp_path / "scenario.bathy.json"
    source.write_bytes(canonical_json(input_files.inputs_document(run.result.inputs)))
    assert main(["world", "bathymetry", str(source), "--output", str(tmp_path / "cli")]) == 0
    assert app.open_bathymetry(tmp_path / "cli").result.inputs == run.result.inputs


def test_other_producer_is_inspectable_but_cannot_be_reexported(
    bundle: Path, tmp_path: Path
) -> None:
    geography = bundle.parent / "geography/context.json"
    context_doc = json.loads(geography.read_bytes())
    context_doc["runtime"]["package_source_sha256"] = "f" * 64
    context_doc.pop("context_sha256")
    context_doc["context_sha256"] = sha256(canonical_json(context_doc)).hexdigest()
    geography.write_bytes(canonical_json(context_doc))
    doc = json.loads(bundle.read_bytes())
    doc["runtime"] = context_doc["runtime"]
    bundle.write_bytes(canonical_json(doc))
    rehash(bundle, "geography/context.json")
    loaded = app.open_bathymetry(bundle)
    assert loaded.runtime["package_source_sha256"] == "f" * 64
    with pytest.raises(ValueError, match="Software changed"):
        app.export_bathymetry(loaded, tmp_path / "not-current")
    assert not (tmp_path / "not-current").exists()


def test_numeric_archive_header_and_cancelled_open_are_bounded(bundle: Path) -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(GenerationCancelled):
        app.open_bathymetry(bundle, cancellation=token)
    # A tiny ZIP containing a malicious NPY allocation claim must fail before allocating.
    import io
    from zipfile import ZipFile

    path = bundle.parent / "bathymetry.npz"
    with np.load(path, allow_pickle=False) as saved:
        arrays = {name: saved[name] for name in saved.files}
    header = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        header, {"descr": "<f4", "fortran_order": False, "shape": (10**9, 10**9)}
    )
    with ZipFile(path, "w") as archive:
        for name, array in arrays.items():
            stream = io.BytesIO()
            np.save(stream, array, allow_pickle=False)
            archive.writestr(
                name + ".npy", header.getvalue() if name == "bed_elevation_m" else stream.getvalue()
            )
    rehash(bundle, "bathymetry.npz")
    with pytest.raises(ValueError):
        app.open_bathymetry(bundle)


def test_documented_public_recipe_reopens_at_its_authored_resolution(tmp_path: Path) -> None:
    manifest = app.build_bathymetry(EXAMPLE, tmp_path / "public-example")
    loaded = app.open_bathymetry(manifest)
    assert loaded.result.context.grid.shape == (90, 180)
    assert loaded.result.inputs == input_files.read_bathymetry_inputs(EXAMPLE)[0]
