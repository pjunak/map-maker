# ADR-0088: Nest regional detail levels, each enriched from the level above

- Status: accepted (experimental product path)
- Date: 2026-10-11
- Extends ADR-0086 (fixed blended tiles) towards ADR-0048 (zoom-driven enrichment).
- Refined by [ADR-0105](0105-regional-levels-see-level-1-slopes.md): every level
  is coloured and shaded by its slopes scaled to level 1.
- Refined by [ADR-0107](0107-regional-temperatures-follow-height-above-the-planet.md): every level
  is as warm as the planet at its height.
- Refined by [ADR-0108](0108-calibrate-regional-relief-against-the-parent-smoothed-alike.md):
  every level keeps the height of the level above at that level's spacing.
- Refined by [ADR-0112](0112-regional-waters-on-sphere-cells.md): rivers,
  lakes and ponds are worked out on cells fixed to the sphere, not on each window's
  pixels.

## Context

Regional windows give about 5 km detail from fixed tiles enriched from the planet.
Users want local maps for specific places at every scale, from a kingdom down to
a valley. Each scale must be deterministic and agree with the scale above.
Enriching a valley-scale window directly from the 12–25 km planet mesh would
skip a scale of landforms. Enriching it from one regional window would make it
depend on where that window happened to be drawn.

## Decision

1. **Levels.** Regional detail has fixed levels, and each step refines spacing
   about fivefold:

   | Level | Spacing | Tile spacing | Halo | Typical window radius |
   |---|---|---|---|---|
   | 1 (region) | 5 km | 600 km | 150 km | 150–1,200 km |
   | 2 (province) | 1 km | 120 km | 30 km | 30–300 km |
   | 3 (local) | 200 m | 24 km | 6 km | 6–60 km |

   The process area is 24 × spacing², and the rock-hardness texture has a
   wavelength of 8 × spacing. A fixed 40 km texture left fine tiles uniform, so
   water cut straight parallel gullies. Level 1 is otherwise ADR-0086 unchanged.
2. **Tiles per level.** Every level uses its own fixed, unjittered Fibonacci tile
   lattice. Tile seeds come from `planet.tile.<id>` at level 1 and
   `planet.tile.l<level>.<id>` below it. A tile's values depend only on the build,
   its level, its id and the level settings.
3. **Parents.**
   - **Level 1** is enriched from the planet.
   - **Level n** is enriched from a *level parent*: a patch mesh at level n−1
     spacing over the tile's support and halo. It carries:
     - the blended level n−1 relief;
     - the planet's forcing, climate, lakes, volcanoes and craters, sampled onto
       the patch;
     - drainage routed on the patch, with planet rivers entering as inflows.
   - The level parent is rebuilt from cached coarser tiles whenever it is
     needed, and is never stored.
4. **Windows.** A level-n window blends level-n tiles. It composes like a level-1
   window, using a level parent built over the window. Coarser tiles are generated
   first, recursively, and every level is cached separately by its settings.

## Consequences

- **Determinism.** A place has the same values at a given level whatever window
  shows it. Seen through its own smoothing scale, each level matches the level
  above it.
- **Cost.** Deep levels need coarser tiles around them, but the cost is bounded
  by the window radius limits. Level-n tiles cost about the same as level-1 tiles
  (about 50–60k mesh nodes each).
- **Display detail per level.** Shading detail stands in for relief the level's
  mesh cannot resolve:
  - its wavelength is 6× the level spacing;
  - its height shrinks as spacing^1.2;
  - it is seeded by the planet and centred on its world-wide mean.

  Overlapping windows therefore draw the same hills. At 200 m, detail sized for
  5 km tiles had cut straight D8 grooves and sunbursts.
- **Remaining window dependence.** Valley carving (capped at the small detail
  height) and river tracing run on each window's pixel grid, with inflow from the
  parent at the rim. Windows are therefore composed over 1.25× their radius and
  cropped, so that rim stays off the map. Near the edges of two overlapping
  windows, river pixels then agree about 96 % of the time (92 % before). The rest
  is pixel-grid alignment.
- **Not yet regenerated.** Climate, lakes and volcanoes are not regenerated per
  level. They come from the planet, lapse-corrected and redrawn sharply.
