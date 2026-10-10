# pyright: reportUnknownMemberType=false
"""Globe and polar views of a generated planet: drag to turn, choose a theme."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from uuid import uuid4

from PIL import Image, ImageTk

from dmtools.terrain.adapters.map_projection import (
    PROJECTION_LABELS,
    MapProjection,
    reproject,
)

VIEW_PIXELS = 720
DRAG_PIXELS = 300  # quicker, coarser frames while dragging
DEGREES_PER_PIXEL = 0.35


class GlobeViewer(tk.Toplevel):
    """Shows planet theme images as a turnable globe or polar views, with export."""

    def __init__(
        self, parent: tk.Misc, previews: dict[str, Image.Image], central_meridian_deg: float
    ) -> None:
        super().__init__(parent)
        self.title("World views (globe and polar)")
        self.previews = previews
        self.central_meridian_deg = central_meridian_deg
        self.theme = tk.StringVar(self, value=next(iter(previews)))
        names = {label: kind for kind, label in PROJECTION_LABELS.items()}
        self._kinds = names
        self.projection = tk.StringVar(self, value=PROJECTION_LABELS["globe"])
        self.graticule = tk.BooleanVar(self, value=True)
        self.lon = central_meridian_deg
        self.lat = 20.0
        self.hint = tk.StringVar(self, value="Drag to turn the view.")
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        theme_input = ttk.Combobox(
            bar, textvariable=self.theme, values=tuple(previews), state="readonly", width=20
        )
        theme_input.pack(side="left")
        theme_input.bind("<<ComboboxSelected>>", lambda _e: self.render())
        projection_input = ttk.Combobox(
            bar, textvariable=self.projection,
            values=tuple(PROJECTION_LABELS[k] for k in ("globe", "north-polar", "south-polar")),
            state="readonly", width=12,
        )
        projection_input.pack(side="left", padx=6)
        projection_input.bind("<<ComboboxSelected>>", lambda _e: self.render())
        ttk.Checkbutton(
            bar, text="Grid", variable=self.graticule, command=self.render
        ).pack(side="left")
        ttk.Button(bar, text="Save view…", command=self.choose_export).pack(side="left", padx=8)
        ttk.Label(bar, textvariable=self.hint).pack(side="left", padx=8)
        self.canvas = tk.Canvas(
            self, width=VIEW_PIXELS, height=VIEW_PIXELS, highlightthickness=0, background="black"
        )
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: self.render())
        self._anchor: tuple[int, int] | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self.render()

    def view(self) -> MapProjection:
        kind = self._kinds[self.projection.get()]
        if kind == "globe":
            return MapProjection("globe", self.lon, self.lat)
        return MapProjection(kind, self.lon)

    def image(self, pixels: int) -> Image.Image:
        return reproject(
            self.previews[self.theme.get()], self.view(), pixels,
            central_meridian_deg=self.central_meridian_deg, graticule=self.graticule.get(),
        )

    def render(self, pixels: int = VIEW_PIXELS) -> None:
        image = self.image(pixels)
        if pixels != VIEW_PIXELS:
            image = image.resize((VIEW_PIXELS, VIEW_PIXELS), Image.Resampling.BILINEAR)
        self._photo = ImageTk.PhotoImage(image, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        view = self.view()
        side = "below" if view.kind == "north-polar" else "above"
        self.hint.set(
            f"Centre {view.lat_deg:+.0f}° {view.lon_deg:+.0f}° · drag to turn"
            if view.kind == "globe"
            else f"{view.lon_deg:+.0f}° meridian {side} the pole · drag to turn"
        )

    def _press(self, event: tk.Event[tk.Misc]) -> None:
        self._anchor = (event.x, event.y)

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._anchor is None:
            return
        dx, dy = event.x - self._anchor[0], event.y - self._anchor[1]
        self._anchor = (event.x, event.y)
        kind = self.view().kind
        if kind == "globe":
            self.lon = (self.lon - dx * DEGREES_PER_PIXEL + 180) % 360 - 180
            self.lat = max(-90.0, min(90.0, self.lat + dy * DEGREES_PER_PIXEL))
        else:
            turn = -dx if kind == "north-polar" else dx
            self.lon = (self.lon + turn * DEGREES_PER_PIXEL + 180) % 360 - 180
        self.render(DRAG_PIXELS)

    def choose_export(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self, title="Save this view as an image",
            initialfile=f"view-{uuid4().hex[:8]}.png", defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
        )
        if selected:
            self.export(Path(selected))

    def export(self, destination: Path, pixels: int = 2048) -> None:
        with destination.open("wb") as stream:
            self.image(pixels).save(stream, format="PNG")
        self.hint.set(f"Saved {destination.name}")
