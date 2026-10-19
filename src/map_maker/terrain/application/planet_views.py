"""Views of planet maps: any saved theme in any projection, turning, or as a 3D globe model."""

from collections.abc import Sequence
from io import BytesIO
from pathlib import Path

from PIL import Image

from map_maker.terrain.adapters.globe_model import globe_model
from map_maker.terrain.adapters.globe_spin import (
    SPIN_FRAMES,
    SPIN_SECONDS,
    check_spin,
    spin_frames,
    write_spin,
)
from map_maker.terrain.adapters.map_projection import (
    MAX_GLOBE_ZOOM,
    Drape,
    MapProjection,
    MapTexture,
    Size,
    render,
)
from map_maker.terrain.adapters.map_views import THEME_BY_ID, THEMES, MapTheme, theme_file
from map_maker.terrain.adapters.planet_load import verified_build
from map_maker.terrain.domain.world import WorldFrame

MIN_VIEW_PIXELS = 64
MAX_VIEW_PIXELS = 8192


def render_view(
    build: Path,
    theme_id: str,
    projection: MapProjection,
    pixels: int,
    *,
    width: int | None = None,
    graticule: bool = False,
) -> Image.Image:
    """The build's ``theme_id`` image shown in ``projection``, ``pixels`` high.

    ``width`` defaults to a square globe or polar view and to a flat world twice as
    wide as high. A globe or polar view fits its shorter side. The view shows the
    world map alone, so a globe zooms at most ``MAX_GLOBE_ZOOM`` times.
    """
    texture, size = _view_texture(build, theme_id, projection, pixels, width)
    return render(texture, projection, size, graticule=graticule)


def export_view(
    build: Path,
    destination: Path,
    theme_id: str,
    projection: MapProjection,
    pixels: int,
    *,
    width: int | None = None,
    graticule: bool = False,
) -> Path:
    """Write a view as a new PNG; existing files are never replaced."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"View destination already exists: {destination}")
    if destination.suffix.lower() != ".png":
        raise ValueError("Views are written as .png images.")
    image = render_view(build, theme_id, projection, pixels, width=width, graticule=graticule)
    with destination.open("xb") as stream:
        image.save(stream, format="PNG")
    return destination


def export_spin(
    build: Path,
    destination: Path,
    theme_id: str,
    projection: MapProjection,
    pixels: int,
    *,
    width: int | None = None,
    frames: int = SPIN_FRAMES,
    seconds: float = SPIN_SECONDS,
    graticule: bool = False,
) -> Path:
    """Write a globe or polar view turning once as a new animated WebP (``globe_spin``).

    Sizes are as for ``render_view``; existing files are never replaced.
    """
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Spin destination already exists: {destination}")
    if destination.suffix.lower() != ".webp":
        raise ValueError("Spinning views are written as .webp images.")
    if projection.kind == "equirectangular":
        raise ValueError("Only a globe or a polar view turns.")
    check_spin(frames, seconds)
    texture, size = _view_texture(build, theme_id, projection, pixels, width)
    images = spin_frames(texture, projection, size, frames=frames, graticule=graticule)
    with destination.open("xb") as stream:
        write_spin(images, stream, seconds)
    return destination


def _view_texture(
    build: Path, theme_id: str, projection: MapProjection, pixels: int, width: int | None
) -> tuple[MapTexture, Size]:
    """The build's ``theme_id`` map prepared for views, and the view's checked size."""
    if projection.zoom > MAX_GLOBE_ZOOM:
        raise ValueError(f"World views zoom a globe from 1 to {MAX_GLOBE_ZOOM:g} times.")
    theme = _theme(theme_id)
    width = width or (2 * pixels if projection.kind == "equirectangular" else pixels)
    for size in (pixels, width):
        if not MIN_VIEW_PIXELS <= size <= MAX_VIEW_PIXELS:
            raise ValueError(f"View sizes must be {MIN_VIEW_PIXELS}-{MAX_VIEW_PIXELS} pixels.")
    name = theme_file(theme)
    folder, manifest = verified_build(build, (name,))
    with Image.open(folder / name) as image:
        texture = MapTexture.from_image(
            image, float(manifest["world_frame"]["central_meridian_deg"])
        )
    return texture, (width, pixels)


def export_globe(build: Path, destination: Path, theme_id: str) -> Path:
    """Write the build's ``theme_id`` map as a 3D globe model (.glb), never replacing a file.

    The globe's band shows the build's image unchanged, after its hash is checked.
    """
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Globe destination already exists: {destination}")
    if destination.suffix.lower() != ".glb":
        raise ValueError("Globe models are written as .glb files.")
    theme = _theme(theme_id)
    name = theme_file(theme)
    folder, manifest = verified_build(build, (name,))
    frame = manifest["world_frame"]
    meridian = float(frame["central_meridian_deg"])
    model = globe_model(
        (folder / name).read_bytes(), meridian, name=theme.label,
        extras=_globe_extras(theme.label, float(frame["radius_km"]), meridian,
                             build_sha256=str(manifest["build_sha256"])),
    )
    with destination.open("xb") as stream:
        stream.write(model)
    return destination


def save_globe(
    destination: Path,
    image: Image.Image,
    label: str,
    frame: WorldFrame,
    drapes: Sequence[Drape] = (),
) -> Path:
    """Write a drawn world-frame map as a 3D globe model (.glb), as the app saves images,
    with the regional maps ``drapes`` over it as the app's globe shows them."""
    if destination.suffix.lower() != ".glb":
        raise ValueError("Globe models are written as .glb files.")
    png = BytesIO()
    image.save(png, format="PNG")
    model = globe_model(png.getvalue(), frame.central_meridian_deg, name=label,
                        extras=_globe_extras(label, frame.radius_km, frame.central_meridian_deg),
                        drapes=drapes)
    with destination.open("wb") as stream:
        stream.write(model)
    return destination


def _globe_extras(
    label: str, radius_km: float, central_meridian_deg: float, *, build_sha256: str | None = None
) -> dict[str, object]:
    """What a globe model shows, recorded in it: the model is 1 m, the planet is not."""
    extras: dict[str, object] = {
        "map": label,
        "model_radius_m": 1.0,
        "planet_radius_m": radius_km * 1000.0,
        "central_meridian_deg": central_meridian_deg,
    }
    if build_sha256 is not None:
        extras["build_sha256"] = build_sha256
    return extras


def _theme(theme_id: str) -> MapTheme:
    theme = THEME_BY_ID.get(theme_id)
    if theme is None:
        raise ValueError(
            f"Unknown view {theme_id!r}; choose one of {', '.join(t.id for t in THEMES)}."
        )
    return theme
