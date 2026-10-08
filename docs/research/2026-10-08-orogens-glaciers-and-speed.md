# Orogen structure, glacial buzzsaw, realism gates and speed — 2026-10-08

Status: **implemented, experimental.** This follows
[Earth-scale landforms](2026-10-07-earth-scale-landforms.md).

## Methods survey

A literature survey ranked candidate methods by benefit ÷ effort for this
pipeline. Items 1, 3, 4, 5 and part of 7 are implemented here. Item 6 was tried
and rejected (see below). Items 2 and 8 remain open.

1. **Realism gates.**
   - Hack's law (h ≈ 0.5–0.6); Horton bifurcation 3–5 and length 1.5–3.5
     (Horton 1945; Strahler 1952).
   - Hypsometry against Earth.
   - χ co-linearity (Perron & Royden 2013).
   - Hovius W/S ≈ 2.
   - Spectral slope β ≈ 2 (Perron et al. 2008).
2. **Analytic n = 1 stream power.** Elevation follows the receiver tree:
   z_i = z_r + U_i (τ_i − τ_r), with τ_i = τ_r + L / (K_i Ã_i^m) capped at the model
   time (Steer 2021; Tzathas et al. 2024). Five to twenty routing iterations
   replace 300 time steps. A coarse-to-fine version would keep the transient
   history.
3. **Cheaper depression handling and parallel accumulation**: Priority-Flood
   (Barnes et al. 2014), level-set parallel routing (Barnes 2019), FastFlow
   (Jain et al. 2024).
4. **Glacial buzzsaw**: peak heights follow the snowline (Egholm et al. 2009).
   Ice-flux fjords are a candidate (Kessler et al. 2008); see below.
5. **Strike-aligned lithology.** Hard and soft rock bands parallel to a belt pin
   divides and create longitudinal valleys (Bernard et al. 2021).
6. **Sediment deposition** (Yuan et al. 2019, G term) with flexure (Wickert 2016).
7. **Rendering**:
   - texture shading (Brown 2010) and sky-view factor (Zakšek et al. 2011);
   - terrain generalisation (Leonowicz et al. 2010);
   - flow-aligned multi-scale amplification on zoom (Schott et al. 2024).
8. **Climate**:
   - an energy-balance continentality term (North et al. 1981);
   - cold eastern-boundary currents giving coastal deserts (Rodwell & Hoskins 2001);
   - monthly harmonics with Köppen classes;
   - linear orographic rain on regional tiles (Smith & Barstad 2004).

## Implemented

- **Composite orogens.** Each great belt is a main axis with a frontal range and
  foothills on the foreland side and a hinterland range on the other.
  - **Geometry.** Positions are taken from the signed across-strike distance
    f / |∇f|; which side faces the foreland changes along strike.
  - **Irregularity.** Sub-ranges wander ±50 %, vary in strength and come and go
    in en-echelon segments.
  - **Plateaus.** Orogenic plateaus sit on the hinterland side.
  - **Fold belts.** Some minor belts are fold belts with parallel ridges
    45 km apart.
- **Strike-aligned lithology.** A hard core (0.55× erodibility) is flanked by
  weak and strong bands (±30 %) parallel to strike, with a noisy phase.
  - **Effect.** Rivers run along strike between ranges before breaking through.
  - **Rivers.** Main stems over 2,000 km went from 27 to 33.
- **Glacial buzzsaw.** Erodibility is multiplied by 1 + 1.5 · (z − ELA)/1 km,
  capped at 5×.
  - **Snowline.** The ELA comes from the climate model's warm-season sea-level
    temperature and lapse rate, plus 300 m: about 4.5 km in the tropics and
    under 1 km near the poles.
  - **Effect.** The highest peak fell from 11.3 km to about 6.4–7.2 km without
    changing the height distribution.
- **Speed.**
  - **Noise.** Value-noise fBm is now a parallel Numba kernel. It is
    bit-identical to the numpy version and 136× faster; it had been 53 % of
    generation time.
  - **Routing.** Steepest-descent receivers are computed directly on the
    surface. Priority-Flood runs only on steps that contain pits; pits vanish
    after about 200 of 300 steps.
  - **Ordering.** An O(n) traversal of the receiver tree replaces the per-step
    argsort.
  - **Result.** A 3.2M relief-only run went from 311 s to 144 s; an 800k run
    takes 27 s. A full 3.2M build with two climate passes went from
    7.7 min to 4.9 min.
- **Openness shading.** Height above the local mean at 8, 30 and 120 km,
  squashed with tanh, modulates the atlas light by ±30 %. This is a cheap
  stand-in for texture shading and sky-view factor.
- **Gate metrics.** `benchmarks.planet.scale_metrics` now reports Strahler
  orders, Horton bifurcation and length ratios, and source-to-mouth sinuosity.

## Boundary currents and ice sheets (second batch)

- **Boundary currents.** The direction to the nearest coast, −∇(coast
  distance), tells which side of an ocean basin a node is on.
  - **Cold side.** Water whose nearest land lies to the east, and land whose
    nearest sea lies to the west, get a cold anomaly of up to −5 °C between 8° and
    42° latitude. Examples are the California, Humboldt, Canary and Benguela
    currents.
  - **Warm side.** The opposite side gets +2.5 °C between 12° and 50°.
  - **Reach.** About 700 km offshore and about 250 km inland.
  - **Rain.** Large-scale rain is suppressed by up to 85 % under the subsiding air
    of a full cold anomaly (Rodwell & Hoskins 2001).
  - **Effect.** At 800k nodes, hot desert went from 6.3 % to 6.7 % of land, in
    narrow subtropical west-coast belts. Savanna went from 22.4 % to 20.2 %.
    Mediterranean shrubland went from 0.8 % to 0.4 %, because the class requires
    hot summers that the cool coasts now lack.
  - **Provenance.** The climate algorithm identifier is now `planet-climate-v3`.
- **Ice-sheet display surface.** Ice is drawn on Nye's perfectly plastic profile,
  h = √(2τ₀/(ρg) · d), with τ₀ = 100 kPa and d the graph distance from the ice
  margin, over a bed smoothed at about 150 km.
  - **Effect.** Polar ice shades as smooth domes about 3 km high with steep
    margins, and nunataks keep their own height.
  - **Scope.** Display only. Exported elevation stays at bedrock.

## Foreland and intermontane basins (third batch)

Mountain loads flex the crust down in front of a range and between its parallel
ranges, and rivers fill the space into flat alluvial plains: the Indo-Gangetic,
Po and Mesopotamian plains, and the Tarim and Fergana basins.

- **Basin field.** The forcing now exports a basin depth on the foreland side of
  great orogens: up to 1,500 m, centred 3.2 half-widths from the main axis.
  Between the main axis and the hinterland range it is up to 800 m deep.
- **Filling.** After erosion the depression is imposed and filled with
  Priority-Flood to its spill level. 4 % of the old relief is kept above the
  fill, so fans slope gently from the mountain front and rivers gather along the
  basin axis. A second fill keeps the plain well drained.
- **Display detail.** World-scale detail amplitude now also scales with
  mesh-scale slope, between 0.2× and 1×, so flat plains and plateau tops stay
  smooth.

### Lakes

- **First version.** The fan relief left pits, giving 271 lakes (86 closed,
  1.7 % of land).
- **With the second fill.** 88 lakes (14 closed, 0.43 % of land), against 41
  before the basins, at 800k nodes.

### Effect on height and IDs

- **Heights.** Land mean went from 875 m to 834 m; land above 1 km went from
  29.9 % to 28.1 %.
- **Provenance.** The relief algorithm identifier is now
  `sphere-mesh-stream-power-v5`.

A conserving sediment model with flexure would replace this geometric
imposition later. It already gives the right landform: flat, well-drained
lowlands along ranges, with the occasional long lake in an intermontane trough.

## River counts measured like a gazetteer

Earth's 230–250 rivers longer than 1,000 km (Grill et al. 2019) include major
tributaries such as the Missouri, Madeira and Irtysh. Main stems that reach the
sea undercount against that.

- **New metric.** `scale_metrics` now also decomposes the network into rivers.
  Each river follows its largest-area branch upstream and ends where it joins a
  larger river.
- **Result.** v10 has 332 / 118 / 34 / 13 rivers longer than 500 / 1,000 /
  2,000 / 3,000 km. Earth, scaled to this land area, has about 180 longer than
  1,000 km and about 47 longer than 2,000 km.
- **Length correction.** Mesh paths at 12 km miss reach-scale meanders
  (sinuosity 1.1–1.4), so true lengths would be about 20–30 % longer.
- **Conclusion.** River counts are now within resolution of Earth's.
- **Swell test.** Weakening, removing or moving the passive-margin swell inland
  changed main stems over 1,000 km only between 75 and 86. The swell is not the
  limit.

## Rejected trials

- **Analytic steady-state solver** (Steer 2021; Tzathas et al. 2024).
  - **Method.** Response times along the receiver tree, z_i = z_r + L U /
    (K Ã^m), capped at the uneroded surface z₀ + U t where the erosion wave has
    not arrived; eight route-and-rebuild iterations.
  - **Speed.** About 3× faster at 800k nodes (8 s against 24.6 s).
  - **Rivers.** The networks became regular herringbone trees with straight
    trunks. Main stems longer than 500 km fell from 154 to 51.
  - **Ranges.** Composite sub-ranges smoothed away.
  - **Spikes.** Isolated nodes rose to 59 km.
  - **Conclusion.** The time-stepped history (inherited drainage, growing
    ranges) carries information the steady state lacks. Time-stepping on the
    coupling mesh with an analytic refinement on the fine mesh remains a
    candidate.

- **Lifting isolated pits** to just above their lowest neighbour, with a
  fallback to Priority-Flood. The persistent pits are multi-node flats, so the
  fallback ran anyway and the run was slower (168 s against 144 s).
- **Sediment deposition** (Yuan G term). Three trials:
  1. **In-step Gauss–Seidel with two passes.** It oscillated: the first pass
     over-deposits, the second sees no net erosion, and every step ended with no
     deposition.
  2. **Lagged, damped flux with uplift rates halved.** Sediment also settled
     inside mountains and rebuilt wide massifs; above 3 km went from 1.7 % to
     5.1 %.
  3. **Slope-limited deposition.** Every gentle lowland aggraded: the median
     height went from 487 m to 996 m, and G = 3 diverged.

  Per-node G·Qs/A on a 24 km mesh does not keep a realistic sediment budget. A
  conserving scheme that removes deposited volume from the downstream flux,
  together with flexure, is needed before alluvial plains can be revisited.

## Result: Aethelara, 3.2M nodes, two climate passes (v10)

| Metric | v8 (previous commit) | v10 | Earth |
|---|---:|---:|---:|
| Build time | 7.7 min | 4.9 min | |
| Land above 1 / 2 / 3 km | 28.9 / 7.4 / 2.2 % | 30.6 / 8.4 / 3.1 % | about 29 / 11 / 5 % |
| Maximum height | 7,043 m | 7,208 m | 8,849 m |
| Rivers > 1,000 / 2,000 / 3,000 km | 69 / 27 / 10 | 72 / 33 / 12 | about 180 / 47 / – |
| Horton bifurcation / length ratio | 4.92 / 2.19 | 4.84 / 1.83 | 3–5 / 1.5–3.5 |
| Main-stem sinuosity (median, basins ≥ 10⁵ km²) | 1.46 | 1.53 | 1.5–2.0 source to mouth |
| Hack exponent (basins ≥ 10⁴ km²) | 0.56 | 0.57 | 0.46–0.55 |
| Hot + cold desert share | 17 % | 17 % | |

The relief algorithm identifier is now `sphere-mesh-stream-power-v4`.

## Next candidates

- **Speed.** An analytic steady-state finish on the fine mesh would cut erosion
  time again, as would level-set parallel accumulation.
- **Climate.**
  - Cold-current coastal deserts.
  - Seasonal continentality from an energy-balance term.
  - Köppen classes that drive the atlas colours.
- **Zoom rendering.** Flow-aligned amplification on regional tiles in place of
  the display noise plus valley carving.
- **Range structure.** Medium-length rivers are still short of Earth's count.
  Plate-boundary-driven belt placement (a light Cortial et al. 2019) would make
  belt geometry follow tectonics instead of noise.
