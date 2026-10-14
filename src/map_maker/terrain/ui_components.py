"""Small reusable Tk widgets built on the shared styles (``ui_style``)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from tkinter import ttk

from map_maker.terrain.ui_jobs import JobState
from map_maker.terrain.ui_style import GAP, PANEL

REWRAP_SLACK_PX = 12
INITIAL_WRAP_PX = 300
WHEEL_UNITS = 120  # one mouse-wheel notch on Windows


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


def page_title(parent: tk.Misc, title: str, intro: str = "") -> None:
    """The heading of a step page and one sentence on what the step is for (packed)."""
    ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w")
    if intro:
        WrappingLabel(parent, text=intro, style="Muted.TLabel").pack(
            fill="x", pady=(GAP // 2, 0)
        )


def hint(parent: tk.Misc, text: str = "", *, textvariable: tk.StringVar | None = None,
         style: str = "Help.TLabel") -> WrappingLabel:
    """Explanatory text under a control (packed)."""
    label = (WrappingLabel(parent, textvariable=textvariable, style=style) if textvariable
             else WrappingLabel(parent, text=text, style=style))
    label.pack(fill="x", pady=(2, 0))
    return label


def field(
    parent: tk.Misc, label: str, variable: tk.Variable, *, unit: str = "", help: str = "",
    width: int = 12,
) -> ttk.Entry:
    """A labelled entry with its unit and one line on what the value means (packed).

    The entry's master is its row, so callers can add buttons beside it.
    """
    box = ttk.Frame(parent, style="Panel.TFrame")
    box.pack(fill="x", pady=(GAP, 0))
    ttk.Label(box, text=label, style="Body.TLabel").pack(anchor="w")
    row = ttk.Frame(box, style="Panel.TFrame")
    row.pack(fill="x", pady=(2, 0))
    entry = ttk.Entry(row, textvariable=variable, width=width)
    entry.pack(side="left")
    if unit:
        ttk.Label(row, text=unit, style="Body.TLabel").pack(side="left", padx=(GAP // 2, 0))
    if help:
        hint(box, help)
    return entry


def button_row(parent: tk.Misc, *, pady: tuple[int, int] = (GAP, 0)) -> ttk.Frame:
    """A row for buttons side by side (packed)."""
    row = ttk.Frame(parent, style="Panel.TFrame")
    row.pack(fill="x", pady=pady)
    return row


class ScrollPage(ttk.Frame):
    """A page whose ``body`` scrolls vertically, with a ``footer`` that always shows.

    The scrollbar keeps its place even when nothing needs scrolling: showing it only
    when needed changes the body's width, which rewraps its text and can toggle it
    back, forever.
    """

    def __init__(self, parent: tk.Misc, *, padding: int = 12) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=PANEL, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._scroll)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.body = ttk.Frame(self.canvas, style="Panel.TFrame", padding=padding)
        self.footer = ttk.Frame(self, style="Panel.TFrame", padding=(padding, 0, padding, padding))
        self.footer.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self._width = 0
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<Configure>", self._resized, add="+")
        self.body.bind("<Configure>", self._resized, add="+")
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _scroll(self, *args: str) -> None:
        self.canvas.yview(*args)  # pyright: ignore[reportUnknownMemberType]

    def _resized(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        width = self.canvas.winfo_width()
        if width != self._width:
            self._width = width
            self.canvas.itemconfigure(self._window, width=width)
        self.canvas.configure(
            scrollregion=(0, 0, width, max(self.body.winfo_reqheight(),
                                           self.canvas.winfo_height()))
        )

    def _wheel(self, event: tk.Event[tk.Misc]) -> None:
        if not self.winfo_ismapped():
            return
        x, y = self.winfo_pointerxy()
        widget = self.winfo_containing(x, y)
        while widget is not None and widget is not self:
            if isinstance(widget, (tk.Text, ttk.Treeview, tk.Listbox)):
                return  # those scroll themselves
            widget = widget.master
        if widget is self:
            self.canvas.yview_scroll(-int(event.delta / WHEEL_UNITS) or 0, "units")

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)


class Collapsible(ttk.Frame):
    """A titled section whose ``body`` shows or hides; the title says what is inside."""

    def __init__(self, parent: tk.Misc, title: str, *, expanded: bool = False) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.title = title
        self.expanded = expanded
        self.header = ttk.Button(self, style="Disclosure.TButton", command=self.toggle,
                                 takefocus=False)
        self.header.pack(fill="x", anchor="w")
        self.body = ttk.Frame(self, style="Panel.TFrame", padding=(14, 0, 0, 0))
        self._show()

    def toggle(self) -> None:
        self.expanded = not self.expanded
        self._show()

    def set_title(self, title: str) -> None:
        self.title = title
        self._show()

    def _show(self) -> None:
        self.header.configure(text=("▾  " if self.expanded else "▸  ") + self.title)
        if self.expanded:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()


class ChoiceList(ttk.Frame):
    """Exclusive options as radio buttons, each with one line explaining it."""

    def __init__(
        self, parent: tk.Misc, variable: tk.StringVar,
        choices: Sequence[tuple[str, str, str]],  # value, label, explanation
        command: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.buttons: list[ttk.Radiobutton] = []
        for value, label, explanation in choices:
            button = ttk.Radiobutton(self, text=label, value=value, variable=variable,
                                     command=command or (lambda: None))
            button.pack(anchor="w", pady=(GAP // 2, 0))
            self.buttons.append(button)
            if explanation:
                WrappingLabel(self, text=explanation, style="Help.TLabel").pack(
                    fill="x", padx=(22, 0)
                )

    def set_enabled(self, enabled: bool) -> None:
        for button in self.buttons:
            button.configure(state="normal" if enabled else "disabled")


@dataclass(slots=True)
class _Step:
    frame: ttk.Frame
    number: ttk.Label | None
    title: ttk.Label
    status: ttk.Label
    index: int  # 0 for unnumbered tools
    enabled: bool = True
    done: bool = False


class StepRail(ttk.Frame):
    """Workflow steps down the left: a number, a name and a status line for each.

    Steps are numbered in order; tools follow under a heading, unnumbered. Clicking an
    enabled entry calls ``on_select`` with its key; the owner then calls ``select``.
    """

    def __init__(self, parent: tk.Misc, on_select: Callable[[str], None]) -> None:
        super().__init__(parent, style="Rail.TFrame", width=170)
        self._on_select = on_select
        self._steps: dict[str, _Step] = {}
        self.current: str | None = None

    def add_step(self, key: str, title: str) -> None:
        self._add(key, title, numbered=True)

    def add_tool(self, key: str, title: str) -> None:
        self._add(key, title, numbered=False)

    def add_heading(self, text: str) -> None:
        ttk.Separator(self).pack(fill="x", pady=(GAP, GAP // 2))
        ttk.Label(self, text=text.upper(), style="RailHeading.TLabel").pack(
            anchor="w", padx=GAP, pady=(0, 2)
        )

    def _add(self, key: str, title: str, *, numbered: bool) -> None:
        frame = ttk.Frame(self, style="Rail.TFrame", padding=(GAP, 6), cursor="hand2")
        frame.pack(fill="x", pady=(0, 1))
        frame.columnconfigure(1, weight=1)
        number, index = None, 0
        if numbered:
            index = sum(step.number is not None for step in self._steps.values()) + 1
            number = ttk.Label(frame, text=str(index), style="RailNumber.TLabel")
            number.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, GAP), pady=(1, 0))
        title_label = ttk.Label(frame, text=title, style="RailTitle.TLabel")
        title_label.grid(row=0, column=1, sticky="w")
        status = ttk.Label(frame, style="RailStatus.TLabel", wraplength=124)
        status.grid(row=1, column=1, sticky="w")
        for widget in (frame, title_label, status, *((number,) if number else ())):
            widget.bind("<Button-1>", lambda _e, key=key: self._clicked(key))
        self._steps[key] = _Step(frame, number, title_label, status, index)
        self._restyle(key)

    def _clicked(self, key: str) -> None:
        if self._steps[key].enabled and key != self.current:
            self._on_select(key)

    def select(self, key: str) -> None:
        previous, self.current = self.current, key
        for changed in {previous, key} - {None}:
            assert changed is not None
            self._restyle(changed)

    def set_status(self, key: str, text: str, *, done: bool | None = None) -> None:
        step = self._steps[key]
        step.status.configure(text=text)
        if text:
            step.status.grid()
        else:
            step.status.grid_remove()
        if done is not None and done != step.done:
            step.done = done
            self._restyle(key)

    def set_enabled(self, key: str, enabled: bool) -> None:
        step = self._steps[key]
        if enabled != step.enabled:
            step.enabled = enabled
            self._restyle(key)

    def status(self, key: str) -> str:
        return str(self._steps[key].status.cget("text"))

    def enabled(self, key: str) -> bool:
        return self._steps[key].enabled

    def _restyle(self, key: str) -> None:
        step = self._steps[key]
        state = ("Current" if key == self.current else "Disabled" if not step.enabled
                 else "Done" if step.done else "")
        step.frame.configure(style=f"Rail{state}.TFrame",
                             cursor="hand2" if step.enabled else "")
        step.title.configure(style=f"RailTitle{state}.TLabel")
        step.status.configure(style=f"RailStatus{state}.TLabel")
        if step.number is not None:
            text = "✓" if step.done and key != self.current else str(step.index)
            step.number.configure(style=f"RailNumber{state}.TLabel", text=text)


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
