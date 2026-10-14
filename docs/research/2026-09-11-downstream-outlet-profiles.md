# Complete downstream outlet profiles - 2026-09-11

Status: implemented and validated. This records terrain-review behavior on public
synthetic projects, not campaign canon or a hydraulic lake model.

## Result

External outlet review now samples the whole inspected downstream path, including
narrow authored features between routing nodes. It uses one bounded profile,
retains every canonical vertex and verifies its Float32 height. A route that
climbs more than 0.01 m from an earlier sampled low stays blocked. This measures
the complete climb, so many smaller steps cannot hide it.

The new [downstream-barrier example](../../examples/terrain/downstream-barrier.terrain.json)
adds a relative +50 m point with a 100 m influence radius at local x = 604 km on
the connected example's external valley. Its elevation mode differs from the
absolute valley, so the point acts independently. All 71 canonical path nodes
still descend; even the 281-station quarter-grid profile misses the climb.

The feature-guided profile uses 1,139 samples and finds a 43.848862 m rise from an
earlier low. Its crest is at (604.0, 1192.962132) km and 196.276337 m elevation,
below the path's earlier 220.628922 m maximum and below the imposed 750 m lake.
Using only the global maximum or only above-lake-height checks would miss this
local climb. The lake now retains all 2,066,225.154998 km2 of its captured area
and exports zero. Total contributing-area balance error is zero in this example.
These are equal-node area proxies, not water volumes.

A red diamond marks the climb crest in both workbench review modes and the
finished-ground review image. Basin details reports sample count, scope, largest
climb and any budget failure. Build v14 records the complete profile and routing
vertex mapping in diagnostics; numeric archive layouts and project v5 stay the
same. The obsolete build v13 schema is removed. No dependency was added.

## Research and model boundary

The official [HEC-HMS channel-flow reference](https://www.hec.usace.army.mil/confluence/hmsdocs/hmstrm/channel-flow/channel-flow-basic-concepts-equations-and-solution-techniques)
describes momentum and continuity using bed slope, pressure/depth gradients,
acceleration, friction and storage. It also requires channel descriptions and
initial/boundary conditions. Our inference is that a terrain-only non-rising
check can conservatively withhold a connection but cannot establish physical
flow impossibility or lake equilibrium. This change extends the existing review
rule; it does not implement those equations. External pool levels, energy and
storage remain explicit future work. The 0.01 m tolerance and feature-spacing
rule are project choices, not prescriptions from that reference.

Reusing the existing sampler keeps the numerical engine in Python and retains
its prepared geometry and Float32 evaluation boundary. A midpoint-only or uniform
profile still misses narrow features when its stations lie on either side.
Checking each edge separately would also reset the budget and could hide a
cumulative climb spread across multiple small steps. The complete profile avoids
both problems while exporting the evidence needed for later pool/sill work.

## Validation

The final repository gates passed: **378 tests**, Ruff and strict Pyright.
All changed text files passed UTF-8 checks, and 192 local file links in the
12 changed Markdown documents resolve; section anchors were not checked.
Regression coverage includes a local crest below an earlier global maximum,
sub-tolerance steps adding to a blocked climb, an accepted small rise, whole-path
budget failure when each individual edge would fit, single-node and incomplete
paths, canonical-height disagreement, exact exported vertex mapping and repeatable
builds. The real generated barrier remains blocked with reversed constraints and
65/129 px delivered rasters, with identical water review and canonical ground.

All 12 hidden Tk overlay combinations passed across the connected flat, blocked
downstream and narrow shoreline examples. The details show 1,139 downstream
samples and a 43.85 m climb for the barrier, while both other external profiles
remain clear. Their distinct lake outcomes stay visible. Final headless builds
completed for the barrier and flat examples. Visual inspection confirms the
amber retained footprint, red crest diamond to its left and readable legends.
This checks generated public examples, not a live campaign document.

All 26 numeric hashes and full water-review records repeat exactly in each of
nine benchmark scenes. The 26 hashes and area summaries also match the preceding
implementation in all eight pre-existing scenes. The new barrier has no older
full benchmark; its delivered 129 px DEM, canonical ground and incoming MFD
accumulation hashes match the saved before-change probe exactly. Its prior outlet
was connected; its newly rejected transfer is a deliberate derived-product change.

The connected flat example still transfers 1,423,407.974020 km2 from its lake and
retains 40,959.020577 km2 there. The narrow-shoreline example retains all its lake
area, independently of the now-reviewed clear downstream path. Diagnostics are
513,427 bytes for the barrier build and 665,265 bytes for the flat build. Profiles
increase diagnostic serialization size; they do not refine the delivered DEM.

## Local refinement evidence

Compare the same complete external path at the default core radius/4 and at
radius/8 and radius/16. A separate 20,001-point reference samples a 2 km window
around the new point in downstream order, at 0.1 m spacing. This local reference
finds a 43.929565 m climb, an upstream minimum at x = 604.37 km and the crest at
x = 604 km. It is a dense sampled reference, not an analytic extremum proof.

| Profile | Total external samples | Largest climb (m) | Difference from local reference (m) |
|---|---:|---:|---:|
| Quarter-grid, no feature guidance | 281 | 0 | 43.929565 |
| Feature radius/4, current default | 1,139 | 43.848862 | 0.080704 |
| Feature radius/8 | 1,995 | 43.887115 | 0.042450 |
| Feature radius/16 | 3,986 | 43.917694 | 0.011871 |

All refined profiles locate the same crest and block transfer. Their earlier-low
estimate improves with refinement. The default smallest local spacing is 25 m;
the broader valley also supplies extra probes. This example supports the current
decision but also shows why a reported sampled climb is not an exact controlling
sill height. Context tails and interacting features can shift the minimum beyond
the narrow point's refinement corridor. Production limits were not increased.

## Performance

CPython 3.14.7 on Windows, seed 42, 768 px, two fresh processes per scene:

| Scene | Generation seconds | Highest generation process peak (MiB) |
|---|---:|---:|
| Authored | 2.390 / 2.278 | 123.8 |
| Archipelago | 2.511 / 2.510 | 104.5 |
| Regional | 1.590 / 1.610 | 130.7 |
| Water | 1.518 / 1.537 | 136.2 |
| Outlet | 1.599 / 1.615 | 135.9 |
| Flat | 1.658 / 1.655 | 135.7 |
| Shoreline | 1.617 / 1.631 | 135.7 |
| Narrow | 1.629 / 1.605 | 136.0 |
| Downstream barrier | 1.607 / 1.604 | 135.9 |

These are generation timings, excluding file export and rendering. Cross-revision
timings were not interleaved, so the small differences from the prior report do
not establish a total speed change. All runs were serial, without competing
terrain generation or tests. Peak process memory includes imports and native
allocations. The largest absolute area-balance error was 1.12e-8 km2 across the
nine scenes; all existing conservation gates passed.

Separate in-process measurements of the complete downstream-profile function,
three repeats on each prepared field, gave median costs of 11.03 ms for the
connected outlet, 10.89 ms for the flat outlet, 11.00 ms for the narrow shoreline
and 13.03 ms for the downstream barrier. Individual timings spanned 10.54-13.71 ms.
They include geometry planning, field evaluation, tuple construction, vertex
verification and rise analysis. They exclude file serialization/rendering and
use 129 px delivery with the unchanged canonical path. These are the cost of
the new profile check, not a measured increase in end-to-end build time.

No measured cost here warrants a Rust rewrite or an added indexing dependency.
The existing complex-coast geometry bottleneck remains separate. Each path has a
65,536-sample budget and 4,096-sample batches; this bounds samples, not input
feature count, geometry operations or total project work. Complex many-lake
projects, 4096 px exports and large real constraint sets remain unmeasured.

Local evidence remains in ignored artifacts:
`artifacts/downstream-barrier-before-20260911.json`,
`artifacts/downstream-before-20260911.json`,
`artifacts/downstream-probe-20260911.py`,
`artifacts/downstream-validation-20260911.json`,
`artifacts/downstream-performance-20260911.json`,
`artifacts/downstream-performance-summary-20260911.json`,
`artifacts/downstream-ui-20260911.json`,
`artifacts/downstream-barrier-build-20260911/` and
`artifacts/downstream-flat-build-20260911/`.

## Next gains

1. Check internal wet links between canonical nodes, retaining rejected-link
   evidence and conservation. Define how finer pool separation affects the
   selected water contact before allowing area transfer.
2. Expand convergence checks to regional transitions, procedural extrema,
   overlapping constraints and context tails. Keep sampled clearance distinct
   from a guaranteed absence of barriers.
3. Measure many-lake planning, evaluation and diagnostic export before choosing
   a spatial index, shared-path reuse or a project-wide budget. Keep exact field
   evaluation and deterministic evidence when considering reuse.
4. Define controlling openings, pool/storage/inflow and boundary-level assumptions;
   then connect compatible acyclic lake chains and compare bounded breach/reroute
   proposals that preserve regional cut limits and authored anchors.

The [TODO](../../TODO.md) and [strategy](../strategy/README.md) track this order.
The [water contract](../terrain-water.md) and
[ADR-0041](../adr/0041-review-complete-downstream-outlet-profiles.md) define the
implemented behavior and its limits.
