"""Spherical coverage, source topology, bounded detail and portable context contracts."""

import json
from dataclasses import replace
from math import cos, pi, sin
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from map_maker.cli import main
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.adapters.world_context import context_input_sha256, write_world_context
from map_maker.terrain.adapters.world_context_render import CONTEXT_LAYERS, render_world_context
from map_maker.terrain.adapters.world_svg import parse_world_svg
from map_maker.terrain.application import world_context as application
from map_maker.terrain.application.world import open_world, save_world
from map_maker.terrain.domain.models import LandComponent
from map_maker.terrain.domain.world import WorldAssignment, WorldContinent, WorldFrame, WorldProject
from map_maker.terrain.domain.world_context import (
    SPLIT_WATER,
    SUBCELL_LAND,
    SUBCELL_WATER,
    SphericalContextGrid,
    WorldContextSettings,
)
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled
from map_maker.terrain.pipeline.world import component_area_km2, prepare_world_map
from map_maker.terrain.pipeline.world_context import WorldContext, generate_world_context
from map_maker.terrain.viewport import MapViewport

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/world/four-shores.world.json"


def project(body: str, *, scale: float = 1, offset: float = 0) -> WorldProject:
    svg = (
        f'<svg viewBox="{offset} {offset} {360 * scale} {180 * scale}">'
        f'<g transform="translate({offset},{offset}) scale({scale})">{body}</g></svg>'
    )
    source = parse_world_svg(svg, "geography.svg")
    return WorldProject(
        "Geography",
        source,
        WorldFrame((offset, offset, offset + 360 * scale, offset + 180 * scale), 1000),
        (WorldContinent("owner", "Continent"),),
        tuple(WorldAssignment(f.id, "owner", "mainland") for f in source.features),
    )


def context(body: str, rows: int = 12) -> WorldContext:
    return generate_world_context(prepare_world_map(project(body)), WorldContextSettings(rows))


@pytest.mark.parametrize("rows", [4, 12, 90, 180, 360])
def test_cell_areas_cover_the_sphere_and_centres_avoid_pole_singularities(rows: int) -> None:
    frame = WorldFrame((17, 0, 2897, 1440), 6000, 35)
    grid = SphericalContextGrid(frame, WorldContextSettings(rows))
    assert sum(grid.cell_area_km2(r) for r in range(rows)) * 2 * rows == pytest.approx(
        4 * pi * 6000**2
    )
    assert all(grid.cell_area_km2(r) > 0 for r in range(rows))
    assert grid.cell_area_km2(0) == pytest.approx(grid.cell_area_km2(rows - 1))
    assert -90 < grid.latitude_deg(rows - 1) < grid.latitude_deg(0) < 90
    assert grid.longitude_deg(0) == pytest.approx(35 - 180 + 90 / rows)


@pytest.mark.parametrize("rows", [0, 3, 361, -1, True, 90.5])
def test_grid_size_admission_rejects_unsafe_or_noninteger_settings(rows: object) -> None:
    with pytest.raises(ValueError, match="latitude cells"):
        WorldContextSettings(cast(int, rows))


@pytest.mark.parametrize("rows", [8, 12, 45])
@pytest.mark.parametrize("scale,offset", [(1, 0), (0.01, -20), (100, 25000)])
def test_latitude_band_area_is_conservative_across_resolution_and_source_units(
    rows: int,
    scale: float,
    offset: float,
) -> None:
    p = project('<path id="belt" d="M0 60 H360 V120 H0 Z"/>', scale=scale, offset=offset)
    result = generate_world_context(prepare_world_map(p), WorldContextSettings(rows))
    expected = 4 * pi * 1000**2 * sin(pi / 6)
    assert result.land_area_km2 == pytest.approx(expected)
    assert abs(result.area_error_km2) < 1e-6
    assert len(result.water_bodies) == 2
    assert all(b.crosses_seam for b in result.water_bodies)
    assert result.world.project is p
    assert np.isfinite(result.land_fraction).all()
    assert np.all((result.land_fraction >= 0) & (result.land_fraction <= 1))


def test_seam_connects_water_and_poles_do_not_bypass_a_land_barrier() -> None:
    single = context('<path id="wall" d="M170 0 H190 V180 H170 Z"/>')
    assert len(single.water_bodies) == 1
    assert single.water_bodies[0].crosses_seam
    closed = context(
        '<path id="wall" d="M170 0 H190 V180 H170 Z"/><path id="seam" d="M355 0 H365 V180 H355 Z"/>'
    )
    assert len(closed.water_bodies) == 2
    assert not any(b.crosses_seam for b in closed.water_bodies)


def test_subcell_gateway_connects_vectors_without_becoming_a_resolved_pixel_passage() -> None:
    common = '<path id="seam" d="M355 0 H365 V180 H355 Z"/>'
    closed = context(common + '<path id="wall" d="M170 0 H190 V180 H170 Z"/>')
    opened = context(
        common + '<path id="north" d="M170 0 H190 V80 H170 Z"/>'
        '<path id="south" d="M170 80.01 H190 V180 H170 Z"/>'
    )
    assert len(closed.water_bodies) == 2
    assert len(opened.water_bodies) == 1
    assert np.any(opened.support_flags & SUBCELL_WATER)
    assert opened.land_area_km2 < closed.land_area_km2


def test_tiny_islands_and_holes_survive_fractional_coverage() -> None:
    result = context(
        '<path id="small" d="M20 20 H21 V21 H20 Z"/>'
        '<path id="main" fill-rule="evenodd" '
        'd="M100 50 H150 V100 H100 Z M110 60 H111 V61 H110 Z"/>'
    )
    assert np.any(result.support_flags & SUBCELL_LAND)
    assert np.any(result.support_flags & SUBCELL_WATER)
    assert len(result.water_bodies) == 2
    assert result.land_area_km2 == pytest.approx(result.world.land_area_km2)
    assert {f.id for f in result.world.project.source.features} == {"small", "main"}


def test_water_pieces_in_one_cell_are_flagged_even_when_connected_elsewhere() -> None:
    result = context('<path id="wall" d="M19 0 H20 V180 H19 Z"/>')
    assert len(result.water_bodies) == 1
    assert np.any(result.support_flags & SPLIT_WATER)
    assert result.split_water_cells > 0


def test_all_land_world_has_zero_water_without_invalid_arrays() -> None:
    result = context('<path id="land" d="M0 0 H360 V180 H0 Z"/>')
    assert not result.water_bodies
    assert np.all(result.land_fraction == 1)
    assert np.all(result.water_body == 0)
    assert not np.any(result.support_flags)


def test_generation_is_order_independent_and_arrays_are_read_only() -> None:
    p = project('<path id="a" d="M40 0 H80 V180 H40 Z"/><path id="b" d="M200 0 H240 V180 H200 Z"/>')
    reordered = replace(
        p,
        assignments=tuple(reversed(p.assignments)),
        source=replace(p.source, features=tuple(reversed(p.source.features))),
    )
    first = generate_world_context(prepare_world_map(p), WorldContextSettings(12))
    second = generate_world_context(prepare_world_map(reordered), WorldContextSettings(12))
    for name in (
        "land_fraction",
        "water_body",
        "support_flags",
        "cell_area_km2",
        "east_opening_km",
        "south_opening_km",
    ):
        np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
    assert first.water_bodies == second.water_bodies
    with pytest.raises(ValueError, match="read-only"):
        first.land_fraction[0, 0] = 0.5


def test_cancellation_at_rows_returns_no_result() -> None:
    world = open_world(EXAMPLE)
    token = CancellationToken()
    calls: list[float] = []

    def progress(fraction: float, _message: str) -> None:
        calls.append(fraction)
        if fraction > 0.1:
            token.cancel()

    with pytest.raises(GenerationCancelled):
        generate_world_context(world, WorldContextSettings(12), progress, cancellation=token)
    assert max(calls) < 1
    with pytest.raises(GenerationCancelled):
        generate_world_context(world, cancellation=token)


def test_export_schema_hashes_snapshot_numeric_fields_and_no_overwrite(tmp_path: Path) -> None:
    world = open_world(EXAMPLE)
    run = application.generate_context(world.project, WorldContextSettings(12))
    target = tmp_path / "context"
    path = application.export_context(run, target)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/world/context-v4.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)  # pyright: ignore[reportUnknownMemberType]
    assert manifest["input_sha256"] == context_input_sha256(run.context)
    assert open_world(target / "input.world.json").project == world.project
    for name, record in manifest["outputs"].items():
        assert file_sha256(target / name) == record["sha256"]
        assert (target / name).stat().st_size == record["bytes"]
    with np.load(target / "geography.npz", allow_pickle=False) as arrays:
        assert arrays["land_fraction"].shape == (12, 24)
        assert arrays["land_fraction"].dtype == np.float64
        assert arrays["water_body"].dtype == np.int32
        assert arrays["support_flags"].dtype == np.uint8
        assert arrays["cell_area_km2"].shape == (12,)
        np.testing.assert_array_equal(arrays["land_fraction"], run.context.land_fraction)
    with pytest.raises(FileExistsError):
        application.export_context(run, target)
    with pytest.raises(ValueError, match="Software changed"):
        application.export_context(replace(run, runtime={}), tmp_path / "bad-runtime")
    assert not (tmp_path / "bad-runtime").exists()
    other = generate_world_context(world, WorldContextSettings(24))
    assert context_input_sha256(other) != context_input_sha256(run.context)


def test_failed_export_never_publishes_completion(tmp_path: Path) -> None:
    result = generate_world_context(open_world(EXAMPLE), WorldContextSettings(12))
    calls = 0

    def verify() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise GenerationCancelled("Stopped while exporting")

    target = tmp_path / "cancelled"
    with pytest.raises(GenerationCancelled):
        write_world_context(result, {}, target, verify=verify)
    assert target.exists() and not (target / "context.json").exists()


def test_source_change_during_cli_build_does_not_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.world.json"
    save_world(open_world(EXAMPLE).project, source)
    original = application.generate_context

    def generate(
        p: WorldProject,
        settings: WorldContextSettings | None = None,
        *,
        cancellation: CancellationToken | None = None,
    ) -> application.WorldContextRun:
        result = original(p, settings, cancellation=cancellation)
        source.write_text(
            source.read_text(encoding="utf-8").replace("Four shores", "Changed name"),
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(application, "generate_context", generate)
    # Change the source regardless of the example's display name.
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["name"] = "Four shores"
    source.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="World project changed"):
        application.build_world_context(source, tmp_path / "result", WorldContextSettings(12))
    assert not (tmp_path / "result").exists()


def test_cli_context_is_usable_and_preview_allocation_is_bounded(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "world",
                "context",
                str(EXAMPLE),
                "--output",
                str(tmp_path / "result"),
                "--latitude-cells",
                "12",
            ]
        )
        == 0
    )
    assert "Geographic context complete" in capsys.readouterr().out
    result = generate_world_context(open_world(EXAMPLE), WorldContextSettings(12))
    viewport = MapViewport()
    viewport.zoom_at(20, (160, 80), (320, 160), (360, 180))
    for layer in CONTEXT_LAYERS:
        with render_world_context(result, viewport, (320, 160), layer) as image:
            assert image.size == (320, 160)
    with pytest.raises(ValueError, match="pixels"):
        render_world_context(result, viewport, (5000, 5000), "Land coverage")


@pytest.mark.parametrize("width", [1e-4, 1e-7, 1e-10])
@pytest.mark.parametrize("y", [1.0, 45.0, 90.0])
def test_tiny_spherical_pockets_do_not_cancel_to_zero(width: float, y: float) -> None:
    frame = WorldFrame((0, 0, 360, 180), 1000)
    x0, x1, y1 = 123.456, 123.456 + width, y + width
    component = LandComponent(((x0, y), (x1, y), (x1, y1), (x0, y1), (x0, y)))
    latitude = (90 - (y + y1) / 2) * pi / 180
    expected = 1000**2 * (x1 - x0) * pi / 180 * 2 * cos(latitude) * sin((y1 - y) * pi / 360)
    measured = component_area_km2(component, frame)
    assert measured > 0
    assert measured == pytest.approx(expected, rel=1e-8, abs=0)


def test_tiny_hole_stays_a_positive_area_water_region() -> None:
    result = context(
        '<path id="main" fill-rule="evenodd" '
        'd="M100 50 H150 V100 H100 Z '
        'M110 60 H110.0000001 V60.0000001 H110 Z"/>'
    )
    assert len(result.water_bodies) == 2
    assert all(b.area_km2 > 0 for b in result.water_bodies)
    assert min(b.area_km2 for b in result.water_bodies) < 1e-6


@pytest.mark.parametrize("gap", [0, 0.01, 4.0])
def test_water_edge_measures_continuous_strait_in_km(gap: float) -> None:
    result = context(
        '<path id="north" d="M170 0 H190 V80 H170 Z"/>'
        f'<path id="south" d="M170 {80 + gap} H190 V180 H170 Z"/>'
    )
    # 15 degree cells; column 11 ends at x=180, row 5 spans y=75..90.
    assert result.east_opening_km[5, 11] == pytest.approx(1000 * pi / 180 * gap)
    assert np.all(result.south_opening_km[-1] == 0)
    assert not result.east_opening_km.flags.writeable


def test_separate_gaps_are_not_added_into_one_gateway() -> None:
    result = context(
        '<path id="north" d="M165 0 H190 V79 H165 Z"/>'
        '<path id="middle" d="M165 81 H190 V85 H165 Z"/>'
        '<path id="south" d="M165 88 H190 V180 H165 Z"/>'
    )
    assert result.east_opening_km[5, 11] == pytest.approx(1000 * pi / 180 * 3)
    # Widths do not erase the existing split-water warning inside the cell.
    assert result.support_flags[5, 11] & SPLIT_WATER


def test_seam_requires_the_same_open_interval_on_both_sides() -> None:
    result = context(
        '<path id="west" d="M0 75 H2 V82 H0 Z"/><path id="east" d="M358 83 H360 V90 H358 Z"/>'
    )
    assert result.east_opening_km[5, -1] == pytest.approx(1000 * pi / 180)
    disjoint = context(
        '<path id="west" d="M0 75 H2 V83 H0 Z"/><path id="east" d="M358 82 H360 V90 H358 Z"/>'
    )
    assert disjoint.east_opening_km[5, -1] == 0


def test_shared_latitude_faces_scale_with_cosine_and_poles_are_closed() -> None:
    result = context('<path id="tiny" d="M20 20 H21 V21 H20 Z"/>')
    for row in range(11):
        expected = 1000 * pi / 12 * cos((90 - 15 * (row + 1)) * pi / 180)
        assert result.south_opening_km[row, 15] == pytest.approx(expected)
    assert np.all(result.south_opening_km[-1] == 0)
    full = context('<path id="all" d="M0 0 H360 V180 H0 Z"/>')
    assert not np.any(full.east_opening_km) and not np.any(full.south_opening_km)


@pytest.mark.parametrize("scale,offset,radius", [(0.01, -20, 1000), (100, 20000, 3000)])
def test_gateway_physical_scale_is_independent_of_source_units(
    scale: float,
    offset: float,
    radius: float,
) -> None:
    body = (
        '<path id="north" d="M170 0 H190 V80 H170 Z"/>'
        '<path id="south" d="M170 81 H190 V180 H170 Z"/>'
    )
    baseline = context(body)
    p = project(body, scale=scale, offset=offset)
    p = replace(p, frame=replace(p.frame, radius_km=radius, central_meridian_deg=67))
    result = generate_world_context(prepare_world_map(p), WorldContextSettings(12))
    np.testing.assert_allclose(
        result.east_opening_km, baseline.east_opening_km * radius / 1000, atol=1e-9
    )
    np.testing.assert_allclose(
        result.south_opening_km, baseline.south_opening_km * radius / 1000, atol=1e-9
    )


def test_gateway_reflection_reverses_edges_without_changing_widths() -> None:
    body = '<path id="shape" d="M20 10 L130 75 L80 140 L20 110 Z"/>'
    a = context(body)
    b = context(f'<g transform="translate(360,0) scale(-1,1)">{body}</g>')
    np.testing.assert_allclose(
        a.east_opening_km, np.roll(b.east_opening_km[:, ::-1], -1, axis=1), atol=1e-9
    )
    np.testing.assert_allclose(a.south_opening_km, b.south_opening_km[:, ::-1], atol=1e-9)


@pytest.mark.parametrize("scale", [0.001, 0.01, 1.0])
def test_fractional_source_origin_does_not_close_the_periodic_seam(scale: float) -> None:
    p = project('<path id="wall" d="M170 0 H190 V180 H170 Z"/>', scale=scale, offset=0.1)
    result = generate_world_context(prepare_world_map(p), WorldContextSettings(12))
    assert len(result.water_bodies) == 1 and result.water_bodies[0].crosses_seam
    np.testing.assert_allclose(result.east_opening_km[:, -1], result.grid.north_south_spacing_km)


def test_integer_frame_coordinates_have_the_same_saved_context_identity(tmp_path: Path) -> None:
    p = project('<path id="land" d="M20 20 H120 V120 H20 Z"/>')
    p = replace(p, frame=WorldFrame((0, 0, 360, 180), 1000, 0))
    run = application.generate_context(p, WorldContextSettings(12))
    path = application.export_context(run, tmp_path / "integer-frame")
    loaded = application.open_context(path)
    assert context_input_sha256(run.context) == context_input_sha256(loaded.context)
    np.testing.assert_array_equal(run.context.land_fraction, loaded.context.land_fraction)
    assert loaded.context.world.project == p



def test_shore_free_world_exports_reopens_and_renders_nodata(tmp_path: Path) -> None:
    from map_maker.terrain.adapters.world_context_render import context_image

    run = application.generate_context(
        project('<path d="M0 0 H360 V180 H0 Z"/>'), WorldContextSettings(12)
    )
    manifest = application.export_context(run, tmp_path / "shore-free")
    reopened = application.open_context(manifest).context
    assert np.isnan(reopened.shore_distance_km).all()
    assert reopened.shore_sampling.sample_count == 0
    assert not reopened.water_exposure.any()
    with context_image(reopened, "Shore distance") as image:
        assert image.getpixel((0, 0)) == (90, 90, 90)
