"""Private numeric results for one parent session, bounded by allocation bytes and entries."""

from collections import OrderedDict
from dataclasses import dataclass, fields
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.domain.regional import RegionalDetailSettings, RegionalSamplingRequest
from map_maker.terrain.pipeline.detail import DetailedRegion
from map_maker.terrain.pipeline.regional import RegionalTerrainSamples

DEFAULT_RESULT_CACHE_BYTES = 64 * 1024 * 1024
MAX_RESULT_CACHE_BYTES = 256 * 1024 * 1024
RESULT_CACHE_ENTRY_LIMIT = 32
type RegionResultKey = tuple[RegionalSamplingRequest, RegionalDetailSettings | None]


@dataclass(frozen=True, slots=True)
class ParentRegionResult:
    samples: RegionalTerrainSamples
    detail: DetailedRegion | None = None


def retained_array_bytes(result: ParentRegionResult) -> int | None:
    """Count complete NumPy backing allocations once, including bases of small views.

    Unknown foreign buffers are not admitted. The session keeps these arrays
    private; callers receive artifact paths, never a mutable alias of a cache entry.
    """
    allocations: dict[int, int] = {}
    for value in (result.samples, result.detail):
        if value is None:
            continue
        for item in fields(value):
            member = getattr(value, item.name)
            if not isinstance(member, np.ndarray):
                continue
            array = cast(NDArray[Any], member)
            if array.flags.writeable or array.dtype.hasobject:
                return None
            while isinstance(array.base, np.ndarray):
                array = array.base
            if not array.flags.owndata:
                return None
            allocations[id(array)] = array.nbytes
    return sum(allocations.values())


@dataclass(frozen=True, slots=True)
class RegionResultCacheInfo:
    budget_bytes: int
    retained_bytes: int
    entries: int
    hits: int
    misses: int
    evictions: int
    bypasses: int


class RegionResultCache:
    def __init__(self, budget_bytes: int) -> None:
        if type(budget_bytes) is not int or not 0 <= budget_bytes <= MAX_RESULT_CACHE_BYTES:
            raise ValueError(
                "Regional result cache bytes must be an integer "
                f"from 0 to {MAX_RESULT_CACHE_BYTES}."
            )
        self._budget = budget_bytes
        self._entries: OrderedDict[RegionResultKey, tuple[ParentRegionResult, int]] = OrderedDict()
        self._bytes = self._hits = self._misses = self._evictions = self._bypasses = 0

    def get(self, key: RegionResultKey) -> ParentRegionResult | None:
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        self._hits += 1
        self._entries.move_to_end(key)
        return entry[0]

    def put(self, key: RegionResultKey, result: ParentRegionResult) -> None:
        size = retained_array_bytes(result) if self._budget else None
        if size is None or size > self._budget:
            self._bypasses += 1
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._bytes -= previous[1]
        while (self._bytes + size > self._budget
               or len(self._entries) >= RESULT_CACHE_ENTRY_LIMIT):
            _key, (_result, removed_bytes) = self._entries.popitem(last=False)
            self._bytes -= removed_bytes
            self._evictions += 1
        self._entries[key] = (result, size)
        self._bytes += size

    def clear(self) -> None:
        self._entries.clear()
        self._bytes = self._hits = self._misses = self._evictions = self._bypasses = 0

    def info(self) -> RegionResultCacheInfo:
        return RegionResultCacheInfo(
            self._budget, self._bytes, len(self._entries), self._hits, self._misses,
            self._evictions, self._bypasses,
        )
