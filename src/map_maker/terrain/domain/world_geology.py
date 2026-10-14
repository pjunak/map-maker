"""Authored geological hypotheses, independent of any terrain simulation."""

from dataclasses import dataclass
from math import isfinite
from re import fullmatch
from typing import Literal

from map_maker.terrain.domain.models import LandformSettings, Point2D
from map_maker.terrain.domain.world import WorldProject

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
# Names and one-line meanings shown in the app; ``pipeline.planet_forcing`` owns
# the heights and erodibility each setting asks for.
SETTING_TEXT: dict[GeologicalSetting, tuple[str, str]] = {
    "unspecified": (
        "Automatic", "No preference: ranges are placed as they would be without geology."
    ),
    "stable-interior": (
        "Stable interior", "An old, quiet continental core: low plains and broad plateaus."
    ),
    "active-belt": (
        "Active mountain belt", "Young ranges still rising, like the Andes or the Himalaya."
    ),
    "rift": ("Rift", "Land pulling apart: hills, fault scarps and deep lake basins."),
    "volcanic": ("Volcanic", "Volcanic highlands crowned by large cones."),
    "sedimentary-basin": (
        "Sedimentary basin", "Sinking lowland filled with soft sediment: flat, easily eroded."
    ),
}
MAX_PROVINCES = 128
MAX_PROVINCE_VERTICES = 256
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
class WorldGeologyRecipe:
    world: WorldProject
    defaults: tuple[ContinentGeology, ...]
    provinces: tuple[GeologyProvince, ...] = ()

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


def follow_world(recipe: WorldGeologyRecipe, world: WorldProject) -> WorldGeologyRecipe:
    """The recipe for an edited version of its world, drawn from the same source map.

    Renaming, rescaling or reassigning shapes keeps the geology: continent defaults
    follow their continents, new continents start unspecified and removed ones drop
    out. Provinces stay where they were drawn on the source map, so they must still
    fit the edited frame.
    """
    if world.source.sha256 != recipe.world.source.sha256:
        raise ValueError("This geology was drawn on another source map; it cannot follow it.")
    profiles = {d.continent_id: d.profile for d in recipe.defaults}
    return WorldGeologyRecipe(
        world,
        tuple(ContinentGeology(c.id, profiles.get(c.id, GeologyProfile()))
              for c in world.continents),
        recipe.provinces,
    )
