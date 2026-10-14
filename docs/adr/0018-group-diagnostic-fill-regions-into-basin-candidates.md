# ADR-0018: Group diagnostic fill regions into basin candidates

**Status:** Accepted
**Date:** 2026-09-04
**Deciders:** Project owner and Map Maker maintainers

## Context

ADR-0017 records individual terminal and fill-cell counts on a canonical
129-cell-longest-side grid. Those totals are measurable, but they do not tell
an author where to inspect the terrain or whether many cells belong to one
broad depression. Automatically converting them into lakes would be unsafe:
some may be generation artefacts, unresolved flats, intentional endorheic
basins, or nested depressions whose topology cannot be represented by one
marker.

Research on depression hierarchies treats nested depressions and their spill
relationships as a topological structure. Implementing that full structure is
the scientifically stronger destination, but it is more machinery than the
current review workflow needs. A smaller derived contract can make the existing
Priority-Flood evidence actionable without claiming hydrological completeness.

## Decision

- Label 8-connected cells whose diagnostic Priority-Flood depth exceeds the
  existing 0.01 m tolerance. Each connected component becomes one deterministic
  `DrainageBasinCandidate`.
- Locate a candidate at its deepest diagnostic cell, breaking equal-depth ties
  by row-major cell index. Sort candidates by decreasing depth, then volume and
  position, so metadata and overlays are reproducible.
- Record normalized location, component cell count and area, original floor
  elevation, conditioned spill estimate, maximum fill depth, fill volume, and
  the number of strict-D8 terminal cells inside the component.
- Report terminal cells outside significant fill separately as flat or
  sub-tolerance terminals.
- Store candidates in derived result metadata and overlay the largest twenty in
  the desktop workbench. Keep the overlay out of the rendered relief image and
  keep every candidate outside authored terrain-project data.
- Describe connected components as coarse *candidates*, not lakes, watershed
  polygons, exact shorelines, or a nested depression hierarchy.

## Options Considered

| Option | Complexity | Scientific value | Authoring safety | Decision |
|---|---:|---:|---:|---|
| Keep raw cell totals only | Low | Low | High | Rejected; not spatially actionable |
| Group connected significant-fill cells | Low | Medium at the diagnostic scale | High when kept derived | Accepted |
| Implement a full nested depression hierarchy now | High | High | High | Deferred until basin and water semantics need the topology |
| Convert fill regions directly into authored lakes | Medium | Low without climate and water-balance rules | Low | Rejected |

## Trade-off Analysis

Connected fill regions are deterministic, cheap on the bounded diagnostic grid,
and immediately reviewable. They can merge nested or adjacent depressions and
their 129-grid areas are deliberately coarse. A depression hierarchy would
retain fill-merge-spill topology and support hydrologic simulation, but it would
not by itself decide whether water persists as a lake. The candidate contract
therefore exposes measurements now while leaving both hierarchy extraction and
authored-water decisions explicit future steps.

## Consequences

- The author can see and rank likely drainage problems directly on the map.
- PNG metadata gains a nested candidate list and the drainage diagnostic
  algorithm identifier advances to version 2.
- Candidate locations and areas represent the canonical diagnostic grid, not
  local-map precision. A finer regional diagnostic may split or move them.
- A connected filled component may contain several nested basins. Consumers
  must not infer one lake per candidate.
- Future hierarchy work can add parent, child, spill-link, and ocean-link data
  without mutating the authoritative Float32 DEM or authored constraints.

## Action Items

1. [x] Add deterministic component grouping, typed candidate measurements,
   metadata, tests, and workbench overlays.
2. [ ] Add authored lake and endorheic-basin constraints before any final-DEM
   fill or breach operation.
3. [ ] Evaluate a full depression hierarchy when regional refinement or
   fill-spill routing requires nested topology.

## Evidence

- Barnes, Callaghan, and Wickert,
  [Depression hierarchies](https://esurf.copernicus.org/articles/8/431/2020/),
  describes nested depressions as a forest of binary trees with spill and ocean
  links.
- Barnes, Callaghan, and Wickert,
  [Fill-Spill-Merge](https://esurf.copernicus.org/articles/9/105/2021/),
  demonstrates why preserving depression topology matters for routing water
  rather than simply deleting every depression.
- Barnes, Lehman, and Mulla,
  [Priority-Flood](https://arxiv.org/abs/1511.04463), remains the fill-depth
  baseline used on the non-authoritative diagnostic copy.
