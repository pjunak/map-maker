"""The catalog of wonders: fantastical landmarks beyond Earth's extremes.

A planet places a wonder at random when its kind is chosen in
``PlanetSettings.wonders``, or where a geology landmark puts it by hand. Hand-placed
wonders replace random ones of their kind.
"""

from dataclasses import dataclass
from typing import Literal

type WonderKind = Literal[
    "titan", "shattered", "active", "crater", "chasm", "cliff", "tepui", "oasis", "fork"
]


@dataclass(frozen=True, slots=True)
class WonderSpec:
    label: str  # its name in the app
    summary: str  # what it is, in a sentence
    size: str | None  # what a hand-placed wonder's size measures; None if it has none
    size_km: tuple[float, float, float] | None  # allowed range and the usual size
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
    "shattered": WonderSpec(
        "Shattered volcano",
        "A volcano that blew itself apart: a horseshoe amphitheatre open on one side, a "
        "summit caldera and a hummocky debris field beyond the breach.",
        "diameter", (20.0, 200.0, 70.0),
    ),
    "active": WonderSpec(
        "Giant active volcano",
        "An erupting stratovolcano up to 8.5 km high, with a glowing vent, lava flows "
        "and an ash blanket downwind.",
        "diameter", (30.0, 250.0, 130.0),
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
    "cliff": WonderSpec(
        "Great cliff",
        "A fault scarp kilometres high whose raised block tilts gently back from its "
        "edge; the high side lies to the left going from the first end to the second.",
        "height", (0.5, 6.0, 2.5), (50.0, 3000.0),
    ),
    "tepui": WonderSpec(
        "Tepui",
        "A table mountain walled by sheer cliffs on every side; random ones come in groups.",
        "diameter", (10.0, 300.0, 70.0),
    ),
    "oasis": WonderSpec(
        "Oasis",
        "A spring-fed pond ringed by palms and gardens in a hot desert; random ones are "
        "scattered across the deserts.",
        "diameter", (2.0, 60.0, 15.0),
    ),
    "fork": WonderSpec(
        "Splitting river",
        "A large river that divides on a low divide and reaches the sea two ways. Place it "
        "near a large river; it splits where the divide is lowest.",
        None, None,
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
