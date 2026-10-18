import numpy as np
import pytest
from PIL import Image

from map_maker.terrain.adapters.map_parchment import ParchmentInputs
from map_maker.terrain.adapters.map_projection import (
    MAX_GLOBE_ZOOM,
    SPACE,
    Drape,
    DrapeTextures,
    MapProjection,
    MapTexture,
    grab,
    lonlat_screen,
    render,
    reproject,
    screen_lonlat,
    view_radius,
    zoomed,
)
from map_maker.terrain.adapters.map_views import PREVIEW_LAYERS, THEME_BY_ID, THEMES, theme_file
from map_maker.terrain.pipeline.planet_patch import forward_aeqd
from map_maker.terrain.pipeline.sphere_views import DRAPE_FADE, latitude_prefilter


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


def _near(a: tuple[float, float] | None, b: tuple[float, float], tolerance: float) -> bool:
    if a is None:
        return False
    return abs((a[0] - b[0] + 180) % 360 - 180) <= tolerance and abs(a[1] - b[1]) <= tolerance


def test_view_positions_put_the_view_centre_and_pole_where_expected() -> None:
    size = (160, 100)
    globe = MapProjection("globe", 40.0, -25.0)
    assert _near(screen_lonlat(globe, size, 80, 50), (40.0, -25.0), 1e-9)
    assert screen_lonlat(globe, size, 1, 1) is None  # space beyond the disc
    # Twice the zoom halves the sine of the angle from the centre at the same pixel.
    near = screen_lonlat(MapProjection("globe", 0.0, 0.0), size, 100, 50)
    closer = screen_lonlat(MapProjection("globe", 0.0, 0.0, zoom=2.0), size, 100, 50)
    assert near is not None and closer is not None
    assert closer[0] == pytest.approx(np.degrees(np.arcsin(np.sin(np.radians(near[0])) / 2)))
    # North-polar: the pole at the centre, the limit latitude at the rim, the
    # chosen meridian straight below the pole and east to its right.
    polar = MapProjection("north-polar", 10.0, 0.0, 30.0)
    pole = screen_lonlat(polar, (100, 100), 50, 50)
    assert pole is not None and pole[1] == pytest.approx(90.0)
    assert _near(screen_lonlat(polar, (100, 100), 50, 100), (10.0, 30.0), 1e-9)
    assert _near(screen_lonlat(polar, (100, 100), 100, 50), (100.0, 30.0), 1e-9)
    south = MapProjection("south-polar", 0.0, 0.0, -20.0)
    assert _near(screen_lonlat(south, (100, 100), 50, 0), (0.0, -20.0), 1e-9)


def test_screen_positions_invert_and_hide_the_far_side() -> None:
    rng = np.random.default_rng(3)
    size = (300, 200)
    for projection in (
        MapProjection("globe", 120.0, 64.0, zoom=1.7),
        MapProjection("globe", -10.0, -90.0),
        MapProjection("north-polar", -40.0, 0.0, 10.0),
        MapProjection("south-polar", 75.0, 0.0, -45.0),
    ):
        for x, y in rng.uniform((0, 0), size, (200, 2)):
            lonlat = screen_lonlat(projection, size, x, y)
            if lonlat is None:
                continue
            assert lonlat_screen(projection, size, *lonlat) == pytest.approx((x, y), abs=1e-6)
    assert lonlat_screen(MapProjection("globe", 0.0, 0.0), size, 180.0, 0.0) is None
    assert lonlat_screen(MapProjection("north-polar", 0.0, 0.0, 30.0), size, 0.0, 10.0) is None


def test_rendered_pixels_show_the_ground_the_screen_geometry_reports() -> None:
    texture = MapTexture.from_image(_lonlat_image(1440), central_meridian_deg=0.0)
    size = (180, 120)
    for projection in (
        MapProjection("globe", -60.0, 30.0, zoom=2.5),
        MapProjection("north-polar", 20.0, 0.0, 20.0),
        MapProjection("south-polar", -100.0, 0.0, -30.0),
    ):
        pixels = np.asarray(render(texture, projection, size), dtype=np.float64)
        rim = view_radius(projection, size)
        checked = 0
        for row in range(4, size[1] - 4, 7):
            for column in range(4, size[0] - 4, 7):
                lonlat = screen_lonlat(projection, size, column + 0.5, row + 0.5)
                # Skip the rim, the poles and the seam, where the encoded longitude jumps.
                if (lonlat is None or abs(lonlat[1]) > 70 or abs(lonlat[0]) > 170
                        or np.hypot(column + 0.5 - size[0] / 2, row + 0.5 - size[1] / 2)
                        > rim - 2):
                    continue
                checked += 1
                # Blue is 128 everywhere on the map, so it measures the globe's limb shading.
                unshaded = pixels[row, column] * 128 / pixels[row, column, 2]
                assert _near(_decode(unshaded), lonlat, 2.5)
        assert checked > 50


def test_grab_keeps_the_held_ground_under_the_cursor() -> None:
    rng = np.random.default_rng(11)
    size = (400, 300)
    views = (
        MapProjection("globe", 30.0, 20.0),
        MapProjection("globe", -150.0, 80.0, zoom=3.0),
        MapProjection("north-polar", 0.0, 0.0, 30.0),
    )
    moved = 0
    for view in views:
        for _ in range(60):
            start = rng.uniform((0, 0), size)
            held = screen_lonlat(view, size, *start)
            if held is None:
                continue
            target = start + rng.normal(0, 25, 2)
            turned = grab(view, size, held, *target)
            if turned is None:
                continue
            moved += 1
            assert turned.kind == view.kind and turned.zoom == view.zoom
            under = screen_lonlat(turned, size, *target)
            if view.kind == "globe":
                assert _near(under, held, 1e-6)
            else:  # a polar view turns about its pole: the meridian follows the cursor
                assert under is not None and _near((under[0], 0.0), (held[0], 0.0), 1e-6)
    assert moved > 100
    # The pole of a north-up globe cannot move sideways.
    top = lonlat_screen(views[0], size, 0.0, 90.0)
    assert top is not None
    assert grab(views[0], size, (0.0, 90.0), top[0] + 30, top[1]) is None


def test_zoom_keeps_the_ground_under_the_cursor_within_limits() -> None:
    size = (400, 300)
    view = MapProjection("globe", 10.0, 40.0)
    cursor = (250.0, 120.0)
    held = screen_lonlat(view, size, *cursor)
    assert held is not None
    closer = zoomed(view, size, 2.0, *cursor)
    assert closer.zoom == 2.0 and _near(screen_lonlat(closer, size, *cursor), held, 1e-6)
    assert zoomed(view, size, 0.5, *cursor).zoom == 1.0
    assert zoomed(closer, size, 100.0, *cursor).zoom == MAX_GLOBE_ZOOM
    polar = MapProjection("north-polar", 0.0, 0.0, 0.0)
    assert zoomed(polar, size, 1.5, *cursor).polar_span_deg == pytest.approx(60.0)
    assert zoomed(polar, size, 0.1, *cursor).polar_span_deg == 150.0


def test_latitude_prefilter_matches_ground_detail_east_west_to_north_south() -> None:
    rows, columns = 90, 360
    stripes = np.zeros((rows, columns, 3), dtype=np.uint8)
    stripes[:, ::2] = 255  # one-pixel stripes: the finest east-west detail there is
    filtered = latitude_prefilter(stripes).astype(np.float64)
    # Near the equator a pixel is as wide as it is high on the ground: unchanged.
    equator = rows // 2
    assert np.array_equal(filtered[equator], stripes[equator])
    # Near a pole pixels are much narrower than high, so stripes average out,
    # and every row keeps its mean colour.
    assert np.ptp(filtered[0]) < 10 and np.ptp(filtered[-1]) < 10
    assert np.allclose(filtered.mean(axis=1), stripes.mean(axis=1), atol=1.0)


def test_small_views_average_fine_detail_instead_of_aliasing() -> None:
    columns = 1024
    stripes = np.zeros((columns // 2, columns, 3), dtype=np.uint8)
    stripes[:, ::2] = 255
    image = Image.fromarray(stripes)
    small = np.asarray(reproject(image, MapProjection("globe", 0.0, 0.0), 64), dtype=np.float64)
    centre = small[24:40, 24:40]
    # Without mip levels each pixel would land on a black or a white stripe.
    assert abs(centre.mean() - 127.5) < 8 and centre.std() < 8


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


FLAT_SIZE = (2400, 1200)  # a flat world 0.15° a pixel


def _flat_lonlat() -> tuple[np.ndarray, np.ndarray]:
    """Longitude and latitude at the pixel centres of a ``FLAT_SIZE`` flat world."""
    width, height = FLAT_SIZE
    lon = (np.arange(width) + 0.5) / width * 360 - 180
    lat = 90 - (np.arange(height) + 0.5) / height * 180
    return np.meshgrid(lon, lat)


def _unit(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    lam, phi = np.radians(lon), np.radians(lat)
    return np.stack((np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)), -1)


def _distance(lon: np.ndarray, lat: np.ndarray, centre: tuple[float, float]) -> np.ndarray:
    """Great-circle angle (radians) from ``centre`` to every point."""
    dot = _unit(lon, lat) @ _unit(np.array(centre[0]), np.array(centre[1]))
    return np.arccos(np.clip(dot, -1, 1))


def _disc_image(size: int, inside: tuple[int, int, int]) -> Image.Image:
    """A regional window's image: ``inside`` on its disc, the app's outside colour beyond."""
    centres = np.arange(size) + 0.5 - size / 2
    disc = np.hypot(*np.meshgrid(centres, centres)) <= size / 2
    rgb = np.where(disc[..., None], np.array(inside), np.array((36, 54, 82)))
    return Image.fromarray(rgb.astype(np.uint8))


def _flat_with(drapes: tuple[Drape, ...]) -> np.ndarray:
    """A black world with ``drapes``; its texels are so large every pixel shows them."""
    black = MapTexture.from_image(Image.new("RGB", (8, 4)))
    flat = render(black, MapProjection("equirectangular"), FLAT_SIZE,
                  drapes=DrapeTextures.from_drapes(drapes))
    return np.asarray(flat, dtype=np.float64)


def test_drapes_show_each_regional_pixel_where_its_azimuthal_mapping_puts_it() -> None:
    planet_m, size = 6.0e6, 128
    # Red and green encode the window position (u across, v down) of each pixel centre.
    ramp = (np.arange(size) + 0.5) / size * 255
    u_code, v_code = np.meshgrid(ramp, ramp)
    coded = Image.fromarray(np.round(np.stack(
        (u_code, v_code, np.full_like(u_code, 255)), axis=-1)).astype(np.uint8))
    lon, lat = _flat_lonlat()
    # Across the antimeridian at high latitude, and in the southern tropics.
    for centre, angle in (((170.0, 55.0), 0.3), ((-30.0, -20.0), 0.5)):
        pixels = _flat_with((Drape(coded, centre, angle),))
        rho = _distance(lon, lat, centre) / angle
        shown = rho < 0.9
        assert shown.sum() > 2000
        assert np.all(pixels[rho > 1, 2] == 0)  # the black world outside the circle
        xy = forward_aeqd(_unit(lon[shown], lat[shown]), *centre, planet_m)
        radius_m = angle * planet_m
        u = (xy[:, 0] + radius_m) / (2 * radius_m)
        v = (radius_m - xy[:, 1]) / (2 * radius_m)
        # Texels are larger than pixels here, so pixels interpolate the code linearly.
        assert np.abs(pixels[shown, 0] / 255 - u).max() < 1.2 / 255
        assert np.abs(pixels[shown, 1] / 255 - v).max() < 1.2 / 255
        # A zoomed globe shows the same positions.
        globe = MapProjection("globe", *centre, zoom=MAX_GLOBE_ZOOM)
        size = (120, 90)
        black = MapTexture.from_image(Image.new("RGB", (8, 4)))
        shaded = np.asarray(render(black, globe, size, drapes=DrapeTextures.from_drapes(
            (Drape(coded, centre, angle),))), dtype=np.float64)
        rows, columns = np.mgrid[0:size[1]:7, 0:size[0]:7]
        points = [screen_lonlat(globe, size, c + 0.5, r + 0.5)
                  for r, c in zip(rows.ravel(), columns.ravel(), strict=True)]
        assert all(point is not None for point in points)
        xy = forward_aeqd(_unit(*np.array(points).T), *centre, planet_m)
        # Blue is 255 on the drape, so it measures the globe's limb shading.
        seen = shaded[rows.ravel(), columns.ravel()]
        unshaded = seen[:, :2] / seen[:, 2:]
        assert np.abs(unshaded[:, 0] - (xy[:, 0] + radius_m) / (2 * radius_m)).max() < 2 / 255
        assert np.abs(unshaded[:, 1] - (radius_m - xy[:, 1]) / (2 * radius_m)).max() < 2 / 255


def test_drapes_fade_into_the_world_over_their_outer_rim() -> None:
    lon, lat = _flat_lonlat()
    centre, angle = (40.0, 10.0), 0.5
    rho = _distance(lon, lat, centre) / angle
    s = np.clip((1 - rho) / DRAPE_FADE, 0, 1)
    expected = 255 * s * s * (3 - 2 * s)  # smoothstep from the rim inwards
    band = (rho > 1 - DRAPE_FADE) & (rho < 1)
    assert band.sum() > 1000
    # The outside colour must not reach the rim through filtering, whether the
    # image is magnified (32 px) or minified (4,096 px) on the view.
    for size in (32, 4096):
        pixels = _flat_with((Drape(_disc_image(size, (255, 255, 255)), centre, angle),))
        assert np.abs(pixels[..., 0] - expected).max() <= 1.0
        assert np.all(pixels[rho <= 1 - DRAPE_FADE] == 255)
        assert np.all(pixels[rho >= 1] == 0)
        assert np.all(pixels[band, 2] == pixels[band, 0])  # no blue from beyond the disc
        assert 0.4 * band.sum() < ((pixels[band, 0] > 10) & (pixels[band, 0] < 245)).sum()


def test_the_last_drape_lies_on_top_and_coarse_pixels_skip_drapes() -> None:
    lon, lat = _flat_lonlat()
    outer = Drape(_disc_image(64, (255, 0, 0)), (10.0, 0.0), 0.3)
    inner = Drape(_disc_image(64, (0, 255, 0)), (14.0, 3.0), 0.08)
    in_inner = _distance(lon, lat, inner.centre) / inner.angle_rad < 0.9
    only_outer = (_distance(lon, lat, outer.centre) / outer.angle_rad < 0.9) & (
        _distance(lon, lat, inner.centre) / inner.angle_rad > 1
    )
    nested = _flat_with((outer, inner))
    assert np.all(nested[in_inner] == (0, 255, 0)) and np.all(nested[only_outer] == (255, 0, 0))
    assert np.all(_flat_with((inner, outer))[in_inner] == (255, 0, 0))
    # A view whose pixels are larger than a world texel shows the world texture
    # alone, exactly; zoomed in, the drape replaces it.
    world = MapTexture.from_image(_lonlat_image(1024))
    drapes = DrapeTextures.from_drapes((outer, inner))
    whole = MapProjection("globe", 10.0, 0.0)
    assert render(world, whole, (200, 200), drapes=drapes).tobytes() == render(
        world, whole, (200, 200)).tobytes()
    close = render(world, MapProjection("globe", *inner.centre, zoom=MAX_GLOBE_ZOOM), (200, 200),
                   drapes=drapes)
    assert np.allclose(np.asarray(close)[100, 100], (0, 255, 0), atol=1)


def test_drapes_are_validated() -> None:
    square = Image.new("RGB", (16, 16))
    for image, centre, angle in (
        (Image.new("RGB", (16, 8)), (0.0, 0.0), 0.1),
        (square, (0.0, 95.0), 0.1),
        (square, (float("inf"), 0.0), 0.1),
        (square, (0.0, 0.0), 0.0),
        (square, (0.0, 0.0), np.pi),
    ):
        with pytest.raises(ValueError):
            Drape(image, centre, angle)


def test_projection_settings_are_validated() -> None:
    for bad in (
        {"kind": "mercator"},
        {"kind": "globe", "lat_deg": 95.0},
        {"kind": "north-polar", "limit_deg": 85.0},
        {"kind": "globe", "lon_deg": float("nan")},
        {"kind": "globe", "zoom": 0.5},
        {"kind": "globe", "zoom": MAX_GLOBE_ZOOM * 2},
        {"kind": "north-polar", "zoom": 2.0},
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
