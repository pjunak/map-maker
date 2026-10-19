# Planet development tools

Whole-planet relief is a product command since ADR-0085:
`map-maker world planet` ([guide](../../docs/world-planet.md)). This folder holds the
development fixtures and measurements used to build and check it.

```powershell
# Deterministic fractal test world: polar and seam-crossing land, inland seas, islands.
.\.venv\Scripts\python.exe -m benchmarks.planet.synthetic_world --seed 7 --output artifacts/planet/worlds

# A sample geology recipe for that world (old interiors, young/worn belts, plateaus, basins).
.\.venv\Scripts\python.exe -m benchmarks.planet.sample_geology artifacts/planet/worlds/fractal-world.world.json --output artifacts/planet/worlds/fractal-world.geology.json

# Resolution sweep: relief statistics should converge as the mesh is refined.
.\.venv\Scripts\python.exe -m benchmarks.planet.sweep artifacts/planet/worlds/fractal-world.world.json --nodes 50000 200000 800000

# Landform scales of a build (range widths, valley spacing, river lengths vs Earth).
.\.venv\Scripts\python.exe -m benchmarks.planet.scale_metrics my-planet --json scales.json

# Straight against curved interpolation (T22): rebuild a finer build's relief, or an
# Earth DEM, from coarse mesh nodes with each interpolant and score it against the truth.
.\.venv\Scripts\python.exe -m benchmarks.planet.interpolation planet truth-build --output interp.json --crops crops
.\.venv\Scripts\python.exe -m benchmarks.planet.interpolation dem ETOPO_2022_v1_60s_N90W180_surface.tif --output earth.json
```

Generated worlds and recipes are development fixtures, not authored canon. Keep
their outputs under ignored `artifacts/`. Reference data such as the Earth DEM
([source](../../docs/research/2026-10-19-curved-interpolation.md#truths)) is
downloaded into ignored `artifacts/` for a run and deleted afterwards. The
original research harness, with its own kernels, is in Git history. Its
measurements are in the
[relief](../../docs/research/2026-10-06-whole-planet-erosion-relief.md) and
[climate](../../docs/research/2026-10-06-planet-climate-v0.md) reports.
