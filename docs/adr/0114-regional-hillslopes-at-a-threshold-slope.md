# ADR-0114: Hold regional hillslopes at a threshold slope

- Status: accepted (experimental product path)
- Date: 2026-10-29
- Refines: [ADR-0086](0086-regional-planet-detail-from-blended-tiles.md) (tile
  erosion). Keeps the calibration of
  [ADR-0109](0109-fit-regional-uplift-corrections-along-the-drainage.md).

## Context

Regional tiles erode by implicit stream power with a process area. It sets each
node's height above its receiver by uplift and erodibility alone, with no upper
limit on slopes. On Earth, landslides hold the hillslopes of fast-rising ranges
near a threshold of about 30–35° however fast rock rises (Burbank et al. 1996;
Montgomery and Brandon 2002).

Measured against Copernicus DEM
([report](../research/2026-10-29-fine-level-drainage-against-reference-terrain.md)),
province and local drainage networks on Aethelara are shaped like Earth's, but
the local map of its steepest range (129.97° W 1.86° S, 6.2 km of relief within
20 km) stood at a median slope of 48.7° and a 90th percentile of 63.4°. The
Annapurna range, with as much relief, stands at 33.9° and 50.1° at the same 39 m
pixels.

## Decision

1. **Threshold hillslopes.** After every erosion step, regional land is lowered
   to the highest surface at or below it that rises at most tan 35° per metre of
   graph distance (`limit_slopes`): a multi-source Dijkstra from the nodes that
   stand below a too-steep neighbour. Fixed nodes keep their level, and land
   stays at its floor and on held plains.
2. **Every level.** The rule holds at every regional level; region and province
   tiles rarely reach it.
3. **Calibration unchanged.** The calibration model still predicts each tile's
   response from uncapped steps.
4. The regional algorithm becomes `planet-blended-tiles-v22`.

## Alternatives considered

- **Capping each node's step above its receiver within the implicit sweep:**
  receivers change from step to step, so tiles kept slopes of 42°.
- **Nonlinear hillslope diffusion** (Roering et al. 1999): it approaches the
  threshold smoothly but needs explicit time steps at node spacing, many per
  erosion step.
- **Limiting slopes only when drawing:** tiles and their drainage would keep the
  steep relief.
- **Capping steps in the calibration model too:** on the steepest summit tile it
  predicted the relief's response worse (correlation 0.68, 0.29 and 0.65 over
  three updates, against 0.79, 0.47 and 0.74 uncapped).
- **Damping calibration updates** (by half, by half on the last update, by the
  measured gain) **or six iterations:** none settled the summit tile in three
  iterations (below).

## Consequences

| Steepest range, local map | v21 | v22 | Annapurna |
|---|---:|---:|---:|
| Slope median / p90 | 48.7° / 63.4° | 36.6° / 49.5° | 33.9° / 50.1° |
| Drainage density (km/km²) | 1.82 | 2.06 | 2.36 |
| Hack exponent | 0.50 | 0.44 | 0.43 |
| Junction angle | 60° | 45° | 35° |
| Highest point (province 7,096 m) | 8,105 m | 7,715 m | |

- Local maps of the steepest ranges stand at the slopes of Earth's threshold
  landscapes, and their drainage measures move towards the Annapurna's. The
  local map no longer stands a kilometre above its province's summit.
- Region maps are unchanged. Province maps differ by 18–30 m on average, and
  local maps of less steep ranges change little.
- A local map's new tiles take 5–26 % longer.
- Calibration in threshold terrain stays noisy. On the steepest range the local
  map stands 225 m above its province in 5 km means (v21: 9 m) and reads brighter,
  because one summit tile's error swings by several hundred metres between
  iterations. On a less steep range of the same belt it stands 17 m above
  (v21: 20 m). This is recorded as open work.
