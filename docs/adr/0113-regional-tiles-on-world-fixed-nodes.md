# ADR-0113: Build regional tiles on world-fixed nodes

- Status: accepted (experimental product path)
- Date: 2026-10-26
- Refines: [ADR-0086](0086-regional-planet-detail-from-blended-tiles.md) (each
  tile's mesh and seed) and [ADR-0088](0088-nested-regional-detail-levels.md) (tile
  seeds per level, level parents' meshes).
- Uses the cells of [ADR-0112](0112-regional-waters-on-sphere-cells.md).

## Context

A regional tile was eroded on a jittered hexagonal lattice in its own azimuthal
plane. Node jitter, rock texture and starting roughness were seeded per tile.
Overlapping tiles therefore held different nodes, and their blend averaged valleys
and ridges that lay apart: blend hollows, ridges up to 1 km apart, plains a few
metres apart. Level parents had lattices of their own too. Since ADR-0112, windows
route on one jittered node per cell of an equiangular cubed sphere.

## Decision

Tiles are built on the sphere's own nodes
([report](../research/2026-10-26-world-fixed-tile-nodes.md)).

1. **World-fixed nodes.** A tile takes the nodes of a `WorldGrid` within its
   support and halo, less 0.6 spacings, and keeps its ring of fixed nodes at the
   rim (`world_patch`). The cells hold as much ground as a lattice node of the
   level's spacing, √(√3/2) spacings on a side, so tiles keep the lattice's node
   count on average. The grid is seeded by `planet.tile-nodes`.
2. **Anywhere in the cell.** A tile node lies anywhere in its cell. Within 0.4 of a
   cell from its centre, as routing cells are, steepest descent on a tilted plane
   ran up to 5.0° off the slope, towards the grid's axes; anywhere in the cell
   1.4° (the lattice: 0.5°).
3. **Triangulated on the sphere.** Nodes are joined by Delaunay in their
   stereographic plane, so overlapping tiles hold the same triangles away from
   their rings.
4. **Level parents** take the coarser level's world-fixed nodes in the same way,
   so overlapping tiles get the same targets.
5. **Texture and roughness per level.** Rock texture is seeded per level
   (`planet.tile.relief`, `planet.tile.l<level>.relief`), its wavelength taken from
   the nominal spacing. Starting roughness is hashed from the cell and that seed.
   Tiles have no seeds of their own.
6. The regional algorithm becomes `planet-blended-tiles-v20`.

## Alternatives considered

- **Nodes within 0.4 of a cell, as routing cells are:** the same agreement, but
  flow bent up to 5° towards the grid's axes.
- **Blending tiles node by node:** where tiles share triangles, the existing blend
  of each tile's linear interpolation already equals it up to the variation of
  the weights within a triangle.
- **A shared hexagonal lattice in fixed flat charts:** seams between charts, which
  ADR-0112 rejected for routing.
- **Exchanging values or corrections between neighbouring tiles** (domain
  decomposition): it would also align what remains, the uplift corrections, but it
  orders tile generation. Recorded as the next step.

## Consequences

| HEAD (v19) → v20 | Region (level 1) | Province (level 2) | Local (level 3) |
|---|---:|---:|---:|
| Overlapping tiles' spread, mean / median (m) | 47.6 / 19.3 → 7.8 / 0.5 | 168 / 103 → 125 / 34 | 2.4 / 0.03 → 2.9 / 0.002 |
| The same, 99th percentile (m) | 321 → 80 | 747 → 1,224 | 50 → 87 |
| Rivers of one tile within 1.5 spacings of the other's | 95 → 100 % | 71 → 87 % | 72 → 96 % |
| Blend hollows deeper than 10 m, sampled without the warp (km²) | 955 → 425 | 739 → 205 | |
| The same, through the window's relief warp (km²) | 3,334 → 2,376 | 539 → 1,248 | 0 → 1.6 |
| Final calibration error per tile, mean (RMS, m) | 62 → 67 | 113 → 120 | 44 → 38 |

Aethelara windows of 600, 150 and 30 km at 56.87° E 30.70° N on `planet-3200k-v31`.

- Overlapping tiles no longer differ by geometry, texture or roughness. On the
  synthetic test planet level-1 tiles differ by 6.3 m on average instead of
  43 m, level-2 tiles by 7.2 m instead of 33 m.
- On sediment-basin plains overlapping tiles agree to a millimetre at level 2
  (0.5 m before). Their big-river channels coincide where both weigh a quarter or
  more (0.54 km apart before).
- What remains is each tile's own uplift correction. Targets of overlapping tiles
  agree within 1.3 m on average, but corrections differ by 4–16 %, and level-2 mountain
  tiles never settle (ADR-0109's noise floor). There one pair of province tiles
  differs by up to 1.6 km (1.0 km before), which sets the province's tail.
- Hollows of the warped blend come mostly from resampling single tiles through the
  relief warp. Windows fill them as plains; in the province they grew where one
  tile dominates.
- The province's big-river course lies 1.0 km from the region's on average instead
  of 2.0 km; the local course 1.4 km instead of 1.2 km. The levels now part near
  the north-west exit instead of in the east.
- Node density follows the place on the cube: tiles hold 0.86–1.10 times the
  lattice's nodes (6 % more at Aethelara). Tile time is unchanged at levels 1
  and 2.
- Wonder aging keeps its own lattice (`regional_mesh`).
- Tiles, window relief and exported GeoTIFFs change at every level.
