"""Visual tokens and ttk styles shared by every desktop window.

Screens use the named styles below and these tokens instead of literal colours
or fonts, so a palette change happens here once.
"""

import tkinter as tk
from tkinter import ttk

# Surfaces and text
INK = "#172225"
MUTED = "#65716f"
PAPER = "#f1ede3"
PANEL = "#fbf8ef"
BORDER = "#d2ccbd"
TROUGH = "#d9d4c7"
ACCENT = "#1d7772"
ACCENT_ACTIVE = "#155e5a"
ACCENT_SOFT = "#d6ebe8"
DISABLED = "#9ba9a6"
WARNING = "#a13223"

# The map area (dark, so colour maps read well)
MAP_BACKGROUND = "#10191b"
MAP_TEXT = "#e3eddf"
MAP_TEXT_MUTED = "#9bb4b3"
MAP_GRID = "#476068"
MAP_FRAME = "#87a6a5"
MAP_HIGHLIGHT = "#f2c14e"

FONT = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_SECTION = ("Segoe UI", 10, "bold")
FONT_BUTTON = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_HEADER = ("Segoe UI", 18, "bold")
FONT_HERO = ("Segoe UI", 24, "bold")
FONT_MAP_LABEL = ("Segoe UI", 10, "bold")
FONT_MONO = ("Consolas", 9)
FONT_MONO_BOLD = ("Consolas", 9, "bold")

GAP = 8  # standard spacing between related controls, px
SECTION_GAP = 14  # spacing between groups


def configure_styles(root: tk.Misc) -> None:
    """Install the app's ttk styles; call once per Tk root."""
    style = ttk.Style(root)
    style.theme_use("clam")
    # A read-only list changes value under the mouse wheel, so scrolling a page past one
    # would silently change a setting; only an explicit choice changes it here.
    root.unbind_class("TCombobox", "<MouseWheel>")
    style.configure(".", background=PANEL, foreground=INK, font=FONT, bordercolor=BORDER)
    style.configure("TFrame", background=PANEL)
    style.configure("Paper.TFrame", background=PAPER)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Toolbar.TFrame", background=PANEL)
    style.configure("TLabel", background=PANEL, foreground=INK)
    style.configure("Header.TLabel", background=PAPER, foreground=INK, font=FONT_HEADER)
    style.configure("Eyebrow.TLabel", background=PAPER, foreground=ACCENT, font=FONT_BOLD)
    style.configure("Section.TLabel", background=PANEL, foreground=INK, font=FONT_SECTION)
    style.configure("Body.TLabel", background=PANEL, foreground=INK, font=FONT)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=FONT)
    style.configure("Value.TLabel", background=PANEL, foreground=ACCENT, font=FONT_MONO_BOLD)
    style.configure("Readout.TLabel", background=PANEL, foreground=INK, font=FONT_MONO)
    style.configure("Status.TLabel", background=PAPER, foreground=ACCENT, font=FONT_BOLD)
    style.configure("Title.TLabel", background=PANEL, foreground=INK, font=FONT_TITLE)
    style.configure("Help.TLabel", background=PANEL, foreground=MUTED, font=FONT_SMALL)
    style.configure("Warning.TLabel", background=PANEL, foreground=WARNING, font=FONT)
    style.configure("Document.TLabel", background=PAPER, foreground=MUTED, font=FONT)
    style.configure("Card.TFrame", background=PAPER, relief="solid", borderwidth=1)
    style.configure("Card.TLabel", background=PAPER, foreground=INK, font=FONT)
    # Workflow steps down the left of a workspace (``ui_components.StepRail``).
    for state, background, title, number in (
        ("", PAPER, MUTED, BORDER),
        ("Current", PANEL, INK, ACCENT),
        ("Done", PAPER, INK, ACCENT_SOFT),
        ("Disabled", PAPER, DISABLED, TROUGH),
    ):
        style.configure(f"Rail{state}.TFrame", background=background)
        style.configure(f"RailTitle{state}.TLabel", background=background, foreground=title,
                        font=FONT_BOLD)
        style.configure(f"RailStatus{state}.TLabel", background=background,
                        foreground=DISABLED if state == "Disabled" else MUTED, font=FONT_SMALL)
        style.configure(
            f"RailNumber{state}.TLabel", background=number, font=FONT_BOLD, anchor="center",
            foreground="#ffffff" if state == "Current" else (ACCENT if state == "Done" else INK),
            width=2, padding=(2, 0),
        )
    style.configure("RailHeading.TLabel", background=PAPER, foreground=MUTED, font=FONT_SMALL)
    style.configure("Disclosure.TButton", background=PANEL, foreground=INK, font=FONT_SECTION,
                    borderwidth=0, padding=(0, 2), anchor="w")
    style.map("Disclosure.TButton", background=[("active", PANEL)],
              foreground=[("active", ACCENT), ("disabled", DISABLED)])
    style.configure("TCheckbutton", background=PANEL, foreground=INK)
    style.map("TCheckbutton", background=[("active", PANEL)])
    style.configure("TRadiobutton", background=PANEL, foreground=INK)
    style.map("TRadiobutton", background=[("active", PANEL)])
    style.configure(
        "Accent.TButton", background=ACCENT, foreground="#ffffff", padding=(18, 10),
        font=FONT_BUTTON,
    )
    style.map("Accent.TButton", background=[("active", ACCENT_ACTIVE), ("disabled", DISABLED)])
    style.configure("Quiet.TButton", background=PANEL, foreground=INK, padding=(12, 7))
    style.configure("Small.TButton", background=PANEL, foreground=INK, padding=(8, 3))
    style.configure("Crumb.TButton", background=PANEL, foreground=ACCENT, padding=(6, 2),
                    font=FONT_BOLD, borderwidth=0)
    style.map("Crumb.TButton", foreground=[("disabled", INK)], background=[("active", PAPER)])
    # Segmented choices: radio buttons drawn as toggle buttons.
    style.configure("Segment.TRadiobutton", background=PANEL, foreground=INK, padding=(10, 3),
                    indicatoron=False, relief="raised", borderwidth=1, anchor="center")
    style.layout("Segment.TRadiobutton", style.layout("Toolbutton"))
    style.map(
        "Segment.TRadiobutton",
        background=[("selected", ACCENT), ("disabled", PANEL), ("active", ACCENT_SOFT)],
        foreground=[("selected", "#ffffff"), ("disabled", DISABLED)],
    )
    style.configure("Segment.TCheckbutton", background=PANEL, foreground=INK, padding=(10, 3),
                    relief="raised", borderwidth=1)
    style.layout("Segment.TCheckbutton", style.layout("Toolbutton"))
    style.map(
        "Segment.TCheckbutton",
        background=[("selected", ACCENT), ("disabled", PANEL), ("active", ACCENT_SOFT)],
        foreground=[("selected", "#ffffff"), ("disabled", DISABLED)],
    )
    style.configure(
        "Accent.Horizontal.TProgressbar", troughcolor=TROUGH, background=ACCENT,
        bordercolor=TROUGH, lightcolor=ACCENT, darkcolor=ACCENT,
    )
    style.configure("TNotebook", background=PANEL, borderwidth=0)
    style.configure("TNotebook.Tab", background=PAPER, foreground=MUTED, padding=(10, 4))
    style.map(
        "TNotebook.Tab",
        background=[("selected", PANEL)], foreground=[("selected", INK)],
    )
    # Vertical stage navigation down the left of a sidebar.
    style.configure("Stages.TNotebook", tabposition="wn", background=PAPER, borderwidth=0)
    style.configure(
        "Stages.TNotebook.Tab", background=PAPER, foreground=MUTED, padding=(12, 8),
        width=14, font=FONT_BOLD,
    )
    style.map(
        "Stages.TNotebook.Tab",
        background=[("selected", PANEL)], foreground=[("selected", ACCENT)],
    )
    # Workspace tabs across the top of the window.
    style.configure("Workspaces.TNotebook", background=PAPER, borderwidth=0)
    style.configure("Workspaces.TNotebook.Tab", padding=(16, 6), font=FONT_BOLD)
