# First authored world through the planet pipeline — 2026-10-06

Status: **experimental run on the user's private campaign world** (not test data;
no map content is committed). It checks that `map-maker world planet` and
`map-maker world region` work on a real authored coastline rather than synthetic
fixtures.

## Input

- **World file.** A saved `.world.json` with 9 continents and 185 source shapes,
  most of them islands. Several continents share continuous land along their
  borders.
- **Frame.** Full-sphere Plate Carrée, (17, 0)–(2897, 1440), 6,000 km radius;
  23.3 % land.
- **Import.** World preparation reports 4 bounded import adjustments: an edge
  trim, two narrow border overlaps and one overlapping island pair.
- **Geology.** None; the forcing is procedural.

## Results

| Run | Nodes | Spacing | Time | Land mean / max | Lakes (closed) | Non-descending receivers |
|---|---:|---:|---:|---:|---:|---:|
| Planet, one climate pass | 200,000 | ~48 km | 44 s | — | — | 0 |
| Planet, two climate passes | 800,000 | ~24 km | 4 min 34 s | 741 m / 5,297 m | 66 (10) | 0 |
| Region, 600 km radius, 5 km | 25 tiles* | 5 km | 53 s | — | — | — |

\*Tiles were generated on first use and cached beside the planet build.

800k-node detail:
- Compass-sector share 0.243.
- Shares of land: 27 % above 1 km, 12 % above 2 km.
- Deserts (cold and hot) 19 %; savanna 22 %; tundra 12 %; ice 3 %.
- Hack's exponent on runoff-weighted area 0.42.

## Defects found and fixed

- **Ice sheets** carried glacial-scour lakes and drawn rivers on a south-polar
  landmass. Real ice sheets have no surface lakes or rivers. Now:
  - young depressions are suppressed where the warm-season temperature is below
    about 0–2 °C (ice-covered now);
  - rivers are not drawn or exported on the ice biome.

  `tests/test_planet.py::test_ice_sheets_hold_no_young_lakes` covers this.

## Findings for the authored source

- **Staircase coastline.** Parts of the coastline carry pixel-staircase edges
  from raster-to-vector conversion, with steps of about 0.8–1.2 map units
  (10–16 km). They are invisible on the planet map but appear as blocky notches
  in 5 km regional detail.
- **Coastline stays authoritative.** The pipeline correctly keeps the coastline
  as drawn. Smoothing it is an authoring decision for the source map. An optional,
  explicitly derived coast refinement for zoom views would need its own decision.
- **Placeholder relief.** Without a geology recipe, mountain and margin placement
  is procedural noise. Authored provinces (belt, shield, rift, basin, ages) in the
  World-tab Geology editor become calibrated targets.
