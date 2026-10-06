# Terrain performance checks

These repository-only tools measure the installed Python engine without adding
runtime dependencies or changing authored projects. Run them from the repository
root with its development environment; they are not installed as `dmtools`
commands.

```powershell
.\.venv\Scripts\python.exe -m benchmarks.terrain --resolution 768 2048 --seed 42 --repeats 3 --output artifacts/performance.json
```

The output must be a new file. Reports are generated artifacts and must not be
committed. A failed run retains an incomplete file without a valid completed
report. The runner checks that repeated inputs produce identical numeric
outputs/diagnostics and that generator source, dependencies and benchmark code
have not changed during the run. Do not edit engine or benchmark Python files
while measuring them, and avoid concurrent tests or other heavy workloads.

## Whole-planet relief

The product command is `dmtools world planet` ([guide](../docs/world-planet.md)).
The [planet tools](planet/README.md) generate realistic synthetic test worlds and
sample geology, and run resolution sweeps of the planet relief.

## Landscape evolution

The [isolated evolution reference](evolution/README.md) compares prescribed
uplift/erosion histories against the current generator. It has its own pinned
scientific environment and produces epoch figures, physical-scale measures and
fresh-process cost evidence. It does not change normal terrain builds.

## Cases

| Case | Purpose |
|---|---|
| `example` | Existing public SVG project and its settings; no authored constraints |
| `square` | Four-edge land boundary; every grid sample is land |
| `archipelago` | Synthetic irregular coast, three islands and inland water; 960 boundary vertices |
| `authored` | Square land with a ridge, peak/pass anchors, relative valley and relative brush |
| `regional` | Public four-region project, including regional relief and incision budgets |
| `water` | Authored lake/dry-basin footprints, cut protection and separate water products |
| `outlet` | Connected public lake with a reviewed route to the coast |
| `flat` | Exact internal flats, collected water and retained pits |
| `shoreline` | Narrow boundary opening missed by the canonical wet nodes |
| `narrow` | 200 m boundary feature needing local refinement |
| `downstream` | 100 m downstream height feature blocking a canonically clear route |
| `internal` | 100 m internal height feature separating a canonically connected lake |
| `dry` | 100 m dry height feature rejected before selecting a clear alternative |
| `lakes_small` | Opt-in: four irregular lakes, two outlets and 16 distributed relative points |
| `lakes` | Opt-in: 16 irregular lakes, eight outlets and 64 distributed relative points |
| `lakes_broad` | Opt-in: the same 16 lakes and 64 points with broad, overlapping influence |

The three `lakes*` scaling cases are excluded from the default run. They keep
physical inputs fixed on a 4000 km square, use five detail levels and mix
positive/negative points. Point radii are 12 km for the distributed cases and
2000 km for the broad case. Lake levels are workload inputs: forecast networks
may exist even when actual outlet review rejects transfer. These are not
recommended authoring settings or a physical lake model. For the current
scaling and guide-query results, see the
[prepared-bounds report](../docs/research/2026-09-13-water-guide-bounds.md).

```powershell
.\.venv\Scripts\python.exe -m benchmarks.terrain --case lakes_small lakes lakes_broad --resolution 768 --seed 42 --repeats 3 --output artifacts/lake-scaling.json
```

Select cases and multiple resolutions/seeds explicitly:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.terrain --case example archipelago --resolution 768 --seed 42 20260902 --repeats 3 --output artifacts/coasts.json
```

The synthetic cases are workload probes, not a complete terrain-realism fixture
suite. A 4,096-pixel run can be requested separately; it is intentionally absent
from the default to keep routine measurements bounded. Regional refinement and
process-spacing experiments still need their own fixtures.

## What is measured

Each repetition starts a new Python subprocess, with no warm-up generation:

- fixture/project loading;
- generation wall time and process CPU time;
- intervals between the generator's existing progress labels;
- delivered-surface quality measurements;
- cartographic and scientific rendering separately; and
- total worker wall time, including startup, imports and result serialization.

Progress labels are diagnostic grouping, not a new public pipeline-stage API.
Canonical drainage diagnostics remain within generation time. Output quality
and rendering are measured afterward. Disk export, PNG encoding and publication
are excluded; these results must not be called full-build timings. Report
serialization and child-process communication are included only in worker wall
time. Deterministic hashes identify elevations, masks and both coordinate axes;
quality, drainage, planned/final routing agreement and overlapping conflict
context summaries are also retained.
Hashes also cover receivers, channels, incision, incision limits, conflict flags
and the finished field on routing nodes. Internal basin paths, flat ranks, full-path
uphill excursions and area-transfer arrays are hashed too. Sampling now emits its label before the first chunk;
older reports charged that first chunk to the preceding routing interval.

Peak resident memory comes from the OS and includes native-library allocations.
The generation measurement is the process high-water mark up to generation's
completion; the products measurement is the high-water mark through quality
and rendering. Both include imports and fixture preparation. They are neither
current memory usage nor sums of per-stage allocations, and their difference
is not a stage's allocation count. Windows uses `GetProcessMemoryInfo`; Linux
and macOS use `getrusage` with platform-specific units. Unsupported platforms
report null. Windows is the currently exercised platform. See the
[Windows counter definitions](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters).

## Comparing revisions

Keep before/after reports from identical arguments. Match rows by case,
resolution and seed, then require identical input hashes, array hashes,
drainage and quality for an optimization that promises unchanged results.
Compare medians and ranges; retain Python, NumPy, GEOS and platform identity.
Source hashes are expected to differ between implementations. A speed change
without matching inputs or numerical validation is not an accepted result.

Run benchmarks separately from the correctness suite. Do not add machine-
dependent timing thresholds to ordinary tests. Use a separate profiler run to
locate expensive functions; profiler timings are not interchangeable with the
unprofiled measurements. These cold-process measurements also differ from the
earlier exploratory repeated generations within one warmed Python process.

The [language assessment](../docs/research/2026-09-05-language-and-performance.md)
records why optimization begins in Python and the evidence required before a
native-language migration.
The [routing-cost comparison](../docs/research/2026-09-17-drainage-routing-cost.md)
records the later NumPy D8 optimization, exact product equality and a separate
allocation probe with up to 128 overlapping mountain regions. That isolated
observer probe is not a full many-region generation benchmark.

The [2026-09-10 review](../docs/maintenance/2026-09-10-sanity-and-performance.md)
records earlier coast/regional bottlenecks. The
[dry-path follow-up](../docs/research/2026-09-11-dry-collection-paths.md) measures
the expanded water workload; the [current status](../docs/research/status.md)
tracks remaining performance and validation gaps.

## Channel-interior profiles

```powershell
.\.venv\Scripts\python.exe -m benchmarks.channel_profiles --output artifacts/channel-profiles.json
.\.venv\Scripts\python.exe -m benchmarks.channel_profiles --case archipelago square regional --seed 104729 --stations 257 --output artifacts/channel-profiles-dense.json
```

This repository-only quality probe prepares the normal deterministic field and
samples every selected channel-to-receiver edge, independently of display
resolution. It uses 65 stations by default, accepts 3-1025, and evaluates at most
256 edges per batch. It does not time generation or modify the field.
Delivered Float32 heights are promoted to Float64 before measuring ordered
uphill excursion. Endpoints descending by more than 0.01 m are reported
separately, as are cardinal and diagonal edges. Non-finite/non-land profiles
remain unresolved counts, not zero-climb successes. Empty groups have null
statistics. Report version 2 also records counts of excursions strictly greater
than 1, 10, 50 and 100 m for each group. Compare the all-finite population when a
change moves edges into or out of the descending-endpoint subset. Profile,
canonical-array, input, runtime and harness/fixture hashes
support comparisons. Outputs must be new files; an interrupted report is not
complete.

Finite station checks do not certify every point between samples. See the
[diagonal-connection experiment](../docs/research/2026-09-16-connected-diagonal-valleys.md)
for measured gains, remaining large excursions and the baseline comparison.
Use source-isolated runs with matching input hashes when comparing algorithms.
The [crest-refinement comparison](../docs/research/2026-09-17-refined-mountain-crests.md)
separates dense macro-barrier observations from finished-channel profiles:
more accurate routing barriers alone do not make every river metric improve.
The [network-floor comparison](../docs/research/2026-09-17-network-floor-conditioning.md)
records why severity, individual regressions and the compared population matter.

## Water-profile convergence

```powershell
.\.venv\Scripts\python.exe -m benchmarks.water_convergence --seed 42 20260913 --repeats 2 --output artifacts/water-convergence.json
```

This separate read-only runner compares real finished-ground profiles in five
synthetic scenes: a narrow regional plateau, global procedural detail, rotated
regional detail, a point's context tail outside its core corridor, and overlapping
positive and negative points. Defaults compare 400/4000 km objects, horizontal/diagonal
canonical edges and a 64-pixel delivered raster. Protected dry footprints keep
automatic cuts from obscuring the field being studied. These are numeric
stress fixtures, not recommended authoring presets. Optional `--direction oblique`
uses a `(1, 0.37)` grid-edge vector; its endpoint is deliberately off the canonical
grid. Horizontal and diagonal remain the defaults.

Every trial preserves the complete production station set. Aligned trials
split each original interval by factors 1, 2, 4, 8, 16, 32 and 64; half-shifted
trials instead place interior probes at `(i + 0.5) / factor`, also keeping the
original endpoints. The reference uses twice the largest factor and includes
all trial stations exactly. It is a finite sampled reference, never continuous
ground truth, a GCI calculation or a hydraulic model. Extrema, greatest raw-ground
rise from an earlier minimum, witness positions, 0.01 m threshold decisions and differences
to that reference are recorded. Shared positions and Float32 values must match
byte for byte; no resampling or interpolation substitutes for field evaluation.

Use `--case`, `--scale`, `--direction`, `--resolution`, `--seed`, `--refinements`
and `--max-samples` to select an experiment. Refinements must be increasing
powers of two starting at 1 (maximum 256); the comparison cap defaults to 262144
and cannot exceed that value. The former 65536 default could not fit the full
128-fold reference after procedural guidance enlarged production profiles. Each complete trial/reference budget is checked before
allocation or evaluation. A missing reference or over-budget baseline remains
explicitly unresolved, with no error difference or accepted prefix. This
research-only cap does not change any production budget.

Reports record inputs, engine/runtime and harness source hashes, all 27 numeric
product hashes, water evidence identity, per-run time/peak process memory and
repeatability. `geometry_only` removes procedural density and context guidance
while keeping authored cores and regional transitions. `without_region_guidance`
omits polygon transition guides only; procedural density remains. Both inspect
the exact same finished field, and are research controls rather than product
settings. The runner observes the existing prepared evaluator call
and verifies that inspection leaves numeric products and water review unchanged.
No new product API is added. Each repeat is a fresh process; output files must
be new, publication is completion-last, and source changes during measurement
invalidate the run. Avoid concurrent heavy work. Results belong under ignored
`artifacts/`; the [station-policy report](../docs/research/2026-09-13-detail-and-context-sampling.md)
records the implemented guidance and remaining gaps.

### Adaptive midpoint experiment

```powershell
.\.venv\Scripts\python.exe -m benchmarks.water_convergence --seed 42 20260913 --direction horizontal diagonal oblique --repeats 2 --adaptive-tolerance 1 .1 .01 --output artifacts/adaptive-profile-matrix-final-20260913.json
```

`--adaptive-tolerance` adds midpoint-residual trials to the `current` profile;
geometry controls and uniform trials remain available. Each threshold is a
positive finite number of metres. This research experiment adds probes where
midpoint ground differs from the endpoint average. It preserves all production
stations and evaluates the entire pending wave only if it fits. The defaults
are `--adaptive-max-depth 7` (allowed 1-8) and `--adaptive-max-samples 65536`
(allowed 1-65536). Exhausted baseline, wave, depth or coordinate precision is
explicit, with no accepted partial metrics or reference comparison.

`indicator_satisfied` means only that the tested residuals passed. It does not
mean clear water, bounded extrema or a converged terrain solution. Afterwards,
a separate reference divides each original interval into
`2**(adaptive_max_depth + 1)` parts: factor 256 at default depth. It includes
all adaptive probes exactly and shares the `--max-samples` reference cap.
A reference that cannot fit remains `budget_exceeded`, and error comparisons
remain unknown. The reference never chooses the adaptive probes.

The report records visited/requested station counts, residuals, hashes, extrema,
baseline/adaptive differences against the same finite reference and
`reference_exceeds_tolerance`. That last flag compares the largest minimum,
maximum or ordered-rise discrepancy with the requested residual threshold;
it is not a hydraulic decision. Station counts include repeated path positions;
they are not unique evaluations. Timings include controls and reference work,
not just the proposed probes. Research report schema v2 records the experiment
method/source identity; product schemas and algorithm identities are unchanged.
See the [adaptive report](../docs/research/2026-09-13-adaptive-water-profile-refinement.md)
for measured benefits, false convergence and the decision to keep this heuristic
out of runtime clearance checks.


### Procedural-noise component and profile bounds

```powershell
.\.venv\Scripts\python.exe -m benchmarks.noise_bounds --seed 42 20260913 --detail 1 6 12 --roughness .25 .55 .9 --span .25 2 --direction horizontal diagonal oblique --divisions 1 16 256 4096 --repeats 2 --output artifacts/noise-geometry-matrix-20260916.json
```

This research runner compares four policies: `natural`, `monotone_cell`,
`profile_slabs` and `profile_hybrid`. The first two enclose the rectangle around
each fixed profile interval with outward natural arithmetic or monotone
fade/bilinear corner bounds plus derived rounding allowances. The third restricts cell work to rounded grid
strips along the original affine path. The fourth chooses a rectangle when the
minor axis touches at most two cells, and clipped strips elsewhere. All four
bound the existing noise component transformed to `Float32(2000 + 1000 * noise)`
metres. The runner does not inspect a saved project or bound the complete coast/region/constraint/incision
field. See the [component report](../docs/research/2026-09-13-noise-component-bounds.md)
for the shared rounding kernel and its original two-policy measurements.

`--span` is the horizontal profile extent in multiples of the fixed 2 km largest
feature; diagonal/oblique profiles also move in Y. `--detail` accepts 1-12,
`--roughness` is strictly between zero and one, and `--divisions` accepts increasing
powers of two through 8192. Defaults use seed 42, details 1/6/12, roughness .55,
spans .25/2, horizontal/oblique directions and subdivisions 1/16/256.

`--max-slabs` defaults to 262144 (allowed 1-262144) and counts the complete initial
strip plan before allocation. `--max-cells` has the same default/range and counts
all planned cell visits across intervals and octaves before lattice evaluation.
An exhausted strip plan has unknown cell demand; neither failure accepts partial
bounds. These limits govern research work, separately from production station caps.

Each case/repeat starts a fresh process. It records source/runtime identity,
input/bound/sample hashes, required/evaluated cells, strip counts, exhaustion,
component/reference timings and process high-water memory. All policies share
endpoint evaluations. Their timing order is fixed: natural, rectangle, strips, hybrid.
A separate 65,537-point finite reference checks every interval and exact shared
Float32 values without selecting bounds from those heights. Reference agreement
is an independent check, not the proof of inclusion. Reports reserve a new path
and publish completion last; changed sources or non-repeatable evidence fail the run.

Report version 3 records hybrid/refinement identities and optional refinement
trials alongside the profile method and ordered uphill bounds/gaps. Ordered-rise
summaries assume complete intervals in path order and include possible low/high
positions within the same interval. These conservative
upper bounds can remain loose even when overall extrema are well bounded. They
are research report fields, not terrain build fields. See the
[profile report](../docs/research/2026-09-14-noise-profile-bounds.md) for rounding,
measured work/uncertainty and the remaining full-terrain boundary. Runtime water
decisions and the existing water-profile benchmark remain separate.


### Bound-driven noise refinement

```powershell
.\.venv\Scripts\python.exe -m benchmarks.noise_bounds --seed 42 20260913 --detail 1 6 12 --roughness .55 .9 --span .25 2 --direction horizontal diagonal oblique --divisions 1 16 256 4096 --adaptive-tolerance 1 .1 --repeats 2 --output artifacts/noise-refinement-matrix-20260916.json
```

`--adaptive-tolerance` adds positive finite metre thresholds. For each, the runner
compares uniform refinement with hybrid geometry, adaptive refinement with strips,
and adaptive refinement with hybrid geometry, in that fixed order. Both refinement
strategies require conservative local endpoint-envelope and ordered-rise gaps to
meet the tolerance. This is different from the midpoint-residual heuristic above.

Cell and strip limits apply cumulatively across every refinement wave, including
superseded parents. `--adaptive-max-samples` defaults to 65536 (allowed 2-65536),
and `--adaptive-max-depth` defaults to 16 (allowed 0-16). Pending waves are checked
in full before evaluation. Cells, allocated strips and evaluated sample positions
are distinct counts. Failure reports keep `accepted: null`; completed-wave metrics
are diagnostics, not evidence that the requested accuracy was achieved.

The reference never directs refinement. Accepted profiles must enclose every
independent reference probe, preserve shared Float32 samples and meet the local
and ordered-rise thresholds. Fresh-process replay and source fingerprints cover
all four research modules. Refinement timings include planning, enclosure,
sampling, partition updates and stopping decisions; reference checks are separate.
The [refinement report](../docs/research/2026-09-16-bounded-noise-refinement.md)
records the arithmetic argument, paired measurements and remaining full-field work.

## Bounded regional sampling

```powershell
.\.venv\Scripts\python.exe -m benchmarks.regional --output artifacts/regional-measurements.json
```

Create the output's parent directory first; the JSON output must not exist.
The default four public/synthetic fixtures compare 65/129/257 core windows and
complete finer sampling at the same spacing, reusing one prepared full context.
`--case`, `--seed` and `--repeats` select fixtures, seed and local timing repeats.
The harness checks exact nested, repeat-order and full-field values, records
runtime/input/source identities and excludes export and full-build review costs.
See the [2026-09-22 measurements](../docs/research/2026-09-22-regional-field-sampling.md).

## Detail-band growth

```powershell
.\.venv\Scripts\python.exe -m benchmarks.detail_bands --case example regional authored water --seed 42 --output artifacts/detail-growth.json
```

This research probe generates each public case on a 257-longest-side grid with
2, 6 and 12 bands. It records fixed coefficients, numeric/source/input hashes,
pointwise differences, changed canonical receivers, and trapezoidal averages
over central 16x16 cells with 8x8 fine intervals each. Only fully land-covered
cells count. This is a whole-map settings comparison, not a local enrichment
operation or a promise of parent consistency. The output must be a new file in
an existing directory; no timing or speedup claim is made. See the
[policy comparison](../docs/research/2026-09-22-stable-detail-band-amplitudes.md).

## Parent-cell preservation experiment

```powershell
.\.venv\Scripts\python.exe -m benchmarks.parent_detail --case regional authored water --seed 42 7 --save-grids --output artifacts/parent-cell-results.json
```

Create the output's parent directory first. The JSON and, with `--save-grids`,
its sibling directory named after the JSON stem must not already exist. Defaults
cover three public fixtures and two seeds. Each run prepares a complete two-band
field, freezes an interior 5x5 parent snapshot and adds two bands with the same
prepared profiles/routing. Whole parent cells are conditioned at 65/129/257 nodes.
The report records nodes, trapezoidal means, overlap/order, density drift, finite
boundary secant slopes, authored points, wet classification and paired inherited
channel profiles, with source/runtime/input/output hashes. Saved grids include
NPZ arrays and ground-only PNG controls.

This is an all-land research kernel, not a finished-build loader or product
regional-enrichment operation. It does not implement partial coastal cells,
protected authored constraints, refined routing or boundary inflow transfer.
Single projection timings exclude global preparation and other job costs.
The [2026-09-23 report](../docs/research/2026-09-23-parent-cell-preservation.md)
rejects this candidate for runtime use and records the next preservation gates.


## Verified-parent local detail

```powershell
.\.venv\Scripts\python.exe -m benchmarks.local_detail --case example regional water --seed 42 7 --output artifacts/local-detail-measurements.json
```

The JSON and its sibling directory named after the JSON stem must both be new.
Each public project is built with 65 longest-side nodes and two detail bands,
then decoded and numerically replayed before detail at 65/129/257 core samples.
The fixed window is not selected for successful detail: lake-heavy cases can be
fully protected and add no heights. A 40 m residual budget makes differences
inspectable. Every child includes numeric/reference/moment arrays and a
reference/detail/difference PNG, with completion provenance and false hydrology
readiness. Nested samples, overlaps, repeat visits, parent nodes and water must
agree. Runtime and benchmark source changes abort publication of the report.

Stage timings are serial observations, not fresh-process speedup comparisons.
They separate parent build, file loading, complete replay, protection preparation,
regional generation and publication. See the
[measured report](../docs/research/2026-09-23-verified-parent-detail.md) and
[usage contract](../docs/terrain-parent-regions.md).

### Fixed-cell preparation reuse

Build the public parents above, then compare repeated requests with caching
disabled, a 128-cell eviction budget and the default 4,096-cell budget:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.detail_reuse --parent artifacts/local-detail-measurements/example-42/parent artifacts/local-detail-measurements/regional-42/parent artifacts/local-detail-measurements/water-42/parent --repeats 3 --output artifacts/detail-reuse.json
```

Parents must match current source/runtime and have at least 33 nodes on each
axis. Each sequence samples a cold window, zoom, overlap, repeat, distant window
and revisit. Variant order alternates between repetitions; every numeric array,
request record and evidence field must match, including after eviction. Cache
counts show retained cells, reuse and recomputation. Timings cover sampling only:
loading/replay, hashing and exports are excluded. No result arrays are cached.
Run serially without concurrent tests; the JSON output must be a new file outside
all parent builds. See the [report](../docs/research/2026-09-23-detail-cell-reuse.md).

### Verified session reuse

```powershell
.\.venv\Scripts\python.exe -m benchmarks.parent_session --parent artifacts/local-detail-measurements/example-42/parent artifacts/local-detail-measurements/regional-42/parent artifacts/local-detail-measurements/water-42/parent --repeats 3 --output artifacts/parent-session.json
```

Use current-runtime parents from the public builder above. This repeats cold,
zoom, overlap, repeat, distant-window and revisit writes in three variants:
independent application calls, a session retaining prepared work only, and a
session also retaining numeric results. All use experimental detail at 40 m.
Variant order alternates; every output hash and complete manifest must match
its independent control. Each write uses a fresh output directory.

Recorded time includes parent/session setup, freshness checks, numerical work,
rendering, file writes, publication and session close. Independent verification
of the benchmark outputs is outside the timed interval. Result-cache bytes and
entry counts are recorded after every write, and retained bytes must return to
zero on close. These are serial same-process observations, not fresh-process
startup comparisons or process-memory measurements. The new JSON and sibling
products directory must be outside every parent build. See the
[report](../docs/research/2026-09-23-parent-region-sessions.md).

### Regional admission and process memory

```powershell
.\.venv\Scripts\python.exe -m benchmarks.regional_memory --parent artifacts/local-detail-measurements/example-42/parent --refine 8 128 --mode reference detail --output artifacts/regional-memory.json
```

Use freshly built current-runtime parents from the public builder above. Each
parent/mode/refinement/repetition gets a fresh worker, which performs cold and
cached exports and verifies identical products/manifests. Parent building is
outside the worker. Reports distinguish baseline/process-lifetime native resident
peaks, exact unique parent numeric storage, cache bytes and policy reservations;
all reservations must release on close. `--repeats` defaults to 1. Run without
concurrent tests or other benchmarks. The new report/products paths must remain
outside each parent. This measures finite workloads, not a hard OS memory limit
or a guarantee for arbitrary native geometry. See the
[report](../docs/research/2026-09-23-regional-memory-admission.md).


Use `--window-samples WIDTH HEIGHT` for an exactly addressed core instead of
an eight-parent-cell window. The normal regional node/halo limits still apply.
For a 65-node public parent, `--refine 128 --window-samples 1409 1409` exercises
nearly two million buffered samples; `--refine 65536 --window-samples 3 262145`
and its transposed shape exercise long thin requests. Keep the complete window
inside the parent. `--memory-mib` chooses the worker's admission budget and
otherwise defaults to 1024; a larger explicit baseline budget can measure a
request that an earlier estimator rejected. The report records the requested
shape, resolved bounds and actual reservation capacity. See the
[rendering comparison](../docs/research/2026-09-23-bounded-terrain-rendering.md).


### Cached-water display and native composition

```powershell
python -m benchmarks.preview_memory --resolution 1024 4096 --mode compose water viewport --output artifacts/preview-memory.json
```

Each size/mode gets a fresh worker with three serial renders. Synthetic cached
pool-area categories exercise hidden/fading/opaque water without running terrain
or water polygonization. `compose` exports borrowed native ground, `water` renders
a native-size overlay, and `viewport` uses a fixed 1296 by 768 frame with fractional
pan/scale. Reports retain source/output pixel hashes, baseline/setup/process peaks
and per-render time; row-band hashing stays outside timing. The report path must
be new, and source/runtime drift prevents publication. Compare reports from each
revision only after verifying every source and output pixel hash matches. Run
without concurrent tests or benchmarks. This isolates display allocations and
does not measure total Tk/worker/geometry memory. See the
[measured comparison](../docs/research/2026-09-23-preview-image-ownership.md).

## Connected drainage and viewport rendering

```powershell
.\.venv\Scripts\python.exe -m benchmarks.channel_network --case example regional square --seed 42 7 --density .5 1 2 --output artifacts/channel-network-review
```

This creates a new directory with overview/zoom comparisons and a completion-last
JSON report. It checks complete edge coverage, reach connections, downstream area
hierarchy and immutable ground. Counts separate generated density from display
selection, and every sampled uphill edge remains in the review. It measures
preparation and viewport wall time without promising physical river geometry or
finer hydrology. See the [measurements](../docs/research/2026-09-24-connected-drainage-review.md).


## World water-piece connectivity

```powershell
.\.venv\Scripts\python.exe -m benchmarks.world_connectivity --output artifacts/world-connectivity.json
```

One fresh process per `--rows` value (default 90, 180, 360), with two deterministic
source-water graph constructions. The default source is public Four Shores;
`--source path/to/world.dmworld.json` accepts another retained world without edits.
Records physical area bounds, graph components, fragmented source support, array
identity/bytes, source/runtime identity and native process peaks. Timings exclude
source preparation, shore/exposure fields, rendering and serialization. Peaks
include imports and allocator retention. No full-context memory or latency bound
is inferred. See the [measured implementation](../docs/research/2026-09-25-water-piece-connectivity.md).
