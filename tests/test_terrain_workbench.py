"""Undo/redo owns authored inputs and never accepts a generated surface."""

from dataclasses import replace

import pytest

from map_maker.terrain.domain import (
    ElevationPoint,
    TerrainBasin,
    TerrainBrushStroke,
    TerrainConstraint,
    TerrainRegion,
    TerrainStructure,
)
from map_maker.terrain.workbench import InstructionHistory, move_instruction

POINT = ElevationPoint((0.5, 0.5), 1200, 80)


def test_instruction_history_restores_properties_deletion_and_clear_in_order() -> None:
    history = InstructionHistory()
    history.append(POINT)
    snapshot = history.constraints
    changed = replace(POINT, elevation_m=1800)
    history.replace(0, changed)
    history.append(replace(POINT, position=(0.2, 0.3)))
    before_delete = history.constraints
    history.delete(0)
    history.commit(())
    history.undo()
    assert len(history.constraints) == 1
    history.undo()
    assert history.constraints == before_delete
    history.undo()
    assert history.constraints == (changed,)
    history.undo()
    assert history.constraints == snapshot == (POINT,)
    history.redo()
    assert history.constraints == (changed,)
    assert snapshot == (POINT,)


def test_new_edit_discards_redo_but_noop_keeps_it() -> None:
    history = InstructionHistory((POINT,))
    history.delete(0)
    history.undo()
    history.replace(0, POINT)
    assert history.can_redo
    history.replace(0, replace(POINT, elevation_m=500))
    assert not history.can_redo
    history.redo()
    assert history.constraints[0] == replace(POINT, elevation_m=500)


def test_open_project_starts_a_new_history() -> None:
    history = InstructionHistory()
    history.append(POINT)
    history.undo()
    history.reset((POINT,))
    assert not history.can_undo and not history.can_redo
    history.undo()
    history.redo()
    assert history.constraints == (POINT,)


@pytest.mark.parametrize("index", [-1, 1, 10])
def test_invalid_selection_cannot_modify_inputs(index: int) -> None:
    history = InstructionHistory((POINT,))
    with pytest.raises(IndexError):
        history.delete(index)
    with pytest.raises(IndexError):
        history.replace(index, POINT)
    assert history.constraints == (POINT,) and not history.can_undo


RING = ((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4), (0.2, 0.2))


@pytest.mark.parametrize("instruction", [
    POINT, TerrainRegion(RING), TerrainBasin(RING, "dry_basin"),
    TerrainBasin(RING, "lake", 200, (0.4, 0.3)),
    TerrainStructure("ridge", ((0.2, 0.2), (0.4, 0.4)), 1000, 50),
    TerrainStructure("valley", ((0.2, 0.2), (0.4, 0.4)), 200, 40),
    TerrainBrushStroke(((0.2, 0.2), (0.4, 0.4)), 300, 30, 0.5),
])
def test_translation_preserves_properties_and_is_reversible(instruction: TerrainConstraint) -> None:
    moved = move_instruction(instruction, (0.1, 0.2))
    before = (instruction.position if isinstance(instruction, ElevationPoint)
              else instruction.points[0])
    after = moved.position if isinstance(moved, ElevationPoint) else moved.points[0]
    assert after == pytest.approx((before[0] + 0.1, before[1] + 0.2))
    history = InstructionHistory((instruction,))
    history.replace(0, moved)
    history.undo()
    assert history.constraints == (instruction,)
    history.redo()
    assert history.constraints == (moved,)
    if isinstance(instruction, TerrainBasin) and instruction.outlet is not None:
        assert isinstance(moved, TerrainBasin)
        assert moved.outlet == pytest.approx((0.5, 0.5))


def test_ring_corner_and_boundary_outlet_follow_vertex_without_opening_ring() -> None:
    lake = TerrainBasin(RING, "lake", 200, (0.4, 0.3))
    moved = move_instruction(lake, (0.1, 0), vertex=1)
    assert isinstance(moved, TerrainBasin)
    assert moved.points[1] == (0.5, 0.2)
    assert moved.points[0] == moved.points[-1] == lake.points[0]
    assert moved.outlet == pytest.approx((0.45, 0.3))
    corner_outlet = TerrainBasin(RING, "lake", 200, RING[0])
    moved = move_instruction(corner_outlet, (0.05, 0.05), vertex=0)
    assert isinstance(moved, TerrainBasin)
    assert moved.outlet == moved.points[0] == moved.points[-1] == (0.25, 0.25)
    assert moved.points[1:-1] == RING[1:-1]


def test_moving_outside_normalized_bounds_cannot_create_an_instruction() -> None:
    with pytest.raises(ValueError):
        move_instruction(POINT, (1., 0.))
    with pytest.raises(IndexError):
        move_instruction(TerrainRegion(RING), (0.1, 0.), vertex=4)


def test_region_holes_move_with_the_region_and_have_editable_vertices() -> None:
    outer = ((.1, .1), (.8, .1), (.8, .8), (.1, .8), (.1, .1))
    hole = ((.3, .3), (.6, .3), (.6, .6), (.3, .6), (.3, .3))
    region = TerrainRegion(outer, holes=(hole,))
    moved = move_instruction(region, (.1, .05))
    assert isinstance(moved, TerrainRegion)
    assert moved.points[0] == pytest.approx((.2, .15))
    assert moved.holes[0][0] == pytest.approx((.4, .35))
    changed = move_instruction(region, (.05, .05), vertex=4)
    assert isinstance(changed, TerrainRegion)
    assert changed.points == outer
    assert changed.holes[0][0] == changed.holes[0][-1] == pytest.approx((.35, .35))
    assert changed.holes[0][1:4] == hole[1:4]
    with pytest.raises(IndexError):
        move_instruction(region, (.01, .01), vertex=8)
