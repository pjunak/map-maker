"""The World tab's Local terrain tool: a continent as a local terrain project."""

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk

from map_maker.terrain.application.world_terrain import WorldTerrainCreated
from map_maker.terrain.domain.world import WorldContinent
from map_maker.terrain.ui_components import WrappingLabel, hint, page_title, section
from map_maker.terrain.ui_style import GAP


class WorldTerrainPanel(ttk.Frame):
    def __init__(
        self, parent: tk.Misc, create: Callable[[str, Path], None],
        open_project: Callable[[WorldTerrainCreated], None],
    ) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self._create = create
        self._open = open_project
        self._continents: tuple[WorldContinent, ...] = ()
        self.created: WorldTerrainCreated | None = None
        self.continent = tk.StringVar(self)
        self.geology_label = tk.StringVar(self)
        self.detail = tk.StringVar(self, value="No project prepared yet.")
        page_title(
            self, "Local terrain",
            "Turn one continent into a project for the Terrain tab, where you can paint "
            "heights, ridges, valleys and lakes by hand on a flat local map.",
        )
        choice = section(self, "Continent")
        self.selection = ttk.Combobox(choice, textvariable=self.continent, state="readonly")
        self.selection.pack(fill="x")
        hint(choice, "The project keeps the world's real scale. The continent's islands and any "
             "land joined to it come along, so land borders do not turn into coastlines.")
        guidance = section(self, "Landform guidance")
        WrappingLabel(guidance, textvariable=self.geology_label, style="Body.TLabel").pack(
            fill="x"
        )
        hint(guidance, "Exact landforms set in the Geology step become editable regions in "
             "the project. If geographic context is open, coastal relief follows it too.")
        self.create_button = ttk.Button(self, text="Create terrain project…",
                                        style="Accent.TButton", command=self.choose_folder)
        self.create_button.pack(fill="x", pady=(2 * GAP, 0))
        hint(self, "Choose a new, empty folder. The project opens in the Terrain tab, ready "
             "to generate at a quick 257 px; climate and aging are not applied there.")
        result = section(self, "Prepared project")
        WrappingLabel(result, textvariable=self.detail, style="Muted.TLabel").pack(fill="x")
        self.open_button = ttk.Button(result, text="Open it in the Terrain tab",
                                      command=self.open_created, state="disabled",
                                      style="Quiet.TButton")
        self.open_button.pack(fill="x", pady=(GAP, 0))
        self.set_geology(None)
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
        self.create_button.configure(state="normal" if self._continents and not busy
                                     else "disabled")
        self.open_button.configure(state="normal" if self.created and not busy else "disabled")

    def set_geology(self, summary: str | None) -> None:
        """Say which geology the project will take: ``None`` when there is none."""
        self.geology_label.set(
            "None: the Geology step has no recipe." if summary is None
            else f"From the Geology step: {summary}."
        )

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
            self._create(selected.id, Path(folder))

    def show_created(self, created: WorldTerrainCreated) -> None:
        self.created = created
        source = created.source
        names = ", ".join(c.name for c in source.world.continents
                          if c.id in source.included_continent_ids)
        stretch = source.projection.maximum_transverse_scale - 1
        self.detail.set(
            f"Land: {names}\n"
            f"Longest extent: {source.object_scale_km:,.1f} km\n"
            f"Largest map stretch: {stretch:.1%}\n"
            f"Landform regions: {len(created.loaded.project.constraints)}\n"
            + ("Coastal relief follows the geographic context (experimental)\n"
               if created.loaded.project.world_context else "No geographic context\n")
            + f"Folder: {created.loaded.path.parent}\n"
            "Keep coastline.svg with terrain.terrain.json when moving the project."
        )
        self.set_busy(False)

    def open_created(self) -> None:
        if self.created is not None:
            self._open(self.created)
