# ADR-0109: Fit regional uplift corrections to the relief uplift builds along the drainage

- Status: accepted (experimental product path)
- Date: 2026-10-19
- Supersedes decision 2 of
  [ADR-0108](0108-calibrate-regional-relief-against-the-parent-smoothed-alike.md)
  (ratio, then a per-node secant); refines
  [ADR-0086](0086-regional-planet-detail-from-blended-tiles.md) (tile calibration).

## Context

A regional tile is eroded from its parent's uplift times a per-node correction,
which is calibrated so that the tile, smoothed over the parent spacing, matches
the parent smoothed alike (ADR-0108). The correction started at 1, took one ratio
step and then per-node secant steps, three in all by default.

That converged on smooth ground (11 m RMS after four steps on the synthetic test
planet) but not in mountains. Uplift at a node raises every node upstream of it,
and the secant ignored this coupling:

- valley floors held low by their outlets barely answer their own uplift, so a
  secant slope of a few metres per unit correction proposed threefold jumps, and
  smoothing over half the parent spacing spread them onto the ridges above;
- on Aethelara (Standard 200,000-node planet; the 14 level-1 and 19 level-2 tiles
  serving the windows at 56.87° E, 30.70° N) mountain tiles kept 100–300 m RMS,
  and one tile's mean error went −213, −137, +81 and +172 m;
- level parents carry the planet's uplift, which builds finer levels two to three
  times too high, so the first run of the level-2 tiles stood 420–1,880 m RMS off
  their parents.

Implicit stream power (n = 1) settles each node U dx / (K (A + A0)^m) above its
receiver. On a level-1 mountain tile, 80 % of the measured steps match that within
1–3 %, so a node stands above where it drains by the sum of those steps down its
path.

## Decision

1. **A start from the steady state.** Before the first erosion run, the starting
   surface is routed, and the steady state its drainage settles to (the sum of
   the steps down every path, from the fixed level where it ends or a basin
   floor that holds it) is fitted as below. No erosion run is added.
2. **A fit weighted by the relief uplift builds.** A relative change of the
   correction raises a node by the smoothed height its uplift steps build above
   where its path ends or a deposit holds it. The change is fitted by least
   squares over a neighbourhood, weighted by that height, so ground that uplift
   raised far decides and ground standing barely above its outlet (less than
   50 m) holds back. It is applied as a factor exp(change), at most 3 per step.
   The correction stays within 0.02–10.
3. **Over two valley spacings.** The neighbourhood spans two valley spacings,
   the square root of the process area (49 km at level 1, 10 km at level 2), and
   never less than half the parent spacing. Fitted finer, corrections chased
   divides that jump between valleys from one run to the next.
4. **Coupling where the drainage model holds.** Two further passes count the lift
   that corrections downstream give the ground above them, weighted by trust: 1
   where the last predicted change of the smoothed relief held to within 20 %, 0
   where it missed by 70 % or more.
5. The regional tile algorithm becomes `planet-blended-tiles-v16`.

## Alternatives considered

Measured on the same tiles at the default three iterations, against the parent
smoothed alike. The final RMS of the ratio-then-secant update was 165 m at level 1
and 163 m at level 2 on `planet-blended-tiles-v14`.

- **Gauss-Newton on the fixed-network model** (least squares on the full node
  Jacobian): a mountain tile ended at 468 m RMS, against 322 m. There, even
  uniform uplift 10 % higher reroutes 6 % of the receivers and changes the relief
  0.87 times as predicted; smooth bumps reroute 17–33 %.
- **Full coupling, without trust:** best on the synthetic planet (5 m RMS after
  four steps), but 410 m RMS at level 2; damped, delayed or regularised, it
  still lost to the local fit there.
- **Local fit over half the parent spacing:** 120 and 138–147 m. The best width
  differed by level, from half the parent spacing at level 1 to twice it or
  more at level 2, as valley spacings do.
- **Measured gains (secant) per tile or per neighbourhood:** worse at level 1 or
  on level-2 high ground.
- **A linear rather than exponential starting factor:** a closer start at level 2
  (242 against 311 m) but a worse end (115 against 99 m).
- **Keeping the best run rather than the last:** 5 m better at level 2 and nothing
  at level 1; not adopted, since it hides rather than removes the swings.

Level 2 has a noise floor. On a level-2 mountain tile, 0.1 % more uplift moved
the smoothed relief by 14 m RMS, and 1 % by 65 m, as divides on high ridges jumped
between valleys. A level-1 mountain tile answered nearly linearly (1 % moved it
23 m RMS, 16 m on average).

## Consequences

| On `planet-blended-tiles-v15` tiles and windows (Aethelara as above) | v15 | v16 |
|---|---:|---:|
| Mean final calibration error per tile, level 1 / 2 (RMS) | 84 / 125 m | 43 / 92 m |
| Worst tile, level 1 / 2 | 200 / 210 m | 87 / 227 m |
| Mean bias per tile (absolute), level 1 / 2 | 20 / 38 m | 5 / 8 m |
| First erosion run, level 1 / 2 (mean RMS) | 231 / 1,067 m | 145 / 267 m |
| High ground (top tenth of each tile): mean absolute bias, level 1 / 2 | 88 / 73 m | 26 / 42 m |
| The same: range over tiles, level 1 | −61 to +383 m | −96 to +45 m |
| The same: range over tiles, level 2 | −144 to +169 m | −46 to +234 m |
| The same, pooled over tiles, level 1 / 2 | +99 / −19 m | −12 / +35 m |
| Synthetic test planet, four steps (RMS) | 156, 120, 24, 16, 11 m | 75, 34, 17, 11, 8 m |
| Province − region in 5 km means: all / steepest 30 % | −21 / −24 m | +7 / +20 m |
| The same where the region is < 1, 1–2, 2–3 km high | −17, −27, +7 m | +2, +5, +26 m |
| Spread of that difference where the region is 2–3 km high | 164 m | 61 m |
| Region − planet in 25 km means: all / steepest 30 % | −3 / +17 m | +5 / +21 m |
| Highest point over the province's ground: region / province (planet 2,438 m) | 2,863 / 4,064 m | 3,127 / 3,506 m |
| Province − region luminance on steep ground; local − province | +1.2; +5.0 | +0.3; +6.8 |
| Spread between overlapping tiles, level 1 / 2 (mean) | 40 / 117 m | 45 / 95 m |

- Mountain tiles converge: the worst level-1 tiles fall from 178–200 m to
  68–87 m, and no level-1 tile ends worse than 87 m. Level-2 tiles end at about
  the noise of their own erosion. Two of them carry the pooled level-2
  high-ground bias (+184 and +234 m): on the highest ground of one, the smoothed
  relief went +371, +478, −78 and +325 m over its runs, the last step with its
  correction there unchanged.
- Peaks follow the parent more closely at the parent spacing, while relief below
  it stays free. On the synthetic planet with peaks four parent spacings apart,
  the relief smoothed alike ends 8 m above the parent on its peaks (35 m below
  before), and its own peaks stand 115 m above the parent's (10 m before).
- Blends of tiles still close hollows where tiles disagree about an outlet. The
  region window here now draws two such lakes, 1,470 km² on a basin plain whose
  outlet the raised ranges beside it closed, and 2,240 km² on low coastal ground;
  its lakes cover 0.4 % of its land (none before). On the synthetic planet,
  overlapping windows draw the same rivers on 90.0 % of the river pixels near
  their edges (93.1 % before) and on 92.6 % inside them (91.4 %).
- Calibration adds no erosion run. Its smoothing uses sparse products, several
  times faster than the neighbour gathering of `smooth_over_land`. Tile time is
  unchanged within its spread: 15.7 → 16.4 s at level 1 and 15.0 → 15.3 s at
  level 2 on average, six tiles at a time.
- Tiles, window relief and exported GeoTIFFs change at every level.
