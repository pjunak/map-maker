# ADR-0106: Wind regional valleys below the tile mesh along an area-preserving flow

- Status: accepted (experimental product path)
- Date: 2026-10-18
- Refines [ADR-0086](0086-regional-planet-detail-from-blended-tiles.md) (blended
  tiles) and [ADR-0088](0088-nested-regional-detail-levels.md) (nested levels);
  refines relief below the mesh as ADR-0090 and ADR-0092 refine coasts and lake
  shores.

## Context

Regional rivers are routed pixel by pixel (D8 over filled depressions) on the
window's relief, the blend of the level's tiles. A tile interpolates linearly
between nodes about one level spacing apart (5 km at level 1). A valley there is
a crease along mesh edges, and where those edges are nearly collinear, or follow
a straight 12–30 km planet river segment the tiles inherit, the valley floor is a
straight line for 15 km or more. Since meanders follow the routed path where
bends are too small to draw ([decision D28](../research/decision-catalog.md),
2026-10-18), a level-1 window (488 m pixels) drew big rivers as long straight
runs with right-angle junctions.

On Aethelara (`planet-3200k-v30`, 56.869° E 30.703° N, 250 km, 1,024 pixels,
tiles `planet-blended-tiles-v11`), 15.6 % of the cells of rivers over 2,000 km²
lay in runs of ten or more identical D8 steps. Fill depth along them was 0: 72 %
of the run cells of rivers over 200 km² lie on valley creases and 23 % on planar
facets, 77 % along the grid axes. Routing was not the cause. Flat resolution
(Barnes et al. 2014) made rivers straighter (0.15 to 0.19 here, 0.07 to 0.20 at
level 3), and fill cells with an exactly level neighbour were too few for a
tie-break to matter ([report](../research/2026-10-12-straight-display-lines.md#straight-regional-rivers--2026-10-18)).

## Decision

1. **Relief is sampled along a flow.** A window samples its level's tile blend
   at points carried by an area-preserving flow (`swirl`): the curl of a stream
   function summed from rotated value-noise octaves, each its amplitude times its
   wavelength times the noise, integrated over unit time in eight midpoint steps.
   Each octave moves points by about its amplitude. A flow never folds and keeps
   areas, so the relief keeps its heights, the area at each height and its closed
   depressions; valleys and ridges bend. Unlike a plain displacement
   (`displace`), it stays fold-free at the strength needed.
2. **One octave sequence for all levels.** Octaves start at two level-1 spacings
   (10 km) and halve; each has an amplitude of 0.15 of its wavelength. Like a
   coast, a level takes only the octaves its tiles cannot carry:
   - a level parent (ADR-0088) samples the coarser blend with that level's
     octaves down to twice its spacing, what the coarser mesh resolves;
   - a window takes the octaves shorter than that, down to its own spacing.

   Level-1 windows bend at 10 and 5 km; provinces carry 10 km through their tiles
   and add 5, 2.5 and 1.25 km; local windows carry 10, 5 and 2.5 km and add
   1.25 km to 312 m. Every level bends rivers where level 1 does.
3. **Tile lookups reach the flow's bound.** Points move no further than 6.5 times
   the sum of the amplitudes (14.6 km at level 1), so windows and level parents
   load the tiles within that much more distance.
4. **Identity.** Level-2 and level-3 tiles are enriched from parents that sample
   the flow, and every window's relief changes, so the regional tile algorithm
   becomes `planet-blended-tiles-v12`. Level-1 tile generation is unchanged.

## Alternatives considered

- **Route windows over the display relief** (tile relief plus sub-tile detail):
  straight runs fell to 0.08, but filled ground rose from 1 % to 11 % of the land,
  so lakes, ponds and playas would change; small rivers changed course, and a
  deep straight tile valley kept its 40-pixel run.
- **A plain domain warp** (`displace`, as for coasts): at a steepness of 0.08
  its Jacobian stayed above 0.35, but it removed only a fifth of the straight
  runs (0.156 to 0.128); at 0.15 (0.102) the Jacobian fell to zero, so the
  relief folds.
- **Sinuosity in tile erosion or seeding:** a 5 km mesh cannot hold bends
  shorter than about 10 km, and warping the seed fields bends only the inherited
  planet troughs.
- **Smooth (C1) tile sampling:** it removes kinks at facet edges, but a valley
  along collinear nodes stays straight.
- **Coarser octaves** (from 20 km): rivers moved 3 km on average without fewer
  straight runs (0.097 against 0.084).
- **Octaves below the level spacing** (down to 2.5 km at level 1): fewer
  straight runs (0.053), but rivers wiggled at pixel scale.

## Revision (2026-10-27): fields follow the warp

A level's relief at a point x is the coarser relief, so the planet's, at the point
the warps carry x to (`ReliefWarp.planet_points`). Channels and the held basin
plain were sampled there since 2026-10-19, but basin depth, lakes and the planet's
uplift, erodibility and runoff were sampled at x itself, so a finer level held its
lakes and stopped uplift on its basins a warp displacement away from the coarser
relief's lake basins and plains. Every level now takes them where its relief holds
them (`RegionalParent.on_planet`), and windows find lake cores where their own warp
shows each cell. Climate, coast, volcanoes and wonders stay in place. On Aethelara,
lake shores moved 487 m on average from the region to the province map instead of
724 m, and 100 m instead of 187 m from the province to the local map
([report](../research/2026-10-27-fronts-and-shores-between-levels.md)). The
regional algorithm becomes `planet-blended-tiles-v21`.

## Consequences

- In the Aethelara level-1 window, the share of river cells (over 2,000 km²) in
  runs of ten or more identical steps fell from 0.156 to 0.058, and in
  near-straight 20-step stretches of any angle from 0.038 to 0.004. Confluences of
  two straight arms at 75–105° fell from 22 to 5 among rivers over 200 km²
  ([report](../research/2026-10-12-straight-display-lines.md#straight-regional-rivers--2026-10-18)).
  Junction angles keep their distribution (median 65° before, 68° after).
- At level 3 (20 km) straight runs fell from 0.076 to 0.046 for rivers over
  200 km², and the regenerated tiles let the 160,000 km² river cross the window.
- Rivers stay in their valleys, which move with them: points move 1.5 km on
  average at level 1 (at most 5.7 km), 0.8 km at level 2 and 0.2 km at level 3.
  Drainage conservation and inherited inflow are unchanged, and lakes fill the
  moved relief from the same cores.
- Pixels sample a winding V-crease off its floor more often than a straight one,
  so single-pixel hollows deeper than 10 m, which hold one-pixel ponds, rose from
  12 to 45 in the level-1 window (0.01 % of its pixels). Filled land went from
  0.6 % to 0.7 %.
- The flow shears the relief, so hillshade shows the same bends; display detail
  and its carving are unchanged and drawn on top. `elevation.tif` holds the moved
  relief. The flow takes about 0.3 s for a 1,280-pixel routing square.
- Overlapping windows agree as before: over six pairs on the test planet, 0.888
  near the edges and 0.919 inside, against 0.905 and 0.880.
