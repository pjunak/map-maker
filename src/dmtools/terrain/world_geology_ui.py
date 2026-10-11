# pyright: reportUnknownMemberType=false
"""Pre-generation geology authoring over a retained world and read-only context."""

from __future__ import annotations

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
from dmtools.terrain.domain.world_context import EXPOSURE_BEARINGS
from dmtools.terrain.domain.world_geology import (
    GEOLOGICAL_SETTINGS,
    MAX_PROVINCE_VERTICES,
    ContinentGeology,
    GeologicalSetting,
    GeologyProfile,
    GeologyProvince,
    WorldGeologyRecipe,
    blank_geology,
)
from dmtools.terrain.map_canvas import FlatMapCanvas, Rect
from dmtools.terrain.pipeline.control import CancellationToken
from dmtools.terrain.pipeline.world import WorldMap
from dmtools.terrain.pipeline.world_geology import GeologyCoverage, resolve_geology
from dmtools.terrain.ui_components import MapInfoStrip, StatusBar, WrappingLabel
from dmtools.terrain.ui_jobs import JobRunner, JobState, Report, TkPump
from dmtools.terrain.ui_style import GAP, MAP_FRAME, MAP_HIGHLIGHT, MAP_TEXT, PAPER
from dmtools.terrain.viewport import MapViewport
from dmtools.terrain.world_landform_ui import WorldLandformForm
from dmtools.terrain.world_view import CONTEXT_LEGENDS

COVERAGE = "Geology coverage"
SOURCE = "Source"
LEGENDS = {
    COVERAGE: "Colours show each region's geological setting (key in the sidebar). Dashed "
    "outlines are provinces; the selected one is bold.",
    SOURCE: "Your source geography, for placing provinces.",
    **CONTEXT_LEGENDS,
}
HINT = "Drag to pan · wheel to zoom · F fits · click a region to select it"
DRAW_HINT = "Click to add vertices · Enter finishes · Backspace removes · Escape cancels"


@dataclass(frozen=True)
class _Result:
    coverage: GeologyCoverage
    mode: Literal["initial", "edit", "open", "save"]
    file: GeologyFile | None = None


class GeologyEditor(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        world: WorldMap,
        context: WorldContextRun | None = None,
        *,
        on_close: Callable[[GeologyFile | None], None] | None = None,
        saved: GeologyFile | None = None,
    ) -> None:
        super().__init__(parent)
        self.configure(background=PAPER)
        self.world = world
        self.context = context
        self.on_close = on_close
        self.file = saved
        self.recipe = saved.coverage.recipe if saved else blank_geology(world.project)
        self.coverage: GeologyCoverage | None = saved.coverage if saved else None
        self._saved_recipe = self.recipe
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
        self._was_busy = False
        self.pump = TkPump(self)
        self.jobs = JobRunner(self.pump, self._job_state, self._job_failed, self._job_cancelled)
        self.values = {
            key: tk.StringVar(self)
            for key in ("name", "priority", "setting", "crust", "rejuvenation", "duration")
        }
        self.layer = tk.StringVar(self, value=COVERAGE)
        self.bearing = tk.StringVar(self, value="N")
        self.status = tk.StringVar(self, value="Select a continent default or draw a province.")
        self.detail = tk.StringVar(self)
        self.legend = tk.StringVar(self, value=LEGENDS[COVERAGE])
        self.inspection = tk.StringVar(self, value=HINT)
        self.title("Geology inputs — " + world.project.name)
        self.geometry("1320x850")
        self.minsize(1050, 740)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", lambda: self.guard(self.close))
        self._build()
        self._populate()
        self._load_form()
        self.bind("<Control-s>", lambda _e: self._key(self.save))
        self.bind("<Control-Shift-S>", lambda _e: self._key(lambda: self.save(save_as=True)))
        self.bind("<Control-o>", lambda _e: self._key(self.choose_open))
        self.canvas.bind("<Return>", lambda _e: self._key(self.apply))
        self.canvas.bind("<Escape>", lambda _e: self._key(self.revert))
        self.canvas.bind("<BackSpace>", lambda _e: self._key(self.remove_vertex))
        self.canvas.bind("f", lambda _e: self._key(self.fit))
        self.grab_set()
        if saved is not None:
            self.load(saved.path)
        else:
            recipe = self.recipe
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
    def dirty(self) -> bool:
        return self.recipe != self._saved_recipe or self.form_dirty or self._draft is not None

    def _button(
        self, parent: tk.Misc, text: str, command: Callable[[], None], *, style: str = "Quiet"
    ) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, style=f"{style}.TButton")
        self._controls.append((button, "normal"))
        return button

    # Layout

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        head = ttk.Frame(self, style="Paper.TFrame", padding=(14, 10))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="Geology inputs", style="Header.TLabel").pack(side="left")
        for text, command in (
            ("Open recipe…", self.choose_open),
            ("Save", self.save),
            ("Save As…", lambda: self.save(save_as=True)),
            ("Undo", self.undo),
            ("Redo", self.redo),
        ):
            self._button(head, text, command).pack(side="left", padx=(GAP, 0))
        main = ttk.Frame(self, style="Paper.TFrame", padding=(14, 0))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)
        self._build_sidebar(main)
        self._build_map(main)
        foot = ttk.Frame(self, style="Paper.TFrame", padding=(14, GAP))
        foot.grid(row=2, column=0, sticky="ew")
        foot.columnconfigure(0, weight=1)
        ttk.Label(
            foot,
            text="Save this recipe, then choose it in the Planet or Terrain stage. Geological "
            "ages remain hypotheses; climate and aging are not applied.",
            style="Eyebrow.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.status_bar = StatusBar(foot, self.status, self.cancel)
        self.status_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))

    def _build_sidebar(self, main: ttk.Frame) -> None:
        side = ttk.Frame(main, style="Panel.TFrame", padding=10, width=340)
        side.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        side.columnconfigure(0, weight=1)
        side.rowconfigure(1, weight=1)
        ttk.Label(side, text="Continent defaults and provinces", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        tree_frame = ttk.Frame(side, style="Panel.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse", height=7)
        self.tree.column("#0", width=300)
        self.tree.grid(row=0, column=0, sticky="nsew")

        def scroll_tree(*args: str) -> None:
            self.tree.yview(*args)

        bar = ttk.Scrollbar(tree_frame, orient="vertical", command=scroll_tree)
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind("<<TreeviewSelect>>", self._selection)
        tools = ttk.Frame(side, style="Panel.TFrame")
        tools.grid(row=2, column=0, sticky="ew", pady=GAP)
        for text, action in (
            ("Draw province", self.start_drawing),
            ("Redraw", lambda: self.start_drawing(redraw=True)),
            ("Delete", self.delete),
        ):
            self._button(tools, text, action).pack(side="left", padx=(0, 4))
        self.form_tabs = ttk.Notebook(side)
        self.form_tabs.grid(row=3, column=0, sticky="ew")
        form = ttk.Frame(self.form_tabs, style="Panel.TFrame", padding=6)
        self.form_tabs.add(form, text="Geological history")
        self.landform_form = WorldLandformForm(self.form_tabs)
        self.form_tabs.add(self.landform_form, text="Landform guidance")
        form.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate(
            (
                ("name", "Name"),
                ("priority", "Priority (0-100)"),
                ("setting", "Setting"),
                ("crust", "Crust age (Ma)"),
                ("rejuvenation", "Rejuvenation (Ma)"),
                ("duration", "Simulation span (Ma)"),
            )
        ):
            ttk.Label(form, text=label, style="Body.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, GAP), pady=3
            )
            widget = (
                ttk.Combobox(
                    form, textvariable=self.values[key], values=GEOLOGICAL_SETTINGS, width=19,
                    state="readonly",
                )
                if key == "setting"
                else ttk.Entry(form, textvariable=self.values[key], width=21)
            )
            widget.grid(row=row, column=1, sticky="ew", pady=3)
            self._field_widgets[key] = widget
            self._controls.append((widget, "readonly" if key == "setting" else "normal"))
        actions = ttk.Frame(side, style="Panel.TFrame")
        actions.grid(row=4, column=0, sticky="ew", pady=GAP)
        actions.columnconfigure((0, 1), weight=1)
        self._button(actions, "Apply / finish polygon", self.apply, style="Accent").grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        self._button(actions, "Revert / cancel", self.revert).grid(
            row=0, column=1, sticky="ew", padx=(3, 0)
        )
        WrappingLabel(
            side,
            text="Ma = million years. Ages are before one common present. "
            "Simulation span is a duration. Blank = unknown. "
            "A province replaces the entire default, including blanks.",
            style="Muted.TLabel",
        ).grid(row=5, column=0, sticky="ew", pady=(0, GAP))
        WrappingLabel(side, textvariable=self.detail, style="Body.TLabel").grid(
            row=6, column=0, sticky="ew", pady=(0, GAP)
        )
        key = ttk.Frame(side, style="Panel.TFrame")
        key.grid(row=7, column=0, sticky="ew")
        for row, (setting, colour) in enumerate(SETTING_COLOURS.items()):
            tk.Label(key, background=colour, width=2).grid(
                row=row // 2, column=row % 2 * 2, padx=(0, 5), pady=1
            )
            ttk.Label(key, text=setting, style="Body.TLabel").grid(
                row=row // 2, column=row % 2 * 2 + 1, sticky="w", padx=(0, 7)
            )

    def _build_map(self, main: ttk.Frame) -> None:
        right = ttk.Frame(main, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        view_tools = ttk.Frame(right, style="Toolbar.TFrame", padding=GAP)
        view_tools.grid(row=0, column=0, sticky="ew")
        ttk.Button(view_tools, text="Fit", style="Small.TButton", command=self.fit).pack(
            side="left"
        )
        layers = (COVERAGE, SOURCE, *(CONTEXT_LAYERS if self.context else ()))
        selector = ttk.Combobox(
            view_tools, textvariable=self.layer, values=layers, state="readonly", width=24
        )
        selector.pack(side="left", padx=GAP)
        selector.bind("<<ComboboxSelected>>", lambda _e: self._layer_changed())
        if self.context:
            ttk.Label(view_tools, text="Look", style="Body.TLabel").pack(side="left")
            bearing = ttk.Combobox(
                view_tools, textvariable=self.bearing, values=EXPOSURE_BEARINGS,
                state="readonly", width=4,
            )
            bearing.pack(side="left", padx=4)
            bearing.bind("<<ComboboxSelected>>", lambda _e: self.canvas.redraw())
        frame = self.world.project.frame
        self.canvas = FlatMapCanvas(
            right, background=OCEAN, on_click=self._click, on_hover=self._hover
        )
        self.canvas.configure(takefocus=True)
        self.canvas.overlay = self._overlay
        self.canvas.show(self._render, (frame.width, frame.height))
        self.canvas.grid(row=1, column=0, sticky="nsew")
        MapInfoStrip(right, self.legend, self.inspection).grid(row=2, column=0, sticky="ew")

    def _layer_changed(self) -> None:
        self.legend.set(LEGENDS.get(self.layer.get(), ""))
        self.canvas.redraw()

    # Form and selection

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
        if self.tree.exists(self._selected):
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
        self._loaded_form = self._form()
        self._lock_identity_fields()
        region = (
            next((r for r in self.coverage.regions if r.id == self._selected), None)
            if self.coverage
            else None
        )
        self.detail.set(
            f"Effective land: {region.area_km2:,.0f} km². "
            + ("Province override." if region.province else "Remaining default coverage.")
            if region
            else "Draw a polygon with at least three vertices."
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
        if selection[0] in ("defaults", "provinces"):
            return
        self._selected = selection[0]
        self._load_form()
        self.canvas.redraw()

    def _profile(self) -> GeologyProfile:
        values = [self.values[key].get().strip() for key in ("crust", "rejuvenation", "duration")]
        return GeologyProfile(
            cast(GeologicalSetting, self.values["setting"].get()),
            *(float(value) if value else None for value in values),
            landform=self.landform_form.read(),
        )

    def _candidate(self) -> WorldGeologyRecipe:
        profile = self._profile()
        if self._draft is not None or not self._selected.startswith("continent:"):
            current = next((p for p in self.recipe.provinces if p.id == self._selected), None)
            province = GeologyProvince(
                self._draft_id or self._selected,
                self.values["name"].get().strip(),
                tuple(self._draft)
                if self._draft is not None
                else current.vertices
                if current
                else (),
                int(self.values["priority"].get()),
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
                "Rename continents in the World workspace; priorities apply to provinces."
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
            self.status.set("Select a province to redraw its boundary.")
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
            "Click polygon vertices. Enter: finish · Backspace: remove vertex · "
            "Escape: cancel. Seam crossings follow the shorter longitude interval."
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
        self.canvas.configure(cursor="")

    def delete(self) -> None:
        if self.busy or self.form_dirty or self._draft is not None:
            self.status.set("Apply or revert the current edit before deleting.")
            return
        if self._selected.startswith("continent:"):
            self.status.set("Continent defaults cannot be deleted; use unspecified / blank values.")
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
            self.status.set("Edit undone." if undo else "Edit restored.")
            self.canvas.redraw()

    def undo(self) -> None:
        self._history(True)

    def redo(self) -> None:
        self._history(False)

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
                        cancellable=cancellable)

    def _job_state(self, state: JobState | None) -> None:
        self.status_bar.show(state)
        busy = state is not None
        if busy == self._was_busy:
            return
        self._was_busy = busy
        self.landform_form.set_busy(busy)
        for widget, normal in self._controls:
            widget["state"] = "disabled" if busy else normal
        self._lock_identity_fields()

    def _job_failed(self, error: Exception) -> None:
        self.status.set(str(error))

    def _job_cancelled(self) -> None:
        self.status.set("Cancelled; previous recipe retained.")

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
        self.status.set(
            f"{len(self.recipe.provinces)} provinces · "
            f"{sum(r.area_km2 for r in self.coverage.regions):,.0f} km² land covered. "
            + (
                f"Saved {self.file.path.name}."
                if event.mode == "save" and self.file
                else "Coverage verified. Inputs remain geological hypotheses."
            )
        )
        self.inspection.set(HINT)
        self.canvas.redraw()
        if after:
            after()

    def cancel(self) -> None:
        self.jobs.cancel()

    # Files

    def choose_open(self) -> None:
        def choose() -> None:
            path = filedialog.askopenfilename(
                parent=self,
                title="Open geology inputs",
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

        self._work("Opening and checking retained geology inputs", operation)

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
                title="Save geology inputs",
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
            "Validating and saving portable geology recipe", operation, after, cancellable=False
        )

    def guard(self, action: Callable[[], None]) -> None:
        if self.busy:
            self.status.set("Finish or cancel the current job before continuing.")
            self.lift()
            return
        if not self.dirty:
            action()
            return
        answer = messagebox.askyesnocancel(
            "Save geology inputs?",
            "Save the recipe before continuing? Unfinished or invalid polygons must be fixed "
            "or cancelled before saving.",
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
        if self._draft is not None:
            if len(self._draft) >= MAX_PROVINCE_VERTICES:
                self.status.set(f"Province vertex limit: {MAX_PROVINCE_VERTICES}.")
                return
            if self._draft:
                width = self.world.project.frame.width
                position = (
                    position[0] + round((self._draft[-1][0] - position[0]) / width) * width,
                    position[1],
                )
            self._draft.append(position)
            self.status.set(
                f"{len(self._draft)} vertices · Enter or Apply to finish. "
                "Backspace removes the last vertex; Escape cancels."
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
            text = "Water · land geology does not apply"
        else:
            p = region.profile
            ages = " · ".join(
                f"{label}: {value:g} Ma" if value is not None else f"{label}: unknown"
                for label, value in (
                    ("crust", p.crust_age_ma),
                    ("rejuvenation", p.rejuvenation_age_ma),
                    ("simulation", p.evolution_duration_ma),
                )
            )
            text = f"{region.name} · {p.setting} · {ages}"
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
        self.jobs.close()
        self.pump.close()
        self.grab_release()
        if self.on_close:
            self.on_close(self.file)
        self.destroy()
