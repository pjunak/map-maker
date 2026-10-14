"""Line-owned crest/floor controls, independent of nearby height points."""

from dataclasses import dataclass
from itertools import pairwise
from math import isfinite

MAX_PROFILE_KNOTS = 64


def _finite_number(value: object) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value))


@dataclass(frozen=True, slots=True)
class StructureProfileKnot:
    """Fraction of the smoothed metric centreline and an absolute height or magnitude."""

    position: float
    elevation_m: float

    def __post_init__(self) -> None:
        for value in (self.position, self.elevation_m):
            if not _finite_number(value):
                raise ValueError("Profile positions and heights must be finite numbers.")
        if not 0. <= self.position <= 1.:
            raise ValueError("Profile positions must be between 0 and 1.")
        if self.elevation_m < 0.:
            raise ValueError("Profile heights, ridge relief and valley depth cannot be negative.")


def validate_structure_profile(
    profile: tuple[StructureProfileKnot, ...], *, absolute_valley: bool,
) -> None:
    if not profile:
        return
    if not 2 <= len(profile) <= MAX_PROFILE_KNOTS:
        raise ValueError(f"A profile needs 2 to {MAX_PROFILE_KNOTS} knots, including both ends.")
    if profile[0].position != 0. or profile[-1].position != 1.:
        raise ValueError("A profile must start at 0% and end at 100% of the line.")
    for first, last in pairwise(profile):
        if first.position >= last.position:
            raise ValueError("Profile positions must increase without duplicates.")
        if absolute_valley and first.elevation_m < last.elevation_m:
            raise ValueError("Absolute valley profile heights must not rise downstream.")
