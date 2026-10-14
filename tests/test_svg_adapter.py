# pyright: reportMissingTypeStubs=false

from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon
from svgelements import Path as SvgPath

from map_maker.terrain.adapters.svg import CoastlineInputError, load_svg_coastline

FIXTURES = Path(__file__).parent / "fixtures" / "terrain"


def test_loads_one_closed_svg_shape() -> None:
    coastline = load_svg_coastline(FIXTURES / "closed-coast.svg", sample_count=256)

    assert coastline.points[0] == coastline.points[-1]
    assert len(coastline.points) >= 4
    assert coastline.source_name == "closed-coast.svg"


def test_import_does_not_use_repeated_whole_path_point_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Path.point performs a costly whole-path lookup per vertex")

    monkeypatch.setattr(SvgPath, "point", fail_if_called)

    coastline = load_svg_coastline(FIXTURES / "closed-coast.svg", sample_count=256)

    assert len(coastline.points) >= 4


def test_loads_multiple_disconnected_land_objects() -> None:
    coastline = load_svg_coastline(FIXTURES / "two-objects.svg", sample_count=256)

    assert coastline.component_count == 2
    assert len(coastline.additional_components) == 1


def test_dissolves_touching_subcontinents_and_ignores_non_land_layers() -> None:
    coastline = load_svg_coastline(FIXTURES / "grouped-land.svg", sample_count=256)
    mainland = Polygon(coastline.points)

    assert coastline.component_count == 2
    assert coastline.bounds == pytest.approx((5.0, 2.0, 95.0, 90.0))
    assert mainland.covers(Point(50.0, 50.0))
    assert not mainland.covers(Point(170.0, 50.0))


def test_closes_sub_sampling_gap_between_adjacent_land_objects() -> None:
    coastline = load_svg_coastline(
        FIXTURES / "near-touching-land.svg",
        sample_count=256,
    )

    assert coastline.component_count == 1
    assert Polygon(coastline.points).covers(Point(50.0, 50.0))


def test_preserves_enclosed_water_after_dissolving_land_objects() -> None:
    coastline = load_svg_coastline(FIXTURES / "land-with-hole.svg", sample_count=256)
    mainland = Polygon(coastline.points, holes=coastline.holes)

    assert coastline.component_count == 1
    assert len(coastline.holes) == 1
    assert mainland.covers(Point(10.0, 10.0))
    assert not mainland.covers(Point(50.0, 50.0))


def test_fills_tiny_enclosed_slivers_between_land_objects() -> None:
    coastline = load_svg_coastline(
        FIXTURES / "land-with-sliver-hole.svg",
        sample_count=4_096,
    )
    mainland = Polygon(coastline.points, holes=coastline.holes)

    assert coastline.component_count == 1
    assert coastline.holes == ()
    assert mainland.covers(Point(500.0, 500.0))


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("open-coast.svg", "open"),
        ("self-intersecting.svg", "not a valid loop"),
    ],
)
def test_rejects_unsupported_coastlines(filename: str, message: str) -> None:
    with pytest.raises(CoastlineInputError, match=message):
        load_svg_coastline(FIXTURES / filename, sample_count=256)


def test_rejects_non_svg_input(tmp_path: Path) -> None:
    source = tmp_path / "coast.txt"
    source.write_text("not svg", encoding="utf-8")

    with pytest.raises(CoastlineInputError, match="SVG files only"):
        load_svg_coastline(source)
