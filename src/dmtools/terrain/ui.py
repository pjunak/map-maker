# pyright: reportUnknownMemberType=false
"""Tk desktop interface for the first terrain-generator vertical slice."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from functools import partial
from math import hypot
from pathlib import Path
from time import monotonic
from tkinter import filedialog, messagebox, ttk
from typing import cast

from PIL import Image, ImageTk
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from dmtools.terrain.adapters import (
    PROJECT_EXTENSION,
    CoastlineInputError,
    CoastlineSource,
    LoadedTerrainProject,
    RenderStyle,
    TerrainProjectInputError,
    elevation_legend_colours,
    load_svg_coastline_source,
    load_terrain_project,
    save_height_map,
    save_terrain_project,
)
from dmtools.terrain.adapters.channel_display import ChannelDisplay, prepare_channel_display
from dmtools.terrain.adapters.render import (
    compose_height_map,
    render_basin_catchment_overlay,
    render_basin_outflow_overlay,
    render_basin_overlay,
    render_height_map_layers,
)
from dmtools.terrain.adapters.viewport import render_viewport
from dmtools.terrain.adapters.water_display import WaterDisplay
from dmtools.terrain.application.world_terrain import WorldTerrainCreated
from dmtools.terrain.domain import (
    BrushToolSettings,
    Coastline,
    ElevationMode,
    ElevationPoint,
    FeatureToolSettings,
    LakeToolSettings,
    LandformSettings,
    TerrainAuthoringState,
    TerrainBasin,
    TerrainBrushStroke,
    TerrainConstraint,
    TerrainProject,
    TerrainRegion,
    TerrainSettings,
    TerrainStructure,
    landform_preset,
)
from dmtools.terrain.domain.terrain_context import TerrainWorldContext
from dmtools.terrain.pipeline import GeneratedTerrain, generate_terrain
from dmtools.terrain.pipeline.control import CancellationToken, GenerationCancelled
from dmtools.terrain.structure_profile_ui import edit_structure_profile
from dmtools.terrain.ui_style import INK, MAP_BACKGROUND, PANEL, PAPER, configure_styles
from dmtools.terrain.viewport import MapViewport
from dmtools.terrain.workbench import (
    GenerationInputs,
    InstructionHistory,
    instruction_vertices,
    move_instruction,
)
from dmtools.terrain.world_ui import WorldWorkspace

_HEIGHT_COLOUR = "#f2c14e"
_RIDGE_COLOUR = "#e47b58"
_VALLEY_COLOUR = "#54a6c2"
_BRUSH_COLOUR = "#9fbe72"
_REGION_COLOUR = "#c5b6f5"

_RENDER_STYLE_LABELS: dict[str, RenderStyle] = {
    "Cartographic relief": "cartographic",
    "Scientific elevation": "scientific",
}


@dataclass(frozen=True, slots=True)
class _ControlSpec:
    key: str
    label: str
    minimum: float
    maximum: float
    default: float
    increment: float
    unit: str = ""
    integer: bool = False


@dataclass(frozen=True, slots=True)
class _ProgressEvent:
    fraction: float
    message: str
    generation: CancellationToken | None = None


@dataclass(frozen=True, slots=True)
class _ResultEvent:
    inputs: GenerationInputs
    terrain: GeneratedTerrain
    image: Image.Image
    water_display: WaterDisplay | None
    generation: CancellationToken | None = None


@dataclass(frozen=True, slots=True)
class _CoastlineEvent:
    source: CoastlineSource


@dataclass(frozen=True, slots=True)
class _ProjectEvent:
    loaded: LoadedTerrainProject


@dataclass(frozen=True, slots=True)
class _ProjectSavedEvent:
    path: Path
    inputs: GenerationInputs


@dataclass(frozen=True, slots=True)
class _ErrorEvent:
    title: str
    status: str
    error: Exception
    generation: CancellationToken | None = None


@dataclass(frozen=True, slots=True)
class _CancelledEvent:
    generation: CancellationToken


type _UiEvent = (
    _ProgressEvent
    | _ResultEvent
    | _CoastlineEvent
    | _ProjectEvent
    | _ProjectSavedEvent
    | _ErrorEvent
    | _CancelledEvent
)


_CONTROLS = (
    _ControlSpec("seed", "Seed", 0, 4_294_967_295, 20_260_902, 1, integer=True),
    _ControlSpec("object_scale_km", "Object scale", 100, 12_000, 4_000, 100, "km"),
    _ControlSpec("resolution_px", "Output resolution", 256, 2_048, 768, 128, "px", True),
    _ControlSpec("maximum_elevation_m", "Elevation ceiling", 250, 12_000, 4_500, 100, "m"),
    _ControlSpec("largest_feature_km", "Largest feature", 25, 2_000, 450, 25, "km"),
    _ControlSpec("detail_levels", "Detail levels", 1, 10, 6, 1, integer=True),
    _ControlSpec("roughness", "Fine-detail strength", 0.25, 0.85, 0.55, 0.01),
    _ControlSpec("coastal_rise_km", "Coastal rise distance", 5, 1_000, 180, 5, "km"),
    _ControlSpec("variability", "Elevation variability", 0, 1, 0.75, 0.01),
    _ControlSpec("drainage_density", "Drainage density", 0.25, 2, 1.0, 0.05),
)


class TerrainApp:
    """Small local workbench for importing, generating, previewing, and exporting."""

    def __init__(self, root: tk.Tk, project: Path | None = None,
                 *, world: Path | None = None) -> None:
        self.root = root
        self.root.title("DM Tools — Map Workbench")
        self.root.geometry("1440x900")
        self.root.minsize(1160, 760)
        self.root.configure(background=PAPER)

        self._coastline: Coastline | None = None
        self._coastline_source: CoastlineSource | None = None
        self._world_context: TerrainWorldContext | None = None
        self._project_path: Path | None = None
        self._terrain: GeneratedTerrain | None = None
        self._image: Image.Image | None = None
        self._water_display: WaterDisplay | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._channel_display: ChannelDisplay | None = None
        self._coast_polygon: Polygon | MultiPolygon | None = None
        self._history = InstructionHistory()
        self._selected_instruction: int | None = None
        self._generated_inputs: GenerationInputs | None = None
        self._saved_inputs: GenerationInputs | None = None
        self._after_save: Callable[[], None] | None = None
        self._busy = False
        self._generation_cancel: CancellationToken | None = None
        self._generation_started: float | None = None
        self._generation_message = ""
        self._generation_fraction = 0.0
        self._closed = False
        self._poll_after_id: str | None = None
        self._viewport = MapViewport()
        self._syncing_selection = False
        self._selection_mode = False
        self._space_pressed = False
        self._pan_start: tuple[float, float] | None = None
        self._drag_origin: tuple[float, float] | None = None
        self._drag_vertex: int | None = None
        self._drag_candidate: TerrainConstraint | None = None
        self._drag_error: str | None = None
        self._settings_widgets: list[ttk.Widget] = []
        self._world_scale_widgets: list[ttk.Widget] = []
        self._draft_points: list[tuple[float, float]] = []
        self._events: queue.Queue[_UiEvent] = queue.Queue()
        self._variables: dict[str, tk.DoubleVar] = {}
        self._value_labels: dict[str, ttk.Label] = {}
        self._specs = {spec.key: spec for spec in _CONTROLS}
        authoring_defaults = TerrainAuthoringState()
        self._authoring_tool = tk.StringVar(value=authoring_defaults.active_tool)
        self._tool_modes = {
            "brush": tk.StringVar(value=authoring_defaults.brush.elevation_mode.title()),
            "height": tk.StringVar(value=authoring_defaults.height.elevation_mode.title()),
            "ridge": tk.StringVar(value=authoring_defaults.ridge.elevation_mode.title()),
            "valley": tk.StringVar(value=authoring_defaults.valley.elevation_mode.title()),
        }
        self._tool_elevations = {
            "brush": tk.DoubleVar(value=authoring_defaults.brush.elevation_m),
            "height": tk.DoubleVar(value=authoring_defaults.height.elevation_m),
            "ridge": tk.DoubleVar(value=authoring_defaults.ridge.elevation_m),
            "valley": tk.DoubleVar(value=authoring_defaults.valley.elevation_m),
        }
        self._tool_sizes = {
            "brush": tk.DoubleVar(value=authoring_defaults.brush.width_km),
            "height": tk.DoubleVar(value=authoring_defaults.height.radius_km),
            "ridge": tk.DoubleVar(value=authoring_defaults.ridge.radius_km),
            "valley": tk.DoubleVar(value=authoring_defaults.valley.radius_km),
        }
        self._brush_intensity_percent = tk.DoubleVar(
            value=authoring_defaults.brush.intensity * 100.0
        )
        self._lake_level = tk.DoubleVar(value=authoring_defaults.lake.water_level_m)
        self._lake_outlet = tk.BooleanVar(value=authoring_defaults.lake.outlet_at_first_vertex)
        self._region_character = tk.StringVar(value="plain")
        self._region_values = {
            name: tk.DoubleVar(value=float(getattr(authoring_defaults.region, name)))
            for name in ("elevation_m", "relief_m", "feature_size_km", "transition_km",
                         "orientation_deg")
        }
        self._render_style_label = tk.StringVar(value="Cartographic relief")
        self._show_instructions = tk.BooleanVar(value=True)
        self._show_drainage = tk.BooleanVar(value=False)
        self._show_depressions = tk.BooleanVar(value=False)
        self._all_channels = tk.BooleanVar(value=False)
        self._show_catchments = tk.BooleanVar(value=False)
        self._review_photo: ImageTk.PhotoImage | None = None
        self._review_image: Image.Image | None = None
        self._review_key: tuple[int, bool, bool, bool] | None = None
        self._legend_swatches: list[tk.Frame] = []
        self._brush_cursor: tuple[float, float] | None = None
        self._active_brush_values: tuple[float, float, float, ElevationMode] | None = None
        self._tool_buttons: dict[str, tk.Button] = {}
        self._authoring_widgets: list[tk.Widget] = []
        self._authoring_enabled = False

        configure_styles(self.root)
        self._build_layout()
        for key, variable in self._variables.items():
            variable.trace_add("write", partial(self._on_settings_changed, key))
        for variable in (*self._tool_modes.values(), *self._tool_elevations.values(),
                         *self._tool_sizes.values(), self._brush_intensity_percent,
                         self._lake_level, self._lake_outlet, self._region_character,
                         *self._region_values.values()):
            variable.trace_add("write", self._refresh_document_state)
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self._request_close)
        self._set_busy(False)
        self._poll_after_id = self.root.after(80, self._poll_events)
        if project is not None:
            self.workspaces.select(self.terrain_page)
            self.root.after_idle(partial(self._load_project, project))
        elif world is not None:
            self.root.after_idle(partial(self.world_workspace.load_world, world))

    def _build_layout(self) -> None:
        self.workspaces = ttk.Notebook(self.root, style="Workspaces.TNotebook")
        self.workspaces.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.world_workspace = WorldWorkspace(
            self.workspaces, self._refresh_document_state, self._accept_world_terrain,
        )
        self.workspaces.add(self.world_workspace, text="  World  ")
        page = self.terrain_page = ttk.Frame(
            self.workspaces, style="Paper.TFrame", padding=(18, 12, 18, 16))
        self.workspaces.add(page, text="  Terrain  ")
        self.workspaces.bind(
            "<<NotebookTabChanged>>", lambda _event: self._refresh_document_state())
        page.columnconfigure(1, weight=1)
        page.rowconfigure(1, weight=1)

        header = ttk.Frame(page, style="Paper.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        ttk.Label(header, text="DM TOOLS  /  LOCAL TERRAIN", style="Eyebrow.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, text="Terrain workspace", style="Header.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Author instructions over a read-only reference, then regenerate. "
                 "World-linked terrain follows shared context.",
            style="Eyebrow.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(3, 0))

        controls = ttk.Frame(page, style="Panel.TFrame", padding=(18, 18))
        controls.grid(row=1, column=0, sticky="nsw", padx=(0, 16))
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(0, weight=1)
        settings_shell = ttk.Frame(controls, style="Panel.TFrame")
        settings_shell.grid(row=0, column=0, sticky="nsew")
        settings_shell.columnconfigure(0, weight=1)
        settings_shell.rowconfigure(0, weight=1)
        settings_canvas = tk.Canvas(
            settings_shell, width=340, height=1, background=PANEL, highlightthickness=0)
        settings_canvas.grid(row=0, column=0, sticky="nsew")
        def scroll_settings(*args: str) -> None:
            settings_canvas.yview(*args)
        settings_scrollbar = ttk.Scrollbar(
            settings_shell, orient="vertical", command=scroll_settings)
        settings_scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
        settings_panel = ttk.Frame(settings_canvas, style="Panel.TFrame")
        settings_panel.columnconfigure(0, weight=1)
        settings_window = settings_canvas.create_window(0, 0, window=settings_panel, anchor="nw")
        settings_canvas.bind("<Configure>", lambda event: settings_canvas.itemconfigure(
            settings_window, width=event.width))
        settings_panel.bind("<Configure>", lambda _event: settings_canvas.configure(
            scrollregion=settings_canvas.bbox("all")))
        self._build_import_panel(settings_panel)
        for row, spec in enumerate(_CONTROLS, start=2):
            self._build_numeric_control(settings_panel, row, spec)
        # Keep Generate and export visible even when the settings panel needs scrolling.
        self._build_actions(controls, 1)

        preview_shell = tk.Frame(
            page, background=INK, highlightthickness=1, highlightbackground="#28383a"
        )
        preview_shell.grid(row=1, column=1, sticky="nsew")
        preview_shell.rowconfigure(2, weight=1)
        preview_shell.columnconfigure(0, weight=1)
        self._build_preview(preview_shell)

    def _build_import_panel(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top.columnconfigure((0, 1), weight=1)
        ttk.Label(top, text="COASTLINE SOURCE", style="Value.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.source_label = ttk.Label(
            top, text="No land geometry loaded", style="Muted.TLabel", width=34
        )
        self.source_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 7))
        self.import_button = ttk.Button(
            top, text="Import SVG…", style="Quiet.TButton", command=self._choose_svg
        )
        self.import_button.grid(row=2, column=0, sticky="ew")
        self.open_project_button = ttk.Button(
            top, text="Open project…", style="Quiet.TButton", command=self._choose_project
        )
        self.open_project_button.grid(row=2, column=1, sticky="ew", padx=(6, 0))
        self.save_project_button = ttk.Button(
            top,
            text="Save",
            style="Quiet.TButton",
            state="disabled",
            command=self._save_project,
        )
        self.save_project_button.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.save_as_button = ttk.Button(
            top, text="Save As…", style="Quiet.TButton", state="disabled",
            command=lambda: self._save_project(save_as=True))
        self.save_as_button.grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        ttk.Separator(parent).grid(row=1, column=0, sticky="ew", pady=(0, 9))

    def _build_numeric_control(self, parent: ttk.Frame, row: int, spec: _ControlSpec) -> None:
        container = ttk.Frame(parent, style="Panel.TFrame")
        container.grid(row=row, column=0, sticky="ew", pady=3)
        container.columnconfigure(0, weight=1)
        variable = tk.DoubleVar(value=spec.default)
        self._variables[spec.key] = variable

        ttk.Label(container, text=spec.label, style="Body.TLabel").grid(row=0, column=0, sticky="w")
        value_label = ttk.Label(container, style="Value.TLabel", width=14, anchor="e")
        value_label.grid(row=0, column=1, sticky="e")
        self._value_labels[spec.key] = value_label

        scale = ttk.Scale(
            container,
            from_=spec.minimum,
            to=spec.maximum,
            variable=variable,
            command=lambda _value, key=spec.key: self._refresh_value(key),
        )
        scale.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        spinbox = ttk.Spinbox(
            container,
            from_=spec.minimum,
            to=spec.maximum,
            increment=spec.increment,
            textvariable=variable,
            width=10,
            command=lambda key=spec.key: self._refresh_value(key),
        )
        spinbox.grid(row=1, column=1, sticky="e")
        self._settings_widgets.extend((scale, spinbox))
        if spec.key == "object_scale_km":
            self._world_scale_widgets.extend((scale, spinbox))
        if spec.key == "resolution_px":
            presets = ttk.Frame(container, style="Panel.TFrame")
            presets.grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
            for label, resolution in (("Quick test · 257 px", 257), ("Detail · 1025 px", 1025)):
                button = ttk.Button(presets, text=label, style="Quiet.TButton",
                                    command=partial(self._set_resolution, resolution))
                button.pack(side="left", padx=(0, 4))
                self._settings_widgets.append(button)
        spinbox.bind("<FocusOut>", lambda _event, key=spec.key: self._refresh_value(key))
        spinbox.bind("<Return>", lambda _event, key=spec.key: self._refresh_value(key))
        self._refresh_value(spec.key)

    def _set_resolution(self, resolution: int) -> None:
        self._variables["resolution_px"].set(resolution)
        self._refresh_value("resolution_px")

    def _build_actions(self, parent: ttk.Frame, row: int) -> None:
        ttk.Separator(parent).grid(row=row, column=0, sticky="ew", pady=(12, 12))
        buttons = ttk.Frame(parent, style="Panel.TFrame")
        buttons.grid(row=row + 1, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        self.generate_button = ttk.Button(
            buttons, text="Generate terrain", style="Accent.TButton",
            command=self._generate_or_cancel
        )
        self.generate_button.grid(row=0, column=0, sticky="ew")
        self.export_button = ttk.Button(
            buttons,
            text="Export PNG…",
            style="Quiet.TButton",
            state="disabled",
            command=self._export,
        )
        self.export_button.grid(row=0, column=1, padx=(8, 0))

        self.progress = ttk.Progressbar(
            parent, style="Accent.Horizontal.TProgressbar", mode="determinate", maximum=100
        )
        self.progress.grid(row=row + 2, column=0, sticky="ew", pady=(12, 0))
        self.status_label = ttk.Label(
            parent, text="Import closed SVG land shapes to begin.", style="Muted.TLabel",
            wraplength=300, justify="left",
        )
        self.status_label.grid(row=row + 3, column=0, sticky="w", pady=(6, 0))

    def _build_preview(self, parent: tk.Frame) -> None:
        toolbar_container = tk.Frame(parent, background=INK)
        toolbar_container.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        toolbar = tk.Frame(toolbar_container, background=INK)
        toolbar.pack(fill="x")
        tk.Label(
            toolbar,
            text="GENERATION REFERENCE",
            background=INK,
            foreground="#dce8e3",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        review_toolbar = tk.Frame(toolbar_container, background=INK)
        review_toolbar.pack(fill="x", pady=(6, 0))
        tk.Checkbutton(
            review_toolbar, text="Drainage review", variable=self._show_drainage,
            command=self._draw_preview, background=INK, foreground="#dce8e3",
            selectcolor=INK, activebackground=INK, activeforeground="white",
        ).pack(side="left", padx=10)
        tk.Checkbutton(
            review_toolbar, text="All channels", variable=self._all_channels,
            command=self._draw_preview, background=INK, foreground="#dce8e3",
            selectcolor=INK, activebackground=INK, activeforeground="white",
        ).pack(side="left", padx=(0, 10))
        tk.Checkbutton(
            review_toolbar, text="Depressions", variable=self._show_depressions,
            command=self._draw_preview, background=INK, foreground="#dce8e3",
            selectcolor=INK, activebackground=INK, activeforeground="white",
        ).pack(side="left", padx=(0, 10))
        tk.Checkbutton(
            review_toolbar, text="Basin catchments", variable=self._show_catchments,
            command=self._draw_preview, background=INK, foreground="#dce8e3",
            selectcolor=INK, activebackground=INK, activeforeground="white",
        ).pack(side="left", padx=(0, 10))
        tk.Button(review_toolbar, text="Basin details", command=self._show_basin_details,
                  background="#2c3e40", foreground="#dce8e3", relief="flat").pack(side="left")
        navigation = tk.Frame(toolbar_container, background=INK)
        navigation.pack(fill="x", pady=(5, 0))
        for text, command in (("Fit", self._fit_view),
                              ("-", partial(self._zoom_view, 1 / 1.5)),
                              ("+", partial(self._zoom_view, 1.5))):
            tk.Button(navigation, text=text, command=command, width=3, relief="flat",
                      background="#2c3e40", foreground="#dce8e3").pack(side="left", padx=2)
        self.zoom_label = tk.Label(navigation, text="1x fit", background=INK,
                                   foreground="#dce8e3", font=("Consolas", 9), justify="left")
        self.zoom_label.pack(side="left", padx=8)
        tk.Checkbutton(navigation, text="Instructions", variable=self._show_instructions,
                       command=self._draw_preview, background=INK, foreground="#dce8e3",
                       selectcolor=INK, activebackground=INK,
                       activeforeground="white").pack(side="left")
        self.preview_meta = tk.Label(
            toolbar_container,
            text="Awaiting land geometry", anchor="w", justify="left",
            background=INK,
            foreground="#80918e",
            font=("Consolas", 9),
        )
        self.preview_meta.pack(fill="x", pady=(4, 0))
        self.reference_label = tk.Label(
            toolbar_container, text="No generated reference. Draw instructions, then generate.",
            background=INK, foreground="#dce8e3", font=("Segoe UI", 9, "bold"),
            anchor="w", justify="left",
        )
        self.reference_label.pack(fill="x", pady=(5, 0))
        def wrap_preview_labels(event: tk.Event[tk.Misc]) -> None:
            for label in (self.preview_meta, self.reference_label):
                label.configure(wraplength=max(180, event.width - 4))
        toolbar_container.bind("<Configure>", wrap_preview_labels)
        self.render_style_input = ttk.Combobox(
            toolbar,
            values=tuple(_RENDER_STYLE_LABELS),
            textvariable=self._render_style_label,
            width=20,
            state="readonly",
            font=("Segoe UI", 8),
        )
        self.render_style_input.pack(side="right", padx=(12, 0))
        self.render_style_input.bind("<<ComboboxSelected>>", self._on_render_style_changed)
        tk.Label(
            toolbar,
            text="STYLE",
            background=INK,
            foreground="#80918e",
            font=("Consolas", 8, "bold"),
        ).pack(side="right", padx=(12, 0))

        authoring = tk.Frame(parent, background="#203033", padx=10, pady=8)
        authoring.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        authoring.columnconfigure(0, weight=1)
        tools_row = tk.Frame(authoring, background="#203033")
        tools_row.grid(row=0, column=0, columnspan=9, sticky="ew")

        self.select_button = tk.Button(
            tools_row, text="Select", command=self._set_selection_mode, relief="flat",
            padx=7, pady=5, font=("Segoe UI", 8, "bold"))
        self.select_button.pack(side="left", padx=(0, 5))
        self._authoring_widgets.append(self.select_button)
        for tool, label in (
            ("brush", "Brush"), ("height", "Height"), ("ridge", "Ridge"),
            ("valley", "Valley"), ("region", "Region"), ("lake", "Lake"),
            ("dry_basin", "Dry basin"),
        ):
            button = tk.Button(
                tools_row,
                text=label,
                command=lambda selected=tool: self._set_authoring_tool(selected),
                relief="flat",
                borderwidth=0,
                padx=5,
                pady=5,
                cursor="hand2",
                font=("Segoe UI", 8, "bold"),
            )
            button.pack(side="left", padx=1)
            self._tool_buttons[tool] = button
            self._authoring_widgets.append(button)

        actions = tk.Frame(tools_row, background="#203033")
        actions.pack(side="left", padx=(4, 0))
        self.finish_line_button = tk.Button(
            actions,
            text="Finish line",
            command=self._finish_structure,
            relief="flat",
            borderwidth=0,
            padx=8,
            pady=5,
            font=("Segoe UI", 8),
        )
        self.finish_line_button.pack(side="left", padx=2)
        self._authoring_widgets.append(self.finish_line_button)
        self._build_instruction_controls(authoring)

        self._feature_parameters = tk.Frame(authoring, background="#203033")
        self._feature_parameters.grid(row=1, column=0, columnspan=9, sticky="w", pady=(7, 0))
        parameters = tk.Frame(self._feature_parameters, background="#203033")
        parameters.pack(anchor="w")
        tk.Label(
            parameters,
            text="Mode",
            background="#203033",
            foreground="#a9bab7",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(0, 4))
        self.mode_input = ttk.Combobox(
            parameters,
            values=("Absolute", "Relative"),
            textvariable=self._tool_modes["brush"],
            width=9,
            state="readonly",
            font=("Segoe UI", 8),
        )
        self.mode_input.pack(side="left")
        self.mode_input.bind("<<ComboboxSelected>>", self._on_elevation_mode_changed)
        self.value_label = tk.Label(
            parameters,
            text="Height offset",
            background="#203033",
            foreground="#a9bab7",
            font=("Segoe UI", 8),
        )
        self.value_label.pack(side="left", padx=(12, 4))
        self.value_input = tk.Spinbox(
            parameters,
            from_=-10_000,
            to=10_000,
            increment=100,
            textvariable=self._tool_elevations["brush"],
            width=7,
            justify="right",
            font=("Consolas", 8),
        )
        self.value_input.pack(side="left")
        self._authoring_widgets.append(self.value_input)
        tk.Label(
            parameters,
            text="m",
            background="#203033",
            foreground="#a9bab7",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(3, 12))
        parameters = tk.Frame(self._feature_parameters, background="#203033")
        parameters.pack(anchor="w", pady=(5, 0))
        self.width_label = tk.Label(
            parameters,
            text="Influence radius",
            background="#203033",
            foreground="#a9bab7",
            font=("Segoe UI", 8),
        )
        self.width_label.pack(side="left", padx=(0, 4))
        self.width_input = tk.Spinbox(
            parameters,
            from_=1,
            to=4_000,
            increment=10,
            textvariable=self._tool_sizes["brush"],
            width=7,
            justify="right",
            font=("Consolas", 8),
        )
        self.width_input.pack(side="left")
        self._authoring_widgets.append(self.width_input)
        tk.Label(
            parameters,
            text="km",
            background="#203033",
            foreground="#a9bab7",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(3, 12))
        tk.Label(
            parameters,
            text="Brush strength",
            background="#203033",
            foreground="#a9bab7",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(0, 4))
        self.brush_strength_input = tk.Spinbox(
            parameters,
            from_=5,
            to=100,
            increment=5,
            textvariable=self._brush_intensity_percent,
            width=5,
            justify="right",
            font=("Consolas", 8),
        )
        self.brush_strength_input.pack(side="left")
        self._authoring_widgets.append(self.brush_strength_input)
        tk.Label(
            parameters,
            text="%",
            background="#203033",
            foreground="#a9bab7",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(3, 0))

        self._region_parameters = tk.Frame(authoring, background="#203033")
        self._region_parameters.grid(row=1, column=0, columnspan=9, sticky="w", pady=(7, 0))
        self._region_character_input = ttk.Combobox(
            self._region_parameters, textvariable=self._region_character,
            values=("plain", "hills", "plateau", "mountains"), width=12, state="readonly",
        )
        self._region_character_input.grid(row=0, column=0, padx=(0, 8))
        self._region_character_input.bind("<<ComboboxSelected>>", self._on_region_character)
        for index, (key, label, upper) in enumerate((
            ("elevation_m", "Base height m", 10000),
            ("relief_m", "Relief m", 10000),
            ("feature_size_km", "Feature size km", 4000),
            ("transition_km", "Transition km", 2000),
            ("orientation_deg", "Direction deg", 179),
        )):
            row, column = divmod(index, 2)
            frame = tk.Frame(self._region_parameters, background="#203033")
            frame.grid(row=row, column=column + 1, padx=6, pady=3, sticky="w")
            tk.Label(frame, text=label, background="#203033", foreground="#a9bab7",
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
            entry = tk.Spinbox(frame, textvariable=self._region_values[key], width=6,
                               from_=1 if key.endswith("_km") else 0, to=upper,
                               increment=1 if key == "orientation_deg" else 10)
            entry.pack(side="left")
            self._authoring_widgets.append(entry)
        self._region_parameters.grid_remove()

        self._lake_parameters = tk.Frame(authoring, background="#203033")
        self._lake_parameters.grid(row=1, column=0, columnspan=9, sticky="w", pady=(7, 0))
        tk.Label(self._lake_parameters, text="Water level (m)", background="#203033",
                 foreground="#a9bab7").pack(side="left", padx=(0, 6))
        lake_level = tk.Spinbox(self._lake_parameters, textvariable=self._lake_level,
                               from_=0, to=12000, increment=10, width=9)
        lake_level.pack(side="left")
        lake_outlet = tk.Checkbutton(
            self._lake_parameters, text="Outlet enabled (new: first vertex)",
            variable=self._lake_outlet,
            background="#203033", foreground="#d6e0dd", selectcolor="#142022",
        )
        lake_outlet.pack(side="left", padx=12)
        self._authoring_widgets.extend((lake_level, lake_outlet))
        self._lake_parameters.grid_remove()

        self.authoring_hint = tk.Label(
            authoring,
            text="Import land geometry to start drawing.", anchor="w", justify="left",
            background="#203033",
            foreground="#8fa5a1",
            font=("Segoe UI", 8),
        )
        self.authoring_hint.grid(row=2, column=0, columnspan=9, sticky="ew", pady=(6, 0))
        authoring.bind("<Configure>", lambda event: self.authoring_hint.configure(
            wraplength=max(180, event.width - 24)))

        content = tk.Frame(parent, background=INK)
        content.grid(row=2, column=0, sticky="nsew", padx=(16, 12), pady=(0, 14))
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        self.preview = tk.Canvas(content, background=MAP_BACKGROUND, highlightthickness=0)
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.preview.create_text(
            20,
            20,
            text="Import SVG land shapes\nto establish the land mask.",
            anchor="nw",
            fill="#71817e",
            font=("Segoe UI", 14),
        )
        self.preview.bind("<Configure>", lambda _event: self._draw_preview())
        self.preview.bind("<ButtonPress-1>", self._on_map_press)
        self.preview.bind("<Control-Button-1>", self._select_on_map)
        self.preview.bind("<B1-Motion>", self._on_map_drag)
        self.preview.bind("<ButtonPress-2>", self._begin_pan)
        self.preview.bind("<B2-Motion>", self._pan_view)
        self.preview.bind("<ButtonRelease-2>", self._end_pan)
        self.preview.bind("<Return>", lambda _event: self._accept_edit())
        self.preview.bind("<ButtonRelease-1>", self._on_map_release)
        self.preview.bind("<Motion>", self._on_map_motion)
        self.preview.bind("<Leave>", self._on_map_leave)
        self.preview.bind("<MouseWheel>", self._on_map_wheel)
        self.preview.bind("<Button-3>", lambda _event: self._finish_structure())

        self.cursor_label = tk.Label(
            content, text="Wheel: zoom · Middle drag or Space+drag: pan · F: fit",
            background=INK, foreground="#9eaaa8", anchor="w", font=("Consolas", 8))
        self.cursor_label.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        content.bind("<Configure>", lambda event: self.cursor_label.configure(
            wraplength=max(180, event.width - 50)))
        legend = tk.Frame(content, background=INK, width=64)
        legend.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        self._legend_high_label = tk.Label(
            legend,
            text="10 km",
            background=INK,
            foreground="#9eaaa8",
            font=("Segoe UI", 7, "bold"),
        )
        self._legend_high_label.pack()
        for colour in elevation_legend_colours():
            swatch = tk.Frame(legend, background=colour, width=22, height=34)
            swatch.pack()
            self._legend_swatches.append(swatch)
        tk.Label(
            legend,
            text="0 m",
            background=INK,
            foreground="#9eaaa8",
            font=("Segoe UI", 7, "bold"),
        ).pack(pady=(3, 0))
        def fit_legend(event: tk.Event[tk.Misc]) -> None:
            height = max(1, min(34, (event.height - 46) // len(self._legend_swatches)))
            for swatch in self._legend_swatches:
                swatch.configure(height=height)
        content.bind("<Configure>", fit_legend, add="+")
        self._set_authoring_enabled(False)
        self._set_authoring_tool("brush")

    @property
    def _constraints(self) -> tuple[TerrainConstraint, ...]:
        return self._history.constraints

    def _build_instruction_controls(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, background="#203033")
        row.grid(row=3, column=0, columnspan=9, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        self.instruction_input = ttk.Combobox(row, width=27, state="disabled")
        self.instruction_input.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.instruction_input.bind("<<ComboboxSelected>>", self._on_instruction_selected)
        self.apply_instruction_button: tk.Button
        self.delete_instruction_button: tk.Button
        self.undo_constraint_button: tk.Button
        self.redo_constraint_button: tk.Button
        self.clear_constraints_button: tk.Button
        self.structure_profile_button: tk.Button
        for column, (name, label, command) in enumerate((
            ("apply_instruction_button", "Apply edit", self._apply_instruction),
            ("structure_profile_button", "Profile...", self._edit_structure_profile),
            ("delete_instruction_button", "Delete", self._delete_instruction),
            ("undo_constraint_button", "Undo", self._undo_constraint),
            ("redo_constraint_button", "Redo", self._redo_constraint),
            ("clear_constraints_button", "Clear", self._clear_constraints),
        ), start=1):
            button = tk.Button(row, text=label, command=command, relief="flat",
                               background="#2c3e40", foreground="#dce8e3", padx=8, pady=4)
            button.grid(row=0, column=column, padx=2)
            setattr(self, name, button)
            self._authoring_widgets.append(button)

    def _instruction_label(self, index: int, constraint: TerrainConstraint) -> str:
        if isinstance(constraint, TerrainRegion):
            description = f"{constraint.settings.character.title()} region"
        elif isinstance(constraint, TerrainBasin):
            description = (f"Lake {constraint.water_level_m:,.0f} m"
                           if constraint.water_level_m is not None else "Dry basin")
        else:
            kind = ("Height" if isinstance(constraint, ElevationPoint) else
                    "Brush" if isinstance(constraint, TerrainBrushStroke)
                    else constraint.kind.title())
            description = f"{kind} {constraint.elevation_m:,.0f} m {constraint.elevation_mode}"
        if isinstance(constraint, TerrainStructure) and constraint.profile:
            description += f" · {len(constraint.profile)} profile knots"
        return f"{index + 1}. {description}"

    def _refresh_instruction_controls(self) -> None:
        self.instruction_input.configure(
            values=("New instruction / cancel edit", *(
                self._instruction_label(index, item) for index, item in enumerate(self._constraints)
            )), state="readonly" if self._authoring_enabled else "disabled",
        )
        index = self._selected_instruction
        self.instruction_input.current(0 if index is None else index + 1)
        selected = self._authoring_enabled and index is not None
        dry_basin = (index is not None and isinstance(self._constraints[index], TerrainBasin)
                     and self._authoring_tool.get() == "dry_basin")
        self.apply_instruction_button.configure(
            state="normal" if selected and not dry_basin else "disabled")
        self.delete_instruction_button.configure(state="normal" if selected else "disabled")
        self.structure_profile_button.configure(
            state="normal" if selected and index is not None
            and isinstance(self._constraints[index], TerrainStructure)
            else "disabled")
        self.redo_constraint_button.configure(
            state="normal" if self._authoring_enabled and self._history.can_redo
            and not self._draft_points else "disabled")

    def _on_instruction_selected(self, _event: tk.Event[tk.Misc]) -> None:
        index = self.instruction_input.current() - 1
        if index < 0:
            self._set_authoring_tool(self._authoring_tool.get())
        else:
            self._select_instruction(index)

    def _select_instruction(self, index: int) -> None:
        if not self._authoring_enabled:
            return
        self._draft_points.clear()
        self._active_brush_values = None
        self._brush_cursor = None
        self._syncing_selection = True
        self._drag_origin = None
        self._drag_candidate = None
        self._selected_instruction = index
        self._selection_mode = True
        self._show_instructions.set(True)
        constraint = self._constraints[index]
        if isinstance(constraint, TerrainRegion):
            tool = "region"
            self._region_character.set(constraint.settings.character)
            for key, value in self._region_values.items():
                value.set(float(getattr(constraint.settings, key)))
        elif isinstance(constraint, TerrainBasin):
            tool = constraint.kind
            if constraint.water_level_m is not None:
                self._lake_level.set(constraint.water_level_m)
            self._lake_outlet.set(constraint.outlet is not None)
        else:
            tool = ("height" if isinstance(constraint, ElevationPoint) else
                    "brush" if isinstance(constraint, TerrainBrushStroke) else constraint.kind)
            self._tool_modes[tool].set(constraint.elevation_mode.title())
            self._tool_elevations[tool].set(constraint.elevation_m)
            self._tool_sizes[tool].set(
                constraint.influence_radius_km * (2 if tool == "brush" else 1))
            if isinstance(constraint, TerrainBrushStroke):
                self._brush_intensity_percent.set(constraint.intensity * 100)
        self._authoring_tool.set(tool)
        self._syncing_selection = False
        self._refresh_authoring_controls()
        self.status_label.configure(
            text="Drag a white handle or the instruction itself. Edit properties, then Apply.")
        self._draw_preview()

    def _instruction_at(self, x: float, y: float) -> int | None:
        if not self._show_instructions.get():
            return None
        point = Point(x, y)
        candidates: list[tuple[float, int]] = []
        for index, constraint in enumerate(self._constraints):
            if isinstance(constraint, ElevationPoint):
                distance = point.distance(Point(self._normalized_to_canvas(constraint.position)))
            else:
                points = [self._normalized_to_canvas(p) for p in constraint.points]
                if isinstance(constraint, (TerrainRegion, TerrainBasin)):
                    holes = ([
                        [self._normalized_to_canvas(p) for p in ring] for ring in constraint.holes
                    ] if isinstance(constraint, TerrainRegion) else [])
                    geometry = Polygon(points, holes)
                    distance = point.distance(geometry.boundary)
                    if geometry.covers(point):
                        distance = min(distance, 8.)
                else:
                    geometry = LineString(points) if len(points) > 1 else Point(points[0])
                    distance = point.distance(geometry)
            if distance <= 10:
                candidates.append((distance, -index))
        return -min(candidates)[1] if candidates else None

    def _select_on_map(self, event: tk.Event[tk.Misc]) -> str:
        if self._authoring_enabled:
            self.preview.focus_set()
            index = self._instruction_at(float(event.x), float(event.y))
            if index is not None:
                self._select_instruction(index)
            else:
                self.status_label.configure(text="Choose an instruction on the map or in the list.")
        return "break"

    def _set_selection_mode(self) -> None:
        self._cancel_edit()
        self._selection_mode = True
        self._show_instructions.set(True)
        self._refresh_authoring_controls()
        self._draw_preview()

    def _begin_instruction_drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._has_pending_instruction():
            self.status_label.configure(text="Apply the current properties or press Esc first.")
            return
        position = self._canvas_to_normalized(float(event.x), float(event.y))
        if position is None or not self._show_instructions.get():
            return
        vertex: int | None = None
        index = self._selected_instruction
        if index is not None:
            instruction = self._constraints[index]
            points = instruction_vertices(instruction)
            for i, point in enumerate(points):
                x, y = self._normalized_to_canvas(point)
                if hypot(x - event.x, y - event.y) <= 8:
                    vertex = i
                    break
        if vertex is None:
            index = self._instruction_at(float(event.x), float(event.y))
        if index is None:
            self._selected_instruction = None
            self._refresh_authoring_controls()
            self._draw_preview()
            return
        self._select_instruction(index)
        self._drag_origin = float(event.x), float(event.y)
        self._drag_vertex = vertex
        self._drag_candidate = self._constraints[index]
        self._drag_error = None

    def _drag_instruction(self, event: tk.Event[tk.Misc]) -> None:
        if self._drag_origin is None or self._selected_instruction is None:
            return
        position = self._canvas_to_normalized(float(event.x), float(event.y))
        self._drag_candidate = None
        self._drag_error = "Keep the instruction inside the map bounds."
        if position is not None:
            rect = self._map_rect()
            assert rect is not None
            delta = ((event.x - self._drag_origin[0]) / (rect[2] - rect[0]),
                     (event.y - self._drag_origin[1]) / (rect[3] - rect[1]))
            try:
                self._drag_candidate = move_instruction(
                    self._constraints[self._selected_instruction], delta, self._drag_vertex)
                self._drag_error = None
            except ValueError as error:
                self._drag_error = str(error)
        self._draw_preview()

    def _finish_instruction_drag(self, event: tk.Event[tk.Misc]) -> None:
        self._drag_instruction(event)
        candidate, error, index = self._drag_candidate, self._drag_error, self._selected_instruction
        self._drag_origin = None
        self._drag_candidate = None
        self._drag_error = None
        if candidate is not None and index is not None:
            try:
                self._validate_instruction_geometry(candidate, excluding=index)
            except ValueError as caught:
                error = str(caught)
            else:
                changed = candidate != self._constraints[index]
                self._history.replace(index, candidate)
                self._instructions_changed("Instruction moved. Regenerate to see its effect."
                                           if changed else "Instruction selected.")
                return
        self.status_label.configure(text=f"Move rejected: {error}")
        self._draw_preview()

    def _validate_instruction_geometry(
        self, instruction: TerrainConstraint, *, excluding: int | None = None,
    ) -> None:
        if self._coast_polygon is None:
            raise ValueError("Load land geometry first.")
        if isinstance(instruction, ElevationPoint):
            geometry = Point(self._normalized_to_source(instruction.position))
        else:
            points = [self._normalized_to_source(point) for point in instruction.points]
            if isinstance(instruction, (TerrainRegion, TerrainBasin)):
                holes = ([
                    [self._normalized_to_source(p) for p in ring] for ring in instruction.holes
                ] if isinstance(instruction, TerrainRegion) else [])
                geometry = Polygon(points, holes)
                if not geometry.is_valid or geometry.area <= 0:
                    raise ValueError("Use a simple polygon without crossing edges.")
                if isinstance(instruction, TerrainRegion):
                    if geometry.intersection(self._coast_polygon).area <= 0:
                        raise ValueError("The region must cover some land.")
                    return
                for i, other in enumerate(self._constraints):
                    if (i != excluding and isinstance(other, TerrainBasin)
                            and geometry.intersects(Polygon([
                                self._normalized_to_source(point) for point in other.points
                            ]))):
                        raise ValueError("Basin areas must not overlap or touch.")
                if instruction.outlet is not None:
                    # Match the normalized-boundary contract, independent of SVG scale.
                    boundary = Polygon(instruction.points).boundary
                    if boundary.distance(Point(instruction.outlet)) > 1e-9:
                        raise ValueError("The lake outlet must lie on its boundary.")
            else:
                geometry = LineString(points) if len(points) > 1 else Point(points[0])
        if not self._coast_polygon.covers(geometry):
            raise ValueError("The instruction must stay on land and exclude water holes.")

    def _edited_instruction(self) -> TerrainConstraint:
        index = self._selected_instruction
        if index is None:
            raise ValueError("Select an instruction first.")
        constraint = self._constraints[index]
        if isinstance(constraint, TerrainRegion):
            settings = self._read_region_settings()
            if settings.elevation_m > self._variables["maximum_elevation_m"].get():
                raise ValueError("Regional base height exceeds the elevation ceiling.")
            return replace(constraint, settings=settings)
        if isinstance(constraint, TerrainBasin):
            if constraint.kind == "dry_basin":
                return constraint
            level = float(self._lake_level.get())
            if level > self._variables["maximum_elevation_m"].get():
                raise ValueError("Water level exceeds the elevation ceiling.")
            # Preserve an imported outlet away from the first vertex unless disabled.
            outlet = ((constraint.outlet or constraint.points[0])
                      if self._lake_outlet.get() else None)
            return replace(constraint, water_level_m=level, outlet=outlet)
        tool = self._authoring_tool.get()
        elevation = float(self._tool_elevations[tool].get())
        radius = float(self._tool_sizes[tool].get()) / (2 if tool == "brush" else 1)
        mode = self._selected_elevation_mode(tool)
        if (isinstance(constraint, TerrainStructure) and constraint.profile
                and mode != constraint.elevation_mode):
            raise ValueError("Clear the line profile before changing its elevation mode.")
        if isinstance(constraint, TerrainBrushStroke):
            return replace(constraint, elevation_m=elevation, influence_radius_km=radius,
                           elevation_mode=mode, intensity=self._brush_intensity_percent.get() / 100)
        return replace(constraint, elevation_m=elevation, influence_radius_km=radius,
                       elevation_mode=mode)

    def _has_pending_instruction(self) -> bool:
        if self._draft_points or self._drag_origin is not None:
            return True
        if self._selected_instruction is None:
            return False
        try:
            return self._edited_instruction() != self._constraints[self._selected_instruction]
        except (ValueError, tk.TclError):
            return True

    def _apply_instruction(self) -> None:
        if not self._authoring_enabled or self._selected_instruction is None:
            return
        try:
            updated = self._edited_instruction()
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Invalid instruction", str(error), parent=self.root)
            return
        self._history.replace(self._selected_instruction, updated)
        self._instructions_changed("Instruction updated. Regenerate to see its effect.")

    def _edit_structure_profile(self) -> None:
        index = self._selected_instruction
        if not self._authoring_enabled or index is None:
            return
        try:
            candidate = self._edited_instruction()
            if not isinstance(candidate, TerrainStructure):
                return
            updated = edit_structure_profile(
                self.root, candidate, float(self._variables["maximum_elevation_m"].get()))
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Invalid profile", str(error), parent=self.root)
            return
        if updated is not None:
            self._history.replace(index, updated)
            self._select_instruction(index)
            self._instructions_changed(
                "Line profile updated. Regenerate to see peaks, passes or floors.")

    def _delete_instruction(self) -> None:
        if not self._authoring_enabled or self._selected_instruction is None:
            return
        self._history.delete(self._selected_instruction)
        self._selected_instruction = None
        self._instructions_changed("Instruction deleted. Undo restores it; regenerate to update.")

    def _generation_inputs(self) -> GenerationInputs:
        if self._coastline is None:
            raise ValueError("No coastline is loaded.")
        return GenerationInputs(self._coastline, self._read_settings(), self._constraints,
                                self._world_context)

    def _reference_is_current(self) -> bool:
        if self._terrain is None or self._generated_inputs is None:
            return False
        try:
            return self._generation_inputs() == self._generated_inputs
        except (ValueError, tk.TclError):
            return False

    def _refresh_reference_state(self) -> None:
        self._refresh_document_state()
        current = self._reference_is_current()
        if self._terrain is None:
            text = "No generated reference. Draw instructions, then generate."
        elif current:
            text = "Generated map matches the applied inputs. Zoom inspects existing samples."
        else:
            text = "Previous generation shown as reference. Inputs changed — regenerate to update."
        self.reference_label.configure(text=text, foreground="#dce8e3" if current else "#f2c14e")
        self.export_button.configure(
            state="normal" if current and self._authoring_enabled else "disabled")

    def _on_settings_changed(self, key: str, *_args: str) -> None:
        self._refresh_reference_state()
        if key == "object_scale_km":
            self._draw_preview()

    def _selected_render_style(self) -> RenderStyle:
        return _RENDER_STYLE_LABELS.get(self._render_style_label.get(), "cartographic")

    def _replace_preview_layers(
        self, image: Image.Image | None, water: WaterDisplay | None,
    ) -> None:
        previous_image, previous_water = self._image, self._water_display
        self._image, self._water_display = image, water
        if previous_image is not None and previous_image is not image:
            previous_image.close()
        if previous_water is not None and previous_water is not water:
            previous_water.close()

    def _clear_review(self) -> None:
        self._channel_display = None
        if self._review_image is not None:
            self._review_image.close()
        self._review_image = None
        self._review_key = None
        self._review_photo = None

    def _on_render_style_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        style = self._selected_render_style()
        if self._terrain is not None:
            try:
                image, water = render_height_map_layers(self._terrain, style=style)
            except Exception as error:
                # A failed replacement keeps both the previous pixels and their legend.
                previous = (self._image.info.get("dmtools.render_style", "cartographic")
                            if self._image is not None else "cartographic")
                label = next(key for key, value in _RENDER_STYLE_LABELS.items()
                             if value == previous)
                self._render_style_label.set(label)
                messagebox.showerror("Rendering failed", str(error), parent=self.root)
                return
            self._replace_preview_layers(image, water)
        self._legend_high_label.configure(text="10 km" if style == "cartographic" else "MAX")
        for swatch, colour in zip(
            self._legend_swatches, elevation_legend_colours(style=style), strict=True,
        ):
            swatch.configure(background=colour)
        if self._terrain is None:
            return
        self.status_label.configure(
            text=("Cartographic relief ready." if style == "cartographic"
                  else "Scientific elevation view ready.")
        )
        self._draw_preview()

    def _set_authoring_enabled(self, enabled: bool) -> None:
        self._authoring_enabled = enabled
        state = "normal" if enabled else "disabled"
        for widget in self._authoring_widgets:
            widget["state"] = state
        self._refresh_authoring_controls()

    def _set_authoring_tool(self, tool: str) -> None:
        if tool not in ("brush", "height", "ridge", "valley", "region", "lake", "dry_basin"):
            raise ValueError(f"Unknown authoring tool: {tool}")
        if self._draft_points:
            self._draft_points.clear()
            self._active_brush_values = None
            self.status_label.configure(text="Unfinished structure discarded.")
        self._selected_instruction = None
        self._drag_origin = None
        self._drag_candidate = None
        self._selection_mode = False
        self._show_instructions.set(True)
        self._authoring_tool.set(tool)
        self._refresh_authoring_controls()
        self._draw_preview()

    def _selected_elevation_mode(self, tool: str | None = None) -> ElevationMode:
        selected = tool or self._authoring_tool.get()
        value = self._tool_modes[selected].get().lower()
        if value not in ("absolute", "relative"):
            raise ValueError(f"Unknown elevation mode: {value}")
        return value

    def _on_elevation_mode_changed(self, _event: tk.Event[tk.Misc]) -> None:
        self._refresh_authoring_controls()
        self._draw_brush_cursor()

    def _refresh_authoring_controls(self) -> None:
        self._refresh_tool_controls()
        if self._selected_instruction is not None:
            text = (f"Instruction {self._selected_instruction + 1}: drag a white handle or the "
                    "whole shape. Apply property edits; Esc cancels. Regenerate to update terrain.")
            self.authoring_hint.configure(text=text)
        elif self._selection_mode:
            self._feature_parameters.grid_remove()
            self._region_parameters.grid_remove()
            self._lake_parameters.grid_remove()
            self.authoring_hint.configure(
                text="Select an instruction to move it or edit properties. "
                "Choose a drawing tool to add a new one.")
        self.select_button.configure(
            background="#dce8e3" if self._selection_mode else "#2c3e40",
            foreground="#142022" if self._selection_mode else "#d6e0dd")
        self._refresh_document_state()

    def _refresh_tool_controls(self) -> None:
        self._refresh_instruction_controls()
        selected = self._authoring_tool.get()
        colours = {
            "brush": _BRUSH_COLOUR,
            "height": _HEIGHT_COLOUR,
            "ridge": _RIDGE_COLOUR,
            "valley": _VALLEY_COLOUR,
            "region": _REGION_COLOUR,
            "lake": "#65bada",
            "dry_basin": "#d2b487",
        }
        for tool, button in self._tool_buttons.items():
            active = tool == selected and not self._selection_mode
            button.configure(
                background=colours[tool] if active else "#2c3e40",
                foreground="#142022" if active else "#d6e0dd",
                activebackground=colours[tool],
                activeforeground="#142022",
                disabledforeground="#71817e",
            )

        line_ready = ((selected in ("ridge", "valley") and len(self._draft_points) >= 2)
                      or (selected in ("region", "lake", "dry_basin")
                          and len(self._draft_points) >= 3))
        self.finish_line_button.configure(
            text="Finish area" if selected in ("region", "lake", "dry_basin") else "Finish line")
        self.finish_line_button.configure(
            state="normal" if self._authoring_enabled and line_ready else "disabled"
        )
        has_authored_work = bool(self._draft_points or self._constraints)
        self.undo_constraint_button.configure(
            state="normal" if (self._authoring_enabled
                               and (self._draft_points or self._history.can_undo)) else "disabled"
        )
        self.clear_constraints_button.configure(
            state="normal" if self._authoring_enabled and has_authored_work else "disabled"
        )
        self._region_character_input.configure(
            state="readonly" if self._authoring_enabled else "disabled")
        self._lake_parameters.grid_remove()
        if selected in ("lake", "dry_basin"):
            self._feature_parameters.grid_remove()
            self._region_parameters.grid_remove()
            if selected == "lake":
                self._lake_parameters.grid()
            self.authoring_hint.configure(text=(
                "Click 3+ corners, then Finish area. Lake outlet, if enabled, is the first corner."
                if selected == "lake" else
                "Draw a dry-basin area. Automatic cutting is excluded; planned exits are reviewed."
            ))
            return
        if selected == "region":
            self._feature_parameters.grid_remove()
            self._region_parameters.grid()
            self.authoring_hint.configure(text=(
                "Click 3+ corners, then Finish area. Regions affect land only."
                if self._authoring_enabled else "Import land geometry to start drawing."
            ))
            return
        self._region_parameters.grid_remove()
        self._feature_parameters.grid()
        elevation_mode = self._selected_elevation_mode(selected)
        self.mode_input.configure(
            textvariable=self._tool_modes[selected],
            state="readonly" if self._authoring_enabled else "disabled",
        )
        signed_relative = elevation_mode == "relative" and selected in ("brush", "height")
        self.value_input.configure(
            from_=-10_000 if signed_relative else 0,
            to=10_000,
            increment=100,
            textvariable=self._tool_elevations[selected],
        )
        value_labels = {
            ("brush", "absolute"): "Target height",
            ("brush", "relative"): "Height offset",
            ("height", "absolute"): "Exact height",
            ("height", "relative"): "Height offset",
            ("ridge", "absolute"): "Minimum crest",
            ("ridge", "relative"): "Ridge relief",
            ("valley", "absolute"): "Outlet floor",
            ("valley", "relative"): "Valley depth",
        }
        self.value_label.configure(text=value_labels[(selected, elevation_mode)])
        if selected == "brush":
            self.width_label.configure(text="Brush width")
            self.width_input.configure(
                from_=10,
                to=4_000,
                increment=20,
                textvariable=self._tool_sizes[selected],
            )
        else:
            self.width_label.configure(
                text="Influence radius" if selected == "height" else "Core radius"
            )
            self.width_input.configure(
                from_=1,
                to=2_000,
                increment=10,
                textvariable=self._tool_sizes[selected],
            )
        self.brush_strength_input.configure(
            state="normal" if self._authoring_enabled and selected == "brush" else "disabled"
        )

        if not self._authoring_enabled:
            hint = "Import land geometry to start drawing."
        elif selected == "brush":
            action = (
                "toward an absolute height"
                if elevation_mode == "absolute"
                else "a signed height offset for the next generation"
            )
            hint = f"Drag to paint {action}. Shift+wheel: width; Ctrl+Shift+wheel: strength."
        elif selected == "height":
            action = "an exact height" if elevation_mode == "absolute" else "a local height offset"
            hint = f"Click to place {action}; its smooth response extends past the core."
        else:
            feature = "ridge" if selected == "ridge" else "valley"
            behavior = (
                "uses an absolute crest or floor"
                if elevation_mode == "absolute"
                else "adds relief or incision relative to the terrain beneath it"
            )
            direction = " Draw from head toward outlet." if selected == "valley" else ""
            hint = (
                f"Click along the {feature}; Finish line or right-click at 2+ points. "
                f"It {behavior}.{direction}"
            )
        count = len(self._constraints)
        if count:
            hint = f"{count} authored feature{'s' if count != 1 else ''}.  {hint}"
        self.authoring_hint.configure(text=hint)

    def _view_dimensions(self) -> tuple[tuple[float, float], tuple[float, float]]:
        if self._coastline is None:
            raise ValueError("Load a coastline first.")
        x0, y0, x1, y1 = self._coastline.bounds
        return ((max(1., float(self.preview.winfo_width())),
                 max(1., float(self.preview.winfo_height()))), (x1 - x0, y1 - y0))

    def _map_rect(self) -> tuple[float, float, float, float] | None:
        return self._viewport.rect(*self._view_dimensions()) if self._coastline else None

    def _fit_view(self) -> None:
        if self._drag_origin is not None or self._active_brush_values is not None:
            return
        self._viewport.fit()
        self._draw_preview()

    def _zoom_view(self, factor: float, anchor: tuple[float, float] | None = None) -> None:
        if self._coastline is None or self._drag_origin is not None or self._active_brush_values:
            return
        canvas, world = self._view_dimensions()
        self._viewport.zoom_at(factor, anchor or (canvas[0] / 2, canvas[1] / 2), canvas, world)
        self._brush_cursor = None
        self._draw_preview()

    def _begin_pan(self, event: tk.Event[tk.Misc]) -> None:
        if self._coastline is None or self._drag_origin is not None or self._active_brush_values:
            return
        self.preview.focus_set()
        self._pan_start = float(event.x), float(event.y)
        self.preview.configure(cursor="fleur")

    def _pan_view(self, event: tk.Event[tk.Misc]) -> None:
        if self._pan_start is None:
            return
        point = float(event.x), float(event.y)
        self._viewport.pan((point[0] - self._pan_start[0], point[1] - self._pan_start[1]),
                           *self._view_dimensions())
        self._pan_start = point
        self._brush_cursor = None
        self._draw_preview()

    def _end_pan(self, _event: tk.Event[tk.Misc]) -> None:
        self._pan_start = None
        self.preview.configure(cursor="")

    def _normalized_to_source(self, position: tuple[float, float]) -> tuple[float, float]:
        if self._coastline is None:
            raise RuntimeError("No coastline is loaded.")
        min_x, min_y, max_x, max_y = self._coastline.bounds
        return (
            min_x + position[0] * (max_x - min_x),
            min_y + position[1] * (max_y - min_y),
        )

    def _normalized_to_canvas(self, position: tuple[float, float]) -> tuple[float, float]:
        rect = self._map_rect()
        if rect is None:
            raise RuntimeError("No coastline is loaded.")
        left, top, right, bottom = rect
        return (
            left + position[0] * (right - left),
            top + position[1] * (bottom - top),
        )

    def _canvas_to_normalized(self, x: float, y: float) -> tuple[float, float] | None:
        rect = self._map_rect()
        if rect is None:
            return None
        left, top, right, bottom = rect
        if not left <= x <= right or not top <= y <= bottom:
            return None
        return (x - left) / (right - left), (y - top) / (bottom - top)

    def _read_constraint_values(self) -> tuple[float, float, ElevationMode] | None:
        tool = self._authoring_tool.get()
        try:
            elevation_m = float(self._tool_elevations[tool].get())
            radius_km = float(self._tool_sizes[tool].get())
            elevation_mode = self._selected_elevation_mode(tool)
            if elevation_mode == "absolute" and elevation_m < 0:
                raise ValueError("Absolute height must be at or above sea level.")
            if elevation_mode == "relative" and tool in ("ridge", "valley") and elevation_m < 0:
                raise ValueError("Ridge relief and valley depth must not be negative.")
            if radius_km <= 0:
                raise ValueError("Influence must be greater than zero.")
        except (tk.TclError, ValueError) as error:
            messagebox.showerror("Invalid authored feature", str(error), parent=self.root)
            return None
        return elevation_m, radius_km, elevation_mode

    def _read_brush_values(self) -> tuple[float, float, float, ElevationMode] | None:
        try:
            elevation_m = float(self._tool_elevations["brush"].get())
            width_km = float(self._tool_sizes["brush"].get())
            intensity = float(self._brush_intensity_percent.get()) / 100.0
            elevation_mode = self._selected_elevation_mode("brush")
            if elevation_mode == "absolute" and elevation_m < 0:
                raise ValueError("Target height must be at or above sea level.")
            if width_km <= 0:
                raise ValueError("Brush width must be greater than zero.")
            if not 0.0 < intensity <= 1.0:
                raise ValueError("Brush strength must be greater than 0% and at most 100%.")
        except (tk.TclError, ValueError) as error:
            messagebox.showerror("Invalid terrain brush", str(error), parent=self.root)
            return None
        return elevation_m, width_km / 2.0, intensity, elevation_mode

    def _brush_map_position(self, x: float, y: float) -> tuple[float, float] | None:
        if self._coast_polygon is None:
            return None
        position = self._canvas_to_normalized(x, y)
        if position is None:
            return None
        if not self._coast_polygon.covers(Point(self._normalized_to_source(position))):
            return None
        return position

    def _on_map_press(self, event: tk.Event[tk.Misc]) -> None:
        self.preview.focus_set()
        if self._space_pressed:
            self._begin_pan(event)
            return
        if not self._authoring_enabled:
            return
        if not self._show_instructions.get():
            self.status_label.configure(
                text="Show Instructions to draw or select; navigation stays active.")
            return
        if self._selection_mode or self._selected_instruction is not None:
            self._begin_instruction_drag(event)
            return
        if self._authoring_tool.get() != "brush":
            self._on_map_click(event)
            return
        if not self._authoring_enabled:
            return
        position = self._brush_map_position(float(event.x), float(event.y))
        if position is None:
            self.root.bell()
            self.status_label.configure(text="Paint on a land component.")
            return
        values = self._read_brush_values()
        if values is None:
            return
        self._active_brush_values = values
        self._draft_points[:] = [position]
        self._brush_cursor = position
        self.status_label.configure(text="Painting terrain guidance…")
        self._refresh_authoring_controls()
        self._draw_brush_draft()
        self._draw_brush_cursor()

    def _on_map_drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._pan_start is not None:
            self._pan_view(event)
            return
        if self._drag_origin is not None:
            self._drag_instruction(event)
            return
        if self._authoring_tool.get() != "brush" or self._active_brush_values is None:
            return
        position = self._brush_map_position(float(event.x), float(event.y))
        if position is None:
            self._brush_cursor = None
            self._draw_brush_cursor()
            return
        self._brush_cursor = position
        if not self._draft_points:
            self._draft_points.append(position)
        else:
            previous = self._draft_points[-1]
            segment = LineString(
                [self._normalized_to_source(previous), self._normalized_to_source(position)]
            )
            if self._coast_polygon is None or not self._coast_polygon.covers(segment):
                self.status_label.configure(text="The brush centre cannot cross open water.")
                self._draw_brush_cursor()
                return
            previous_canvas = self._normalized_to_canvas(previous)
            radius_km = self._active_brush_values[1]
            spacing = max(2.0, min(16.0, self._influence_radius_pixels(radius_km) * 0.12))
            moved = hypot(
                float(event.x) - previous_canvas[0],
                float(event.y) - previous_canvas[1],
            )
            if moved >= spacing:
                self._draft_points.append(position)
        self._draw_brush_draft()
        self._draw_brush_cursor()

    def _on_map_release(self, event: tk.Event[tk.Misc]) -> None:
        if self._pan_start is not None:
            self._end_pan(event)
            return
        if self._drag_origin is not None:
            self._finish_instruction_drag(event)
            return
        if self._authoring_tool.get() != "brush" or self._active_brush_values is None:
            return
        elevation_m, radius_km, intensity, elevation_mode = self._active_brush_values
        points = tuple(self._draft_points)
        self._active_brush_values = None
        self._draft_points.clear()
        if not points:
            self._refresh_authoring_controls()
            return
        self._history.append(
            TerrainBrushStroke(
                points=points,
                elevation_m=elevation_m,
                influence_radius_km=radius_km,
                intensity=intensity,
                elevation_mode=elevation_mode,
            )
        )
        self._instructions_changed("Terrain brush stroke added. Generate to apply it.")

    def _on_map_motion(self, event: tk.Event[tk.Misc]) -> None:
        self._inspect_position(float(event.x), float(event.y))
        if (self._authoring_tool.get() != "brush" or not self._authoring_enabled
                or self._selection_mode or self._selected_instruction is not None):
            return
        self._brush_cursor = self._brush_map_position(float(event.x), float(event.y))
        self._draw_brush_cursor()

    def _on_map_leave(self, _event: tk.Event[tk.Misc]) -> None:
        self._brush_cursor = None
        self._draw_brush_cursor()

    def _on_map_wheel(self, event: tk.Event[tk.Misc]) -> str | None:
        if not int(event.state) & 0x0001:
            if event.delta:
                self._zoom_view(1.25 if event.delta > 0 else 0.8,
                                (float(event.x), float(event.y)))
            return "break"
        if (self._authoring_tool.get() != "brush" or not self._authoring_enabled
                or self._active_brush_values is not None):
            return "break"
        delta = int(event.delta)
        if delta == 0:
            return "break"
        steps = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        if int(event.state) & 0x0004:
            current = float(self._brush_intensity_percent.get())
            self._brush_intensity_percent.set(min(100.0, max(5.0, current + 5.0 * steps)))
        else:
            current = float(self._tool_sizes["brush"].get())
            increment = max(10.0, round(current * 0.08 / 10.0) * 10.0)
            self._tool_sizes["brush"].set(
                min(4_000.0, max(10.0, current + increment * steps))
            )
        self._brush_cursor = self._brush_map_position(float(event.x), float(event.y))
        self._refresh_authoring_controls()
        self._draw_brush_cursor()
        return "break"

    def _on_map_click(self, event: tk.Event[tk.Misc]) -> None:
        if not self._authoring_enabled or self._coast_polygon is None:
            return
        position = self._canvas_to_normalized(float(event.x), float(event.y))
        if position is None:
            return
        source_point = self._normalized_to_source(position)
        if (self._authoring_tool.get() != "region"
                and not self._coast_polygon.covers(Point(source_point))):
            self.root.bell()
            self.status_label.configure(text="Place authored features on a land component.")
            return

        tool = self._authoring_tool.get()
        if tool == "height":
            values = self._read_constraint_values()
            if values is None:
                return
            elevation_m, radius_km, elevation_mode = values
            self._history.append(
                ElevationPoint(
                    position=position,
                    elevation_m=elevation_m,
                    influence_radius_km=radius_km,
                    elevation_mode=elevation_mode,
                )
            )
            self._instructions_changed("Height point added. Generate to apply it.")
        else:
            if self._draft_points:
                segment = LineString(
                    [
                        self._normalized_to_source(self._draft_points[-1]),
                        source_point,
                    ]
                )
                if tool != "region" and not self._coast_polygon.covers(segment):
                    self.root.bell()
                    self.status_label.configure(
                        text="That segment leaves the coastline; choose a different point."
                    )
                    return
            self._draft_points.append(position)
            self.status_label.configure(
                text=f"{tool.capitalize()} vertex {len(self._draft_points)} added."
            )
            self._refresh_authoring_controls()
            self._draw_preview()

    def _finish_structure(self) -> None:
        if not self._authoring_enabled:
            return
        tool = self._authoring_tool.get()
        if tool in ("lake", "dry_basin"):
            self._finish_basin()
            return
        if tool == "region":
            self._finish_region()
            return
        if tool not in ("ridge", "valley") or len(self._draft_points) < 2:
            return
        values = self._read_constraint_values()
        if values is None:
            return
        elevation_m, radius_km, elevation_mode = values
        self._history.append(
            TerrainStructure(
                kind=tool,
                points=tuple(self._draft_points),
                elevation_m=elevation_m,
                influence_radius_km=radius_km,
                elevation_mode=elevation_mode,
            )
        )
        self._draft_points.clear()
        self._instructions_changed(f"{tool.capitalize()} added. Generate to apply it.")

    def _read_region_settings(self) -> LandformSettings:
        character = self._region_character.get()
        if character not in ("plain", "hills", "plateau", "mountains"):
            raise ValueError("Unknown landform character.")
        return LandformSettings(
            character=character,
            **{key: float(value.get()) for key, value in self._region_values.items()},
        )

    def _on_region_character(self, _event: tk.Event[tk.Misc]) -> None:
        character = self._region_character.get()
        if character not in ("plain", "hills", "plateau", "mountains"):
            return
        preset = landform_preset(character)
        for key, value in self._region_values.items():
            value.set(float(getattr(preset, key)))

    def _finish_region(self) -> None:
        if len(self._draft_points) < 3:
            return
        points = tuple(self._draft_points)
        if points[0] != points[-1]:
            points += (points[0],)
        try:
            region = TerrainRegion(points, self._read_region_settings())
            self._validate_instruction_geometry(region)
            if region.settings.elevation_m > float(self._variables["maximum_elevation_m"].get()):
                raise ValueError("Regional base height exceeds the elevation ceiling.")
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Invalid landform region", str(error), parent=self.root)
            return
        self._history.append(region)
        self._draft_points.clear()
        self._instructions_changed("Landform region added. Generate to apply it.")

    def _finish_basin(self) -> None:
        tool = self._authoring_tool.get()
        if tool not in ("lake", "dry_basin") or len(self._draft_points) < 3:
            return
        points = tuple(self._draft_points)
        if points[0] != points[-1]:
            points += (points[0],)
        try:
            basin = TerrainBasin(
                points, tool, float(self._lake_level.get()) if tool == "lake" else None,
                points[0] if tool == "lake" and self._lake_outlet.get() else None,
            )
            self._validate_instruction_geometry(basin)
            if (basin.water_level_m is not None
                    and basin.water_level_m > float(self._variables["maximum_elevation_m"].get())):
                raise ValueError("Water level exceeds the elevation ceiling.")
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Invalid basin area", str(error), parent=self.root)
            return
        self._history.append(basin)
        self._draft_points.clear()
        self._instructions_changed("Basin area added. Generate to protect and review it.")

    def _undo_constraint(self) -> None:
        if not self._authoring_enabled:
            return
        if self._drag_origin is not None:
            self._cancel_edit()
            return
        if self._draft_points:
            self._draft_points.pop()
            self.status_label.configure(text="Removed the last unfinished vertex.")
            self._refresh_authoring_controls()
            self._draw_preview()
            return
        self._history.undo()
        self._selected_instruction = None
        self._instructions_changed("Undid instruction edit.")

    def _redo_constraint(self) -> None:
        if not self._authoring_enabled or self._draft_points or self._drag_origin is not None:
            return
        self._history.redo()
        self._selected_instruction = None
        self._instructions_changed("Redid instruction edit.")

    def _clear_constraints(self) -> None:
        if not self._authoring_enabled:
            return
        self._draft_points.clear()
        self._active_brush_values = None
        self._selected_instruction = None
        self._history.commit(())
        self._instructions_changed("All instructions cleared. Undo restores them.")

    def _instructions_changed(self, status: str) -> None:
        self._drag_origin = None
        self._drag_candidate = None
        self._drag_error = None
        self.progress.configure(value=0)
        self.status_label.configure(text=status)
        self._refresh_authoring_controls()
        self._refresh_reference_state()
        self._draw_preview()

    def _refresh_value(self, key: str) -> None:
        spec = self._specs[key]
        try:
            raw = float(self._variables[key].get())
        except tk.TclError, ValueError:
            return
        value = round(raw) if spec.integer else raw
        rendered = (
            f"{value:,.0f}" if spec.integer or spec.increment >= 1 else f"{value:.2f}"
        )
        if spec.unit:
            rendered = f"{rendered} {spec.unit}"
        self._value_labels[key].configure(text=rendered)

    def _document_is_dirty(self) -> bool:
        if self._coastline is None:
            return False
        if self._saved_inputs is None or self._has_pending_instruction():
            return True
        try:
            return self._generation_inputs() != self._saved_inputs
        except (ValueError, tk.TclError):
            return True

    def _refresh_document_state(self, *_args: str) -> None:
        if self._syncing_selection:
            return
        if self._world_active():
            world = self.world_workspace
            name = world.path.name if world.path else world.values["name"].get()
        else:
            name = self._project_path.name if self._project_path else "Local terrain"
        marker = "* " if self._document_is_dirty() or self.world_workspace.unsaved else ""
        self.root.title(f"{marker}{name} — DM Tools Map Workbench")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.import_button.configure(state=state)
        self.open_project_button.configure(state=state)
        can_save = not busy and self._coastline_source is not None
        self.save_project_button.configure(state="normal" if can_save else "disabled")
        self.save_as_button.configure(state="normal" if can_save else "disabled")
        token = self._generation_cancel
        if token is not None:
            self.generate_button.configure(
                text="Cancelling…" if token.is_cancelled else "Cancel generation",
                state="disabled" if token.is_cancelled else "normal",
            )
        else:
            self.generate_button.configure(
                text="Generate terrain",
                state="normal" if not busy and self._coastline is not None else "disabled",
            )
        for widget in self._settings_widgets:
            widget["state"] = state
        if self._coastline_source is not None and self._coastline_source.world_terrain is not None:
            for widget in self._world_scale_widgets:
                widget["state"] = "disabled"
        self.render_style_input.configure(state="disabled" if busy else "readonly")
        self._set_authoring_enabled(not busy and self._coastline is not None)
        self._refresh_reference_state()

    def _accept_world_terrain(self, created: WorldTerrainCreated) -> None:
        self._guard_unsaved(lambda: self._load_project(created.loaded.path))

    def _guard_unsaved(self, action: Callable[[], None]) -> None:
        if self._busy:
            self.status_label.configure(text=(
                "Cancel generation or wait for it to finish." if self._generation_cancel else
                "Wait for the current operation to finish."))
            return
        if not self._document_is_dirty():
            action()
            return
        answer = messagebox.askyesnocancel(
            "Save changes?", "Save the current project before continuing?\n"
            "Yes saves, No discards these edits, Cancel stays here.\n"
            "Unfinished drawing or property edits must be finished before saving.",
            parent=self.root)
        if answer is True:
            self._save_project(after_save=action)
        elif answer is False:
            action()

    def _world_active(self) -> bool:
        return cast("str", self.workspaces.select()) == str(self.world_workspace)

    def _request_close(self) -> None:
        if self._busy:
            self.workspaces.select(self.terrain_page)
            self._guard_unsaved(self._close)
            return
        self.world_workspace.guard(lambda: self._guard_unsaved(self._close))

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.world_workspace.close()
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        self.preview.delete("all")
        self._preview_photo = None
        self._clear_review()
        self._replace_preview_layers(None, None)
        self._terrain = None
        self._generated_inputs = None
        self.root.destroy()

    def _shortcut(self, command: Callable[[], None], *, editing: bool = False) -> str | None:
        focus = self.root.focus_get()
        if editing and focus is not None and focus.winfo_class() in (
            "Entry", "TEntry", "Spinbox", "TSpinbox", "TCombobox", "Text",
        ):
            return None
        if self._world_active():
            world = self.world_workspace
            actions = {
                self._choose_project: world.choose_world,
                self._save_project: world.save_current,
                self._undo_constraint: world.undo_current,
                self._redo_constraint: world.redo_current,
                self._fit_view: world.fit, self._generate: world.primary_action,
            }
            if isinstance(command, partial) and command.func == self._save_project:
                world.save_current(save_as=True)
            elif command in actions:
                actions[command]()
        elif not self._busy:
            command()
        return "break"

    def _bind_shortcuts(self) -> None:
        for sequence, command in (
            ("<Control-o>", self._choose_project), ("<Control-s>", self._save_project),
            ("<Control-Shift-S>", partial(self._save_project, save_as=True)),
            ("<Control-Return>", self._generate),
        ):
            self.root.bind(sequence, lambda _event, action=command: self._shortcut(action))
        for sequence, command in (
            ("<Control-z>", self._undo_constraint), ("<Control-y>", self._redo_constraint),
            ("<Control-Shift-Z>", self._redo_constraint),
            ("<Delete>", self._delete_instruction),
            ("<f>", self._fit_view),
        ):
            self.root.bind(sequence, lambda _event, action=command: self._shortcut(
                action, editing=True))
        self.root.bind("<Escape>", lambda _event: self._escape())
        self.root.bind("<KeyPress-space>", lambda _event: self._space_key(True))
        self.root.bind("<KeyRelease-space>", lambda _event: self._space_key(False))
        self.root.bind("<FocusOut>", lambda _event: self._space_key(False))

    def _space_key(self, pressed: bool) -> str | None:
        if not pressed:
            self._space_pressed = False
            return None
        if self.root.focus_get() == self.preview:
            self._space_pressed = True
            return "break"
        return None

    def _cancel_edit(self) -> None:
        self._drag_origin = None
        self._drag_candidate = None
        self._drag_error = None
        self._draft_points.clear()
        self._active_brush_values = None
        self._brush_cursor = None
        self._pan_start = None
        self._space_pressed = False
        self.preview.configure(cursor="")
        if self._selected_instruction is not None:
            self._select_instruction(self._selected_instruction)
        self._refresh_authoring_controls()
        self._draw_preview()
        self.status_label.configure(text="Unapplied edits cancelled; committed inputs are kept.")

    def _accept_edit(self) -> str:
        if self._selected_instruction is not None:
            self._apply_instruction()
        else:
            self._finish_structure()
        return "break"

    def _inspect_position(self, x: float, y: float) -> None:
        position = self._canvas_to_normalized(x, y)
        if position is None:
            return
        _, world = self._view_dimensions()
        try:
            extent_km = (self._terrain.settings.object_scale_km if self._terrain is not None
                         else self._variables["object_scale_km"].get())
            scale = extent_km / max(world)
        except tk.TclError:
            return
        text = (f"x {position[0] * world[0] * scale:,.1f} · "
                f"y {position[1] * world[1] * scale:,.1f} km")
        if self._terrain is not None:
            terrain = self._terrain
            col = round(position[0] * (terrain.width - 1))
            row = round(position[1] * (terrain.height - 1))
            value = (f"{float(terrain.elevation_m[row, col]):,.0f} m ground"
                     if terrain.land_mask[row, col] else "water / no ground sample")
            text += f" · Reference sample: {value}"
        self.cursor_label.configure(text=text)

    def _choose_svg(self) -> None:
        if self._busy:
            return
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Import SVG land geometry",
            filetypes=(("SVG vector", "*.svg"), ("All files", "*.*")),
        )
        if not selected:
            return
        self._guard_unsaved(partial(self._load_svg, Path(selected)))

    def _load_svg(self, source: Path) -> None:
        self._set_busy(True)
        self.source_label.configure(text=f"Reading {source.name}…")
        self.status_label.configure(text="Validating coastline in the background…")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)

        def worker() -> None:
            try:
                self._events.put(_CoastlineEvent(load_svg_coastline_source(source)))
            except CoastlineInputError as error:
                self._events.put(
                    _ErrorEvent(
                        title="Coastline could not be imported",
                        status="Coastline import failed.",
                        error=error,
                    )
                )
            except Exception as error:
                self._events.put(
                    _ErrorEvent(
                        title="Unexpected import failure",
                        status="Coastline import failed.",
                        error=error,
                    )
                )

        threading.Thread(target=worker, name="coastline-importer", daemon=True).start()

    def _choose_project(self) -> None:
        if self._busy:
            return
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Open terrain project",
            filetypes=(
                ("DM Tools terrain project", f"*{PROJECT_EXTENSION}"),
                ("JSON document", "*.json"),
                ("All files", "*.*"),
            ),
        )
        if not selected:
            return
        self._guard_unsaved(partial(self._load_project, Path(selected)))

    def _load_project(self, source: Path) -> None:
        self._set_busy(True)
        self.source_label.configure(text=f"Reading {source.name}…")
        self.status_label.configure(text="Validating project and coastline…")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)

        def worker() -> None:
            try:
                self._events.put(_ProjectEvent(load_terrain_project(source)))
            except TerrainProjectInputError as error:
                self._events.put(
                    _ErrorEvent(
                        title="Terrain project could not be opened",
                        status="Project open failed.",
                        error=error,
                    )
                )
            except Exception as error:
                self._events.put(
                    _ErrorEvent(
                        title="Unexpected project failure",
                        status="Project open failed.",
                        error=error,
                    )
                )

        threading.Thread(target=worker, name="terrain-project-loader", daemon=True).start()

    def _save_project(
        self, *, save_as: bool = False, after_save: Callable[[], None] | None = None,
    ) -> None:
        if self._busy:
            return
        if self._coastline is None or self._coastline_source is None:
            messagebox.showinfo(
                "Import land geometry",
                "Import closed SVG land shapes before saving a terrain project.",
                parent=self.root,
            )
            return
        if self._has_pending_instruction():
            messagebox.showinfo(
                "Finish the current instruction",
                "Finish drawing, Apply edit, or cancel the instruction before saving.",
                parent=self.root,
            )
            return
        try:
            project = TerrainProject(
                coastline=self._coastline,
                settings=self._read_settings(),
                constraints=tuple(self._constraints),
                authoring=self._read_authoring_state(),
                world_context=self._world_context,
            )
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Invalid project settings", str(error), parent=self.root)
            return

        destination = self._project_path
        if save_as or destination is None:
            initial_file = (destination.name if destination is not None else
                            f"{Path(self._coastline.source_name).stem}{PROJECT_EXTENSION}")
            selected = filedialog.asksaveasfilename(
                parent=self.root, title="Save terrain project as", initialfile=initial_file,
                initialdir=str(destination.parent) if destination is not None else "",
                defaultextension=PROJECT_EXTENSION,
                filetypes=(("DM Tools terrain project", f"*{PROJECT_EXTENSION}"),),
            )
            if not selected:
                return
            destination = Path(selected)
        coastline_source = self._coastline_source
        inputs = GenerationInputs(project.coastline, project.settings, project.constraints,
                                  project.world_context)
        self._after_save = after_save
        self._set_busy(True)
        self.status_label.configure(text="Saving authored terrain project…")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)

        def worker() -> None:
            try:
                save_terrain_project(project, coastline_source, destination)
                self._events.put(_ProjectSavedEvent(destination.resolve(), inputs))
            except (OSError, TerrainProjectInputError) as error:
                self._events.put(
                    _ErrorEvent(
                        title="Terrain project could not be saved",
                        status="Project save failed.",
                        error=error,
                    )
                )
            except Exception as error:
                self._events.put(
                    _ErrorEvent(
                        title="Unexpected project save failure",
                        status="Project save failed.",
                        error=error,
                    )
                )

        threading.Thread(target=worker, name="terrain-project-saver", daemon=True).start()

    def _accept_coastline(
        self,
        coastline: Coastline,
        source: CoastlineSource | None = None,
    ) -> None:
        self.workspaces.select(self.terrain_page)
        self._coastline = coastline
        self._coastline_source = source
        self._world_context = None
        if source is not None and source.world_terrain is not None:
            self._variables["object_scale_km"].set(source.world_terrain.object_scale_km)
        self._project_path = None
        self._saved_inputs = None
        self._viewport.fit()
        self._drag_origin = None
        self._drag_candidate = None
        self._pan_start = None
        self._selection_mode = False
        self._clear_review()
        land_geometry = unary_union(
            [
                Polygon(component.exterior, holes=component.holes)
                for component in coastline.components
            ]
        )
        if not isinstance(land_geometry, (Polygon, MultiPolygon)):
            raise ValueError("The imported coastlines do not form polygonal land geometry.")
        self._coast_polygon = land_geometry
        self._history.reset()
        self._selected_instruction = None
        self._generated_inputs = None
        self._draft_points.clear()
        self._active_brush_values = None
        self._brush_cursor = None
        self._terrain = None
        self._replace_preview_layers(None, None)
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._set_busy(False)
        self.source_label.configure(text=coastline.source_name)
        self.status_label.configure(
            text="Land geometry valid. Draw controls or generate directly."
        )
        component_label = "component" if coastline.component_count == 1 else "components"
        self.preview_meta.configure(
            text=(
                f"{coastline.boundary_point_count:,} sampled boundary points · "
                f"{coastline.component_count} land {component_label}"
            )
        )
        self._refresh_authoring_controls()
        self._refresh_reference_state()
        self._draw_preview()

    def _read_settings(self) -> TerrainSettings:
        values = {key: variable.get() for key, variable in self._variables.items()}
        if self._coastline_source is not None:
            self._coastline_source.validate_scale(values["object_scale_km"])
        return TerrainSettings(
            seed=round(values["seed"]),
            object_scale_km=values["object_scale_km"],
            resolution_px=round(values["resolution_px"]),
            maximum_elevation_m=values["maximum_elevation_m"],
            largest_feature_km=values["largest_feature_km"],
            detail_levels=round(values["detail_levels"]),
            roughness=values["roughness"],
            coastal_rise_km=values["coastal_rise_km"],
            variability=values["variability"],
            drainage_density=values["drainage_density"],
        )

    def _apply_settings(self, settings: TerrainSettings) -> None:
        for key, variable in self._variables.items():
            variable.set(float(getattr(settings, key)))
            self._refresh_value(key)

    def _read_authoring_state(self) -> TerrainAuthoringState:
        active_tool = self._authoring_tool.get()
        if active_tool not in ("brush", "height", "ridge", "valley", "region", "lake", "dry_basin"):
            raise ValueError(f"Unknown authoring tool: {active_tool}")

        def feature(tool: str) -> FeatureToolSettings:
            return FeatureToolSettings(
                elevation_mode=self._selected_elevation_mode(tool),
                elevation_m=float(self._tool_elevations[tool].get()),
                radius_km=float(self._tool_sizes[tool].get()),
            )

        return TerrainAuthoringState(
            active_tool=active_tool,
            region=self._read_region_settings(),
            lake=LakeToolSettings(float(self._lake_level.get()), bool(self._lake_outlet.get())),
            brush=BrushToolSettings(
                elevation_mode=self._selected_elevation_mode("brush"),
                elevation_m=float(self._tool_elevations["brush"].get()),
                width_km=float(self._tool_sizes["brush"].get()),
                intensity=float(self._brush_intensity_percent.get()) / 100.0,
            ),
            height=feature("height"),
            ridge=feature("ridge"),
            valley=feature("valley"),
        )

    def _apply_authoring_state(self, authoring: TerrainAuthoringState) -> None:
        self._authoring_tool.set(authoring.active_tool)
        self._lake_level.set(authoring.lake.water_level_m)
        self._lake_outlet.set(authoring.lake.outlet_at_first_vertex)
        self._region_character.set(authoring.region.character)
        for key, value in self._region_values.items():
            value.set(float(getattr(authoring.region, key)))
        self._tool_modes["brush"].set(authoring.brush.elevation_mode.title())
        self._tool_elevations["brush"].set(authoring.brush.elevation_m)
        self._tool_sizes["brush"].set(authoring.brush.width_km)
        self._brush_intensity_percent.set(authoring.brush.intensity * 100.0)
        for tool, settings in (
            ("height", authoring.height),
            ("ridge", authoring.ridge),
            ("valley", authoring.valley),
        ):
            self._tool_modes[tool].set(settings.elevation_mode.title())
            self._tool_elevations[tool].set(settings.elevation_m)
            self._tool_sizes[tool].set(settings.radius_km)
        self._refresh_authoring_controls()

    def _accept_project(self, loaded: LoadedTerrainProject) -> None:
        project = loaded.project
        self._accept_coastline(project.coastline, loaded.coastline_source)
        self._project_path = loaded.path
        self._world_context = project.world_context
        self._apply_settings(project.settings)
        self._history.reset(project.constraints)
        self._apply_authoring_state(project.authoring)
        self._saved_inputs = GenerationInputs(
            project.coastline, project.settings, project.constraints, project.world_context)
        count = len(self._constraints)
        suffix = "s" if count != 1 else ""
        self.status_label.configure(
            text=f"Opened {loaded.path.name} with {count} authored feature{suffix}."
        )
        if loaded.coastline_source.world_terrain is not None:
            self.status_label.configure(
                text="World terrain project ready. Scale is fixed by the world projection. "
                "Add instructions or click Generate terrain."
                + (" Geographic context is connected to coastal relief (experimental)."
                   if project.world_context else "")
            )
        self.preview_meta.configure(text=f"{count} authored feature{suffix}")
        self._refresh_reference_state()
        self._draw_preview()

    def _generate_or_cancel(self) -> None:
        if self._generation_cancel is not None:
            self._cancel_generation()
        else:
            self._generate()

    def _escape(self) -> str:
        if self._world_active():
            self.world_workspace.escape()
            return "break"
        if self._generation_cancel is not None:
            self._cancel_generation()
        elif not self._busy:
            self._cancel_edit()
        return "break"

    def _cancel_generation(self) -> None:
        if self._generation_cancel is not None:
            self._generation_cancel.cancel()
            # Keep the worker's slot until it acknowledges the stop.
            self._set_busy(True)
            self._update_generation_status()

    def _update_generation_status(self) -> None:
        if self._generation_started is None or self._generation_cancel is None:
            return
        message = ("Cancelling — waiting for the current step to stop"
                   if self._generation_cancel.is_cancelled else self._generation_message)
        elapsed = monotonic() - self._generation_started
        self.status_label.configure(text=f"{message} · {elapsed:.1f} s")

    def _end_generation(self) -> float | None:
        elapsed = (None if self._generation_started is None else
                   monotonic() - self._generation_started)
        self._generation_started = None
        self._generation_cancel = None
        return elapsed

    def _finish_cancelled_generation(self) -> None:
        elapsed = self._end_generation()
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._set_busy(False)
        timing = f" after {elapsed:.1f} s" if elapsed is not None else ""
        reference = " Previous map kept as reference." if self._terrain is not None else ""
        self.status_label.configure(text=f"Generation cancelled{timing}.{reference}")

    @staticmethod
    def _discard_result(event: _ResultEvent) -> None:
        event.image.close()
        if event.water_display is not None:
            event.water_display.close()

    def _generate(self) -> None:
        if self._busy:
            return
        if self._coastline is None:
            messagebox.showinfo(
                "Import land geometry",
                "Choose one or more closed SVG land objects first.",
                parent=self.root,
            )
            return
        if self._has_pending_instruction():
            messagebox.showinfo("Finish the current instruction",
                                "Finish drawing, Apply edit, or cancel before generating.",
                                parent=self.root)
            return
        try:
            inputs = self._generation_inputs()
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Invalid settings", str(error), parent=self.root)
            return

        cancellation = CancellationToken()
        self._generation_cancel = cancellation
        self._generation_started = monotonic()
        self._generation_message = "Starting deterministic generation"
        self._generation_fraction = 0.0
        self._set_busy(True)
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._update_generation_status()
        render_style = self._selected_render_style()

        def worker() -> None:
            image: Image.Image | None = None
            water: WaterDisplay | None = None
            completed_event: _ResultEvent | _CancelledEvent | _ErrorEvent
            try:
                terrain = generate_terrain(
                    inputs.coastline,
                    inputs.settings,
                    lambda fraction, message: self._events.put(
                        _ProgressEvent(0.94 * fraction, message, cancellation)),
                    constraints=inputs.constraints,
                    world_context=inputs.world_context,
                    cancellation=cancellation,
                )
                cancellation.checkpoint()
                self._events.put(_ProgressEvent(0.97, "Rendering colour relief", cancellation))
                image, water = render_height_map_layers(
                    terrain, style=render_style, cancellation=cancellation)
                cancellation.checkpoint()
                completed_event = _ResultEvent(inputs, terrain, image, water, cancellation)
                image, water = None, None  # Ownership transfers to the UI event.
            except GenerationCancelled:
                completed_event = _CancelledEvent(cancellation)
            except Exception as error:
                completed_event = _ErrorEvent(
                    title="Terrain generation failed",
                    status="Generation failed.",
                    error=error,
                    generation=cancellation,
                )
            finally:
                if image is not None:
                    image.close()
                if water is not None:
                    water.close()
            # A terminal event releases the UI's job slot, so send it after cleanup.
            self._events.put(completed_event)

        threading.Thread(target=worker, name="terrain-generator", daemon=True).start()

    def _poll_events(self) -> None:
        if self._closed:
            return
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        try:
            while True:
                event = self._events.get_nowait()
                if isinstance(event, (_ProgressEvent, _ResultEvent, _ErrorEvent, _CancelledEvent)):
                    if event.generation is not self._generation_cancel:
                        if isinstance(event, _ResultEvent):
                            self._discard_result(event)
                        continue
                    if event.generation is not None and event.generation.is_cancelled:
                        if isinstance(event, _ProgressEvent):
                            continue
                        if isinstance(event, _ResultEvent):
                            self._discard_result(event)
                        self._finish_cancelled_generation()
                        continue
                if isinstance(event, _ProgressEvent):
                    self._generation_fraction = max(self._generation_fraction, event.fraction)
                    self.progress.configure(value=self._generation_fraction * 100.0)
                    self._generation_message = event.message
                    self.status_label.configure(text=event.message)
                elif isinstance(event, _CancelledEvent):
                    self._finish_cancelled_generation()
                elif isinstance(event, _CoastlineEvent):
                    self._accept_coastline(event.source.coastline, event.source)
                elif isinstance(event, _ProjectEvent):
                    self._accept_project(event.loaded)
                elif isinstance(event, _ProjectSavedEvent):
                    self._project_path = event.path
                    self._saved_inputs = event.inputs
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=100)
                    self._set_busy(False)
                    self.status_label.configure(text=f"Saved project {event.path.name}")
                    continuation, self._after_save = self._after_save, None
                    if continuation is not None and not self._document_is_dirty():
                        continuation()
                        if self._closed:
                            return
                elif isinstance(event, _ResultEvent):
                    elapsed = self._end_generation()
                    self._generated_inputs = event.inputs
                    self._terrain = event.terrain
                    self._replace_preview_layers(event.image, event.water_display)
                    self._clear_review()
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.progress.configure(value=100)
                    drainage = event.terrain.drainage.summary
                    if drainage.basin_candidate_count:
                        drainage_status = (
                            f"Drainage check grouped "
                            f"{drainage.potential_sink_cell_count:,} potential terminal cells "
                            f"into {drainage.basin_candidate_count:,} basin candidates."
                        )
                    elif drainage.potential_sink_cell_count:
                        drainage_status = (
                            f"Drainage check found {drainage.potential_sink_cell_count:,} "
                            "flat or sub-tolerance terminal cells."
                        )
                    else:
                        drainage_status = "No potential sinks on the canonical grid."
                    agreement = event.terrain.routing_agreement
                    conflicts = event.terrain.routing_conflicts.summary
                    basin_issues = sum(
                        bool(item.issues) for item in event.terrain.water.review.basins)
                    water_status = (f" Basin review: {basin_issues} areas need attention."
                                    if event.terrain.water.review.basins else "")
                    self.status_label.configure(text=(
                        (f"Terrain ready in {elapsed:.1f} s. " if elapsed is not None
                         else "Terrain ready. ") + f"{drainage_status} "
                        f"Planned channels: {agreement.uphill_channel_edge_count:,} uphill edges; "
                        f"{conflicts.insufficient_cut_edge_count:,} exceed cut allowance, "
                        f"{conflicts.depression_edge_count:,} touch depressions (may overlap)."
                        f"{water_status}"
                    ))
                    peak = float(event.terrain.elevation_m[event.terrain.land_mask].max())
                    connected_percent = (
                        100.0
                        * drainage.directly_connected_land_cell_count
                        / drainage.land_cell_count
                    )
                    self.preview_meta.configure(
                        text=(
                            f"{event.terrain.width} x {event.terrain.height} px"
                            f"  ·  peak {peak:,.0f} m"
                            f"  ·  direct drainage {connected_percent:.1f}%"
                            f"  ·  {drainage.basin_candidate_count:,} basin candidates"
                        )
                    )
                    self._set_busy(False)
                    self._draw_preview()
                else:
                    self._end_generation()
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self._after_save = None
                    self._set_busy(False)
                    source_name = (
                        self._coastline.source_name
                        if self._coastline is not None
                        else "No land geometry loaded"
                    )
                    self.source_label.configure(text=source_name)
                    self._refresh_reference_state()
                    self.status_label.configure(text=event.status)
                    messagebox.showerror(event.title, str(event.error), parent=self.root)
        except queue.Empty:
            pass
        self._update_generation_status()
        self._poll_after_id = self.root.after(80, self._poll_events)

    def _show_basin_details(self) -> None:
        if self._terrain is None:
            self.status_label.configure(text="Generate terrain to review authored basin areas.")
            return
        records = self._terrain.water.review.basins
        if not records:
            self.status_label.configure(
                text="Draw a lake or dry-basin area, then generate terrain.")
            return
        descriptions = {
            "unresolved_footprint": "Area is smaller than the review grid can resolve.",
            "no_water_at_level": "The water level does not cover any reviewed ground.",
            "disconnected_water": "The water separates into multiple pools.",
            "low_boundary": "Water reaches low ground beyond the drawn area; review its boundary.",
            "exposed_height_anchor": "An authored height point remains above the lake level.",
            "outlet_above_water": "The outlet terrain is above the water level.",
            "outlet_below_water": "The outlet is submerged at the authored water level.",
            "outlet_route_blocked": "The declared outlet has no clear downstream route.",
            "shoreline_low_ground": (
                "Fine boundary samples reveal low ground outside the declared outlet opening."),
            "shoreline_sampling_unresolved": (
                "The fine shoreline check could not cover this whole boundary."),
            "outlet_shoreline_uncontained": "A low shoreline opening lies away from the outlet.",
            "dry_link_barrier": "Finer ground rises block some dry collection links.",
            "dry_link_sampling_unresolved": "Dry collection exceeded its sample budget.",
            "dry_path_uphill": "Small rises combine into larger climbs along some dry paths.",
            "wet_link_barrier": "High ground blocks some internal water links.",
            "wet_link_sampling_unresolved": "Internal water connectivity needs finer review.",
            "outlet_water_disconnected": (
                "Not all water reaches the selected contact through clear internal links."),
            "outlet_partial_catchment": (
                "Amber dry samples have no verified path to connected water. "
                "Pits, ground rises, missing links or incomplete sampling can retain them."),
            "unexpected_planned_basin_exit": "Unexpected planned basin exit; inspect routing.",
        }
        sections: list[str] = []
        for record in records[:20]:
            title = f"A{record.intent_id}. {record.source.kind.replace('_', ' ').title()}"
            if record.source.water_level_m is not None:
                title += f" at {record.source.water_level_m:,.1f} m"
                title += f" ({record.wet_cell_count} wet / {record.dry_cell_count} dry samples)"
            findings = [descriptions[issue] for issue in record.issues]
            if not findings:
                findings = ["No sampled conflict found. This is not a river-flow certification."]
            findings.append(
                f"Retained contributing area: {record.retained_contributing_area_km2:,.1f} km².")
            findings.append(
                f"Footprint samples: {record.collected_wet_cell_count} water + "
                f"{record.collected_dry_cell_count} land feed the outlet; "
                f"{record.retained_cell_count} retained.")
            if record.flat_routed_cell_count:
                findings.append(f"Flat paths: {record.flat_routed_cell_count} dry samples; "
                                f"{record.collected_flat_cell_count} of them feed the outlet.")
            if record.outlet_ground_minus_water_m is not None:
                assert record.outlet_elevation_m is not None
                delta = record.outlet_ground_minus_water_m
                at_level = not ({"outlet_above_water", "outlet_below_water"} & set(record.issues))
                comparison = ("within 0.01 m of water" if at_level else
                              f"{abs(delta):,.2f} m {'above' if delta > 0 else 'below'} water")
                findings.append(f"Outlet ground: {record.outlet_elevation_m:,.2f} m "
                                f"({comparison}).")
                findings.append("The water level is imposed; a stable spill level is not modeled.")
            if record.outlet_connection == "connected":
                findings.append(f"Connected outlet: {record.outlet_contributing_area_km2:,.1f} km² "
                                "of contributing area reaches the downstream boundary.")
            elif record.outlet_connection == "blocked":
                findings.append("Outlet connection blocked; contributing area stays retained.")
            shoreline = record.shoreline
            if shoreline is not None and shoreline.profile.status == "sampled":
                findings.append(f"Boundary review: {len(shoreline.profile.ground_m)} samples; "
                                f"{shoreline.uncontrolled_low_sample_count} below water outside "
                                "the outlet opening.")
            links = record.wet_links
            if links is not None:
                if links.status == "sampled":
                    findings.append(f"Internal water links: {links.blocked_link_count} blocked of "
                                    f"{links.candidate_link_count}; "
                                    f"{links.contact_reachable_wet_cell_count} of "
                                    f"{record.wet_cell_count} water samples reach the selected "
                                    f"contact ({links.requested_sample_count:,} ground samples).")
                    if links.blocked_link_count:
                        findings.append("Red diamonds mark high ground on water links. "
                                        "Clear alternate paths may still connect the pool.")
                else:
                    findings.append("Internal water links: sample budget exceeded; at least "
                                    f"{links.requested_sample_count:,} samples required. "
                                    "No partial network was accepted; area stays retained.")
            dry = record.dry_links
            if dry is not None:
                if dry.status == "sampled":
                    findings.append(f"Dry collection links: {dry.blocked_link_count} blocked of "
                                    f"{dry.candidate_link_count} "
                                    f"({dry.requested_sample_count:,} ground samples).")
                    findings.append(f"Complete dry paths: {dry.cumulative_uphill_cell_count} "
                                    "samples exceed the 0.01 m accumulated-climb limit.")
                    if dry.blocked_link_count:
                        findings.append("The largest dry-link climbs are marked in red. "
                                        "Clear alternatives can still collect area.")
                else:
                    findings.append("Dry collection links: sample budget exceeded; at least "
                                    f"{dry.requested_sample_count:,} samples required. "
                                    "All dry area stays retained; verified water still drains.")
            route = record.outlet_route
            for label, profile in (("Boundary", shoreline.profile if shoreline else None),
                                   ("Connection", route.connection_profile if route else None),
                                   ("Downstream", route.downstream.profile
                                    if route and route.downstream else None)):
                if (profile is not None and profile.status == "sampled"
                        and profile.feature_sample_count and profile.feature_spacing_limit_km):
                    findings.append(f"{label} feature checks: {profile.feature_sample_count} extra "
                                    "samples near authored terrain; smallest local spacing limit "
                                    f"{profile.feature_spacing_limit_km * 1000:,.3g} m.")
            if route is not None:
                profile = route.connection_profile
                if profile is not None and profile.maximum_ground_m is not None:
                    findings.append(f"Highest sampled connection ground: "
                                    f"{profile.maximum_ground_m:,.2f} m; spacing at most "
                                    f"{profile.spacing_limit_km:,.3f} km.")
                downstream = route.downstream
                if downstream is not None:
                    scope = ("to the candidate terminal"
                             if downstream.reaches_terminal else "prefix only")
                    if downstream.maximum_uphill_excursion_m is None:
                        findings.append("Downstream ground check: sample budget exceeded; "
                                        f"at least {downstream.profile.requested_sample_count:,} "
                                        f"samples required ({scope}).")
                    else:
                        findings.append(f"Downstream ground check: "
                                        f"{len(downstream.profile.ground_m):,} samples ({scope}); "
                                        "largest climb from an earlier low "
                                        f"{downstream.maximum_uphill_excursion_m:,.2f} m.")
                findings.append(f"Outlet candidate: {route.length_km:,.1f} km reviewed; "
                                f"{route.uphill_edge_count} uphill steps, "
                                f"largest rise {route.maximum_rise_m:,.2f} m.")
                route_descriptions = {
                    "outlet_above_water": "The outlet terrain is above the water level.",
                    "outlet_without_sampled_water": "No sampled water connects to the outlet.",
                    "outlet_connection_above_water": (
                        "Ground along the water-to-outlet connection rises above the water level."),
                    "outlet_connection_unresolved": (
                        "The fine outlet-connection check is unresolved."),
                    "outlet_downstream_uphill": (
                        "Finer downstream samples climb after a low point; transfer is blocked. "
                        "Flow through such a pool needs water-level and storage review."),
                    "outlet_downstream_unresolved": (
                        "The downstream profile exceeds its sample budget; transfer is blocked."),
                    "outlet_attachment_unresolved": "No nearby outward attachment was resolved.",
                    "outlet_route_cycle": "The candidate route contains a loop.",
                    "outlet_route_invalid_receiver": "The candidate route has an invalid step.",
                    "outlet_route_enters_basin": "The candidate route enters an authored basin.",
                    "outlet_route_crosses_nonland": "The candidate route crosses a coastline gap.",
                    "outlet_route_interior_terminal": "The candidate route stops inland.",
                    "outlet_route_uphill": "The candidate route climbs on the finished ground.",
                    "outlet_terminal_level_unknown": "The terminal water level is unknown.",
                }
                findings.extend(route_descriptions[issue] for issue in route.issues)
                if route.status == "sampled_clear" and record.outlet_connection != "connected":
                    findings.append("Downstream path is clear; review the lake findings above.")
            sections.append(title + "\n" + "\n".join(findings))
        if len(records) > 20:
            sections.append(f"Showing 20 of {len(records)} areas.")
        messagebox.showinfo("Authored basin review", "\n\n".join(sections), parent=self.root)

    def _review_layer(self) -> Image.Image:
        terrain = self._terrain
        if terrain is None:
            raise ValueError("Generate terrain before showing reviews.")
        key = (id(terrain), self._show_drainage.get(), self._show_catchments.get(),
               self._show_depressions.get())
        if self._review_image is not None and key == self._review_key:
            return self._review_image
        # Cache basin rasters and the channel graph; channel strokes are viewport-native.
        ratio = min(1., 1536 / max(terrain.width, terrain.height))
        size = (max(1, round(terrain.width * ratio)), max(1, round(terrain.height * ratio)))
        review = Image.new("RGBA", size)
        try:
            if self._show_depressions.get():
                with closing(render_basin_overlay(terrain, size)) as basins:
                    review.alpha_composite(basins)
            if self._show_catchments.get():
                with closing(render_basin_catchment_overlay(terrain, size)) as catchments:
                    review.alpha_composite(catchments)
            with closing(render_basin_outflow_overlay(terrain, size)) as paths:
                review.alpha_composite(paths)
            channels = prepare_channel_display(terrain) if self._show_drainage.get() else None
        except BaseException:
            review.close()
            raise
        self._clear_review()
        self._review_image, self._review_key = review, key
        self._channel_display = channels
        return review

    def _draw_preview(self) -> None:
        self.preview.delete("all")
        self._preview_photo = None
        self._review_photo = None
        if not (self._show_drainage.get() or self._show_catchments.get()
                or self._show_depressions.get()):
            self._clear_review()
        if self._coastline is None:
            self.preview.create_text(
                20, 20, text="Open a terrain project or import SVG land shapes.\n"
                "Draw instructions, then Generate terrain.", anchor="nw", fill="#71817e",
                font=("Segoe UI", 12), width=max(180, self.preview.winfo_width() - 40))
            return
        rect = self._map_rect()
        if rect is None:
            return
        size = (max(1, self.preview.winfo_width()), max(1, self.preview.winfo_height()))
        left, top, right, bottom = rect
        scale_label = ""
        try:
            extent_km = (self._terrain.settings.object_scale_km if self._terrain is not None
                         else self._variables["object_scale_km"].get())
            scale = extent_km / max(right - left, bottom - top)
            scale_label = f" · {scale:,.2f} km/px"
            if self._terrain is not None:
                grid = self._terrain.grid
                spacing = max(grid.x_spacing_km, grid.y_spacing_km)
                scale_label += f"\nground {spacing:,.2f} km/sample"
        except tk.TclError:
            pass
        self.zoom_label.configure(text=f"{self._viewport.zoom:.1f}x fit{scale_label}")
        if self._image is not None:
            with closing(render_viewport(self._image, rect, size)) as display:
                if self._water_display is not None:
                    with closing(self._water_display.render(rect, size)) as water:
                        display.alpha_composite(water)
                self._preview_photo = ImageTk.PhotoImage(display)
            self.preview.create_image(0, 0, image=self._preview_photo, anchor="nw")
        else:
            for exterior, holes in self._coastline_canvas_coordinates():
                self.preview.create_polygon(exterior, fill="#243638", outline="")
                for hole in holes:
                    self.preview.create_polygon(hole, fill=MAP_BACKGROUND, outline="")
        for exterior, holes in self._coastline_canvas_coordinates():
            for coordinates in (exterior, *holes):
                self.preview.create_line(coordinates, fill="#b9cbc6", width=1.5, joinstyle="round")
        if self._terrain is not None and (self._show_drainage.get() or self._show_catchments.get()
                                          or self._show_depressions.get()):
            with closing(render_viewport(self._review_layer(), rect, size)) as review:
                if self._channel_display is not None:
                    with closing(self._channel_display.render(
                        rect, size, all_channels=self._all_channels.get(),
                    )) as channels:
                        review.alpha_composite(channels)
                self._review_photo = ImageTk.PhotoImage(review)
            self.preview.create_image(0, 0, image=self._review_photo, anchor="nw")
            legends: list[str] = []
            if self._show_drainage.get():
                display = self._channel_display
                assert display is not None
                visible = display.visible_reach_count(rect, all_channels=self._all_channels.get())
                total = len(display.network.reaches)
                mode = "All channels" if self._all_channels.get() else "Scale-aware channels"
                spacing = max(self._terrain.routing_grid.x_spacing_km,
                              self._terrain.routing_grid.y_spacing_km)
                legends.append(f"{mode}: {visible}/{total} reaches. "
                               "Blue: planned; all uphill edges red.")
                legends.append(f"Routing {spacing:,.2f} km/sample (fixed).")
            if self._show_depressions.get():
                legends.append("Purple: depressions. Yellow: spills.")
            if self._show_catchments.get():
                legends.append("Cyan water / green land feed the outlet; amber stays retained.")
            legends.append("Teal: lake outlets. Orange: low boundary. Red diamonds: barriers. "
                           "Sampled review only.")
            self.preview.create_text(8, 8, anchor="nw", fill="white", text="\n".join(legends),
                                     width=max(1, size[0] - 16))
        if self._show_instructions.get():
            for index, original in enumerate(self._constraints):
                constraint = (self._drag_candidate if index == self._selected_instruction
                              and self._drag_candidate is not None else original)
                self._draw_constraint(constraint)
                if index == self._selected_instruction:
                    points = instruction_vertices(constraint)
                    for point in points:
                        x, y = self._normalized_to_canvas(point)
                        self.preview.create_rectangle(x - 5, y - 5, x + 5, y + 5,
                                                      outline="white", width=2)
            self._draw_draft_structure()
            self._draw_brush_cursor()

    def _coastline_canvas_coordinates(
        self,
    ) -> list[tuple[list[float], tuple[list[float], ...]]]:
        if self._coastline is None:
            return []
        min_x, min_y, max_x, max_y = self._coastline.bounds
        span_x = max_x - min_x
        span_y = max_y - min_y
        rect = self._map_rect()
        assert rect is not None
        left, top, right, bottom = rect
        def canvas_ring(points: tuple[tuple[float, float], ...]) -> list[float]:
            step = max(1, (len(points) - 1) // 1_200)
            sampled = list(points[:-1:step])
            sampled.append(points[-1])
            coordinates: list[float] = []
            for x, y in sampled:
                canvas_x = left + (x - min_x) / span_x * (right - left)
                canvas_y = top + (y - min_y) / span_y * (bottom - top)
                coordinates.extend((canvas_x, canvas_y))
            return coordinates

        return [
            (
                canvas_ring(component.exterior),
                tuple(canvas_ring(hole) for hole in component.holes),
            )
            for component in self._coastline.components
        ]

    def _influence_radius_pixels(self, influence_radius_km: float) -> float:
        rect = self._map_rect()
        if rect is None:
            return 0.0
        try:
            object_scale_km = float(self._variables["object_scale_km"].get())
        except (tk.TclError, ValueError):
            return 0.0
        if object_scale_km <= 0:
            return 0.0
        left, top, right, bottom = rect
        return influence_radius_km / object_scale_km * max(right - left, bottom - top)

    def _draw_constraint(self, constraint: TerrainConstraint) -> None:
        if isinstance(constraint, TerrainBasin):
            colour = "#65bada" if constraint.kind == "lake" else "#d2b487"
            coordinates = [value for point in constraint.points
                           for value in self._normalized_to_canvas(point)]
            self.preview.create_line(coordinates, fill=colour, width=2, dash=(5, 3))
            label = (f"Lake {constraint.water_level_m:,.0f} m"
                     if constraint.water_level_m is not None else "Dry basin")
            if self._terrain is not None:
                intent_id = next((item.intent_id for item in self._terrain.water.review.basins
                                  if item.source == constraint), None)
                if intent_id is not None:
                    label = f"A{intent_id}: {label}"
            if constraint.outlet is not None:
                x, y = self._normalized_to_canvas(constraint.outlet)
                self.preview.create_polygon(x, y - 5, x + 5, y, x, y + 5, x - 5, y,
                                            fill="#ffd85a", outline="")
                label += " / outlet"
            self.preview.create_text(coordinates[0] + 5, coordinates[1] - 5,
                                     text=label, anchor="sw", fill=colour)
            return
        if isinstance(constraint, TerrainRegion):
            coordinates = [value for point in constraint.points
                           for value in self._normalized_to_canvas(point)]
            for ring in (constraint.points, *constraint.holes):
                outline = [v for p in ring for v in self._normalized_to_canvas(p)]
                self.preview.create_polygon(outline, fill="", outline=_REGION_COLOUR,
                                            width=2, dash=(6, 3))
            self.preview.create_text(coordinates[0] + 6, coordinates[1] - 6,
                                     text=constraint.settings.character, anchor="sw",
                                     fill=_REGION_COLOUR)
            return
        if isinstance(constraint, TerrainBrushStroke):
            canvas_points = [self._normalized_to_canvas(point) for point in constraint.points]
            radius = max(2.0, self._influence_radius_pixels(constraint.influence_radius_km))
            if len(canvas_points) == 1:
                x, y = canvas_points[0]
                self.preview.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill=_BRUSH_COLOUR,
                    outline="#d7e7bd",
                    width=1,
                    stipple="gray50",
                )
                label_x, label_y = x, y
            else:
                coordinates = [value for point in canvas_points for value in point]
                self.preview.create_line(
                    coordinates,
                    fill=_BRUSH_COLOUR,
                    width=max(3.0, 2.0 * radius),
                    capstyle="round",
                    joinstyle="round",
                    smooth=False,
                    splinesteps=12,
                    stipple="gray50",
                )
                self.preview.create_line(
                    coordinates,
                    fill="#d7e7bd",
                    width=2,
                    capstyle="round",
                    joinstyle="round",
                    smooth=False,
                    splinesteps=12,
                )
                label_x, label_y = canvas_points[len(canvas_points) // 2]
            self.preview.create_text(
                label_x + 7,
                label_y - 6,
                text=(
                    "brush  "
                    + (
                        f"{constraint.elevation_m:+,.0f} m relative"
                        if constraint.elevation_mode == "relative"
                        else f"{constraint.elevation_m:,.0f} m absolute"
                    )
                    + f"  {2.0 * constraint.influence_radius_km:,.0f} km  "
                    + f"{constraint.intensity:.0%}"
                ),
                anchor="sw",
                fill="#d7e7bd",
                font=("Consolas", 8, "bold"),
            )
            return

        if isinstance(constraint, ElevationPoint):
            x, y = self._normalized_to_canvas(constraint.position)
            radius = max(4.0, self._influence_radius_pixels(constraint.influence_radius_km))
            self.preview.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                outline=_HEIGHT_COLOUR,
                dash=(3, 3),
            )
            self.preview.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill=_HEIGHT_COLOUR,
                outline=MAP_BACKGROUND,
                width=1,
            )
            self.preview.create_text(
                x + 8,
                y - 7,
                text=(
                    f"{constraint.elevation_m:+,.0f} m relative"
                    if constraint.elevation_mode == "relative"
                    else f"{constraint.elevation_m:,.0f} m absolute"
                ),
                anchor="sw",
                fill="#fff3bf",
                font=("Consolas", 8, "bold"),
            )
            return

        colour = _RIDGE_COLOUR if constraint.kind == "ridge" else _VALLEY_COLOUR
        coordinates: list[float] = []
        canvas_points: list[tuple[float, float]] = []
        for point in constraint.points:
            canvas_point = self._normalized_to_canvas(point)
            canvas_points.append(canvas_point)
            coordinates.extend(canvas_point)
        if constraint.kind == "valley":
            self.preview.create_line(
                coordinates,
                fill=colour,
                width=3,
                joinstyle="round",
                capstyle="round",
                smooth=False,
                splinesteps=16,
                arrow=tk.LAST,
                arrowshape=(9, 11, 4),
            )
        else:
            self.preview.create_line(
                coordinates,
                fill=colour,
                width=3,
                joinstyle="round",
                capstyle="round",
                smooth=False,
                splinesteps=16,
            )
        for x, y in canvas_points:
            self.preview.create_oval(x - 3, y - 3, x + 3, y + 3, fill=colour, outline="")
        label_x, label_y = canvas_points[len(canvas_points) // 2]
        self.preview.create_text(
            label_x + 7,
            label_y - 6,
            text=(
                f"{constraint.kind}  "
                + (
                    f"{'relief' if constraint.kind == 'ridge' else 'depth'} "
                    f"{constraint.elevation_m:,.0f} m"
                    if constraint.elevation_mode == "relative"
                    else (
                        f"outlet floor {constraint.elevation_m:,.0f} m"
                        if constraint.kind == "valley"
                        else f"{constraint.elevation_m:,.0f} m absolute"
                    )
                )
            ),
            anchor="sw",
            fill=colour,
            font=("Consolas", 8, "bold"),
        )

    def _draw_draft_structure(self) -> None:
        if self._authoring_tool.get() == "brush":
            self._draw_brush_draft()
            return
        if not self._draft_points:
            return
        tool = self._authoring_tool.get()
        colour = {"ridge": _RIDGE_COLOUR, "valley": _VALLEY_COLOUR,
                  "region": _REGION_COLOUR, "lake": "#65bada",
                  "dry_basin": "#d2b487"}.get(tool, _REGION_COLOUR)
        coordinates: list[float] = []
        canvas_points: list[tuple[float, float]] = []
        for point in self._draft_points:
            canvas_point = self._normalized_to_canvas(point)
            canvas_points.append(canvas_point)
            coordinates.extend(canvas_point)
        if len(canvas_points) >= 2:
            if tool in ("region", "lake", "dry_basin"):
                self.preview.create_line(coordinates, fill=colour, width=2, dash=(6, 4))
                if len(canvas_points) >= 3:
                    self.preview.create_line(*canvas_points[-1], *canvas_points[0],
                                             fill=colour, width=1, dash=(2, 4))
            elif tool == "valley":
                self.preview.create_line(
                    coordinates,
                    fill=colour,
                    width=2,
                    dash=(6, 4),
                    joinstyle="round",
                    smooth=False,
                    splinesteps=16,
                    arrow=tk.LAST,
                    arrowshape=(9, 11, 4),
                )
            else:
                self.preview.create_line(
                    coordinates,
                    fill=colour,
                    width=2,
                    dash=(6, 4),
                    joinstyle="round",
                    smooth=False,
                    splinesteps=16,
                )
        for x, y in canvas_points:
            self.preview.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill=MAP_BACKGROUND,
                outline=colour,
                width=2,
            )

    def _draw_brush_draft(self) -> None:
        self.preview.delete("brush-draft")
        if self._authoring_tool.get() != "brush" or not self._draft_points:
            return
        canvas_points = [self._normalized_to_canvas(point) for point in self._draft_points]
        radius_km = (
            self._active_brush_values[1]
            if self._active_brush_values is not None
            else float(self._tool_sizes["brush"].get()) / 2.0
        )
        radius = max(2.0, self._influence_radius_pixels(radius_km))
        if len(canvas_points) == 1:
            x, y = canvas_points[0]
            self.preview.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=_BRUSH_COLOUR,
                outline="#e2efca",
                stipple="gray50",
                tags=("brush-draft",),
            )
            return
        coordinates = [value for point in canvas_points for value in point]
        self.preview.create_line(
            coordinates,
            fill=_BRUSH_COLOUR,
            width=max(3.0, 2.0 * radius),
            capstyle="round",
            joinstyle="round",
            smooth=False,
            splinesteps=12,
            stipple="gray50",
            tags=("brush-draft",),
        )
        self.preview.create_line(
            coordinates,
            fill="#e2efca",
            width=2,
            capstyle="round",
            joinstyle="round",
            smooth=False,
            splinesteps=12,
            tags=("brush-draft",),
        )

    def _draw_brush_cursor(self) -> None:
        self.preview.delete("brush-cursor")
        if (
            self._authoring_tool.get() != "brush"
            or not self._authoring_enabled
            or self._brush_cursor is None
            or self._selected_instruction is not None
            or self._selection_mode
            or not self._show_instructions.get()
        ):
            return
        x, y = self._normalized_to_canvas(self._brush_cursor)
        width_km = float(self._tool_sizes["brush"].get())
        radius = max(3.0, self._influence_radius_pixels(width_km / 2.0))
        strength = float(self._brush_intensity_percent.get())
        self.preview.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            outline="#e2efca",
            width=2,
            dash=(4, 3),
            tags=("brush-cursor",),
        )
        self.preview.create_oval(
            x - 2,
            y - 2,
            x + 2,
            y + 2,
            fill="#e2efca",
            outline="",
            tags=("brush-cursor",),
        )
        self.preview.create_text(
            x + radius + 7,
            y,
            text=f"{width_km:,.0f} km  {strength:.0f}%",
            anchor="w",
            fill="#e2efca",
            font=("Consolas", 8, "bold"),
            tags=("brush-cursor",),
        )

    def _export(self) -> None:
        if self._terrain is None or self._image is None or not self._reference_is_current():
            return
        stem = Path(self._terrain.source_name).stem
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export colour height map",
            initialfile=f"{stem}-height-map.png",
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"),),
        )
        if not selected:
            return
        try:
            with closing(compose_height_map(self._image, self._water_display)) as image:
                save_height_map(image, self._terrain, Path(selected))
        except OSError as error:
            messagebox.showerror("Export failed", str(error), parent=self.root)
            return
        self.status_label.configure(text=f"Exported {Path(selected).name}")


def run(project: Path | None = None, *, world: Path | None = None) -> None:
    """Launch the world-source and local-terrain workspaces."""

    root = tk.Tk()
    TerrainApp(root, project, world=world)
    root.mainloop()
