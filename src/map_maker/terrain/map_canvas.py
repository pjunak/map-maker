# pyright: reportUnknownMemberType=false
"""Interactive map canvases: a pan/zoom flat map and a turnable, zoomable globe.

Both are presentation only. They show images they are given (or ask a renderer
for one) and report what is under the cursor in map coordinates; the screens
that use them decide what the map means. ``MapImages`` gives a screen the maps
of a source that draws them on demand, drawing missing ones in the background.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from math import degrees
from typing import Protocol

from PIL import Image, ImageTk

from map_maker.terrain.adapters.map_projection import (
    SPACE,
    MapProjection,
    MapTexture,
    grab,
    lonlat_screen,
    render,
    screen_lonlat,
    view_radius,
    zoomed,
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
    """A rendered globe or polar frame and the view it shows."""

    image: Image.Image
    projection: MapProjection
    size: tuple[int, int]


SPACE_COLOUR = "#{:02x}{:02x}{:02x}".format(*SPACE)  # matches the projected views' surround


class GlobeCanvas(tk.Canvas):
    """A world-frame map shown as a globe or polar view, rendered off the Tk thread.

    Every frame is drawn sharp over the whole canvas (``map_projection.render``).
    Dragging keeps the ground under the cursor under it, north up; the wheel
    zooms a globe towards the cursor and a polar view about its pole; ``fit``
    shows the whole globe or hemisphere again. Clicks and hover report
    longitude and latitude in degrees, and ``overlay`` draws vector marks
    placed with ``to_canvas`` over each frame.
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
        self.zoom = 1.0
        self.polar_span = 90.0
        self.graticule = True
        self.central_meridian_deg = 0.0
        self.image: Image.Image | None = None
        self.placeholder = ""  # shown while there is no image
        self.overlay: Callable[[GlobeCanvas], None] | None = None
        self.frame: GlobeFrame | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self._texture: tuple[Image.Image, float, MapTexture] | None = None
        self._press: Point | None = None
        self._grabbed: Point | None = None  # longitude and latitude held by a drag
        self._dragging = False
        self.bind("<Configure>", lambda _e: self.request())
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._on_hover(None) if self._on_hover else None)
        self.bind("<ButtonPress-1>", self._press_left)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)

    def show(self, image: Image.Image | None, central_meridian_deg: float) -> None:
        self.image, self.central_meridian_deg = image, central_meridian_deg
        self.request()

    def set_kind(self, kind: str) -> None:
        if kind != self.kind:
            self.kind = kind
            self.request()

    def projection(self) -> MapProjection:
        if self.kind == "globe":
            return MapProjection("globe", self.lon, self.lat, zoom=self.zoom)
        sign = 1.0 if self.kind == "north-polar" else -1.0
        return MapProjection(self.kind, self.lon, limit_deg=sign * (90.0 - self.polar_span))

    def set_projection(self, projection: MapProjection) -> None:
        """Show the view ``projection`` describes."""
        self.kind, self.lon = projection.kind, projection.lon_deg
        if projection.kind == "globe":
            self.lat, self.zoom = projection.lat_deg, projection.zoom
        else:
            self.polar_span = projection.polar_span_deg
        self.request()
        self._notify()

    def fit(self) -> None:
        """Show the whole globe, or a polar view out to the equator."""
        self.zoom, self.polar_span = 1.0, 90.0
        self.request()
        self._notify()

    def size(self) -> tuple[int, int]:
        return max(1, self.winfo_width()), max(1, self.winfo_height())

    def request(self) -> None:
        """Ask for a frame of the current view, rendered in the background.

        The worker renders the newest request next, so a burst of requests (a
        drag) costs one frame at a time.
        """
        image = self.image
        if image is None:
            self.delete("all")
            self.photo, self.frame = None, None
            if self.placeholder:
                width, height = self.size()
                self.create_text(width / 2, height / 2, text=self.placeholder,
                                 fill=MAP_TEXT_MUTED, font=FONT_MAP_LABEL[:2])
            return
        size, projection = self.size(), self.projection()
        meridian, graticule = self.central_meridian_deg, self.graticule

        def work() -> GlobeFrame:
            texture = self._texture_of(image, meridian)
            return GlobeFrame(render(texture, projection, size, graticule=graticule),
                              projection, size)

        self._worker.submit(work, self._present)

    def render(self, pixels: int) -> Image.Image:
        """The middle square of the current view, ``pixels`` square (for saving).

        Runs on the calling thread.
        """
        assert self.image is not None
        texture = self._texture_of(self.image, self.central_meridian_deg)
        return render(texture, self.projection(), (pixels, pixels), graticule=self.graticule)

    def _texture_of(self, image: Image.Image, meridian: float) -> MapTexture:
        cached = self._texture
        if cached is not None and cached[0] is image and cached[1] == meridian:
            return cached[2]
        texture = MapTexture.from_image(image, meridian)
        self._texture = (image, meridian, texture)
        return texture

    def _present(self, frame: GlobeFrame) -> None:
        if self.image is None:
            return
        self.frame = frame
        photo = self.photo
        if photo is not None and (photo.width(), photo.height()) == frame.size:
            photo.paste(frame.image)
        else:
            self.photo = ImageTk.PhotoImage(frame.image, master=self)
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw", tags=("map",))
        self.draw_overlay()

    def draw_overlay(self) -> None:
        """Redraw only the vector marks over the current frame (cheap, e.g. on hover)."""
        self.delete("overlay")
        if self.overlay is None or self.frame is None:
            return
        self.overlay(self)
        self.addtag_all("overlay")
        self.dtag("map", "overlay")

    def to_lonlat(self, x: float, y: float) -> Point | None:
        """Longitude/latitude (degrees) under a canvas point of the shown frame."""
        frame = self.frame
        return None if frame is None else screen_lonlat(frame.projection, frame.size, x, y)

    def to_canvas(self, lon: float, lat: float) -> Point | None:
        """Canvas position of a longitude/latitude on the shown frame, or None if hidden."""
        frame = self.frame
        return None if frame is None else lonlat_screen(frame.projection, frame.size, lon, lat)

    # Interaction

    def _motion(self, event: tk.Event[tk.Misc]) -> None:
        if self._on_hover is not None and self._press is None:
            self._on_hover(self.to_lonlat(event.x, event.y))

    def _wheel(self, event: tk.Event[tk.Misc]) -> str:
        self.focus_set()
        if event.delta and self.image is not None:
            factor = WHEEL_STEP if event.delta > 0 else 1 / WHEEL_STEP
            self.set_projection(zoomed(self.projection(), self.size(), factor, event.x, event.y))
        return "break"

    def _press_left(self, event: tk.Event[tk.Misc]) -> None:
        self.focus_set()
        self._press, self._dragging = (event.x, event.y), False
        self._grabbed = screen_lonlat(self.projection(), self.size(), event.x, event.y)

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._press is None:
            return
        dx, dy = event.x - self._press[0], event.y - self._press[1]
        if not self._dragging and max(abs(dx), abs(dy)) < DRAG_THRESHOLD_PX:
            return
        self._dragging = True
        self.configure(cursor="fleur")
        self._press = (event.x, event.y)
        self.drag_to(event.x, event.y, dx, dy)

    def drag_to(self, x: float, y: float, dx: float, dy: float) -> None:
        """Turn the view so the grabbed ground follows the cursor to (x, y).

        Where no north-up view can do that (a pole dragged sideways, or a press
        off the planet) the view turns by the drag (dx, dy) instead and grabs
        the ground now under the cursor.
        """
        size = self.size()
        moved = None if self._grabbed is None else grab(
            self.projection(), size, self._grabbed, x, y
        )
        if moved is None:
            self.turn(dx, dy)
            self._grabbed = screen_lonlat(self.projection(), size, x, y)
        else:
            self.set_projection(moved)

    def turn(self, dx: float, dy: float) -> None:
        """Turn the view as if its centre were dragged by (dx, dy) pixels."""
        step = degrees(1.0 / view_radius(self.projection(), self.size()))
        if self.kind == "globe":
            self.lon = (self.lon - dx * step + 180) % 360 - 180
            self.lat = max(-90.0, min(90.0, self.lat + dy * step))
        else:
            turn = -dx if self.kind == "north-polar" else dx
            self.lon = (self.lon + turn * step + 180) % 360 - 180
        self.request()
        self._notify()

    def _release(self, event: tk.Event[tk.Misc]) -> None:
        dragged = self._dragging
        self._press, self._grabbed, self._dragging = None, None, False
        self.configure(cursor="")
        if not dragged and self._on_click is not None:
            position = self.to_lonlat(event.x, event.y)
            if position is not None:
                self._on_click(position, event)

    def _notify(self) -> None:
        if self._on_view_changed is not None:
            self._on_view_changed()
