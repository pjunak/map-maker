# Ice sheets from mass balance and shallow-ice flow — 2026-10-13

Decision: [ADR-0093](../adr/0093-ice-sheets-from-mass-balance-and-shallow-ice-flow.md).
Catalog entry: D31 in the [decision catalog](decision-catalog.md).

## Problem

The Aethelara atlas (`planet-800k-final`, 800k nodes, 23.8 km spacing) showed its
south polar ice as a white band whose edge ran along a line of latitude near
75 °S. The edge broke into straight triangle facets, tundra holes sat inside the
ice, lakes lay on it, and the dome shaded in facets. Regional windows drew no ice
at all.

## Causes found

- **Ice was a temperature class.** A node was ice where its warmest month stayed
  below 0 °C, so the edge was that isotherm, whatever the snowfall.
- **The edge was the parent's interpolated class.** Maps drew ice where the
  triangle-linear class passed 0.5: straight inside each triangle.
- **The bare polar continent has warm summers.** Medians of the warmest month on
  its land are −3 °C at 80–90 °S, −0.3 °C at 75–80 °S, +4.8 °C at 70–75 °S and
  +9 °C at 65–70 °S, with 70–115 mm of precipitation: a Canadian-Arctic climate.
  Antarctica is colder because its ice is high and bright, which the class could
  not represent.

## Method

**Mass balance.** Ice grows where snowfall outweighs melt. Melt for a warmest-month
temperature T is the precipitation that balances a glacier at its equilibrium line,
P = 645 + 296 T + 9 T² mm (Ohmura et al. 1992), zero below −2.35 °C. It is the
relation the snowline display already inverts. Two feedbacks follow the ice surface:
the lapse rate (6.5 °C/km), with snowfall falling by 7 % per degree of cooling
(Clausius–Clapeyron), and albedo, up to 5 °C of summer cooling scaled by the ice
share within 300 km. Air over Greenland's melting ice stays near 0–3 °C in summer
while the tundra at Kangerlussuaq reaches about 11 °C, several degrees beyond the
lapse-rate difference.

**Flow.** The shallow-ice approximation, dH/dt = b + ∇·(D ∇s), D = 2A(ρg)³H⁵|∇s|²/5,
with A = 1e-16 Pa⁻³ yr⁻¹ (EISMINT), on the mesh's cotangent weights. Edge
diffusivity uses the mean thickness, and ice leaves only a node that holds it. Ice
reaching the sea calves. Explicit steps of 10 years from no ice for 100 kyr; balance
is refreshed every 500 years and the albedo share every 5 kyr. A numba kernel
handles only nodes within three edges of ice or positive balance.

## Trials

| Trial | Outcome |
|---|---|
| Fixed point: ice where routed balance flux stays positive, Nye surface from the margin | No equilibrium. About 345 margin nodes flipped every iteration. Monotone growth settled after 95 iterations at 8,164 nodes; each trim then removed fewer nodes without stopping (587, 364, 172, 107, 77, 62, 46, 43, 41, 35). |
| Fixed point, no albedo feedback | 2.6 % of land iced; 85 % of land at 75–90 °S, 4 % at 65–75 °S. |
| Shallow ice, uncapped | 60 kyr took 120,000 steps (0.5 yr) and 44 s. A few nodes limited the step: ice on the titan's steep flanks near the equator, a steep mid-latitude range and small mesh cells. |
| Shallow ice, diffusivity capped for 10-year steps | 100 kyr in 10,000 steps; volume grew 1 % in the last 10 kyr. |
| Plus flow enhancement varying 30-fold over 400 km (soft beds) | Unchanged extent: 3.21 % against 3.19 % of land. The margin sits on the equilibrium line, where dry snowfall feeds an ablation zone only about one spacing wide. |
| Plus regional summer wander, 0.67 °C standard deviation | Margin bends of about ±75 km: still straight at world scale. Summers warm by about 1 °C per degree of latitude there. |
| Plus wander of 1.6 °C standard deviation | Bends of 100–300 km. Warmest months vary by several degrees between longitudes at 70 °N on Earth (about 5–14 °C). |

The model adds about 11 s to an 800k-node build.

## Drawing ice

- **Sheets and glaciers.** The model also grows ice caps on high ranges. Drawn as
  surfaces they were flat white blobs over whole ranges. Ice bodies are drawn as
  sheets only when at least 100,000 km² and thick enough to bury their bed: mean
  thickness at least four times the bed's relief, its standard deviation within
  about 50 km. On Aethelara that ratio is 10.5 for the polar sheet, at both 800k
  and 3.2 million nodes, and at most 2.7 for every other body, the largest being
  the titan volcano's cap (134,000 km²) and a range at 45 °N (124,000 km²).
  Relief between neighbouring nodes, tried first, shrinks on finer meshes: at
  3.2 million nodes two mountain icefields passed and were drawn as flat white
  sheets. Mountain ice keeps the per-pixel snow and glacier colour, which follows
  ridges and valleys.
- **Margin.** A signed distance to the margin, zero halfway along each edge from
  an ice node to a bare one, is sampled through the nested warp of lake outlines,
  larger for ice (6 spacings, 0.6-spacing amplitude). Thickness near the margin
  follows Nye's plastic profile (150 m at 1 km, 470 m at 10 km).
- **Surface.** Thickness and bed are smoothed over 0.6 mesh spacings, which hides
  interpolation facets, before the margin profile is applied; ice covers pixels
  where this surface lies above the map's detailed relief, so nunataks rise
  through it. Undulations of up to 50 m at 40 km and finer octaves down to each
  map's resolution give texture; hillshade contrast on ice is 2.5 times that on
  land, saturating, as a low polar sun shows ice relief.
- **Colour.** Firn above the equilibrium line, bluish bare ice below it. No rivers
  or lakes are drawn on ice.

## Aethelara

Same world and settings as `planet-800k-final`; build `planet-800k-ice`.

| | Before (`planet-800k-final`) | After (`planet-800k-ice`) |
|---|---|---|
| Ice on land | 1.86 % (ice class) | 2.80 % modelled, 1.98 % drawn as sheets |
| Land under ice at 80–90 °S, 75–80 °S, 70–75 °S | ice class only | 99.6 %, 70 %, 0.6 % |
| Sheet thickness | plastic display dome | up to 2,380 m, mean 1,354 m |
| Northern edge of the sheet | about 75 °S along a parallel | 74.7–82.9 °S around the pole (10° longitude bands) |
| Lakes and tundra holes on the ice | many | none |

- The ablation zone covers 0.2 % of the sheet's nodes: with 70–115 mm of
  snowfall, ice reaches little beyond its equilibrium line.
- Mountain ice covers another 0.8 % of land, on high ranges and the titan
  volcano (3.8 km thick on its summit); all of it is drawn as snow and glaciers.
- Regional windows on the margin (level 1 at 15 °E, 75.8 °S, radius 250 km;
  level 2 at 15 °E, 75.2 °S, radius 60 km) show lobes, a shaded ice front, a
  band of bare ice and meltwater rivers along the margin. Topographic windows
  draw the sheet as glacier with its contours.

Images: `artifacts/aethelara/planet-800k-ice/atlas.png` and the regional builds
`artifacts/aethelara/ice-region-l1` and `ice-region-l2` (local, not tracked).

## Limits and follow-ups

- No ice shelves or sea ice: sheets end at the coast.
- On a broad plain a dry sheet's margin follows the regional climate and stays
  smooth at world scale.
- Mountain ice is modelled at the mesh's resolution but drawn as snow and
  glaciers; rivers are hidden on it although its map shows snowy rock.
- The mass-balance relation is an equilibrium-line fit, not an energy balance.
