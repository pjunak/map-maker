# Current status

Updated 2026-10-17. This page says what works now. Order of work is owned by the
[living plan](../strategy/README.md), method conclusions by the
[decision catalog](decision-catalog.md), failed trials by the
[method register](terrain-method-decisions.md), and measurements by the dated
reports in the [research index](README.md).

Everything below is experimental unless marked otherwise. Generated terrain is
plausible and process-informed, not a validated physical model.

## Product paths

| Area | Works now | Limits | Owner |
|---|---|---|---|
| **World source** | Retained SVG, full-sphere frame, continent/island mapping, bounded preparation, World tab, portable saves, `map-maker world inspect`. | Partial-draft saves; other projections. | [World guide](../terrain-worlds.md) |
| **Geographic context** | Spherical coverage, water topology, shore distance, exposure, verified exports. M1 binds it to local rough relief. | Local AEQD binding only. | [Context guide](../world-context.md), ADR-0084 |
| **Geology and bathymetry** | Authored geology recipes, which the planet calibrates as uplift and erodibility. Ocean-depth hypotheses. | The planet ocean floor does not yet use the bathymetry product. | [Geology](../world-geology.md), [bathymetry](../world-bathymetry.md) |
| **Planet relief (M2)** | `map-maker world planet`. Builds up to 3.2M nodes (about 12 km), with uplift and stream-power erosion. Includes plates, collision belts that vary along strike, rifts, volcanism, sediment basins and flood basalts. Ocean floor from plate age with transform faults and trenches. Lakes, and rivers with discharge. | No moving continents (the coastline is authored, with polar land worked in true distance, smoothed east-west so drawn shapes do not become radial fingers, and touched poles covered, ADR-0094, ADR-0100); no below-sea-level land basins. | [Planet guide](../world-planet.md), ADR-0085, ADR-0094, ADR-0100 |
| **Climate (M3)** | Two seasons, winds, continentality, monsoons, orographic rain, runoff, biomes and Köppen classes, coupled to erosion. Ice sheets grown from mass balance by shallow-ice flow, drawn with refined margins on the atlas and in regional windows (ADR-0093). | Annual means only; no ocean model. No ice shelves or sea ice; mountain ice is drawn as snow and glaciers. | [Köppen report](2026-10-08-continentality-and-koppen.md), [ice report](2026-10-13-ice-sheets.md) |
| **Volcanoes and wonders** | Arcs, hotspots, rifts, seamounts, calderas, and opt-in volcanic islands. Wonders: a titan shield, a shattered and a giant active volcano, impact craters, a great chasm system with parallel troughs and side canyons, great cliffs, tepuis, oases and a splitting river, each fresh or aged (ADR-0091), either opt-in random (the same at every resolution) or placed by hand in their own `.wonders.json` document, each with its own shape seed and the kind's settings it fixes (ADR-0098), on the planet's maps, or kept from suggested sites scored by stated hypotheses (ADR-0099). Wonders are a pass on the planet without them, so changing them reruns only that pass and keeps regional tiles (ADR-0097). | The map under placed wonders is the planet as last made. Suggestion scores are hypotheses and may order near-equal sites differently at another mesh resolution. The climate does not see them. Crater and chasm floors stay above sea level. | [Volcanism report](2026-10-08-volcanism.md) |
| **Map views** | A theme registry with globe, polar and flat projections. Themes: atlas, relief, climate, topographic, parchment, plates, sea-floor age, basins and geology. `map-maker world view` (with globe zoom); the app's map view shows any theme in any projection (ADR-0089). The globe fills the window, turns at about 55 frames a second with the grabbed ground under the cursor, zooms to 16x and outlines opened and picked regions (ADR-0101); zoomed in, it shows the opened regional maps over the planet map, the deepest on top (ADR-0103), and zooms on into them until their pixels fill the screen's (ADR-0104). `map-maker world globe` and the Explore step save a map as a glTF globe model (`.glb`) that other 3D tools can turn (ADR-0102). | Political and civilization views need authored overlays. Globe detail is bounded by the build width outside opened regions and by their own resolution inside them. | ADR-0087, ADR-0101, ADR-0102, ADR-0103, ADR-0104 |
| **Regional detail (M6)** | `map-maker world region --level 1-3` and app drill-down (world, region, province, local). Nested levels from fixed blended tiles that do not depend on the window: region (5 km), province (1 km) and local (200 m). Each level is enriched from the one above, seeded from smooth parent fields so parent triangles leave no facets. Coasts refined below the drawing's precision at every level, or only below the detail a refined map already carries (ADR-0090); `world refine-coast` exports that coast as a source map (ADR-0095). Sharp volcanoes, craters and chasms. Lakes fill the regional relief with refined outlines (ADR-0092); playas. Rivers entering a map carry the drainage of the level above, so big rivers continue through every level, and meander along their valley on gentle ground. Atlas, relief, topographic and parchment images; every level colours and shades its slopes scaled to level 1, so nested maps agree in tone (ADR-0105). | Display detail is world-anchored, and rivers are routed over a padded window, so overlapping maps agree apart from pixel alignment. Display carving drains filled hollows along their thalweg rather than in straight grid-direction lines ([report](2026-10-12-straight-display-lines.md)); D8 can still draw parallel channels on smooth steep slopes. Fine-level drainage is unvalidated against reference terrain. | ADR-0086, ADR-0088, ADR-0090, ADR-0092, ADR-0105, [planet guide](../world-planet.md) |
| **Desktop app** | World workspace in six guided steps (Source map, Planet, Geology, Generate, Wonders, Explore) with explained fields and defaults, geology and wonders edited in place and following world edits, wonders applied without eroding again, planet maps drawn when first shown, and secondary tools (context, ocean floor, local terrain); layers, hover, export, zoom and globe views (ADR-0096). | No side-by-side comparison of planets yet (M4). The Terrain workspace keeps its older layout pending M5. | [README](../../README.md), [planet guide](../world-planet.md) |
| **Local terrain path** | Composed generator and editor, saved-project builds (Float32 DEM, GeoTIFF, review archive), water review and sampling. M1 context-bound rough relief. | Planned channels can still rise internally. It awaits the M5 decision on what replaces it. | [Terrain builds](../terrain-builds.md), [water](../terrain-water.md) |

## Research references, not adopted

- **Landscape-evolution reference.** An isolated two-epoch Landlab/SciPy
  reference, kept in a separate environment because of GPL dependencies
  ([plan](../strategy/landscape-evolution.md), [report](2026-09-24-landscape-evolution-reference.md),
  [dependencies](../DEPENDENCIES.md)).
- **Noise and water-profile bounds.** Measured enclosures for the noise component
  and refinement trials. They are not runtime rules
  ([noise bounds](2026-09-13-noise-component-bounds.md),
  [adaptive refinement](2026-09-13-adaptive-water-profile-refinement.md)).
- **Groundwater and canyon processes.** A literature and API review only. No
  coupled model has been measured.
