"""Aggregate admission, reservation ownership and request-size estimates."""

import gc
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from threading import Barrier

import pytest

from map_maker.terrain.application.region_memory import (
    ParentMemoryEstimate,
    RegionalMemoryAdmissionError,
    RegionalMemoryBudget,
    estimate_regional_job,
)
from map_maker.terrain.domain import EndpointGrid
from map_maker.terrain.domain.regional import RegionalSamplingRequest


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_budget_requires_positive_integer_bytes(value: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        RegionalMemoryBudget(value)


def test_failed_resize_preserves_reservation_and_close_is_idempotent() -> None:
    pool = RegionalMemoryBudget(100)
    with pool.reserve(40, "parent") as parent:
        with pool.reserve(30, "sampling"):
            with pytest.raises(RegionalMemoryAdmissionError, match="budget 100"):
                parent.resize(71)
            assert pool.info().reserved_bytes == 70
            parent.resize(70)
            assert pool.info().reserved_bytes == 100
        assert pool.info().reserved_bytes == 70
    parent.close()
    assert pool.info().reserved_bytes == pool.info().reservations == 0
    assert pool.info().peak_reserved_bytes == 100
    with pytest.raises(RuntimeError, match="closed"):
        parent.resize(1)


def test_failed_new_reservation_and_abandoned_owner_do_not_leak_capacity() -> None:
    pool = RegionalMemoryBudget(100)
    with pytest.raises(RegionalMemoryAdmissionError):
        pool.reserve(101, "too large")
    for value in (-1, True, 1.5):
        with pytest.raises(ValueError):
            pool.reserve(value, "invalid")  # type: ignore[arg-type]
    assert pool.info().reservations == 0
    lease = pool.reserve(100, "abandoned")
    del lease
    gc.collect()
    assert pool.info().reserved_bytes == pool.info().reservations == 0


def test_concurrent_jobs_cannot_over_admit_the_shared_budget() -> None:
    pool = RegionalMemoryBudget(1000)
    start, attempted = Barrier(8), Barrier(8)

    def attempt(_index: int) -> bool:
        start.wait(timeout=10)
        lease = None
        try:
            with suppress(RegionalMemoryAdmissionError):
                lease = pool.reserve(400, "job")
            attempted.wait(timeout=10)  # Successful reservations remain held until all try.
            return lease is not None
        finally:
            if lease is not None:
                lease.close()

    with ThreadPoolExecutor(max_workers=8) as workers:
        assert sum(workers.map(attempt, range(8))) == 2
    assert pool.info().peak_reserved_bytes == 800
    assert pool.info().reserved_bytes == pool.info().reservations == 0


def test_job_estimate_includes_halo_arrays_thin_panels_and_cold_preparation() -> None:
    parent = ParentMemoryEstimate(0, 0, 0, 1234, 0, 0, 0, 5)
    grid = EndpointGrid((0., 0., 10., 10.), 65, 65)
    request = RegionalSamplingRequest("a" * 64, grid, 8, (8, 8, 9, 300))
    height, width = request.sample_shape
    plain = estimate_regional_job(request, parent, detail=False, needs_preparation=False)
    detail = estimate_regional_job(request, parent, detail=True, needs_preparation=False)
    cold = estimate_regional_job(request, parent, detail=True, needs_preparation=True)
    assert plain.result_array_bytes == 13 * height * width + 8 * (height + width)
    assert detail.result_array_bytes > plain.result_array_bytes
    assert detail.rendering_allowance_bytes >= 12 * 300 * (293 + 56)
    assert cold.preparation_allowance_bytes > detail.preparation_allowance_bytes == 0
    assert cold.total_bytes > detail.total_bytes > plain.total_bytes
