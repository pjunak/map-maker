# ADR-0112: Work out regional waters on cells fixed to the sphere

- Status: accepted (experimental product path)
- Date: 2026-10-26
- Refines: [ADR-0086](0086-regional-planet-detail-from-blended-tiles.md) (how windows
  draw rivers, lakes and ponds) and [ADR-0088](0088-nested-regional-detail-levels.md)
  (the window dependence that remained).
- Its cells also give regional tiles their nodes
  ([ADR-0113](0113-regional-tiles-on-world-fixed-nodes.md)).

## Context

A regional window composed its relief on pixels of its own, an azimuthal
equidistant grid centred on the window, and worked out its rivers, lakes and ponds
on those pixels over 1.25 times its radius (ADR-0088). Tiles and display detail do
not depend on the window, yet overlapping windows drew different rivers. On the
synthetic test planet (level 1, six pairs of 300 km windows at 160 pixels, 120 km
apart):

| Pair differs in | B's river pixels within 1.5 px of A's river ink |
|---|---:|
| Routing extent only (1.6 instead of 1.25 radii, same pixels) | 100 % |
| Pixel grid only (moved 0.37 pixel, same extent) | 98.6–99.1 % |
| Pixel count only (200 instead of 160) | 99.1 % |
| Both (centres 120 km apart) | 99.8 % |

Where routing starts did not matter; where the cells lie did. Steepest descent
across gentle ground and filled hollows follows the cells, and on a pixel grid it
also steps in only eight directions: a river on a plane tilted 30° off a grid axis
runs 15° off its slope.

Meanders depended on the window too. Each river's bends were drawn from a random
generator seeded by the pixel index of its head and phased from that head, which
for a river entering a window is where it crosses the routing circle.

A first draft of this decision routed on square cells in the plane of the nearest
of fixed charts about 1,500 km apart. Windows on one chart then agreed, but windows
on neighbouring charts still differed by 1–2 % of their river pixels; cells far from
a chart's centre were up to 3 % smaller on the ground than in its plane; lakes and
ponds were still worked out again on each window's pixels, so a river could end a
pixel away from a lake's drawn shore; and drawing windows as cut-outs of their
chart, to share lakes too, would have turned maps up to 17° off north at 70°
latitude.

## Decision

Waters are worked out on the sphere and only drawn flat
([report](../research/2026-10-26-sphere-routing-grid.md)).

1. **Cells of an equiangular cubed sphere** (`pipeline/planet_grid.py`,
   `WorldGrid`). Each face's two angles step evenly in N cells along each edge, so
   cells are near-square everywhere, their areas vary by 1.41 at most, and the
   sphere has no poles, seams between maps or projection to choose. N comes from
   a fixed ladder of sizes (2^(k/4) m) nearest a window's pixels, so the pixels are
   within 9 % of the cells.
2. **One jittered node per cell.** Each node lies within 0.4 of its cell's angular
   width of the cell's centre along both angles, by a hash of the cell and the
   planet seed, so nodes stay at least 0.15 cell apart and every map that uses a
   size sees the same nodes.
3. **Triangulated on the sphere.** A window takes the nodes within its routing
   reach and a ring of two cells beyond it, and joins them by Delaunay in their
   stereographic plane, which maps circles to circles and so gives the spherical
   Delaunay triangulation, in parallel strips. Every triangle away from the ring
   is the one any other window holding its nodes finds. Steepest descent then has no preferred
   directions. Ties in routing break by the cells' world-fixed order.
4. **All waters on those cells.** Relief (the tiles' blend and what the window
   draws on it), coast, inflowing parent rivers, lakes, ponds, playas and the
   climate that decides which ponds overflow are worked out on the cells
   (`window_hydrology`), by the rules windows used on pixels: rim walls, entry
   walls, filled blend hollows, lakes filling the relief from the parent's lake
   cores, overflowing hollows crossed as plains.
5. **Drawn flat.** Rivers come back as lines in the window's pixel units and are
   drawn there at widths set by its pixel size. A pixel is a lake, salt lake or
   playa where the nearest such cell lies within a cell spacing and the pixel's
   own ground is no higher than that cell's water level (or playa bed), so shores
   follow the pixel relief. Relief, colour, ice, display carving and exports stay
   on the window's own pixels, which are no longer padded beyond the map.
6. **Main stems.** A network splits into rivers that continue through each
   junction along their largest donor (ties to the higher cell index), so the
   split depends on discharge, not on which heads a window holds or the order
   they are drawn in.
7. **Bends fixed to the place.** Every cell carries a mark hashed from the cell
   and the planet seed. Along a river, a node is a landmark when its mark is the
   least within two meander wavelengths up or down the river; each landmark fixes
   the bend phase to a value from its mark, and between two landmarks the river
   runs the whole number of extra bends nearest its own wavelength, scaled to fit.
   Each bend's swing is drawn from the mark of the landmark before it and its
   count of half-turns from that landmark, times a reach factor drawn per eight
   bends. The meander wavelength is averaged over the river's channel wavelength
   rather than the largest wavelength of the drawn river. All of this depends only
   on the river within a few wavelengths. The random bend-to-bend stretch of the
   wavelength is dropped; the fit between landmarks varies it instead.
8. The regional algorithm becomes `planet-blended-tiles-v19`. Tiles are unchanged.

## Alternatives considered

- **Charts** (the first draft above), and **windows as cut-outs of the chart
  grid**: seams between charts, distorted cells, and maps turned off north.
- **HEALPix** (Górski et al. 2005): equal-area, but its cells are diamonds whose
  shape changes with latitude and towards its twelve base pixels' corners, its
  open implementation (healpy) is GPL, and once nodes are jittered and
  triangulated the cubed sphere's 1.41 area ratio does not matter: each cell
  carries its exact area into drainage.
- **Icosahedral hexagonal grids, H3**: more uniform hexagons, but twelve
  pentagons, harder indexing, and for H3 a dependency with a hierarchy that does
  not nest; triangulated jittered nodes are as isotropic.
- **Unjittered cells with eight neighbours** (pixel-like D8 on the sphere): the same
  15° bias as pixels.
- **Jittered nodes joined to their eight lattice neighbours**, without
  triangulating: built in 0.8 s instead of 3.8 s for a million nodes, but rivers
  on a tilted plane still ran up to 6° off the slope (under 2.3° triangulated).
- **Fixed routing domains per tile with seams between them.** Routing extent was
  shown not to matter, and seams break rivers where neighbours disagree, as the
  first form of ADR-0086 did.
- **Composing relief once, on the cells, and resampling it to pixels.** Linear
  interpolation between jittered nodes about a pixel apart would shade as facets;
  sharp features (volcanoes, crater rims, coasts) are cheap to draw at pixels.
- **Bends from smooth world noise.** Swings and stretch taken from value noise at
  each point of the valley line varied within a bend and stayed high across
  neighbouring bends, against the slowly varying swing the closed-form curve
  assumes: on a test valley at gentle-ground wavelengths the channel touched
  itself in 18 of 20 draws, against 0 of 20 before. Swings drawn per bend left
  7 of 40 touching while the noise stretch remained, and none without it.

## Consequences

- Windows that share a cell size work out the same drainage on the same cells
  wherever they overlap, anywhere on the planet; their river lines differ only by
  the few metres each window's map plane bends them by.
- Bends belong to the place: a river drawn from a point 600 nodes down its course
  winds, eight wavelengths on, within 0.07 pixel of the whole river's bends.
- Each window composes its relief on its pixels and on its cells, and
  triangulates its cells: a million in about 1.6 s, in parallel strips. The
  pixels are no longer padded. A cached region map on Aethelara took 7.2 s
  instead of 5.2 s, a province map 10.2 s instead of 5.8 s.
- Thin rivers draw softer: lines no longer run through pixel centres, so a river
  under a pixel wide spreads over two pixels at the same total weight.
- Lake and pond shores are drawn from cells about a pixel apart: a shore follows
  the pixel relief, but where the cells see no water a pixel can be dry ground a
  little below a lake's level.
