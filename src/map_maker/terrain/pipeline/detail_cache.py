"""Bounded scalar cell support owned by one prepared detail context.

This cache retains no terrain arrays, geometries, or parent references. Callers
own its identity and use it serially; it is neither persistent nor shared.
"""

from collections import OrderedDict
from dataclasses import dataclass

from map_maker.terrain.domain.regional import DETAIL_CELL_LIMIT


@dataclass(frozen=True, slots=True)
class CellDetailSupport:
    protected: bool
    amplitude_m: float
    reference_mean_m: float
    detailed_mean_m: float  # NaN until a halo-only cell is requested for delivery.
    x_weight: float


@dataclass(frozen=True, slots=True)
class DetailCacheInfo:
    capacity: int
    cells: int
    hits: int
    misses: int
    evictions: int


class DetailSupportCache:
    """Least-recently-used cells, with zero capacity as an uncached control."""

    def __init__(self, capacity: int) -> None:
        if type(capacity) is not int or not 0 <= capacity <= DETAIL_CELL_LIMIT:
            raise ValueError(
                f"Detail cache capacity must be an integer from 0 to {DETAIL_CELL_LIMIT}."
            )
        self._capacity = capacity
        self._cells: OrderedDict[tuple[int, int], CellDetailSupport] = OrderedDict()
        self._hits = self._misses = self._evictions = 0

    def get(self, column: int, row: int) -> CellDetailSupport | None:
        key = (column, row)
        value = self._cells.get(key)
        if value is None:
            self._misses += 1
        else:
            self._hits += 1
            self._cells.move_to_end(key)
        return value

    def put(self, column: int, row: int, support: CellDetailSupport) -> None:
        if not self._capacity:
            return
        key = (column, row)
        if key not in self._cells and len(self._cells) == self._capacity:
            self._cells.popitem(last=False)
            self._evictions += 1
        self._cells[key] = support
        self._cells.move_to_end(key)

    def clear(self) -> None:
        self._cells.clear()
        self._hits = self._misses = self._evictions = 0

    def info(self) -> DetailCacheInfo:
        return DetailCacheInfo(
            self._capacity, len(self._cells), self._hits, self._misses, self._evictions
        )
