# pyright: reportUnknownMemberType=false
"""Viewer window for regional planet detail (experimental M6)."""

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from uuid import uuid4

import numpy as np
from PIL import ImageTk

from dmtools.terrain.adapters.planet_region import window_image
from dmtools.terrain.application.planet_region import RegionRun


class RegionViewer(tk.Toplevel):
    """Shows one regional window with layer choice, hover readout and export."""

    def __init__(
        self, parent: tk.Misc, run: RegionRun, export: Callable[[RegionRun, Path], None]
    ) -> None:
        super().__init__(parent)
        self.run = run
        self._export = export
        lon, lat = run.window.centre
        self.title(
            f"Regional detail · {abs(lat):.2f}°{'N' if lat >= 0 else 'S'} "
            f"{abs(lon):.2f}°{'E' if lon >= 0 else 'W'} · "
            f"{run.window.radius_m / 1000:,.0f} km radius (experimental)"
        )
        self.layer = tk.StringVar(
            self, value="Atlas" if run.window.vegetation_rgb is not None else "Relief"
        )
        self.readout = tk.StringVar(
            self,
            value=f"{len(run.window.tiles)} blended tiles · {run.settings.spacing_km:g} km "
            "detail spacing. Hover for height.",
        )
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        choices = ("Atlas", "Relief") if run.window.vegetation_rgb is not None else ("Relief",)
        self.layer_input = ttk.Combobox(
            bar, textvariable=self.layer, values=choices, state="readonly", width=10
        )
        self.layer_input.pack(side="left")
        self.layer_input.bind("<<ComboboxSelected>>", lambda _e: self._render())
        ttk.Button(bar, text="Export region…", command=self.choose_export).pack(
            side="left", padx=8
        )
        ttk.Label(bar, textvariable=self.readout).pack(side="left", padx=8)
        size = run.window.pixels
        self.canvas = tk.Canvas(self, width=size, height=size, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Motion>", self._motion)
        self._photo: ImageTk.PhotoImage | None = None
        self._render()

    def _render(self) -> None:
        image = window_image(self.run.window, atlas=self.layer.get() == "Atlas")
        self._photo = ImageTk.PhotoImage(image, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    def _motion(self, event: tk.Event[tk.Misc]) -> None:
        window = self.run.window
        row, column = int(event.y), int(event.x)
        if not (0 <= row < window.pixels and 0 <= column < window.pixels):
            return
        value = float(window.elevation_m[row, column])
        if not np.isfinite(value):
            self.readout.set("Outside the region")
            return
        x = (column + 0.5) * window.pixel_m - window.radius_m
        y = window.radius_m - (row + 0.5) * window.pixel_m
        where = f"{x / 1000:+,.0f} km E · {y / 1000:+,.0f} km N of centre"
        self.readout.set(
            f"{where} · {'ground' if window.land[row, column] else 'sea floor'} {value:,.0f} m"
        )

    def choose_export(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self, title="Create a new region folder", initialfile="region-" + uuid4().hex[:8]
        )
        if selected:
            self._export(self.run, Path(selected))
