"""Background work for Tk screens: long jobs with progress and cancellation, and
latest-wins view rendering. Tk itself is only touched on the Tk thread.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from dmtools.terrain.pipeline.control import CancellationToken, GenerationCancelled

type Report = Callable[[float | None, str], None]

POLL_MS = 30


class TkPump:
    """Runs callbacks posted from worker threads on the Tk thread."""

    def __init__(self, widget: tk.Misc) -> None:
        # Schedule on the toplevel, which outlives the widget's own Tcl commands.
        self._widget = widget.winfo_toplevel()
        self._queue: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._after: str | None = self._widget.after(POLL_MS, self._poll)
        self.closed = False

    def post(self, callback: Callable[[], None]) -> None:
        """Thread-safe: queue ``callback`` for the Tk thread."""
        self._queue.put(callback)

    def drain(self) -> None:
        while not self.closed:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                return
            callback()

    def _poll(self) -> None:
        self._after = None
        self.drain()
        if not self.closed:
            self._after = self._widget.after(POLL_MS, self._poll)

    def close(self) -> None:
        self.closed = True
        if self._after is not None:
            self._widget.after_cancel(self._after)
            self._after = None


@dataclass(frozen=True, slots=True)
class JobState:
    """What the status bar shows about the running job."""

    label: str
    fraction: float | None
    message: str
    cancellable: bool
    cancelling: bool = False


class JobRunner:
    """One long job at a time (generation, export, opening files) on a worker thread.

    ``work`` receives a progress reporter and a cancellation token; ``done`` runs on
    the Tk thread with its result. Cancellation and errors go to the runner's
    handlers, so a failed or cancelled job never installs a result.
    """

    def __init__(
        self,
        pump: TkPump,
        on_state: Callable[[JobState | None], None],
        on_error: Callable[[Exception], None],
        on_cancelled: Callable[[], None],
    ) -> None:
        self._pump = pump
        self._on_state = on_state
        self._on_error = on_error
        self._on_cancelled = on_cancelled
        self._state: JobState | None = None
        self._token: CancellationToken | None = None
        self._lock = threading.Lock()
        self._latest: tuple[float | None, str] | None = None

    @property
    def busy(self) -> bool:
        return self._state is not None

    @property
    def state(self) -> JobState | None:
        return self._state

    def start[T](
        self,
        label: str,
        work: Callable[[Report, CancellationToken], T],
        done: Callable[[T], None],
        *,
        cancellable: bool = True,
    ) -> bool:
        """Start ``work``; returns False (and does nothing) while another job runs."""
        if self.busy or self._pump.closed:
            return False
        token = CancellationToken()
        self._token = token
        self._set_state(JobState(label, None, "", cancellable))

        def report(fraction: float | None, message: str) -> None:
            with self._lock:
                pending = self._latest is not None
                self._latest = (fraction, message)
            if not pending:
                self._pump.post(self._show_progress)

        def finish(callback: Callable[[], None]) -> None:
            def deliver() -> None:
                if self._token is not token:
                    return
                self._token = None
                self._set_state(None)
                callback()

            self._pump.post(deliver)

        def run() -> None:
            try:
                value = work(report, token)
            except GenerationCancelled:
                finish(self._on_cancelled)
            except Exception as error:
                finish(lambda error=error: self._on_error(error))
            else:
                if token.is_cancelled:
                    finish(self._on_cancelled)
                else:
                    finish(lambda: done(value))

        threading.Thread(target=run, name=f"job: {label}", daemon=True).start()
        return True

    def cancel(self) -> None:
        state, token = self._state, self._token
        if state is None or token is None or not state.cancellable or state.cancelling:
            return
        token.cancel()
        self._set_state(JobState(state.label, state.fraction, "Stopping at the next checkpoint…",
                                 cancellable=True, cancelling=True))

    def close(self) -> None:
        if self._token is not None:
            self._token.cancel()
        self._token = None
        self._state = None

    def _show_progress(self) -> None:
        with self._lock:
            latest, self._latest = self._latest, None
        state = self._state
        if latest is None or state is None or state.cancelling:
            return
        fraction, message = latest
        self._set_state(JobState(
            state.label, state.fraction if fraction is None else fraction, message,
            state.cancellable,
        ))

    def _set_state(self, state: JobState | None) -> None:
        self._state = state
        self._on_state(state)


class LatestWorker:
    """Renders views off the Tk thread, newest request first.

    A request submitted while another runs replaces any queued one, and results
    are delivered only if they are newer than what is already shown, so dragging
    shows intermediate frames without ever going backwards.
    """

    def __init__(self, pump: TkPump, on_error: Callable[[Exception], None]) -> None:
        self._pump = pump
        self._on_error = on_error
        self._lock = threading.Lock()
        self._pending: tuple[int, Callable[[], object], Callable[[object], None]] | None = None
        self._running = False
        self._submitted = 0
        self._shown = 0
        self._settled = 0

    @property
    def idle(self) -> bool:
        """True when every submitted request has been delivered or superseded."""
        return self._settled == self._submitted

    def submit[T](self, work: Callable[[], T], done: Callable[[T], None]) -> None:
        with self._lock:
            self._submitted += 1
            self._pending = (self._submitted, work, cast(Callable[[object], None], done))
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._loop, name="view-render", daemon=True).start()

    def cancel(self) -> None:
        """Forget queued and running requests; nothing more is delivered for them."""
        with self._lock:
            self._pending = None
            self._shown = self._settled = self._submitted

    def _loop(self) -> None:
        while True:
            with self._lock:
                request, self._pending = self._pending, None
                if request is None:
                    self._running = False
                    return
            sequence, work, done = request
            try:
                value = work()
            except Exception as error:
                self._pump.post(lambda error=error, sequence=sequence: self._fail(sequence, error))
            else:
                self._pump.post(
                    lambda value=value, sequence=sequence, done=done:
                    self._deliver(sequence, value, done)
                )

    def _deliver(self, sequence: int, value: object, done: Callable[[object], None]) -> None:
        self._settle(sequence)
        if sequence > self._shown:
            self._shown = sequence
            done(value)

    def _fail(self, sequence: int, error: Exception) -> None:
        self._settle(sequence)
        if sequence > self._shown:
            self._on_error(error)

    def _settle(self, sequence: int) -> None:
        with self._lock:
            # Requests replaced before they ran settle with the newer one.
            if self._pending is None or self._pending[0] <= sequence:
                self._settled = max(self._settled, sequence)
            else:
                self._settled = max(self._settled, self._pending[0] - 1)
