"""Bounded current-format feature snapshots, separate from product build formats."""

import io
import json
from dataclasses import asdict, fields
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, cast
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import numpy as np

from benchmarks.evolution.constrained import FittedSurface, HardHeights
from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.feature_surface import FEATURE_MODEL_ID, FeatureSurface, digest
from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.valley_boundaries import HeadTransition
from benchmarks.evolution.valley_patches import PatchSettings, ValleyPatches
from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.adapters.numeric import read_numeric_archive
from map_maker.terrain.domain.evolution import EvolutionGrid

FORMAT = "map-maker.experimental.feature-surface"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARRAY_BYTES = 8 * 1024 * 1024


def _frame() -> dict[str, object]:
    return {"origin_m": [0, 0], "axes": "x-right-y-down", "units": "metres"}


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Feature records must be JSON objects.")
    record = cast(dict[str, Any], value)
    if set(record) != keys:
        raise ValueError("Feature record fields do not match the current contract.")
    return record


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate feature field: {key}.")
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise ValueError(f"Nonfinite feature JSON value: {value}.")


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("Feature quantities must be finite numbers, not booleans.")
    return cast(float, value)


def _count(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Feature counts exceed the bounded current contract.")
    return value


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Feature file is missing or linked: {path.name}.")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError(f"Feature file is empty or oversized: {path.name}.")
    return data


def _specs(grid: EvolutionGrid, counts: dict[str, Any]) -> dict[str, tuple[tuple[int, ...], str]]:
    n = _count(counts["segments"], 1, 2048)
    pins = _count(counts["pins"], 0, 16)
    mouths = _count(counts["mouths"], 1, 256)
    nodes = _count(counts["nodes"], 2, 256)
    return {
        "segments_m": ((n, 2, 2), "<f8"),
        "bed_heights_m": ((n, 2), "<f8"),
        "anchor_corrections_m": ((pins,), "<f8"),
        "mouth_segments_m": ((mouths, 2, 2), "<f8"),
        "mouth_heights_m": ((mouths,), "<f8"),
        "mouth_inward": ((mouths, 2), "<f8"),
        "source_m": (grid.shape, "<f4"),
        "cap_m": (grid.shape, "<f4"),
        "hard_points_m": ((pins, 2), "<f8"),
        "hard_heights_m": ((pins,), "<f8"),
        "coordinates_m": ((nodes, 2), "<f8"),
        "receivers": ((nodes,), "<i8"),
    }


def write_feature_surface(surface: FeatureSurface, output: Path) -> dict[str, Any]:
    """Write a new directory, publishing its manifest only after complete numeric data."""
    p = surface.patch
    counts = {
        "segments": len(p.segments_m),
        "pins": len(p.hard.heights_m),
        "mouths": len(p.mouth_heights_m),
        "nodes": len(surface.network.receivers),
    }
    specs = _specs(surface.grid, counts)
    arrays = {k: np.asarray(v, dtype=specs[k][1]) for k, v in surface.arrays().items()}
    raw = io.BytesIO()
    # Fixed member order/timestamps and canonical metadata make repeats identical
    # within the recorded runtime; byte identity is not promised across zlib versions.
    with ZipFile(raw, "w", compression=ZIP_DEFLATED) as archive:
        for name, array in sorted(arrays.items()):
            encoded = io.BytesIO()
            np.lib.format.write_array(encoded, array, version=(1, 0), allow_pickle=False)
            info = ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, encoded.getvalue())
    payload = raw.getvalue()
    if len(payload) > MAX_ARRAY_BYTES:
        raise ValueError("Feature numeric archive exceeds its file budget.")
    producer = identity()
    manifest = {
        "format": FORMAT,
        "version": 1,
        "model": FEATURE_MODEL_ID,
        "patch_model": p.model_id,
        "surface_identity": surface.identity(),
        "parent_identity": surface.parent_identity,
        "frame": _frame(),
        "grid": asdict(surface.grid),
        "counts": counts,
        "mode": p.mode,
        "settings": asdict(p.settings),
        "protected_bounds_m": p.protected_bounds_m,
        "head_transitions": [asdict(t) for t in p.head_transitions],
        "producer": {
            "package_source_sha256": producer["runtime"]["package_source_sha256"],
            "benchmark_source_sha256": producer["benchmark_source_sha256"],
            "python": producer["runtime"]["python"],
            "numpy": producer["runtime"]["dependencies"]["numpy"],
        },
        "arrays": {k: numeric_hash(v) for k, v in arrays.items()},
        "archive_sha256": sha256(payload).hexdigest(),
        "archive_bytes": len(payload),
    }
    manifest["manifest_sha256"] = sha256(canonical_json(manifest)).hexdigest()
    encoded_manifest = canonical_json(manifest)
    if len(encoded_manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("Feature manifest exceeds its file budget.")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "fields.npz").open("xb") as stream:
        stream.write(payload)
    write_json(output / "manifest.json", manifest)
    return manifest


def read_feature_surface(source: Path, *, expected_identity: str | None = None) -> FeatureSurface:
    """Verify integrity and representation invariants; do not certify terrain quality."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Feature snapshot must be a directory, not a link.")
    if expected_identity is not None:
        digest(expected_identity)
    try:
        value: object = json.loads(
            _read(source / "manifest.json", MAX_MANIFEST_BYTES),
            object_pairs_hook=_unique,
            parse_constant=_constant,
        )
        doc = _object(
            value,
            {
                "format",
                "version",
                "model",
                "patch_model",
                "surface_identity",
                "parent_identity",
                "frame",
                "grid",
                "counts",
                "mode",
                "settings",
                "protected_bounds_m",
                "head_transitions",
                "producer",
                "arrays",
                "archive_sha256",
                "archive_bytes",
                "manifest_sha256",
            },
        )
        unsigned = {k: v for k, v in doc.items() if k != "manifest_sha256"}
        if digest(doc["manifest_sha256"]) != sha256(canonical_json(unsigned)).hexdigest():
            raise ValueError("Feature manifest hash mismatch.")
        if (
            doc["format"] != FORMAT
            or type(doc["version"]) is not int
            or doc["version"] != 1
            or doc["model"] != FEATURE_MODEL_ID
            or canonical_json(doc["frame"]) != canonical_json(_frame())
        ):
            raise ValueError("Unsupported feature format, model or coordinate frame.")
        content_identity = digest(doc["surface_identity"])
        if expected_identity is not None and expected_identity != content_identity:
            raise ValueError("Feature snapshot does not match the expected identity.")
        parent = digest(doc["parent_identity"])
        producer = _object(
            doc["producer"],
            {
                "package_source_sha256",
                "benchmark_source_sha256",
                "python",
                "numpy",
            },
        )
        for key in ("package_source_sha256", "benchmark_source_sha256"):
            digest(producer[key])
        if any(
            type(producer[k]) is not str or not 0 < len(producer[k]) <= 64
            for k in ("python", "numpy")
        ):
            raise ValueError("Invalid feature producer versions.")
        grid_values = _object(doc["grid"], {f.name for f in fields(EvolutionGrid)})
        grid = EvolutionGrid(**{k: _number(v) for k, v in grid_values.items()})
        counts = _object(doc["counts"], {"segments", "pins", "mouths", "nodes"})
        specs = _specs(grid, counts)
        settings_values = _object(doc["settings"], {f.name for f in fields(PatchSettings)})
        for key, item in settings_values.items():
            if key not in ("cross_section", "boundary_model"):
                _number(item)
        settings = PatchSettings(**settings_values)
        bounds = doc["protected_bounds_m"]
        if not isinstance(bounds, list) or len(cast(list[object], bounds)) != 4:
            raise ValueError("Feature protected bounds require four coordinates.")
        rectangle = tuple(_number(v) for v in cast(list[object], bounds))
        assert len(rectangle) == 4
        transitions = doc["head_transitions"]
        if (
            not isinstance(transitions, list)
            or len(cast(list[object], transitions)) > counts["nodes"]
        ):
            raise ValueError("Feature head records exceed their network.")
        heads: list[HeadTransition] = []
        for record in cast(list[object], transitions):
            values = _object(record, {f.name for f in fields(HeadTransition)})
            for key in ("head", "stop_node"):
                _count(values[key], 0, counts["nodes"] - 1)
            for key in ("length_m", "lower_at_head_m", "lift_at_head_m"):
                _number(values[key])
            heads.append(HeadTransition(**values))
        hashes = _object(doc["arrays"], set(specs))
        for value in hashes.values():
            digest(value)
        size = _count(doc["archive_bytes"], 1, MAX_ARRAY_BYTES)
        payload = _read(source / "fields.npz", MAX_ARRAY_BYTES)
        if len(payload) != size or sha256(payload).hexdigest() != digest(doc["archive_sha256"]):
            raise ValueError("Feature numeric archive size or hash mismatch.")
        arrays = read_numeric_archive(payload, specs)
        if any(numeric_hash(v) != hashes[k] for k, v in arrays.items()):
            raise ValueError("Feature numeric array hash mismatch.")
        patch = ValleyPatches(
            FittedSurface(grid, arrays["source_m"], {}),
            FittedSurface(grid, arrays["cap_m"], {}),
            rectangle,
            HardHeights(arrays["hard_points_m"], arrays["hard_heights_m"]),
            arrays["segments_m"],
            arrays["bed_heights_m"],
            doc["mode"],
            settings,
            arrays["anchor_corrections_m"],
            arrays["mouth_segments_m"],
            arrays["mouth_heights_m"],
            arrays["mouth_inward"],
            tuple(heads),
        )
        if doc["patch_model"] != patch.model_id:
            raise ValueError("Unsupported feature patch model.")
        result = FeatureSurface(
            patch, RiverNetwork(arrays["coordinates_m"], arrays["receivers"]), parent
        )
        if result.identity() != content_identity:
            raise ValueError("Decoded feature surface identity mismatch.")
        return result
    except (OSError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError(f"Invalid feature snapshot: {error}") from error
