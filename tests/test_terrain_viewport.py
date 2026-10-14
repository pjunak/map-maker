"""Navigation preserves geography and allocates only a viewport-sized raster."""

import pytest
from PIL import Image

from map_maker.terrain.adapters.viewport import render_viewport
from map_maker.terrain.viewport import MapViewport


def test_zoom_keeps_the_geographic_point_beneath_the_cursor() -> None:
    view = MapViewport()
    canvas, world = (800., 600.), (2000., 1000.)
    anchor = (525., 360.)
    left, top, right, bottom = view.rect(canvas, world)
    point = ((anchor[0] - left) / (right - left), (anchor[1] - top) / (bottom - top))
    for factor in (2., 3., 0.5, 0.75):
        view.zoom_at(factor, anchor, canvas, world)
        left, top, right, bottom = view.rect(canvas, world)
        assert (left + point[0] * (right - left), top + point[1] * (bottom - top)) == (
            pytest.approx(anchor))
    view.fit()
    assert view.zoom == 1 and view.centre == (0.5, 0.5)
    assert view.visible_bounds(canvas, world) == (0, 0, 1, 1)


def test_pan_and_resize_keep_a_stable_geographic_centre_and_bounded_zoom() -> None:
    view = MapViewport()
    canvas, world = (800., 600.), (2000., 1000.)
    view.zoom_at(4, (400., 300.), canvas, world)
    before = view.rect(canvas, world)
    view.pan((48., -30.), canvas, world)
    after = view.rect(canvas, world)
    assert after[0] - before[0] == pytest.approx(48)
    assert after[1] - before[1] == pytest.approx(-30)
    resized = view.rect((1200., 800.), world)
    assert resized[0] + view.centre[0] * (resized[2] - resized[0]) == pytest.approx(600)
    assert resized[1] + view.centre[1] * (resized[3] - resized[1]) == pytest.approx(400)
    bounds = view.visible_bounds(canvas, world)
    assert 0 < bounds[0] < bounds[2] < 1 and 0 < bounds[1] < bounds[3] < 1
    view.zoom_at(1e6, (400., 300.), canvas, world)
    assert view.zoom == 32
    view.zoom_at(1e-6, (400., 300.), canvas, world)
    assert view.zoom == 1
    view.pan((1e9, -1e9), canvas, world)
    assert view.centre == (0, 1)


@pytest.mark.parametrize("factor", [0., -1., float("inf"), float("nan")])
def test_invalid_zoom_is_rejected(factor: float) -> None:
    with pytest.raises(ValueError):
        MapViewport().zoom_at(factor, (400., 300.), (800., 600.), (1., 1.))


def test_raster_allocation_depends_on_canvas_not_magnification() -> None:
    with Image.new("RGBA", (64, 64), (90, 140, 70, 255)) as source:
        original = source.tobytes()
        with render_viewport(source, (-50000, -50000, 50000, 50000), (800, 600)) as view:
            assert view.size == (800, 600)
            assert view.getpixel((400, 300)) == (90, 140, 70, 255)
        with render_viewport(source, (10, 10, 50, 50), (60, 60)) as view:
            assert view.getpixel((0, 0)) == (0, 0, 0, 0)
            assert view.getpixel((30, 30)) == (90, 140, 70, 255)
        assert source.tobytes() == original
