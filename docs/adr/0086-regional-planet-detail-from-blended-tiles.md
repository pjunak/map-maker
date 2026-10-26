# ADR-0086: Generate regional planet detail from blended fixed tiles

- Status: accepted (experimental product path)
- Date: 2026-10-06
- Implements the first M6 slice of ADR-0048 (zoom-driven enrichment) on the planet
  parent of ADR-0085.
- Refined by [ADR-0108](0108-calibrate-regional-relief-against-the-parent-smoothed-alike.md):
  tiles are calibrated against the parent surface smoothed alike.
- Refined by [ADR-0109](0109-fit-regional-uplift-corrections-along-the-drainage.md):
  the uplift correction is fitted to the relief uplift builds along the drainage.
- Refined by [ADR-0112](0112-regional-waters-on-sphere-cells.md):
  windows work out rivers, lakes and ponds on the tiles' blend over cells fixed to
  the sphere.

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

## Revision (2026-10-19): hollows of the blend

Every tile fills its depressions as it erodes, so it drains fully; parent lakes
are its only sinks. A blend of tiles does not. Overlapping tiles drain the same
plain through valleys that lie apart, and their weighted mean half fills each
valley with the other tile's flank, so the blend's sill stands above both tiles'
plains. Windows had drawn such hollows deeper than 10 m as lakes or playas. In
the Aethelara region window at 56.87° E, 30.70° N (Standard 200,000-node planet,
600 km, `planet-blended-tiles-v16`):

| Hollow | Tiles (weight at the sill) | Their outlets | Each outlet in the other tile | Blended sill | Hollow, lake |
|---|---|---|---|---:|---|
| Basin plain, 59.4° E 29.1° N | 312 (0.36), 346 (0.64); plains at 746 and 776 m | gorges west through a range, 3–5 km apart, at 744 and 775–782 m | 815 and 797 m | 786 m | 28 m deep over 1,850 km²; lake 1,470 km² |
| Coastal plain, 56.9° E 34.2° N | 257 (0.52), 291 (0.48); plain at 12–13 m | channels to the sea 13 km apart, at 12 and 11 m | 36 and 45 m (a coastal ridge) | 23.5 m | 11 m deep over 8,400 km²; lake 2,240 km² |

Blend hollows deeper than 10 m covered 5,270 km² of that window, against 2,850 km²
on v15 tiles: ADR-0109 raised the ranges beside such outlets by up to 300 m, and
with them the flanks that fill the other tile's valley.

Windows now treat hollows of the tiles' blend as plains that sediment fills, as
tiles and the planet fill their own. Ponds are measured on the blend with its
hollows filled, with the sea, the window's rim and lakes as sinks, plus the
relief the window draws on top of the tiles: volcanoes, crater floors and
wonders. Only that relief holds ponds, lakes and playas: crater troughs, chasm
floors, calderas and valleys a volcano dams. Planet lakes still fill the relief
from their cores, and the drawn relief and river routing are unchanged; rivers
no longer end in blend hollows. Tiles are unchanged, windows change, and the
regional algorithm becomes `planet-blended-tiles-v17`.

| Aethelara windows (900 px), lakes drawn | v16 | v17 |
|---|---:|---:|
| Region, 600 km at 56.87° E 30.70° N | 3,732 km² (0.36 % of land) | 0 |
| Province, 150 km there | 151 km² (0.21 %) | 0 |
| Local, 30 km there | 0 | 0 |
| Region, 300 km (600 px) over a 48,854 km² planet lake at 144.4° E 15.5° N | 48,946 km² | 48,946 km² |

Not chosen:

- **A blend that follows the lower tile** (a weighted soft-min over a scale T):
  at T = 5–40 m it left 490–1,370 km² of hollows deeper than 10 m in that
  window, while land stood 8–24 m and its highest tenth 34–79 m below the blend,
  against the calibration of ADR-0109. Any continuous blend of valleys that lie
  apart can close a hollow.
- **Breaching the blend's sills in the drawn relief**: it would cut pixel-wide
  trenches through ranges and change exported elevation, for hollows 10–30 m deep
  on plains.
- **Tiles sharing one mesh per level**, so that channels traced along the same
  planet link coincide: it would align outlets at the source, but tiles also
  differ in seeds, roughness and corrections. It stays with domain decomposition
  below as a possible next step.

## Revision (2026-10-19): one river course through every level

On the Aethelara basin plain (56.87° E, 30.70° N, `planet-3200k-v31`) the region
and the planet run the 160,000 km² river north-west through the centre of a 20 km
window, while the province and local maps turned it north at a junction 13 km
east of the centre. Two faults combined.

- **Tiles cut a river in different places.** Finer tiles traced their channels
  along their level parent's own drainage, and each parent routes the coarser
  relief on a lattice of its own: on the held plain two overlapping province
  tiles cut the river 3.1 km apart on average and up to 10.6 km. Their blend
  broke the channel.
- **A tile dammed the plain.** A tile holds the planet's surface, sampled
  smoothly. Downstream the planet's river runs between two nodes at 682.9 and
  681.1 m through a gap between hills, and between them the smooth surface rises
  to 710–714 m. Region tiles, 1,260 km across, breach that sill (their blend
  crosses it at 678–680 m), but province tile 7577, 252 km across, found a lower
  way out over its own ring beside the river's entry, at 695.7 m. It filled
  2,400 km² of plain to that level, up to 14 m above the planet's.

Every level now carries the planet's rivers instead of re-deriving them:

- **Channels follow the planet's links where the coarser relief carries them.**
  A level parent samples the coarser level's blend through its relief warp
  (ADR-0106), and that level's tiles stood on a parent that sampled the level
  above through the coarser warp, down to level 1, which is enriched from the
  planet in place. Level parents carry the planet's links and that chain of warps
  (`ReliefWarp.planet_points`). A tile traces the links at its nodes carried into
  the planet's relief, so its channel lies in the coarser level's. Cut along the
  links at the nodes' own places, channels lay up to the warps' displacement
  beside the inherited ones, and the province window lost the river within 6 km
  (T21). The held plain is sampled at the same points, so its lows lie where the
  coarser level has them.
- **Traced along the line.** A link is traced a neighbour at a time, to whichever
  neighbour further along it lies nearest its line, from where it crosses into
  the region. Stepping to the neighbour nearest the receiver drifted off the line
  by about an eighth of the link's length: 1.4 km on a 12 km planet link, several
  local spacings, and differently on every lattice. Links from beyond the region
  had been traced along its ring.
- **Beds follow the planet's river.** A channel's bed falls along its link from
  the planet's height at one node to the next, less its bankfull depth, wherever
  the sampled surface stands higher. Every level cuts the same bed, so smooth
  sampling no longer raises sills across a river that the planet does not have.
- **Level parents let planet rivers in where the warps carry them**, with their
  entry walls there too. Routing level parents in the channels as well changed
  no course in the province or local window, so they route the coarser relief
  as before.

| Aethelara, 20 km windows (level 1: 30 km) | v17 | v18 |
|---|---:|---:|
| Province tiles 7577 and 7721, big channel apart, mean / max (km) | 3.1 / 10.6 | 0.5 / 2.1 |
| Province course from level 1's, mean / max (km) | 5.1 / 13.9 | 2.0 / 5.9 |
| Local course from level 1's, mean / max (km) | 4.5 / 14.3 | 1.2 / 4.1 |
| Where levels 1 / 2 / 3 leave the 20 km circle (km east, north) | (−17.9, 8.9) / (11.1, 16.6) / (10.8, 16.9) | (−16.3, 11.5) / (−16.6, 11.1) / (−16.5, 11.2) |
| Box plain against the smooth planet, mean, levels 1 / 2 / 3 (m) | +3.4 / +1.7 / +1.6 | +0.1 / +0.9 / +1.7 |
| Box plain against the linearly sampled planet, mean (m) | −0.6 / −2.3 / −2.3 | −3.9 / −3.0 / −2.3 |
| Overlapping tiles' spread on the plain, levels 2 / 3, mean (m) | 4.7 / 0.5 | 0.5 / 0.1 |

The box is the 36 km square of T21; its plain's medians lie within 0.4 m of the
smooth planet at every level. The region's plain fell 3.3 m on average in its
highest part (90th percentile 18.1 m above the smooth planet before, 12.5 m now),
while its median moved 0.2 m. On the synthetic test planet six pairs of overlapping level-1 windows
agree on 94.0 % of river pixels near their edges and 92.8 % inside (v17: 90.0 %
and 92.6 %). Every level cuts the planet's links of at least its process area;
the regional tile algorithm becomes `planet-blended-tiles-v18`.

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
