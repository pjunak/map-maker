"""Bounded review panels derived from full-resolution regional ground and deltas."""

from contextlib import closing
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from map_maker.terrain.adapters.render import GROUND_RENDER_TILE_EDGE
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled

COMPARISON_PANEL_LIMIT = 1024
COMPARISON_LAYOUT_ID = "bounded-regional-comparison@1"


@dataclass(frozen=True, slots=True)
class ComparisonLayout:
    source_size: tuple[int, int]
    panel_size: tuple[int, int]
    panel_width: int

    @property
    def canvas_size(self) -> tuple[int, int]:
        return 3 * self.panel_width, self.panel_size[1] + 56

    @property
    def reduced(self) -> bool:
        return self.source_size != self.panel_size


def comparison_layout(width: int, height: int) -> ComparisonLayout:
    if type(width) is not int or type(height) is not int or min(width, height) < 1:
        raise ValueError("Comparison dimensions must be positive integers.")
    scale = min(1., COMPARISON_PANEL_LIMIT / max(width, height))
    size = max(1, round(width * scale)), max(1, round(height * scale))
    return ComparisonLayout((width, height), size, max(300, size[0]))


def _difference_image(
    added: NDArray[np.float32], cancellation: CancellationToken | None,
) -> tuple[Image.Image, float]:
    """Keep the colour scale tied to native extrema, independent of preview size."""
    height, width = added.shape
    edge = GROUND_RENDER_TILE_EDGE
    peak = 0.0
    for top in range(0, height, edge):
        for left in range(0, width, edge):
            check_cancelled(cancellation)
            peak = max(peak, float(np.abs(added[top:top + edge, left:left + edge]).max()))
    scale = max(peak, 1e-9)
    image = Image.new("RGB", (width, height))
    try:
        for top in range(0, height, edge):
            for left in range(0, width, edge):
                check_cancelled(cancellation)
                delta = added[top:top + edge, left:left + edge].astype(np.float64)
                rgb = np.full((*delta.shape, 3), 230.0, dtype=np.float64)
                rgb[..., 0] -= 190 * np.maximum(-delta / scale, 0)
                rgb[..., 2] -= 190 * np.maximum(delta / scale, 0)
                rgb[..., 1] -= 170 * (np.abs(delta) / scale)
                with closing(Image.fromarray(rgb.astype(np.uint8))) as tile:
                    image.paste(tile, (left, top))
                del rgb, delta
        return image, peak
    except BaseException:
        image.close()
        raise


def render_parent_comparison(
    reference: Image.Image, detailed: Image.Image, added: NDArray[np.float32], *,
    cancellation: CancellationToken | None = None,
) -> Image.Image:
    """Keep numeric/native scientific products intact; fit only this review image."""
    if reference.size != detailed.size or added.shape != (detailed.height, detailed.width):
        raise ValueError("Comparison inputs must cover the same native samples.")
    check_cancelled(cancellation)
    layout = comparison_layout(*detailed.size)
    difference, peak = _difference_image(added, cancellation)
    with closing(difference):
        review = Image.new("RGB", layout.canvas_size, "#121c20")
        try:
            draw = ImageDraw.Draw(review)
            panels = ((reference, "Verified reference"), (detailed, "Experimental detail"),
                      (difference, f"Added metres: blue -{peak:.3f}, red +{peak:.3f}"))
            for index, (source, label) in enumerate(panels):
                check_cancelled(cancellation)
                with closing(source.resize(layout.panel_size, Image.Resampling.BOX)) as panel:
                    x = index * layout.panel_width
                    review.paste(panel, (x + (layout.panel_width - panel.width) // 2, 30))
                    draw.text((x + 6, 8), label, fill="white")
            note = "Ground only. Local hydrology unreviewed."
            if layout.reduced:
                note += (f" Preview {detailed.width}x{detailed.height} -> "
                         f"{layout.panel_size[0]}x{layout.panel_size[1]}.")
            draw.text((6, layout.panel_size[1] + 36), note, fill="white")
            review.info.update({
                "map-maker.comparison_layout": COMPARISON_LAYOUT_ID,
                "map-maker.native_size": f"{detailed.width}x{detailed.height}",
                "map-maker.panel_size": f"{layout.panel_size[0]}x{layout.panel_size[1]}",
                "map-maker.preview_reduced": str(layout.reduced).lower(),
                "map-maker.maximum_added_height_m": str(peak),
            })
            check_cancelled(cancellation)
            return review
        except BaseException:
            review.close()
            raise
