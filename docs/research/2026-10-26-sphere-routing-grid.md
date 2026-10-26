# A routing grid on the sphere — 2026-10-26

Decision: [ADR-0112](../adr/0112-regional-waters-on-sphere-cells.md). Catalog entry:
D25 in the [decision catalog](decision-catalog.md).

## Question

Regional windows worked out their rivers, lakes and ponds on their own pixels, a
flat azimuthal equidistant grid centred on each window, so overlapping windows drew
different rivers. A draft routed on cells of fixed flat charts instead, which left
seams between charts. Can the waters be worked out on the sphere itself, with maps
flat only where they are drawn and exported, and on which representation?

## What a routing grid needs

- **Fixed to the planet:** every window that uses a cell size sees the same cells.
- **Local:** a window can list the cells within 1,500 km of its centre without
  touching the rest of a planet of 10⁸–10¹⁰ cells at regional sizes.
- **Isotropic:** steepest descent should follow the slope in every direction.
- **Even:** cell sizes near the window's pixels everywhere, with known areas.
- **Plain to build:** no dependency for a few hundred lines of geometry.

## Candidates

| Grid | Cell areas (max/min) | Shape | Local listing | Notes |
|---|---|---|---|---|
| Equiangular cubed sphere (Ronchi, Iacono and Paolucci 1996) | 1.41 (measured) | square at face centres, rhombic towards the 8 cube corners (120° there) | per face, a box of rows and columns | closed-form areas; edges subdivide alike on both faces |
| Gnomonic cubed sphere | 5.16 (measured) | square at face centres, stretched at corners | as above | too uneven |
| HEALPix (Górski et al. 2005) | 1 (equal area) | diamonds changing with latitude and near its base pixels' corners | per base pixel | healpy is GPL; nested numbering needs power-of-two sizes |
| Icosahedral hexagons, H3 | not measured | hexagons, 12 pentagons | per face | H3 does not nest; a new dependency |
| Jittered Fibonacci (the planet mesh) | near 1 | irregular | no cheap listing of a disc at 10⁹ points | |
| Fixed flat charts (the draft) | — | squares in each chart's plane | per chart | seams between charts (1–2 % of river pixels, the draft's measurement); cells up to 3 % small at 1,200 km |

On any of them, steepest descent between cell centres steps in a few fixed
directions; nodes jittered within their cells and triangulated do not. Once nodes
are jittered and each carries its cell's exact area into drainage, the grid's
area ratio matters little, so the cubed sphere's simple geometry won.

## Measurements

Scripts ran on a 6,000 km planet from the working tree of this change.

**Grid geometry.** At 256 cells per face edge, equiangular cell areas sum to the
sphere to 1e-12 and vary 1.41 times; the gnomonic cube's vary 5.16 times. In a
600 km disc over a cube corner, with nodes jittered by up to 0.4 of a cell along
both angles, the nearest neighbours lie 0.19 to (median) 0.66 cells apart, with 3
to 10 triangulated neighbours (median 6).

**The routing kernel.** On a raster's pixels, the graph kernel gives the same
receivers, filled surface and drainage as the pixel kernel exactly, ties
included; its ties break by each cell's world-fixed order.

**Cost of a window's disc** (750 km at 1.45 km cells, 922,000 nodes):

| Step | Time |
|---|---:|
| Listing and jittering the cells, with lattice neighbours (rejected) | 0.8 s |
| Delaunay in the stereographic plane, one Qhull (3.3–3.5 s) | 3.7–3.9 s |
| The same in parallel strips | 1.6 s |
| Routing on the cells | 0.25 s |
| Routing 1.17 million pixels, for comparison | 0.21 s |

Strips: every empty circle among nodes jittered within their own cells has a
radius under √2 cells, so strips cut with a margin of four cells each keep the
triangles whose circumcentres fall in their own core and whose radius is under
the margin. That is the whole set's triangulation: its neighbour lists equal one
Qhull's for every node within the routing reach; only 1,175 hull nodes in the
wall ring beyond it lose long, thin hull triangles.

**Directions.** Rivers traced 150 steps down a plane tilted 1 % (with 0.3 m of
roughness) from 200 starts; the error is between their overall heading and the
slope (median, 90th percentile in brackets, degrees):

| Slope azimuth | Pixels (D8) | Jittered, lattice neighbours | Jittered, triangulated |
|---|---:|---:|---:|
| 0° | 0.0 (0.0) | 1.1 (2.8) | 1.4 (3.1) |
| 10° | 10.0 (10.0) | 2.1 (3.8) | 2.3 (3.8) |
| 22.5° | 5.9 (7.9) | 6.3 (8.2) | 1.0 (2.4) |
| 30° | 15.0 (15.0) | 5.8 (7.6) | 1.1 (2.8) |
| 45° | 0.0 (0.0) | 0.4 (1.0) | 0.9 (2.5) |
| 60° | 15.0 (15.0) | 5.9 (7.1) | 0.9 (2.4) |
| 80° | 10.0 (10.0) | 1.2 (3.0) | 2.0 (3.6) |

Single steps on the triangulated cells keep a weak four-fold grain (0.26–0.39)
from the lattice under the jitter, but paths do not.

**Window independence on an analytic relief.** Two 750 km discs 300 km apart
held 678,526 cells in common, with identical neighbour lists (by cell) away from
their rims. On a relief of five noise octaves (400 to 5 km) on a regional tilt,
97.97 % of the cells inside both share their receiver; where the two filled
surfaces agree, 99.89 % do. The rest is the routing domain, not the grid: with
many closed hollows, a hollow fills to a level set by where its overflow can leave
the disc.

**Overlapping windows on the synthetic test planet.** Six pairs of level-1
windows (300 km radius, 160 pixels, rivers from 500 km²) at land centres at
least 700 km apart, each pair's centres 120 km apart east to west; both ways
round for each pair:

| Share of B's river pixels | Own pixels (HEAD) | Sphere cells |
|---|---:|---:|
| within 1.5 pixels of A's river ink | 99.5–100 % | 100 % in every pair |
| on one of A's river pixels | 96.2–100 % | 99.2–100 % |

The pairs route on the same cells and trace the same lines; what still differs is
each map's anti-aliasing of those lines on its own pixels.

**Aethelara** (`planet-3200k-v32` and `-v31`, tiles cached; the second composition
in one process; HEAD is `d0d9fdf`):

| Window | HEAD | Cells, one Qhull | Cells, Qhull in strips |
|---|---:|---:|---:|
| Region, 300 km at 96.0° W 19.6° N, 900 px | 5.2 s | 9.6 s | 7.2 s |
| Region, 300 km at 56.87° E 30.70° N, 900 px | 5.1 s | 10.5 s | |
| Province, 60 km there, 900 px | 5.8 s | 13.6 s | 10.2 s |
| Local, 20 km there, 600 px | 5.6 s | 8.3 s | |

The first opening in a process, which loads tiles and compiles kernels, took
14.4 s for HEAD's region at 96.0° W and 15.8 s on the cells (in strips). In the province map's 10.3 s, the
cells' disc took 2.1 s (Qhull in strips 1.3 s, against 3.7 s in one piece for a
million nodes), the relief on the cells about 1.6 s and its waters 2.1 s (four
routings 1.2 s); the window's own pixels about 2.2 s. Pixels are no longer
padded beyond the map.

Drainage is unchanged in kind. The region at 96.0° W took in the same 53
parent rivers (72,856 km²); its largest drainage is 166,368 km² on the cells and
166,191 km² on pixels, with 2,390 cells and 2,408 pixels over 25,000 km².
Courses and networks match at all three levels, and the province and local maps'
160,000 km² river keeps its course and its bends. Thin rivers on the region maps
draw softer: the total of river coverage is about the same (4,433 against 4,317
pixels' worth), but lines no longer run through pixel centres, so a river 0.85
pixel wide spreads over two pixels: 85 pixels reach full coverage against 443.

**In the app.** On a Standard Aethelara planet (200,000 nodes) made in the app,
the region (600 km), province (150 km) and local (30 km) maps at 56.87° E
30.70° N opened in 49, 62 and 71 s, tile generation included, drew connected
rivers, and showed draped over the globe at 16× and 62.5×.

## Disposition

Waters are worked out on jittered, triangulated cells of an equiangular cubed
sphere and drawn into each window's pixels (ADR-0112, `planet-blended-tiles-v19`).
The cost is about 2 s more for a cached region map and 4 s more for a province
map. Revisit composing relief once, on the cells, if a way to draw it on pixels
without faceted shading is found, and the drawing of thin rivers if their softer
anti-aliasing reads as too faint.
