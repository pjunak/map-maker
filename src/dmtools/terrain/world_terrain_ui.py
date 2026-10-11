"""World-to-terrain controls, separate from source editing and projection."""

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk

from dmtools.terrain.application.world_terrain import WorldTerrainCreated
from dmtools.terrain.domain.world import WorldContinent


class WorldTerrainPanel(ttk.Frame):
    def __init__(
        self, parent: tk.Misc, create: Callable[[str, Path, Path | None], None],
        open_project: Callable[[WorldTerrainCreated], None],
    ) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=12)
        self._create = create
        self._open = open_project
        self._continents: tuple[WorldContinent, ...] = ()
        self.created: WorldTerrainCreated | None = None
        self.continent = tk.StringVar(self)
        self.geology_path: Path | None = None
        self.geology_label = tk.StringVar(self, value="Background terrain · no geology recipe")
        self.detail = tk.StringVar(self, value="Choose a continent from the imported world.")
        ttk.Label(self, text="Generate terrain from your world", style="Value.TLabel",
                  wraplength=340).pack(anchor="w", pady=(0, 12))
        ttk.Label(self, text="Continent", style="Body.TLabel").pack(anchor="w")
        self.selection = ttk.Combobox(self, textvariable=self.continent, state="readonly")
        self.selection.pack(fill="x", pady=(4, 12))
        ttk.Label(
            self, text="Creates a terrain project at the world's physical scale. "
            "The continent's islands and any connected neighbouring land are included "
            "to keep land borders from becoming coastlines.",
            style="Body.TLabel", wraplength=340,
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(
            self, text="Start at 257 pixels, then adjust terrain settings and generate in "
            "the Terrain workspace. Generate or open context first to include "
            "spherical coastal support. Climate and aging are not applied yet.",
            style="Muted.TLabel", wraplength=340,
        ).pack(anchor="w", pady=(0, 16))
        ttk.Label(self, textvariable=self.geology_label, wraplength=340,
                  style="Body.TLabel").pack(anchor="w", pady=(0, 4))
        geology_buttons = ttk.Frame(self, style="Panel.TFrame")
        geology_buttons.pack(fill="x", pady=(0, 12))
        self.geology_button = ttk.Button(
            geology_buttons, text="Choose geology recipe…", command=self.choose_geology,
        )
        self.geology_button.pack(side="left")
        self.clear_geology_button = ttk.Button(
            geology_buttons, text="Clear", command=lambda: self.set_geology(None),
        )
        self.clear_geology_button.pack(side="left", padx=6)
        self.create_button = ttk.Button(self, text="Create terrain project…",
                                       style="Accent.TButton", command=self.choose_folder)
        self.create_button.pack(fill="x")
        ttk.Separator(self).pack(fill="x", pady=12)
        ttk.Label(self, textvariable=self.detail, wraplength=340,
                  style="Muted.TLabel").pack(anchor="w")
        self.open_button = ttk.Button(self, text="Open prepared project",
                                      command=self.open_created, state="disabled",
                                      style="Quiet.TButton")
        self.open_button.pack(fill="x", pady=12)
        self.set_busy(False)

    def set_continents(self, continents: tuple[WorldContinent, ...]) -> None:
        self._continents = tuple(sorted(continents, key=lambda c: c.name.casefold()))
        names = tuple(c.name for c in self._continents)
        self.selection.configure(values=names)
        if self.continent.get() not in names:
            self.continent.set(names[0] if names else "")
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self.selection.configure(state="disabled" if busy else "readonly")
        self.geology_button.configure(state="disabled" if busy else "normal")
        self.clear_geology_button.configure(
            state="normal" if self.geology_path is not None and not busy else "disabled",
        )
        self.create_button.configure(state="normal" if self._continents and not busy
                                     else "disabled")
        self.open_button.configure(state="normal" if self.created and not busy else "disabled")

    def set_geology(self, path: Path | None) -> None:
        self.geology_path = path
        self.geology_label.set(
            f"Landform guidance: {path.name}\n{path.parent}" if path else
            "Background terrain · no geology recipe"
        )
        self.set_busy(False)

    def choose_geology(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self, title="Choose saved landform guidance for this world",
            filetypes=[("World geology recipe", "*.dmgeology.json")],
        )
        if selected:
            self.set_geology(Path(selected))

    def choose_folder(self) -> None:
        selected = next((c for c in self._continents if c.name == self.continent.get()), None)
        if selected is None:
            return
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in selected.name)
        folder = filedialog.asksaveasfilename(
            parent=self, title="Create a new terrain project folder",
            initialfile="terrain-" + slug,
        )
        if folder:
            self._create(selected.id, Path(folder), self.geology_path)

    def show_created(self, created: WorldTerrainCreated) -> None:
        self.created = created
        source = created.source
        names = ", ".join(c.name for c in source.world.continents
                          if c.id in source.included_continent_ids)
        stretch = source.projection.maximum_transverse_scale - 1
        self.detail.set(
            f"Prepared land: {names}\n"
            f"Longest projected extent: {source.object_scale_km:,.1f} km\n"
            f"Maximum sampled projection stretch: {stretch:.1%}\n\n"
            f"Landform regions: {len(created.loaded.project.constraints)}\n"
            + ("Context: coastal relief connected (experimental)\n"
               if created.loaded.project.world_context else "Context: not supplied\n")
            + f"Saved in: {created.loaded.path.parent}\n"
            "Keep coastline.svg with terrain.dmterrain.json when moving the project."
        )
        self.set_busy(False)

    def open_created(self) -> None:
        if self.created is not None:
            self._open(self.created)
