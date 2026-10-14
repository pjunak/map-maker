"""Comparison previews stay bounded while preserving native input and extrema."""

from typing import Any

import numpy as np
import pytest
from PIL import Image

from benchmarks.regional_memory import sample_bounds
from map_maker.terrain.adapters.regional_review import (
    COMPARISON_PANEL_LIMIT,
    comparison_layout,
    render_parent_comparison,
)
from map_maker.terrain.application.region_memory import ParentMemoryEstimate, estimate_regional_job
from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.domain.regional import RegionalSamplingRequest
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled


@pytest.mark.parametrize("size", [(17, 13), (4097, 3), (3, 4097), (1500, 1400)])
def test_panels_fit_without_upscaling_or_modifying_native_images(size: tuple[int, int]) -> None:
    width, height = size
    delta = np.zeros((height, width), dtype=np.float32)
    delta[-1, -1] = 9.
    delta[0, 0] = -7.
    before = delta.tobytes()
    with (Image.new("RGBA", size, (20, 50, 90, 255)) as reference,
          Image.new("RGBA", size, (30, 70, 100, 255)) as detailed,
          render_parent_comparison(reference, detailed, delta) as review):
        layout = comparison_layout(*size)
        assert review.size == layout.canvas_size
        assert review.width <= 3 * COMPARISON_PANEL_LIMIT
        assert review.height <= COMPARISON_PANEL_LIMIT + 56
        assert all(a <= b for a, b in zip(layout.panel_size, size, strict=True))
        assert review.info["map-maker.native_size"] == f"{width}x{height}"
        assert review.info["map-maker.preview_reduced"] == str(max(size) > 1024).lower()
        assert float(review.info["map-maker.maximum_added_height_m"]) == 9.
        assert reference.getpixel((0, 0)) == (20, 50, 90, 255)
        assert detailed.getpixel((0, 0)) == (30, 70, 100, 255)
    assert delta.tobytes() == before


def test_difference_colours_use_full_native_extrema_and_zero_remains_neutral() -> None:
    delta = np.zeros((8, 8), dtype=np.float32)
    delta[1, 1], delta[1, 2] = -6., 6.
    with (Image.new("RGBA", (8, 8)) as reference,
          render_parent_comparison(reference, reference, delta) as review):
        x = 600 + (300 - 8) // 2
        assert review.getpixel((x + 1, 31)) == (40, 60, 230)
        assert review.getpixel((x + 2, 31)) == (230, 60, 40)
        assert review.getpixel((x + 3, 31)) == (230, 230, 230)
    delta[:] = 0.
    with (Image.new("RGBA", (8, 8)) as reference,
          render_parent_comparison(reference, reference, delta) as review):
        assert review.info["map-maker.maximum_added_height_m"] == "0.0"
        assert review.getpixel((x + 1, 31)) == (230, 230, 230)


def test_cancelled_comparison_releases_derived_images_but_keeps_borrowed_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = CancellationToken()
    created: list[Image.Image] = []
    new, resize = Image.new, Image.Image.resize

    def record_new(*args: Any, **kwargs: Any) -> Image.Image:
        image = new(*args, **kwargs)
        if image.mode == "RGB" and image.size in ((32, 32), (900, 88)):
            created.append(image)
        return image

    def cancel(self: Image.Image, *args: Any, **kwargs: Any) -> Image.Image:
        result = resize(self, *args, **kwargs)
        created.append(result)
        token.cancel()
        return result

    with Image.new("RGBA", (32, 32), (20, 50, 90, 255)) as source:
        monkeypatch.setattr(Image, "new", record_new)
        monkeypatch.setattr(Image.Image, "resize", cancel)
        with pytest.raises(GenerationCancelled):
            render_parent_comparison(source, source, np.zeros((32, 32), dtype=np.float32),
                                     cancellation=token)
        assert source.getpixel((0, 0)) == (20, 50, 90, 255)
    assert len(created) == 4
    for image in created:
        with pytest.raises(ValueError, match="closed"):
            image.getpixel((0, 0))


@pytest.mark.parametrize("size,factor", [((1409, 1409), 128), ((3, 262145), 65536),
                                       ((262145, 3), 65536)])
def test_stress_window_bounds_round_trip_and_render_admission_is_bounded(
    size: tuple[int, int], factor: int,
) -> None:
    grid = EndpointGrid((0., 0., 4000., 2400.), 65, 39)
    bounds = sample_bounds(grid, factor, size)
    request = RegionalSamplingRequest.for_bounds("0" * 64, grid, bounds, factor)
    assert (request.grid().width, request.grid().height) == size
    parent = ParentMemoryEstimate(0, 0, 0, 0, 0, 0, 0, 0)
    job = estimate_regional_job(request, parent, detail=True, needs_preparation=False)
    assert job.rendering_allowance_bytes < 128 * 1024 * 1024
    assert job.total_bytes < 256 * 1024 * 1024


@pytest.mark.parametrize("size", [(0, 4), (1, 4), (True, 4), (4, 1.5), (4000, 4000)])
def test_invalid_stress_windows_reject_before_allocating(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        sample_bounds(EndpointGrid((0., 0., 1., 1.), 65, 65), 8, size)
