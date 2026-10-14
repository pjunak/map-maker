# Internal water links - 2026-09-11

Status: implemented and validated on public synthetic terrain. This records
sampled connectivity at an imposed lake level, not campaign canon or equilibrium.

## Result and authoring behavior

Internal lake-water connections now inspect ground between canonical wet nodes.
A link with ground above the imposed water level plus 0.01 m is removed, and the
remaining wet graph is traversed from the already-selected outlet contact.
Clear alternate paths may keep the pool connected. If any sampled water remains
separated, the existing single-pool rule keeps the whole outlet blocked and all
its captured contributing area retained. No contact is moved and no isolated
pool is drained merely because it shares the authored polygon.

The new [internal-water-barrier example](../../examples/terrain/internal-water-barrier.terrain.json)
adds a relative +1,500 m height point with a 100 m influence radius at normalized
(0.32037, 0.5033112582781457). The public lake is at 750 m. Its canonical mask has
253 wet nodes in one component, and its shoreline and external outlet stay clear.
Without internal feature guidance, even the quarter-grid links collect its water.

The finer network has 853 candidate links and 10,712 samples. One rejected bridge
has sampled ground at 1,735.541382 m, at local (1281.48, 1192.962132) km. Its own
profile uses 36 stations, 31 added by refinement, with a 25 m smallest local limit.
After removing it, only 25 of 253 wet nodes reach the selected contact. The lake
retains all 2,052,777.898760 km2 of captured area and transfers zero. These are
contributing-area proxies, not water volumes or exact vector pool areas.

Moving the same point to normalized x = 0.40037 demonstrates alternate paths:
two of 800 links are rejected, but all 238 wet nodes remain reachable. That lake
still transfers 574,041.303115 km2. A rejected link is therefore evidence for
review, not an automatic rejection of the entire outlet.

Basin details shows link counts, selected-contact reach and budget status. Red
diamonds mark sampled high ground, including where other paths remain usable.
The completed split example visibly retains its amber footprint, with the new
crest diamond just inside its western side. The DEM and clipped water product
are unchanged by this review. Dry collection links still use canonical heads.

## Implementation and model boundary

The existing sampler now separates planning, station construction and ground
evaluation. Its previous shoreline/connection/downstream results stay identical.
Each vector-contained undirected wet pair is planned once with the same baseline
and feature-guided spacing. Link endpoints must match canonical Float32 heights
exactly; disagreement fails generation. Evaluation batches of at most 4,096
samples are shared across links instead of invoking the terrain evaluator for
each small profile.

A whole-lake network has a 65,536-sample limit, including repeated endpoints.
Reject excessive baseline or refined plans before evaluating any ground; failed
counts are required lower bounds, and no partial network is accepted. A single
wet contact with no links needs zero additional samples. This bounds samples,
not input feature count, geometry operations or total project work.

Build v15 records `wet_links` per basin: candidate/blocked counts, contact reach,
status and each link's endpoint indices, maximum ground/location and sample
provenance. Maxima retain the decision evidence without duplicating complete
profiles for every link in JSON. An earlier ineligible basin has null evidence;
an excessive network has no accepted links or reachable count. The coarse
`wet_component_count` remains distinct from the finer contact-reach result.
Project v5 and numeric archive layouts remain unchanged; v14's schema is removed.

The official [HEC-HMS channel-flow reference](https://www.hec.usace.army.mil/confluence/hmsdocs/hmstrm/channel-flow/channel-flow-basic-concepts-equations-and-solution-techniques)
uses momentum and continuity, including pressure, friction, inflow and storage.
Our inference is that a sampled terrain connection at a fixed level should stay
separate from those dynamic assumptions. This change does not calculate filling,
discharge, water budgets or stable levels. Its threshold and graph rule are
project decisions, not rules prescribed by that reference. D8 links can also
miss narrow off-grid wet detours; finer 2D pool/shoreline geometry remains work.

## Validation

**389 tests passed**, with Ruff and strict Pyright. Changed text passed UTF-8
checks and all 199 local file links in 12 changed Markdown documents resolve;
section anchors were not checked. New coverage exercises
above-water barriers, submerged and tolerated crests, alternate wet paths, dry
nodes that cannot join pools, canonical endpoint identity and shared evaluation
batches. Baseline, per-profile and refinement budget failures evaluate no prefix.
The application-level budget regression retains all captured area.

The real split-pool fixture remains blocked at 65 and 129 px with reversed
constraint order and identical water review. A controlled ablation disables only
internal feature guidance and restores the formerly accepted connection; delivered
DEM, canonical ground and incoming MFD accumulation are exactly equal. This
isolates the review decision from the authored point's effect on terrain.

All 16 hidden Tk overlay combinations passed across connected, split, alternate
and over-budget scenarios, including the revised disconnection explanation.
Final headless builds completed for the split and flat examples. The split review
image was visually inspected for the crest marker, retained fill and readable
legend. Private campaign maps and existing authored projects stayed untouched.

All 26 numeric hashes and full water records repeat exactly for each of ten
benchmark scenes. All nine pre-existing scenes retain their previous numeric
hashes and area accounting. After excluding the new review fields/identities,
previous water evidence also matches exactly, including all shoreline and outlet
sample positions and heights. This verifies that the sampler split preserves
its original numerical behavior. The new internal fixture has no old full
benchmark; its controlled ablation supplies the ground-preservation evidence.

The connected flat example still transfers 1,423,407.974020 km2 from its lake and
retains 40,959.020577 km2 there. The largest absolute global area-balance error
across all ten scenes is 1.12e-8 km2. The final diagnostics are 882,252 bytes for
the split example and 804,192 bytes for the flat example; the latter previously
used 665,265 bytes. Per-link summaries add useful evidence but are not free to
serialize. Large many-lake exports remain unmeasured.

## Performance

CPython 3.14.7 on Windows, seed 42, 768 px, two fresh processes per scene:

| Scene | Generation seconds | Highest generation process peak (MiB) |
|---|---:|---:|
| Authored | 2.367 / 2.410 | 123.8 |
| Archipelago | 2.532 / 2.527 | 105.4 |
| Regional | 1.625 / 1.598 | 130.9 |
| Water | 1.518 / 1.532 | 136.3 |
| Outlet | 1.725 / 1.739 | 136.3 |
| Flat | 1.705 / 1.753 | 136.2 |
| Shoreline | 1.607 / 1.636 | 136.0 |
| Narrow shoreline | 1.635 / 1.659 | 136.0 |
| Downstream barrier | 1.628 / 1.641 | 136.6 |
| Internal barrier | 1.757 / 1.732 | 136.0 |

These timings exclude file export and rendering. All runs were serial with no
competing tests or other terrain generation. Peak process memory includes imports
and native allocations. Revisions were not timed in an interleaved comparison,
so these totals are not a precise estimate of incremental cost.

Separate serial in-process probes, three repeats on each prepared field at
129 px delivery with unchanged canonical coordinates, measured the full new
wet-link check, including planning, evaluation, endpoint validation, maxima,
link rejection and wet reachability:

| Scene | Candidate links | Samples | Terrain calls per check | Median ms |
|---|---:|---:|---:|---:|
| Connected outlet | 947 | 12,464 | 4 | 110.05 |
| Flat outlet | 318 | 6,470 | 2 | 59.74 |
| Internal barrier | 853 | 10,712 | 3 | 106.60 |
| Alternate-path variant | 800 | 11,440 | 3 | 115.67 |

For the connected example, separately evaluating the same 947 link profiles took
1,254.94 ms in one serial comparison and made 947 terrain calls. Every maximum,
maximum position and sample count matched the batched result exactly. This
supports batching as the useful optimization here; it is not a whole-generator
speedup claim. The comparison includes Python loop and assertion overhead and
is not an interleaved statistical performance study.

The measured 60-116 ms median cost per eligible lake is acceptable for this
iteration in Python. It does not establish many-lake performance or remove the
existing complex-coast geometry bottleneck. Measure those workloads before
adding an index, shared station reuse or a native implementation. No new library
or language migration was needed.

Ignored local evidence:
`artifacts/wet-links-performance-20260911.json`,
`artifacts/wet-links-performance-summary-20260911.json`,
`artifacts/wet-links-probe-20260911.py`,
`artifacts/wet-links-validation-20260911.json`,
`artifacts/wet-links-ui-20260911.json`,
`artifacts/wet-links-internal-build-20260911/` and
`artifacts/wet-links-flat-build-20260911/`.

## Next gains

1. Extend finer checks to dry-to-dry and dry-to-water collection links, including
   flat paths. Keep water-surface head, alternate path selection and closed pits
   explicit while conserving captured area.
2. Compare refined 2D wet components and off-grid detours, regional transitions,
   overlapping features and context tails. Sampled graph connectivity is not a
   complete shoreline or controlling-sill model.
3. Measure many-lake total planning, evaluation and export costs before choosing
   shared station/path reuse, indexing or a broader budget strategy.
4. Define pool, inflow, storage and boundary assumptions before lake chains and
   bounded breach/reroute proposals; preserve authored anchors and regional caps.

The [TODO](../../TODO.md), [strategy](../strategy/README.md),
[water contract](../terrain-water.md) and
[ADR-0042](../adr/0042-review-internal-water-links.md) record the current scope.
