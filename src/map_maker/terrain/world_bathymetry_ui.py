# pyright: reportUnknownMemberType=false
"""Ocean-floor scenarios over immutable geography; all edits require generation."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast

import numpy as np
from PIL import Image

from map_maker.terrain.adapters.world_bathymetry_inputs import (
    BATHYMETRY_EXTENSION,
    bathymetry_file_hash,
)
from map_maker.terrain.adapters.world_bathymetry_render import (
    BATHYMETRY_LAYERS,
    BathymetryLayer,
    render_bathymetry,
)
from map_maker.terrain.adapters.world_context_render import render_world_context
from map_maker.terrain.adapters.world_render import OCEAN
from map_maker.terrain.application.world_bathymetry import (
    BathymetryFile,
    BathymetryRun,
    export_bathymetry,
    generate_bathymetry,
    match_context,
    open_bathymetry,
    open_bathymetry_inputs,
    save_bathymetry_inputs,
)
from map_maker.terrain.application.world_context import WorldContextRun
from map_maker.terrain.domain.world_bathymetry import BathymetryInputs, BathymetrySettings
from map_maker.terrain.map_canvas import FlatMapCanvas, Rect
from map_maker.terrain.pipeline.control import CancellationToken
from map_maker.terrain.ui_components import MapInfoStrip, StatusBar, WrappingLabel
from map_maker.terrain.ui_jobs import JobRunner, JobState, Report, TkPump
from map_maker.terrain.ui_style import GAP, PAPER
from map_maker.terrain.viewport import MapViewport
from map_maker.terrain.world_view import map_label

CONNECTED = "Connected water"
HINT = "Drag to pan · wheel to zoom · F fits the map"
STALE = "PREVIOUS RESULT · Generate to apply the edited inputs"


class BathymetryEditor(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        context: WorldContextRun,
        *,
        on_close: Callable[[BathymetryFile | None], None] | None = None,
        saved: BathymetryFile | None = None,
    ) -> None:
        super().__init__(parent)
        self.configure(background=PAPER)
        self.context = context
        self.run: BathymetryRun | None = None
        self.file: BathymetryFile | None = None
        self.on_close = on_close
        self._closed = False
        self._loading = True
        self._was_busy = False
        self._controls: list[tuple[ttk.Widget, str]] = []
        self._built_signature: object = None
        self._saved_signature: object = None
        self._frozen_selection: tuple[str, ...] = ()
        self.pump = TkPump(self)
        self.jobs = JobRunner(self.pump, self._job_state, self._job_failed, self._job_cancelled)
        settings = BathymetrySettings(latitude_cells=context.context.grid.shape[0])
        self.values = {
            key: tk.StringVar(self, value=str(getattr(settings, key)))
            for key in (
                "latitude_cells",
                "shelf_width_km",
                "shelf_depth_m",
                "slope_width_km",
                "basin_depth_m",
            )
        }
        self.layer = tk.StringVar(self, value=CONNECTED)
        self.status = tk.StringVar(
            self,
            value="Largest water region is suggested. "
            "Review ocean membership and the illustrative parameters before generating.",
        )
        self.summary = tk.StringVar(
            self, value="No bathymetry generated. Unselected water has no depth."
        )
        self.inspection = tk.StringVar(self, value=HINT)
        self.legend = tk.StringVar(self)
        self.title("Bathymetry inputs — " + context.context.world.project.name)
        self.geometry("1320x850")
        self.minsize(1050, 760)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", lambda: self.guard(self.close))
        self._build()
        for body in context.context.water_bodies:
            self.tree.insert(
                "",
                "end",
                iid=str(body.id),
                text=f"Water {body.id}",
                values=(f"{body.area_km2:,.0f}" if body.area_km2 >= 1 else "<1",),
            )
        if context.context.water_bodies:
            self.tree.selection_set(str(context.context.water_bodies[0].id))
        for value in self.values.values():
            value.trace_add("write", self._changed)
        self._saved_signature = self._signature()
        self._loading = False
        self.bind("<Control-s>", lambda _e: self._key(self.save))
        self.bind("<Control-Shift-S>", lambda _e: self._key(lambda: self.save(save_as=True)))
        self.canvas.bind("f", lambda _e: self._key(self.fit))
        self.grab_set()
        if saved is not None:
            self.load_inputs(saved.path)

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
    def dirty(self) -> bool:
        return self._signature() != self._saved_signature

    @property
    def current(self) -> bool:
        return self.run is not None and self._signature() == self._built_signature

    def _signature(self) -> object:
        return tuple(v.get() for v in self.values.values()), tuple(sorted(self.tree.selection()))

    def _button(
        self, parent: tk.Misc, text: str, action: Callable[[], None], *, style: str = "Quiet"
    ) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=action, style=f"{style}.TButton")
        self._controls.append((button, "normal"))
        return button

    # Layout

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        head = ttk.Frame(self, style="Paper.TFrame", padding=(14, 10))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="Ocean-floor hypotheses", style="Header.TLabel").pack(side="left")
        for text, action in (
            ("Open inputs…", self.choose_inputs),
            ("Save inputs", self.save),
            ("Save As…", lambda: self.save(save_as=True)),
            ("Open result…", self.choose_result),
        ):
            self._button(head, text, action).pack(side="left", padx=(GAP, 0))
        main = ttk.Frame(self, style="Paper.TFrame", padding=(14, 0))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)
        self._build_sidebar(main)
        right = ttk.Frame(main, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(right, style="Toolbar.TFrame", padding=GAP)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Fit", style="Small.TButton", command=self.fit).pack(side="left")
        choice = ttk.Combobox(
            toolbar, textvariable=self.layer, values=(CONNECTED, *BATHYMETRY_LAYERS),
            state="readonly", width=23,
        )
        choice.pack(side="left", padx=GAP)
        choice.bind("<<ComboboxSelected>>", lambda _e: self.canvas.redraw())
        frame = self.context.context.grid.frame
        self.canvas = FlatMapCanvas(right, background=OCEAN, on_hover=self._hover)
        self.canvas.configure(takefocus=True)
        self.canvas.overlay = self._overlay
        self.canvas.show(self._render, (frame.width, frame.height))
        self.canvas.grid(row=1, column=0, sticky="nsew")
        MapInfoStrip(right, self.legend, self.inspection).grid(row=2, column=0, sticky="ew")
        footer = ttk.Frame(self, style="Paper.TFrame", padding=(14, GAP))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status_bar = StatusBar(footer, self.status, self.cancel)
        self.status_bar.grid(row=0, column=0, sticky="ew")

    def _build_sidebar(self, main: ttk.Frame) -> None:
        side = ttk.Frame(main, style="Panel.TFrame", padding=10)
        side.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        side.columnconfigure(0, weight=1)
        side.rowconfigure(1, weight=1)
        ttk.Label(side, text="Oceans (Ctrl/Shift for several)", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        tree_frame = ttk.Frame(side, style="Panel.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=("area",), selectmode="extended", height=8)
        self.tree.heading("#0", text="Connected water")
        self.tree.heading("area", text="Area (km²)")
        self.tree.column("#0", width=135)
        self.tree.column("area", width=160, anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew")

        def scroll_tree(*args: str) -> None:
            self.tree.yview(*args)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=scroll_tree)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        form = ttk.Frame(side, style="Panel.TFrame")
        form.grid(row=2, column=0, sticky="ew", pady=10)
        form.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate(
            (
                ("latitude_cells", "Latitude rows (4-360)"),
                ("shelf_width_km", "Shelf width (km)"),
                ("shelf_depth_m", "Shelf-break depth (m)"),
                ("slope_width_km", "Slope width (km)"),
                ("basin_depth_m", "Basin depth (m)"),
            )
        ):
            ttk.Label(form, text=label, style="Body.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, GAP), pady=3
            )
            entry = ttk.Entry(form, textvariable=self.values[key], width=15)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self._controls.append((entry, "normal"))
        self._button(side, "Generate ocean floor", self.generate, style="Accent").grid(
            row=3, column=0, sticky="ew"
        )
        self._button(side, "Export result…", self.export).grid(row=4, column=0, sticky="ew",
                                                               pady=6)
        WrappingLabel(
            side,
            text="One editable margin profile for the selected waters. "
            "These values are hypotheses, not inferred age or measured depth. "
            "Mixed-layer depth and water transport are separate future models.",
            style="Muted.TLabel",
        ).grid(row=5, column=0, sticky="ew", pady=GAP)
        WrappingLabel(side, textvariable=self.summary, style="Body.TLabel").grid(
            row=6, column=0, sticky="ew", pady=GAP
        )

    # Inputs

    def _selected(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self.busy:
            if self.tree.selection() != self._frozen_selection:
                self.tree.selection_set(self._frozen_selection)
            return
        self._changed()

    def _changed(self, *_args: str) -> None:
        if self._loading:
            return
        self.title(
            ("* " if self.dirty else "")
            + "Bathymetry inputs — "
            + self.context.context.world.project.name
        )
        if self.run and not self.current:
            self.status.set(
                "Inputs changed. The previous result is stale; generate to apply changes."
            )
        self.canvas.redraw()

    def inputs(self) -> BathymetryInputs:
        return BathymetryInputs(
            self.context.context.world.project,
            tuple(sorted(int(i) for i in self.tree.selection())),
            BathymetrySettings(
                int(self.values["latitude_cells"].get()),
                *(
                    float(self.values[key].get())
                    for key in (
                        "shelf_width_km",
                        "shelf_depth_m",
                        "slope_width_km",
                        "basin_depth_m",
                    )
                ),
            ),
        )

    def _apply_inputs(self, inputs: BathymetryInputs) -> None:
        inputs = match_context(inputs, self.context)
        self._loading = True
        for key, value in self.values.items():
            value.set(str(getattr(inputs.settings, key)))
        self.tree.selection_set(tuple(map(str, inputs.ocean_ids)))
        self._loading = False
        self._changed()

    # Jobs

    def _work[T](
        self,
        label: str,
        work: Callable[[Report, CancellationToken], T],
        done: Callable[[T], None],
        after: Callable[[], None] | None = None,
        *,
        cancellable: bool = True,
    ) -> None:
        if self.busy:
            return
        self._frozen_selection = self.tree.selection()

        def finished(value: T) -> None:
            done(value)
            self._changed()
            if after:
                after()

        self.jobs.start(label, work, finished, cancellable=cancellable)

    def _job_state(self, state: JobState | None) -> None:
        self.status_bar.show(state)
        busy = state is not None
        if busy != self._was_busy:
            self._was_busy = busy
            for control, normal in self._controls:
                control["state"] = "disabled" if busy else normal

    def _job_failed(self, error: Exception) -> None:
        self.status.set(str(error))

    def _job_cancelled(self) -> None:
        self.status.set("Cancelled; previous result and inputs retained.")

    def _show_run(self, run: BathymetryRun, *, opened: bool) -> None:
        self.context = WorldContextRun(run.result.context, run.runtime)
        if opened:
            self._apply_inputs(run.result.inputs)
            self.file = None
            self._saved_signature = self._signature()
        self.run = run
        self._built_signature = self._signature()
        self.layer.set("Ocean floor")
        missing = run.result.unsampled_ocean_ids
        self.summary.set(
            f"{run.result.sampled_cells:,} ocean samples · "
            f"{run.result.context.grid.shape[1]} x "
            f"{run.result.context.grid.shape[0]} cells. "
            f"{run.result.context.mixed_cells:,} mixed coast cells remain approximate. "
            + (
                "No centre samples in selected waters: " + ", ".join(map(str, missing)) + ". "
                if missing
                else ""
            )
            + "Cell-centre elevations are not cell-average depth or transport capacity."
        )
        self.status.set(
            "Ocean-floor hypothesis ready. Coastline unchanged; "
            "numerical error does not measure geological uncertainty."
        )

    def _show_file(self, file: BathymetryFile, *, opened: bool) -> None:
        if opened:
            self._apply_inputs(file.inputs)
        self.file = file
        self._saved_signature = self._signature()
        self.status.set(
            f"Inputs {'opened' if opened else 'saved'}: {file.path.name}. Generate to apply them."
        )

    def generate(self) -> None:
        if self.busy:
            return
        try:
            inputs = self.inputs()
        except ValueError as error:
            self.status.set(str(error))
            return
        context = self.context
        self._work(
            "Preparing the ocean-depth scenario",
            lambda report, token: generate_bathymetry(
                inputs, context, report, cancellation=token
            ),
            lambda run: self._show_run(run, opened=False),
        )

    def save(self, *, save_as: bool = False, after: Callable[[], None] | None = None) -> None:
        if self.busy:
            return
        try:
            inputs = self.inputs()
            path, digest = (self.file.path, self.file.sha256) if self.file else (None, None)
            if path is None or save_as:
                selected = filedialog.asksaveasfilename(
                    parent=self,
                    title="Save bathymetry inputs",
                    defaultextension=BATHYMETRY_EXTENSION,
                    initialfile=path.name if path else "world.bathy.json",
                    filetypes=[("Bathymetry inputs", "*.bathy.json")],
                )
                if not selected:
                    return
                path = Path(selected)
                if self.file is None or path.resolve() != self.file.path.resolve():
                    digest = bathymetry_file_hash(path)
        except (ValueError, OSError) as error:
            self.status.set(str(error))
            return
        target, context = path, self.context
        self._work(
            "Saving portable inputs",
            lambda _report, _token: save_bathymetry_inputs(inputs, context, target, digest),
            lambda file: self._show_file(file, opened=False),
            after,
            cancellable=False,
        )

    def load_inputs(self, path: Path) -> None:
        context = self.context
        self._work(
            "Opening bathymetry inputs",
            lambda _report, token: open_bathymetry_inputs(path, context, cancellation=token),
            lambda file: self._show_file(file, opened=True),
        )

    def choose_inputs(self) -> None:
        def choose() -> None:
            selected = filedialog.askopenfilename(
                parent=self,
                title="Open bathymetry inputs",
                filetypes=[("Bathymetry inputs", "*.bathy.json")],
            )
            if selected:
                self.load_inputs(Path(selected))

        self.guard(choose)

    def load_result(self, path: Path) -> None:
        context = self.context

        def operation(_report: Report, token: CancellationToken) -> BathymetryRun:
            result = open_bathymetry(path, cancellation=token)
            match_context(result.result.inputs, context)
            return result

        self._work(
            "Verifying bathymetry and its geographic dependency", operation,
            lambda run: self._show_run(run, opened=True),
        )

    def choose_result(self) -> None:
        def choose() -> None:
            selected = filedialog.askopenfilename(
                parent=self,
                title="Open completed bathymetry",
                filetypes=[("Bathymetry result", "bathymetry.json")],
            )
            if selected:
                self.load_result(Path(selected))

        self.guard(choose)

    def export(self) -> None:
        if self.busy:
            return
        if self.run is None or not self.current:
            self.status.set("Generate from the current inputs before exporting.")
            return
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="New bathymetry output folder",
            initialfile="world-bathymetry",
            confirmoverwrite=False,
        )
        if not selected:
            return
        run, target = self.run, Path(selected)
        self._work(
            "Exporting a new result with its geographic source",
            lambda _report, token: export_bathymetry(run, target, cancellation=token),
            lambda path: self.status.set(f"Exported completed bathymetry: {path}"),
        )

    def cancel(self) -> None:
        self.jobs.cancel()

    def guard(self, action: Callable[[], None]) -> None:
        if self.busy:
            self.status.set("Finish or cancel the current job before continuing.")
            self.lift()
            return
        if not self.dirty:
            action()
            return
        answer = messagebox.askyesnocancel(
            "Save bathymetry inputs?", "Save these inputs before continuing?", parent=self
        )
        if answer is True:
            self.save(after=action)
        elif answer is False:
            action()

    # Map

    def fit(self) -> None:
        self.canvas.fit()

    def _render(self, viewport: MapViewport, size: tuple[int, int]) -> Image.Image:
        if self.run is not None and self.layer.get() in BATHYMETRY_LAYERS:
            depth = self.run.result.inputs.settings.basin_depth_m
            if self.layer.get() == "Ocean floor":
                legend = f"Light: 0 m · dark blue: -{depth:g} m. Green: land. "
            elif self.layer.get() == "Distance error":
                legend = f"Dark: 0 m · orange: {depth:g} m numerical bound. "
            else:
                legend = "Orange: mixed/split or subcell geography. "
            self.legend.set(legend + "Grey: unselected water. Zoom does not add samples.")
            return render_bathymetry(
                self.run.result, viewport, size, cast(BathymetryLayer, self.layer.get())
            )
        self.legend.set(
            "Colours distinguish connected water regions. Hover shows the "
            "dominant cell ID; mixed cells may contain other waters."
        )
        return render_world_context(self.context.context, viewport, size, CONNECTED)

    def _overlay(self, canvas: FlatMapCanvas, _rect: Rect) -> None:
        if self.run is not None and not self.current:
            map_label(canvas, 12, 12, STALE)

    def _hover(self, point: tuple[float, float] | None) -> None:
        if point is None:
            self.inspection.set(HINT)
            return
        grid = self.context.context.grid
        rows, columns = grid.shape
        row = min(rows - 1, int(point[1] * rows))
        column = min(columns - 1, int(point[0] * columns))
        if self.run and self.layer.get() != CONNECTED:
            result = self.run.result
            body = int(result.centre_water_body[row, column])
            bed = float(result.bed_elevation_m[row, column])
            text = (
                f"Water {body} · bed {bed:,.2f} m · numerical bound "
                f"{result.distance_depth_error_m[row, column]:.2f} m"
                if np.isfinite(bed)
                else f"{'Land' if body == 0 else f'Water {body}'} · no depth"
            )
        else:
            text = f"Dominant water ID: {self.context.context.water_body[row, column]}"
        flags = int(self.context.context.support_flags[row, column])
        self.inspection.set(
            f"{grid.latitude_deg(row):.2f}°, {grid.longitude_deg(column):.2f}° · "
            f"{text} · geographic support flags {flags}"
        )

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
