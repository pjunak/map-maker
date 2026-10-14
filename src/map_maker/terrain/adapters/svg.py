# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportArgumentType=false, reportOptionalMemberAccess=false
"""Read and dissolve closed land shapes from an SVG document."""

from dataclasses import dataclass
from hashlib import file_digest
from math import hypot, isclose
from pathlib import Path as FilePath
from typing import Any

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.validation import explain_validity
from svgelements import SVG, Close, Group, Line, Move, Path, Shape

from map_maker.terrain.domain import Coastline, LandComponent
from map_maker.terrain.domain.world_terrain import WorldTerrainSource


class CoastlineInputError(ValueError):
    """The imported vector cannot serve as supported land geometry."""


@dataclass(frozen=True, slots=True)
class CoastlineSource:
    """A parsed coastline and the fingerprint of its authoritative SVG source."""

    path: FilePath
    sha256: str
    coastline: Coastline
    world_terrain: WorldTerrainSource | None = None

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise ValueError("Coastline source path must be absolute.")
        invalid_character = any(
            character not in "0123456789abcdef" for character in self.sha256
        )
        if len(self.sha256) != 64 or invalid_character:
            raise ValueError("Coastline source SHA-256 is invalid.")
        if self.world_terrain is not None and self.world_terrain.coastline != self.coastline:
            raise ValueError("World-derived coastline and its source record disagree.")

    def validate_scale(self, object_scale_km: float) -> None:
        if self.world_terrain is not None and not isclose(
            object_scale_km, self.world_terrain.object_scale_km, rel_tol=1e-12, abs_tol=1e-9,
        ):
            raise ValueError("World-derived terrain scale is fixed by the world projection.")


def coastline_sha256(source: FilePath) -> str:
    """Fingerprint a coastline source without loading the whole file into memory."""

    try:
        with source.open("rb") as stream:
            return file_digest(stream, "sha256").hexdigest()
    except OSError as error:
        raise CoastlineInputError(f"Could not read SVG: {error}") from error


def _same_point(first: tuple[float, float], second: tuple[float, float], tolerance: float) -> bool:
    return hypot(first[0] - second[0], first[1] - second[1]) <= tolerance


def _normalized_group_name(group: Group) -> str:
    attributes = group.values.get("attributes", {})
    raw_name = (
        attributes.get("{http://www.serif.com/}id")
        or attributes.get("id")
        or ""
    )
    return "".join(character for character in str(raw_name).casefold() if character.isalnum())


def _iter_groups(element: object) -> list[Group]:
    groups: list[Group] = []
    if isinstance(element, Shape):
        return groups
    if isinstance(element, Group):
        groups.append(element)
    try:
        children = iter(element)  # type: ignore[arg-type]
    except TypeError:
        return groups
    for child in children:
        groups.extend(_iter_groups(child))
    return groups


def _iter_shapes(element: object) -> list[Shape]:
    if isinstance(element, Shape):
        return [element]
    try:
        children = iter(element)  # type: ignore[arg-type]
    except TypeError:
        return []
    shapes: list[Shape] = []
    for child in children:
        shapes.extend(_iter_shapes(child))
    return shapes


def _land_shapes(document: SVG) -> list[Shape]:
    """Prefer explicit Land Shapes groups, falling back to all drawable shapes."""

    land_groups = [
        group for group in _iter_groups(document) if _normalized_group_name(group) == "landshapes"
    ]
    if land_groups:
        return [shape for group in land_groups for shape in _iter_shapes(group)]
    return _iter_shapes(document)


def _remove_dissolve_slivers(
    component: Polygon,
    *,
    maximum_hole_area: float,
) -> Polygon:
    """Fill only tiny enclosed gaps produced where separately drawn land pieces meet."""

    retained_holes = [
        interior.coords
        for interior in component.interiors
        if Polygon(interior).area > maximum_hole_area
    ]
    return Polygon(component.exterior.coords, holes=retained_holes)


def _point_coordinates(point: Any) -> tuple[float, float]:
    return float(point.x), float(point.y)


def _distance_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0.0:
        return hypot(point[0] - start[0], point[1] - start[1])
    position = (
        (point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y
    ) / length_squared
    position = min(1.0, max(0.0, position))
    nearest_x = start[0] + position * delta_x
    nearest_y = start[1] + position * delta_y
    return hypot(point[0] - nearest_x, point[1] - nearest_y)


def _flatten_curve(
    segment: Any,
    start_t: float,
    end_t: float,
    start: tuple[float, float],
    end: tuple[float, float],
    tolerance: float,
    depth: int = 0,
) -> list[tuple[float, float]]:
    span = end_t - start_t
    quarter = _point_coordinates(segment.point(start_t + 0.25 * span))
    middle_t = start_t + 0.5 * span
    middle = _point_coordinates(segment.point(middle_t))
    three_quarters = _point_coordinates(segment.point(start_t + 0.75 * span))
    flatness = max(
        _distance_to_segment(quarter, start, end),
        _distance_to_segment(middle, start, end),
        _distance_to_segment(three_quarters, start, end),
    )
    if flatness <= tolerance or depth >= 12:
        return [end]
    return [
        *_flatten_curve(
            segment,
            start_t,
            middle_t,
            start,
            middle,
            tolerance,
            depth + 1,
        ),
        *_flatten_curve(
            segment,
            middle_t,
            end_t,
            middle,
            end,
            tolerance,
            depth + 1,
        ),
    ]


def flatten_svg_path(path: Path, tolerance: float) -> list[tuple[float, float]]:
    if path.first_point is None:
        return []
    points = [_point_coordinates(path.first_point)]
    curves: list[Any] = []
    for segment in path:
        if isinstance(segment, Move) or segment.end is None:
            continue
        end = _point_coordinates(segment.end)
        if isinstance(segment, (Line, Close)):
            candidate_points = [end]
        else:
            curves.append(segment)
            candidate_points = _flatten_curve(
                segment,
                0.0,
                1.0,
                _point_coordinates(segment.start),
                end,
                tolerance,
            )
        for candidate in candidate_points:
            if candidate != points[-1]:
                points.append(candidate)

    if len(points) < 4 and curves:
        points = [_point_coordinates(path.first_point)]
        for segment in path:
            if isinstance(segment, Move) or segment.end is None:
                continue
            if isinstance(segment, (Line, Close)):
                candidate_points = [_point_coordinates(segment.end)]
            else:
                candidate_points = [
                    _point_coordinates(segment.point(position))
                    for position in (0.25, 0.5, 0.75, 1.0)
                ]
            for candidate in candidate_points:
                if candidate != points[-1]:
                    points.append(candidate)
    return points


def _uniform_sample_path(
    path: Path,
    *,
    sample_count: int,
    length_error: float,
) -> list[tuple[float, float]]:
    positions = np.linspace(0.0, 1.0, sample_count, endpoint=False, dtype=np.float64)
    sampled_array = np.asarray(path.npoint(positions, error=length_error), dtype=np.float64)
    if sampled_array.shape != (sample_count, 2) or not np.all(np.isfinite(sampled_array)):
        return []
    sampled = [(float(x), float(y)) for x, y in sampled_array]
    sampled.append(sampled[0])
    return sampled


def load_svg_coastline(source: FilePath, *, sample_count: int = 4_096) -> Coastline:
    """Load closed land shapes, dissolve shared borders, and flatten their coasts."""

    if source.suffix.lower() != ".svg":
        raise CoastlineInputError("The first version accepts SVG files only.")
    if sample_count < 32:
        raise ValueError("sample_count must be at least 32.")

    # Prepared sources carry exact numeric polygons, including holes and narrow
    # gaps. Their canonical visible paths are verified by the owning adapter.
    from map_maker.terrain.adapters.world_terrain_source import read_world_terrain_svg

    try:
        prepared = read_world_terrain_svg(source)
        if prepared is not None:
            return prepared.coastline
        document = SVG.parse(str(source), reify=True, on_error="raise")
    except (OSError, ValueError, TypeError) as error:
        raise CoastlineInputError(f"Could not read SVG: {error}") from error

    shapes = _land_shapes(document)
    if not shapes:
        raise CoastlineInputError("The SVG contains no drawable land shapes.")

    paths: list[Path] = []
    bounds: list[tuple[float, float, float, float]] = []
    for index, shape in enumerate(shapes, start=1):
        path = Path(shape)
        path.reify()
        if path.count_subpaths() != 1:
            raise CoastlineInputError(
                f"Land object {index} must contain exactly one continuous subpath."
            )
        if len(path) < 2 or path.first_point is None or path.current_point is None:
            raise CoastlineInputError(f"Land object {index} is empty.")
        bbox = path.bbox()
        if bbox is None:
            raise CoastlineInputError(f"Land object {index} has no measurable bounds.")
        paths.append(path)
        bounds.append(tuple(float(value) for value in bbox))

    min_x = min(bound[0] for bound in bounds)
    min_y = min(bound[1] for bound in bounds)
    max_x = max(bound[2] for bound in bounds)
    max_y = max(bound[3] for bound in bounds)
    longest_span = max(max_x - min_x, max_y - min_y)
    tolerance = max(1e-9, longest_span * 1e-9)
    polygons: list[Polygon] = []
    flatten_tolerance = longest_span / (sample_count * 2.0)
    length_error = max(1e-6, longest_span * 1e-6)
    for index, path in enumerate(paths, start=1):
        first = (float(path.first_point.x), float(path.first_point.y))
        last = (float(path.current_point.x), float(path.current_point.y))
        if not _same_point(first, last, tolerance):
            raise CoastlineInputError(
                f"Land object {index} is open; join its final node to its first node."
            )
        sampled = flatten_svg_path(path, flatten_tolerance)
        if sampled and sampled[-1] != sampled[0]:
            sampled.append(sampled[0])
        polygon = Polygon(sampled)
        if not polygon.is_valid:
            fallback_sample_count = max(256, min(sample_count, 4 * len(path)))
            sampled = _uniform_sample_path(
                path,
                sample_count=fallback_sample_count,
                length_error=length_error,
            )
            polygon = Polygon(sampled)
        if not polygon.is_valid:
            raise CoastlineInputError(
                f"Land object {index} is not a valid loop: {explain_validity(polygon)}"
            )
        if polygon.area <= 0:
            raise CoastlineInputError(f"Land object {index} encloses no area.")
        polygons.append(polygon)

    dissolved = unary_union(polygons)
    if isinstance(dissolved, MultiPolygon):
        seam_radius = flatten_tolerance / 2.0
        dissolved = dissolved.buffer(
            seam_radius,
            quad_segs=1,
            join_style="mitre",
        ).buffer(
            -seam_radius,
            quad_segs=1,
            join_style="mitre",
        )
    if isinstance(dissolved, Polygon):
        components = [dissolved]
    elif isinstance(dissolved, MultiPolygon):
        components = list(dissolved.geoms)
    else:
        raise CoastlineInputError("The land shapes could not be dissolved into valid polygons.")
    if not dissolved.is_valid or dissolved.area <= 0:
        raise CoastlineInputError(
            f"The dissolved land geometry is invalid: {explain_validity(dissolved)}"
        )

    maximum_sliver_area = longest_span * longest_span * 2e-6
    components = [
        _remove_dissolve_slivers(
            component,
            maximum_hole_area=maximum_sliver_area,
        )
        for component in components
    ]
    components.sort(key=lambda component: (-component.area, *component.bounds))
    land_components = [
        LandComponent(
            exterior=tuple((float(x), float(y)) for x, y in component.exterior.coords),
            holes=tuple(
                tuple((float(x), float(y)) for x, y in interior.coords)
                for interior in component.interiors
            ),
        )
        for component in components
    ]
    primary = land_components[0]
    return Coastline(
        points=primary.exterior,
        source_name=source.name,
        holes=primary.holes,
        additional_components=tuple(land_components[1:]),
    )


def load_svg_coastline_source(source: FilePath) -> CoastlineSource:
    """Load a coastline with stable source provenance for project persistence."""

    try:
        resolved = source.resolve(strict=True)
    except OSError as error:
        raise CoastlineInputError(f"Could not read SVG: {error}") from error
    before = coastline_sha256(resolved)
    from map_maker.terrain.adapters.world_terrain_source import read_world_terrain_svg

    try:
        prepared = read_world_terrain_svg(resolved)
    except (OSError, ValueError) as error:
        raise CoastlineInputError(str(error)) from error
    coastline = prepared.coastline if prepared else load_svg_coastline(resolved)
    after = coastline_sha256(resolved)
    if before != after:
        raise CoastlineInputError("The SVG changed while it was being imported; import it again.")
    return CoastlineSource(path=resolved, sha256=after, coastline=coastline,
                           world_terrain=prepared)
