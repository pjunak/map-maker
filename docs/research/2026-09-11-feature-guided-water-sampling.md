# Feature-guided water sampling - 2026-09-11

Status: implemented and validated. This is evidence for the current
review behavior, not campaign canon or a lake-equilibrium model.

## Problem and result

The public shoreline-gap scene showed a remaining alignment problem. Its 2 km
height influence already produced two low quarter-grid samples, but reducing
the radius to 200 m or 20 m left every fixed probe above the 750 m lake level
outside the intended opening. Both narrower cases connected incorrectly. The
finished field at the exact height point is about 0.000676 m.

Local refinement now targets narrow authored point cores, brush segments and
smoothed ridge/valley crossings. It keeps every baseline station, merges
intersecting refinement requirements and samples within selected corridors at
one quarter of the evaluator's narrowest core radius. Width taper and attached
absolute-point factors come from the evaluator. Failed budgets return no partial
evidence. The sampler remains a typed Python stage, with no new dependency.

The new [200 m example](../../examples/terrain/narrow-shoreline-gap.terrain.json)
is blocked with 11 low samples outside the opening. Its boundary uses 1,151
samples, 69 more than the 1,082-station baseline, with a smallest local spacing
limit of 50 m. The exact low point is sampled. Both 200 m and 20 m cases retain
their captured area without changing any DEM, canonical ground or incoming-flow
hashes. The older 2 km example now also finds the near-zero minimum, with 1,149
samples and 11 low findings. Counts describe evidence, not physical opening width.

## Research and implementation choice

The US Army Corps of Engineers' [HEC-RAS 2D Flow Areas manual](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/entering-and-editing-geometric-data/2d-flow-areas)
explains aligning mesh faces with important high ground and channel banks using
breaklines and selecting local spacing. Our inference is that known authored
geometry should guide where we inspect a coarse connection. We implement local
point profiles, not HEC-RAS mesh generation, face hydraulics or fluid equations.
The two-radius corridor and radius/4 rule are explicit project choices, not
spacing rules prescribed by that reference.

[Shapely's manual](https://shapely.readthedocs.io/en/stable/manual.html)
documents the geometry intersections, normalization, projection, buffers and
nearest-point operations used here. A spatial index remains an option if
many-feature profiling justifies it; the current change adds no indexing engine.
The existing library and licensing boundary are unchanged.

Error-driven midpoint refinement alone can miss a narrow core when all initial
samples look alike. Global densification pays for every unaffected shoreline
segment. Feature-guided intervals address that known failure while keeping the
baseline and hard sample budget. Overlapping intervals use the finest active
spacing rather than independently charging duplicate samples. Polyline segments
are considered separately so repeated crossings cannot collapse to one nearest
point. Corridor end caps are conservative squares; their extra corner area can
add work but cannot omit a nearby core through circular buffer approximation.

## Validation and measurements

The final repository gates passed: **369 tests**, Ruff and strict Pyright.
All 184 local file links in the 11 changed Markdown files also passed.
Tests include the real opening with refinement disabled as a controlled
comparison, inner/outer narrow contact barriers, point offsets and scales,
parallel/collinear/oblique segments, repeated crossings, overlap deduplication,
baseline preservation, exact budgets and empty failure evidence. Existing
resolution/order, Float32, area-conservation and repeatable-build gates remain.

Hidden Tk checks passed all 12 overlay combinations across connected, closed
and narrow-opening scenes. Details correctly shows added samples and smallest
local spacing, while retaining existing collection/flat-route information.
Both final public headless builds completed. The narrow-opening review image was
visually inspected: the footprint stays amber and an orange point locates the
opening at its upper edge. The 11 close samples overlap at this display scale.
These are public synthetic examples, not edits to campaign geography.

The narrow example retains 2,069,615.059935 km2 and transfers zero, with a total
area-balance error of -9.3e-10 km2. The flat example still transfers
1,423,407.974020 km2 and retains 40,959.020577 km2. These are equal-node
contributing-area proxies, not water volumes. Its boundary now has 1,132 samples
(50 extra) and its connection 19 (13 extra); the sampled connection maximum
remains 222.206406 m. Diagnostics occupy 354,419 bytes for the narrow example
and 509,040 bytes for the flat example.

### Local convergence

For each of the 2 km, 200 m and 20 m point radii, compare radius/4, radius/8
and radius/16 profiles with 20,001 independent evaluations across a six-radius
window around the opening. Reference spacings are respectively 0.6 m, 0.06 m
and 0.006 m. Interpolate the two ground crossings of the imposed 750 m level
within each profile and compare their positions with the dense local reference.
These crossing estimates are a validation calculation, not a new exported
physical opening-width or water-level product.

| Authored radius (m) | Largest crossing error at radius/4 (m) | At radius/8 (m) | At radius/16 (m) |
|---:|---:|---:|---:|
| 2,000 | 9.7545 | 3.0811 | 0.7459 |
| 200 | 0.9600 | 0.2528 | 0.0511 |
| 20 | 0.0325 | 0.0140 | 0.0060 |

All three refined settings detect all three openings; the fixed baseline misses
both narrower cases. The 200 m scene uses 1,151 / 1,217 / 1,365 boundary stations
at the three refinement levels. Its two crossings converge from about 0.96 m
to 0.25 m to 0.05 m error. The sampled profile minimum is 0.000676 m, while
its dense local minimum is 0.000649 m: targeting the authored point does not
mathematically locate every blended extremum. These are three related opening
cases, not a general error bound or convergence evidence for all terrain.

No production spacing or budget was enlarged for the denser comparison. The
current radius/4 default detects the failures with substantially fewer samples.
The 200 m core is below the spacing of the delivered DEM; these checks inspect
the same finished field at extra positions, without refining the output raster.

### Runtime and scale

CPython 3.14.7, Windows, 768 px, seed 42, two fresh processes per scene:

| Scene | Generation seconds | Highest generation process peak (MiB) |
|---|---:|---:|
| Authored | 2.382 / 2.285 | 123.8 |
| Archipelago | 2.535 / 2.509 | 105.5 |
| Regional | 1.596 / 1.584 | 130.8 |
| Water | 1.554 / 1.530 | 135.9 |
| Outlet | 1.609 / 1.635 | 136.0 |
| Flat | 1.655 / 1.655 | 136.0 |
| Shoreline | 1.602 / 1.623 | 135.8 |
| Narrow | 1.614 / 1.633 | 136.2 |

All 26 numeric hashes and complete water-review records repeat exactly per
scene. All 26 hashes match the previous implementation for the seven existing
scenes. The new narrow scene has no full previous-version benchmark; its DEM,
canonical ground and incoming accumulation hashes match the before-change
129 px probe, as do the 2 km and 20 m variants. New diagnostics intentionally
differ. The connected examples retain their previous flow results.

Separate in-process instrumentation on the five public/variant scenes measured
5.71-6.98 ms for boundary checks and 1.59-2.22 ms for the connection profile,
roughly 7-9 ms combined. Those timings include planning, terrain evaluation and
profile construction; they exclude file export and rendering. The probe uses
129 px output, while routing and water-check coordinates remain fixed. They
are the cost of the complete current checks, not a measured incremental cost
against the preceding implementation.

A separate one-profile construction probe used a 100 km straight line, 250 m
baseline spacing and 20 m point radii, with a constant-ground callback:

| Nearby point features | Profile samples | Median milliseconds, three runs |
|---:|---:|---:|
| 10 | 577 | 1.39 |
| 100 | 2,166 | 9.89 |
| 500 | 9,189 | 48.25 |

That probe exposes geometry/planning and serialization-to-tuples cost; it does
not include evaluating a real field with hundreds of constraints. Long parallel
narrow cores can still exceed 65,536 samples; the regression fixture verifies
retention with no evaluated prefix. The budget bounds profile samples, not the
number of input features, geometry operations or project-wide work.

All timed generation/profile runs were serial, without competing tests or other
terrain generation. Cross-revision timing was not interleaved, so no total
speedup is claimed from differences against older measurements. Full 4096 px,
complex many-lake exports and large real constraint sets remain unmeasured.
The measured cost gives no reason for a language rewrite in this slice.

Evidence remains in ignored local artifacts:
`artifacts/feature-water-before-20260911.json`,
`artifacts/feature-water-probe-20260911.py`,
`artifacts/feature-water-validation-20260911.json`,
`artifacts/feature-water-performance-20260911.json`,
`artifacts/feature-water-performance-summary-20260911.json`,
`artifacts/feature-water-ui-20260911.json`,
`artifacts/feature-water-narrow-20260911/` and
`artifacts/feature-water-flat-20260911/`.


## Remaining gains

1. Extend finer evidence to internal wet links and every downstream route edge.
   Both still rely on canonical ground outside the short outlet connection.
2. Expand convergence cases to regional transitions, procedural extrema,
   interacting features and context tails. A finest local spacing value is not
   a uniform resolution, a global error bound or a certified controlling sill.
3. Measure many-lake total planning, evaluation and export cost before adding an
   index, larger budgets or project-wide limits. Per-profile limits do not bound
   the number of authored features or profiles in a project.
4. Define opening geometry, storage/inflow/boundary assumptions and compatible
   acyclic lake chains, then compare constrained breach/reroute proposals while
   preserving regional cut limits and authored anchors.

The [roadmap](../../TODO.md) and [strategy](../strategy/README.md) preserve that
order. The [water contract](../terrain-water.md) and
[ADR-0040](../adr/0040-refine-water-profiles-around-authored-features.md) define
the implementation. Build v13 adds refinement provenance to the profiles; project
v5 and numeric archive layouts remain current. No legacy schema is retained.
