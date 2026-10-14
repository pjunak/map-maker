# Line-owned terrain profiles: connected-landform authoring slice

Date: 2026-09-27. Starting revision: `95f5bb9`.

## Scope and method choice

The engine already had ridge/valley lines and height-point-derived profiles.
Another noise preset would not give explicit control over the relationship
between peaks, passes and a descending spur. Add line-owned profiles as the
first authoring slice of the connected range/lowland milestone; do not describe
that entire generation milestone as complete.

Reuse the existing PCHIP-style interpolation. The
[SciPy reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.PchipInterpolator.html)
documents monotonicity preservation, no overshoot between knots and continuous
first derivatives, with possible second-derivative jumps. These are interpolation
properties, not geological validation. No dependency or second implementation is
added. [ADR-0082](../adr/0082-own-structure-profiles.md) owns the concrete contract.

## Delivered behavior

- Explicit position/height knots belong to one ridge or valley and move with it.
- The editor offers a curve preview, add/replace/remove, a two-peaks/pass starting
  shape, validation, cancel and one-step undo/redo. Regeneration applies the inputs.
- Absolute and relative modes retain their existing physical meanings. Absolute
  valley floors must descend; relative valleys retain source-aware no-fill fitting.
- Separate height points remain authoritative but no longer attach to a line that
  has its own profile. Coast, ceiling, incision and shared-coordinate gates remain.
- Narrow profile intervals inform local water-review sampling and existing budgets.
- Project v8, snapshot v3, build v19 and regional samples v3 preserve these inputs.

## Public comparison and limits

The public [range-lowland project](../../examples/terrain/range-lowland.terrain.json)
uses a synthetic 1,000 km square, a lowland recipe, a main ridge, one connected spur
and a descending valley. Compare the same project and seed with profiles cleared
versus authored profiles. The five-generation/preparation probe took 5.303 s.
The paired seed-42 grid has the same coast/mask, finite land samples and zero
incision-budget excess. Mean absolute land-height change is 161.318 m; this is a
change measurement, not a realism score. Native pixels are enlarged threefold
in the comparison image, without implying new detail.

At three positions along the main crest, seed 42 produces **2,481.766 / 1,429.019 /
2,173.435 m** (peak/pass/peak). Seeds 43 and 20260902 retain those heights to
0.001 m. Isolated-line numeric controls hit their 2,800 / 1,400 / 2,400 m targets
within 0.002 m, with terrain falling away across the pass. The combined example
shifts those targets because other structure influences overlap. The visual
comparison shows a pass and connected descending spur, but also broad smooth
shoulders and synthetic line-shaped geometry. Do not call this accepted natural
mountain or river generation.

Local ignored evidence: `artifacts/structure-profiles-2026-09-27/comparison.json`
and `comparison.png`. The example and its SVG source are versioned public inputs.

## Alternatives and problems retained

**Proximity-only attachment is insufficient for explicit range control.** Absolute
points can attach to every nearby compatible line; relative points become
unattached when the nearest line is ambiguous. Preserve that established behavior
for lines without an explicit profile, but do not use it to assign a profile's
ownership. The new profile belongs to one line by construction.

**A different noise carrier was considered, not tested or adopted.** It would
change existing regional terrain and routing without establishing an authored
range/pass network. Automatic structure generation remains a follow-up with its
own fixed-seed/scale evidence; this batch does not replace the mountain carrier.

**Independent profiles do not solve graph junctions.** Even compatible endpoint
values do not remove all overlapping influence away from the junction. Retain
this limitation and compare explicit shared-junction authority/branch construction
before claiming exact multi-line peak heights. No numeric acceptance threshold
was relaxed to fit the new feature.

Development checks caught stale schema identifiers and a test that passed Python
tuples directly to a JSON decoder. Current references and an actual JSON
serialization roundtrip fix those checks; decoder array validation remains intact.
The snapshot schema references project definitions, so the implementation updates
those references rather than duplicating its constraint definitions.

## Validation checkpoint

- Final profile/editor group: **65 passed in 29.04 s**, including saved-build
  parent replay and exact sampled-ground agreement.
- Build/parent/regional/world integration group: **136 passed in 54.84 s**.
- Ruff and strict Pyright pass. All 12 public terrain projects pass the current
  schema and runtime loading. The documented CLI accepts `terrain gui --project`.
- Visually inspected the actual workbench at 1440 x 900 and 1160 x 760, and the
  dialog at 620 x 640 and 540 x 570. The first minimum-size preview clipped its
  final point because it used a fixed 500 px lower width bound; sizing to the
  actual canvas fixes it. The three dialog tests pass again after that correction.
- The documentation inventory contains all 205 Markdown files plus one legal
  notice; all 218 inventory/support links are unique. Local Markdown links,
  schema file references and `git diff --check` pass.
- The user-approved full suite passed: **1,879 passed, 1 skipped in 581.07 s
  (9 minutes 41 seconds)**. It completed within the 15-minute stop limit without
  failures. The skipped `test_evolution_reference.py` check requires the separate
  isolated scientific-reference environment; that comparison was not rerun.
  All checkpoint file hashes matched before and after the suite. No terrain
  source, fixture or acceptance threshold changed during the run.
- Local evidence additionally includes `full-suite.log`, `full-suite.xml`,
  `full-suite-result.json` and `validation.json` under the ignored evidence
  directory above. These passing software gates do not close the documented
  terrain-realism and shared-junction limitations.

## Next work

1. Show and move individual profile positions directly on the map.
2. Give connected ridge junctions explicit compatible ownership, then generate
   subordinate spurs and transitions into lowlands from a shared range structure.
3. Add slope and narrow-support feedback in physical units; a continuous profile
   alone does not bound steepness or guarantee drainage.
4. Keep river/ground representation and physical-history acceptance independent
   of this usable authoring feature.
