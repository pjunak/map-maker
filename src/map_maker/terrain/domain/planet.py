"""Whole-planet relief and climate settings, independent of files and solvers."""

from dataclasses import dataclass, field
from math import isfinite

from map_maker.terrain.domain.seeds import validate_master_seed

PLANET_RELIEF_ALGORITHM = "sphere-mesh-stream-power-v30"
PLANET_CLIMATE_ALGORITHM = "planet-climate-v7"
PLANET_MESH_STAGE_ID = "planet.mesh"
PLANET_FORCING_STAGE_ID = "planet.forcing"
PLANET_INITIAL_STAGE_ID = "planet.initial"
PLANET_VOLCANISM_STAGE_ID = "planet.volcanism"
MIN_PLANET_NODES = 2_000
MAX_PLANET_NODES = 4_000_000


def _finite(value: object, label: str, low: float, high: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"{label} must be a finite number from {low:g} to {high:g}.")


@dataclass(frozen=True, slots=True)
class PlanetClimateSettings:
    """Declared planetary assumptions for the provisional climate (Earth-like defaults)."""

    obliquity_deg: float = 23.4
    equator_sst_c: float = 27.0
    pole_sst_c: float = -15.0
    lapse_c_per_km: float = 6.5
    wind_speed_m_s: float = 7.0
    prograde_rotation: bool = True
    mean_land_precip_mm: float = 800.0

    def __post_init__(self) -> None:
        _finite(self.obliquity_deg, "Obliquity", 0, 60)
        _finite(self.equator_sst_c, "Equator sea temperature", -20, 45)
        _finite(self.pole_sst_c, "Pole sea temperature", -60, 30)
        if self.pole_sst_c > self.equator_sst_c:
            raise ValueError("Pole sea temperature cannot exceed the equator's.")
        _finite(self.lapse_c_per_km, "Lapse rate", 0, 12)
        _finite(self.wind_speed_m_s, "Wind speed", 0.5, 40)
        _finite(self.mean_land_precip_mm, "Mean land precipitation", 10, 5000)
        if type(self.prograde_rotation) is not bool:  # pyright: ignore[reportUnnecessaryComparison]
            raise ValueError("Prograde rotation must be true or false.")


@dataclass(frozen=True, slots=True)
class PlanetSettings:
    """One whole-planet generation request.

    Relief is made by uplift and implicit stream-power erosion on an irregular
    sphere mesh. ``process_area_km2`` is the smallest resolved drainage area;
    it keeps relief statistics independent of ``nodes``. ``climate_passes`` is the
    number of climate -> runoff-weighted erosion couplings (0 = no climate).
    Wonders are not planet settings: they are added to the finished planet
    (``domain.wonders.WonderSettings``, ADR-0097).
    """

    seed: int = 20261006
    nodes: int = 200_000
    duration_myr: float = 30.0
    step_kyr: float = 100.0
    erodibility: float = 5e-6
    area_exponent: float = 0.45
    process_area_km2: float = 600.0
    calibration_iterations: int = 3
    climate_passes: int = 1
    climate: PlanetClimateSettings = field(default_factory=PlanetClimateSettings)
    # Opt-in: young volcanoes at sea may break the surface as new islands, which
    # adds land beyond the authored coastline.
    volcanic_islands: bool = False

    def __post_init__(self) -> None:
        validate_master_seed(self.seed)
        if type(self.volcanic_islands) is not bool:
            raise ValueError("Volcanic islands must be true or false.")
        if (
            type(self.nodes) is not int
            or not MIN_PLANET_NODES <= self.nodes <= MAX_PLANET_NODES
        ):
            raise ValueError(
                f"Planet nodes must be an integer from {MIN_PLANET_NODES:,} "
                f"to {MAX_PLANET_NODES:,}."
            )
        _finite(self.duration_myr, "Evolution duration", 0.1, 500)
        _finite(self.step_kyr, "Evolution step", 1, 5000)
        if self.step_kyr * 1e-3 > self.duration_myr:
            raise ValueError("The evolution step cannot exceed the duration.")
        if self.steps > 20_000:
            raise ValueError("Evolution needs at most 20,000 steps; use a longer step.")
        _finite(self.erodibility, "Erodibility", 1e-9, 1e-3)
        _finite(self.area_exponent, "Area exponent", 0.2, 0.8)
        _finite(self.process_area_km2, "Process area", 0, 1e6)
        for label, value, high in (
            ("Calibration iterations", self.calibration_iterations, 10),
            ("Climate passes", self.climate_passes, 5),
        ):
            if type(value) is not int or not 0 <= value <= high:
                raise ValueError(f"{label} must be an integer from 0 to {high}.")

    @property
    def steps(self) -> int:
        return max(1, round(self.duration_myr * 1e3 / self.step_kyr))


REGIONAL_ALGORITHM = "planet-blended-tiles-v9"
TILE_STAGE_PREFIX = "planet.tile."


def tile_stage_prefix(level: int) -> str:
    """Stage-seed prefix of a detail level's tiles (level 1 keeps the plain prefix)."""
    return TILE_STAGE_PREFIX if level == 1 else f"{TILE_STAGE_PREFIX}l{level}."


@dataclass(frozen=True, slots=True)
class RegionalSettings:
    """Fine detail inside a planet: fixed blended tiles enriched from the parent.

    Tiles are centred on a fixed Fibonacci lattice about ``tile_km`` apart; each is
    generated over its blend support plus ``halo_km``. ``process_area_km2`` is the
    smallest resolved drainage area at this detail.
    """

    spacing_km: float = 5.0
    process_area_km2: float = 600.0
    calibration_iterations: int = 3
    tile_km: float = 600.0
    halo_km: float = 150.0
    support_factor: float = 0.8

    def __post_init__(self) -> None:
        _finite(self.spacing_km, "Regional spacing", 0.05, 100)
        _finite(self.process_area_km2, "Regional process area", 0.01, 1e5)
        _finite(self.tile_km, "Tile spacing", 10, 5000)
        _finite(self.halo_km, "Tile halo", 0, 2000)
        _finite(self.support_factor, "Tile support factor", 0.7, 2.0)
        if self.tile_km < 20 * self.spacing_km:
            raise ValueError("Tiles must span at least 20 node spacings.")
        iterations = self.calibration_iterations
        if type(iterations) is not int or not 0 <= iterations <= 10:
            raise ValueError("Regional calibration iterations must be an integer from 0 to 10.")


# Nested detail levels (ADR-0088): region, province, local. Each refines the
# spacing about fivefold and is enriched from the level above.
REGION_LEVELS: tuple[RegionalSettings, ...] = (
    RegionalSettings(),
    RegionalSettings(spacing_km=1.0, process_area_km2=24.0, tile_km=120.0, halo_km=30.0),
    RegionalSettings(spacing_km=0.2, process_area_km2=0.96, tile_km=24.0, halo_km=6.0),
)
REGION_LEVEL_NAMES = ("region", "province", "local")
REGION_LEVEL_MAX_RADIUS_KM = (5000.0, 300.0, 60.0)
