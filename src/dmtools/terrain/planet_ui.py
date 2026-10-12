"""World-tab Planet stage: whole-planet relief, climate and lakes (experimental)."""

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from uuid import uuid4

import numpy as np

from dmtools.terrain.adapters.map_views import THEMES
from dmtools.terrain.application.planet import PlanetRun
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.domain.wonders import AGE_PRESETS, WONDER_KINDS, WONDERS
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.ui_components import WrappingLabel, section
from dmtools.terrain.ui_style import GAP

DETAIL_PRESETS = {
    "Quick · 50,000 nodes (~100 km)": 50_000,
    "Standard · 200,000 nodes (~50 km)": 200_000,
    "Detailed · 800,000 nodes (~25 km)": 800_000,
    # Resolves Earth-scale ranges and valleys; about 4 minutes on a desktop.
    "Fine · 3,200,000 nodes (~12 km)": 3_200_000,
}
DEFAULT_PRESET = "Standard · 200,000 nodes (~50 km)"


def mean_land(result: PlanetResult, values: np.ndarray[tuple[int], np.dtype[np.float64]]) -> float:
    weights = result.mesh.area_m2[result.land]
    return float((values[result.land] * weights).sum() / weights.sum())


class PlanetPanel(ttk.Frame):
    """Planet stage: generation settings, Generate and Export, and a result summary.

    The maps themselves, globe and polar views and regional zoom live in the map
    view, so this page only makes and keeps planets.
    """

    def __init__(
        self,
        parent: tk.Misc,
        generate: Callable[[PlanetSettings, Path | None], None],
        export: Callable[[Path], None],
    ) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=12)
        self._generate = generate
        self._export = export
        self.run: PlanetRun | None = None
        self.detail_preset = tk.StringVar(self, value=DEFAULT_PRESET)
        self.climate = tk.BooleanVar(self, value=True)
        self.islands = tk.BooleanVar(self, value=False)
        self.wonders = {kind: tk.BooleanVar(self, value=False) for kind in WONDER_KINDS}
        self.wonder_age = tk.StringVar(self, value=next(iter(AGE_PRESETS)))
        self.seed = tk.StringVar(self, value=str(PlanetSettings().seed))
        self.geology_path: Path | None = None
        self.geology_label = tk.StringVar(self, value="Automatic ranges · no geology recipe")
        self.detail = tk.StringVar(
            self,
            value="Generate relief for the whole planet. Your coastline stays exactly as drawn; "
            "uplift and river erosion shape everything inland.",
        )
        ttk.Label(self, text="Whole planet (experimental)", style="Section.TLabel").pack(
            anchor="w"
        )
        mesh = section(self, "Detail")
        self.preset_input = ttk.Combobox(
            mesh, textvariable=self.detail_preset, values=tuple(DETAIL_PRESETS), state="readonly"
        )
        self.preset_input.pack(fill="x")
        seed_row = ttk.Frame(mesh, style="Panel.TFrame")
        seed_row.pack(fill="x", pady=(GAP, 0))
        ttk.Label(seed_row, text="Seed", style="Body.TLabel").pack(side="left")
        self.seed_input = ttk.Entry(seed_row, textvariable=self.seed, width=14)
        self.seed_input.pack(side="left", padx=GAP)
        features = section(self, "Features")
        self.climate_input = ttk.Checkbutton(
            features, text="Climate, lakes and biomes", variable=self.climate
        )
        self.climate_input.pack(anchor="w")
        self.islands_input = ttk.Checkbutton(
            features, text="Volcanic islands (adds land beyond your coastline)",
            variable=self.islands,
        )
        self.islands_input.pack(anchor="w", pady=(GAP // 2, 0))
        wonders = section(self, "Wonders")
        WrappingLabel(
            wonders,
            text="Fantastical landmarks beyond Earth's extremes, placed at random. "
            "Landmarks in the geology recipe place them by hand.",
            style="Muted.TLabel",
        ).pack(fill="x")
        grid = ttk.Frame(wonders, style="Panel.TFrame")
        grid.pack(fill="x", pady=(GAP // 2, 0))
        self.wonder_inputs: list[ttk.Checkbutton] = []
        for index, kind in enumerate(WONDER_KINDS):
            check = ttk.Checkbutton(grid, text=WONDERS[kind].label, variable=self.wonders[kind])
            check.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, GAP))
            self.wonder_inputs.append(check)
        age_row = ttk.Frame(wonders, style="Panel.TFrame")
        age_row.pack(fill="x", pady=(GAP // 2, 0))
        ttk.Label(age_row, text="Age", style="Body.TLabel").pack(side="left")
        self.wonder_age_input = ttk.Combobox(
            age_row, textvariable=self.wonder_age, values=tuple(AGE_PRESETS), state="readonly",
            width=20,
        )
        self.wonder_age_input.pack(side="left", padx=GAP)
        geology = section(self, "Geology")
        WrappingLabel(geology, textvariable=self.geology_label, style="Body.TLabel").pack(
            fill="x"
        )
        geology_row = ttk.Frame(geology, style="Panel.TFrame")
        geology_row.pack(fill="x", pady=(GAP // 2, 0))
        self.geology_button = ttk.Button(
            geology_row, text="Choose recipe…", style="Quiet.TButton", command=self.choose_geology
        )
        self.geology_button.pack(side="left")
        self.clear_geology_button = ttk.Button(
            geology_row, text="Clear", style="Quiet.TButton",
            command=lambda: self.set_geology(None),
        )
        self.clear_geology_button.pack(side="left", padx=GAP)
        actions = ttk.Frame(self, style="Panel.TFrame")
        actions.pack(fill="x", pady=(2 * GAP, 0))
        self.generate_button = ttk.Button(
            actions, text="Generate planet", style="Accent.TButton", command=self.request_generate
        )
        self.generate_button.pack(fill="x")
        self.export_button = ttk.Button(
            actions, text="Export planet build…", style="Quiet.TButton",
            command=self.choose_export, state="disabled",
        )
        self.export_button.pack(fill="x", pady=(GAP, 0))
        ttk.Separator(self).pack(fill="x", pady=2 * GAP)
        WrappingLabel(self, textvariable=self.detail, style="Muted.TLabel").pack(fill="x")
        self.set_busy(False)

    def settings(self) -> PlanetSettings:
        try:
            seed = int(self.seed.get().strip())
        except ValueError as error:
            raise ValueError("Seed must be a whole number from 0 to 4,294,967,295.") from error
        return PlanetSettings(
            seed=seed,
            nodes=DETAIL_PRESETS[self.detail_preset.get()],
            climate_passes=1 if self.climate.get() else 0,
            volcanic_islands=bool(self.islands.get()),
            wonders=tuple(kind for kind in WONDER_KINDS if self.wonders[kind].get()),
            wonder_age_myr=AGE_PRESETS[self.wonder_age.get()],
        )

    def request_generate(self) -> None:
        try:
            settings = self.settings()
        except ValueError as error:
            self.detail.set(str(error))
            return
        self._generate(settings, self.geology_path)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.preset_input.configure(state="disabled" if busy else "readonly")
        self.wonder_age_input.configure(state="disabled" if busy else "readonly")
        for widget in (self.climate_input, self.islands_input, *self.wonder_inputs,
                       self.seed_input, self.geology_button, self.generate_button):
            widget.configure(state=state)
        self.clear_geology_button.configure(
            state="normal" if self.geology_path is not None and not busy else "disabled"
        )
        self.export_button.configure(
            state="normal" if self.run is not None and not busy else "disabled"
        )

    def set_geology(self, path: Path | None) -> None:
        self.geology_path = path
        self.geology_label.set(
            f"Recipe: {path.name}" if path else "Automatic ranges · no geology recipe"
        )
        self.set_busy(False)

    def choose_geology(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self, title="Choose the geology recipe for this world",
            filetypes=[("World geology recipe", "*.dmgeology.json")],
        )
        if selected:
            self.set_geology(Path(selected))

    def choose_export(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self, title="Create a new planet build folder",
            initialfile="planet-" + uuid4().hex[:8],
        )
        if selected:
            self._export(Path(selected))

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
            f"{result.mesh.size:,} nodes · {result.mesh.spacing_m / 1000:,.0f} km spacing",
            f"Land: mean {hypsometry['mean']:,.0f} m · highest {hypsometry['max']:,.0f} m",
            f"Lakes: {len(lakes.level_m)} ({int(lakes.endorheic.sum())} closed basins)",
        ]
        if result.climate is not None:
            rain = mean_land(result, result.climate.precipitation_mm)
            lines.append(f"Mean land rainfall {rain:,.0f} mm/yr (provisional climate)")
        if result.calibration:
            final = [r for r in result.calibration[-1] if r.target_m is not None and r.measured_m]
            if final:
                worst = max(abs(r.measured_m - r.target_m) / r.target_m for r in final
                            if r.measured_m is not None and r.target_m is not None)
                lines.append(f"Geology targets met within {worst:.0%}")
        shown = sum(theme.label in run.previews for theme in THEMES)
        lines.append(
            f"{shown} of {len(THEMES)} maps ready. Choose Planet above the map, then a map "
            "and a projection; Zoom to region builds regional detail. Export writes the "
            "GeoTIFF, rivers, lakes and the mesh archive."
        )
        self.detail.set("\n".join(lines))
        self.set_busy(False)
