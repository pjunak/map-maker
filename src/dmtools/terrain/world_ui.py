# pyright: reportUnknownMemberType=false
"""World-source workspace: review geography and ownership before generation."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast
from uuid import uuid4

from PIL import Image, ImageTk
from shapely.geometry import Point, Polygon

from dmtools.terrain.adapters.planet_render import PREVIEW_LAYERS
from dmtools.terrain.adapters.world_context_render import (
    CONTEXT_LAYERS,
    ContextLayer,
    render_world_context,
)
from dmtools.terrain.adapters.world_geology import world_fingerprint
from dmtools.terrain.adapters.world_project import WORLD_EXTENSION
from dmtools.terrain.adapters.world_render import OCEAN, render_world_source
from dmtools.terrain.adapters.world_svg import load_world_svg
from dmtools.terrain.application.planet import (
    PlanetRun,
    export_planet,
    generate_planet_run,
    planet_identity,
    user_tile_cache,
)
from dmtools.terrain.application.planet_region import RegionRun, export_region, region_window
from dmtools.terrain.application.world import (
    continent_from_name,
    open_world,
    propose_group_assignments,
    save_world,
)
from dmtools.terrain.application.world_bathymetry import BathymetryFile
from dmtools.terrain.application.world_context import (
    WorldContextRun,
    export_context,
    generate_context,
    open_context,
)
from dmtools.terrain.application.world_geology import GeologyFile
from dmtools.terrain.application.world_terrain import (
    WorldTerrainCreated,
    create_world_terrain_project,
)
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.domain.world import (
    WorldAssignment,
    WorldContinent,
    WorldFrame,
    WorldGeometryError,
    WorldProject,
    WorldRole,
    WorldSource,
)
from dmtools.terrain.domain.world_context import (
    EXPOSURE_BEARINGS,
    WorldContextSettings,
    exposure_range_km,
    exposure_steps,
)
from dmtools.terrain.pipeline.control import CancellationToken, GenerationCancelled
from dmtools.terrain.pipeline.planet_regional import RegionalParent
from dmtools.terrain.pipeline.world import WorldMap, prepare_world_map
from dmtools.terrain.planet_ui import PlanetPanel, PlanetProbe
from dmtools.terrain.region_ui import RegionViewer
from dmtools.terrain.viewport import MapViewport
from dmtools.terrain.world_bathymetry_ui import BathymetryEditor
from dmtools.terrain.world_geology_ui import GeologyEditor
from dmtools.terrain.world_terrain_ui import WorldTerrainPanel


@dataclass(frozen=True)
class _GeologyReady:
    world: WorldMap


@dataclass(frozen=True)
class _Opened:
    world: WorldMap
    path: Path


@dataclass(frozen=True)
class _Saved:
    world: WorldMap
    path: Path


@dataclass(frozen=True)
class _ContextReady:
    run: WorldContextRun
    signature: object
    rows: int


@dataclass(frozen=True)
class _ContextOpened:
    run: WorldContextRun
    path: Path
    signature: object


@dataclass(frozen=True)
class _ContextExported:
    path: Path


@dataclass(frozen=True)
class _TerrainReady:
    created: WorldTerrainCreated
    signature: object


@dataclass(frozen=True)
class _Progress:
    message: str


@dataclass(frozen=True)
class _PlanetReady:
    run: PlanetRun
    signature: object


@dataclass(frozen=True)
class _PlanetExported:
    path: Path


@dataclass(frozen=True)
class _RegionReady:
    run: RegionRun


@dataclass(frozen=True)
class _RegionExported:
    path: Path


def frame_view(
    image: Image.Image,
    rect: tuple[float, float, float, float],
    size: tuple[int, int],
    background: str,
) -> Image.Image:
    """Place a world-frame image into the canvas rectangle of the current viewport."""
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
    resample = Image.Resampling.BILINEAR if sx < 1 else Image.Resampling.LANCZOS
    canvas.paste(crop.resize((int(x1 - x0), int(y1 - y0)), resample), (int(x0), int(y0)))
    return canvas


type _Event = (
    WorldSource
    | WorldMap
    | _Opened
    | _GeologyReady
    | _Saved
    | _ContextReady
    | _ContextOpened
    | _ContextExported
    | _TerrainReady
    | _PlanetReady
    | _PlanetExported
    | _RegionReady
    | _RegionExported
    | _Progress
    | Exception
)
type _Ownership = tuple[tuple[WorldContinent, ...], tuple[WorldAssignment, ...]]


class WorldWorkspace(ttk.Frame):
    def __init__(
        self, parent: tk.Misc, on_change: Callable[[], None],
        on_terrain_ready: Callable[[WorldTerrainCreated], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Paper.TFrame", padding=(18, 12))
        self.on_change = on_change
        self.on_terrain_ready = on_terrain_ready
        self._scheduler = self.winfo_toplevel()
        self.source: WorldSource | None = None
        self.path: Path | None = None
        self.validated: WorldMap | None = None
        self.geology_editor: GeologyEditor | None = None
        self._geology_file: GeologyFile | None = None
        self.bathymetry_editor: BathymetryEditor | None = None
        self._bathymetry_file: BathymetryFile | None = None
        self.context_run: WorldContextRun | None = None
        self.planet_run: PlanetRun | None = None
        self._planet_probe: PlanetProbe | None = None
        self.region_viewers: list[RegionViewer] = []
        self.region_workers: int | None = None
        self._context_cancellation: CancellationToken | None = None
        self.continents: tuple[WorldContinent, ...] = ()
        self.assignments: tuple[WorldAssignment, ...] = ()
        self._undo: list[_Ownership] = []
        self._redo: list[_Ownership] = []
        self._saved_signature: object = None
        self._loading = False
        self.busy = False
        self._closed = False
        self._events: queue.Queue[_Event] = queue.Queue()
        self._after_save: Callable[[], None] | None = None
        self._poll_id: str | None = None
        self._draw_id: str | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self.viewport = MapViewport()
        self._pan: tuple[float, float] | None = None
        self._controls: list[tuple[ttk.Widget, str]] = []
        self.values = {
            key: tk.StringVar(self, value=value)
            for key, value in (
                ("name", "Untitled world"),
                ("radius", ""),
                ("meridian", "0"),
                ("x", "0"),
                ("y", "0"),
                ("width", "360"),
                ("height", "180"),
            )
        }
        self.owner = tk.StringVar(self)
        self.role = tk.StringVar(self, value="Mainland")
        self.status = tk.StringVar(self, value="Import an SVG world map, or open a saved world.")
        self.summary = tk.StringVar(
            self,
            value="Your source map stays intact. Assign each shape "
            "to a continent or exclude it, then confirm the world frame.",
        )
        self.inspection = tk.StringVar(
            self, value="Wheel: zoom  ·  Middle/right drag: pan  ·  F: fit"
        )
        self.show_excluded = tk.BooleanVar(self, value=True)
        self.context_rows = tk.StringVar(self, value="180")
        self.display_layer = tk.StringVar(self, value="Source")
        self.exposure_bearing = tk.StringVar(self, value="N")
        self.context_legend = tk.StringVar(self)
        self.context_detail = tk.StringVar(
            self, value="Generate geographic context from the current world."
        )
        self.viewer_note = tk.StringVar(self, value="Source geography · context available")
        self._build()
        self.context_rows.trace_add("write", self._context_settings_changed)
        for value in self.values.values():
            value.trace_add("write", self._changed)
        self._poll_id = self._scheduler.after(80, self._poll)

    @property
    def dirty(self) -> bool:
        return self.source is not None and self._signature() != self._saved_signature

    def _signature(self) -> object:
        return (
            self.source.sha256 if self.source else None,
            tuple((k, v.get()) for k, v in self.values.items()),
            self.continents,
            self.assignments,
        )

    def _button(
        self, parent: tk.Misc, label: str, action: Callable[[], object], *, accent: bool = False
    ) -> ttk.Button:
        button = ttk.Button(
            parent,
            text=label,
            command=action,
            style="Accent.TButton" if accent else "Quiet.TButton",
        )
        self._controls.append((button, "normal"))
        return button

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        header = ttk.Frame(self, style="Paper.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(header, text="World map", style="Header.TLabel").pack(side="left")
        for label, action in (
            ("Import SVG…", self.choose_svg),
            ("Open world…", self.choose_world),
            ("Save", self.save),
            ("Save As…", lambda: self.save(save_as=True)),
            ("Geology…", self.edit_geology),
            ("Bathymetry…", self.edit_bathymetry),
            ("Planet…", self.show_planet),
            ("Terrain…", self.show_terrain),
        ):
            self._button(header, label, action).pack(side="left", padx=(10, 0))
        ttk.Label(
            self,
            text="1  WORLD SOURCE     →     2  CONTEXT     →     3  PLANET"
            "     →     4  REGIONAL TERRAIN",
            style="Eyebrow.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))
        sidebar = ttk.Frame(self, style="Panel.TFrame", padding=12)
        sidebar.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(0, weight=1)
        pages = ttk.Notebook(sidebar, width=390)
        self.pages = pages
        self.terrain_panel = WorldTerrainPanel(
            pages, self.create_terrain, self._open_prepared_terrain, self.cancel_context,
        )
        pages.grid(row=0, column=0, sticky="nsew")
        mapping = ttk.Frame(pages, style="Panel.TFrame", padding=8)
        frame_page = ttk.Frame(pages, style="Panel.TFrame", padding=12)
        pages.add(mapping, text="Continents & shapes")
        pages.add(frame_page, text="World frame")
        mapping.columnconfigure(0, weight=1)
        mapping.rowconfigure(1, weight=1)
        tools = ttk.Frame(mapping, style="Panel.TFrame")
        tools.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self._button(tools, "Suggest from groups", self.suggest_groups).pack(side="left")
        self._button(tools, "Undo", self.undo).pack(side="left", padx=4)
        self._button(tools, "Redo", self.redo).pack(side="left")
        self.tree = ttk.Treeview(mapping, columns=("owner",), selectmode="extended", height=10)
        self.tree.tag_configure("issue", foreground="#a13223")
        self.tree.heading("#0", text="Source shape")
        self.tree.heading("owner", text="Assignment")
        self.tree.column("#0", width=215, minwidth=110, stretch=True)
        self.tree.column("owner", width=120, minwidth=95, stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew")

        def scroll_tree(*args: str) -> None:
            self.tree.yview(*args)

        scrollbar = ttk.Scrollbar(mapping, orient="vertical", command=scroll_tree)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._selection)
        self.detail = ttk.Label(
            mapping,
            text="Select shapes here or click the map.",
            style="Muted.TLabel",
            wraplength=370,
        )
        self.detail.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(mapping, text="Continent name (choose or enter)", style="Body.TLabel").grid(
            row=3, column=0, sticky="w"
        )
        self.owner_input = ttk.Combobox(mapping, textvariable=self.owner)
        self.owner_input.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(3, 6))
        self._controls.append((self.owner_input, "normal"))
        self.role_input = ttk.Combobox(
            mapping,
            textvariable=self.role,
            state="readonly",
            values=("Mainland", "Island", "Exclude"),
        )
        self.role_input.grid(row=5, column=0, columnspan=2, sticky="ew")
        self._controls.append((self.role_input, "readonly"))
        self._button(mapping, "Assign selected shapes", self.assign_selected).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=6
        )
        self._button(mapping, "Rename assigned continent…", self.rename_continent).grid(
            row=7, column=0, columnspan=2, sticky="ew"
        )
        self._button(mapping, "Select all shapes", self.select_all).grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=6
        )
        ttk.Label(frame_page, text="Full-world spherical Plate Carrée", style="Value.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        for row, (key, label) in enumerate(
            (
                ("name", "World name"),
                ("radius", "Planet radius · km"),
                ("meridian", "Central meridian · °"),
                ("x", "Frame left · source units"),
                ("y", "Frame top · source units"),
                ("width", "Frame width · source units"),
                ("height", "Frame height · source units"),
            ),
            start=1,
        ):
            ttk.Label(frame_page, text=label, style="Body.TLabel").grid(
                row=row * 2, column=0, sticky="w", pady=(7, 2)
            )
            entry = ttk.Entry(frame_page, textvariable=self.values[key], width=32)
            entry.grid(row=row * 2 + 1, column=0, sticky="ew")
            self._controls.append((entry, "normal"))
        ttk.Label(
            frame_page,
            text="This frame represents 360° longitude and 180° latitude. "
            "Confirm its bounds from your map's projection; exclude legends and margins. "
            "SVG display size is not planetary scale. Enter your planet's radius.",
            style="Muted.TLabel",
            wraplength=335,
        ).grid(row=17, column=0, sticky="ew", pady=12)
        pages.add(self.terrain_panel, text="Terrain")
        self.adjustments_page = ttk.Frame(pages, style="Panel.TFrame", padding=8)
        pages.add(self.adjustments_page, text="Adjustments")
        self.adjustments_page.columnconfigure(0, weight=1)
        self.adjustments_page.rowconfigure(1, weight=1)
        ttk.Label(
            self.adjustments_page,
            text="Import adjustments",
            style="Value.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.adjustment_tree = ttk.Treeview(
            self.adjustments_page,
            show="tree",
            selectmode="browse",
            height=6,
        )
        self.adjustment_tree.grid(row=1, column=0, sticky="nsew")
        self.adjustment_tree.column("#0", width=330, minwidth=160)

        def scroll_adjustments(*args: str) -> None:
            self.adjustment_tree.yview(*args)

        adjustment_scroll = ttk.Scrollbar(
            self.adjustments_page,
            orient="vertical",
            command=scroll_adjustments,
        )
        adjustment_scroll.grid(row=1, column=1, sticky="ns")
        self.adjustment_tree.configure(yscrollcommand=adjustment_scroll.set)
        self.adjustment_tree.bind("<<TreeviewSelect>>", self._review_adjustment)
        self.adjustment_detail = ttk.Label(
            self.adjustments_page,
            style="Body.TLabel",
            wraplength=335,
            text="Validate the world to inspect export rounding and shared land. "
            "The original SVG and assignments are retained.",
        )
        self.adjustment_detail.grid(row=2, column=0, columnspan=2, sticky="ew", pady=12)
        self.context_page = ttk.Frame(pages, style="Panel.TFrame", padding=10)
        pages.add(self.context_page, text="Context")
        self.planet_panel = PlanetPanel(
            pages, self.generate_planet, self.export_planet, self.cancel_context,
            self.zoom_region,
        )
        pages.add(self.planet_panel, text="Planet")
        self.context_page.columnconfigure(0, weight=1)
        self.context_page.rowconfigure(7, weight=1)
        ttk.Label(self.context_page, text="Geographic context", style="Value.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            self.context_page,
            text="Latitude cells · longitude uses twice as many",
            style="Body.TLabel",
        ).grid(row=1, column=0, sticky="w")
        resolution = ttk.Combobox(
            self.context_page,
            textvariable=self.context_rows,
            values=("90", "180", "360"),
            state="readonly",
        )
        resolution.grid(row=2, column=0, sticky="ew", pady=6)
        self._controls.append((resolution, "readonly"))
        self._button(
            self.context_page, "Generate context", self.generate_context, accent=True
        ).grid(row=3, column=0, sticky="ew", pady=5)
        self._button(self.context_page, "Export context…", self.export_context).grid(
            row=4, column=0, sticky="ew", pady=5
        )
        self._button(self.context_page, "Open context…", self.choose_context).grid(
            row=5, column=0, sticky="ew", pady=5
        )
        self.context_cancel = ttk.Button(
            self.context_page,
            text="Cancel context job",
            command=self.cancel_context,
            state="disabled",
        )
        self.context_cancel.grid(row=6, column=0, sticky="ew", pady=5)
        details = ttk.Frame(self.context_page, style="Panel.TFrame")
        details.grid(row=7, column=0, sticky="nsew", pady=12)
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        style = ttk.Style(self)
        self.context_text = tk.Text(
            details,
            height=4,
            width=1,
            wrap="word",
            state="disabled",
            borderwidth=0,
            highlightthickness=0,
            background=style.lookup("Body.TLabel", "background"),
            foreground=style.lookup("Body.TLabel", "foreground"),
            font=style.lookup("Body.TLabel", "font"),
        )
        self.context_text.grid(row=0, column=0, sticky="nsew")
        details_scroll = ttk.Scrollbar(details, command=self._scroll_context_detail)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.context_text.configure(yscrollcommand=details_scroll.set)
        self.context_detail.trace_add("write", self._context_detail_changed)
        self._context_detail_changed()
        ttk.Label(
            self.context_page,
            textvariable=self.context_legend,
            style="Muted.TLabel",
            wraplength=335,
        ).grid(row=8, column=0, sticky="ew", pady=6)
        self._button(sidebar, "Validate world", self.validate, accent=True).grid(
            row=1, column=0, sticky="ew", pady=(10, 5)
        )
        self.progress = ttk.Progressbar(sidebar, mode="indeterminate")
        self.progress.grid(row=2, column=0, sticky="ew")
        viewer = ttk.Frame(self, style="Panel.TFrame")
        viewer.grid(row=2, column=1, sticky="nsew")
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(viewer, style="Panel.TFrame", padding=6)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Fit world", command=self.fit).pack(side="left")
        self.excluded_toggle = ttk.Checkbutton(
            toolbar,
            text="Excluded shapes",
            variable=self.show_excluded,
            command=self._schedule_draw,
        )
        self.excluded_toggle.pack(side="left", padx=12)
        self.layer_input = ttk.Combobox(
            toolbar,
            textvariable=self.display_layer,
            values=("Source", *CONTEXT_LAYERS, *PREVIEW_LAYERS),
            state="readonly",
            width=20,
        )
        self.layer_input.pack(side="left", padx=4)
        self.layer_input.bind("<<ComboboxSelected>>", self._layer_changed)
        self.bearing_input = ttk.Combobox(
            toolbar,
            textvariable=self.exposure_bearing,
            values=EXPOSURE_BEARINGS,
            state="disabled",
            width=4,
        )
        self.bearing_input.pack(side="left", padx=4)
        self.bearing_input.bind("<<ComboboxSelected>>", self._layer_changed)
        ttk.Label(toolbar, textvariable=self.viewer_note, style="Muted.TLabel").pack(
            side="right", padx=5
        )
        self.canvas = tk.Canvas(viewer, background=OCEAN, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self._schedule_draw())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-1>", self._pick)
        self.canvas.bind("<Motion>", self._motion)
        for button in (2, 3):
            self.canvas.bind(f"<ButtonPress-{button}>", self._pan_start)
            self.canvas.bind(f"<B{button}-Motion>", self._pan_move)
            self.canvas.bind(f"<ButtonRelease-{button}>", self._pan_end)
        ttk.Label(viewer, textvariable=self.inspection, style="Muted.TLabel", padding=6).grid(
            row=2, column=0, sticky="ew"
        )
        ttk.Label(
            viewer, textvariable=self.summary, style="Body.TLabel", padding=10, wraplength=720
        ).grid(row=3, column=0, sticky="ew")
        ttk.Label(self, textvariable=self.status, style="Eyebrow.TLabel", wraplength=1100).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0)
        )

    def _changed(self, *_args: str) -> None:
        if self._loading:
            return
        self.validated = None
        self._clear_context()
        self._clear_planet()
        self.adjustment_tree.delete(*self.adjustment_tree.get_children())
        self.pages.tab(self.adjustments_page, text="Adjustments")
        self.adjustment_detail.configure(text="Validate the world to inspect import adjustments.")
        if self.source:
            remaining = len(self.source.features) - len(self.assignments)
            excluded = sum(a.role == "exclude" for a in self.assignments)
            issues = sum(bool(f.issue) for f in self.source.features)
            self.summary.set(
                f"{len(self.continents)} continents · {remaining} unassigned · "
                f"{excluded} excluded · {issues} import issues. "
                "Review assignments and world frame, then validate."
            )
        self.on_change()
        self._schedule_draw()

    def _frame(self) -> WorldFrame:
        try:
            x, y, w, h = (float(self.values[k].get()) for k in ("x", "y", "width", "height"))
            return WorldFrame(
                (x, y, x + w, y + h),
                float(self.values["radius"].get()),
                float(self.values["meridian"].get()),
            )
        except ValueError as error:
            raise ValueError(
                "Confirm numeric world-frame bounds, central meridian and a positive "
                f"planet radius in the World frame tab. {error}"
            ) from error

    def project(self) -> WorldProject:
        if self.source is None:
            raise ValueError("Import or open a world map first.")
        return WorldProject(
            self.values["name"].get().strip(),
            self.source,
            self._frame(),
            self.continents,
            self.assignments,
        )

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for control, normal in self._controls:
            control["state"] = "disabled" if busy else normal
        self.context_cancel.configure(
            state="normal" if busy and self._context_cancellation is not None else "disabled"
        )
        self.terrain_panel.set_busy(busy, self._context_cancellation is not None)
        self.planet_panel.set_busy(busy, self._context_cancellation is not None)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _work(self, label: str, operation: Callable[[], _Event]) -> None:
        if self.busy:
            return
        self.status.set(label)
        self._set_busy(True)

        def worker() -> None:
            try:
                self._events.put(operation())
            except Exception as error:
                self._events.put(error)

        threading.Thread(target=worker, name="world-source-worker", daemon=True).start()

    def _poll(self) -> None:
        if self._closed:
            return
        self._poll_id = None
        while not self._events.empty():
            event = self._events.get_nowait()
            if isinstance(event, _Progress):
                self.status.set(event.message)
                continue
            self._context_cancellation = None
            self._set_busy(False)
            if isinstance(event, GenerationCancelled):
                self.status.set("World job cancelled. No new completed result was published.")
            elif isinstance(event, _TerrainReady):
                self.terrain_panel.show_created(event.created)
                self.pages.select(self.terrain_panel)
                self.status.set(f"Terrain project saved: {event.created.loaded.path}")
                if event.signature == self._signature():
                    self._open_prepared_terrain(event.created)
                else:
                    self.status.set(
                        f"World inputs changed. Prepared project retained separately: "
                        f"{event.created.loaded.path}"
                    )
            elif isinstance(event, _PlanetReady):
                if event.signature != self._signature():
                    self.status.set("World inputs changed; generate the planet again.")
                    continue
                self.planet_run = event.run
                self._planet_probe = PlanetProbe(event.run.result)
                self.planet_panel.show(event.run)
                self.pages.select(self.planet_panel)
                self.display_layer.set(
                    "Planet atlas" if "Planet atlas" in event.run.previews else "Planet relief"
                )
                self._layer_changed()
                self.status.set(
                    "Planet ready. Inspect the layers; export to keep a reproducible build."
                )
            elif isinstance(event, _RegionReady):
                viewer = RegionViewer(self, event.run, self.export_region)
                self.region_viewers.append(viewer)
                self.status.set(
                    f"Regional detail ready from {len(event.run.window.tiles)} tiles; tiles are "
                    "cached for later zooms."
                )
            elif isinstance(event, _RegionExported):
                self.status.set(f"Region exported: {event.path}")
            elif isinstance(event, _PlanetExported):
                self.status.set(f"Planet exported: {event.path}. Inputs and outputs are hashed.")
            elif isinstance(event, _GeologyReady):
                self.validated = event.world
                self._show_summary(event.world)
                self._open_geology_editor(event.world)
            elif isinstance(event, _ContextReady):
                if (
                    event.signature != self._signature()
                    or str(event.rows) != self.context_rows.get()
                ):
                    self.status.set("World inputs changed; generate context again.")
                    continue
                self.context_run = event.run
                self.validated = event.run.context.world
                self._show_summary(self.validated)
                self._show_context_details()
                self.display_layer.set("Land coverage")
                self.pages.select(self.context_page)
                self._layer_changed()
                self.status.set(
                    "Geographic context ready. Review land, water and resolution support; "
                    "export to retain a reproducible result."
                )
            elif isinstance(event, _ContextOpened):
                if event.signature != self._signature():
                    self.status.set(
                        "World inputs changed while opening context; current work retained."
                    )
                    continue
                # The embedded source is an immutable product, never a Save target.
                self.accept_world(event.run.context.world, None)
                self.context_rows.set(str(event.run.context.grid.settings.latitude_cells))
                self.context_run = event.run
                self._show_context_details()
                self.display_layer.set("Land coverage")
                self.pages.select(self.context_page)
                self._layer_changed()
                self.status.set(
                    f"Opened verified context: {event.path}. Saved producer identity retained; "
                    "Save writes a separate world project."
                )
            elif isinstance(event, _ContextExported):
                self.status.set(
                    f"Context exported: {event.path}. Source snapshot and output hashes included."
                )
            elif isinstance(event, Exception):
                self._after_save = None
                self.status.set(str(event).partition("\n")[0])
                if isinstance(event, WorldGeometryError):
                    self._select_issues(event.feature_ids)
                messagebox.showerror("World map needs attention", str(event), parent=self)
            elif isinstance(event, WorldSource):
                self.accept_source(event)
            elif isinstance(event, _Opened):
                self.accept_world(event.world, event.path)
            else:
                result = event.world if isinstance(event, _Saved) else event
                self.validated = result
                self._show_summary(result)
                if isinstance(event, _Saved):
                    self.path = event.path
                    self._saved_signature = self._signature()
                    self.status.set(
                        f"Saved {event.path.name}. Original SVG is embedded. "
                        f"{len(result.adjustments)} import adjustments recorded by preparation."
                    )
                    self.on_change()
                    callback, self._after_save = self._after_save, None
                    if callback:
                        callback()
                        if self._closed:
                            return
                else:
                    self.status.set(
                        "World source validated. Save it to retain this geography and "
                        f"continent assignment. {len(result.adjustments)} import adjustments "
                        "are listed in the Adjustments tab."
                    )
        self._poll_id = self._scheduler.after(80, self._poll)

    def _clear_context(self) -> None:
        had_context = self.context_run is not None
        self.context_run = None
        self.display_layer.set("Source")
        self.excluded_toggle.configure(state="normal")
        self.viewer_note.set("Source geography · context available")
        self.context_detail.set(
            "Inputs changed. Generate context again."
            if had_context
            else "Generate geographic context from the current world. Land and water areas use "
            "the declared sphere. Small features remain in the source "
            "even when a cell cannot resolve them."
        )
        self._layer_changed()

    def _context_settings_changed(self, *_args: str) -> None:
        if self.context_run is not None and self.context_rows.get() == str(
            self.context_run.context.grid.settings.latitude_cells
        ):
            return
        self._clear_context()
        self._schedule_draw()

    def _clear_planet(self) -> None:
        if self.planet_run is not None:
            self.planet_run = None
            self._planet_probe = None
            self.planet_panel.clear("Inputs changed. Generate the planet again.")
            if self.display_layer.get() in PREVIEW_LAYERS:
                self.display_layer.set("Source")
                self._layer_changed()

    def _layer_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self.display_layer.get() in PREVIEW_LAYERS:
            run = self.planet_run
            if run is None or self.display_layer.get() not in run.previews:
                self.display_layer.set("Source")
                self.status.set(
                    "Generate the planet (with climate for atlas, rainfall and temperature) "
                    "before choosing its layers."
                )
                self.pages.select(self.planet_panel)
        elif self.display_layer.get() != "Source" and self.context_run is None:
            self.display_layer.set("Source")
            self.status.set("Generate context in the Context tab before choosing its layers.")
            self.pages.select(self.context_page)
        context = self.context_run.context if self.context_run else None
        self.excluded_toggle.configure(
            state="normal" if self.display_layer.get() == "Source" else "disabled"
        )
        layer = self.display_layer.get()
        self.bearing_input.configure(
            state="readonly"
            if context and layer in ("Water exposure", "Exposure support")
            else "disabled"
        )
        legends = {
            "Source": "Select a context layer after generation. Zoom inspects existing cells; "
            "it does not refine them. Climate and terrain are later stages.",
            "Land coverage": "Green = land; blue = water. Mixed colours retain fractional "
            "coverage of unresolved shores, islands and straits.",
            "Connected water": "Different colours identify connected water regions. "
            "Each cell displays its largest water region.",
            "Resolution support": "Orange = land missed by centre sampling; cyan = water "
            "missed by centre sampling; violet = disconnected water in one cell.",
            "Water openings": "Blue = full edge; orange = partial; dark = closed. Width is "
            "the longest continuous wet edge, not channel depth or transport capacity.",
            "Water connectivity": "Blue = one water piece; gold = several separate pieces; "
            "green = land; pink = unresolved water-region connectivity. "
            "Hover for piece identities and shared intervals. "
            "Outlines show the source coast. Connections do not yet model currents.",
            "Shore distance": "Cream = 0 km; purple = 3,000+ km. Distance is measured at "
            "cell centres and includes inland shores. Grey = no shoreline exists.",
            "Water exposure": "Tan = 0% water; blue = 100%. Choose the initial look direction "
            "beside the layer. Nearer water has more weight. This is not rainfall. "
            "Outlines show source geography.",
            "Exposure support": "Dark = 0%; gold = 100% of exposure weight falls in mixed "
            "coastal cells. This flags unresolved geography; it is not an error bound.",
        }
        legends |= {
            "Planet atlas": "Provisional biomes on shaded relief. Blue lines are rivers sized by "
            "discharge; blue lakes overflow, grey lakes are closed basins.",
            "Planet relief": "Elevation from uplift and river erosion; coast kept exactly.",
            "Planet rainfall": "Brown = dry; green = moderate; blue = 2,500+ mm/yr (provisional).",
            "Planet temperature": "Annual mean: violet = -25 °C; cream ≈ 5 °C; red = 30 °C.",
        }
        self.context_legend.set(legends.get(layer, legends["Source"]))
        planet = self.planet_run.result if self.planet_run else None
        self.viewer_note.set(
            f"{planet.mesh.spacing_m / 1000:,.0f} km planet mesh"
            if planet and layer in PREVIEW_LAYERS
            else f"{context.grid.angular_step_deg:g}° cells"
            if context and self.display_layer.get() != "Source"
            else "Retained source geography"
        )
        self._schedule_draw()

    def _scroll_context_detail(self, *args: str) -> None:
        self.context_text.yview(*args)

    def _context_detail_changed(self, *_args: str) -> None:
        self.context_text.configure(state="normal")
        self.context_text.delete("1.0", "end")
        self.context_text.insert("1.0", self.context_detail.get())
        self.context_text.configure(state="disabled")
        self.context_text.yview_moveto(0)

    def _show_context_details(self) -> None:
        if self.context_run is None:
            return
        result = self.context_run.context
        rows, columns = result.grid.shape
        invisible = sum(b.displayed_cells == 0 for b in result.water_bodies)
        graph = result.connectivity
        topology = (
            f"{len(graph.fragmented_bodies)} source water regions have unresolved connectivity; "
            "transport unsupported for those regions."
            if graph.fragmented_bodies
            else "Graph components match source regions."
        )
        self.context_detail.set(
            f"{columns} x {rows} cells · {result.grid.angular_step_deg:g}°\n"
            f"North-south spacing: {result.grid.north_south_spacing_km:,.1f} km\n"
            "East-west spacing decreases towards the poles.\n\n"
            f"{len(result.water_bodies)} connected water regions; {invisible} below display scale\n"
            f"{result.mixed_cells:,} mixed coastal cells\n"
            f"{result.connectivity.split_cells:,} cells with disconnected water\n"
            f"{len(result.connectivity.water_body):,} water pieces; "
            f"{len(result.connectivity.link_nodes):,} shared intervals\n"
            f"{graph.component_count} graph components. {topology}\n\n"
            f"Shore distance: {result.shore_sampling.sample_count:,} samples; "
            f"overestimate at most {result.shore_sampling.max_error_km:.2f} km.\n\n"
            f"Water exposure: 8 directions over {exposure_range_km(result.grid):,.0f} km; "
            f"{exposure_steps(result.grid)} samples per ray.\n"
            "Sampling may miss narrow features. Inspect Exposure support and compare "
            "grid resolutions before drawing conclusions."
        )

    def show_planet(self) -> None:
        self.pages.select(self.planet_panel)

    def generate_planet(self, settings: PlanetSettings, geology_path: Path | None) -> None:
        if self.busy:
            return
        try:
            project = self.project()
        except ValueError as error:
            messagebox.showerror("Planet needs a valid world", str(error), parent=self)
            return
        signature = self._signature()
        cancellation = CancellationToken()
        self._context_cancellation = cancellation

        def progress(fraction: float, message: str) -> None:
            self._events.put(_Progress(f"{fraction:.0%} · {message}"))

        self._work(
            "Generating the planet…",
            lambda: _PlanetReady(
                generate_planet_run(
                    project, geology_path, settings, progress, cancellation=cancellation
                ),
                signature,
            ),
        )

    def export_planet(self, destination: Path) -> None:
        run = self.planet_run
        if self.busy or run is None:
            return
        cancellation = CancellationToken()
        self._context_cancellation = cancellation
        self._work(
            "Exporting the planet build…",
            lambda: _PlanetExported(export_planet(run, destination, cancellation=cancellation)),
        )

    def zoom_region(self, radius_km: float | None = None) -> None:
        run = self.planet_run
        if self.busy or run is None:
            return
        frame = run.result.world.project.frame
        x = frame.bounds[0] + self.viewport.centre[0] * frame.width
        y = frame.bounds[1] + self.viewport.centre[1] * frame.height
        longitude, latitude = frame.source_to_lonlat((x, y))
        if radius_km is None:
            # About the half-width of the visible map, clamped to a sensible window.
            radius_km = 3.1416 * frame.radius_km / 2 / self.viewport.zoom
            radius_km = min(1200.0, max(150.0, radius_km))
        parent = RegionalParent.from_result(run.result)
        identity = planet_identity(run)
        cancellation = CancellationToken()
        self._context_cancellation = cancellation
        workers = self.region_workers

        def progress(fraction: float, message: str) -> None:
            self._events.put(_Progress(f"{fraction:.0%} · {message}"))

        self._work(
            "Generating regional detail…",
            lambda: _RegionReady(
                region_window(
                    parent, identity, user_tile_cache(), (longitude, latitude), radius_km,
                    pixels=900, workers=workers, progress=progress, cancellation=cancellation,
                )
            ),
        )

    def export_region(self, run: RegionRun, destination: Path) -> None:
        if self.busy:
            return
        self._work(
            "Exporting the region…", lambda: _RegionExported(export_region(run, destination))
        )

    def show_terrain(self) -> None:
        self.pages.select(self.terrain_panel)

    def _open_prepared_terrain(self, created: WorldTerrainCreated) -> None:
        if self.on_terrain_ready is not None:
            self.on_terrain_ready(created)

    def create_terrain(
        self, continent_id: str, output: Path, geology_path: Path | None = None,
    ) -> None:
        if self.busy:
            return
        try:
            project = self.project()
        except ValueError as error:
            messagebox.showerror("Terrain needs a valid world", str(error), parent=self)
            return
        signature = self._signature()
        context = self.context_run
        cancellation = CancellationToken()
        self._context_cancellation = cancellation

        def progress(_fraction: float, message: str) -> None:
            self._events.put(_Progress(message))

        self._work(
            "Preparing world land for terrain generation…",
            lambda: _TerrainReady(
                create_world_terrain_project(
                    project, continent_id, output, progress=progress, cancellation=cancellation,
                    geology_path=geology_path, context=context,
                ),
                signature,
            ),
        )

    def generate_context(self) -> None:
        if self.busy:
            return
        try:
            project = self.project()
            settings = WorldContextSettings(int(self.context_rows.get()))
        except ValueError as error:
            messagebox.showerror("Context needs a valid world", str(error), parent=self)
            return
        signature = self._signature()
        cancellation = CancellationToken()
        self._context_cancellation = cancellation

        def progress(_fraction: float, message: str) -> None:
            self._events.put(_Progress(message))

        self._work(
            "Generating geographic context…",
            lambda: _ContextReady(
                generate_context(project, settings, progress, cancellation=cancellation),
                signature,
                settings.latitude_cells,
            ),
        )

    def choose_context(self) -> None:
        def choose() -> None:
            selected = filedialog.askopenfilename(
                parent=self,
                title="Open a completed world context",
                filetypes=[("World context manifest", "context.json")],
            )
            if selected:
                self.load_context(Path(selected))

        self.guard(choose)

    def load_context(self, path: Path) -> None:
        if self.busy:
            return
        cancellation = CancellationToken()
        self._context_cancellation = cancellation
        signature = self._signature()
        self._work(
            "Verifying context source, hashes and numeric products…",
            lambda: _ContextOpened(open_context(path, cancellation=cancellation), path, signature),
        )

    def cancel_context(self) -> None:
        if self._context_cancellation is not None:
            self._context_cancellation.cancel()
            self.status.set("Stopping the world job at the next checkpoint…")
            self.context_cancel.configure(state="disabled")
            self.terrain_panel.cancel_button.configure(state="disabled")
            self.planet_panel.cancel_button.configure(state="disabled")

    def export_context(self) -> None:
        if self.busy:
            return
        run = self.context_run
        if run is None:
            self.status.set("Generate context before exporting it.")
            return
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Create a new context result folder",
            initialdir=str(self.path.parent) if self.path else None,
            initialfile="world-context-" + uuid4().hex[:8],
        )
        if not selected:
            return
        cancellation = CancellationToken()
        self._context_cancellation = cancellation
        self._work(
            "Exporting context and its source snapshot…",
            lambda: _ContextExported(
                export_context(run, Path(selected), cancellation=cancellation)
            ),
        )

    def choose_svg(self) -> None:
        def choose() -> None:
            selected = filedialog.askopenfilename(
                parent=self, title="Import full world SVG", filetypes=[("SVG world map", "*.svg")]
            )
            if selected:
                self.load_svg(Path(selected))

        self.guard(choose)

    def load_svg(self, path: Path) -> None:
        self._work("Reading world source and retained shapes…", lambda: load_world_svg(path))

    def choose_world(self) -> None:
        def choose() -> None:
            selected = filedialog.askopenfilename(
                parent=self, title="Open world", filetypes=[("DM Tools world", "*.dmworld.json")]
            )
            if selected:
                self.load_world(Path(selected))

        self.guard(choose)

    def load_world(self, path: Path) -> None:
        self._work("Opening and checking portable world…", lambda: _Opened(open_world(path), path))

    def accept_source(self, source: WorldSource) -> None:
        self._loading = True
        self.source, self.path, self.validated = source, None, None
        self.continents, self.assignments = (), ()
        self._undo.clear()
        self._redo.clear()
        self._saved_signature = None
        x0, y0, x1, y1 = source.suggested_bounds
        for key, value in (
            ("name", Path(source.name).stem),
            ("radius", ""),
            ("meridian", "0"),
            ("x", str(x0)),
            ("y", str(y0)),
            ("width", str(x1 - x0)),
            ("height", str(y1 - y0)),
        ):
            self.values[key].set(value)
        self._loading = False
        self.viewport.fit()
        self._populate()
        self._changed()
        issues = tuple(f.id for f in source.features if f.issue)
        self._select_issues(issues)
        self.status.set(
            f"Imported {source.name}: {len(source.features)} shapes. "
            + (
                f"{len(issues)} shapes need attention and are selected; review their details."
                if issues
                else "Assign continents (or suggest from groups), then confirm the World frame."
            )
        )

    def accept_world(self, world: WorldMap, path: Path | None) -> None:
        self.accept_source(world.project.source)
        self._loading = True
        self.continents = world.project.continents
        self.assignments = world.project.assignments
        frame = world.project.frame
        for key, value in (
            ("name", world.project.name),
            ("radius", str(frame.radius_km)),
            ("meridian", str(frame.central_meridian_deg)),
            ("x", str(frame.bounds[0])),
            ("y", str(frame.bounds[1])),
            ("width", str(frame.width)),
            ("height", str(frame.height)),
        ):
            self.values[key].set(value)
        self._loading = False
        self.path, self.validated = path, world
        self._saved_signature = self._signature()
        self._populate()
        self._show_summary(world)
        self.status.set(
            f"Opened {path.name if path else world.project.name}. Source and ownership verified; "
            f"{len(world.adjustments)} import adjustments."
        )
        self.on_change()
        self._schedule_draw()

    def _populate(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        owners = {c.id: c.name for c in self.continents}
        assignments = {a.feature_id: a for a in self.assignments}
        if self.source:
            for feature in self.source.features:
                assignment = assignments.get(feature.id)
                label = "Needs attention" if feature.issue else "Unassigned"
                if assignment:
                    label = (
                        "Excluded"
                        if assignment.continent_id is None
                        else owners[assignment.continent_id]
                        + (" · island" if assignment.role == "island" else "")
                    )
                self.tree.insert(
                    "",
                    "end",
                    iid=feature.id,
                    text=feature.label,
                    values=(label,),
                    tags=("issue",) if feature.issue else (),
                )
        self.owner_input.configure(values=sorted(owners.values(), key=str.casefold))
        self.terrain_panel.set_continents(self.continents)
        self.tree.selection_set([key for key in selected if self.tree.exists(key)])
        self._schedule_draw()

    def _select_issues(self, identifiers: tuple[str, ...]) -> None:
        existing = [key for key in identifiers if self.tree.exists(key)]
        if existing:
            self.display_layer.set("Source")
            self._layer_changed()
            self.tree.selection_set(existing)
            self.tree.see(existing[0])
            self._selection()

    def _selection(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.tree.selection()
        if self.source and selection:
            feature = next(f for f in self.source.features if f.id == selection[0])
            self.detail.configure(
                text=f"{len(selection)} selected · {feature.label}"
                + f"\nID: {feature.id}"
                + (f"\nGroup: {' / '.join(feature.groups)}" if feature.groups else "")
                + (f"\n{feature.issue}" if feature.issue else "")
            )
            assignment = next((a for a in self.assignments if a.feature_id == selection[0]), None)
            if assignment:
                self.role.set(assignment.role.title())
                if assignment.continent_id:
                    self.owner.set(
                        next(c.name for c in self.continents if c.id == assignment.continent_id)
                    )
        else:
            self.detail.configure(text="Select shapes here or click the map.")
        self._schedule_draw()

    def _commit_ownership(
        self, continents: tuple[WorldContinent, ...], assignments: tuple[WorldAssignment, ...]
    ) -> None:
        if (continents, assignments) == (self.continents, self.assignments):
            return
        self._undo.append((self.continents, self.assignments))
        self._undo = self._undo[-100:]
        self._redo.clear()
        self.continents, self.assignments = continents, assignments
        self._populate()
        self._changed()

    def suggest_groups(self) -> None:
        if self.source and not self.busy:
            continents, assignments = propose_group_assignments(self.source)
            self._commit_ownership(continents, assignments)
            self.status.set(
                "Group suggestions applied. Review ownership and excluded shapes; "
                "Undo restores the previous assignments."
            )

    def assign_selected(self) -> None:
        selected = self.tree.selection()
        if self.busy or not selected:
            self.status.set("Select one or more source shapes first.")
            return
        try:
            roles: dict[str, WorldRole] = {
                "Mainland": "mainland",
                "Island": "island",
                "Exclude": "exclude",
            }
            role = roles[self.role.get()]
            continents = {c.id: c for c in self.continents}
            owner: str | None = None
            if role != "exclude":
                name = self.owner.get().strip()
                continent = next(
                    (c for c in self.continents if c.name.casefold() == name.casefold()), None
                )
                if continent is None:
                    continent = continent_from_name(name)
                    if continent.id in continents:
                        continent = WorldContinent(continent.id + "-" + uuid4().hex[:8], name)
                continents[continent.id] = continent
                owner = continent.id
            assignments = {a.feature_id: a for a in self.assignments}
            assignments.update((key, WorldAssignment(key, owner, role)) for key in selected)
            used = {a.continent_id for a in assignments.values()}
            self._commit_ownership(
                tuple(c for c in continents.values() if c.id in used),
                tuple(sorted(assignments.values(), key=lambda a: a.feature_id)),
            )
        except ValueError as error:
            self.status.set(str(error))

    def rename_continent(self) -> None:
        from tkinter import simpledialog

        if self.busy:
            return
        current = next((c for c in self.continents if c.name == self.owner.get()), None)
        if current is None:
            self.status.set("Select a shape assigned to the continent you want to rename.")
            return
        name = simpledialog.askstring(
            "Rename continent", "Continent name:", initialvalue=current.name, parent=self
        )
        if name is None:
            return
        try:
            renamed = WorldContinent(current.id, name.strip())
            if any(
                c.id != current.id and c.name.casefold() == renamed.name.casefold()
                for c in self.continents
            ):
                raise ValueError("Another continent already has that name.")
            self._commit_ownership(
                tuple(renamed if c.id == current.id else c for c in self.continents),
                self.assignments,
            )
            self.owner.set(renamed.name)
        except ValueError as error:
            self.status.set(str(error))

    def undo(self) -> None:
        if self._undo and not self.busy:
            self._redo.append((self.continents, self.assignments))
            self.continents, self.assignments = self._undo.pop()
            self._populate()
            self._changed()

    def redo(self) -> None:
        if self._redo and not self.busy:
            self._undo.append((self.continents, self.assignments))
            self.continents, self.assignments = self._redo.pop()
            self._populate()
            self._changed()

    def select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def edit_bathymetry(self) -> None:
        if self.busy:
            return
        if self.bathymetry_editor is not None:
            self.bathymetry_editor.lift()
            return
        if self.context_run is None or not self.context_run.context.water_bodies:
            self.status.set(
                "Generate or open geographic context with water first, then choose Bathymetry."
            )
            self.pages.select(self.context_page)
            return
        saved = self._bathymetry_file
        if saved and world_fingerprint(saved.inputs.world) != world_fingerprint(self.project()):
            saved = None

        def closed(file: BathymetryFile | None) -> None:
            self._bathymetry_file = file
            self.bathymetry_editor = None

        self.bathymetry_editor = BathymetryEditor(
            self, self.context_run, on_close=closed, saved=saved
        )
        self.status.set(
            "Bathymetry inputs open; ocean depths are generated from explicit hypotheses."
        )

    def edit_geology(self) -> None:
        if self.busy:
            return
        if self.geology_editor is not None:
            self.geology_editor.lift()
            return
        try:
            project = self.project()
        except ValueError as error:
            self.status.set(str(error))
            return
        if self.validated is not None:
            self._open_geology_editor(self.validated)
        else:
            self._work(
                "Preparing world for geology inputs…",
                lambda: _GeologyReady(prepare_world_map(project)),
            )

    def _open_geology_editor(self, world: WorldMap) -> None:
        saved = self._geology_file
        if saved and world_fingerprint(saved.coverage.recipe.world) != world_fingerprint(
            world.project
        ):
            saved = None

        def closed(file: GeologyFile | None) -> None:
            self._geology_file = file
            if file is not None:
                self.terrain_panel.set_geology(file.path)
                self.planet_panel.set_geology(file.path)
            self.geology_editor = None

        self.geology_editor = GeologyEditor(
            self, world, self.context_run, on_close=closed, saved=saved
        )
        self.status.set("Geology inputs open in their own editor; world source retained.")

    def validate(self) -> None:
        if self.busy:
            return
        try:
            project = self.project()
        except ValueError as error:
            self.status.set(str(error))
            if isinstance(error, WorldGeometryError):
                self._select_issues(error.feature_ids)
            return
        self._work(
            "Checking world frame, seams, ownership and overlap…",
            lambda: prepare_world_map(project),
        )

    def save(self, *, save_as: bool = False, after_save: Callable[[], None] | None = None) -> None:
        if self.busy:
            return
        try:
            project = self.project()
        except ValueError as error:
            self.status.set(str(error))
            if isinstance(error, WorldGeometryError):
                self._select_issues(error.feature_ids)
            return
        path = self.path
        if save_as or path is None:
            selected = filedialog.asksaveasfilename(
                parent=self,
                title="Save world inputs",
                defaultextension=WORLD_EXTENSION,
                initialfile=(self.path.name if self.path else "world.dmworld.json"),
                filetypes=[("DM Tools world", "*.dmworld.json")],
            )
            if not selected:
                return
            path = Path(selected)
        target = path
        self._after_save = after_save
        self._work(
            "Validating and saving portable world…",
            lambda: _Saved(save_world(project, target), target),
        )

    def guard(self, action: Callable[[], None]) -> None:
        if self.bathymetry_editor is not None:
            floor_editor = self.bathymetry_editor

            def continue_after_bathymetry() -> None:
                floor_editor.close()
                self.guard(action)

            floor_editor.guard(continue_after_bathymetry)
            return
        if self.geology_editor is not None:
            editor = self.geology_editor

            def continue_after_geology() -> None:
                editor.close()
                self.guard(action)

            editor.guard(continue_after_geology)
            return
        if self.busy:
            self.status.set("Wait for the world operation to finish before continuing.")
            return
        if not self.dirty:
            action()
            return
        answer = messagebox.askyesnocancel(
            "Save world changes?", "Save this world's inputs before continuing?", parent=self
        )
        if answer is True:
            self.save(after_save=action)
        elif answer is False:
            action()

    def _show_summary(self, world: WorldMap) -> None:
        self.adjustment_tree.delete(*self.adjustment_tree.get_children())
        titles = {
            "edge_clip": "Rounded world edge",
            "shared_land": "Shared land within one continent",
            "border_overlap": "Narrow continent-border overlap",
        }
        for index, adjustment in enumerate(world.adjustments):
            self.adjustment_tree.insert("", "end", iid=str(index), text=titles[adjustment.kind])
        self.pages.tab(self.adjustments_page, text=f"Adjustments ({len(world.adjustments)})")
        self.adjustment_detail.configure(
            text=(
                "Select an adjustment to highlight its source shapes. "
                "Prepared coverage counts shared land once. "
                "Original SVG and assignments are retained."
                if world.adjustments
                else "No import adjustments were needed."
            )
        )
        names = " · ".join(f"{c.name}: {c.area_km2:,.0f} km²" for c in world.continents)
        self.summary.set(
            f"{len(world.continents)} continents · {world.land_fraction:.1%} land · "
            f"radius {world.project.frame.radius_km:,.0f} km\n{names}\n"
            f"{len(world.adjustments)} import adjustments; see the Adjustments tab. "
            "Areas use prepared coverage on the declared sphere. "
            "World source is ready. Use Terrain to create a local generation project."
        )

    def _review_adjustment(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self.adjustment_tree.selection()
        if self.busy or self.validated is None or not selected:
            return
        adjustment = self.validated.adjustments[int(selected[0])]
        self.adjustment_detail.configure(
            text=(
                adjustment.message + f"\n\nShared/trimmed area: "
                f"{adjustment.area_source_units2:.6g} square source units. "
                "Original SVG and assignments are unchanged."
            )
        )
        self._select_issues(adjustment.feature_ids)

    def _bounds(self) -> tuple[float, float, float, float]:
        try:
            return self._frame().bounds
        except ValueError:
            return self.source.suggested_bounds if self.source else (0.0, 0.0, 360.0, 180.0)

    def _schedule_draw(self) -> None:
        if not self._closed and self._draw_id is None:
            self._draw_id = self._scheduler.after(25, self._draw)

    def _draw(self) -> None:
        self._draw_id = None
        self.canvas.delete("all")
        self._photo = None
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if self.source is None:
            self.canvas.create_text(
                width / 2,
                height / 2 - 24,
                text="Start with your world",
                fill="#d9e5df",
                font=("Segoe UI", 24, "bold"),
            )
            self.canvas.create_text(
                width / 2,
                height / 2 + 25,
                text="Import an SVG or open the public example world.\n"
                "Continents, islands and the world frame stay connected.",
                fill="#9bb4b3",
                font=("Segoe UI", 11),
                justify="center",
            )
            return
        bounds = self._bounds()
        try:
            if self.planet_run is not None and self.display_layer.get() in PREVIEW_LAYERS:
                world_size = (bounds[2] - bounds[0], bounds[3] - bounds[1])
                preview = frame_view(
                    self.planet_run.previews[self.display_layer.get()],
                    self.viewport.rect((width, height), world_size),
                    (width, height),
                    OCEAN,
                )
            elif self.context_run is not None and self.display_layer.get() in CONTEXT_LAYERS:
                preview = render_world_context(
                    self.context_run.context,
                    self.viewport,
                    (width, height),
                    cast(ContextLayer, self.display_layer.get()),
                    EXPOSURE_BEARINGS.index(self.exposure_bearing.get()),
                )
            else:
                preview = render_world_source(
                    self.source,
                    bounds,
                    self.assignments,
                    self.viewport,
                    (width, height),
                    frozenset(self.tree.selection()),
                    show_excluded=self.show_excluded.get(),
                )
            with preview as image:
                self._photo = ImageTk.PhotoImage(image, master=self)
        except ValueError as error:
            self.status.set(str(error))
            return
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        left, top, right, bottom = self.viewport.rect(
            (width, height), (bounds[2] - bounds[0], bounds[3] - bounds[1])
        )
        for index in range(1, 6):
            x = left + (right - left) * index / 6
            self.canvas.create_line(x, top, x, bottom, fill="#476068", dash=(2, 6))
        for index in range(1, 6):
            y = top + (bottom - top) * index / 6
            self.canvas.create_line(left, y, right, y, fill="#476068", dash=(2, 6))
        self.canvas.create_rectangle(left, top, right, bottom, outline="#87a6a5")
        self.canvas.create_text(
            12,
            12,
            anchor="nw",
            text=f"{self.source.name}  ·  {self.viewport.zoom:.1f}x  ·  {self.display_layer.get()}",
            fill="#e3eddf",
            font=("Segoe UI", 10, "bold"),
        )

    def fit(self) -> None:
        self.viewport.fit()
        self._schedule_draw()

    def _size(self) -> tuple[int, int]:
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def _world_size(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self._bounds()
        return x1 - x0, y1 - y0

    def _wheel(self, event: tk.Event[tk.Misc]) -> str:
        self.canvas.focus_set()
        if event.delta:
            self.viewport.zoom_at(
                1.25 if event.delta > 0 else 0.8,
                (event.x, event.y),
                self._size(),
                self._world_size(),
            )
            self._schedule_draw()
        return "break"

    def _pan_start(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.focus_set()
        self._pan = event.x, event.y
        self.canvas.configure(cursor="fleur")

    def _pan_move(self, event: tk.Event[tk.Misc]) -> None:
        if self._pan:
            self.viewport.pan(
                (event.x - self._pan[0], event.y - self._pan[1]), self._size(), self._world_size()
            )
            self._pan = event.x, event.y
            self._schedule_draw()

    def _pan_end(self, _event: tk.Event[tk.Misc]) -> None:
        self._pan = None
        self.canvas.configure(cursor="")

    def _position(self, event: tk.Event[tk.Misc]) -> tuple[float, float] | None:
        left, top, right, bottom = self.viewport.rect(self._size(), self._world_size())
        if not left <= event.x <= right or not top <= event.y <= bottom:
            return None
        x0, y0, x1, y1 = self._bounds()
        return (
            x0 + (event.x - left) / (right - left) * (x1 - x0),
            y0 + (event.y - top) / (bottom - top) * (y1 - y0),
        )

    def _motion(self, event: tk.Event[tk.Misc]) -> None:
        position = self._position(event)
        if position is None:
            return
        try:
            longitude, latitude = self._frame().source_to_lonlat(position)
            detail = "Wheel: zoom · Middle/right drag: pan · F: fit"
            if self._planet_probe is not None and self.display_layer.get() in PREVIEW_LAYERS:
                detail = self._planet_probe.describe(longitude, latitude)
            elif self.context_run is not None and self.display_layer.get() != "Source":
                context = self.context_run.context
                frame = context.grid.frame
                rows, columns = context.grid.shape
                col = min(columns - 1, int((position[0] - frame.bounds[0]) / frame.width * columns))
                row = min(rows - 1, int((position[1] - frame.bounds[1]) / frame.height * rows))
                detail = (
                    f"Cell {row + 1}, {col + 1}: {context.land_fraction[row, col]:.1%} land · "
                    f"water region {context.water_body[row, col]} · "
                    + (
                        "mixed/subgrid support"
                        if context.support_flags[row, col]
                        else "single surface"
                    )
                )
                if self.display_layer.get() == "Shore distance":
                    distance = float(context.shore_distance_km[row, col])
                    detail = (
                        f"Cell-centre shore distance: {distance:,.1f} km · "
                        f"overestimate <= {context.shore_sampling.max_error_km:.2f} km"
                        if isfinite(distance)
                        else "No shoreline exists in this world"
                    )
                elif self.display_layer.get() in ("Water exposure", "Exposure support"):
                    direction = EXPOSURE_BEARINGS.index(self.exposure_bearing.get())
                    detail = (
                        f"Looking {self.exposure_bearing.get()}: "
                        f"{context.water_exposure[direction, row, col]:.1%} weighted water · "
                        f"{context.exposure_mixed_support[direction, row, col]:.1%} mixed support"
                    )
                elif self.display_layer.get() == "Water connectivity":
                    graph = context.connectivity
                    cell = row * columns + col
                    start, end = map(int, graph.cell_offsets[cell : cell + 2])
                    pieces = "; ".join(
                        f"#{node}: region {graph.water_body[node]}, "
                        f"{graph.incident_links[node]} intervals"
                        for node in range(start, min(end, start + 3))
                    )
                    detail = f"Cell {row + 1}, {col + 1}: {end - start} water pieces"
                    if pieces:
                        detail += " · " + pieces + ("; …" if end - start > 3 else "")
                    if any(body in graph.fragmented_bodies for body in graph.water_body[start:end]):
                        detail += " · unresolved connectivity"
                elif self.display_layer.get() == "Water openings":
                    north = context.south_opening_km[row - 1, col] if row else 0.0
                    detail = (
                        f"Cell {row + 1}, {col + 1} · longest water opening (km): "
                        f"N {north:.2f} · E {context.east_opening_km[row, col]:.2f} · "
                        f"S {context.south_opening_km[row, col]:.2f} · "
                        f"W {context.east_opening_km[row, (col - 1) % columns]:.2f}"
                    )
            self.inspection.set(
                f"{abs(latitude):.2f}° {'N' if latitude >= 0 else 'S'}   "
                f"{abs(longitude):.2f}° {'E' if longitude >= 0 else 'W'}   ·   " + detail
            )
        except ValueError:
            self.inspection.set(
                f"Source x {position[0]:.2f}, y {position[1]:.2f} · "
                "Confirm the world frame and radius for geographic coordinates."
            )

    def _pick(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.focus_set()
        if self.display_layer.get() != "Source":
            self._motion(event)
            return
        position = self._position(event)
        if position is None or self.source is None:
            return
        span = self._world_size()[0]
        excluded = {a.feature_id for a in self.assignments if a.role == "exclude"}
        for feature in reversed(self.source.features):
            if feature.id in excluded and not self.show_excluded.get():
                continue
            if any(
                Polygon(c.exterior, c.holes).covers(Point(position[0] + shift, position[1]))
                for c in feature.components
                for shift in (-span, 0.0, span)
            ):
                if int(event.state) & 0x0004:
                    self.tree.selection_add(feature.id)
                else:
                    self.tree.selection_set(feature.id)
                self.tree.see(feature.id)
                return

    def close(self) -> None:
        self._closed = True
        if self.geology_editor is not None:
            self.geology_editor.close()
        if self.bathymetry_editor is not None:
            self.bathymetry_editor.close()
        for viewer in self.region_viewers:
            if viewer.winfo_exists():
                viewer.destroy()
        self.region_viewers.clear()
        if self._context_cancellation is not None:
            self._context_cancellation.cancel()
        for identifier in (self._poll_id, self._draw_id):
            if identifier:
                self._scheduler.after_cancel(identifier)
        self._poll_id = self._draw_id = None
        self._photo = None
