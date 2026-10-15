# pyright: reportUnknownMemberType=false
"""The World workspace's Wonders step: wonders placed by hand, in their own document.

Like the Geology step, the editor is a sidebar page (this frame) plus its own map
(``self.map``), which the workspace shows while the step is open. The map shows the
source drawing or, once a planet exists, any of its maps under the wonders. Edits
are checked at once; opening and saving run on the workspace's job runner. The
planet adds the wonders after erosion and climate (ADR-0097); the workspace applies
them to a generated planet. Each kind's settings come from the catalog (ADR-0098).
"""

from __future__ import annotations

import math
import random
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Literal
from uuid import uuid4

from PIL import Image

from map_maker.terrain.adapters.map_views import THEME_BY_LABEL, THEMES
from map_maker.terrain.adapters.world_render import OCEAN, render_world_source
from map_maker.terrain.adapters.world_wonders import WONDERS_EXTENSION, wonders_file_hash
from map_maker.terrain.application.world_wonders import WonderFile, open_wonders, save_wonders
from map_maker.terrain.domain.models import Point2D
from map_maker.terrain.domain.seeds import MAX_MASTER_SEED
from map_maker.terrain.domain.wonders import WONDER_KINDS, WONDERS, WonderKind
from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_wonders import (
    WorldWonder,
    WorldWonders,
    blank_wonders,
    follow_world,
)
from map_maker.terrain.map_canvas import FlatMapCanvas, ImagePyramid, Rect
from map_maker.terrain.map_probes import PlanetProbe
from map_maker.terrain.pipeline.control import CancellationToken
from map_maker.terrain.pipeline.world import WorldMap
from map_maker.terrain.ui_components import (
    MapInfoStrip,
    WrappingLabel,
    button_row,
    field,
    hint,
    section,
)
from map_maker.terrain.ui_jobs import JobRunner, Report
from map_maker.terrain.ui_style import GAP, MAP_FRAME, MAP_HIGHLIGHT, MAP_TEXT
from map_maker.terrain.viewport import MapViewport

KIND_BY_LABEL: dict[str, WonderKind] = {WONDERS[kind].label: kind for kind in WONDER_KINDS}
HINT = "Drag to pan · wheel to zoom · F fits · click a wonder's name in the list to select it"
SOURCE_LAYER = "Source map"
RELIEF_LAYER = "Planet relief"
SOURCE_LEGEND = "Your source map. Wonders are drawn to scale; the selected one is bright."
FILETYPES = [("Wonders", f"*{WONDERS_EXTENSION}")]


def new_seed() -> int:
    """A fresh seed for a wonder's shape."""
    return random.randint(0, MAX_MASTER_SEED)


def draw_wonders(
    canvas: FlatMapCanvas,
    frame: WorldFrame,
    rect: Rect,
    wonders: tuple[WorldWonder, ...],
    selected: str | None,
) -> None:
    """Wonders to scale on a flat world map whose frame fills ``rect``.

    Volcanoes are cones, a tepui a block, other round wonders rings, a chasm a
    broad line and a cliff an escarpment symbol, across the seam where that is
    shorter.
    """
    left, top, right, bottom = rect
    sx, sy = (right - left) / frame.width, (bottom - top) / frame.height

    def at(x: float, y: float) -> tuple[float, float]:
        return left + (x - frame.bounds[0]) * sx, top + (y - frame.bounds[1]) * sy

    px_per_km = (right - left) / (2 * math.pi * frame.radius_km)
    for w in wonders:
        x, y = at(*w.position)
        r = max(5.0, w.effective_size_km / 2 * px_per_km)
        colour = MAP_HIGHLIGHT if w.id == selected else MAP_TEXT
        if w.end is not None:
            ex, ey = at(
                w.end[0] + round((w.position[0] - w.end[0]) / frame.width) * frame.width,
                w.end[1],
            )
            if w.kind == "cliff":
                draw_scarp(canvas, (x, y), (ex, ey), colour)
                r = 5.0
            else:
                canvas.create_line(
                    x, y, ex, ey, fill=colour, width=max(3.0, 2 * r), capstyle="round",
                    stipple="gray50",
                )
                canvas.create_line(x, y, ex, ey, fill=colour, width=2)
            # Label a line wonder beyond its right-hand end, clear of the line.
            x, y = max((x, y), (ex, ey))
        elif w.kind in ("titan", "shattered", "active"):
            # Volcanoes: a cone, dashed where it blew apart, with a vent if erupting.
            canvas.create_polygon(
                x, y - r, x - r, y + r * 0.7, x + r, y + r * 0.7,
                outline=colour, fill="", width=2,
                dash=(4, 3) if w.kind == "shattered" else (),
            )
            if w.kind == "active":
                canvas.create_oval(x - 3, y - r - 3, x + 3, y - r + 3, fill=colour, outline="")
        elif w.kind == "oasis":
            canvas.create_oval(x - r, y - r, x + r, y + r, outline=colour, width=2)
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=colour, outline="")
        elif w.kind == "fork":
            # A river dividing in two.
            r = 7.0
            canvas.create_line(x, y + r, x, y, fill=colour, width=3)
            canvas.create_line(x, y, x - r, y - r, fill=colour, width=3)
            canvas.create_line(x, y, x + r, y - r, fill=colour, width=3)
        elif w.kind == "tepui":
            canvas.create_rectangle(x - r, y - 0.7 * r, x + r, y + 0.7 * r, outline=colour,
                                    width=2)
        else:
            canvas.create_oval(x - r, y - r, x + r, y + r, outline=colour, width=2)
        canvas.create_text(x + r + 4, y, text=w.name, fill=colour, anchor="w")


def draw_scarp(
    canvas: FlatMapCanvas, start: tuple[float, float], end: tuple[float, float], colour: str
) -> None:
    """The map symbol of an escarpment: its edge with ticks down the low side.

    The high side lies to the left going from ``start`` to ``end`` (north up).
    """
    (x, y), (ex, ey) = start, end
    canvas.create_line(x, y, ex, ey, fill=colour, width=3)
    length = math.hypot(ex - x, ey - y)
    if length < 1:
        return
    dx, dy = (ex - x) / length, (ey - y) / length
    for k in range(1, int(length // 10) + 1):
        px, py = x + dx * 10 * k, y + dy * 10 * k
        canvas.create_line(px, py, px - dy * 7, py + dx * 7, fill=colour, width=2)


class WonderEditor(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        map_parent: tk.Misc,
        world: WorldMap,
        *,
        jobs: JobRunner,
        status: tk.StringVar,
        on_change: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.world = world
        self.jobs = jobs
        self.status = status
        self.on_change = on_change
        self.file: WonderFile | None = None
        self.wonders = blank_wonders(world.project)
        self._saved: WorldWonders | None = None
        self._undo: list[WorldWonders] = []
        self._redo: list[WorldWonders] = []
        self._controls: list[tuple[ttk.Widget, str]] = []
        self.selected: str | None = None
        self._placing = False
        self._line_start: Point2D | None = None  # a line wonder's first click
        self._closed = False
        self.values = {
            "name": tk.StringVar(self),
            "kind": tk.StringVar(self, value=WONDERS["crater"].label),
            "size": tk.StringVar(self),
            "age": tk.StringVar(self),
        }
        # The chosen kind's settings (``WonderSpec.options``); blank is automatic.
        self.option_values: dict[str, tk.StringVar] = {}
        self._option_inputs: list[ttk.Entry] = []
        self.help = tk.StringVar(self)
        self.file_label = tk.StringVar(self)
        self.layer = tk.StringVar(self, value=SOURCE_LAYER)
        self._layer_chosen = False
        self._previews: dict[str, Image.Image] = {}
        self._pyramids: dict[str, ImagePyramid] = {}
        self.probe: PlanetProbe | None = None
        self.legend = tk.StringVar(self, value=SOURCE_LEGEND)
        self.inspection = tk.StringVar(self, value=HINT)
        self._build()
        self.map = self._build_map(map_parent)
        self.values["kind"].trace_add("write", self._describe)
        self._describe()
        self._populate()
        self._show_file()
        self.canvas.bind("<Escape>", lambda _e: self._key(self.cancel_placing))
        self.canvas.bind("f", lambda _e: self._key(self.fit))

    @staticmethod
    def _key(action: Callable[[], None]) -> str:
        action()
        return "break"

    @property
    def busy(self) -> bool:
        return self.jobs.busy

    @property
    def editing(self) -> bool:
        """A wonder is being placed on the map."""
        return self._placing

    @property
    def dirty(self) -> bool:
        changed = (
            bool(self.wonders.wonders) if self._saved is None else self.wonders != self._saved
        )
        return changed or self.editing

    def summary(self) -> str:
        """One line for the step list."""
        count = len(self.wonders.wonders)
        text = f"{count} wonder{'s' * (count != 1)}"
        return text + (" · unsaved" if self.dirty else "")

    def _button(
        self, parent: tk.Misc, text: str, command: Callable[[], None], *, style: str = "Quiet"
    ) -> ttk.Button:
        width: int | Literal[""] = len(text) + 2 if style == "Small" else ""
        button = ttk.Button(parent, text=text, command=command, style=f"{style}.TButton",
                            width=width)
        self._controls.append((button, "normal"))
        return button

    # Layout

    def _build(self) -> None:
        files = button_row(self, pady=(0, 0))
        WrappingLabel(files, textvariable=self.file_label, style="Body.TLabel").pack(fill="x")
        row = button_row(self, pady=(GAP // 2, 0))
        for text, command in (
            ("Open…", self.choose_open),
            ("Save", self.save),
            ("Save As…", lambda: self.save(save_as=True)),
        ):
            self._button(row, text, command, style="Small").pack(side="left", padx=(0, 4))
        placed = section(self, "Placed wonders")
        self.tree = ttk.Treeview(placed, show="tree", selectmode="browse", height=7)
        self.tree.column("#0", width=260)
        self.tree.pack(fill="x", pady=(GAP // 2, 0))
        self.tree.bind("<<TreeviewSelect>>", self._selection)
        history = button_row(placed, pady=(GAP // 2, 0))
        for text, command in (("Undo", self.undo), ("Redo", self.redo)):
            self._button(history, text, command, style="Small").pack(side="left", padx=(0, 4))
        self._build_form()

    def _build_form(self) -> None:
        box = section(self, "Wonder")
        grid = ttk.Frame(box, style="Panel.TFrame")
        grid.pack(fill="x", pady=(GAP // 2, 0))
        grid.columnconfigure(1, weight=1)
        kind = ttk.Combobox(
            grid, textvariable=self.values["kind"], values=tuple(KIND_BY_LABEL),
            state="readonly", width=20,
        )
        ttk.Label(grid, text="Kind", style="Body.TLabel").grid(row=0, column=0, sticky="w")
        kind.grid(row=0, column=1, sticky="w", pady=2)
        name = ttk.Entry(grid, textvariable=self.values["name"], width=22)
        ttk.Label(grid, text="Name", style="Body.TLabel").grid(row=1, column=0, sticky="w")
        name.grid(row=1, column=1, sticky="w", pady=2)
        size = ttk.Entry(grid, textvariable=self.values["size"], width=8)
        ttk.Label(grid, text="Size", style="Body.TLabel").grid(row=2, column=0, sticky="w")
        size.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(grid, text="km", style="Body.TLabel").grid(row=2, column=1, padx=(70, 0),
                                                              sticky="w")
        age = ttk.Entry(grid, textvariable=self.values["age"], width=8)
        ttk.Label(grid, text="Age", style="Body.TLabel").grid(row=3, column=0, sticky="w",
                                                               padx=(0, GAP))
        age.grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(grid, text="million years", style="Body.TLabel").grid(
            row=3, column=1, padx=(70, 0), sticky="w"
        )
        self._controls.extend(
            ((name, "normal"), (kind, "readonly"), (size, "normal"), (age, "normal"))
        )
        hint(box, textvariable=self.help)
        self.settings_box = ttk.Frame(box, style="Panel.TFrame")
        self.settings_box.pack(fill="x")
        buttons = button_row(box)
        buttons.columnconfigure((0, 1), weight=1, uniform="actions")
        for index, (text, action) in enumerate((
            ("Place on map", self.place),
            ("Update", self.update_selected),
            ("New shape", self.new_shape),
            ("Delete", self.delete),
        )):
            self._button(buttons, text, action).grid(
                row=index // 2, column=index % 2, sticky="ew",
                padx=(0, 3) if index % 2 == 0 else (3, 0), pady=(0, 4),
            )

    def _build_map(self, parent: tk.Misc) -> ttk.Frame:
        frame_widget = ttk.Frame(parent, style="Panel.TFrame")
        frame_widget.columnconfigure(0, weight=1)
        frame_widget.rowconfigure(1, weight=1)
        tools = ttk.Frame(frame_widget, style="Toolbar.TFrame", padding=GAP)
        tools.grid(row=0, column=0, sticky="ew")
        ttk.Label(tools, text="Wonders", style="Section.TLabel").pack(side="left")
        self.layer_input = ttk.Combobox(
            tools, textvariable=self.layer, values=(SOURCE_LAYER,), state="readonly", width=24
        )
        self.layer_input.pack(side="left", padx=GAP)
        self.layer_input.bind("<<ComboboxSelected>>", lambda _e: self._layer_picked())
        ttk.Button(tools, text="Fit", style="Small.TButton", command=self.fit).pack(side="right")
        frame = self.world.project.frame
        self.canvas = FlatMapCanvas(
            frame_widget, background=OCEAN, on_click=self._click, on_hover=self._hover
        )
        self.canvas.configure(takefocus=True)
        self.canvas.overlay = self._overlay
        self.canvas.show(self._render, (frame.width, frame.height))
        self.canvas.grid(row=1, column=0, sticky="nsew")
        MapInfoStrip(frame_widget, self.legend, self.inspection).grid(
            row=2, column=0, sticky="ew"
        )
        return frame_widget

    # Form and list

    def _kind(self) -> WonderKind:
        return KIND_BY_LABEL[self.values["kind"].get()]

    def _describe(self, *_args: str) -> None:
        self._build_settings()
        spec = WONDERS[self._kind()]
        if spec.size_km is None:
            size = " It has no size."
        else:
            low, high, usual = spec.size_km
            size = f" Size is its {spec.size}, {low:g}-{high:g} km; blank uses {usual:g} km."
        clicks = " Place it with two clicks, one per end." if spec.line else ""
        age = (
            " Age erodes it; blank uses the age chosen under Wonders in the Generate step."
            if spec.ages else " It does not age."
        )
        self.help.set(f"{spec.summary}{size}{clicks}{age} Placed wonders replace random "
                      "ones of their kind.")

    def _build_settings(self) -> None:
        """Fields for the chosen kind's settings, made from the catalog."""
        for child in self.settings_box.winfo_children():
            child.destroy()
        self.option_values = {}
        self._option_inputs = []
        options = WONDERS[self._kind()].options
        if not options:
            return
        ttk.Label(self.settings_box, text="Settings · blank is automatic",
                  style="Body.TLabel").pack(anchor="w", pady=(GAP, 0))
        for option in options:
            variable = tk.StringVar(self)
            entry = field(self.settings_box, option.label, variable, unit=option.unit,
                          help=option.help, width=10)
            self.option_values[option.key] = variable
            self._option_inputs.append(entry)
            if self.busy:
                entry.configure(state="disabled")

    def _fixed_settings(self) -> tuple[tuple[str, float], ...]:
        """The settings the form fixes, sorted by name."""
        fixed: list[tuple[str, float]] = []
        spec = WONDERS[self._kind()]
        for key, variable in sorted(self.option_values.items()):
            text = variable.get().strip()
            if not text:
                continue
            try:
                fixed.append((key, float(text)))
            except ValueError as error:
                option = spec.option(key)
                label = key if option is None else option.label
                raise ValueError(f"{label} must be a number, or blank.") from error
        return tuple(fixed)

    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for w in sorted(self.wonders.wonders, key=lambda w: w.name):
            size = "" if WONDERS[w.kind].size_km is None else f" {w.effective_size_km:,.4g} km"
            self.tree.insert("", "end", iid=w.id, text=f"{w.name} · {WONDERS[w.kind].label}{size}")
        if self.selected and self.tree.exists(self.selected):
            self.tree.selection_set(self.selected)
            self.tree.see(self.selected)
        else:
            self.selected = None

    def _selection(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        chosen = self.tree.selection()
        wonder = next((w for w in self.wonders.wonders if chosen and w.id == chosen[0]), None)
        if wonder is None or wonder.id == self.selected:
            return
        self.selected = wonder.id
        self.values["name"].set(wonder.name)
        self.values["kind"].set(WONDERS[wonder.kind].label)
        self.values["size"].set("" if wonder.size_km is None else f"{wonder.size_km:g}")
        self.values["age"].set("" if wonder.age_myr is None else f"{wonder.age_myr:g}")
        for key, variable in self.option_values.items():
            value = wonder.option(key)
            variable.set("" if value is None else f"{value:g}")
        self.canvas.redraw()

    def _age(self) -> float | None:
        text = self.values["age"].get().strip()
        try:
            return float(text) if text else None
        except ValueError as error:
            raise ValueError("Age must be a number of million years, or blank.") from error

    def _size(self) -> float | None:
        text = self.values["size"].get().strip()
        try:
            return float(text) if text else None
        except ValueError as error:
            raise ValueError("Size must be a number of km, or blank.") from error

    def _wonder_name(self, kind: WonderKind, keep: str | None = None) -> str:
        name = self.values["name"].get().strip()
        if name:
            return name
        names = {w.name for w in self.wonders.wonders if w.id != keep}
        label = WONDERS[kind].label
        return next(f"{label} {n}" for n in range(1, 1000) if f"{label} {n}" not in names)

    def _current(self) -> WorldWonder | None:
        return next((w for w in self.wonders.wonders if w.id == self.selected), None)

    # Editing

    def _commit(self, wonders: tuple[WorldWonder, ...], selected: str | None, done: str) -> None:
        try:
            candidate = WorldWonders(self.wonders.world, wonders)
        except ValueError as error:
            self.status.set(str(error))
            return
        self._undo.append(self.wonders)
        self._undo = self._undo[-20:]
        self._redo.clear()
        self.wonders, self.selected = candidate, selected
        self._refresh(done)

    def _refresh(self, message: str) -> None:
        self._populate()
        self._show_file()
        self.status.set(message)
        self.canvas.redraw()
        self.on_change()

    def place(self) -> None:
        if self.busy:
            return
        self._placing = True
        self._line_start = None
        self.canvas.configure(cursor="crosshair")
        self.canvas.focus_set()
        spec = WONDERS[self._kind()]
        self.status.set(
            f"Click one end of the {spec.label.lower()} on the map." if spec.line
            else f"Click the map to place the {spec.label.lower()}."
        )
        self.on_change()

    def cancel_placing(self) -> None:
        if self._placing:
            self._end_placing()
            self.status.set("Placing cancelled.")
            self.on_change()

    def _end_placing(self) -> None:
        self._placing = False
        self._line_start = None
        self.canvas.configure(cursor="")
        self.canvas.redraw()

    def place_at(self, position: Point2D) -> None:
        """Place the form's wonder at ``position`` (a line wonder needs two calls)."""
        kind = self._kind()
        if WONDERS[kind].line and self._line_start is None:
            self._line_start = position
            self.status.set(f"Click the other end of the {WONDERS[kind].label.lower()}.")
            self.canvas.redraw()
            return
        start = self._line_start
        self._end_placing()
        try:
            wonder = WorldWonder(
                "wonder-" + uuid4().hex, self._wonder_name(kind), kind,
                position if start is None else start, new_seed(), self._size(),
                None if start is None else position, self._age(), self._fixed_settings(),
            )
        except ValueError as error:
            self.status.set(str(error))
            self.on_change()
            return
        self.values["name"].set("")
        self._commit((*self.wonders.wonders, wonder), wonder.id, f"Placed {wonder.name}.")

    def update_selected(self) -> None:
        current = self._current()
        if self.busy or current is None:
            self.status.set("Select a wonder to update.")
            return
        try:
            kind = self._kind()
            updated = WorldWonder(
                current.id, self._wonder_name(kind, current.id), kind, current.position,
                current.seed, self._size(), current.end if WONDERS[kind].line else None,
                self._age(), self._fixed_settings(),
            )
        except ValueError as error:
            self.status.set(str(error))
            return
        self._commit(
            tuple(updated if w.id == current.id else w for w in self.wonders.wonders),
            current.id, f"Updated {updated.name}.",
        )

    def new_shape(self) -> None:
        """Draw the selected wonder again from a new seed, keeping everything else."""
        current = self._current()
        if self.busy or current is None:
            self.status.set("Select a wonder to give it a new shape.")
            return
        changed = WorldWonder(
            current.id, current.name, current.kind, current.position, new_seed(),
            current.size_km, current.end, current.age_myr, current.options,
        )
        self._commit(
            tuple(changed if w.id == current.id else w for w in self.wonders.wonders),
            current.id, f"{current.name} will take a new shape.",
        )

    def delete(self) -> None:
        current = self._current()
        if self.busy or current is None:
            self.status.set("Select a wonder to delete.")
            return
        self._commit(
            tuple(w for w in self.wonders.wonders if w.id != current.id), None,
            f"Deleted {current.name}.",
        )

    def _history(self, undo: bool) -> None:
        source, target = (self._undo, self._redo) if undo else (self._redo, self._undo)
        if self.busy or self._placing or not source:
            return
        target.append(self.wonders)
        self.wonders = source.pop()
        self._refresh("Wonder edit undone." if undo else "Wonder edit restored.")

    def undo(self) -> None:
        self._history(True)

    def redo(self) -> None:
        self._history(False)

    # The world it belongs to

    def follow(self, world: WorldMap) -> None:
        """Carry the wonders over to an edited version of their world (same source map)."""
        try:
            moved = follow_world(self.wonders, world.project)
        except ValueError as error:
            self.status.set(
                f"Wonders no longer fit the edited world: {error} Undo the world edit, or "
                "remove the wonders to continue without them."
            )
            return
        self._end_placing()
        self.world = world
        self.wonders = moved
        self._undo.clear()
        self._redo.clear()
        frame = world.project.frame
        self.canvas.show(self._render, (frame.width, frame.height))
        self._refresh("Wonders moved to the edited world; save them to keep it.")

    # Files

    def _show_file(self) -> None:
        if self.file is None:
            self.file_label.set("Not saved yet. Save the wonders to reuse them later.")
        else:
            self.file_label.set(
                f"Wonders: {self.file.path.name}"
                + (" · unsaved changes" if self.dirty else " · saved")
            )

    def _opened(self, opened: WonderFile, verb: str, after: Callable[[], None] | None) -> None:
        self.file = opened
        self._saved = opened.wonders
        if verb == "Opened":
            self.wonders = opened.wonders
            self.selected = None
            self._undo.clear()
            self._redo.clear()
        self._refresh(f"{verb} {opened.path.name}.")
        if after is not None:
            after()

    def choose_open(self) -> None:
        def choose() -> None:
            path = filedialog.askopenfilename(parent=self, title="Open wonders",
                                              filetypes=FILETYPES)
            if path:
                self.load(Path(path))

        self.guard(choose)

    def load(self, path: Path) -> None:
        project = self.world.project

        def work(_report: Report, _token: CancellationToken) -> WonderFile:
            return open_wonders(path, project)

        self.jobs.start("Opening the wonders", work,
                        lambda opened: self._opened(opened, "Opened", None),
                        cancellable=False, failed=self._failed)

    def save(self, *, save_as: bool = False, after: Callable[[], None] | None = None) -> None:
        if self.busy:
            return
        if self._placing:
            self.status.set("Finish or cancel placing the wonder first.")
            return
        path = self.file.path if self.file else None
        expected = self.file.sha256 if self.file else None
        if path is None or save_as:
            name = filedialog.asksaveasfilename(
                parent=self, title="Save the wonders", defaultextension=WONDERS_EXTENSION,
                initialfile=path.name if path else f"world{WONDERS_EXTENSION}",
                filetypes=FILETYPES,
            )
            if not name:
                return
            path = Path(name)
            try:
                # The same path keeps the opened file's fingerprint, even through Save As.
                if self.file is None or path.resolve() != self.file.path.resolve():
                    expected = wonders_file_hash(path)
            except (OSError, ValueError) as error:
                self.status.set(str(error))
                return
        document, target = self.wonders, path

        def work(_report: Report, _token: CancellationToken) -> WonderFile:
            return save_wonders(document, target, expected)

        self.jobs.start("Saving the wonders", work,
                        lambda saved: self._opened(saved, "Saved", after),
                        cancellable=False, failed=self._failed)

    def _failed(self, error: Exception) -> None:
        self.status.set(str(error))

    def guard(self, action: Callable[[], None]) -> None:
        if self.busy:
            self.status.set("Finish or cancel the current job before continuing.")
            return
        if not self.dirty:
            action()
            return
        answer = messagebox.askyesnocancel(
            "Save the wonders?", "Save the placed wonders before continuing?", parent=self
        )
        if answer is True:
            self.save(after=action)
        elif answer is False:
            action()

    def set_busy(self, busy: bool) -> None:
        for widget, normal in (*self._controls, *((e, "normal") for e in self._option_inputs)):
            widget["state"] = "disabled" if busy else normal

    # The map under the wonders

    def set_planet(self, previews: dict[str, Image.Image], probe: PlanetProbe | None) -> None:
        """Offer the generated planet's maps (theme label -> image) as backgrounds."""
        self._previews, self.probe = previews, probe
        self._pyramids = {}
        layers = (SOURCE_LAYER, *(theme.label for theme in THEMES if theme.label in previews))
        self.layer_input.configure(values=layers)
        if self.layer.get() not in layers:
            self.layer.set(SOURCE_LAYER)
        if not self._layer_chosen and self.layer.get() == SOURCE_LAYER and RELIEF_LAYER in layers:
            self.layer.set(RELIEF_LAYER)  # wonders are placed on the relief once there is one
        self._layer_changed()

    def _layer_picked(self) -> None:
        self._layer_chosen = True
        self._layer_changed()

    def _layer_changed(self) -> None:
        layer = self.layer.get()
        theme = THEME_BY_LABEL.get(layer)
        self.legend.set(
            SOURCE_LEGEND if theme is None or layer not in self._previews
            else f"{theme.legend} Wonder symbols are drawn to scale on the planet as it was "
            "last made; apply to see changed wonders in it."
        )
        self.canvas.redraw()

    # Map

    def fit(self) -> None:
        self.canvas.fit()

    def _source_point(self, point: tuple[float, float]) -> Point2D:
        frame = self.world.project.frame
        return (frame.bounds[0] + point[0] * frame.width,
                frame.bounds[1] + point[1] * frame.height)

    def _click(self, point: tuple[float, float], _event: tk.Event[tk.Misc]) -> None:
        if self.busy or not self._placing:
            return
        self.place_at(self._source_point(point))

    def _hover(self, point: tuple[float, float] | None) -> None:
        if point is None:
            self.inspection.set(HINT)
            return
        longitude, latitude = self.world.project.frame.source_to_lonlat(
            self._source_point(point)
        )
        text = f"{latitude:.2f}°, {longitude:.2f}°"
        if self.probe is not None and self.layer.get() in self._previews:
            text += " · " + self.probe.describe(longitude, latitude)
        self.inspection.set(text)

    def _render(self, viewport: MapViewport, size: tuple[int, int]) -> Image.Image:
        project = self.world.project
        frame = project.frame
        layer = self.layer.get()
        if layer in self._previews:
            if layer not in self._pyramids:
                self._pyramids[layer] = ImagePyramid(self._previews[layer])
            return self._pyramids[layer].renderer((frame.width, frame.height), OCEAN)(
                viewport, size
            )
        return render_world_source(
            project.source, frame.bounds, project.assignments, viewport, size,
            show_excluded=False,
        )

    def _overlay(self, canvas: FlatMapCanvas, rect: Rect) -> None:
        frame = self.world.project.frame
        draw_wonders(canvas, frame, rect, self.wonders.wonders, self.selected)
        left, top, right, bottom = rect
        if self._line_start is not None:
            x = left + (self._line_start[0] - frame.bounds[0]) * (right - left) / frame.width
            y = top + (self._line_start[1] - frame.bounds[1]) * (bottom - top) / frame.height
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, outline=MAP_HIGHLIGHT, width=2)
        # Cover off-frame copies without touching the source image.
        width, height = canvas.size()
        for bounds in (
            (0, 0, max(0, left), height),
            (min(width, right), 0, width, height),
            (0, 0, width, max(0, top)),
            (0, min(height, bottom), width, height),
        ):
            canvas.create_rectangle(*bounds, fill=OCEAN, outline="")
        canvas.create_rectangle(left, top, right, bottom, outline=MAP_FRAME)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.map.destroy()
        self.destroy()
