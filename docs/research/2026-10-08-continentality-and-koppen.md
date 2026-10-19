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

## Monsoons

Over open ocean the ITCZ follows the sun only a few degrees. Summer heating of
large low-latitude landmasses deepens a thermal low that pulls the rain belt
and onshore winds far poleward (South Asia to about 25°N, the Sahel, northern
Australia).

- **Seasonal shift.** The shift of the wind and rain belts is now set per node:
  the base 8° plus up to 10° more. The extra grows with the share of heatable
  summer-hemisphere land (5–35° latitude) within about 1,500 km.
- **Desert belt.** The subtropical dry belt moves poleward with it over the
  continents.
- **Aethelara at 800k nodes.**

  | Köppen class or group | Before | After |
  |---|---:|---:|
  | Am (monsoon) | 1.7 % | 2.4 % |
  | Aw (savanna) | 5.2 % | 6.0 % |
  | Cwa (monsoon-influenced subtropical) | 0.5 % | 0.7 % |
  | Cfa (humid subtropical) | 10.2 % | 13.4 % |
  | B (arid) | 30.4 % | 27.4 % |
  | Csa (Mediterranean) | 3.0 % | 2.4 % |

  Arid land shrank as the desert belt moved poleward; Mediterranean climates
  narrowed with it.
- **Provenance.** The climate algorithm identifier is now `planet-climate-v5`.
- **Test.** A synthetic northern subtropical continent pulls the northern-summer
  belts at least 5° further poleward than open ocean at the same latitude.

## Snow, glaciers and high massifs

At regional zoom, high ranges drew as solid white because snow depended only on
temperature.

- **Snowfall.** The equilibrium line's summer temperature now follows Ohmura et
  al. 1992, P = 645 + 296 T + 9 T². It is about −2 °C at 100 mm, +1 °C at
  1,000 mm and +4 °C at 2,000 mm. Wet ranges hold ice lower, and dry ranges
  keep only thin snowlines.
- **Mass elevation effect** (Massenerhebung). Big high massifs heat the air above
  them in summer, so the warm season rises by 1.5 °C per km of mean elevation
  above 1 km within about 200 km. Snowlines and treelines rise on plateaus.
  Polar (E) climates fall from 9.9 % to 9.3 % of Aethelara's land.
- **Rock between snowfields.** Snow lies more in hollows. Steep faces and
  wind-scoured crests (terrain position) show rock, so glaciated ranges read as
  snowfields and rock rather than a solid white blob.
- **Arc volcanoes.** They now need a stronger leading edge and have wider
  flat-slab gaps: 360 instead of 540 at 800k nodes.
- **Provenance.** The climate identifier is now `planet-climate-v6` and the
  relief identifier `sphere-mesh-stream-power-v13`.

## Sand seas, stony plains and dunes

Hot deserts drew as uniform pale beige. On Earth, wind-blown sand gathers in
the flattest, driest low ground as sand seas (ergs: Rub' al Khali, the Saharan
ergs, Taklamakan). Most other desert is stony plain (reg, hamada) or rock.

- **Erg cover.** It needs:
  - P/PET below about 0.05–0.14;
  - pixel slopes below about 0.4–2 %, scaled at zoom;
  - low terrain position;
  - patchy noise at about 500 km.
- **Colours.** Ergs are orange sand, paler where cold. Hyper-arid ground outside
  them darkens towards gravel brown (reg).
- **Dunes in regional windows.** Linear (seif) dunes follow the parent's annual
  mean wind.
  - **Size.** Spacing is about 2.5 km (±30 %) and height about 45 m.
  - **Shape.** The phase is warped so ridges merge in Y-junctions, and noise at
    12 km breaks them up along their length.
  - **Wind.** The planet archive's wind fields now reach regional windows.
  - **2026-10-19:** the warped phase drew rings and whorls wherever the wind or
    spacing varied, and depended on the window's origin. Crests now follow the
    zero contours of world-anchored noise averaged along the wind (decision D28).

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
- **Simplified monsoons.** Monsoons are a heating-weighted shift of the rain
  belts; there is no explicit thermal low or onshore pressure gradient.
- **Biomes and Köppen.** The Whittaker biome labels remain for ice detection and
  the biome summary; Köppen classes are the climate product to use.
