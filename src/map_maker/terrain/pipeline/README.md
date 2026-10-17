# Terrain pipeline

This package orchestrates terrain generation using typed inputs and effective
configuration. Stochastic stages use named deterministic seeds; generation
returns numeric elevation, retained routing products and diagnostics.

The whole-planet path lives in `planet*.py`:
- `planet.py` orchestrates it;
- `planet_mesh.py` builds the mesh;
- `planet_tectonics.py` and `planet_forcing.py` set uplift and the ocean floor;
- `planet_evolution.py` erodes, with Numba kernels in `planet_kernels.py`;
- `planet_climate.py` and `planet_koppen.py` model climate;
- `planet_volcanism.py` and `planet_wonders.py` add young landforms; wonders are a
  separate pass on the base planet (`finish_planet`, ADR-0097), and
  `planet_suggestions.py` suggests sites for them (ADR-0099);
- `planet_regional.py` and `planet_tiles.py` provide regional detail;
- `sphere_views.py` holds the display kernels that draw globe, polar and flat
  views of world-frame images (ADR-0101).

See the [planet guide](../../../../docs/world-planet.md) and ADR-0085/0086. The
rest of this page describes the local composed generator.

The independent `world.py` source-inspection stage validates typed world ownership,
periodic geometry and overlaps, then measures sampled land on the declared sphere.
It generates no terrain or climate. File decoding, saving and source rendering
remain in adapters. See the [world guide](../../../../docs/terrain-worlds.md).

The implemented generator builds a coordinate-addressed relief field and a
separate low-frequency macro surface. Regional recipes and authored constraints,
including valley profiles prepared against a stable pre-incision reference,
shape that macro surface before routing. `landform_weights.py` owns dissolved
regional coverage and compact recipe mixing; `landforms.py` owns relief carriers.
Background fades occur at exposed coverage boundaries, not shared recipe edges.
Crest and water-density probes cover neighboring support, and native incision
limits use the same weights. MFD contributing area uses a
Priority-Flood-conditioned copy on a fixed canonical grid, then drives bounded,
stream-power-inspired automatic valleys. Incision is sampled in local metric
coordinates, so changing output resolution does not reroute major valleys.
Mountain carriers select seven-point interior probes and bounded searches near
observed zeros and same-sign local approaches to zero. A source-scale variation
screen admits same-sign endpoint pairs; regular probes are retained alongside
refined locations. The full authored macro at these positions supplies shared
D8 edge barriers to the
Priority-Flood, MFD and steepest-receiver stages. Priority-Flood can revise a
queued route through a later lower pass; both flow models reject crossings above
the source routing level. This can change the canonical network and its derived
cuts, while retaining the regional/global budget policy and authored authority.
These finite observations target one recipe, not every hidden terrain extremum;
see [ADR-0053](../../../../docs/adr/0053-observe-mountain-crests-in-drainage.md)
and [ADR-0054](../../../../docs/adr/0054-refine-observed-mountain-crests.md).

Receiver selection uses eight ordered array sweeps, preserving ties and tiny
positive drops. MFD retains its stable accumulation order while reusing metric
work; each mountain carrier folds into shared candidate masks and is released.
This bounds working grid storage as region count grows. The
[performance comparison](../../../../docs/research/2026-09-17-drainage-routing-cost.md)
records unchanged numeric output, measured cost and remaining scaling limits.

Before reconstruction, the canonical channel network carries downstream
minimum floor requirements upstream through every tributary. It recovers
unnecessary cuts without raising above the uncut source, then lowers receivers
within their existing ceilings. Feasible nodal intervals descend; impossible
ones retain explicit conflicts. Subsequent steepness correction remains bounded.
Routing, area, terminals and ceilings stay fixed; generated cuts can change.
The internal floor-correction array is the signed net incision change, negative
for cut recovery. See
[ADR-0056](../../../../docs/adr/0056-condition-network-floors-in-both-directions.md).

Incision and residual-detail suppression start with bounded bicubic Hermite
patches: shared nodal derivatives soften cell-edge creases. Selected diagonal
channel connections then receive compact, metric corrections toward their
endpoint shaping values, reducing scalloping without changing cell edges or
canonical nodes. These initial shaping fields stay in their cell corner ranges;
see [ADR-0051](../../../../docs/adr/0051-connect-diagonal-valley-shaping.md).
A source-aware floor stage then fits cuts inside selected cardinal/diagonal
corridors using actual macro heights and retained detail. Cuts may increase to
lower humps or decrease to avoid artificial pits; they remain nonnegative and
obey the existing bilinear nodal cut ceiling, while canonical nodes stay fixed.
This final cut is not restricted to the corner cut range. See
[ADR-0052](../../../../docs/adr/0052-fit-channel-cuts-to-sampled-terrain.md).
Before evaluation, eligible segments also observe 17 source/ceiling positions.
Downstream obstacle envelopes and upstream uncut-source envelopes adjust their
floor targets, reducing avoidable dips within the same limits. Sparse cubic
profiles retain fixed canonical pins and use the existing corridor blending;
missing-land/retained profiles are omitted completely. The shared PCHIP slope
kernel remains numerically unchanged. See
[ADR-0055](../../../../docs/adr/0055-prepare-attainable-channel-floor-profiles.md).
Exact basin masks still exclude both automatic effects inside retained footprints.
Active ceilings may retain slope breaks. This preserves routing nodes, not every
between-node height, and does not add terrain detail or certify flow. See
[ADR-0050](../../../../docs/adr/0050-reconstruct-valleys-with-bounded-cubics.md).
Final shaping applies authored brush, ridge, valley and height-point responses
and restores permitted high-frequency residual. Absolute constraints attenuate
that residual to satisfy absolute metre elevations. Relative constraints are deterministic
displacement fields over the surface entering their stage and preserve its
residual relief. The order is brush, ridge, valley, relative point, then exact
absolute point. Same-kind overlaps are order-independent. The coastline remains
a hard zero-elevation boundary.

Absolute height points attached to an absolute ridge or valley define a
shape-preserving longitudinal profile through their projected arc-length
positions. Baseline shoulder knots return isolated authored sections to the
structure target. The controlled centreline can rise or fall through peaks and
passes, while the existing cross-structure weight turns a lower crest anchor
into a saddle. Synthetic crest/floor variation is suppressed inside that
authored span so it cannot overshoot the supplied anchors.

A relative point near a relative structure is attached to the uniquely nearest
compatible line and uses the same longitudinal interpolation. Its signed value
modifies ridge relief as `base relief + displacement` or valley incision as
`base depth - displacement`. An attached point is consumed by the structure
profile and is not applied again as a circular point field. Ambiguous and
unattached relative points retain their free-standing displacement behavior.

Valley vertex order is semantic: the first vertex is upstream and the final
vertex is the outlet. Before chunked raster generation, the pipeline samples
the complete deterministic surface entering the valley stage at metric
positions spaced by at most 2 km, with every authored anchor inserted as an
exact knot. Relative incision profiles are subtracted from this reference. A
cumulative downstream minimum then removes only floor rises; it never raises
the preferred floor. Absolute valleys interpolate non-rising absolute-height
anchors toward the line's outlet-floor value and reject an uphill hard-anchor
sequence. The prepared profile is independent of output raster resolution and
is reused by every processing chunk.

Automatic drainage is broad terrain structure, not a hydrologic certification.
Its temporary filled surface is never substituted for the DEM, and it currently
routes the authored macro surface before final constraint restoration. Regional
relief limits automatic incision, including downstream corrections.
Authored lake/dry-basin footprints retain planned flow and exclude automatic
cuts. Sediment, lithology, climate and validated river-vector products are not
implemented.

MFD accumulation measures broad convergence, while a complementary D8 receiver
tree supplies one generated valley centreline. A logarithmic contributing-area
hierarchy blends narrow channel, near-shoulder, and broad trunk responses so
larger downstream valleys widen at a fixed incision relief. The same canonical
field suppresses fine residual noise most strongly on major floors and tapers
that suppression across shoulders. D8 here is a shaping tree retained in the
numeric routing archive; it is not a validated river product.

The selected D8 tree also receives deterministic Horton-Strahler order. Channel
heads have order one; equal highest-order tributaries increment the downstream
order, while a smaller tributary joining a larger reach does not. The order
raster is retained and exported as numeric topology, with zero outside the
channel network. It does not currently modify elevation or width: direct
order-based width and centreline-depth experiments regressed the synthetic
width fixture or the historical Tharkeniss drainage check (ADR-0023). Area and slope therefore remain the
active shaping controls until valley character and confinement are explicit.

The broad response also receives a deliberately small MFD convergence
correction. MFD area is normalized logarithmically above the channel threshold,
raised to a high-order trunk gate, combined with bounded local slope, and added
at 4% strength. This pulls a D8-quantized cross-section toward the continuous
flow minimum without replacing the connected D8 network or its floor
conditioning. The established residual-detail suppression field is unchanged.

Channel initiation combines source area and once-smoothed receiver slope. The
local area threshold follows a bounded `A*S^2` relation: it may fall to 35% of
the base threshold on steep terrain or rise to four times that threshold on
gentle terrain. Initiated cells are closed downstream over the D8 receiver tree,
so large low-gradient trunks remain connected even where they would not
independently satisfy the headwater test. This is a heterogeneous-terrain
heuristic, not a rainfall- or substrate-calibrated channel prediction.
A small logarithmic relief ramp rises from zero to 8% between the minimum
source area and the established area threshold. This makes selected heads
visible without allowing their cross-sections to rival downstream trunks.

The generated floor is checked again after its permitted residual detail is
restored. A stable upstream-to-downstream pass lowers a selected receiver only
when its reconstructed floor would otherwise climb, enforcing a 0.01 m minimum
drop. Correction is limited to 60% of reconstructed local elevation and an
additional 2% of the generation ceiling, subject to the regional relief budget.
Cap-limited edges remain explicit diagnostics. See the
[region guide](../../../../docs/terrain-regions.md) for the effective limits.
This is conservative generated-network conditioning, not final-DEM filling or
authored stream burning.

A second generated-only profile pass checks consecutive channel edges with
normalized steepness `S * A^0.45`. A downstream reach may be up to eight times
the upstream normalized steepness before it is treated as an extreme numerical
knickpoint. The solver lowers only the middle cell, reuses the existing incision
cap, and converges through at most 16 fixed upstream-to-downstream passes.
Ordinary slope variation remains, and bound-limited residuals are reported.
This heuristic does not apply to authored terrain and does not infer uplift,
lithology, waterfall status, erosion rate, or equilibrium.

After all generated and authored shaping, the pipeline evaluates the finished
Float32 field on the shared 257-longest-side routing/review grid. Strict downhill
D8 reports direct boundary connectivity and potential inland terminals.
Priority-Flood operates on a copy, and its conditioned receivers are reused for
channel comparison, fill extents and deterministic escape candidates. The typed
analysis retains labels, original-terrain spill points, terminals and raster
exterior/enclosed-water boundary context. It never repairs the authoritative DEM.
Candidate IDs and canonical numeric products are independent of delivered
resolution for otherwise identical inputs and algorithms. See the
[basin contract](../../../../docs/terrain-basins.md) for representative-route
selection and the limits of connected components versus authored lakes.

Free ridge and valley endpoints narrow gradually so authored structures do not
end as blunt walls. When an endpoint meets another structure of the same kind
and elevation mode, the junction keeps its full cross-section instead. A stable
metric tolerance of at most 2 km (and no more than 2% of the narrower structure
radius) recognizes drawing-level contact without making near but separate
features connect. Splitting one authored range or valley into compatible
segments therefore preserves the continuous line's junction cross-section;
minor bounded differences away from the join can remain because distance to a
segmented Shapely geometry is not numerically identical to distance to one
line.

Explicit absolute ridge profiles additionally preserve actual authored contacts
while smoothing the spans between them. `ridge_crests.py` validates compatible
contact heights and blends separate crest targets by distance so each centreline
retains its own height during the ridge stage. Valley cuts and final height points
keep later authority. Loops/self-crossings and shared spans are rejected for these
profiles; near misses are not snapped. See
[ADR-0083](../../../../docs/adr/0083-preserve-shared-ridge-crests.md).

Stages must not depend on implicit process state such as the current directory,
wall-clock time, ambient random generators, or undeclared environment settings.

Read-only review orchestration is owned by `diagnostics.py`, with basin geometry
in `basins.py`; flow and incision primitives remain in `hydrology.py`. Conflict evidence and the
near-zero flow correction are specified in
[ADR-0032](../../../../docs/adr/0032-classify-channel-conflicts.md).

Authored retention footprints and separate lake-water products live in
`water.py`. Canonical incision budgets and exact vector membership exclude
generated cutting inside lake/dry-basin areas. MFD absorption preserves captured
contributing area at each footprint node.

`water_sampling.py` plans bounded feature-guided Float32 profiles for shoreline
and outlet contact. `outlet_profiles.py` checks full external paths;
`wet_links.py` checks internal water connectivity; `dry_links.py` checks dry
candidate links and cumulative rises along chosen paths. `flat_routing.py`
routes exact flats using integer ranks without changing elevations.
`basin_flow.py` transfers eligible collected area and checks terminal conservation.
A failed/budget-limited review retains the affected area instead of accepting a
sampled prefix. No review repairs terrain or establishes a physical lake level.
See the [water contract](../../../../docs/terrain-water.md) for precise gates,
scope, algorithms and exported evidence.


Water review prepares normalized feature parts once and reuses exact coordinate
samples within each bounded profile/network call. The evaluator is pointwise;
all logical stations, endpoint checks, failed-link evidence and budget counts
survive reconstruction. Reuse does not persist between builds. See the
[measured comparison](../../../../docs/research/2026-09-13-water-sampling-reuse.md).
