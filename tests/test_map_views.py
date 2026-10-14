import numpy as np
import pytest
from PIL import Image

from map_maker.terrain.adapters.map_parchment import ParchmentInputs
from map_maker.terrain.adapters.map_projection import (
    SPACE,
    MapProjection,
    projected_lonlat,
    reproject,
)
from map_maker.terrain.adapters.map_views import PREVIEW_LAYERS, THEME_BY_ID, THEMES, theme_file


def _lonlat_image(columns: int = 720) -> Image.Image:
    """An equirectangular image whose red/green channels encode longitude/latitude."""
    rows = columns // 2
    lon = (np.arange(columns) + 0.5) / columns * 360 - 180
    lat = 90 - (np.arange(rows) + 0.5) / rows * 180
    glon, glat = np.meshgrid(lon, lat)
    rgb = np.stack(
        ((glon + 180) / 360 * 255, (glat + 90) / 180 * 255, np.full(glon.shape, 128.0)), axis=-1
    )
    return Image.fromarray(np.round(rgb).astype(np.uint8))


def _decode(pixel: np.ndarray) -> tuple[float, float]:
    return float(pixel[0]) / 255 * 360 - 180, float(pixel[1]) / 255 * 180 - 90


def test_projected_coordinates_put_the_view_centre_and_pole_where_expected() -> None:
    lon, lat, inside, limb = projected_lonlat(MapProjection("globe", 40.0, -25.0), 101)
    assert lon[50, 50] == pytest.approx(40.0, abs=1e-6)
    assert lat[50, 50] == pytest.approx(-25.0, abs=1e-6)
    assert limb[50, 50] == pytest.approx(1.0, abs=1e-3)
    assert not inside[0, 0] and inside[50, 50]
    # North-polar: the pole at the centre, the limit latitude at the rim, the
    # chosen meridian straight below the pole.
    lon, lat, inside, _ = projected_lonlat(MapProjection("north-polar", 10.0, 0.0, 30.0), 101)
    assert lat[50, 50] == pytest.approx(90.0, abs=1.0)
    assert lat[100, 50] == pytest.approx(30.0, abs=1.5)
    assert ((lon[100, 50] + 180) % 360 - 180) == pytest.approx(10.0, abs=1.0)
    # East is to the right of a north-polar view with its meridian below.
    assert ((lon[50, 100] - 10 + 180) % 360 - 180) == pytest.approx(90.0, abs=1.5)
    lon, lat, _, _ = projected_lonlat(MapProjection("south-polar", 0.0, 0.0, -20.0), 101)
    assert lat[50, 50] == pytest.approx(-90.0, abs=1.0)
    assert lat[0, 50] == pytest.approx(-20.0, abs=1.5)


def test_reprojection_samples_the_world_image_and_is_repeatable() -> None:
    image = _lonlat_image()
    globe = reproject(image, MapProjection("globe", -60.0, 30.0), 200)
    again = reproject(image, MapProjection("globe", -60.0, 30.0), 200)
    assert globe.tobytes() == again.tobytes()
    pixels = np.asarray(globe)
    centre_lon, centre_lat = _decode(pixels[100, 100])
    assert centre_lon == pytest.approx(-60.0, abs=2.0)
    assert centre_lat == pytest.approx(30.0, abs=2.0)
    assert tuple(pixels[0, 0]) == SPACE
    # A frame central meridian shifts which longitude a column holds.
    shifted = reproject(image, MapProjection("globe", 0.0, 0.0), 200, central_meridian_deg=90.0)
    assert _decode(np.asarray(shifted)[100, 100])[0] == pytest.approx(-90.0, abs=2.0)
    flat = reproject(image, MapProjection("equirectangular"), 100)
    assert flat.size == (200, 100)
    polar = reproject(image, MapProjection("north-polar"), 120, graticule=True)
    assert polar.size == (120, 120)


def test_projection_settings_are_validated() -> None:
    for bad in (
        {"kind": "mercator"},
        {"kind": "globe", "lat_deg": 95.0},
        {"kind": "north-polar", "limit_deg": 85.0},
        {"kind": "globe", "lon_deg": float("nan")},
    ):
        with pytest.raises(ValueError):
            MapProjection(**bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        reproject(_lonlat_image(), MapProjection("globe"), 8)


def test_theme_registry_names_files_labels_and_legends_uniquely() -> None:
    ids = [theme.id for theme in THEMES]
    assert len(set(ids)) == len(ids) == len(set(PREVIEW_LAYERS))
    assert theme_file(THEME_BY_ID["atlas"]) == "atlas.png"
    assert all(theme.legend for theme in THEMES)


def _parchment_inputs(z: np.ndarray, land: np.ndarray) -> ParchmentInputs:
    zeros = np.zeros(z.shape)
    false = np.zeros(z.shape, dtype=bool)
    return ParchmentInputs(
        z, land, false, zeros, np.ones(z.shape), zeros, false, zeros, zeros, false, false
    )


def test_parchment_maps_draw_mountains_on_rugged_ground_and_repeat_exactly() -> None:
    from map_maker.terrain.adapters.map_parchment import PAPER, parchment_image

    rows, columns = 160, 320
    y, x = np.mgrid[0:rows, 0:columns]
    land = (x > 10) & (x < columns - 10) & (y > 10) & (y < rows - 10)
    # Left half rugged mountains, right half a high flat plateau.
    rugged = 1500 + 1200 * np.sin(x / 4.0) * np.cos(y / 5.0)
    z = np.where(land, np.where(x < columns // 2, rugged, 2500.0), -3000.0)
    image = parchment_image(_parchment_inputs(z, land), 7, 18.0)
    again = parchment_image(_parchment_inputs(z, land), 7, 18.0)
    assert image.tobytes() == again.tobytes()
    ink = np.asarray(image, dtype=np.float64).sum(axis=-1) < 300
    left, right = ink[20:-20, 30 : columns // 2 - 20], ink[20:-20, columns // 2 + 20 : -30]
    assert left.mean() > 4 * max(right.mean(), 1e-3)
    # Beyond a round window nothing is drawn but plain paper.
    outside = z.astype(np.float64).copy()
    outside[:, :40] = np.nan
    blank = np.asarray(parchment_image(_parchment_inputs(outside, land), 7, 18.0))
    assert np.allclose(blank[60:100, 15:30].mean(axis=(0, 1)), np.array(PAPER) * 0.93, atol=25)
