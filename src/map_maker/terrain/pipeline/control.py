"""Cooperative cancellation at generation checkpoints, with no worker ownership."""

from collections.abc import Callable
from threading import Event

type ProgressCallback = Callable[[float, str], None]


class GenerationCancelled(Exception):
    """A requested stop, distinct from invalid inputs or a failed generation."""


class CancellationToken:
    """One-way, thread-safe stop request; create a new token for each operation."""

    def __init__(self) -> None:
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def checkpoint(self) -> None:
        if self.is_cancelled:
            raise GenerationCancelled("Terrain generation cancelled.")


def check_cancelled(cancellation: CancellationToken | None) -> None:
    if cancellation is not None:
        cancellation.checkpoint()


def cancellable_progress(
    progress: ProgressCallback | None, cancellation: CancellationToken | None,
) -> ProgressCallback | None:
    """Check on both sides of callbacks, including callbacks that request a stop."""
    if cancellation is None:
        return progress

    def report(fraction: float, message: str) -> None:
        cancellation.checkpoint()
        if progress is not None:
            progress(fraction, message)
        cancellation.checkpoint()

    return report
