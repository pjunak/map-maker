# Ordered terrain implementation plan

Updated 2026-10-13. **Active milestone: M6, nested deterministic regional and local
maps.** Map views run alongside it. The plan is world-first: one whole-planet
relief, made by uplift and erosion on a sphere mesh, feeds climate, map views and
regional zoom ([decision D00a](../research/decision-catalog.md)).

Keep one active milestone and at most one experiment needed to choose its next
step. This file owns execution order. [TODO](../../TODO.md) keeps the feature
backlog, and [status](../research/status.md) records what works now.

## Milestones

| Milestone | State | Deliverable | Completion evidence |
|---|---|---|---|
| **M1** | implemented, experimental | Context-bound local rough terrain: one landmass, AEQD (ADR-0084). | [Evidence](../research/2026-09-28-context-bound-rough-terrain.md). |
| **M2** | implemented, experimental | **Whole-planet relief** (ADR-0085), with geology recipes as uplift and erodibility. Includes plates, volcanism, sediment basins and ocean floor. `dmtools world planet` exports a GeoTIFF, a mesh archive, rivers and lakes. | Coast invariant, descending receivers, isotropic flow, mesh-converged statistics, deterministic repeats. See the [planet guide](../world-planet.md). |
| **M3** | implemented, experimental | **Provisional climate:** seasonal temperature, winds, moisture with orographic lift, runoff, biomes and Köppen. | Controlled windward/leeward and coastal/interior responses; closed water budget ([report](../research/2026-10-08-continentality-and-koppen.md)). |
| **M4** | partly implemented | **Coupled, inspectable workflow:** runoff-weighted erosion and lakes (done); a World-tab stage with cancel and stale state (done); a single map view with background jobs and drill-down through every level (ADR-0089); compare and regenerate. | A user can run, inspect, change an input and regenerate, and sees nonconvergence. |
| **M5** | queued | **Accepted parent and native core:** reference-world realism gates, an adoption ADR, and a port of the stable kernels to a native core with differential tests. Decide what replaces the local composed generator. | Metric thresholds; Python/native agreement within tolerance; dependency audit. |
| **M6** | **ACTIVE** | **Regional and local zoom.** Fixed blended tiles (ADR-0086) and nested levels are done: region (5 km), province (1 km) and local (200 m), each enriched from the level above (ADR-0088). Display detail is world-anchored and scaled per level; fine tiles branch; next: rivers traced on tiles. | Overlapping and nested requests agree; inherited flow is conserved; revisits do not age terrain again (ADR-0048). |
| **Views** | implemented, experimental | **Map themes and projections** (ADR-0087): globe and polar views; atlas, relief, climate, topographic, parchment, plates, sea-floor age, basins and geology themes. Political and civilization views will need authored overlays. | Themes are registered once; projections are deterministic and verified against the build. |
| **M7** | deferred | Water and materials, plus selected landforms (discharge widths, lake storage, glacial, karst), when integrated results show a need. | A control and a conservation ledger for each mechanism. |
| **M8** | deferred | Accepted ecology and stronger planetary models. | Traceable classifications and uncertainty. |

## Next

1. **M6 seamless local maps.**
   - Display detail is now world-anchored and scaled per level.
   - Rivers are routed over a padded window, so overlapping windows draw the
     same rivers (about 96 % agreement near the edges).
   - Rock texture now follows each level's spacing, so fine tiles branch rather
     than cutting parallel gullies.
   - Regional coasts are refined below the drawing's precision, so local maps
     show bays and headlands instead of smooth traced curves (ADR-0090, tile
     algorithm `planet-blended-tiles-v6`).
   - Regional lakes fill the regional relief from the parent lake, with outlines
     refined below the parent spacing, so shores lose the parent mesh's straight
     edges; crater lakes are no longer pits (ADR-0092, `planet-blended-tiles-v7`).
     Open lakes drain their window basin, so no playa ring lines their shores.
   - Regional plains no longer show straight grid lines: display carving drains
     filled hollows along their thalweg, and ridged detail has no steps
     ([report](../research/2026-10-12-straight-display-lines.md)).
2. **Wonder catalog** ([wonder guide](../wonders.md)): each kind is chosen in the
   settings for random placement or placed by hand. Titans, shattered and
   giant active volcanoes, craters, chasms, great cliffs, tepuis, oases and a
   splitting river are done, wonders age on their own patches (ADR-0091), and
   rivers fall as waterfalls off their cliffs. Next: more kinds as needed.
3. **Political and civilization overlays** as registered themes.

## Integration and adoption checks

| Always required, including experiments | Required before default adoption or stronger claims |
|---|---|
| Source geography and authored-input roles preserved. Explicit units, coordinates, dependencies and deterministic seeds. | Reference-world realism metrics and authoring coverage; accepted relief/river correspondence. |
| Finite numeric state, valid masks, declared corrections, cancellation, and honest incomplete results. | Calibrated physical assumptions, conservation evidence, parent consistency, and a license review. |
| Supported inputs enforced, failures told apart from unsupported cases, and experimental status kept on save and reopen. | A reviewed adoption decision on the integrated application, not only a benchmark. |

## Deliberately deferred

Further polish of the local composed generator, noise-certification bounds, GPU
work and speculative tuning. The native rewrite waits for M5, so it ports the
stable planet core rather than the local generator.

## Keep this plan current

In the same commit as any substantive implementation or experiment, update:

1. This page's date, milestone states and **Next** list.
2. Affected [TODO](../../TODO.md) items and [status](../research/status.md).
3. The affected [decision](../research/decision-catalog.md). Failed methods go to
   the [method register](../research/terrain-method-decisions.md).
4. A dated report for new measurements, and an ADR when architecture changes.
5. Links and the [file inventory](../FILE_INDEX.md) when files are added or removed.
