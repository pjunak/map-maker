# Whole-planet relief, climate and biomes (experimental)

`dmtools world planet` turns a saved world (`.dmworld.json`) into a whole-planet
map. It produces:
- relief made by uplift and river erosion;
- an ocean floor;
- a provisional climate (temperature, rain, runoff);
- provisional biome labels;
- lakes, both open and closed basins;
- river lines.

The planet keeps your coastline exactly; zoomed maps only add detail finer than
you drew it. An optional geology recipe (`.dmgeology.json`)
says where mountains, plateaus, old worn ranges and basins should be. The
generator honours those elevations approximately and lets erosion shape every
valley and divide.

This is experimental, so it is not yet an accepted world parent for local or zoomed
terrain. See [ADR-0085](adr/0085-generate-planet-relief-on-a-sphere-mesh.md) and the
evidence for [relief](research/2026-10-06-whole-planet-erosion-relief.md) and
[climate](research/2026-10-06-planet-climate-v0.md).

## In the desktop app

Open or import a world in the **World** tab. The stages run down the left
(Shapes, Frame, Context, Planet, Terrain); the map is on the right.

1. **Open the 4 Planet stage and choose the detail.**
   - Quick: 50k nodes, about 100 km apart.
   - Standard: 200k nodes, about 50 km.
   - Detailed: 800k nodes, about 25 km.
   - Fine: 3.2M nodes, about 12 km.
2. **Set the features.**
   - Keep **Climate, lakes and biomes** on for the atlas, climate zone, rainfall
     and temperature maps.
   - **Volcanic islands** and **Wonders** are optional.
   - Optionally choose a geology recipe. A recipe saved from the Geology editor is
     picked up automatically.
3. **Click Generate planet.** The status bar under the map shows progress.
   **Cancel** stops at the next checkpoint without installing a result. The app
   stays responsive while it works.
4. **Choose what the map shows** with the bar above it:
   - **Source · Context · Planet** picks the data.
   - The list beside it picks the map: every theme the planet rendered, such as
     atlas, relief, climate zones, topographic, parchment, plates, sea-floor age,
     drainage basins and geology.
   - **Flat world · Globe · North polar · South polar** picks the projection.
     **Grid** draws latitude and longitude every 30°.

   On a flat map, drag to pan, use the wheel to zoom and press F to fit. On a globe,
   drag to turn it; on a polar view the wheel also zooms. Below the map:
   - the legend explains the current map;
   - **Under the cursor** reads out the ground height, lake, river discharge,
     temperature, rainfall, Köppen zone and any volcano.
5. **Save image…** writes what is shown as a PNG: a flat planet map at its full
   width, or the current globe or polar view at 2,048 px.
6. **Click Export planet build…** to write the same build folder as the command line.

Editing the world (names, frame, assignments) discards the generated planet, so
a stale planet is never shown as current.

### Zoom into regional, province and local detail

With a planet shown, click **Zoom to region** above the map:
1. Choose a radius, or keep **Auto**. Auto takes about half the visible width,
   from 150 to 1,200 km.
2. Click the map, flat or globe. A circle shows the area before you click; Esc
   cancels.

The region opens in the same view, at about 5 km detail: ridges, valley networks,
altitude zones and rivers. From a region, **Zoom to province** builds 1 km detail
(30–300 km radius); from a province, **Zoom to local** builds 200 m detail
(6–60 km radius). Each level is enriched from the one above
([ADR-0088](adr/0088-nested-regional-detail-levels.md)).
- The path above the map (**World / Region … / Province …**) returns to any larger
  map. Each larger map outlines the smaller ones opened from it.
- Choose **Planet atlas**, **Planet relief**, **Planet topographic** or **Planet
  parchment**. Each renders in the background and is kept. The topographic view
  stretches its tints over the window's own height range and draws contours at
  true heights.
- Coasts gain detail as you zoom. The planet keeps your drawn coastline exactly.
  Regional, province and local maps smooth it at the precision you drew it, then
  add bays, headlands, coves and islets at every finer scale. Each deeper level
  only adds smaller detail, so a coast keeps its shape as you zoom in. The coast
  can move by up to about one drawing unit from your line, which is 13 km on an
  Earth-size world drawn 2,880 units wide
  ([ADR-0090](adr/0090-regional-coast-detail-below-drawing-precision.md)).
- Volcanoes, impact craters and chasms are drawn sharply. Closed hollows deeper
  than 10 m (crater troughs, chasm floors, calderas) fill with lakes where it is wet. Where it is dry, a playa
  lies only in the lowest part.
- A scale bar shows distance. Hovering shows the place, the offset from the centre
  and the height.
- **Export region…** writes a local-projection GeoTIFF, previews and a manifest.

Every level is built from fixed, cached tiles. Zooming the same place again is
quick and gives identical values, whichever window you choose. Deeper levels
first build the coarser tiles they need, so a first province or local zoom takes
a few minutes.

### Views of a saved build

A saved build can be viewed the same way from the command line:

```powershell
dmtools world view my-planet --theme atlas --projection globe --lon 40 --lat 20 --graticule --output globe.png
dmtools world view my-planet --theme koppen --projection north-polar --limit 30 --output arctic.png
```

`--theme` is a build image's name without `.png`: `atlas`, `relief`, `koppen`,
`volcanoes`, `precipitation`, `temperature`, and the thematic maps `plates`
(tectonic plates, boundary types and motion), `seafloor` (ocean-crust age),
`basins` (drainage basins) and `geology` (geological provinces), and `topographic`
(hypsometric tints with contours every 500 m on a 4,096-5,760 px world, every
fifth bold, and isobaths). A polar view's `--lon` is the
meridian below (north) or above (south) the pole, and `--limit` is the latitude
at its edge (0 = the equator). Views are deterministic and never overwrite a
file ([ADR-0087](adr/0087-map-themes-and-projections.md)).

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
| `--wonders` | off | Add fantastical landmarks beyond Earth's extremes: a titan shield volcano (~10 km high, ~560 km across, ice-capped, with a basal cliff), 1-3 impact craters 180-300 km across that may hold ring lakes, and a great chasm 900-2,200 km long, 60 km wide and up to 3 km deep, with side canyons and uplifted shoulders. Also a checkbox on the Planet page. |
| `--volcanic-islands` | off | Let young volcanoes at sea rise as islands: hotspot chains of shield islands and island arcs behind ocean trenches. **Adds land beyond your coastline.** Also a checkbox on the Planet page. |
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
| 3.2M nodes, two climate passes | about 4 min |

Regional detail for an exported planet:

```powershell
dmtools world region my-planet --lon 61 --lat -39.6 --radius-km 500 --output my-region
```

Tiles are cached in `my-planet.tiles/` beside the build and reused by later regions.
Go deeper with `--level`. Each level is enriched from the level above it, and
windows at the same level agree wherever they overlap
([ADR-0088](adr/0088-nested-regional-detail-levels.md)).

| Level | Detail | Window radius | Example |
|---|---|---|---|
| 1 region | 5 km | up to 5,000 km | a kingdom, a mountain range |
| 2 province | 1 km | up to 300 km | valleys, a crater, a coast |
| 3 local | 200 m | up to 60 km | a few valleys, a town's surroundings |

```powershell
dmtools world region my-planet --lon 61 --lat -39.6 --radius-km 120 --level 2 --output my-province
```

The first deep window takes a few minutes, because it also generates the coarser
tiles it needs. Later windows nearby reuse the cache.

Options:
- `--spacing-km` sets the level-1 detail spacing (5 km by default).
- `--pixels` sets the image size (1,024 by default).
- `--cache` puts the tile cache elsewhere.
- `--workers` sets how many tile processes run (0 = automatic).

A region writes `elevation.tif` (the blended tile relief), `relief.png` and
`topographic.png`. With climate it also writes the natural-colour `atlas.png` and
the hand-drawn `parchment.png`.

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
| `koppen.png` | Köppen–Geiger climate zones in their standard colours. |
| `volcanoes.png` | The atlas with land volcanoes marked: red for active, dark for extinct. |
| `topographic.png` | Hypsometric tints, contour lines (every fifth bold), isobaths, soft hillshade and water. |
| `parchment.png` | A hand-drawn fantasy map: inked coasts, mountain, hill, tree, marsh and dune symbols, and rivers on aged paper (needs climate). |
| `plates.png`, `seafloor.png` | Tectonic plates with boundary types and motion; ocean-crust age. |
| `basins.png`, `geology.png` | Drainage basins with divides; geological provinces. |
| `elevation.tif` | Float32 elevation in metres (land, and an ocean floor with mid-ocean ridges, sea-floor ageing and trenches), on a geographic CRS for your world's sphere radius. |
| `rivers.geojson` | River polylines in world longitude/latitude, with discharge, contributing area and mouth (sea or lake). |
| `lakes.geojson` | Lake polygons with surface level, area and whether the lake is closed (endorheic). |
| `volcanoes.geojson` | Volcano points with kind (stratovolcano, shield, caldera, seamount), setting (arc, hotspot, rift, intraplate), activity, age, summit height and size. |
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
   recipe, the world is split into 18 rotating tectonic plates. Ranges rise
   where plates collide inside continents, rift valleys open where they pull
   apart, and coasts on a plate's leading edge get coastal ranges and offshore
   trenches. Volcanoes follow the plates: arcs inland of leading-edge coasts,
   hotspot tracks (shield volcanoes and calderas on land, seamount chains at
   sea) and rift volcanoes. Older, lower ranges, fold belts and hill country fill in at scales
   from about 100 km to several thousand kilometres.
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
