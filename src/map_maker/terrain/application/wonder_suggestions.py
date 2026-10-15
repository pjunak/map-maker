"""Suggested wonder sites for a generated planet, in its world's source coordinates.

Suggestions belong to the planet without wonders they were found on (ADR-0099). A
suggestion the user keeps becomes an ordinary placed wonder with its own seed.
"""

from dataclasses import dataclass
from math import asin, atan2, degrees
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.application.planet import PlanetRun
from map_maker.terrain.domain.models import Point2D
from map_maker.terrain.domain.wonders import WONDER_KINDS, WONDERS, WonderKind
from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_wonders import WorldWonder
from map_maker.terrain.pipeline.planet_suggestions import suggest_wonders


@dataclass(frozen=True, slots=True)
class SuggestedWonder:
    """A plausible site for a wonder, ready to keep."""

    id: str  # unique among one planet's suggestions
    kind: WonderKind
    position: Point2D
    end: Point2D | None
    size_km: float | None  # within the kind's range for placed wonders
    score: float  # 0..1, how well the place fits the kind's hypothesis
    reason: str

    @property
    def name(self) -> str:
        return WONDERS[self.kind].label

    @property
    def effective_size_km(self) -> float:
        return 0.0 if self.size_km is None else self.size_km


def suggest(
    run: PlanetRun, kinds: tuple[WonderKind, ...] = WONDER_KINDS
) -> tuple[SuggestedWonder, ...]:
    """The best few plausible sites for each of ``kinds`` on ``run``'s planet without wonders."""
    frame = run.result.world.project.frame
    out: list[SuggestedWonder] = []
    for index, s in enumerate(suggest_wonders(run.base, kinds)):
        spec = WONDERS[s.kind]
        size = None
        if spec.size_km is not None and s.size_m is not None:
            low, high, _ = spec.size_km
            size = round(min(max(s.size_m / 1e3, low), high), 1)
        out.append(SuggestedWonder(
            f"suggestion-{index}", s.kind, _source(frame, s.xyz),
            None if s.end is None else _source(frame, s.end), size, s.score, s.reason,
        ))
    return tuple(out)


def keep(suggestion: SuggestedWonder, name: str, seed: int) -> WorldWonder:
    """The suggestion as a placed wonder with its own ``seed``."""
    return WorldWonder(
        "wonder-" + uuid4().hex, name, suggestion.kind, suggestion.position, seed,
        suggestion.size_km, suggestion.end,
    )


def _source(frame: WorldFrame, xyz: NDArray[np.float64]) -> Point2D:
    x, y, z = (float(v) for v in xyz)
    return frame.lonlat_to_source((degrees(atan2(y, x)), degrees(asin(max(-1.0, min(1.0, z))))))
