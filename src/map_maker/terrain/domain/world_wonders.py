"""Wonders placed by hand on one world, independent of any planet build (ADR-0097)."""

from dataclasses import dataclass
from math import isfinite
from re import fullmatch

from map_maker.terrain.domain.models import Point2D
from map_maker.terrain.domain.seeds import MAX_MASTER_SEED
from map_maker.terrain.domain.wonders import (
    MAX_WONDER_AGE_MYR,
    WONDER_KINDS,
    WONDERS,
    WonderKind,
)
from map_maker.terrain.domain.world import WorldProject

MAX_WONDERS = 32


def _finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)


@dataclass(frozen=True, slots=True)
class WorldWonder:
    """A wonder from the catalog (``domain.wonders``) at a source-map position.

    ``size_km`` is what the kind's size measures (a diameter, a width or a
    height); None uses the usual size. Line wonders run from ``position`` to
    ``end``. Its shape is drawn from ``seed`` and its kind alone, so other
    wonders and the planet seed do not change it.
    """

    id: str
    name: str
    kind: WonderKind
    position: Point2D
    seed: int
    size_km: float | None = None
    end: Point2D | None = None
    age_myr: float | None = None  # None uses the wonder settings' age

    def __post_init__(self) -> None:
        if not fullmatch(r"wonder-[A-Za-z0-9][A-Za-z0-9_-]*", self.id) or len(self.id) > 256:
            raise ValueError("Wonder ID must start with wonder- and use letters, digits, _ or -.")
        if not self.name.strip() or len(self.name) > 256:
            raise ValueError("A wonder's name needs 1-256 non-blank characters.")
        if self.kind not in WONDER_KINDS:
            raise ValueError(f"Wonder kind must be one of: {', '.join(WONDER_KINDS)}.")
        if len(self.position) != 2 or any(not _finite_number(v) for v in self.position):
            raise ValueError(f"{self.name}: the position must be a finite coordinate pair.")
        if type(self.seed) is not int or not 0 <= self.seed <= MAX_MASTER_SEED:
            raise ValueError(
                f"{self.name}: the seed must be a whole number from 0 to {MAX_MASTER_SEED:,}."
            )
        spec = WONDERS[self.kind]
        label = spec.label.lower()
        if self.size_km is not None:
            if spec.size_km is None:
                raise ValueError(f"A {label} has no size.")
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
        if self.age_myr is not None:
            if not spec.ages:
                raise ValueError(f"A {label} does not age.")
            if not _finite_number(self.age_myr) or not 0 <= self.age_myr <= MAX_WONDER_AGE_MYR:
                raise ValueError(f"A {label}'s age must be 0-{MAX_WONDER_AGE_MYR:g} Myr.")

    @property
    def effective_size_km(self) -> float:
        """The size in kilometres, defaulting to the kind's usual size."""
        if self.size_km is not None:
            return self.size_km
        usual = WONDERS[self.kind].size_km
        return 0.0 if usual is None else usual[2]


@dataclass(frozen=True, slots=True)
class WorldWonders:
    """The wonders placed by hand on one world, in source-map coordinates."""

    world: WorldProject
    wonders: tuple[WorldWonder, ...] = ()

    def __post_init__(self) -> None:
        if len(self.wonders) > MAX_WONDERS:
            raise ValueError(f"A world holds at most {MAX_WONDERS} placed wonders.")
        if len({w.id for w in self.wonders}) != len(self.wonders):
            raise ValueError("Wonder IDs must be unique.")
        if len({w.name.casefold() for w in self.wonders}) != len(self.wonders):
            raise ValueError("Wonder names must be unique.")
        frame = self.world.frame
        x0, y0, x1, y1 = frame.bounds
        for wonder in self.wonders:
            for x, y in (wonder.position, *(() if wonder.end is None else (wonder.end,))):
                if not (x0 <= x <= x1 and y0 <= y <= y1):
                    raise ValueError(f"{wonder.name}: position is outside the world frame.")
            spec = WONDERS[wonder.kind]
            if wonder.end is not None and spec.length_km is not None:
                length = frame.distance_km(
                    frame.source_to_lonlat(wonder.position), frame.source_to_lonlat(wonder.end)
                )
                low, high = spec.length_km
                if not low <= length <= high:
                    raise ValueError(
                        f"{wonder.name}: a {spec.label.lower()} must be "
                        f"{low:,.0f}-{high:,.0f} km long (it is {length:,.0f} km)."
                    )


def blank_wonders(world: WorldProject) -> WorldWonders:
    return WorldWonders(world)


def follow_world(wonders: WorldWonders, world: WorldProject) -> WorldWonders:
    """The wonders for an edited version of their world, drawn on the same source map.

    Wonders stay where they were placed on the source map, so they must still fit
    the edited frame.
    """
    if world.source.sha256 != wonders.world.source.sha256:
        raise ValueError("These wonders were placed on another source map; they cannot follow it.")
    return WorldWonders(world, wonders.wonders)
