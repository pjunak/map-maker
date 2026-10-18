# ADR-0105: Colour and shade every regional level by slopes scaled to level 1

- Status: accepted (experimental product path)
- Date: 2026-10-18
- Refines: [ADR-0088](0088-nested-regional-detail-levels.md) (nested levels) and
  [ADR-0103](0103-regional-detail-on-the-globe.md) (regional maps on the globe).
- Refined by [ADR-0107](0107-regional-temperatures-follow-height-above-the-planet.md):
  the region's remaining darker steep ground came from window climates, the
  mean of display relief and tile heights, not from display lapse alone.

## Context

With the regional maps draped over the globe (ADR-0103) and the globe zoomed into
them (ADR-0104), a local window shows as a circle of another tone inside its
province. On Aethelara (Standard planet; region 600 km, province 150 km and local
30 km windows at 56.87° E, 30.70° N, 900 pixels each, on `planet-blended-tiles-v10`
tiles), the local atlas averaged over each province pixel of their shared ground
was:

| Ground | Province | Local | Local − province (R, G, B) |
|---|---:|---:|---|
| Mountains (province relief slope above 0.12) | luminance 112.0 | 101.9 | +4, −16, +1: brown and dark |
| Plain (below 0.04) | 118.7 | 126.4 | +11, +7, +6: pale and yellow |

There were three causes.

1. **Finer levels resolve steeper slopes.** On the mountains the median slope was
   0.634 in the local window and 0.217 in the province. Over all shared ground it
   was 2.1 times the province's median, and the province's was 1.9 times the
   region's (means 2.7x and 2.2x). Rock, bare hills and slope dryness are
   thresholds on slope. With the same thresholds and a hillshade exaggeration of
   1.3 at every level, the local mountains classed as rock and bare ground. Their
   hillshade fell to a mean of 0.76 against 0.94, so shading alone darkened them
   by 16 levels of luminance. Unshaded they were brighter than the province but
   browner. From region to province, an unscaled slope-dryness term in the
   vegetation (`smooth(slope, 0.1, 0.5)`) browned the province most.
2. **Slopes follow the level, not the pixel size.** Halving a window's pixel width
   at the same level raised the median slope only 1.13x (province) and 1.08x
   (local). The relief between mesh nodes is smooth apart from display detail.
3. **Terrain position read the ground outside the window.** The valley-to-ridge
   position compares height with its 3 km and 15 km Gaussian means. Display
   relief holds −200 m outside the window's disc, and a 15 km mean reaches across
   most of a 30 km window, so the whole local window read as ridge: a flat plain
   filling such a window scored 0.30–0.81 instead of 0. Ridges are drier, hence the pale plain. Without
   the position term the plain matched the province within one level.

Display detail was not a cause at the local level. It differs from the tile
relief by 22 m rms there, and tile and display slopes agree (medians 0.135 and
0.132). Level-1 detail is not excessive either: averaged to region pixels, the
province's relief about its 5 km mean has a standard deviation of 261 m, against
159 m for the region's display relief.

## Decision

1. **Level-1 slopes.** Atlas colours, parchment vegetation, hillshade (atlas,
   relief, topographic, parchment), waterfalls and the sand seas that place dunes
   all see a window's slopes scaled to the level-1 mesh. The gradient is
   multiplied by `(spacing / 5 km)^0.5`, where `spacing` is the window level's
   mesh spacing: 1 at level 1, 0.45 for provinces (1 km) and 0.2 for local windows
   (200 m). The exponent lies between the measured median (0.41–0.45) and mean
   (0.48–0.61) steepening per level. The colour thresholds keep their level-1
   calibration (`REGION_SLOPE_SCALE`).
2. **Hillshade exaggeration by level.** Shading uses the same scaled gradient with
   an exaggeration of 2.9. In effect that is 2.9 for regions, 1.3 for provinces,
   their exaggeration before, and 0.58 for local windows.
3. **Terrain position from the window's own ground.** Its Gaussian means are taken
   over the window's disc only, normalised by the share of the kernel inside it.

## Alternatives considered

- **Scaling by pixel size.** A pixel-width power law would change a window's
  colours with its radius at the same level, by 1.41x per halving where slopes
  change 1.1x.
- **Level-1 exaggeration of 1.3 at every level.** It matches the tones as well,
  but provinces lose their relief: they shade at 0.58 and local windows at 0.26.
  Raising level 1 to 2.9 keeps provinces as they were drawn and gives regions
  clearer relief. On Earth, too, smaller-scale maps take more exaggeration.
- **Scaling colour thresholds only.** On steep ground the local window stayed 11
  levels darker than the province, from hillshade.
- **Thresholds matched to each window's slope distribution.** These would depend
  on the window rather than the ground, so overlapping windows would disagree.
- **Classifying on slopes smoothed to a fixed ground scale.** That loses the rock
  and gullies that finer levels resolve.

## Consequences

- Nested windows agree in tone. Averaged over each coarser pixel of the shared
  ground (land without rivers, lakes or playas), the luminance difference was:

  | Comparison | Before: all / steepest 30 % / gentlest 30 % | After: all / steepest / gentlest |
  |---|---:|---:|
  | Province → local | +2.5 / −8.9 / +6.9 | −0.9 / +1.5 / −1.0 |
  | Region → province | +2.7 / +9.7 / −3.2 | +1.2 / +6.2 / −3.4 |

  The local mountains are now 110.5 against the province's 108.1, with colour
  differences of (+5.5, +1.4, +3.1), and the plain is 117.5 against 118.7. Finer
  levels still add their own ridges, gullies and rock on the steepest faces.
- On `planet-blended-tiles-v11` tiles, whose dissected basin fronts move the
  mountain front mostly out of this local window, province to local went from
  +9.7 (steepest +8.8, gentlest +7.9) to −0.1 (−1.4, +2.0).
- Regions shade with more contrast, and their steep ground is about 3 levels
  darker. Against the planet map at its 18 km texels, the region's steep ground
  moves from 8.0 to 10.8 levels darker. Its gentle ground stays 8.5 levels
  brighter: that seam has other causes.
- Region and province still differ on steep ground, where the region is darker.
  Most of that comes from the lapse correction of the region's display relief:
  without it, the steep-ground difference falls from 6.2 to 2.0 levels.
- Exported regional GeoTIFFs, rivers and tiles are unchanged, so the regional
  algorithm identifier stays. Only the images change.
