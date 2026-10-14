"""Bounded local samples must preserve the full source and common coordinates."""

from dataclasses import replace
from typing import cast

import numpy as np
import pytest

from benchmarks.terrain import fixture
from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.domain.regional import RegionalSamplingRequest
from map_maker.terrain.pipeline import regional
from map_maker.terrain.pipeline.generate import generate_terrain
from map_maker.terrain.pipeline.grid import grid_coordinates

SOURCE = "a" * 64


@pytest.mark.parametrize("refinement", [1, 2, 8, 64])
def test_nested_coordinates_retain_exact_reference_nodes(refinement: int) -> None:
    grid = EndpointGrid((-123.14, .007, 784.1, 571.37), 74, 45)
    request = RegionalSamplingRequest(SOURCE, grid, refinement,
                                      (10 * refinement, 7 * refinement,
                                       14 * refinement, 11 * refinement), 0)
    x, y = regional.regional_coordinates(request)
    reference_x, reference_y = grid_coordinates(grid)
    np.testing.assert_array_equal(x[::refinement], reference_x[10:15])
    np.testing.assert_array_equal(y[::refinement], reference_y[7:12])
    if refinement > 1:
        coarser = replace(request, refinement=refinement // 2,
                          window=tuple(i // 2 for i in request.window))
        cx, cy = regional.regional_coordinates(coarser)
        np.testing.assert_array_equal(x[::2], cx)
        np.testing.assert_array_equal(y[::2], cy)


def test_bounds_round_outwards_and_halo_clips_at_source_edges() -> None:
    grid = EndpointGrid((0., 0., 100., 60.), 11, 7)
    request = RegionalSamplingRequest.for_bounds(SOURCE, grid, (0., 5.1, 19.9, 60.), 4)
    assert request.window == (0, 2, 8, 24)
    assert request.sample_window == (0, 1, 9, 24)
    assert request.sample_shape == (24, 10)
    assert request.core_slices == (slice(1, 24), slice(0, 9))
    assert request.grid().extent_km == (0., 5., 20., 60.)
    # Bounds copied from an existing request do not acquire an extra border.
    assert RegionalSamplingRequest.for_bounds(
        SOURCE, grid, request.grid().extent_km, 4) == request


@pytest.mark.parametrize("value", [0, 3, -2, 131072, True, 2.0])
def test_invalid_refinement_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="power of two"):
        RegionalSamplingRequest(SOURCE, EndpointGrid((0., 0., 1., 1.), 65, 65),
                                cast(int, value), (1, 1, 2, 2))


@pytest.mark.parametrize("halo", [-1, 33, True, 1.5])
def test_invalid_halo_is_rejected(halo: object) -> None:
    with pytest.raises(ValueError, match="halo"):
        RegionalSamplingRequest(SOURCE, EndpointGrid((0., 0., 1., 1.), 65, 65),
                                1, (1, 1, 2, 2), cast(int, halo))


def test_sample_budget_counts_halo_before_allocating() -> None:
    grid = EndpointGrid((0., 0., 10., 10.), 2049, 2049)
    with pytest.raises(ValueError, match="limit is 2,000,000"):
        RegionalSamplingRequest(SOURCE, grid, 1, (1, 1, 1414, 1414))
    assert RegionalSamplingRequest(SOURCE, grid, 1, (1, 1, 1414, 1414), 0)


@pytest.mark.parametrize("grid,refinement", [
    (EndpointGrid((1e15, 0., 1e15 + 1., 1.), 65, 65), 8),
    (EndpointGrid((0., 0., 1., 1.), 2**48, 2), 64),
])
def test_precision_is_rejected_before_bounds_addressing(
    grid: EndpointGrid, refinement: int,
) -> None:
    with pytest.raises(ValueError, match="precision"):
        RegionalSamplingRequest.for_bounds(SOURCE, grid, grid.extent_km, refinement)


def test_small_window_does_not_allocate_world_axes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even this intentionally enormous reference needs only four local axis nodes.
    grid = EndpointGrid((0., 0., 1e6, 1e6), 100_000_001, 100_000_001)
    request = RegionalSamplingRequest(SOURCE, grid, 8, (400_000_000, 2, 400_000_003, 5), 0)
    def no_world_axis(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Regional coordinates must not allocate a full reference axis")
    monkeypatch.setattr(np, "linspace", no_world_axis)
    x, y = regional.regional_coordinates(request)
    assert x.shape == y.shape == (4,)
    assert x[0] == 500_000.


@pytest.mark.parametrize("case", ["square", "regional", "water", "archipelago", "authored"])
def test_regional_samples_match_full_source_and_overlap(case: str) -> None:
    coastline, settings, constraints = fixture(case, 65, 19)
    full = generate_terrain(coastline, settings, constraints=constraints)
    sampler = regional.prepare_regional_sampler(coastline, settings, constraints=constraints)
    grid = sampler.reference_grid
    # Include coast, non-land, authored regions and water across the complete reference.
    request = RegionalSamplingRequest(sampler.source_id, grid, 2,
                                      (0, 0, (grid.width - 1) * 2, (grid.height - 1) * 2))
    fine = sampler.sample(request)
    np.testing.assert_array_equal(fine.elevation_m[::2, ::2], full.elevation_m)
    np.testing.assert_array_equal(fine.land_mask[::2, ::2], full.land_mask)
    np.testing.assert_array_equal(fine.water_surface_m[::2, ::2], full.water.surface_m)
    np.testing.assert_array_equal(fine.basin_intent_ids[::2, ::2], full.water.intent_ids)
    assert fine.canonical_grid == full.routing_grid
    a = sampler.sample(replace(request, window=(12, 14, 32, 30)))
    b = sampler.sample(replace(request, window=(24, 20, 46, 38)))
    repeated = sampler.sample(a.request)
    for name in ("elevation_m", "land_mask", "water_surface_m", "basin_intent_ids"):
        field = getattr(fine, name)
        for part in (a, b, repeated):
            x0, y0, x1, y1 = part.request.sample_window
            values = getattr(part, name)
            np.testing.assert_array_equal(values, field[y0:y1 + 1, x0:x1 + 1])
            assert not values.flags.writeable
    assert not a.x_km.flags.writeable and not a.y_km.flags.writeable


def test_sampler_reuses_preparation_and_bounds_evaluation_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coastline, settings, constraints = fixture("square", 65, 42)
    sampler = regional.prepare_regional_sampler(coastline, settings, constraints=constraints)
    def no_prepare(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Each window must reuse the already prepared global field")
    monkeypatch.setattr(regional, "prepare_terrain_field", no_prepare)
    monkeypatch.setattr(regional, "REGIONAL_CHUNK_SAMPLES", 7)
    # A non-row-aligned chunk boundary must not affect exact outputs.
    request = RegionalSamplingRequest(sampler.source_id, sampler.reference_grid, 8,
                                      (30, 40, 46, 52))
    progress: list[float] = []
    chunked = sampler.sample(request, lambda fraction, _label: progress.append(fraction))
    monkeypatch.setattr(regional, "REGIONAL_CHUNK_SAMPLES", 65_536)
    ordinary = sampler.sample(request)
    np.testing.assert_array_equal(chunked.elevation_m, ordinary.elevation_m)
    assert len(progress) == (chunked.elevation_m.size + 6) // 7
    assert progress[-1] == 1.
    with pytest.raises(ValueError, match="different terrain source"):
        sampler.sample(replace(request, source_id="0" * 64))
    with pytest.raises(ValueError, match="different terrain source"):
        sampler.sample(replace(request, reference_grid=replace(sampler.reference_grid, width=66)))


def test_source_identity_binds_inputs_and_algorithms(monkeypatch: pytest.MonkeyPatch) -> None:
    coastline, settings, constraints = fixture("authored", 65, 42)
    identity = regional.sampling_source_id(coastline, settings, constraints)
    assert identity == regional.sampling_source_id(coastline, settings, tuple(constraints))
    assert identity != regional.sampling_source_id(
        coastline, replace(settings, seed=43), constraints)
    assert identity != regional.sampling_source_id(coastline, settings, constraints[:-1])
    monkeypatch.setattr(regional, "GENERATOR_ALGORITHM_ID", "future-generator")
    assert identity != regional.sampling_source_id(coastline, settings, constraints)
