# Plain edges and lake shores between levels — 2026-10-27

Decision: [ADR-0106 revision](../adr/0106-wind-regional-valleys-below-the-tile-mesh.md#revision-2026-10-27-fields-follow-the-warp).
Catalog entry: D25 in the [decision catalog](decision-catalog.md).

## Question

Every regional level samples the coarser level's relief through a relief warp, an
area-preserving flow that bends valleys below the mesh (ADR-0106). The coarser
relief at a level's point x is therefore the planet's relief at the point the
warps carry x to (`ReliefWarp.planet_points`), on average 1.5 km away at level 1.
Since 2026-10-19 channels and the basins' held plain were sampled there, but basin
depth, lakes and the planet's uplift, erodibility and runoff were still sampled at
x itself. Did that move plain edges and lake shores between levels, and does
sampling them where the warps carry each point keep them in place?

## Change

- A level parent finds the planet's sediment basins and lakes where its relief
  holds them (`RegionalParent.on_planet`): finer tiles hold lakes flat and stop
  uplift on basins there.
- A level parent takes the planet's uplift, erodibility and runoff at the same
  points.
- A window finds the planet's lake cores where its own warp shows each cell.
- Climate, coast, volcanoes and wonders stay at the points themselves: climate is
  smooth at these distances, and the others are authored or placed where they
  are drawn.
- Regional algorithm `planet-blended-tiles-v21`; level-1 tiles are unchanged.

## Method

Aethelara `planet-3200k-v31`. At two places, windows of two levels on the same
pixels (1,024 across): level 1 and 2 at 60 km radius, level 2 and 3 at 20 km.

- **Basin front:** 56.869° E 30.703° N, where a basin plain meets a range.
- **Lake shore:** the shore point of lake 236 (5,537 km², open, at 143.41° E 18.72° N)
  nearest its centre, at 143.408° E 19.066° N.

HEAD (`4e4d4d8`, v20) and the change each generated their own tiles, then:

- **Shore offset:** the area between the two levels' lake outlines over the
  coarser outline's length.
- **Lake overlap:** intersection over union of the two levels' lakes.
- **Relief difference:** mean absolute difference of the two levels' relief, both
  smoothed over 1 km, on shared land.
- **Plain-edge offset:** the same measure as the shore offset, for the contour 100 m
  above the coarser map's 10th-percentile height. That contour also outlines
  hills, so it is a noisy measure of the front alone.

## Results

| Pair | Measure | HEAD | Change |
|---|---|---:|---:|
| Lake, level 1 → 2 (60 km) | shore offset | 724 m | 487 m |
| | lake overlap | 92.4 % | 94.8 % |
| Lake, level 2 → 3 (20 km) | shore offset | 187 m | 100 m |
| | lake overlap | 94.0 % | 96.6 % |
| Basin, level 1 → 2 (60 km) | relief difference | 40.1 m | 31.2 m |
| | plain-edge offset | 188 m | 182 m |
| Basin, level 2 → 3 (20 km) | relief difference | 1.09 m | 0.97 m |
| | plain-edge offset | 6.5 m | 5.8 m |

The region map's lake is unchanged (298,427 pixels either way): its cores lie well
inside so large a lake. On the province map, the shore now follows the region's
outline and adds finer bends to it; before, it had a bay where the region has
land and a different hook. What still differs between levels is mostly that finer
detail, which a finer level is meant to add.

## Disposition

Every level takes the planet's basins, lakes and forcing where its relief holds
them. Plain edges and lake shores move less between levels; the remaining offsets
are the finer levels' own detail. Images and scripts are kept locally in
`artifacts/research-notes/fronts-shores/`, not tracked in the repository.
