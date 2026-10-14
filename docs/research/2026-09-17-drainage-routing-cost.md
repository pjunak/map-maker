# Drainage routing cost and bounded regional working storage

Date: 2026-09-17. Baseline: `b281a14`, following the
[mountain-crest routing implementation](2026-09-16-mountain-crest-routing.md).

## Scope and diagnosis

Reduce the cost added by observing mountain crests while preserving the current
terrain and routing behavior. The previous comparison identified measurable
regional overhead and a full carrier grid retained for every mountain region.
No terrain-quality rule or observation coverage is changed by this work.

Separate cProfile runs on example, regional and authored public fixtures at
513 px / seed 42 identify receiver selection, MFD and Priority-Flood as major
Python costs. Each generation calls receiver selection three times, including
diagnostics. The old receiver loop takes 0.295/0.345/0.661 s cumulatively in
those profiled runs. Profiling locates work; its timings are not unprofiled
application latency.

## Changes and preserved numerical contracts

D8 receiver choice is independent between cells, so process the eight directions
as NumPy array views. Keep the original direction order and update only for a
strictly better slope. Retain the scaled-drop comparison when positive slopes
underflow to zero; a zero stored grade must not erase the downhill receiver.
Coast/missing-land masks, retention terminals and observed barriers still filter
candidates. Array views also handle strided, reversed and singleton inputs.

MFD still accumulates cells in the same stable descending order and distributes
to neighbours in the same order. Compute each direction's metric distance once
per call, keep the maximum local slope as a scalar, and read the source area
once before distributing it. Neither summation nor multiplication/division order
changes. Priority-Flood uses the scalar standard-library successor and computes
it once per settled node; queued lower-pass relaxation remains unchanged.

For crest observations, fold one regional carrier at a time into four shared
candidate masks. Release the carrier and its views before the next region.
Sampling retains the same candidate union, ordering, seven interior positions,
4096-edge batch limit and symmetric barrier values. Working grid storage no
longer grows with the number of mountain regions. Authored region objects and
the work required to evaluate them still scale with input size.

This optimizes existing numerical behavior. Keep generator
`coastline-constraint-terrain@12`, automatic valleys
`regional-budget-mfd-d8-valleys@10`, seeds, schemas and settings. The recorded
runtime source identity changes. No new dependency or compatibility path is
introduced; the scalar reference in tests is an independent selection oracle.

## Reproducible measurements

Save the baseline source with `git archive b281a14 src/map_maker` and import it
through an isolated Python path. Use the same maintained terrain benchmark,
fixtures and environment for both versions. Keep all generated evidence ignored
under `artifacts/routing-cost-2026-09-17/`. Freeze runtime/benchmark source during
measurement, and run correctness tests separately from timed work.

```powershell
.\.venv\Scripts\python.exe -m benchmarks.terrain --case example regional authored outlet archipelago --resolution 513 --seed 42 20260902 --repeats 3 --output artifacts/routing-performance.json
```

The main comparison uses a fresh process per repetition and excludes file
export. Reports retain input identity, runtime/source identity, full numerical
product hashes and diagnostic summaries. Peak memory is process high-water
resident usage, including imports, rather than an isolated stage allocation.

The separate many-region allocation probe uses a 257-square grid over 4000 km,
seed 42, and 1/16/64/128 fully overlapping mountain regions. Region i has
feature size `240 + 40*(i % 7)` km and orientation `(37*i) % 180` degrees,
with elevation 1400 m, relief 800 m and the default 50 km transition. All nodes
are land and every region covers the full metric square.
An analytic sampler, `1000 + 200*sin(x/180)*cos(y/200)` metres, isolates observer
preparation from full regional blending. Start tracemalloc immediately before
observation preparation in each fresh process and record sampled-coordinate
and barrier hashes, query counts, bounded batches and process peak memory.
Tracing measures allocations; these runs are not generation timing evidence.

## Generation time and numerical identity

Three repetitions per case/seed/version give **60 fresh-process runs**. All
27 numeric product hashes, input hashes and full quality/drainage/channel/
water/outflow summaries match both within and across versions for every pair.
The runtime source hashes differ as intended. All before/after timing ranges
are disjoint in this matrix; no additional repeated batch was necessary.

| Case / seed | Before s | After s | Median reduction | Median peak change MiB |
|---|---:|---:|---:|---:|
| example / 42 | 1.058 | 0.787 | 25.7% | 0.00 |
| example / 20260902 | 1.066 | 0.783 | 26.6% | +0.02 |
| regional / 42 | 1.390 | 1.033 | 25.7% | -0.19 |
| regional / 20260902 | 1.367 | 1.040 | 23.9% | +0.31 |
| authored / 42 | 1.843 | 1.343 | 27.1% | +0.32 |
| authored / 20260902 | 1.844 | 1.327 | 28.1% | -0.03 |
| outlet / 42 | 2.819 | 2.583 | 8.4% | +0.15 |
| outlet / 20260902 | 2.881 | 2.599 | 9.8% | -0.30 |
| archipelago / 42 | 1.764 | 1.510 | 14.4% | -0.09 |
| archipelago / 20260902 | 1.784 | 1.526 | 14.4% | +0.73 |

Observed generation reductions range from 8.4% to 28.1%; the two regional cases
improve by 23.9-25.7%. Outlet builds improve less because other work still
occupies much of their runtime. These results apply to these 513 px fixtures,
not every project or complete export. Median process-peak differences range
from -0.30 to +0.73 MiB; ordinary-generation memory is effectively similar on
this matrix. The larger allocation reduction concerns many-region preparation.

The after-profile receiver totals are 0.011/0.010/0.023 s for
example/regional/authored, compared with 0.295/0.345/0.661 s before. MFD and
Priority-Flood also decrease in those profiles. Keep those instrumented timings
separate from the fresh-process generation table.

## Many-region allocation comparison

| Regions | Interior queries, unchanged | Traced peak MiB before / after | Process peak MiB before / after |
|---|---:|---:|---:|
| 1 | 74,494 | 15.02 / 12.85 | 80.49 / 78.05 |
| 16 | 707,434 | 23.90 / 13.06 | 90.79 / 78.72 |
| 64 | 1,533,168 | 52.11 / 14.05 | 119.73 / 80.79 |
| 128 | 1,776,432 | 88.87 / 14.51 | 156.79 / 80.54 |

Every query-sequence hash and barrier-array hash matches. The largest batch has
28,672 points, exactly the existing 4096-edge by seven-position limit. Retained traced
allocations stay about 4.04 MiB in both implementations. At 128 regions,
traced peak allocation falls **83.7%**, from 88.87 to 14.51 MiB.

The new peaks vary as the candidate union becomes denser; they are bounded by
the grid and batch sizes instead of retaining another full carrier per region.
Process peaks include the interpreter, imports and tracing overhead. This probe
does not time full generation with 128 blended regions or measure its complete
memory budget. Ground evaluation still performs work for applicable regions.

## Validation and remaining work

- Exact scalar-oracle comparisons cover normal/subnormal grades, ties, anisotropic
  spacing, masks, barriers, terminals, reversed/strided arrays, singleton axes
  and empty grids. A separate lifetime regression checks that repeated regions
  do not accumulate live carrier grids.
- The complete suite passes: **814 tests**, including conservation, lower-pass
  relaxation, authored-budget and terrain regressions. No timing thresholds or
  machine-dependent byte-count assertions are added to unit tests.
- Ruff and strict Pyright pass; 569 local Markdown file targets resolve.
  No UI, renderer or public schema changes are made.
- Measure whole builds with many regions and larger delivered/process grids;
  the isolated allocation probe does not complete those performance questions.
- Return to broader crest/extrema coverage, whole-route conditioning and D8 turn
  smoothing. The previous terrain-quality limitations remain unchanged by this
  optimization; its improved crest avoidance is retained exactly in the checks.
