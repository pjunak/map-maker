# Planet climate v0 and relief coupling — 2026-10-06

Status: **experimental**. It was first built in the research harness and is now
`dmtools/terrain/pipeline/planet_climate.py` (ADR-0085).
It is provisional and explainable, not a general circulation model. Its biome
labels are provisional. It builds on the
[whole-planet relief harness](2026-10-06-whole-planet-erosion-relief.md).

## Model

All fields live on the same sphere mesh as the relief.

1. **Temperature.**
   - Sea surface: from −15 °C at the poles to 27 °C at the equator, following cos(lat)^1.3.
   - Land: minus 6.5 °C/km, minus 6 °C × continentality × sin²(lat) (cold winter-dominated interiors), plus up to 4 °C clear-sky warming at low latitude.
   - Seasonal half-range: (2 + 22 · sin|lat| · obliquity/23.4) × (0.35 + 0.65 · continentality). Continentality is coast distance / 1,500 km, capped at 1.
2. **Wind belts.**
   - Easterly trades below about 28°, westerlies from 32° to 58°, polar easterlies above about 62°.
   - Equatorward trades and poleward westerlies.
   - Two seasons, with the belts shifted by ±8° × obliquity/23.4.
3. **Moisture.** Semi-Lagrangian transport with a sparse barycentric departure operator; each step moves about one node spacing. Then, each step:
   - eddy mixing with neighbours, weak in the trades and strong in the storm tracks;
   - ocean evaporation relaxing towards capacity ∝ exp(0.068 (T − 15));
   - storm-track import towards 60 % of zonal ocean capacity, fading inland over 1,200 km;
   - rain = rain fraction × moisture + supersaturation, where the rain fraction is large-scale ascent by latitude band plus orographic lift / 2.5 km;
   - land re-evaporates 38 % of its rain.
4. **Units.** Precipitation is scaled so the planetary land mean is 800 mm/yr. This is a declared calibration, not a prediction.
5. **Evaporation and runoff.**
   - Potential evapotranspiration: Hargreaves, with annual-mean radiation by latitude and a diurnal range from continentality.
   - Actual evapotranspiration: Budyko–Fu with w = 2.6.
   - Runoff = P − AET, which is non-negative and never exceeds P.
6. **Biomes.** Whittaker-style labels from mean temperature, warm-season temperature and aridity P/PET, with ice and alpine overrides.
7. **Coupling.** Runoff relative to the land mean, floored at 0.05, multiplies each node's contributing area in stream power. The geology calibration is re-run under that runoff, and the climate is recomputed on the new relief. The harness flag is `--climate-passes`.

## Development trail (failed intermediate versions retained)

All runs used the 200k-node fractal world with the sample geology.

| Version | Change | Outcome |
|---|---|---|
| a | Orographic rain-out 1 − exp(−w / 0.004 m/s) | **Rejected:** air rained out at the first coastal node; 79 % of land was desert while the mean was 800 mm. |
| b | Orographic share = lift / (2 × 2.5 km), with lapse supersaturation | Rain shadows appear, but there are dry interiors everywhere and streaky bands. |
| c | + land recycling, eddy mixing, two seasons | Plausible mix, but almost no hot deserts (0.9 %). |
| d | Stronger mid-latitude rain-out | **Rejected:** coasts got wetter and interiors drier, with the 40–60° median at 30–100 mm. Depletion, not rain-out, was the limit. |
| e | + storm-track moisture import | Zonal profile shaped like Earth's, but deserts vanished because the import propped up every interior. |
| f | Import fades inland; drier subtropical highs | Deserts 4.5 %. |
| g | Hargreaves instead of Holdridge PET | Deserts about 12–13 %. This is the current model. |

Zonal land medians for version f:

| Latitude band | Precipitation |
|---|---:|
| 0–20° | 1,400–1,600 mm |
| 20–30° | about 450–630 mm |
| 30–60° | about 300–420 mm |
| Above 70° | under 200 mm |

## Results (200k nodes, two coupling passes)

| Biome share of land | Value | Earth, for orientation |
|---|---:|---:|
| Savanna | 21 % | about 15 % |
| Temperate grassland | 17 % | about 8 % |
| Tropical seasonal + rainforest | 18 % | about 15 % |
| Boreal forest | 11 % | about 11 % |
| Temperate forest + rainforest | 10 % | about 12 % |
| Cold + hot desert | 11 % | about 19 % |
| Tundra + ice | 10 % | about 13 % (including Antarctica) |

- **Water.** Land runoff settles at 278 → 266 → 264 mm/yr over the passes.
- **Geology targets** are still met within about 4 % after the runoff-weighted recalibration.
- **Rivers.** There are no non-descending receivers.
- **Cost.** Climate takes about 22 s per evaluation at 200k nodes. The complete coupled run takes 3 minutes.
- **Control test** (`tests/test_planet_relief.py`):
  - A north–south range in the westerlies gets more than 1.3× more rain on its windward side than on the lee side.
  - The lee side is drier than with no range.
  - The land mean matches its target, 0 ≤ runoff ≤ precipitation, and the summit is more than 15 °C colder.

## Moisture travel convergence (after promotion)

The harness integrated moisture over 3πR of travel per season, about 60,000 km.
That made climate cost grow with mesh density: 198 s at 800k nodes. The test
used the 100k-node product build and compared against the 60,000 km result:

| Travel | Max relative change in precipitation (P ≥ 50 mm) | Land labels changed |
|---:|---:|---:|
| 16,000 km | 6 % | 0.27 % |
| 8,000 km | 123 % | 2.5 % |
| 5,000 km | 474 % | 10 % |

The product uses a fixed 20,000 km per season, independent of mesh density.

## Limits

- **Annual means only.** There are two-season averages, but no monthly climate, monsoon dynamics, ocean currents or sea ice.
- **No energy balance.** Temperature is prescribed by latitude rather than solved.
- **Constants and biomes.** All constants are first choices, tuned against qualitative Earth patterns on one synthetic world. Biome thresholds are simplified Whittaker/UNEP-style boundaries.
- **Lakes.** Lakes and endorheic retention are not modelled; arid basins are still filled.
- **Feedback.** The runoff weighting changes the meaning of the Hack exponent (it is measured on runoff-weighted area: 0.43 in the coupled run).
