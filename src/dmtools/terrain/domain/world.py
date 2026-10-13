"""Authored world identity and spherical Plate Carree coordinates, without I/O."""

from dataclasses import dataclass
from math import asin, cos, isfinite, pi, radians, sin, sqrt
from typing import Literal

from dmtools.terrain.domain.models import LandComponent, Point2D

type WorldRole = Literal["mainland", "island", "exclude"]
type Bounds = tuple[float, float, float, float]

WORLD_PREPARATION = "bounded-world-v1"
WORLD_EDGE_TOLERANCE_FRACTION = 1e-5
WORLD_BORDER_OVERLAP_FRACTION = 1e-4
MAX_COAST_DETAIL_KM = 1000.0


def _name(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{label} must contain 1-256 non-blank characters.")


@dataclass(frozen=True, slots=True)
class WorldFrame:
    """A complete 360 x 180 degree source frame on a custom spherical planet."""

    bounds: Bounds
    radius_km: float
    central_meridian_deg: float = 0.0

    def __post_init__(self) -> None:
        if len(self.bounds) != 4 or any(not isfinite(v) for v in self.bounds):
            raise ValueError("World frame must contain four finite bounds.")
        x0, y0, x1, y1 = self.bounds
        if not isfinite(x1 - x0) or not isfinite(y1 - y0) or x1 <= x0 or y1 <= y0:
            raise ValueError("World frame width and height must be positive.")
        if (
            not isfinite(self.radius_km)
            or self.radius_km <= 0
            or not isfinite(4 * pi * self.radius_km * self.radius_km)
            or self.radius_km * self.radius_km == 0
        ):
            raise ValueError("Planet radius must be positive and finite, in kilometres.")
        if not isfinite(self.central_meridian_deg) or not -180 <= self.central_meridian_deg < 180:
            raise ValueError("Central meridian must be in [-180, 180) degrees.")

    @property
    def width(self) -> float:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> float:
        return self.bounds[3] - self.bounds[1]

    @property
    def geometry_tolerance(self) -> float:
        """Source-space export tolerance, independent of display zoom and planet radius."""
        return min(self.width, self.height) * WORLD_EDGE_TOLERANCE_FRACTION

    @property
    def surface_area_km2(self) -> float:
        return 4 * pi * self.radius_km**2

    def source_to_lonlat(self, point: Point2D, *, wrap: bool = True) -> Point2D:
        if any(not isfinite(v) for v in point):
            raise ValueError("Source coordinates must be finite.")
        longitude = self.central_meridian_deg + (point[0] - self.bounds[0]) / self.width * 360 - 180
        latitude = 90 - (point[1] - self.bounds[1]) / self.height * 180
        if not -90 <= latitude <= 90:
            raise ValueError("Source position is outside the north/south world frame.")
        return ((longitude + 180) % 360 - 180 if wrap else longitude), latitude

    def lonlat_to_source(self, point: Point2D, *, wrap: bool = True) -> Point2D:
        longitude, latitude = point
        if any(not isfinite(v) for v in point) or not -90 <= latitude <= 90:
            raise ValueError("Geographic coordinates must be finite with latitude in [-90, 90].")
        offset = longitude - self.central_meridian_deg
        if wrap:
            offset = (offset + 180) % 360 - 180
        return (
            self.bounds[0] + (offset + 180) / 360 * self.width,
            self.bounds[1] + (90 - latitude) / 180 * self.height,
        )

    def distance_km(self, first: Point2D, second: Point2D) -> float:
        """Shortest great-circle distance between longitude/latitude positions."""
        self.lonlat_to_source(first)
        self.lonlat_to_source(second)
        lon0, lat0, lon1, lat1 = map(radians, (*first, *second))
        value = sin((lat1 - lat0) / 2) ** 2 + cos(lat0) * cos(lat1) * sin((lon1 - lon0) / 2) ** 2
        return 2 * self.radius_km * asin(sqrt(min(1.0, max(0.0, value))))


class WorldGeometryError(ValueError):
    """A source validation failure whose affected shapes can be selected for review."""

    def __init__(self, message: str, feature_ids: tuple[str, ...]) -> None:
        super().__init__(message)
        self.feature_ids = feature_ids


@dataclass(frozen=True, slots=True)
class WorldFeature:
    """One retained SVG shape. Invalid candidates can be explicitly excluded."""

    id: str
    label: str
    groups: tuple[str, ...]
    components: tuple[LandComponent, ...]
    issue: str = ""

    @property
    def description(self) -> str:
        parts = (
            self.groups
            if self.groups and self.groups[-1] == self.label
            else (*self.groups, self.label)
        )
        return f"{' / '.join(parts)} [{self.id}]"


@dataclass(frozen=True, slots=True)
class WorldSource:
    """Portable original vector text and separately flattened inspection geometry."""

    name: str
    svg: str
    sha256: str
    features: tuple[WorldFeature, ...]
    suggested_bounds: Bounds


@dataclass(frozen=True, slots=True)
class WorldContinent:
    id: str
    name: str

    def __post_init__(self) -> None:
        _name(self.id, "Continent ID")
        _name(self.name, "Continent name")


@dataclass(frozen=True, slots=True)
class WorldAssignment:
    feature_id: str
    continent_id: str | None
    role: WorldRole

    def __post_init__(self) -> None:
        _name(self.feature_id, "Feature ID")
        if self.role not in ("mainland", "island", "exclude"):
            raise ValueError("Choose mainland, island or exclude for each source shape.")
        if (self.role == "exclude") != (self.continent_id is None):
            raise ValueError("Land must have a continent; excluded shapes must not have one.")
        if self.continent_id is not None:
            _name(self.continent_id, "Continent ID")


@dataclass(frozen=True, slots=True)
class WorldProject:
    """A reviewed source map; it does not contain climate or generated terrain."""

    name: str
    source: WorldSource
    frame: WorldFrame
    continents: tuple[WorldContinent, ...]
    assignments: tuple[WorldAssignment, ...]
    # The drawn coast already carries detail down to this wavelength (km), as a
    # map exported from a planet's refined coast does. Regional maps then add
    # only finer coast detail (ADR-0090). None: refine the drawing in full.
    coast_detail_km: float | None = None

    def __post_init__(self) -> None:
        _name(self.name, "World name")
        if self.coast_detail_km is not None and not (
            isfinite(self.coast_detail_km) and 0 < self.coast_detail_km <= MAX_COAST_DETAIL_KM
        ):
            raise ValueError(
                f"Drawn coast detail must be a positive wavelength of at most "
                f"{MAX_COAST_DETAIL_KM:g} km, or left blank."
            )
        ids = [c.id for c in self.continents]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("A world needs continents with unique IDs.")
        if len({c.name.casefold() for c in self.continents}) != len(ids):
            raise ValueError("Continent names must be distinct.")
        features = {feature.id: feature for feature in self.source.features}
        if len(features) != len(self.source.features):
            raise ValueError("Source shape IDs must be unique.")
        mapped = [a.feature_id for a in self.assignments]
        if len(mapped) != len(set(mapped)) or set(mapped) != features.keys():
            raise ValueError("Assign every source shape exactly once, or explicitly exclude it.")
        used: set[str] = set()
        for assignment in self.assignments:
            if assignment.continent_id is None:
                continue
            if assignment.continent_id not in ids:
                raise ValueError("A shape refers to an unknown continent.")
            feature = features[assignment.feature_id]
            if feature.issue or not feature.components:
                raise WorldGeometryError(
                    f"{feature.description}: {feature.issue or 'No valid land geometry.'}",
                    (feature.id,),
                )
            used.add(assignment.continent_id)
        if used != set(ids):
            raise ValueError("Every continent needs at least one assigned land shape.")
