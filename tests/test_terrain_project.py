import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, validate

from map_maker.terrain.adapters import (
    CoastlineSource,
    TerrainProjectInputError,
    load_svg_coastline_source,
    load_terrain_project,
    save_terrain_project,
)
from map_maker.terrain.domain import (
    BrushToolSettings,
    ElevationPoint,
    FeatureToolSettings,
    TerrainAuthoringState,
    TerrainBrushStroke,
    TerrainProject,
    TerrainSettings,
    TerrainStructure,
)

FIXTURES = Path(__file__).parent / "fixtures" / "terrain"
EXAMPLES = Path(__file__).parents[1] / "examples" / "terrain"


def _source_in(tmp_path: Path) -> CoastlineSource:
    source = tmp_path / "inputs" / "coastline.svg"
    source.parent.mkdir()
    shutil.copyfile(FIXTURES / "closed-coast.svg", source)
    return load_svg_coastline_source(source)


def _project_for(source: CoastlineSource) -> TerrainProject:
    return TerrainProject(
        coastline=source.coastline,
        settings=TerrainSettings(seed=42, object_scale_km=3_850.0, resolution_px=512,
                                 drainage_density=1.4),
        constraints=(
            TerrainBrushStroke(
                points=((0.25, 0.4), (0.5, 0.45)),
                elevation_m=450.0,
                influence_radius_km=130.0,
                intensity=0.6,
                elevation_mode="relative",
            ),
            ElevationPoint((0.62, 0.31), 3_900.0, 75.0, "absolute"),
            TerrainStructure(
                "ridge", ((0.2, 0.3), (0.5, 0.4), (0.8, 0.35)), 1_100.0, 90.0, "relative"
            ),
            TerrainStructure(
                "valley", ((0.3, 0.7), (0.7, 0.6)), 550.0, 65.0, "absolute"
            ),
        ),
        authoring=TerrainAuthoringState(
            active_tool="valley",
            brush=BrushToolSettings("relative", -300.0, 240.0, 0.45),
            height=FeatureToolSettings("relative", 800.0, 55.0),
            ridge=FeatureToolSettings("absolute", 4_200.0, 100.0),
            valley=FeatureToolSettings("relative", 650.0, 70.0),
        ),
    )


def test_project_round_trip_preserves_authored_state_and_relative_svg_path(
    tmp_path: Path,
) -> None:
    source = _source_in(tmp_path)
    project = _project_for(source)
    destination = tmp_path / "projects" / "continent.terrain.json"

    save_terrain_project(project, source, destination)

    serialized = cast(
        "dict[str, object]", json.loads(destination.read_text(encoding="utf-8"))
    )
    coastline = cast("dict[str, object]", serialized["coastline"])
    constraints = cast("list[dict[str, object]]", serialized["constraints"])
    authoring = cast("dict[str, object]", serialized["authoring"])
    tools = cast("dict[str, dict[str, object]]", authoring["tools"])
    assert serialized["schema"] == "map-maker.terrain-project"
    assert serialized["schema_version"] == 9
    schema_path = EXAMPLES.parents[1] / "schemas" / "terrain" / "project-v9.schema.json"
    schema: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validate(serialized, schema, cls=Draft202012Validator)
    assert coastline["path"] == "../inputs/coastline.svg"
    assert constraints[0]["type"] == "terrain_brush"
    assert tools["brush"]["width_km"] == 240.0

    loaded = load_terrain_project(destination)

    assert loaded.project == project
    assert loaded.coastline_source.path == source.path
    assert loaded.path == destination.resolve()


def test_committed_example_project_loads() -> None:
    loaded = load_terrain_project(EXAMPLES / "example.terrain.json")

    assert loaded.project.settings == TerrainSettings()
    assert loaded.project.authoring == TerrainAuthoringState()
    assert loaded.project.constraints == ()


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_committed_projects_load_after_git_checkout(tmp_path: Path, autocrlf: str) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    shutil.copytree(EXAMPLES, repository / "examples" / "terrain")
    attributes = EXAMPLES.parents[1] / ".gitattributes"
    if attributes.is_file():
        shutil.copyfile(attributes, repository / ".gitattributes")

    def git(*arguments: str) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                f"core.autocrlf={autocrlf}",
                "-c",
                "core.eol=lf",
                "-c",
                "core.safecrlf=false",
                "-c",
                f"core.attributesFile={os.devnull}",
                *arguments,
            ],
            cwd=repository,
            check=True,
            capture_output=True,
            timeout=30,
        )

    git("init", "--quiet", "--template=")
    git("add", "--all")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git("checkout-index", "--all", f"--prefix={checkout.as_posix()}/")

    # Exercise Git's checkout conversion, which does not run on a simple file copy.
    projects = sorted((checkout / "examples" / "terrain").glob("*.terrain.json"))
    assert projects
    for project in projects:
        assert load_terrain_project(project).path == project.resolve()


def test_project_load_rejects_modified_coastline(tmp_path: Path) -> None:
    source = _source_in(tmp_path)
    destination = tmp_path / "continent.terrain.json"
    save_terrain_project(_project_for(source), source, destination)
    source.path.write_text(
        source.path.read_text(encoding="utf-8") + "\n<!-- changed -->\n",
        encoding="utf-8",
    )

    with pytest.raises(TerrainProjectInputError, match="does not match the SHA-256"):
        load_terrain_project(destination)


def test_project_save_rejects_coastline_changed_after_import(tmp_path: Path) -> None:
    source = _source_in(tmp_path)
    source.path.write_text(
        source.path.read_text(encoding="utf-8") + "\n<!-- changed -->\n",
        encoding="utf-8",
    )

    with pytest.raises(TerrainProjectInputError, match="changed after it was imported"):
        save_terrain_project(_project_for(source), source, tmp_path / "project.terrain.json")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 1, "Unsupported project schema version"),
        ("schema_version", 2, "Unsupported project schema version"),
        ("schema_version", 4, "Unsupported project schema version"),
        ("schema_version", 99, "Unsupported project schema version"),
        ("unexpected", True, "unknown fields"),
    ],
)
def test_project_load_rejects_incompatible_contract(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    source = _source_in(tmp_path)
    destination = tmp_path / "continent.terrain.json"
    save_terrain_project(_project_for(source), source, destination)
    document = cast(
        "dict[str, object]", json.loads(destination.read_text(encoding="utf-8"))
    )
    document[field] = value
    destination.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(TerrainProjectInputError, match=message):
        load_terrain_project(destination)


def test_project_rejects_removed_seed_policy_setting(tmp_path: Path) -> None:
    source = _source_in(tmp_path)
    path = tmp_path / "project.terrain.json"
    save_terrain_project(_project_for(source), source, path)
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    document["settings"]["seed_policy"] = "named-stage-sha256@1"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TerrainProjectInputError, match="unknown fields: seed_policy"):
        load_terrain_project(path)
