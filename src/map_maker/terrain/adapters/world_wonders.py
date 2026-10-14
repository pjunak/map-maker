"""Portable hand-placed wonder documents with retained world identity (ADR-0097)."""

import json
from hashlib import sha256
from pathlib import Path
from typing import cast

from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.adapters.document_files import document_file_hash, write_document
from map_maker.terrain.adapters.world_geology import world_fingerprint
from map_maker.terrain.adapters.world_project import (
    world_project_document,
    world_project_from_bytes,
)
from map_maker.terrain.domain.models import Point2D
from map_maker.terrain.domain.wonders import WONDER_KINDS
from map_maker.terrain.domain.world_wonders import WorldWonder, WorldWonders

WONDERS_SCHEMA = "map-maker.world-wonders"
WONDERS_VERSION = 1
WONDERS_EXTENSION = ".wonders.json"
MAX_WONDERS_BYTES = 40 * 1024 * 1024
FIELDS = {"id", "name", "kind", "position", "seed", "size_km", "end", "age_myr"}


def wonders_document(document: WorldWonders) -> dict[str, object]:
    def point(value: Point2D | None) -> list[float] | None:
        return None if value is None else [float(value[0]), float(value[1])]

    return {
        "schema": WONDERS_SCHEMA,
        "version": WONDERS_VERSION,
        "world_sha256": world_fingerprint(document.world),
        "world": world_project_document(document.world),
        "wonders": [
            {
                "id": w.id,
                "name": w.name,
                "kind": w.kind,
                "position": point(w.position),
                "seed": w.seed,
                "size_km": None if w.size_km is None else float(w.size_km),
                "end": point(w.end),
                "age_myr": None if w.age_myr is None else float(w.age_myr),
            }
            for w in sorted(document.wonders, key=lambda w: w.id)
        ],
    }


def wonders_sha256(document: WorldWonders) -> str:
    """Hash of the canonical document, independent of file formatting."""
    return sha256(canonical_json(wonders_document(document))).hexdigest()


def _record(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(cast(dict[str, object], value)) != fields:
        raise ValueError(f"Expected exactly these wonder fields: {', '.join(sorted(fields))}.")
    return cast(dict[str, object], value)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Wonder sizes, ages and coordinates must be numbers.")
    return float(value)


def _point(value: object) -> Point2D:
    if not isinstance(value, list) or len(cast(list[object], value)) != 2:
        raise ValueError("Wonder positions and ends need two coordinates.")
    x, y = cast(list[object], value)
    return (_number(x), _number(y))


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Wonder names and IDs must be text.")
    return value


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate wonder field: {key}.")
        result[key] = value
    return result


def _wonder(value: object) -> WorldWonder:
    item = _record(value, FIELDS)
    kind = item["kind"]
    if kind not in WONDER_KINDS:
        raise ValueError(f"Unknown wonder kind: {kind}.")
    seed = item["seed"]
    if type(seed) is not int:
        raise ValueError("A wonder's seed must be a whole number.")
    return WorldWonder(
        _text(item["id"]),
        _text(item["name"]),
        kind,
        _point(item["position"]),
        seed,
        None if item["size_km"] is None else _number(item["size_km"]),
        None if item["end"] is None else _point(item["end"]),
        None if item["age_myr"] is None else _number(item["age_myr"]),
    )


def wonders_from_bytes(raw: bytes) -> WorldWonders:
    if len(raw) > MAX_WONDERS_BYTES:
        raise ValueError("Wonder document exceeds 40 MiB.")
    try:
        value: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        record = _record(value, {"schema", "version", "world_sha256", "world", "wonders"})
        if (
            record["schema"] != WONDERS_SCHEMA
            or type(record["version"]) is not int
            or record["version"] != WONDERS_VERSION
        ):
            raise ValueError("Unsupported wonder document format.")
        world = world_project_from_bytes(canonical_json(record["world"]))
        if world_fingerprint(world) != record["world_sha256"]:
            raise ValueError("Wonder document's world fingerprint does not match its world.")
        items = record["wonders"]
        if not isinstance(items, list):
            raise ValueError("Wonders must be an array.")
        return WorldWonders(world, tuple(_wonder(item) for item in cast(list[object], items)))
    except (UnicodeError, json.JSONDecodeError, OverflowError, RecursionError) as error:
        raise ValueError(f"Invalid wonder document: {error}") from error


def read_wonders(path: Path) -> tuple[WorldWonders, str]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_WONDERS_BYTES + 1)
    return wonders_from_bytes(raw), sha256(raw).hexdigest()


def wonders_file_hash(path: Path) -> str | None:
    return document_file_hash(path, MAX_WONDERS_BYTES, "wonder")


def write_wonders(document: WorldWonders, path: Path, expected_hash: str | None) -> str:
    """Atomic replacement; reject an externally changed or unexpectedly existing file."""
    if not path.name.endswith(WONDERS_EXTENSION):
        raise ValueError(f"Save wonders with the {WONDERS_EXTENSION} extension.")
    data = canonical_json(wonders_document(document))
    if len(data) > MAX_WONDERS_BYTES:
        raise ValueError("Wonder document exceeds 40 MiB.")
    return write_document(path, data, expected_hash, MAX_WONDERS_BYTES, "wonder")
