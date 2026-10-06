# Whole-planet relief, climate and biomes (experimental)

`dmtools world planet` turns a saved world (`.dmworld.json`) into a whole-planet
map. It produces:
- relief made by uplift and river erosion;
- an ocean floor;
- a provisional climate (temperature, rain, runoff);
- provisional biome labels;
- lakes, both open and closed basins;
- river lines.

Your coastline is never changed. An optional geology recipe (`.dmgeology.json`)
says where mountains, plateaus, old worn ranges and basins should be. The
generator honours those elevations approximately and lets erosion shape every
valley and divide.

This is experimental, so it is not yet an accepted world parent for local or zoomed
terrain. See [ADR-0085](adr/0085-generate-planet-relief-on-a-sphere-mesh.md) and the
evidence for [relief](research/2026-10-06-whole-planet-erosion-relief.md) and
[climate](research/2026-10-06-planet-climate-v0.md).

## Run it

```powershell
dmtools world planet my-world.dmworld.json --output my-planet
dmtools world planet my-world.dmworld.json --geology my-world.dmgeology.json --output my-planet-geo
```

The output folder must not exist. Progress is printed. A cancelled or failed run
leaves no `manifest.json`, so it never looks complete.

| Option | Default | Meaning |
|---|---:|---|
| `--nodes` | 200,000 | Sphere mesh size. On an Earth-size world, 200,000 nodes are about 50 km apart and 800,000 about 25 km. Time grows a little faster than linearly. |
| `--geology` | none | A geology recipe for this exact world. Without one, ranges and margins are placed procedurally. |
| `--calibrate` | 3 | How many times each geology region's uplift is corrected towards its target elevation. |
| `--climate-passes` | 1 | Climate → erosion couplings. 0 skips climate and biomes. |
| `--erodibility` | 4e-6 | Lower values give higher overall relief. Geology targets are re-calibrated either way. |
| `--process-km2` | 10,000 | Smallest drainage area treated as a river at world scale. Smaller values give more, finer valleys. |
| `--duration-myr` | 30 | Simulated history length. |
| `--seed` | 20261006 | Master seed. Mesh, forcing and initial noise each use a named stage seed. |
| `--width` | 4,096 | Width of the GeoTIFF and images. Height follows your SVG frame's aspect. |
| `--river-km2` | 25,000 | River size threshold, as a catchment area at the planet's mean runoff. Rivers are selected by discharge, so dry regions show fewer. |

Typical times on a 16-thread desktop:

| Run | Time |
|---|---:|
| 100k nodes, geology and one climate pass | about 50 s |
| 800k nodes | several minutes |

## Outputs

| File | Contents |
|---|---|
| `atlas.png` | Biome-coloured shaded relief with rivers (needs climate). |
| `relief.png` | Hypsometric shaded relief with rivers. |
| `precipitation.png`, `temperature.png` | Annual climate previews. |
| `elevation.tif` | Float32 elevation (land and display ocean floor) in metres, on a geographic CRS for your world's sphere radius. |
| `rivers.geojson` | River polylines in world longitude/latitude, with discharge, contributing area and mouth (sea or lake). |
| `lakes.geojson` | Lake polygons with surface level, area and whether the lake is closed (endorheic). |
| `planet.npz` | The authoritative mesh: nodes, triangles, land, elevation, receivers, drainage area, forcing and climate fields. |
| `world.dmworld.json`, `geology.dmgeology.json` | Snapshots of the inputs used. |
| `manifest.json` | Settings, stage seeds, input hashes, runtime, calibration, metrics and output hashes ([schema](../schemas/world/planet-build-v1.schema.json)). |

**Aligning with your drawing.** Images and the GeoTIFF cover exactly your SVG
world frame: column 0 is the left edge and row 0 is the top. Scale a PNG to the
SVG's size and it lies under your coastline drawing.

## How it works, briefly

1. **Mesh.** Nodes are spread evenly over the sphere and triangulated. There are no
   poles, seams or preferred directions.
2. **Uplift and erosion.** Land is uplifted, and rivers erode in proportion to
   drainage area and slope over millions of years. The coast is sea level.
   Depressions fill up like sediment basins, so every river reaches the sea.
3. **Geology.** Each region becomes an uplift rate and a rock hardness. For
   example, young belts are high and sharp, 300 Ma belts are low and smooth,
   plateaus are uplifted late, and basins are soft and low. Uplift is re-scaled
   until each region's elevation statistic is close to its target.
4. **Climate.**
   - **Temperature** comes from latitude, height and distance from the sea.
   - **Winds** blow in trade, westerly and polar belts.
   - **Rain:** moisture travels with the wind, rains out on rising ground and over
     the tropics, and leaves rain shadows behind ranges.
   - **Runoff** is rain minus evaporation. It makes wet regions erode more in the
     next pass.
   - **Biomes** come from temperature and dryness.
5. **Lakes.**
   - **Young depressions** are added where geology or climate says they belong:
     rifts, sedimentary basins, interior sags, and recently glaciated lowlands.
   - **Open lakes:** where inflow beats evaporation, the depression fills and
     overflows.
   - **Closed (endorheic) lakes:** otherwise the lake shrinks until evaporation
     balances inflow, and rivers end there. The previews show them in grey.

## Limits

- **Lakes.** Levels are a steady annual balance. Small lake districts are mostly
  below world resolution, and basins below sea level are not modelled yet.
- **Climate.** It is an explainable annual-mean model, not a weather or ocean
  simulation. Its constants are tuned to look Earth-like; change the planet
  assumptions in code until UI controls exist.
- **Ocean floor.** It is display only and does not yet use the separate
  bathymetry product.
- **Local terrain.** It does not yet start from this planet. That is planned
  (regional enrichment and zoom).
