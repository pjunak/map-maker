"""Read and write the versioned terrain-project JSON contract."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import cast

from map_maker.terrain.adapters.landform_inputs import landform_from_json
from map_maker.terrain.adapters.svg import (
    CoastlineInputError,
    CoastlineSource,
    coastline_sha256,
    load_svg_coastline_source,
)
from map_maker.terrain.adapters.terrain_context import (
    context_from_json,
    context_to_json,
    validate_context_source,
)
from map_maker.terrain.domain import (
    BrushToolSettings,
    Coastline,
    ElevationMode,
    ElevationPoint,
    FeatureToolSettings,
    LakeToolSettings,
    LandComponent,
    StructureProfileKnot,
    TerrainAuthoringState,
    TerrainBasin,
    TerrainBrushStroke,
    TerrainConstraint,
    TerrainProject,
    TerrainRegion,
    TerrainSettings,
    TerrainStructure,
)

PROJECT_SCHEMA = "map-maker.terrain-project"
PROJECT_SCHEMA_VERSION = 9
PROJECT_EXTENSION = ".terrain.json"
_MAX_PROJECT_BYTES = 16 * 1024 * 1024


class TerrainProjectInputError(ValueError):
    """A project document or its referenced coastline is not trustworthy."""


@dataclass(frozen=True, slots=True)
class LoadedTerrainProject:
    """A parsed project together with verified coastline provenance."""

    project: TerrainProject
    coastline_source: CoastlineSource
    path: Path


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TerrainProjectInputError(f"{context} must be a JSON object.")
    untyped = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in untyped):
        raise TerrainProjectInputError(f"{context} must use string field names.")
    return cast("dict[str, object]", value)


def _sequence(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise TerrainProjectInputError(f"{context} must be a JSON array.")
    return cast("list[object]", value)


def _require_keys(value: dict[str, object], expected: set[str], context: str) -> None:
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise TerrainProjectInputError(f"{context} is missing: {', '.join(sorted(missing))}.")
    if extra:
        raise TerrainProjectInputError(f"{context} has unknown fields: {', '.join(sorted(extra))}.")


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise TerrainProjectInputError(f"{context} must be a non-empty string.")
    return value


def _number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TerrainProjectInputError(f"{context} must be a number.")
    result = float(value)
    if not isfinite(result):
        raise TerrainProjectInputError(f"{context} must be finite.")
    return result


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TerrainProjectInputError(f"{context} must be an integer.")
    return value


def _elevation_mode(value: object, context: str) -> ElevationMode:
    mode = _string(value, context)
    if mode not in ("absolute", "relative"):
        raise TerrainProjectInputError(f"{context} must be 'absolute' or 'relative'.")
    return mode


def _point(value: object, context: str) -> tuple[float, float]:
    parts = _sequence(value, context)
    if len(parts) != 2:
        raise TerrainProjectInputError(f"{context} must contain exactly two coordinates.")
    return _number(parts[0], f"{context}[0]"), _number(parts[1], f"{context}[1]")


def _points(value: object, context: str) -> tuple[tuple[float, float], ...]:
    values = _sequence(value, context)
    return tuple(_point(point, f"{context}[{index}]") for index, point in enumerate(values))


def _settings_from_json(value: object) -> TerrainSettings:
    data = _mapping(value, "settings")
    expected = {
        "seed",
        "object_scale_km",
        "resolution_px",
        "maximum_elevation_m",
        "largest_feature_km",
        "detail_levels",
        "roughness",
        "coastal_rise_km",
        "variability",
        "drainage_density",
    }
    _require_keys(data, expected, "settings")
    try:
        return TerrainSettings(
            seed=_integer(data["seed"], "settings.seed"),
            object_scale_km=_number(data["object_scale_km"], "settings.object_scale_km"),
            resolution_px=_integer(data["resolution_px"], "settings.resolution_px"),
            maximum_elevation_m=_number(
                data["maximum_elevation_m"], "settings.maximum_elevation_m"
            ),
            largest_feature_km=_number(
                data["largest_feature_km"], "settings.largest_feature_km"
            ),
            detail_levels=_integer(data["detail_levels"], "settings.detail_levels"),
            roughness=_number(data["roughness"], "settings.roughness"),
            coastal_rise_km=_number(data["coastal_rise_km"], "settings.coastal_rise_km"),
            variability=_number(data["variability"], "settings.variability"),
            drainage_density=_number(data["drainage_density"], "settings.drainage_density"),
        )
    except ValueError as error:
        raise TerrainProjectInputError(f"Invalid generator settings: {error}") from error


def _feature_tool_from_json(value: object, name: str) -> FeatureToolSettings:
    data = _mapping(value, f"authoring.tools.{name}")
    _require_keys(data, {"elevation_mode", "elevation_m", "radius_km"}, f"authoring.tools.{name}")
    return FeatureToolSettings(
        elevation_mode=_elevation_mode(
            data["elevation_mode"], f"authoring.tools.{name}.elevation_mode"
        ),
        elevation_m=_number(data["elevation_m"], f"authoring.tools.{name}.elevation_m"),
        radius_km=_number(data["radius_km"], f"authoring.tools.{name}.radius_km"),
    )


def _authoring_from_json(value: object) -> TerrainAuthoringState:
    data = _mapping(value, "authoring")
    _require_keys(data, {"active_tool", "tools"}, "authoring")
    active_tool_value = _string(data["active_tool"], "authoring.active_tool")
    if active_tool_value not in (
        "brush", "height", "ridge", "valley", "region", "lake", "dry_basin",
    ):
        raise TerrainProjectInputError("authoring.active_tool is not supported.")
    tools = _mapping(data["tools"], "authoring.tools")
    _require_keys(tools, {"brush", "height", "ridge", "valley", "region", "lake"},
                  "authoring.tools")
    lake = _mapping(tools["lake"], "authoring.tools.lake")
    _require_keys(lake, {"water_level_m", "outlet_at_first_vertex"}, "authoring.tools.lake")
    if not isinstance(lake["outlet_at_first_vertex"], bool):
        raise TerrainProjectInputError("Lake outlet selection must be boolean.")
    brush = _mapping(tools["brush"], "authoring.tools.brush")
    _require_keys(
        brush,
        {"elevation_mode", "elevation_m", "width_km", "intensity"},
        "authoring.tools.brush",
    )
    try:
        return TerrainAuthoringState(
            active_tool=active_tool_value,
            lake=LakeToolSettings(_number(lake["water_level_m"], "lake water level"),
                                  lake["outlet_at_first_vertex"]),
            region=landform_from_json(tools["region"]),
            brush=BrushToolSettings(
                elevation_mode=_elevation_mode(
                    brush["elevation_mode"], "authoring.tools.brush.elevation_mode"
                ),
                elevation_m=_number(
                    brush["elevation_m"], "authoring.tools.brush.elevation_m"
                ),
                width_km=_number(brush["width_km"], "authoring.tools.brush.width_km"),
                intensity=_number(brush["intensity"], "authoring.tools.brush.intensity"),
            ),
            height=_feature_tool_from_json(tools["height"], "height"),
            ridge=_feature_tool_from_json(tools["ridge"], "ridge"),
            valley=_feature_tool_from_json(tools["valley"], "valley"),
        )
    except ValueError as error:
        raise TerrainProjectInputError(f"Invalid authoring settings: {error}") from error


def _constraint_from_json(value: object, index: int) -> TerrainConstraint:
    context = f"constraints[{index}]"
    data = _mapping(value, context)
    kind = _string(data.get("type"), f"{context}.type")
    common = {"type", "elevation_mode", "elevation_m", "influence_radius_km"}
    try:
        if kind in ("lake", "dry_basin"):
            _require_keys(data, {"type", "points", "water_level_m", "outlet"}, context)
            return TerrainBasin(
                _points(data["points"], f"{context}.points"), kind,
                None if data["water_level_m"] is None else _number(data["water_level_m"], context),
                None if data["outlet"] is None else _point(data["outlet"], context),
            )
        if kind == "terrain_region":
            _require_keys(data, {"type", "points", "holes", "settings"}, context)
            return TerrainRegion(
                _points(data["points"], f"{context}.points"),
                landform_from_json(data["settings"]),
                tuple(_points(ring, f"{context}.holes") for ring in
                      _sequence(data["holes"], f"{context}.holes")),
            )
        elevation_mode = _elevation_mode(data.get("elevation_mode"), f"{context}.elevation_mode")
        elevation_m = _number(data.get("elevation_m"), f"{context}.elevation_m")
        radius_km = _number(
            data.get("influence_radius_km"), f"{context}.influence_radius_km"
        )
        if kind == "height_point":
            _require_keys(data, common | {"position"}, context)
            return ElevationPoint(
                position=_point(data["position"], f"{context}.position"),
                elevation_m=elevation_m,
                influence_radius_km=radius_km,
                elevation_mode=elevation_mode,
            )
        if kind == "terrain_brush":
            _require_keys(data, common | {"points", "intensity"}, context)
            return TerrainBrushStroke(
                points=_points(data["points"], f"{context}.points"),
                elevation_m=elevation_m,
                influence_radius_km=radius_km,
                intensity=_number(data["intensity"], f"{context}.intensity"),
                elevation_mode=elevation_mode,
            )
        if kind in ("ridge", "valley"):
            _require_keys(data, common | {"points", "profile"}, context)
            profile: list[StructureProfileKnot] = []
            for item in _sequence(data["profile"], f"{context}.profile"):
                knot = _mapping(item, f"{context}.profile knot")
                _require_keys(knot, {"position", "elevation_m"}, f"{context}.profile knot")
                profile.append(StructureProfileKnot(
                    _number(knot["position"], f"{context}.profile position"),
                    _number(knot["elevation_m"], f"{context}.profile elevation"),
                ))
            return TerrainStructure(
                kind=kind,
                points=_points(data["points"], f"{context}.points"),
                elevation_m=elevation_m,
                influence_radius_km=radius_km,
                elevation_mode=elevation_mode,
                profile=tuple(profile),
            )
    except ValueError as error:
        raise TerrainProjectInputError(f"Invalid {context}: {error}") from error
    raise TerrainProjectInputError(f"{context}.type is not supported: {kind!r}.")


def settings_to_json(settings: TerrainSettings) -> dict[str, int | float]:
    """Serialize current effective generator settings."""
    return {
        "seed": settings.seed,
        "object_scale_km": settings.object_scale_km,
        "resolution_px": settings.resolution_px,
        "maximum_elevation_m": settings.maximum_elevation_m,
        "largest_feature_km": settings.largest_feature_km,
        "detail_levels": settings.detail_levels,
        "roughness": settings.roughness,
        "coastal_rise_km": settings.coastal_rise_km,
        "variability": settings.variability,
        "drainage_density": settings.drainage_density,
    }


def _authoring_to_json(authoring: TerrainAuthoringState) -> dict[str, object]:
    def feature(settings: FeatureToolSettings) -> dict[str, str | float]:
        return {
            "elevation_mode": settings.elevation_mode,
            "elevation_m": settings.elevation_m,
            "radius_km": settings.radius_km,
        }

    return {
        "active_tool": authoring.active_tool,
        "tools": {
            "region": asdict(authoring.region),
            "lake": asdict(authoring.lake),
            "brush": {
                "elevation_mode": authoring.brush.elevation_mode,
                "elevation_m": authoring.brush.elevation_m,
                "width_km": authoring.brush.width_km,
                "intensity": authoring.brush.intensity,
            },
            "height": feature(authoring.height),
            "ridge": feature(authoring.ridge),
            "valley": feature(authoring.valley),
        },
    }


def _constraint_to_json(constraint: TerrainConstraint) -> dict[str, object]:
    if isinstance(constraint, TerrainBasin):
        return {"type": constraint.kind, "points": [list(p) for p in constraint.points],
                "water_level_m": constraint.water_level_m,
                "outlet": None if constraint.outlet is None else list(constraint.outlet)}
    if isinstance(constraint, TerrainRegion):
        return {"type": "terrain_region", "points": [list(p) for p in constraint.points],
                "holes": [[list(p) for p in ring] for ring in constraint.holes],
                "settings": asdict(constraint.settings)}
    data: dict[str, object] = {
        "elevation_mode": constraint.elevation_mode,
        "elevation_m": constraint.elevation_m,
        "influence_radius_km": constraint.influence_radius_km,
    }
    if isinstance(constraint, ElevationPoint):
        data.update(type="height_point", position=list(constraint.position))
    elif isinstance(constraint, TerrainBrushStroke):
        data.update(
            type="terrain_brush",
            points=[list(point) for point in constraint.points],
            intensity=constraint.intensity,
        )
    else:
        data.update(type=constraint.kind, points=[list(point) for point in constraint.points],
                    profile=[asdict(k) for k in constraint.profile])
    return data


def _relative_source_path(source: Path, destination: Path) -> str:
    try:
        relative = os.path.relpath(source, destination.parent.resolve())
    except ValueError:
        return source.as_posix()
    return Path(relative).as_posix()


def save_terrain_project(
    project: TerrainProject,
    coastline_source: CoastlineSource,
    destination: Path,
) -> None:
    """Atomically save authored state while preserving external SVG provenance."""

    if project.coastline != coastline_source.coastline:
        raise TerrainProjectInputError("The project coastline does not match its source record.")
    coastline_source.validate_scale(project.settings.object_scale_km)
    validate_context_source(project.world_context, coastline_source.world_terrain)
    current_sha256 = coastline_sha256(coastline_source.path)
    if current_sha256 != coastline_source.sha256:
        raise TerrainProjectInputError(
            "The coastline SVG changed after it was imported. Import it again before saving."
        )

    target = destination.resolve()
    document: dict[str, object] = {
        "schema": PROJECT_SCHEMA,
        "schema_version": PROJECT_SCHEMA_VERSION,
        "coastline": {
            "path": _relative_source_path(coastline_source.path, target),
            "sha256": coastline_source.sha256,
        },
        "settings": settings_to_json(project.settings),
        "constraints": [_constraint_to_json(constraint) for constraint in project.constraints],
        "authoring": _authoring_to_json(project.authoring),
        "world_context": context_to_json(project.world_context),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_terrain_project(source: Path) -> LoadedTerrainProject:
    """Load the current project format and verify its referenced coastline."""

    try:
        resolved = source.resolve(strict=True)
        if resolved.stat().st_size > _MAX_PROJECT_BYTES:
            raise TerrainProjectInputError("Terrain project is larger than 16 MiB.")
        raw: object = json.loads(resolved.read_text(encoding="utf-8"))
    except TerrainProjectInputError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TerrainProjectInputError(f"Could not read terrain project: {error}") from error

    data = _mapping(raw, "project")
    _require_keys(
        data,
        {"schema", "schema_version", "coastline", "settings", "constraints", "authoring",
         "world_context"},
        "project",
    )
    if data["schema"] != PROJECT_SCHEMA:
        raise TerrainProjectInputError(f"Unsupported project schema: {data['schema']!r}.")
    version = _integer(data["schema_version"], "schema_version")
    if version != PROJECT_SCHEMA_VERSION:
        raise TerrainProjectInputError(
            f"Unsupported project schema version {version}; expected {PROJECT_SCHEMA_VERSION}."
        )

    coastline_data = _mapping(data["coastline"], "coastline")
    _require_keys(coastline_data, {"path", "sha256"}, "coastline")
    coastline_path_text = _string(coastline_data["path"], "coastline.path")
    declared_sha256 = _string(coastline_data["sha256"], "coastline.sha256").lower()
    if len(declared_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in declared_sha256
    ):
        raise TerrainProjectInputError("coastline.sha256 must be 64 hexadecimal characters.")

    settings = _settings_from_json(data["settings"])
    constraints = tuple(
        _constraint_from_json(value, index)
        for index, value in enumerate(_sequence(data["constraints"], "constraints"))
    )
    authoring = _authoring_from_json(data["authoring"])

    coastline_path = Path(coastline_path_text)
    if not coastline_path.is_absolute():
        coastline_path = resolved.parent / coastline_path
    try:
        coastline_source = load_svg_coastline_source(coastline_path)
    except CoastlineInputError as error:
        raise TerrainProjectInputError(f"Could not load project coastline: {error}") from error
    if coastline_source.sha256 != declared_sha256:
        raise TerrainProjectInputError(
            "The coastline SVG does not match the SHA-256 recorded by this project."
        )

    try:
        coastline_source.validate_scale(settings.object_scale_km)
    except ValueError as error:
        raise TerrainProjectInputError(str(error)) from error
    context = context_from_json(data["world_context"])
    validate_context_source(context, coastline_source.world_terrain)
    project = TerrainProject(
        coastline=coastline_source.coastline,
        settings=settings,
        constraints=constraints,
        authoring=authoring,
        world_context=context,
    )
    return LoadedTerrainProject(project=project, coastline_source=coastline_source, path=resolved)


INPUT_SNAPSHOT_SCHEMA = "map-maker.terrain-input-snapshot"
INPUT_SNAPSHOT_VERSION = 4


def project_snapshot_to_json(project: TerrainProject) -> dict[str, object]:
    """Portable effective inputs; no external source paths or ambiguous constraint types."""
    return {
        "schema": INPUT_SNAPSHOT_SCHEMA, "schema_version": INPUT_SNAPSHOT_VERSION,
        "coastline": asdict(project.coastline), "settings": settings_to_json(project.settings),
        "constraints": [_constraint_to_json(c) for c in project.constraints],
        "authoring": _authoring_to_json(project.authoring),
        "world_context": context_to_json(project.world_context),
    }


def project_snapshot_from_json(value: object) -> TerrainProject:
    """Read only the current effective-input contract without reopening authored files."""
    data = _mapping(value, "input snapshot")
    _require_keys(data, {"schema", "schema_version", "coastline", "settings", "constraints",
                         "authoring", "world_context"}, "input snapshot")
    if (data["schema"] != INPUT_SNAPSHOT_SCHEMA
            or _integer(data["schema_version"], "snapshot version") != INPUT_SNAPSHOT_VERSION):
        raise TerrainProjectInputError("Unsupported terrain input snapshot; rebuild the parent.")
    coast = _mapping(data["coastline"], "snapshot coastline")
    _require_keys(coast, {"points", "holes", "additional_components", "source_name"},
                  "snapshot coastline")

    def holes(value: object) -> tuple[tuple[tuple[float, float], ...], ...]:
        return tuple(_points(ring, "hole") for ring in _sequence(value, "holes"))

    components: list[LandComponent] = []
    for item in _sequence(coast["additional_components"], "additional components"):
        part = _mapping(item, "land component")
        _require_keys(part, {"exterior", "holes"}, "land component")
        components.append(LandComponent(_points(part["exterior"], "exterior"),
                                        holes(part["holes"])))
    return TerrainProject(
        Coastline(_points(coast["points"], "coastline points"),
                  _string(coast["source_name"], "source name"), holes(coast["holes"]),
                  tuple(components)),
        _settings_from_json(data["settings"]),
        tuple(_constraint_from_json(c, i)
              for i, c in enumerate(_sequence(data["constraints"], "constraints"))),
        _authoring_from_json(data["authoring"]),
        context_from_json(data["world_context"]),
    )
