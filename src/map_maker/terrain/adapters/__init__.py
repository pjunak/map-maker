"""File-format and rendering adapters for terrain generation."""

from map_maker.terrain.adapters.project import (
    PROJECT_EXTENSION,
    LoadedTerrainProject,
    TerrainProjectInputError,
    load_terrain_project,
    save_terrain_project,
)
from map_maker.terrain.adapters.render import (
    RenderStyle,
    elevation_legend_colours,
    elevation_palette_rgb,
    render_height_map,
    save_height_map,
)
from map_maker.terrain.adapters.svg import (
    CoastlineInputError,
    CoastlineSource,
    load_svg_coastline,
    load_svg_coastline_source,
)

__all__ = [
    "PROJECT_EXTENSION",
    "CoastlineInputError",
    "CoastlineSource",
    "LoadedTerrainProject",
    "RenderStyle",
    "TerrainProjectInputError",
    "elevation_legend_colours",
    "elevation_palette_rgb",
    "load_svg_coastline",
    "load_svg_coastline_source",
    "load_terrain_project",
    "render_height_map",
    "save_height_map",
    "save_terrain_project",
]
