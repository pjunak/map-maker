# pyright: reportUnknownMemberType=false
"""Interactive map canvases: a pan/zoom flat map and a turnable globe or polar view.

Both are presentation only. They show images they are given (or ask a renderer
for one) and report what is under the cursor in map coordinates; the screens
that use them decide what the map means. ``MapImages`` gives a screen the maps
of a source that draws them on demand, drawing missing ones in the background.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageTk

from map_maker.terrain.adapters.map_projection import (
    SPACE,
    MapProjection,
    displayed_lonlat,
    reproject,
)
from map_maker.terrain.ui_jobs import LatestWorker
from map_maker.terrain.ui_style import FONT_HERO, FONT_MAP_LABEL, MAP_TEXT, MAP_TEXT_MUTED
from map_maker.terrain.viewport import MapViewport

type Point = tuple[float, float]
type Rect = tuple[float, float, float, float]
type Renderer = Callable[[MapViewport, tuple[int, int]], Image.Image]

DRAG_THRESHOLD_PX = 4
REDRAW_MS = 15
WHEEL_STEP = 1.25


def frame_view(
    image: Image.Image, rect: Rect, size: tuple[int, int], background: str
) -> Image.Image:
    """Place a whole-map image into the canvas rectangle ``rect`` of the current view."""
    width, height = size
    canvas = Image.new("RGB", size, background)
    left, top, right, bottom = rect
    if right <= left or bottom <= top:
        return canvas
    x0, y0 = max(0.0, left), max(0.0, top)
    x1, y1 = min(float(width), right), min(float(height), bottom)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return canvas
    sx, sy = image.width / (right - left), image.height / (bottom - top)
    crop = image.crop(
        (int((x0 - left) * sx), int((y0 - top) * sy),
         max(int((x0 - left) * sx) + 1, int((x1 - left) * sx)),
         max(int((y0 - top) * sy) + 1, int((y1 - top) * sy)))
    )
    canvas.paste(
        crop.resize((int(x1 - x0), int(y1 - y0)), Image.Resampling.BILINEAR), (int(x0), int(y0))
    )
    return canvas


class ImagePyramid:
    """An image with cached half-size copies, so any zoom resamples less than 2:1."""

    def __init__(self, image: Image.Image) -> None:
        self.levels = [image if image.mode in ("RGB", "RGBA") else image.convert("RGB")]

    @property
    def image(self) -> Image.Image:
        return self.levels[0]

    def level(self, displayed_width: float) -> Image.Image:
        """The smallest cached copy at least ``displayed_width`` pixels wide."""
        while (last := self.levels[-1]).width // 2 >= max(displayed_width, 64):
            self.levels.append(last.reduce(2))
        return next(
            (lvl for lvl in reversed(self.levels) if lvl.width >= displayed_width), self.levels[0]
        )

    def view(self, rect: Rect, size: tuple[int, int], background: str) -> Image.Image:
        """The image stretched over canvas rectangle ``rect`` of a ``size`` canvas."""
        return frame_view(self.level(rect[2] - rect[0]), rect, size, background)

    def renderer(self, world_size: Point, background: str) -> Renderer:
        """A flat-canvas renderer showing this image over a map of ``world_size``."""
        def render(viewport: MapViewport, size: tuple[int, int]) -> Image.Image:
            return self.view(viewport.rect((float(size[0]), float(size[1])), world_size),
                             size, background)

        return render


class MapSource(Protocol):
    """Maps by label, each drawn the first time it is asked for (``PlanetMaps``)."""

    @property
    def labels(self) -> tuple[str, ...]: ...

    def image(self, label: str) -> Image.Image | None: ...

    def draw(self, label: str) -> Image.Image: ...


class MapImages:
    """One screen's maps from a source: drawn maps at once, missing ones in the background.

    A missing map is drawn on ``worker``, which the screen owns, so choosing another
    map before it is ready replaces the queued request. ``on_drawn`` gets the label
    on the Tk thread once the map is ready.
    """

    def __init__(self, worker: LatestWorker, on_drawn: Callable[[str], None]) -> None:
        self._worker = worker
        self._on_drawn = on_drawn
        self.source: MapSource | None = None
        self._pyramids: dict[str, ImagePyramid] = {}

    @property
    def labels(self) -> tuple[str, ...]:
        return () if self.source is None else self.source.labels

    def show(self, source: MapSource | None) -> None:
        """Use another source; maps still requested from the previous one are dropped."""
        self._worker.cancel()
        self.source, self._pyramids = source, {}

    def ready(self, label: str) -> bool:
        return self.source is not None and self.source.image(label) is not None

    def image(self, label: str) -> Image.Image | None:
        """The map, or None while it is drawn in the background (requested now)."""
        source = self.source
        if source is None or label not in source.labels:
            return None
        image = source.image(label)
        if image is None:
            self._worker.submit(
                lambda: source.draw(label), lambda _image: self._drawn(source, label)
            )
        return image

    def pyramid(self, label: str) -> ImagePyramid | None:
        """``image`` with cached half-size copies for zooming."""
        if label not in self._pyramids:
            image = self.image(label)
            if image is None:
                return None
            self._pyramids[label] = ImagePyramid(image)
        return self._pyramids[label]

    def _drawn(self, source: MapSource, label: str) -> None:
        if source is self.source:
            self._on_drawn(label)


class FlatMapCanvas(tk.Canvas):
    """A rectangular map with wheel zoom and drag panning.

    A left click without dragging goes to ``on_click`` with the normalized map
    position (0-1 across, 0-1 down); hovering goes to ``on_hover``. ``overlay``
    draws vector marks over the image in canvas coordinates.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        background: str,
        on_click: Callable[[Point, tk.Event[tk.Misc]], None] | None = None,
        on_hover: Callable[[Point | None], None] | None = None,
        on_view_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, background=background, highlightthickness=0)
        self.map_background = background
        self.viewport = MapViewport()
        self.world_size: Point = (2.0, 1.0)
        self.renderer: Renderer | None = None
        self.overlay: Callable[[FlatMapCanvas, Rect], None] | None = None
        self.placeholder: tuple[str, str] = ("", "")
        self.photo: ImageTk.PhotoImage | None = None
        self._on_click = on_click
        self._on_hover = on_hover
        self._on_view_changed = on_view_changed
        self._draw_id: str | None = None
        self._press: Point | None = None
        self._dragging = False
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._on_hover(None) if self._on_hover else None)
        self.bind("<ButtonPress-1>", self._press_left)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release_left)
        for button in (2, 3):
            self.bind(f"<ButtonPress-{button}>", self._press_pan)
            self.bind(f"<B{button}-Motion>", self._drag)
            self.bind(f"<ButtonRelease-{button}>", self._release_pan)

    # Content and view

    def show(self, renderer: Renderer | None, world_size: Point, *, fit: bool = False) -> None:
        if fit:
            self.viewport.fit()
        self.renderer, self.world_size = renderer, world_size
        self.redraw()

    def redraw(self) -> None:
        if self._draw_id is None:
            self._draw_id = self.after(REDRAW_MS, self.draw_now)

    def draw_now(self) -> None:
        if self._draw_id is not None:
            self.after_cancel(self._draw_id)
            self._draw_id = None
        self.delete("all")
        width, height = self.size()
        if self.renderer is None:
            self.photo = None
            title, body = self.placeholder
            self.create_text(width / 2, height / 2 - 24, text=title, fill=MAP_TEXT,
                             font=FONT_HERO)
            self.create_text(width / 2, height / 2 + 25, text=body, fill=MAP_TEXT_MUTED,
                             font=FONT_MAP_LABEL[:2], justify="center")
            return
        with self.renderer(self.viewport, (width, height)) as image:
            self.photo = ImageTk.PhotoImage(image, master=self)
        self.create_image(0, 0, image=self.photo, anchor="nw", tags=("map",))
        self.draw_overlay()

    def draw_overlay(self) -> None:
        """Redraw only the vector marks over the current image (cheap, e.g. on hover)."""
        self.delete("overlay")
        if self.overlay is None or self.renderer is None:
            return
        self.overlay(self, self.map_rect())
        self.addtag_all("overlay")
        self.dtag("map", "overlay")

    def fit(self) -> None:
        self.viewport.fit()
        self._changed()

    def zoom_by(self, factor: float, anchor: Point | None = None) -> None:
        width, height = self.size()
        self.viewport.zoom_at(
            factor, anchor or (width / 2, height / 2), (width, height), self.world_size
        )
        self._changed()

    # Coordinates

    def size(self) -> tuple[int, int]:
        return max(1, self.winfo_width()), max(1, self.winfo_height())

    def map_rect(self) -> Rect:
        width, height = self.size()
        return self.viewport.rect((float(width), float(height)), self.world_size)

    def to_map(self, x: float, y: float) -> Point | None:
        """Normalized map position of a canvas point, or None outside the map."""
        left, top, right, bottom = self.map_rect()
        if not (left <= x <= right and top <= y <= bottom):
            return None
        return (x - left) / (right - left), (y - top) / (bottom - top)

    def to_canvas(self, u: float, v: float) -> Point:
        left, top, right, bottom = self.map_rect()
        return left + u * (right - left), top + v * (bottom - top)

    # Interaction

    def _changed(self) -> None:
        self.redraw()
        if self._on_view_changed is not None:
            self._on_view_changed()

    def _wheel(self, event: tk.Event[tk.Misc]) -> str:
        self.focus_set()
        if event.delta:
            self.zoom_by(WHEEL_STEP if event.delta > 0 else 1 / WHEEL_STEP,
                         (float(event.x), float(event.y)))
        return "break"

    def _motion(self, event: tk.Event[tk.Misc]) -> None:
        if self._on_hover is not None and self.renderer is not None:
            self._on_hover(self.to_map(event.x, event.y))

    def _press_left(self, event: tk.Event[tk.Misc]) -> None:
        self.focus_set()
        self._press, self._dragging = (event.x, event.y), False

    def _press_pan(self, event: tk.Event[tk.Misc]) -> None:
        self._press_left(event)
        self._dragging = True
        self.configure(cursor="fleur")

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._press is None:
            return
        dx, dy = event.x - self._press[0], event.y - self._press[1]
        if not self._dragging and max(abs(dx), abs(dy)) < DRAG_THRESHOLD_PX:
            return
        if not self._dragging:
            self._dragging = True
            self.configure(cursor="fleur")
        self.viewport.pan((dx, dy), self.size(), self.world_size)
        self._press = (event.x, event.y)
        self._changed()

    def _release_left(self, event: tk.Event[tk.Misc]) -> None:
        clicked = self._press is not None and not self._dragging
        self._release_pan(event)
        if clicked and self._on_click is not None and self.renderer is not None:
            position = self.to_map(event.x, event.y)
            if position is not None:
                self._on_click(position, event)

    def _release_pan(self, _event: tk.Event[tk.Misc]) -> None:
        self._press, self._dragging = None, False
        self.configure(cursor="")


@dataclass(frozen=True, slots=True)
class GlobeFrame:
    """A rendered globe or polar frame and, for full frames, each pixel's position."""

    image: Image.Image
    projection: MapProjection
    lon: NDArray[np.float64] | None = None
    lat: NDArray[np.float64] | None = None
    inside: NDArray[np.bool_] | None = None


POLAR_SPAN_DEG = (30.0, 150.0)  # pole-to-edge angle range for polar zoom
DEGREES_PER_PIXEL = 0.35
DRAG_FRAME_SCALE = 0.4  # drag frames render at this fraction of the canvas, then scale up
DRAG_SOURCE_WIDTH = 1024
SPACE_COLOUR = "#{:02x}{:02x}{:02x}".format(*SPACE)  # matches the projected views' surround


class GlobeCanvas(tk.Canvas):
    """A world-frame map shown as a globe or polar view, rendered off the Tk thread.

    Drag turns the view (quick low-resolution frames while dragging, a sharp one on
    release); the wheel zooms polar views. Clicks and hover report longitude and
    latitude in degrees.
    """

    def __init__(
        self,
        parent: tk.Misc,
        worker: LatestWorker,
        *,
        on_click: Callable[[Point, tk.Event[tk.Misc]], None] | None = None,
        on_hover: Callable[[Point | None], None] | None = None,
        on_view_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, background=SPACE_COLOUR, highlightthickness=0)
        self._worker = worker
        self._on_click = on_click
        self._on_hover = on_hover
        self._on_view_changed = on_view_changed
        self.kind = "globe"
        self.lon = 0.0
        self.lat = 20.0
        self.polar_span = 90.0
        self.graticule = True
        self.central_meridian_deg = 0.0
        self.image: Image.Image | None = None
        self.placeholder = ""  # shown while there is no image
        self._drag_source: Image.Image | None = None
        self.frame: GlobeFrame | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self._press: Point | None = None
        self._dragging = False
        self._render_id: str | None = None
        self.bind("<Configure>", lambda _e: self.request())
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._on_hover(None) if self._on_hover else None)
        self.bind("<ButtonPress-1>", self._press_left)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)

    def show(self, image: Image.Image | None, central_meridian_deg: float) -> None:
        changed = image is not self.image or central_meridian_deg != self.central_meridian_deg
        if image is not self.image:
            self.image = image
            self._drag_source = None
        self.central_meridian_deg = central_meridian_deg
        if changed and image is not None:
            self.request(quick=True)
        self.request()

    def set_kind(self, kind: str) -> None:
        if kind != self.kind:
            self.kind = kind
            if self.image is not None:
                self.request(quick=True)
            self.request()

    def projection(self) -> MapProjection:
        if self.kind == "globe":
            return MapProjection("globe", self.lon, self.lat)
        sign = 1.0 if self.kind == "north-polar" else -1.0
        return MapProjection(self.kind, self.lon, limit_deg=sign * (90.0 - self.polar_span))

    def view_size(self) -> int:
        return max(16, min(self.winfo_width(), self.winfo_height()))

    def request(self, *, quick: bool = False) -> None:
        """Ask for a new frame of the current view (coalesced, rendered in the background)."""
        if self.image is None:
            self.delete("all")
            self.photo, self.frame = None, None
            if self.placeholder:
                self.create_text(
                    max(1, self.winfo_width()) / 2, max(1, self.winfo_height()) / 2,
                    text=self.placeholder, fill=MAP_TEXT_MUTED, font=FONT_MAP_LABEL[:2],
                )
            return
        if quick:
            self._submit(quick=True)
        elif self._render_id is None:
            self._render_id = self.after(REDRAW_MS, self._submit)

    def render(self, size: int) -> Image.Image:
        """The current view at ``size`` pixels (on the calling thread; used for saving)."""
        assert self.image is not None
        return reproject(
            self.image, self.projection(), size,
            central_meridian_deg=self.central_meridian_deg, graticule=self.graticule,
        )

    def _submit(self, *, quick: bool = False) -> None:
        if self._render_id is not None:
            self.after_cancel(self._render_id)
            self._render_id = None
        image = self.image
        if image is None:
            return
        size = self.view_size()
        projection, meridian, graticule = self.projection(), self.central_meridian_deg, \
            self.graticule
        if quick:
            source = self._quick_source(image)
            small = max(64, int(size * DRAG_FRAME_SCALE))

            def work() -> GlobeFrame:
                frame = reproject(source, projection, small, central_meridian_deg=meridian,
                                  graticule=graticule)
                return GlobeFrame(frame.resize((size, size), Image.Resampling.BILINEAR),
                                  projection)
        else:
            def work() -> GlobeFrame:
                frame = reproject(image, projection, size, central_meridian_deg=meridian,
                                  graticule=graticule)
                lon, lat, inside = displayed_lonlat(projection, size)
                return GlobeFrame(frame, projection, lon, lat, inside)

        self._worker.submit(work, self._present)

    def _quick_source(self, image: Image.Image) -> Image.Image:
        if self._drag_source is None:
            factor = max(1, image.width // DRAG_SOURCE_WIDTH)
            self._drag_source = image.reduce(factor) if factor > 1 else image
        return self._drag_source

    def _present(self, frame: GlobeFrame) -> None:
        if self.image is None:
            return
        self.frame = frame
        self.photo = ImageTk.PhotoImage(frame.image, master=self)
        self.delete("all")
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        self.create_image(width / 2, height / 2, image=self.photo, anchor="center")

    def to_lonlat(self, x: float, y: float) -> Point | None:
        """Longitude/latitude (degrees) under a canvas point of the last full frame."""
        frame = self.frame
        if frame is None or frame.lon is None or frame.lat is None or frame.inside is None:
            return None
        size = frame.image.width
        column = int(x - (self.winfo_width() - size) / 2)
        row = int(y - (self.winfo_height() - size) / 2)
        if not (0 <= row < size and 0 <= column < size) or not frame.inside[row, column]:
            return None
        lon = (float(frame.lon[row, column]) + 180) % 360 - 180
        lat = float(frame.lat[row, column])
        return (lon, lat) if isfinite(lon) and isfinite(lat) else None

    def _motion(self, event: tk.Event[tk.Misc]) -> None:
        if self._on_hover is not None and self._press is None:
            self._on_hover(self.to_lonlat(event.x, event.y))

    def _wheel(self, event: tk.Event[tk.Misc]) -> str:
        if self.kind != "globe" and event.delta:
            low, high = POLAR_SPAN_DEG
            factor = 1 / WHEEL_STEP if event.delta > 0 else WHEEL_STEP
            self.polar_span = min(high, max(low, self.polar_span * factor))
            self.request()
            self._notify()
        return "break"

    def _press_left(self, event: tk.Event[tk.Misc]) -> None:
        self.focus_set()
        self._press, self._dragging = (event.x, event.y), False

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._press is None:
            return
        dx, dy = event.x - self._press[0], event.y - self._press[1]
        if not self._dragging and max(abs(dx), abs(dy)) < DRAG_THRESHOLD_PX:
            return
        self._dragging = True
        self.configure(cursor="fleur")
        self._press = (event.x, event.y)
        self.turn(dx, dy)
        self.request(quick=True)

    def turn(self, dx: float, dy: float) -> None:
        """Turn the view as if dragged by (dx, dy) pixels."""
        if self.kind == "globe":
            self.lon = (self.lon - dx * DEGREES_PER_PIXEL + 180) % 360 - 180
            self.lat = max(-90.0, min(90.0, self.lat + dy * DEGREES_PER_PIXEL))
        else:
            turn = -dx if self.kind == "north-polar" else dx
            self.lon = (self.lon + turn * DEGREES_PER_PIXEL + 180) % 360 - 180
        self._notify()

    def _release(self, event: tk.Event[tk.Misc]) -> None:
        dragged = self._dragging
        self._press, self._dragging = None, False
        self.configure(cursor="")
        if dragged:
            self.request()
        elif self._on_click is not None:
            position = self.to_lonlat(event.x, event.y)
            if position is not None:
                self._on_click(position, event)

    def _notify(self) -> None:
        if self._on_view_changed is not None:
            self._on_view_changed()
