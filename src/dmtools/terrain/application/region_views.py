"""Map themes available for a regional detail window, rendered on request."""

from collections.abc import Callable

from PIL import Image

from dmtools.terrain.adapters.map_views import THEMES, MapTheme
from dmtools.terrain.adapters.planet_region import (
    RegionWindow,
    window_image,
    window_parchment,
    window_topographic,
)

_RENDERERS: dict[str, Callable[[RegionWindow], Image.Image]] = {
    "atlas": lambda window: window_image(window, atlas=True),
    "relief": lambda window: window_image(window, atlas=False),
    "topographic": window_topographic,
    "parchment": lambda window: _required(window_parchment(window)),
}


def _required(image: Image.Image | None) -> Image.Image:
    if image is None:
        raise ValueError("This map needs the planet's climate.")
    return image


def region_themes(window: RegionWindow) -> tuple[MapTheme, ...]:
    """Registry themes this window can show, in registry order."""
    return tuple(
        theme for theme in THEMES
        if theme.id in _RENDERERS and not (theme.needs_climate and window.climate is None)
    )


def render_region_theme(window: RegionWindow, theme_id: str) -> Image.Image:
    if theme_id not in {theme.id for theme in region_themes(window)}:
        raise ValueError(f"Regional detail cannot show the {theme_id!r} map.")
    return _RENDERERS[theme_id](window)
