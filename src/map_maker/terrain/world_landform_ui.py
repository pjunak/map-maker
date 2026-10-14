"""Explicit landform controls shared by every geological default or province."""

import tkinter as tk
from tkinter import ttk
from typing import cast

from map_maker.terrain.domain.models import LandformKind, LandformSettings, landform_preset

DEFAULT_TERRAIN = "Use background terrain"
_FIELDS = (
    ("elevation_m", "Base elevation (m)"),
    ("relief_m", "Relief (m)"),
    ("feature_size_km", "Feature size (km)"),
    ("transition_km", "Transition (km)"),
    ("orientation_deg", "Direction (0-180°)"),
)


class WorldLandformForm(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, padding=6)
        self.columnconfigure(1, weight=1)
        self.character = tk.StringVar(self, value=DEFAULT_TERRAIN)
        self.values = {key: tk.StringVar(self) for key, _ in _FIELDS}
        self._busy = False
        ttk.Label(self, text="Landform").grid(row=0, column=0, sticky="w")
        self.selection = ttk.Combobox(
            self, textvariable=self.character, state="readonly", width=23,
            values=(DEFAULT_TERRAIN, "plain", "hills", "plateau", "mountains"),
        )
        self.selection.grid(row=0, column=1, sticky="ew", pady=3)
        self.selection.bind("<<ComboboxSelected>>", lambda _e: self.set_busy(self._busy))
        self.entries: list[ttk.Entry] = []
        for row, (key, label) in enumerate(_FIELDS, 1):
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8))
            entry = ttk.Entry(self, textvariable=self.values[key], width=15)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self.entries.append(entry)
        self.preset_button = ttk.Button(self, text="Use starting values", command=self.preset)
        self.preset_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Label(
            self, text="Direction is in the local terrain plane: 0° east-west, "
            "90° north-south. Ages do not set these controls.", wraplength=310,
        ).grid(row=7, column=0, columnspan=2, sticky="ew")
        self.load(None)

    def snapshot(self) -> tuple[str, ...]:
        return (self.character.get(), *(v.get() for v in self.values.values()))

    def load(self, settings: LandformSettings | None) -> None:
        self.character.set(DEFAULT_TERRAIN if settings is None else settings.character)
        values = settings or LandformSettings()
        for key, value in self.values.items():
            value.set(str(getattr(values, key)))
        self.set_busy(self._busy)

    def read(self) -> LandformSettings | None:
        if self.character.get() == DEFAULT_TERRAIN:
            return None
        return LandformSettings(
            cast(LandformKind, self.character.get()),
            *(float(value.get()) for value in self.values.values()),
        )

    def preset(self) -> None:
        if not self._busy and self.character.get() != DEFAULT_TERRAIN:
            self.load(landform_preset(cast(LandformKind, self.character.get())))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.selection.configure(state="disabled" if busy else "readonly")
        state = "disabled" if busy or self.character.get() == DEFAULT_TERRAIN else "normal"
        for entry in self.entries:
            entry.configure(state=state)
        self.preset_button.configure(state=state)
