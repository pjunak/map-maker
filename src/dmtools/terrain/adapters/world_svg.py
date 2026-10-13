# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Retain SVG shape identity and source coordinates without coastline repair."""

from hashlib import sha256
from io import StringIO
from itertools import pairwise
from math import isfinite
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.parsers import expat

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize, unary_union
from svgelements import SVG, Group, Move, Shape
from svgelements import Path as SvgPath

from dmtools.terrain.adapters.svg import flatten_svg_path
from dmtools.terrain.domain.models import LandComponent, Point2D
from dmtools.terrain.domain.world import Bounds, WorldFeature, WorldSource

MAX_SVG_BYTES = 8 * 1024 * 1024
MAX_WORLD_FEATURES = 4096
MAX_WORLD_POINTS = 500_000
# Root attribute of a map exported from a planet's refined coast: the finest
# coast wavelength (km) it already carries.
COAST_DETAIL_ATTRIBUTE = "data-dmtools-coast-detail-km"
WORLD_IMPORTER = "retained-svg-v2"


def polygon_components(geometry: Polygon | MultiPolygon) -> tuple[LandComponent, ...]:
    polygons = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
    return tuple(
        LandComponent(
            tuple((float(x), float(y)) for x, y in polygon.exterior.coords),
            tuple(
                tuple((float(x), float(y)) for x, y in ring.coords) for ring in polygon.interiors
            ),
        )
        for polygon in sorted(polygons, key=lambda p: (*p.bounds, p.area))
    )


def _winding_number(points: list[Point2D], x: float, y: float) -> int:
    winding = 0
    for (x0, y0), (x1, y1) in pairwise(points):
        side = (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0)
        # Half-open crossings count a shared vertex once and ignore horizontal edges.
        if y0 <= y < y1 and side > 0:
            winding += 1
        elif y1 <= y < y0 and side < 0:
            winding -= 1
    return winding


def _shape_geometry(shape: Shape, tolerance: float) -> tuple[LandComponent, ...]:
    path = SvgPath(shape)
    path.reify()
    rings: list[list[Point2D]] = []
    for subpath in path.as_subpaths():
        part = SvgPath(subpath)
        # A compound-path Move can retain the previous ring's endpoint as its
        # start. It is not part of this ring and must not become its first vertex.
        if len(part) and isinstance(part[0], Move):
            part[0].start = None
        if part.first_point is None or part.current_point is None:
            continue
        if part.first_point != part.current_point:
            raise ValueError("Open path: close it in the source, or exclude it from land.")
        points = flatten_svg_path(part, tolerance)
        if len(points) < 4:
            raise ValueError("Shape has no closed area.")
        if any(not isfinite(v) for point in points for v in point):
            raise ValueError("Shape has non-finite coordinates.")
        rings.append(points)
    if not rings:
        raise ValueError("Shape contains no closed land rings.")
    if sum(map(len, rings)) > MAX_WORLD_POINTS:
        raise ValueError("Shape exceeds 500,000 sampled points.")
    evenodd = (shape.values or {}).get("fill-rule", "nonzero") == "evenodd"
    # SVG allows self-intersections and retraced edges. Node the sampled paths,
    # then classify each face using the ORIGINAL directed segments; polygon
    # validity repair or face orientation would lose nonzero/evenodd semantics.
    faces = polygonize(unary_union([LineString(points) for points in rings]))
    selected: list[Polygon] = []
    for face in faces:
        point = face.representative_point()
        winding = sum(_winding_number(points, point.x, point.y) for points in rings)
        if (winding % 2 != 0) if evenodd else (winding != 0):
            selected.append(face)
    geometry = unary_union(selected)
    if (
        not isinstance(geometry, (Polygon, MultiPolygon))
        or geometry.is_empty
        or not geometry.is_valid
    ):
        raise ValueError("Shape does not produce valid filled land.")
    return polygon_components(geometry)


def _label(element: Group | Shape) -> str:
    attributes = (element.values or {}).get("attributes", {})
    return str(
        attributes.get("{https://www.affinity.studio/}id")
        or attributes.get("{http://www.serif.com/}id")
        or attributes.get("{http://www.inkscape.org/namespaces/inkscape}label")
        or attributes.get("id")
        or ""
    )


def _xml_root(svg: str) -> ET.Element:
    # A normal SVG export's external DOCTYPE is metadata, not a dependency.
    # Expat checks its structure without loading its system/public identifier.
    # Reject internal subsets before declarations can expand or change the tree.
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def doctype(name: str, _system: str | None, _public: str | None, internal: int) -> None:
        if name.rsplit(":", 1)[-1] != "svg" or internal:
            raise ValueError("World SVG cannot contain an internal DTD subset or custom entities.")

    def reject_entity(*_args: object) -> int:
        raise ValueError("World SVG cannot resolve custom XML entities.")

    root_offset = 0

    def first_element(_name: str, _attributes: dict[str, str]) -> None:
        nonlocal root_offset
        root_offset = parser.CurrentByteIndex
        parser.StartElementHandler = None

    parser.StartElementHandler = first_element
    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = reject_entity
    parser.ExternalEntityRefHandler = reject_entity
    parser.SkippedEntityHandler = reject_entity
    try:
        parser.Parse(svg, True)
        # Remove only the parsed prolog from the derived copy. Without a DTD,
        # ElementTree rejects unresolved entity references even in attributes
        # (Expat can otherwise silently omit them when an external DTD is skipped).
        return ET.fromstring(svg.encode("utf-8")[root_offset:].decode("utf-8"))
    except (expat.ExpatError, ET.ParseError) as error:
        raise ValueError(f"Invalid world SVG: {error}") from error


def parse_world_svg(svg: str, name: str) -> WorldSource:
    """Parse a bounded UTF-8 snapshot; retain original bytes through UTF-8 round trips."""
    if not name.strip() or len(name) > 256:
        raise ValueError("World source name must contain 1-256 non-blank characters.")
    raw = svg.encode("utf-8")
    if not raw or len(raw) > MAX_SVG_BYTES:
        raise ValueError("World SVG must be non-empty and at most 8 MiB.")
    root = _xml_root(svg)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("World source must have an SVG root.")
    seen: set[str] = set()
    nodes = list(root.iter())
    if len(nodes) > 30_000:
        raise ValueError("World SVG exceeds 30,000 XML elements.")
    for node in nodes:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in {"use", "image", "foreignObject", "script"} or (
            tag == "svg" and node is not root
        ):
            raise ValueError(f"Unsupported SVG {tag}; export explicit vector paths.")
        identity = node.get("id")
        if identity:
            if identity in seen:
                raise ValueError(f"Duplicate SVG ID: {identity}. Give source objects unique IDs.")
            seen.add(identity)
    viewbox = root.get("viewBox")
    try:
        if viewbox:
            x, y, width, height = map(float, viewbox.replace(",", " ").split())
        else:
            x, y = 0.0, 0.0
            width = float(root.get("width", "360").removesuffix("px"))
            height = float(root.get("height", "180").removesuffix("px"))
    except ValueError as error:
        raise ValueError("Use a numeric SVG viewBox to identify source coordinates.") from error
    if not all(isfinite(v) for v in (x, y, width, height)) or width <= 0 or height <= 0:
        raise ValueError("SVG viewBox must have finite coordinates and positive dimensions.")
    bounds: Bounds = (x, y, x + width, y + height)
    # SVG.parse normally converts the viewBox to display pixels. World coordinates
    # belong to the original source frame, independent of export width or height.
    root.attrib.pop("viewBox", None)
    root.set("width", str(width))
    root.set("height", str(height))
    root.attrib.pop("preserveAspectRatio", None)
    document = SVG.parse(
        StringIO(ET.tostring(root, encoding="unicode")),
        reify=True,
        parse_display_none=True,
        on_error="raise",
    )
    features: list[WorldFeature] = []
    ids: set[str] = set()
    total_points = 0
    tolerance = max(width, height) / 32_768

    def visit(element: object, groups: tuple[str, ...] = (), unsupported: bool = False) -> None:
        nonlocal total_points
        if isinstance(element, (Group, Shape)):
            attrs = (element.values or {}).get("attributes", {})
            unsupported = unsupported or any(
                (element.values or {}).get(key, attrs.get(key, "none")) != "none"
                for key in ("clip-path", "mask")
            )
        if isinstance(element, Shape):
            if len(features) >= MAX_WORLD_FEATURES:
                raise ValueError("World SVG exceeds 4,096 shapes.")
            label = _label(element) or (groups[-1] if groups else type(element).__name__)
            path = SvgPath(element)
            path.reify()
            identity = str(element.id or "")
            if not identity:
                identity = (
                    "shape-"
                    + sha256(("/".join(groups) + "\n" + str(path)).encode("utf-8")).hexdigest()[:24]
                )
            if identity in ids:
                raise ValueError("Indistinguishable unnamed shapes; assign unique SVG IDs.")
            if len(identity) > 256:
                raise ValueError("SVG object IDs must be at most 256 characters.")
            ids.add(identity)
            issue = ""
            components: tuple[LandComponent, ...] = ()
            try:
                if unsupported:
                    raise ValueError("Clipped/masked shape: export outlines or exclude it.")
                components = _shape_geometry(element, tolerance)
            except (ValueError, TypeError, OverflowError) as error:
                issue = str(error)
            total_points += sum(len(c.exterior) + sum(map(len, c.holes)) for c in components)
            if total_points > MAX_WORLD_POINTS:
                raise ValueError("World inspection geometry exceeds 500,000 sampled points.")
            features.append(WorldFeature(identity, label, groups, components, issue))
        elif isinstance(element, Group):
            label = _label(element)
            ancestry = (*groups, label) if element is not document and label else groups
            for child in element:
                visit(child, ancestry, unsupported)

    visit(document)
    if not features:
        raise ValueError("The SVG contains no supported vector shapes to assign.")
    return WorldSource(name, svg, sha256(raw).hexdigest(), tuple(features), bounds)


def drawn_coast_detail_km(svg: str) -> float | None:
    """The coast detail (km) a DM Tools refined-coast export declares on its root, if any."""
    value = _xml_root(svg).get(COAST_DETAIL_ATTRIBUTE)
    try:
        km = float(value) if value is not None else None
    except ValueError:
        return None
    return km if km is not None and isfinite(km) and km > 0 else None


def load_world_svg(path: Path) -> WorldSource:
    if path.suffix.lower() != ".svg":
        raise ValueError("Import an SVG world map; native Affinity files are not supported.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SVG_BYTES + 1)
    if len(raw) > MAX_SVG_BYTES:
        raise ValueError("World SVG exceeds 8 MiB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Export the world SVG with UTF-8 text encoding.") from error
    return parse_world_svg(text, path.name)
