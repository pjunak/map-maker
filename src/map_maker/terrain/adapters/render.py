"""Render and export colour-graded terrain previews."""

import json
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, PngImagePlugin

from map_maker.terrain.adapters.palettes import (
    CARTOGRAPHIC_RELIEF_MAX_ELEVATION_M,
    CARTOGRAPHIC_RELIEF_PALETTE_ID,
    CARTOGRAPHIC_RELIEF_RGB,
    CARTOGRAPHIC_RELIEF_STOPS,
    OLERON_LAND_RGB,
    SCIENTIFIC_ELEVATION_PALETTE_ID,
)
from map_maker.terrain.adapters.water_display import (
    WATER_DISPLAY_ID,
    WaterDisplay,
    prepare_water_display,
)
from map_maker.terrain.domain import (
    ElevationPoint,
    EndpointGrid,
    TerrainBrushStroke,
    TerrainConstraint,
    TerrainRegion,
)
from map_maker.terrain.pipeline import GeneratedTerrain
from map_maker.terrain.pipeline.basin_flow import BasinCatchmentClass
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.diagnostics import (
    CUT_LIMIT,
    DEPRESSION,
    FINAL_ADJUSTMENT,
    REGION_TRANSITION,
)

type RenderStyle = Literal["cartographic", "scientific"]

GROUND_RENDER_TILE_EDGE = 256

_SCIENTIFIC_COLOUR_STOPS = np.linspace(0.0, 1.0, len(OLERON_LAND_RGB))


def _palette(style: RenderStyle) -> tuple[np.ndarray, np.ndarray, str]:
    if style == "cartographic":
        return (
            CARTOGRAPHIC_RELIEF_STOPS,
            CARTOGRAPHIC_RELIEF_RGB,
            CARTOGRAPHIC_RELIEF_PALETTE_ID,
        )
    return (
        _SCIENTIFIC_COLOUR_STOPS,
        OLERON_LAND_RGB,
        SCIENTIFIC_ELEVATION_PALETTE_ID,
    )


def elevation_palette_rgb(
    normalized: np.ndarray,
    *,
    style: RenderStyle = "cartographic",
) -> np.ndarray:
    """Map normalized elevations to the selected display palette in sRGB."""

    values = np.clip(np.asarray(normalized, dtype=np.float64), 0.0, 1.0)
    stops, colours, _palette_id = _palette(style)
    rgb = np.empty((*values.shape, 3), dtype=np.float64)
    for channel in range(3):
        rgb[..., channel] = np.interp(
            values,
            stops,
            colours[:, channel],
        )
    return rgb


def elevation_legend_colours(
    sample_count: int = 7,
    *,
    style: RenderStyle = "cartographic",
) -> tuple[str, ...]:
    """Return high-to-low hex samples matching the rendered elevation palette."""

    if sample_count < 2:
        raise ValueError("The elevation legend needs at least two colour samples.")
    normalized = np.linspace(1.0, 0.0, sample_count)
    rgb = np.rint(elevation_palette_rgb(normalized, style=style) * 255.0).astype(np.uint8)
    return tuple(f"#{red:02x}{green:02x}{blue:02x}" for red, green, blue in rgb)


def _illumination(
    elevation_m: NDArray[np.float32], grid: EndpointGrid, vertical_exaggeration: float,
) -> np.ndarray:
    elevation_km = np.nan_to_num(elevation_m, nan=0.0).astype(np.float64) / 1_000.0
    y_spacing = grid.y_spacing_km
    x_spacing = grid.x_spacing_km
    gradient_y, gradient_x = np.gradient(elevation_km, y_spacing, x_spacing)

    normal_x = -gradient_x * vertical_exaggeration
    normal_y = -gradient_y * vertical_exaggeration
    normal_z = np.ones_like(elevation_km)
    magnitude = np.sqrt(normal_x**2 + normal_y**2 + normal_z**2)
    normal_x /= magnitude
    normal_y /= magnitude
    normal_z /= magnitude

    azimuth = np.deg2rad(315.0)
    altitude = np.deg2rad(42.0)
    light_x = np.cos(altitude) * np.sin(azimuth)
    light_y = -np.cos(altitude) * np.cos(azimuth)
    light_z = np.sin(altitude)
    return normal_x * light_x + normal_y * light_y + normal_z * light_z


def _hillshade(
    elevation_m: NDArray[np.float32], grid: EndpointGrid, style: RenderStyle,
) -> np.ndarray:
    if style == "cartographic":
        illumination = _illumination(elevation_m, grid, vertical_exaggeration=18.0)
        return np.clip(0.52 + 0.72 * illumination, 0.22, 1.20)
    illumination = _illumination(elevation_m, grid, vertical_exaggeration=1.0)
    return np.clip(0.72 + 0.38 * illumination, 0.55, 1.08)


def _ground_rgba(
    elevation_m: NDArray[np.float32], land_mask: NDArray[np.bool_], grid: EndpointGrid,
    colour_scale_maximum_m: float, style: RenderStyle,
) -> NDArray[np.uint8]:
    normalized = np.clip(
        np.nan_to_num(elevation_m, nan=0.0) / colour_scale_maximum_m, 0.0, 1.0,
    )
    rgb = elevation_palette_rgb(normalized, style=style) * 255.0
    # Use the original grid's spacing. Reconstructing a tile extent would introduce
    # rounding differences into the slopes. The caller supplies stencil halos.
    rgb *= _hillshade(elevation_m, grid, style)[..., np.newaxis]
    rgb_uint8 = np.clip(rgb, 0, 255).astype(np.uint8)
    alpha = np.where(land_mask, 255, 0).astype(np.uint8)
    return np.dstack((rgb_uint8, alpha))


def render_ground_map(
    elevation_m: NDArray[np.float32], land_mask: NDArray[np.bool_], grid: EndpointGrid,
    maximum_elevation_m: float, *, style: RenderStyle = "scientific",
    cancellation: CancellationToken | None = None,
) -> Image.Image:
    """Shade full-resolution pixels with bounded scratch and one-node tile halos."""
    if elevation_m.shape != grid.shape or land_mask.shape != grid.shape:
        raise ValueError("Ground rendering requires arrays matching the supplied grid.")
    check_cancelled(cancellation)
    colour_scale_maximum_m = (
        CARTOGRAPHIC_RELIEF_MAX_ELEVATION_M if style == "cartographic" else maximum_elevation_m
    )
    image = Image.new("RGBA", (grid.width, grid.height))
    try:
        for top in range(0, grid.height, GROUND_RENDER_TILE_EDGE):
            bottom = min(top + GROUND_RENDER_TILE_EDGE, grid.height)
            sy, ey = max(0, top - 1), min(grid.height, bottom + 1)
            for left in range(0, grid.width, GROUND_RENDER_TILE_EDGE):
                check_cancelled(cancellation)
                right = min(left + GROUND_RENDER_TILE_EDGE, grid.width)
                sx, ex = max(0, left - 1), min(grid.width, right + 1)
                rgba = _ground_rgba(elevation_m[sy:ey, sx:ex], land_mask[sy:ey, sx:ex],
                                    grid, colour_scale_maximum_m, style)
                with (closing(Image.fromarray(rgba)) as tile,
                      closing(tile.crop((left - sx, top - sy, right - sx, bottom - sy))) as core):
                    image.paste(core, (left, top))
                del rgba
        check_cancelled(cancellation)
        _stops, _colours, palette_id = _palette(style)
        image.info["map-maker.render_style"] = style
        image.info["map-maker.colour_palette"] = palette_id
        image.info["map-maker.colour_scale_maximum_m"] = f"{colour_scale_maximum_m:g}"
        image.info["map-maker.water_visibility"] = "none"
        return image
    except BaseException:
        image.close()
        raise


def render_height_map_layers(
    terrain: GeneratedTerrain, *, style: RenderStyle = "cartographic",
    cancellation: CancellationToken | None = None,
) -> tuple[Image.Image, WaterDisplay | None]:
    """Transfer owned relief/area images to the caller only after both succeed."""
    image = render_ground_map(terrain.elevation_m, terrain.land_mask, terrain.grid,
                              terrain.settings.maximum_elevation_m, style=style,
                              cancellation=cancellation)
    water: WaterDisplay | None = None
    try:
        image.info["map-maker.water_visibility"] = (
            WATER_DISPLAY_ID if style == "cartographic" else "none")
        check_cancelled(cancellation)
        water = (prepare_water_display(terrain.water.surface_m, terrain.land_mask)
                 if style == "cartographic" else None)
        check_cancelled(cancellation)
        return image, water
    except BaseException:
        image.close()
        if water is not None:
            water.close()
        raise


def compose_height_map(
    image: Image.Image, water: WaterDisplay | None, *,
    cancellation: CancellationToken | None = None,
) -> Image.Image:
    """Copy borrowed ground for native export; viewport magnification has no effect."""
    check_cancelled(cancellation)
    result = image.copy()
    try:
        if water is not None:
            water.composite_native(result, cancellation=cancellation)
        return result
    except BaseException:
        result.close()
        raise


def render_height_map(
    terrain: GeneratedTerrain, *, style: RenderStyle = "cartographic",
    cancellation: CancellationToken | None = None,
) -> Image.Image:
    """Return owned native relief, composing water without duplicating the ground."""
    image, water = render_height_map_layers(terrain, style=style, cancellation=cancellation)
    try:
        if water is not None:
            water.composite_native(image, cancellation=cancellation)
        return image
    except BaseException:
        image.close()
        raise
    finally:
        if water is not None:
            water.close()


def _constraint_payload(constraint: TerrainConstraint) -> dict[str, object]:
    payload = asdict(constraint)
    if isinstance(constraint, ElevationPoint):
        payload["type"] = "elevation_point"
    elif isinstance(constraint, TerrainBrushStroke):
        payload["type"] = "terrain_brush"
    elif isinstance(constraint, TerrainRegion):
        payload["type"] = "terrain_region"
    else:
        payload["type"] = constraint.kind
    return payload


def save_height_map(image: Image.Image, terrain: GeneratedTerrain, destination: Path) -> None:
    """Save the rendered PNG with reproducibility settings in text metadata."""

    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("map-maker.source", terrain.source_name)
    metadata.add_text("map-maker.settings", json.dumps(asdict(terrain.settings), sort_keys=True))
    metadata.add_text(
        "map-maker.drainage_diagnostics",
        json.dumps(asdict(terrain.drainage.summary), sort_keys=True),
    )
    metadata.add_text(
        "map-maker.render_style",
        str(image.info.get("map-maker.render_style", "cartographic")),
    )
    metadata.add_text(
        "map-maker.colour_palette",
        str(image.info.get("map-maker.colour_palette", CARTOGRAPHIC_RELIEF_PALETTE_ID)),
    )
    metadata.add_text(
        "map-maker.colour_scale_maximum_m",
        str(
            image.info.get(
                "map-maker.colour_scale_maximum_m",
                f"{CARTOGRAPHIC_RELIEF_MAX_ELEVATION_M:g}",
            )
        ),
    )
    metadata.add_text("map-maker.water_visibility",
                      str(image.info.get("map-maker.water_visibility", "none")))
    metadata.add_text(
        "map-maker.constraints",
        json.dumps(
            [_constraint_payload(constraint) for constraint in terrain.constraints],
            sort_keys=True,
        ),
    )
    metadata.add_text(
        "map-maker.note",
        "Colour relief preview; the authoritative in-memory values are Float32 metres.",
    )
    image.save(destination, format="PNG", pnginfo=metadata)


def render_basin_overlay(
    terrain: GeneratedTerrain, size: tuple[int, int] | None = None,
) -> Image.Image:
    """Tint depression extents and trace the top eight representative spill routes."""
    analysis, grid = terrain.drainage, terrain.routing_grid
    width, height = size or (grid.width, grid.height)
    labels = analysis.basin_labels
    rgba = np.zeros((*labels.shape, 4), dtype=np.uint8)
    rgba[labels > 0] = (165, 112, 230, 65)
    padded = np.pad(labels, 1)
    edge = np.zeros(labels.shape, dtype=np.bool_)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        edge |= labels != padded[1 + dr:1 + dr + grid.height,
                                 1 + dc:1 + dc + grid.width]
    rgba[edge & (labels > 0)] = (200, 148, 255, 170)
    with closing(Image.fromarray(rgba)) as source:
        image = source.resize((width, height), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(image)
    x_scale = (width - 1) / max(1, grid.width - 1)
    y_scale = (height - 1) / max(1, grid.height - 1)

    def position(flat_index: int) -> tuple[float, float]:
        row, column = divmod(flat_index, grid.width)
        return column * x_scale, row * y_scale

    for basin in analysis.summary.basin_candidates[:8]:
        index = basin.deepest_flat_index
        path = [position(index)]
        while index != basin.outlet.spill_flat_index:
            index = int(analysis.receivers.flat[index])
            if index < 0:
                raise RuntimeError("The basin spill must lie on its conditioned route.")
            path.append(position(index))
        if len(path) > 1:
            draw.line(path, fill=(255, 216, 90, 240), width=1)
        x, y = path[0]
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), outline="white", width=1)
        x, y = path[-1]
        draw.polygon(((x, y - 4), (x + 4, y), (x, y + 4), (x - 4, y)),
                     outline=(255, 216, 90, 255))
        text = f"B{basin.basin_id}"
        box = draw.textbbox((0, 0), text)
        label_width = box[2] - box[0]
        label_height = box[3] - box[1]
        tx = max(0., min(x + 6, width - label_width - 2))
        ty = max(0., min(y - 12, height - label_height - 4))
        draw.text((tx, ty), text, fill=(255, 234, 167, 255),
                  stroke_width=1, stroke_fill=(24, 33, 43, 255))
    return image


def render_drainage_review(terrain: GeneratedTerrain) -> Image.Image:
    """Show channel context and basin geometry on the same canonical nodes."""
    routing = terrain.routing
    mask = terrain.routing_land_mask
    width, height = terrain.routing_grid.width, terrain.routing_grid.height
    scale = max(1, 640 // max(width, height))
    map_width, map_height = width * scale, height * scale
    panel_width, panel_height = max(512, map_width), map_height + 32
    image = Image.new("RGB", (panel_width * 2 + 24, panel_height * 2 + 150), "#18212b")
    draw = ImageDraw.Draw(image)
    context = terrain.routing_conflicts
    summary = context.summary
    titles = ("Authored routing surface", "Finished terrain: channels and basin catchments",
              "Conflict context", "Depression extents and spill candidates")
    fields = (routing.source_elevation_m, terrain.routing_final_elevation_m,
              terrain.routing_final_elevation_m, terrain.routing_final_elevation_m)
    for index, field in enumerate(fields):
        left = 8 + (index % 2) * (panel_width + 8)
        top = (index // 2) * panel_height
        draw.text((left, top + 8), titles[index], fill="white")
        grey = np.rint(45 + 150 * np.clip(field / terrain.settings.maximum_elevation_m, 0, 1))
        rgb = np.repeat(grey[..., None], 3, axis=2).astype(np.uint8)
        rgb[~mask] = (24, 33, 43)
        if index < 3:
            rgb[routing.channel_mask] = (45, 185, 255)
            if index:
                rgb[context.flags != 0] = (255, 95, 65)
        if index == 2:
            # Later colours win visually; the numeric archive retains every bit.
            for bit, colour in ((CUT_LIMIT, (240, 80, 190)),
                                (DEPRESSION, (170, 130, 255)),
                                (FINAL_ADJUSTMENT, (255, 150, 65)),
                                (REGION_TRANSITION, (255, 215, 80))):
                rgb[(context.flags & bit) != 0] = colour
        with closing(Image.fromarray(rgb)) as panel:
            resized = panel.resize((map_width, map_height), Image.Resampling.NEAREST)
            image.paste(resized, (left, top + 28))
            resized.close()
        if index == 1:
            with closing(render_basin_catchment_overlay(
                terrain, (map_width, map_height),
            )) as overlay:
                image.paste(overlay, (left, top + 28), overlay)
        if index < 3:
            for basin in terrain.water.review.basins:
                points = [(left + x * (map_width - 1), top + 28 + y * (map_height - 1))
                          for x, y in basin.source.points]
                colour = "#7cddd2" if basin.source.kind == "lake" else "#d3b17d"
                draw.line(points, fill=colour, width=1)
                draw.text(points[0], f"A{basin.intent_id}", fill=colour)
        if index in (1, 2):
            with closing(render_basin_outflow_overlay(terrain, (map_width, map_height))) as overlay:
                image.paste(overlay, (left, top + 28), overlay)
        if index == 3:
            with closing(render_basin_overlay(terrain, (map_width, map_height))) as overlay:
                image.paste(overlay, (left, top + 28), overlay)
    lines = (
        "Blue: planned. Red: uphill. Context priority: yellow transition > orange final "
        "adjustment > purple depression > pink cut limit.",
        f"{summary.uphill_edge_count} uphill edges; overlapping contexts: "
        f"{summary.insufficient_cut_edge_count} cut limit, "
        f"{summary.final_adjustment_edge_count} final adjustment, "
        f"{summary.region_transition_edge_count} transition, "
        f"{summary.depression_edge_count} depression; {summary.unclassified_edge_count} other.",
        "A: cyan lake / tan dry-basin retention. B: purple depressions, white deepest nodes, "
        "yellow candidate exits. Teal: connected lake outflow.",
        "Basin fills: cyan water / green land feed a connected outlet; amber stays retained. "
        "Footprint nodes only, not full upstream catchments.",
        "Orange dots: fine boundary openings. Red diamonds: water barriers or ground climbs. "
        "Sampled evidence; stable lake levels are not modeled.",
        f"Shared review grid: {width} x {height}. Natural-basin escape candidates ignore "
        "authored retention. Connected outflows use sampled finished terrain.",
    )
    for row, line in enumerate(lines):
        draw.text((8, panel_height * 2 + 10 + 21 * row), line, fill="white")
    return image


def render_basin_catchment_overlay(
    terrain: GeneratedTerrain, size: tuple[int, int],
) -> Image.Image:
    """Colour canonical footprint nodes without interpolating categorical outcomes."""
    classes = terrain.basin_outflow.catchment_class
    palette = np.zeros((len(BasinCatchmentClass), 4), dtype=np.uint8)
    palette[BasinCatchmentClass.RETAINED] = (239, 171, 87, 165)
    palette[BasinCatchmentClass.COLLECTED_WATER] = (70, 182, 236, 200)
    palette[BasinCatchmentClass.COLLECTED_DRY] = (132, 218, 128, 175)
    width, height = size
    # Both the review grid and authored overlays use endpoints, not pixel centres.
    columns = np.rint(np.linspace(0, classes.shape[1] - 1, width, dtype=np.float64)).astype(np.intp)
    rows = np.rint(np.linspace(0, classes.shape[0] - 1, height, dtype=np.float64)).astype(np.intp)
    return Image.fromarray(palette[classes[rows[:, None], columns[None, :]]])


def render_basin_outflow_overlay(
    terrain: GeneratedTerrain, size: tuple[int, int],
) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    grid = terrain.routing_grid
    x0, y0, x1, y1 = grid.extent_km

    def pixel(point: tuple[float, float]) -> tuple[float, float]:
        return ((point[0] - x0) * (width - 1) / (x1 - x0),
                (point[1] - y0) * (height - 1) / (y1 - y0))

    for record in terrain.water.review.basins:
        shoreline = record.shoreline
        if shoreline is not None:
            for index in shoreline.uncontrolled_low_sample_indices:
                px, py = pixel(shoreline.profile.positions_km[index])
                draw.ellipse((px - 3, py - 3, px + 3, py + 3),
                             fill=(255, 160, 60, 255), outline=(24, 33, 43, 255))
        route = record.outlet_route
        barriers = ([link.maximum_position_km for link in record.wet_links.links if link.blocked]
                    if record.wet_links is not None else [])
        if record.dry_links is not None:
            candidates = [(link.maximum_uphill_excursion_m, link.crest_position_km)
                          for link in record.dry_links.links if link.blocked]
            candidates.extend((path.maximum_uphill_excursion_m, path.crest_position_km)
                              for path in record.dry_links.path_barriers)
            selected: list[tuple[float, float]] = []
            # Thousands of rejected candidates can exist; show the strongest
            # spatially separated witnesses and retain every one in diagnostics.
            for _rise, position in sorted(candidates, key=lambda item: -item[0]):
                px, py = pixel(position)
                if any((px-x)**2 + (py-y)**2 < 16**2 for x, y in selected):
                    continue
                selected.append((px, py))
                barriers.append(position)
                if len(selected) == 12:
                    break
        if route is not None and "outlet_connection_above_water" in route.issues:
            assert route.connection_profile is not None
            assert route.connection_profile.maximum_position_km is not None
            barriers.append(route.connection_profile.maximum_position_km)
        if route is not None and "outlet_downstream_uphill" in route.issues:
            assert route.downstream is not None
            assert route.downstream.rise_to_sample_index is not None
            barriers.append(route.downstream.profile.positions_km[
                route.downstream.rise_to_sample_index])
        for position in barriers:
            px, py = pixel(position)
            draw.polygon(((px, py - 4), (px + 4, py), (px, py + 4), (px - 4, py)),
                         fill=(255, 95, 65, 255), outline="white")
        if record.outlet_connection != "connected":
            continue
        assert record.outlet_route is not None and record.source.outlet is not None
        x, y = record.source.outlet
        points = [(x * (width - 1), y * (height - 1))]
        for node in record.outlet_route.path_flat_indices:
            row, column = divmod(node, grid.width)
            points.append((column * (width - 1) / (grid.width - 1),
                           row * (height - 1) / (grid.height - 1)))
        draw.line(points, fill=(65, 235, 195, 255), width=2)
    return image


def render_drainage_overlay(
    terrain: GeneratedTerrain, size: tuple[int, int] | None = None,
) -> Image.Image:
    """Transparent planned D8 edges; red marks rises on the final field."""
    grid = terrain.routing_grid
    routing = terrain.routing
    width, height = size or (grid.width, grid.height)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    x_scale, y_scale = (width - 1) / (grid.width - 1), (height - 1) / (grid.height - 1)
    rises = terrain.routing_conflicts.rise_m
    edges = routing.channel_mask & (routing.receivers >= 0)
    for uphill in (False, True):
        selected = edges & ((rises > terrain.routing_agreement.elevation_tolerance_m) == uphill)
        for row, column in np.argwhere(selected):
            target_row, target_column = divmod(int(routing.receivers[row, column]), grid.width)
            draw.line((int(column) * x_scale, int(row) * y_scale,
                       target_column * x_scale, target_row * y_scale),
                      width=1,
                      fill=(255, 95, 65, 255) if uphill else (45, 185, 255, 230))
    with closing(render_basin_outflow_overlay(terrain, (width, height))) as outflow:
        image.alpha_composite(outflow)
    return image
