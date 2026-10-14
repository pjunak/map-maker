# Natural-looking planet and regional maps — 2026-10-07

Status: **implemented, experimental display layer.** The user reviewed the first
authored-world atlas and called it "extremely unrealistic and jarring". This
report records what made it look artificial, what replaced it, and the
measurements behind the choices. Everything here is a derived display: the
authoritative relief (planet mesh nodes, regional tile meshes) and every exported
GeoTIFF are unchanged by the display detail.

## What looked wrong

| Symptom | Cause |
|---|---|
| Glowing cyan halo around every coast | Uniform 120 km shelf, bright shallow-water colours |
| Posterised, patchwork land | One flat colour per Whittaker biome class |
| Thick zig-zag rivers | Mesh-edge polylines, constant 2-4 px width, no smoothing |
| Plastic, glossy relief | Hypsometric tints and a single-light hillshade on smooth relief |
| Smooth ramps between rivers | The mesh resolves landforms only to its process scale (tens of km) |
| Regional windows: smooth domes, flat white snow blobs | 5 km tile mesh; regional slopes median 3 %, 90th percentile 5 % |

## World atlas (`atlas.png`, `relief.png`)

- **Continuous land colour.** Colour follows aridity (precipitation / Hargreaves PET)
  and the lapse-corrected temperature: desert → steppe → grassland → forest,
  tundra, rock on steep or high ground, bare dryland hills and perennial snow.
  There are no class boundaries.
  - **Ragged boundaries.** Soil patchiness at 300 km and 35 km breaks up vegetation
    edges and hides the parent mesh's straight triangle edges.
  - **Desert hue.** Varies between ochre, sand and grey gravel.
- **Snowline.** Snow follows the warm-season temperature at the displayed height.
  - It wanders by about ±1.4 °C with local climate noise.
  - It lies about 2.5 °C lower on shaded slopes.
  - It leaves steep faces bare.
- **Display detail.** Derivative-damped ("eroded") fBm is added below the mesh scale.
  - Rolling texture in lowlands becomes ridged texture in mountains.
  - It is faded at the coast and along large rivers.
  - New numba kernel `eroded_fbm`, about 60 M samples/s.
- **Hillshade.** Multi-directional: 315°/42° at weight 0.62, 270°/50° at 0.23 and
  355°/55° at 0.15, normalised to 1 on flat ground.
- **Sea.**
  - **Colour.** Depth-tinted with darker, less saturated shallows.
  - **Shelf width.** Varies along the coast from about 10 to 260 km, with noise at
    about 400 km. A uniform shelf drew an identical halo around every coast.
  - **Deep floor.** The shelf break drops onto a steep slope, a continental rise,
    abyssal plains, and broad ridges or swells.
- **Rivers.**
  - **Drawing.** Rivers follow discharge, are Chaikin-smoothed and tapered, and are
    drawn 2× supersampled and downsampled with Lanczos.
  - **Width.** Grows with (Q / Q_max)^0.4.
  - **Dryland corridors.** In drylands, a blurred river mask raises local
    moisture, so rivers get green corridors; humid land is unaffected.
- **Finer process area.** The default A0 is now 2,500 km² (was 10,000 km²), so
  smaller valleys form. Erodibility is 5e-6 (was 4e-6), so mean relief stays
  comparable.
  - **Convergence (no climate).** Mean land height is 567 m at 200k nodes and
    580 m at 800k.

## Regional windows (`map-maker world region`, World-tab zoom)

Regional windows now use the same colouring, with these additions.

- **Real bathymetry.** The parent's display ocean floor (`sea_floor_m`) replaces a
  constant −2,000 m.
- **Sub-tile ridges and valleys.** This is display only.
  1. **Roughness.** Ridged noise at 30 km and 5 octaves, scaled by 70 m + 0.6 × tile
     height, gives the surface roughness.
  2. **Valley carving.** Four implicit stream-power steps (Braun & Willett, n = 1,
     m = 0.5, K·dt = 0.4) are routed with Priority-Flood and D8 over the rough
     pixel surface. They carve it into a connected, branching valley network.
     - The incision is capped at the local detail amplitude.
     - It is blurred with σ = 1.3 px, which widens one-pixel channels into valleys.
     - It is gated by the tile surface's slope (0.6–3 %), because flats and
       plateaus carve into straight grid-aligned grooves.
  3. **Window rim.** Cells outside the circle hold their nearest inside height.
     Otherwise every border valley cuts down to the rim.
- **Snow and vegetation** are lapse-corrected to the displayed relief, so snow sits
  on ridges and valleys stay green.

Measured on three Aethelara windows at 500 m per pixel:

| Window | Height band | Slope median / 90th percentile, tile only | With display relief |
|---|---|---:|---:|
| Glaciated coastal range | >1,500 m | 0.053 / 0.105 * | 0.152 / 0.326 |
| Glaciated coastal range | 500–1,500 m | 0.033 / 0.069 * | 0.055 / 0.117 |
| Glaciated coastal range | <500 m | 0.008 / 0.026 * | 0.010 / 0.038 |
| Hot desert plain | 0–500 m | 0.003 / 0.006 | 0.012 / 0.023 |

\* The tile-only column already includes the first, weak noise trial (50 m standard deviation).

- **Cost.** Carving takes 1.5–2.5 s for a 1,400² window.
- **Rejected trials.**
  - Pure fractal detail at 12 km wavelength gave realistic slopes but read as
    crumpled paper: there was no drainage organisation.
  - Unblurred incision drew D8 hatching (parallel straight channels).

## Calibration-transfer test

`test_large_meshes_calibrate_on_a_coarse_mesh_then_run_once` failed at a median
transfer error of 0.207 (limit 0.2) after the A0 change.

- **Why it failed.** The test's meshes have about 21,000 km² per cell, so a
  2,500 km² process area measures coarse-mesh dependence, not calibration transfer.
  Production keeps A0 at about 4 fine cells at 800k nodes.
- **Errors by process area** (24k fine nodes):

  | A0 | Coarse nodes | Median error | Max error |
  |---|---:|---:|---:|
  | 10,000 km² | 6k | 0.163 | 0.39 |
  | 2,500 km² | 6k | 0.207 | 0.42 |
  | 94,000 km² (production ratio) | 6k | 0.073 | 0.51 |
  | 94,000 km² (production ratio) | 3k | 0.128 | 0.35 |

- **Change.** The test now uses 90,000 km² and keeps its 0.2 bound.

## Treeline and wetlands

On flat cold plains the boundary between forest, grassland and tundra followed
a line of latitude. It blended across 4–11 °C of summer warmth, about 1,000 km
of a lowland plain, so the plain looked smudged rather than textured.

- **Treeline.** Tundra now replaces forest near the 10 °C warmest-month isotherm
  (Köppen ET), over 7.5–10.5 °C.
- **Effective warmth.** The warmth that places treeline and forest varies
  locally:
  - it varies by ±`ECOTONE_C` (3 °C) with the vegetation mosaic noise (~300 km
    and ~35 km);
  - it is up to 1.2 °C warmer in sheltered valleys and cooler on exposed crests;
  - it is up to 4 °C warmer along rivers, where gallery forest reaches poleward
    (Mackenzie, Lena).

  The forest-tundra is then a ragged mosaic 100–300 km wide.
- **Wetlands.** Flat, low, humid ground with cool summers (5–20 °C) drains
  badly and is drawn as mottled dark-olive peatland (West Siberian Plain,
  Hudson Bay Lowlands).

## Aethelara (private; not committed)

The run used 800k nodes, two climate passes and a 5,760 px atlas, and took about
5 min.

- **Relief.** Mean land height 788 m, maximum 5,790 m; Hack exponent 0.472;
  compass-sector share 0.245; no non-descending receivers.
- **Lakes.** 69 lakes, 8 of them endorheic.

## Limits and next steps

- **Display only.** Display detail is not part of `elevation.tif` and does not drive
  rivers, lakes or climate. A real sub-mesh process needs regional tiles at finer
  spacing, or an exported, inherited-hydrology detail product (ADR-0048).
- **Regional colour.** Regional vegetation and snow come from the parent climate;
  there is no regional climate yet.
- **Coastline staircases.** Staircases in the authored coastline stay visible at
  regional zoom. They belong to the source drawing.
- **D8 grooves.** Some remain on moderate slopes; multiple-flow-direction routing
  would remove them.
