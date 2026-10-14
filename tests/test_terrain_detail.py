# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false
"""Added detail preserves reference structure independently of window/density/order."""

from dataclasses import replace
from hashlib import sha256
from itertools import pairwise
from typing import Any

import numpy as np
import pytest
import shapely
from numpy.typing import NDArray
from shapely.geometry import LineString, box
from shapely.strtree import STRtree

from benchmarks.terrain import fixture
from map_maker.terrain.domain import ElevationPoint, EndpointGrid, TerrainProject
from map_maker.terrain.domain.regional import (
    RegionalDetailSettings,
    RegionalSamplingRequest,
    detail_cell_window,
    detail_support_window,
)
from map_maker.terrain.pipeline import regional
from map_maker.terrain.pipeline.detail import (
    DetailedRegion,
    PreparedRegionalDetail,
    prepare_regional_detail,
)
from map_maker.terrain.pipeline.detail_basis import (
    edge_coefficients,
    residual_basis,
    terrain_x_weight,
)
from map_maker.terrain.pipeline.generate import PreparedTerrainField, generate_terrain
from map_maker.terrain.pipeline.parent import (
    ParentRouting,
    ParentTerrainData,
    VerifiedTerrainParent,
    prepare_verified_parent,
)


def numerical_parent(project: TerrainProject) -> VerifiedTerrainParent:
    terrain = generate_terrain(project.coastline, project.settings, constraints=project.constraints)
    routing = terrain.routing
    data = ParentTerrainData(
        sha256(repr(project).encode()).hexdigest(),
        project,
        terrain.x_km,
        terrain.y_km,
        terrain.elevation_m,
        terrain.land_mask,
        terrain.water.surface_m,
        terrain.water.intent_ids,
        ParentRouting(
            np.linspace(0, terrain.grid.extent_km[2], terrain.routing_grid.width),
            np.linspace(0, terrain.grid.extent_km[3], terrain.routing_grid.height),
            terrain.routing_land_mask,
            terrain.routing_final_elevation_m,
            routing.source_elevation_m,
            routing.receivers,
            routing.channel_mask,
            routing.accumulation_km2,
            routing.incision_m,
            routing.incision_limit_m,
        ),
    )
    return prepare_verified_parent(data)


@pytest.fixture(
    scope="module", params=[("example", 42), ("authored", 7), ("regional", 42), ("water", 42)]
)
def detail_field(request: pytest.FixtureRequest) -> tuple[PreparedRegionalDetail, tuple[int, int]]:
    case, seed = request.param
    coast, settings, constraints = fixture(case, 65, seed)
    settings = replace(settings, detail_levels=2)
    parent = numerical_parent(TerrainProject(coast, settings, tuple(constraints)))
    data = parent.data
    field = prepare_regional_detail(parent, RegionalDetailSettings(40.0))
    grid = data.grid
    survey = field.sample(
        RegionalSamplingRequest(
            data.build_id,
            grid,
            8,
            (8 * 8, 8 * 8, (grid.width - 9) * 8, (grid.height - 9) * 8),
            halo_cells=0,
        )
    )
    candidates = np.flatnonzero(survey.cell_amplitude_m > 0)
    assert candidates.size, "The public fixture should contain some eligible interior land."
    chosen = int(candidates[candidates.size // 2])
    left = int(np.clip(survey.cell_columns[chosen] - 4, 1, grid.width - 10))
    top = int(np.clip(survey.cell_rows[chosen] - 4, 1, grid.height - 10))
    return field, (left, top)


def sample(
    field: PreparedRegionalDetail, origin: tuple[int, int], refinement: int, halo: int = 0
) -> DetailedRegion:
    x, y = origin
    parent = field.parent
    request = RegionalSamplingRequest(
        parent.data.build_id,
        parent.data.grid,
        refinement,
        (x * refinement, y * refinement, (x + 8) * refinement, (y + 8) * refinement),
        halo,
    )
    return field.sample(request)


def test_65_129_257_windows_preserve_common_samples_and_parent_nodes(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    field, origin = detail_field
    results = [sample(field, origin, factor) for factor in (8, 16, 32)]
    assert [r.samples.elevation_m.shape for r in results] == [(65, 65), (129, 129), (257, 257)]
    for coarse, fine in pairwise(results):
        for name in ("elevation_m", "land_mask", "water_surface_m", "basin_intent_ids"):
            np.testing.assert_array_equal(
                getattr(coarse.samples, name), getattr(fine.samples, name)[::2, ::2]
            )
        np.testing.assert_array_equal(coarse.cell_amplitude_m, fine.cell_amplitude_m)
        np.testing.assert_array_equal(coarse.reference_cell_mean_m, fine.reference_cell_mean_m)
        np.testing.assert_array_equal(coarse.detailed_cell_mean_m, fine.detailed_cell_mean_m)
    x, y = origin
    expected = field.parent.data.elevation_m[y : y + 9, x : x + 9]
    for factor, result in zip((8, 16, 32), results, strict=True):
        np.testing.assert_array_equal(result.samples.elevation_m[::factor, ::factor], expected)
        assert np.count_nonzero(result.added_detail_m) > 0
        assert np.max(np.abs(result.added_detail_m)) <= field.settings.amplitude_m + 0.001
        assert result.evidence.maximum_cell_mean_error_m < 0.00025
        assert result.evidence.parent_cells == 64
        assert result.evidence.support_cells == 100
        assert not result.samples.elevation_m.flags.writeable



def test_overlap_repeat_visit_halo_and_batch_size_do_not_change_ground(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field, origin = detail_field
    first = sample(field, origin, 8, 1)
    shifted = sample(field, (origin[0] + 1, origin[1] + 1), 8, 3)
    _xs, x1, x2 = np.intersect1d(first.samples.x_km, shifted.samples.x_km, return_indices=True)
    _ys, y1, y2 = np.intersect1d(first.samples.y_km, shifted.samples.y_km, return_indices=True)
    np.testing.assert_array_equal(
        first.samples.elevation_m[np.ix_(y1, x1)], shifted.samples.elevation_m[np.ix_(y2, x2)]
    )
    monkeypatch.setattr(regional, "REGIONAL_CHUNK_SAMPLES", 127)
    repeated = sample(field, origin, 8, 1)
    np.testing.assert_array_equal(first.samples.elevation_m, repeated.samples.elevation_m)
    np.testing.assert_array_equal(first.reference_elevation_m, repeated.reference_elevation_m)


def test_water_authored_cores_and_channel_corridors_keep_reference_ground(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    field, origin = detail_field
    result = sample(field, origin, 16)
    samples = result.samples
    xx, yy = np.meshgrid(samples.x_km, samples.y_km)
    protected = samples.basin_intent_ids > 0
    parent = field.parent
    for constraint in parent.data.project.constraints:
        if isinstance(constraint, ElevationPoint):
            x = constraint.position[0] * parent.data.grid.extent_km[2]
            y = constraint.position[1] * parent.data.grid.extent_km[3]
            protected |= np.hypot(xx - x, yy - y) <= constraint.influence_radius_km
    routing = parent.data.routing
    lines: list[LineString] = []
    for source in np.flatnonzero(routing.channel_mask):
        target = int(routing.receivers.flat[source])
        if target < 0:
            continue
        row, col = divmod(int(source), routing.x_km.size)
        tr, tc = divmod(target, routing.x_km.size)
        lines.append(
            LineString(
                [(routing.x_km[col], routing.y_km[row]), (routing.x_km[tc], routing.y_km[tr])]
            )
        )
    if lines:
        guard = min(parent.data.grid.x_spacing_km, parent.data.grid.y_spacing_km)
        pairs = STRtree(lines).query(
            shapely.points(xx.ravel(), yy.ravel()), predicate="dwithin", distance=guard * 0.99
        )
        protected.ravel()[np.unique(pairs[0])] = True
    np.testing.assert_array_equal(
        samples.elevation_m[protected], result.reference_elevation_m[protected]
    )
    reference = parent.sampler.sample(samples.request)
    np.testing.assert_array_equal(samples.water_surface_m, reference.water_surface_m)
    np.testing.assert_array_equal(samples.basin_intent_ids, reference.basin_intent_ids)


def test_edge_basis_has_zero_moment_exact_nodes_and_bounded_amplitude() -> None:
    coefficients = edge_coefficients(
        np.array([9, 10], dtype=np.int64), np.array([7, 8], dtype=np.int64), 2026
    )
    amplitudes = np.full((2, 4), 0.75, dtype=np.float64)
    for n in (16, 32, 64):
        axis = np.linspace(0.0, 1.0, n + 1)
        u, v = np.meshgrid(axis, axis)
        values = residual_basis(u[..., None], v[..., None], coefficients, amplitudes)
        means = np.trapezoid(np.trapezoid(values, axis, axis=0), axis, axis=0)
        assert np.max(np.abs(means)) < 1e-15
        assert np.max(np.abs(values)) <= 1
        assert np.count_nonzero(values[np.ix_([0, -1], [0, -1])]) == 0
        assert np.count_nonzero(values[0, :]) > n // 2
        assert np.count_nonzero(values[:, 0]) > n // 2
    np.testing.assert_array_equal(
        coefficients,
        edge_coefficients(
            np.array([10, 9], dtype=np.int64), np.array([8, 7], dtype=np.int64), 2026
        )[::-1],
    )


@pytest.mark.parametrize("axis", [0, 1])
def test_shared_edge_values_and_first_derivatives_agree(axis: int) -> None:
    columns = np.array([9, 10] if axis == 0 else [9, 9], dtype=np.int64)
    rows = np.array([7, 7] if axis == 0 else [7, 8], dtype=np.int64)
    coefficients = edge_coefficients(columns, rows, 2026)
    amplitudes = np.array([[.3, .4, .5, .6], [.4, .5, .6, .7]])
    if axis == 1:
        amplitudes[1, 2] = amplitudes[0, 3]
    t = np.linspace(0, 1, 101)

    def value(cell: int, normal: float) -> NDArray[np.float64]:
        coordinate = np.full_like(t, normal)
        u, v = (coordinate, t) if axis == 0 else (t, coordinate)
        return residual_basis(u, v, coefficients[cell], amplitudes[cell])

    np.testing.assert_array_equal(value(0, 1), value(1, 0))
    epsilon = 1e-6
    left = (value(0, 1) - value(0, 1 - epsilon)) / epsilon
    right = (value(1, epsilon) - value(1, 0)) / epsilon
    assert np.max(np.abs(left - right)) < 0.00002
    assert np.max(np.abs(left)) < 0.00001
    epsilon = 1e-4
    left_second = (value(0, 1) - 2 * value(0, 1 - epsilon)
                   + value(0, 1 - 2 * epsilon)) / epsilon**2
    right_second = (value(1, 0) - 2 * value(1, epsilon)
                    + value(1, 2 * epsilon)) / epsilon**2
    assert np.max(np.abs(left_second - right_second)) < 0.01


def test_terrain_direction_uses_physical_slopes_and_flat_is_isotropic() -> None:
    axis = np.linspace(0, 1, 17, dtype=np.float32)
    xx, yy = np.meshgrid(axis, axis)
    reference = np.stack((xx, yy, xx + yy, xx * 0))
    np.testing.assert_allclose(terrain_x_weight(reference, 1, 1), [.75, .25, .5, .5])
    # Twice the x spacing means half the x gradient and one quarter its energy.
    assert terrain_x_weight(reference[2:3], 2, 1)[0] == pytest.approx(.35)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), 101.0, True])
def test_invalid_detail_amplitude_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        RegionalDetailSettings(value)


def test_cell_budget_is_separate_from_delivered_sample_budget() -> None:
    grid = EndpointGrid((0.0, 0.0, 1000.0, 1000.0), 129, 129)
    request = RegionalSamplingRequest("a" * 64, grid, 8, (0, 0, 1024, 1024))
    with pytest.raises(ValueError, match="parent cells"):
        detail_cell_window(request)


def test_mismatched_parent_request_fails(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    field, origin = detail_field
    request = sample(field, origin, 8).samples.request
    with pytest.raises(ValueError, match="different parent"):
        field.sample(replace(request, source_id="0" * 64))


def test_finer_bound_violation_fails_instead_of_clipping(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field, origin = detail_field
    original = sample(field, origin, 8)
    positive = np.flatnonzero(original.added_detail_m > 0)
    assert positive.size
    index = int(positive[0])
    method = regional.TerrainRegionSampler.sample

    def corrupt(
        self: regional.TerrainRegionSampler, *args: Any, **kwargs: Any
    ) -> regional.RegionalTerrainSamples:
        baseline = method(self, *args, **kwargs)
        ground: NDArray[np.float32] = baseline.elevation_m.copy()
        ground.flat[index] = field.parent.data.project.settings.maximum_elevation_m
        return replace(baseline, elevation_m=ground)

    monkeypatch.setattr(regional.TerrainRegionSampler, "sample", corrupt)
    with pytest.raises(ValueError, match="between fixed probes"):
        sample(field, origin, 8)


def test_protected_ground_can_equal_the_rounded_float32_height_ceiling() -> None:
    coast, settings, _constraints = fixture("square", 65, 42)
    ceiling = 1234.56
    settings = replace(settings, maximum_elevation_m=ceiling, detail_levels=2)
    project = TerrainProject(coast, settings, (ElevationPoint((0.5, 0.5), ceiling, 50.0),))
    parent = numerical_parent(project)
    assert parent.data.elevation_m[32, 32] == np.float32(ceiling)
    assert float(np.float32(ceiling)) > ceiling
    field = prepare_regional_detail(parent, RegionalDetailSettings())
    result = sample(field, (28, 28), 8)
    assert result.samples.elevation_m[32, 32] == np.float32(ceiling)
    assert result.added_detail_m[32, 32] == 0


def test_recorded_moments_match_the_actual_fixed_probe_grid(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    field, origin = detail_field
    detail = sample(field, origin, 16)
    weights = np.ones((17, 17), dtype=np.float64)
    weights[[0, -1], :] *= 0.5
    weights[:, [0, -1]] *= 0.5
    weights /= 256
    for index in np.flatnonzero(np.isfinite(detail.reference_cell_mean_m)):
        x = (int(detail.cell_columns[index]) - origin[0]) * 16
        y = (int(detail.cell_rows[index]) - origin[1]) * 16
        reference = detail.reference_elevation_m[y : y + 17, x : x + 17].astype(np.float64)
        actual = detail.samples.elevation_m[y : y + 17, x : x + 17].astype(np.float64)
        assert np.sum(reference * weights) == pytest.approx(
            detail.reference_cell_mean_m[index], abs=1e-10, rel=0
        )
        assert np.sum(actual * weights) == pytest.approx(
            detail.detailed_cell_mean_m[index], abs=1e-10, rel=0
        )


def test_repeated_detail_window_reuses_fixed_ground_probes(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field, origin = detail_field
    first = sample(field, origin, 8)
    assert first.evidence.probe_samples > 0

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("A cached cell must not repeat its fixed ground probes.")

    monkeypatch.setattr(PreparedTerrainField, "sample_ground", forbidden)
    repeated = sample(field, origin, 16)
    np.testing.assert_array_equal(first.cell_amplitude_m, repeated.cell_amplitude_m)
    np.testing.assert_array_equal(first.reference_cell_mean_m, repeated.reference_cell_mean_m)
    np.testing.assert_array_equal(first.detailed_cell_mean_m, repeated.detailed_cell_mean_m)
    np.testing.assert_array_equal(first.samples.elevation_m, repeated.samples.elevation_m[::2, ::2])


def assert_identical_detail(actual: DetailedRegion, expected: DetailedRegion) -> None:
    assert actual.evidence == expected.evidence
    assert actual.samples.request == expected.samples.request
    for left, right, names in (
        (actual, expected, (
            "reference_elevation_m", "added_detail_m", "cell_columns", "cell_rows",
            "cell_amplitude_m", "reference_cell_mean_m", "detailed_cell_mean_m",
        )),
        (actual.samples, expected.samples, (
            "x_km", "y_km", "elevation_m", "land_mask", "water_surface_m", "basin_intent_ids",
        )),
    ):
        for name in names:
            a, b = getattr(left, name), getattr(right, name)
            assert a.dtype == b.dtype and a.shape == b.shape
            assert a.tobytes() == b.tobytes(), name


def test_cache_reuses_overlap_without_changing_results_or_evidence(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    original, origin = detail_field
    cached = replace(original, cache_cells=128)
    uncached = replace(original, cache_cells=0)
    for position, factor in ((origin, 8), ((origin[0] + 1, origin[1] + 1), 8), (origin, 16)):
        assert_identical_detail(
            sample(cached, position, factor), sample(uncached, position, factor)
        )
    info = cached.cache_info()
    assert (info.cells, info.hits, info.misses, info.evictions) == (119, 81 + 100, 119, 0)
    assert uncached.cache_info().cells == uncached.cache_info().hits == 0


def test_eviction_and_clear_recompute_exactly(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    original, origin = detail_field
    cached = replace(original, cache_cells=8)
    expected = sample(replace(original, cache_cells=0), origin, 8, halo=1)
    for _ in range(2):
        assert_identical_detail(sample(cached, origin, 8, halo=1), expected)
        assert cached.cache_info().cells == 8
        assert cached.cache_info().evictions > 0
    cached.clear_cache()
    assert cached.cache_info().cells == cached.cache_info().hits == 0
    assert cached.cache_info().misses == cached.cache_info().evictions == 0
    assert_identical_detail(sample(cached, origin, 8, halo=1), expected)


def test_replacing_detail_context_does_not_inherit_cached_support(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    original, origin = detail_field
    sample(original, origin, 8)
    changed = replace(original, settings=RegionalDetailSettings(1.0))
    assert changed.cache_info().cells == 0
    expected = sample(replace(changed, cache_cells=0), origin, 8)
    assert_identical_detail(sample(changed, origin, 8), expected)
    assert np.max(expected.cell_amplitude_m) <= 1.0
    for fresh in (
        replace(original, parent=original.parent),
        prepare_regional_detail(original.parent, original.settings),
    ):
        assert fresh.cache_info().cells == 0


def test_failed_probe_batch_can_be_retried_without_stale_support(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, origin = detail_field
    cached = replace(original)
    method = PreparedTerrainField.sample_ground

    def invalid(
        self: PreparedTerrainField, x: NDArray[np.float64], y: NDArray[np.float64],
    ) -> NDArray[np.float32]:
        return np.full(x.shape, np.nan, dtype=np.float32)

    monkeypatch.setattr(PreparedTerrainField, "sample_ground", invalid)
    with pytest.raises(RuntimeError, match="invalid interior ground"):
        sample(cached, origin, 8)
    monkeypatch.setattr(PreparedTerrainField, "sample_ground", method)
    assert_identical_detail(
        sample(cached, origin, 8), sample(replace(original, cache_cells=0), origin, 8)
    )


def test_protection_batches_preserve_all_intersections_and_numeric_results(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from map_maker.terrain.pipeline import detail as detail_module

    field, origin = detail_field
    left, top = origin
    x, y = field.parent.data.x_km, field.parent.data.y_km
    # Many overlapping features exercise the pair-product query. Protect one half
    # so equivalence checks include both suppressed and active detail cells.
    geometry = box(x[left], y[top], x[left + 4], y[top + 8])
    tree = STRtree([geometry] * 100)
    context = replace(field, protections=tree, cache_cells=0)
    monkeypatch.setattr(detail_module, "DETAIL_CELL_BATCH", 4096)
    control = sample(context, origin, 8, 1)
    monkeypatch.setattr(detail_module, "DETAIL_CELL_BATCH", 7)
    original = STRtree.query
    sizes: list[int] = []

    def query(self: STRtree, geometries: Any, *args: Any, **kwargs: Any) -> Any:
        if self is tree:
            sizes.append(len(geometries))
            assert len(geometries) <= 7
        return original(self, geometries, *args, **kwargs)

    monkeypatch.setattr(STRtree, "query", query)
    batched = sample(context, origin, 8, 1)
    assert len(sizes) > 1
    assert batched.evidence == control.evidence
    for name in ("reference_elevation_m", "added_detail_m", "cell_amplitude_m",
                 "reference_cell_mean_m", "detailed_cell_mean_m"):
        np.testing.assert_array_equal(getattr(batched, name), getattr(control, name))
    np.testing.assert_array_equal(batched.samples.elevation_m, control.samples.elevation_m)


def test_support_halo_is_admitted_before_any_preparation() -> None:
    grid = EndpointGrid((0., 0., 1000., 1000.), 129, 129)
    # The 64 by 64 delivered cells fit, but their 66 by 66 support does not.
    request = RegionalSamplingRequest("a" * 64, grid, 8, (8, 8, 65 * 8, 65 * 8), 0)
    with pytest.raises(ValueError, match="including support halo"):
        detail_cell_window(request)
    small = replace(request, window=(8, 8, 9 * 8, 9 * 8))
    assert detail_cell_window(small) == (1, 1, 8, 8)
    assert detail_support_window(small) == (0, 0, 9, 9)


def test_partial_cell_request_matches_the_same_global_detail_field(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    field, origin = detail_field
    whole = sample(field, origin, 16)
    x0, y0, x1, y1 = whole.samples.request.window
    request = replace(whole.samples.request, window=(x0 + 3, y0 + 5, x1 - 7, y1 - 9))
    partial = replace(field, cache_cells=0).sample(request)
    np.testing.assert_array_equal(
        partial.samples.elevation_m, whole.samples.elevation_m[5:-9, 3:-7])
    np.testing.assert_array_equal(
        partial.reference_elevation_m, whole.reference_elevation_m[5:-9, 3:-7])


def test_crossing_edges_change_but_protected_interfaces_do_not(
    detail_field: tuple[PreparedRegionalDetail, tuple[int, int]],
) -> None:
    field, origin = detail_field
    result = sample(field, origin, 16)
    amplitudes = result.cell_amplitude_m.reshape(8, 8)
    changed_edge = False
    for row in range(8):
        for column in range(7):
            values = result.added_detail_m[row * 16:(row + 1) * 16 + 1, (column + 1) * 16]
            if min(amplitudes[row, column:column + 2]) == 0:
                assert np.count_nonzero(values) == 0
            else:
                changed_edge |= bool(np.any(values))
    for row in range(7):
        for column in range(8):
            values = result.added_detail_m[(row + 1) * 16, column * 16:(column + 1) * 16 + 1]
            if min(amplitudes[row:row + 2, column]) == 0:
                assert np.count_nonzero(values) == 0
            else:
                changed_edge |= bool(np.any(values))
    assert changed_edge
