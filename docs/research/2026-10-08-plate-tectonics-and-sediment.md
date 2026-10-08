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

## Limits

- **Ridges.** Mid-ocean ridges still come from the boundaries between the
  oceans nearest to each landmass, not from divergent plate boundaries. The two
  agree in spirit but are not linked.
- **No motion of land.** Plates never move land, because the coastline is
  authored. Collision belts are where boundaries happen to cross land, not where
  continents have actually collided.
- **No island arcs.** Ocean–ocean convergence makes no island arcs: new land
  would change the authored coastline.
