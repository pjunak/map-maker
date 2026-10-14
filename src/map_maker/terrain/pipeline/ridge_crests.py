# pyright: reportUnknownMemberType=false
"""Crest ownership and compatible contacts for explicitly profiled ridges."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import LineString, Point
from shapely.ops import substring

from map_maker.terrain.pipeline.profile import shape_preserving_profile

JUNCTION_HEIGHT_TOLERANCE_M = .001


type FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ProfileRidge:
    instruction_number: int
    line: LineString
    positions_km: tuple[float, ...]
    heights_m: tuple[float, ...]

    def height_at(self, point: Point) -> float:
        position = float(self.line.project(point))
        return float(shape_preserving_profile(
            np.asarray(self.positions_km), np.asarray(self.heights_m),
            np.asarray([position]),
        )[0])


def _check_line(instruction: int, line: LineString) -> None:
    if not line.is_simple or line.is_closed:
        raise ValueError(
            f"Profiled ridge instruction {instruction} must be a simple, "
            "open line. Split loops or self-crossings into separate branches.")


def _contacts(first: int, line: LineString, second: int, other: LineString) -> list[Point]:
    contact = line.intersection(other)
    if contact.length > 0.:
        raise ValueError(
            f"Profiled ridge instructions {first} and {second} overlap along a line. "
            "Keep one shared crest and end the branches on it.")
    return [Point(float(x), float(y)) for x, y in shapely.get_coordinates(contact)]


def smooth_connected_ridges(
    lines: dict[int, LineString],
    smooth: Callable[[list[tuple[float, float]]], list[tuple[float, float]]],
) -> dict[int, LineString]:
    """Round each span independently so authored contacts remain shared vertices."""
    stops: dict[int, dict[float, tuple[float, float]]] = {}
    for number, line in lines.items():
        _check_line(number, line)
        stops[number] = {0.: (float(line.coords[0][0]), float(line.coords[0][1])),
                         line.length: (float(line.coords[-1][0]), float(line.coords[-1][1]))}
    items = list(lines.items())
    for index, (number, line) in enumerate(items):
        for other_number, other in items[:index]:
            for point in _contacts(other_number, other, number, line):
                coordinate = (point.x, point.y)
                stops[number][float(line.project(point))] = coordinate
                stops[other_number][float(other.project(point))] = coordinate
    result: dict[int, LineString] = {}
    for number, line in items:
        prepared: list[tuple[float, float]] = []
        for (start, first), (end, last) in pairwise(sorted(stops[number].items())):
            span = substring(line, start, end)
            if not isinstance(span, LineString):
                raise ValueError("Ridge junction positions do not form distinct line spans.")
            coordinates = [(float(x), float(y)) for x, y in span.coords]
            # Reuse the very same intersection coordinates on both branches.
            # Reconstructing by arc length can introduce tiny unequal endpoints.
            coordinates[0], coordinates[-1] = first, last
            rounded = smooth(coordinates)
            prepared.extend(rounded if not prepared else rounded[1:])
        result[number] = LineString(prepared)
    return result


def validate_ridge_contacts(ridges: Sequence[ProfileRidge]) -> None:
    """Reject incompatible exact contacts without moving any authored geometry."""
    for index, ridge in enumerate(ridges):
        _check_line(ridge.instruction_number, ridge.line)
        for other in ridges[:index]:
            for point in _contacts(other.instruction_number, other.line,
                                   ridge.instruction_number, ridge.line):
                first, second = other.height_at(point), ridge.height_at(point)
                if abs(first - second) > JUNCTION_HEIGHT_TOLERANCE_M:
                    raise ValueError(
                        f"Ridge junction conflict: instructions {other.instruction_number} "
                        f"and {ridge.instruction_number} request {first:.3f} m and "
                        f"{second:.3f} m at ({point.x:.6f}, {point.y:.6f}) km "
                        f"(profiles {100*other.line.project(point)/other.line.length:.6f}% "
                        f"and {100*ridge.line.project(point)/ridge.line.length:.6f}%). "
                        "Match their profile heights at the contact or separate the lines.")


class CrestBlend:
    """Streaming inverse-square target shares with exact centreline ownership.

    Distance ratios rescale the accumulator instead of dividing by zero or
    capping weights with an epsilon. The maximum physical response controls
    coverage; neighboring lines do not add their strengths into a flat plateau.
    """

    def __init__(self, reference: FloatArray) -> None:
        self.coverage = np.zeros_like(reference)
        self.weight = np.zeros_like(reference)
        self.targets = np.zeros_like(reference)
        self.distance_scale = np.full_like(reference, np.inf)

    def add(self, response: FloatArray, target: FloatArray, distance_km: FloatArray) -> None:
        active = response > 0.
        scale = np.minimum(self.distance_scale, np.where(active, distance_km, np.inf))
        previous = np.divide(
            scale, self.distance_scale, out=np.zeros_like(scale),
            where=np.isfinite(self.distance_scale) & (self.distance_scale > 0.),
        )
        previous = np.where(self.distance_scale == 0., 1., previous)
        ratio = np.divide(scale, distance_km, out=np.zeros_like(scale),
                          where=active & (distance_km > 0.))
        ratio = np.where(active & (distance_km == 0.), 1., ratio)
        share = response * ratio**2
        self.weight = self.weight * previous**2 + share
        self.targets = self.targets * previous**2 + share * target
        self.distance_scale = scale
        self.coverage = np.maximum(self.coverage, response)

    def apply(self, elevation: FloatArray) -> FloatArray:
        target = np.divide(self.targets, self.weight, out=np.zeros_like(elevation),
                           where=self.weight > 0.)
        return elevation * (1. - self.coverage) + target * self.coverage
