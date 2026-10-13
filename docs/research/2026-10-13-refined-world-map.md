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

## Limits and follow-ups

- Adopting the refined map as Aethelara's source is the author's decision; the
  authored project is unchanged.
- A source that already holds regional coast detail gets it again at level 1.
  If refined maps become sources, a project could state the scale its coast is
  drawn to, so levels add only finer octaves.
