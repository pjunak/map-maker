"""World-tab Generate and Explore steps: make a whole planet, then look at and keep it."""

import random
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from uuid import uuid4

import numpy as np

from dmtools.terrain.adapters.map_views import THEMES
from dmtools.terrain.application.planet import PlanetRun
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.domain.seeds import MAX_MASTER_SEED
from dmtools.terrain.domain.wonders import AGE_PRESETS, WONDER_KINDS, WONDERS
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.ui_components import (
    ChoiceList,
    Collapsible,
    WrappingLabel,
    button_row,
    field,
    hint,
    page_title,
    section,
)
from dmtools.terrain.ui_style import GAP

# Mesh nodes for each detail choice: (label, nodes, explanation). Times are for the
# four-continent example on a desktop; climate adds to them.
DETAIL_PRESETS: tuple[tuple[str, int, str], ...] = (
    ("Quick", 50_000, "Points about 100 km apart · under a minute. For trying settings."),
    ("Standard", 200_000, "About 50 km · a minute or two. Shows the whole world well."),
    ("Detailed", 800_000, "About 25 km · a few minutes. Sharper ranges and valleys."),
    ("Fine", 3_200_000, "About 12 km · ten minutes or more. Earth-like ranges and valleys."),
)
DEFAULT_PRESET = "Standard"
NODES = {label: nodes for label, nodes, _ in DETAIL_PRESETS}


def mean_land(result: PlanetResult, values: np.ndarray[tuple[int], np.dtype[np.float64]]) -> float:
    weights = result.mesh.area_m2[result.land]
    return float((values[result.land] * weights).sum() / weights.sum())


class PlanetPanel(ttk.Frame):
    """The Generate step: what kind of planet to make, then Generate."""

    def __init__(
        self,
        parent: tk.Misc,
        generate: Callable[[PlanetSettings], None],
        edit_geology: Callable[[], None],
    ) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self._generate = generate
        self.detail_preset = tk.StringVar(self, value=DEFAULT_PRESET)
        self.climate = tk.BooleanVar(self, value=True)
        self.islands = tk.BooleanVar(self, value=False)
        self.wonders = {kind: tk.BooleanVar(self, value=False) for kind in WONDER_KINDS}
        self.wonder_age = tk.StringVar(self, value=next(iter(AGE_PRESETS)))
        self.seed = tk.StringVar(self, value=str(PlanetSettings().seed))
        self.geology_label = tk.StringVar(self)
        self.message = tk.StringVar(self)
        page_title(
            self, "Generate the planet",
            "Uplift and river erosion shape the whole planet; then climate brings rain, "
            "rivers, lakes and ice. Your coastline stays as you drew it.",
        )
        detail = section(self, "Detail")
        self.detail_input = ChoiceList(
            detail, self.detail_preset, [(label, label, text) for label, _, text in DETAIL_PRESETS]
        )
        self.detail_input.pack(fill="x")
        hint(detail, "Zoomed regional maps add finer detail at any setting.")
        variation = section(self, "Variation")
        self.seed_input = field(
            variation, "Seed", self.seed, width=14,
            help="The same seed and inputs always make the same planet. Another seed gives "
            "a different take on the same world.",
        )
        self.new_seed_button = ttk.Button(
            self.seed_input.master, text="New seed", style="Small.TButton", command=self.new_seed
        )
        self.new_seed_button.pack(side="left", padx=(GAP, 0))
        features = section(self, "Include")
        self.climate_input = ttk.Checkbutton(
            features, text="Climate, rivers, lakes and ice", variable=self.climate
        )
        self.climate_input.pack(anchor="w")
        hint(features, "Temperature, rainfall, biomes and ice sheets; the atlas, climate and "
             "parchment maps need them. Off is faster and gives relief only.")
        self.islands_input = ttk.Checkbutton(
            features, text="Volcanic islands", variable=self.islands,
        )
        self.islands_input.pack(anchor="w", pady=(GAP, 0))
        hint(features, "Young volcanoes at sea may rise as new islands: land you did not draw.")
        self.wonder_section = Collapsible(self, "Wonders")
        self.wonder_section.pack(fill="x", pady=(2 * GAP, 0))
        wonders = self.wonder_section.body
        hint(wonders, "Fantastical landmarks beyond Earth's extremes, placed at random. To "
             "place one exactly, add it as a landmark in the Geology step.")
        grid = ttk.Frame(wonders, style="Panel.TFrame")
        grid.pack(fill="x", pady=(GAP // 2, 0))
        self.wonder_inputs: list[ttk.Checkbutton] = []
        for index, kind in enumerate(WONDER_KINDS):
            check = ttk.Checkbutton(grid, text=WONDERS[kind].label, variable=self.wonders[kind],
                                    command=self._wonders_changed)
            check.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, GAP))
            self.wonder_inputs.append(check)
        age_row = button_row(wonders)
        ttk.Label(age_row, text="Age", style="Body.TLabel").pack(side="left")
        self.wonder_age_input = ttk.Combobox(
            age_row, textvariable=self.wonder_age, values=tuple(AGE_PRESETS), state="readonly",
            width=20,
        )
        self.wonder_age_input.pack(side="left", padx=GAP)
        hint(wonders, "How long erosion has worn them. Fresh wonders are sharp-edged.")
        self._wonders_changed()
        geology = section(self, "Geology")
        WrappingLabel(geology, textvariable=self.geology_label, style="Body.TLabel").pack(
            fill="x"
        )
        self.geology_button = ttk.Button(
            geology, text="Edit geology", style="Small.TButton", command=edit_geology
        )
        self.geology_button.pack(anchor="w", pady=(GAP // 2, 0))
        self.set_geology(None)
        self.generate_button = ttk.Button(
            self, text="Generate planet", style="Accent.TButton", command=self.request_generate
        )
        self.generate_button.pack(fill="x", pady=(2 * GAP, 0))
        hint(self, textvariable=self.message, style="Warning.TLabel")
        hint(self, "It runs in the background: the status bar shows progress and Cancel.")
        self.set_busy(False)

    def settings(self) -> PlanetSettings:
        try:
            seed = int(self.seed.get().strip())
        except ValueError as error:
            raise ValueError(
                f"Seed must be a whole number from 0 to {MAX_MASTER_SEED:,}."
            ) from error
        return PlanetSettings(
            seed=seed,
            nodes=NODES[self.detail_preset.get()],
            climate_passes=1 if self.climate.get() else 0,
            volcanic_islands=bool(self.islands.get()),
            wonders=tuple(kind for kind in WONDER_KINDS if self.wonders[kind].get()),
            wonder_age_myr=AGE_PRESETS[self.wonder_age.get()],
        )

    def summary(self) -> str:
        """One line for the step list."""
        return f"{self.detail_preset.get()} detail"

    def new_seed(self) -> None:
        self.seed.set(str(random.randint(0, MAX_MASTER_SEED)))

    def _wonders_changed(self) -> None:
        chosen = sum(variable.get() for variable in self.wonders.values())
        self.wonder_section.set_title(f"Wonders · {chosen} chosen" if chosen else
                                      "Wonders · none")

    def request_generate(self) -> None:
        try:
            settings = self.settings()
        except ValueError as error:
            self.message.set(str(error))
            return
        self.message.set("")
        self._generate(settings)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.detail_input.set_enabled(not busy)
        self.wonder_age_input.configure(state="disabled" if busy else "readonly")
        for widget in (self.climate_input, self.islands_input, *self.wonder_inputs,
                       self.seed_input, self.new_seed_button, self.geology_button,
                       self.generate_button):
            widget.configure(state=state)

    def set_geology(self, summary: str | None) -> None:
        """Say which geology generation will use: ``None`` for automatic ranges."""
        self.geology_label.set(
            "Automatic: mountain ranges are placed from the coastline." if summary is None
            else f"From the Geology step: {summary}."
        )


class PlanetResultPanel(ttk.Frame):
    """The Explore step: what the planet is, how to look around, and how to keep it."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        export: Callable[[Path], None],
        zoom: Callable[[], None],
        save_image: Callable[[], None],
        change_settings: Callable[[], None],
    ) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self._export = export
        self.run: PlanetRun | None = None
        self.detail = tk.StringVar(self, value="Generate a planet in the Generate step.")
        page_title(
            self, "Explore",
            "Look at the planet in different maps and projections, zoom into regions and "
            "keep what you like.",
        )
        facts = section(self, "This planet")
        card = ttk.Frame(facts, style="Card.TFrame", padding=GAP)
        card.pack(fill="x")
        WrappingLabel(card, textvariable=self.detail, style="Card.TLabel").pack(fill="x")
        self.outdated = tk.StringVar(self)
        self._outdated_label = hint(facts, textvariable=self.outdated, style="Warning.TLabel")
        self._outdated_label.pack_forget()
        look = section(self, "Look around")
        hint(look, "Above the map, Source · Context · Planet chooses what to show and the "
             "list beside it the map: atlas, relief, climate zones, topographic and more. "
             "Flat world, Globe and the polar views choose the projection. Hover the map "
             "to read height, rainfall and climate under the cursor.")
        zoom_box = section(self, "Zoom in")
        hint(zoom_box, "Pick a place to build a region with about 5 km detail. From there, a "
             "province adds 1 km detail and a local map 200 m. Zoomed maps are cached, so "
             "revisiting a place is quick and gives the same result.")
        self.zoom_button = ttk.Button(zoom_box, text="Pick a region on the map",
                                      style="Quiet.TButton", command=zoom)
        self.zoom_button.pack(anchor="w", pady=(GAP // 2, 0))
        keep = section(self, "Keep it")
        self.export_button = ttk.Button(
            keep, text="Export planet build…", style="Quiet.TButton",
            command=self.choose_export, state="disabled",
        )
        self.export_button.pack(fill="x")
        hint(keep, "A new folder with heights (GeoTIFF), rivers, lakes, map images and the "
             "mesh, plus a manifest naming the exact inputs and settings.")
        self.image_button = ttk.Button(
            keep, text="Save the shown map as an image…", style="Quiet.TButton",
            command=save_image,
        )
        self.image_button.pack(fill="x", pady=(GAP, 0))
        self.change_button = ttk.Button(
            self, text="← Change settings and generate again", style="Quiet.TButton",
            command=change_settings,
        )
        self.change_button.pack(fill="x", pady=(2 * GAP, 0))
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        ready = self.run is not None and not busy
        for button in (self.export_button, self.zoom_button, self.image_button):
            button.configure(state="normal" if ready else "disabled")
        self.change_button.configure(state="disabled" if busy else "normal")

    def choose_export(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self, title="Create a new planet build folder",
            initialfile="planet-" + uuid4().hex[:8],
        )
        if selected:
            self._export(Path(selected))

    def set_outdated(self, message: str | None) -> None:
        """Warn that an input changed after this planet was made, or clear the warning."""
        self.outdated.set(message or "")
        if message:
            self._outdated_label.pack(fill="x", pady=(GAP // 2, 0))
        else:
            self._outdated_label.pack_forget()

    def clear(self, message: str) -> None:
        self.run = None
        self.detail.set(message)
        self.set_busy(False)

    def show(self, run: PlanetRun) -> None:
        self.run = run
        result = run.result
        metrics = result.metrics
        hypsometry = metrics["hypsometry_m"]
        assert isinstance(hypsometry, dict)
        lakes = result.lakes
        lines = [
            f"{result.mesh.size:,} points about {result.mesh.spacing_m / 1000:,.0f} km apart",
            f"Land: mean height {hypsometry['mean']:,.0f} m · highest {hypsometry['max']:,.0f} m",
            f"Lakes: {len(lakes.level_m)}, of which {int(lakes.endorheic.sum())} have no outlet",
        ]
        if result.climate is not None:
            rain = mean_land(result, result.climate.precipitation_mm)
            lines.append(f"Mean rainfall on land: {rain:,.0f} mm a year (provisional climate)")
        if result.calibration:
            final = [r for r in result.calibration[-1] if r.target_m is not None and r.measured_m]
            if final:
                worst = max(abs(r.measured_m - r.target_m) / r.target_m for r in final
                            if r.measured_m is not None and r.target_m is not None)
                lines.append(f"Geology heights met within {worst:.0%}")
        shown = sum(theme.label in run.previews for theme in THEMES)
        if shown < len(THEMES):
            lines.append(f"{shown} of {len(THEMES)} maps: the others need climate.")
        self.detail.set("\n".join(lines))
        self.set_busy(False)
