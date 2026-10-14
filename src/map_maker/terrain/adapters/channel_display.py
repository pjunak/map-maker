"""Viewport-native channel review, with connected scale selection and bounded scratch."""

from contextlib import closing
from dataclasses import dataclass
from math import isfinite, sqrt

from PIL import Image, ImageDraw

from map_maker.terrain.pipeline.channel_network import (
    ChannelNetwork,
    Point,
    build_channel_network,
)
from map_maker.terrain.pipeline.generate import GeneratedTerrain

CHANNEL_DISPLAY_ID = "connected-catchment-screen-scale@1"
CHANNEL_RENDER_TILE_EDGE = 256
_ANTIALIAS = 3
_HALO = 5
# These are cartographic screen-area thresholds, not river widths or discharge.
HIDDEN_CATCHMENT_SPAN_PX = 64.0
OPAQUE_CATCHMENT_SPAN_PX = 112.0

type Rect = tuple[float, float, float, float]


def reach_opacity(area_km2: float, pixels_per_km2: float, *, all_channels: bool = False) -> int:
    if all_channels:
        return 230
    span = sqrt(max(0., area_km2*pixels_per_km2))
    fade = min(1., max(0., (span-HIDDEN_CATCHMENT_SPAN_PX)
                         / (OPAQUE_CATCHMENT_SPAN_PX-HIDDEN_CATCHMENT_SPAN_PX)))
    return round(230*fade*fade*(3.-2.*fade))


def _compact(points: tuple[Point, ...]) -> tuple[Point, ...]:
    """Remove only collinear forward vertices; keep endpoints and every bend."""
    result = [points[0]]
    for a, b, c in zip(points, points[1:], points[2:], strict=False):
        ab, bc = (b[0]-a[0], b[1]-a[1]), (c[0]-b[0], c[1]-b[1])
        # Metric coordinate roundoff must not remove actual D8 direction changes.
        if abs(ab[0]*bc[1]-ab[1]*bc[0]) > 1e-10*(abs(ab[0])+abs(ab[1]))**2:
            result.append(b)
    result.append(points[-1])
    return tuple(result)


@dataclass(frozen=True, slots=True)
class _Stroke:
    points: tuple[Point, ...]
    colour: tuple[int, int, int, int]
    width: float
    bounds: Rect


@dataclass(frozen=True, slots=True)
class ChannelDisplay:
    network: ChannelNetwork
    uphill_edges: tuple[tuple[Point, Point], ...]
    paths: tuple[tuple[Point, ...], ...]

    def _scale(self, rect: Rect) -> tuple[float, float]:
        left, top, right, bottom = rect
        if not all(isfinite(v) for v in rect) or right <= left or bottom <= top:
            raise ValueError("Channel viewport needs a finite positive map rectangle.")
        x0, y0, x1, y1 = self.network.grid.extent_km
        return (right-left)/(x1-x0), (bottom-top)/(y1-y0)

    def visible_reach_count(self, rect: Rect, *, all_channels: bool = False) -> int:
        """Whole-map scale selection count, independent of cropping or panning."""
        sx, sy = self._scale(rect)
        return sum(reach_opacity(reach.contributing_area_km2, sx*sy,
                                 all_channels=all_channels) > 0
                   for reach in self.network.reaches)

    def render(
        self, rect: Rect, size: tuple[int, int], *, all_channels: bool = False,
    ) -> Image.Image:
        """Draw fixed-width strokes in output pixels, never magnify a cached raster.

        Red sampled conflicts are always included, even on hidden tributaries.
        Supersampling scratch is one haloed tile, not a zoom-sized map image.
        """
        sx, sy = self._scale(rect)
        x0, y0, _x1, _y1 = self.network.grid.extent_km
        strokes: list[_Stroke] = []
        def append(
            points: tuple[Point, ...], colour: tuple[int, int, int, int], width: float,
        ) -> None:
            screen = tuple((rect[0]+(x-x0)*sx, rect[1]+(y-y0)*sy) for x, y in points)
            xs, ys = zip(*screen, strict=True)
            bounds = min(xs), min(ys), max(xs), max(ys)
            if (bounds[2] >= -_HALO and bounds[0] <= size[0]+_HALO
                    and bounds[3] >= -_HALO and bounds[1] <= size[1]+_HALO):
                strokes.append(_Stroke(screen, colour, width, bounds))
        for reach, points in zip(self.network.reaches, self.paths, strict=True):
            alpha = reach_opacity(reach.contributing_area_km2, sx*sy, all_channels=all_channels)
            if alpha:
                append(points, (45, 185, 255, alpha), min(2.2, 1.+.3*(reach.stream_order-1)))
        for points in self.uphill_edges:
            append(points, (255, 95, 65, 255), 1.6)
        strokes.sort(key=lambda stroke: (stroke.colour[3], stroke.width))
        image = Image.new("RGBA", size)
        try:
            for top in range(0, size[1], CHANNEL_RENDER_TILE_EDGE):
                bottom = min(top+CHANNEL_RENDER_TILE_EDGE, size[1])
                for left in range(0, size[0], CHANNEL_RENDER_TILE_EDGE):
                    right = min(left+CHANNEL_RENDER_TILE_EDGE, size[0])
                    _paint_tile(image, strokes, (left, top, right, bottom))
            image.info["map-maker.channel_display"] = CHANNEL_DISPLAY_ID
            return image
        except BaseException:
            image.close()
            raise


def _paint_tile(
    image: Image.Image, strokes: list[_Stroke], rect: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = rect
    width, height = right-left+2*_HALO, bottom-top+2*_HALO
    selected = [s for s in strokes if s.bounds[2] >= left-_HALO and s.bounds[0] <= right+_HALO
                and s.bounds[3] >= top-_HALO and s.bounds[1] <= bottom+_HALO]
    if not selected:
        return
    with closing(Image.new("RGBA", (width*_ANTIALIAS, height*_ANTIALIAS))) as tile:
        draw = ImageDraw.Draw(tile)
        for stroke in selected:
            points = [((x-left+_HALO)*_ANTIALIAS, (y-top+_HALO)*_ANTIALIAS)
                      for x, y in stroke.points]
            draw.line(points, fill=stroke.colour, width=round(stroke.width*_ANTIALIAS),
                      joint="curve")
        with (closing(tile.resize((width, height), Image.Resampling.LANCZOS)) as reduced,
              closing(reduced.crop((_HALO, _HALO, width-_HALO, height-_HALO))) as core):
            image.paste(core, (left, top))


def prepare_channel_display(terrain: GeneratedTerrain) -> ChannelDisplay:
    """Prepare graph and geometry once per generated result, independently of zoom."""
    network = build_channel_network(
        terrain.routing, terrain.routing_land_mask, terrain.routing_grid)
    flagged = (terrain.routing_conflicts.rise_m.ravel()
               > terrain.routing_agreement.elevation_tolerance_m)
    uphill: list[tuple[Point, Point]] = []
    for reach in network.reaches:
        for index, donor in enumerate(reach.nodes[:-1]):
            if flagged[donor]:
                uphill.append((reach.points_km[index], reach.points_km[index+1]))
    return ChannelDisplay(network, tuple(uphill),
                          tuple(_compact(r.points_km) for r in network.reaches))
