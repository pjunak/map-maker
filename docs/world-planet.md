# Whole-planet relief, climate and biomes (experimental)

`map-maker world planet` turns a saved world (`.world.json`) into a whole-planet
map. It produces:
- relief made by uplift and river erosion;
- an ocean floor;
- a provisional climate (temperature, rain, runoff);
- provisional biome labels;
- lakes, both open and closed basins;
- river lines.

The planet keeps your coastline, except near the poles (see below); zoomed maps
only add detail finer than you drew it. An optional geology recipe (`.geology.json`)
says where mountains, plateaus, old worn ranges and basins should be. The
generator honours those elevations approximately and lets erosion shape every
valley and divide.

**Near the poles** a flat world drawing breaks down, so the planet works polar land
in true distance ([ADR-0094](adr/0094-planet-polar-land-in-true-distance.md),
[ADR-0100](adr/0100-smooth-polar-land-east-west.md)):
- A drawing unit east-west shrinks toward a pole, so shapes that look ordinary on
  the flat map would become thin radial fingers. Poleward of 55°, land is
  smoothed east-west only, more strongly nearer the pole (up to 4 drawing units
  across at the pole). The coast keeps its north-south place and follows the
  average of fingers and fjords; where smoothing barely moves it, it stays as
  drawn.
- Land and water narrower than half a drawing unit are then removed, so traced
  stair-steps do not become radial streaks. Tiny islets stay.
- Land drawn down to the map's top or bottom edge along only part of its width
  would meet the pole as a wedge. The planet covers that pole with land about 4°
  across, with a natural coast, so an ice sheet can dome over it. The build's
  manifest reports the added area under `metrics.pole_cover`.

Your drawing and the world's Source view are unchanged.

This is experimental, so it is not yet an accepted world parent for local or zoomed
terrain. See [ADR-0085](adr/0085-generate-planet-relief-on-a-sphere-mesh.md) and the
evidence for [relief](research/2026-10-06-whole-planet-erosion-relief.md) and
[climate](research/2026-10-06-planet-climate-v0.md).

## In the desktop app

Open or import a world in the **World** tab and work through its steps down the
left (Source map, Planet, Geology, Generate, Wonders, Explore; see the
[world guide](terrain-worlds.md#the-steps)). The map is on the right.

1. **Open the Generate step and choose the detail.** Each choice says how far
   apart the mesh points are and roughly how long it takes on a desktop:
   - Quick: 50k points, about 100 km apart; under a minute.
   - Standard (the default): 200k points, about 50 km; a minute or two.
   - Detailed: 800k points, about 25 km; a few minutes.
   - Fine: 3.2M points, about 12 km; ten minutes or more.
2. **Set the variation and features.**
   - The **Seed** picks one of many planets for the same world; **New seed** draws
     a random one. The same seed and inputs always give the same planet.
   - Keep **Climate, rivers, lakes and ice** on for the atlas, climate zone,
     rainfall and temperature maps.
   - **Volcanic islands** and the [wonders](wonders.md) are optional. Wonders
     are added to the finished planet: placing or changing them later in the
     **Wonders** step, or generating again with only the wonders changed, does not
     erode the planet again.
   - The **Geology** line says what the planet uses: the recipe in the Geology
     step, saved or not, or automatic mountain ranges when there is none.
3. **Click Generate planet.** The status bar under the map shows progress.
   **Cancel** stops at the next checkpoint without installing a result. The app
   stays responsive while it works. When it finishes, the **Explore** step opens
   with a summary of the planet.
4. **Choose what the map shows** with the bar above it:
   - **Source · Context · Planet** picks the data.
   - The list beside it picks the map: every theme the planet has, such as
     atlas, relief, climate zones, topographic, parchment, plates, sea-floor age,
     drainage basins and geology. The map shown when the planet is ready (the
     one you last looked at, else the first in the list) is drawn with it. Any
     other is drawn in the background the first time you choose it, while the
     map says **Drawing this map…**, and is then kept.
   - The projection list picks **Flat world**, **Globe**, **North polar** or
     **South polar**. **Grid** draws latitude and longitude every 30°.

   On a flat map, drag to pan, use the wheel to zoom and press F to fit. On a globe:
   - drag to turn it: the ground you grab follows the cursor, with north kept up;
   - flick it to set it spinning; it slows to a stop, and a click stops it;
   - use the wheel to zoom towards the cursor, up to 16 times, or + and - to zoom
     about the centre;
   - use the arrow keys to turn it;
   - press F to see the whole globe again.

   On a polar view, drag to turn it about the pole and use the wheel to show more
   or less of it. The globe fills the window and stays sharp while it turns
   ([ADR-0101](adr/0101-interactive-globe-views.md)). Opened regions are outlined
   on it, and a scale bar gives the distance at the centre of the view. Below the
   map:
   - the legend explains the current map;
   - **Under the cursor** reads out the ground height, lake, river discharge,
     temperature, rainfall, Köppen zone and any volcano.
5. **Save image…** above the map (or **Save the shown map as an image…** in
   Explore) writes what is shown as a PNG: a flat planet map at its full width, or
   the middle square of the current globe or polar view at 2,048 px, zoom included.
6. **Save the shown map as a 3D globe…** in Explore writes the whole-planet map
   you are looking at as a globe model (`.glb`) that 3D viewers, Blender and game
   engines can turn. See [Globe models](#globe-models).
7. **Click Export planet build…** in Explore to write the same build folder as the
   command line.

Editing the world (names, frame, assignments) discards the generated planet and
returns to the Generate step, so a stale planet is never shown as current.

### Zoom into regional, province and local detail

With a planet shown, click **Zoom to region** above the map, or **Pick a region
on the map** in Explore:
1. Choose a radius, or keep **Auto**. Auto takes about half the visible width,
   from 150 to 1,200 km.
2. Click the map, flat, globe or polar. A circle shows the area before you click;
   Esc cancels.

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
- Coasts gain detail as you zoom. Regional, province and local maps smooth it at the precision you drew it, then
  add bays, headlands, coves and islets at every finer scale. Each deeper level
  only adds smaller detail, so a coast keeps its shape as you zoom in. The coast
  can move by up to about one drawing unit from your line, which is 13 km on an
  Earth-size world drawn 2,880 units wide
  ([ADR-0090](adr/0090-regional-coast-detail-below-drawing-precision.md)). If
  your map already carries that detail, for example one exported from a planet's
  refined coast, enter the finest detail it carries as **Coast detail already
  drawn** in the Planet step: zoomed maps then keep its coast unsmoothed and add
  only finer detail. `map-maker world refine-coast` makes such a map: see
  [The refined coast as a source map](#the-refined-coast-as-a-source-map).
- Volcanoes, impact craters and chasms are drawn sharply, chasm outlines down to
  the map's own scale. Closed hollows deeper than 10 m (crater troughs, chasm
  floors, calderas) fill with lakes where it is wet. Where it is dry, a playa lies
  only in the lowest part.
- Planet lakes fill the zoomed relief up to their level, so shores follow its
  hills and valleys, including a crater's sharp trough. Their outlines also gain
  detail below the planet's mesh spacing, as coasts do. The world map draws the
  same outlines down to its own pixel size, so zooming in only adds smaller bays
  and points, though a shore can move a few kilometres. Rivers and closed hollows in a
  lake's basin drain into it, so no ring of playa or ponds lines its shore, and
  an open lake drains out over its basin's lowest pass
  ([ADR-0092](adr/0092-regional-lakes-fill-the-regional-relief.md)).
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
map-maker world view my-planet --theme atlas --projection globe --lon 40 --lat 20 --graticule --output globe.png
map-maker world view my-planet --theme topographic --lon 40 --lat 35 --zoom 3 --output close.png
map-maker world view my-planet --theme koppen --projection north-polar --limit 30 --output arctic.png
```

`--theme` is a build image's name without `.png`: `atlas`, `relief`, `koppen`,
`volcanoes`, `precipitation`, `temperature`, and the thematic maps `plates`
(tectonic plates, boundary types and motion), `seafloor` (ocean-crust age),
`basins` (drainage basins) and `geology` (geological provinces), and `topographic`
(hypsometric tints with contours every 500 m on a 4,096-5,760 px world, every
fifth bold, and isobaths). A polar view's `--lon` is the
meridian below (north) or above (south) the pole, and `--limit` is the latitude
at its edge (0 = the equator). A globe's `--zoom` enlarges it from 1 (the whole
globe) to 16. Views are deterministic and never overwrite a file
([ADR-0087](adr/0087-map-themes-and-projections.md),
[ADR-0101](adr/0101-interactive-globe-views.md)).

### Globe models

A globe model shows a planet map on a sphere in any 3D viewer, without Map
Maker. It is a glTF 2.0 binary file (`.glb`), the open standard for 3D scenes, so
Blender, game engines and browser glTF viewers can open it
([ADR-0102](adr/0102-globe-models-in-gltf.md)):

```powershell
map-maker world globe my-planet --theme atlas --output atlas.glb
```

- `--theme` is a build image's name, as for `world view`. The file must not exist.
- The model is a smooth desk globe one metre in radius, with north up and your
  map's central meridian facing the viewer. Its `extras` record the map, the
  planet's true radius and the build it came from.
- Between 60° N and 60° S the globe shows the map itself, unchanged, so it is as
  sharp as the build image (4,096 pixels wide by default). The app's **Save the
  shown map as a 3D globe…** embeds the map it has drawn, 2,048 pixels wide.
- Poleward of 60° it shows two polar images drawn from the map, as sharp as the
  rest. A map stretched over the whole sphere would show radial streaks around
  the poles in viewers such as three.js.
- Viewers that support glTF's unlit materials show the map's own shading; others
  light the globe as a matte ball.

## Run it from the command line

```powershell
map-maker world planet my-world.world.json --output my-planet
map-maker world planet my-world.world.json --geology my-world.geology.json --output my-planet-geo
map-maker world planet my-world.world.json --wonders my-world.wonders.json --random-wonders crater,tepui --output my-planet-wonders
```

The output folder must not exist. Progress is printed. A cancelled or failed run
leaves no `manifest.json`, so it never looks complete.

| Option | Default | Meaning |
|---|---:|---|
| `--nodes` | 200,000 | Sphere mesh size. On an Earth-size world, 200,000 nodes are about 50 km apart, 800,000 about 25 km and 3,200,000 about 12 km. Use 3,200,000 for a final map: coarser meshes cannot resolve Earth-scale ranges and valleys and are previews. |
| `--geology` | none | A geology recipe for this exact world. Without one, ranges and margins are placed procedurally. |
| `--calibrate` | 3 | How many times each geology region's uplift is corrected towards its target elevation. |
| `--climate-passes` | 1 | Climate → erosion couplings. 0 skips climate and biomes. |
| `--wonders` | none | A `.wonders.json` file of wonders placed by hand for this exact world, from the Wonders step. See the [wonder guide](wonders.md). |
| `--random-wonders` | none | Wonder kinds placed at random: a comma-separated list such as `titan,chasm`, or `all`. Placed wonders replace random ones of their kind. Also checkboxes under Wonders in the Generate step. |
| `--wonder-age` | 0 | Erode the wonders for this many million years (0 keeps them fresh); placed wonders may set their own. See the [wonder guide](wonders.md#age). Also **Age** under Wonders in the Generate step. |
| `--volcanic-islands` | off | Let young volcanoes at sea rise as islands: hotspot chains of shield islands and island arcs behind ocean trenches. **Adds land beyond your coastline.** Also a checkbox in the Generate step. |
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
map-maker world region my-planet --lon 61 --lat -39.6 --radius-km 500 --output my-region
```

Tiles are cached in `my-planet.tiles/` beside the build and reused by later regions.
They are made from the planet without wonders, which windows draw on top, so they
are cached under its identity and outlast changes to the wonders.
Go deeper with `--level`. Each level is enriched from the level above it, and
windows at the same level agree wherever they overlap
([ADR-0088](adr/0088-nested-regional-detail-levels.md)).

| Level | Detail | Window radius | Example |
|---|---|---|---|
| 1 region | 5 km | up to 5,000 km | a kingdom, a mountain range |
| 2 province | 1 km | up to 300 km | valleys, a crater, a coast |
| 3 local | 200 m | up to 60 km | a few valleys, a town's surroundings |

```powershell
map-maker world region my-planet --lon 61 --lat -39.6 --radius-km 120 --level 2 --output my-province
```

The first deep window takes a few minutes, because it also generates the coarser
tiles it needs. Later windows nearby reuse the cache.

### The refined coast as a source map

Zoomed maps draw your coast with more detail than you drew, and the planet
reshapes polar land. To see, edit or adopt that coast, export it as a new SVG:

```powershell
map-maker world refine-coast my-world.world.json --output my-world-refined.svg
```

- `--detail-km` sets the finest coast wavelength drawn (10 km by default; finer
  detail means more points, and the export refuses maps the importer cannot read).
- `--seed` is the planet's master seed (the default matches `world planet`),
  since the coast detail depends on it.
- Each shape keeps its continent and its mainland or island role, and continents
  that share a land border stay apart.

Import the SVG in the World tab: its **Coast detail already drawn** is filled in,
so zoomed maps add only finer detail instead of the same detail twice. Your
original world is unchanged until you save the import as a world
([ADR-0095](adr/0095-export-the-refined-coast-as-a-source-map.md)).

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
Atlas and relief images also anti-alias coasts: each coast pixel mixes land and sea
by the share of it on land, so coasts do not step along the pixel grid. Lake shores
are softened the same way. The land mask in `elevation.tif` and the other outputs
still follows pixel centres.

## Outputs

| File | Contents |
|---|---|
| `atlas.png` | Natural-colour shaded relief: vegetation from dryness and temperature, rock, snow, ice sheets, depth-tinted sea, lakes and rivers (needs climate). |
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
| `lakes.geojson` | Lake polygons with surface level, area and whether the lake is closed (endorheic). Outlines are the map's, refined below the mesh spacing. |
| `volcanoes.geojson` | Volcano points with kind (stratovolcano, shield, caldera, seamount), setting (arc, hotspot, rift, intraplate), activity, age, summit height and size. |
| `planet.npz` | The authoritative mesh: nodes, triangles, land, elevation, receivers, drainage area, forcing and climate fields, and ice thickness and mass balance. With wonders, also the surface, routing, lakes and volcanic relief of the planet without them, which regional tiles start from. |
| `input.world.json`, `input.geology.json`, `input.wonders.json` | Snapshots of the inputs used. |
| `manifest.json` | Settings, wonder settings, stage seeds, input hashes, runtime, calibration, metrics, output hashes and two identities: `build_sha256` for this planet and `base_sha256` for the planet without wonders ([schema](../schemas/world/planet-build-v2.schema.json)). |

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
   - **Ice sheets** grow where snowfall outweighs summer melt at the ice's own
     surface, which their height and brightness cool, and flow outward under
     their weight until melt at the margin balances them (ADR-0093). Dry polar
     plains can stay bare; wet uplands carry ice caps. Large sheets are drawn
     with their own smooth surface, firn above the snowline and bare blue ice
     below it; mountain ice is drawn as snow and glaciers on the relief.
5. **Lakes.**
   - **Young depressions** are added where geology or climate says they belong:
     rifts, sedimentary basins, interior sags, and recently glaciated lowlands;
     none under ice.
   - **Open lakes:** where inflow beats evaporation, the depression fills and
     overflows.
   - **Closed (endorheic) lakes:** otherwise the lake shrinks until evaporation
     balances inflow, and rivers end there. The previews show them in grey.

## Limits

- **Ice.** There are no ice shelves or sea ice: sheets end at the coast. On a
  broad plain a dry sheet's margin follows the regional climate and stays smooth
  at world scale. Mountain ice is drawn as snow and glaciers.
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
