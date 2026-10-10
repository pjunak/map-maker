# ADR-0087: Render map themes on the world frame and project them as views

- Status: accepted (experimental product path)
- Date: 2026-10-10

## Context

Planet builds produced a fixed set of flat world images: atlas, relief, climate
zones, volcanoes, rainfall and temperature. Users want more views of the same
world and expect to add more later, such as political and civilization maps:

- globe and polar views;
- topographic and fantasy-style maps;
- thematic data maps.

Each new view should not need its own projection code, and a view of a saved
build should not need the planet to be regenerated.

## Decision

1. **Themes.** A theme says what a map shows. Each theme is registered once in
   `adapters/map_views.py` with:
   - an id (its file stem in a build and its CLI name);
   - an app label;
   - a legend;
   - whether it needs climate.

   It is rendered once on the world frame (equirectangular) and saved in the
   build as `<id>.png`.
2. **Projections.** A projection says how the world is shown.
   `adapters/map_projection.py` resamples a world-frame theme image into:
   - a flat world;
   - an orthographic globe centred anywhere;
   - north or south polar azimuthal-equidistant views out to a chosen
     latitude.

   It can add a 30° graticule. Projections are pure functions of the image and
   the view, so any theme can be shown in any projection, deterministically.
3. **Products.**
   - `dmtools world view <build>` writes any saved theme in any projection. It
     first checks the build hash and the theme file.
   - The app's **Globe and polar views** window turns the globe by dragging and
     saves views.
   - The flat map keeps its pan, zoom and hover.

## Consequences

- **Adding a theme** means adding a registry entry and a renderer. Projections,
  the CLI, the build outputs and the app's layer list pick it up.
- **Projection quality.** Globe and polar views resample the world-frame raster.
  Their detail is bounded by the build width (a 5,760 px build is about 6.5 km
  per pixel on an Earth-sized world), and hillshade light comes from the flat
  map's north-west.
- **Local maps.** Regional windows keep their own local projection (ADR-0086).
  Themes that should also work there (topographic, fantasy) render from shared
  map fields rather than from the planet raster alone.
