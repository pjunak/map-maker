# pyright: reportUnknownMemberType=false
"""The World workspace's Geology step: authored geology over the retained world.

The editor is a sidebar page (this frame) plus its own map (``self.map``), which the
workspace shows in place of the world map while the step is open. Its work runs on
the workspace's job runner, so it shares one status bar and one job at a time.
"""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Literal, cast
from uuid import uuid4

from PIL import Image

from dmtools.terrain.adapters.world_context_render import (
    CONTEXT_LAYERS,
    ContextLayer,
    render_world_context,
)
from dmtools.terrain.adapters.world_geology import GEOLOGY_EXTENSION, geology_file_hash
from dmtools.terrain.adapters.world_geology_render import SETTING_COLOURS, render_geology
from dmtools.terrain.adapters.world_render import OCEAN, render_world_source
from dmtools.terrain.application.world_context import WorldContextRun
from dmtools.terrain.application.world_geology import GeologyFile, open_geology, save_geology
from dmtools.terrain.domain.models import Point2D
from dmtools.terrain.domain.wonders import WONDER_KINDS, WONDERS, WonderKind
from dmtools.terrain.domain.world_context import EXPOSURE_BEARINGS
from dmtools.terrain.domain.world_geology import (
    GEOLOGICAL_SETTINGS,
    MAX_PROVINCE_VERTICES,
    SETTING_TEXT,
    ContinentGeology,
    GeologicalSetting,
    GeologyLandmark,
    GeologyProfile,
    GeologyProvince,
    WorldGeologyRecipe,
    blank_geology,
    follow_world,
)
from dmtools.terrain.map_canvas import FlatMapCanvas, Rect
from dmtools.terrain.pipeline.control import CancellationToken
from dmtools.terrain.pipeline.world import WorldMap
from dmtools.terrain.pipeline.world_geology import GeologyCoverage, resolve_geology
from dmtools.terrain.ui_components import (
    Collapsible,
    MapInfoStrip,
    WrappingLabel,
    button_row,
    field,
    hint,
    section,
)
from dmtools.terrain.ui_jobs import JobRunner, Report
from dmtools.terrain.ui_style import GAP, MAP_FRAME, MAP_HIGHLIGHT, MAP_TEXT
from dmtools.terrain.viewport import MapViewport
from dmtools.terrain.world_landform_ui import WorldLandformForm
from dmtools.terrain.world_view import CONTEXT_LEGENDS

KIND_BY_LABEL: dict[str, WonderKind] = {WONDERS[kind].label: kind for kind in WONDER_KINDS}
SETTING_BY_LABEL: dict[str, GeologicalSetting] = {
    SETTING_TEXT[setting][0]: setting for setting in GEOLOGICAL_SETTINGS
}

COVERAGE = "Geology coverage"
SOURCE = "Source"
LEGENDS = {
    COVERAGE: "Colours show each region's geological setting (key in the sidebar). Dashed "
    "outlines are provinces; the selected one is bold.",
    SOURCE: "Your source map, for placing provinces.",
    **CONTEXT_LEGENDS,
}
HINT = "Drag to pan · wheel to zoom · F fits · click a region to select it"
DRAW_HINT = "Click to add corners · Enter finishes · Backspace removes · Escape cancels"


@dataclass(frozen=True)
class _Result:
    coverage: GeologyCoverage
    mode: Literal["initial", "edit", "open", "save", "follow"]
    file: GeologyFile | None = None


class GeologyEditor(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        map_parent: tk.Misc,
        world: WorldMap,
        context: WorldContextRun | None = None,
        *,
        jobs: JobRunner,
        status: tk.StringVar,
        on_change: Callable[[], None] = lambda: None,
        recipe: WorldGeologyRecipe | None = None,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.world = world
        self.context = context
        self.jobs = jobs
        self.status = status
        self.on_change = on_change
        self.file: GeologyFile | None = None
        self.recipe = recipe or blank_geology(world.project)
        self.coverage: GeologyCoverage | None = None
        self._saved_recipe: WorldGeologyRecipe | None = None
        self._undo: list[GeologyCoverage] = []
        self._redo: list[GeologyCoverage] = []
        self._controls: list[tuple[ttk.Widget, str]] = []
        self._field_widgets: dict[str, ttk.Widget] = {}
        self._selected = "continent:" + world.continents[0].id
        self._next_selected = self._selected
        self._draft: list[Point2D] | None = None
        self._draft_id: str | None = None
        self._loaded_form: tuple[str, ...] = ()
        self._closed = False
        self.values = {
            key: tk.StringVar(self)
            for key in ("name", "priority", "setting", "crust", "rejuvenation", "duration")
        }
        self.setting_label = tk.StringVar(self)
        self.setting_help = tk.StringVar(self)
        self.landmark = {
            "name": tk.StringVar(self),
            "kind": tk.StringVar(self, value=WONDERS["crater"].label),
            "size": tk.StringVar(self),
            "age": tk.StringVar(self),
        }
        self.landmark_help = tk.StringVar(self)
        self._landmark_selected: str | None = None
        self._placing = False
        self._line_start: Point2D | None = None  # a line wonder's first click
        self.layer = tk.StringVar(self, value=COVERAGE)
        self.bearing = tk.StringVar(self, value="N")
        self.file_label = tk.StringVar(self)
        self.region_title = tk.StringVar(self)
        self.detail = tk.StringVar(self)
        self.legend = tk.StringVar(self, value=LEGENDS[COVERAGE])
        self.inspection = tk.StringVar(self, value=HINT)
        self._build()
        self.map = self._build_map(map_parent)
        self.values["setting"].trace_add("write", self._setting_changed)
        self.setting_label.trace_add("write", self._setting_chosen)
        self._populate()
        self._load_form()
        self._show_file()
        self.canvas.bind("<Return>", lambda _e: self._key(self.apply))
        self.canvas.bind("<Escape>", lambda _e: self._key(self.revert))
        self.canvas.bind("<BackSpace>", lambda _e: self._key(self.remove_vertex))
        self.canvas.bind("f", lambda _e: self._key(self.fit))

    def start(self) -> None:
        """Resolve the starting recipe; until then the map shows no coverage."""
        recipe, world = self.recipe, self.world
        self._work(
            "Resolving continent defaults",
            lambda token: _Result(resolve_geology(world, recipe, token), "initial"),
        )

    @staticmethod
    def _key(action: Callable[[], None]) -> str:
        action()
        return "break"

    @property
    def busy(self) -> bool:
        return self.jobs.busy

    @property
    def viewport(self) -> MapViewport:
        return self.canvas.viewport

    @property
    def form_dirty(self) -> bool:
        return self._form() != self._loaded_form

    @property
    def editing(self) -> bool:
        """An unapplied form edit, an unfinished outline or a landmark being placed."""
        return self.form_dirty or self._draft is not None or self._placing

    @property
    def dirty(self) -> bool:
        return self.recipe != self._saved_recipe or self.editing

    def summary(self) -> str:
        """One line on what this recipe sets, for the step list and other steps."""
        provinces, landmarks = len(self.recipe.provinces), len(self.recipe.landmarks)
        parts = [f"{provinces} province{'s' * (provinces != 1)}"]
        if landmarks:
            parts.append(f"{landmarks} landmark{'s' * (landmarks != 1)}")
        if self.dirty:
            parts.append("unsaved")
        return " · ".join(parts)

    def _button(
        self, parent: tk.Misc, text: str, command: Callable[[], None], *, style: str = "Quiet"
    ) -> ttk.Button:
        # Small buttons fit their text, so a row of them fits the sidebar.
        width: int | Literal[""] = len(text) + 2 if style == "Small" else ""
        button = ttk.Button(parent, text=text, command=command, style=f"{style}.TButton",
                            width=width)
        self._controls.append((button, "normal"))
        return button

    # Layout

    def _build(self) -> None:
        recipe = button_row(self, pady=(0, 0))
        WrappingLabel(recipe, textvariable=self.file_label, style="Body.TLabel").pack(fill="x")
        files = button_row(self, pady=(GAP // 2, 0))
        for text, command in (
            ("Open…", self.choose_open),
            ("Save", self.save),
            ("Save As…", lambda: self.save(save_as=True)),
        ):
            self._button(files, text, command, style="Small").pack(side="left", padx=(0, 4))
        for text, command in (("Redo", self.redo), ("Undo", self.undo)):
            self._button(files, text, command, style="Small").pack(side="right", padx=(4, 0))
        self._build_regions()
        self._build_region_form()
        self._build_landmarks()

    def _build_regions(self) -> None:
        box = section(self, "Regions")
        hint(box, "Every continent has a default. Draw provinces to give part of the land "
             "its own geology; where provinces overlap, the higher priority wins.")
        tree_frame = ttk.Frame(box, style="Panel.TFrame")
        tree_frame.pack(fill="x", pady=(GAP // 2, 0))
        tree_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse", height=8)
        self.tree.column("#0", width=260)
        self.tree.grid(row=0, column=0, sticky="nsew")

        def scroll_tree(*args: str) -> None:
            self.tree.yview(*args)

        bar = ttk.Scrollbar(tree_frame, orient="vertical", command=scroll_tree)
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind("<<TreeviewSelect>>", self._selection)
        tools = button_row(box, pady=(GAP // 2, 0))
        for text, action in (
            ("Draw province", self.start_drawing),
            ("Redraw outline", lambda: self.start_drawing(redraw=True)),
            ("Delete", self.delete),
        ):
            self._button(tools, text, action, style="Small").pack(side="left", padx=(0, 4))
        key = ttk.Frame(box, style="Panel.TFrame")
        key.pack(fill="x", pady=(GAP, 0))
        for row, (setting, colour) in enumerate(SETTING_COLOURS.items()):
            tk.Label(key, background=colour, width=2).grid(
                row=row // 2, column=row % 2 * 2, padx=(0, 5), pady=1
            )
            ttk.Label(key, text=SETTING_TEXT[setting][0], style="Help.TLabel").grid(
                row=row // 2, column=row % 2 * 2 + 1, sticky="w", padx=(0, 7)
            )

    def _build_region_form(self) -> None:
        ttk.Label(self, textvariable=self.region_title, style="Section.TLabel").pack(
            anchor="w", pady=(2 * GAP, 0)
        )
        self.detail_label = WrappingLabel(self, textvariable=self.detail, style="Help.TLabel")
        self.detail_label.pack(fill="x")
        self.identity = ttk.Frame(self, style="Panel.TFrame")
        self.identity.pack(fill="x")
        for key, label, help_text in (
            ("name", "Province name", ""),
            ("priority", "Priority", "0-100. Where provinces overlap, the higher one wins."),
        ):
            entry = field(self.identity, label, self.values[key], width=24 if key == "name" else 6,
                          help=help_text)
            self._field_widgets[key] = entry
            self._controls.append((entry, "normal"))
        box = ttk.Frame(self, style="Panel.TFrame")
        box.pack(fill="x", pady=(GAP, 0))
        ttk.Label(box, text="Geological setting", style="Body.TLabel").pack(anchor="w")
        setting = ttk.Combobox(
            box, textvariable=self.setting_label, state="readonly", width=24,
            values=tuple(SETTING_TEXT[s][0] for s in GEOLOGICAL_SETTINGS),
        )
        setting.pack(anchor="w", pady=(2, 0))
        self._field_widgets["setting"] = setting
        self._controls.append((setting, "readonly"))
        hint(box, textvariable=self.setting_help)
        for key, label, help_text in (
            ("crust", "Crust age",
             "How old the rock is. Crust older than 1,000 million years is harder and "
             "erodes more slowly. Blank: unknown."),
            ("rejuvenation", "Time since uplift",
             "When its mountains last rose. Older ranges are lower and smoother; "
             "0 means still rising. Blank: unknown."),
        ):
            entry = field(self, label, self.values[key], unit="million years", width=10,
                          help=help_text)
            self._field_widgets[key] = entry
            self._controls.append((entry, "normal"))
        landform = Collapsible(self, "Exact landform (optional)")
        landform.pack(fill="x", pady=(GAP, 0))
        hint(landform.body, "Sets heights directly instead of the setting's usual ones.")
        self.landform_form = WorldLandformForm(landform.body)
        self.landform_form.pack(fill="x")
        self.landform_section = landform
        more = Collapsible(self, "Recorded only")
        more.pack(fill="x", pady=(GAP // 2, 0))
        entry = field(more.body, "Simulation span", self.values["duration"],
                      unit="million years", width=10,
                      help="Kept with the recipe for later tools; generation does not use it.")
        self._field_widgets["duration"] = entry
        self._controls.append((entry, "normal"))
        actions = button_row(self)
        actions.columnconfigure((0, 1), weight=1)
        self._button(actions, "Apply changes", self.apply, style="Accent").grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        self._button(actions, "Revert", self.revert).grid(
            row=0, column=1, sticky="ew", padx=(3, 0)
        )

    def _build_landmarks(self) -> None:
        """Hand-placed wonders from the catalog (``domain.wonders``)."""
        box = section(self, "Landmarks")
        hint(box, "Wonders placed exactly where you want them. Placed wonders replace "
             "random ones of their kind.")
        grid = ttk.Frame(box, style="Panel.TFrame")
        grid.pack(fill="x", pady=(GAP // 2, 0))
        grid.columnconfigure(1, weight=1)
        kind = ttk.Combobox(
            grid, textvariable=self.landmark["kind"], values=tuple(KIND_BY_LABEL),
            state="readonly", width=20,
        )
        ttk.Label(grid, text="Kind", style="Body.TLabel").grid(row=0, column=0, sticky="w")
        kind.grid(row=0, column=1, sticky="w", pady=2)
        name = ttk.Entry(grid, textvariable=self.landmark["name"], width=22)
        ttk.Label(grid, text="Name", style="Body.TLabel").grid(row=1, column=0, sticky="w")
        name.grid(row=1, column=1, sticky="w", pady=2)
        size = ttk.Entry(grid, textvariable=self.landmark["size"], width=8)
        ttk.Label(grid, text="Size", style="Body.TLabel").grid(row=2, column=0, sticky="w")
        size.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(grid, text="km", style="Body.TLabel").grid(row=2, column=1, padx=(70, 0),
                                                              sticky="w")
        age = ttk.Entry(grid, textvariable=self.landmark["age"], width=8)
        ttk.Label(grid, text="Age", style="Body.TLabel").grid(row=3, column=0, sticky="w",
                                                               padx=(0, GAP))
        age.grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(grid, text="million years", style="Body.TLabel").grid(
            row=3, column=1, padx=(70, 0), sticky="w"
        )
        self._controls.extend(
            ((name, "normal"), (kind, "readonly"), (size, "normal"), (age, "normal"))
        )
        hint(box, textvariable=self.landmark_help)
        buttons = button_row(box)
        for text, action in (
            ("Place on map", self.place_landmark),
            ("Update", self.update_landmark),
            ("Delete", self.delete_landmark),
        ):
            self._button(buttons, text, action, style="Small").pack(side="left", padx=(0, 4))
        self.landmark["kind"].trace_add("write", self._describe_landmark)
        self._describe_landmark()

    def _landmark_kind(self) -> WonderKind:
        return KIND_BY_LABEL[self.landmark["kind"].get()]

    def _describe_landmark(self, *_args: str) -> None:
        spec = WONDERS[self._landmark_kind()]
        if spec.size_km is None:
            size = " It has no size."
        else:
            low, high, usual = spec.size_km
            size = f" Size is its {spec.size}, {low:g}-{high:g} km; blank uses {usual:g} km."
        clicks = " Place it with two clicks, one per end." if spec.line else ""
        age = (
            " Age erodes it; blank uses the planet's wonder age." if spec.ages
            else " It does not age."
        )
        self.landmark_help.set(f"{spec.summary}{size}{clicks}{age}")

    def _build_map(self, parent: tk.Misc) -> ttk.Frame:
        frame_widget = ttk.Frame(parent, style="Panel.TFrame")
        frame_widget.columnconfigure(0, weight=1)
        frame_widget.rowconfigure(1, weight=1)
        view_tools = ttk.Frame(frame_widget, style="Toolbar.TFrame", padding=GAP)
        view_tools.grid(row=0, column=0, sticky="ew")
        ttk.Label(view_tools, text="Geology", style="Section.TLabel").pack(side="left")
        self.layer_input = ttk.Combobox(
            view_tools, textvariable=self.layer, state="readonly", width=24
        )
        self.layer_input.pack(side="left", padx=GAP)
        self.layer_input.bind("<<ComboboxSelected>>", lambda _e: self._layer_changed())
        self.look_label = ttk.Label(view_tools, text="Look", style="Body.TLabel")
        self.bearing_input = ttk.Combobox(
            view_tools, textvariable=self.bearing, values=EXPOSURE_BEARINGS,
            state="readonly", width=4,
        )
        self.bearing_input.bind("<<ComboboxSelected>>", lambda _e: self.canvas.redraw())
        ttk.Button(view_tools, text="Fit", style="Small.TButton", command=self.fit).pack(
            side="right"
        )
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
        self._sync_layers()
        return frame_widget

    def _sync_layers(self) -> None:
        self.layer_input.configure(
            values=(COVERAGE, SOURCE, *(CONTEXT_LAYERS if self.context else ()))
        )
        if self.context is None and self.layer.get() not in (COVERAGE, SOURCE):
            self.layer.set(COVERAGE)
        if self.context is not None:
            self.look_label.pack(side="left")
            self.bearing_input.pack(side="left", padx=4)
        else:
            self.look_label.pack_forget()
            self.bearing_input.pack_forget()
        self._layer_changed()

    def set_context(self, context: WorldContextRun | None) -> None:
        """Offer the world's current geographic context as backgrounds."""
        self.context = context
        self._sync_layers()

    def _layer_changed(self) -> None:
        self.legend.set(LEGENDS.get(self.layer.get(), ""))
        self.canvas.redraw()

    # Form and selection

    def _setting_changed(self, *_args: str) -> None:
        setting = cast(GeologicalSetting, self.values["setting"].get())
        if setting in SETTING_TEXT:
            label, meaning = SETTING_TEXT[setting]
            if self.setting_label.get() != label:
                self.setting_label.set(label)
            self.setting_help.set(meaning)

    def _setting_chosen(self, *_args: str) -> None:
        setting = SETTING_BY_LABEL.get(self.setting_label.get())
        if setting is not None and self.values["setting"].get() != setting:
            self.values["setting"].set(setting)

    def _form(self) -> tuple[str, ...]:
        return (*tuple(v.get() for v in self.values.values()), *self.landform_form.snapshot())

    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree.insert("", "end", iid="defaults", text="Continent defaults", open=True)
        self.tree.insert(
            "", "end", iid="provinces", text="Provinces · higher priority wins", open=True
        )
        for c in self.world.continents:
            self.tree.insert("defaults", "end", iid="continent:" + c.id, text=c.name)
        for p in sorted(self.recipe.provinces, key=lambda p: (-p.priority, p.name)):
            self.tree.insert("provinces", "end", iid=p.id, text=f"{p.name} · priority {p.priority}")
        self.tree.insert("", "end", iid="landmarks", text="Landmarks", open=True)
        for m in sorted(self.recipe.landmarks, key=lambda m: m.name):
            self.tree.insert(
                "landmarks", "end", iid=m.id,
                text=f"{m.name} · {WONDERS[m.kind].label}"
                + ("" if WONDERS[m.kind].size_km is None else f" {m.effective_size_km:,.4g} km"),
            )
        if self._landmark_selected and self.tree.exists(self._landmark_selected):
            self.tree.selection_set(self._landmark_selected)
            self.tree.see(self._landmark_selected)
        elif self.tree.exists(self._selected):
            self.tree.selection_set(self._selected)
            self.tree.see(self._selected)

    def _load_form(self) -> None:
        province = next((p for p in self.recipe.provinces if p.id == self._selected), None)
        if province:
            name, priority, profile = province.name, str(province.priority), province.profile
        else:
            owner = self._selected.removeprefix("continent:")
            default = next((d for d in self.recipe.defaults if d.continent_id == owner), None)
            name = next((c.name for c in self.world.continents if c.id == owner), "New province")
            priority, profile = "0", default.profile if default else GeologyProfile()
        for key, value in zip(
            self.values,
            (
                name,
                priority,
                profile.setting,
                "" if profile.crust_age_ma is None else str(profile.crust_age_ma),
                "" if profile.rejuvenation_age_ma is None else str(profile.rejuvenation_age_ma),
                "" if profile.evolution_duration_ma is None else str(profile.evolution_duration_ma),
            ),
            strict=True,
        ):
            self.values[key].set(value)
        self.landform_form.load(profile.landform)
        if profile.landform is not None and not self.landform_section.expanded:
            self.landform_section.toggle()
        self._loaded_form = self._form()
        is_default = self._selected.startswith("continent:") and self._draft is None
        self.region_title.set(
            f"{name} · continent default" if is_default
            else f"New province: {name}" if province is None else f"Province: {name}"
        )
        if is_default:
            self.identity.pack_forget()
        else:
            self.identity.pack(fill="x", after=self.detail_label)
        self._lock_identity_fields()
        region = (
            next((r for r in self.coverage.regions if r.id == self._selected), None)
            if self.coverage
            else None
        )
        self.detail.set(
            f"Covers {region.area_km2:,.0f} km² of land"
            + (" (this province wins there)." if region.province
               else " not claimed by a province.")
            if region
            else "Click at least three corners on the map, then Apply changes."
            if self._draft is not None
            else ""
        )

    def _lock_identity_fields(self) -> None:
        state = (
            "disabled"
            if self.busy
            else ("readonly" if self._selected.startswith("continent:") else "normal")
        )
        for key in ("name", "priority"):
            self._field_widgets[key]["state"] = state

    def _selection(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.tree.selection()
        if not selection or selection[0] == self._selected:
            return
        if self.busy or self.form_dirty or self._draft is not None:
            self.status.set("Apply or revert the current edit before selecting another region.")
            if self.tree.exists(self._selected):
                self.tree.selection_set(self._selected)
            return
        if selection[0] in ("defaults", "provinces", "landmarks"):
            return
        landmark = next((m for m in self.recipe.landmarks if m.id == selection[0]), None)
        if landmark is not None:
            self._landmark_selected = landmark.id
            self.landmark["name"].set(landmark.name)
            self.landmark["kind"].set(WONDERS[landmark.kind].label)
            self.landmark["size"].set("" if landmark.size_km is None else f"{landmark.size_km:g}")
            self.landmark["age"].set("" if landmark.age_myr is None else f"{landmark.age_myr:g}")
            self.canvas.redraw()
            return
        self._landmark_selected = None
        self._selected = selection[0]
        self._load_form()
        self.canvas.redraw()

    def _profile(self) -> GeologyProfile:
        values = [self.values[key].get().strip() for key in ("crust", "rejuvenation", "duration")]
        try:
            ages = [float(value) if value else None for value in values]
        except ValueError as error:
            raise ValueError("Ages are numbers of million years, or blank.") from error
        return GeologyProfile(
            cast(GeologicalSetting, self.values["setting"].get()),
            *ages,
            landform=self.landform_form.read(),
        )

    def _candidate(self) -> WorldGeologyRecipe:
        profile = self._profile()
        if self._draft is not None or not self._selected.startswith("continent:"):
            current = next((p for p in self.recipe.provinces if p.id == self._selected), None)
            try:
                priority = int(self.values["priority"].get())
            except ValueError as error:
                raise ValueError("Priority is a whole number from 0 to 100.") from error
            province = GeologyProvince(
                self._draft_id or self._selected,
                self.values["name"].get().strip(),
                tuple(self._draft)
                if self._draft is not None
                else current.vertices
                if current
                else (),
                priority,
                profile,
            )
            self._next_selected = province.id
            return replace(
                self.recipe,
                provinces=(*(p for p in self.recipe.provinces if p.id != province.id), province),
            )
        if (
            self.values["name"].get() != self._loaded_form[0]
            or self.values["priority"].get() != "0"
        ):
            raise ValueError(
                "Rename continents in the Source map step; priorities apply to provinces."
            )
        owner = self._selected.removeprefix("continent:")
        self._next_selected = self._selected
        return replace(
            self.recipe,
            defaults=tuple(
                ContinentGeology(owner, profile) if d.continent_id == owner else d
                for d in self.recipe.defaults
            ),
        )

    # Editing

    def apply(self, after: Callable[[], None] | None = None) -> None:
        if self.busy:
            return
        try:
            candidate = self._candidate()
        except ValueError as error:
            self.status.set(str(error))
            return
        world = self.world
        self._work(
            "Resolving province priorities and land coverage",
            lambda token: _Result(resolve_geology(world, candidate, token), "edit"),
            after,
        )

    def start_drawing(self, *, redraw: bool = False) -> None:
        if self.busy or self.form_dirty or self._draft is not None:
            self.status.set("Apply or revert the current edit before drawing.")
            return
        if redraw and self._selected.startswith("continent:"):
            self.status.set("Select a province to redraw its outline.")
            return
        self._draft = []
        self._draft_id = self._selected if redraw else "province-" + uuid4().hex
        if not redraw:
            self._selected = self._draft_id
            self.tree.selection_remove(*self.tree.selection())
            self._load_form()
            names = {p.name for p in self.recipe.provinces}
            number = 1
            while f"Province {number}" in names:
                number += 1
            self.values["name"].set(f"Province {number}")
        self.status.set(
            "Click the province's corners on the map. Enter: finish · Backspace: remove the "
            "last corner · Escape: cancel. An outline may cross the map's left/right edge."
        )
        self.inspection.set(DRAW_HINT)
        self.canvas.configure(cursor="crosshair")
        self.canvas.focus_set()
        self.canvas.redraw()

    def remove_vertex(self) -> None:
        if not self.busy and self._draft:
            self._draft.pop()
            self.canvas.redraw()

    def revert(self) -> None:
        if self.busy:
            return
        self._end_draft()
        if not self.tree.exists(self._selected):
            self._selected = "continent:" + self.world.continents[0].id
        self._load_form()
        self._populate()
        self.status.set("Unapplied edit discarded.")
        self.canvas.redraw()

    def _end_draft(self) -> None:
        self._draft = None
        self._draft_id = None
        self._placing = False
        self._line_start = None
        self.canvas.configure(cursor="")

    def delete(self) -> None:
        if self.busy or self.form_dirty or self._draft is not None:
            self.status.set("Apply or revert the current edit before deleting.")
            return
        if self._selected.startswith("continent:"):
            self.status.set("Continent defaults cannot be deleted; choose Automatic instead.")
            return
        candidate = replace(
            self.recipe, provinces=tuple(p for p in self.recipe.provinces if p.id != self._selected)
        )
        self._next_selected = "continent:" + self.world.continents[0].id
        world = self.world
        self._work(
            "Checking coverage after deletion",
            lambda token: _Result(resolve_geology(world, candidate, token), "edit"),
        )

    # Landmarks

    def _landmark_age(self) -> float | None:
        text = self.landmark["age"].get().strip()
        try:
            return float(text) if text else None
        except ValueError as error:
            raise ValueError("Landmark age must be a number of million years, or blank.") from error

    def _landmark_values(self, kind_default: int) -> tuple[str, WonderKind, float | None]:
        kind = self._landmark_kind()
        name = self.landmark["name"].get().strip()
        if not name:
            names = {m.name for m in self.recipe.landmarks}
            label = WONDERS[kind].label
            name = next(
                f"{label} {n}" for n in range(kind_default, 1000) if f"{label} {n}" not in names
            )
        text = self.landmark["size"].get().strip()
        try:
            size = float(text) if text else None
        except ValueError as error:
            raise ValueError("Landmark size must be a number of km, or blank.") from error
        return name, kind, size

    def _apply_landmarks(
        self, landmarks: tuple[GeologyLandmark, ...], selected: str | None
    ) -> None:
        try:
            candidate = replace(self.recipe, landmarks=landmarks)
        except ValueError as error:
            self.status.set(str(error))
            return
        self._landmark_selected = selected
        self._next_selected = self._selected
        world = self.world
        self._work(
            "Checking landmarks",
            lambda token: _Result(resolve_geology(world, candidate, token), "edit"),
        )

    def place_landmark(self) -> None:
        if self.busy or self.form_dirty or self._draft is not None:
            self.status.set("Apply or revert the current edit before placing a landmark.")
            return
        self._placing = True
        self._line_start = None
        self.canvas.configure(cursor="crosshair")
        self.canvas.focus_set()
        spec = WONDERS[self._landmark_kind()]
        self.status.set(
            f"Click one end of the {spec.label.lower()} on the map." if spec.line
            else f"Click the map to place the {spec.label.lower()}."
        )

    def _place_at(self, position: Point2D) -> None:
        spec = WONDERS[self._landmark_kind()]
        if spec.line and self._line_start is None:
            self._line_start = position
            self.status.set(f"Click the other end of the {spec.label.lower()}.")
            self.canvas.redraw()
            return
        start, self._line_start = self._line_start, None
        self._placing = False
        self.canvas.configure(cursor="")
        try:
            name, kind, size = self._landmark_values(len(self.recipe.landmarks) + 1)
            landmark = GeologyLandmark(
                "landmark-" + uuid4().hex, name, kind,
                position if start is None else start, size,
                None if start is None else position, self._landmark_age(),
            )
        except ValueError as error:
            self.status.set(str(error))
            return
        self.landmark["name"].set("")
        self._apply_landmarks((*self.recipe.landmarks, landmark), landmark.id)

    def update_landmark(self) -> None:
        current = next(
            (m for m in self.recipe.landmarks if m.id == self._landmark_selected), None
        )
        if self.busy or current is None:
            self.status.set("Select a landmark to update.")
            return
        try:
            name, kind, size = self._landmark_values(1)
            updated = GeologyLandmark(
                current.id, name, kind, current.position, size,
                current.end if WONDERS[kind].line else None, self._landmark_age(),
            )
        except ValueError as error:
            self.status.set(str(error))
            return
        self._apply_landmarks(
            tuple(updated if m.id == current.id else m for m in self.recipe.landmarks), current.id
        )

    def delete_landmark(self) -> None:
        if self.busy or self._landmark_selected is None:
            self.status.set("Select a landmark to delete.")
            return
        self._apply_landmarks(
            tuple(m for m in self.recipe.landmarks if m.id != self._landmark_selected), None
        )

    def _history(self, undo: bool) -> None:
        source, target = (self._undo, self._redo) if undo else (self._redo, self._undo)
        if self.busy or self.form_dirty or self._draft is not None:
            self.status.set("Apply or revert the current edit before using history.")
            return
        if source and self.coverage:
            target.append(self.coverage)
            self.coverage = source.pop()
            self.recipe = self.coverage.recipe
            if not self._selected.startswith("continent:") and not any(
                p.id == self._selected for p in self.recipe.provinces
            ):
                self._selected = "continent:" + self.world.continents[0].id
            self._populate()
            self._load_form()
            self.status.set("Geology edit undone." if undo else "Geology edit restored.")
            self.canvas.redraw()
            self._changed()

    def undo(self) -> None:
        self._history(True)

    def redo(self) -> None:
        self._history(False)

    # The world it belongs to

    def follow(self, world: WorldMap) -> None:
        """Carry the recipe over to an edited version of its world (same source map)."""
        if self.busy:
            return
        try:
            candidate = follow_world(self.recipe, world.project)
        except ValueError as error:
            self.status.set(f"Geology cannot follow the edited world: {error}")
            return

        def work(token: CancellationToken) -> _Result:
            return _Result(resolve_geology(world, candidate, token), "follow")

        def failed(error: Exception) -> None:
            self.status.set(
                f"Geology no longer fits the edited world: {error} Undo the world edit, or "
                "remove geology to continue without it."
            )

        self._end_draft()
        self.jobs.start(
            "Moving geology to the edited world",
            lambda _report, token: work(token),
            lambda result: self._followed(world, result),
            failed=failed, cancelled=self._job_cancelled,
        )

    def _followed(self, world: WorldMap, result: _Result) -> None:
        self.world = world
        self._undo.clear()
        self._redo.clear()
        known = {"continent:" + c.id for c in world.continents}
        if self._selected.startswith("continent:") and self._selected not in known:
            self._selected = "continent:" + world.continents[0].id
        self._finished(result, None)
        frame = world.project.frame
        self.canvas.show(self._render, (frame.width, frame.height))

    # Jobs

    def _work(
        self,
        label: str,
        action: Callable[[CancellationToken], _Result],
        after: Callable[[], None] | None = None,
        *,
        cancellable: bool = True,
    ) -> None:
        def work(_report: Report, token: CancellationToken) -> _Result:
            return action(token)

        self.jobs.start(label, work, lambda result: self._finished(result, after),
                        cancellable=cancellable, failed=self._job_failed,
                        cancelled=self._job_cancelled)

    def set_busy(self, busy: bool) -> None:
        self.landform_form.set_busy(busy)
        for widget, normal in self._controls:
            widget["state"] = "disabled" if busy else normal
        self._lock_identity_fields()

    def _job_failed(self, error: Exception) -> None:
        self.status.set(str(error))

    def _job_cancelled(self) -> None:
        self.status.set("Cancelled; previous geology retained.")

    def _finished(self, event: _Result, after: Callable[[], None] | None) -> None:
        if event.mode == "edit" and self.coverage and event.coverage.recipe != self.recipe:
            self._undo.append(self.coverage)
            self._undo = self._undo[-20:]
            self._redo.clear()
        self.coverage, self.recipe = event.coverage, event.coverage.recipe
        if event.mode in ("open", "save"):
            self.file = event.file
            self._saved_recipe = self.recipe
        if event.mode == "open":
            self._undo.clear()
            self._redo.clear()
            self._next_selected = "continent:" + self.world.continents[0].id
        if event.mode in ("edit", "open"):
            self._selected = self._next_selected
        self._end_draft()
        self._populate()
        self._load_form()
        self._show_file()
        self.status.set(
            f"Geology: {len(self.recipe.provinces)} provinces cover "
            f"{sum(r.area_km2 for r in self.coverage.regions):,.0f} km² of land. "
            + (
                f"Saved {self.file.path.name}."
                if event.mode == "save" and self.file
                else "Opened " + self.file.path.name + "."
                if event.mode == "open" and self.file
                else "Moved to the edited world; save the recipe to keep it."
                if event.mode == "follow"
                else "Every continent starts as Automatic: choose its setting, or draw "
                "provinces."
                if event.mode == "initial"
                else "Applied."
            )
        )
        self.inspection.set(HINT)
        self.canvas.redraw()
        self._changed()
        if after:
            after()

    def _changed(self) -> None:
        self._show_file()
        self.on_change()

    def _show_file(self) -> None:
        if self.file is None:
            self.file_label.set("Recipe not saved yet. Save it to reuse it in another session.")
        else:
            self.file_label.set(
                f"Recipe: {self.file.path.name}"
                + (" · unsaved changes" if self.dirty else " · saved")
            )

    def cancel(self) -> None:
        self.jobs.cancel()

    # Files

    def choose_open(self) -> None:
        def choose() -> None:
            path = filedialog.askopenfilename(
                parent=self,
                title="Open a geology recipe",
                filetypes=[("Geology recipe", "*.dmgeology.json")],
            )
            if path:
                self.load(Path(path))

        self.guard(choose)

    def load(self, path: Path) -> None:
        world = self.world

        def operation(token: CancellationToken) -> _Result:
            result = open_geology(path, world, token)
            return _Result(result.coverage, "open", result)

        self._work("Opening and checking the geology recipe", operation)

    def save(self, *, save_as: bool = False, after: Callable[[], None] | None = None) -> None:
        if self.busy:
            return
        if self.form_dirty or self._draft is not None:
            self.apply(lambda: self.save(save_as=save_as, after=after))
            return
        if self.coverage is None:
            return
        path = self.file.path if self.file else None
        expected = self.file.sha256 if self.file else None
        if path is None or save_as:
            name = filedialog.asksaveasfilename(
                parent=self,
                title="Save the geology recipe",
                defaultextension=GEOLOGY_EXTENSION,
                initialfile=path.name if path else "world.dmgeology.json",
                filetypes=[("Geology recipe", "*.dmgeology.json")],
            )
            if not name:
                return
            path = Path(name)
            try:
                # Same path must keep the loaded fingerprint, even through Save As.
                if self.file is None or path.resolve() != self.file.path.resolve():
                    expected = geology_file_hash(path)
            except (OSError, ValueError) as error:
                self.status.set(str(error))
                return
        coverage, target = self.coverage, path

        def operation(_token: CancellationToken) -> _Result:
            result = save_geology(coverage, target, expected)
            return _Result(result.coverage, "save", result)

        self._work(
            "Validating and saving the geology recipe", operation, after, cancellable=False
        )

    def guard(self, action: Callable[[], None]) -> None:
        if self.busy:
            self.status.set("Finish or cancel the current job before continuing.")
            return
        if not self.dirty:
            action()
            return
        answer = messagebox.askyesnocancel(
            "Save the geology recipe?",
            "Save the geology recipe before continuing? Unfinished or invalid provinces must "
            "be fixed or cancelled before saving.",
            parent=self,
        )
        if answer is True:
            self.save(after=action)
        elif answer is False:
            action()

    # Map

    def fit(self) -> None:
        self.canvas.fit()

    def _source_point(self, point: tuple[float, float]) -> Point2D:
        frame = self.world.project.frame
        return (frame.bounds[0] + point[0] * frame.width,
                frame.bounds[1] + point[1] * frame.height)

    def _click(self, point: tuple[float, float], _event: tk.Event[tk.Misc]) -> None:
        if self.busy:
            return
        position = self._source_point(point)
        if self._placing:
            self._place_at(position)
            return
        if self._draft is not None:
            if len(self._draft) >= MAX_PROVINCE_VERTICES:
                self.status.set(f"A province has at most {MAX_PROVINCE_VERTICES} corners.")
                return
            if self._draft:
                width = self.world.project.frame.width
                position = (
                    position[0] + round((self._draft[-1][0] - position[0]) / width) * width,
                    position[1],
                )
            self._draft.append(position)
            self.status.set(
                f"{len(self._draft)} corners · Enter or Apply changes finishes. "
                "Backspace removes the last corner; Escape cancels."
            )
            self.canvas.draw_overlay()
        elif self.coverage and not self.form_dirty:
            region = self.coverage.at(position)
            if region:
                self.tree.selection_set(region.id)

    def _hover(self, point: tuple[float, float] | None) -> None:
        if point is None or self.coverage is None:
            self.inspection.set(DRAW_HINT if self._draft is not None else HINT)
            return
        position = self._source_point(point)
        region = self.coverage.at(position)
        longitude, latitude = self.world.project.frame.source_to_lonlat(position)
        if region is None:
            text = "Water · geology applies to land"
        else:
            p = region.profile
            ages = " · ".join(
                f"{label} {value:g} Ma" if value is not None else f"{label} unknown"
                for label, value in (
                    ("crust", p.crust_age_ma),
                    ("uplift", p.rejuvenation_age_ma),
                )
            )
            text = f"{region.name} · {SETTING_TEXT[p.setting][0]} · {ages}"
        self.inspection.set(f"{latitude:.2f}°, {longitude:.2f}° · {text}")

    def _render(self, viewport: MapViewport, size: tuple[int, int]) -> Image.Image:
        project = self.world.project
        if self.layer.get() == COVERAGE and self.coverage:
            return render_geology(self.coverage, viewport, size)
        if self.context and self.layer.get() in CONTEXT_LAYERS:
            return render_world_context(
                self.context.context, viewport, size, cast(ContextLayer, self.layer.get()),
                EXPOSURE_BEARINGS.index(self.bearing.get()),
            )
        return render_world_source(
            project.source, project.frame.bounds, project.assignments, viewport, size,
            show_excluded=False,
        )

    def _overlay(self, canvas: FlatMapCanvas, rect: Rect) -> None:
        frame = self.world.project.frame
        left, top, right, bottom = rect
        sx, sy = (right - left) / frame.width, (bottom - top) / frame.height

        def at(x: float, y: float) -> tuple[float, float]:
            return left + (x - frame.bounds[0]) * sx, top + (y - frame.bounds[1]) * sy

        outlines = [(p.vertices, p.name, p.id == self._selected) for p in self.recipe.provinces]
        if self._draft:
            outlines.append((tuple(self._draft), "Draft", True))
        for vertices, name, selected in outlines:
            if len(vertices) == 1:
                x, y = at(*vertices[0])
                canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=MAP_HIGHLIGHT, outline=OCEAN)
                continue
            for offset in (-frame.width, 0.0, frame.width):
                points = [at(x + offset, y) for x, y in vertices]
                canvas.create_line(
                    *(v for point in (*points, points[0]) for v in point),
                    fill=MAP_HIGHLIGHT if selected else MAP_TEXT,
                    width=3 if selected else 1,
                    dash=(5, 3),
                )
                x, y = points[0]
                if left <= x <= right and top <= y <= bottom:
                    canvas.create_text(x + 5, y - 9, text=name, fill=MAP_HIGHLIGHT, anchor="sw")
        if self.coverage and self._selected.startswith("continent:"):
            selected_region = next(
                (r for r in self.coverage.regions if r.id == self._selected), None
            )
            if selected_region:
                for component in selected_region.components:
                    for ring in (component.exterior, *component.holes):
                        canvas.create_line(
                            *(v for x, y in ring for v in at(x, y)),
                            fill=MAP_HIGHLIGHT,
                            width=2,
                        )
        # Landmarks to scale: volcanoes as cones, a tepui as a block, other
        # round wonders as rings, a chasm as a broad line and a cliff as an
        # escarpment symbol, across the seam where that is shorter.
        px_per_km = (right - left) / (2 * math.pi * frame.radius_km)
        for m in self.recipe.landmarks:
            x, y = at(*m.position)
            r = max(5.0, m.effective_size_km / 2 * px_per_km)
            colour = MAP_HIGHLIGHT if m.id == self._landmark_selected else MAP_TEXT
            if m.end is not None:
                ex, ey = at(
                    m.end[0] + round((m.position[0] - m.end[0]) / frame.width) * frame.width,
                    m.end[1],
                )
                if m.kind == "cliff":
                    self._draw_scarp(canvas, (x, y), (ex, ey), colour)
                    r = 5.0
                else:
                    canvas.create_line(
                        x, y, ex, ey, fill=colour, width=max(3.0, 2 * r), capstyle="round",
                        stipple="gray50",
                    )
                    canvas.create_line(x, y, ex, ey, fill=colour, width=2)
                # Label a line wonder beyond its right-hand end, clear of the line.
                x, y = max((x, y), (ex, ey))
            elif m.kind in ("titan", "shattered", "active"):
                # Volcanoes: a cone, dashed where it blew apart, with a vent if erupting.
                canvas.create_polygon(
                    x, y - r, x - r, y + r * 0.7, x + r, y + r * 0.7,
                    outline=colour, fill="", width=2,
                    dash=(4, 3) if m.kind == "shattered" else (),
                )
                if m.kind == "active":
                    canvas.create_oval(x - 3, y - r - 3, x + 3, y - r + 3, fill=colour, outline="")
            elif m.kind == "oasis":
                canvas.create_oval(x - r, y - r, x + r, y + r, outline=colour, width=2)
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=colour, outline="")
            elif m.kind == "fork":
                # A river dividing in two.
                r = 7.0
                canvas.create_line(x, y + r, x, y, fill=colour, width=3)
                canvas.create_line(x, y, x - r, y - r, fill=colour, width=3)
                canvas.create_line(x, y, x + r, y - r, fill=colour, width=3)
            elif m.kind == "tepui":
                canvas.create_rectangle(x - r, y - 0.7 * r, x + r, y + 0.7 * r, outline=colour,
                                        width=2)
            else:
                canvas.create_oval(x - r, y - r, x + r, y + r, outline=colour, width=2)
            canvas.create_text(x + r + 4, y, text=m.name, fill=colour, anchor="w")
        if self._line_start is not None:
            x, y = at(*self._line_start)
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

    @staticmethod
    def _draw_scarp(
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

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.map.destroy()
        self.destroy()
