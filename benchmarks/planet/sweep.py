"""Planet relief resolution sweep: same world and settings at several mesh sizes.

Relief statistics should converge with mesh density because the process area,
not the mesh cell, sets the smallest resolved river. Prints one JSON line per run.

    python -m benchmarks.planet.sweep WORLD [--geology G] --nodes 50000 200000 800000
"""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from dmtools.terrain.adapters.world_geology import read_geology
from dmtools.terrain.application.world import open_world
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.pipeline.planet import generate_planet


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("world", type=Path)
    parser.add_argument("--geology", type=Path)
    parser.add_argument("--nodes", type=int, nargs="+", default=[50_000, 200_000])
    parser.add_argument("--climate-passes", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20261006)
    args = parser.parse_args()
    world = open_world(args.world)
    recipe = None if args.geology is None else read_geology(args.geology)[0]
    base = PlanetSettings(seed=args.seed, climate_passes=args.climate_passes)
    for nodes in args.nodes:
        started = time.perf_counter()
        result = generate_planet(world, replace(base, nodes=nodes), recipe)
        record = {
            "nodes": nodes,
            "spacing_km": result.mesh.spacing_m / 1000,
            "seconds": time.perf_counter() - started,
            "metrics": result.metrics,
            "calibration": [
                {"name": r.name, "target_m": r.target_m, "measured_m": r.measured_m}
                for r in (result.calibration[-1] if result.calibration else ())
            ],
        }
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
