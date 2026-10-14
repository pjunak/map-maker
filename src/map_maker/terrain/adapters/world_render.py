"""Bounded world-source previews with per-shape hole masks and stable owner colours."""

from colorsys import hls_to_rgb

from PIL import Image, ImageDraw

from map_maker.terrain.domain.world import Bounds, WorldAssignment, WorldSource
from map_maker.terrain.viewport import MapViewport

OCEAN = "#10282e"


def owner_colours(assignments: tuple[WorldAssignment, ...]) -> dict[str, str]:
    owners = sorted({a.continent_id for a in assignments if a.continent_id is not None})
    colours: dict[str, str] = {}
    for index, owner in enumerate(owners):
        # Evenly separated hues stay reproducible across source/assignment order.
        # Colours are a view of the owner set, never persistent semantic identity.
        red, green, blue = hls_to_rgb((index / len(owners) + 0.12) % 1, 0.68, 0.34)
        colours[owner] = f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"
    return colours


def render_world_source(
    source: WorldSource,
    bounds: Bounds,
    assignments: tuple[WorldAssignment, ...],
    viewport: MapViewport,
    size: tuple[int, int],
    selected: frozenset[str] = frozenset(),
    *,
    show_excluded: bool = True,
) -> Image.Image:
    width, height = size
    if width <= 0 or height <= 0 or width * height > 16_777_216:
        raise ValueError("World preview must contain 1-16,777,216 pixels.")
    image = Image.new("RGB", size, OCEAN)
    left, top, right, bottom = viewport.rect(size, (bounds[2] - bounds[0], bounds[3] - bounds[1]))
    sx = (right - left) / (bounds[2] - bounds[0])
    sy = (bottom - top) / (bounds[3] - bounds[1])
    owners = {a.feature_id: a for a in assignments}
    colours = owner_colours(assignments)
    try:
        for feature in sorted(source.features, key=lambda f: (f.id in selected, f.id)):
            assignment = owners.get(feature.id)
            excluded = assignment is not None and assignment.role == "exclude"
            if excluded and not show_excluded:
                continue
            colour = (
                "#34494d"
                if excluded
                else colours.get(assignment.continent_id or "", "#78888a")
                if assignment
                else "#78888a"
            )
            for component in feature.components:
                # Source-linear wraps are preview copies; original vectors remain untouched.
                for offset in (-(bounds[2] - bounds[0]), 0.0, bounds[2] - bounds[0]):
                    rings = [
                        [
                            (left + (x + offset - bounds[0]) * sx, top + (y - bounds[1]) * sy)
                            for x, y in ring
                        ]
                        for ring in (component.exterior, *component.holes)
                    ]
                    outer = rings[0]
                    x0 = max(0, int(left), int(min(x for x, _ in outer)))
                    y0 = max(0, int(top), int(min(y for _, y in outer)))
                    x1 = min(width, int(right) + 1, int(max(x for x, _ in outer)) + 2)
                    y1 = min(height, int(bottom) + 1, int(max(y for _, y in outer)) + 2)
                    if x1 <= x0 or y1 <= y0:
                        continue
                    with Image.new("L", (x1 - x0, y1 - y0)) as mask:
                        painter = ImageDraw.Draw(mask)
                        for index, ring in enumerate(rings):
                            painter.polygon(
                                [(x - x0, y - y0) for x, y in ring], fill=255 if index == 0 else 0
                            )
                        image.paste(colour, (x0, y0, x1, y1), mask)
                    outline = "#f5ce74" if feature.id in selected else "#c9dfd6"
                    if excluded:
                        outline = "#647d80"
                    with Image.new("L", (x1 - x0, y1 - y0)) as edge_mask:
                        painter = ImageDraw.Draw(edge_mask)
                        for ring in rings:
                            painter.line(
                                [(x - x0, y - y0) for x, y in ring],
                                fill=255,
                                width=2 if feature.id in selected else 1,
                            )
                        image.paste(outline, (x0, y0, x1, y1), edge_mask)
        return image
    except BaseException:
        image.close()
        raise
