# Attainable channel-floor profiles

Date: 2026-09-17. Baseline: `79ceeff`. Implemented decision:
[ADR-0055](../adr/0055-prepare-attainable-channel-floor-profiles.md).

## Diagnosis

The preceding crest refinement selected a new regional seed-7 segment,
9958 -> 9702, with an 85.47 m rise at 1025 stations. A denser 4097-station probe
finds 85.77 m. Its upstream/downstream delivered heights are 2276.182617 and
1981.070190 m. The rise begins in a dip at t=0.171143 and reaches a crest at
t=0.379639. Both the dip and crest already use their local cut ceilings:
115.438096 and 109.851573 m respectively.

The observed crest's uncut source is 2436.959848 m. Its deepest permitted floor
is therefore about 2327.108275 m, still 50.93 m above the fixed upstream node.
An everywhere-descending floor is impossible for these sampled constraints.
Fitting a straight line more strongly would deepen the preceding dip: fully
clamping to that line produces a 94.25 m sampled climb. Removing the avoidable
dip, rather than increasing cut allowances, is the bounded improvement here.

## Implementation

Prepare 17 source/ceiling observations per eligible segment, carry downstream
minimum floors upstream and unfillable source limits downstream, and constrain
the original linear target with both envelopes. Store only changed targets in
sparse immutable rows and use range-bounded cubic interpolation. The existing
corridor weights, endpoint tapers, overlap rules and final local cut clipping
remain. The shared PCHIP slope kernel retains its existing arithmetic.

Unavailable sea/retention stations omit the complete profile; invalid land
samples fail. Source profiles use the same macro and retained detail as pointwise
evaluation before authored constraints. Canonical samples, routing, nodal cuts,
cut ceilings, suppression and input authority remain unchanged. Generator and
valley IDs become `coastline-constraint-terrain@14` and
`regional-budget-mfd-d8-valleys@12`.

On the diagnosed segment, the dense sampled rise falls from **85.77 to 50.93 m**.
The trough is now its fixed upstream endpoint, and the crest remains at the same
position and permitted floor. This reaches the observed lower limit to Float32
rounding; it is not a continuous clearance proof or a repaired descending river.

## Paired measurements

The maintained `benchmarks.channel_profiles` harness sampled five regional
seeds at 257 stations per selected segment and eight other fixture/seed pairs
at 65 stations. Both versions used identical public inputs and the same harness.
All 13 canonical-product hash sets, descending-edge populations and nonfinite
profile counts match between versions.

The tables cover finite segments whose delivered upstream endpoint is more than
0.01 m above the downstream endpoint. Each segment's excursion is its largest
rise above a preceding sampled minimum; means include zero-excursion segments.
"Uphill" counts excursions greater than 0.01 m. These finite, within-segment
measurements do not include every network failure or prove whole-route descent.
All height columns are metres and show before -> after.

### Regional profiles, 257 stations

| Seed | Segments | Uphill | Mean | 95th percentile | Maximum |
|---|---:|---:|---:|---:|---:|
| 7 | 2203 | 579 -> 579 | 0.869 -> 0.837 | 4.479 -> 4.424 | 85.148 -> 53.030 |
| 42 | 2400 | 494 -> 494 | 0.707 -> 0.683 | 3.551 -> 3.456 | 58.998 -> 58.998 |
| 20260902 | 2410 | 595 -> 595 | 0.855 -> 0.837 | 3.832 -> 3.832 | 58.359 -> 58.359 |
| 104729 | 2598 | 571 -> 570 | 0.655 -> 0.650 | 3.345 -> 3.254 | 54.261 -> 54.261 |
| 3001 | 3130 | 826 -> 826 | 0.888 -> 0.864 | 3.201 -> 3.126 | 64.900 -> 64.900 |

The seed-7 matrix maximum now belongs to a different edge. Its diagnosed
9958 -> 9702 edge measures 50.57 m at 257 stations and 50.93 m at 4097 stations;
this difference is why the denser diagnosis is retained separately.

### Other public profiles, 65 stations

| Case / seed | Segments | Uphill | Mean | 95th percentile | Maximum |
|---|---:|---:|---:|---:|---:|
| example / 42 | 2040 | 452 -> 452 | 0.909 -> 0.901 | 4.816 -> 4.707 | 67.772 -> 67.772 |
| example / 20260902 | 2010 | 524 -> 524 | 1.113 -> 1.111 | 6.034 -> 6.034 | 72.163 -> 72.163 |
| authored / 42 | 2052 | 747 -> 747 | 1.451 -> 1.449 | 7.785 -> 7.722 | 62.879 -> 62.879 |
| authored / 20260902 | 2444 | 723 -> 723 | 1.086 -> 1.084 | 6.207 -> 6.207 | 57.149 -> 57.226 |
| outlet / 42 | 1245 | 153 -> 153 | 0.275 -> 0.274 | 1.275 -> 1.252 | 45.089 -> 45.089 |
| outlet / 20260902 | 1130 | 174 -> 174 | 0.384 -> 0.384 | 2.553 -> 2.553 | 42.686 -> 42.686 |
| archipelago / 42 | 1114 | 265 -> 264 | 1.088 -> 1.066 | 6.074 -> 5.918 | 61.713 -> 61.713 |
| archipelago / 20260902 | 1329 | 304 -> 304 | 0.843 -> 0.843 | 5.332 -> 5.332 | 39.298 -> 39.298 |

Mean excursion improves in 12 of 13 pairs, including all five regional seeds.
Most uphill counts and worst climbs remain unchanged. Outlet / 20260902 has a
small mean regression, 0.383731 -> 0.383915 m; authored / 20260902 has a maximum
regression, 57.148926 -> 57.226074 m. Individual subsets can also worsen: the
archipelago / 20260902 diagonal 95th percentile rises 9.323 -> 10.060 m. Local
target guidance with corridor blending is not a per-segment improvement guarantee.

Both archipelago seeds retain three nonfinite profiles, excluded from the finite
statistics; every other case has zero. The all-finite maxima, which include
upward endpoint pairs, remain unchanged across all 13 cases. Large unresolved
network climbs therefore remain despite the improvement on descending pairs.

### Fresh-process cost and numeric products

The maintained `benchmarks.terrain` harness ran the example, regional, authored,
outlet and archipelago fixtures at 513 px, seeds 42 and 20260902, with three
fresh-process repeats per version: 60 runs total. No test suite or other terrain
workload ran concurrently. Baseline source came from
`git archive 79ceeff src/map_maker` and was selected in a separate process through
`PYTHONPATH`; the new source stayed frozen during measurement. The harness checks repeat hashes
and records source/runtime identities. File export is excluded from timing.

Runtime: CPython 3.14.7 on Windows 11 AMD64, NumPy 2.5.2, Shapely 2.1.2 /
GEOS 3.13.1. The complete dependency identity is retained in each artifact.
Generation wall times below are median (minimum-maximum) seconds. Peak change
is the difference between median process lifetime peak resident memory values
at generation completion, including imports, in MiB; it is not isolated profile
storage or a portable allocation bound.

| Case / seed | Before, s | After, s | Median change | Peak change, MiB |
|---|---:|---:|---:|---:|
| example / 42 | 0.773 (0.769-0.792) | 0.852 (0.846-0.858) | +10.1% | +1.37 |
| example / 20260902 | 0.775 (0.771-0.776) | 0.861 (0.853-0.862) | +11.1% | +1.05 |
| regional / 42 | 1.062 (1.060-1.066) | 1.247 (1.219-1.269) | +17.4% | +1.82 |
| regional / 20260902 | 1.064 (1.057-1.065) | 1.295 (1.287-1.306) | +21.7% | +1.59 |
| authored / 42 | 1.307 (1.302-1.324) | 1.437 (1.345-1.442) | +9.9% | +1.17 |
| authored / 20260902 | 1.313 (1.309-1.317) | 1.478 (1.399-1.552) | +12.5% | +1.41 |
| outlet / 42 | 2.559 (2.547-2.565) | 2.664 (2.635-2.879) | +4.1% | +1.28 |
| outlet / 20260902 | 2.559 (2.553-2.619) | 2.655 (2.637-2.696) | +3.8% | +0.66 |
| archipelago / 42 | 1.477 (1.465-1.483) | 1.600 (1.584-1.635) | +8.3% | -0.67 |
| archipelago / 20260902 | 1.477 (1.468-1.489) | 1.636 (1.623-1.638) | +10.7% | +0.77 |

The observed generation cost increases by approximately 0.08-0.23 s, or 4-22%.
Timing ranges are disjoint for each paired case, but these are sequential local
measurements, not confidence intervals or a general performance guarantee.
Many-region and larger process-grid scaling remain unmeasured for this increment.
Preparation queries at most 4352 source positions per batch (256 edges x 17),
while the sparse profile table and four edge-ID grids persist for evaluation.

Only `elevation` changes among the 27 hashed numeric products in each full-build
pair; the other 26 are identical. The complete `drainage`, `routing_agreement`,
`channel_conflicts`, `authored_water` and `basin_outflow` summaries also match.
These unchanged canonical summaries are not evidence of repaired between-node
rivers; the separate profile measurements above evaluate that boundary.

### Public visual review

Generated before/after colour relief for regional seeds 7 and 42 at 1025 px
(607 x 1025 samples). Inspected seed 7 at full size and in a detail crop. Large
landforms remain similar, with local changes to channel dips and shading; D8
bends, scalloping and the mountain recipe's repeating lobes remain visible.
This was a static render review, not a GUI workflow or user acceptance test.

The finite masks are identical. Seed 7 changes 672 samples, with RMS elevation
difference 0.161 m and maximum absolute difference 61.865 m; seed 42 changes
614 samples, with RMS 0.122 m and maximum 17.332 m. These whole-raster summaries
include unchanged land and should not be mistaken for local improvement scores.

## Validation and remaining work

The full repository suite passed: **839 tests in 238.88 s**, including 19 new
cases covering attainable/conflicting envelopes, all eight D8 directions,
source/cut limits, fixed pins, invalid/unavailable samples, immutable sparse
storage, cubic bounds and derivatives, query order, batching, canonical ground
and the dense seed-7 regression. Repository-wide Ruff and strict Pyright passed.
All 588 local Markdown file targets resolve, and `git diff --check` is clean.

Evidence lives under ignored
`artifacts/channel-continuity-2026-09-17/`, including the baseline source archive,
dense diagnosis, public profiles, performance reports and previews. No private
map or authored source was changed.

Seventeen observations can miss narrow detail. Feasibility of sampled targets
does not prove feasibility of the completed field after clipping, tapers,
intersecting corridors or authored constraints. Segment guidance stops at fixed
canonical pins. The next route-level work must compare alternative paths or
reviewable pin changes within existing budgets, together with retention and
whole-network semantics. Turn smoothing and variable physical valley widths
also remain open.
