"""Map themes available for a regional detail window, rendered on request."""

from collections.abc import Callable

from PIL import Image

from dmtools.terrain.adapters.map_views import THEME_BY_ID, MapTheme
from dmtools.terrain.adapters.planet_region import RegionWindow, window_image, window_topographic

_RENDERERS: dict[str, Callable[[RegionWindow], Image.Image]] = {
    "atlas": lambda window: window_image(window, atlas=True),
    "relief": lambda window: window_image(window, atlas=False),
    "topographic": window_topographic,
}


def region_themes(window: RegionWindow) -> tuple[MapTheme, ...]:
    """Registry themes this window can show, in registry order."""
    return tuple(
        THEME_BY_ID[theme_id] for theme_id in _RENDERERS
        if not (THEME_BY_ID[theme_id].needs_climate and window.climate is None)
    )


def render_region_theme(window: RegionWindow, theme_id: str) -> Image.Image:
    if theme_id not in {theme.id for theme in region_themes(window)}:
        raise ValueError(f"Regional detail cannot show the {theme_id!r} map.")
    return _RENDERERS[theme_id](window)
