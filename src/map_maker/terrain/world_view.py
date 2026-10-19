# pyright: reportUnknownMemberType=false
"""The World workspace's map: source, context and planet maps in one view.

Planet maps come from the theme registry (``map_views.THEMES``) and show in any
projection (``map_projection.PROJECTIONS``); neither list needs code here. A planet
map not drawn yet is drawn in the background when it is first shown.
Regional detail opens in the same view as a deeper level, with a breadcrumb back
to the world. The view only presents results; the workspace owns the data and
the jobs that make it.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from math import asin, atan2, cos, degrees, pi, radians, sin
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Literal, cast
from uuid import uuid4

from PIL import Image

from map_maker.terrain.adapters.globe_spin import SPIN_FRAMES, write_spin
from map_maker.terrain.adapters.map_projection import (
    PROJECTION_LABELS,
    PROJECTIONS,
    Drape,
    drapes_in_full,
    view_radius,
)
from map_maker.terrain.adapters.map_views import (
    PREVIEW_LAYERS,
    THEME_BY_ID,
    THEME_BY_LABEL,
    THEMES,
    MapTheme,
)
from map_maker.terrain.adapters.world_context_render import (
    CONTEXT_LAYERS,
    ContextLayer,
    render_world_context,
)
from map_maker.terrain.adapters.world_render import OCEAN, render_world_source
from map_maker.terrain.application.planet import PlanetRun
from map_maker.terrain.application.planet_region import RegionRun
from map_maker.terrain.application.planet_views import save_globe
from map_maker.terrain.application.region_views import region_themes, render_region_theme
from map_maker.terrain.application.world_context import WorldContextRun
from map_maker.terrain.domain.planet import REGION_LEVEL_MAX_RADIUS_KM, REGION_LEVEL_NAMES
from map_maker.terrain.domain.world import WorldAssignment, WorldFrame, WorldSource
from map_maker.terrain.domain.world_context import EXPOSURE_BEARINGS
from map_maker.terrain.map_canvas import (
    FlatMapCanvas,
    GlobeCanvas,
    ImagePyramid,
    MapImages,
    Rect,
)
from map_maker.terrain.map_probes import (
    PlanetProbe,
    context_readout,
    lonlat_text,
    region_readout,
    window_lonlat,
    window_position,
)
from map_maker.terrain.pipeline.control import CancellationToken
from map_maker.terrain.ui_components import MapInfoStrip, SegmentedChoice
from map_maker.terrain.ui_jobs import JobRunner, LatestWorker, Report
from map_maker.terrain.ui_style import (
    FONT_MAP_LABEL,
    GAP,
    MAP_BACKGROUND,
    MAP_FRAME,
    MAP_GRID,
    MAP_HIGHLIGHT,
    MAP_TEXT,
)
from map_maker.terrain.viewport import MapViewport

SOURCE, CONTEXT, PLANET = "Source", "Context", "Planet"
EXPOSURE_LAYERS = ("Water exposure", "Exposure support")
FLAT = "equirectangular"
GRATICULE_STEP_DEG = 30
AUTO_RADIUS = "Auto"
# Radius choices when zooming from each level: the world, then region and province.
REGION_RADII_KM = ((150, 300, 600, 1200), (30, 75, 150, 300), (6, 15, 30, 60))
SAVE_PIXELS = 2048
SPIN_PIXELS = 720  # a spinning globe's frames are this many pixels square
START = (
    "Start with your world",
    "Import an SVG or open a saved world.\n"
    "Continents, islands and the world frame stay connected.",
)
DRAWING = "Drawing this map…"

SOURCE_LEGEND = (
    "Your drawn map. Each continent has its own colour; grey shapes are not assigned yet "
    "and dark ones are excluded. Selected shapes have a gold outline."
)
CONTEXT_LEGENDS: dict[str, str] = {
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
    "Water exposure": "Tan = 0% water; blue = 100%. Choose the look direction "
    "beside the layer. Nearer water has more weight. This is not rainfall. "
    "Outlines show source geography.",
    "Exposure support": "Dark = 0%; gold = 100% of exposure weight falls in mixed "
    "coastal cells. This flags unresolved geography; it is not an error bound.",
}
HINTS = {
    "source": "Click a shape to select it (Ctrl adds) · drag to pan · wheel to zoom · F fits",
    "flat": "Drag to pan · wheel to zoom · F fits the map",
    "globe": "Drag or flick to turn the globe · wheel or +/- to zoom · arrows turn · "
             "F shows all of it",
    "polar": "Drag or flick to turn · wheel or +/- to zoom · F shows out to the equator",
    "pick": "Click the map to build {name} detail there · Esc cancels",
    "region": "Drag to pan · wheel to zoom · the path above returns to larger maps",
}


@dataclass(frozen=True, slots=True)
class SourceScene:
    """What the Source map draws, as the workspace currently has it."""

    source: WorldSource
    bounds: tuple[float, float, float, float]
    assignments: tuple[WorldAssignment, ...]
    selection: frozenset[str]
    frame: WorldFrame | None  # None while the World frame inputs are incomplete
    central_meridian_deg: float


@dataclass(slots=True)
class RegionLevel:
    """One regional detail window below the world map, with its rendered themes."""

    run: RegionRun
    themes: tuple[MapTheme, ...]
    theme_id: str
    images: dict[str, ImagePyramid] = field(default_factory=dict[str, ImagePyramid])
    viewport: MapViewport = field(default_factory=MapViewport)

    @property
    def title(self) -> str:
        """Short breadcrumb name: level and centre (the scale bar shows the size)."""
        lon, lat = self.run.window.centre
        name = REGION_LEVEL_NAMES[self.run.level - 1].title()
        return (f"{name} {abs(lat):.1f}°{'N' if lat >= 0 else 'S'} "
                f"{abs(lon):.1f}°{'E' if lon >= 0 else 'W'}")


def map_label(
    canvas: tk.Canvas, x: float, y: float, text: str, *, anchor: Literal["nw", "w"] = "nw"
) -> None:
    """Text over a map, on a dark backdrop so it reads on light and dark maps."""
    item = canvas.create_text(x, y, anchor=anchor, text=text, fill=MAP_TEXT,
                              font=FONT_MAP_LABEL)
    box = canvas.bbox(item)
    if box:
        backdrop = canvas.create_rectangle(box[0] - 5, box[1] - 3, box[2] + 5, box[3] + 3,
                                           fill=MAP_BACKGROUND, outline="")
        canvas.tag_lower(backdrop, item)


class WorldMapView(ttk.Frame):
    """Map area: layer, theme and projection choice, legend, hover and drill-down."""

    def __init__(
        self,
        parent: tk.Misc,
        worker: LatestWorker,
        jobs: JobRunner,
        *,
        drawing: LatestWorker,
        pick_shape: Callable[[tuple[float, float], bool], None],
        request_region: Callable[[float, float, float, int], None],
        export_region: Callable[[RegionRun, Path], None],
        status: Callable[[str], None],
        show_excluded: tk.BooleanVar | None = None,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self._worker = worker
        self._jobs = jobs
        self._pick_shape = pick_shape
        self._request_region = request_region
        self._export_region = export_region
        self._status = status
        self.scene: SourceScene | None = None
        self.context_run: WorldContextRun | None = None
        self.planet_run: PlanetRun | None = None
        self.probe: PlanetProbe | None = None
        # Planet maps, drawn on ``drawing`` so frames on ``worker`` never wait for them.
        self.planet_maps = MapImages(drawing, self._map_drawn)
        self.levels: list[RegionLevel] = []
        self.level = 0  # 0 is the world; n shows levels[n - 1]
        self._world_viewport = MapViewport()
        self._remembered = {SOURCE: SOURCE, CONTEXT: CONTEXT_LAYERS[0], PLANET: ""}
        self._pick_at: tuple[float, float] | None = None
        self._busy = False
        self._world_layer = SOURCE
        self.display_layer = tk.StringVar(self, value=SOURCE)
        self.group = tk.StringVar(self, value=SOURCE)
        self.projection = tk.StringVar(self, value=FLAT)
        self.projection_label = tk.StringVar(self, value=PROJECTION_LABELS[FLAT])
        self.graticule = tk.BooleanVar(self, value=True)
        # Whether excluded source shapes are drawn; the workspace offers the choice.
        self.show_excluded = show_excluded or tk.BooleanVar(self, value=True)
        self.exposure_bearing = tk.StringVar(self, value=EXPOSURE_BEARINGS[0])
        self.picking = tk.BooleanVar(self, value=False)
        self.region_radius = tk.StringVar(self, value=AUTO_RADIUS)
        self.legend = tk.StringVar(self, value=SOURCE_LEGEND)
        self.inspection = tk.StringVar(self, value=HINTS["flat"])
        self._build()
        self._sync_controls()

    # Layout

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        navigation = ttk.Frame(self, style="Toolbar.TFrame", padding=(GAP, GAP, GAP, 0))
        navigation.grid(row=0, column=0, sticky="ew")
        self.crumbs = ttk.Frame(navigation, style="Toolbar.TFrame")
        self.crumbs.pack(side="left")
        tools = ttk.Frame(navigation, style="Toolbar.TFrame")
        tools.pack(side="right")
        self.export_region_button = ttk.Button(
            tools, text="Export region…", style="Small.TButton", command=self.choose_region_export
        )
        self.save_button = ttk.Button(
            tools, text="Save image…", style="Small.TButton", command=self.choose_save_image
        )
        self.save_button.pack(side="right", padx=(GAP // 2, 0))
        self.radius_input = ttk.Combobox(
            tools, textvariable=self.region_radius, state="readonly",
            width=8,
        )
        self.radius_input.pack(side="right", padx=(GAP // 2, 0))
        self.pick_button = ttk.Checkbutton(
            tools, text="Zoom to region", variable=self.picking, style="Segment.TCheckbutton",
            command=self._picking_changed, takefocus=False,
        )
        self.pick_button.pack(side="right", padx=(GAP, 0))

        layers = ttk.Frame(self, style="Toolbar.TFrame", padding=GAP)
        layers.grid(row=1, column=0, sticky="ew")
        self.group_choice = SegmentedChoice(
            layers, self.group, [(g, g) for g in (SOURCE, CONTEXT, PLANET)], self._group_changed
        )
        self.group_choice.pack(side="left")
        self.layer_input = ttk.Combobox(
            layers, textvariable=self.display_layer, state="readonly", width=20
        )
        self.layer_input.pack(side="left", padx=(GAP, 0))
        self.layer_input.bind("<<ComboboxSelected>>", lambda _e: self.set_layer())
        self.bearing_input = ttk.Combobox(
            layers, textvariable=self.exposure_bearing, values=EXPOSURE_BEARINGS,
            state="readonly", width=4,
        )
        self.bearing_input.bind("<<ComboboxSelected>>", lambda _e: self.set_layer())
        ttk.Button(layers, text="Fit", style="Small.TButton", command=self.fit, width=4).pack(
            side="right", padx=(GAP, 0)
        )
        self.grid_toggle = ttk.Checkbutton(
            layers, text="Grid", variable=self.graticule, command=self.refresh
        )
        self.grid_toggle.pack(side="right", padx=(GAP, 0))
        self.projection_input = ttk.Combobox(
            layers, textvariable=self.projection_label, state="readonly", width=11,
            values=tuple(PROJECTION_LABELS[kind] for kind in PROJECTIONS),
        )
        self.projection_input.pack(side="right")
        self.projection_input.bind("<<ComboboxSelected>>", lambda _e: self._projection_chosen())
        self.projection.trace_add("write", self._projection_changed)
        self._layer_bar = layers

        stage = ttk.Frame(self, style="Panel.TFrame")
        stage.grid(row=2, column=0, sticky="nsew")
        stage.rowconfigure(0, weight=1)
        stage.columnconfigure(0, weight=1)
        self.flat = FlatMapCanvas(
            stage, background=OCEAN, on_click=self._click_flat, on_hover=self._hover_flat,
            on_view_changed=self._view_changed,
        )
        self.flat.placeholder = START
        self.flat.grid(row=0, column=0, sticky="nsew")
        self.globe = GlobeCanvas(
            stage, self._worker, on_click=self._click_globe,
            on_hover=self._hover_globe, on_view_changed=self._view_changed,
        )
        self.globe.placeholder = DRAWING
        self.globe.overlay = self._globe_overlay
        for canvas in (self.flat, self.globe):
            canvas.bind("<Escape>", lambda _e: self.escape())

        MapInfoStrip(self, self.legend, self.inspection).grid(row=3, column=0, sticky="ew")
        self._rebuild_crumbs()

    # Data from the workspace

    def show_source(self, scene: SourceScene | None) -> None:
        self.scene = scene
        if scene is None:
            self._drop_levels()
        self.refresh()

    def set_context(self, run: WorldContextRun | None) -> None:
        self.context_run = run
        if run is None and self.group.get() == CONTEXT:
            self.display_layer.set(SOURCE)
        self.set_layer()

    def set_planet(self, run: PlanetRun | None, probe: PlanetProbe | None) -> None:
        self.planet_run, self.probe = run, probe
        self.planet_maps.show(None if run is None else run.maps)
        self._drop_levels()
        self.picking.set(False)
        if run is None:
            if self.group.get() == PLANET:
                self.display_layer.set(SOURCE)
        else:
            labels = self.planet_layers()
            self.display_layer.set(
                next((label for label in self.shown_planet_maps() if label in labels), SOURCE)
            )
        self.set_layer()

    def shown_planet_maps(self) -> tuple[str, ...]:
        """Planet maps by preference: a new planet shows the first one it has."""
        return (self._remembered[PLANET], *PREVIEW_LAYERS)

    def add_region(self, run: RegionRun, image: Image.Image, theme_id: str) -> None:
        """Show a new detail window at its level, below the maps it was picked from."""
        level = RegionLevel(run, region_themes(run.window), theme_id)
        level.images[theme_id] = ImagePyramid(image)
        shown = self.display_layer.get()  # keep the map the user was looking at
        if self.level:
            self.levels[self.level - 1].viewport = self.flat.viewport
        self.levels = [*self.levels[: run.level - 1], level]
        self.picking.set(False)
        self.go_to_level(run.level)
        if shown != self.display_layer.get() and shown in self.layers_for(PLANET):
            self.set_layer(shown)

    def _drop_levels(self) -> None:
        if self.level:
            self.flat.viewport = self._world_viewport
        self.levels.clear()
        self.level = 0
        self._rebuild_crumbs()

    # Layer choice

    def planet_layers(self) -> tuple[str, ...]:
        return self.planet_maps.labels

    def layers_for(self, group: str) -> tuple[str, ...]:
        if self.level:
            return tuple(t.label for t in self.levels[self.level - 1].themes)
        if group == CONTEXT:
            return CONTEXT_LAYERS if self.context_run is not None else ()
        if group == PLANET:
            return self.planet_layers()
        return (SOURCE,)

    def group_of(self, layer: str) -> str:
        if layer in CONTEXT_LAYERS:
            return CONTEXT
        if layer in THEME_BY_LABEL:
            return PLANET
        return SOURCE

    def set_layer(self, layer: str | None = None) -> None:
        """Show ``layer`` (or the selector's current value) if it is available."""
        if layer is not None:
            self.display_layer.set(layer)
        layer = self.display_layer.get()
        if self.level:
            current = self.levels[self.level - 1]
            if layer not in self.layers_for(PLANET):
                self.display_layer.set(THEME_BY_ID[current.theme_id].label)
            else:
                self._show_region_theme(current, THEME_BY_LABEL[layer].id)
                return
        else:
            group = self.group_of(layer)
            if layer not in self.layers_for(group):
                self.display_layer.set(SOURCE)
                if group == PLANET:
                    self._status(
                        "Generate the planet (with climate for the atlas, rainfall and "
                        "temperature maps) before choosing its maps."
                    )
                elif group == CONTEXT:
                    self._status("Generate context in the Context stage before choosing it.")
            self.group.set(self.group_of(self.display_layer.get()))
            self._remembered[self.group.get()] = self.display_layer.get()
        self._sync_controls()
        self.refresh()

    def _group_changed(self) -> None:
        group = self.group.get()
        layers = self.layers_for(group)
        remembered = self._remembered.get(group, "")
        self.set_layer(remembered if remembered in layers else (layers[0] if layers else SOURCE))

    # Levels

    def go_to_level(self, index: int) -> None:
        if not 0 <= index <= len(self.levels):
            return
        if self.level == 0:
            self._world_viewport = self.flat.viewport
            self._world_layer = self.display_layer.get()
        elif self.level <= len(self.levels):
            self.levels[self.level - 1].viewport = self.flat.viewport
        self.level = index
        if index == 0:
            self.flat.viewport = self._world_viewport
            self.set_layer(self._world_layer)
        else:
            level = self.levels[index - 1]
            self.flat.viewport = level.viewport
            self.group.set(PLANET)
            self.display_layer.set(THEME_BY_ID[level.theme_id].label)
            self._sync_controls()
            self.refresh()
        self._rebuild_crumbs()

    def _rebuild_crumbs(self) -> None:
        for child in self.crumbs.winfo_children():
            child.destroy()
        names = ["World", *(level.title for level in self.levels)]
        for index, name in enumerate(names):
            if index:
                ttk.Label(self.crumbs, text="/", style="Muted.TLabel").pack(side="left")
            ttk.Button(
                self.crumbs, text=name, style="Crumb.TButton",
                command=lambda index=index: self.go_to_level(index),
                state="disabled" if index == self.level else "normal",
            ).pack(side="left")

    def _show_region_theme(self, level: RegionLevel, theme_id: str) -> None:
        if theme_id in level.images:
            level.theme_id = theme_id
            self._sync_controls()
            self.refresh()
            return
        self.legend.set(f"Rendering {THEME_BY_ID[theme_id].label}…")
        window = level.run.window

        def shown(image: Image.Image) -> None:
            level.images[theme_id] = ImagePyramid(image)
            if self.level and self.levels[self.level - 1] is level:
                if THEME_BY_LABEL.get(self.display_layer.get()) is THEME_BY_ID[theme_id]:
                    level.theme_id = theme_id
                self._sync_controls()
                self.refresh()

        self._worker.submit(lambda: render_region_theme(window, theme_id), shown)

    # Controls

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._sync_controls()

    def _uses_globe(self) -> bool:
        return self.level == 0 and self.group.get() == PLANET and self.projection.get() != FLAT

    def _sync_controls(self) -> None:
        busy = self._busy
        world = self.level == 0
        for group in (SOURCE, CONTEXT, PLANET):
            self.group_choice.set_enabled(
                group, world and self.scene is not None and bool(self.layers_for(group))
            )
        layers = self.layers_for(self.group.get())
        self.layer_input.configure(values=layers, state="readonly" if layers else "disabled")
        planet_world = world and self.group.get() == PLANET
        self.projection_input.configure(state="readonly" if planet_world else "disabled")
        if world:
            self.grid_toggle.pack(side="right", padx=(GAP, 0))
            self.projection_input.pack(side="right")
        else:
            self.projection_input.pack_forget()
            self.grid_toggle.pack_forget()
        layer = self.display_layer.get()
        if world and layer in EXPOSURE_LAYERS and self.context_run is not None:
            self.bearing_input.pack(side="left", padx=(GAP, 0))
        else:
            self.bearing_input.pack_forget()
        deepest = self.level >= len(REGION_LEVEL_NAMES)
        can_pick = self.planet_run is not None and not busy and not deepest
        if not can_pick and self.picking.get():
            self.picking.set(False)
        target = REGION_LEVEL_NAMES[min(self.level, len(REGION_LEVEL_NAMES) - 1)]
        self.pick_button.configure(
            state="normal" if can_pick else "disabled", text=f"Zoom to {target}"
        )
        choices = (AUTO_RADIUS, *(f"{r:,} km" for r in REGION_RADII_KM[min(self.level, 2)]))
        if self.region_radius.get() not in choices:
            self.region_radius.set(AUTO_RADIUS)
        self.radius_input.configure(
            values=choices, state="readonly" if can_pick else "disabled"
        )
        self.save_button.configure(
            state="normal" if self.scene is not None and not busy else "disabled"
        )
        if self.level:
            self.export_region_button.pack(side="right", padx=(GAP // 2, 0))
            self.export_region_button.configure(state="disabled" if busy else "normal")
        else:
            self.export_region_button.pack_forget()
        self._update_legend()
        self.inspection.set(self._hint())

    def _hint(self) -> str:
        if self.picking.get():
            name = REGION_LEVEL_NAMES[min(self.level, len(REGION_LEVEL_NAMES) - 1)]
            return HINTS["pick"].format(name=name) + f" · radius {self.radius_km():,.0f} km"
        if self.level:
            return HINTS["region"]
        if self._uses_globe():
            return HINTS["globe" if self.projection.get() == "globe" else "polar"]
        return HINTS["source" if self.group.get() == SOURCE and self.scene else "flat"]

    def _update_legend(self) -> None:
        layer = self.display_layer.get()
        theme = THEME_BY_LABEL.get(layer)
        if theme is not None:
            text = theme.legend
            if self.level == 0 and self.planet_run is not None:
                missing = len(THEMES) - len(self.planet_maps.labels)
                if missing:
                    text += (f"\n{missing} more maps need climate (or volcanoes); turn on "
                             "Climate in the Planet stage and generate again.")
            self.legend.set(text)
        elif layer in CONTEXT_LEGENDS:
            self.legend.set(CONTEXT_LEGENDS[layer])
        else:
            self.legend.set(SOURCE_LEGEND)

    def _projection_chosen(self) -> None:
        kind = next(k for k in PROJECTIONS if PROJECTION_LABELS[k] == self.projection_label.get())
        if kind != self.projection.get():
            self.projection.set(kind)
            self.refresh()

    def _projection_changed(self, *_args: str) -> None:
        self.projection_label.set(PROJECTION_LABELS[self.projection.get()])

    def _picking_changed(self) -> None:
        self._pick_at = None
        cursor = "crosshair" if self.picking.get() else ""
        self.flat.configure(cursor=cursor)
        self.globe.configure(cursor=cursor)
        self.inspection.set(self._hint())
        self.flat.draw_overlay()
        self.globe.draw_overlay()

    def start_picking(self) -> None:
        """Wait for a click on the map to zoom into the next detail level there."""
        if str(self.pick_button["state"]) == "normal" and not self.picking.get():
            self.picking.set(True)
            self._picking_changed()
            (self.globe if self._uses_globe() else self.flat).focus_set()

    def escape(self) -> bool:
        """Leave region picking; returns True if there was something to cancel."""
        if self.picking.get():
            self.picking.set(False)
            self._picking_changed()
            return True
        return False

    def fit(self) -> None:
        if self._uses_globe():
            self.globe.fit()
        else:
            self.flat.fit()

    def radius_km(self) -> float:
        choice = self.region_radius.get()
        if choice != AUTO_RADIUS:
            return float(choice.removesuffix(" km").replace(",", ""))
        choices = REGION_RADII_KM[min(self.level, 2)]
        low = float(choices[0])
        high = min(float(choices[-1]), REGION_LEVEL_MAX_RADIUS_KM[min(self.level, 2)])
        zoom = self.globe.projection().zoom if self._uses_globe() else self.flat.viewport.zoom
        # About half the visible width of the map.
        if self.level:
            half = self.levels[self.level - 1].run.window.radius_m / 1000 / zoom
        else:
            scene = self.scene
            radius = scene.frame.radius_km if scene and scene.frame else 6371.0
            half = pi * radius / 2 / zoom
        return min(high, max(low, half))

    # Drawing

    @property
    def photo(self) -> object:
        """The image currently on screen (for tests and checks)."""
        return self.globe.photo if self._uses_globe() else self.flat.photo

    def refresh(self) -> None:
        if self._uses_globe():
            self.flat.grid_remove()
            self.globe.grid(row=0, column=0, sticky="nsew")
            run = self.planet_run
            assert run is not None
            self.globe.graticule = self.graticule.get()
            self.globe.set_kind(self.projection.get())
            self.globe.show(
                self.planet_maps.image(self.display_layer.get()),
                run.result.world.project.frame.central_meridian_deg,
                self._drapes(self.display_layer.get()),
            )
        else:
            self.globe.grid_remove()
            self.globe.show(None, 0.0)
            self.flat.grid(row=0, column=0, sticky="nsew")
            renderer, size = self._flat_content()
            self.flat.placeholder = START if self.scene is None else (
                self.display_layer.get(), DRAWING
            )
            self.flat.overlay = self._overlay
            self.flat.show(renderer, size)
        self.inspection.set(self._hint())

    def draw_now(self) -> None:
        if not self._uses_globe():
            self.flat.draw_now()

    def _drape_image(self, level: RegionLevel, layer: str) -> Image.Image | None:
        """The level's image of the map ``layer``, if drawn: it lies over the globe."""
        theme = THEME_BY_LABEL.get(layer)
        pyramid = None if theme is None else level.images.get(theme.id)
        return None if pyramid is None else pyramid.image

    def _drapes(self, layer: str) -> tuple[Drape, ...]:
        """Opened regions drawn in the map ``layer``, to show on the globe, deepest last."""
        return tuple(
            Drape(image, level.run.window.centre,
                  level.run.window.radius_m / level.run.window.planet_m)
            for level in self.levels
            if (image := self._drape_image(level, layer)) is not None
        )

    def _flat_content(
        self,
    ) -> tuple[Callable[[MapViewport, tuple[int, int]], Image.Image] | None, tuple[float, float]]:
        if self.level:
            level = self.levels[self.level - 1]
            return level.images[level.theme_id].renderer((1.0, 1.0), MAP_BACKGROUND), (1.0, 1.0)
        scene = self.scene
        if scene is None:
            return None, (2.0, 1.0)
        x0, y0, x1, y1 = scene.bounds
        size = (x1 - x0, y1 - y0)
        layer = self.display_layer.get()
        if self.group.get() == PLANET and layer in self.planet_maps.labels:
            pyramid = self.planet_maps.pyramid(layer)
            return None if pyramid is None else pyramid.renderer(size, OCEAN), size
        context = self.context_run
        if self.group.get() == CONTEXT and context is not None:
            bearing = EXPOSURE_BEARINGS.index(self.exposure_bearing.get())
            return self._guarded(
                lambda viewport, canvas: render_world_context(
                    context.context, viewport, canvas, cast(ContextLayer, layer), bearing
                )
            ), size
        show_excluded = self.show_excluded.get()
        return self._guarded(
            lambda viewport, canvas: render_world_source(
                scene.source, scene.bounds, scene.assignments, viewport, canvas,
                scene.selection, show_excluded=show_excluded,
            )
        ), size

    def _guarded(
        self, render: Callable[[MapViewport, tuple[int, int]], Image.Image]
    ) -> Callable[[MapViewport, tuple[int, int]], Image.Image]:
        def safe(viewport: MapViewport, size: tuple[int, int]) -> Image.Image:
            try:
                return render(viewport, size)
            except ValueError as error:
                self._status(str(error))
                return Image.new("RGB", size, OCEAN)

        return safe

    def _map_drawn(self, label: str) -> None:
        if self.level == 0 and self.display_layer.get() == label:
            self.refresh()

    def _overlay(self, canvas: FlatMapCanvas, rect: Rect) -> None:
        left, top, right, bottom = rect
        scene = self.scene
        if self.level == 0 and scene is not None:
            if self.graticule.get():
                self._draw_graticule(canvas, rect, scene.central_meridian_deg)
            if scene.frame is not None:
                for level in self.levels:
                    lon, lat = level.run.window.centre
                    self._draw_circle(canvas, scene, lon, lat, level.run.window.radius_m / 1000,
                                      MAP_TEXT, width=2)
                if self.picking.get() and self._pick_at is not None:
                    self._draw_circle(canvas, scene, *self._pick_at, self.radius_km(),
                                      MAP_HIGHLIGHT, width=2)
        if self.level:
            current = self.levels[self.level - 1]
            for child in self.levels[self.level:]:
                lon, lat = child.run.window.centre
                self._draw_local_circle(canvas, current, lon, lat,
                                        child.run.window.radius_m / 1000, MAP_TEXT)
            if self.picking.get() and self._pick_at is not None:
                self._draw_local_circle(canvas, current, *self._pick_at, self.radius_km(),
                                        MAP_HIGHLIGHT)
        canvas.create_rectangle(left, top, right, bottom, outline=MAP_FRAME)
        if self.level:
            self._draw_scale(canvas, self.levels[self.level - 1])
        map_label(canvas, 12, 12, f"{self.display_layer.get()}  ·  {canvas.viewport.zoom:.1f}x")

    @staticmethod
    def _draw_graticule(canvas: FlatMapCanvas, rect: Rect, meridian: float) -> None:
        left, top, right, bottom = rect
        for lon in range(-180, 180, GRATICULE_STEP_DEG):
            u = ((lon - meridian + 180) % 360) / 360
            x = left + u * (right - left)
            canvas.create_line(x, top, x, bottom, fill=MAP_GRID, dash=(2, 6))
        for lat in range(-90 + GRATICULE_STEP_DEG, 90, GRATICULE_STEP_DEG):
            y = top + (90 - lat) / 180 * (bottom - top)
            canvas.create_line(left, y, right, y, fill=MAP_GRID, dash=(2, 6))

    @staticmethod
    def _circle(lon: float, lat: float, radius_km: float, planet_radius_km: float
                ) -> list[tuple[float, float]]:
        """Longitude and latitude of points around a small circle on the sphere."""
        angle = radius_km / planet_radius_km
        phi, lam = radians(lat), radians(lon)
        points: list[tuple[float, float]] = []
        for step in range(0, 361, 5):
            bearing = radians(step)
            phi2 = asin(sin(phi) * cos(angle) + cos(phi) * sin(angle) * cos(bearing))
            lam2 = lam + atan2(sin(bearing) * sin(angle) * cos(phi),
                               cos(angle) - sin(phi) * sin(phi2))
            points.append((degrees(lam2), degrees(phi2)))
        return points

    def _draw_circle(
        self, canvas: FlatMapCanvas, scene: SourceScene, lon: float, lat: float,
        radius_km: float, colour: str, *, width: int = 1,
    ) -> None:
        """A small circle on the sphere drawn on the flat map (split at the seam)."""
        assert scene.frame is not None
        segment: list[float] = []
        previous: float | None = None
        for point_lon, point_lat in self._circle(lon, lat, radius_km, scene.frame.radius_km):
            u = ((point_lon - scene.central_meridian_deg + 180) % 360) / 360
            if previous is not None and abs(u - previous) > 0.5:
                if len(segment) >= 4:
                    canvas.create_line(*segment, fill=colour, width=width)
                segment = []
            segment.extend(canvas.to_canvas(u, (90 - point_lat) / 180))
            previous = u
        if len(segment) >= 4:
            canvas.create_line(*segment, fill=colour, width=width)

    def _globe_overlay(self, canvas: GlobeCanvas) -> None:
        """Opened regions and the region about to be picked, on the globe or polar view.

        A region whose map lies over the view is outlined until the view's centre
        shows that map in full.
        """
        frame = canvas.frame
        assert frame is not None
        projection = frame.projection
        scene = self.scene
        if scene is not None and scene.frame is not None:
            # Ground per pixel at the centre: an orthographic globe is true to scale
            # there, and a polar view is true along every meridian.
            planet_m = scene.frame.radius_km * 1000
            ground_m = planet_m if projection.kind == "globe" else (
                planet_m * radians(projection.polar_span_deg))
            metres_per_px = ground_m / view_radius(projection, frame.size)
            image = canvas.image
            detailed = image is not None and drapes_in_full(projection, frame.size, image.width)
            layer = self.display_layer.get()
            circles = [(*level.run.window.centre, level.run.window.radius_m / 1000, MAP_TEXT)
                       for level in self.levels
                       if not (detailed and self._drape_image(level, layer) is not None)]
            if self.picking.get() and self._pick_at is not None:
                circles.append((*self._pick_at, self.radius_km(), MAP_HIGHLIGHT))
            for lon, lat, radius_km, colour in circles:
                segment: list[float] = []
                for point in self._circle(lon, lat, radius_km, scene.frame.radius_km):
                    position = canvas.to_canvas(*point)
                    if position is None:
                        if len(segment) >= 4:
                            canvas.create_line(*segment, fill=colour, width=2)
                        segment = []
                    else:
                        segment.extend(position)
                if len(segment) >= 4:
                    canvas.create_line(*segment, fill=colour, width=2)
            self._draw_scale_bar(canvas, metres_per_px, float(frame.size[1]))
        zoom = f"  ·  {projection.zoom:.1f}x" if projection.kind == "globe" else ""
        map_label(canvas, 12, 12, f"{self.display_layer.get()}{zoom}")

    @staticmethod
    def _draw_local_circle(
        canvas: FlatMapCanvas, level: RegionLevel, lon: float, lat: float, radius_km: float,
        colour: str,
    ) -> None:
        """A circle on a regional map (distances from its centre are true)."""
        window = level.run.window
        u, v = window_position(window, lon, lat)
        r = radius_km * 1000 / (2 * window.radius_m)
        x0, y0 = canvas.to_canvas(u - r, v - r)
        x1, y1 = canvas.to_canvas(u + r, v + r)
        canvas.create_oval(x0, y0, x1, y1, outline=colour, width=2)

    @staticmethod
    def _draw_scale(canvas: FlatMapCanvas, level: RegionLevel) -> None:
        left, _, right, bottom = canvas.map_rect()
        metres_per_px = 2 * level.run.window.radius_m / max(right - left, 1.0)
        WorldMapView._draw_scale_bar(canvas, metres_per_px, bottom)

    @staticmethod
    def _draw_scale_bar(canvas: tk.Canvas, metres_per_px: float, bottom: float) -> None:
        """A bar of a round distance about 140 pixels long, at the map's bottom left."""
        target = 140 * metres_per_px
        nice = max((n * 10**p for p in range(0, 8) for n in (1, 2, 5) if n * 10**p <= target),
                   default=target)
        width_px = nice / metres_per_px
        height = canvas.winfo_height()
        x0, y0 = 16.0, min(bottom, float(height)) - 18
        label = f"{nice / 1000:,.0f} km" if nice >= 1000 else f"{nice:,.0f} m"
        map_label(canvas, x0 + width_px + 8, y0, label, anchor="w")
        canvas.create_rectangle(x0 - 4, y0 - 5, x0 + width_px + 4, y0 + 5,
                                fill=MAP_BACKGROUND, outline="")
        canvas.create_line(x0, y0, x0 + width_px, y0, fill=MAP_TEXT, width=3)


    def _view_changed(self) -> None:
        if self.picking.get():
            self.inspection.set(self._hint())

    # Hover and clicks

    def describe_at(self, u: float, v: float) -> str:
        """The readout for normalized flat-map position (u across, v down)."""
        if self.level:
            return region_readout(self.levels[self.level - 1].run.window, u, v)
        scene = self.scene
        if scene is None:
            return ""
        x0, y0, x1, y1 = scene.bounds
        position = (x0 + u * (x1 - x0), y0 + v * (y1 - y0))
        if scene.frame is None:
            return (f"Source x {position[0]:.2f}, y {position[1]:.2f} · Confirm the world "
                    "frame and radius for geographic coordinates.")
        lon, lat = scene.frame.source_to_lonlat(position)
        return lonlat_text(lon, lat) + "  ·  " + self._detail(lon, lat, u, v)

    def _detail(self, lon: float, lat: float, u: float, v: float) -> str:
        group, layer = self.group.get(), self.display_layer.get()
        if group == PLANET and self.probe is not None:
            return self.probe.describe(lon, lat)
        if group == CONTEXT and self.context_run is not None:
            return context_readout(
                self.context_run.context, layer, self.exposure_bearing.get(), u, v
            )
        return HINTS["flat"]

    def _hover_flat(self, point: tuple[float, float] | None) -> None:
        if point is None:
            self.inspection.set(self._hint())
            return
        text = self.describe_at(*point)
        if self.picking.get():
            self._pick_at = self._lonlat_at(*point)
            self.flat.draw_overlay()
            text = f"{text}\n{self._hint()}"
        self.inspection.set(text)

    def _lonlat_at(self, u: float, v: float) -> tuple[float, float] | None:
        """Longitude and latitude at a normalized flat-map position, if known."""
        if self.level:
            return window_lonlat(self.levels[self.level - 1].run.window, u, v)
        scene = self.scene
        if scene is None or scene.frame is None:
            return None
        x0, y0, x1, y1 = scene.bounds
        return scene.frame.source_to_lonlat((x0 + u * (x1 - x0), y0 + v * (y1 - y0)))

    def _hover_globe(self, lonlat: tuple[float, float] | None) -> None:
        if self.picking.get():
            self._pick_at = lonlat
            self.globe.draw_overlay()
        if lonlat is None or self.probe is None:
            self.inspection.set(self._hint())
            return
        text = lonlat_text(*lonlat) + "  ·  " + self.probe.describe(*lonlat)
        self.inspection.set(f"{text}\n{self._hint()}" if self.picking.get() else text)

    def _click_flat(self, point: tuple[float, float], event: tk.Event[tk.Misc]) -> None:
        if self.picking.get():
            lonlat = self._lonlat_at(*point)
            if lonlat is not None:
                self._pick(*lonlat)
            return
        scene = self.scene
        if self.level or scene is None or self.group.get() != SOURCE:
            return
        x0, y0, x1, y1 = scene.bounds
        position = (x0 + point[0] * (x1 - x0), y0 + point[1] * (y1 - y0))
        self._pick_shape(position, bool(int(event.state) & 0x0004))

    def _click_globe(self, lonlat: tuple[float, float], _event: tk.Event[tk.Misc]) -> None:
        if self.picking.get():
            self._pick(*lonlat)

    def _pick(self, lon: float, lat: float) -> None:
        radius = self.radius_km()
        self.picking.set(False)
        self._picking_changed()
        self._request_region(lon, lat, radius, self.level + 1)

    # Saving

    def current_image(self) -> Callable[[], Image.Image] | None:
        """A function that renders what is shown, for saving (run it off the Tk thread)."""
        if self.level:
            level = self.levels[self.level - 1]
            image = level.images[level.theme_id].image
            return image.copy
        if self._uses_globe():
            globe = self.globe
            return None if globe.image is None else globe.snapshot(SAVE_PIXELS)
        run, layer = self.planet_run, self.display_layer.get()
        if self.group.get() == PLANET and run is not None and layer in run.maps.labels:
            maps = run.maps
            return lambda: maps.draw(layer).copy()
        renderer, _ = self._flat_content()
        if renderer is None:
            return None
        viewport = MapViewport(self.flat.viewport.centre, self.flat.viewport.zoom)
        size = self.flat.size()
        return lambda: renderer(viewport, size)

    def choose_save_image(self) -> None:
        render = self.current_image()
        if render is None:
            self._status("Nothing to save yet: wait until the map is drawn.")
            return
        selected = filedialog.asksaveasfilename(
            parent=self, title="Save this map as an image", defaultextension=".png",
            initialfile=f"map-{uuid4().hex[:8]}.png", filetypes=[("PNG image", "*.png")],
        )
        if selected:
            self.save_image(Path(selected), render)

    def save_image(self, destination: Path, render: Callable[[], Image.Image]) -> None:
        def work(_report: Report, _token: CancellationToken) -> Path:
            with destination.open("wb") as stream:
                render().save(stream, format="PNG")
            return destination

        self._jobs.start(
            "Saving the map image…", work, lambda path: self._status(f"Saved {path.name}"),
            cancellable=False,
        )

    def choose_save_globe(self) -> None:
        """Save the shown planet map as a 3D globe model."""
        run, layer = self.planet_run, self.display_layer.get()
        if self.level or self.group.get() != PLANET or run is None or layer not in run.maps.labels:
            self._status("Show a planet map of the whole world to save it as a 3D globe.")
            return
        selected = filedialog.asksaveasfilename(
            parent=self, title="Save this map as a 3D globe", defaultextension=".glb",
            initialfile=f"globe-{uuid4().hex[:8]}.glb", filetypes=[("glTF 3D model", "*.glb")],
        )
        if selected:
            self.write_globe(Path(selected), layer)

    def write_globe(self, destination: Path, layer: str) -> None:
        """Save the planet map ``layer`` as a 3D globe, with the opened regions drawn in it."""
        run = self.planet_run
        assert run is not None
        maps, frame = run.maps, run.result.world.project.frame
        drapes = self._drapes(layer)
        regions = f" with {len(drapes)} regional map{'s' * (len(drapes) > 1)}" if drapes else ""

        def work(_report: Report, _token: CancellationToken) -> Path:
            return save_globe(destination, maps.draw(layer), layer, frame, drapes)

        self._jobs.start(
            "Saving the 3D globe…", work,
            lambda path: self._status(f"Saved {path.name}{regions}"),
            cancellable=False,
        )

    def choose_save_spin(self) -> None:
        """Save the shown globe or polar view turning once, as an animated image."""
        if not self._uses_globe() or self.globe.image is None:
            self._status("Show a planet map as a globe or polar view to save it spinning.")
            return
        selected = filedialog.asksaveasfilename(
            parent=self, title="Save this globe spinning", defaultextension=".webp",
            initialfile=f"spin-{uuid4().hex[:8]}.webp",
            filetypes=[("Animated WebP image", "*.webp")],
        )
        if selected:
            self.write_spin(Path(selected))

    def write_spin(self, destination: Path) -> None:
        """Save the view's middle square turning once (see ``globe_spin``)."""
        draw = self.globe.turn_snapshot(SPIN_PIXELS, SPIN_FRAMES)

        def work(_report: Report, _token: CancellationToken) -> Path:
            frames = draw()
            with destination.open("wb") as stream:
                write_spin(frames, stream)
            return destination

        self._jobs.start(
            "Saving the spinning globe…", work, lambda path: self._status(f"Saved {path.name}"),
            cancellable=False,
        )

    def choose_region_export(self) -> None:
        if not self.level:
            return
        selected = filedialog.asksaveasfilename(
            parent=self, title="Create a new region folder",
            initialfile="region-" + uuid4().hex[:8],
        )
        if selected:
            self._export_region(self.levels[self.level - 1].run, Path(selected))

