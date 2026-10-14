"""Feature snapshot integrity, owned data and metric sampling contracts."""

import io
import json
from collections.abc import Callable
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import numpy as np
import pytest

from benchmarks.evolution.constrained import FittedSurface
from benchmarks.evolution.evidence import numeric_hash
from benchmarks.evolution.feature_archive import read_feature_surface, write_feature_surface
from benchmarks.evolution.feature_surface import FeatureSurface
from benchmarks.evolution.network_fixture import fixture
from benchmarks.evolution.valley_layout import relocate_guides
from benchmarks.evolution.valley_patches import PatchSettings, prepare_patches
from map_maker.terrain.adapters.build import canonical_json


@pytest.fixture(scope="module")
def surface() -> FeatureSurface:
    f = fixture(1000)
    f = replace(f, network=relocate_guides(f, movable_edges=f.network.required).network)
    patch = prepare_patches(
        f, f.source, mode="fresh", settings=PatchSettings(boundary_model="head-mouth")
    )
    return FeatureSurface(patch, f.network, sha256(b"public-test-parent").hexdigest())


def test_snapshot_reopens_without_regeneration_and_is_deterministic(
    surface: FeatureSurface,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = tmp_path / "first", tmp_path / "second"
    doc = write_feature_surface(surface, a)
    assert doc == write_feature_surface(surface, b)
    for name in ("manifest.json", "fields.npz"):
        assert (a / name).read_bytes() == (b / name).read_bytes()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Reopening must not prepare the surface again.")

    monkeypatch.setattr("benchmarks.evolution.valley_patches.prepare_patches", forbidden)
    loaded = read_feature_surface(a, expected_identity=surface.identity())
    assert loaded.identity() == surface.identity()
    assert loaded.parent_identity == surface.parent_identity
    assert loaded.network.identity() == surface.network.identity()
    for key, values in surface.arrays().items():
        np.testing.assert_array_equal(values, loaded.arrays()[key])
        assert not np.shares_memory(values, loaded.arrays()[key])
        with pytest.raises(ValueError):
            loaded.arrays()[key].setflags(write=True)
    with pytest.raises(FileExistsError):
        write_feature_surface(surface, a)
    with pytest.raises(ValueError, match="expected identity"):
        read_feature_surface(a, expected_identity="f" * 64)


def test_snapshot_owns_arrays_and_preserves_source(surface: FeatureSurface) -> None:
    geometry = surface.patch.segments_m.copy()
    heights = surface.patch.source.ground_m.copy()
    source = FittedSurface(surface.grid, heights, {})
    pending = replace(surface.patch, source=source, segments_m=geometry)
    snapshot = FeatureSurface(pending, surface.network, surface.parent_identity)
    before = snapshot.identity()
    geometry[:] = 0
    source.ground_m.setflags(write=True)
    source.ground_m[:] = 0
    assert snapshot.identity() == before == surface.identity()
    assert np.any(snapshot.patch.segments_m)


def test_queries_preserve_batch_order_broadcast_and_overlapping_tiles(
    surface: FeatureSurface,
) -> None:
    rng = np.random.default_rng(987)
    xy = rng.random((2053, 2)) * (surface.grid.width_m, surface.grid.height_m)
    expected = surface.patch.sample(*xy.T)
    for batch in (1, 7, 641, 8192):
        np.testing.assert_array_equal(surface.sample(*xy.T, batch_points=batch), expected)
    order = rng.permutation(len(xy))
    np.testing.assert_array_equal(surface.sample(*xy[order].T), expected[order])
    x = np.linspace(0, surface.grid.width_m, 129)
    y = np.linspace(0, surface.grid.height_m, 97)
    whole = surface.sample(x[None, :], y[:, None])
    left = surface.sample(x[None, :70], y[:, None])
    right = surface.sample(x[None, 60:], y[:, None])
    top = surface.sample(x[None, :], y[:55, None])
    bottom = surface.sample(x[None, :], y[45:, None])
    np.testing.assert_array_equal(left, whole[:, :70])
    np.testing.assert_array_equal(right, whole[:, 60:])
    np.testing.assert_array_equal(left[:, 60:], right[:, :10])
    np.testing.assert_array_equal(top[45:], bottom[:10])
    np.testing.assert_array_equal(surface.sample(x[::2][None, :], y[::2, None]), whole[::2, ::2])
    assert surface.sample(np.array(123.0), np.array(456.0)).shape == ()
    assert surface.sample(np.empty(0), np.empty(0)).shape == (0,)


@pytest.mark.parametrize(
    "x,y",
    [
        (-1.0, 0.0),
        (0.0, -1.0),
        (32001.0, 0.0),
        (0.0, 24001.0),
        (float("nan"), 2.0),
        (1.0, float("inf")),
    ],
)
def test_queries_reject_invalid_metric_coordinates(
    surface: FeatureSurface, x: float, y: float
) -> None:
    with pytest.raises(ValueError, match="inside the metric domain"):
        surface.sample(np.array(x), np.array(y))


def test_queries_reject_work_before_broadcast_materialization(surface: FeatureSurface) -> None:
    with pytest.raises(ValueError, match="262,144"):
        surface.sample(np.zeros((10000, 1)), np.zeros((1, 10000)))
    for batch in (0, 8193, True):
        with pytest.raises(ValueError, match="batch"):
            surface.sample(np.zeros(1), np.zeros(1), batch_points=batch)


def _manifest(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    doc = json.loads((path / "manifest.json").read_bytes())
    change(doc)
    unsigned = {k: v for k, v in doc.items() if k != "manifest_sha256"}
    doc["manifest_sha256"] = sha256(canonical_json(unsigned)).hexdigest()
    (path / "manifest.json").write_bytes(canonical_json(doc))


MANIFEST_CASES: list[tuple[Callable[[dict[str, Any]], None], str]] = [
    (lambda d: d.update(version=2), "Unsupported feature"),
    (lambda d: d.update(version=True), "Unsupported feature"),
    (lambda d: d.update(model="unknown"), "Unsupported feature"),
    (lambda d: d.update(patch_model="unknown"), "patch model"),
    (lambda d: d["frame"].update(units="degrees"), "coordinate frame"),
    (lambda d: d["frame"].update(origin_m=[False, False]), "coordinate frame"),
    (lambda d: d["counts"].update(segments=1000000000), "counts"),
    (lambda d: d["counts"].update(pins=True), "counts"),
    (lambda d: d["grid"].update(spacing_m=True), "finite numbers"),
    (lambda d: d["settings"].update(profile_spacing_m=0), "positive"),
    (lambda d: d["settings"].update(anchor_radius_m=1e-300), "numerical envelope"),
    (lambda d: d.update(parent_identity="bad"), "SHA-256"),
    (lambda d: d.update(parent_identity="f" * 64), "identity mismatch"),
    (lambda d: d["head_transitions"][0].update(head=999), "counts"),
    (lambda d: d.update(unexpected=True), "record fields"),
]


@pytest.mark.parametrize("change,match", MANIFEST_CASES)
def test_manifest_guards(
    surface: FeatureSurface, tmp_path: Path, change: Callable[[dict[str, Any]], None], match: str
) -> None:
    out = tmp_path / "snapshot"
    write_feature_surface(surface, out)
    _manifest(out, change)
    with pytest.raises(ValueError, match=match):
        read_feature_surface(out)


@pytest.mark.parametrize("fault", ["hash", "duplicate", "nonfinite", "oversized", "truncated"])
def test_broken_manifest_fails_before_numeric_decode(
    surface: FeatureSurface,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    out = tmp_path / "snapshot"
    write_feature_surface(surface, out)
    p = out / "manifest.json"
    raw = p.read_bytes()
    if fault == "hash":
        doc = json.loads(raw)
        doc["surface_identity"] = "f" * 64
        raw = canonical_json(doc)
    elif fault == "duplicate":
        raw = b'{"version":1,' + raw[1:]
    elif fault == "nonfinite":
        raw = b'{"nonfinite":NaN}'
    elif fault == "oversized":
        raw = b" " * (256 * 1024 + 1)
    else:
        raw = raw[:100]
    p.write_bytes(raw)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Rejected manifest must not decode numeric data.")

    monkeypatch.setattr("benchmarks.evolution.feature_archive.read_numeric_archive", forbidden)
    with pytest.raises(ValueError):
        read_feature_surface(out)


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "missing",
        "extra",
        "shape",
        "dtype",
        "object",
        "nonfinite",
        "negative-cap",
        "network",
        "trailing",
    ],
)
def test_archive_and_geometry_guards(surface: FeatureSurface, tmp_path: Path, fault: str) -> None:
    out = tmp_path / "snapshot"
    write_feature_surface(surface, out)
    p = out / "fields.npz"
    if fault == "hash":
        p.write_bytes(p.read_bytes()[:-5])
    else:
        with ZipFile(p) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        name = "cap_m"
        a = surface.patch.cap_field.ground_m.copy()
        if fault == "missing":
            members.pop("cap_m.npy")
        elif fault == "extra":
            members["../unwanted.npy"] = b"ignored"
        elif fault == "trailing":
            members["cap_m.npy"] += b"trailing data"
        else:
            if fault == "shape":
                a = a[:-1]
            elif fault == "dtype":
                a = a.astype(np.float64)
            elif fault == "object":
                a = a.astype(object)
            elif fault == "nonfinite":
                a[0, 0] = np.nan
            elif fault == "negative-cap":
                a[0, 0] = -1
            elif fault == "network":
                name = "segments_m"
                a = surface.patch.segments_m.copy()
                a[0, 0, 0] += 1
            stream = io.BytesIO()
            np.lib.format.write_array(stream, a, version=(1, 0), allow_pickle=True)
            members[f"{name}.npy"] = stream.getvalue()
            _manifest(out, lambda d: d["arrays"].update({name: numeric_hash(a)}))
        with ZipFile(p, "w") as archive:
            for key, value in members.items():
                archive.writestr(key, value)
        _manifest(
            out,
            lambda d: d.update(
                archive_bytes=p.stat().st_size, archive_sha256=sha256(p.read_bytes()).hexdigest()
            ),
        )
    with pytest.raises(ValueError):
        read_feature_surface(out)
    assert not (tmp_path / "unwanted.npy").exists()


def test_incomplete_write_cannot_publish_a_readable_snapshot(
    surface: FeatureSurface,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("injected manifest failure")

    monkeypatch.setattr("benchmarks.evolution.feature_archive.write_json", fail)
    out = tmp_path / "snapshot"
    with pytest.raises(OSError, match="injected"):
        write_feature_surface(surface, out)
    assert not (out / "manifest.json").exists()
    with pytest.raises(ValueError, match="missing"):
        read_feature_surface(out)


def test_comparison_retains_actual_ground_gates_and_failed_raster(tmp_path: Path) -> None:
    from benchmarks.evolution.feature_comparison import run

    output = tmp_path / "evidence"
    report = run(output, figures=False)
    assert report["status"] == "complete"
    assert report["quality_decision"]["status"] == "passed-this-fixture-only"
    assert not report["quality_decision"]["production_eligible"]
    assert len(report["rows"]) == 4
    for row in report["rows"]:
        loaded = read_feature_surface(output / row["case"] / "surface")
        assert loaded.identity() == row["surface_identity"]
        assert row["roundtrip_exact"] and row["repeated_files_exact"]
        assert row["dense_banks"]["section_count"] == 575
        assert row["dense_banks"]["inward_uphill_sections"] == 0
        assert row["raster_dense_banks"]["inward_uphill_sections"] > 0
        assert all(row["loaded"]["quality_gates"].values())
        assert row["queries"]["four_tiles_and_halos_exact"]
        assert row["queries"]["order_and_batch_exact"]
        with np.load(output / row["case"] / "checks.npz", allow_pickle=False) as archive:
            for name, expected in row["numeric_hashes"].items():
                assert numeric_hash(archive[name]) == expected


def test_comparison_failure_cannot_publish_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks.evolution.feature_comparison import run

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("injected decoder failure")

    monkeypatch.setattr("benchmarks.evolution.feature_comparison.read_feature_surface", fail)
    output = tmp_path / "evidence"
    with pytest.raises(ValueError, match="injected decoder"):
        run(output, figures=False)
    assert not (output / "comparison.json").exists()
    assert json.loads((output / "incomplete.json").read_bytes())["status"] == "failed"


def test_returned_manifest_cannot_mutate_the_format_contract(
    surface: FeatureSurface,
    tmp_path: Path,
) -> None:
    out = tmp_path / "snapshot"
    manifest = write_feature_surface(surface, out)
    manifest["frame"]["origin_m"][0] = 123
    assert read_feature_surface(out).identity() == surface.identity()
    fresh = write_feature_surface(surface, tmp_path / "second")
    assert fresh["frame"]["origin_m"] == [0, 0]


@pytest.mark.parametrize("fault", ["huge-header", "oversized-member", "duplicate-member"])
def test_hostile_numeric_headers_and_members_are_bounded(
    surface: FeatureSurface,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    out = tmp_path / "snapshot"
    write_feature_surface(surface, out)
    path = out / "fields.npz"
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    if fault == "huge-header":
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(
            header,
            {"descr": "<f4", "fortran_order": False, "shape": (2**40,)},
        )
        evil = header.getvalue()
        members["cap_m.npy"] = evil
        original = np.load

        def guarded(stream: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(stream, io.BytesIO) and stream.getvalue() == evil:
                pytest.fail("A mismatched huge header reached NumPy allocation.")
            return original(stream, *args, **kwargs)

        monkeypatch.setattr("map_maker.terrain.adapters.numeric.np.load", guarded)
    elif fault == "oversized-member":
        # A small compressed file still declares an excessive expanded member.
        members["cap_m.npy"] = b"0" * 1_000_000
    from zipfile import ZIP_DEFLATED

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for key, value in members.items():
            archive.writestr(key, value)
        if fault == "duplicate-member":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("cap_m.npy", members["cap_m.npy"])
    _manifest(
        out,
        lambda d: d.update(
            archive_bytes=path.stat().st_size, archive_sha256=sha256(path.read_bytes()).hexdigest()
        ),
    )
    with pytest.raises(ValueError):
        read_feature_surface(out)


@pytest.mark.parametrize("coordinate", [np.array(1 + 2j), np.array("12"), np.array(True)])
def test_queries_reject_non_real_numeric_inputs(surface: FeatureSurface, coordinate: Any) -> None:
    with pytest.raises(ValueError, match="real numeric"):
        surface.sample(coordinate, np.array(1.0))
