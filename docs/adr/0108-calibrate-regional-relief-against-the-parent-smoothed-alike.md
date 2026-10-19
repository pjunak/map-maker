# ADR-0108: Calibrate regional relief against the parent smoothed alike

- Status: accepted (experimental product path)
- Date: 2026-10-19
- Refines [ADR-0086](0086-regional-planet-detail-from-blended-tiles.md) (tile
  calibration) and [ADR-0088](0088-nested-regional-detail-levels.md) (nested
  levels); follows up [ADR-0107](0107-regional-temperatures-follow-height-above-the-planet.md).

## Context

A regional tile is eroded from its parent's uplift with a per-node uplift
correction (ratio, then secant), so that the tile, smoothed over the parent
spacing, matches the parent (ADR-0086). The smoothing is graph diffusion over
land, a Gaussian of about half the parent spacing. The parent surface it was
compared with, however, was sampled smoothly but not smoothed.

Since ADR-0107 every level is as warm as the planet at its height, so heights that
differ between levels show as tones that differ. The test case is Aethelara:
Standard planet (200,000 nodes, no volcanic islands); region 600 km, province
150 km and local 30 km windows at 56.87° E, 30.70° N; 900 pixels each;
`planet-blended-tiles-v13` tiles. In 5 km Gaussian means over shared land:

- the province stood above the region by +205 m where the region is 2–3 km
  high, +334 m at 3–4 km and +531 m above 4 km (−81 m below 1 km). On the
  steepest 30 % of shared ground it stood +244 m above;
- the region stood above the planet surface by +372 m on its steepest 30 %
  (+241 m in 25 km means, +468 m where the planet is 3–4 km high). Over the
  province's ground the planet rises to 2,432 m, but the region drew peaks of
  5,257 m.

The tiles behind those windows (14 at level 1, 19 at level 2 and 19 at level 3)
show three causes.

1. **The target asked for more than the parent.** Smoothing over the parent
   spacing lowers the parent's peaks. At level 2 it lowers them by 41 m where the
   smoothed parent is 3–4 km high and by 96 m above 4 km; at level 1 by 64 m and
   171 m. Relief whose smoothed height reaches the parent's own peaks must stand
   above the parent by more than that. A smooth uplift correction cannot build
   such relief, and the secant chased it into overshoots. The level-2 tiles ended
   255 m and 446 m above the parent smoothed alike in those two height classes.
   Their final calibration error was 216 m RMS, and their mean bias swung
   +590, −13, −122 and −17 m over the iterations. A synthetic parent with peaks
   four parent spacings apart isolates the effect. After three iterations, the
   highest tenth of the relief stood 119 m above the parent smoothed alike and
   323 m above the parent's own peaks.
2. **Eroded basin plains pull the uplift up around them.** Tiles give sediment
   basins no uplift, so no correction can raise their plain, which tiles erode
   below the parent's. The calibration makes up the deficit by raising the uplift
   around the basin, and this window's range runs along one.
3. **Drainage couples the correction.** Uplift at a node raises every node
   upstream of it. Valley floors held low by their outlets therefore gained
   corrections of 5–15, which lifted the ridges above them, and the per-node
   secant overshot in mountain tiles. One level-1 mountain tile's mean error
   went −213, −137, +81 and +172 m over its iterations.

## Decision

1. **Compare like with like.** Enrichment smooths the parent surface over the
   parent spacing, on the tile mesh and over the same land, exactly as it
   smooths the relief, and calibrates the one against the other. A finer level
   keeps the coarser level's height at the coarser spacing and is free below it.
   The tile ring is still held at the parent surface, and tiles still start from
   it. The calibration history reports errors against the smoothed parent.
2. **The update stays ratio, then secant.** It converges fastest where the
   relief answers its own uplift (11 m RMS after four iterations on the
   synthetic test planet).
3. **Basins are left to their own fix.** Holding basin land at the parent's
   plain removes the second cause at its source. Measured with such a floor
   during erosion, which is in development, the province lies 19 m below the
   region in 5 km means (14 m on the steepest 30 %), and the region 15 m above
   the planet on steep ground.
4. The regional tile algorithm becomes `planet-blended-tiles-v14`.

## Alternatives considered

Measured on the 14 level-1 tiles at the default three iterations (secant: 165 m
RMS, +217 m where the smoothed parent is above 3 km), on the synthetic test
planet, and on the windows:

- **Ratio updates only:** 133 m RMS and +127 m on the tiles. They converge
  slowly on the synthetic planet (69 m RMS after four iterations against 11 m),
  and synthetic peaks end 200 m low.
- **Correcting each node by the mean error over its catchment,** which accounts
  for drainage coupling: 118 m RMS and +68 m on the tiles. It is as sluggish on
  the synthetic planet (65 m RMS, peaks 200 m low). Limiting only increases by
  the catchment error was no better.
- **Damping the secant, capping the correction at 3, smoothing it over the full
  parent spacing, estimating slopes regionally, or holding insensitive nodes:**
  over six iterations none settled in mountain tiles, which kept 100–300 m RMS.
  On high ground they swung by up to ±300 m from one iteration to the next.
- **Weighting both smoothed surfaces by the share of uplift each node gets,**
  so that basins do not count: the province came to 13 m below the region on
  steep ground. Its eroded basin plain then sat lower still, however, and the
  planet's lake flooded 17 % of the province. With basin land held at the plain,
  the levels agree as well without it (calibration error 89, 128 and 44 m RMS at
  levels 1–3, against 91, 139 and 82 m with it).
- **Refilling basins to the parent's plain after erosion:** the levels agreed as
  well (−18 m on steep ground), and province lakes fell to 0.4 %. The basin-plain
  work found, however, that a refill dams valleys just outside basins that had
  graded to the eroded plain, and it belongs to that work.
- **Adding the remaining smoothed error after erosion:** this would match
  exactly at the parent spacing. At level 2, however, that error (about 150 m
  RMS, over 2.5 km) would tilt river courses by up to 6 % and dam big rivers.
- **More iterations:** each costs another erosion run, 25 % more per tile.

## Consequences

| On the Aethelara windows | v13 | v14 |
|---|---:|---:|
| Region − planet: all / steepest 30 % | +70 / +372 m | −1 / +39 m |
| The same in 25 km means | +71 / +241 m | 0 / +15 m |
| Region − planet in 25 km means where the planet is 1–2 / 2–3 / 3–4 km high | +109 / +241 / +468 m | 0 / +78 / −148 m |
| Region's highest point over the province's ground (planet: 2,432 m) | 5,257 m | 4,205 m |
| Province − region in 5 km means: all / steepest 30 % | +38 / +244 m | −16 / +69 m |
| The same where the region is < 1, 1–2, 2–3, 3–4 km high | −81, −22, +205, +334 m | −42, −39, +110, +35 m |
| Local − province in 5 km means: all / steepest 30 % | −70 / −114 m | −56 / −77 m |
| Final calibration error, level 1 / 2 / 3 (RMS) | 142 / 216 / 188 m | 113 / 155 / 154 m |
| Province − region luminance: all / steep / gentle | +1.9 / +5.7 / +0.1 | +0.7 / +2.4 / −0.1 |
| Local − province luminance: all / steep / gentle | +3.0 / +2.8 / +0.7 | +2.1 / +1.9 / +0.2 |
| Lakes in the province (share of its land) | 3.2 % | 13.0 % |

Calibration errors in v13 are measured against the unsmoothed parent.

- Regions no longer exaggerate the planet's mountains as much, and provinces the
  region's. Over the province's ground the median slope is now 0.030 in the
  region (0.044 before) and 0.057 in the province (0.080). Each finer level still
  adds relief below the coarser spacing. Spread about the 2.5 km mean is 53 m in
  the region, 130 m in the province and 148 m in the local map.
- Where basins border mountains, the province stood up to 110 m above the region
  (2–3 km high ground here). With basin land held at the planet's plain
  ([ADR-0086](0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-19-sediment-basin-plains),
  `planet-blended-tiles-v15`) it lies 7 m above there, 21 m below the region
  overall and 24 m below on the steepest 30 %.
- Basin plains erode differently in each tile, and blended windows close
  hollows that their lakes fill. Here the province's closed hollows grew from
  5 % to 15 % of its land, and its lakes from 3 % to 13 %. With basin land held
  at the planet's plain, closed hollows cover 2.0 % of the province and lakes
  0.1 %, in its mountains (1,760 m on average).
- Mountain calibration stays noisy. Drainage couples the correction, so mountain
  tiles keep 100–300 m RMS against the smoothed parent, and where a few massifs
  decide a height class, the region can stand 100 m or more off the planet
  (−148 m where the planet is 3–4 km high here).
- A tile's calibration costs one more smoothing pass, 0.17 s at level 1. Tile
  time is unchanged within its spread: three level-1 tiles took 17.7 s before
  and 17.0 s after, and single tiles vary by up to 20 % with the relief they
  erode.
- Tiles, window relief and exported GeoTIFFs change at every level.
