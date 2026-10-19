# ADR-0086: Generate regional planet detail from blended fixed tiles

- Status: accepted (experimental product path)
- Date: 2026-10-06
- Implements the first M6 slice of ADR-0048 (zoom-driven enrichment) on the planet
  parent of ADR-0085.
- Refined by [ADR-0108](0108-calibrate-regional-relief-against-the-parent-smoothed-alike.md):
  tiles are calibrated against the parent surface smoothed alike.
- Refined by [ADR-0109](0109-fit-regional-uplift-corrections-along-the-drainage.md):
  the uplift correction is fitted to the relief uplift builds along the drainage.

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
6. **Outputs.** `map-maker world region` and the World-tab **Zoom detail** action
   publish a window. It contains:
   - a Float32 GeoTIFF in a local azimuthal-equidistant CRS on the world sphere;
   - relief and atlas previews;
   - a manifest written last
     ([schema](../../schemas/world/planet-region-v1.schema.json)).

## Revision (2026-10-13)

Tiles were seeded from parent fields interpolated linearly inside each parent
triangle: the starting surface, the calibration target, uplift, erodibility and
runoff. Erosion did not erase that start, so province and local maps showed the
parent's triangles as planar facets with straight creases along their edges.
These fields are now sampled with Clough-Tocher cubics in the tile's azimuthal
plane, which equal the parent at its nodes and have no creases (uplift is kept
non-negative, erodibility within the parent's range; masks stay linear). The
tile lattice's node jitter rises from 0.2 to 0.35 spacings, as on the planet
mesh, because steepest descent at 0.2 still followed the lattice's three axes.
The regional tile algorithm becomes `planet-blended-tiles-v8`, and the relief
algorithm `sphere-mesh-stream-power-v27`, since wonder aging uses the same
lattice ([regional facets report](../research/2026-10-13-regional-facets.md)).

## Revision (2026-10-18)

Inside a sediment basin a tile keeps its parent plain: where basin depth reaches
200 m, uplift stops and erodibility drops by 97 %. Basin depth was sampled
linearly in each planet triangle, so local maps showed plain meeting mountains
along a straight front with kinks at triangle edges; sampling it smoothly only
bent the kinks. Basin depth now stays on the planet mesh, like lakes (ADR-0092),
and every level samples it smoothly at points displaced by rotated noise octaves
from four planet spacings down to twice its own spacing. Fronts gain re-entrants
and spurs at every scale a level resolves, alike at every level, and a finer
level only adds smaller ones. Level parents (ADR-0088) take uplift, erodibility
and runoff from the planet smoothly, as level 1 does. The cubics are built at
unit scale on a plane measured in mesh spacings: SciPy estimates their gradients
to an absolute tolerance, so uplift in metres a year had kept almost no gradient
and was interpolated worse than linearly. The regional tile algorithm becomes
`planet-blended-tiles-v11`.

## Revision (2026-10-19)

Since the revision above, the cubics carry real gradients, and they overshot
where a field steps sharply. Across a mountain front on Aethelara, a plain at
160 m below a 1,124 m range within one 4.6 km parent spacing, a province tile's
calibration target fell to −75 m at its ring, and the ring was held at sea level
there. The tile drained a 160,000 km² river to that outlet, 100–170 m below its
neighbour over the same ground. In 5 % of that tile's nodes the target lay below
the lowest corner of their parent triangle, by up to 1,100 m. The levels below
inherited a 50 m barrier and 30 m pits on the river's course, and the local
window sent the river back out where it entered. Each smooth sample now stays
within the values at the corners of its triangle, as a linear sample does.
Clamping erodibility to the parent's range is no longer needed. The regional
tile algorithm becomes `planet-blended-tiles-v13`.

## Revision (2026-10-19): sediment-basin plains

The planet sinks its sediment basins and fills them from their spill level after
erosion, so a basin plain is a deposit, not an eroded surface. Tiles only stopped
uplift and cut erodibility by 97 % where basin depth reached 200 m. Big inherited
rivers still cut the plain down, each tile to whatever outlet its own ring
offered. Over a 36 km box of the basin plain on Aethelara (56.87° E, 30.70° N),
levels 1–3 lay 335, 407 and 433 m below the planet's plain on average, and
overlapping region tiles there differed by 200 m.

Tiles now keep the planet's plain at every level:

- **Floor.** Land in a basin never erodes below the planet's surface, less
  (1 − basin) × 200 m towards the margin, the ramp uplift and erodibility already
  follow. Every level holds the planet's plain, which level parents carry on the
  planet mesh, rather than the surface of the level above. The floor holds inside
  the implicit erosion sweep, so each node grades to its receiver's held height.
  Rivers cross the plain on it, and range fronts grade to it.
- **Breached sills.** Sampled between parent nodes, a parent surface has sills
  where a river runs between two nodes and a higher third corner weighs in:
  60–80 m at this plain's outlet. Held there, they dammed each tile's plain at
  its own sill, 49–59 m above the planet. The floor is therefore that surface
  with its sills breached, the dual of the planet's fill: the lowest pass out of
  each hollow is lowered to just below it, unless that would cut a fixed node,
  and then the hollow fills to that node.
- **Start.** Tiles start from their parent's surface, breached in the same way.
  Started behind a sill, ground first fills like a lake, and a plain eroding at
  3 % of the rate kept the fill. Basins start without the random roughness that
  breaks ties elsewhere, since each level stacked a few metres of it on the
  plain of the level above.
- **Channels.** Parent rivers keep their bankfull channels, 0.27 Q^0.39 m deep
  (Moody and Troutman 2002, Q from 0.3 m of runoff a year): 4.7 m for a
  160,000 km² river. A channel is cut along the parent's link, traced over the
  tile mesh a neighbour at a time so it has no gaps, and through the ring only
  where the river leaves. Because every level holds the planet's plain, a coarse
  level's channel, as wide as its cells, fills back up around the finer level's
  own. Along a parent river the basin margin's spurs stop at its banks, since a
  floodplain is a deposit too.
- **Level parents.** Their boundary lets no water out within the longest planet
  step of where a planet river flows in, and nearer there than to where any
  leaves, as window rims do. Planet rivers enter at their first node inside, up
  to a step in.

Held level, the planet's plains had told finer levels nothing about where a river
runs. Every level routed them in its own flood order, and the province window
lost the 160,000 km² river. The planet now grades its plains towards their
outlets (`sphere-mesh-stream-power-v31`), and with it the levels below carry that
river through. Rejected: filling the plain back up after erosion, which dammed
valleys just outside basins; a fill to each tile's own spill level, which its ring
would set differently in each tile; channels as deep as a narrow channel lowers a
coarse cell on average (0.2 m at level 1), lost among centimetre differences once
resampled; and channels along the planet's links at every level, with which
the province window lost the river again within 6 km of its entry
([T21](../research/terrain-method-decisions.md#t21---hold-regional-basin-plains-at-the-sampled-parent-surface-or-refill-them)).

| Box on the graded planet (plain mean 717.5 m) | level 1 | level 2 | level 3 |
|---|---:|---:|---:|
| Plain mean, v14 / v15 (m) | 383 / 717 | 311 / 715 | 285 / 715 |
| Overlapping tiles' spread on the plain, mean, v14 / v15 (m) | 200 / 4.4 | 32 / 4.2 | 10.5 / 0.6 |

Still open: levels 2 and 3 agree on the big river's course, but at a junction
13 km east of the window's centre they turn it north, where level 1 and the
planet run it north-west. The two province tiles' level parents route the river
north-west too, but on lattices of their own, along lines up to 8 km apart, so
their blend likely breaks the channel and the window's water takes the next way
out. The regional tile algorithm becomes `planet-blended-tiles-v15`.

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
