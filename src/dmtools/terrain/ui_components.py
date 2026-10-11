"""Small reusable Tk widgets built on the shared styles (``ui_style``)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk

from dmtools.terrain.ui_jobs import JobState
from dmtools.terrain.ui_style import GAP


class WrappingLabel(ttk.Label):
    """A label whose text wraps to its current width."""

    def __init__(self, parent: tk.Misc, *, minimum: int = 120, **options: object) -> None:
        super().__init__(parent, **options)  # type: ignore[arg-type]
        self._minimum = minimum
        self.bind("<Configure>", self._rewrap, add="+")

    def _rewrap(self, event: tk.Event[tk.Misc]) -> None:
        width = max(self._minimum, int(event.width) - 4)
        if int(self.cget("wraplength") or 0) != width:
            self.configure(wraplength=width)


class SegmentedChoice(ttk.Frame):
    """Mutually exclusive options shown as joined toggle buttons."""

    def __init__(
        self,
        parent: tk.Misc,
        variable: tk.StringVar,
        choices: Sequence[tuple[str, str]],
        command: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Toolbar.TFrame")
        self.buttons: dict[str, ttk.Radiobutton] = {}
        for value, label in choices:
            button = ttk.Radiobutton(
                self, text=label, value=value, variable=variable, style="Segment.TRadiobutton",
                command=command or (lambda: None), takefocus=False,
            )
            button.pack(side="left")
            self.buttons[value] = button

    def set_enabled(self, value: str, enabled: bool) -> None:
        self.buttons[value].configure(state="normal" if enabled else "disabled")


def section(parent: tk.Misc, title: str, *, first: bool = False) -> ttk.Frame:
    """A titled group in a sidebar page; returns the frame to fill (packed)."""
    ttk.Label(parent, text=title, style="Section.TLabel").pack(
        anchor="w", pady=(0 if first else 2 * GAP, GAP // 2)
    )
    body = ttk.Frame(parent, style="Panel.TFrame")
    body.pack(fill="x")
    return body


class StatusBar(ttk.Frame):
    """The workspace message line with job progress and a Cancel button."""

    def __init__(self, parent: tk.Misc, message: tk.StringVar, cancel: Callable[[], None]) -> None:
        super().__init__(parent, style="Paper.TFrame")
        self.message = message
        self.columnconfigure(0, weight=1)
        ttk.Label(self, textvariable=message, style="Status.TLabel").grid(
            row=0, column=0, sticky="ew"
        )
        self.progress = ttk.Progressbar(
            self, mode="determinate", maximum=1.0, length=220,
            style="Accent.Horizontal.TProgressbar",
        )
        self.cancel_button = ttk.Button(self, text="Cancel", style="Small.TButton", command=cancel)
        self.show(None)

    def show(self, state: JobState | None) -> None:
        if state is None:
            self.progress.stop()
            self.progress.grid_remove()
            self.cancel_button.grid_remove()
            return
        detail = f" · {state.message}" if state.message else ""
        self.message.set(state.label + detail)
        if state.fraction is None:
            if str(self.progress.cget("mode")) != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(15)
        else:
            if str(self.progress.cget("mode")) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
            self.progress.configure(value=min(1.0, max(0.0, state.fraction)))
        self.progress.grid(row=0, column=1, padx=(GAP, 0))
        if state.cancellable:
            self.cancel_button.grid(row=0, column=2, padx=(GAP, 0))
            self.cancel_button.configure(state="disabled" if state.cancelling else "normal")
        else:
            self.cancel_button.grid_remove()
