# Plate tectonics and sediment — 2026-10-08

Status: **implemented, experimental.** This follows
[orogens, glaciers and speed](2026-10-08-orogens-glaciers-and-speed.md). The work
order runs from foundations up: plates (where things are), then sediment (how
they evolve), then zoom detail (how they look), then parallel speed.

## Plate tectonics (light Cortial et al. 2019)

`pipeline/planet_tectonics.py` splits the sphere into 18 plates.

- **Plates.** A Voronoi of random seeds on a noise-warped metric, so boundaries
  bend.
- **Motion.** Each plate rotates about its own Euler pole at 0.25–1.1°/Myr,
  which gives surface speeds of a few cm/yr.
- **Boundaries.** The closing rate across a boundary is (v_a − v_b)·n̂.
  - **Convergent inside a continent:** a composite collision orogen. Its
    half-width grows with the closing rate (50–130 km). Its foreland basin and
    hinterland plateau come from the signed distance to the boundary. Which side
    is the foreland is a fixed property of each plate pair.
  - **Divergent inside a continent:** a rift graben, about 900 m deep and filled
    as a basin, with uplifted shoulders.
- **Leading edges.**
  - **Rule.** Where a coast's plate moves seaward (4 cm/yr counts as fully
    leading), the coast is an active margin with a coastal cordillera and an
    offshore trench, as in the Andes. Trailing coasts are passive (Inman &
    Nordstrom 1971).
  - **Change.** This replaces the noise gate that placed active margins and
    trenches.
- **Old orogens.** The earlier noise-placed great belts remain at 45 % of the
  active uplift, with their own strike-aligned lithology, standing for welded
  sutures such as the Urals, Appalachians and Caledonides.
- **First trial.** With 14 plates and no old orogens, too few boundaries crossed
  land. Land above 3 km fell to 2.4 % and the large eastern orogen disappeared.
- **Cost.** Building the plates takes about 0.6 s at 400k nodes.

### Result at 800k nodes (Aethelara)

| | Before (noise belts) | Plates + old orogens | Earth |
|---|---:|---:|---:|
| Land above 1 / 2 / 3 km | 29.5 / 8.0 / 2.9 % | 31.1 / 9.4 / 3.5 % | about 29 / 11 / 5 % |
| Rivers > 1,000 km (gazetteer) | — | 108 | about 180 at this land area |
| Horton bifurcation ratio | — | 5.03 | 3–5 |
| Lakes (endorheic) | 88 (14) | 110 (12) | |

Belts now follow plate boundaries: collision ranges cross continents where
plates converge, rifts with lakes open where they diverge, and coastal
cordilleras line the leading edges.

The relief algorithm identifier is now `sphere-mesh-stream-power-v7`.

## Sediment budget: delta shelves

The authored coastline means sediment cannot build new land. It can, however,
build continental shelf off river mouths.

- **Flux.** Near steady state, erosion balances uplift, so each river mouth
  delivers Qs = Σ U·area over its catchment, in m³/yr.
- **Shelf.** Most sediment ever delivered leaves the shelf for deep-sea fans or
  drifts along the coast, so the shelf a river builds follows its present flux:
  R = 15 √Qs, capped at 350 km. Rivers below 10⁷ m³/yr build none.
  - **Calibration.** The Amazon (~4×10⁸ m³/yr) reaches about 300 km and the
    Rhône (~2×10⁶ m³/yr) about 20 km.
- **Rejected first trial.** Scaling by the 30 Myr volume put every median river
  on a 260 km shelf.
- **Effect.** The atlas shows broader, lighter shelves off the largest rivers.
- **Provenance.** The relief algorithm identifier is now
  `sphere-mesh-stream-power-v8`.
- **Not done.** A sediment-conserving land model, where basin fill is bounded
  by catchment supply, remains a TODO.

## Terrain-coupled vegetation (zoom detail)

Vegetation was a climate field with noise patches. At regional zoom it ignored
the relief, so forests and grassland formed blobs that crossed ridges.

- **Moisture.** Land colour now shifts moisture by terrain position: ±0.5 in log
  aridity, from height above the local mean.
  - **Atlas scales.** 8, 30 and 120 km, as for openness shading.
  - **Regional scales.** 3 and 15 km.
  - **Effect.** Valleys gather water and soil, so they are greener and forested.
    Ridges and slopes steeper than about 10 % are drier.
- **Mosaic grain.** The finest mosaic noise drops from 35 km to 8 km in regional
  windows.
- **Result.** Forest now grows in dendritic patterns up the valleys and ridges
  read as open country, as on satellite imagery of humid hill country.

## Speed: local depression filling

A profile of a full 3.2M build showed flow routing at 177 of 332 s, almost all of
it in the global Priority-Flood on steps that still had pits.

- **Localised fill.**
  - **Method.** Only catchments that drain into pits need filling. They are found
    by walking up the receiver tree from the pits (`draining_to`), and
    Priority-Flood then runs on them alone, seeded from their well-drained rims.
  - **Accuracy.** Results match the global fill to within 1 µm.
- **Parallel receivers.** The steepest-descent receiver kernel now runs in
  parallel.
- **Result.** Routing went from 177 s to 76 s, and a full 3.2M build with two
  climate passes from about 5 to about 4 minutes.
- **Remaining costs** (3.2M build):
  - mesh construction, about 20 s per mesh;
  - per-step array arithmetic in `evolve`, about 35 s;
  - climate, about 30 s;
  - plate tectonics, computed four times, about 18 s.

## Limits

- **Ridges.** Mid-ocean ridges still come from the boundaries between the
  oceans nearest to each landmass, not from divergent plate boundaries. The two
  agree in spirit but are not linked.
- **No motion of land.** Plates never move land, because the coastline is
  authored. Collision belts are where boundaries happen to cross land, not where
  continents have actually collided.
- **No island arcs.** Ocean–ocean convergence makes no island arcs: new land
  would change the authored coastline.
