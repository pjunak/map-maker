"""Refined-coast export: a world's zoomed coast as an importable source map."""

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Polygon

from map_maker.terrain.adapters.world_project import read_world_project
from map_maker.terrain.adapters.world_svg import drawn_coast_detail_km, load_world_svg
from map_maker.terrain.application.world import (
    export_refined_coast,
    propose_group_assignments,
    save_world,
)
from map_maker.terrain.domain.world import WorldFrame, WorldProject
from map_maker.terrain.pipeline.planet_coast import coastline
from map_maker.terrain.pipeline.world import prepare_world_map

SEED = 20261006
# Two continents sharing a land border, an island, and a lake in the west.
SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="360" height="180" viewBox="0 0 360 180"
  xmlns:affinity="https://www.affinity.studio/">
  <g affinity:id="West"><g affinity:id="Land Shapes"><g affinity:id="mainland">
    <path id="west" d="M100 60 L180 60 L180 120 L100 120 Z M120 80 L120 95 L140 95 L140 80 Z"/>
  </g><g affinity:id="islands"><path id="isle" d="M100 140 L115 140 L115 150 L100 150 Z"/></g>
  </g></g>
  <g affinity:id="East"><g affinity:id="Land Shapes"><g affinity:id="mainland">
    <path id="east" d="M180 60 L250 60 L250 120 L180 120 Z"/>
  </g></g></g>
</svg>"""


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("refine")
    svg = folder / "drawn.svg"
    svg.write_text(SVG, encoding="utf-8")
    source = load_world_svg(svg)
    continents, assignments = propose_group_assignments(source)
    path = folder / "drawn.world.json"
    save_world(
        WorldProject("Drawn", source, WorldFrame((0, 0, 360, 180), 1000), continents, assignments),
        path,
    )
    return path


def _imported(svg: Path, frame: WorldFrame) -> WorldProject:
    source = load_world_svg(svg)
    continents, assignments = propose_group_assignments(source)
    return WorldProject(
        "Refined", source, frame, continents, assignments, drawn_coast_detail_km(source.svg)
    )


def test_refined_coast_imports_with_its_continents_roles_and_detail(
    project: Path, tmp_path: Path
) -> None:
    drawn = read_world_project(project)
    destination = tmp_path / "refined.svg"
    coast = export_refined_coast(project, destination, master_seed=SEED, detail_km=60.0)
    assert coast.detail_km == 60.0
    refined = _imported(destination, drawn.frame)
    assert refined.coast_detail_km == 60.0
    # Continents keep their land, the shared border included, and roles survive.
    before = {c.name: c for c in prepare_world_map(drawn).continents}
    after = {c.name: c for c in prepare_world_map(refined).continents}
    assert set(after) == {"West", "East"}
    for name in after:
        assert after[name].area_km2 == pytest.approx(before[name].area_km2, rel=0.08)
    assert after["West"].island_shapes >= 1 and after["East"].island_shapes == 0
    # The lake stays water.
    holes = [h for s in coast.shapes for h in s.polygon.interiors]
    assert any(Polygon(h).area > 100 for h in holes)
    # Zoomed to the exported detail, the imported world draws the export as it is.
    xyz = np.random.default_rng(2).normal(size=(20_000, 3))
    xyz /= np.linalg.norm(xyz, axis=1, keepdims=True)
    exported = coastline(prepare_world_map(refined))
    original = coastline(prepare_world_map(drawn))
    same = exported.contains(xyz, 60e3, SEED) == original.contains(xyz, 60e3, SEED)
    assert same.mean() > 0.995
    with pytest.raises(FileExistsError):
        export_refined_coast(project, destination, master_seed=SEED, detail_km=60.0)
    with pytest.raises(ValueError, match="svg"):
        export_refined_coast(project, tmp_path / "x.png", master_seed=SEED)


def test_refined_coast_refuses_more_points_than_the_importer_reads(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import map_maker.terrain.adapters.world_refined_svg as refined

    monkeypatch.setattr(refined, "MAX_WORLD_POINTS", 50)
    with pytest.raises(ValueError, match="coarser coast detail"):
        export_refined_coast(project, tmp_path / "big.svg", master_seed=SEED, detail_km=60.0)
    assert not (tmp_path / "big.svg").exists()

