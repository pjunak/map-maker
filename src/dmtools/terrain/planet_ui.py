"""World-tab Planet stage: whole-planet relief, climate and lakes (experimental)."""

import tkinter as tk
from collections.abc import Callable
from math import cos, radians, sin
from pathlib import Path
from tkinter import filedialog, ttk
from uuid import uuid4

import numpy as np
from scipy.spatial import KDTree  # pyright: ignore[reportMissingTypeStubs]

from dmtools.terrain.application.planet import PlanetRun
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.pipeline.planet_climate import BIOMES

DETAIL_PRESETS = {
    "Quick · 50,000 nodes (~100 km)": 50_000,
    "Standard · 200,000 nodes (~50 km)": 200_000,
    "Detailed · 800,000 nodes (~25 km)": 800_000,
}
DEFAULT_PRESET = "Standard · 200,000 nodes (~50 km)"


class PlanetProbe:
    """Nearest-node description of a planet result under the cursor."""

    def __init__(self, result: PlanetResult) -> None:
        self.result = result
        self.tree = KDTree(result.mesh.xyz)

    def describe(self, longitude_deg: float, latitude_deg: float) -> str:
        lon, lat = radians(longitude_deg), radians(latitude_deg)
        point = (cos(lat) * cos(lon), cos(lat) * sin(lon), sin(lat))
        node = int(self.tree.query(point)[1])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        result = self.result
        if not result.land[node]:
            return f"Sea · floor {result.elevation_m[node]:,.0f} m (display bathymetry)"
        lakes = result.lakes
        parts = [f"Ground {result.elevation_m[node]:,.0f} m"]
        lake = int(lakes.lake[node])
        if lake >= 0:
            kind = "closed lake" if lakes.endorheic[lake] else "lake"
            parts.append(f"{kind} surface {lakes.level_m[lake]:,.0f} m")
        flow = float(lakes.discharge_m3_s[node])
        if flow >= 1:
            parts.append(f"river {flow:,.0f} m³/s")
        climate = result.climate
        if climate is not None:
            parts.append(
                f"{climate.temperature_c[node]:.0f} °C · "
                f"{climate.precipitation_mm[node]:,.0f} mm/yr · "
                f"{BIOMES[int(climate.biome[node])]}"
            )
        return " · ".join(parts)


def mean_land(result: PlanetResult, values: np.ndarray[tuple[int], np.dtype[np.float64]]) -> float:
    weights = result.mesh.area_m2[result.land]
    return float((values[result.land] * weights).sum() / weights.sum())


class PlanetPanel(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        generate: Callable[[PlanetSettings, Path | None], None],
        export: Callable[[Path], None],
        cancel: Callable[[], None],
    ) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=12)
        self._generate = generate
        self._export = export
        self.run: PlanetRun | None = None
        self.detail_preset = tk.StringVar(self, value=DEFAULT_PRESET)
        self.climate = tk.BooleanVar(self, value=True)
        self.seed = tk.StringVar(self, value=str(PlanetSettings().seed))
        self.geology_path: Path | None = None
        self.geology_label = tk.StringVar(self, value="Automatic ranges · no geology recipe")
        self.detail = tk.StringVar(
            self,
            value="Generate relief for the whole planet. Your coastline stays exactly as drawn; "
            "uplift and river erosion shape everything inland.",
        )
        ttk.Label(self, text="Whole planet (experimental)", style="Value.TLabel").pack(
            anchor="w", pady=(0, 10)
        )
        ttk.Label(self, text="Detail", style="Body.TLabel").pack(anchor="w")
        self.preset_input = ttk.Combobox(
            self, textvariable=self.detail_preset, values=tuple(DETAIL_PRESETS), state="readonly"
        )
        self.preset_input.pack(fill="x", pady=(4, 8))
        self.climate_input = ttk.Checkbutton(
            self, text="Climate, lakes and biomes", variable=self.climate
        )
        self.climate_input.pack(anchor="w", pady=(0, 8))
        seed_row = ttk.Frame(self, style="Panel.TFrame")
        seed_row.pack(fill="x", pady=(0, 8))
        ttk.Label(seed_row, text="Seed", style="Body.TLabel").pack(side="left")
        self.seed_input = ttk.Entry(seed_row, textvariable=self.seed, width=14)
        self.seed_input.pack(side="left", padx=8)
        ttk.Label(self, textvariable=self.geology_label, style="Body.TLabel", wraplength=340).pack(
            anchor="w", pady=(4, 4)
        )
        geology_row = ttk.Frame(self, style="Panel.TFrame")
        geology_row.pack(fill="x", pady=(0, 12))
        self.geology_button = ttk.Button(
            geology_row, text="Choose geology recipe…", command=self.choose_geology
        )
        self.geology_button.pack(side="left")
        self.clear_geology_button = ttk.Button(
            geology_row, text="Clear", command=lambda: self.set_geology(None)
        )
        self.clear_geology_button.pack(side="left", padx=6)
        self.generate_button = ttk.Button(
            self, text="Generate planet", style="Accent.TButton", command=self.request_generate
        )
        self.generate_button.pack(fill="x")
        self.cancel_button = ttk.Button(
            self, text="Cancel planet job", style="Quiet.TButton", command=cancel,
            state="disabled",
        )
        self.cancel_button.pack(fill="x", pady=6)
        self.export_button = ttk.Button(
            self, text="Export planet…", style="Quiet.TButton", command=self.choose_export,
            state="disabled",
        )
        self.export_button.pack(fill="x")
        ttk.Separator(self).pack(fill="x", pady=12)
        ttk.Label(self, textvariable=self.detail, style="Muted.TLabel", wraplength=340).pack(
            anchor="w"
        )
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
        )

    def request_generate(self) -> None:
        try:
            settings = self.settings()
        except ValueError as error:
            self.detail.set(str(error))
            return
        self._generate(settings, self.geology_path)

    def set_busy(self, busy: bool, cancellable: bool = False) -> None:
        state = "disabled" if busy else "normal"
        self.preset_input.configure(state="disabled" if busy else "readonly")
        for widget in (self.climate_input, self.seed_input, self.geology_button,
                       self.generate_button):
            widget.configure(state=state)
        self.clear_geology_button.configure(
            state="normal" if self.geology_path is not None and not busy else "disabled"
        )
        self.cancel_button.configure(state="normal" if busy and cancellable else "disabled")
        self.export_button.configure(
            state="normal" if self.run is not None and not busy else "disabled"
        )

    def set_geology(self, path: Path | None) -> None:
        self.geology_path = path
        self.geology_label.set(
            f"Geology recipe: {path.name}" if path else "Automatic ranges · no geology recipe"
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
        lines.append("Choose a Planet layer above the map. Export writes the GeoTIFF, "
                     "rivers, lakes and the mesh archive.")
        self.detail.set("\n".join(lines))
        self.set_busy(False)
