# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Bounded export tolerance, ownership and union/area conservation controls."""

from dataclasses import replace
from pathlib import Path

import pytest
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from map_maker.cli import main
from map_maker.terrain.adapters.world_project import world_project_document
from map_maker.terrain.adapters.world_svg import parse_world_svg
from map_maker.terrain.application.world import open_world, save_world
from map_maker.terrain.domain.world import (
    WORLD_PREPARATION,
    WorldAssignment,
    WorldContinent,
    WorldFrame,
    WorldGeometryError,
    WorldProject,
)
from map_maker.terrain.pipeline.world import WorldMap, prepare_world_map


def project(
    body: str, *, separate: bool = False, scale: float = 1, offset: float = 0
) -> WorldProject:
    frame = WorldFrame((offset, offset, offset + 360 * scale, offset + 180 * scale), 1000)
    svg = (
        f'<svg viewBox="{offset} {offset} {360 * scale} {180 * scale}">'
        f'<g transform="translate({offset},{offset}) scale({scale})">{body}</g></svg>'
    )
    source = parse_world_svg(svg, "controls.svg")
    continents = tuple(
        WorldContinent(f"owner-{i}", f"Owner {i}")
        for i in range(len(source.features) if separate else 1)
    )
    assignments = tuple(
        WorldAssignment(f.id, continents[i if separate else 0].id, "mainland")
        for i, f in enumerate(source.features)
    )
    return WorldProject("Controls", source, frame, continents, assignments)


def polygons(world: WorldMap) -> list[Polygon]:
    return [Polygon(c.exterior, c.holes) for f in world.land for c in f.components]


def assert_union_preserved(world: WorldMap) -> None:
    # These controls lie within one longitude period; compare clipped source
    # coverage independently of per-feature area/ownership preparation.
    original = unary_union(
        [Polygon(c.exterior, c.holes) for f in world.project.source.features for c in f.components]
    ).intersection(box(*world.project.frame.bounds))
    prepared = polygons(world)
    union = unary_union(prepared)
    assert union.symmetric_difference(original).area == pytest.approx(0, abs=1e-8)
    assert sum(p.area for p in prepared) == pytest.approx(union.area)
    assert sum(c.area_km2 for c in world.continents) == world.land_area_km2


@pytest.mark.parametrize("scale,offset", [(1, 0), (0.01, -50), (1000, 123456)])
@pytest.mark.parametrize("edge", ["north", "south"])
def test_rounding_is_clipped_in_source_units_without_changing_the_frame(
    scale: float,
    offset: float,
    edge: str,
) -> None:
    y0, y1 = (-0.0009, 10) if edge == "north" else (170, 180.0009)
    p = project(f'<path id="coast" d="M20 {y0} H100 V{y1} H20 Z"/>', scale=scale, offset=offset)
    original = p.source
    result = prepare_world_map(p)
    assert result.project.source is original and result.project.frame is p.frame
    assert [a.kind for a in result.adjustments] == ["edge_clip"]
    assert result.adjustments[0].area_source_units2 == pytest.approx(
        80 * 0.0009 * scale**2, rel=1e-5
    )
    assert all(
        g.bounds[1] >= p.frame.bounds[1] and g.bounds[3] <= p.frame.bounds[3]
        for g in polygons(result)
    )
    assert_union_preserved(result)


@pytest.mark.parametrize(
    "body,match",
    [
        ('<path id="a" d="M20 170 H100 V180.002 H20 Z"/>', "outside"),
        ('<path id="a" d="M20 -0.0015 H30 V-0.0003 H20 Z"/>', "no land"),
    ],
)
def test_overflow_beyond_tolerance_or_entirely_outside_land_is_not_hidden(
    body: str,
    match: str,
) -> None:
    with pytest.raises(WorldGeometryError, match=match):
        prepare_world_map(project(body))


def test_contained_and_overlapping_same_owner_shapes_retain_identity_and_count_once() -> None:
    p = project(
        '<path id="main" d="M10 20 H90 V100 H10 Z"/>'
        '<path id="contained" d="M20 30 H30 V40 H20 Z"/>'
        '<path id="neighbour" d="M80 20 H120 V100 H80 Z"/>'
    )
    p = replace(
        p,
        assignments=tuple(
            replace(a, role="island") if a.feature_id == "contained" else a for a in p.assignments
        ),
    )
    r = prepare_world_map(p)
    assert {f.feature_id for f in r.land} == {f.id for f in p.source.features}
    assert not next(f for f in r.land if f.feature_id == "contained").components
    assert r.project.assignments == p.assignments
    assert all(a.role != "exclude" for a in r.project.assignments)
    assert [a.kind for a in r.adjustments] == ["shared_land", "shared_land"]
    assert_union_preserved(r)
    expected = prepare_world_map(project('<path id="union" d="M10 20 H120 V100 H10 Z"/>'))
    assert r.land_area_km2 == pytest.approx(expected.land_area_km2)


def test_narrow_foreign_border_is_disjoint_and_order_independent(tmp_path: Path) -> None:
    p = project(
        '<path id="west" d="M10 20 H100 V100 H10 Z"/>'
        '<path id="east" d="M99.9995 20 H180 V100 H99.9995 Z"/>',
        separate=True,
    )
    r = prepare_world_map(p)
    assert [a.kind for a in r.adjustments] == ["border_overlap"]
    assert_union_preserved(r)
    reordered = replace(
        p,
        source=replace(p.source, features=tuple(reversed(p.source.features))),
        assignments=tuple(reversed(p.assignments)),
        continents=tuple(reversed(p.continents)),
    )
    other = prepare_world_map(reordered)
    assert (
        other.land == r.land
        and other.continents == r.continents
        and other.adjustments == r.adjustments
    )
    path = tmp_path / "input.world.json"
    save_world(p, path)
    reopened = open_world(path)
    assert reopened.land == r.land and reopened.adjustments == r.adjustments
    assert reopened.continents == r.continents and reopened.land_area_km2 == r.land_area_km2
    assert reopened.project.source == p.source and reopened.project.frame == p.frame
    assert set(reopened.project.assignments) == set(p.assignments)
    assert world_project_document(p)["preparation"] == WORLD_PREPARATION


@pytest.mark.parametrize(
    "body",
    [
        # Small total area is insufficient when overlap lies inside a continent.
        '<path id="a" d="M0 20 H100 V120 H0 Z"/>'
        '<path id="b" d="M120 20 H220 V120 H120 Z M50 50 H50.001 V50.001 H50 Z"/>',
        # A small island must not be swallowed by a different owner, even near an edge.
        '<path id="a" d="M0 20 H100 V120 H0 Z"/>'
        '<path id="b" d="M99.9995 21 H99.9999 V21.0004 H99.9995 Z"/>',
        # A thick, shallow-area sliver also exceeds the linear tolerance.
        '<path id="a" d="M0 20 H100 V120 H0 Z"/>'
        '<path id="b" d="M99.99 50 H199.99 V50.01 H99.99 Z"/>',
    ],
)
def test_real_foreign_ownership_conflicts_still_fail(body: str) -> None:
    with pytest.raises(WorldGeometryError, match="overlap"):
        prepare_world_map(project(body, separate=True))


def test_many_small_foreign_overlaps_cannot_evade_the_combined_area_budget() -> None:
    p = project(
        '<path id="middle" d="M60 20 H80 V100 H60 Z"/>'
        '<path id="left" d="M0 20 H60.0015 V100 H0 Z"/>'
        '<path id="right" d="M79.9985 20 H160 V100 H79.9985 Z"/>',
        separate=True,
    )
    with pytest.raises(WorldGeometryError, match="combined border") as error:
        prepare_world_map(p)
    assert set(error.value.feature_ids) == {"left", "middle", "right"}


def test_tolerated_seam_overlap_preserves_holes_and_never_double_counts() -> None:
    p = project(
        '<path id="seam" fill-rule="evenodd" '
        'd="M355 30 H365 V80 H355 Z M358 40 H363 V50 H358 Z"/>'
        '<path id="east" d="M4.9995 30 H60 V80 H4.9995 Z"/>',
        separate=True,
    )
    r = prepare_world_map(p)
    assert [a.kind for a in r.adjustments] == ["border_overlap"]
    coverage = unary_union(polygons(r))
    assert coverage.area == pytest.approx(65 * 50 - 5 * 10)
    assert sum(g.area for g in polygons(r)) == pytest.approx(coverage.area)
    assert len(next(f for f in r.land if f.feature_id == "seam").components) == 2
    assert isinstance(coverage, MultiPolygon)


def test_preparation_is_reported_by_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = project('<path id="a" d="M20 170 H100 V180.0009 H20 Z"/>')
    path = tmp_path / "input.world.json"
    save_world(p, path)
    assert main(["world", "inspect", str(path)]) == 0
    output = capsys.readouterr().out
    assert "Import adjustments: 1" in output and "export overflow" in output
