# Regional tiles on world-fixed nodes — 2026-10-26

Decision: [ADR-0113](../adr/0113-regional-tiles-on-world-fixed-nodes.md). Catalog
entry: D25 in the [decision catalog](decision-catalog.md).

## Question

Each regional tile was eroded on a jittered hexagonal lattice in its own azimuthal
plane, with node jitter, rock texture and starting roughness seeded per tile.
Overlapping tiles therefore held different nodes, and their Wendland blend
disagreed: blend hollows (ADR-0086, "hollows of the blend"), ridges up to 1 km
apart, 4–45 m on plains ([nested levels](2026-10-19-nested-regional-levels.md)).
Since ADR-0112, windows route on world-fixed cells of an equiangular cubed sphere
(`WorldGrid`). Does building every tile of a level on that grid's nodes remove the
disagreement, and at what cost?

## Candidate

- **Nodes.** A tile takes the `WorldGrid` nodes within its support and halo, less
  0.6 spacings, and keeps its ring of fixed nodes at the rim. A cell holds as much
  ground as a lattice node (side √(√3/2) spacings), so tiles keep the lattice's
  node count on average.
- **Triangles.** Delaunay in the stereographic plane about the tile's centre, which
  is the triangulation on the sphere. Two level-1 patches 300 km apart at Aethelara
  share 42,551 nodes at identical positions and all 75,702 triangles away from both
  rings.
- **Level parents** take the coarser level's world-fixed nodes the same way.
- **Texture and roughness.** Rock texture is seeded per level, with its wavelength
  from the nominal spacing rather than each mesh's own estimate. Starting roughness
  is hashed from the cell and the level seed.

Overlapping tiles therefore start from the same ground on the same nodes. They
still differ by their rings, by where water enters, and by the uplift correction
each fits for itself.

## Direction bias and node density

Steepest descent on tilted planes on a 300 km patch at Aethelara, every 5° from
0° to 85°, three noise draws each. The figure is the mean flow direction's
deviation from the slope:

| Nodes | Largest deviation | RMS over directions |
|---|---:|---:|
| Jittered hexagonal lattice (0.35 spacings, Gaussian) | 0.47° | 0.28° |
| World cells, nodes within 0.4 of a cell of its centre (routing cells) | 4.97° | 3.19° |
| World cells, within 0.45 | 2.67° | 1.65° |
| World cells, anywhere in the cell (adopted) | 1.39° | 0.75° |

Flow on the routing cells' jitter bends towards the grid's axes, at this place
skewed by the cube face. Nodes anywhere in their cells keep the bias near the
lattice's.

Equiangular cells vary in area by 1.41, so node density follows the place on the
cube. A 630 km level-1 patch holds 61,355 nodes at Aethelara and 57,847 on the
lattice. 200 km patches at three places hold 0.86–1.10 times the lattice's count.

## Synthetic test planet

The 20,000-node test planet, with the test levels: 30 km spacing on 1,500 km tiles,
then 10 km on 300 km tiles. Level 1 is measured in six 800 km discs around the
six window-pair centres, level 2 in one 300 km disc. Spread is the range of the
tiles weighing 0.25 or more where two or more do. Hollows are measured on the blend
sampled through the window's relief warp, with the sea, parent lakes and the rim
as outlets.

| | HEAD (v19) | Jitter 0.4 | Jitter 0.5 (adopted) |
|---|---:|---:|---:|
| Level 1 spread, mean / 90th pct / max (m) | 43.0 / 96 / 696 | 6.2 / 17 / 132 | 6.3 / 17 / 121 |
| Level 1 hollows deeper than 3 / 10 m (km²) | 52,982 / 26,542 | 25,787 / 3,206 | 25,349 / 2,809 |
| Level 2 spread, mean / 90th pct / max (m) | 33.0 / 80 / 321 | 8.7 / 20 / 89 | 7.2 / 16 / 65 |
| Level 2 hollows deeper than 3 / 10 m (km²) | 255 / 2 | 180 / 0 | 318 / 18 |
| Final calibration error, level 1 / 2 (RMS, m) | 36.3 / 15.8 | 36.6 / 14.5 | 36.3 / 14.9 |
| Tile time, level 1 / 2 (s) | 8.2 / 4.2 | 8.5 / 4.3 | 7.4 / 3.9 |
| Six window pairs: B's river pixels near / on A's | 100 / 99.66 % | 100 / 99.62 % | 100 / 99.64 % |

Windows already share tiles and routing cells (ADR-0112), so pair agreement
measures window independence and does not move.

## Aethelara

The `planet-3200k-v31` build (6,000 km radius, 3.2M nodes) at 56.869° E 30.703° N.
Region, province and local windows of 600, 150 and 30 km at 900 pixels, and course
windows of 30, 20 and 20 km at 1,024 pixels. Both versions generated their tiles
afresh into scratch caches, six at a time. Measures are taken on the routing cells
at each window's pixel size.

| HEAD → world-fixed nodes | Region (level 1) | Province (level 2) | Local (level 3) |
|---|---:|---:|---:|
| Spread, mean (m) | 47.6 → 7.8 | 168 → 125 | 2.4 → 2.9 |
| Spread, median | 19.3 → 0.5 | 103 → 34 | 0.03 → 0.002 |
| Spread, 90th percentile | 128 → 28 | 454 → 322 | 1.9 → 0.12 |
| Spread, 99th percentile | 321 → 80 | 747 → 1,224 | 50 → 87 |
| Spread, max | 485 → 162 | 1,036 → 1,642 | 215 → 210 |
| Rivers of one tile within 1.5 spacings of the other's | 95 → 100 % | 71 → 87 % | 72 → 96 % |
| Their distance, median | 2.9 km → 0 | 0.80 km → 0 | 163 m → 0 |
| Hollows of the warped blend deeper than 3 / 10 m (km²) | 8,592 / 3,334 → 10,845 / 2,376 | 2,096 / 539 → 3,363 / 1,248 | 0.5 / 0 → 3.1 / 1.6 |
| The same, blend sampled without the warp | 5,495 / 955 → 2,794 / 425 | 2,723 / 739 → 953 / 205 | |
| Final calibration error per tile, mean / worst (RMS, m) | 62 / 96 → 67 / 132 | 113 / 236 → 120 / 233 | 44 / 168 → 38 / 105 |
| Mean absolute bias per tile (m) | 4.5 → 5.6 | 11.1 → 6.8 | 6.0 → 4.7 |
| Tile time, six at a time (s) | 30 → 31 | 30 → 31 | 27 → 16 |

Rivers are each tile routed alone on its own mesh, compared where both tiles of a
pair weigh 0.25 or more: nodes draining four process areas, matched against the
other tile's nodes draining two. Tiles hold 6 % more nodes here than on the
lattice. The level-3 time was not investigated.

**Spread by height** (mean, m):

| Ground | Region | Province |
|---|---:|---:|
| Below 1 km | 23 → 1.0 | 29 → 10.5 |
| 1–2 km | 93 → 12.6 | 164 → 68 |
| 2–3 km | 56 → 20 | 286 → 254 (90th pct 610 → 786) |
| Above 3 km | 80 → 31 | 300 → 254 |

**Basin plain.** On full-basin ground in the 36 km box, overlapping tiles differ by
0.50 → 0.0002 m at level 2 and 0.13 → 0.017 m at level 3. Plain means move by under
0.2 m. The big river's channel in province tiles 7721 and 7577, where both weigh a
quarter or more, lies 0.54 km apart on average (1.10 km at most) on HEAD and in the
same place now. Local tiles 191829 and 192816 cut it 0.11 / 0.28 km apart, now
0.01 / 0.12 km.

**Courses across levels.** Within 20 km of the centre, the province's big-river
course lies 1.97 km (5.87 at most) from the region's on HEAD and 1.03 km (3.62)
now. The local course lies 1.18 km (4.13) and 1.36 km (5.44) from it. On HEAD all
three leave the 20 km circle within 0.5 km of each other, but the province swings
3–4 km south of the others in the east. Now the three run together through the
middle and east and part near the north-west exit, where the province and local
courses leave 3.7 and 5.4 km from the region's.

**Maps.** Region, province and local maps keep their look. In the province,
valleys read a little crisper, where overlapping tiles no longer average valleys
that lie apart. The province draws 163 lake pixels instead of 454.

## What still differs

**Uplift corrections.** On the test planet's four tiles around its land centre,
overlapping tiles' targets agree within 0.06–1.3 m on average. Their uplift
corrections, fitted by each tile within its own domain, differ by 4–10 %
(log ratio), and height differences follow them (correlation 0.5–0.8). The worst
Aethelara pair is the same in both versions: province tiles 7810 and 7954, on
2–3.6 km mountains (mean difference 350 m on HEAD, 524 m now). At their 1,287 shared
overlap nodes the targets are identical, the corrections differ by 16 %, and
neither tile's calibration settles: 209, 243, 162 and 179 m, and 240, 187, 218 and
233 m RMS over its runs. This is ADR-0109's level-2 noise floor, where divides on
high ridges jump between valleys. Points of the province window whose tiles differ
by more than 1 km rose from 2 to 865 of about 40,000, 854 of them in that pair.
Points more than 300 m apart fell from 8,523 to 4,523.

**Hollows through the relief warp.** A tile alone, sampled through the window's
warp on routing cells, already holds hollows. Level-1 tile 291 holds 5,680 km²
deeper than 3 m on HEAD and 7,720 km² now, and 2,767 and 1,719 km² deeper than
10 m. Sampled without the warp, it holds 3,390 / 903 and 1,436 / 138 km². The
warp stretches cells apart, so cells miss narrow valley floors. In the province,
hollows of the warped blend deeper than 10 m lie where only one tile weighs 0.25 or
more, or the tiles agree within a metre: 442 km² on HEAD, 1,143 km² now. Where
tiles differ by more than a metre they cover 97 and 105 km². They come from resampling single tiles, not from the blend.
Windows fill them as plains (ADR-0086), so they hold no lakes. They are the
one-cell ponds of the [nested levels report](2026-10-19-nested-regional-levels.md#open-after-3443ff2).

## Decision

Adopted as [ADR-0113](../adr/0113-regional-tiles-on-world-fixed-nodes.md),
`planet-blended-tiles-v20`. Tiles no longer differ by geometry, texture or
roughness. Agreement improves several times at level 1, overlapping tiles hold
plains and rivers alike at every level, and the blend's own hollows halve. What
remains is each tile's own uplift correction, which mountain tiles at level 2 never
settle. A correction shared by overlapping tiles (domain decomposition, or fitting
it on the level parent) is the next step.

## Files

Scripts and outputs are kept locally in `artifacts/research-notes/tile-grid/`:

- `tile_eval.py` composes windows and records tile histories;
- `tile_metrics.py` measures spread, hollows, rivers, calibration and courses;
- `grain_jitter.py` measures direction bias;
- `node_diag.py`, `pair_diag.py`, `tail_diag.py`, `hollow_diag.py` and
  `hollow_where.py` are the diagnostics;
- comparison images (`cmp-*.png`, `crop-*.png`, `courses.png`).
