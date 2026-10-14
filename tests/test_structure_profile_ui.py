# pyright: reportPrivateUsage=false
"""Real Tk profile editing, validation and cancel behavior."""

import tkinter as tk
from collections.abc import Iterator

import pytest

from map_maker.terrain.domain import StructureProfileKnot as Knot
from map_maker.terrain.domain import TerrainStructure
from map_maker.terrain.structure_profile_ui import StructureProfileDialog


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    try:
        window = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    window.withdraw()
    yield window
    window.destroy()


def test_peak_pass_preset_apply_and_cancel_do_not_mutate_the_input(root: tk.Tk) -> None:
    ridge = TerrainStructure("ridge", ((.1, .5), (.9, .5)), 3000., 40.)
    dialog = StructureProfileDialog(root, ridge, 6000.)
    dialog._peaks()
    root.update_idletasks()
    assert len(dialog.table.get_children()) == 5
    assert len(dialog.preview.find_all()) > 6
    assert dialog.knots[2].elevation_m < dialog.knots[1].elevation_m
    dialog._apply()
    assert dialog.result is not None and len(dialog.result.profile) == 5
    assert ridge.profile == ()
    cancelled = StructureProfileDialog(root, ridge, 6000.)
    cancelled._peaks()
    cancelled.destroy()
    assert cancelled.result is None and ridge.profile == ()


def test_invalid_values_endpoints_and_ceiling_leave_the_dialog_open(root: tk.Tk) -> None:
    ridge = TerrainStructure("ridge", ((.1, .5), (.9, .5)), 3000., 40.)
    dialog = StructureProfileDialog(root, ridge, 6000.)
    dialog.position.set("nan")
    dialog._upsert()
    assert dialog.error.get() and dialog.knots == []
    dialog.position.set("50")
    dialog.elevation.set("7000")
    dialog._upsert()
    dialog._apply()
    assert dialog.result is None and dialog.winfo_exists()
    dialog._flat()
    dialog.position.set("50")
    dialog._upsert()
    dialog._apply()
    assert "ceiling" in dialog.error.get() and dialog.result is None
    dialog.elevation.set("1500")
    dialog._upsert()
    dialog._apply()
    assert dialog.result is not None and dialog.result.profile[1] == Knot(.5, 1500.)


def test_valley_validation_and_clearing_profile(root: tk.Tk) -> None:
    valley = TerrainStructure("valley", ((.1, .5), (.9, .5)), 50., 40.,
                              profile=(Knot(0., 500.), Knot(1., 50.)))
    dialog = StructureProfileDialog(root, valley, 6000.)
    dialog.position.set("50")
    dialog.elevation.set("900")
    dialog._upsert()
    dialog._apply()
    assert "downstream" in dialog.error.get() and dialog.result is None
    dialog._clear()
    dialog._apply()
    assert dialog.result is not None and dialog.result.profile == ()
    assert valley.profile == (Knot(0., 500.), Knot(1., 50.))
