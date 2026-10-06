# ADR-0085: Generate whole-planet relief by erosion on an irregular sphere mesh

- Status: accepted (experimental product path)
- Date: 2026-10-06
- Adds a world-level product beside local terrain builds. It does not change
  ADR-0024/0028 local Float32 DEM authority. It realises the world-first order
  in the [living plan](../strategy/README.md).

## Context

Local terrain composes noise and authored shapes, then carves rivers planned on a
fixed 257-node D8 grid. Repairs did not make river paths and ground agree
(ADR-0050–0056, T05–T13). The isolated Landlab reference showed that erosion
history helps, but on a raster it kept D8 bias and grid-spacing dependence
(LE2). Whole-world work was blocked on per-continent AEQD domains with no poles,
no seam and no ocean. Climate needs a whole-world relief.

## Decision

1. **Mesh.** Generate world relief on jittered Fibonacci nodes with a spherical
   Delaunay triangulation (the convex hull of unit vectors). Node positions come
   from the `planet.mesh` stage seed. There are no pole, seam or compass-direction
   special cases.
2. **Relief process.** Make relief with uplift and implicit stream-power erosion
   (Braun–Willett, n = 1, m = 0.45):
   - Priority-Flood fills depressions every step, as sediment-filled basins.
   - Each land node drains to its steepest strictly descending neighbour.
   - Water nodes are held at sea level and land stays at least 1 m above it, so the
     vector coastline is the erosion base level and cannot move.
3. **Process area.** Add a fixed physical process area (default 10,000 km²) to every
   node's drainage area. The smallest resolved river is then a physical choice, and
   relief statistics converge with mesh density.
4. **Geology recipes as calibrated forcing.** A geology recipe is soft intent:
   - **Settings** give rock erodibility.
   - **Landforms**, explicit or implied by the setting, give an elevation target
     with a declared statistic.
   - **Orogen age** lowers residual relief.
   - **Plateaus** receive a late uplift pulse.
   - **Calibration** rescales each region's uplift by target ÷ measured, a few
     times; the response is linear for n = 1.

   Without a recipe, a procedural forcing is used.
5. **Climate.** The provisional climate (`planet-climate-v0`) runs on the same mesh.
   It only weights erosion by relative runoff and labels provisional biomes.
6. **Surface authority.**
   - The authoritative planet relief is the node `elevation_m` in `planet.npz`, with
     triangle-linear interpolation between nodes. Every river follows a mesh edge to
     a strictly lower node, so this surface has no hidden rises along rivers.
   - The GeoTIFF and images are derived. They are aligned with the world SVG frame
     (columns linear in longitude, rows in latitude) on a custom-sphere geographic
     CRS. Land/sea in rasters comes from the vector coastline.
   - Ocean-floor values are display bathymetry until a separate decision couples
     the bathymetry product.
7. **Publication.** `dmtools world planet` publishes a new directory with the
   manifest written last ([schema](../../schemas/world/planet-build-v1.schema.json)).
8. **Numba.** Numba 0.68 becomes a runtime dependency for compiled graph kernels.
   Planet manifests record the Numba and llvmlite versions.

## Consequences

- A whole world, including poles, seam-crossing land and islands, generates in
  under a minute at 100k nodes and in minutes at 800k nodes.
- Rivers agree with relief by construction.
- Flow directions are unbiased (compass-sector share ≈ 0.25).
- Mean and percentile relief converge across a 4× change in node spacing.
- The output is experimental. It is not an accepted world parent, and it has no
  lakes, endorheic basins, monthly climate or energy balance.
- The local composed generator remains for local editing until M5 decides how
  local and regional generation inherit from the planet (ADR-0048 still governs
  zoom).
- A future native core ports these kernels, guided by the Python implementation
  and its tests.

## Alternatives considered

- **Latitude/longitude raster.** Rejected: pole singularity, seam and anisotropic cells.
- **Cubed sphere.** Workable, but it keeps grid-aligned directions.
- **Continue local repairs.** Rejected by the T-series evidence.
- **Landlab on a raster.** Rejected: grid sensitivity, a GPL dependency in its stack,
  and no sphere support.
- **Fastscapelib.** Not adopted: GPL, and no Python 3.14 Windows wheel.

Evidence:
[relief](../research/2026-10-06-whole-planet-erosion-relief.md),
[climate](../research/2026-10-06-planet-climate-v0.md).
