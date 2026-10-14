"""Lake visibility changes with display scale without changing generated water."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from benchmarks.terrain import fixture
from map_maker.terrain.adapters import render as renderer
from map_maker.terrain.adapters import water_display as water_module
from map_maker.terrain.adapters.render import (
    compose_height_map,
    render_height_map,
    render_height_map_layers,
    save_height_map,
)
from map_maker.terrain.adapters.viewport import render_viewport
from map_maker.terrain.adapters.water_display import (
    WATER_COLOUR,
    WATER_DISPLAY_ID,
    WaterDisplay,
    prepare_water_display,
)
from map_maker.terrain.pipeline import generate_terrain
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled


def _display(wet: np.ndarray) -> WaterDisplay:
    surface = np.where(wet, 100., np.nan).astype(np.float32)
    display = prepare_water_display(surface, np.ones_like(wet, dtype=np.bool_))
    assert display is not None
    return display


def test_separate_pools_keep_individual_areas_and_dry_islands() -> None:
    wet = np.zeros((20, 24), dtype=np.bool_)
    wet[2:12, 2:12] = True
    wet[5:8, 5:8] = False
    wet[14:16, 14:16] = True
    wet[16, 16] = True  # Corner contact must not merge their display importance.
    display = _display(wet)
    areas = np.asarray(display.pool_area)
    assert areas[2, 2] == 91 and areas[14, 14] == 4 and areas[16, 16] == 1
    assert areas[6, 6] == 0
    np.testing.assert_array_equal(areas > 0, wet)
    with display.render((0., 0., 24., 20.), (24, 20)) as image:
        assert image.getpixel((3, 3)) == (*WATER_COLOUR, 255)
        assert image.getpixel((6, 6)) == (*WATER_COLOUR, 0)
        assert image.getpixel((14, 14)) == (*WATER_COLOUR, 0)


def test_small_pool_appears_monotonically_only_as_it_grows_on_screen() -> None:
    display = _display(np.ones((2, 2), dtype=np.bool_))
    alphas: list[int] = []
    for side in (2, 3, 4, 5, 6, 12):
        with display.render((0., 0., float(side), float(side)), (side, side)) as image:
            pixel = image.getpixel((side // 2, side // 2))
            assert isinstance(pixel, tuple)
            alphas.append(pixel[3])
    assert alphas[0:2] == [0, 0]
    assert 0 < alphas[2] < alphas[3] < 255
    assert alphas[-2:] == [255, 255]
    assert alphas == sorted(alphas)


def test_pan_does_not_reclassify_a_partially_visible_lake() -> None:
    display = _display(np.ones((10, 10), dtype=np.bool_))
    with (
        display.render((0., 0., 10., 10.), (10, 10)) as whole,
        display.render((-9., 0., 1., 10.), (10, 10)) as sliver,
    ):
        # Just one column remains on screen, but the whole 100-pixel pool counts.
        assert whole.getpixel((0, 4)) == sliver.getpixel((0, 4)) == (*WATER_COLOUR, 255)
        assert sliver.getpixel((1, 4)) == (*WATER_COLOUR, 0)


def test_area_uses_both_axes_and_visibility_is_independent_of_canvas_size() -> None:
    display = _display(np.ones((4, 4), dtype=np.bool_))
    rect = (0., 0., 2., 8.)  # 16 px squared, even with anisotropic scaling.
    with (
        display.render(rect, (4, 10)) as first,
        display.render(rect, (24, 15)) as wider,
    ):
        pixel = first.getpixel((1, 4))
        assert isinstance(pixel, tuple) and 0 < pixel[3] < 255
        assert pixel == wider.getpixel((1, 4))


def test_render_allocation_and_cached_areas_do_not_grow_with_zoom() -> None:
    display = _display(np.ones((10, 10), dtype=np.bool_))
    before = display.pool_area.tobytes()
    with display.render((-100000., -100000., 100000., 100000.), (80, 60)) as image:
        assert image.size == (80, 60) and image.getpixel((40, 30)) == (*WATER_COLOUR, 255)
    assert display.pool_area.tobytes() == before


def test_source_resolution_does_not_change_visibility_for_the_same_sampled_extent() -> None:
    wet = np.zeros((8, 16), dtype=np.bool_)
    wet[2:4, 5:8] = True
    fine = np.repeat(np.repeat(wet, 2, axis=0), 2, axis=1)
    with (
        _display(wet).render((0., 0., 32., 16.), (32, 16)) as coarse,
        _display(fine).render((0., 0., 32., 16.), (32, 16)) as detailed,
    ):
        assert coarse.tobytes() == detailed.tobytes()


def test_nonland_infinity_and_missing_water_are_never_displayed_or_mutated() -> None:
    surface = np.array([[100., np.inf], [np.nan, 100.]], dtype=np.float32)
    land = np.array([[True, True], [True, False]])
    original_surface, original_land = surface.copy(), land.copy()
    display = prepare_water_display(surface, land)
    assert display is not None
    np.testing.assert_array_equal(np.asarray(display.pool_area), [[1., 0.], [0., 0.]])
    np.testing.assert_array_equal(surface, original_surface)
    np.testing.assert_array_equal(land, original_land)
    assert prepare_water_display(surface, np.zeros_like(land)) is None


@pytest.mark.parametrize("surface,land", [
    (np.zeros(3, dtype=np.float32), np.ones(3, dtype=np.bool_)),
    (np.zeros((3, 3), dtype=np.float32), np.ones((2, 3), dtype=np.bool_)),
])
def test_incompatible_water_arrays_are_rejected(surface: np.ndarray, land: np.ndarray) -> None:
    with pytest.raises(ValueError, match="matching two-dimensional"):
        prepare_water_display(surface, land)


def test_export_scale_metadata_and_scientific_ground_are_separate(tmp_path: Path) -> None:
    coast, settings, constraints = fixture("square", 65, 42)
    dry = generate_terrain(coast, settings, constraints=constraints)
    surface = np.full(dry.elevation_m.shape, np.nan, dtype=np.float32)
    surface[20:30, 20:30] = 2000
    surface[40:42, 40:42] = 2000
    terrain = replace(dry, water=replace(dry.water, surface_m=surface))
    before = (terrain.elevation_m.copy(), terrain.water.surface_m.copy(),
              terrain.routing.receivers.copy())
    image, water = render_height_map_layers(terrain)
    assert water is not None
    with (
        compose_height_map(image, water) as composed,
        render_height_map(terrain) as cartographic,
        render_height_map(terrain, style="scientific") as scientific,
        render_height_map(dry, style="scientific") as dry_scientific,
    ):
        assert composed.tobytes() == cartographic.tobytes()
        assert cartographic.getpixel((25, 25)) == (*WATER_COLOUR, 255)
        assert cartographic.getpixel((40, 40)) == image.getpixel((40, 40))
        assert scientific.tobytes() == dry_scientific.tobytes()
        assert scientific.info["map-maker.water_visibility"] == "none"
        destination = tmp_path / "water.png"
        save_height_map(composed, terrain, destination)
        with Image.open(destination) as saved:
            assert saved.info["map-maker.water_visibility"] == WATER_DISPLAY_ID
            assert saved.tobytes() == cartographic.tobytes()
        # View rendering must not affect a later full-map export.
        with water.render((-100., -100., 500., 500.), (80, 60)):
            pass
        with compose_height_map(image, water) as after_zoom:
            assert after_zoom.tobytes() == cartographic.tobytes()
    for actual, expected in zip((terrain.elevation_m, terrain.water.surface_m,
                                 terrain.routing.receivers), before, strict=True):
        np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize("rect,size", [
    ((0., 0., 517., 259.), (517, 259)),
    ((-19.25, 11.125, 1017.75, 388.5), (531, 279)),
    ((0.5, -0.5, 517.5, 258.5), (517, 259)),
    ((-100000., -100000., 100000., 100000.), (513, 263)),
    ((0., 0., 1., 1.), (2, 2)),
])
def test_water_tiles_match_dense_pixel_control_and_bound_colour_scratch(
    rect: tuple[float, float, float, float], size: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = np.random.default_rng(42).choice(
        np.array([0., 4., 9., 9.001, 16., 25., 35.999, 36., 1000.], dtype=np.float32),
        (259, 517),
    )
    with closing(Image.fromarray(values)) as source:
        display = WaterDisplay(source)
        before = source.tobytes()
        with closing(render_viewport(source, rect, size,
                                     resample=Image.Resampling.NEAREST)) as sampled:
            scale = ((rect[2] - rect[0]) / source.width
                     * (rect[3] - rect[1]) / source.height)
            # Independent dense control retains the established arithmetic order.
            fade = np.clip((np.asarray(sampled) * scale - 9.) / (36. - 9.), 0., 1.)
            expected = np.empty((size[1], size[0], 4), dtype=np.uint8)
            expected[..., :3] = WATER_COLOUR
            expected[..., 3] = np.rint(255 * fade * fade * (3 - 2 * fade)).astype(np.uint8)
        fromarray = Image.fromarray
        observed: list[tuple[int, ...]] = []
        def bounded(array: np.ndarray, *args: Any, **kwargs: Any) -> Image.Image:
            observed.append(array.shape)
            assert max(array.shape[:2]) <= water_module.WATER_RENDER_TILE_EDGE
            return fromarray(array, *args, **kwargs)
        monkeypatch.setattr(Image, "fromarray", bounded)
        with closing(display.render(rect, size)) as actual:
            np.testing.assert_array_equal(np.asarray(actual), expected)
        assert observed and source.tobytes() == before


def test_native_water_composition_matches_dense_overlay_and_keeps_borrowed_inputs() -> None:
    rng = np.random.default_rng(82)
    rgba = rng.integers(0, 256, (259, 517, 4), dtype=np.uint8)
    areas = rng.uniform(0., 64., (259, 517)).astype(np.float32)
    with (closing(Image.fromarray(rgba)) as ground,
          closing(WaterDisplay(Image.fromarray(areas))) as water,
          closing(ground.copy()) as expected,
          closing(water.render((0., 0., 517., 259.), ground.size)) as overlay):
        expected.alpha_composite(overlay)
        ground.info["provenance"] = "unchanged"
        with closing(compose_height_map(ground, water)) as actual:
            np.testing.assert_array_equal(np.asarray(actual), np.asarray(expected))
            assert actual.info == ground.info
        np.testing.assert_array_equal(np.asarray(ground), rgba)
        np.testing.assert_array_equal(np.asarray(water.pool_area), areas)


def test_cancelled_water_render_closes_output_and_tiles_but_keeps_cached_areas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = CancellationToken()
    with closing(WaterDisplay(Image.new("F", (517, 259), 16.))) as water:
        owned: list[Image.Image] = []
        new, crop, paste = Image.new, Image.Image.crop, Image.Image.paste
        def record_new(*args: Any, **kwargs: Any) -> Image.Image:
            image = new(*args, **kwargs)
            if image.size == (517, 259):
                owned.append(image)
            return image
        def record_crop(self: Image.Image, *args: Any, **kwargs: Any) -> Image.Image:
            image = crop(self, *args, **kwargs)
            owned.append(image)
            return image
        def cancel(self: Image.Image, tile: Image.Image, *args: Any, **kwargs: Any) -> None:
            owned.append(tile)
            paste(self, tile, *args, **kwargs)
            token.cancel()
        monkeypatch.setattr(Image, "new", record_new)
        monkeypatch.setattr(Image.Image, "crop", record_crop)
        monkeypatch.setattr(Image.Image, "paste", cancel)
        with pytest.raises(GenerationCancelled):
            water.render((0., 0., 517., 259.), (517, 259), cancellation=token)
        assert len(owned) >= 3
        for image in owned:
            with pytest.raises(ValueError, match="closed"):
                image.getpixel((0, 0))
        assert water.pool_area.getpixel((0, 0)) == 16.


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_layer_preparation_releases_owned_ground_and_area_images(
    cancel: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coast, settings, constraints = fixture("square", 65, 42)
    terrain = generate_terrain(coast, settings, constraints=constraints)
    ground, pool = Image.new("RGBA", (65, 65)), Image.new("F", (65, 65))
    token = CancellationToken()
    def render(*_args: object, **_kwargs: object) -> Image.Image:
        return ground
    def prepare(*_args: object, **_kwargs: object) -> WaterDisplay:
        if cancel:
            token.cancel()
            return WaterDisplay(pool)
        raise RuntimeError("classification failed")
    monkeypatch.setattr(renderer, "render_ground_map", render)
    monkeypatch.setattr(renderer, "prepare_water_display", prepare)
    with pytest.raises(GenerationCancelled if cancel else RuntimeError):
        render_height_map_layers(terrain, cancellation=token)
    with pytest.raises(ValueError, match="closed"):
        ground.getpixel((0, 0))
    if cancel:
        with pytest.raises(ValueError, match="closed"):
            pool.getpixel((0, 0))
    pool.close()


@pytest.mark.parametrize("wet", [False, True])
def test_one_shot_render_transfers_ground_without_duplicate_and_closes_water(
    wet: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coast, settings, constraints = fixture("square", 65, 42)
    terrain = generate_terrain(coast, settings, constraints=constraints)
    ground = Image.new("RGBA", (65, 65), (21, 40, 60, 255))
    water = WaterDisplay(Image.new("F", (65, 65), 16.)) if wet else None
    def layers(*_args: object, **_kwargs: object) -> tuple[Image.Image, WaterDisplay | None]:
        return ground, water
    monkeypatch.setattr(renderer, "render_height_map_layers", layers)
    with closing(render_height_map(terrain)) as result:
        assert result is ground
        assert result.getpixel((0, 0)) is not None
        if water is not None:
            with pytest.raises(ValueError, match="closed"):
                water.pool_area.getpixel((0, 0))


def test_failed_native_composition_closes_only_the_export_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned: list[Image.Image] = []
    def fail(_self: WaterDisplay, image: Image.Image, **_kwargs: object) -> None:
        owned.append(image)
        image.putpixel((0, 0), (0, 0, 0, 0))
        raise OSError("native composition failed")
    monkeypatch.setattr(WaterDisplay, "composite_native", fail)
    with (closing(Image.new("RGBA", (3, 3), (20, 50, 90, 255))) as ground,
          closing(WaterDisplay(Image.new("F", (3, 3), 9.))) as water):
        with pytest.raises(OSError):
            compose_height_map(ground, water)
        assert ground.getpixel((0, 0)) == (20, 50, 90, 255)
        assert water.pool_area.getpixel((0, 0)) == 9.
    assert len(owned) == 1
    with pytest.raises(ValueError, match="closed"):
        owned[0].getpixel((0, 0))
