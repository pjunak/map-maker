# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""Water-piece incidence must preserve barriers, finite gaps, areas and units."""

from dataclasses import replace
from math import pi

import numpy as np
import pytest
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from test_world_context import context, project

from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_context import SphericalContextGrid, WorldContextSettings
from map_maker.terrain.pipeline import world_connectivity as connectivity
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled
from map_maker.terrain.pipeline.world import prepare_world_map
from map_maker.terrain.pipeline.world_context import generate_world_context, water_topology


def graph(land: BaseGeometry, rows: int = 12) -> connectivity.WaterConnectivity:
    grid = SphericalContextGrid(WorldFrame((0, 0, 360, 180), 1000), WorldContextSettings(rows))
    polygons, ids, _bodies = water_topology(land, grid.frame, None)
    return connectivity.build_water_connectivity(land, polygons, ids, grid, checkpoint=lambda: None)


def nodes_at(g: connectivity.WaterConnectivity, row: int, col: int, columns: int = 24) -> range:
    index = row * columns + col
    return range(int(g.cell_offsets[index]), int(g.cell_offsets[index + 1]))


def test_open_sphere_has_periodic_longitude_but_no_corner_or_polar_links() -> None:
    g = graph(Polygon())
    assert len(g.water_body) == 12 * 24
    assert len(g.link_nodes) == 12 * 24 + 11 * 24
    assert g.component_count == 1 and g.split_cells == 0
    assert g.area_km2.sum() == pytest.approx(4 * pi * 1000**2)
    for (a, b), axis in zip(g.link_nodes, g.link_axis, strict=True):
        ar, ac = divmod(int(a), 24)
        br, bc = divmod(int(b), 24)
        assert (br, bc) == ((ar, (ac + 1) % 24) if axis == 0 else (ar + 1, ac))
    assert np.all(g.link_width_km > 0)
    assert np.all(g.incident_links[:24] == 3)
    assert np.all(g.incident_links[-24:] == 3)
    assert np.all(g.incident_links[24:-24] == 4)


def test_land_only_has_a_valid_empty_graph() -> None:
    g = graph(box(0, 0, 360, 180))
    assert not g.water_body.size and not g.link_nodes.size
    assert g.component_count == 0
    assert np.all(g.cell_offsets == 0)
    assert g.link_nodes.shape == (0, 2) and g.sample_uv.shape == (0, 2)


def test_same_ocean_on_both_sides_of_a_cell_wall_has_separate_local_nodes() -> None:
    g = graph(box(172, 50, 178, 100))
    a, b = nodes_at(g, 4, 11)
    assert g.water_body[a] == g.water_body[b] == 1
    assert g.component[a] == g.component[b]  # Connected around the wall elsewhere.
    assert not np.any(np.all(g.link_nodes == (a, b), axis=1))
    assert g.sample_uv[a, 0] < 172 / 360 < 178 / 360 < g.sample_uv[b, 0]
    neighbours_a = set(g.link_nodes[np.any(g.link_nodes == a, axis=1)].ravel()) - {a}
    neighbours_b = set(g.link_nodes[np.any(g.link_nodes == b, axis=1)].ravel()) - {b}
    assert set(nodes_at(g, 4, 10)) <= neighbours_a
    assert not set(nodes_at(g, 4, 12)) & neighbours_a
    assert set(nodes_at(g, 4, 12)) <= neighbours_b
    assert not set(nodes_at(g, 4, 10)) & neighbours_b


def test_two_intervals_between_the_same_pieces_are_retained_separately() -> None:
    g = graph(box(177, 63, 183, 67))
    (a,) = nodes_at(g, 4, 11)
    (b,) = nodes_at(g, 4, 12)
    match = np.all(g.link_nodes == (a, b), axis=1)
    assert np.count_nonzero(match) == 2
    assert np.allclose(g.link_interval[match], [(0, 3 / 15), (7 / 15, 1)])
    assert g.link_width_km[match].sum() == pytest.approx(11 * pi / 180 * 1000)


@pytest.mark.parametrize("gap", [0.001, 0.01, 0.1])
def test_subcell_strait_carries_only_its_positive_physical_interval(gap: float) -> None:
    land = box(170, 0, 190, 80).union(box(170, 80 + gap, 190, 180))
    g = graph(land)
    (a,) = nodes_at(g, 5, 11)
    (b,) = nodes_at(g, 5, 12)
    match = np.all(g.link_nodes == (a, b), axis=1)
    assert match.sum() == 1
    assert g.link_width_km[match][0] == pytest.approx(gap * pi / 180 * 1000)
    assert g.component_count == 1


def test_corner_only_water_contact_never_links_two_basins() -> None:
    wet = box(15, 15, 30, 30).union(box(30, 30, 45, 45))
    g = graph(box(0, 0, 360, 180).difference(wet))
    assert len(g.water_body) == 2 and not len(g.link_nodes)
    assert g.component_count == 2


def test_disjoint_periodic_edge_intervals_never_link() -> None:
    left = box(0, 60, 10, 65)
    right = box(350, 70, 360, 75)
    g = graph(box(0, 0, 360, 180).difference(left.union(right)))
    assert len(g.water_body) == 2 and not len(g.link_nodes)
    assert g.component_count == 2
    opened = graph(box(0, 0, 360, 180).difference(left.union(box(350, 63, 360, 68))))
    assert len(opened.link_nodes) == 1 and opened.component_count == 1
    assert opened.link_width_km[0] == pytest.approx(2 * pi / 180 * 1000)


def test_lake_and_ocean_in_one_cell_keep_distinct_bodies_and_conserve_area() -> None:
    result = context(
        '<path fill-rule="evenodd" d="M100 50 H150 V100 H100 Z M101 61 H102 V62 H101 Z"/>'
    )
    g = result.connectivity
    ids = list(nodes_at(g, 4, 6))
    assert len(ids) == 2 and len(set(g.water_body[ids])) == 2
    lake = ids[int(np.argmin(g.area_km2[ids]))]
    assert g.incident_links[lake] == 0
    assert g.area_km2.sum() + result.land_area_km2 == pytest.approx(
        result.grid.frame.surface_area_km2
    )


@pytest.mark.parametrize("scale,offset", [(0.01, -20.35), (10, 123.7)])
def test_graph_units_and_topology_ignore_page_scale_and_origin(scale: float, offset: float) -> None:
    body = '<path d="M172 50 H178 V100 H172 Z"/>'
    base = context(body).connectivity
    changed = generate_world_context(
        prepare_world_map(project(body, scale=scale, offset=offset)), WorldContextSettings(12)
    ).connectivity
    for name, array in base.arrays().items():
        assert np.allclose(array, changed.arrays()[name], rtol=1e-10, atol=1e-9), name
    p = project(body)
    larger = generate_world_context(
        prepare_world_map(replace(p, frame=replace(p.frame, radius_km=2000))),
        WorldContextSettings(12),
    ).connectivity
    assert np.allclose(larger.area_km2, 4 * base.area_km2)
    assert np.allclose(larger.link_width_km, 2 * base.link_width_km)
    assert np.array_equal(base.link_nodes, larger.link_nodes)


def test_graph_is_deterministic_read_only_and_cancellable() -> None:
    a, b = graph(box(172, 50, 178, 100)), graph(box(172, 50, 178, 100))
    for name, array in a.arrays().items():
        assert np.array_equal(array, b.arrays()[name])
        assert not array.flags.writeable
    assert not a.component.flags.writeable and not a.incident_links.flags.writeable
    token = CancellationToken()

    def cancel(_fraction: float, message: str) -> None:
        if message.startswith("Connecting water passages"):
            token.cancel()

    with pytest.raises(GenerationCancelled):
        generate_world_context(
            prepare_world_map(project('<path d="M50 50 H60 V60 H50 Z"/>')),
            WorldContextSettings(12),
            cancel,
            cancellation=token,
        )


@pytest.mark.parametrize(
    "budget",
    [
        "MAX_WATER_PIECES",
        "MAX_WATER_LINKS",
        "MAX_CELL_PIECES",
        "MAX_CLIPPED_VERTICES",
        "MAX_FACE_INTERVALS",
    ],
)
def test_geometry_admission_fails_instead_of_dropping_water(
    budget: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connectivity, budget, 0)
    with pytest.raises(ValueError, match=r"budget|Too many"):
        graph(box(172, 50, 178, 100))


def test_subprecision_opening_retains_pieces_with_explicit_unresolved_support() -> None:
    # Independent synthetic thin triangular lake. Its cut at a latitude edge
    # can round to one point despite a positive-area source polygon.
    tip = float(np.nextafter(172.775, 0))
    wet = Polygon(((172.125, 82.125), (172.775, 90.125), (tip, 90.125)))
    land = box(0, 0, 360, 180).difference(wet)
    frame = WorldFrame((0, 0, 360, 180), 1000)
    _, _, bodies = water_topology(land, frame, None)
    g = graph(land, rows=36)
    assert len(bodies) == 1
    assert g.fragmented_bodies == (1,) and g.component_count == 2
    assert len(g.water_body) == 2 and np.all(g.area_km2 > 0)
    assert not g.link_nodes.size
    assert g.area_km2.sum() == pytest.approx(bodies[0].area_km2, abs=1e-8)
