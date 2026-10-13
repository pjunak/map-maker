"""Ice sheets: mass balance, shallow-ice flow, margins and their display (ADR-0093)."""

import numpy as np
import pytest

from dmtools.terrain.pipeline.planet_ice import (
    MELT_FLOOR_C,
    IceSheets,
    equilibrium_line_c,
    ice_sheet_nodes,
    ice_sheets,
    margin_distance,
    melt_mm,
    nye_thickness,
    surface_balance,
)
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, build_mesh

RADIUS = 6.371e6


@pytest.fixture(scope="module")
def mesh() -> SphereMesh:
    return build_mesh(8000, RADIUS, 5)


def _polar(mesh: SphereMesh) -> tuple[np.ndarray, np.ndarray]:
    """Absolute latitude (deg) and a summer cooling poleward of about 66 deg."""
    lat = np.degrees(np.abs(mesh.lat))
    return lat, 22.0 - 30.0 * np.sin(np.radians(lat)) ** 2


def test_melt_balances_precipitation_at_the_equilibrium_line() -> None:
    precipitation = np.array([100.0, 645.0, 1000.0, 2000.0])
    assert np.allclose(melt_mm(equilibrium_line_c(precipitation)), precipitation, rtol=1e-9)
    summer = np.array([-10.0, MELT_FLOOR_C - 0.1, 0.0, 5.0, 10.0])
    melt = melt_mm(summer)
    assert melt[0] == melt[1] == 0.0 and np.all(np.diff(melt) >= 0)
    # Height and albedo cool the surface; height also dries it.
    flat = surface_balance(np.array([1.0]), np.array([500.0]), np.array([0.0]), 6.5, np.zeros(1))
    high = surface_balance(np.array([1.0]), np.array([500.0]), np.array([1000.0]), 6.5, np.zeros(1))
    bright = surface_balance(np.array([1.0]), np.array([500.0]), np.array([0.0]), 6.5, np.ones(1))
    assert flat[0] < 0 < high[0] and flat[0] < bright[0]
    assert high[0] < 500.0 * np.exp(-0.07 * 6.5) / 917.0 + 1e-12  # drier aloft, no melt


def test_ice_grows_where_snow_outlasts_summer_and_flows_beyond_its_snowline(
    mesh: SphereMesh,
) -> None:
    lat, warm = _polar(mesh)
    land = np.ones(mesh.size, dtype=bool)
    bed = np.full(mesh.size, 200.0)
    precipitation = np.full(mesh.size, 400.0)
    ice = ice_sheets(mesh, land, bed, bed, warm, precipitation, 6.5, 7)
    thickness = ice.thickness_m
    assert np.all(np.isfinite(thickness)) and np.all(thickness >= 0)
    assert np.all(thickness[lat > 72] > 0) and not np.any(thickness[lat < 45] > 0)
    assert thickness[lat > 85].min() > 1000.0
    # The dome accumulates and its margin ablates: ice flows to where it melts.
    iced = thickness > 0
    assert ice.balance_m[lat > 85].min() > 0 and (ice.balance_m[iced] < 0).any()
    # Height and albedo feedbacks carry ice where bare ground would lose snow.
    bare = surface_balance(warm, precipitation, np.zeros(mesh.size), 6.5, np.zeros(mesh.size))
    assert (iced & (bare < 0)).any()
    # Without snowfall nothing grows, however cold.
    dry = ice_sheets(mesh, land, bed, bed, warm, np.zeros(mesh.size), 6.5, 7)
    assert not dry.thickness_m.any()
    again = ice_sheets(mesh, land, bed, bed, warm, precipitation, 6.5, 7)
    assert np.array_equal(again.thickness_m, thickness)


def test_ice_calves_at_the_sea_and_holds_no_water_nodes(mesh: SphereMesh) -> None:
    lat, warm = _polar(mesh)
    land = lat > 62
    bed = np.where(land, 300.0, -3000.0)
    ice = ice_sheets(mesh, land, bed, bed, warm, np.full(mesh.size, 400.0), 6.5, 7)
    assert not ice.thickness_m[~land].any()
    assert ice.thickness_m[lat > 80].min() > 500.0


def test_margin_distance_is_zero_halfway_between_ice_and_bare_nodes(mesh: SphereMesh) -> None:
    lat, _ = _polar(mesh)
    ice = lat > 60
    margin = margin_distance(mesh, ice)
    assert np.all(margin[ice] > 0) and np.all(margin[~ice] < 0)
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    border = ice[src] & ~ice[mesh.nbr]
    # On a border edge the two ends sit about equally far from the margin.
    assert np.abs(margin[src[border]] + margin[mesh.nbr[border]]).mean() < 0.3 * mesh.spacing_m
    assert np.all(margin_distance(mesh, np.zeros(mesh.size, dtype=bool)) < 0)


def test_only_large_ice_bodies_that_bury_their_bed_are_drawn_as_sheets() -> None:
    mesh = build_mesh(40_000, RADIUS, 6)
    lat, lon = np.degrees(mesh.lat), np.degrees(mesh.lon)
    rng = np.random.default_rng(1)
    flat = np.full(mesh.size, 300.0)
    rugged = 300.0 + rng.uniform(0.0, 3000.0, mesh.size)
    cap = lat > 70  # ~ 3 million km2
    small = (np.abs(lat) < 1) & (np.abs(lon) < 1)  # ~ 50,000 km2
    range_ = (np.abs(lat - 30) < 6) & (np.abs(lon - 60) < 6)
    thickness = np.where(cap, 2000.0, np.where(small | range_, 600.0, 0.0))
    bed = np.where(range_, rugged, flat)
    sheets = ice_sheet_nodes(mesh, thickness, bed)
    assert np.all(sheets[cap]) and not sheets[small].any() and not sheets[range_].any()
    assert not ice_sheet_nodes(mesh, np.zeros(mesh.size), flat).any()


def test_bed_relief_for_ice_sheets_does_not_depend_on_the_mesh() -> None:
    from dmtools.terrain.pipeline.planet_ice import local_relief

    # Hills of 2,000 km wavelength: relief between neighbouring nodes about
    # halves on a mesh twice as fine; relief at a fixed scale stays.
    reliefs: list[float] = []
    steps: list[float] = []
    for nodes in (20_000, 80_000):
        mesh = build_mesh(nodes, RADIUS, 8)
        hills = 900.0 * np.sin(mesh.xyz[:, 0] * RADIUS / 320e3) * np.cos(
            mesh.xyz[:, 1] * RADIUS / 320e3
        )
        middle = np.abs(np.degrees(mesh.lat)) < 50
        reliefs.append(float(local_relief(mesh, hills, 400e3)[middle].mean()))
        src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
        steps.append(float(np.sqrt(np.mean((hills[mesh.nbr] - hills[src]) ** 2))))
    assert reliefs[1] == pytest.approx(reliefs[0], rel=0.05)
    assert steps[1] < 0.7 * steps[0]


def test_ice_rises_steeply_from_its_margin_and_lies_only_inside_it() -> None:
    from dmtools.terrain.adapters.planet_natural import ice_surface

    margin = np.linspace(-5e3, 60e3, 131)
    thickness = np.full(margin.shape, 2000.0)
    on_ice, surface = ice_surface(
        margin, thickness, np.full(margin.shape, 100.0), lambda v: v, np.zeros(margin.shape)
    )
    assert np.array_equal(on_ice, margin > 0)
    assert np.all(np.diff(surface[on_ice]) >= 0)
    assert nye_thickness(np.array([1e3]))[0] == pytest.approx(149.1, rel=0.01)
    inside = surface[np.argmin(np.abs(margin - 10e3))] - 100.0
    assert 400.0 < inside < 550.0 and surface.max() <= 2100.0 + 1e-9


def test_ice_sheets_of_a_planet_without_climate_are_empty() -> None:
    none = IceSheets.none(5)
    assert not none.thickness_m.any() and not none.balance_m.any()


def test_ice_sheets_show_firn_above_their_equilibrium_line_and_bare_ice_below() -> None:
    from dmtools.terrain.adapters.planet_natural import IcePixels, PixelClimate, land_colour

    shape = (1, 3)
    points = np.tile([0.0, 0.0, 1.0], (3, 1))

    def fill(value: float) -> np.ndarray:
        return np.full(shape, value)

    # Tundra summers: bare ground is brown, not snow.
    climate = PixelClimate(fill(-12.0), fill(6.0), fill(300.0), fill(300.0), None)
    ice = IcePixels(np.array([[0.0, 1.0, 1.0]]), np.array([[0.0, 0.3, -1.0]]))
    rgb = land_colour(
        points, RADIUS, climate, fill(300.0), fill(0.0), fill(1.0), ice=ice
    )[0]
    tundra, firn, bare = rgb
    assert firn.min() > 230 and tundra.mean() < firn.mean() - 40
    # Bare glacier ice is bluish grey, darker than firn.
    assert bare[2] > bare[0] + 15 and bare.mean() < firn.mean() - 25
