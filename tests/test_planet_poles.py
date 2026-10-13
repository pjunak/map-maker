# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The planet's polar land: covered poles, true-distance polar coasts, the rest unchanged."""

from math import cos, pi, radians

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from dmtools.terrain.adapters.world_svg import parse_world_svg
from dmtools.terrain.domain.world import WorldAssignment, WorldContinent, WorldFrame, WorldProject
from dmtools.terrain.pipeline.planet_poles import POLE_CAP_DEG, planet_world
from dmtools.terrain.pipeline.world import WorldMap, component_area_km2, prepare_world_map

SEED = 20261006
RADIUS_KM = 1000.0


def _world(body: str) -> WorldMap:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="180" '
        f'viewBox="0 0 360 180">{body}</svg>'
    )
    imported = parse_world_svg(svg, "poles.svg")
    return prepare_world_map(
        WorldProject(
            "Poles",
            imported,
            WorldFrame((0, 0, 360, 180), RADIUS_KM),
            (WorldContinent("c", "Continent"),),
            tuple(WorldAssignment(f.id, "c", "mainland") for f in imported.features),
        )
    )


def _land(world: WorldMap) -> BaseGeometry:
    land = unary_union([Polygon(c.exterior, c.holes) for v in world.land for c in v.components])
    shapely.prepare(land)
    return land


def _at(land: BaseGeometry, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    return np.asarray(shapely.contains_xy(land, lon + 180, 90 - lat), dtype=bool)


WEDGE = '<path id="wedge" d="M 100 150 L 260 150 L 260 180 L 100 180 Z"/>'
ISLAND = '<path id="island" d="M 20 60 L 60 60 L 60 90 L 20 90 Z"/>'


def test_land_touching_a_pole_covers_it_and_mid_latitudes_are_unchanged() -> None:
    drawn = _world(WEDGE + ISLAND)
    world = planet_world(drawn, SEED)
    lon = np.linspace(-179.5, 179.5, 720)
    near_pole = _at(_land(world), lon, np.full_like(lon, -89.0))
    assert near_pole.all()
    assert not _at(_land(drawn), lon, np.full_like(lon, -89.0)).all()

    rng = np.random.default_rng(1)
    lon = rng.uniform(-180, 180, 50_000)
    lat = rng.uniform(-54, 54, 50_000)
    assert np.array_equal(_at(_land(world), lon, lat), _at(_land(drawn), lon, lat))

    (cover,) = [a for a in world.adjustments if a.kind == "pole_cover"]
    assert cover.feature_ids == ("wedge",)
    added = world.land_area_km2 - drawn.land_area_km2
    cap = 2 * pi * RADIUS_KM**2 * (1 - cos(radians(POLE_CAP_DEG)))
    assert 0.2 * cap < added < 2.0 * cap
    assert world.land_area_km2 == pytest.approx(
        sum(component_area_km2(c, world.project.frame) for v in world.land for c in v.components)
    )
    assert world.land_area_km2 == pytest.approx(sum(s.area_km2 for s in world.continents))


def test_cap_outline_depends_on_the_seed_only() -> None:
    drawn = _world(WEDGE)
    first, again = planet_world(drawn, SEED), planet_world(_world(WEDGE), SEED)
    other = planet_world(drawn, SEED + 1)
    lon = np.linspace(-179.5, 179.5, 720)
    lat = np.full_like(lon, -88.0 + POLE_CAP_DEG / 2)
    assert np.array_equal(_at(_land(first), lon, lat), _at(_land(again), lon, lat))
    assert first.land_area_km2 != other.land_area_km2


def test_land_already_covering_a_pole_is_not_capped_and_stays_joined_at_the_seam() -> None:
    cap = '<path id="cap" d="M 0 165 L 360 165 L 360 180 L 0 180 Z"/>'
    world = planet_world(_world(cap), SEED)
    assert not [a for a in world.adjustments if a.kind == "pole_cover"]
    lat = np.linspace(-89.9, -80.0, 200)
    land = _land(world)
    assert _at(land, np.full_like(lat, -179.999), lat).all()
    assert _at(land, np.full_like(lat, 179.999), lat).all()


def test_polar_coasts_are_smoothed_in_true_distance() -> None:
    # Teeth 0.5 drawing units wide at 80 degrees south are about 1.5 km across but
    # 50 km long: radial streaks. True-distance smoothing removes them.
    teeth = "".join(
        f"L {x} 167 L {x + 0.5} 167 L {x + 0.5} 170 L {x + 1} 170 " for x in range(40, 80)
    )
    body = f'<path id="comb" d="M 40 170 {teeth} L 80 170 L 80 175 L 40 175 Z"/>'
    drawn = _world(body)
    world = planet_world(drawn, SEED)
    tips_lon = np.arange(40, 80) + 0.25 - 180.0
    tips_lat = np.full_like(tips_lon, -77.5)
    assert _at(_land(drawn), tips_lon, tips_lat).all()
    assert _at(_land(world), tips_lon, tips_lat).mean() < 0.2


def test_worlds_without_polar_land_are_returned_unchanged() -> None:
    drawn = _world(ISLAND)
    assert planet_world(drawn, SEED) is drawn
