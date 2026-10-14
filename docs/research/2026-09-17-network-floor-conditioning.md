# Network-wide channel-floor conditioning

Date: 2026-09-17. Baseline: `a55c9cd`. Implemented decision:
[ADR-0056](../adr/0056-condition-network-floors-in-both-directions.md).

## Diagnosis and scope

The previous segment-floor work removed avoidable dips between fixed canonical
nodes. Its known seed-7 crest still requires approximately 50.93 m of rise with
those fixed pins and cuts. At its source, undoing all 34.14 m of automatic cut
would raise ground only to 2310.33 m, below the sampled 2327.11 m minimum crest.
That particular obstruction still needs another route or different path-wide
constraints; an upstream cut release alone cannot solve it.

A separate, wider defect is unnecessary nodal excavation before a downstream
cut-limited node. The old correction deepened receivers without considering
whether upstream cuts should be shallower. A public prototype found that
propagating the downstream floor requirements through the complete network
reduces large climbs without changing routes or granting more excavation.

## Implemented nodal rule

For each selected node, S is its source including retained detail, C its existing
cut ceiling, and I its preferred cut. The admissible floor interval is [S-C, S].
In reverse receiver order compute R[i] = max(S[i]-C[i], R[j]+0.01) for i -> j.
Raise preferred floors toward R, capped at S. Traverse upstream to downstream,
lowering receivers as needed for the incoming floors, but never below S-C.
Every incoming branch is processed before a confluence continues downstream.

If R <= S everywhere, this produces a descending nodal solution. In that case
an upstream floor is at least its R, so lowering its receiver to at most that
floor minus the drop still leaves the receiver at least its own R. The same
argument holds for every tributary. If R > S, the source and cut limits win and
the unresolved edge count remains explicit. This is a finite graph feasibility
argument, not an optimal excavation objective or a full-terrain certificate.

No receivers, accumulation, local ceilings, detail suppression or authored
inputs change. Generated cuts and canonical ground may change. Existing
steepness correction follows; the internal floor-correction array now reports
signed net incision change, so recovered cuts are not mislabeled as extra cuts.
Generator/valley identities advance to @15/@13; public schemas and seeds stay.

## Dense public comparison

Run the maintained `benchmarks.channel_profiles` harness against the archived
baseline and final implementation, using 257 stations per selected edge for
regional seeds 7, 42, 20260902, 104729 and 3001, and example/authored/outlet/
archipelago seeds 42 and 20260902. Reports use schema version 2 with severity
counts. Inputs, fixture and harness hashes match. Only incision changes among
the seven canonical hash entries; receivers, channel selection, ceilings,
suppression and axes match exactly in all 13 pairs.

Both versions select the same 28,541 edges. Six profiles remain nonfinite
(three per archipelago seed), so the table compares the same **28,535 finite
segments**, including segments whose endpoints climb. Excursion is the largest
sampled rise above a preceding minimum, with Float32 ground promoted to Float64
before subtraction. Height columns are metres; entries show before -> after.

| Case / seed | Finite segments | Mean | 95th percentile | Maximum | Above 10 m | Above 50 m |
|---|---:|---:|---:|---:|---:|---:|
| regional / 7 | 2368 | 2.338 -> 2.010 | 9.810 -> 7.884 | 149.827 -> 149.827 | 118 -> 99 | 25 -> 20 |
| regional / 42 | 2585 | 3.091 -> 2.671 | 11.124 -> 8.588 | 171.500 -> 152.632 | 142 -> 118 | 59 -> 49 |
| regional / 20260902 | 2706 | 3.159 -> 2.699 | 16.464 -> 11.200 | 315.327 -> 315.327 | 168 -> 144 | 43 -> 36 |
| regional / 104729 | 2811 | 2.457 -> 2.059 | 10.913 -> 7.979 | 97.253 -> 97.253 | 150 -> 117 | 47 -> 36 |
| regional / 3001 | 3616 | 3.900 -> 3.689 | 28.151 -> 25.687 | 152.991 -> 152.991 | 320 -> 299 | 87 -> 79 |
| example / 42 | 2115 | 2.641 -> 2.193 | 8.646 -> 7.306 | 128.505 -> 115.506 | 98 -> 78 | 37 -> 32 |
| example / 20260902 | 2077 | 2.540 -> 2.146 | 9.896 -> 8.783 | 137.398 -> 124.729 | 103 -> 88 | 38 -> 27 |
| authored / 42 | 2455 | 4.857 -> 4.451 | 33.147 -> 27.595 | 135.067 -> 135.067 | 270 -> 246 | 69 -> 58 |
| authored / 20260902 | 2861 | 3.741 -> 3.218 | 21.630 -> 15.581 | 119.838 -> 109.739 | 241 -> 217 | 61 -> 43 |
| outlet / 42 | 1273 | 0.638 -> 0.426 | 1.765 -> 1.765 | 81.653 -> 49.796 | 18 -> 9 | 2 -> 0 |
| outlet / 20260902 | 1197 | 0.713 -> 0.629 | 3.165 -> 2.863 | 95.091 -> 76.594 | 11 -> 11 | 3 -> 1 |
| archipelago / 42 | 1127 | 1.441 -> 1.241 | 6.873 -> 6.085 | 106.696 -> 61.713 | 41 -> 37 | 6 -> 2 |
| archipelago / 20260902 | 1344 | 1.260 -> 1.070 | 6.733 -> 6.672 | 96.114 -> 63.210 | 36 -> 31 | 5 -> 3 |

Mean excursion falls in all 13 cases, by 5.4-33.1%. Counts above 10 m decrease
in 12 cases and tie in the other; each case's all-finite maximum improves or ties.
Across the same finite population:

| Excursion strictly above | Before | After |
|---|---:|---:|
| 0.01 m | 8,839 | 9,025 |
| 1 m | 5,400 | 5,507 |
| 10 m | 1,716 | 1,494 |
| 50 m | 482 | 386 |
| 100 m | 63 | 46 |

This is a severity tradeoff, not an unconditional improvement. The dense paired
prototype found individual increases as large as 16.557 m and 27 previously
smaller segments newly above 10 m. The mean of the descending-endpoint subset
increases in every case, although that subset also changes membership as nodes
move. For example, its maximum rises 45.094 -> 49.796 m for outlet / 42 and
39.305 -> 52.049 m for archipelago / 20260902. Do not substitute that changing
subset for a matched population, or hide the individual regressions behind the
all-finite average.

Nodal unresolved edges in the prototype fall from 1,427 to 1,115. Every prototype
Float32 profile hash matches its corresponding final source-isolated run, on
both sides of the comparison. The known seed-7 between-node obstruction remains;
this increment solves a different source of network failure. The largest overall
sampled rise is still 315.33 m, and no continuous descent is certified.

## Runtime and delivered products

The maintained `benchmarks.terrain` harness ran five public cases at 513 px,
seeds 42 and 20260902, three fresh-process repeats per version: 60 runs. Baseline
source was extracted with `git archive a55c9cd src/map_maker` and selected through
`PYTHONPATH` in separate processes. Sources stayed fixed throughout measurement;
no tests or other terrain workload ran during timing. File export is excluded.
Runtime was CPython 3.14.7 / Windows 11 AMD64; reports retain full source,
benchmark and dependency identities. Repeats reproduce their output hashes.

Times are generation wall-time median (minimum-maximum) seconds. Peak change is
the difference between median process lifetime peak resident bytes at generation
completion, including imports, converted to MiB; it is not isolated allocation.

| Case / seed | Before, s | After, s | Median change | Peak change, MiB |
|---|---:|---:|---:|---:|
| example / 42 | 1.097 (1.060-1.233) | 0.987 (0.960-1.008) | -10.0% | +0.07 |
| example / 20260902 | 1.088 (1.029-1.238) | 1.049 (0.952-1.055) | -3.5% | -0.07 |
| regional / 42 | 1.434 (1.291-1.445) | 1.506 (1.416-1.513) | +5.0% | +0.19 |
| regional / 20260902 | 1.389 (1.348-1.447) | 1.478 (1.464-1.578) | +6.4% | +0.82 |
| authored / 42 | 1.856 (1.721-1.932) | 1.695 (1.685-1.797) | -8.7% | +0.28 |
| authored / 20260902 | 1.732 (1.666-1.805) | 1.688 (1.651-1.769) | -2.5% | +0.19 |
| outlet / 42 | 3.360 (3.208-3.967) | 3.500 (3.378-3.676) | +4.2% | +0.34 |
| outlet / 20260902 | 3.135 (3.079-3.333) | 3.692 (3.390-3.696) | +17.8% | -1.39 |
| archipelago / 42 | 1.931 (1.853-2.023) | 1.882 (1.755-1.937) | -2.5% | -0.31 |
| archipelago / 20260902 | 1.848 (1.847-1.902) | 1.718 (1.674-1.724) | -7.0% | +0.52 |

Several ranges overlap, and the apparent regressions were checked separately:
regional and outlet seed 20260902 ran in before/after/after/before order, two
fresh-process repeats per case in each block (16 additional runs). Regional
medians were 1.240 -> 1.235 s, with ranges 1.191-1.291 / 1.219-1.281; outlet
medians were 2.739 -> 2.684 s, with ranges 2.577-2.918 / 2.591-2.860. The earlier
regional +6.4% and outlet +17.8% slowdowns did not reproduce. These overlapping
local observations support neither a speedup claim nor a material isolated
runtime regression. Large projects and many-region scaling were not measured.

Six of 27 hashed numeric products change in every main pair: delivered elevation,
canonical final elevation, canonical incision, conditioned-final receivers,
final basin labels and channel-conflict flags. The other 21 hashes match. The
complete authored-water and basin-outflow summaries match for every pair;
final-ground drainage/routing/conflict summaries change as expected. Canonical
planned routing remains fixed, while drainage derived from changed ground need
not match. Repeatability is checked within each implementation, not across the
intentional terrain change.

## Public visual review

Generated regional seeds 7 and 42 at 1025 px (607 x 1025 arrays); inspected the
seed-42 full renders and seed-7 detail crops before/after. Most broad landforms
look similar. Some local trenches become shallower, while straight D8 turns,
scalloping and repeating mountain lobes remain conspicuous. This is a numeric
network correction, not a finished visual-quality or physical-river milestone.
No interactive editor or private-map acceptance was performed.

Finite masks match. Seed 7 changes 29,350 samples, with whole-finite-raster RMS
2.282 m and maximum absolute difference 83.767 m. Seed 42 changes 32,835 samples,
with RMS 3.842 m and maximum 93.162 m. These differences include unchanged land
and measure the extent of the change, not its local correctness.

## Research direction

[Lindsay (2016)](https://jblindsay.github.io/ghrg/pubs/Lindsay-HP-preprint.pdf)
compares filling, breaching and hybrid approaches, including constrained breach
depth and length. [Cordonnier et al. (2019)](https://esurf.copernicus.org/articles/7/549/2019/esurf-7-549-2019.html)
construct a graph between drainage basins to route through depressions. These
remain references for full-path alternatives, not adopted implementations or
new dependencies. Our constraint-driven generator must also preserve intentional
retention areas and authored anchors; automatically removing every depression
would contradict that contract.

The next comparison should evaluate complete candidate paths against source
upper bounds, excavation depth and length, observed interior crests and retained
basins. The nodal rule here does not search paths. Couple nodal decisions to
between-node evidence and corridor reconstruction before claiming physical
rivers. Use the same finite populations, severity thresholds and nonfinite counts
when comparing proposals; a better nodal count alone is insufficient.

## Validation and remaining boundaries

The full suite passed: **861 tests in 228.55 s**, including 22 new cases covering
network feasibility, confluences, source/cut bounds, fixed terminals, ownership,
malformed graphs and strict severity thresholds. Repository-wide Ruff and strict
Pyright pass. All 598 local Markdown file targets resolve and `git diff --check`
is clean. The 4097-station seed-7 recheck retains the 50.925537 m obstruction and
unchanged delivered endpoints, confirming that it remains separate work.

Evidence is retained under ignored
`artifacts/network-floors-2026-09-17/`: baseline source archive, prototypes,
dense profiles, fresh-process benchmarks and public previews. No private map
or user-authored source was modified.
