# pyright: reportPrivateUsage=false
"""Background jobs and latest-wins rendering deliver on the Tk thread, in order."""

import threading
import time
import tkinter as tk
from collections.abc import Callable, Iterator

import pytest

from map_maker.terrain.pipeline.control import CancellationToken
from map_maker.terrain.ui_jobs import JobRunner, JobState, LatestWorker, Report, TkPump


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    try:
        window = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}")
    window.withdraw()
    yield window
    window.destroy()


def pump_until(root: tk.Tk, condition: Callable[[], bool], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    assert condition()


class Recorder:
    def __init__(self) -> None:
        self.states: list[JobState | None] = []
        self.errors: list[Exception] = []
        self.cancelled = 0
        self.results: list[object] = []


def runner(root: tk.Tk) -> tuple[JobRunner, Recorder]:
    record = Recorder()

    def cancelled() -> None:
        record.cancelled += 1

    return JobRunner(TkPump(root), record.states.append, record.errors.append, cancelled), record


def test_job_reports_progress_then_delivers_on_the_tk_thread(root: tk.Tk) -> None:
    jobs, record = runner(root)
    threads: list[threading.Thread] = []

    def work(report: Report, _token: CancellationToken) -> int:
        report(0.5, "halfway")
        return 42

    def done(value: int) -> None:
        threads.append(threading.current_thread())
        record.results.append(value)

    assert jobs.start("Working", work, done)
    assert jobs.busy and not jobs.start("Second", work, done)
    pump_until(root, lambda: bool(record.results))
    assert record.results == [42] and threads == [threading.main_thread()]
    assert not jobs.busy and record.states[-1] is None
    assert any(s is not None and s.fraction == 0.5 and s.message == "halfway"
               for s in record.states)


def test_cancelled_and_failed_jobs_never_deliver_results(root: tk.Tk) -> None:
    jobs, record = runner(root)
    started = threading.Event()

    def slow(_report: Report, token: CancellationToken) -> int:
        started.set()
        while True:
            token.checkpoint()
            time.sleep(0.005)

    jobs.start("Slow", slow, record.results.append)
    started.wait(5)
    jobs.cancel()
    state = jobs.state
    assert state is not None and state.cancelling
    pump_until(root, lambda: not jobs.busy)
    assert record.cancelled == 1 and not record.results

    def broken(_report: Report, _token: CancellationToken) -> int:
        raise ValueError("bad input")

    jobs.start("Broken", broken, record.results.append)
    pump_until(root, lambda: not jobs.busy)
    assert [str(e) for e in record.errors] == ["bad input"] and not record.results


def test_latest_worker_skips_superseded_requests_and_never_goes_backwards(root: tk.Tk) -> None:
    errors: list[Exception] = []
    worker = LatestWorker(TkPump(root), errors.append)
    gate = threading.Event()
    shown: list[int] = []

    def first() -> int:
        gate.wait(5)
        return 1

    worker.submit(first, shown.append)
    for value in (2, 3, 4):
        worker.submit(lambda value=value: value, shown.append)
    assert not worker.idle
    gate.set()
    pump_until(root, lambda: worker.idle)
    # The running request finishes; queued ones are replaced by the newest.
    assert shown == [1, 4] and not errors
    worker.submit(lambda: 5, shown.append)
    worker.cancel()
    pump_until(root, lambda: worker.idle)
    root.update()
    assert shown == [1, 4]
