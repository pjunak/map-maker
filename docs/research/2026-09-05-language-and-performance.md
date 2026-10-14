# Language and performance — 2026-09-05

Status: **assessment and proposed experiments**, not approval for a rewrite or
new dependencies. The recommendation is to tighten foundations now, retain
Python for the next terrain experiments, and prefer Rust if measured needs
justify a later runtime replacement. A rewrite is not an inevitable milestone.
This adds R45–R47 to the [roadmap](../../TODO.md) and brings profiling forward;
it does not replace the [current strategy](../strategy/README.md).

## Current evidence

Inspected baseline `9487c58`, particularly the
[generator](../../src/map_maker/terrain/pipeline/generate.py),
[noise](../../src/map_maker/terrain/pipeline/noise.py),
[hydrology](../../src/map_maker/terrain/pipeline/hydrology.py),
[headless build](../../src/map_maker/terrain/application/build.py) and dependency
constraints. The application already separates domain, pipeline, adapters and
interfaces; preserving and completing those boundaries is more useful than
replacing them with a new framework.

Measured `generate_terrain` on the current Windows host with Python 3.14.7 and
NumPy 2.5.2. Loaded the public example once, retained its settings/seed and empty
constraint list, then changed only `resolution_px`. Warmed the process with one
64-pixel generation and timed three sequential runs at each resolution, in
ascending order. Deleted each returned terrain before the next run. Timings
exclude imports, SVG/project loading, image rendering, the build-quality pass
and file publication; the generator's own drainage diagnostics are included.

| Longest dimension | Actual array, rows × columns | Three runs, seconds | Median, seconds |
|---|---|---|---|
| 768 | 455 × 768 | 1.482, 1.460, 1.434 | 1.460 |
| 2,048 | 1,214 × 2,048 | 11.926, 10.633, 9.360 | 10.633 |
| 4,096 | 2,427 × 4,096 | 32.053, 29.579, 31.271 | 31.271 |

This is a local diagnostic sample, not a controlled performance guarantee.
Background load, caches and CPU behavior were not controlled. It covers one
coastline/seed, no authored constraints, and no peak-memory measurement. It
does establish that larger builds warrant performance work; it does not prove
which language will meet future requirements.

One separate 2,048-pixel `cProfile` run after those timings took 7.818 seconds:

| Operation | Profile time, seconds | Approximate share |
|---|---|---|
| Shapely `distance` (internal time, including native GEOS work) | 3.874 | 50% |
| `fractal_value_noise` (cumulative, including NumPy operations) | 2.121 | 27% |
| Automatic-valley preparation (cumulative) | 0.654 | 8% |

These are selected entries, not disjoint stages: automatic-valley preparation
also calls geometry and noise. Do not add the shares. The profile run is
separate from the timing medians; its lower duration illustrates measurement
variability, not an optimization. A function in a Python module can spend most
of its time executing native array/library operations.

The current output evaluation constructs points and queries coast distance
for the whole rectangular chunk before discarding ocean elevations. Routing
uses a fixed 257-sample longest dimension and diagnostics a separate 129-sample
grid. Increasing output resolution does not increase either process grid's
resolution. A faster language alone would not correct that scale limitation.

To repeat the generation timings from the repository's Python environment:

```python
from dataclasses import replace
from pathlib import Path
from statistics import median
from time import perf_counter

from map_maker.terrain.adapters.project import load_terrain_project
from map_maker.terrain.pipeline.generate import generate_terrain

project = load_terrain_project(Path("examples/terrain/example.terrain.json")).project
generate_terrain(project.coastline, replace(project.settings, resolution_px=64),
                 constraints=project.constraints)
for resolution in (768, 2048, 4096):
    settings = replace(project.settings, resolution_px=resolution)
    times = []
    for _ in range(3):
        start = perf_counter()
        terrain = generate_terrain(project.coastline, settings,
                                   constraints=project.constraints)
        times.append(perf_counter() - start)
        del terrain
    print(resolution, times, median(times))
```

For a separate profile, use `cProfile.Profile().runcall(generate_terrain, ...)`
with the 2,048-pixel settings and inspect both internal and cumulative times.
Do not use test-suite duration as a substitute for application benchmarks.

## Recommended next implementation boundary

1. Complete the coordinate/grid, authored-constraint priority and named-stage
   seed contracts. Preserve authored vectors and the authoritative Float32 DEM.
   Specify nodata, tie-breaking, numerical tolerances and algorithm versions.
2. Establish representative performance and quality fixtures: mountain/pass,
   plateau/plain, basin/outlet, complex coast, and nested regional refinement.
   Include hard-constraint residuals, drainage connectivity, seams and peak
   memory alongside duration. Agree separate draft and full-build budgets.
3. Optimize the measured geometry/noise work. Investigate reuse, exact spatial
   indexing, reduced allocations and fused array operations. Validate every
   optimization against the same inputs; approximate distance fields are an
   algorithm change requiring explicit error and refinement checks.
4. Continue a bounded terrain slice in Python to exercise those contracts,
   including a comparison of candidate surface solvers and authored drainage.
   Avoid expanding simultaneously into climate, glaciers, dunes and deltas.

Do not wait for the entire feature backlog before reconsidering migration.
Review after this foundation pass and one representative terrain experiment.
Port a stable, measured bottleneck when the expected end-to-end benefit is
material; commit to a full rewrite only when the broader acceptance criteria
below are met. A long feature freeze for speculative infrastructure is also
unjustified.

## Language assessment

**Rust is the preferred eventual terrain-core language.** Ownership-based
memory management and explicit array/data ownership fit a long-lived numerical
engine; Rayon supplies data parallelism. This is a project-specific judgment,
not a measured speed comparison. Rust introduces compile time, ownership/FFI
design work and additional effort reproducing scientific prototypes. It does
not automatically improve native geometry calls, algorithms or memory traffic.
See the [Rust ownership guide](https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html)
and [Rayon documentation](https://docs.rs/rayon/latest/rayon/).

**C++ is the strongest alternative if direct reuse of native scientific or GPU
implementations becomes decisive.** GDAL exposes C/C++ APIs; Rust bindings
also call the native library. The deployment and native-library compatibility
work remains either way. Prefer Rust for new project-owned code unless a
specific required dependency makes C++ materially simpler. See
[GDAL](https://gdal.org/en/stable/) and the
[GeoRust GDAL binding/build requirements](https://github.com/georust/gdal).

**Keeping Python with targeted acceleration is a credible outcome**, not merely
a temporary failure to migrate. Shapely already uses GEOS and array-oriented
ufuncs. The live Numba compatibility table lists 0.67.0 supporting Python
3.14 and NumPy 2.5, matching the current installed pair. A bounded Numba
experiment may therefore test noise fusion or suitable numeric loops without
rewriting the application. Windows installation, actual kernel support,
compilation latency and benefits have not been tested; the repository's broad
NumPy `<3` range must not be mistaken for Numba support for every allowed future
version. No dependency was installed for this assessment. See
[Shapely](https://shapely.readthedocs.io/en/stable/) and the
[Numba version table](https://numba.readthedocs.io/en/stable/user/installing.html#version-support-information).

If a gradual transition is chosen, PyO3/rust-numpy can expose a Rust kernel
through NumPy arrays, and Maturin packages Rust Python extensions on Windows.
Keep numerical Rust functions independent of Python bindings and cross the
boundary with whole arrays, not callbacks per cell. Measure copies and binding
overhead. This is explicitly a hybrid transition, not a completed Python
replacement. A complete Rust application can instead consume the same project
files and be compared with the Python reference as a separate executable.
See [rust-numpy](https://github.com/PyO3/rust-numpy) and
[Maturin](https://www.maturin.rs/).

## Migration acceptance gate

- Representative workloads miss an agreed runtime/memory or deployment goal,
  and profiling identifies costs a native implementation can actually change.
- Stage inputs/outputs and at least one representative terrain workflow have
  stable semantics. New scientific experiments can remain outside the product
  runtime rather than constantly changing the replacement engine's contract.
- A release-built native proof improves complete builds, including conversion,
  I/O and memory costs, enough to justify the extra maintenance and build work.
- Compare numerical residuals and terrain invariants at agreed tolerances;
  specify exact seed/hash/tie behavior separately. Do not promise Float32
  bit-for-bit identity across different arithmetic implementations or thread
  schedules without evidence. Version intentional output changes.
- Verify project loading/saving, CLI errors, cancellation, export/provenance,
  desktop workflows where in scope, and native-library packaging on Windows.
  Choose explicitly between a hybrid kernel transition and complete removal of
  the Python product runtime. Compilation or one fast kernel proves neither
  full workflow parity nor a complete rewrite.
