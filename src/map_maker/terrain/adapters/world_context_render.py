"""Pixel-faithful context previews; zoom never invents geographic resolution."""

from colorsys import hls_to_rgb
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw

from map_maker.terrain.adapters.world_render import OCEAN
from map_maker.terrain.domain.world_context import (
    MIXED_COAST,
    SPLIT_WATER,
    SUBCELL_LAND,
    SUBCELL_WATER,
)
from map_maker.terrain.pipeline.world_context import WorldContext
from map_maker.terrain.viewport import MapViewport

type ContextLayer = Literal[
    "Land coverage",
    "Connected water",
    "Resolution support",
    "Water openings",
    "Shore distance",
    "Water exposure",
    "Exposure support",
    "Water connectivity",
]
CONTEXT_LAYERS: tuple[ContextLayer, ...] = (
    "Land coverage",
    "Connected water",
    "Resolution support",
    "Water openings",
    "Shore distance",
    "Water exposure",
    "Exposure support",
    "Water connectivity",
)


def context_image(
    context: WorldContext,
    layer: ContextLayer,
    bearing: int = 0,
) -> Image.Image:
    if type(bearing) is not int or not 0 <= bearing < 8:
        raise ValueError("Context exposure bearing must be an index from 0 to 7.")
    land = np.array((157, 177, 119), dtype=np.float64)
    water = np.array((24, 70, 89), dtype=np.float64)
    fraction = context.land_fraction[..., None]
    rgb = water * (1 - fraction) + land * fraction
    if layer == "Connected water":
        palette = np.zeros((len(context.water_bodies) + 1, 3), dtype=np.float64)
        palette[0] = water
        for body in context.water_bodies:
            palette[body.id] = (
                np.array(hls_to_rgb((0.54 + (body.id - 1) * 0.618034) % 1, 0.5, 0.5)) * 255
            )
        rgb = palette[context.water_body] * (1 - fraction) + land * fraction
    elif layer == "Resolution support":
        flags = context.support_flags
        rgb[(flags & MIXED_COAST) != 0] = (231, 181, 83)
        rgb[(flags & SUBCELL_LAND) != 0] = (221, 135, 82)
        rgb[(flags & SUBCELL_WATER) != 0] = (110, 200, 224)
        rgb[(flags & SPLIT_WATER) != 0] = (201, 130, 203)
    elif layer == "Water connectivity":
        pieces = np.diff(context.connectivity.cell_offsets).reshape(context.grid.shape)
        rgb[pieces == 0] = land
        rgb[pieces == 1] = (52, 141, 176)
        rgb[pieces > 1] = (241, 166, 69)
        graph = context.connectivity
        unresolved = np.isin(graph.water_body, graph.fragmented_bodies)
        cells = np.repeat(np.arange(pieces.size), pieces.ravel())
        rgb.reshape(-1, 3)[cells[unresolved]] = (214, 111, 176)
    elif layer in ("Shore distance", "Water exposure", "Exposure support"):
        if layer == "Shore distance":
            value = np.nan_to_num(np.clip(context.shore_distance_km / 3000, 0, 1))
            low, high = (229, 220, 178), (102, 52, 111)
        elif layer == "Water exposure":
            value = context.water_exposure[bearing]
            low, high = (193, 156, 104), (47, 133, 185)
        else:
            value = context.exposure_mixed_support[bearing]
            low, high = (36, 69, 76), (238, 177, 73)
        rgb = np.array(low) + value[..., None] * (np.array(high) - np.array(low))
        if layer == "Shore distance":
            rgb[np.isnan(context.shore_distance_km)] = (90, 90, 90)
    pixels = np.rint(rgb).astype(np.uint8)
    if layer == "Water openings":
        # Three pixels per cell expose shared faces when zoomed; no interpolation.
        pixels = np.repeat(np.repeat(pixels, 3, axis=0), 3, axis=1)
        for widths, maximum, axis in (
            (context.east_opening_km, context.grid.north_south_spacing_km, "east"),
            (
                context.south_opening_km,
                np.array(
                    [context.grid.south_edge_length_km(r) for r in range(context.grid.shape[0])]
                )[:, None],
                "south",
            ),
        ):
            colours = np.full((*widths.shape, 3), (10, 27, 33), dtype=np.uint8)
            colours[widths > 0] = (52, 141, 176)
            colours[(widths > 0) & (widths < maximum * (1 - 1e-9))] = (241, 166, 69)
            if axis == "east":
                pixels[:, 2::3] = np.repeat(colours, 3, axis=0)
                pixels[:, 0] = np.repeat(colours[:, -1], 3, axis=0)
            else:
                pixels[2::3, :] = np.repeat(colours, 3, axis=1)
        pixels[0, :] = (10, 27, 33)
    return Image.fromarray(pixels)


def render_world_context(
    context: WorldContext,
    viewport: MapViewport,
    size: tuple[int, int],
    layer: ContextLayer,
    bearing: int = 0,
) -> Image.Image:
    if min(size) <= 0 or size[0] * size[1] > 16_777_216:
        raise ValueError("World preview must contain 1-16,777,216 pixels.")
    frame = context.grid.frame
    left, top, right, bottom = viewport.rect(size, (frame.width, frame.height))
    with context_image(context, layer, bearing) as source:
        sx, sy = source.width / (right - left), source.height / (bottom - top)
        preview = source.transform(
            size,
            Image.Transform.AFFINE,
            (sx, 0, -left * sx, 0, sy, -top * sy),
            resample=Image.Resampling.NEAREST,
            fillcolor=OCEAN,
        )
    if layer in ("Shore distance", "Water exposure", "Exposure support", "Water connectivity"):
        # Source outlines are a geographic reference; they do not refine the field.
        painter = ImageDraw.Draw(preview)
        sx, sy = (right - left) / frame.width, (bottom - top) / frame.height
        for feature in context.world.land:
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
