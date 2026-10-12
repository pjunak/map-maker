"""The catalog of wonders: fantastical landmarks beyond Earth's extremes.

A planet places a wonder at random when its kind is chosen in
``PlanetSettings.wonders``, or where a geology landmark puts it by hand. Hand-placed
wonders replace random ones of their kind.
"""

from dataclasses import dataclass
from typing import Literal

type WonderKind = Literal["titan", "crater", "chasm"]


@dataclass(frozen=True, slots=True)
class WonderSpec:
    label: str  # its name in the app
    summary: str  # what it is, in a sentence
    size: str  # what a hand-placed wonder's size measures
    size_km: tuple[float, float, float]  # allowed range and the usual size
    length_km: tuple[float, float] | None = None  # set for wonders placed by two ends

    @property
    def line(self) -> bool:
        return self.length_km is not None


WONDERS: dict[WonderKind, WonderSpec] = {
    "titan": WonderSpec(
        "Titan volcano",
        "An ice-capped shield volcano about 10 km high with a cliff around its base.",
        "diameter", (200.0, 1200.0, 560.0),
    ),
    "crater": WonderSpec(
        "Impact crater",
        "A fresh crater with a central plateau that may hold a ring lake.",
        "diameter", (20.0, 600.0, 240.0),
    ),
    "chasm": WonderSpec(
        "Great chasm",
        "A rift canyon system up to 3 km deep with parallel troughs and side canyons.",
        "width", (10.0, 200.0, 60.0), (100.0, 4000.0),
    ),
}
WONDER_KINDS: tuple[WonderKind, ...] = tuple(WONDERS)


def wonder_kinds(text: str) -> tuple[WonderKind, ...]:
    """The kinds named in a comma-separated list (or ``all``), in catalog order."""
    names = {name.strip().lower() for name in text.split(",") if name.strip()}
    if names == {"all"}:
        return WONDER_KINDS
    unknown = names - set(WONDER_KINDS)
    if unknown:
        raise ValueError(
            f"Unknown wonder kind: {', '.join(sorted(unknown))}. "
            f"Choose from {', '.join(WONDER_KINDS)} or all."
        )
    return tuple(kind for kind in WONDER_KINDS if kind in names)
