# First executable landscape-evolution batch

2026-09-24. Public synthetic fixtures only; no campaign maps were read or changed.
Implements LE1 and the first LE2 comparison from the
[history plan](../strategy/landscape-evolution.md), following the
[primary-source review](2026-09-24-landscape-evolution-models.md).

## Decision

The geological-history concept is now executable and worth retaining as a
candidate. Equal integrated uplift produces different terrain when its timing
changes, and material resistance changes the response. Erosion generates related
valleys rather than merely smoothing the starting relief.

**Do not promote the current D8/bilinear result into the normal generator.**
Continuous channel profiles still rise internally, visible grid directions
persist, and the tested full landscapes do not demonstrate spatial convergence.
A small local timestep error does not bound global river-capture differences.
LE1's controlled mathematical tests pass; LE2's product-quality gate remains open.

The next bounded B/R48 batch is continuous terrain/channel reconstruction on
these frozen states and the existing generator controls, including matched
source/terminal coverage. Resolve process-grid sensitivity and sensitive captures
before full LE3 authoring/constraint integration. Keep one eventual production
path. Sediment, history editor controls, climate/deserts and zoom jobs do not
precede that gate. This result does not require a Python-to-Rust rewrite.

## Delivered implementation

- Dependency-light `EvolutionGrid`, `EvolutionEpoch`, `EvolutionHistory` and
  `EvolutionBudget` types with explicit units and bounded inputs.
- One named initial-noise field, metric uplift/resistance/runoff fields and exact
  epoch endpoints; initial fields agree at shared coordinates across grids.
- An optional Landlab adapter for uplift, rerouting, implicit `n=1` incision and
  conservative hillslope flux. Full-versus-two-half-step comparison, rollback,
  dry/flooded protection, finite/fixed-boundary checks and bounded work are real
  executable behavior, not just plan items.
- A research command with fresh worker processes, numeric state/field hashes,
  source/runtime identity checks, water and material ledgers, Float32 rerouting,
  peak resident memory, stage costs, completion-last results and partial reports.
- Current-generator, constant-forcing, reversed-history, uplift-only,
  diffusion-only, incision-only and uniform-rock controls. Local HTML, paired
  PNGs, epoch snapshots, longitudinal profiles and downloadable numeric states.
- A hash-pinned, isolated 53-wheel environment. Application dependencies, saved
  project schemas, normal terrain generation and the editor are unchanged.

The [command guide](../../benchmarks/evolution/README.md) owns setup, exact model
parameters and reproducible commands. Implementation lives in
[`benchmarks/evolution/`](../../benchmarks/evolution/README.md), with
[domain inputs](../../src/map_maker/terrain/domain/evolution.py) and
[numerical tests](../../tests/test_evolution_reference.py).

## Frozen experiment and provenance

The public rectangle is 80 x 60 km. Fixed zero perimeter nodes own no control
area: the 129 x 97 grid at 625 m has 4,712.890625 km2 of contributing area.
A 25-degree oblique uplift belt receives 2 Myr at 0.5 mm/year and then 4 Myr at
0.05 mm/year, multiplied by its spatial taper. Effective runoff is 0.4 m/year;
`Ke=0.001 m/year`, `Qref=1,000,000 m3/year`, discharge exponent 0.5 and slope
exponent 1. Resistance varies smoothly from 1 to 4. Hillslope diffusivity is
0.05 m2/year. The maximum trial step is 25,000 years; the local height-difference
criterion is 0.5 m. Parameters were not tuned after viewing held-out seed 20260902.

Constant forcing integrates the same uplift and runoff; reversed history uses
exactly the same two epochs in reverse order. All these cases share initial
fields. The current generator instead receives a present-day 1,300 m ridge and
120 m plain with 120 m relief; its complete inputs are recorded. It is a visual
reference, not equal physical forcing or a matched automatic-channel cohort.

All figures use a common height range within each report, physical-spacing
hillshade and the same extent. Blue terrain tint denotes low elevation, not
water. Raw working elevations are Float64; delivered DEM samples are Float32.
The report's bilinear sampler is deliberately explicit and is not the accepted
project reconstruction. Final metrics reroute the quantized DEM. Channels use a
fixed 25 km2 contributing-area threshold and 17 finite profile stations per edge.

Measured source identities (before the local implementation commit):

```text
package_source_sha256:
ca0d8870258c393f2d37f6aba8d01291e246c35eb472c71d5ef0155bfed66b34
benchmark_source_sha256:
a42a0a8fb2631a16c8c3116bdcc1099c786c48d2a3ed6e2fd5e4f4b705b30893
```

The complete package/runtime inventories are inside each result. Local hardware:
AMD Ryzen 7 9800X3D, 8 cores / 16 logical processors, about 31.1 GiB OS-reported
physical memory, Windows x86-64, CPython 3.14.7. Runs were dispatched serially.
Timings are observations on this machine, not portable guarantees.

Ignored output directories are `artifacts/evolution-cohort-20260924/`,
`evolution-ablations-20260924/`, `evolution-spacing-20260924/`,
`evolution-rotated-20260924/`, `evolution-extent-20260924/`,
`evolution-repeat-20260924/` and `evolution-timestep-20260924/`, all under
`artifacts/`. The small control report is `artifacts/evolution-controls-20260924.json`.
Earlier smoke directories are exploratory, not this frozen cohort's evidence.
The frozen cohort produced 22 completed workers and one correctly stopped
worker. All 22 share one package/benchmark source identity and exactly balance
their reported final outlet discharge. Generated terrain/report files are not
committed; commands and concise measurements below are the durable record.

## Numerical evidence

The 25 new tests pass in the isolated environment. They check zero forcing,
exact uplift/epoch boundaries, one-link implicit incision, doubled runoff,
zero-runoff `m=0`, conservative diffusion with multiple stable substeps,
depression routing without changing ground, spatial runoff at physical scale,
rejected-trial rollback, deterministic output, a steady slope-area channel,
knickpoint refinement, input ownership, shared-coordinate sampling, invalid
histories/grids/receiver cycles and failure/overwrite behavior.

For `z_t = U - v*z_x`, `v=1 m/year`, `U=0.01 m/year`, over 2,000 years, the
steady profile has zero measured mean error. A 200 m initial step at x=6 km
moves upstream; mean absolute errors shrink under both refinements:

| Control | Coarse | Middle | Fine |
|---|---:|---:|---:|
| Spatial: dx 200 / 100 / 50 m, dt 5 years | 8.587 m | 6.120 m | 4.420 m |
| Temporal: dt 100 / 50 / 25 years, dx 50 m | 7.279 m | 5.953 m | 5.159 m |

This establishes component behavior on a fixed one-dimensional channel, not
whole-landscape convergence. No timing threshold is encoded as a unit test.

For seed 42 at 625 m, total uplift is 1.202152e12 m3, incision export is
8.002031e11 m3 and hillslope boundary export is 2.289859e7 m3. The Float64 volume
residual is -0.000427 m3, about 2.13e-16 of the imposed/export throughput.
Initial/final storage and each flux are retained separately. All completed
cohort histories have relative residual below 5.4e-16. This is bulk surface
volume with export-only incision, not mobile-sediment mass or lake storage.
Outlet discharge balances effective runoff under the declared control-area policy.
Maximum Float32 quantization change in the seed-42 candidate is about 0.000061 m;
that does not explain its much larger between-node profile failures.

A separate fresh-process repeat of seed 42 at 625 m matches **all recorded
numeric array hashes**, including snapshots and flow products, with identical
source/runtime identity. NPZ container bytes are not the repeatability assertion.

## Chronology and material response

Seed 42, 625 m; mean elevations are over contributing interior nodes:

| Case | Final mean height | Final maximum | Incision exported |
|---|---:|---:|---:|
| Active then waning uplift | 156.08 m | 1,319.62 m | 800.20 km3 |
| Matched constant forcing | 196.02 m | 1,337.09 m | 612.00 km3 |
| Waning then active uplift | 239.01 m | 1,351.21 m | 409.40 km3 |
| Uplift only | 325.88 m | 1,374.22 m | 0 |
| Uplift + diffusion only | 325.83 m | 1,367.69 m | 0 |
| Uplift + incision only | 138.56 m | 1,332.01 m | 882.82 km3 |
| Uniform weak rock, both processes | 134.02 m | 1,191.25 m | 904.19 km3 |

The constant and reversed results differ from the two-epoch result by 40.41 m
and 82.98 m mean absolute height respectively, despite identical total forcing.
Removing resistant rock increases incision; removing incision leaves a broad
smooth belt. This demonstrates a process/history response on the fixed
experiment. It does not calibrate geological ages or prove realistic morphology.

## Resource and quality measurements

| Run | Solver time | Accepted steps | Fresh-worker peak |
|---|---:|---:|---:|
| Two epochs, seed 42, 625 m, first cohort run | 42.87 s | 495 | 246.8 MiB |
| Exact repeat of that run | 10.61 s | 495 | 247.6 MiB |
| Two epochs, seed 7, 625 m | 11.57 s | 519 | 246.7 MiB |
| Two epochs, held-out seed 20260902, 625 m | 11.46 s | 535 | 247.5 MiB |
| Two epochs, seed 42, 312.5 m / 49,601 nodes | 45.16 s | 671 | 329.8 MiB |
| Two epochs, seed 42, 156.25 m / 197,505 nodes | **Stopped at 60 s solver budget** | no accepted final history | no completed result |

The first seed-42 timing was a substantial outlier despite identical numeric
output; do not silently discard it or claim a universal 11-second run. Full
worker times include startup and measurement (46.80 s for the 312.5 m run);
figures render later in the parent. Native allocations and scientific imports
are included in peak resident memory. The 156.25 m attempt left `failure.json`
and an `incomplete.json` matrix, with no final `result.json` for that history.
The existing 60-second ceiling was respected rather than raised to finish it.

A 70-degree rotation of seed 7 completed in 13.39 s and a 160 x 120 km extent
at 1,250 m completed in 16.10 s. Those probe orientation/extent behavior; they
are not evidence that continental-scale performance or grid invariance is solved.

The two-epoch 625 m cases have channel density 0.1211 / 0.1214 / 0.1285 km/km2
for seeds 42 / 7 / 20260902, respectively. All contributing nodes reach the
perimeter, with no final depression depth on those cases. Nevertheless:

| Case | Largest sampled internal rise on an endpoint-descending edge |
|---|---:|
| Two epochs, seed 42, 625 m | 37.51 m |
| Two epochs, seed 7, 625 m | 41.66 m |
| Two epochs, held-out seed, 625 m | 45.48 m |
| Two epochs, seed 42, 312.5 m | 24.64 m |

The seed-42 failures occur on diagonal bilinear paths; cardinal descending
profiles have no sampled rise. The common-routing current-generator reference
has 8.68-12.84 m maxima in this separate synthetic cohort. These networks differ:
neither this comparison nor the reduced longest-straight-run values establishes
a matched-route percentage improvement. D8 direction bins and worst-edge IDs
are preserved for inspection. Figures still show directional grooves and an
oversimplified continuous uplift crest. Peak/pass topology is not yet scored.

## Sensitivity and remaining gate

Shared-coordinate comparison of final Float32 elevations (interior nodes):

| Comparison | Mean absolute difference | RMS difference | Maximum difference |
|---|---:|---:|---:|
| 1,250 m versus 625 m process spacing | 42.68 m | 83.20 m | 584.97 m |
| 625 m versus 312.5 m process spacing | 52.46 m | 92.91 m | 562.03 m |
| 625 m: dt cap 25,000/error 0.5 versus cap 12,500/error 0.25 | 0.41 m | 2.36 m | 113.81 m |

Initial/material fields agree exactly at shared coordinates. Final terrain does
not, and the spatial differences do not shrink in this test. Temporal mean
sensitivity is much smaller but its localized maximum remains important; inspect
receiver/outlet changes before treating it as acceptable capture behavior.
The 0.5 m local full/half-step criterion is not a bound on the final map error.
Do not describe the ~50,000-node run as a converged terrain model.

Required follow-up, recorded in the primary strategy and TODO:

1. A continuous terrain/channel reconstruction comparison with actual ground
   profiles and fixed source/terminal coverage, including oblique and flat controls.
2. Resolution-sensitive channel/valley representation and capture analysis;
   fix a physical process policy before simply spending more on finer grids.
3. Peak/pass/divide structure and harder seeds/extents after the first two gates.
4. Only then full authoring constraints, real multipart coast and basin semantics,
   prepared-state integration and an explicit production implementation decision.

## Implementation findings

The initial Landlab `PriorityFloodFlowRouter` D8 path spent most of its time in
per-node Python work. Five warm routes on the initial public fixture averaged
about 82 ms at 625 m and 348 ms at 312.5 m. `FlowAccumulator` with
`DepressionFinderAndRouter` measured about 6.2 ms and 16.7 ms, respectively,
before our precision correction. Those are router probes, not equal whole-run
output comparisons or a general speedup claim. The selected router does not
mutate depression ground; flooded nodes are excluded from incision.

A physical-scale runoff test found Landlab 2.11.0's discharge accumulation uses
a C `float` temporary even with Float64 output. One initial fixture differed by
8 m3/year from the 1,850,625,000 m3/year input total. The adapter now uses the
same public function's Float64 additive-area branch for volumetric source
weights, then supplies the corrected discharge to incision. A nonuniform-runoff
regression validates the correction at 1e-14 relative tolerance. Installed
third-party sources are unmodified. See the pinned package's
`landlab/components/flow_accum/cfuncs.pyx` and `flow_accum_bw.py`.

The selected primitives are the existing
[Fastscape incision component](https://landlab.csdms.io/generated/api/landlab.components.stream_power.fastscape_stream_power.html)
and [LinearDiffuser](https://landlab.csdms.io/generated/api/landlab.components.diffusion.diffusion.html).
Their equations, assumptions and alternative models are discussed in the earlier
primary-source review; this report adds local execution evidence.

## Validation boundary

Focused reference and domain tests pass (25). The base application environment
intentionally skips the optional reference-test module when Landlab is absent;
that skip is complemented by the explicit isolated-environment run above.
Repository-wide pytest passes: **1,266 passed, 1 optional module skipped**, in
406.08 seconds. Ruff and strict Pyright pass. All 53 installed reference versions
match the wheel lock; `pip check` reports no broken requirements. Updated local
document links and `git diff --check` pass. The paired comparison and finer epoch
figures were inspected. No new desktop UI or private map generation was exercised
because this batch adds no application history UI.
