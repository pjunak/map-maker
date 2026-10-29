# Fine-level drainage against reference terrain — 2026-10-29

Decision: [ADR-0114](../adr/0114-regional-hillslopes-at-a-threshold-slope.md).
Catalog entry: D11 in the [decision catalog](decision-catalog.md).

## Question

Province (1 km tiles) and local (200 m tiles) maps are drawn at 117 m and 39 m
pixels. Do their slopes and drainage networks look like real terrain measured
the same way, and where they do not, why?

## Reference terrain

Copernicus DEM, GLO-90 for 60 km windows and GLO-30 for 20 km windows (© DLR e.V.
2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS
by the European Union and ESA; read from the public AWS buckets). Four ranges of
different kinds:

| Range | 60 km window | 20 km window |
|---|---|---|
| Zagros fold belt | 47.1° E 32.9° N | 47.5° E 33.5° N |
| Northern Apennines | 12.0° E 43.5° N | 11.5° E 43.5° N |
| Basin and Range, Nevada | 117.0° W 38.5° N | 116.5° W 38.5° N |
| Annapurna, Himalaya | 83.9° E 28.6° N | 83.75° E 28.6° N |

Aethelara (`planet-3200k-v31`, regional algorithm `planet-blended-tiles-v21`):

- the basin front (56.869° E 30.703° N) and lake shore (143.408° E 19.066° N) of
  the [previous report](2026-10-27-fronts-and-shores-between-levels.md);
- **range A** at 129.966° W 1.862° S, the planet's steepest ground: 6.2 km of
  relief within the 20 km window;
- **range C** at 132.564° W 4.253° S, the same mountain belt on other tiles: 3.5 km
  of relief within 30 km;
- a volcano at 117.091° W 22.238° N, whose edifice is drawn on the tiles rather
  than eroded, as a control.

## Method

Every window is a 1,024-pixel azimuthal equidistant square: 60 km radius at
117 m pixels for province maps, 20 km at 39 m for local maps. DEMs are resampled
onto the same square by area averaging; land is ground above 0.5 m inside the
window's disc. Generated windows are measured on their relief (`elevation_m`),
and province windows also on their drawn relief (`display_relief`). All are
routed alike by steepest descent between pixels (`planet_detail.grid_flow`).

- **Slopes:** central differences; medians and 90th percentiles, also by the
  relief within a 5 km square around each pixel, so ranges of different height
  compare.
- **Drainage density:** channel length per area for channels draining at least
  1 km² (province) or 0.1 km² (local).
- **Hack exponent:** the power of longest upstream flow length against area,
  for channels up to 1,000 times that threshold.
- **Junction angle:** median angle between the two largest donors of each
  confluence, each traced 1 km upstream along its largest donor.
- **Concavity:** the slope–area exponent of median channel slopes between 24 and
  2,400 km² (province) or 1 and 100 km² (local). It is noisy on pixel-routed DEMs.

## Province maps (117 m pixels)

| Window | Relief (m) | Slope median / p90 | at 0.8–1.6 / >1.6 km relief | Density (km/km²) | Hack | Junction | Concavity |
|---|---:|---:|---:|---:|---:|---:|---:|
| Zagros | 2,012 | 4.9° / 19.5° | 14.9° / 21.4° | 0.84 | 0.52 | 53° | 0.06 |
| Apennines | 1,081 | 9.4° / 19.5° | 16.9° / – | 0.70 | 0.51 | 70° | 0.35 |
| Nevada | 1,610 | 3.6° / 18.8° | 17.2° / – | 0.94 | 0.47 | 42° | 0.39 |
| Annapurna | 5,950 | 26.5° / 41.6° | 22.5° / 30.0° | 0.62 | 0.50 | 63° | 0.44 |
| Basin front | 1,828 | 2.3° / 6.7° | – | 0.69 | 0.47 | 45° | 0.64 |
| Lake shore | 97 | 0.2° / 0.3° | – | 0.66 | 0.44 | 38° | 0.23 |
| Range A | 6,191 | 11.0° / 25.6° | 12.4° / 20.4° | 0.64 | 0.46 | 48° | 0.58 |
| Range A, drawn | 6,000 | 16.1° / 32.1° | 17.9° / 24.6° | 0.61 | 0.51 | 56° | 0.50 |
| Range C | 5,920 | 7.9° / 19.7° | 12.2° / 9.4° | 0.75 | 0.45 | 34° | 0.45 |

Province networks are shaped like Earth's: Hack exponents 0.44–0.51 against
0.47–0.52, junctions 34–56° against 42–70°, densities 0.61–0.75 against
0.62–0.94 km/km². Drawn slopes at a given relief are close to the Zagros, Apennines
and Nevada (17.9° against 14.9–17.2° on ground with 0.8–1.6 km of relief).
The highest range is gentler than the Annapurna: 24.6° against 30.0° on ground
with more than 1.6 km of relief. Region maps at these pixels are not compared: a
5 km mesh cannot carry drainage at that scale.

## Local maps (39 m pixels)

| Window | Relief (m) | Slope median / p90 | at 0.8–1.6 / >1.6 km relief | Density (km/km²) | Hack | Junction | Concavity |
|---|---:|---:|---:|---:|---:|---:|---:|
| Zagros | 752 | 5.3° / 21.0° | – | 2.55 | 0.52 | 43° | 0.16 |
| Apennines | 806 | 11.0° / 21.2° | 20.2° / – | 2.13 | 0.53 | 57° | 0.31 |
| Nevada | 1,038 | 8.9° / 26.7° | 19.6° / – | 2.65 | 0.50 | 40° | 0.35 |
| Annapurna | 5,513 | 33.9° / 50.1° | 26.6° / 34.5° | 2.36 | 0.43 | 35° | 0.37 |
| Basin front | 430 | 0.0° / 3.7° | – | 2.38 | 0.52 | 43° | 0.33 |
| Lake shore | 51 | 0.4° / 0.8° | – | 2.10 | 0.45 | 40° | 0.23 |
| Range A | 6,380 | **48.7° / 63.4°** | 38.8° / 48.7° | 1.82 | 0.50 | 60° | 0.19 |
| Range C | 4,387 | 12.1° / 31.8° | 12.0° / 19.9° | 2.42 | 0.47 | 32° | 0.09 |

Local networks are Earth-like too, except range A, which is far too steep: 73 %
of it stands steeper than 40°, where the Annapurna, with as much relief, has a
median of 34°. Without the window's relief warp the range stood at 47.1° / 56.7°,
so the tiles themselves are steep. Stream power with a process area sets each
node's height above its receiver by uplift and erodibility alone and has no
upper limit on slopes. On Earth, landslides hold the hillslopes of fast-rising
ranges near a threshold of about 30–35° however fast rock rises (Burbank et al.
1996; Montgomery and Brandon 2002). Range A rises fast enough that on its summit
tile 92 % of the nodes would stand steeper than 35° above their receivers.

## Change

After every erosion step, regional land is lowered to the highest surface at or
below it that rises at most tan 35° per metre of graph distance
(`limit_slopes`), so steeper ground slides down to its neighbours (ADR-0114,
`planet-blended-tiles-v22`). HEAD (`9423140`) and the change each generated
their own tiles for every window.

| Range A, local map | HEAD | Change | Annapurna |
|---|---:|---:|---:|
| Slope median / p90 | 48.7° / 63.4° | 36.6° / 49.5° | 33.9° / 50.1° |
| at 0.8–1.6 / >1.6 km relief | 38.8° / 48.7° | 35.8° / 36.6° | 26.6° / 34.5° |
| Drainage density (km/km²) | 1.82 | 2.06 | 2.36 |
| Hack exponent | 0.50 | 0.44 | 0.43 |
| Junction angle | 60° | 45° | 35° |
| Concavity | 0.19 | 0.25 | 0.37 |
| Highest point (province 7,096 m) | 8,105 m | 7,715 m | |

Every measure moves towards the Annapurna, and the local map no longer stands a
kilometre above the province's summit. Region maps are unchanged, and province
maps differ by 18–30 m on average (their means by less than 3 m). At range C the
limit lowers little (local p90 31.8° → 31.4°); at the volcano nothing changes.

Calibration (ADR-0109) keeps predicting each tile's response from uncapped
steps. Capping each step at the threshold in that model, as the evolution
does, predicted the response worse on range A's summit tile: the correlation
between predicted and actual change of the smoothed relief was 0.68, 0.29 and
0.65 over three updates, against 0.79, 0.47 and 0.74 uncapped.

## What remains

- **Calibration in threshold terrain.** On range A the local map stands 225 m
  above the province in 5 km means (HEAD +9 m), with 319 m RMS (153 m), and is
  13.0 luminance levels brighter (HEAD 7.8). Level-3 tiles there end 203 m RMS
  off their parents on average (175 m); within 10 km of the summit, the summit
  tile's error changes sign from one iteration to the next by 250–600 m. Halving
  each update (353 m RMS, +159 m mean), halving only the last (312 m, +96 m),
  dividing by the measured gain (348 m, +83 m) and six iterations (315 m, −15 m,
  still swinging ±200 m between iterations) did not settle it; HEAD's tile ends
  at 284 m. At range C the local map is 17 m above its province (HEAD 20 m) and
  at the volcano 38 m (36 m).
- **Highest province slopes.** Province maps of the steepest range are gentler
  than the Annapurna's (above).
- **Cost.** A local map's new tiles take 5–26 % longer (range A 80 → 101 s, range
  C 101 → 124 s, the volcano 81 → 85 s): the limiter takes 14.5 ms per step on
  a 64,000-node tile, routing 1.9 ms. Heapifying its seeds did not help.

## Disposition

Regional hillslopes stand no steeper than 35° between nodes. Province and local
drainage networks now match the reference ranges in shape and, on the steepest
ground, in slope. Calibration in threshold terrain is recorded as open work.
Scripts, measurements and images are kept locally in
`artifacts/research-notes/fine-drainage/`, not tracked in the repository.
