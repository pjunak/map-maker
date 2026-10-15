# pyright: reportUnknownMemberType=false
"""Hand-placed wonder documents: validation, files and world identity (ADR-0097)."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from map_maker.terrain.adapters import world_wonders as files
from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.adapters.world_project import read_world_project
from map_maker.terrain.application.world_wonders import open_wonders, save_wonders
from map_maker.terrain.domain.world_wonders import (
    WorldWonder,
    WorldWonders,
    blank_wonders,
    follow_world,
)

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples/world"
EXAMPLE = EXAMPLES / "four-shores.wonders.json"


def validator() -> Draft202012Validator:
    schemas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (
            ROOT / "schemas/world/project-v1.schema.json",
            ROOT / "schemas/world/wonders-v2.schema.json",
        )
    ]
    registry = Registry[Any]().with_resources(
        [(schema["$id"], Resource.from_contents(schema)) for schema in schemas]
    )
    Draft202012Validator.check_schema(schemas[1])
    return Draft202012Validator(schemas[1], registry=registry)


def placed() -> WorldWonders:
    project = read_world_project(EXAMPLES / "four-shores.world.json")
    x0, y0, x1, y1 = project.frame.bounds
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    return WorldWonders(project, (
        WorldWonder("wonder-sky", "Skyfather", "titan", centre, 1),
        WorldWonder("wonder-eye", "The Eye", "crater", (x0 + 1, y0 + 1), 2, 180.0),
        WorldWonder(
            "wonder-rift", "The Rift", "chasm", centre, 3, None,
            (centre[0] + 0.02 * (x1 - x0), centre[1]), 20.0,
        ),
    ))


def test_example_and_documents_round_trip(tmp_path: Path) -> None:
    validator().validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    example, _ = files.read_wonders(EXAMPLE)
    assert example.world == read_world_project(EXAMPLES / "four-shores.world.json")
    assert len(example.wonders) == 4
    rift = next(w for w in example.wonders if w.name == "The Rift")
    assert rift.options == (("depth_m", 2500.0), ("side_canyons", 5.0))
    document = placed()
    raw = files.wonders_document(document)
    validator().validate(raw)
    reopened = files.wonders_from_bytes(canonical_json(raw))
    assert reopened.wonders == tuple(sorted(document.wonders, key=lambda w: w.id))
    by_name = {w.name: w for w in reopened.wonders}
    assert by_name["The Rift"].effective_size_km == 60.0  # chasm default width
    assert by_name["Skyfather"].effective_size_km == 560.0  # titan default diameter
    assert by_name["The Rift"].seed == 3
    # Files are written atomically and never over a file changed elsewhere.
    path = tmp_path / "w.wonders.json"
    saved = save_wonders(document, path)
    assert open_wonders(path, document.world).wonders.wonders == reopened.wonders
    with pytest.raises(ValueError, match="extension"):
        files.write_wonders(document, tmp_path / "w.json", None)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed outside"):
        save_wonders(document, path, saved.sha256)
    # A document belongs to its world.
    other = replace(document.world, name="Another world")
    with pytest.raises(ValueError, match="different world"):
        open_wonders(EXAMPLE, other)
    with pytest.raises(ValueError, match="Duplicate"):
        files.wonders_from_bytes(b'{"version":1,"version":1}')


def test_wonders_reject_what_they_cannot_be() -> None:
    document = placed()
    world = document.world
    x0, y0, x1, _ = world.frame.bounds
    centre = document.wonders[0].position
    for bad in (
        {"kind": "volcano"},
        {"size_km": 5.0},
        {"id": "landmark-eye"},
        {"end": (x0 + 1, y0 + 1)},  # only a line wonder has an end
        {"kind": "chasm"},  # without one
        {"kind": "chasm", "end": centre},
        {"age_myr": -1.0},
        {"kind": "titan", "age_myr": 5.0},  # volcanoes stay young
        {"seed": -1},
        {"seed": 2**32},
        {"seed": True},
        {"name": " "},
    ):
        with pytest.raises(ValueError):
            WorldWonder(**({"id": "wonder-a", "name": "A", "kind": "crater",
                            "position": centre, "seed": 1} | bad))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="outside the world frame"):
        WorldWonders(world, (WorldWonder("wonder-a", "A", "crater", (x1 + 5, y0), 1),))
    with pytest.raises(ValueError, match="km long"):
        WorldWonders(world, (
            WorldWonder("wonder-a", "A", "chasm", centre, 1, None, (centre[0] + 1e-6, centre[1])),
        ))
    with pytest.raises(ValueError, match="names must be unique"):
        WorldWonders(world, (
            WorldWonder("wonder-a", "Same", "crater", centre, 1),
            WorldWonder("wonder-b", "same", "titan", centre, 2),
        ))
    with pytest.raises(ValueError, match="IDs must be unique"):
        WorldWonders(world, (
            WorldWonder("wonder-a", "A", "crater", centre, 1),
            WorldWonder("wonder-a", "B", "titan", centre, 2),
        ))


def test_settings_follow_the_catalog() -> None:
    from map_maker.terrain.domain.wonders import OPTION_KEYS, WONDERS, WonderKind

    centre = placed().wonders[0].position
    tepui = WorldWonder("wonder-t", "T", "tepui", centre, 1,
                        options=(("elongation", 1.5), ("height_m", 2500.0)))
    assert (tepui.option("height_m"), tepui.option("orientation_deg")) == (2500.0, None)
    cases: tuple[tuple[WonderKind, tuple[tuple[str, float], ...], str], ...] = (
        ("tepui", (("depth_m", 1.0),), "has no setting"),  # not a tepui's
        ("tepui", (("height_m", 9e3),), "height must be a number from 500 to 4,000 m"),
        ("chasm", (("side_canyons", 2.5),), "must be a whole number"),
        ("tepui", (("height_m", 2e3), ("elongation", 1.5)), "sorted"),
        ("tepui", (("height_m", 2e3), ("height_m", 2e3)), "distinct"),
        ("oasis", (("height_m", 1e3),), "has no setting"),
    )
    for kind, options, message in cases:
        end = (centre[0] + 5.0, centre[1]) if WONDERS[kind].line else None
        with pytest.raises(ValueError, match=message):
            WorldWonder("wonder-x", "X", kind, centre, 1, None, end, None, options)
    # The schema names exactly the catalog's settings, and documents keep them.
    schema = json.loads((ROOT / "schemas/world/wonders-v2.schema.json").read_text("utf-8"))
    keys = schema["properties"]["wonders"]["items"]["properties"]["options"]["propertyNames"]
    assert tuple(keys["enum"]) == OPTION_KEYS
    document = WorldWonders(placed().world, (tepui,))
    raw = files.wonders_document(document)
    validator().validate(raw)
    wonders = cast(list[dict[str, object]], raw["wonders"])
    assert wonders[0]["options"] == {"elongation": 1.5, "height_m": 2500.0}
    assert files.wonders_from_bytes(canonical_json(raw)) == document


def test_wonders_follow_edits_of_their_own_world_only() -> None:
    document = placed()
    renamed = replace(document.world, name="Renamed")
    moved = follow_world(document, renamed)
    assert moved.world == renamed and moved.wonders == document.wonders
    assert blank_wonders(renamed).wonders == ()
    other = read_world_project(EXAMPLES / "landform-world.world.json")
    with pytest.raises(ValueError, match="another source map"):
        follow_world(document, other)
