# pyright: reportPrivateUsage=false
"""Exact pixel/stencil agreement and bounded rendering scratch for unusual shapes."""

from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from map_maker.terrain.adapters import render
from map_maker.terrain.adapters.palettes import CARTOGRAPHIC_RELIEF_MAX_ELEVATION_M
from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled


@pytest.mark.parametrize("style", ["scientific", "cartographic"])
@pytest.mark.parametrize("shape,edge", [((13, 17), 1), ((13, 17), 7), ((259, 517), 256),
                                       ((2, 1103), 256), ((1103, 2), 256), ((2, 2), 256)])
def test_tiles_match_whole_grid_stencils_and_do_not_change_inputs(
    style: render.RenderStyle, shape: tuple[int, int], edge: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ground = np.random.default_rng(42).uniform(0., 6000., shape).astype(np.float32)
    land = np.indices(shape).sum(axis=0) % 7 != 0
    ground[~land] = np.nan
    ground.setflags(write=False)
    land.setflags(write=False)
    before = ground.tobytes(), land.tobytes()
    grid = EndpointGrid((-713.123, 173.971, 514.237, 700.777), shape[1], shape[0])
    maximum = CARTOGRAPHIC_RELIEF_MAX_ELEVATION_M if style == "cartographic" else 6000.
    # Dense control applies the established stencil to the complete grid in one
    # pass. The optimized path must match even at tile/global edges and NaN coasts.
    expected = render._ground_rgba(ground, land, grid, maximum, style)
    original = render._ground_rgba
    sizes: list[tuple[int, ...]] = []

    def bounded(
        z: NDArray[np.float32], mask: NDArray[np.bool_], frame: EndpointGrid,
        ceiling: float, selected: render.RenderStyle,
    ) -> NDArray[np.uint8]:
        sizes.append(z.shape)
        assert max(z.shape) <= edge + 2
        assert frame == grid
        return original(z, mask, frame, ceiling, selected)

    monkeypatch.setattr(render, "GROUND_RENDER_TILE_EDGE", edge)
    monkeypatch.setattr(render, "_ground_rgba", bounded)
    with render.render_ground_map(ground, land, grid, 6000., style=style) as image:
        np.testing.assert_array_equal(np.asarray(image), expected)
        assert image.size == (shape[1], shape[0])
        assert image.info["map-maker.render_style"] == style
        assert image.info["map-maker.water_visibility"] == "none"
    assert sizes and (ground.tobytes(), land.tobytes()) == before


def test_cancel_between_tiles_closes_canvas_and_all_intermediate_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = CancellationToken()
    original = render._ground_rgba
    created: list[Image.Image] = []
    new, fromarray, crop = Image.new, Image.fromarray, Image.Image.crop

    def record_new(*args: Any, **kwargs: Any) -> Image.Image:
        image = new(*args, **kwargs)
        if image.size == (32, 32):
            created.append(image)
        return image

    def record_array(*args: Any, **kwargs: Any) -> Image.Image:
        image = fromarray(*args, **kwargs)
        created.append(image)
        return image

    def record_crop(self: Image.Image, *args: Any, **kwargs: Any) -> Image.Image:
        image = crop(self, *args, **kwargs)
        created.append(image)
        return image

    def cancel(*args: Any, **kwargs: Any) -> NDArray[np.uint8]:
        result = original(*args, **kwargs)
        token.cancel()
        return result

    monkeypatch.setattr(Image, "new", record_new)
    monkeypatch.setattr(Image, "fromarray", record_array)
    monkeypatch.setattr(Image.Image, "crop", record_crop)
    monkeypatch.setattr(render, "_ground_rgba", cancel)
    monkeypatch.setattr(render, "GROUND_RENDER_TILE_EDGE", 8)
    with pytest.raises(GenerationCancelled):
        render.render_ground_map(np.zeros((32, 32), dtype=np.float32),
                                 np.ones((32, 32), dtype=np.bool_),
                                 EndpointGrid((0., 0., 1., 1.), 32, 32), 6000., cancellation=token)
    assert len(created) == 3
    for image in created:
        with pytest.raises(ValueError, match="closed"):
            image.getpixel((0, 0))


def test_shape_mismatch_fails_before_allocating_canvas(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Invalid grids must fail before rendering allocation.")
    monkeypatch.setattr(Image, "new", forbidden)
    with pytest.raises(ValueError, match="matching"):
        render.render_ground_map(np.zeros((4, 3), dtype=np.float32),
                                 np.ones((3, 4), dtype=np.bool_),
                                 EndpointGrid((0., 0., 1., 1.), 4, 3), 6000.)
