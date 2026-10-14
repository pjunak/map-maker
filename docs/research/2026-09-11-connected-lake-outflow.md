# Connected lake outflow: implementation and next steps

Date: 2026-09-11. Accepted decision:
[ADR-0036](../adr/0036-connect-lake-outflow-with-area-transfer.md).
Current usage and numeric contract: [authored water](../terrain-water.md).

## Result

Eligible authored lake outlets now connect after finished-terrain validation.
The connection carries captured contributing area to its downstream boundary,
with explicit source, throughput and terminal arrays. Two outlets sharing a
trunk add their respective sources once. The complete area balance is checked
before a build can finish.

A lake does not automatically export every contribution inside its polygon.
Water must form one connected component with vector-contained links to the
outlet contact. Dry nodes must descend to that water surface within the polygon;
submerged bed elevations are not used as their receiving height. Dry pits and
unresolved flats retain their contributions. Extra low shoreline openings
outside the bounded outlet aperture block connection.

Every run reassesses current Float32 ground. A connection never silently cuts
terrain or changes authored height points. Closing the outlet changes the
water-flow result while leaving the DEM and automatic-incision capture graph
unchanged. Routes through other basins are blocked until explicit lake-chain
semantics exist.

Build v9 adds `basin-flow.npz` and its diagnostics/hash. Project v5 stays current;
there is no saved connected state to become stale. The workbench explains closed,
blocked, connected and partial-catchment results, and drainage review shows
connected paths in teal. The categorized TODO and execution strategy are updated.

## Public example and an actual rejected route

The [connected-outlet fixture](../../examples/terrain/connected-outlet.terrain.json)
uses the public synthetic coastline, one lake, one dry basin and a deliberately
straight authored valley. This is a connection test, not a natural river-shape
showcase. The valley finishes at the actual vector coast. Ending it at normalized
x=0.01 instead leaves an approximately 111 m rise before the coast; regeneration
correctly blocks that outlet. This real-example failure is now a regression test.

At seed 42 on the canonical 257 by 152 grid:

| Accounting | Contributing area (km2) |
|---|---:|
| Lake captured | 2,066,161.818656 |
| Lake delivered through its outlet | 649,077.696806 |
| Lake retained in unresolved dry ground | 1,417,084.121850 |
| Closed dry basin retained | 1,207,356.489491 |
| Direct boundary delivery from the capture graph | 4,672,531.683829 |
| All source land nodes | 7,946,049.991976 |

The area balance error is about -9.3e-10 km2. These are equal-node grid areas,
not surveyed catchment areas or water volumes. The lake is connected with an
explicit `outlet_partial_catchment` finding. No unresolved area is silently
redirected to make the result appear complete.

The ignored review build is `artifacts/connected-outlet-20260911/`.

## Verification and performance

- **301 tests passed**, including analytical conservation, shared trunks,
  isolated pockets, shoreline conflicts, blocked/re-entering paths, real-scene
  revalidation, resolution/input-order independence and closing without ground changes.
- Ruff, strict Pyright and dependency checks passed.
- Repeated headless builds validate the current schema, required products,
  numeric arrays, diagnostics and deterministic hashes.
- Hidden Tk smoke checks passed for connected, closed and blocked basin details
  and drainage previews. The generated cartographic and drainage images were inspected.

CPython 3.14.7 on Windows, 768 px, seed 42, two fresh-process runs per scene:

| Scene | Generation seconds | Highest generation process peak (MiB) |
|---|---:|---:|
| Authored constraints | 2.514 / 2.549 | 123.9 |
| Archipelago | 2.742 / 2.615 | 104.5 |
| Regional terrain | 1.674 / 1.670 | 130.7 |
| Closed authored water | 1.601 / 1.578 | 136.3 |
| Connected outlet | 1.700 / 1.747 | 136.0 |

Evidence: `artifacts/connected-outlet-performance-20260911.json`. Repeated output
hashes agree. Every previously recorded numeric hash for the first four scenes
matches the prior retention implementation. The new outlet fixture differs in
authored inputs, so its timing versus the closed scene does not isolate connection
cost. No controlled cross-revision speedup is claimed. File export and drainage
panel rendering are outside benchmark timings; process peaks include imports.
Many outlets, complex retained boundaries and 4096 px stress runs are unmeasured.

## Research rationale and remaining limits

[Fill-Spill-Merge](https://esurf.copernicus.org/articles/9/105/2021/esurf-9-105-2021.html)
models runoff redistribution through a depression hierarchy. Its separation of
routing, storage and overflow supports keeping those concepts distinct here.
Our contributing-area transfer does not implement its water-volume simulation.
[Landlab's lake routing API](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.depression_finder.lake_mapper.html)
remains a reference for future lake-chain and outlet topology work; no new engine
or dependency was needed for this implementation.

The authored water level is an imposed surface, without a solved storage or
runoff budget. An outlet bed below that level does not prove the lake can sustain
its prescribed level. Sill/level agreement needs explicit review before claiming
physically stable water. Current path checks are sampled, the opening spans one
grid diagonal, and internal flats stay unresolved. Outlet transfer does not
recompute channel width/incision or certify the remaining river network.

## Next gains

1. Show collected versus retained basin nodes, inspect isolated dry pockets,
   and define flat routing that respects divides and authored water levels.
2. Refine outlet apertures, sill/level agreement and terrain sampling between
   nodes before treating coarse connections as hydrologically stable.
3. Support explicit lake chains with compatible levels and acyclic dependencies.
4. Compare full constrained breach/reroute proposals, preserving regional cutting
   limits and authored anchors. River geometry and channel-size feedback follow
   validated routes; they should not bypass their terrain constraints.

These items are logged in [TODO](../../TODO.md). Keep Python iteration; current
measurements do not justify changing the runtime for this feature.
