# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Screen-scale visibility of sampled lake pools, independent of hydrology."""

from contextlib import closing
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from rasterio.features import rasterize, shapes
from shapely.geometry import shape

from map_maker.terrain.adapters.viewport import render_viewport
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled

WATER_DISPLAY_ID = "sampled-pool-screen-area@1"
WATER_COLOUR = (49, 133, 175)
WATER_RENDER_TILE_EDGE = 256
# Cartographic thresholds in output pixels, not physical water-size estimates.
HIDDEN_AREA_PX2 = 9.0
OPAQUE_AREA_PX2 = 36.0


@dataclass(frozen=True, slots=True)
class WaterDisplay:
    """Cached whole-pool areas in source pixels; never cropped before classification."""

    pool_area: Image.Image

    def close(self) -> None:
        """Release the owned whole-pool area image."""
        self.pool_area.close()

    def render(
        self,
        rect: tuple[float, float, float, float],
        size: tuple[int, int],
        *, cancellation: CancellationToken | None = None,
    ) -> Image.Image:
        """Retain one area viewport and output image; colour scratch stays tiled."""
        check_cancelled(cancellation)
        left, top, right, bottom = rect
        pixel_area_scale = ((right - left) / self.pool_area.width
                            * (bottom - top) / self.pool_area.height)
        # Keep the original full viewport transform: tile-local affine offsets can
        # round differently exactly at sample boundaries. Areas stay categorical.
        with closing(render_viewport(self.pool_area, rect, size,
                                     resample=Image.Resampling.NEAREST)) as areas:
            image = Image.new("RGBA", size)
            try:
                _paint_water(image, areas, pixel_area_scale, composite=False,
                             cancellation=cancellation)
                return image
            except BaseException:
                image.close()
                raise

    def composite_native(
        self, image: Image.Image, *, cancellation: CancellationToken | None = None,
    ) -> None:
        """Composite into caller-owned native ground without a full water overlay."""
        if image.mode != "RGBA" or image.size != self.pool_area.size:
            raise ValueError("Native water composition requires matching RGBA ground.")
        _paint_water(image, self.pool_area, 1., composite=True, cancellation=cancellation)


def _paint_water(
    target: Image.Image, areas: Image.Image, pixel_area_scale: float, *, composite: bool,
    cancellation: CancellationToken | None,
) -> None:
    for top in range(0, target.height, WATER_RENDER_TILE_EDGE):
        bottom = min(top + WATER_RENDER_TILE_EDGE, target.height)
        for left in range(0, target.width, WATER_RENDER_TILE_EDGE):
            check_cancelled(cancellation)
            right = min(left + WATER_RENDER_TILE_EDGE, target.width)
            with closing(areas.crop((left, top, right, bottom))) as tile_areas:
                area_px2 = np.asarray(tile_areas) * pixel_area_scale
                fade = np.clip((area_px2 - HIDDEN_AREA_PX2)
                               / (OPAQUE_AREA_PX2 - HIDDEN_AREA_PX2), 0., 1.)
                alpha = np.rint(255 * fade * fade * (3 - 2 * fade)).astype(np.uint8)
                rgba = np.empty((bottom - top, right - left, 4), dtype=np.uint8)
                rgba[..., :3] = WATER_COLOUR
                rgba[..., 3] = alpha
                with closing(Image.fromarray(rgba)) as tile:
                    if composite:
                        target.alpha_composite(tile, (left, top))
                    else:
                        target.paste(tile, (left, top))
                del area_px2, fade, alpha, rgba
    check_cancelled(cancellation)


def prepare_water_display(
    surface_m: NDArray[np.float32], land_mask: NDArray[np.bool_],
) -> WaterDisplay | None:
    """Classify connected wet pixels once per result, not on wheel/pan events.

    Four-neighbour connectivity is a display convention, not a claim of water
    exchange: corner contact does not combine the visibility of separate pools.
    Rasterio and Shapely are existing adapters, used only on a binary wet mask.
    """
    if surface_m.ndim != 2 or surface_m.shape != land_mask.shape:
        raise ValueError("Water display requires matching two-dimensional water and land arrays.")
    wet = np.isfinite(surface_m) & land_mask
    if not np.any(wet):
        return None
    components = [(polygon, shape(polygon).area)
                  for polygon, _value in shapes(wet.astype(np.uint8), mask=wet, connectivity=4)]
    areas = rasterize(components, out_shape=wet.shape, fill=0, dtype="float32",
                      skip_invalid=False)
    return WaterDisplay(Image.fromarray(areas))
