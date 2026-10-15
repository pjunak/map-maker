"""The catalog of wonders: fantastical landmarks beyond Earth's extremes.

A planet places a wonder at random when its kind is chosen in
``WonderSettings.random``, or where a wonder document (``domain.world_wonders``)
puts it by hand. Hand-placed wonders replace random ones of their kind. Wonders are
added to a finished base planet (ADR-0097).
"""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

type WonderKind = Literal[
    "titan", "shattered", "active", "crater", "chasm", "cliff", "tepui", "oasis", "fork"
]


def _finite_in(value: object, low: float, high: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and isfinite(value)
        and low <= value <= high
    )


@dataclass(frozen=True, slots=True)
class WonderOption:
    """A setting that a placed wonder of one kind may fix; blank leaves it to the generator.

    The catalog is the one definition of these settings: validation, the wonder
    document and the app's form all follow it.
    """

    key: str  # its name in the wonder document
    label: str  # its name in the app
    unit: str
    low: float
    high: float
    help: str  # what it means and what blank does
    whole: bool = False  # a count

    def check(self, value: float, name: str) -> None:
        if not _finite_in(value, self.low, self.high) or (self.whole and value != int(value)):
            kind = "a whole number" if self.whole else "a number"
            raise ValueError(
                f"{name}: {self.label.lower()} must be {kind} from {self.low:,g} to "
                f"{self.high:,g}{f' {self.unit}' if self.unit else ''}, or blank."
            )


@dataclass(frozen=True, slots=True)
class WonderSpec:
    label: str  # its name in the app
    summary: str  # what it is, in a sentence
    size: str | None  # what a hand-placed wonder's size measures; None if it has none
    size_km: tuple[float, float, float] | None  # allowed range and the usual size
    length_km: tuple[float, float] | None = None  # set for wonders placed by two ends
    ages: bool = False  # the aging tool can erode it (ADR-0091)
    options: tuple[WonderOption, ...] = ()  # settings a placed one may fix (ADR-0098)

    @property
    def line(self) -> bool:
        return self.length_km is not None

    def option(self, key: str) -> WonderOption | None:
        return next((o for o in self.options if o.key == key), None)


WONDERS: dict[WonderKind, WonderSpec] = {
    "titan": WonderSpec(
        "Titan volcano",
        "An ice-capped shield volcano about 10 km high with a cliff around its base.",
        "diameter", (200.0, 1200.0, 560.0),
        options=(
            WonderOption("height_m", "Height", "m", 6000.0, 14000.0,
                         "Summit above the plain. Blank: about 10 km, more for a larger one."),
        ),
    ),
    "shattered": WonderSpec(
        "Shattered volcano",
        "A volcano that blew itself apart: a horseshoe amphitheatre open on one side, a "
        "summit caldera and a hummocky debris field beyond the breach.",
        "diameter", (20.0, 200.0, 70.0),
        options=(
            WonderOption("height_m", "Height", "m", 2000.0, 6000.0,
                         "Height of the ruined cone. Blank: from its size, 2.5-6 km."),
        ),
    ),
    "active": WonderSpec(
        "Giant active volcano",
        "An erupting stratovolcano up to 8.5 km high, with a glowing vent, lava flows "
        "and an ash blanket downwind.",
        "diameter", (30.0, 250.0, 130.0),
        options=(
            WonderOption("height_m", "Height", "m", 3000.0, 9000.0,
                         "Summit above the plain. Blank: from its size, 3-9 km."),
        ),
    ),
    "crater": WonderSpec(
        "Impact crater",
        "A fresh crater with a central plateau that may hold a ring lake.",
        "diameter", (20.0, 600.0, 240.0), ages=True,
        options=(
            WonderOption("depth_m", "Depth", "m", 100.0, 6000.0,
                         "Rim crest to trough floor; the floor must stay above sea level. "
                         "Blank: about 0.9 % of its diameter, less on low ground."),
        ),
    ),
    "chasm": WonderSpec(
        "Great chasm",
        "A rift canyon system up to 3 km deep with parallel troughs and side canyons.",
        "width", (10.0, 200.0, 60.0), (100.0, 4000.0), ages=True,
        options=(
            WonderOption("depth_m", "Depth", "m", 300.0, 6000.0,
                         "The deepest it is cut; shallower where the ground is lower, so "
                         "its floor stays above sea level. Blank: 3,000 m."),
            WonderOption("side_canyons", "Side canyons", "", 0.0, 10.0,
                         "Canyons branching off it. Blank: three to six.", whole=True),
            WonderOption("parallel_troughs", "Parallel troughs", "", 0.0, 5.0,
                         "Troughs beside part of it. Blank: one to three.", whole=True),
        ),
    ),
    "cliff": WonderSpec(
        "Great cliff",
        "A fault scarp kilometres high whose raised block tilts gently back from its "
        "edge; the high side lies to the left going from the first end to the second.",
        "height", (0.5, 6.0, 2.5), (50.0, 3000.0), ages=True,
    ),
    "tepui": WonderSpec(
        "Tepui",
        "A table mountain walled by sheer cliffs on every side; random ones come in groups.",
        "diameter", (10.0, 300.0, 70.0), ages=True,
        options=(
            WonderOption("height_m", "Height", "m", 500.0, 4000.0,
                         "Wall height above the plain. Blank: from its size, 1-2.8 km."),
            WonderOption("elongation", "Elongation", "", 1.0, 3.0,
                         "Long axis over short axis; 1 is round. Blank: 1-2.2."),
            WonderOption("orientation_deg", "Orientation", "°", 0.0, 180.0,
                         "Direction of its long axis, from north towards east. Blank: any."),
        ),
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
        options=(
            WonderOption("share_pct", "Water taken", "%", 10.0, 50.0,
                         "Share of the river's water that leaves by the other basin. "
                         "Blank: 25-45 %."),
        ),
    ),
}
WONDER_KINDS: tuple[WonderKind, ...] = tuple(WONDERS)
# Every setting name used by some kind, for the document schema.
OPTION_KEYS: tuple[str, ...] = tuple(
    sorted({option.key for spec in WONDERS.values() for option in spec.options})
)


MAX_WONDER_AGE_MYR = 500.0
AGE_PRESETS: dict[str, float] = {
    "Fresh": 0.0,
    "Weathered · 10 Myr": 10.0,
    "Old · 30 Myr": 30.0,
    "Ancient · 80 Myr": 80.0,
}


@dataclass(frozen=True, slots=True)
class WonderSettings:
    """Wonders placed at random, and the age of every wonder without its own."""

    random: tuple[WonderKind, ...] = ()
    age_myr: float = 0.0  # for the aging tool (ADR-0091); 0 keeps wonders fresh

    def __post_init__(self) -> None:
        if (
            type(self.random) is not tuple
            or len(set(self.random)) != len(self.random)
            or any(kind not in WONDER_KINDS for kind in self.random)
        ):
            raise ValueError(f"Wonders must be distinct kinds from: {', '.join(WONDER_KINDS)}.")
        if not _finite_in(self.age_myr, 0, MAX_WONDER_AGE_MYR):
            raise ValueError(
                f"Wonder age (Myr) must be a finite number from 0 to {MAX_WONDER_AGE_MYR:g}."
            )


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
