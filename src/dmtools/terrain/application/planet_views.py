"""Views of completed planet builds: any saved theme in any projection."""

from pathlib import Path

from PIL import Image

from dmtools.terrain.adapters.map_projection import MapProjection, reproject
from dmtools.terrain.adapters.map_views import THEME_BY_ID, THEMES, theme_file
from dmtools.terrain.adapters.planet_load import verified_build

MIN_VIEW_PIXELS = 64
MAX_VIEW_PIXELS = 8192


def render_view(
    build: Path,
    theme_id: str,
    projection: MapProjection,
    pixels: int,
    *,
    graticule: bool = False,
) -> Image.Image:
    """The build's ``theme_id`` image shown in ``projection`` (``pixels`` high)."""
    theme = THEME_BY_ID.get(theme_id)
    if theme is None:
        raise ValueError(
            f"Unknown view {theme_id!r}; choose one of {', '.join(t.id for t in THEMES)}."
        )
    if not MIN_VIEW_PIXELS <= pixels <= MAX_VIEW_PIXELS:
        raise ValueError(f"View size must be {MIN_VIEW_PIXELS}-{MAX_VIEW_PIXELS} pixels.")
    name = theme_file(theme)
    folder, manifest = verified_build(build, (name,))
    with Image.open(folder / name) as image:
        return reproject(
            image, projection, pixels,
            central_meridian_deg=float(manifest["world_frame"]["central_meridian_deg"]),
            graticule=graticule,
        )


def export_view(
    build: Path,
    destination: Path,
    theme_id: str,
    projection: MapProjection,
    pixels: int,
    *,
    graticule: bool = False,
) -> Path:
    """Write a view as a new PNG; existing files are never replaced."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"View destination already exists: {destination}")
    if destination.suffix.lower() != ".png":
        raise ValueError("Views are written as .png images.")
    image = render_view(build, theme_id, projection, pixels, graticule=graticule)
    with destination.open("xb") as stream:
        image.save(stream, format="PNG")
    return destination
