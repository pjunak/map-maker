# Shared ridge crests and preserved junctions

Date: 2026-09-27. Starting revision: `3e9babd`.

## Problem and delivered slice

The preceding line-profile feature gave each ridge its own targets, but a
Gaussian weighted mean still mixed neighboring targets on the ridge itself.
Independent corner smoothing also moved a main ridge away from a branch ending
at an authored corner. These are separate composition and geometry failures.

Explicit **absolute** ridge profiles now own their centreline during the ridge
stage. A streaming, rescaled inverse-square distance blend combines targets;
the strongest physical response controls the blend into surrounding ground.
Distances are never epsilon-capped and strengths are not added into a plateau.
Constraint sorting preserves instruction-order reproducibility. This is an
interpolation rule, not a new physical mountain model.

Raw intersections between these ridges become protected shared vertices.
Smoothing operates separately between contacts. It reuses exact intersection
coordinates on every participating line, so reconstructing a distance along a
line cannot introduce slightly different copies of a shared endpoint. Profiles
continue to use the final smoothed line's fractional physical arc length.

[Shapely's substring operation](https://shapely.readthedocs.io/en/stable/manual.html#substring)
provides the metric spans; the existing corner smoother and shape-preserving
height interpolation are reused. No package or serialized field is added.
[ADR-0083](../adr/0083-preserve-shared-ridge-crests.md) owns the new contract.

Actual contacts must have compatible profile heights within 0.001 m. Generation
reports both instruction numbers, coordinates and along-profile percentages
when they disagree. Self-crossing/closed profiled absolute ridges and overlapping
line spans are rejected with guidance to use separate branches and one shared
crest. Near misses are not snapped; mixed/relative ridge modes keep their
existing semantics. Authored source coordinates are never rewritten.

## Paired public evidence

The bounded comparison loads the generator from `3e9babd` alongside the new
implementation. It uses public inputs, identical seeds/settings and native
257-pixel grids. The total probe took **20.509 s**. The enlarged comparison uses
nearest-neighbor display at 2x, identical scientific colours and elevation limits.

For the ridge-only controls derived from `range-lowland.terrain.json`:

| Extent | Seed | Old maximum crest-control error | New error |
|---|---:|---:|---:|
| 500 km | 42 | 244.800 m | 0 m |
| 1,000 km | 42 | 214.667 m | 0 m |
| 1,000 km | 43 | 214.667 m | 0 m |
| 1,000 km | 20260902 | 214.667 m | 0 m |
| 2,000 km | 42 | 139.641 m | 0 m |

These are sampled controls on the actual Float32 field, not a continuous-surface
certificate or a naturalness score. In the public
[connected-crests example](../../examples/terrain/connected-crests.terrain.json),
the main ridge's distance from the authored corner junction falls from **75 km
to 0 km**. The image changes from a rounded, disconnected main crest to a joined
crest and spur. Mean absolute land-height change is 99.229 m.

With the original example's valley present, the peak/pass/peak samples change
from 2481.766 / 1429.019 / 2173.435 m to 2481.766 / 1270.115 / 2148.763 m.
Valley carving still follows ridge construction; those are not hard final crest
equalities. Mean absolute change is 84.953 m. Both rendered comparisons retain
identical masks, finite land samples and zero incision-budget excess.

The remaining broad smooth shoulders and sharp protected junction turns are
visible. This feature establishes compatible authored topology and crest control;
it does not complete natural mountain branching, slope/curvature acceptance,
drainage realism or physical history.

Ignored local evidence: `artifacts/ridge-crests-2026-09-27/compare.py`,
`comparison.json` and `comparison.png`. The new example reuses the existing public
square SVG and is portable through project saving and verified-parent replay.

## What failed and what was retained

- Ordinary ridge averaging cannot preserve different nearby crest targets. The
  new blend preserves each axis and uses convex target shares away from it.
- Rounding every line independently destroyed the corner contact. Protecting
  actual intersections before smoothing fixes the geometry as well as its height.
- A new test incorrectly expected a valley floor to override a later independent
  height point. That point raised the sampled floor from 100 m to 161.669 m.
  The test now checks valley and point priority independently. Existing authority
  and numeric tolerances were retained.
- A point-only junction patch was considered but not executed: it would leave
  the rest of each crest subject to neighboring target averaging. A full new
  ridge graph, automatic snapping and a shared-height editor are not implemented
  by this slice. Rejecting incompatible input is preferable to averaging its
  authored heights or silently moving its lines.

## Validation

The preliminary crest/profile/generation group passed 71 tests in 74.82 s.
After preserving corner contacts, final crest/profile/editor/replay coverage passed
**77 tests in 52.09 s**. Ruff and strict Pyright pass. Both public terrain comparison
rows were visually inspected. All 13 public terrain examples validate and load;
all local links and 220 unique inventory entries covering 207 Markdown files,
one legal notice and supporting contracts were checked.

The full suite passed: **1,894 passed, 1 skipped in 718.36 s (11m 58s)**, within
the established first-failure/15-minute stop rule. The skipped Landlab reference
module requires the separate scientific-reference environment and was not rerun.
Checkpoint hashes matched before and after the run. No tested source or acceptance
threshold changed during validation. Local evidence additionally includes
`full-suite.log`, `full-suite.xml`, `full-suite-result.json` and `validation.json`
in the ignored evidence directory above.

## Next substantial gains

1. Generate subordinate branches from a shared range structure and expose junction
   relationships for editing, including deliberate snapping and propagated heights.
2. Add controlled tangents, asymmetric sides and cross-sections without losing
   the protected contacts or downstream valley/point authority.
3. Compare final ground slopes/curvature and drainage on varied regional backgrounds;
   direct map handles should support these checks rather than delay them.
