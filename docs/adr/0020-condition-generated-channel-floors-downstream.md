# ADR-0020: Condition generated channel floors downstream

**Status:** Accepted
**Date:** 2026-09-04
**Deciders:** Project owner and Map Maker maintainers

## Context

ADR-0019 guarantees that the selected automatic channel mask is topologically
connected over the canonical D8 receiver tree. It does not guarantee that the
terrain reconstructed along that mask descends. The incision response includes
local slope and contributing area, while some stochastic residual detail is
deliberately retained. Incision can therefore weaken faster than the underlying
surface descends and leave short uphill steps in an otherwise connected valley.

On the default Tharkeniss build, the generated macro floor contained 12 uphill
channel edges with a maximum 19.2 m rise. Reapplying retained detail increased
that to 16 edges and a maximum 61.4 m rise. Applying Priority-Flood to the final
DEM would remove those barriers, but it would also modify terrain outside the
generated network and pre-empt future lake and endorheic-basin semantics.

## Decision

- Reconstruct the exact surface that enters the generated-valley result on the
  fixed 257-cell grid: macro elevation plus retained residual detail minus
  automatic incision.
- Traverse selected channel cells in descending routing-surface order. For each
  selected D8 edge, lower only the downstream cell as needed to provide at
  least 0.01 m of drop. Never raise a cell or change routing topology.
- At confluences, use the lowest floor required by any processed upstream donor.
  Stable routing order and the existing fixed D8 tree make the pass
  deterministic.
- Bound the total incision to 60% of reconstructed local elevation and bound
  added correction to 2% of the generation ceiling. Preserve any existing
  incision that is already deeper than those correction limits.
- Retain the exact centreline correction without a lateral smoothing pass. A
  one-cell shoulder experiment did not improve coarse diagnostics and slightly
  increased estimated fill volume.
- Record the correction raster and unresolved-edge count in the internal typed
  `DrainageIncision` result. An edge that exceeds the conservative bounds is
  reported rather than silently over-cut.
- Apply this only to generated valleys before authored constraints. Do not use
  it to rewrite authored rivers, lakes, basins, ridges, or the final Float32
  DEM.

## Options Considered

| Option | Scope | Connectivity | Terrain disturbance | Decision |
|---|---:|---:|---:|---|
| Leave local uphill steps | Generated network | Topological only | None | Rejected |
| Priority-Flood the completed DEM | Whole DEM | Strong | High; removes unclassified natural basins | Rejected |
| Globally smooth or burn the channel network | Channel and shoulders | Strong | Can erase local form and create scale mismatch | Rejected |
| Bounded downstream-only centreline correction | Generated channel cells | Strong within accepted bounds | Minimal and measurable | Accepted |

## Trade-off Analysis

The accepted pass is an inequality correction, not erosion simulation. It
preserves the generated network and changes only cells that violate downstream
descent. The bounds prevent a filled routing path from carving an arbitrarily
deep trench through a real basin or near-coastal barrier. This also means an
edge can remain unresolved and must stay visible to diagnostics.

The correction is defined on the 257-cell automatic-valley grid. At that
aligned scale it measurably improves drainage. The existing 129-cell completed-
surface diagnostic can alias a one-cell correction and must not be treated as a
finer-network certification. Regional refinement needs a buffered hierarchy and
its own diagnostics.

## Consequences

- Generated centreline floors descend through retained stochastic detail
  whenever the conservative correction bounds permit.
- On Tharkeniss at the aligned 257 scale, terminal cells fall from 101 to 94,
  basin candidates from 85 to 80, direct connectivity rises from 85.63% to
  88.17%, and estimated fill volume falls by about 9%.
- The default 129-cell completed-surface basin count remains 22; its estimated
  fill volume rises because it can miss narrow 257-grid correction paths.
- Automatic-valley elevations change and are not numerically compatible with
  builds made before this decision.
- Authored constraints can deliberately alter the generated floor afterward.
  Final diagnostics remain authoritative for reporting those combined effects.

## Action Items

1. [x] Add residual-aware downstream conditioning, conservative bounds,
   correction diagnostics, and a synthetic retained-detail fixture.
2. [ ] Carry parent channel corridors into buffered regional refinements so
   coarser and finer drainage routes remain connected.
3. [ ] Add explicit lake and endorheic-basin semantics before any completed-DEM
   fill or breach operation.

## Evidence

- ANUDEM's [drainage enforcement documentation](https://fennerschool.anu.edu.au/research/products/anudem-version-5-3)
  requires input streamlines to descend and applies conservative tolerances
  rather than contradicting elevation evidence without limit.
- Zhang et al.,
  [Topographic hydro-conditioning](https://pmc.ncbi.nlm.nih.gov/articles/PMC10434835/),
  discusses monotonically decreasing river profiles while preserving selected
  depressions.
- Lindsay,
  [The practice of DEM stream burning revisited](https://doi.org/10.1002/esp.3888),
  documents topological risks from indiscriminate stream burning.
