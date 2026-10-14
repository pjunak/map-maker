# Basin retention and downstream outlet assessment

Date: 2026-09-11. Implemented decision: [ADR-0035](../adr/0035-retain-basin-flow-and-assess-outlets.md).
Current contract: [authored water](../terrain-water.md).

## What improved

The planner now stops at authored lake/dry-basin footprint nodes. Priority-Flood
uses them as additional seeds, D8 sends no flow out, and MFD retains their
contributing area. Channel initiation, order, sizing and bounded cutting use
this corrected graph. A basin's area is reported explicitly rather than being
silently passed to downstream coast channels. All automatic cuts and detail
suppression remain zero within the authored polygon; authored features still apply.

Declared lake outlets receive a deterministic candidate assessment using the
finished Float32 ground and a separate conditioned topology. Evidence includes
sampled path indices, inspected length, uphill count/largest rise, highest ground
above water, and terminal boundary context. Vector segment checks detect basin
crossings and coastline gaps between raster nodes. Re-entry, cycles, bad
receivers, missing sampled water contact and unresolved attachments are explicit.

All declared outlets remain closed in planning. A clear sampled candidate does
not yet transfer basin area or establish a river. The next implementation must
connect these pieces with shoreline checks and finished-field revalidation.
Build v8 exports retention terminals and the richer diagnostics; project v5
remains current. The workbench's basin details explain findings, and drainage
review outlines authored retention separately from natural depression candidates.

## Research rationale

[Fill-Spill-Merge](https://esurf.copernicus.org/articles/9/105/2021/esurf-9-105-2021.html)
separates routing into depressions from redistribution through their hierarchy.
Its hierarchy and finite water volumes are prerequisites for overflow/storage
behavior. That supports keeping our retained contributing area separate from
water depth; this implementation does not reproduce the paper's simulator.

[Landlab's DepressionFinderAndRouter](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.depression_finder.lake_mapper.html)
provides a useful reference for explicit lake/outlet routing. Integrating such
an engine would still require mapping authored polygons, bed elevations and
outlet authority into its contracts. No new dependency is needed for this slice.

The selected approach is an engineering planning boundary: stop and account for
area first, then connect eligible outlets. Full nested hydrology remains an
option when runoff, storage and overflow become actual requirements.

## Validation and public-scene evidence

The full suite passed: **289 tests**. Ruff, strict Pyright and dependency checks
passed. New analytical cases cover conservation in D8 and MFD, zero-height
flats, intercepted downhill flow, retention without an external cut budget,
protected anchors/ground, deterministic nested samples, off-grid outlets,
uphill steps, re-entry, cycles, invalid/interior terminals, small vector gaps
and basin crossings, unresolved attachments and unknown terminal levels.
Repeated headless builds check current schemas, export arrays and hashes.
After the review annotation change, all 51 focused routing/water/build tests
passed. A hidden Tk smoke verified basin details and drainage preview for both
closed and declared-outlet cases; the generated images were visually inspected.

Public `basin-water.terrain.json`, seed 42:

- Closed dry basin: 1,672 canonical nodes, zero planned exits, retained
  contributing area 1,165,028.31 km2.
- Closed lake: 4,440 canonical footprint nodes, 1,550 wet nodes, zero planned
  exits, retained contributing area 2,346,891.68 km2.
- Total contributing area entering and ending at all planning terminals:
  7,946,049.991975777 km2 in both sums. These are equal-node grid areas,
  not exact vector catchment areas or water volumes.
- All 55,543 delivered samples inside the authored areas match the previous
  ground DEM exactly. Lake water samples and footprint IDs also remain unchanged.
- Both closed areas have no current sampled basin-review issues. Remaining
  uphill channels elsewhere are still reported; retention does not certify all rivers.

Ignored evidence is under `artifacts/basin-retention-20260911/` and
`artifacts/basin-retention-performance-20260911.json`. The final annotated review is under
`artifacts/basin-retention-final-20260911/`; its ground and routing/water numeric
files match the initial build byte for byte. Generated files stay untracked.

## Performance

CPython 3.14.7, Windows, 768 px, seed 42, two fresh-process runs per scene:

| Scene | Generation runs (seconds) | Highest generation process peak (MiB) |
|---|---:|---:|
| Authored constraints | 2.227 / 2.233 | 123.4 |
| Archipelago | 2.487 / 2.509 | 105.5 |
| Regional terrain | 1.552 / 1.553 | 130.5 |
| Authored water | 1.500 / 1.500 | 135.7 |

Repeated numeric hashes match. Every previously recorded numeric hash in the
three scenes without basin constraints matches the 2026-09-10 baseline.
The water scene intentionally changes outside terrain, channels and derived
natural depressions after correcting its contributing-area routing.

This is not a controlled cross-revision speedup claim: previous timings varied
with machine state. The benchmark excludes file export and the drainage review
panel renderer; process peaks include imports. Large outlet counts and 4096 px
stress runs are unmeasured. There is no evidence here requiring a language rewrite.

## Next gains, in order

1. Connect eligible outlets: collect retained area, resolve wet-component and
   shoreline conflicts, establish a single explicit lake exit, reject inter-basin
   cycles and revalidate after any changes to the finished field.
2. Compare full constrained breach and reroute proposals. Measure path length,
   required cuts, regional limits and authored anchor conflicts; avoid treating
   local uphill deficits as a complete breach design.
3. Improve boundary editing and refinement: movable basin/outlet vertices,
   vector shorelines, narrow footprint features and sub-grid height checks.
4. Define exterior/enclosed water levels, then add runoff and nested storage
   only when the product needs physical overflow behavior.

All remaining improvements are logged in [TODO](../../TODO.md) and ordered in
[the strategy](../strategy/README.md).
