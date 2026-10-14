# ADR-0017: Report canonical drainage diagnostics without repairing the DEM

Status: Accepted
Date: 2026-09-04
Deciders: Project owner and Map Maker maintainers

## Context

Automatic valleys are routed on a conditioned macro surface, but the completed
terrain also contains residual detail and authoritative user constraints. Those
later stages can introduce pits, flats, or barriers. The tool needs measurable
evidence before it can claim drainage validity, but it has no authored lake or
endorheic-basin semantics yet and therefore cannot safely decide which
depressions should be filled or breached.

Analysing every requested output pixel would make the result depend on export
resolution and would add prohibitive Python routing cost at 4,096 pixels.
Silently applying Priority-Flood to the final DEM would be faster to explain,
but it would overwrite potentially intentional authored geography.

## Decision

- Re-evaluate the complete terrain pipeline on a fixed 129-cell-longest-side
  metric diagnostic grid after automatic and authored valley preparation.
- Keep this surface a pipeline diagnostic, not an authoritative DEM or exported
  drainage product. Record its dimensions, kilometre spacing, fill tolerance,
  and algorithm identifier with every summary.
- Route strict downhill D8 receivers on the unmodified diagnostic surface.
  Report potential inland terminal cells and the number of land cells that
  reach a coastline or enclosed-water boundary without conditioning.
- Run Priority-Flood on a copy only. Report cells requiring more than 0.01 m of
  fill, maximum fill depth, estimated fill volume, and the largest conditioned
  outlet catchment. Verify internally that the copied conditioned surface can
  route every land cell to an outlet.
- Attach the compact summary to `GeneratedTerrain`, store it in exported PNG
  metadata, and show direct-connectivity and potential-sink feedback in the
  desktop workbench.
- Do not fail generation merely because potential sinks exist. Until lakes and
  endorheic basins are explicit, these are review findings rather than errors.

## Options considered

| Option | Advantages | Costs and risks | Decision |
|---|---|---|---|
| Analyse the full Float32 output | Exact for that raster | Resolution-dependent, expensive, and unsuitable for interactive 4,096 px builds | Rejected for the default check |
| Analyse a canonical completed-pipeline surface | Stable, bounded, comparable, includes authored effects | Detects regional rather than local drainage and is not the exported DEM | Accepted |
| Automatically fill or breach the final DEM | Produces a drainage-conditioned raster immediately | Can erase authored lakes/basins and silently change hard geography | Rejected until water semantics exist |

## Consequences

- Every generated result now states how much broad drainage conditioning its
  completed terrain would require instead of relying on appearance.
- Diagnostics remain stable when only output resolution changes and add bounded
  runtime and memory.
- A strict D8 terminal may represent a true pit, an unresolved flat, or an
  intentional basin. The UI must call it a *potential* sink.
- Local gullies below the 129-cell diagnostic scale are deliberately not
  measured. Later regional builds need their own buffered, finer diagnostic
  grid tied to a parent build.
- Future authored-water work can classify findings and choose fill, breach,
  lake, or endorheic policies without changing the diagnostic contract silently.

## Evidence

- Synthetic fixtures cover a fully connected planar slope and a known inland
  depression, including non-mutation, fill depth, volume, and connectivity.
- Existing nested-resolution tests require identical diagnostic summaries at
  65 and 129 output samples.
- Barnes et al., [Priority-Flood](https://arxiv.org/abs/1511.04463), provides
  the depression-conditioning baseline used only on the diagnostic copy.

## Action items

- [x] Attach the canonical summary to generated terrain, PNG metadata, tests,
  and workbench feedback.
- [ ] Add authored lake and endorheic-basin classification before offering any
  automatic final-DEM repair.
- [ ] Add buffered finer diagnostics to the future regional-refinement contract.
