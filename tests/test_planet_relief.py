"""Whole-planet relief research harness: mesh geometry and erosion invariants."""

from math import pi
from pathlib import Path

import numpy as np
import pytest

from benchmarks.planet.evolve import evolve, route
from benchmarks.planet.fields import coast_distance, default_tectonics, land_on_mesh
from benchmarks.planet.kernels import accumulate, laplacian, priority_flood
from benchmarks.planet.mesh import SphereMesh, build_mesh
from benchmarks.planet.metrics import direction_isotropy, uphill_edges
from benchmarks.planet.synthetic_world import WorldSpec, build_world
from dmtools.terrain.application.world import open_world

RADIUS = 6.371e6


@pytest.fixture(scope="module")
def mesh() -> SphereMesh:
    return build_mesh(4000, RADIUS, seed=3)


def test_mesh_covers_the_sphere_with_symmetric_neighbours(mesh: SphereMesh) -> None:
    assert mesh.area_m2.sum() == pytest.approx(4 * pi * RADIUS**2, rel=1e-9)
    assert len(mesh.triangles) == 2 * mesh.size - 4  # Euler: closed triangulated sphere
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    forward = set(zip(src.tolist(), mesh.nbr.tolist(), strict=True))
    assert all((b, a) in forward for a, b in forward)
    assert np.all(mesh.length_m > 0)
    assert np.all(mesh.weight > -1e-9)  # Delaunay: opposite angles sum <= pi
    water = np.zeros(mesh.size, dtype=bool)
    lap = laplacian(np.full(mesh.size, 7.0), water, mesh.ptr, mesh.nbr, mesh.weight,
                    mesh.area_m2, 0.0)
    assert np.max(np.abs(lap)) < 1e-12


def test_flooded_routing_drains_every_land_node_to_water(mesh: SphereMesh) -> None:
    rng = np.random.default_rng(1)
    water = mesh.xyz[:, 2] < -0.2
    h = np.where(water, 0.0, 100 * rng.random(mesh.size))
    filled, parent = priority_flood(h, water, mesh.ptr, mesh.nbr, 1e-3)
    assert np.all(filled >= h)
    assert np.all(parent[~water] >= 0)
    state = route(mesh, h, water)
    assert uphill_edges(state.filled, state.receiver, water) == 0
    # Every land node reaches water, and drainage area is conserved at the coast.
    outlets = (~water) & water[np.maximum(state.receiver, 0)]
    total = accumulate(state.order, state.receiver, water, np.where(water, 0.0, mesh.area_m2))
    assert total[outlets].sum() == pytest.approx(mesh.area_m2[~water].sum(), rel=1e-12)


def test_evolution_keeps_the_coast_and_builds_descending_isotropic_rivers(tmp_path: Path) -> None:
    world = open_world(build_world(WorldSpec(seed=5, columns=256, continents=3), tmp_path, "w"))
    mesh = build_mesh(20_000, world.project.frame.radius_km * 1000, seed=4)
    land = land_on_mesh(world, mesh)
    water = ~land
    coast = coast_distance(mesh, land)
    tectonics = default_tectonics(mesh, land, coast, 4, erodibility=4e-6)
    h, state, history = evolve(
        mesh, water, tectonics, np.ones(mesh.size), duration_yr=5e6, dt_yr=2.5e5,
        process_area_m2=1e10, verbose=False,
    )
    assert np.all(h[land] >= 1.0)
    assert np.all(h[water] == 0.0)
    assert uphill_edges(h, state.receiver, water) == 0
    assert history.max_m[-1] > 500
    assert direction_isotropy(mesh, state.receiver, land)["compass_sector_share"] == (
        pytest.approx(0.25, abs=0.03)
    )
    again, _, _ = evolve(
        mesh, water, tectonics, np.ones(mesh.size), duration_yr=5e6, dt_yr=2.5e5,
        process_area_m2=1e10, verbose=False,
    )
    assert np.array_equal(h, again)


def test_geology_intent_is_calibrated_while_erosion_shapes_the_relief(tmp_path: Path) -> None:
    from benchmarks.planet.geology import as_tectonics, forcing_parts, geology_forcing, measure
    from benchmarks.planet.sample_geology import sample_recipe

    world_path = build_world(WorldSpec(seed=7, columns=512), tmp_path, "w")
    world = open_world(world_path)
    recipe = sample_recipe(world_path)
    mesh = build_mesh(30_000, world.project.frame.radius_km * 1000, seed=2)
    land = land_on_mesh(world, mesh)
    water = ~land
    coast = coast_distance(mesh, land)
    forcing = geology_forcing(world, recipe, mesh, land)
    assert set(np.unique(forcing.region[land]).tolist()) >= {0}
    assert np.all(forcing.region[water] == -1)
    duration = 1e7
    scale = np.ones(len(forcing.intents))
    errors: list[float] = []
    measured: list[float | None] = []
    for _ in range(3):
        parts = forcing_parts(mesh, land, coast, forcing, scale, 1, 4e-6, duration)
        h, state, _ = evolve(
            mesh, water, as_tectonics(parts), np.ones(mesh.size), duration_yr=duration,
            dt_yr=2.5e5, process_area_m2=1e10, pulse=parts.pulse, pulse_start_yr=0.8 * duration,
            verbose=False,
        )
        assert uphill_edges(h, state.receiver, water) == 0
        measured = measure(h, forcing)
        errors = []
        for k, (intent, value) in enumerate(zip(forcing.intents, measured, strict=True)):
            if intent is None or value is None:
                continue
            errors.append(abs(value - intent.target_m) / intent.target_m)
            scale[k] *= float(np.clip(intent.target_m / max(value, 1e-9), 0.33, 3.0))
    by_name = dict(zip(forcing.names, measured, strict=True))
    young = [v for n, v in by_name.items() if n.endswith("young belt") and v is not None]
    worn = [v for n, v in by_name.items() if n.endswith("worn belt") and v is not None]
    assert young and worn and min(young) > max(worn)
    assert np.median(errors) < 0.15
