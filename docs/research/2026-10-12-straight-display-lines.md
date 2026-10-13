# Straight lines in regional hillshade — 2026-10-12

Catalog entries: D06 and D28 in the [decision catalog](decision-catalog.md).

## Problem

A level-1 window of Aethelara (800k-node build, centre 85.76°, 22.74°, radius
250 km, 900 px, 0.55 km per pixel) showed straight lines on the arid plain inside
a large impact crater, roughly pixels 250–480 × 260–470. They were vertical
lines tens of kilometres long and a diagonal of about 45°. Steeper runs alternate
45° and 90° steps and read as about 60° once blurred. All of them were sharp at
pixel scale. They stayed when wonder aging was removed, and also when all
wonders were removed.

## Isolating the layer

The same window was composed once from cached tiles, and only the display was
varied:

| Variant | Straight lines | Curved, lattice-aligned scarps |
|---|---|---|
| Blended tile surface alone (hillshade of `elevation_m`) | none (5 km triangle facets only) | none |
| Display relief (current) | yes | yes |
| Display relief without valley carving | none | yes |
| Display relief without ridged detail | yes | none |
| Neither | none | none |

The tile surface, tile blending and the jittered hexagonal patches are not the
cause. Hexagonal-lattice drainage would run at 0°, 60° and 120°, but the lines are
at 0°, 45° and 90°: pixel-grid (D8) directions. Two display defects overlapped.

## Cause 1: routing across filled depressions

Display carving (`carve_valleys`) and window rivers (`grid_flow`) route over a
Priority-Flood fill with a 1 mm gradient. Inside a depression every cell sits at
the spill height, so the flood visits it in rings from the spill point. Steepest
descent on that gradient then runs in straight 8-direction lines across the fill,
whatever the ground beneath. The implicit stream-power step lowers the spill
cell, and the lowering travels up those lines. It cuts straight trenches that
show wherever they dip below the real ground, which is mostly near the
depression's margins. In the crater window 39 % of the land lies in filled
depressions. The crater bowl is one of them, and the hollows of the detail noise
are many more.

**Rejected trial: no incision on fill.** Skipping fill cells removed the lines.
It also removed many mountain valley networks, which form where incision breaches
the detail noise's hollows.

**Chosen fix.** Within a depression the flood visits cells lowest ground first,
because the heap is keyed by water level and then ground height. It runs down the
hollow's thalweg and then spreads uphill, and fill cells drain to the cell they
were flooded from. Depressions still drain and are still carved, but along the
ground's own valleys. Ground without depressions routes exactly as before and
still matches the mesh kernels. The authoritative mesh pipeline is unchanged.

## Cause 2: steps in ridged display detail

`eroded_fbm` damps each finer octave by the gradient accumulated over the coarser
ones. With ridged blending that gradient included the derivative of |v|, which
flips sign wherever an octave crosses zero. Every finer octave therefore stepped
there. The steps were sharp scarps along the zero lines of 3D value noise, which
run in rounded rectangles aligned with the noise lattice. Near 86° E the lattice
axes project north–south and east–west. The fix damps by a continuous slope: the
plain gradient times √(1 − 2r + 5r²). That factor is the root-mean-square of the
ridged slope over the two sides of a crest, (1 − 3r) and (1 + r), so the mean
damping is as before. A factor of (1 + r) also removed the steps, but damped more
at intermediate weights and lost 1 % of the detail's spread. Ridged crests stay
sharp, and the output is continuous. With r = 0, which every colour noise uses,
nothing changes.

Neither fix touches the mesh pipeline or the tiles, so no algorithm identifier
changes (`planet-blended-tiles-v6` stays). Map images are derived display and
carry no identifier of their own.

## Measurements

Regression tests on synthetic inputs (old code / new code):

- **Straight drainage.** A 96 × 96 closed basin of rough ground with a 6 m per
  pixel cone and 25 m texture; 55 % of it fills. The share of channel cells whose
  next eight steps keep one grid direction fell from 0.62 to 0.07.
- **Continuity.** Along a 300 km arc, the largest step between samples was
  measured at two sample spacings, the second ten times finer. The ratio of the
  two was 0.99 before (steps of 0.04–0.14 in a [−1, 1] field) and 0.10 after, at
  ridged weights 0.15, 0.5 and 1.0.

A directional autocorrelation of curvature at a 12 px lag did not separate before
from after on the real window, because the lines cover too little of it. A
gradient-orientation histogram of the multi-directional hillshade is anisotropic
even for isotropic ground. Neither became a test.

Display relief time for the 900 px window is unchanged (0.9 s).

## Aethelara before and after

Same build (`planet-800k-final`, relief `sphere-mesh-stream-power-v24`) and the
same cached tiles (`planet-blended-tiles-v6`, unchanged), with aging removed:

- **Crater plain.** The 45° trench along the crater wall, the parallel vertical
  grooves and the curved scarps are gone. The plain shows only rolling texture.
- **Window as a whole.** Thin rectilinear hairlines across the plateau and the
  northern hills are gone.
- **Mountains to the south.** Branching valleys remain. Dark-green valley
  tongues that had straight branches are shorter and rounder.
- **Without wonders.** The parallel grooves beside the central basin and the
  curved scarps are gone as well.

**World atlas.** The 800k planet was built twice from the same source, with and
without the fix (`planet-800k-head`, `planet-800k-lines`). All 87 arrays in
`planet.npz` are identical, as are the elevation GeoTIFF, lakes and rivers, so the
authoritative relief is unchanged. Only display images differ. The atlas changes
by 0.13 grey levels on average, 1.3 % of its pixels change by more than 2 levels,
and local contrast around the crater is unchanged (12.60 against 12.56).

The images are local artifacts, not tracked in the repository
(`artifacts/aethelara/lines/`).

## Limits and follow-ups

- D8 still draws parallel channels on smooth, steep slopes where the detail is
  too weak to bend them (the [natural-map report](2026-10-07-natural-map-rendering.md)
  lists this). Multiple-flow routing for incision remains the candidate.
- The crater's salt pan has straight edges 25–50 km long. Its shore is most likely
  where the parent's lake cover, interpolated linearly on 24 km triangles, passes
  0.15, which is a straight line within each triangle. This is a separate defect,
  fixed by ADR-0092 ([lake shores](2026-10-12-regional-lake-shores.md)).
- The mesh kernels still route filled flats along their 1 mm gradient. Their
  tiles showed no such lines here.

## Faceted regional relief — 2026-10-14

Province and local windows of a 3.2 million-node Aethelara build (refined map,
around 70 °E, 24 °N) showed straight-edged planar facets and seams in the tiles'
own relief, not only in display detail.

- **Cause: parent triangles.** Overlaid on the shaded tile relief, the facets'
  edges are the planet mesh's triangle edges. Tiles were seeded from parent
  fields interpolated linearly inside each parent triangle: the starting
  surface, the calibration target, uplift, erodibility and runoff. Erosion
  did not erase that start, so each parent triangle stayed a tilted plane with
  creases along its edges, and finer levels inherited them.
- **Not the cause alone: lattice grain.** Tiles erode on a jittered hexagonal
  lattice. On a gently tilted plane with small roughness, steepest-descent flow
  azimuths had a six-fold grain (|mean exp(6iθ)|) of 0.20 at the old jitter of
  0.2 spacings, pulling mean flow up to 5.8° towards the lattice axes. Jitter
  0.35 (as on the planet mesh) gives 0.02, as do a jittered or plain sunflower
  spiral (0.02, 0.01) and Poisson-disk points (0.03). Raising the jitter alone
  changed the fine texture but kept the facets.
- **Fix.** Seed fields are sampled with Clough-Tocher cubics in the tile's
  azimuthal plane: equal to the parent at its nodes, without creases. Uplift is
  kept non-negative and erodibility within the parent's range; basin depth stays
  linear. The plane and its triangulation are built once per tile: 0.03 s, then
  0.01–0.2 s per field, against 2 s per field for the linear sampler. Jitter is
  0.35. Tile algorithm `planet-blended-tiles-v8`; relief algorithm
  `sphere-mesh-stream-power-v27` (wonder aging uses the same lattice).
- **Result.** The creased facets are gone from province and local relief; a
  province escarpment is now cut back by valleys. In the natural-colour atlas
  the change is subtle, because display detail and uniform desert colour
  dominate at these zooms. A curvature measure along parent edges did not
  separate the cases (1.15 to 1.08 at region level, about 1 at province), since
  gully texture dominates curvature there.
- **Real straight features stay.** A straight east-west escarpment over 100 km
  long crossing the province window is in the planet's own relief (a 500 m drop
  within 30 km at every profile across it), and regional erosion sharpens it.

One local window failed once with `[Errno 22] Invalid argument` while starting
tile worker processes and succeeded when repeated.

