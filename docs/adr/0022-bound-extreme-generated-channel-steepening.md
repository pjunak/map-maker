# ADR-0022: Bound extreme generated-channel steepening

**Status:** Accepted
**Date:** 2026-09-04
**Deciders:** Project owner and Map Maker maintainers

## Context

ADR-0020 guarantees that selected generated channel floors descend toward an
outlet. A descending profile can still contain an artificial knickpoint: a
nearly flat edge followed immediately by an extremely steep edge. The default
Tharkeniss canonical field had a compact tail of these transitions. Ninety-five
percent of channel triples had a downstream normalized-steepness ratio below
1.88, while nine exceeded 8 and the largest exceeded 5,000 because a 0.01 m
minimum-drop edge was followed by a much steeper reach.

The stream-power slope-area relation commonly expresses normalized channel
steepness as `S * A^theta`, where `S` is channel slope, `A` is contributing
area, and `theta` is a reference concavity. It is useful for finding abrupt
profile changes, but it is not a universal truth: lithology, uplift, climate,
waterfalls, and transient erosion can produce real knickpoints.

## Decision

- Apply profile conditioning only to generated D8 channels, after retained
  detail and monotonic floor conditioning have been assembled. Do not modify
  authored ridges, valleys, height points, water features, or constraints.
- For each consecutive pair of channel edges, compare downstream and upstream
  normalized steepness using reference concavity `theta = 0.45`.
- Treat a downstream-to-upstream ratio of at most 8 as acceptable. This removes
  only the extreme measured tail rather than forcing every generated channel
  toward a fitted equilibrium profile.
- When the ratio exceeds 8, lower only the middle cell to the exact limiting
  elevation. This simultaneously steepens the upstream edge and relaxes the
  downstream edge without raising terrain or changing channel topology.
- Traverse channel cells upstream to downstream in stable routing order and
  repeat for at most 16 fixed passes. Stop early when no cell changes.
- Reuse the existing maximum-incision raster from ADR-0020. If the required cut
  exceeds that conservative limit, retain the bound and report the unresolved
  ratio rather than cutting without limit.
- Record the steepness-only correction raster, remaining excessive-ratio count,
  and maximum final ratio in the internal `DrainageIncision` result. Keep the
  existing floor-correction raster as the total of monotonic and steepness
  corrections.

## Options Considered

| Option | Scientific behavior | Terrain disturbance | Decision |
|---|---|---|---|
| Leave every descending profile unchanged | Preserves all possible knickpoints | None, including obvious numerical artifacts | Rejected |
| Smooth channel elevations or slopes globally | Produces visually regular profiles | Can erase meaningful structure and violate bounds | Rejected |
| Fit every channel in chi space | Strong equilibrium-style profile model | Assumes uniform process parameters not yet authored | Deferred |
| Bound only extreme local normalized-steepness ratios | Removes measured artifacts and preserves ordinary variation | Thirteen small canonical cuts on Tharkeniss | Accepted |

## Trade-off Analysis

The ratio threshold is intentionally permissive. A stricter value would make
generated channels smoother, but would also encode an unjustified uniform
geology and uplift history. The reference concavity of 0.45 is a conventional
comparison value, not a calibrated Aethelara constant. It therefore remains an
internal generated-terrain heuristic and is not exposed as a claim about river
age, discharge, erosion rate, or tectonics.

Lowering the middle cell preserves downstream descent and does not move the
channel. Repeated upstream-to-downstream passes are necessary because lowering
one cell changes the adjacent triples. A fixed pass ceiling preserves runtime
and reproducibility; the explicit unresolved count prevents a bound-limited
profile from appearing certified.

## Consequences

- The default Tharkeniss canonical field changes 13 cells. The largest
  steepness-only cut is 8.89 m; no channel edge climbs and no ratio remains
  above 8 beyond the documented numerical tolerance.
- At the aligned 257 grid, terminal cells remain 94, basin candidates remain
  80, direct connectivity remains 88.1663%, and estimated fill volume improves
  from 1,579.01 to 1,576.13 km3.
- At the standard 129 diagnostic grid, terminal cells remain 22, basin
  candidates remain 22, direct connectivity remains 88.4108%, and estimated
  fill volume changes from 1,104.18 to 1,110.14 km3. The coarser resampling
  remains sensitive to sub-cell profile changes.
- Generated elevations are not numerically compatible with builds made before
  this decision.
- Future authored waterfall, resistant-rock, fault, or uplift features need
  explicit semantics that can exempt or intentionally create a knickpoint.

## Action Items

1. [x] Add bounded normalized-steepness conditioning, diagnostics, and a
   synthetic extreme-knickpoint fixture.
2. [ ] Surface generated-channel profile diagnostics in a durable build report
   and inspection overlay.
3. [ ] Add explicit waterfall, lithology, fault, and uplift semantics before
   applying similar conditioning to authored drainage.
4. [ ] Evaluate chi-space fitting only after terrain-character regions can
   provide process parameters and exemptions.

## Evidence

- Royden and Perron,
  [Solutions of the stream power equation and application to the evolution of river longitudinal profiles](https://doi.org/10.1002/jgrf.20031),
  describes area-normalized longitudinal profiles and the distinct behavior of
  transient and stationary knickpoints.
- Perron and Royden,
  [An integral approach to bedrock river profile analysis](https://doi.org/10.1002/esp.3302),
  motivates chi-space comparison while documenting the assumptions behind a
  steady-state interpretation.
- Gailleton et al.,
  [Impact of changing concavity indices on channel steepness and divide migration metrics](https://doi.org/10.1029/2020JF006060),
  shows why the chosen reference concavity must remain explicit and qualified.
