# ADR-0086: Generate regional planet detail from blended fixed tiles

- Status: accepted (experimental product path)
- Date: 2026-10-06
- Implements the first M6 slice of ADR-0048 (zoom-driven enrichment) on the planet
  parent of ADR-0085.

## Context

Users need finer detail than the planet mesh (about 25–50 km) when they zoom in.
A regional window regenerated from the parent with finer erosion looks right and
agrees with the parent at parent scale. Two overlapping windows, however,
disagreed by 238 m RMS: erosion is non-local, so a result depends on where its
window boundary pins it. ADR-0048 requires overlapping requests to agree.

## Decision

1. **Fixed tiles.** Tiles are centred on a fixed unjittered Fibonacci lattice,
   about 600 km apart by default.
2. **Generation.** Each tile is generated once over its blend support (0.8 × tile
   spacing) plus a 150 km halo:
   - fine jittered mesh in a local azimuthal plane;
   - exact vector land;
   - ring land fixed at the parent surface;
   - parent rivers entering as inflows;
   - parent forcing with finer rock texture;
   - a smaller process area (24 × spacing² by default);
   - per-node uplift correction (ratio, then secant), so the tile, smoothed over
     the parent spacing, matches the parent.

   Seeds are `planet.tile.<id>`, derived from the master seed.
3. **Blending.** A point's value blends its covering tiles with normalised
   Wendland C2 weights. Any request over a place sees the same values. Each river
   segment is drawn by the tile with the largest weight there.
4. **Tile cache.** Tiles are cached by parent identity, regional algorithm and
   settings:
   - `<planet>.tiles/<key>/` beside an exported build; the build itself stays
     immutable;
   - a per-user cache for planets generated in the app.
5. **Biomes.** Regional biomes are re-derived per pixel from parent climate,
   lapse-corrected to the fine relief.
6. **Outputs.** `dmtools world region` and the World-tab **Zoom detail** action
   publish a window. It contains:
   - a Float32 GeoTIFF in a local azimuthal-equidistant CRS on the world sphere;
   - relief and atlas previews;
   - a manifest written last
     ([schema](../../schemas/world/planet-region-v1.schema.json)).

## Consequences

- Detail is reproducible and independent of the requested window. Tiles are
  generated in parallel processes and reused across requests.
- In blend zones the surface is a weighted mean of eroded surfaces, not itself an
  eroded surface, and river lines may jog there. Exchanging boundary values
  between neighbouring tiles (domain decomposition) is the recorded next step.
- Regional lakes and a regional climate solve are not generated yet.
- The local composed terrain generator remains separate; M5 decides how it
  relates to planet and regional detail.

Evidence: [regional enrichment and tiles](../research/2026-10-06-regional-enrichment-tiles.md).
