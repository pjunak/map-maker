"""Completed context consumption, corruption checks and allocation admission."""

import io
import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pytest
from numpy.typing import NDArray

from map_maker.cli import main
from map_maker.terrain.adapters import world_context_load as loader
from map_maker.terrain.adapters.build import canonical_json, file_sha256
from map_maker.terrain.application import world_context as application
from map_maker.terrain.application.world import open_world
from map_maker.terrain.domain.world_context import WorldContextSettings
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled

EXAMPLE = Path(__file__).parents[1] / "examples/world/four-shores.world.json"


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    run = application.generate_context(open_world(EXAMPLE).project, WorldContextSettings(12))
    return application.export_context(run, tmp_path / "context")


def edit_manifest(path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    edit(doc)
    doc.pop("context_sha256")
    doc["context_sha256"] = sha256(canonical_json(doc)).hexdigest()
    path.write_bytes(canonical_json(doc))


def rehash_product(path: Path, name: str) -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc["outputs"][name] = {
            "bytes": (path.parent / name).stat().st_size,
            "sha256": file_sha256(path.parent / name),
        }

    edit_manifest(path, edit)


def test_saved_context_reopens_without_regeneration_and_is_immutable(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def no_generation(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Saved context must load its numeric products without rerunning generation.")

    monkeypatch.setattr(application, "generate_world_context", no_generation)
    run = application.open_context(bundle.parent)
    assert run.context.grid.shape == (12, 24)
    assert run.context.world.project == open_world(EXAMPLE).project
    for array in (
        run.context.land_fraction,
        run.context.water_body,
        run.context.support_flags,
        run.context.east_opening_km,
        run.context.south_opening_km,
        run.context.shore_distance_km,
        run.context.water_exposure,
        run.context.exposure_mixed_support,
    ):
        assert not array.flags.writeable
    assert main(["world", "inspect-context", str(bundle)]) == 0
    assert "Verified context" in capsys.readouterr().out
    assert main(["world", "inspect-context", str(bundle.parent / "missing.json")]) == 1


def test_other_runtime_is_inspectable_but_cannot_be_relabelled_as_current(
    bundle: Path,
    tmp_path: Path,
) -> None:
    edit_manifest(bundle, lambda doc: doc["runtime"].update(package_source_sha256="f" * 64))
    run = application.open_context(bundle)
    assert run.runtime["package_source_sha256"] == "f" * 64
    with pytest.raises(ValueError, match="Software changed"):
        application.export_context(run, tmp_path / "relabelled")
    assert not (tmp_path / "relabelled").exists()


def test_manifest_and_product_hash_changes_are_rejected(bundle: Path) -> None:
    data = bundle.read_bytes()
    bundle.write_bytes(data.replace(b'"columns": 24', b'"columns": 25'))
    with pytest.raises(ValueError, match="fingerprint"):
        application.open_context(bundle)
    bundle.write_bytes(data)
    (bundle.parent / "geography.npz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash verification"):
        application.open_context(bundle)


METADATA_EDITS: list[Callable[[dict[str, Any]], None]] = [
    lambda d: d.update(version=3),
    lambda d: d["shore_distance"].update(sample_count=True),
    lambda d: d["shore_distance"].update(sample_count=500001),
    lambda d: d["shore_distance"].update(max_error_km=-1),
    lambda d: d["exposure"].update(range_km=20),
    lambda d: d["exposure"].update(distance_samples=100000),
    lambda d: d.update(version=True),
    lambda d: d.update(extra="unknown"),
    lambda d: d["connectivity"].update(components=0),
    lambda d: d["connectivity"].update(fragmented_bodies=[1]),
    lambda d: d["connectivity"].update(split_cells=-1),
    lambda d: d["connectivity"].update(registration="cell-centres"),
    lambda d: d["grid"].update(columns=25),
    lambda d: d["settings"].update(latitude_cells=361),
    lambda d: d["settings"].update(latitude_cells=True),
    lambda d: d.update(input_sha256="f" * 64),
    lambda d: d["support"].update(mixed_cells=0),
    lambda d: d["gateways"].update(positive_east_faces=0),
    lambda d: d["areas_km2"].update(land=0),
    lambda d: d["water_bodies"][0].update(displayed_cells=-1),
    lambda d: d["water_bodies"][0].update(area_km2=-1),
    lambda d: d["outputs"].update({"../outside": {"bytes": 1, "sha256": "f" * 64}}),
]


@pytest.mark.parametrize("edit", METADATA_EDITS)
def test_rehashed_inconsistent_metadata_is_rejected(
    bundle: Path,
    edit: Callable[[dict[str, Any]], None],
) -> None:
    edit_manifest(bundle, edit)
    with pytest.raises(ValueError):
        application.open_context(bundle)


@pytest.mark.parametrize(
    "field,value",
    [
        ("land_fraction", float("nan")),
        ("land_fraction", 2.0),
        ("water_body", -1),
        ("support_flags", 255),
        ("latitude_deg", 100),
        ("cell_area_km2", -1),
        ("east_opening_km", -1),
        ("south_opening_km", 1e12),
    ],
)
def test_rehashed_invalid_numeric_payload_is_rejected(
    bundle: Path, field: str, value: float
) -> None:
    path = bundle.parent / "geography.npz"
    with np.load(path, allow_pickle=False) as data:
        arrays: dict[str, NDArray[Any]] = {key: data[key] for key in data.files}
    arrays[field].flat[0] = value
    np.savez_compressed(path, allow_pickle=False, **arrays)
    rehash_product(bundle, path.name)
    with pytest.raises(ValueError):
        application.open_context(bundle)


@pytest.mark.parametrize(
    "problem", ["huge-header", "expanded-entry", "object", "duplicate", "extra"]
)
def test_archive_rejected_before_unsafe_numpy_allocation(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    path = bundle.parent / "geography.npz"
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    key = "land_fraction.npy"
    if problem in ("huge-header", "object"):
        stream = io.BytesIO()
        np.lib.format.write_array_header_1_0(
            stream,
            {
                "descr": "|O" if problem == "object" else "<f8",
                "fortran_order": False,
                "shape": (12, 24) if problem == "object" else (10**9, 10**9),
            },
        )
        entries[key] = stream.getvalue()
    elif problem == "expanded-entry":
        entries[key] = b"0" * 30_000
    elif problem == "extra":
        entries["surprise.npy"] = entries[key]
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        if problem == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                archive.writestr(key, entries[key])
    rehash_product(bundle, path.name)

    def no_load(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Malformed archive/header must fail before NumPy loads arrays.")

    monkeypatch.setattr(np, "load", no_load)
    with pytest.raises(ValueError):
        application.open_context(bundle)


def test_duplicate_json_field_is_rejected(bundle: Path) -> None:
    bundle.write_bytes(bundle.read_bytes().replace(b"{", b'{"version": 2,', 1))
    with pytest.raises(ValueError, match="Duplicate context field"):
        application.open_context(bundle)


def test_changed_bundle_during_load_and_cancellation_are_rejected(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = loader.read_numeric_archive

    def change(*args: Any, **kwargs: Any) -> dict[str, NDArray[Any]]:
        arrays = original(*args, **kwargs)
        (bundle.parent / "land.png").write_bytes(b"changed")
        return arrays

    monkeypatch.setattr(loader, "read_numeric_archive", change)
    with pytest.raises(ValueError, match=r"changed|size"):
        application.open_context(bundle)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(GenerationCancelled):
        application.open_context(bundle, cancellation=token)


@pytest.mark.parametrize(
    "field,value",
    [
        ("shore_distance_km", float("nan")),
        ("shore_distance_km", -1),
        ("shore_distance_km", 1e20),
        ("water_exposure", 1.01),
        ("water_exposure", float("inf")),
        ("exposure_mixed_support", -0.01),
    ],
)
def test_invalid_exposure_products_rejected(bundle: Path, field: str, value: float) -> None:
    path = bundle.parent / "exposure.npz"
    with np.load(path, allow_pickle=False) as data:
        arrays: dict[str, NDArray[Any]] = {key: data[key] for key in data.files}
    arrays[field].flat[0] = value
    np.savez_compressed(path, allow_pickle=False, **arrays)
    rehash_product(bundle, path.name)
    with pytest.raises(ValueError):
        application.open_context(bundle)


def test_exposure_roundtrip_preserves_all_bearings_and_sampling(bundle: Path) -> None:
    restored = application.open_context(bundle).context
    original = application.generate_context(open_world(EXAMPLE).project, WorldContextSettings(12))
    for name in ("shore_distance_km", "water_exposure", "exposure_mixed_support"):
        np.testing.assert_array_equal(getattr(restored, name), getattr(original.context, name))
    assert restored.shore_sampling == original.context.shore_sampling


def test_boundary_only_cells_do_not_publish_phantom_water(tmp_path: Path) -> None:
    run = application.generate_context(open_world(EXAMPLE).project, WorldContextSettings(90))
    context = run.context
    dry = context.water_body == 0
    assert np.all(context.land_fraction[dry] == 1)
    assert np.all(context.support_flags[dry] == 0)
    # Previously 161 full dry cells had fractions 1-1e-16 and mixed-water flags.
    assert context.land_fraction[15, 23] == 1 and context.water_body[15, 23] == 0
    manifest = application.export_context(run, tmp_path / "context-90")
    loaded = application.open_context(manifest)
    np.testing.assert_array_equal(loaded.context.land_fraction, context.land_fraction)
    assert len(loaded.context.water_bodies) == 2


@pytest.mark.parametrize(
    "field",
    [
        "cell_offsets",
        "water_body",
        "area_km2",
        "sample_uv",
        "link_nodes",
        "link_axis",
        "link_interval",
        "link_width_km",
    ],
)
def test_rehashed_water_graph_disagrees_with_actual_source(bundle: Path, field: str) -> None:
    path = bundle.parent / "connectivity.npz"
    with np.load(path, allow_pickle=False) as data:
        arrays = {key: data[key] for key in data.files}
    if field == "link_nodes":
        # A valid node index in the same ocean is still not a valid shared face.
        node = int(arrays[field][0, 0])
        candidates = np.flatnonzero(arrays["water_body"] == arrays["water_body"][node])
        arrays[field][0, 1] = candidates[-1]
    elif field == "link_axis":
        arrays[field][0] = 1 - arrays[field][0]
    else:
        arrays[field].flat[0] += 1
    np.savez_compressed(path, allow_pickle=False, **arrays)
    rehash_product(bundle, path.name)
    with pytest.raises(ValueError, match="connectivity disagrees with source"):
        application.open_context(bundle)


@pytest.mark.parametrize(
    "field,value",
    [("pieces", True), ("pieces", -1), ("pieces", 500001), ("links", 1000001), ("links", 0.5)],
)
def test_graph_size_admission_precedes_numeric_allocation(
    bundle: Path,
    field: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from map_maker.terrain.adapters import world_connectivity as graph_loader

    edit_manifest(bundle, lambda doc: doc["connectivity"].update({field: value}))

    def no_arrays(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Untrusted graph counts must be bounded before allocation.")

    monkeypatch.setattr(graph_loader, "read_numeric_archive", no_arrays)
    with pytest.raises(ValueError, match="connectivity count"):
        application.open_context(bundle)


def test_graph_header_size_is_checked_before_numpy_decoding(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = bundle.parent / "connectivity.npz"
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        stream,
        {
            "descr": "<i4",
            "fortran_order": False,
            "shape": (10**9,),
        },
    )
    entries["cell_offsets.npy"] = stream.getvalue()
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    rehash_product(bundle, path.name)

    def no_load(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Malformed graph headers must be rejected before np.load.")

    # Geography is decoded earlier, so guard only the graph's bounded reader.
    from map_maker.terrain.adapters import world_connectivity as graph_loader

    reader = graph_loader.read_numeric_archive

    def guarded(*args: Any, **kwargs: Any) -> Any:
        monkeypatch.setattr(np, "load", no_load)
        return reader(*args, **kwargs)

    monkeypatch.setattr(graph_loader, "read_numeric_archive", guarded)
    with pytest.raises(ValueError):
        application.open_context(bundle)
