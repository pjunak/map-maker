"""Geographic navigation independent of Tk and generated raster resolution."""

from dataclasses import dataclass
from math import isfinite

type Point = tuple[float, float]
type Rect = tuple[float, float, float, float]


@dataclass(slots=True)
class MapViewport:
    """A normalized map centre and magnification relative to the fitted overview."""

    centre: Point = (0.5, 0.5)
    zoom: float = 1.0

    def fit(self) -> None:
        self.centre = (0.5, 0.5)
        self.zoom = 1.0

    def rect(self, canvas: Point, world: Point) -> Rect:
        width, height = canvas
        scale = min(max(1., width - 36.) / world[0], max(1., height - 36.) / world[1])
        map_width, map_height = world[0] * scale * self.zoom, world[1] * scale * self.zoom
        left = width / 2 - self.centre[0] * map_width
        top = height / 2 - self.centre[1] * map_height
        return left, top, left + map_width, top + map_height

    def zoom_at(self, factor: float, anchor: Point, canvas: Point, world: Point) -> None:
        if not isfinite(factor) or factor <= 0:
            raise ValueError("Zoom factor must be finite and positive.")
        left, top, right, bottom = self.rect(canvas, world)
        position = ((anchor[0] - left) / (right - left), (anchor[1] - top) / (bottom - top))
        self.zoom = min(32., max(1., self.zoom * factor))
        new_left, new_top, new_right, new_bottom = self.rect(canvas, world)
        self.centre = self._bounded((
            position[0] - (anchor[0] - canvas[0] / 2) / (new_right - new_left),
            position[1] - (anchor[1] - canvas[1] / 2) / (new_bottom - new_top),
        ))

    def pan(self, delta: Point, canvas: Point, world: Point) -> None:
        left, top, right, bottom = self.rect(canvas, world)
        self.centre = self._bounded((self.centre[0] - delta[0] / (right - left),
                                     self.centre[1] - delta[1] / (bottom - top)))

    def visible_bounds(self, canvas: Point, world: Point) -> Rect:
        """Normalized geographic extent, suitable for a future generation request."""
        left, top, right, bottom = self.rect(canvas, world)
        return (max(0., -left / (right - left)), max(0., -top / (bottom - top)),
                min(1., (canvas[0] - left) / (right - left)),
                min(1., (canvas[1] - top) / (bottom - top)))

    @staticmethod
    def _bounded(point: Point) -> Point:
        return min(1., max(0., point[0])), min(1., max(0., point[1]))
