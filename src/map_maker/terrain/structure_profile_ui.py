"""Edit a line-owned crest or valley profile before generation."""

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import ttk
from typing import cast

import numpy as np

from map_maker.terrain.domain import StructureProfileKnot, TerrainStructure
from map_maker.terrain.domain.structure_profiles import MAX_PROFILE_KNOTS
from map_maker.terrain.pipeline.profile import shape_preserving_profile


class StructureProfileDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, structure: TerrainStructure, ceiling_m: float) -> None:
        super().__init__(parent)
        self.structure, self.ceiling_m = structure, ceiling_m
        self.result: TerrainStructure | None = None
        self.knots = list(structure.profile)
        self.title(f"{structure.kind.title()} profile")
        self.geometry("620x640")
        self.minsize(540, 570)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        unit = ("Height above sea level" if structure.elevation_mode == "absolute" else
                "Added ridge relief" if structure.kind == "ridge" else "Preferred valley depth")
        self.position = tk.StringVar(value="50")
        self.elevation = tk.StringVar(value=str(structure.elevation_m))
        self.error = tk.StringVar()
        ttk.Label(self, text=f"{unit} (m)", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 6))
        ttk.Label(self, text="Positions follow the smoothed line: 0% is its start, 100% its end.\n"
                  "Profile values replace the base value. Nearby height points stay separate.",
                  wraplength=570).grid(row=1, column=0, sticky="ew", padx=16)
        self.preview = tk.Canvas(self, height=145, background="#fbf8ef", highlightthickness=0)
        self.preview.grid(row=2, column=0, sticky="ew", padx=16, pady=10)
        self.preview.bind("<Configure>", lambda _event: self._draw_preview())
        self.table = ttk.Treeview(self, columns=("position", "height"), show="headings",
                                  selectmode="browse", height=7)
        self.table.heading("position", text="Along line (%)")
        self.table.heading("height", text=f"{unit} (m)")
        self.table.column("position", width=130, stretch=False)
        self.table.column("height", width=350)
        self.table.grid(row=3, column=0, sticky="nsew", padx=16)
        scroll = cast(
            Callable[..., None],
            self.table.yview,  # pyright: ignore[reportUnknownMemberType]
        )
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=scroll)
        scrollbar.grid(row=3, column=1, sticky="ns", padx=(0, 8))
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self._select)
        form = ttk.Frame(self)
        form.grid(row=4, column=0, sticky="ew", padx=16, pady=8)
        ttk.Label(form, text="Position %").grid(row=0, column=0, sticky="w")
        ttk.Label(form, text="Value (m)").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Entry(form, textvariable=self.position, width=12).grid(row=1, column=0)
        ttk.Entry(form, textvariable=self.elevation, width=15).grid(row=1, column=1, padx=8)
        ttk.Button(form, text="Add / replace", command=self._upsert).grid(row=1, column=2)
        ttk.Button(form, text="Remove selected", command=self._remove).grid(
            row=1, column=3, padx=8)
        presets = ttk.Frame(self)
        presets.grid(row=5, column=0, sticky="w", padx=16)
        ttk.Button(presets, text="Flat profile", command=self._flat).pack(side="left")
        if structure.kind == "ridge":
            ttk.Button(presets, text="Two peaks and a pass", command=self._peaks).pack(
                side="left", padx=8)
        ttk.Button(presets, text="Clear profile", command=self._clear).pack(side="left")
        ttk.Label(self, textvariable=self.error, foreground="#a83232", wraplength=570).grid(
            row=6, column=0, sticky="ew", padx=16, pady=(6, 0))
        note = ("Valley direction is upstream to outlet. Absolute floors must not rise downstream."
                if structure.kind == "valley" else
                "Use matching heights where range and spur lines meet.\n"
                "A profile is not a global slope limit.")
        ttk.Label(self, text=note, wraplength=570).grid(
            row=7, column=0, sticky="ew", padx=16, pady=8)
        actions = ttk.Frame(self)
        actions.grid(row=8, column=0, sticky="e", padx=16, pady=(0, 14))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="left", padx=8)
        ttk.Button(actions, text="Apply profile", command=self._apply).pack(side="left")
        self._refresh()

    def _refresh(self) -> None:
        self.table.delete(*self.table.get_children())
        for index, knot in enumerate(self.knots):
            self.table.insert("", "end", iid=str(index),
                              values=(f"{100*knot.position:g}", f"{knot.elevation_m:g}"))
        self._draw_preview()

    def _select(self, _event: tk.Event[tk.Misc]) -> None:
        selected = self.table.selection()
        if selected:
            knot = self.knots[int(selected[0])]
            self.position.set(str(100*knot.position))
            self.elevation.set(str(knot.elevation_m))

    def _upsert(self) -> None:
        try:
            knot = StructureProfileKnot(float(self.position.get())/100, float(self.elevation.get()))
            updated = [k for k in self.knots if k.position != knot.position] + [knot]
            if len(updated) > MAX_PROFILE_KNOTS:
                raise ValueError(f"Use at most {MAX_PROFILE_KNOTS} profile knots.")
            self.knots = sorted(updated, key=lambda k: k.position)
            self.error.set("")
            self._refresh()
        except ValueError as error:
            self.error.set(str(error))

    def _remove(self) -> None:
        selected = self.table.selection()
        if selected:
            self.knots.pop(int(selected[0]))
            self.error.set("")
            self._refresh()

    def _flat(self) -> None:
        self.knots = [StructureProfileKnot(p, self.structure.elevation_m) for p in (0., 1.)]
        self.error.set("")
        self._refresh()

    def _peaks(self) -> None:
        self.knots = [StructureProfileKnot(p, fraction*self.structure.elevation_m)
                      for p, fraction in ((0., .35), (.25, 1.), (.5, .55), (.75, 1.), (1., .35))]
        self.error.set("")
        self._refresh()

    def _clear(self) -> None:
        self.knots = []
        self.error.set("")
        self._refresh()

    def _draw_preview(self) -> None:
        canvas = self.preview
        canvas.delete("all")
        width, height = max(100, canvas.winfo_width()), 145
        margin = 44
        canvas.create_line([margin, 12, margin, height-24, width-16, height-24], fill="#a8b2ad")
        knots = self.knots or [
            StructureProfileKnot(p, self.structure.elevation_m) for p in (0., 1.)]
        scale = max(1., max(k.elevation_m for k in knots))
        canvas.create_text(margin-5, 12, text=f"{scale:g}", anchor="e", fill="#52645f")
        canvas.create_text(margin-5, height-24, text="0", anchor="e", fill="#52645f")
        canvas.create_text(margin, height-10, text="Start", anchor="w", fill="#52645f")
        canvas.create_text(width-16, height-10, text="End", anchor="e", fill="#52645f")
        if len(knots) >= 2:
            x = np.linspace(knots[0].position, knots[-1].position, 161)
            y = shape_preserving_profile(np.array([k.position for k in knots]),
                                        np.array([k.elevation_m for k in knots]), x)
            coords = [value for px, py in zip(x, y, strict=True) for value in
                      (margin+px*(width-margin-16), height-24-py/scale*(height-40))]
            canvas.create_line(*coords, fill="#1d7772", width=2)
        for knot in knots:
            xk = margin+knot.position*(width-margin-16)
            yk = height-24-knot.elevation_m/scale*(height-40)
            canvas.create_oval(xk-3, yk-3, xk+3, yk+3, fill="#b56c42", outline="")

    def _apply(self) -> None:
        try:
            candidate = replace(self.structure, profile=tuple(self.knots))
            if (candidate.elevation_mode == "absolute"
                    and any(k.elevation_m > self.ceiling_m for k in candidate.profile)):
                raise ValueError("Profile height exceeds the terrain elevation ceiling.")
        except ValueError as error:
            self.error.set(str(error))
            return
        self.result = candidate
        self.destroy()


def edit_structure_profile(
    parent: tk.Misc, structure: TerrainStructure, ceiling_m: float,
) -> TerrainStructure | None:
    dialog = StructureProfileDialog(parent, structure, ceiling_m)
    dialog.wait_visibility()
    dialog.grab_set()
    dialog.wait_window()
    return dialog.result
