# Refined mountain-crest observations

Date: 2026-09-17. Baseline: `b0898d6`. Implemented decision:
[ADR-0054](../adr/0054-refine-observed-mountain-crests.md).

## Why change the sampler

Endpoint carrier signs can agree on opposite sides of two roots or a tangent
approach to zero. A correctly selected edge can still have its crest between
the seven regular macro probes. The resulting graph understates the obstacle
before Priority-Flood and flow accumulation choose a route.

Use the shared two-octave carrier to screen same-sign candidates and refine
observed crossings/local approaches to zero. Full authored-macro sampling then
checks those positions alongside all retained regular stations. Batches and
streamed grid storage remain bounded; equivalent regional carriers reuse work.
The ADR records the derivative estimate, finite search policy and limits.

Generator identity becomes `coastline-constraint-terrain@13`; automatic valleys
become `regional-budget-mfd-d8-valleys@11`. Terrain recipes, named seeds, public
settings, schemas, authored-input authority and cut-budget formulas do not change.
Routing, derived incision and delivered ground can change. No dependency is added.

## Dense finite macro reference

An ignored observer probe imports the baseline `routing_edges.py` from a
`git archive b0898d6 src/map_maker` snapshot. Both observers receive identical
canonical nodes, regions and the current full authored-macro callback. For each
of five public regional seeds, inspect all 33,635 undirected land-land edges
whose endpoints contact a mountain polygon buffered by the longest grid edge.
This population includes edges neither observer selected. Evaluate 257 equally
spaced positions per edge in batches of 128 edges. Compare each observed barrier
with the largest finite reference height, clamping negative deficits to zero.

The probe verifies that no new barrier is below its previous observation and
records barrier/reference hashes, runtime identity and full-macro query counts.
Evidence is under ignored `artifacts/crest-refinement-2026-09-17/`, including the
probe source and baseline snapshot. The measurement ran with the final numerical
policy before the provenance-ID update. It does not certify continuous maxima;
a refined position can exceed the regular reference's highest observation.

| Seed | Misses >1 m before / after | Misses >10 m before / after | Maximum deficit m before / after | Macro queries before / after |
|---|---:|---:|---:|---:|
| 42 | 1481 / 486 | 578 / 32 | 88.58 / 33.20 | 10,108 / 14,281 |
| 20260902 | 1494 / 435 | 552 / 22 | 79.95 / 51.40 | 9,898 / 14,144 |
| 104729 | 1377 / 434 | 435 / 29 | 69.99 / 23.60 | 8,484 / 13,082 |
| 7 | 1442 / 406 | 292 / 27 | 58.88 / 21.19 | 10,731 / 16,371 |
| 3001 | 1197 / 443 | 361 / 42 | 85.23 / 30.25 | 7,959 / 11,938 |

The number of deficits above 10 m falls by **88-96%** across these five seeds
(2,218 to 152 in aggregate). Deficits above 1 m and maximum deficits also fall in
every measured case. Remaining maxima of 21-51 m show that this is still
incomplete coverage. Full-macro queries rise by 41-54%; cheap carrier evaluations
are additional work and are not included in those query counts.

Single instrumented observer calls take 0.049-0.088 s before and 0.097-0.169 s
after. These locate the additional work; the fresh-process measurements below
are the application generation-cost comparison.

## Finished channels and generation cost

Use the maintained `benchmarks.channel_profiles` runner with all five regional
seeds and 257 stations per selected edge. Float32 ground is promoted to Float64
before measuring the rise above a preceding running minimum. These populations
have descending endpoints by more than 0.01 m; routing changes their membership.
All profiles in this matrix are finite. They do not certify whole rivers.

| Seed | Descending edges before / after | Uphill interiors before / after | Mean excursion m before / after | P95 m before / after | Maximum m before / after |
|---|---:|---:|---:|---:|---:|
| 42 | 2405 / 2400 | 495 / 494 | 0.7301 / 0.7069 | 3.601 / 3.551 | 58.996 / 58.998 |
| 20260902 | 2405 / 2410 | 592 / 595 | 0.8330 / 0.8555 | 3.851 / 3.832 | 58.360 / 58.359 |
| 104729 | 2595 / 2598 | 573 / 571 | 0.6543 / 0.6549 | 3.126 / 3.345 | 54.280 / 54.261 |
| 7 | 2185 / 2203 | 564 / 579 | 0.8655 / 0.8694 | 4.473 / 4.479 | 53.040 / 85.148 |
| 3001 | 3130 / 3130 | 828 / 826 | 0.8760 / 0.8877 | 3.168 / 3.201 | 64.909 / 64.900 |

This is **not a uniform finished-river improvement**. Seed 42's mean falls;
the other four means increase slightly or moderately. Seed 7's maximum grows
from 53.04 to 85.15 m on newly selected edge 9958 -> 9702. A 1025-station check
finds 85.47 m there. Before this change, node 9958 was not a channel and routed
to 10216; sampling the same unselected segment found a 117.73 m hump. The revised
network cuts it down but leaves a climb. The two endpoint source-macro heights
remain unchanged (2320.933487 and 2059.101122 m, rounded). Whole-route consistency and the
interaction with bounded shaping remain unresolved.

Finished-ground diagnostics also mix gains and regressions. For regional seed
20260902, node-to-node maximum channel rise falls from 210.77 to 180.08 m while
uphill-edge count rises from 188 to 190. Depression cells fall from 5223 to 5141
and diagnostic fill volume from 339,528 to 320,211 km3. These node/DEM quantities
are distinct from downhill-endpoint interior profiles above.

### Generation cost and identity

Run the same maintained `benchmarks.terrain` harness on source-isolated versions:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.terrain --case example regional authored outlet archipelago --resolution 513 --seed 42 20260902 --repeats 3 --output artifacts/crest-performance.json
```

This gives 60 fresh-process runs. Each version repeats exactly; all 27 numeric
product hashes and complete quality/drainage/channel/water/outflow summaries
match across versions for the eight non-mountain pairs. Inputs match for every
pair. Regional outputs intentionally change. The benchmark records source,
fixture/harness and runtime identity and rejects mid-run source changes.

| Case / seed | Before median s (range) | After median s (range) | Peak-memory delta MiB |
|---|---:|---:|---:|
| example / 42 | 0.845 (0.843-0.852) | 0.846 (0.843-0.855) | +0.04 |
| example / 20260902 | 0.867 (0.850-0.874) | 0.854 (0.852-0.858) | +0.22 |
| regional / 42 | 1.201 (1.163-1.207) | 1.187 (1.181-1.206) | -0.38 |
| regional / 20260902 | 1.178 (1.171-1.222) | 1.192 (1.185-1.226) | +0.81 |
| authored / 42 | 1.685 (1.616-1.701) | 1.593 (1.576-1.613) | -0.12 |
| authored / 20260902 | 1.734 (1.698-1.758) | 1.595 (1.579-1.642) | -0.21 |
| outlet / 42 | 2.989 (2.906-3.040) | 2.992 (2.832-3.078) | -0.19 |
| outlet / 20260902 | 2.933 (2.930-2.939) | 2.983 (2.955-3.056) | +1.02 |
| archipelago / 42 | 1.630 (1.628-1.640) | 1.595 (1.592-1.608) | -0.97 |
| archipelago / 20260902 | 1.632 (1.630-1.636) | 1.650 (1.587-1.760) | +0.38 |

The initial regional timing ranges overlap and unchanged controls vary, so do
not interpret these medians as a speed improvement. A second, targeted run
alternates before/after and after/before order using the same fresh-process
worker: four repetitions per version/seed, 16 further runs. Every result must
match its version's earlier input, product and diagnostic identities.

| Regional seed | Before median s (range) | After median s (range) | Median change | Peak-memory delta MiB |
|---|---:|---:|---:|---:|
| 42 | 1.166 (1.124-1.344) | 1.208 (1.192-1.235) | +3.6% | +0.07 |
| 20260902 | 1.171 (1.148-1.197) | 1.214 (1.182-1.233) | +3.7% | +0.63 |

The interleaved medians add approximately 42-43 ms, or 3.6-3.7%, for these
regional maps. Ranges still overlap; this is a measured local cost, not a precise
prediction for other machines or projects. Timing excludes file export; peak
memory includes process imports. Full many-region scaling and larger process
grids remain open. No correctness tests or other task workloads ran concurrently
with timed measurements.

### Appearance

Generated before/after public regional previews at 1025 px for seeds 42 and 7;
reviewed seed 7's complete render and enlarged mountain crop. Large landforms
remain visually similar, with local channel/shading changes. Grid-aligned turns,
scalloping and the recipe's separate ridge lobes remain visible. This is static
preview inspection, not a desktop interaction or user acceptance test.

Land/nodata masks match. The DEM differences are:

- seed 42: RMS 1.822 m, largest lowering 175.67 m and raising 161.33 m;
- seed 7: RMS 3.296 m, largest lowering 159.33 m and raising 159.92 m.

Raising relative to an earlier build can mean moving or reducing a previous cut;
it does not imply changing source heights or increasing incision budgets.

## Validation and remaining work

- Focused routing, receiver and hydrology checks: 56 passed.
- Full suite: 820 passed in 230.53 s.
- Ruff passed; strict Pyright reported zero errors and zero warnings.
- All 579 local Markdown file targets resolve; `git diff --check` passed.
- New regressions cover off-station crossings, paired roots, tangent approaches,
  real rotated carriers on unequal axes, region-order/batch invariance, masks,
  symmetric barriers, false-candidate rejection and streamed carrier lifetimes.
- Numerical evidence includes five dense macro-reference cases, ten dense
  finished-channel runs, 76 fresh-process performance runs and public previews.

Adopt the more accurate observation policy while keeping the reported final-ground
regression explicit. It improves the information used by the drainage graph;
it does not complete consistent river floors. Prioritize whole-route conditioning
and turn smoothing next, using seed 7's newly selected segment as a regression
fixture when that behavior is addressed.

The source-scale screen is not a rounded full-field bound, and the fixed carrier
stations cannot isolate arbitrary multiple extrema within a subinterval. Local
searches retain observations without certifying unimodality or convergence.
Other recipes, crest-height modulation, regional blending, authored features and
residual detail remain separate observation work. Retention, final-ground climbs,
whole-route conditioning and D8 turn smoothing remain development priorities.
