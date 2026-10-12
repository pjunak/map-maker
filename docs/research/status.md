# Current status

Updated 2026-10-11. This page says what works now. Order of work is owned by the
[living plan](../strategy/README.md), method conclusions by the
[decision catalog](decision-catalog.md), failed trials by the
[method register](terrain-method-decisions.md), and measurements by the dated
reports in the [research index](README.md).

Everything below is experimental unless marked otherwise. Generated terrain is
plausible and process-informed, not a validated physical model.

## Product paths

| Area | Works now | Limits | Owner |
|---|---|---|---|
| **World source** | Retained SVG, full-sphere frame, continent/island mapping, bounded preparation, World tab, portable saves, `dmtools world inspect`. | Partial-draft saves; other projections. | [World guide](../terrain-worlds.md) |
| **Geographic context** | Spherical coverage, water topology, shore distance, exposure, verified exports. M1 binds it to local rough relief. | Local AEQD binding only. | [Context guide](../world-context.md), ADR-0084 |
| **Geology and bathymetry** | Authored geology recipes, which the planet calibrates as uplift and erodibility. Ocean-depth hypotheses. | The planet ocean floor does not yet use the bathymetry product. | [Geology](../world-geology.md), [bathymetry](../world-bathymetry.md) |
| **Planet relief (M2)** | `dmtools world planet`. Builds up to 3.2M nodes (about 12 km), with uplift and stream-power erosion. Includes plates, collision belts that vary along strike, rifts, volcanism, sediment basins and flood basalts. Ocean floor from plate age with transform faults and trenches. Lakes, and rivers with discharge. | No moving continents (the coastline is authored); no below-sea-level land basins. | [Planet guide](../world-planet.md), ADR-0085 |
| **Climate (M3)** | Two seasons, winds, continentality, monsoons, orographic rain, runoff, biomes and Köppen classes, coupled to erosion. | Annual means only; no ocean model. | [Köppen report](2026-10-08-continentality-and-koppen.md) |
| **Volcanoes and wonders** | Arcs, hotspots, rifts, seamounts, calderas, and opt-in volcanic islands. Wonders: a titan shield, a shattered and a giant active volcano, impact craters, a great chasm system with parallel troughs and side canyons, great cliffs, tepuis, oases and a splitting river, either opt-in random (the same at every resolution) or placed by hand in the geology recipe. | Hand placement is in the geology editor's Landmarks tab. Crater and chasm floors stay above sea level. | [Volcanism report](2026-10-08-volcanism.md) |
| **Map views** | A theme registry with globe, polar and flat projections. Themes: atlas, relief, climate, topographic, parchment, plates, sea-floor age, basins and geology. `dmtools world view`; the app's map view shows any theme in any projection (ADR-0089). | Political and civilization views need authored overlays. | ADR-0087 |
| **Regional detail (M6)** | `dmtools world region --level 1-3` and app drill-down (world, region, province, local). Nested levels from fixed blended tiles that do not depend on the window: region (5 km), province (1 km) and local (200 m). Each level is enriched from the one above. Coasts refined below the drawing's precision at every level (ADR-0090). Sharp volcanoes, craters and chasms, lakes and playas. Atlas, relief, topographic and parchment images. | Display detail is world-anchored, and rivers are routed over a padded window, so overlapping maps agree apart from pixel alignment. Fine-level drainage is unvalidated against reference terrain. | ADR-0086, ADR-0088, ADR-0090, [planet guide](../world-planet.md) |
| **Desktop app** | World workspace with Context, Geology, Bathymetry and Planet pages, layers, hover, export, zoom and globe views. | A responsiveness and UX rework is in progress in a separate session. | [README](../../README.md), [planet guide](../world-planet.md) |
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
