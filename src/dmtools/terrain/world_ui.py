# pyright: reportUnknownMemberType=false
"""World workspace: guided steps from a drawn map to a whole planet, beside one map.

The steps run down the left (Source map, Planet, Geology, Generate, Explore), with
secondary tools after them. The workspace owns the world document, its derived
results and the single job runner; each step page only gathers input and shows
results.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from math import pi
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from PIL import Image
from shapely.geometry import Point, Polygon

from dmtools.terrain.adapters.world_geology import world_fingerprint
from dmtools.terrain.adapters.world_project import WORLD_EXTENSION
from dmtools.terrain.adapters.world_svg import drawn_coast_detail_km, load_world_svg
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
from dmtools.terrain.domain.world_geology import WorldGeologyRecipe, follow_world
from dmtools.terrain.map_probes import PlanetProbe
from dmtools.terrain.pipeline.control import CancellationToken
from dmtools.terrain.pipeline.planet_regional import RegionalParent
from dmtools.terrain.pipeline.world import WorldMap, prepare_world_map
from dmtools.terrain.planet_ui import PlanetPanel, PlanetResultPanel
from dmtools.terrain.ui_components import (
    ChoiceList,
    Collapsible,
    ScrollPage,
    SegmentedChoice,
    StatusBar,
    StepRail,
    WrappingLabel,
    button_row,
    field,
    hint,
    page_title,
    section,
)
from dmtools.terrain.ui_jobs import JobRunner, JobState, LatestWorker, Report, TkPump
from dmtools.terrain.ui_style import GAP, WARNING
from dmtools.terrain.world_bathymetry_ui import BathymetryEditor
from dmtools.terrain.world_geology_ui import GeologyEditor
from dmtools.terrain.world_terrain_ui import WorldTerrainPanel
from dmtools.terrain.world_view import CONTEXT, PLANET, SOURCE, SourceScene, WorldMapView

REGION_PIXELS = 900
STEPS = {
    "source": "Source map",
    "planet": "Planet",
    "geology": "Geology",
    "generate": "Generate",
    "explore": "Explore",
}
TOOLS = {"context": "Geographic context", "ocean": "Ocean floor", "terrain": "Local terrain"}
EARTH_RADIUS_KM = 6371.0
RADIUS_PRESETS = (("Earth", 6371.0), ("Mars", 3390.0), ("Large", 9000.0))
CONTEXT_DETAIL = (
    ("90", "Coarse", "2° cells · a few seconds"),
    ("180", "Standard", "1° cells, about 110 km on an Earth-sized world"),
    ("360", "Fine", "0.5° cells · slower; resolves narrower straits"),
)
ROLES: dict[str, WorldRole] = {"Mainland": "mainland", "Island": "island", "Exclude": "exclude"}

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
        self.geology: GeologyEditor | None = None
        self.bathymetry_editor: BathymetryEditor | None = None
        self._bathymetry_file: BathymetryFile | None = None
        self.context_run: WorldContextRun | None = None
        self.planet_run: PlanetRun | None = None
        self._planet_geology: WorldGeologyRecipe | None = None
        self.region_workers: int | None = None
        self.continents: tuple[WorldContinent, ...] = ()
        self.assignments: tuple[WorldAssignment, ...] = ()
        self.step = "source"
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
                ("radius", f"{EARTH_RADIUS_KM:g}"),
                ("meridian", "0"),
                ("x", "0"),
                ("y", "0"),
                ("width", "360"),
                ("height", "180"),
                ("coast", ""),
            )
        }
        self.owner = tk.StringVar(self)
        self.role = tk.StringVar(self, value="Mainland")
        self.status = tk.StringVar(self, value="Import an SVG world map, or open a saved world.")
        self.document = tk.StringVar(self)
        self.source_label = tk.StringVar(self)
        self.summary = tk.StringVar(self)
        self.scale_text = tk.StringVar(self)
        self.check = tk.StringVar(self)
        self.context_rows = tk.StringVar(self, value="180")
        self.context_detail = tk.StringVar(
            self, value="Generate geographic context from the current world."
        )
        self.ocean_detail = tk.StringVar(self)
        self._build()
        self.context_rows.trace_add("write", self._context_settings_changed)
        for value in self.values.values():
            value.trace_add("write", self._changed)
        for key in ("radius", "width", "height"):
            self.values[key].trace_add("write", self._describe_scale)
        self._describe_scale()
        self._clear_check()
        self.show_step("source")
        self._refresh_steps()

    @property
    def busy(self) -> bool:
        return self.jobs.busy

    @property
    def dirty(self) -> bool:
        """The world document has unsaved changes (the geology recipe is separate)."""
        return self.source is not None and self._signature() != self._saved_signature

    @property
    def unsaved(self) -> bool:
        """Anything in this workspace that a save would keep."""
        return self.dirty or (self.geology is not None and self.geology.dirty)

    def _signature(self) -> object:
        return (
            self.source.sha256 if self.source else None,
            tuple((k, v.get()) for k, v in self.values.items()),
            self.continents,
            self.assignments,
        )

    def _button(
        self, parent: tk.Misc, label: str, action: Callable[[], object], *,
        style: str = "Quiet",
    ) -> ttk.Button:
        button = ttk.Button(parent, text=label, command=action, style=f"{style}.TButton")
        self._controls.append((button, "normal"))
        return button

    # Layout

    def _build(self) -> None:
        self.columnconfigure(2, weight=1)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(1, minsize=370)
        header = ttk.Frame(self, style="Paper.TFrame")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, GAP))
        ttk.Label(header, text="World", style="Header.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.document, style="Document.TLabel").pack(
            side="left", padx=(2 * GAP, 0), pady=(8, 0)
        )
        for label, action in (
            ("Save As…", lambda: self.save(save_as=True)),
            ("Save", self.save),
            ("Open world…", self.choose_world),
            ("Import SVG…", self.choose_svg),
        ):
            self._button(header, label, action).pack(side="right", padx=(GAP, 0))

        self.rail = StepRail(self, self.show_step)
        self.rail.grid(row=1, column=0, sticky="nsw", padx=(0, GAP))
        for key, title in STEPS.items():
            self.rail.add_step(key, title)
        self.rail.add_heading("More tools")
        for key, title in TOOLS.items():
            self.rail.add_tool(key, title)

        self.page_area = ttk.Frame(self, style="Panel.TFrame")
        self.page_area.grid(row=1, column=1, sticky="nsew", padx=(0, 12))
        self.page_area.columnconfigure(0, weight=1)
        self.page_area.rowconfigure(0, weight=1)
        self.pages = {key: ScrollPage(self.page_area) for key in (*STEPS, *TOOLS)}
        self.map_view_show_excluded = tk.BooleanVar(self, value=True)
        self._build_source(self.pages["source"].body)
        self._build_planet(self.pages["planet"].body)
        self._build_geology(self.pages["geology"].body)
        self.planet_panel = PlanetPanel(
            self.pages["generate"].body, self.generate_planet,
            lambda: self.show_step("geology"),
        )
        self.planet_panel.pack(fill="x")
        self.result_panel = PlanetResultPanel(
            self.pages["explore"].body, export=self.export_planet,
            zoom=self.pick_region, save_image=self.save_map_image,
            change_settings=lambda: self.show_step("generate"),
        )
        self.result_panel.pack(fill="x")
        self._build_context(self.pages["context"].body)
        self._build_ocean(self.pages["ocean"].body)
        self.terrain_panel = WorldTerrainPanel(
            self.pages["terrain"].body, self.create_terrain, self._open_prepared_terrain
        )
        self.terrain_panel.pack(fill="x")

        self.map_area = ttk.Frame(self, style="Panel.TFrame")
        self.map_area.grid(row=1, column=2, sticky="nsew")
        self.map_area.columnconfigure(0, weight=1)
        self.map_area.rowconfigure(0, weight=1)
        self.map_view = WorldMapView(
            self.map_area, self.renders, self.jobs, pick_shape=self.pick_shape,
            request_region=self.zoom_region, export_region=self.export_region,
            status=self.status.set, show_excluded=self.map_view_show_excluded,
        )
        self.map_view.grid(row=0, column=0, sticky="nsew")
        self.status_bar = StatusBar(self, self.status, self.cancel_job)
        self.status_bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(GAP, 0))

    def _nav(
        self, key: str, back: str | None, forward: tuple[str, Callable[[], None]] | None,
    ) -> None:
        """Back and next buttons at the foot of a step page, always in view."""
        row = button_row(self.pages[key].footer, pady=(GAP, 0))
        if back is not None:
            self._button(row, f"← {STEPS[back]}", lambda: self.show_step(back)).pack(
                side="left"
            )
        if forward is not None:
            label, action = forward
            self._button(row, label, action, style="Accent").pack(side="right")

    def _build_source(self, page: ttk.Frame) -> None:
        page_title(page, "Source map",
                   "Import the SVG of your world, then say which shapes make up each continent.")
        self.source_empty = ttk.Frame(page, style="Panel.TFrame")
        hint(self.source_empty,
             "The SVG must show the whole planet as a flat world map: 360° of longitude "
             "across and 180° of latitude down, so twice as wide as it is tall. Draw land "
             "as closed, filled shapes; lakes can be holes.", style="Muted.TLabel")
        self._button(self.source_empty, "Import SVG map…", self.choose_svg,
                     style="Accent").pack(fill="x", pady=(2 * GAP, 0))
        self._button(self.source_empty, "Open a saved world…", self.choose_world).pack(
            fill="x", pady=(GAP, 0)
        )
        self.source_empty.pack(fill="x", pady=(2 * GAP, 0))
        self.source_loaded = ttk.Frame(page, style="Panel.TFrame")
        loaded = self.source_loaded
        ttk.Label(loaded, textvariable=self.source_label, style="Body.TLabel").pack(
            anchor="w", pady=(GAP, 0)
        )
        hint(loaded, textvariable=self.summary, style="Muted.TLabel")
        shapes = section(loaded, "Continents")
        hint(shapes, "Each shape is mainland or an island of one continent, or excluded "
             "from the world. Click shapes here or on the map; Ctrl adds to the selection.")
        self._button(shapes, "Suggest from SVG groups", self.suggest_groups).pack(
            anchor="w", pady=(GAP, 0)
        )
        hint(shapes, "Each top-level group or layer becomes a continent; groups named "
             "Islands hold its islands and a layer named Map furniture is excluded.")
        tree_frame = ttk.Frame(shapes, style="Panel.TFrame")
        tree_frame.pack(fill="x", pady=(GAP, 0))
        tree_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=("owner",), selectmode="extended",
                                 height=9)
        self.tree.tag_configure("issue", foreground=WARNING)
        self.tree.heading("#0", text="Shape")
        self.tree.heading("owner", text="Continent")
        self.tree.column("#0", width=150, minwidth=100, stretch=True)
        self.tree.column("owner", width=160, minwidth=100, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")

        def scroll_tree(*args: str) -> None:
            self.tree.yview(*args)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=scroll_tree)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._selection)
        self.detail = WrappingLabel(loaded, text="", style="Help.TLabel")
        self.detail.pack(fill="x", pady=(2, 0))
        ttk.Checkbutton(
            loaded, text="Show excluded shapes on the map",
            variable=self.map_view_show_excluded, command=self._update_map,
        ).pack(anchor="w", pady=(GAP // 2, 0))
        assign = section(loaded, "Assign the selected shapes")
        ttk.Label(assign, text="Continent", style="Body.TLabel").pack(anchor="w")
        self.owner_input = ttk.Combobox(assign, textvariable=self.owner)
        self.owner_input.pack(fill="x", pady=(2, 0))
        self._controls.append((self.owner_input, "normal"))
        hint(assign, "Choose a continent, or type a new name to start one.")
        role_row = button_row(assign)
        ttk.Label(role_row, text="As", style="Body.TLabel").pack(side="left", padx=(0, GAP))
        self.role_input = SegmentedChoice(
            role_row, self.role, [("Mainland", "Mainland"), ("Island", "Island")]
        )
        self.role_input.pack(side="left")
        hint(assign, "Islands belong to the continent but keep their own coastline.")
        actions = button_row(assign)
        actions.columnconfigure((0, 1), weight=1)
        self._button(actions, "Assign", self.assign_selected, style="Accent").grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        self._button(actions, "Exclude", self.exclude_selected).grid(
            row=0, column=1, sticky="ew", padx=(3, 0)
        )
        hint(assign, "Exclude legends, scale bars and frames so they do not become land.")
        more = button_row(loaded, pady=(2 * GAP, 0))
        for label, action in (
            ("Rename continent…", self.rename_continent), ("Select all", self.select_all),
            ("Undo", self.undo), ("Redo", self.redo),
        ):
            self._button(more, label, action, style="Small").pack(side="left", padx=(0, 4))
        self._nav("source", None, ("Next: Planet →", self.next_from_source))

    def _build_planet(self, page: ttk.Frame) -> None:
        page_title(page, "Planet", "How big the world is, and how your map wraps the globe.")
        name = field(page, "World name", self.values["name"], width=30)
        self._controls.append((name, "normal"))
        radius = field(page, "Planet radius", self.values["radius"], unit="km", width=10)
        self._controls.append((radius, "normal"))
        for label, value in RADIUS_PRESETS:
            self._button(
                radius.master, label, lambda value=value: self.values["radius"].set(f"{value:g}"),
                style="Small",
            ).pack(side="left", padx=(GAP // 2 if label != "Earth" else GAP, 0))
        hint(page, textvariable=self.scale_text)
        meridian = field(
            page, "Longitude at the map's centre", self.values["meridian"], unit="°", width=10,
            help="0° puts the prime meridian in the middle, as on most world maps. It only "
            "changes longitude labels and where the date line falls.",
        )
        self._controls.append((meridian, "normal"))
        edges = self.edges_section = Collapsible(page, "Map edges · detected from the SVG")
        edges.pack(fill="x", pady=(2 * GAP, 0))
        hint(edges.body, "These edges become 180° W to 180° E and 90° N to 90° S. Change them "
             "only if the SVG has margins, a border or a legend around the map.")
        for key, label in (("x", "Left edge"), ("y", "Top edge"), ("width", "Width"),
                           ("height", "Height")):
            entry = field(edges.body, label, self.values[key], unit="SVG units", width=12)
            self._controls.append((entry, "normal"))
        self._button(edges.body, "Use the detected edges", self.reset_edges, style="Small").pack(
            anchor="w", pady=(GAP, 0)
        )
        coast = Collapsible(page, "Coast detail · advanced")
        coast.pack(fill="x", pady=(GAP // 2, 0))
        entry = field(
            coast.body, "Coast detail already drawn", self.values["coast"], unit="km",
            width=10,
            help="Leave blank for a hand-drawn map: zoomed maps add bays and headlands below "
            "the precision you drew. For a map exported with world refine-coast, enter the "
            "finest detail it already carries, so zoomed maps add only finer detail.",
        )
        self._controls.append((entry, "normal"))
        check = section(page, "World check")
        hint(check, textvariable=self.check, style="Body.TLabel")
        self.adjustment_box = ttk.Frame(check, style="Panel.TFrame")
        self.adjustment_tree = ttk.Treeview(self.adjustment_box, show="tree",
                                            selectmode="browse", height=4)
        self.adjustment_tree.pack(fill="x", pady=(GAP // 2, 0))
        self.adjustment_tree.bind("<<TreeviewSelect>>", self._review_adjustment)
        self.adjustment_detail = WrappingLabel(self.adjustment_box, style="Help.TLabel",
                                               text="Select an adjustment to highlight its "
                                               "shapes.")
        self.adjustment_detail.pack(fill="x", pady=(2, 0))
        self.check_button = self._button(check, "Check now", self.validate, style="Small")
        self.check_button.pack(anchor="w", pady=(GAP, 0))
        self._nav("planet", "source", ("Next: Geology →", self.next_from_planet))

    def _build_geology(self, page: ttk.Frame) -> None:
        page_title(
            page, "Geology (optional)",
            "Say where mountains, plateaus, rifts and basins should be. Skip this step and "
            "mountain ranges are placed automatically from the coastline.",
        )
        self.geology_empty = ttk.Frame(page, style="Panel.TFrame")
        self.geology_empty.pack(fill="x")
        hint(self.geology_empty,
             "A geology recipe gives each continent a default setting, such as an old stable "
             "interior or a young mountain belt, and lets you draw provinces that differ and "
             "place landmarks. It is saved as its own file, beside the world.",
             style="Muted.TLabel")
        self._button(self.geology_empty, "Create a geology recipe", self.start_geology,
                     style="Accent").pack(fill="x", pady=(2 * GAP, 0))
        self._button(self.geology_empty, "Open a recipe…", self.choose_geology).pack(
            fill="x", pady=(GAP, 0)
        )
        self.geology_holder = ttk.Frame(page, style="Panel.TFrame")
        self.geology_holder.pack(fill="x", pady=(GAP, 0))
        self.geology_remove = self._button(page, "Remove geology", self.stop_geology,
                                           style="Small")
        self._nav("geology", "planet", ("Next: Generate →", self.next_from_geology))

    def _build_context(self, page: ttk.Frame) -> None:
        page_title(
            page, "Geographic context",
            "Measure the drawn world on a latitude-longitude grid: land and water cover, "
            "connected seas, distance to the shore and exposure to open water.",
        )
        hint(page, "The planet does not need it. Use it to check how well a grid resolves "
             "your straits and islands, as a background in the Geology step, and for the "
             "Ocean floor and Local terrain tools.", style="Muted.TLabel")
        detail = section(page, "Grid")
        self.context_choice = ChoiceList(
            detail, self.context_rows, [(rows, label, text) for rows, label, text in
                                        CONTEXT_DETAIL],
        )
        self.context_choice.pack(fill="x")
        self._button(page, "Generate context", self.generate_context, style="Accent").pack(
            fill="x", pady=(2 * GAP, 0)
        )
        buttons = button_row(page)
        buttons.columnconfigure((0, 1), weight=1)
        self._button(buttons, "Export context…", self.export_context).grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        self._button(buttons, "Open context…", self.choose_context).grid(
            row=0, column=1, sticky="ew", padx=(3, 0)
        )
        result = section(page, "Result")
        details = ttk.Frame(result, style="Panel.TFrame")
        details.pack(fill="x")
        details.columnconfigure(0, weight=1)
        style = ttk.Style(self)
        self.context_text = tk.Text(
            details, height=16, width=1, wrap="word", state="disabled", borderwidth=0,
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

    def _build_ocean(self, page: ttk.Frame) -> None:
        page_title(
            page, "Ocean floor",
            "Design ocean depths by hand: continental shelves, slopes and deep basins for "
            "the seas you choose, saved as separate scenarios.",
        )
        hint(page, "The planet already makes its own sea floor; this is a hand-tuned "
             "alternative. It works on geographic context, which is generated first if "
             "there is none.", style="Muted.TLabel")
        self._button(page, "Open the ocean-floor editor…", self.edit_bathymetry,
                     style="Accent").pack(fill="x", pady=(2 * GAP, 0))
        hint(page, textvariable=self.ocean_detail)

    # Steps

    def show_step(self, key: str) -> None:
        """Open a step or tool page; the map beside it follows."""
        if key == "geology":
            self._geology_follows_world()
        self.step = key
        for name, page in self.pages.items():
            if name == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()
        self.rail.select(key)
        self._show_map()
        # Each step shows the map it works on, unless that map is already shown.
        group = self.map_view.group.get()
        if key in ("source", "planet") and group != SOURCE:
            self.map_view.set_layer(SOURCE)
        elif key == "context" and self.context_run is not None and group != CONTEXT:
            self.map_view.set_layer(self.map_view.layers_for(CONTEXT)[0])
        elif key in ("generate", "explore") and self.planet_run is not None and group != PLANET:
            self.map_view.set_layer(self.map_view.planet_layers()[0])

    def _show_map(self) -> None:
        geology = self.geology if self.step == "geology" else None
        if geology is not None:
            self.map_view.grid_remove()
            geology.map.grid(row=0, column=0, sticky="nsew")
        else:
            if self.geology is not None:
                self.geology.map.grid_remove()
            self.map_view.grid(row=0, column=0, sticky="nsew")

    def _refresh_steps(self) -> None:
        rail, source = self.rail, self.source
        if source is None:
            rail.set_status("source", "Import a map", done=False)
        else:
            unassigned = len(source.features) - len(self.assignments)
            rail.set_status(
                "source",
                f"{len(self.continents)} continent{'s' * (len(self.continents) != 1)}"
                + (f" · {unassigned} unassigned" if unassigned else ""),
                done=bool(self.continents) and not unassigned,
            )
        try:
            radius = f"{float(self.values['radius'].get()):,.0f} km radius"
        except ValueError:
            radius = "Enter a radius"
        rail.set_status("planet", radius, done=self.validated is not None)
        rail.set_status(
            "geology",
            "Optional · automatic" if self.geology is None else self.geology.summary(),
            done=self.geology is not None and not self.geology.dirty,
        )
        current = None if self.geology is None else self.geology.recipe
        geology_changed = self.planet_run is not None and current != self._planet_geology
        rail.set_status(
            "generate",
            self.planet_panel.summary() + (" · geology changed" if geology_changed else ""),
            done=self.planet_run is not None and not geology_changed,
        )
        self.result_panel.set_outdated(
            "The geology has changed since this planet was made. Generate again to apply it."
            if geology_changed else None
        )
        rail.set_status(
            "explore", "Planet ready" if self.planet_run else "Generate first",
            done=self.planet_run is not None,
        )
        rail.set_status("context", "Generated" if self.context_run else "")
        rail.set_status("ocean", "Editor open" if self.bathymetry_editor else "")
        rail.set_status("terrain", "Project prepared" if self.terrain_panel.created else "")
        for key in ("planet", "geology", "generate", "context", "ocean"):
            rail.set_enabled(key, source is not None)
        rail.set_enabled("terrain", bool(self.continents))
        rail.set_enabled("explore", self.planet_run is not None)
        summary = None if self.geology is None else self.geology.summary()
        self.planet_panel.set_geology(summary)
        self.terrain_panel.set_geology(summary)
        self._show_document()

    def _show_document(self) -> None:
        name = self.values["name"].get() if self.source else "No world open"
        where = self.path.name if self.path else ("not saved yet" if self.source else "")
        changed = " · unsaved changes" if self.source and self.dirty and self.path else ""
        self.document.set(" — ".join(p for p in (name, where) if p) + changed)

    def next_from_source(self) -> None:
        if self.source is None:
            return
        assigned = {a.feature_id for a in self.assignments}
        missing = tuple(f.id for f in self.source.features if f.id not in assigned)
        if missing:
            self._select_issues(missing)
            self.status.set(
                f"Assign or exclude the {len(missing)} selected shape"
                f"{'s' * (len(missing) != 1)} first; every shape needs a place."
            )
            return
        self.show_step("planet")

    def next_from_planet(self) -> None:
        self.validate(then=lambda: self.show_step("geology"))

    def next_from_geology(self) -> None:
        if self.geology is not None and self.geology.editing:
            self.status.set("Apply or revert the geology edit first.")
            return
        self.show_step("generate")

    def primary_action(self) -> None:
        """Ctrl+Enter: the main action of the open step."""
        actions: dict[str, Callable[[], None]] = {
            "source": self.next_from_source, "planet": self.next_from_planet,
            "geology": self.next_from_geology,
            "generate": self.planet_panel.request_generate, "context": self.generate_context,
        }
        if not self.busy and self.step in actions:
            actions[self.step]()

    def save_current(self, *, save_as: bool = False) -> None:
        """Ctrl+S: the geology recipe in its step, otherwise the world."""
        if self.step == "geology" and self.geology is not None:
            self.geology.save(save_as=save_as)
        else:
            self.save(save_as=save_as)

    def undo_current(self) -> None:
        if self.step == "geology" and self.geology is not None:
            self.geology.undo()
        else:
            self.undo()

    def redo_current(self) -> None:
        if self.step == "geology" and self.geology is not None:
            self.geology.redo()
        else:
            self.redo()

    # World inputs and the map

    def _changed(self, *_args: str) -> None:
        if self._loading:
            return
        self.validated = None
        self._clear_context()
        self._clear_planet()
        self._clear_check()
        if self.source:
            remaining = len(self.source.features) - len(self.assignments)
            excluded = sum(a.role == "exclude" for a in self.assignments)
            issues = sum(bool(f.issue) for f in self.source.features)
            self.summary.set(
                f"{len(self.continents)} continents · {remaining} unassigned · "
                f"{excluded} excluded · {issues} import issues"
            )
        self.on_change()
        self._update_map()
        self._refresh_steps()

    def _describe_scale(self, *_args: str) -> None:
        try:
            radius = float(self.values["radius"].get())
            width = float(self.values["width"].get())
            height = float(self.values["height"].get())
            if radius <= 0 or width <= 0 or height <= 0:
                raise ValueError
        except ValueError:
            self.scale_text.set(f"Enter the radius in kilometres; Earth's is "
                                f"{EARTH_RADIUS_KM:,.0f} km.")
            return
        around = 2 * pi * radius
        across, down = around / width, pi * radius / height
        text = (f"The equator is {around:,.0f} km around, so one SVG unit is "
                f"{across:,.1f} km east-west at the equator")
        if abs(across / down - 1) > 0.01:
            text += (f" but {down:,.1f} km north-south: the map edges are not twice as wide "
                     "as tall, so the drawing is stretched.")
        else:
            text += " and north-south."
        self.scale_text.set(text)

    def reset_edges(self) -> None:
        if self.source is None:
            return
        x0, y0, x1, y1 = self.source.suggested_bounds
        for key, value in (("x", x0), ("y", y0), ("width", x1 - x0), ("height", y1 - y0)):
            self.values[key].set(str(value))

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
                "Check the Planet step: the radius, the longitude at the map's centre and the "
                f"map edges must be numbers, with a positive radius. {error}"
            ) from error

    def project(self) -> WorldProject:
        if self.source is None:
            raise ValueError("Import or open a world map first.")
        coast = self.values["coast"].get().strip()
        try:
            coast_detail_km = float(coast) if coast else None
        except ValueError as error:
            raise ValueError(
                "Enter the coast detail already drawn as a number of km, or leave it blank."
            ) from error
        return WorldProject(
            self.values["name"].get().strip(),
            self.source,
            self._frame(),
            self.continents,
            self.assignments,
            coast_detail_km,
        )

    def _bounds(self) -> tuple[float, float, float, float]:
        try:
            return self._frame().bounds
        except ValueError:
            return self.source.suggested_bounds if self.source else (0.0, 0.0, 360.0, 180.0)

    def fit(self) -> None:
        if self.step == "geology" and self.geology is not None:
            self.geology.fit()
        else:
            self.map_view.fit()

    def escape(self) -> None:
        self.map_view.escape()

    # Jobs

    def _set_busy(self, busy: bool) -> None:
        for control, normal in self._controls:
            control["state"] = "disabled" if busy else normal
        self.role_input.set_enabled("Mainland", not busy)
        self.role_input.set_enabled("Island", not busy)
        self.context_choice.set_enabled(not busy)
        self.terrain_panel.set_busy(busy)
        self.planet_panel.set_busy(busy)
        self.result_panel.set_busy(busy)
        self.map_view.set_busy(busy)
        if self.geology is not None:
            self.geology.set_busy(busy)

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
            self.show_step("source")
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
        if self.geology is not None:
            self.geology.set_context(None)
        self.context_detail.set(
            "Inputs changed. Generate context again."
            if had_context
            else "Not generated yet. Land and water areas are measured on the planet's "
            "sphere. Small features stay in the source even when a cell cannot resolve them."
        )

    def _context_settings_changed(self, *_args: str) -> None:
        if self.context_run is not None and self.context_rows.get() == str(
            self.context_run.context.grid.settings.latitude_cells
        ):
            return
        self._clear_context()
        self._refresh_steps()

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
        if self.geology is not None:
            self.geology.set_context(run)
        self.show_step("context")
        self.map_view.set_layer("Land coverage")
        self._refresh_steps()

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

    def generate_context(self, then: Callable[[], None] | None = None) -> None:
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
            if then is not None:
                then()

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
            self.result_panel.clear("Inputs changed. Generate the planet again.")
            self.map_view.set_planet(None, None)
            if self.step == "explore":
                self.show_step("generate")

    def generate_planet(self, settings: PlanetSettings) -> None:
        if self.busy:
            return
        try:
            project = self.project()
            geology = self._geology_recipe(project)
        except ValueError as error:
            messagebox.showerror("The planet needs a valid world", str(error), parent=self)
            return
        signature = self._signature()
        # The step's recipe as used, to tell when later geology edits make the planet old.
        used = None if self.geology is None else self.geology.recipe

        def work(report: Report, token: CancellationToken) -> tuple[PlanetRun, PlanetProbe]:
            run = generate_planet_run(project, geology, settings, report, cancellation=token)
            report(None, "Preparing the map readout")
            return run, PlanetProbe(run.result)

        def done(ready: tuple[PlanetRun, PlanetProbe]) -> None:
            if signature != self._signature():
                self.status.set("World inputs changed; generate the planet again.")
                return
            run, probe = ready
            self.planet_run = run
            self._planet_geology = used
            self.result_panel.show(run)
            self.map_view.set_planet(run, probe)
            self.show_step("explore")
            self._refresh_steps()
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

    def pick_region(self) -> None:
        """Start picking a place on the map to zoom into."""
        self.map_view.start_picking()

    def save_map_image(self) -> None:
        self.map_view.choose_save_image()

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

    # Local terrain

    def _open_prepared_terrain(self, created: WorldTerrainCreated) -> None:
        if self.on_terrain_ready is not None:
            self.on_terrain_ready(created)

    def create_terrain(self, continent_id: str, output: Path) -> None:
        if self.busy:
            return
        try:
            project = self.project()
            geology = self._geology_recipe(project)
        except ValueError as error:
            messagebox.showerror("Terrain needs a valid world", str(error), parent=self)
            return
        signature = self._signature()
        context = self.context_run

        def done(created: WorldTerrainCreated) -> None:
            self.terrain_panel.show_created(created)
            self.show_step("terrain")
            self._refresh_steps()
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
                geology=geology, context=context,
            ),
            done,
        )

    # Geology

    def _geology_recipe(self, project: WorldProject) -> WorldGeologyRecipe | None:
        """The Geology step's recipe for ``project``; it follows world edits."""
        editor = self.geology
        if editor is None:
            return None
        if editor.editing:
            raise ValueError(
                "The Geology step has an edit that is not applied. Apply or revert it first."
            )
        return editor.recipe if editor.recipe.world == project else follow_world(
            editor.recipe, project
        )

    def _with_validated(self, then: Callable[[WorldMap], None]) -> None:
        """Run ``then`` with the prepared current world, checking it first if needed."""
        try:
            project = self.project()
        except ValueError as error:
            self.status.set(str(error))
            return
        if self.validated is not None and self.validated.project == project:
            then(self.validated)
            return
        self.validate(then=lambda: then(self.validated) if self.validated else None)

    def _geology_follows_world(self) -> None:
        editor = self.geology
        if editor is None or self.busy:
            return
        try:
            project = self.project()
        except ValueError as error:
            self.status.set(str(error))
            return
        if editor.world.project != project:
            self._with_validated(editor.follow)

    def start_geology(self, path: Path | None = None) -> None:
        """Begin a recipe for the current world (blank, or opened from ``path``)."""
        if self.busy or self.source is None or self.geology is not None:
            return

        def create(world: WorldMap) -> None:
            if not world.continents:
                self.status.set("Assign shapes to continents before adding geology.")
                return
            editor = GeologyEditor(
                self.geology_holder, self.map_area, world, self.context_run, jobs=self.jobs,
                status=self.status, on_change=self._refresh_steps,
            )
            editor.pack(fill="x")
            self.geology = editor
            self.geology_empty.pack_forget()
            self.geology_remove.pack(anchor="w", pady=(2 * GAP, 0), after=self.geology_holder)
            self.show_step("geology")
            if path is None:
                editor.start()
            else:
                editor.load(path)
            self._refresh_steps()

        self._with_validated(create)

    def choose_geology(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self, title="Open a geology recipe",
            filetypes=[("Geology recipe", "*.dmgeology.json")],
        )
        if selected:
            self.start_geology(Path(selected))

    def stop_geology(self) -> None:
        """Generate without geology from now on (asks to save unsaved recipe edits)."""
        editor = self.geology
        if editor is None or self.busy:
            return
        editor.guard(self._close_geology)

    def _close_geology(self) -> None:
        if self.geology is None:
            return
        self.geology.close()
        self.geology = None
        self.geology_remove.pack_forget()
        self.geology_empty.pack(fill="x", before=self.geology_holder)
        self._show_map()
        self._refresh_steps()
        self.status.set("Geology removed: mountain ranges will be placed automatically.")

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
        if self.geology is not None and self.geology.world.project.source.sha256 != source.sha256:
            self._close_geology()  # geology is drawn on one source map
        self._loading = True
        self.source, self.path, self.validated = source, None, None
        self.continents, self.assignments = (), ()
        self._undo.clear()
        self._redo.clear()
        self._saved_signature = None
        x0, y0, x1, y1 = source.suggested_bounds
        drawn = drawn_coast_detail_km(source.svg)
        for key, value in (
            ("name", Path(source.name).stem),
            ("radius", f"{EARTH_RADIUS_KM:g}"),
            ("meridian", "0"),
            ("x", str(x0)),
            ("y", str(y0)),
            ("width", str(x1 - x0)),
            ("height", str(y1 - y0)),
            ("coast", "" if drawn is None else f"{drawn:g}"),
        ):
            self.values[key].set(value)
        self._loading = False
        self.map_view.flat.viewport.fit()
        self.source_empty.pack_forget()
        self.source_loaded.pack(fill="x")
        self.source_label.set(f"{source.name} · {len(source.features)} shapes")
        self._populate()
        self._changed()
        if "stretched" in self.scale_text.get() and not self.edges_section.expanded:
            self.edges_section.toggle()  # the detected edges need a look
        self.show_step("source")
        issues = tuple(f.id for f in source.features if f.issue)
        self._select_issues(issues)
        self.status.set(
            f"Imported {source.name}: {len(source.features)} shapes. "
            + (
                f"{len(issues)} shapes need attention and are selected; review their details."
                if issues
                else "Assign continents (or suggest them from SVG groups), then go to Planet."
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
            ("radius", f"{frame.radius_km:g}"),
            ("meridian", f"{frame.central_meridian_deg:g}"),
            ("x", str(frame.bounds[0])),
            ("y", str(frame.bounds[1])),
            ("width", str(frame.width)),
            ("height", str(frame.height)),
            ("coast", "" if (km := world.project.coast_detail_km) is None else f"{km:g}"),
        ):
            self.values[key].set(value)
        self._loading = False
        self.path, self.validated = path, world
        self._saved_signature = self._signature()
        self._populate()
        self._changed()
        self.validated = world
        self._show_summary(world)
        self._refresh_steps()
        self.status.set(
            f"Opened {path.name if path else world.project.name}. Source and ownership verified; "
            f"{len(world.adjustments)} import adjustments. Generate a planet, or revisit any "
            "step."
        )
        self.on_change()
        self._update_map()
        self.show_step("generate")  # a saved world is ready for its planet

    def validate(self, then: Callable[[], None] | None = None) -> None:
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
            self._refresh_steps()
            self.status.set(
                f"World checked: {len(world.continents)} continents, "
                f"{world.land_fraction:.1%} land. Save it to keep this geography and its "
                "continents."
            )
            if then is not None:
                then()

        self._run(
            "Checking map edges, seams, continents and overlaps",
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
                title="Save world",
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
                f"Saved {target.name}. The original SVG is embedded. "
                f"{len(world.adjustments)} import adjustments recorded."
            )
            self._refresh_steps()
            self.on_change()
            callback, self._after_save = self._after_save, None
            if callback:
                callback()

        self._run(
            "Checking and saving the world",
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
        if self.busy:
            self.status.set("Wait for the world operation to finish before continuing.")
            return
        if self.geology is not None and self.geology.dirty:
            self.geology.guard(lambda: self._guard_world(action))
            return
        self._guard_world(action)

    def _guard_world(self, action: Callable[[], None]) -> None:
        if self.busy:
            return
        if not self.dirty:
            action()
            return
        answer = messagebox.askyesnocancel(
            "Save world changes?", "Save this world before continuing?", parent=self
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
                + (f" · group {' / '.join(feature.groups)}" if feature.groups else "")
                + (f"\n{feature.issue}" if feature.issue else "")
            )
            assignment = next((a for a in self.assignments if a.feature_id == selection[0]), None)
            if assignment and assignment.role != "exclude":
                self.role.set(assignment.role.title())
                if assignment.continent_id:
                    self.owner.set(
                        next(c.name for c in self.continents if c.id == assignment.continent_id)
                    )
        else:
            self.detail.configure(text="")
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
                if self.step != "source":
                    self.show_step("source")
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
                "Continents suggested from SVG groups. Review them and any shapes left "
                "unassigned; Undo restores the previous assignments."
            )

    def assign_selected(self) -> None:
        selected = self.tree.selection()
        if self.busy or not selected:
            self.status.set("Select one or more shapes first, in the list or on the map.")
            return
        try:
            role = ROLES[self.role.get()]
            continents = {c.id: c for c in self.continents}
            owner: str | None = None
            if role != "exclude":
                name = self.owner.get().strip()
                if not name:
                    raise ValueError("Choose a continent, or type a name for a new one.")
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

    def exclude_selected(self) -> None:
        role = self.role.get()
        self.role.set("Exclude")
        try:
            self.assign_selected()
        finally:
            self.role.set(role)

    def rename_continent(self) -> None:
        from tkinter import simpledialog

        if self.busy:
            return
        current = next((c for c in self.continents if c.name == self.owner.get()), None)
        if current is None:
            self.status.set("Choose the continent to rename in the Continent box first.")
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

    # Ocean floor

    def edit_bathymetry(self) -> None:
        if self.busy:
            return
        if self.bathymetry_editor is not None:
            self.bathymetry_editor.lift()
            return
        if self.context_run is None:
            self.ocean_detail.set("Generating geographic context first…")
            self.generate_context(then=self._open_bathymetry)
            return
        self._open_bathymetry()

    def _open_bathymetry(self) -> None:
        run = self.context_run
        if run is None:
            return
        if not run.context.water_bodies:
            self.ocean_detail.set("This world has no water at the context's grid detail.")
            self.show_step("ocean")
            return
        saved = self._bathymetry_file
        if saved and world_fingerprint(saved.inputs.world) != world_fingerprint(self.project()):
            saved = None

        def closed(file: BathymetryFile | None) -> None:
            self._bathymetry_file = file
            self.bathymetry_editor = None

        self.bathymetry_editor = BathymetryEditor(self, run, on_close=closed, saved=saved)
        self.show_step("ocean")
        self.ocean_detail.set("The ocean-floor editor is open in its own window.")
        self.status.set(
            "Ocean-floor inputs open; depths are generated from explicit hypotheses."
        )

    # World check

    def _clear_check(self) -> None:
        self.adjustment_tree.delete(*self.adjustment_tree.get_children())
        self.adjustment_box.pack_forget()
        self.check.set(
            "Not checked yet. Next checks the map edges, seams, continents and overlaps."
            if self.source else "Import a map first."
        )

    def _show_summary(self, world: WorldMap) -> None:
        self.adjustment_tree.delete(*self.adjustment_tree.get_children())
        titles = {
            "edge_clip": "Rounded world edge",
            "shared_land": "Shared land within one continent",
            "border_overlap": "Narrow continent-border overlap",
        }
        for index, adjustment in enumerate(world.adjustments):
            self.adjustment_tree.insert("", "end", iid=str(index), text=titles[adjustment.kind])
        if world.adjustments:
            self.adjustment_box.pack(fill="x", before=self.check_button)
        else:
            self.adjustment_box.pack_forget()
        names = "\n".join(f"{c.name}: {c.area_km2:,.0f} km²" for c in world.continents)
        self.check.set(
            f"✓ The world is valid. {len(world.continents)} continents cover "
            f"{world.land_fraction:.1%} of the planet:\n{names}\n"
            + (f"{len(world.adjustments)} import adjustments (small fixes the import "
               "made; your SVG is unchanged):" if world.adjustments
               else "No import adjustments were needed.")
        )

    def _review_adjustment(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self.adjustment_tree.selection()
        if self.busy or self.validated is None or not selected:
            return
        adjustment = self.validated.adjustments[int(selected[0])]
        self.adjustment_detail.configure(
            text=(
                adjustment.message + f"\n\nShared/trimmed area: "
                f"{adjustment.area_source_units2:.6g} square SVG units. "
                "Your SVG and assignments are unchanged."
            )
        )
        self._select_issues(adjustment.feature_ids)

    def close(self) -> None:
        self._closed = True
        if self.geology is not None:
            self.geology.close()
            self.geology = None
        if self.bathymetry_editor is not None:
            self.bathymetry_editor.close()
        self.jobs.close()
        self.renders.cancel()
        self.pump.close()
