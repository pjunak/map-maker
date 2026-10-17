# Terrain adapters

This package owns concrete file and rendering boundaries:

- load, dissolve, validate and fingerprint local-terrain SVG land geometry;
- independently retain world SVG shapes/hierarchy and immutable source text,
  atomically save portable world projects and render bounded source previews;
- strictly read and atomically write the current JSON terrain project;
- render relief, water and drainage review images and save PNG previews;
- write Float32 local-metric GeoTIFF, NPY terrain/mask/coordinate arrays and
  NPZ routing/water/basin-flow products; and
- serialize diagnostics and publish a hashed completion manifest after the
  build application verifies completion inputs.

Planet and map adapters:
- `planet_build.py` and `planet_load.py` write and verify planet builds;
- `planet_render.py` and `planet_natural.py` render world-frame rasters and the
  atlas;
- `map_views.py` is the theme registry, and `planet_maps.py` draws a planet's
  themes, each the first time it is asked for;
- `map_projection.py` draws globe, polar and flat views with the kernels in
  `pipeline/sphere_views.py`, and maps between view pixels and longitude and
  latitude (ADR-0101);
- `globe_model.py` writes a map as a glTF globe model (ADR-0102);
- `map_topographic.py`, `map_parchment.py` and `map_thematic.py` render themes;
- `planet_region.py` composes and exports regional windows.

See the [planet guide](../../../../docs/world-planet.md) and ADR-0087.

Read the [build contract](../../../../docs/terrain-builds.md) for the product
inventory and publication rules, and the [world guide](../../../../docs/terrain-worlds.md)
for retained-source formats. Vector products other than river and lake GeoJSON, and
external scientific-engine exchange, remain future adapters.

An adapter translates external behavior into domain contracts and reports its
effective tool/library versions where required by the build manifest.
