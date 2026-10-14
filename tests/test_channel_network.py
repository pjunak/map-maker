"""Connected reach topology and bounded scale-aware diagnostic rendering."""

from dataclasses import replace
from itertools import pairwise
from typing import Any

import numpy as np
import pytest
from PIL import Image

from map_maker.terrain.adapters import channel_display
from map_maker.terrain.adapters.channel_display import ChannelDisplay, reach_opacity
from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.pipeline.channel_network import ChannelNetwork, build_channel_network
from map_maker.terrain.pipeline.hydrology import DrainageIncision, drainage_incision


@pytest.fixture
def fork() -> tuple[DrainageIncision, np.ndarray[Any, Any], EndpointGrid]:
    grid = EndpointGrid((10., 20., 18., 32.), 5, 5)
    land = np.ones(grid.shape, dtype=np.bool_)
    surface = (100.-np.arange(25, dtype=np.float64)).reshape(grid.shape)
    routing = drainage_incision(surface, land, np.ones(grid.shape), x_spacing_km=2.,
                               y_spacing_km=3., maximum_elevation_m=200., variability=.5)
    receivers = np.full(grid.shape, -1, dtype=np.int64)
    for a, b in ((0, 6), (6, 12), (4, 8), (8, 12), (11, 12), (12, 17), (17, 22)):
        receivers.ravel()[a] = b
    channels = np.zeros(grid.shape, dtype=np.bool_)
    channels.ravel()[[0, 6, 4, 8, 12, 17, 22]] = True
    order = channels.astype(np.uint16)
    order.ravel()[[12, 17, 22]] = 2
    return replace(routing, receivers=receivers, channel_mask=channels,
                   routing_elevation_m=surface, stream_order=order), land, grid


def test_reaches_preserve_junctions_cover_edges_once_and_count_unique_area(
    fork: tuple[DrainageIncision, np.ndarray[Any, Any], EndpointGrid],
) -> None:
    drainage, land, grid = fork
    network = build_channel_network(drainage, land, grid)
    assert [r.nodes for r in network.reaches] == [(0, 6, 12), (4, 8, 12), (12, 17, 22)]
    assert [r.downstream for r in network.reaches] == [2, 2, None]
    # Six km2 per cell. Include the unchannelled donor 11 in the trunk area.
    assert [r.contributing_area_km2 for r in network.reaches] == [12., 12., 42.]
    assert network.reaches[-1].length_km == 6.
    assert network.reaches[0].points_km[-1] == network.reaches[-1].points_km[0] == (14., 26.)
    edges = [edge for reach in network.reaches for edge in pairwise(reach.nodes)]
    assert len(edges) == len(set(edges)) == network.edge_count == 6
    assert network == build_channel_network(drainage, land, grid)
    for scale in (.01, 100., 500., 1000., 1e6):
        for reach in network.reaches:
            if reach.downstream is not None:
                assert reach_opacity(reach.contributing_area_km2, scale) <= reach_opacity(
                    network.reaches[reach.downstream].contributing_area_km2, scale)


@pytest.mark.parametrize("fault", ["cycle", "gap", "index", "nonland", "nonlocal"])
def test_invalid_network_is_rejected(
    fork: tuple[DrainageIncision, np.ndarray[Any, Any], EndpointGrid], fault: str,
) -> None:
    routing, land, grid = fork
    if fault == "cycle":
        routing.receivers.ravel()[22] = 12
    elif fault == "gap":
        routing.channel_mask.ravel()[17] = False
    elif fault == "index":
        routing.receivers.ravel()[0] = 25
    elif fault == "nonland":
        land.ravel()[22] = False
    else:
        routing.receivers.ravel()[0] = 12
    with pytest.raises(ValueError):
        build_channel_network(routing, land, grid)


def _display(network: ChannelNetwork, *, conflict: bool = False) -> ChannelDisplay:
    reach = network.reaches[0]
    uphill = ((reach.points_km[0], reach.points_km[1]),) if conflict else ()
    return ChannelDisplay(network, uphill, tuple(r.points_km for r in network.reaches))


def test_visibility_is_monotone_with_zoom_and_independent_of_pan(
    fork: tuple[DrainageIncision, np.ndarray[Any, Any], EndpointGrid],
) -> None:
    display = _display(build_channel_network(*fork))
    counts = [display.visible_reach_count((0., 0., z*8., z*12.)) for z in (1., 10., 20., 100.)]
    assert counts == sorted(counts)
    assert counts[0] == 0 and counts[-1] == 3
    assert display.visible_reach_count((-100., -50., 60., 190.)) == counts[2]
    assert display.visible_reach_count((0., 0., 8., 12.), all_channels=True) == 3


def test_uphill_edges_remain_visible_when_every_reach_is_hidden(
    fork: tuple[DrainageIncision, np.ndarray[Any, Any], EndpointGrid],
) -> None:
    display = _display(build_channel_network(*fork), conflict=True)
    rect = (10., 10., 90., 130.)
    assert display.visible_reach_count(rect) == 0
    with display.render(rect, (150, 150)) as image:
        pixels = np.asarray(image)
        visible = pixels[pixels[..., 3] > 100]
        assert len(visible) > 10
        assert np.all(visible[:, 0] > visible[:, 2])


def test_tile_boundaries_and_cropped_pan_match_without_zoom_sized_scratch(
    fork: tuple[DrainageIncision, np.ndarray[Any, Any], EndpointGrid],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    display = _display(build_channel_network(*fork), conflict=True)
    rect = (-67., -33., 757., 931.)
    size = (390, 310)
    monkeypatch.setattr(channel_display, "CHANNEL_RENDER_TILE_EDGE", 512)
    with display.render(rect, size, all_channels=True) as image:
        reference = np.array(image)
    allocations: list[tuple[int, int]] = []
    new = Image.new
    def record(mode: str, size: tuple[int, int], *args: Any, **kwargs: Any) -> Image.Image:
        allocations.append(size)
        return new(mode, size, *args, **kwargs)
    monkeypatch.setattr(channel_display, "CHANNEL_RENDER_TILE_EDGE", 32)
    monkeypatch.setattr(Image, "new", record)
    with display.render(rect, size, all_channels=True) as tiled:
        np.testing.assert_array_equal(np.asarray(tiled), reference)
    assert all(s == size or max(s) <= 126 for s in allocations)
    shifted = (rect[0]-80, rect[1]-55, rect[2]-80, rect[3]-55)
    with display.render(shifted, (200, 180), all_channels=True) as cropped:
        np.testing.assert_array_equal(np.asarray(cropped), reference[55:235, 80:280])


def test_zoom_increases_line_length_without_enlarging_stroke_width(
    fork: tuple[DrainageIncision, np.ndarray[Any, Any], EndpointGrid],
) -> None:
    display = _display(build_channel_network(*fork))
    counts: list[int] = []
    for factor in (1, 4):
        with display.render((10., 10., 210.*factor, 290.*factor),
                            (220*factor, 300*factor), all_channels=True) as image:
            counts.append(int(np.count_nonzero(np.asarray(image)[..., 3] > 100)))
    assert 3*counts[0] < counts[1] < 5*counts[0]
