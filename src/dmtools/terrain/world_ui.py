# pyright: reportUnknownMemberType=false
"""World workspace: world source, context and planet stages beside one map view."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from PIL import Image
from shapely.geometry import Point, Polygon

from dmtools.terrain.adapters.world_geology import world_fingerprint
from dmtools.terrain.adapters.world_project import WORLD_EXTENSION
from dmtools.terrain.adapters.world_svg import load_world_svg
from dmtools.terrain.application.planet import (
    PlanetRun,
    export_planet,
    generate_planet_run,
    planet_identity,
    user_tile_cache,
)
from dmtools.terrain.application.planet_region import RegionRun, export_region, region_window
from dmtools.terrain.application.region_views import region_themes, render_region_theme
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
from dmtools.terrain.domain.planet import REGION_LEVEL_NAMES, PlanetSettings
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
    WorldContextSettings,
    exposure_range_km,
    exposure_steps,
)
from dmtools.terrain.map_probes import PlanetProbe
from dmtools.terrain.pipeline.control import CancellationToken
from dmtools.terrain.pipeline.planet_regional import RegionalParent
from dmtools.terrain.pipeline.world import WorldMap, prepare_world_map
from dmtools.terrain.planet_ui import PlanetPanel
from dmtools.terrain.ui_components import StatusBar, WrappingLabel
from dmtools.terrain.ui_jobs import JobRunner, JobState, LatestWorker, Report, TkPump
from dmtools.terrain.ui_style import GAP, WARNING
from dmtools.terrain.world_bathymetry_ui import BathymetryEditor
from dmtools.terrain.world_geology_ui import GeologyEditor
from dmtools.terrain.world_terrain_ui import WorldTerrainPanel
from dmtools.terrain.world_view import SOURCE, SourceScene, WorldMapView

REGION_PIXELS = 900

type _Ownership = tuple[tuple[WorldContinent, ...], tuple[WorldAssignment, ...]]


class WorldWorkspace(ttk.Frame):
    def __init__(
        self, parent: tk.Misc, on_change: Callable[[], None],
        on_terrain_ready: Callable[[WorldTerrainCreated], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Paper.TFrame", padding=(18, 12))
        self.on_change = on_change
        self.on_terrain_ready = on_terrain_ready
        self.source: WorldSource | None = None
        self.path: Path | None = None
        self.validated: WorldMap | None = None
        self.geology_editor: GeologyEditor | None = None
        self._geology_file: GeologyFile | None = None
        self.bathymetry_editor: BathymetryEditor | None = None
        self._bathymetry_file: BathymetryFile | None = None
        self.context_run: WorldContextRun | None = None
        self.planet_run: PlanetRun | None = None
        self.region_workers: int | None = None
        self.continents: tuple[WorldContinent, ...] = ()
        self.assignments: tuple[WorldAssignment, ...] = ()
        self._undo: list[_Ownership] = []
        self._redo: list[_Ownership] = []
        self._saved_signature: object = None
        self._loading = False
        self._closed = False
        self._after_save: Callable[[], None] | None = None
        self._controls: list[tuple[ttk.Widget, str]] = []
        self._was_busy = False
        self.pump = TkPump(self)
        self.jobs = JobRunner(self.pump, self._job_state, self._job_failed, self._job_cancelled)
        self.renders = LatestWorker(self.pump, self._render_failed)
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
        self.context_rows = tk.StringVar(self, value="180")
        self.context_detail = tk.StringVar(
            self, value="Generate geographic context from the current world."
        )
        self._build()
        self.context_rows.trace_add("write", self._context_settings_changed)
        for value in self.values.values():
            value.trace_add("write", self._changed)

    @property
    def busy(self) -> bool:
        return self.jobs.busy

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

    # Layout

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self, style="Paper.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, GAP))
        ttk.Label(header, text="World", style="Header.TLabel").pack(side="left", padx=(0, 6))
        for label, action in (
            ("Import SVG…", self.choose_svg),
            ("Open world…", self.choose_world),
            ("Save", self.save),
            ("Save As…", lambda: self.save(save_as=True)),
        ):
            self._button(header, label, action).pack(side="left", padx=(GAP, 0))
        ttk.Separator(header, orient="vertical").pack(side="left", fill="y", padx=2 * GAP)
        for label, action in (("Geology…", self.edit_geology),
                              ("Bathymetry…", self.edit_bathymetry)):
            self._button(header, label, action).pack(side="left", padx=(0, GAP))

        sidebar = ttk.Frame(self, style="Paper.TFrame")
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(0, weight=1)
        pages = ttk.Notebook(sidebar, style="Stages.TNotebook", width=360)
        self.pages = pages
        pages.grid(row=0, column=0, sticky="nsew")
        mapping = ttk.Frame(pages, style="Panel.TFrame", padding=10)
        frame_page = ttk.Frame(pages, style="Panel.TFrame", padding=12)
        self.adjustments_page = ttk.Frame(pages, style="Panel.TFrame", padding=10)
        self.context_page = ttk.Frame(pages, style="Panel.TFrame", padding=10)
        self.planet_panel = PlanetPanel(pages, self.generate_planet, self.export_planet)
        self.terrain_panel = WorldTerrainPanel(
            pages, self.create_terrain, self._open_prepared_terrain
        )
        for page, title in (
            (mapping, "1  Shapes"),
            (frame_page, "2  Frame"),
            (self.adjustments_page, "Adjustments"),
            (self.context_page, "3  Context"),
            (self.planet_panel, "4  Planet"),
            (self.terrain_panel, "5  Terrain"),
        ):
            pages.add(page, text=title)
        self._build_mapping(mapping)
        self._build_frame(frame_page)
        self._build_adjustments(self.adjustments_page)
        self._build_context(self.context_page)
        self._button(sidebar, "Validate world", self.validate, accent=True).grid(
            row=1, column=0, sticky="ew", pady=(GAP, 0)
        )

        self.map_view = WorldMapView(
            self, self.renders, self.jobs, pick_shape=self.pick_shape,
            request_region=self.zoom_region, export_region=self.export_region,
            status=self.status.set,
        )
        self.map_view.grid(row=1, column=1, sticky="nsew")
        self.status_bar = StatusBar(self, self.status, self.cancel_job)
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(GAP, 0))

    def _build_mapping(self, mapping: ttk.Frame) -> None:
        mapping.columnconfigure(0, weight=1)
        mapping.rowconfigure(2, weight=1)
        WrappingLabel(mapping, textvariable=self.summary, style="Muted.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, GAP)
        )
        tools = ttk.Frame(mapping, style="Panel.TFrame")
        tools.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self._button(tools, "Suggest from groups", self.suggest_groups).pack(side="left")
        self._button(tools, "Undo", self.undo).pack(side="left", padx=4)
        self._button(tools, "Redo", self.redo).pack(side="left")
        self.tree = ttk.Treeview(mapping, columns=("owner",), selectmode="extended", height=10)
        self.tree.tag_configure("issue", foreground=WARNING)
        self.tree.heading("#0", text="Source shape")
        self.tree.heading("owner", text="Assignment")
        self.tree.column("#0", width=200, minwidth=110, stretch=True)
        self.tree.column("owner", width=120, minwidth=95, stretch=False)
        self.tree.grid(row=2, column=0, sticky="nsew")

        def scroll_tree(*args: str) -> None:
            self.tree.yview(*args)

        scrollbar = ttk.Scrollbar(mapping, orient="vertical", command=scroll_tree)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._selection)
        self.detail = WrappingLabel(
            mapping, text="Select shapes here or click the Source map.", style="Muted.TLabel"
        )
        self.detail.grid(row=3, column=0, columnspan=2, sticky="ew", pady=GAP)
        ttk.Label(mapping, text="Continent name (choose or enter)", style="Body.TLabel").grid(
            row=4, column=0, sticky="w"
        )
        self.owner_input = ttk.Combobox(mapping, textvariable=self.owner)
        self.owner_input.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(3, 6))
        self._controls.append((self.owner_input, "normal"))
        self.role_input = ttk.Combobox(
            mapping, textvariable=self.role, state="readonly",
            values=("Mainland", "Island", "Exclude"),
        )
        self.role_input.grid(row=6, column=0, columnspan=2, sticky="ew")
        self._controls.append((self.role_input, "readonly"))
        self._button(mapping, "Assign selected shapes", self.assign_selected).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=6
        )
        actions = ttk.Frame(mapping, style="Panel.TFrame")
        actions.grid(row=8, column=0, columnspan=2, sticky="ew")
        actions.columnconfigure((0, 1), weight=1)
        self._button(actions, "Rename continent…", self.rename_continent).grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        self._button(actions, "Select all", self.select_all).grid(
            row=0, column=1, sticky="ew", padx=(3, 0)
        )

    def _build_frame(self, frame_page: ttk.Frame) -> None:
        frame_page.columnconfigure(0, weight=1)
        ttk.Label(frame_page, text="Full-world spherical Plate Carrée",
                  style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
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
            entry = ttk.Entry(frame_page, textvariable=self.values[key])
            entry.grid(row=row * 2 + 1, column=0, sticky="ew")
            self._controls.append((entry, "normal"))
        WrappingLabel(
            frame_page,
            text="This frame represents 360° longitude and 180° latitude. "
            "Confirm its bounds from your map's projection; exclude legends and margins. "
            "SVG display size is not planetary scale. Enter your planet's radius.",
            style="Muted.TLabel",
        ).grid(row=17, column=0, sticky="ew", pady=12)

    def _build_adjustments(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ttk.Label(page, text="Import adjustments", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, GAP)
        )
        self.adjustment_tree = ttk.Treeview(page, show="tree", selectmode="browse", height=6)
        self.adjustment_tree.grid(row=1, column=0, sticky="nsew")
        self.adjustment_tree.column("#0", width=300, minwidth=160)

        def scroll_adjustments(*args: str) -> None:
            self.adjustment_tree.yview(*args)

        adjustment_scroll = ttk.Scrollbar(page, orient="vertical", command=scroll_adjustments)
        adjustment_scroll.grid(row=1, column=1, sticky="ns")
        self.adjustment_tree.configure(yscrollcommand=adjustment_scroll.set)
        self.adjustment_tree.bind("<<TreeviewSelect>>", self._review_adjustment)
        self.adjustment_detail = WrappingLabel(
            page, style="Body.TLabel",
            text="Validate the world to inspect export rounding and shared land. "
            "The original SVG and assignments are retained.",
        )
        self.adjustment_detail.grid(row=2, column=0, columnspan=2, sticky="ew", pady=12)

    def _build_context(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        page.rowconfigure(5, weight=1)
        ttk.Label(page, text="Geographic context", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, GAP)
        )
        ttk.Label(page, text="Latitude cells · longitude uses twice as many",
                  style="Body.TLabel").grid(row=1, column=0, sticky="w")
        resolution = ttk.Combobox(
            page, textvariable=self.context_rows, values=("90", "180", "360"), state="readonly"
        )
        resolution.grid(row=2, column=0, sticky="ew", pady=6)
        self._controls.append((resolution, "readonly"))
        self._button(page, "Generate context", self.generate_context, accent=True).grid(
            row=3, column=0, sticky="ew", pady=5
        )
        buttons = ttk.Frame(page, style="Panel.TFrame")
        buttons.grid(row=4, column=0, sticky="ew", pady=5)
        buttons.columnconfigure((0, 1), weight=1)
        self._button(buttons, "Export context…", self.export_context).grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        self._button(buttons, "Open context…", self.choose_context).grid(
            row=0, column=1, sticky="ew", padx=(3, 0)
        )
        details = ttk.Frame(page, style="Panel.TFrame")
        details.grid(row=5, column=0, sticky="nsew", pady=12)
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        style = ttk.Style(self)
        self.context_text = tk.Text(
            details, height=4, width=1, wrap="word", state="disabled", borderwidth=0,
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

    # World inputs and the map

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
        self._update_map()

    def _update_map(self) -> None:
        if self._closed:
            return
        if self.source is None:
            self.map_view.show_source(None)
            return
        try:
            frame: WorldFrame | None = self._frame()
        except ValueError:
            frame = None
        try:
            meridian = float(self.values["meridian"].get())
        except ValueError:
            meridian = 0.0
        self.map_view.show_source(SourceScene(
            self.source, self._bounds(), self.assignments, frozenset(self.tree.selection()),
            frame, meridian,
        ))

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
                f"planet radius in the Frame stage. {error}"
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

    def _bounds(self) -> tuple[float, float, float, float]:
        try:
            return self._frame().bounds
        except ValueError:
            return self.source.suggested_bounds if self.source else (0.0, 0.0, 360.0, 180.0)

    def fit(self) -> None:
        self.map_view.fit()

    def escape(self) -> None:
        self.map_view.escape()

    # Jobs

    def _set_busy(self, busy: bool) -> None:
        for control, normal in self._controls:
            control["state"] = "disabled" if busy else normal
        self.terrain_panel.set_busy(busy)
        self.planet_panel.set_busy(busy)
        self.map_view.set_busy(busy)

    def _job_state(self, state: JobState | None) -> None:
        self.status_bar.show(state)
        busy = state is not None
        if busy != self._was_busy:
            self._was_busy = busy
            self._set_busy(busy)

    def _run[T](
        self,
        label: str,
        work: Callable[[Report, CancellationToken], T],
        done: Callable[[T], None],
        *,
        cancellable: bool = True,
    ) -> None:
        self.jobs.start(label, work, done, cancellable=cancellable)

    def _job_failed(self, error: Exception) -> None:
        self._after_save = None
        self.status.set(str(error).partition("\n")[0])
        if isinstance(error, WorldGeometryError):
            self._select_issues(error.feature_ids)
        messagebox.showerror("World map needs attention", str(error), parent=self)

    def _job_cancelled(self) -> None:
        self._after_save = None
        self.status.set("World job cancelled. No new completed result was published.")

    def _render_failed(self, error: Exception) -> None:
        self.status.set(f"Could not draw this map: {str(error).partition(chr(10))[0]}")

    def cancel_job(self) -> None:
        self.jobs.cancel()

    # Context

    def _clear_context(self) -> None:
        had_context = self.context_run is not None
        self.context_run = None
        self.map_view.set_context(None)
        self.context_detail.set(
            "Inputs changed. Generate context again."
            if had_context
            else "Generate geographic context from the current world. Land and water areas use "
            "the declared sphere. Small features remain in the source "
            "even when a cell cannot resolve them."
        )

    def _context_settings_changed(self, *_args: str) -> None:
        if self.context_run is not None and self.context_rows.get() == str(
            self.context_run.context.grid.settings.latitude_cells
        ):
            return
        self._clear_context()

    def _scroll_context_detail(self, *args: str) -> None:
        self.context_text.yview(*args)

    def _context_detail_changed(self, *_args: str) -> None:
        self.context_text.configure(state="normal")
        self.context_text.delete("1.0", "end")
        self.context_text.insert("1.0", self.context_detail.get())
        self.context_text.configure(state="disabled")
        self.context_text.yview_moveto(0)

    def _show_context(self, run: WorldContextRun) -> None:
        self.context_run = run
        self._show_context_details()
        self.map_view.set_context(run)
        self.map_view.set_layer("Land coverage")
        self.pages.select(self.context_page)

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

        def done(run: WorldContextRun) -> None:
            if signature != self._signature() or str(settings.latitude_cells) != (
                self.context_rows.get()
            ):
                self.status.set("World inputs changed; generate context again.")
                return
            self.validated = run.context.world
            self._show_summary(self.validated)
            self._show_context(run)
            self.status.set(
                "Geographic context ready. Review land, water and resolution support; "
                "export to retain a reproducible result."
            )

        self._run(
            "Generating geographic context",
            lambda report, token: generate_context(project, settings, report,
                                                   cancellation=token),
            done,
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
        signature = self._signature()

        def done(run: WorldContextRun) -> None:
            if signature != self._signature():
                self.status.set(
                    "World inputs changed while opening context; current work retained."
                )
                return
            # The embedded source is an immutable product, never a Save target.
            self.accept_world(run.context.world, None)
            self.context_rows.set(str(run.context.grid.settings.latitude_cells))
            self._show_context(run)
            self.status.set(
                f"Opened verified context: {path}. Saved producer identity retained; "
                "Save writes a separate world project."
            )

        self._run(
            "Verifying context source, hashes and numeric products",
            lambda _report, token: open_context(path, cancellation=token),
            done,
        )

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
        self._run(
            "Exporting context and its source snapshot",
            lambda _report, token: export_context(run, Path(selected), cancellation=token),
            lambda path: self.status.set(
                f"Context exported: {path}. Source snapshot and output hashes included."
            ),
        )

    # Planet and regions

    def _clear_planet(self) -> None:
        if self.planet_run is not None:
            self.planet_run = None
            self.planet_panel.clear("Inputs changed. Generate the planet again.")
            self.map_view.set_planet(None, None)

    def generate_planet(self, settings: PlanetSettings, geology_path: Path | None) -> None:
        if self.busy:
            return
        try:
            project = self.project()
        except ValueError as error:
            messagebox.showerror("Planet needs a valid world", str(error), parent=self)
            return
        signature = self._signature()

        def work(report: Report, token: CancellationToken) -> tuple[PlanetRun, PlanetProbe]:
            run = generate_planet_run(project, geology_path, settings, report, cancellation=token)
            report(None, "Preparing the map readout")
            return run, PlanetProbe(run.result)

        def done(ready: tuple[PlanetRun, PlanetProbe]) -> None:
            if signature != self._signature():
                self.status.set("World inputs changed; generate the planet again.")
                return
            run, probe = ready
            self.planet_run = run
            self.planet_panel.show(run)
            self.pages.select(self.planet_panel)
            self.map_view.set_planet(run, probe)
            self.status.set(
                "Planet ready. Choose maps and projections above the map; export to keep a "
                "reproducible build."
            )

        self._run("Generating the planet", work, done)

    def export_planet(self, destination: Path) -> None:
        run = self.planet_run
        if self.busy or run is None:
            return
        self._run(
            "Exporting the planet build",
            lambda _report, token: export_planet(run, destination, cancellation=token),
            lambda path: self.status.set(
                f"Planet exported: {path}. Inputs and outputs are hashed."
            ),
        )

    def zoom_region(
        self, longitude: float, latitude: float, radius_km: float, level: int = 1
    ) -> None:
        """Build detail of ``level`` (1 region, 2 province, 3 local) around a point."""
        run = self.planet_run
        if self.busy or run is None:
            return
        identity = planet_identity(run)
        workers = self.region_workers

        def work(report: Report, token: CancellationToken) -> tuple[RegionRun, Image.Image, str]:
            parent = RegionalParent.from_result(run.result)
            region = region_window(
                parent, identity, user_tile_cache(), (longitude, latitude), radius_km,
                level=level, pixels=REGION_PIXELS, workers=workers, progress=report,
                cancellation=token,
            )
            report(0.96, "Drawing the map")
            theme = region_themes(region.window)[0].id
            return region, render_region_theme(region.window, theme), theme

        def done(ready: tuple[RegionRun, Image.Image, str]) -> None:
            if run is not self.planet_run:
                self.status.set("The planet changed; zoom to the region again.")
                return
            region, image, theme = ready
            self.map_view.add_region(region, image, theme)
            self.status.set(
                f"{REGION_LEVEL_NAMES[level - 1].title()} detail ready from "
                f"{len(region.window.tiles)} tiles; tiles are cached for later zooms."
            )

        self._run(
            f"Generating {REGION_LEVEL_NAMES[level - 1]} detail ({radius_km:,.0f} km radius)",
            work, done,
        )

    def export_region(self, run: RegionRun, destination: Path) -> None:
        if self.busy:
            return
        self._run(
            "Exporting the region",
            lambda _report, _token: export_region(run, destination),
            lambda path: self.status.set(f"Region exported: {path}"),
            cancellable=False,
        )

    # Terrain

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

        def done(created: WorldTerrainCreated) -> None:
            self.terrain_panel.show_created(created)
            self.pages.select(self.terrain_panel)
            self.status.set(f"Terrain project saved: {created.loaded.path}")
            if signature == self._signature():
                self._open_prepared_terrain(created)
            else:
                self.status.set(
                    f"World inputs changed. Prepared project retained separately: "
                    f"{created.loaded.path}"
                )

        self._run(
            "Preparing world land for terrain generation",
            lambda report, token: create_world_terrain_project(
                project, continent_id, output, progress=report, cancellation=token,
                geology_path=geology_path, context=context,
            ),
            done,
        )

    # Opening and saving

    def choose_svg(self) -> None:
        def choose() -> None:
            selected = filedialog.askopenfilename(
                parent=self, title="Import full world SVG", filetypes=[("SVG world map", "*.svg")]
            )
            if selected:
                self.load_svg(Path(selected))

        self.guard(choose)

    def load_svg(self, path: Path) -> None:
        self._run(
            "Reading world source and retained shapes",
            lambda _report, _token: load_world_svg(path), self.accept_source, cancellable=False,
        )

    def choose_world(self) -> None:
        def choose() -> None:
            selected = filedialog.askopenfilename(
                parent=self, title="Open world", filetypes=[("DM Tools world", "*.dmworld.json")]
            )
            if selected:
                self.load_world(Path(selected))

        self.guard(choose)

    def load_world(self, path: Path) -> None:
        self._run(
            "Opening and checking portable world",
            lambda _report, _token: open_world(path),
            lambda world: self.accept_world(world, path),
            cancellable=False,
        )

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
        self.map_view.flat.viewport.fit()
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
        self._update_map()

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

        def done(world: WorldMap) -> None:
            self.validated = world
            self._show_summary(world)
            self.status.set(
                "World source validated. Save it to retain this geography and "
                f"continent assignment. {len(world.adjustments)} import adjustments "
                "are listed in the Adjustments stage."
            )

        self._run(
            "Checking world frame, seams, ownership and overlap",
            lambda _report, _token: prepare_world_map(project), done, cancellable=False,
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

        def done(world: WorldMap) -> None:
            self.validated = world
            self._show_summary(world)
            self.path = target
            self._saved_signature = self._signature()
            self.status.set(
                f"Saved {target.name}. Original SVG is embedded. "
                f"{len(world.adjustments)} import adjustments recorded by preparation."
            )
            self.on_change()
            callback, self._after_save = self._after_save, None
            if callback:
                callback()

        self._run(
            "Validating and saving portable world",
            lambda _report, _token: save_world(project, target), done, cancellable=False,
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

    # Shapes and continents

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
        self._update_map()

    def _select_issues(self, identifiers: tuple[str, ...]) -> None:
        existing = [key for key in identifiers if self.tree.exists(key)]
        if existing:
            self.map_view.set_layer(SOURCE)
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
            self.detail.configure(text="Select shapes here or click the Source map.")
        self._update_map()

    def pick_shape(self, position: tuple[float, float], additive: bool) -> None:
        """Select the source shape under a source-unit position (Ctrl adds to the selection)."""
        if self.source is None:
            return
        span = self._bounds()[2] - self._bounds()[0]
        excluded = {a.feature_id for a in self.assignments if a.role == "exclude"}
        for feature in reversed(self.source.features):
            if feature.id in excluded and not self.map_view.show_excluded.get():
                continue
            if any(
                Polygon(c.exterior, c.holes).covers(Point(position[0] + shift, position[1]))
                for c in feature.components
                for shift in (-span, 0.0, span)
            ):
                if additive:
                    self.tree.selection_add(feature.id)
                else:
                    self.tree.selection_set(feature.id)
                self.tree.see(feature.id)
                self.pages.select(0)
                return

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

    # Editors

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
            return

        def done(world: WorldMap) -> None:
            self.validated = world
            self._show_summary(world)
            self._open_geology_editor(world)

        self._run(
            "Preparing world for geology inputs",
            lambda _report, _token: prepare_world_map(project), done, cancellable=False,
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
            f"{len(world.adjustments)} import adjustments (see Adjustments). "
            "Areas use prepared coverage on the declared sphere."
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

    def close(self) -> None:
        self._closed = True
        if self.geology_editor is not None:
            self.geology_editor.close()
        if self.bathymetry_editor is not None:
            self.bathymetry_editor.close()
        self.jobs.close()
        self.renders.cancel()
        self.pump.close()
