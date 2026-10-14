"""Measure public drainage density, connected scale selection and viewport cost."""

import argparse
import json
from contextlib import closing
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from benchmarks import terrain as fixtures
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.adapters.channel_display import CHANNEL_DISPLAY_ID, prepare_channel_display
from map_maker.terrain.adapters.render import render_drainage_overlay, render_height_map
from map_maker.terrain.adapters.viewport import render_viewport
from map_maker.terrain.pipeline.channel_network import CHANNEL_NETWORK_ID
from map_maker.terrain.pipeline.generate import (
    AUTOMATIC_VALLEY_ALGORITHM_ID,
    GENERATOR_ALGORITHM_ID,
    generate_terrain,
)

CASES = ("example", "regional", "square")


def probe(case: str, seed: int, density: float, output: Path) -> dict[str, Any]:
    coast, settings, constraints = fixtures.fixture(case, 513, seed)
    settings = replace(settings, drainage_density=density)
    start = perf_counter()
    terrain = generate_terrain(coast, settings, constraints=constraints)
    generation_seconds = perf_counter()-start
    start = perf_counter()
    display = prepare_channel_display(terrain)
    preparation_seconds = perf_counter()-start
    network = display.network
    total = len(network.reaches)
    mask = terrain.routing.channel_mask
    for reach in network.reaches:
        if reach.downstream is not None:
            target = network.reaches[reach.downstream]
            if (reach.nodes[-1] != target.nodes[0]
                    or reach.contributing_area_km2 > target.contributing_area_km2):
                raise AssertionError("Broken reach connection or area hierarchy")
    size = (1025, round(1025*terrain.height/terrain.width))
    original = terrain.elevation_m.copy()
    zooms: list[dict[str, Any]] = []
    prefix = f"{case}-{seed}-density-{density:g}"
    with closing(render_height_map(terrain, style="cartographic")) as ground:
        for zoom in (1, 2, 4, 8):
            left, top = (1-zoom)*size[0]/2, (1-zoom)*size[1]/2
            rect = (left, top, left+zoom*size[0], top+zoom*size[1])
            start = perf_counter()
            with display.render(rect, size) as overlay:
                elapsed = perf_counter()-start
                if zoom in (1, 4):
                    with render_viewport(ground, rect, size) as view:
                        view.alpha_composite(overlay)
                        view.save(output/f"{prefix}-zoom-{zoom}.png")
            selected = display.visible_reach_count(rect)
            zooms.append({"zoom": zoom, "selected_reaches": selected,
                          "selected_fraction": selected/total if total else 0.,
                          "render_seconds": elapsed})
        if density == 1.:
            with (closing(render_drainage_overlay(terrain, size)) as raw,
                  closing(render_viewport(ground, (0., 0., float(size[0]), float(size[1])), size))
                  as view):
                view.alpha_composite(raw)
                view.save(output/f"{prefix}-raw.png")
    np.testing.assert_array_equal(terrain.elevation_m, original)
    if network.edge_count != terrain.routing_agreement.channel_edge_count:
        raise AssertionError("Reach extraction lost selected edges")
    return {
        "case": case, "seed": seed, "drainage_density": density,
        "input_sha256": sha256(canonical_json({
            "coastline": asdict(coast), "settings": asdict(settings),
            "constraints": [asdict(value) for value in constraints],
        })).hexdigest(),
        "generation_seconds": generation_seconds,
        "network_preparation_seconds": preparation_seconds,
        "channel_nodes": int(np.count_nonzero(mask)),
        "channel_heads": int(np.count_nonzero(terrain.routing.channel_head_mask)),
        "channel_edges": network.edge_count, "reaches": total,
        "length_km": sum(r.length_km for r in network.reaches),
        "downstream_connected": True, "display_preserved_dem": True,
        "uphill_edges_retained": len(display.uphill_edges),
        "routing_agreement": asdict(terrain.routing_agreement), "zooms": zooms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, nargs="+", default=list(CASES))
    parser.add_argument("--seed", type=int, nargs="+", default=[42, 7])
    parser.add_argument("--density", type=float, nargs="+", default=[.5, 1., 2.])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(not .25 <= density <= 2. for density in args.density):
        parser.error("--density must be between 0.25 and 2")
    args.output.mkdir(exist_ok=False)
    runtime = runtime_identity()
    source_hash = file_sha256(Path(__file__))
    fixture_hash = file_sha256(Path(fixtures.__file__))
    results: list[dict[str, Any]] = []
    for case in args.case:
        for seed in args.seed:
            for density in args.density:
                result = probe(case, seed, density, args.output)
                results.append(result)
                print(json.dumps(result), flush=True)
    if (runtime != runtime_identity() or source_hash != file_sha256(Path(__file__))
            or fixture_hash != file_sha256(Path(fixtures.__file__))):
        raise RuntimeError("Source/runtime changed during drainage-network measurement")
    with (args.output/"report.json").open("xb") as stream:
        stream.write(canonical_json({
            "schema": "map-maker.channel-network-experiment", "schema_version": 1,
            "complete": True, "runtime": runtime, "benchmark_source_sha256": source_hash,
            "fixture_source_sha256": fixture_hash, "algorithms": {
                "generator": GENERATOR_ALGORITHM_ID,
                "automatic_valleys": AUTOMATIC_VALLEY_ALGORITHM_ID,
                "network": CHANNEL_NETWORK_ID, "display": CHANNEL_DISPLAY_ID,
            }, "cases": results,
        }))


if __name__ == "__main__":
    main()
