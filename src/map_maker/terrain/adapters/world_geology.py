"""Portable, current-only geology recipes with retained world identity."""

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import cast

from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.adapters.document_files import document_file_hash, write_document
from map_maker.terrain.adapters.landform_inputs import landform_from_json
from map_maker.terrain.adapters.world_project import (
    world_project_document,
    world_project_from_bytes,
)
from map_maker.terrain.domain.world import WorldProject
from map_maker.terrain.domain.world_geology import (
    GEOLOGICAL_SETTINGS,
    ContinentGeology,
    GeologyProfile,
    GeologyProvince,
    WorldGeologyRecipe,
)

GEOLOGY_SCHEMA = "map-maker.world-geology"
GEOLOGY_VERSION = 2
GEOLOGY_EXTENSION = ".geology.json"
MAX_GEOLOGY_BYTES = 40 * 1024 * 1024
TIME_REFERENCE = "Ma-before-common-present"


def world_fingerprint(world: WorldProject) -> str:
    return sha256(canonical_json(world_project_document(world))).hexdigest()


def geology_document(recipe: WorldGeologyRecipe) -> dict[str, object]:
    def profile(value: GeologyProfile) -> dict[str, object]:
        return {
            "setting": value.setting,
            "landform": None if value.landform is None else {
                key: number if isinstance(number, str) else float(number)
                for key, number in asdict(value.landform).items()
            },
            "crust_age_ma": None if value.crust_age_ma is None else float(value.crust_age_ma),
            "rejuvenation_age_ma": None
            if value.rejuvenation_age_ma is None
            else float(value.rejuvenation_age_ma),
            "evolution_duration_ma": None
            if value.evolution_duration_ma is None
            else float(value.evolution_duration_ma),
        }

    return {
        "schema": GEOLOGY_SCHEMA,
        "version": GEOLOGY_VERSION,
        "time_reference": TIME_REFERENCE,
        "world_sha256": world_fingerprint(recipe.world),
        "world": world_project_document(recipe.world),
        "defaults": [
            {"continent_id": d.continent_id, "profile": profile(d.profile)}
            for d in sorted(recipe.defaults, key=lambda d: d.continent_id)
        ],
        "provinces": [
            {
                "id": p.id,
                "name": p.name,
                "priority": p.priority,
                "vertices": [[float(x), float(y)] for x, y in p.vertices],
                "profile": profile(p.profile),
            }
            for p in sorted(recipe.provinces, key=lambda p: p.id)
        ],
    }


def _record(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(cast(dict[str, object], value)) != fields:
        raise ValueError(f"Expected exactly these geology fields: {', '.join(sorted(fields))}.")
    return cast(dict[str, object], value)


def _keys(value: object) -> set[str]:
    return set(cast(dict[str, object], value)) if isinstance(value, dict) else set()


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Geology collections must be arrays.")
    return cast(list[object], value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("Geology names and IDs need 1-256 non-blank characters.")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Geology ages and coordinates must be numbers.")
    return float(value)


def _profile(value: object) -> GeologyProfile:
    fields = ("crust_age_ma", "rejuvenation_age_ma", "evolution_duration_ma")
    record = _record(value, {"setting", "landform", *fields})
    setting = record["setting"]
    if not isinstance(setting, str) or setting not in GEOLOGICAL_SETTINGS:
        raise ValueError("Unknown geological setting.")
    return GeologyProfile(
        setting, *(None if record[key] is None else _number(record[key]) for key in fields),
        landform=None if record["landform"] is None else landform_from_json(record["landform"]),
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate geology field: {key}.")
        result[key] = value
    return result


def geology_from_bytes(raw: bytes) -> WorldGeologyRecipe:
    if len(raw) > MAX_GEOLOGY_BYTES:
        raise ValueError("Geology recipe exceeds 40 MiB.")
    try:
        value: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if "landmarks" in _keys(value):
            raise ValueError(
                "This recipe holds landmarks, which are now wonders in their own document "
                "(.wonders.json, ADR-0097). Place them again in the Wonders step."
            )
        record = _record(value, {
            "schema", "version", "time_reference", "world_sha256", "world", "defaults",
            "provinces",
        })
        if (
            record["schema"] != GEOLOGY_SCHEMA
            or type(record["version"]) is not int
            or record["version"] != GEOLOGY_VERSION
            or record["time_reference"] != TIME_REFERENCE
        ):
            raise ValueError("Unsupported geology format or time reference.")
        world = world_project_from_bytes(canonical_json(record["world"]))
        if world_fingerprint(world) != record["world_sha256"]:
            raise ValueError("Geology world fingerprint does not match the retained world.")
        defaults: list[ContinentGeology] = []
        for item in _array(record["defaults"]):
            default = _record(item, {"continent_id", "profile"})
            defaults.append(
                ContinentGeology(_text(default["continent_id"]), _profile(default["profile"]))
            )
        provinces: list[GeologyProvince] = []
        for item in _array(record["provinces"]):
            province = _record(item, {"id", "name", "priority", "vertices", "profile"})
            vertices: list[tuple[float, float]] = []
            for item_point in _array(province["vertices"]):
                point = tuple(_number(n) for n in _array(item_point))
                if len(point) != 2:
                    raise ValueError("Province vertices need two coordinates.")
                vertices.append((point[0], point[1]))
            priority = province["priority"]
            if type(priority) is not int:
                raise ValueError("Province priority must be an integer.")
            provinces.append(
                GeologyProvince(
                    _text(province["id"]),
                    _text(province["name"]),
                    tuple(vertices),
                    priority,
                    _profile(province["profile"]),
                )
            )
        return WorldGeologyRecipe(world, tuple(defaults), tuple(provinces))
    except (UnicodeError, json.JSONDecodeError, OverflowError, RecursionError) as error:
        raise ValueError(f"Invalid geology recipe: {error}") from error


def read_geology(path: Path) -> tuple[WorldGeologyRecipe, str]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_GEOLOGY_BYTES + 1)
    return geology_from_bytes(raw), sha256(raw).hexdigest()


def geology_file_hash(path: Path) -> str | None:
    return document_file_hash(path, MAX_GEOLOGY_BYTES, "geology")


def write_geology(recipe: WorldGeologyRecipe, path: Path, expected_hash: str | None) -> str:
    """Atomic replacement; reject an externally changed or unexpectedly existing file."""
    if not path.name.endswith(GEOLOGY_EXTENSION):
        raise ValueError(f"Save geology recipes with the {GEOLOGY_EXTENSION} extension.")
    data = canonical_json(geology_document(recipe))
    if len(data) > MAX_GEOLOGY_BYTES:
        raise ValueError("Geology recipe exceeds 40 MiB.")
    return write_document(path, data, expected_hash, MAX_GEOLOGY_BYTES, "geology")
