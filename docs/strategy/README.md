# Ordered terrain implementation plan

Updated 2026-10-26. **Active milestone: M6, nested deterministic regional and local
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
| **M2** | implemented, experimental | **Whole-planet relief** (ADR-0085), with geology recipes as uplift and erodibility. Includes plates, volcanism, sediment basins and ocean floor. `map-maker world planet` exports a GeoTIFF, a mesh archive, rivers and lakes. | Coast invariant, descending receivers, isotropic flow, mesh-converged statistics, deterministic repeats. See the [planet guide](../world-planet.md). |
| **M3** | implemented, experimental | **Provisional climate:** seasonal temperature, winds, moisture with orographic lift, runoff, biomes and Köppen; ice sheets from mass balance and shallow-ice flow (ADR-0093). | Controlled windward/leeward and coastal/interior responses; closed water budget ([report](../research/2026-10-08-continentality-and-koppen.md)). |
| **M4** | partly implemented | **Coupled, inspectable workflow:** runoff-weighted erosion and lakes (done); a World-tab stage with cancel and stale state (done); a single map view with background jobs and drill-down through every level (ADR-0089); guided steps with geology edited in place and following world edits (ADR-0096, done); wonders regenerated without eroding again (ADR-0097, done); compare and regenerate. | A user can run, inspect, change an input and regenerate, and sees nonconvergence. |
| **M5** | queued | **Accepted parent and native core:** reference-world realism gates, an adoption ADR, and a port of the stable kernels to a native core with differential tests. Decide what replaces the local composed generator. | Metric thresholds; Python/native agreement within tolerance; dependency audit. |
| **M6** | **ACTIVE** | **Regional and local zoom.** Fixed blended tiles (ADR-0086) and nested levels are done: region (5 km), province (1 km) and local (200 m), each enriched from the level above (ADR-0088). Display detail is world-anchored and scaled per level, every level is coloured and shaded by slopes scaled to level 1 (ADR-0105) and is as warm as the planet at its height (ADR-0107) and keeps the height of the level above at that level's spacing (ADR-0108); sediment plains keep the planet's height at every level and big rivers one course through them all; fine tiles branch; waters are worked out on cells fixed to the sphere, so overlapping maps draw the same rivers (ADR-0112); next: fronts and shores that stay put between levels. | Overlapping and nested requests agree; inherited flow is conserved; revisits do not age terrain again (ADR-0048). |
| **Views** | implemented, experimental | **Map themes and projections** (ADR-0087): an interactive globe (zoom, grab-to-turn, ADR-0101) that shows opened regional maps when zoomed in, down to their own resolution (ADR-0103, ADR-0104), glTF globe models with opened regional maps (ADR-0102, ADR-0111), spinning globes as animated WebP (ADR-0110) and polar views; atlas, relief, climate, topographic, parchment, plates, sea-floor age, basins and geology themes. Political and civilization views will need authored overlays. | Themes are registered once; projections are deterministic and verified against the build. |
| **M7** | deferred | Water and materials, plus selected landforms (discharge widths, lake storage, glacial, karst), when integrated results show a need. | A control and a conservation ledger for each mechanism. |
| **M8** | deferred | Accepted ecology and stronger planetary models. | Traceable classifications and uncertainty. |

## Next

1. **M6 seamless local maps.**
   - Display detail is now world-anchored and scaled per level.
   - Rivers are routed over a padded window, so overlapping windows draw the
     same rivers (about 96 % agreement near the edges).
   - Rivers entering a map keep the drainage of the level above. A window's
     routing rim is a wall, so water leaves only down valleys; each parent river
     enters where it crosses, or in the window's own valley within one parent
     spacing. Level parents reach a planet step beyond the area they serve, so
     planet rivers cross into it, and tiles weight inherited drainage once
     (`planet-blended-tiles-v10`).
   - Wide rivers on fine maps meander about their valley line, the routed path
     smoothed over half a bend, instead of about each pixel step, where their
     bends crossed into tangles.
   - Valleys wind below the tile mesh: every level samples its tile blend along
     an area-preserving flow of nested noise octaves, so region maps no longer
     draw big rivers as straight runs between mesh nodes meeting at right angles
     (ADR-0106, `planet-blended-tiles-v12`).
   - Rock texture now follows each level's spacing, so fine tiles branch rather
     than cutting parallel gullies.
   - Regional coasts are refined below the drawing's precision, so local maps
     show bays and headlands instead of smooth traced curves (ADR-0090, tile
     algorithm `planet-blended-tiles-v6`). A map that already carries that detail
     (an exported refined coast) states it and gets only finer detail;
     `world refine-coast` exports that coast as a source map (ADR-0095).
   - Regional lakes fill the regional relief from the parent lake, with outlines
     refined below the parent spacing, so shores lose the parent mesh's straight
     edges; crater lakes are no longer pits (ADR-0092, `planet-blended-tiles-v7`).
     Open lakes drain their window basin, so no playa ring lines their shores.
     Hollows overflow when their catchment outruns evaporation, and big rivers
     fill shallow ones with sediment and run on; no water leaves a window
     where a river comes in.
   - Regional plains no longer show straight grid lines: display carving drains
     filled hollows along their thalweg, and ridged detail has no steps
     ([report](../research/2026-10-12-straight-display-lines.md)). Tiles are
     seeded from smooth parent fields on a more irregular lattice, so province
     and local relief no longer shows the parent's triangles as creased facets
     (`planet-blended-tiles-v8`).
   - Plains meet mountains along dissected fronts. Every level samples the
     planet's sediment-basin depth smoothly at points displaced by nested noise,
     as lake shores are refined, so plains run up valleys and spurs reach out
     into them, where the front was straight within each planet triangle. Level
     parents take planet forcing smoothly too (`planet-blended-tiles-v11`).
   - Smooth parent samples stay within each parent triangle's corner values:
     cubics overshooting a mountain front had set tile rings to sea level and
     drained big rivers to them (`planet-blended-tiles-v13`).
   - Every level is as warm as the planet at its height, and display detail
     warms or cools colour only about its own mean (ADR-0107).
   - Every level keeps the height of the level above at that level's spacing.
     Tiles are calibrated against the parent surface smoothed as they are,
     instead of the parent itself, which smoothing lowers at peaks. Provinces
     had stood 200–530 m above regions in mountains, and regions had drawn 5 km
     peaks over 2.4 km planet mountains (ADR-0108, `planet-blended-tiles-v14`).
   - Sediment-basin plains keep the planet's height at every level. Basin land
     never erodes below the planet's plain, breached where sampling leaves sills
     between parent nodes, and parent rivers keep bankfull channels along their
     links, so big rivers cross plains in their channels and overlapping tiles
     agree there (`planet-blended-tiles-v15`).
   - Mountain tiles calibrate as well as smooth ones. The uplift correction is
     fitted to the relief uplift builds along the drainage, from the steady state
     the starting surface drains to, so a valley's correction no longer lifts the
     ridges above it unseen. Level 1 ends at 43 m RMS against the smoothed parent,
     level 2 at 92 m, near the noise of its own erosion (ADR-0109,
     `planet-blended-tiles-v16`).
   - Maps no longer draw lakes where blended tiles disagree about an outlet.
     Tiles drain fully, so the hollows their blend closes are plains that
     sediment fills; only craters, chasms, calderas and volcanic dams drawn on
     top of the tiles hold ponds. The Aethelara region window lost its two such
     lakes, 2,240 and 1,470 km², while planet lakes are drawn as before
     (ADR-0086 revision, `planet-blended-tiles-v17`).
   - A big river keeps one course through every level. Every level cuts its
     channels along the planet's links where its relief carries them, on beds
     graded from one planet node to the next, so overlapping tiles cut one channel
     and no tile dams a plain behind a sill that smooth sampling raises. On the
     Aethelara basin plain the province and local maps follow the region's course
     instead of turning north at a junction (ADR-0086 revision,
     `planet-blended-tiles-v18`).
   - Rivers, lakes and ponds are worked out on the sphere and only drawn flat.
     Windows route on jittered, triangulated cells of an equiangular cubed sphere
     near their pixel size, the same cells for every window of that size, so
     overlapping maps draw the same waters, and rivers follow slopes in every
     direction instead of eight. Bends are fixed to the place (ADR-0112,
     `planet-blended-tiles-v19`).
   - Tiles stand on the sphere's own nodes. Every tile of a level erodes the
     cubed sphere's world-fixed nodes from ground and rock seeded per level, so
     overlapping tiles agree several times more closely and carve plains and
     channels alike. Each tile still fits its own uplift correction, which
     level-2 mountain tiles never settle (ADR-0113, `planet-blended-tiles-v20`).
   - **Next:** basin depth, lakes and planet forcing sampled where the relief
     warps carry each level's points, so basin fronts and lake shores stay put
     between levels.
   - Polar land is worked in true distance and a touched pole is covered, so the
     south polar ice sheet domes over the pole instead of ending in a spike
     (ADR-0094, relief algorithm `sphere-mesh-stream-power-v26`). Polar land is
     first smoothed east-west, so shapes drawn on the flat map no longer become
     radial fingers in polar views (ADR-0100, `sphere-mesh-stream-power-v30`).
   - Sediment-basin plains fall towards where they drain at an alluvial gradient
     of 1e-4 instead of lying level at their spill height, so a river crossing a
     plain has a direction at every zoom level (`sphere-mesh-stream-power-v31`).
   - Fold belts are trains of en echelon anticlines that wander, step sideways and
     plunge out, instead of parallel rails along a whole belt, which read as a
     stamped washboard on the world map (`sphere-mesh-stream-power-v32`).
2. **Wonder layer** ([wonder guide](../wonders.md)). Titans, shattered and
   giant active volcanoes, craters, chasms, great cliffs, tepuis, oases and a
   splitting river are done; wonders age on their own patches (ADR-0091) and
   rivers fall as waterfalls off their cliffs.
   - Wonders are a pass on a base planet without them (ADR-0097): random kinds
     are wonder settings, placed wonders have their own `.wonders.json` document,
     Wonders step and seed each, and applying or regenerating them never erodes
     again. Regional tiles come from the base, so wonder edits keep them. A run
     draws only the map shown; the others are drawn when first chosen.
   - Each kind's settings are declared once in the catalog (ADR-0098), and
     wonders are placed on the planet's maps.
   - The Wonders step suggests plausible sites per kind, scored by stated
     hypotheses, to keep or reject (ADR-0099). Next: more kinds as needed.
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
