# pyright: reportPrivateUsage=false
"""Map canvases: pyramid levels, flat-map coordinates and globe hover positions."""

import time
import tkinter as tk
from collections.abc import Iterator
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from dmtools.terrain.adapters.map_projection import MapProjection, displayed_lonlat
from dmtools.terrain.map_canvas import FlatMapCanvas, GlobeCanvas, ImagePyramid, frame_view
from dmtools.terrain.ui_jobs import LatestWorker, TkPump


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    try:
        window = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}")
    window.geometry("400x300")
    yield window
    window.destroy()


def gradient(width: int, height: int) -> Image.Image:
    """Red encodes the column and green the row, to check where pixels land."""
    x = np.linspace(0, 255, width)[None, :].repeat(height, 0)
    y = np.linspace(0, 255, height)[:, None].repeat(width, 1)
    rgb = np.stack([x, y, np.zeros_like(x)], axis=-1).astype(np.uint8)
    return Image.fromarray(rgb)


def test_pyramid_picks_the_smallest_copy_that_still_covers_the_view() -> None:
    pyramid = ImagePyramid(gradient(2048, 1024))
    assert pyramid.level(3000).width == 2048
    assert pyramid.level(900).width == 1024
    assert pyramid.level(300).width == 512
    # Same picture from a reduced level: the view centre shows the image centre.
    view = pyramid.view((0, 0, 400, 200), (400, 200), "#000000")
    red, green = (int(v) for v in np.asarray(view)[100, 200, :2])
    assert abs(red - 128) <= 3 and abs(green - 128) <= 3


def test_frame_view_crops_the_visible_part_and_fills_the_rest() -> None:
    image = gradient(200, 100)
    view = frame_view(image, (-100, 0, 300, 200), (200, 100), "#0000ff")
    assert view.size == (200, 100)
    # The canvas's left edge is a quarter of the way across the map.
    assert abs(int(np.asarray(view)[0, 0, 0]) - 64) <= 3
    assert view.getpixel((199, 99)) != (0, 0, 255)  # still on the map
    assert frame_view(image, (300, 0, 500, 100), (200, 100), "#0000ff").getpixel((5, 5)) == (
        0, 0, 255
    )  # an off-canvas map leaves the background


def test_flat_canvas_maps_between_canvas_and_map_positions(root: tk.Tk) -> None:
    clicks: list[tuple[float, float]] = []
    canvas = FlatMapCanvas(root, background="#000000",
                           on_click=lambda point, _e: clicks.append(point))
    canvas.pack(fill="both", expand=True)
    root.update()
    pyramid = ImagePyramid(gradient(512, 256))
    canvas.show(pyramid.renderer((2.0, 1.0), "#000000"), (2.0, 1.0))
    canvas.draw_now()
    assert canvas.photo is not None
    x, y = canvas.to_canvas(0.25, 0.75)
    position = canvas.to_map(x, y)
    assert position is not None and np.allclose(position, (0.25, 0.75))
    canvas.zoom_by(2.0, (x, y))
    assert np.allclose(canvas.to_map(x, y) or (0, 0), (0.25, 0.75))  # zoom keeps the anchor
    canvas._press_left(SimpleNamespace(x=x, y=y))  # type: ignore[arg-type]
    canvas._release_left(SimpleNamespace(x=x, y=y))  # type: ignore[arg-type]
    assert clicks and np.allclose(clicks[0], (0.25, 0.75))
    # A drag pans and is not a click.
    canvas._press_left(SimpleNamespace(x=x, y=y))  # type: ignore[arg-type]
    canvas._drag(SimpleNamespace(x=x + 40, y=y))  # type: ignore[arg-type]
    canvas._release_left(SimpleNamespace(x=x + 40, y=y))  # type: ignore[arg-type]
    assert len(clicks) == 1 and np.allclose(canvas.to_map(x + 40, y) or (0, 0), (0.25, 0.75))


def test_displayed_globe_positions_follow_the_drawn_disc() -> None:
    view = MapProjection("globe", 30.0, 10.0)
    lon, lat, inside = displayed_lonlat(view, 101)
    assert inside[50, 50] and np.isclose(lon[50, 50], 30.0, atol=2) and np.isclose(
        lat[50, 50], 10.0, atol=2
    )
    assert not inside[0, 0] and not inside[50, 100]  # corner and halo are off the planet


def test_globe_canvas_renders_off_the_tk_thread_and_reports_positions(root: tk.Tk) -> None:
    worker = LatestWorker(TkPump(root), lambda error: (_ for _ in ()).throw(error))
    hovered: list[tuple[float, float] | None] = []
    canvas = GlobeCanvas(root, worker, on_hover=hovered.append)
    canvas.pack(fill="both", expand=True)
    root.update()
    canvas.show(gradient(512, 256), central_meridian_deg=0.0)
    canvas.lon, canvas.lat = 40.0, -20.0
    canvas.request()
    deadline = time.monotonic() + 10
    while (canvas.frame is None or canvas.frame.lon is None) and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert canvas.photo is not None and canvas.frame is not None
    centre = canvas.to_lonlat(canvas.winfo_width() / 2, canvas.winfo_height() / 2)
    assert centre is not None and np.allclose(centre, (40.0, -20.0), atol=2)
    assert canvas.to_lonlat(1, 1) is None
    canvas.turn(20, 0)
    assert canvas.lon < 40.0
    canvas.set_kind("north-polar")
    assert canvas.projection().kind == "north-polar"
