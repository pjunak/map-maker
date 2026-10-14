"""Explicit local-plane conversion and endpoint-node grid contracts.

These values do not assign a world CRS or a planetary scale to local inputs.
"""

from dataclasses import dataclass
from math import isfinite
from typing import ClassVar

type Bounds = tuple[float, float, float, float]
type Coordinate = tuple[float, float]


def _positive(value: float, label: str) -> None:
    if isinstance(value, bool) or not isfinite(value) or value <= 0.0:
        raise ValueError(f"{label} must be positive and finite.")


def _bounds(bounds: Bounds) -> None:
    if len(bounds) != 4 or any(isinstance(v, bool) or not isfinite(v) for v in bounds):
        raise ValueError("Bounds must contain four finite coordinates.")
    _positive(bounds[2] - bounds[0], "Bounds width")
    _positive(bounds[3] - bounds[1], "Bounds height")


def _count(value: object, minimum: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}.")


def _point(point: Coordinate) -> None:
    if len(point) != 2 or any(isinstance(v, bool) or not isfinite(v) for v in point):
        raise ValueError("Point must contain two finite coordinates.")


@dataclass(frozen=True, slots=True)
class LocalMetricFrame:
    """Source-right/source-down plane, scaled by its longest dimension."""

    source_bounds: Bounds
    longest_side_km: float
    model_id: ClassVar[str] = "local-svg-plane@1"

    def __post_init__(self) -> None:
        _bounds(self.source_bounds)
        _positive(self.longest_side_km, "Longest side")
        _positive(self.km_per_source_unit, "Source scale")
        _positive(self.width_km, "Local width")
        _positive(self.height_km, "Local height")

    @property
    def km_per_source_unit(self) -> float:
        x0, y0, x1, y1 = self.source_bounds
        return self.longest_side_km / max(x1 - x0, y1 - y0)

    @property
    def width_km(self) -> float:
        return (self.source_bounds[2] - self.source_bounds[0]) * self.km_per_source_unit

    @property
    def height_km(self) -> float:
        return (self.source_bounds[3] - self.source_bounds[1]) * self.km_per_source_unit

    @property
    def extent_km(self) -> Bounds:
        return 0.0, 0.0, self.width_km, self.height_km

    def source_to_local(self, point: Coordinate) -> Coordinate:
        _point(point)
        x0, y0, _x1, _y1 = self.source_bounds
        scale = self.km_per_source_unit
        result = ((point[0] - x0) * scale, (point[1] - y0) * scale)
        _point(result)
        return result

    def local_to_source(self, point: Coordinate) -> Coordinate:
        """Invert without clipping, including coordinates for future halos."""
        _point(point)
        scale = self.km_per_source_unit
        result = (
            point[0] / scale + self.source_bounds[0],
            point[1] / scale + self.source_bounds[1],
        )
        _point(result)
        return result


@dataclass(frozen=True, slots=True)
class EndpointGrid:
    """Uniform x-right/y-down samples including both ends of each axis.

    Extents identify sample positions, not raster pixel outer corners.
    """

    extent_km: Bounds
    width: int
    height: int
    registration: ClassVar[str] = "endpoint-nodes"

    def __post_init__(self) -> None:
        _bounds(self.extent_km)
        _count(self.width, 2, "Grid width")
        _count(self.height, 2, "Grid height")
        _positive(self.x_spacing_km, "X spacing")
        _positive(self.y_spacing_km, "Y spacing")

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    @property
    def x_spacing_km(self) -> float:
        return (self.extent_km[2] - self.extent_km[0]) / (self.width - 1)

    @property
    def y_spacing_km(self) -> float:
        return (self.extent_km[3] - self.extent_km[1]) / (self.height - 1)

    @classmethod
    def for_extent(
        cls, extent_km: Bounds, longest_samples: int, *, minimum_samples: int = 2
    ) -> EndpointGrid:
        """Calculate aspect-ratio dimensions with ties-to-even rounding."""
        _bounds(extent_km)
        _count(minimum_samples, 2, "Minimum samples")
        _count(longest_samples, minimum_samples, "Longest-axis samples")
        width_km = extent_km[2] - extent_km[0]
        height_km = extent_km[3] - extent_km[1]
        longest_km = max(width_km, height_km)
        return cls(
            extent_km,
            max(minimum_samples, round(longest_samples * width_km / longest_km)),
            max(minimum_samples, round(longest_samples * height_km / longest_km)),
        )

    def refined(self, factor: int) -> EndpointGrid:
        """Subdivide intervals; this does not generate or reconcile a child DEM."""
        _count(factor, 1, "Refinement factor")
        return EndpointGrid(
            self.extent_km, (self.width - 1) * factor + 1, (self.height - 1) * factor + 1
        )
