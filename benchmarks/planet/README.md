# Planet development tools

Whole-planet relief is a product command since ADR-0085:
`dmtools world planet` ([guide](../../docs/world-planet.md)). This folder holds the
development fixtures and measurements used to build and check it.

```powershell
# Deterministic fractal test world: polar and seam-crossing land, inland seas, islands.
.\.venv\Scripts\python.exe -m benchmarks.planet.synthetic_world --seed 7 --output artifacts/planet/worlds

# A sample geology recipe for that world (old interiors, young/worn belts, plateaus, basins).
.\.venv\Scripts\python.exe -m benchmarks.planet.sample_geology artifacts/planet/worlds/fractal-world.dmworld.json --output artifacts/planet/worlds/fractal-world.dmgeology.json

# Resolution sweep: relief statistics should converge as the mesh is refined.
.\.venv\Scripts\python.exe -m benchmarks.planet.sweep artifacts/planet/worlds/fractal-world.dmworld.json --nodes 50000 200000 800000

# Regional enrichment research (M6): one window, or blended fixed tiles.
.\.venv\Scripts\python.exe -m benchmarks.planet.regional artifacts/planet/worlds/fractal-world.dmworld.json --lon 61 --lat -39.6 --output artifacts/planet/region
.\.venv\Scripts\python.exe -m benchmarks.planet.tiles artifacts/planet/worlds/fractal-world.dmworld.json --lon 61 --lat -39.6 --output artifacts/planet/tiles
```

Generated worlds and recipes are development fixtures, not authored canon. Keep
their outputs under ignored `artifacts/`. The original research harness, with its
own kernels, is in Git history. Its measurements are in the
[relief](../../docs/research/2026-10-06-whole-planet-erosion-relief.md) and
[climate](../../docs/research/2026-10-06-planet-climate-v0.md) reports.
