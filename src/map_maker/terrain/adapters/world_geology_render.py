"""Inspectable geology coverage colours; source/context images remain independent."""

from PIL import Image, ImageDraw

from map_maker.terrain.adapters.world_render import OCEAN
from map_maker.terrain.domain.world_geology import GeologicalSetting
from map_maker.terrain.pipeline.world_geology import GeologyCoverage
from map_maker.terrain.viewport import MapViewport

SETTING_COLOURS: dict[GeologicalSetting, str] = {
    "unspecified": "#87999b",
    "stable-interior": "#84bd9b",
    "active-belt": "#dc986c",
    "rift": "#c78cbf",
    "volcanic": "#dcce78",
    "sedimentary-basin": "#86b3d3",
}


def render_geology(
    coverage: GeologyCoverage,
    viewport: MapViewport,
    size: tuple[int, int],
) -> Image.Image:
    width, height = size
    if width <= 0 or height <= 0 or width * height > 16_777_216:
        raise ValueError("Geology preview must contain 1-16,777,216 pixels.")
    frame = coverage.recipe.world.frame
    left, top, right, bottom = viewport.rect(size, (frame.width, frame.height))
    sx, sy = (right - left) / frame.width, (bottom - top) / frame.height
    image = Image.new("RGB", size, OCEAN)
    try:
        for region in coverage.regions:
            for component in region.components:
                rings = [
                    [
                        (left + (x - frame.bounds[0]) * sx, top + (y - frame.bounds[1]) * sy)
                        for x, y in ring
                    ]
                    for ring in (component.exterior, *component.holes)
                ]
                x0 = max(0, int(min(x for x, _ in rings[0])))
                y0 = max(0, int(min(y for _, y in rings[0])))
                x1 = min(width, int(max(x for x, _ in rings[0])) + 2)
                y1 = min(height, int(max(y for _, y in rings[0])) + 2)
                if x1 <= x0 or y1 <= y0:
                    continue
                with Image.new("L", (x1 - x0, y1 - y0)) as mask:
                    painter = ImageDraw.Draw(mask)
                    for i, ring in enumerate(rings):
                        painter.polygon(
                            [(x - x0, y - y0) for x, y in ring], fill=255 if i == 0 else 0
                        )
                    image.paste(SETTING_COLOURS[region.profile.setting], (x0, y0, x1, y1), mask)
        return image
    except BaseException:
        image.close()
        raise
