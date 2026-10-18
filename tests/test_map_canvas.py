# pyright: reportPrivateUsage=false
"""Map canvases: pyramid levels, flat-map coordinates and globe hover positions."""

import time
import tkinter as tk
from collections.abc import Iterator
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from map_maker.terrain.adapters.map_projection import (
    MAX_GLOBE_ZOOM,
    Drape,
    drape_zoom,
    lonlat_screen,
)
from map_maker.terrain.map_canvas import (
    KEY_TURN,
    FlatMapCanvas,
    GlobeCanvas,
    ImagePyramid,
    frame_view,
)
from map_maker.terrain.ui_jobs import LatestWorker, TkPump


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


def test_globe_canvas_renders_off_the_tk_thread_and_follows_the_cursor(root: tk.Tk) -> None:
    worker = LatestWorker(TkPump(root), lambda error: (_ for _ in ()).throw(error))
    hovered: list[tuple[float, float] | None] = []
    canvas = GlobeCanvas(root, worker, on_hover=hovered.append)
    canvas.pack(fill="both", expand=True)
    root.update()
    drawn: list[object] = []
    canvas.overlay = lambda c: drawn.append(c.frame)

    def settle() -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            root.update()
            frame = canvas.frame
            if worker.idle and frame is not None and frame.projection == canvas.projection():
                return
            time.sleep(0.01)
        raise AssertionError("The globe did not render its current view.")

    canvas.show(gradient(512, 256), central_meridian_deg=0.0)
    canvas.lon, canvas.lat = 40.0, -20.0
    canvas.request()
    settle()
    assert canvas.photo is not None and canvas.frame is not None
    assert canvas.frame.image.size == canvas.size()  # frames fill the whole canvas
    assert drawn and drawn[-1] is canvas.frame  # the overlay follows each frame
    width, height = canvas.size()
    centre = canvas.to_lonlat(width / 2, height / 2)
    assert centre is not None and np.allclose(centre, (40.0, -20.0), atol=1e-6)
    assert canvas.to_lonlat(1, 1) is None
    position = canvas.to_canvas(40.0, -20.0)
    assert position is not None and np.allclose(position, (width / 2, height / 2))
    # Dragging carries the ground under the cursor with it.
    start, end = (width / 2 - 30, height / 2 + 20), (width / 2 + 25, height / 2 - 10)
    held = canvas.to_lonlat(*start)
    canvas._press_left(SimpleNamespace(x=start[0], y=start[1]))  # type: ignore[arg-type]
    canvas._drag(SimpleNamespace(x=end[0], y=end[1]))  # type: ignore[arg-type]
    canvas._release(SimpleNamespace(x=end[0], y=end[1]))  # type: ignore[arg-type]
    settle()
    assert held is not None and np.allclose(canvas.to_lonlat(*end) or (0, 0), held, atol=1e-6)
    # The wheel zooms towards the cursor, and fit shows the whole globe again.
    canvas._wheel(SimpleNamespace(delta=120, x=end[0], y=end[1]))  # type: ignore[arg-type]
    settle()
    assert canvas.zoom > 1 and np.allclose(canvas.to_lonlat(*end) or (0, 0), held, atol=1e-6)
    canvas.fit()
    assert canvas.projection().zoom == 1.0
    # Saving keeps the canvas's framing, its shorter side at the size asked for.
    saved = canvas.snapshot(240)()
    assert saved.height == 240 and abs(saved.width / 240 - width / height) < 0.01
    canvas.turn(20, 0)
    canvas.set_kind("north-polar")
    assert canvas.projection().kind == "north-polar"
    settle()


def test_globe_canvas_spins_after_a_flick_and_keys_turn_it(root: tk.Tk) -> None:
    worker = LatestWorker(TkPump(root), lambda error: (_ for _ in ()).throw(error))
    canvas = GlobeCanvas(root, worker)
    canvas.pack(fill="both", expand=True)
    root.update()
    canvas.show(gradient(512, 256), central_meridian_deg=0.0)
    canvas.lon, canvas.lat = 0.0, 0.0
    # Arrow keys turn the view east and north; plus and minus zoom about the centre.
    canvas._key_turn(1, 0)
    assert canvas.lon > 0 and canvas.lat == 0
    canvas._key_turn(0, 1)
    assert canvas.lat > 0
    canvas._key_zoom(2.0)
    assert canvas.zoom == 2.0
    canvas._key_zoom(0.25)
    assert canvas.zoom == 1.0
    # Zoomed in, an arrow key still turns the view by the same share of the canvas.
    canvas.lon, canvas.lat, canvas.zoom = 0.0, 0.0, 12.0
    canvas._key_turn(1, 0)
    width, height = canvas.size()
    moved = lonlat_screen(canvas.projection(), (width, height), 0.0, 0.0)
    assert moved is not None
    assert moved[0] == pytest.approx(width / 2 - KEY_TURN * min(width, height) / 2, abs=0.01)
    # Past 16x, the keys zoom only into a drape, until its texels fill the pixels.
    drape = Drape(gradient(900, 900), (0.0, 0.0), 0.005)
    canvas.show(gradient(512, 256), central_meridian_deg=0.0, drapes=(drape,))
    canvas.lon, canvas.lat, canvas.zoom = 0.0, 0.0, MAX_GLOBE_ZOOM
    for _ in range(40):
        canvas._key_zoom(2.0)
    assert canvas.zoom == pytest.approx(drape_zoom(drape, canvas.size()))
    canvas.fit()
    canvas.show(gradient(512, 256), central_meridian_deg=0.0)
    # A quick flick keeps the globe turning until friction stops it.
    now = time.monotonic()
    canvas._samples = [(now - 0.05, 100.0, 100.0), (now - 0.01, 140.0, 100.0)]
    velocity = canvas._release_velocity()
    assert velocity is not None and velocity[0] == pytest.approx(1000.0)
    before = canvas.lon
    canvas.spin(velocity)
    deadline = time.monotonic() + 10
    while canvas.spinning and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert not canvas.spinning and canvas.lon < before  # dragged east, so the view turns west
    # A slow release, or one too brief to measure, does not spin; a press stops a spin.
    now = time.monotonic()
    canvas._samples = [(now - 0.05, 100.0, 100.0), (now - 0.01, 102.0, 100.0)]
    assert canvas._release_velocity() is None
    canvas._samples = [(now - 0.002, 100.0, 100.0), (now - 0.001, 140.0, 100.0)]
    assert canvas._release_velocity() is None
    canvas._samples = [(now - 0.05, 100.0, 100.0), (now - 0.01, 900.0, 100.0)]
    assert canvas._release_velocity() == pytest.approx((4000.0, 0.0))  # capped
    canvas.spin((800.0, 0.0))
    canvas._press_left(SimpleNamespace(x=10, y=10))  # type: ignore[arg-type]
    assert not canvas.spinning
