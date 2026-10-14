"""Scalar support eviction, memory cardinality and operational controls."""

import pytest

from map_maker.terrain.domain.regional import DETAIL_CELL_LIMIT
from map_maker.terrain.pipeline.detail_cache import CellDetailSupport, DetailSupportCache


def test_recently_used_cell_survives_eviction_and_replacement() -> None:
    cache = DetailSupportCache(2)
    first = CellDetailSupport(False, 12.0, 400.0, 400.0, 0.5)
    second = CellDetailSupport(True, 0.0, float("nan"), float("nan"), 0.5)
    cache.put(1, 2, first)
    cache.put(2, 1, second)
    assert cache.get(1, 2) is first  # Touch the older entry before inserting another.
    cache.put(3, 4, first)
    assert cache.get(2, 1) is None
    assert cache.get(1, 2) is first
    cache.put(1, 2, second)
    assert cache.get(1, 2) is second
    assert cache.get(3, 4) is first
    info = cache.info()
    assert (info.capacity, info.cells, info.hits, info.misses, info.evictions) == (2, 2, 4, 1, 1)
    cache.clear()
    assert cache.info().cells == cache.info().hits == cache.info().misses == 0
    assert cache.info().evictions == 0
    assert cache.info().capacity == 2


@pytest.mark.parametrize("capacity", [0, 1, 31, DETAIL_CELL_LIMIT])
def test_cache_never_retains_more_than_its_cell_budget(capacity: int) -> None:
    cache = DetailSupportCache(capacity)
    support = CellDetailSupport(False, 1.0, 2.0, 2.0, 0.5)
    for column in range(DETAIL_CELL_LIMIT + 10):
        cache.put(column, 0, support)
        assert cache.info().cells <= capacity
    assert cache.info().cells == capacity
    if capacity == 0:
        assert cache.get(DETAIL_CELL_LIMIT + 9, 0) is None
        assert cache.info().evictions == 0


@pytest.mark.parametrize("capacity", [-1, DETAIL_CELL_LIMIT + 1, True, 1.0])
def test_invalid_cache_capacity_is_rejected(capacity: int) -> None:
    with pytest.raises(ValueError, match="cache capacity"):
        DetailSupportCache(capacity)
