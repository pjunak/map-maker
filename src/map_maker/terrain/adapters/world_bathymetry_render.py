"""Cell-faithful ocean-floor and numerical-support views, separate from land DEMs."""

from typing import Literal

import numpy as np
from PIL import Image, ImageDraw

from map_maker.terrain.adapters.world_render import OCEAN
from map_maker.terrain.pipeline.world_bathymetry import WorldBathymetry
from map_maker.terrain.viewport import MapViewport

type BathymetryLayer = Literal["Ocean floor", "Distance error", "Resolution support"]
BATHYMETRY_LAYERS: tuple[BathymetryLayer, ...] = (
    "Ocean floor",
    "Distance error",
    "Resolution support",
)


def bathymetry_image(result: WorldBathymetry, layer: BathymetryLayer) -> Image.Image:
    sampled = np.isfinite(result.bed_elevation_m)
    water = result.centre_water_body != 0
    pixels = np.full((*sampled.shape, 3), (157, 177, 119), dtype=np.uint8)
    pixels[water] = (72, 80, 88)
    if layer == "Ocean floor":
        value = np.nan_to_num(-result.bed_elevation_m / result.inputs.settings.basin_depth_m)
        low, high = np.array((154, 215, 208)), np.array((18, 39, 90))
    elif layer == "Distance error":
        # Fixed depth-normalized scale, labelled in the UI; zero is not model certainty.
        value = np.nan_to_num(result.distance_depth_error_m / result.inputs.settings.basin_depth_m)
        low, high = np.array((37, 73, 88)), np.array((244, 172, 75))
    else:
        value = (result.context.support_flags != 0).astype(np.float64)
        low, high = np.array((37, 73, 88)), np.array((244, 172, 75))
    colour = np.rint(low + np.clip(value, 0, 1)[..., None] * (high - low)).astype(np.uint8)
    pixels[sampled] = colour[sampled]
    if layer == "Resolution support":
        # Include unsupported water/land cells even if a selected ocean has no centre sample.
        pixels[result.context.support_flags != 0] = (244, 172, 75)
    return Image.fromarray(pixels)


def render_bathymetry(
    result: WorldBathymetry,
    viewport: MapViewport,
    size: tuple[int, int],
    layer: BathymetryLayer = "Ocean floor",
) -> Image.Image:
    if min(size) <= 0 or size[0] * size[1] > 16_777_216:
        raise ValueError("Bathymetry preview must contain 1-16,777,216 pixels.")
    frame = result.context.grid.frame
    left, top, right, bottom = viewport.rect(size, (frame.width, frame.height))
    with bathymetry_image(result, layer) as source:
        sx, sy = source.width / (right - left), source.height / (bottom - top)
        preview = source.transform(
            size,
            Image.Transform.AFFINE,
            (sx, 0, -left * sx, 0, sy, -top * sy),
            resample=Image.Resampling.NEAREST,
            fillcolor=OCEAN,
        )
    painter = ImageDraw.Draw(preview)
    sx, sy = (right - left) / frame.width, (bottom - top) / frame.height
    for feature in result.context.world.land:
        for component in feature.components:
            for ring in (component.exterior, *component.holes):
                painter.line(
                    [
                        (left + (x - frame.bounds[0]) * sx, top + (y - frame.bounds[1]) * sy)
                        for x, y in ring
                    ],
                    fill=(24, 49, 57),
                    width=1,
                )
    return preview
