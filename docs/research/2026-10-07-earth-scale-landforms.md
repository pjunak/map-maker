# Earth-scale landforms: ranges, valleys and rivers — 2026-10-07

Status: **implemented, experimental.** This follows
[world-scale detail](2026-10-07-world-scale-detail.md).

The user found that mountain ridges, fjords and river lengths were still far
too massive for the size of whole continents. They asked for research into
real sizes, allowing fantastical features but making the result look real.

The world radius is 6,000 km, 0.94× Earth's 6,371 km, so Earth's sizes carry
over almost unchanged. Reference figures come from a literature and data
survey; encyclopaedic values are good to about 10–30 %.

## Earth reference values

| Feature | Earth | Source |
|---|---|---|
| Major orogen width across strike | Himalaya 150–350 km (Tibetan Plateau 1,000 km); Andes mostly ~200 km (640–700 km at the Altiplano); Alps ~200 km; Urals 50–250 km; Caucasus 160 km; Scandinavian Mountains 320 km | Encyclopaedic range data |
| Orogen length | Alps ~1,000 km; Himalaya 2,400 km; Urals 2,500 km; Andes 8,900 km | Encyclopaedic range data |
| Internal ridge spacing | Basin and Range crests 25–35 km apart; Zagros folds ~10 km; Valley and Ridge folds up to ~18 km | Regional geology |
| Outlet spacing of linear belts | Spacing ≈ half-width / 2.1 (1.91–2.23 between belts). Typical half-widths of 20–40 km give outlets 10–20 km apart; wide belts ~40 km. | Hovius 1996; Talling et al. 1997; Castelltort & Simpson 2006 |
| Hack's law | L ≈ 2.0 A^0.49 (km, km²); large basins have an exponent of about 0.46–0.5 | Montgomery & Dietrich 1992; Mueller 1973; Sassolas-Serrayet et al. 2018 |
| Largest rivers | 6,000–6,650 km main stems. L / √A is 2.4 for the Amazon, 3.5 for the Mississippi, 3.7 for the Nile and 4.7 for the Yangtze. | River system lists |
| Long rivers | About 230–250 longer than 1,000 km and about 61 longer than 2,000 km, on about 135 M km² of ice-free land | Grill et al. 2019 |
| Largest basin's share of its continent | Asia 7 %, Africa 12 %, North America 13–15 %, Australia 14 %, South America 34–39 % | Derived |
| River sinuosity (reach scale) | 1.1–1.4 | Wu et al. 2023 |
| Fjords | 1–10 km wide, 15–400 km long. Major fjords are 40–80 km apart, with minor ones every few km. | Encyclopaedic fjord data |
| Passive-margin escarpments | 30–200 km from the coast; relief over 1 km | Wang & Willett 2021 |
| Plateaus | Tibet 2,500 × 1,000 km; Altiplano 1,800 × 350–400 km; Colorado ~600 km across | Encyclopaedic data |

## Measured on Aethelara before this change

The build had 800k nodes (24 km spacing) and a process area of 2,500 km².
Measurements come from the new `benchmarks.planet.scale_metrics` tool.

| Metric | Aethelara | Earth equivalent |
|---|---:|---:|
| Mountain-belt width, area-weighted | 525 km | 100–350 km |
| Largest connected mountain network | 9.4 M km², about 18,000 km long | Ranges of 1,000–3,000 km |
| Spacing of valleys draining ≥ 2,500 km² | about 96 km | 10–40 km between major valleys |
| Rivers > 1,000 / > 2,000 km | 52 / 7 | about 180 / 47 at this land area |
| Longest river | 4,371 km | 6,000–6,650 km |
| Largest basins, L / √A | 1.6–2.1 | 2.4–4.7 |

Three things were wrong:

- **Mountains** were 2–4× too coarse. Belts were bands of thresholded ridged
  noise; at the noise's continental wavelength the band was 500–1,700 km wide
  and covered about half of all land. The 2,500 km² process area also put
  valleys no closer than its own scale (√2,500 km² ≈ 50 km), with mesh-scale
  valleys roughly 100 km apart.
- **Rivers were too short, too few and too straight**, not too long. A smooth
  inland-rising starting dome sent them straight down to the coast.
- **Fjords** are not generated. The wide inlets are part of the authored
  coastline.

## Changes

- **Range geometry.** Crest lines are the zero lines of smooth noise. The
  distance to a crest is estimated as |f| / |∇f|, which is within about 6 % of
  the exact graph distance near the crest. Each range then has an explicit
  half-width:

  | Feature | Half-width or width | Notes |
  |---|---|---|
  | Great orogens | 60–175 km half-width | Segments 1,000–3,000 km long |
  | Minor ranges and fold belts | 20–60 km half-width | |
  | Active margins | about 150 km wide | |
  | Passive-margin swell | crest about 150 km inland | |
  | Orogenic plateaus | 4× the belt half-width | Behind some great orogens |
  | Broad swells | 1,000–3,000 km across | |

- **Erodibility.**
  - **Shields.** Rock outside active belts has 0.25× erodibility. Plateaus and
    shields therefore keep most of their slow, accumulated uplift and are incised
    only from their edges (as on the African and Colorado plateaus) instead of
    becoming continental badlands.
  - **Lithology.** Rock strength now varies down to about 30 km.
- **Inherited surface.** The starting surface has fractal relief of up to 600 m,
  and its rise inland is 0.2 m/km instead of 2 m/km. Slowly eroding shields keep
  their old drainage, and a smooth 2 km dome had left straight radial rivers.
- **Uplift rates.** Belts 2.2 mm/yr, minor ranges and margins 1 mm/yr. Plateaus
  0.3 mm/yr, swells 0.08 mm/yr, shields 0.05 mm/yr. The rates are tuned to
  Earth's hypsometry.
- **Resolution.**
  - **Process area.** The default is now 600 km², so valleys can form at
    Earth-like spacing.
  - **Fine mesh.** A *Fine* preset of 3.2M nodes (about 12 km) resolves 20 km
    half-width ranges with valleys tens of kilometres apart. Coarser meshes
    remain available as previews.
- **Cost control.**
  - **Climate mesh.** Moisture transport runs on at most 200k nodes. Temperature
    with its lapse rate, PET, runoff and biomes are recomputed on the full mesh
    (`downscale_climate`).
  - **Coupling mesh.** Climate-coupling erosion passes run on at most 800k nodes;
    only the final relief uses the full mesh.
  - **Result.** At 800k nodes a build went from 448 s to 204 s. A full 3.2M
    build with two climate passes takes 7.7 min.
- **Provenance.** Algorithm identifiers move to `sphere-mesh-stream-power-v3`
  and `planet-climate-v2`.

## Result: 3.2M nodes, two climate passes, Aethelara

| Metric | Before (800k) | After (3.2M) | Earth |
|---|---:|---:|---:|
| Land above 1 / 2 / 3 km | 30 / 14 / 5.6 % | 28.9 / 7.4 / 2.2 % | about 29 / 11 / 5 % |
| Mean land height | 840 m | 838 m | about 700–840 m |
| Rivers > 1,000 / 2,000 / 3,000 km | 52 / 7 / 3 | 69 / 27 / 10 | about 180 / 47 / – |
| Longest river | 4,371 km | 5,145 km | 6,000–6,650 km |
| Largest basins, L / √A | 1.6–2.1 | 1.9–2.9 | 2.4–4.7 |
| Largest basin's share of its continent | 2–20 % | 5–21 % | 7–39 % |
| Hack exponent, basins ≥ 10⁴ km² | 0.51 | 0.56 | 0.46–0.55 |
| Lakes (endorheic) | 53 (9) | 106 (5) | |

Hot and cold desert together cover 17 % of land.

Two caveats on the mountain figures. The mountain mask (above 1,500 m, or above
1,000 m and rugged) now also covers plateaus. Its area-weighted width (361 km)
therefore measures belts together with their plateaus; individual chains are
100–250 km wide.

## Limits and next steps

- **Medium-length rivers.** There are still about 2.5× too few rivers longer
  than 1,000 km. Earth's count comes from many medium basins with elongated main
  stems, which longitudinal valleys between parallel ranges would create.
- **Range structure.** A belt is a single axial ridge. Earth's belts have
  parallel sub-ranges, foothills and intermontane basins.
- **Fjords and coastline.** Fjords come from the authored coastline. Real fjords
  are 1–10 km wide (about one pixel at 6 km per pixel), so a realistic fjord
  coast is a fine fringe rather than inlets tens of kilometres wide. Changing it
  stays the author's decision.
- **Resolution dependence.** With a 600 km² process area, meshes coarser than
  about 1.6M nodes no longer resolve it, so their relief is a preview. Geology
  calibration transfers from a 100k mesh, which is now further from the target
  resolution.
