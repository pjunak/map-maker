# Whole-planet relief harness

Research harness for milestone M2 (whole-planet relief). It evolves all land of a
saved `.dmworld.json` on an irregular sphere mesh, using uplift and implicit
stream-power erosion, and writes ignored artifacts. It is not a product command
yet; see the [evidence report](../../docs/research/2026-10-06-whole-planet-erosion-relief.md).

```powershell
# A realistic synthetic test world (fractal coasts, polar and seam-crossing land).
.\.venv\Scripts\python.exe -m benchmarks.planet.synthetic_world --seed 7 --output artifacts/planet/worlds

# Evolve it: 200k nodes ~ 50 km spacing; the output folder must not exist.
.\.venv\Scripts\python.exe -m benchmarks.planet --world artifacts/planet/worlds/fractal-world.dmworld.json `
  --output artifacts/planet/run --nodes 200000 --duration-myr 30 --erodibility 4e-6 --process-km2 10000
```

With a geology recipe (here generated for the synthetic world):

```powershell
.\.venv\Scripts\python.exe -m benchmarks.planet.sample_geology artifacts/planet/worlds/fractal-world.dmworld.json --output artifacts/planet/worlds/fractal-world.dmgeology.json
.\.venv\Scripts\python.exe -m benchmarks.planet --world artifacts/planet/worlds/fractal-world.dmworld.json --geology artifacts/planet/worlds/fractal-world.dmgeology.json --output artifacts/planet/geo
```

Outputs:

- `relief.png`: equirectangular shaded relief with rivers.
- `forcing.png`: normalised uplift.
- `mesh-state.npz`: nodes, elevation, land, receivers, drainage area and uplift.
- `report.json`: settings, timings, history and metrics.

| Module | Role |
|---|---|
| `mesh.py` | Jittered Fibonacci nodes, spherical Delaunay, CSR neighbours, areas, cotangent weights |
| `kernels.py` | Numba kernels: Priority-Flood, receivers, accumulation, implicit stream power, diffusion, Dijkstra, interpolation |
| `fields.py` | Land, coast distance, procedural forcing, ocean floor |
| `evolve.py` | Time stepping with the coast as base level and optional late uplift pulse |
| `geology.py` | Geology recipe → uplift/erodibility with calibrated elevation intent |
| `sample_geology.py` | Deterministic sample recipe for a synthetic world |
| `metrics.py` | Hypsometry, flow isotropy, Hack exponent, non-descending receivers |
| `render.py` | Equirectangular interpolation, hillshade and river overlay |
| `synthetic_world.py` | Deterministic fractal world SVG + reviewed world project |

The `--process-km2` area is added to every node's drainage area. It fixes the
smallest resolved river at a physical scale, so relief statistics do not depend
on mesh density.
