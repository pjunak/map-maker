# Depression handling and channel conflicts - 2026-09-10

This follow-up narrows the next hydrology work using primary literature,
current tool documentation and measured Map Maker fixtures. It adds no external
runtime dependency and does not change authored geography.

## Research findings

[Barnes, Callaghan and Wickert (2021), Fill-Spill-Merge](https://esurf.copernicus.org/articles/9/105/2021/)
retains depressions in a hierarchy and distributes available runoff through
filling, spilling and merging. The useful distinction for this project is that
a topographic depression does not itself establish a permanent lake: water
availability matters. A connected fill-mask component is not a nested depression
hierarchy. Our implementation does not claim to run this algorithm.

[Lindsay (2016), hybrid breaching/filling](https://jblindsay.github.io/ghrg/pubs/Lindsay-HP-preprint.pdf)
describes complete, selective and constrained breaching. Depth and length
limits allow control over channel modification. For Map Maker, an incision
allowance is therefore a constraint to retain during outlet proposals, rather
than a parameter to silently expand until a path works. The current edge-local
cut deficit is not a complete breach profile or a route-length calculation.

[Landlab's DepressionFinderAndRouter documentation](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.depression_finder.lake_mapper.html)
exposes depression depths, lake maps, outlets, areas and volumes, with D8/D4
connectivity choices and optional rerouting of existing flow fields. This is a
useful future reference for explicit outlet maps and separate identification/
rerouting operations. No Landlab installation or Python 3.14 execution was
validated here; this review is not an MFD equivalence test.

## Implemented application of the research

Extract basin and routing diagnostics into `pipeline/diagnostics.py`, leaving
flow and incision primitives in `hydrology.py`. Reuse the finished-field flood
copy already needed for routing agreement; do not replace the Float32 DEM.

Classify uphill planned edges with overlapping indicators:

- endpoint in a finished-field depression deeper than 0.01 m;
- receiver allowance insufficient to lower that endpoint to the donor's height;
- final shaping increases the edge's rise relative to macro terrain minus incision;
- endpoint within any authored region's inward boundary transition.

Keep an explicit unclassified count. Export spatial evidence and show context
in the build review; do not invent a lake, a physical cause or an automatic fix.
The exact contract is in [ADR-0032](../adr/0032-classify-channel-conflicts.md).

## Fixture evidence

Use the ADR-0031 fixture: seed 42, 1000 km square, maximum 6000 m, coastal rise
5 km, default variability and recipe, region corners 0.05..0.95. Counts cover
all planned canonical edges, including region boundaries and background.

| Recipe | Uphill | Insufficient cut | Depression | Final adjustment | Region transition |
|---|---:|---:|---:|---:|---:|
| Plain | 253 | 253 | 234 | 130 | 43 |
| Hills | 279 | 279 | 269 | 158 | 56 |
| Plateau | 9 | 9 | 9 | 6 | 2 |
| Mountains | 621 | 621 | 508 | 380 | 247 |

Counts overlap and must not be added. All cases have zero unclassified edges;
that is coverage by measured indicators, not proof of an identified cause.
The public four-region example has 194 uphill edges: all exceed remaining cut,
177 touch depressions, 92 have a final-adjustment contribution and 66 touch a
regional transition. The existing terrain and channel count are not repaired
by attaching labels.

New zero-height fixtures exposed numerical underflow: tiny flood steps could
produce zero MFD weights and no D8 receiver. Relative-drop fallback arithmetic
now preserves routing and contributing area without inflating physical slopes
or turning numerical steps into lake candidates. Ordinary inputs retain the
previous arithmetic. Algorithm identities advance for this corrected edge case.

## Next bounded steps

1. Identify connected depression extents and deterministic spill/outlet
   candidates on the canonical finished grid. Specify how enclosed SVG water
   differs from ocean and an authored lake before connecting them.
2. Define an authored lake/outlet contract: water level, protected terrain,
   outlet identity and dry/endorheic intent. Require explicit acceptance.
3. Compare retain-lake, constrained breach and reroute proposals. Measure full
   route depth/length, affected area, anchors, cut limits and downstream closure.
4. Add a nested hierarchy and water/sediment accounting only when those inputs
   and semantics exist. Use reference engines behind adapters with separate
   environment and license validation.

The implementation passes 241 tests plus lint, strict typing and dependency
checks. Representative 768-pixel comparisons preserve prior terrain/routing
arrays and scalar diagnostics apart from version identifiers. The flat-zero
case changes intentionally. Full-resolution stress, an external solver run and
interactive lake/outlet authoring remain unvalidated/unimplemented.
