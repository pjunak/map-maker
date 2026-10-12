"""Authored geological hypotheses, independent of any terrain simulation."""

from dataclasses import dataclass
from math import isfinite
from re import fullmatch
from typing import Literal

from dmtools.terrain.domain.models import LandformSettings, Point2D
from dmtools.terrain.domain.wonders import WONDER_KINDS, WONDERS, WonderKind
from dmtools.terrain.domain.world import WorldProject

type GeologicalSetting = Literal[
    "unspecified", "stable-interior", "active-belt", "rift", "volcanic", "sedimentary-basin"
]
GEOLOGICAL_SETTINGS: tuple[GeologicalSetting, ...] = (
    "unspecified",
    "stable-interior",
    "active-belt",
    "rift",
    "volcanic",
    "sedimentary-basin",
)
MAX_PROVINCES = 128
MAX_PROVINCE_VERTICES = 256
MAX_LANDMARKS = 32
MAX_AGE_MA = 1_000_000.0


def _name(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{label} needs 1-256 non-blank characters.")


def _finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)


@dataclass(frozen=True, slots=True)
class GeologyProfile:
    """Blank ages are unknown; duration is not an age or a different present."""

    setting: GeologicalSetting = "unspecified"
    crust_age_ma: float | None = None
    rejuvenation_age_ma: float | None = None
    evolution_duration_ma: float | None = None
    landform: LandformSettings | None = None

    def __post_init__(self) -> None:
        if self.setting not in GEOLOGICAL_SETTINGS:
            raise ValueError("Unknown geological setting.")
        for label, value in (
            ("Crust age", self.crust_age_ma),
            ("Rejuvenation age", self.rejuvenation_age_ma),
            ("Simulation duration", self.evolution_duration_ma),
        ):
            if value is not None and (not _finite_number(value) or not 0 <= value <= MAX_AGE_MA):
                raise ValueError(f"{label} must be blank or 0-{MAX_AGE_MA:g} Ma.")


@dataclass(frozen=True, slots=True)
class ContinentGeology:
    continent_id: str
    profile: GeologyProfile = GeologyProfile()


@dataclass(frozen=True, slots=True)
class GeologyProvince:
    """Source-linear polygon; unwrapped x coordinates permit a seam crossing."""

    id: str
    name: str
    vertices: tuple[Point2D, ...]
    priority: int = 0
    profile: GeologyProfile = GeologyProfile()

    def __post_init__(self) -> None:
        _name(self.id, "Province ID")
        if not fullmatch(r"province-[A-Za-z0-9][A-Za-z0-9_-]*", self.id):
            raise ValueError(
                "Province ID must start with province- and use letters, digits, _ or -."
            )
        _name(self.name, "Province name")
        if type(self.priority) is not int or not 0 <= self.priority <= 100:
            raise ValueError("Province priority must be an integer from 0 to 100.")
        if not 3 <= len(self.vertices) <= MAX_PROVINCE_VERTICES:
            raise ValueError(f"A province needs 3-{MAX_PROVINCE_VERTICES} vertices.")
        if any(len(p) != 2 or any(not _finite_number(v) for v in p) for p in self.vertices):
            raise ValueError("Province vertices must be finite coordinate pairs.")
        if len(set(self.vertices)) != len(self.vertices):
            raise ValueError("Province vertices must be distinct; do not repeat the closing point.")


@dataclass(frozen=True, slots=True)
class GeologyLandmark:
    """A hand-placed wonder (``domain.wonders``) at a source position.

    ``size_km`` is what the kind's size measures (a diameter, a width or a
    height); None uses the usual size. Line wonders run from ``position`` to
    ``end``.
    """

    id: str
    name: str
    kind: WonderKind
    position: Point2D
    size_km: float | None = None
    end: Point2D | None = None

    def __post_init__(self) -> None:
        _name(self.id, "Landmark ID")
        if not fullmatch(r"landmark-[A-Za-z0-9][A-Za-z0-9_-]*", self.id):
            raise ValueError(
                "Landmark ID must start with landmark- and use letters, digits, _ or -."
            )
        _name(self.name, "Landmark name")
        if self.kind not in WONDER_KINDS:
            raise ValueError(f"Landmark kind must be one of: {', '.join(WONDER_KINDS)}.")
        if len(self.position) != 2 or any(not _finite_number(v) for v in self.position):
            raise ValueError("A landmark position must be a finite coordinate pair.")
        spec = WONDERS[self.kind]
        label = spec.label.lower()
        if self.size_km is not None:
            low, high, _ = spec.size_km
            if not _finite_number(self.size_km) or not low <= self.size_km <= high:
                raise ValueError(f"A {label} needs a {spec.size} from {low:g} to {high:g} km.")
        if spec.line:
            if self.end is None or len(self.end) != 2 or any(
                not _finite_number(v) for v in self.end
            ):
                raise ValueError(f"A {label} needs a finite end point.")
            if tuple(self.end) == tuple(self.position):
                raise ValueError(f"A {label}'s ends must differ.")
        elif self.end is not None:
            raise ValueError(f"A {label} has no end point.")

    @property
    def effective_size_km(self) -> float:
        """The size in kilometres, defaulting to the kind's usual size."""
        return WONDERS[self.kind].size_km[2] if self.size_km is None else self.size_km


@dataclass(frozen=True, slots=True)
class WorldGeologyRecipe:
    world: WorldProject
    defaults: tuple[ContinentGeology, ...]
    provinces: tuple[GeologyProvince, ...] = ()
    landmarks: tuple[GeologyLandmark, ...] = ()

    def __post_init__(self) -> None:
        owners = {c.id for c in self.world.continents}
        if len(self.defaults) != len(owners) or {d.continent_id for d in self.defaults} != owners:
            raise ValueError("Geology needs exactly one default for each retained continent.")
        if len(self.provinces) > MAX_PROVINCES:
            raise ValueError(f"A recipe supports at most {MAX_PROVINCES} provinces.")
        if len({p.id for p in self.provinces}) != len(self.provinces):
            raise ValueError("Province IDs must be unique.")
        if len({p.name.casefold() for p in self.provinces}) != len(self.provinces):
            raise ValueError("Province names must be unique.")
        frame = self.world.frame
        x0, y0, x1, y1 = frame.bounds
        if len(self.landmarks) > MAX_LANDMARKS:
            raise ValueError(f"A recipe supports at most {MAX_LANDMARKS} landmarks.")
        if len({m.id for m in self.landmarks}) != len(self.landmarks):
            raise ValueError("Landmark IDs must be unique.")
        if len({m.name.casefold() for m in self.landmarks}) != len(self.landmarks):
            raise ValueError("Landmark names must be unique.")
        for landmark in self.landmarks:
            for x, y in (landmark.position, *(() if landmark.end is None else (landmark.end,))):
                if not (x0 <= x <= x1 and y0 <= y <= y1):
                    raise ValueError(f"{landmark.name}: position is outside the world frame.")
            spec = WONDERS[landmark.kind]
            if landmark.end is not None and spec.length_km is not None:
                length = frame.distance_km(
                    frame.source_to_lonlat(landmark.position), frame.source_to_lonlat(landmark.end)
                )
                low, high = spec.length_km
                if not low <= length <= high:
                    raise ValueError(
                        f"{landmark.name}: a {spec.label.lower()} must be "
                        f"{low:,.0f}-{high:,.0f} km long (it is {length:,.0f} km)."
                    )
        for province in self.provinces:
            xs, ys = zip(*province.vertices, strict=True)
            # Anchor one copy in the world and allow the remaining points to unwrap.
            if not x0 <= xs[0] <= x1 or min(ys) < y0 or max(ys) > y1:
                raise ValueError(f"{province.name}: anchor/latitude is outside the world frame.")
            if max(xs) - min(xs) > frame.width:
                raise ValueError(f"{province.name}: polygon spans more than one world width.")
            pairs = zip(
                province.vertices, (*province.vertices[1:], province.vertices[0]), strict=True
            )
            if any(abs(a[0] - b[0]) > frame.width / 2 for a, b in pairs):
                raise ValueError(
                    f"{province.name}: each edge must span at most half the world; "
                    "add intermediate vertices or unwrap across the longitude seam."
                )


def blank_geology(world: WorldProject) -> WorldGeologyRecipe:
    return WorldGeologyRecipe(world, tuple(ContinentGeology(c.id) for c in world.continents))
