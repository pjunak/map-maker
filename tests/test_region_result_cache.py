"""Result retention counts backing allocations and enforces both cache limits."""

from dataclasses import replace

import numpy as np
import pytest

from map_maker.terrain.application.region_cache import (
    MAX_RESULT_CACHE_BYTES,
    RESULT_CACHE_ENTRY_LIMIT,
    ParentRegionResult,
    RegionResultCache,
    retained_array_bytes,
)
from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.domain.regional import RegionalDetailSettings, RegionalSamplingRequest
from map_maker.terrain.pipeline.regional import RegionalTerrainSamples


def result() -> ParentRegionResult:
    grid = EndpointGrid((0., 0., 10., 10.), 3, 3)
    request = RegionalSamplingRequest("a" * 64, grid, 1, (0, 0, 1, 1), 0)
    axis = np.array([0., 5.])
    ground = np.zeros((2, 2), dtype=np.float32)
    land = np.ones((2, 2), dtype=np.bool_)
    labels = np.zeros((2, 2), dtype=np.uint32)
    for array in (axis, ground, land, labels):
        array.setflags(write=False)
    return ParentRegionResult(RegionalTerrainSamples(
        request, axis, axis, ground, land, ground, labels, grid, 1000.,
    ))


def test_count_full_backing_storage_and_deduplicate_shared_arrays() -> None:
    value = result()
    assert retained_array_bytes(value) == 16 + 16 + 4 + 16
    backing = np.zeros(1024, dtype=np.float32)
    view = backing[:4].reshape(2, 2)
    view.setflags(write=False)
    value = replace(value, samples=replace(value.samples, elevation_m=view))
    assert retained_array_bytes(value) == backing.nbytes + 52


def test_writable_and_foreign_buffers_are_not_retained() -> None:
    original = result()
    cache = RegionResultCache(1024)
    objects = np.zeros((2, 2), dtype=object)
    objects.setflags(write=False)
    for array in (
        np.zeros((2, 2), dtype=np.float32),
        np.frombuffer(bytes(16), dtype=np.float32).reshape(2, 2),
        objects,
    ):
        value = replace(original, samples=replace(original.samples, elevation_m=array))
        assert retained_array_bytes(value) is None
        cache.put((value.samples.request, None), value)
    assert cache.info().entries == cache.info().retained_bytes == 0
    assert cache.info().bypasses == 3


def test_lru_eviction_respects_bytes_and_touch_order() -> None:
    value = result()
    size = retained_array_bytes(value)
    assert size is not None
    cache = RegionResultCache(2 * size)
    a = (value.samples.request, None)
    b = (value.samples.request, RegionalDetailSettings(1.))
    c = (value.samples.request, RegionalDetailSettings(2.))
    cache.put(a, value)
    cache.put(b, value)
    assert cache.get(a) is value
    cache.put(c, value)
    assert cache.get(b) is None
    assert cache.get(a) is cache.get(c) is value
    assert cache.info().retained_bytes == 2 * size
    assert cache.info().evictions == 1
    cache.put(a, value)
    assert cache.info().retained_bytes == 2 * size
    assert cache.info().evictions == 1
    cache.clear()
    info = cache.info()
    assert info.budget_bytes == 2 * size
    assert info.retained_bytes == info.entries == info.hits == info.misses == 0
    assert info.evictions == info.bypasses == 0


def test_entry_limit_bounds_tiny_results_even_with_large_byte_budget() -> None:
    cache = RegionResultCache(MAX_RESULT_CACHE_BYTES)
    value = result()
    for index in range(RESULT_CACHE_ENTRY_LIMIT + 1):
        cache.put((value.samples.request, RegionalDetailSettings(index + 1)), value)
        assert cache.info().entries <= RESULT_CACHE_ENTRY_LIMIT
    assert cache.info().evictions == 1
    assert cache.get((value.samples.request, RegionalDetailSettings(1))) is None


@pytest.mark.parametrize("budget", [0, 1])
def test_disabled_or_oversized_results_are_bypassed(budget: int) -> None:
    cache = RegionResultCache(budget)
    value = result()
    key = value.samples.request, None
    cache.put(key, value)
    assert cache.get(key) is None
    assert cache.info().bypasses == 1
    assert cache.info().entries == cache.info().retained_bytes == 0


@pytest.mark.parametrize("budget", [-1, MAX_RESULT_CACHE_BYTES + 1, True, 1.5])
def test_invalid_result_budget_is_rejected(budget: int) -> None:
    with pytest.raises(ValueError, match="cache bytes"):
        RegionResultCache(budget)
