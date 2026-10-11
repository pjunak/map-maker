"""Registry of map themes: what each view shows and how it is labelled.

A theme is rendered once on the world frame (``<id>.png`` in a planet build)
and shown in any projection (``map_projection``). New views, such as political
or civilization maps, are added here with their renderer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MapTheme:
    id: str  # file stem in a planet build and the CLI name
    label: str  # name in the app's layer selector
    legend: str
    needs_climate: bool = False


THEMES: tuple[MapTheme, ...] = (
    MapTheme(
        "atlas", "Planet atlas",
        "Provisional biomes on shaded relief. Blue lines are rivers sized by discharge; "
        "blue lakes overflow, grey lakes are closed basins.",
        needs_climate=True,
    ),
    MapTheme(
        "relief", "Planet relief", "Elevation from uplift and river erosion; coast kept exactly."
    ),
    MapTheme(
        "koppen", "Planet climate zones",
        "Köppen-Geiger climate classes from the provisional seasonal climate.",
        needs_climate=True,
    ),
    MapTheme(
        "volcanoes", "Planet volcanoes",
        "The atlas with land volcanoes marked: red = active, dark = extinct.",
        needs_climate=True,
    ),
    MapTheme(
        "precipitation", "Planet rainfall",
        "Brown = dry; green = moderate; blue = 2,500+ mm/yr (provisional).",
        needs_climate=True,
    ),
    MapTheme(
        "temperature", "Planet temperature",
        "Annual mean: violet = -25 °C; cream ≈ 5 °C; red = 30 °C.",
        needs_climate=True,
    ),
    MapTheme(
        "topographic", "Planet topographic",
        "Atlas-style hypsometric tints with contour lines (interval set by the map scale, "
        "every fifth bold), isobaths, soft hillshade, rivers and lakes.",
    ),
    MapTheme(
        "parchment", "Planet parchment",
        "A hand-drawn fantasy map: inked coasts with ripple lines, mountain, hill, tree, "
        "marsh and dune symbols placed from the terrain and climate, rivers on old paper.",
        needs_climate=True,
    ),
    MapTheme(
        "plates", "Planet plates",
        "Tectonic plates in distinct colours. Boundaries: red = converging, blue = "
        "spreading, yellow = sliding past. Arrows show plate motion (8 cm/yr fills a cell).",
    ),
    MapTheme(
        "seafloor", "Planet sea-floor age",
        "Ocean crust age: red = new at spreading ridges, through yellow and green, to "
        "violet = 180+ million years. Fracture zones step the bands.",
    ),
    MapTheme(
        "basins", "Planet drainage basins",
        "Each river system to the sea in its own colour; the great basins (100,000+ km²) "
        "are stronger, with their divides drawn. Hatched grey = closed basins.",
    ),
    MapTheme(
        "geology", "Planet geology",
        "Provinces: pink = shield, orange = old fold belt, brown = active mountain belt, "
        "yellow = sedimentary basin, olive = rift, purple = flood basalt, red = volcanic.",
    ),
)
THEME_BY_ID = {theme.id: theme for theme in THEMES}
THEME_BY_LABEL = {theme.label: theme for theme in THEMES}
PREVIEW_LAYERS = tuple(theme.label for theme in THEMES)


def theme_file(theme: MapTheme) -> str:
    return f"{theme.id}.png"
