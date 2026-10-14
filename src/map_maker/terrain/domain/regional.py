"""Bounded regional requests on subdivisions of one reference endpoint grid."""

from dataclasses import dataclass
from math import ceil, floor, isfinite, ulp

from map_maker.terrain.domain.coordinates import Bounds, EndpointGrid

REGIONAL_SAMPLE_LIMIT = 2_000_000
MAX_REGIONAL_REFINEMENT = 65_536


def _refinement(value: object) -> None:
    if (isinstance(value, bool) or not isinstance(value, int)
            or not 1 <= value <= MAX_REGIONAL_REFINEMENT or value & (value - 1)):
        raise ValueError("Regional refinement must be a power of two from 1 through 65536.")


def _grid_precision(grid: EndpointGrid, refinement: int) -> None:
    if max(grid.width - 1, grid.height - 1) * refinement > 2**52:
        raise ValueError("Regional grid addresses exceed supported coordinate precision.")
    a, b, c, d = grid.extent_km
    for first, last, spacing in ((a, c, grid.x_spacing_km), (b, d, grid.y_spacing_km)):
        if spacing / refinement < max(ulp(first), ulp(last)):
            raise ValueError("Regional spacing is below coordinate precision.")


def _axis_position(start: float, stop: float, count: int, index: int, factor: int) -> float:
    coarse, remainder = divmod(index, factor)
    step = (stop - start) / (count - 1)
    lower = stop if coarse == count - 1 else start + coarse * step
    if not remainder:
        return lower
    upper = stop if coarse + 1 == count - 1 else start + (coarse + 1) * step
    return lower + (upper - lower) * (remainder / factor)


@dataclass(frozen=True, slots=True)
class RegionalSamplingRequest:
    """Inclusive global fine-grid addresses; a source identity binds the full field.

    The source is either an input-defined field or a verified immutable parent.
    A halo supplies neighboring point samples, not a new local catchment.
    """

    source_id: str
    reference_grid: EndpointGrid
    refinement: int
    window: tuple[int, int, int, int]
    halo_cells: int = 1

    def __post_init__(self) -> None:
        if len(self.source_id) != 64 or any(c not in "0123456789abcdef" for c in self.source_id):
            raise ValueError("Regional source identity must be a lowercase SHA-256 digest.")
        _refinement(self.refinement)
        _grid_precision(self.reference_grid, self.refinement)
        if (type(self.halo_cells) is not int
                or not 0 <= self.halo_cells <= 32):
            raise ValueError("Regional halo must be an integer from 0 through 32 cells.")
        if len(self.window) != 4 or any(type(i) is not int for i in self.window):
            raise ValueError("Regional window must contain four integer grid addresses.")
        x0, y0, x1, y1 = self.window
        nx = (self.reference_grid.width - 1) * self.refinement
        ny = (self.reference_grid.height - 1) * self.refinement
        if not (0 <= x0 < x1 <= nx and 0 <= y0 < y1 <= ny):
            raise ValueError("Regional window must cover intervals inside the reference grid.")
        height, width = self.sample_shape
        if height * width > REGIONAL_SAMPLE_LIMIT:
            raise ValueError(f"Regional request needs {height * width:,} samples including halo; "
                             f"limit is {REGIONAL_SAMPLE_LIMIT:,}. "
                             "Use a smaller window or refinement.")

    @property
    def sample_window(self) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = self.window
        h = self.halo_cells
        return (max(0, x0 - h), max(0, y0 - h),
                min((self.reference_grid.width - 1) * self.refinement, x1 + h),
                min((self.reference_grid.height - 1) * self.refinement, y1 + h))

    @property
    def sample_shape(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.sample_window
        return y1 - y0 + 1, x1 - x0 + 1

    @property
    def core_slices(self) -> tuple[slice, slice]:
        x0, y0, x1, y1 = self.window
        sx, sy, _ex, _ey = self.sample_window
        return slice(y0 - sy, y1 - sy + 1), slice(x0 - sx, x1 - sx + 1)

    def grid(self, *, include_halo: bool = False) -> EndpointGrid:
        x0, y0, x1, y1 = self.sample_window if include_halo else self.window
        a, b, c, d = self.reference_grid.extent_km
        nx, ny = self.reference_grid.width, self.reference_grid.height
        factor = self.refinement
        return EndpointGrid((_axis_position(a, c, nx, x0, factor),
                             _axis_position(b, d, ny, y0, factor),
                             _axis_position(a, c, nx, x1, factor),
                             _axis_position(b, d, ny, y1, factor)), x1 - x0 + 1, y1 - y0 + 1)

    @classmethod
    def for_bounds(
        cls, source_id: str, reference_grid: EndpointGrid, bounds_km: Bounds,
        refinement: int, *, halo_cells: int = 1,
    ) -> RegionalSamplingRequest:
        """Cover metric bounds with globally aligned nodes, rounding outwards."""
        _refinement(refinement)
        _grid_precision(reference_grid, refinement)
        EndpointGrid(bounds_km, 2, 2)  # Validate units/finite nonempty extent without allocation.
        a, b, c, d = reference_grid.extent_km
        x0, y0, x1, y1 = bounds_km
        if not (a <= x0 < x1 <= c and b <= y0 < y1 <= d):
            raise ValueError("Requested bounds must lie inside the reference extent in kilometres.")

        def cover(
            start: float, stop: float, count: int, low: float, high: float,
        ) -> tuple[int, int]:
            last = (count - 1) * refinement
            lo = max(0, min(last - 1, floor((low - start) / (stop - start) * last)))
            hi = max(1, min(last, ceil((high - start) / (stop - start) * last)))
            # Correct only arithmetic rounding at a grid boundary. The final
            # decision uses the same parent-anchored positions as sampling.
            def at(index: int) -> float:
                return _axis_position(start, stop, count, index, refinement)
            while lo > 0 and at(lo) > low:
                lo -= 1
            while lo < last - 1 and at(lo + 1) <= low:
                lo += 1
            while hi < last and at(hi) < high:
                hi += 1
            while hi > 1 and at(hi - 1) >= high:
                hi -= 1
            return lo, hi

        left, right = cover(a, c, reference_grid.width, x0, x1)
        top, bottom = cover(b, d, reference_grid.height, y0, y1)
        return cls(source_id, reference_grid, refinement, (left, top, right, bottom), halo_cells)


DETAIL_CELL_LIMIT = 4096
DETAIL_PROBE_INTERVALS = 16


@dataclass(frozen=True, slots=True)
class RegionalDetailSettings:
    """An explicit experimental residual budget; it never changes parent settings."""

    amplitude_m: float = 12.

    def __post_init__(self) -> None:
        if (isinstance(self.amplitude_m, bool) or not isfinite(self.amplitude_m)
                or not 0 < self.amplitude_m <= 100):
            raise ValueError("Experimental detail amplitude must be finite and in (0, 100] metres.")


def _detail_windows(request: RegionalSamplingRequest) -> tuple[
    tuple[int, int, int, int], tuple[int, int, int, int],
]:
    if request.refinement < 8:
        raise ValueError("Experimental detail requires refinement of at least 8.")
    x0, y0, x1, y1 = request.sample_window
    factor = request.refinement
    left, top = x0 // factor, y0 // factor
    right, bottom = (x1 - 1) // factor, (y1 - 1) // factor
    grid = request.reference_grid
    support = (max(0, left - 1), max(0, top - 1),
               min(grid.width - 2, right + 1), min(grid.height - 2, bottom + 1))
    count = (support[2] - support[0] + 1) * (support[3] - support[1] + 1)
    if count > DETAIL_CELL_LIMIT:
        raise ValueError(f"Detail preparation needs {count:,} parent cells including support halo; "
                         f"limit is {DETAIL_CELL_LIMIT:,}. Use a smaller window.")
    return (left, top, right, bottom), support


def detail_cell_window(request: RegionalSamplingRequest) -> tuple[int, int, int, int]:
    """Delivered cells, with the shared-edge support halo included in admission."""
    return _detail_windows(request)[0]


def detail_support_window(request: RegionalSamplingRequest) -> tuple[int, int, int, int]:
    """One extra parent cell on each side, clipped to the reference frame."""
    return _detail_windows(request)[1]
