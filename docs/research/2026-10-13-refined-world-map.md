# Refined world map as a source — 2026-10-13

Related: [ADR-0090](../adr/0090-regional-coast-detail-below-drawing-precision.md)
(regional coast detail), [ADR-0094](../adr/0094-planet-polar-land-in-true-distance.md)
(polar land), [ADR-0093](../adr/0093-ice-sheets-from-mass-balance-and-shallow-ice-flow.md)
(ice sheets).

## The refined map

`World map (refined).svg` (a local artifact, not tracked) is the planet's land of
Aethelara traced back into vector form:

- the drawn coast with the regional coast detail of ADR-0090 down to 10 km
  wavelengths;
- polar land worked in true distance, with the south pole covered (ADR-0094);
- traced stair-steps removed by simplification and Chaikin smoothing.

It keeps the original frame and continent groups: 180 shapes, 374,500 points
(the importer allows 500,000). Imported as a separate project, *Aethelara
(refined)*, with the original's frame, its groups assign to the same nine
continents (160 mainland and 20 island shapes).

## Planet comparison

Both builds use the same settings: 3.2 million nodes, two climate passes,
volcanic islands, no wonders, seed 20261006 (original `planet-3200k-v23-poles`,
refined `planet-3200k-refined`).

| | Original | Refined |
|---|---|---|
| Land on the planet | 106.18 million km² | 106.13 million km² |
| Pole cover added (ADR-0094) | 403,066 km² | 16,785 km² |
| Source adjustments | export overflow at the edge, two border overlaps, one shared-land overlap | none |
| Rivers; lakes (closed) | 1,239; 533 (59) | 1,221; 519 (61) |
| Volcanoes on land; islands | 711; 250 | 661; 249 |
| Land above 1 km; 2 km | 31.3 %; 9.3 % | 31.2 %; 9.3 % |
| Köppen groups A, B, C, D, E | 22.3, 27.5, 24.1, 17.3, 8.9 % | 22.3, 27.4, 24.2, 17.5, 8.7 % |
| Ice on land | 3.54 % | 3.65 % |

- **Same geography.** 0.28 % of the sphere differs, almost all coast detail.
  Statistics of relief, climate, rivers and lakes agree within a few per cent.
  Volcanoes on land fall from 711 to 661; their placement depends on the coast
  (arcs stand inland of leading-edge coasts), and this comparison does not
  separate the cause further.
- **Cleaner coasts.** At full atlas resolution, the original's traced
  stair-step fingers along northern and western coasts are gone; islets differ
  slightly.
- **Detail added twice.** The refined coast already holds the level-1 coast
  detail: in a 150 km window at 500 m pixels it differs from the original's
  level-1 coast on 0.19 % of pixels. Regional levels refine it again with the
  same noise, which changes 1.5 % of pixels, a mean coast shift of about 1.5 km,
  with coast length within 0.3 %. Province and region windows show slightly
  shifted bays and rivers and no new artifacts.

## Found along the way

At 3.2 million nodes two mountain icefields were drawn as flat white ice sheets:
the test for drawing a body as a sheet compared thickness with the bed's relief
between neighbouring nodes, which shrinks on finer meshes. It now uses the bed's
relief within about 50 km ([ADR-0093 revision](../adr/0093-ice-sheets-from-mass-balance-and-shallow-ice-flow.md#revision-2026-10-13)).

## Drawn coast detail

A world project can now state the coast detail its drawing already carries
(`coast_detail_km`, ADR-0090 revision). With 10 km stated for the refined map,
its coast is not smoothed, level 1 adds nothing, and levels 2 and 3 add only the
octaves below 10 km. Mean coast shift from the original drawing's refined coast,
in 600-pixel windows:

| Window (lon, lat, radius) | Level 1 | Level 2 | Level 3 | Refined twice (level 1) |
|---|---|---|---|---|
| −60°, 45°, 150 km | 0.20 km | 0.21 km | 0.22 km | 1.47 km |
| −124.29°, 35.88°, 40 km | 0.19 km | 0.17 km | 0.17 km | 1.01 km |
| 74.87°, 65.75°, 40 km | 0.10 km | 0.14 km | 0.16 km | 1.28 km |
| 105°, 70°, 150 km | 0.24 km | 0.28 km | 0.28 km | 2.37 km |

The remaining shift most likely comes from the export's tracing (0.2-unit cells) and its
smoothing.

## Export command

`map-maker world refine-coast` now makes such maps (ADR-0095). Unlike the first
script, it names island groups so the importer keeps their role (the script's
export came back with 160 of 180 shapes as mainland), and it cuts the traced land
by the drawn shapes' territories, so Tharkeniss Kel and Oul, and Dra and Veld,
which share land borders, keep their areas. On Aethelara: 195 shapes (185
islands), 398,489 points, every continent within 0.2 % of its drawn area except
Oskarath, which gains the land the planet adds at the south pole; the import
needs no adjustments.

## Limits and follow-ups

- Adopting the refined map as Aethelara's source is the author's decision; the
  authored project is unchanged.
