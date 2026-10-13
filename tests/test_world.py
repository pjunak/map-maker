"""World source ownership, coordinates, topology and portable current-format contracts."""

import json
from dataclasses import replace
from math import pi, sin
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from shapely.geometry import Point, Polygon

from dmtools.cli import main
from dmtools.terrain.adapters.world_project import read_world_project, world_project_document
from dmtools.terrain.adapters.world_render import OCEAN, render_world_source
from dmtools.terrain.adapters.world_svg import parse_world_svg
from dmtools.terrain.application.world import open_world, propose_group_assignments, save_world
from dmtools.terrain.domain.models import LandComponent
from dmtools.terrain.domain.world import WorldAssignment, WorldContinent, WorldFrame, WorldProject
from dmtools.terrain.pipeline.world import component_area_km2, prepare_world_map
from dmtools.terrain.viewport import MapViewport

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/world/four-shores.dmworld.json"


def source(body: str, *, width: int = 360) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="180" '
        f'viewBox="0 0 360 180">{body}</svg>'
    )


def world(body: str) -> WorldProject:
    imported = parse_world_svg(source(body), "test.svg")
    return WorldProject(
        "Test world",
        imported,
        WorldFrame((0, 0, 360, 180), 1000),
        (WorldContinent("c", "Continent"),),
        tuple(WorldAssignment(f.id, "c", "mainland") for f in imported.features),
    )


def different_owners(project: WorldProject) -> WorldProject:
    return replace(
        project,
        continents=(WorldContinent("c", "First"), WorldContinent("other", "Second")),
        assignments=tuple(
            replace(a, continent_id="c" if index == 0 else "other")
            for index, a in enumerate(project.assignments)
        ),
    )


def test_explicit_frame_roundtrips_offset_radius_and_central_meridian() -> None:
    frame = WorldFrame((17, 11, 2897, 1451), 4321, 35)
    for point in ((17.0, 11.0), (2897.0, 1451.0), (1457.0, 731.0), (45.0, 400.0)):
        assert frame.lonlat_to_source(frame.source_to_lonlat(point, wrap=False), wrap=False) == (
            pytest.approx(point)
        )
    assert frame.source_to_lonlat((1457, 731)) == (35, 0)
    assert frame.distance_km((0, 0), (90, 0)) == pytest.approx(pi * 4321 / 2)
    assert frame.distance_km((179, 0), (-179, 0)) == pytest.approx(pi * 4321 / 90)
    assert frame.distance_km((10, 90), (150, 90)) == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("radius", [0, -1, float("nan"), float("inf"), 1e300, 1e-300])
def test_world_frame_rejects_unusable_numeric_scale(radius: float) -> None:
    with pytest.raises(ValueError):
        WorldFrame((0, 0, 360, 180), radius)


def test_custom_sphere_area_uses_latitude_and_holes() -> None:
    frame = WorldFrame((0, 0, 360, 180), 2000)
    rectangle = LandComponent(((0, 0), (360, 0), (360, 180), (0, 180), (0, 0)))
    assert component_area_km2(rectangle, frame) == pytest.approx(frame.surface_area_km2)
    cap = replace(rectangle, exterior=((0, 0), (360, 0), (360, 30), (0, 30), (0, 0)))
    assert component_area_km2(cap, frame) == pytest.approx(
        2 * pi * frame.radius_km**2 * (1 - sin(pi / 3))
    )
    equator = LandComponent(((10, 80), (20, 80), (20, 90), (10, 90), (10, 80)))
    poleward = replace(equator, exterior=tuple((x, y - 60) for x, y in equator.exterior))
    assert component_area_km2(equator, frame) > component_area_km2(poleward, frame)


def test_svg_display_size_does_not_rescale_source_and_nested_transforms() -> None:
    body = (
        '<g id="A" transform="translate(10,20)"><g transform="scale(2)">'
        '<path id="land" d="M0 0 H10 V10 H0 Z"/></g></g>'
    )
    small = parse_world_svg(source(body), "world.svg")
    large = parse_world_svg(source(body, width=1440), "world.svg")
    assert small.features == large.features
    assert Polygon(small.features[0].components[0].exterior).bounds == (10, 20, 30, 40)
    assert small.svg == source(body)


@pytest.mark.parametrize(
    "fill_rule,inner,holes",
    [
        ("evenodd", "M 5 5 H 15 V 15 H 5 Z", 1),
        ("nonzero", "M 5 5 H 15 V 15 H 5 Z", 0),
        ("nonzero", "M 5 5 V 15 H 15 V 5 Z", 1),
    ],
)
def test_compound_paths_retain_svg_fill_semantics(fill_rule: str, inner: str, holes: int) -> None:
    parsed = parse_world_svg(
        source(f'<path id="a" fill-rule="{fill_rule}" d="M0 0 H20 V20 H0 Z {inner}"/>'), "world.svg"
    )
    feature = parsed.features[0]
    assert not feature.issue
    assert len(feature.components[0].holes) == holes
    polygon = Polygon(feature.components[0].exterior, feature.components[0].holes)
    assert polygon.covers(Point(10, 10)) == (holes == 0)


def test_tiny_holes_and_gaps_are_not_repaired_by_world_import() -> None:
    project = world(
        '<path id="a" fill-rule="evenodd" '
        'd="M0 0 H20 V20 H0 Z M5 5 H5.0001 V5.0001 H5 Z"/>'
        '<path id="b" d="M20.00001 0 H30 V20 H20.00001 Z"/>'
    )
    result = prepare_world_map(project)
    first = result.land[0].components[0]
    assert len(first.holes) == 1
    assert len(result.land) == 2
    assert Polygon(first.exterior, first.holes).area < 400


def test_touching_named_continents_keep_ownership_and_islands() -> None:
    result = open_world(EXAMPLE)
    assert len(result.continents) == 4
    assert {c.name for c in result.continents} == {
        "Westreach",
        "Eastreach",
        "Southmere",
        "Seam Isles",
    }
    assert sum(c.island_shapes for c in result.continents) == 3
    assert "scale-bar" not in {f.feature_id for f in result.land}
    assert len(next(f for f in result.land if f.feature_id == "seam-island").components) == 2
    assert 0 < result.land_fraction < 1


def test_seam_wrapping_does_not_duplicate_land_area() -> None:
    crossing = prepare_world_map(world('<path id="a" d="M355 80 H365 V100 H355 Z"/>'))
    middle = prepare_world_map(world('<path id="a" d="M175 80 H185 V100 H175 Z"/>'))
    assert len(crossing.land[0].components) == 2
    assert crossing.land_area_km2 == pytest.approx(middle.land_area_km2)
    assert max(x for x, _ in crossing.project.source.features[0].components[0].exterior) == 365


def test_seam_and_ordinary_overlaps_are_explicit_errors() -> None:
    for paths in (
        '<path id="a" d="M0 0 H20 V20 H0 Z"/><path id="b" d="M10 0 H30 V20 H10 Z"/>',
        '<path id="a" d="M355 80 H365 V100 H355 Z"/><path id="b" d="M0 80 H10 V100 H0 Z"/>',
    ):
        with pytest.raises(ValueError, match="overlap"):
            prepare_world_map(different_owners(world(paths)))


def test_source_order_does_not_change_stable_feature_identity_or_area() -> None:
    first = '<g id="North"><path id="a" d="M10 10 H30 V30 H10 Z"/></g>'
    second = '<g id="South"><path id="b" d="M50 50 H70 V70 H50 Z"/></g>'
    a, b = world(first + second), world(second + first)
    assert {f.id: f for f in a.source.features} == {f.id: f for f in b.source.features}
    assert prepare_world_map(a).land == prepare_world_map(b).land
    assert prepare_world_map(a).land_area_km2 == prepare_world_map(b).land_area_km2


@pytest.mark.parametrize(
    "body,match",
    [
        ('<path id="a"/><path id="a"/>', "Duplicate SVG ID"),
        ('<use href="#a"/>', "Unsupported SVG use"),
        ('<image href="external.png"/>', "Unsupported SVG image"),
    ],
)
def test_ambiguous_or_external_svg_features_are_rejected(body: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_world_svg(source(body), "world.svg")


def test_open_shapes_must_be_explicitly_excluded() -> None:
    parsed = parse_world_svg(
        source('<path id="land" d="M0 0 H10 V10 H0 Z"/><path id="line" d="M20 20 L30 30"/>'),
        "world.svg",
    )
    assert parsed.features[1].issue
    with pytest.raises(ValueError, match="every source shape"):
        WorldProject(
            "Map",
            parsed,
            WorldFrame((0, 0, 360, 180), 1000),
            (WorldContinent("a", "A"),),
            (WorldAssignment("land", "a", "mainland"),),
        )
    project = WorldProject(
        "Map",
        parsed,
        WorldFrame((0, 0, 360, 180), 1000),
        (WorldContinent("a", "A"),),
        (WorldAssignment("land", "a", "mainland"), WorldAssignment("line", None, "exclude")),
    )
    assert len(prepare_world_map(project).land) == 1


def test_group_suggestions_are_explicit_and_do_not_change_source() -> None:
    project = read_world_project(EXAMPLE)
    original = project.source
    continents, assignments = propose_group_assignments(original)
    assert {c.name for c in continents} == {c.name for c in project.continents}
    assert next(a for a in assignments if a.feature_id == "scale-bar").role == "exclude"
    assert next(a for a in assignments if a.feature_id == "west-island").role == "island"
    assert project.source is original


def test_portable_roundtrip_needs_no_original_svg(tmp_path: Path) -> None:
    project = read_world_project(EXAMPLE)
    output = tmp_path / "portable.dmworld.json"
    save_world(project, output)
    loaded = open_world(output)
    assert loaded.project.source == project.source
    assert loaded.project.frame == project.frame
    assert set(loaded.project.assignments) == set(project.assignments)
    schema = json.loads((ROOT / "schemas/world/project-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(  # pyright: ignore[reportUnknownMemberType]
        json.loads(output.read_text(encoding="utf-8"))
    )


def test_drawn_coast_detail_is_optional_and_roundtrips(tmp_path: Path) -> None:
    from dmtools.terrain.adapters.world_svg import drawn_coast_detail_km

    project = read_world_project(EXAMPLE)
    plain = world_project_document(project)
    assert "coast_detail_km" not in plain  # projects without it keep their bytes
    refined = replace(project, coast_detail_km=10.0)
    output = tmp_path / "refined.dmworld.json"
    save_world(refined, output)
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["coast_detail_km"] == 10.0
    schema = json.loads((ROOT / "schemas/world/project-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(document)  # pyright: ignore[reportUnknownMemberType]
    assert open_world(output).project.coast_detail_km == 10.0
    for bad in (0.0, -5.0, float("nan"), 5000.0):
        with pytest.raises(ValueError, match="coast detail"):
            replace(project, coast_detail_km=bad)
    # A refined-coast export declares its detail on the SVG root.
    marked = source("<path d='M10 10 H50 V50 Z'/>").replace(
        "<svg ", '<svg data-dmtools-coast-detail-km="10" ', 1
    )
    assert drawn_coast_detail_km(marked) == 10.0
    assert drawn_coast_detail_km(source("<path d='M10 10 H50 V50 Z'/>")) is None


@pytest.mark.parametrize(
    "change", ["hash", "projection", "version", "preparation", "extra", "duplicate"]
)
def test_bad_world_files_fail_without_fallback(tmp_path: Path, change: str) -> None:
    document = world_project_document(read_world_project(EXAMPLE))
    raw = json.dumps(document)
    if change == "hash":
        raw = raw.replace(read_world_project(EXAMPLE).source.sha256, "0" * 64)
    elif change == "projection":
        raw = raw.replace('"plate-carree"', '"mercator"')
    elif change == "version":
        raw = raw.replace('"version": 1', '"version": true')
    elif change == "preparation":
        raw = raw.replace('"bounded-world-v1"', '"unknown-preparation"')
    elif change == "extra":
        raw = raw[:-1] + ', "unknown": 1}'
    else:
        raw = raw[:-1] + ', "name": "duplicate"}'
    path = tmp_path / "bad.dmworld.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        open_world(path)


def test_invalid_world_save_leaves_existing_file_untouched(tmp_path: Path) -> None:
    path = tmp_path / "world.dmworld.json"
    project = read_world_project(EXAMPLE)
    save_world(project, path)
    original = path.read_bytes()
    invalid = replace(project, frame=WorldFrame((0, 0, 100, 50), 6500))
    with pytest.raises(ValueError, match="outside"):
        save_world(invalid, path)
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="extension"):
        save_world(project, tmp_path / "source.svg")
    with pytest.raises(ValueError, match="snapshot"):
        save_world(replace(project, source=replace(project.source, sha256="0" * 64)), path)
    assert path.read_bytes() == original


def test_world_preview_does_not_fill_holes_or_change_authored_geometry() -> None:
    project = world(
        '<path id="a" fill-rule="evenodd" d="M80 40 H280 V140 H80 Z M150 75 H210 V105 H150 Z"/>'
    )
    original = project.source.features
    with render_world_source(
        project.source, project.frame.bounds, project.assignments, MapViewport(), (396, 216)
    ) as image:
        assert image.getpixel((198, 108)) == tuple(bytes.fromhex(OCEAN[1:]))
        assert image.getpixel((130, 108)) != tuple(bytes.fromhex(OCEAN[1:]))
    assert project.source.features == original


def test_world_cli_inspects_saved_project(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["world", "inspect", str(EXAMPLE)]) == 0
    output = capsys.readouterr().out
    assert "Four Shores" in output and "Continents: 4" in output and "6500 km" in output
    assert "world terrain for a local project" in output
    assert "coupled world terrain is planned" in output


def test_startup_world_and_terrain_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as error:
        main(["terrain", "gui", "--world", str(EXAMPLE), "--project", "other.json"])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "style", ['clip-path="url(#clip)"', 'style="clip-path:url(#clip)"', 'style="mask:url(#mask)"']
)
def test_clipped_and_masked_land_is_not_silently_imported(style: str) -> None:
    parsed = parse_world_svg(
        source(f'<g {style}><path id="a" d="M10 10 H30 V30 H10 Z"/></g>'), "world.svg"
    )
    assert parsed.features[0].issue.startswith("Clipped/masked")
    assert not parsed.features[0].components


def test_world_preview_clips_seam_outlines_to_declared_frame() -> None:
    project = world('<path id="a" d="M350 70 H370 V110 H350 Z"/>')
    viewport = MapViewport()
    size = (396, 216)
    left, top, right, bottom = viewport.rect(size, (360, 180))
    ocean = tuple(bytes.fromhex(OCEAN[1:]))
    with render_world_source(
        project.source, project.frame.bounds, project.assignments, viewport, size
    ) as image:
        for x, y in (
            (int(left) - 2, 108),
            (int(right) + 2, 108),
            (198, int(top) - 2),
            (198, int(bottom) + 2),
        ):
            assert image.getpixel((x, y)) == ocean


@pytest.mark.parametrize("name", ["", "   ", "x" * 257])
def test_world_source_name_matches_public_contract(name: str) -> None:
    with pytest.raises(ValueError, match="source name"):
        parse_world_svg(source('<path id="a" d="M10 10 H30 V30 H10 Z"/>'), name)


def test_failed_atomic_world_replace_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dmtools.terrain.adapters import world_project

    project = read_world_project(EXAMPLE)
    path = tmp_path / "world.dmworld.json"
    save_world(project, path)
    original = path.read_bytes()

    def reject_replace(*_args: object) -> None:
        raise OSError("Simulated replace failure")

    monkeypatch.setattr(world_project.os, "replace", reject_replace)
    with pytest.raises(OSError, match="Simulated"):
        save_world(replace(project, name="Changed"), path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "declaration",
    [
        "<!DOCTYPE svg>",
        '<!DOCTYPE svg SYSTEM "https://example.invalid/never-fetch.dtd">',
        '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">',
    ],
)
def test_export_doctype_is_accepted_and_retained(declaration: str, tmp_path: Path) -> None:
    from hashlib import sha256

    svg = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        + declaration
        + source('<g id="North"><path id="land" d="M10 10 H30 V30 H10 Z"/></g>')
    )
    parsed = parse_world_svg(svg, "export.svg")
    assert parsed.svg == svg and parsed.sha256 == sha256(svg.encode("utf-8")).hexdigest()
    continents, assignments = propose_group_assignments(parsed)
    project = WorldProject(
        "Map", parsed, WorldFrame((0, 0, 360, 180), 1000), continents, assignments
    )
    target = tmp_path / "doctype.dmworld.json"
    save_world(project, target)
    assert open_world(target).project.source == parsed


@pytest.mark.parametrize(
    "declaration",
    [
        '<!DOCTYPE svg [<!ENTITY name "expanded">]>',
        '<!DOCTYPE svg [<!ENTITY name SYSTEM "file:///not-a-source.txt">]>',
        '<!DOCTYPE svg [<!ENTITY % external SYSTEM "https://example.invalid/never-fetch.dtd">'
        "%external;]>",
        '<!DOCTYPE svg [<!ATTLIST svg viewBox CDATA "0 0 1 1">]>',
    ],
)
def test_custom_dtd_content_is_rejected_before_expansion(declaration: str) -> None:
    with pytest.raises(ValueError, match="internal DTD"):
        parse_world_svg(declaration + source('<path d="M0 0 H10 V10 H0 Z"/>'), "unsafe.svg")


def test_doctype_never_supplies_external_entities(tmp_path: Path) -> None:
    dtd = tmp_path / "external.dtd"
    dtd.write_text('<!ENTITY custom "unexpected">', encoding="utf-8")
    with pytest.raises(ValueError, match=r"entities|undefined entity"):
        parse_world_svg(
            f'<!DOCTYPE svg SYSTEM "{dtd.as_uri()}">'
            + source('<g id="&custom;"><path d="M0 0 H10 V10 H0 Z"/></g>'),
            "external.svg",
        )


def test_xml_comments_are_not_mistaken_for_declarations() -> None:
    parsed = parse_world_svg(
        source(
            "<!-- A note about <!DOCTYPE and <!ENTITY is plain text. -->"
            '<path id="island&amp;reef" d="M0 0 H10 V10 H0 Z"/>'
        ),
        "comment.svg",
    )
    assert parsed.features[0].id == "island&reef"


@pytest.mark.parametrize("namespace", ["https://www.affinity.studio/", "http://www.serif.com/"])
def test_affinity_labels_survive_unique_ids_and_geometry_wrappers(namespace: str) -> None:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:a="{namespace}" viewBox="0 0 360 180">'
    for index, name in enumerate(("North Reach", "South Reach")):
        svg += (
            f'<g id="{name.replace(" ", "-")}" a:id="{name}">'
            f'<g id="Land-Shapes{index}" a:id="Land Shapes">'
            f'<g id="mainland{index}" a:id="mainland">'
            f'<path d="M{index * 60 + 10} 10 h20 v20 h-20 Z"/></g>'
            f'<g id="islands{index}" a:id="islands"><g transform="translate(0,50)">'
            f'<g id="cluster{index}">'
            f'<path id="island{index}" d="M{index * 60 + 10} 10 h5 v5 h-5 Z"/>'
            "</g></g></g></g>"
            f'<g id="Labels{index}" a:id="Labels">'
            f'<path id="decoration{index}" d="M100 100 h5 v5 h-5 Z"/>'
            "</g></g>"
        )
    parsed = parse_world_svg(svg + "</svg>", "affinity.svg")
    continents, assignments = propose_group_assignments(parsed)
    assert {c.name for c in continents} == {"North Reach", "South Reach"}
    assert len(assignments) == 6
    owners = {c.id: c.name for c in continents}
    for index, name in enumerate(("North Reach", "South Reach")):
        island = next(a for a in assignments if a.feature_id == f"island{index}")
        assert island.role == "island" and owners[island.continent_id or ""] == name
        assert (
            next(a for a in assignments if a.feature_id == f"decoration{index}").role == "exclude"
        )
    assert parsed.features[0].label == "mainland"
    assert parsed.features[0].groups == ("North Reach", "Land Shapes", "mainland")
    assert "Group" not in parsed.features[1].groups


@pytest.mark.parametrize("fill_rule", ["nonzero", "evenodd"])
def test_self_crossing_coastline_retains_both_filled_lobes(fill_rule: str) -> None:
    parsed = parse_world_svg(
        source(f'<path fill-rule="{fill_rule}" d="M0 0 L20 20 L0 20 L20 0 Z"/>'), "crossing.svg"
    )
    feature = parsed.features[0]
    assert not feature.issue and len(feature.components) == 2
    polygons = [Polygon(c.exterior, c.holes) for c in feature.components]
    assert sum(p.area for p in polygons) == pytest.approx(200)
    assert all(any(p.covers(Point(x, y)) for p in polygons) for x, y in ((10, 5), (10, 15)))
    assert not any(p.covers(Point(1, 10)) for p in polygons)


@pytest.mark.parametrize("fill_rule,filled", [("nonzero", True), ("evenodd", False)])
def test_retraced_loop_uses_original_winding_not_polygonized_face_count(
    fill_rule: str,
    filled: bool,
) -> None:
    parsed = parse_world_svg(
        source(f'<path fill-rule="{fill_rule}" d="M0 0 H20 V20 H0 V0 H20 V20 H0 Z"/>'),
        "retraced.svg",
    )
    feature = parsed.features[0]
    assert bool(feature.components) == filled
    if filled:
        assert not feature.issue
        assert Polygon(feature.components[0].exterior).area == pytest.approx(400)
    else:
        assert feature.issue


@pytest.mark.parametrize("fill_rule", ["nonzero", "evenodd"])
def test_retraced_bridge_to_inner_coastline_retains_hole(fill_rule: str) -> None:
    parsed = parse_world_svg(
        source(
            f'<path fill-rule="{fill_rule}" d="M0 0 H40 V40 H0 V0 L10 10 V30 H30 V10 H10 L0 0 Z"/>'
        ),
        "bridge.svg",
    )
    feature = parsed.features[0]
    assert not feature.issue and len(feature.components) == 1
    polygon = Polygon(feature.components[0].exterior, feature.components[0].holes)
    assert polygon.area == pytest.approx(1200)
    assert polygon.covers(Point(5, 5)) and not polygon.covers(Point(20, 20))


@pytest.mark.parametrize("outside", [False, True])
def test_geometry_errors_identify_exact_source_shapes(outside: bool) -> None:
    from dmtools.terrain.domain.world import WorldGeometryError

    project = world(
        '<g id="North"><path id="coast" d="M10 10 H30 V30 H10 Z"/>'
        + (
            '<path id="outside" d="M100 170 H120 V180.002 H100 Z"/>'
            if outside
            else '<path id="overlap" d="M20 20 H40 V40 H20 Z"/>'
        )
        + "</g>"
    )
    project = different_owners(project)
    original = project.source
    with pytest.raises(WorldGeometryError) as error:
        prepare_world_map(project)
    if outside:
        assert error.value.feature_ids == ("outside",)
        assert "180.002" in str(error.value) and "North / outside" in str(error.value)
    else:
        assert set(error.value.feature_ids) == {"coast", "overlap"}
        assert "100 square source units" in str(error.value)
    assert project.source is original


def test_doctype_removal_uses_utf8_parser_offsets_and_preserves_source() -> None:
    svg = '<?xml version="1.0"?><!-- Příliš žluťoučký -->\n' + (
        '<!DOCTYPE svg SYSTEM "https://example.invalid/unneeded.dtd">'
        + source('<path id="island" d="M10 10 H30 V30 H10 Z"/>')
    )
    parsed = parse_world_svg(svg, "unicode.svg")
    assert parsed.svg == svg and not parsed.features[0].issue
