"""Input editing state for the workbench; generated surfaces are never editable."""

from dataclasses import dataclass, field, replace
from itertools import pairwise

from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    TerrainBasin,
    TerrainConstraint,
    TerrainRegion,
    TerrainSettings,
)
from map_maker.terrain.domain.terrain_context import TerrainWorldContext


@dataclass(frozen=True, slots=True)
class GenerationInputs:
    """The exact input snapshot used by a background generation request."""

    coastline: Coastline
    settings: TerrainSettings
    constraints: tuple[TerrainConstraint, ...]
    world_context: TerrainWorldContext | None = None


@dataclass(slots=True)
class InstructionHistory:
    """Reversible edits of immutable authored inputs, scoped to one open project."""

    constraints: tuple[TerrainConstraint, ...] = ()
    _undo: list[tuple[TerrainConstraint, ...]] = field(
        default_factory=list[tuple[TerrainConstraint, ...]], init=False)
    _redo: list[tuple[TerrainConstraint, ...]] = field(
        default_factory=list[tuple[TerrainConstraint, ...]], init=False)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def reset(self, constraints: tuple[TerrainConstraint, ...] = ()) -> None:
        self.constraints = constraints
        self._undo.clear()
        self._redo.clear()

    def commit(self, constraints: tuple[TerrainConstraint, ...]) -> None:
        if constraints == self.constraints:
            return
        self._undo.append(self.constraints)
        self.constraints = constraints
        self._redo.clear()

    def append(self, constraint: TerrainConstraint) -> None:
        self.commit((*self.constraints, constraint))

    def replace(self, index: int, constraint: TerrainConstraint) -> None:
        if not 0 <= index < len(self.constraints):
            raise IndexError("No instruction at this index.")
        self.commit((*self.constraints[:index], constraint, *self.constraints[index + 1:]))

    def delete(self, index: int) -> None:
        if not 0 <= index < len(self.constraints):
            raise IndexError("No instruction at this index.")
        self.commit((*self.constraints[:index], *self.constraints[index + 1:]))

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self.constraints)
            self.constraints = self._undo.pop()

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self.constraints)
            self.constraints = self._redo.pop()



def instruction_vertices(instruction: TerrainConstraint) -> tuple[tuple[float, float], ...]:
    if isinstance(instruction, ElevationPoint):
        return (instruction.position,)
    if isinstance(instruction, TerrainRegion):
        return tuple(p for ring in (instruction.points, *instruction.holes) for p in ring[:-1])
    return instruction.points[:-1] if isinstance(instruction, TerrainBasin) else instruction.points


def move_instruction(
    instruction: TerrainConstraint, delta: tuple[float, float], vertex: int | None = None,
) -> TerrainConstraint:
    """Translate an input or one vertex; closed rings and attached outlets follow it."""
    def moved(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] + delta[0], point[1] + delta[1]

    if isinstance(instruction, ElevationPoint):
        return replace(instruction, position=moved(instruction.position))
    if isinstance(instruction, TerrainRegion):
        if vertex is not None and not 0 <= vertex < len(instruction_vertices(instruction)):
            raise IndexError("No vertex at this index.")
        rings: list[tuple[tuple[float, float], ...]] = []
        offset = 0
        for ring in (instruction.points, *instruction.holes):
            values = tuple(moved(p) if vertex is None or offset + i == vertex else p
                           for i, p in enumerate(ring[:-1]))
            rings.append((*values, values[0]))
            offset += len(ring) - 1
        return replace(instruction, points=rings[0], holes=tuple(rings[1:]))
    original = instruction.points
    closed = isinstance(instruction, (TerrainRegion, TerrainBasin))
    count = len(original) - int(closed)
    if vertex is not None and not 0 <= vertex < count:
        raise IndexError("No vertex at this index.")
    points = tuple(moved(p) if vertex is None or i == vertex else p
                   for i, p in enumerate(original[:count]))
    if closed:
        points += (points[0],)
    if not isinstance(instruction, TerrainBasin) or instruction.outlet is None:
        return replace(instruction, points=points)
    outlet = instruction.outlet
    if vertex is None:
        outlet = moved(outlet)
    else:
        # Keep an imported outlet at the same fraction of its boundary edge.
        # This also handles an outlet coinciding with a dragged corner.
        for i, (a, b) in enumerate(pairwise(original)):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length2 = dx * dx + dy * dy
            if length2 == 0:
                continue
            t = ((outlet[0] - a[0]) * dx + (outlet[1] - a[1]) * dy) / length2
            if 0 <= t <= 1 and ((a[0] + t * dx - outlet[0]) ** 2
                               + (a[1] + t * dy - outlet[1]) ** 2) <= 1e-18:
                start, end = points[i], points[i + 1]
                outlet = (start[0] + t * (end[0] - start[0]),
                          start[1] + t * (end[1] - start[1]))
                break
    return replace(instruction, points=points, outlet=outlet)
