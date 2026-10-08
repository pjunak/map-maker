# Wind-driven continentality and Köppen climate zones — 2026-10-08

Status: **implemented, experimental** (climate algorithm `planet-climate-v4`).

## Continentality from the wind

The seasonal temperature range used to grow with distance from the coast alone.
On Earth it depends on where the air comes from. West coasts under the
westerlies are mild and maritime (Bergen, Vancouver). East coasts at the same
latitude receive air from the interior and have hot summers and cold winters
(Halifax, Vladivostok).

- **Maritime tracer.** A tracer for maritime air is 1 over the sea. It is carried
  with each season's prevailing winds and the eddy diffusion already used for
  moisture, and decays with an e-folding of 900 km of land travel. Continentality
  is 1 − tracer.
- **Coastal floor.** Sea breezes keep a 150 km coastal strip at least half
  maritime.
- **Effects.** Continentality sets the seasonal half-range and the interior
  cooling. The fine mesh interpolates it from the 200k climate mesh.
- **Test.** On a synthetic mid-latitude continent, east coasts are more
  continental than west coasts and have a larger annual temperature range.

## Seasonal rainfall

The two-season moisture simulation already ran; it now keeps both seasons.
Warm- and cold-half-year precipitation are mapped to each hemisphere's summer
and winter and scaled with the annual total. This is what separates
Mediterranean (summer-dry) from monsoon and savanna (winter-dry) climates.

## Köppen–Geiger classes

`pipeline/planet_koppen.py` follows Kottek et al. 2006.

- **Monthly cycle.** Twelve monthly temperatures and precipitations are rebuilt
  from the warmest and coldest month and the two half-year rates with a cosine
  annual cycle. They are classified into the 30 standard classes, plus ocean.
- **Rules.** The classifier applies the standard thresholds. For example, 690
  mm/yr of summer rain at 26 °C is BSh steppe, not savanna. Unit tests cover
  Af, Aw, BWh, Csa, Cfb, Dfc, ET and EF.

| Köppen group | Aethelara (800k) | Earth's land (Beck et al. 2018) |
|---|---:|---:|
| A tropical | 21 % | ~19 % |
| B arid | 30 % | ~30 % |
| C temperate | 22 % | ~13–14 % |
| D continental | 17 % | ~22–24 % |
| E polar | 10 % | ~15–17 % (with Antarctica) |

The pattern is Earth-like:
- rainforest on equatorial windward coasts;
- hot deserts in subtropical interiors and lee sides;
- steppe fringes;
- humid subtropical east coasts;
- Mediterranean patches on subtropical west coasts;
- boreal and tundra belts poleward.

Aethelara has relatively more C and less D than Earth, which fits its smaller,
more maritime northern continents.

## Outputs and appearance

- **New layer.** "Planet climate zones" (`koppen.png`) in standard Köppen colours,
  drawn per node without interpolation, since classes are categorical.
- **Archive.** `planet.npz` stores `koppen`, `continentality` and both half-year
  precipitations.
- **Manifest.** Reports Köppen class and group shares.
- **Atlas colour.** Vegetation follows growing-season water: 0.45 × annual
  plus 0.55 × warm-half-year precipitation. Summer-dry Mediterranean land browns
  and monsoon land greens, on the world map and in regional windows.

## Limits

- **Two seasons only.** Monthly values are a cosine fit to two seasons, so there
  are no two-peak rain regimes such as equatorial bimodal rains.
- **Simplified monsoons.** The monsoon is the latitude shift of the rain belts
  only; there is no thermal low over continents.
- **Biomes and Köppen.** The Whittaker biome labels remain for ice detection and
  the biome summary; Köppen classes are the climate product to use.
