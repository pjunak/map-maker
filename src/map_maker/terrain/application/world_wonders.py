"""Open and save hand-placed wonders without changing a world or a planet build."""

from dataclasses import dataclass, replace
from pathlib import Path

from map_maker.terrain.adapters.world_geology import world_fingerprint
from map_maker.terrain.adapters.world_svg import parse_world_svg
from map_maker.terrain.adapters.world_wonders import read_wonders, write_wonders
from map_maker.terrain.domain.world import WorldProject
from map_maker.terrain.domain.world_wonders import WorldWonders


@dataclass(frozen=True, slots=True)
class WonderFile:
    wonders: WorldWonders
    path: Path
    sha256: str


def open_wonders(path: Path, world: WorldProject | None = None) -> WonderFile:
    """A wonder document, checked against ``world`` when given."""
    document, digest = read_wonders(path)
    if world is not None:
        if world_fingerprint(world) != world_fingerprint(document.world):
            raise ValueError(
                "These wonders belong to a different world source, frame or ownership; "
                "open their world."
            )
        document = replace(document, world=world)
    return WonderFile(document, path, digest)


def save_wonders(
    document: WorldWonders, path: Path, expected_hash: str | None = None
) -> WonderFile:
    world = document.world
    if parse_world_svg(world.source.svg, world.source.name) != world.source:
        raise ValueError("Wonder source snapshot and retained geometry disagree; import again.")
    return WonderFile(document, path, write_wonders(document, path, expected_hash))
