# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Lossless world-derived SVG sources with a retained world and metric provenance."""

import json
from dataclasses import asdict
from hashlib import sha256
from html import escape
from math import isfinite
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree as ET

from shapely.geometry import MultiPolygon, Polygon

from map_maker.terrain.adapters.world_geology import geology_document, geology_from_bytes
from map_maker.terrain.adapters.world_project import (
    world_project_document,
    world_project_from_bytes,
)
from map_maker.terrain.domain.models import Coastline, LandComponent
from map_maker.terrain.domain.world_terrain import (
    GEOLOGY_LANDFORM_MODEL,
    MAX_PROJECTED_POINTS,
    WORLD_TERRAIN_MODEL,
    WorldTerrainProjection,
    WorldTerrainSource,
)

SOURCE_SCHEMA = "map-maker.world-terrain-source"
SOURCE_VERSION = 2
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_MARKER = b"data-map-maker-world-terrain"


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def source_document(source: WorldTerrainSource) -> dict[str, object]:
    world = world_project_document(source.world)
    return {
        "schema": SOURCE_SCHEMA,
        "version": SOURCE_VERSION,
        "model": WORLD_TERRAIN_MODEL,
        "world": world,
        "world_sha256": sha256(_json(world)).hexdigest(),
        "requested_continent_id": source.requested_continent_id,
        "included_continent_ids": list(source.included_continent_ids),
        "feature_ids": list(source.feature_ids),
        "projection": asdict(source.projection),
        "axes": "projected-east-south-metres",
        "coastline": asdict(source.coastline),
        "geology": None if source.geology is None else {
            "model": GEOLOGY_LANDFORM_MODEL,
            "recipe": geology_document(source.geology),
        },
    }


def source_svg(source: WorldTerrainSource) -> bytes:
    """Canonical visible paths and metadata describe exactly the same polygons."""
    coast = source.coastline
    x0, y0, x1, y1 = coast.bounds

    def ring(points: tuple[tuple[float, float], ...]) -> str:
        return "M" + " L".join(f"{x:.17g},{y:.17g}" for x, y in points[:-1]) + " Z"

    paths = "\n".join(
        f'<path id="land-{i}" fill-rule="evenodd" d="'
        + " ".join(ring(r) for r in (part.exterior, *part.holes))
        + '"/>'
        for i, part in enumerate(coast.components)
    )
    metadata = escape(_json(source_document(source)).decode("utf-8"), quote=False)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" data-map-maker-world-terrain="1" '
        f'viewBox="{x0:.17g} {y0:.17g} {x1 - x0:.17g} {y1 - y0:.17g}">\n'
        f'<metadata id="map-maker-world-terrain">{metadata}</metadata>\n'
        f'<g id="LandShapes" fill="#799369">\n{paths}\n</g>\n</svg>\n'
    ).encode()


def _record(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("World-derived coastline fields do not match the current format.")
    return cast(dict[str, Any], value)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate world-derived coastline field.")
        result[key] = value
    return result


def _coastline(value: object) -> Coastline:
    data = _record(value, {"points", "holes", "additional_components", "source_name"})
    count = 0

    def ring(value: object) -> tuple[tuple[float, float], ...]:
        nonlocal count
        if not isinstance(value, list):
            raise ValueError("Coastline rings must be coordinate arrays.")
        count += len(value)
        if not len(value) >= 4 or count > MAX_PROJECTED_POINTS:
            raise ValueError("World-derived coastline exceeds its point budget.")
        points: list[tuple[float, float]] = []
        for p in cast(list[object], value):
            if not isinstance(p, list) or len(p) != 2:
                raise ValueError("Coastline points require two metric coordinates.")
            if any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)
                for v in cast(list[object], p)
            ):
                raise ValueError("Coastline coordinates must be finite numbers.")
            points.append((float(p[0]), float(p[1])))
        return tuple(points)

    def holes(value: object) -> tuple[tuple[tuple[float, float], ...], ...]:
        if not isinstance(value, list):
            raise ValueError("Coastline holes must be arrays.")
        return tuple(ring(v) for v in cast(list[object], value))

    if not isinstance(data["source_name"], str) or not data["source_name"].strip():
        raise ValueError("World-derived coastline needs a name.")
    if not isinstance(data["additional_components"], list):
        raise ValueError("Coastline components must be an array.")
    others = []
    for item in cast(list[object], data["additional_components"]):
        part = _record(item, {"exterior", "holes"})
        others.append(LandComponent(ring(part["exterior"]), holes(part["holes"])))
    coast = Coastline(
        ring(data["points"]), data["source_name"], holes(data["holes"]), tuple(others)
    )
    polygons = [Polygon(p.exterior, p.holes) for p in coast.components]
    if any(not p.is_valid or p.area <= 0 for p in polygons):
        raise ValueError("World-derived coastline contains invalid land polygons.")
    # Subtracting continental-scale areas can lose several square centimetres
    # even for disjoint polygons. Validate topology directly.
    if not MultiPolygon(polygons).is_valid:
        raise ValueError("World-derived coastline components overlap.")
    return coast


def read_world_terrain_svg(path: Path) -> WorldTerrainSource | None:
    """Recognize our generated dialect without changing ordinary authored SVG import."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if _MARKER not in raw:
        return None
    if len(raw) > MAX_SOURCE_BYTES or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("World-derived SVG is oversized or has unsupported declarations.")
    try:
        root = ET.fromstring(raw)
        metadata = root.find("{http://www.w3.org/2000/svg}metadata")
        if metadata is None or metadata.text is None:
            raise ValueError("World-derived SVG metadata is missing.")
        doc = _record(
            json.loads(metadata.text, object_pairs_hook=_unique),
            {
                "schema",
                "version",
                "model",
                "world",
                "world_sha256",
                "requested_continent_id",
                "included_continent_ids",
                "feature_ids",
                "projection",
                "axes",
                "coastline",
                "geology",
            },
        )
        if (
            doc["schema"] != SOURCE_SCHEMA
            or type(doc["version"]) is not int
            or doc["version"] != SOURCE_VERSION
            or doc["model"] != WORLD_TERRAIN_MODEL
            or doc["axes"] != "projected-east-south-metres"
        ):
            raise ValueError("Unsupported world-derived coastline format.")
        world_bytes = _json(doc["world"])
        if sha256(world_bytes).hexdigest() != doc["world_sha256"]:
            raise ValueError("Retained world identity does not match its snapshot.")
        world = world_project_from_bytes(world_bytes)
        projection = WorldTerrainProjection(
            **_record(
                doc["projection"],
                {
                    "radius_km",
                    "longitude_deg",
                    "latitude_deg",
                    "maximum_angle_deg",
                    "maximum_transverse_scale",
                    "curve_tolerance_m",
                    "source_step_deg",
                },
            )
        )
        if projection.radius_km != world.frame.radius_km:
            raise ValueError("Projected source and world disagree about the planet radius.")
        included, features = doc["included_continent_ids"], doc["feature_ids"]
        if (
            not isinstance(included, list)
            or not included
            or any(not isinstance(v, str) for v in cast(list[object], included))
            or included != sorted(set(included))
            or not set(included) <= {c.id for c in world.continents}
            or doc["requested_continent_id"] not in included
            or not isinstance(features, list)
            or not features
            or any(not isinstance(v, str) for v in cast(list[object], features))
            or features != sorted(set(features))
            or not set(features)
            <= {a.feature_id for a in world.assignments if a.continent_id in included}
        ):
            raise ValueError("World-derived coastline ownership is inconsistent.")
        geology = None
        if doc["geology"] is not None:
            transfer = _record(doc["geology"], {"model", "recipe"})
            if transfer["model"] != GEOLOGY_LANDFORM_MODEL:
                raise ValueError("Unsupported geological landform transfer.")
            geology = geology_from_bytes(_json(transfer["recipe"]))
            if geology.world != world:
                raise ValueError("Geology and terrain must retain the same world.")
        result = WorldTerrainSource(
            world,
            doc["requested_continent_id"],
            tuple(included),
            tuple(features),
            _coastline(doc["coastline"]),
            projection,
            geology,
        )
        # Do not accept metadata describing one coast while the visible SVG draws
        # another. Regenerate from world inputs instead of editing this artifact.
        if source_svg(result) != raw:
            raise ValueError("World-derived SVG changed; recreate it from the world source.")
        return result
    except (ET.ParseError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise ValueError(f"Invalid world-derived SVG: {error}") from error
