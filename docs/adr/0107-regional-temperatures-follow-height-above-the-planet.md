# ADR-0107: Regional temperatures follow height above the planet surface

- Status: accepted (experimental product path)
- Date: 2026-10-18
- Refines: [ADR-0088](0088-nested-regional-detail-levels.md) (nested levels) and
  [ADR-0105](0105-regional-levels-see-level-1-slopes.md) (tone agreement between
  levels).

## Context

After ADR-0105, a region's steep ground was still darker than its province's.
The test case is Aethelara: Standard planet; region 600 km, province 150 km and
local 30 km windows at 56.87° E, 30.70° N; 900 pixels each; `planet-blended-tiles-v11`
tiles. Over shared ground (land without rivers, lakes or playas, averaged to region
pixels), province minus region luminance was +1.6 overall. It was +5.0 on the
steepest 30 % and −2.9 on the gentlest 30 %.

Forest carried the difference. On steep ground the region showed a forest cover
of 0.63 and the province 0.47. Without forest the gap reversed to −2.8; snow,
tundra, rock and bare hills each moved it by under a level. Forest differed by
dryness, not warmth. The region's potential evapotranspiration was 635 mm a year
and the province's 791 mm, because their window climates averaged 3.0 °C and
6.7 °C there. Three things set those temperatures.

1. **Level parents misplaced the planet's temperatures.** A planet's temperatures
   hold at its surface. Level 1 lapse-corrects them from there to its tiles,
   exactly. A province's level parent sampled them unchanged, but its windows
   lapse-corrected them from the parent's own surface, the level-1 tiles. On this
   steep ground those tiles stand 1,014 m above the planet surface, so the
   province was 6.5 °C too warm. On the gentle ground, 372 m below the planet
   surface, it was 2.4 °C too cold.
2. **Colour lapse-corrected the mean of display relief.** Display relief at level 1
   lay 822 m below its tiles on steep ground. Detail noise accounts for −72 m and
   valley carving for −749 m: carving lowers ridges too, here by 43 % of the
   1,740 m detail height. The province's display relief lay 282 m below its tiles.
   Lapse-correcting that warmed the region's mountains by 5.3 °C and the
   province's by 1.8 °C. The summer warmth that colour saw then agreed by
   coincidence (18.3 °C against 18.5 °C), but the potential evapotranspiration,
   which follows the window climate, did not.
3. **Province tiles stand higher than the region's.** On the same steep ground they
   stand 425 m above level-1 tiles. In 5 km means over land, the gap is +455 m
   where the region is 3–4 km high and +722 m above 4 km; it is −38 m below 1 km.
   Local tiles keep the province's mean (−20 m).

The first darkened the province's mountains, the second the region's, and the
third brightens the province's. With the first two corrected, the province is
2.75 °C colder than the region on steep ground, following its higher tiles.
Its summers there are 10–13 °C, near the treeline, so it shows more tundra and
snow and less forest.

## Decision

1. **A parent's temperatures hold at its own surface.** A level parent takes the
   planet's temperatures lapse-corrected from the planet surface to the coarser
   tiles' relief (`RegionalParent.temperatures_at`). At any height, every level
   is as warm as the planet at that height.
2. **Colour lapse-corrects display relief about its own mean.** Display relief
   stands in for relief the level's mesh does not resolve. Only its departure
   from its Gaussian mean over one mesh spacing, taken over the window's land,
   changes the temperature that atlas and parchment colours see. That spacing is
   5 km for regions, 1 km for provinces and 200 m for local maps. Snowlines and
   treelines still follow display ridges and gullies, but carving's lowering no
   longer warms whole mountains.

## Alternatives considered

- **No lapse correction of display relief.** Tones agree as well (+9.8 on steep
  ground, simulated), but snow and treelines no longer follow the drawn ridges and
  gullies.
- **Means over 3 or 6 mesh spacings.** These keep the temperature spread of
  level-1 detail's coarse octaves (its wavelength is 30 km), which darkened the
  region's mountains by 2–4 more levels (+12.4 and +14.4, simulated).
- **Moving display relief to the tiles' local mean.** Tones are about the same
  (+9.3), but hillshade changes at every level, and level-1 ridges coarser than
  the mesh disappear.
- **Only the display change.** With the level parents left as they were, steep
  ground would read −2.2 and gentle ground −3.0 (simulated). That agreement comes
  from a province 6.5 °C too warm offsetting tiles 425 m too high. It would also
  leave each level's climate depending on the relief of the level above.

## Consequences

- Luminance differences over shared ground, averaged to each coarser pixel. The
  world comparison uses the planet atlas at its 18 km texels.

  | Comparison | Before: all / steepest 30 % / gentlest 30 % | After |
  |---|---:|---:|
  | World → region | −1.6 / −10.9 / +8.0 | −0.7 / −7.5 / +8.0 |
  | Region → province | +1.6 / +5.0 / −2.9 | +3.4 / +10.3 / +0.8 |
  | Province → local | −0.1 / −1.4 / +2.0 | +1.5 / +1.3 / +2.4 |

- The province's mountains now read brighter than the region's, by a difference
  in the tiles rather than in the display. Enrichment calibrates a level's relief,
  smoothed over the parent spacing, against the parent surface itself rather than
  the parent surface smoothed alike. Wherever smoothing lowers peaks, finer levels
  must therefore stand above the coarser level. That is the likely cause, and the
  [plan](../strategy/README.md) takes it up next.
- Province and local window climates change: on average by −1.0 °C and +2.0 °C
  here, with a spread of 4.9 °C in the province. Closed basins whose dryness
  crosses the threshold switch between lake and playa: here the province's lake
  pixels fell from 64,100 to 59,247 and its playa pixels rose from 722 to 2,876.
  Tiles, window relief, exported GeoTIFFs and level-1 windows are unchanged, so
  the regional algorithm identifier stays. Only images change, as with ADR-0105.
