"""Small reusable Tk widgets built on the shared styles (``ui_style``)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk

from dmtools.terrain.ui_jobs import JobState
from dmtools.terrain.ui_style import GAP

REWRAP_SLACK_PX = 12
INITIAL_WRAP_PX = 300


class WrappingLabel(ttk.Label):
    """A label whose text wraps to its current width."""

    def __init__(
        self, parent: tk.Misc, *, minimum: int = 120, initial: int = INITIAL_WRAP_PX,
        **options: object,
    ) -> None:
        # Start narrow, so long text never makes its column claim the window.
        super().__init__(parent, wraplength=initial, **options)  # type: ignore[arg-type]
        self._minimum = minimum
        self.bind("<Configure>", self._rewrap, add="+")

    def _rewrap(self, event: tk.Event[tk.Misc]) -> None:
        width = max(self._minimum, int(event.width) - 4)
        # Small changes are usually the label's own response to rewrapping; reacting
        # to them can make the geometry manager oscillate.
        if abs(int(str(self.cget("wraplength")) or 0) - width) > REWRAP_SLACK_PX:
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


class MapInfoStrip(ttk.Frame):
    """Legend and under-the-cursor readout below a map.

    Its height is fixed, so a longer readout never resizes (and redraws) the map.
    """

    HEIGHT = 92

    def __init__(
        self, parent: tk.Misc, legend: tk.StringVar, inspection: tk.StringVar
    ) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=(GAP, GAP // 2, GAP, GAP),
                         height=self.HEIGHT)
        self.grid_propagate(False)
        self.columnconfigure(0, weight=3, uniform="info")
        self.columnconfigure(1, weight=2, uniform="info")
        ttk.Label(self, text="Legend", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Under the cursor", style="Section.TLabel").grid(
            row=0, column=1, sticky="w", padx=(2 * GAP, 0)
        )
        WrappingLabel(self, textvariable=legend, style="Muted.TLabel").grid(
            row=1, column=0, sticky="new"
        )
        WrappingLabel(self, textvariable=inspection, style="Readout.TLabel").grid(
            row=1, column=1, sticky="new", padx=(2 * GAP, 0)
        )


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
