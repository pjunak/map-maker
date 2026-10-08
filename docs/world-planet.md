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

## In the desktop app

Open or import a world in the **World** tab, then choose **Planet…** (or the
**Planet** page in the sidebar):

1. **Choose the detail.**
   - Quick: 50k nodes, about 100 km apart.
   - Standard: 200k nodes, about 50 km.
   - Detailed: 800k nodes, about 25 km.
2. **Set the options.** Keep **Climate, lakes and biomes** on for the atlas,
   rainfall and temperature layers. Optionally choose a geology recipe; a
   recipe saved from the Geology editor is picked up automatically.
3. **Click Generate planet.** Progress shows below the map, and **Cancel planet
   job** stops at the next checkpoint without installing a result.
4. **Pick a layer** above the map: **Planet atlas**, **Planet relief**, **Planet
   rainfall** or **Planet temperature**. Hovering shows the ground height,
   lake, river discharge, temperature, rainfall and biome under the cursor.
5. **Click Export planet…** to write the same build folder as the command line.

Editing the world (names, frame, assignments) discards the generated planet, so
a stale planet is never shown as current.

### Zoom into regional detail

With a planet shown, pan and zoom the map to the area you care about and click
**Zoom detail at map centre** on the Planet page.
- A window opens with that region at about 5 km detail: ridges, valley networks,
  altitude zones and rivers.
- Its radius follows how far you zoomed in, from 150 to 1,200 km.
- **Export region…** writes a local-projection GeoTIFF, previews and a manifest.

The region is built from fixed, cached tiles. Zooming the same place again is
quick and gives identical values, whichever window you choose.

## Run it from the command line

```powershell
dmtools world planet my-world.dmworld.json --output my-planet
dmtools world planet my-world.dmworld.json --geology my-world.dmgeology.json --output my-planet-geo
```

The output folder must not exist. Progress is printed. A cancelled or failed run
leaves no `manifest.json`, so it never looks complete.

| Option | Default | Meaning |
|---|---:|---|
| `--nodes` | 200,000 | Sphere mesh size. On an Earth-size world, 200,000 nodes are about 50 km apart, 800,000 about 25 km and 3,200,000 about 12 km. Use 3,200,000 for a final map: coarser meshes cannot resolve Earth-scale ranges and valleys and are previews. |
| `--geology` | none | A geology recipe for this exact world. Without one, ranges and margins are placed procedurally. |
| `--calibrate` | 3 | How many times each geology region's uplift is corrected towards its target elevation. |
| `--climate-passes` | 1 | Climate → erosion couplings. 0 skips climate and biomes. |
| `--erodibility` | 5e-6 | Lower values give higher overall relief. Geology targets are re-calibrated either way. |
| `--process-km2` | 600 | Smallest drainage area treated as a river at world scale. Smaller values give more, finer valleys; keep it at least a few mesh cells. |
| `--duration-myr` | 30 | Simulated history length. |
| `--seed` | 20261006 | Master seed. Mesh, forcing and initial noise each use a named stage seed. |
| `--width` | 4,096 | Width of the GeoTIFF and images. Height follows your SVG frame's aspect. |
| `--river-km2` | 25,000 | River size threshold, as a catchment area at the planet's mean runoff. Rivers are selected by discharge, so dry regions show fewer. |

Typical times on a 16-thread desktop:

| Run | Time |
|---|---:|
| 100k nodes, geology and one climate pass | about 50 s |
| 800k nodes, two climate passes | about 1.5 min |
| 3.2M nodes, two climate passes | about 5 min |

Regional detail for an exported planet:

```powershell
dmtools world region my-planet --lon 61 --lat -39.6 --radius-km 500 --output my-region
```

Tiles are cached in `my-planet.tiles/` beside the build and reused by later regions.
Use `--spacing-km` for a different detail spacing. A region writes `elevation.tif`
(the blended tile relief), `relief.png` and, with climate, a natural-colour `atlas.png`.

**What the images add.** Atlas and relief images draw small ridges, valleys and
texture below the mesh resolution, so slopes do not shade as smooth ramps. This
detail, including small valleys carved into it, is for display only. It is not in `elevation.tif` and does not change
rivers, lakes or climate. See the [rendering report](research/2026-10-07-natural-map-rendering.md).

## Outputs

| File | Contents |
|---|---|
| `atlas.png` | Natural-colour shaded relief: vegetation from dryness and temperature, rock, snow, depth-tinted sea, lakes and rivers (needs climate). |
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
   until each region's elevation statistic is close to its target. Without a
   recipe, ranges, minor fold belts, hill country and active margins are placed
   procedurally at scales from about 100 km to several thousand kilometres.
   Ranges have Earth-like widths (great ranges 120–350 km, minor ones 40–120 km)
   and lengths. Some great ranges carry a high plateau behind them, and broad
   swells lift whole regions. Old shields erode slowly, so plateaus stay smooth
   and rivers cut into them from their edges. Great ranges have frontal ranges,
   foothills and a hinterland range, with valleys between them where rivers run
   along the range. Above the snowline glaciers erode fast, so peaks stay within
   a few kilometres of it. In front of great ranges and between their parallel
   ranges the crust sags into basins that fill with sediment: flat plains with
   rivers along their axis, and sometimes a long lake.
4. **Climate.**
   - **Temperature** comes from latitude, height and distance from the sea.
   - **Winds** blow in trade, westerly and polar belts.
   - **Rain:** moisture travels with the wind, rains out on rising ground and over
     the tropics, and leaves rain shadows behind ranges. Weather systems also mix
     moisture sideways (strongest in the mid-latitude storm tracks), so desert
     edges grade over hundreds of kilometres. Cold ocean currents along
     subtropical west coasts cool them and suppress rain (coastal deserts); warm
     currents keep east coasts mild.
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
- **Regional detail.** It blends overlapping tiles. Inside the blend zones, river
  lines may jog slightly, and regional lakes and climate are not regenerated.
- **Local terrain.** The Terrain workspace does not yet start from this planet.
