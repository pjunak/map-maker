# Parent-conditioned regional enrichment and blended tiles — 2026-10-06

Status: **experimental**, first built as a research harness for M6 and ADR-0048.

> Later the same day this was promoted to `dmtools world region` and the World-tab
> zoom ([ADR-0086](../adr/0086-regional-planet-detail-from-blended-tiles.md)). The
> harness modules were removed; module paths below are historical.
> - **Product additions:**
>   - a verified build reader;
>   - a tile cache beside builds or per user;
>   - the exact tile selection: every centre within the window radius plus the support;
>   - blending only inside the window circle;
>   - biomes re-derived per pixel with the lapse rate.
> - **Live timing:** a 1,200 km zoom over the fractal world's young belt took 84 s
>   and used 25 tiles at 5 km, generated in parallel on first use. Repeat zooms
>   reuse the cached tiles.

## Question

Can a region of an experimental planet be regenerated with much finer, physically
eroded detail that:
- keeps the parent's coast, relief and drainage at parent scale;
- gives the same values no matter which window is requested?

## Regional enrichment

1. **Mesh.** A jittered triangular lattice (0.2 spacing jitter) inside a circle in
   a local azimuthal-equidistant plane, plus an even outer ring. It is triangulated
   with planar Delaunay and mapped to the sphere. Planet kernels run on it
   unchanged, using the new `mesh_from_triangles`.
2. **Land** is the exact vector coastline at the finer spacing.
3. **Boundary.** Ring land nodes are fixed at the parent's surface, interpolated
   triangle-linearly. Kernels and `evolve` now accept fixed nodes at any base
   level (`fixed_level`). Sea is held at 0. Parent rivers crossing into the region
   enter as area sources (`inflow_m2`) at the nearest interior node.
4. **Forcing.**
   - Parent steady and pulse uplift, erodibility and runoff weight are interpolated.
   - Erodibility gets extra fine texture at about 40 km.
   - The process area shrinks from 10,000 km² (planet) to 600 km² (5 km spacing).
5. **Consistency with the parent.** A per-node uplift correction makes the regional
   relief, smoothed over the parent spacing, match the parent surface.
   - Iteration 1 uses the ratio target ÷ smoothed.
   - Later iterations use a per-node secant on the correction → smoothed-relief
     response, which accounts for fixed boundary base levels.
   - Steps are clamped to ×1/3–×3 and smoothed over half the parent spacing.

**Fractal world, young belt at 61°E 40°S** (200k-node parent, 700 km radius, 5 km
spacing, 71k nodes):

| Iteration | RMS vs parent (smoothed) | Mean bias | Max |
|---:|---:|---:|---:|
| 0 | 1,074 m | +768 m | 8,592 m |
| 1 | 231 m | +47 m | 5,945 m |
| 2 | 214 m | −83 m | 4,649 m |
| 3 | 119 m | +7 m | 5,263 m |

- About 17 s for four evolutions.
- Zero non-descending receivers; compass-sector share 0.252.
- **Visually:** the same range, main valleys and lowland basin as the parent, with
  dendritic erosional detail.

**Hard case: an inland plateau 2,500 km from the coast** (coarse 160 km parent,
20 km region). The first ratio-only update closed only about 25 % of the gap per
iteration, because relief sits on fixed boundary levels: −471 → −275 m bias after
2 iterations, still −66 m after 5. The secant update reaches +4 m after 3
iterations. The ratio-only update is retained here as a failed control.

## Overlapping windows disagree

Two independently generated 700 km windows 400 km apart (26,823 shared land
nodes) differ by **238 m RMS** (p95 559 m) against 1,327 m local relief standard
deviation. Erosion is non-local: a node depends on its whole catchment and on
where the window boundary pins it. Windows therefore cannot satisfy ADR-0048's
agreement requirement, and this is recorded as a rejected design.

## Blended fixed tiles

- **Tile layout.** The planet is covered by fixed tiles with centres on an
  unjittered Fibonacci lattice, about 600 km apart.
- **Generation.** Each tile is enriched once over its support radius plus a 150 km
  halo. Its seed is `planet.tile.<id>`, derived from the master seed.
- **Blending.** A point's value is a Wendland-C2 weighted blend of the covering
  tiles, normalised to one.
- **Window independence.** A tile depends only on the parent, its id and the
  settings, so every window over a place gets the same value. Regenerating a tile
  in a fresh process differs by exactly 0 m.

| Support / spacing | Tiles for two windows | Mean tile nodes | Time (8 processes) | Neighbour-tile RMS median / max |
|---:|---:|---:|---:|---:|
| 1.15 | 16 | 102,710 | 66 s | 58 m / 1,083 m |
| 0.8 (current) | 15 | 57,826 | 34 s | 73 m / 602 m |

Both show no visible seams. The wider support softens detail, because more
points average two or three different valley networks; 0.8 keeps detail crisp.

## Limits and next steps

- In blend zones the surface is a weighted mean of eroded surfaces, not itself an
  eroded surface. Rivers may not descend exactly there, and drawn rivers must come
  from one tile. Domain-decomposition iterations that exchange boundary values
  between neighbouring tiles could remove this; they are not tried yet.
- Lakes and climate are not yet regenerated per region. Parent climate is
  interpolated for erosion weighting only.
- **Inflows.** Inflow attribution uses the nearest interior node to the parent
  receiver, which is coarse.
- **Process area.** Process area per spacing is a calibration choice (600 km² at
  5 km).
- **Promotion** needs a planet build reader, a tile cache next to a planet build,
  window exports and a viewer action.
