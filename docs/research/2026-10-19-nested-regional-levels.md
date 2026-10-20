# Nested regional levels — 2026-10-19

Catalog entries: D06, D25, D28 and D30 in the [decision catalog](decision-catalog.md).
Register entries: [T20](terrain-method-decisions.md#t20---straighten-regional-rivers-in-routing-over-display-detail-or-by-a-plain-warp),
[T21](terrain-method-decisions.md#t21---hold-regional-basin-plains-at-the-sampled-parent-surface-or-refill-them)
and [T23](terrain-method-decisions.md#t23---carry-a-big-rivers-course-through-every-regional-level).

## Question

Do the nested maps of one place (region at 5 km, province at 1 km, local at 200 m)
draw the same big rivers, plains and mountains, at the same heights and in the same
tones? Where they did not, what caused it?

This report gathers the evidence of the 2026-10-18/19 changes that answered it, in
the order they were made. Each change's decision and its main figures are already
in an ADR, the catalog or the register, linked below. This report keeps the shared
setting, the figures recorded nowhere else and the follow-ups left open.

## Setting

- **Place.** Aethelara, 3.2M-node build (`planet-3200k-v30`, from 47d5009 `-v31`),
  at 56.869° E 30.703° N. A river draining about 160,000 km² crosses a
  sediment-basin plain there from south-east to north-west, below a mountain front.
- **Windows.** Region, province and local windows at that centre, from 20 km to
  600 km in radius. Tiles were regenerated in scratch caches for every variant.
- **Agreement.** Overlapping windows on the 20,000-node synthetic test planet: one
  pair in `test_overlapping_windows_draw_the_same_rivers`, and six pairs 120 km
  apart for the edge and inside shares of matching river pixels.
- **Luminance** is compared on ground both windows show, the finer averaged to the
  coarser one's pixels, on a 0–255 scale.
- **Load.** Several sessions ran at once, so no timings are reported.

Notes, measurement scripts and before/after images are kept locally in
`artifacts/research-notes/`, not tracked in the repository.

## Changes

| Commit | Change | Identifier | Decision |
|---|---|---|---|
| dd477ca | Inherited rivers enter nested windows | tiles v10 | [ADR-0086 2026-10-18](../adr/0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-18) |
| bbaa2c5 | Meanders laid along a smoothed valley line | display | D28 |
| 9f28961 | Basin fronts dissected below the planet mesh | tiles v11 | [ADR-0086 2026-10-18](../adr/0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-18) |
| c998e32 | Colour and shading see slopes scaled to level 1 | display | [ADR-0105](../adr/0105-regional-levels-see-level-1-slopes.md) |
| 040189c | Valleys wound below the tile mesh | tiles v12 | [ADR-0106](../adr/0106-wind-regional-valleys-below-the-tile-mesh.md), [report](2026-10-12-straight-display-lines.md#straight-regional-rivers--2026-10-18) |
| c9cd6d6 | Smooth samples held within their parent triangle | tiles v13 | [ADR-0086 2026-10-19](../adr/0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-19) |
| 8d3443f | Big rivers fill and cross the hollows they enter | windows | D30 |
| 4a0b417 | Every level as warm as the planet at its height | display, climate | [ADR-0107](../adr/0107-regional-temperatures-follow-height-above-the-planet.md) |
| afafc22 | Calibration against the parent smoothed alike | tiles v14 | [ADR-0108](../adr/0108-calibrate-regional-relief-against-the-parent-smoothed-alike.md) |
| 47d5009 | Planet basin plains graded towards their outlets | relief v31 | D06 |
| 13b06f7 | Regional basin plains held at the planet's plain | tiles v15 | [ADR-0086 basin plains](../adr/0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-19-sediment-basin-plains), T21 |
| 64574be | Uplift corrections fitted along the drainage | tiles v16 | [ADR-0109](../adr/0109-fit-regional-uplift-corrections-along-the-drainage.md) |
| 5dab756 | Hollows of the tile blend drawn as plains | tiles v17 | [ADR-0086 hollows](../adr/0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-19-hollows-of-the-blend) |
| 3443ff2 | One big-river course through every level | tiles v18 | [ADR-0086 one course](../adr/0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-19-one-river-course-through-every-level), T23 |

"Tiles" is `planet-blended-tiles-vN` and "relief" `sphere-mesh-stream-power-vN`.

## Rivers lost at the window rim (dd477ca)

The local map drew no big river. The valley never moved: the planet, level 1,
level 2 and the level-3 patch put the river within about 3 km of each other. The
water was lost on its way into each window:

1. **Rim outlets.** Every cell beyond the window circle was an outlet at 0 m, so
   96–99.9 % of the rim inflow left through the pixel it entered, at every level.
2. **Inflow at exits too.** Inflow sampled the parent's drainage at every rim
   pixel: 316,000 km² entered a 60 km window that one 160,000 km² river crosses.
3. **Small level parents.** They reached 1.25 times the area they serve, 6 km
   beyond a local window. A planet river enters at its first node inside, up to the
   longest planet step in (30.8 km on v30; jittered Fibonacci edges reach 2.6
   spacings). The river started 22.6 km from the centre of the 25 km routing
   circle, so it never crossed into the window.
4. **Double weighting.** Tiles multiplied inherited drainage, already weighted by
   runoff, by the local runoff weight again.

Largest drainage of the main river in each window:

| Level (window radius) | Before | After |
|---|---:|---:|
| Region (60 km) | 13,000 km² | 169,000 km² |
| Province (60 km) | 32,000 km² | 194,000 km² |
| Local (20 km) | 13,400 km² | 165,000 km² |

The straight north-west front beside the river was not a tile, patch or calibration
seam either. It is where the planet's basin depth, held on its 12 km mesh, crosses
200 m (`BASIN_FULL_M`): inside it uplift stops and erodibility drops by 97 %.
Sampled triangle-linearly, that contour is straight within each planet triangle.
Smooth sampling alone only rounded its kinks, and was not committed.

## Basin fronts below the planet mesh (9f28961)

- Basin depth stays on the planet mesh and is sampled smoothly at points displaced
  by rotated noise octaves, from four planet spacings (amplitude half a spacing)
  down to the level's finest; octaves from one spacing down are capped at the
  coast's steepness.
- SciPy's Clough-Tocher gradient estimate has an absolute tolerance. Uplift in
  m/yr (about 1e-4) therefore kept almost no gradient and interpolated 13 times
  worse than linear; sampled at unit scale it is 13 times better. Level-1 seeding
  had carried this defect since 2026-10-13.
- On the synthetic planet the unrefined front is exactly straight. Refined, its
  roughness below the parent spacing is 3.0–4.6 % of that spacing at three levels,
  within a factor of 1.36 between levels over six seeds. On Aethelara the margin
  moves 3.9 km at the median and 8 km at the 95th percentile.
- **Regression.** Levels 2 and 3 lost the river again, which ended in a playa at
  its entry and a lake at its exit. Overlapping level-2 tiles held it about 50 m
  apart on average, before and after, and their blend left hollows up to 30 m deep
  (6 m before). Windows ended every river in a pond deeper than 10 m, whatever
  flowed in. Reverting the smooth level-parent forcing did not bring it back.
- The single test pair fell from 95.8 % to 93.7 % (the sampler fix alone 94.6 %,
  the warp alone 95.9 %, unpadded routing 92.4 %), so its bar went from 94 % to
  93 %. Over six pairs agreement did not change (edge 0.909 against 0.908, inside
  0.932 against 0.934).

## Meanders of wide rivers (bbaa2c5)

At 39 m pixels the 1,500 m³/s main stem drew as a self-crossing ribbon. Its routed
D8 path was clean: no turn over 90°, sinuosity 1.1–1.4 over 50 pixels, 79 % of it
on filled flats, no rings. Bends of up to about 0.8 of a 53-pixel wavelength were
offset along the normal of each pixel step, which flips at every D8 step, so the
curve folded. Steep reaches inside a meandering chain had a wavelength near zero
and drew a pixel-scale random walk.

The fix lays sine-generated bends, in closed form, about the path smoothed over half
a wavelength. Each bend lobe draws its own swing (0.7–1.8 rad, times a reach factor
of 0.55–1.05 over about four bends), wavelengths vary by ±35 %, and the swing shrinks
where the valley line turns tightly. On the main stem afterwards:

- no two points more than three widths apart along the river come within one width
  of each other (closest 6.2 px, width 4.9 px);
- the drawn river is 1.32 times the D8 path and 1.73 times the chord;
- it stays within 18 px (0.7 km) of the D8 path.

Where bends are too small to draw (wavelength 2–5 px at level 1) rivers now follow
the routed path exactly. That exposed straight valleys in the tile relief, which
ADR-0106 winds ([report](2026-10-12-straight-display-lines.md#straight-regional-rivers--2026-10-18)).

## Overshooting cubics and the hollows big rivers enter (c9cd6d6, 8d3443f)

On v12 tiles the province window still lost the river after 71 pixels, and the
local window drew a 3,326-pixel playa on it. Diagnosed on v11 tiles, the cause lay
in the tiles, not in the window's ponds:

- In the local window the river entered on the south-east rim and left 25 pixels
  later. Its valley floor (53–66 m) lay 40–50 m below a barrier at 105.5 m on the
  parent's course, so a pond-spill rule alone could not have kept it.
- Local tiles 192816 and 191829 held the river 50 m apart over the same ground. Their
  targets came from the level-2 patch, whose surface along the river ran
  130, 9, 113, 34 and 99 m.
- Province tiles 7721 and 7577 held it 100–170 m apart: 7721 graded it to 1 m over
  60 km towards four ring nodes at 0 m. Across a 1,124 to 160 m mountain front its
  smooth target at those nodes was −8 to −75 m where linear values were 200–255 m,
  and clipped to 0 m they became a sea-level outlet. 5 % of the tile's nodes lay
  below their parent triangle's lowest corner, 401 of them by more than 100 m.

Smooth samples are now held within their triangle's corner values (v13). Windows let
a hollow overflow when its catchment's runoff beats what its area evaporates, cross
it as plain when the river's sediment (0.1 mm a year) would fill it within
10,000 years, and let no water out where a big river comes in. The river then
crossed the province and local windows with no playa or lake. Six synthetic pairs
went from 92.9 % to 95.6 %. Overlapping tiles over the window differ by 83 m at the
90th percentile in the province (96 m before) and 33 m locally (47 m); ridges still
differ by up to 1 km.

## Tone and temperature across levels (c998e32, 4a0b417)

[ADR-0105](../adr/0105-regional-levels-see-level-1-slopes.md) and
[ADR-0107](../adr/0107-regional-temperatures-follow-height-above-the-planet.md) hold
the causes and results. Figures not recorded there:

- **Terrain position.** It took 3 and 15 km means over relief that is −200 m beyond
  the window's disc, so a flat plain in a 30 km window scored 0.30–0.81 instead of 0.
  Ridges count as drier, and the local plain drew 8 levels paler and yellower.
- **Region to province** improved from +2.7 to +1.2 with ADR-0105, leaving the
  region's steep ground about 6 levels darker than the province's.
- **Forest carried that gap.** On the steepest 30 % of shared ground (by level-1
  tile slope), forest cover was 0.63 in the region and 0.47 in the province;
  switching forest off reversed the gap (−2.8). The forests differed by dryness:
  evapotranspiration 635 against 791 mm, from window climates of 3.0 and 6.7 °C.
  Snow, tundra and rock each moved the gap by less than one level.
- **Display relief.** Valley carving accounted for 749 m of the region's 822 m drop
  below its tiles on steep ground, 43 % of the 1,740 m detail amplitude, and noise
  for 72 m; the province's display relief lay 282 m below its tiles. The display
  lapse turned that into 5.3 °C of warming in the region and 1.8 °C in the province.
- **The higher tiles.** After ADR-0107 the province drew high mountains brighter
  (+10.3 on steep ground), because its tiles stood 425 m above the region's on steep
  ground (in 5 km means +455 m where the region is 3–4 km high, +722 m above 4 km,
  −38 m below 1 km). Local tiles kept the province's mean (−20 m). That led to
  ADR-0108; its table holds the tone after it.

## Heights, basin plains and calibration (afafc22, 13b06f7, 64574be)

[ADR-0108](../adr/0108-calibrate-regional-relief-against-the-parent-smoothed-alike.md),
[T21](terrain-method-decisions.md#t21---hold-regional-basin-plains-at-the-sampled-parent-surface-or-refill-them)
and [ADR-0109](../adr/0109-fit-regional-uplift-corrections-along-the-drainage.md)
hold the measured windows. Additional figures:

- **Calibration target.** Smoothing over the parent spacing lowers the parent's
  peaks by 41 m at 3–4 km height and 96 m above 4 km at level 2. Chasing the
  unsmoothed target, the secant oscillated: level-2 bias +590, −13, −122 and −17 m
  over its iterations, ending at 216 m RMS.
- **Basin plains, over the 36 km box** (1,187 of 1,369 points in full basins).
  On the graded v31 planet (box plain 717.5 m), tiles v14 against v15:

  | | Region | Province | Local |
  |---|---:|---:|---:|
  | Plain mean, v14 | 383 m | 311 m | 285 m |
  | Plain mean, v15 | 717.0 m | 715.2 m | 715.2 m |
  | Overlapping tiles' spread on the plain, v14 → v15 | 200 → 4.4 m | 32 → 4.2 m | 10.5 → 0.6 m |

  The province map carried only 12,000 km² of the river on v14 and all of it on v15.
  On the Standard planet's windows, closed hollows fell from 15 % to 2 % of the
  province's land and lakes from 13 % to 0.1 %; the province lies 21 m below the
  region (24 m on steep ground). Levels 2 and 3 still turned the river north at a
  junction 13 km east of the centre, where the region and the planet run it
  north-west (T23).
- **Drainage coupling (ADR-0109).** It cost two closed-hollow lakes in the region
  window, of 1,470 km² on a basin plain at 59.4° E 29.1° N and 2,240 km² on low
  coastal ground, overlapping level-1 tiles 45 m apart on average instead of 40 m,
  and edge agreement on the synthetic planet of 90 % instead of 93 %. The province
  lies 7 m above the region in 5 km means (21 m below before), and the spread of
  that difference on 2–3 km ground fell from 164 to 61 m. Two level-2 tiles (7200
  and 7632) swing about 400 m on their highest ground between runs whatever the
  correction does, the noise floor ADR-0109 records.

## Hollows of the tile blend (5dab756)

Tiles drain fully, but overlapping tiles drain one plain through valleys that lie
apart, and their weighted mean half fills each valley with the other tile's flank.
The blend's sill then stands above both tiles' plains:

| | Basin plain, 59.4° E 29.1° N | Coastal plain, 56.9° E 34.2° N |
|---|---|---|
| Lake drawn on v16 | 1,472 km² at about 768 m | 2,240 km² at 13 m |
| Tiles (weights) | 312 (0.36), 346 (0.64) | 257 (0.52), 291 (0.48) |
| Their plains | about 746 and 776 m | 12–13 m |
| Their outlets | gorges 3–5 km apart: 312's at 744 m, where 346 stands 815 m; 346's at 775–782 m, where 312 stands 797 m | channels 13 km apart, each across the other's 35–45 m coastal ridge |
| Blended sill | 786.2 m | 23.5 m |
| Hollow behind it | 28 m deep, 1,852 km² | 11 m deep, 8,427 km² |

Blend hollows deeper than 10 m covered 5,270 km² of the region window on v16 and
2,850 km² on v15, since v16's higher ranges raised the flanks. Measuring ponds on the
blend with its own hollows filled, plus what windows draw on top of the tiles, took
lakes from 3,732 to 0 km² in the region window and from 151 to 0 km² in the province;
relief is unchanged and 180 river pixels moved at level 1. Planet lakes were kept
pixel for pixel in region windows over a 48,854 km² lake (144.36° E 15.45° N) and a
38,923 km² endorheic salt lake (85.27° E 38.2° N); the ponds kept there sit beside
1.2–1.5 km volcanic cones.

A weighted soft minimum of the tiles (temperature 5–40 m) still left 490–1,370 km² of
hollows deeper than 10 m, lowered land by 8–24 m and its top tenth by 34–79 m, and
broke ADR-0109's calibration. Breaching sills in the drawn relief was not chosen: it
cuts trenches and changes the exported GeoTIFF. One shared mesh per level would align
outlets at their source, but tiles also differ in seeds, roughness and corrections;
it stays a candidate.

## Open after 3443ff2

- **Sampling points.** Basin depth, lakes and planet forcing are still sampled at a
  level's own points, not at `planet_points`, so basin fronts and lake shores shift
  between levels by the warps' displacement, a few kilometres.
- **Unresolved rivers.** Rivers the planet does not resolve still take each tile's
  own course (tile boundary exchange, TODO M6).
- **Straight lines on smooth plains.** D8 still draws straight runs across planar
  facets of smooth plains: a 45-pixel run lies on the local basin plain under the
  drawn meanders.
- **One-pixel ponds.** Pixel centres miss winding V-crease floors and leave pits
  deeper than 10 m; v12 raised them from 12 to 45 in the region window. A minimum
  pond size would remove them.
- **Test bar.** The single-pair agreement bar fell from 94 % (v10) to 93 % (v11),
  90 % (v12) and 87 % (v16). Six-pair agreement later rose (95.6 % at v13, 94.0 %
  near edges and 92.8 % inside at v18), so the bar can be raised again.
- **Tile caches.** `artifacts/aethelara/planet-3200k-v30.tiles-stale/` and
  `artifacts/aethelara/varA.tiles` hold experiment tiles whose keys equal real ones;
  they are safe to delete.
