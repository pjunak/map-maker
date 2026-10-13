# Generate geographic world context

The World workspace now implements the first WC1 stage: fractional land coverage,
connected water regions, separate water pieces and their shared intervals, shoreline distance,
eight directional water-exposure fields and resolution support
on a custom spherical planet. Completed context bundles can be reopened for inspection.
It consumes the validated source and its reported preparation adjustments.
Separate [geology inputs](world-geology.md) and [ocean-depth hypotheses](world-bathymetry.md)
are implemented. M1 can bind this result to experimental rough terrain. Climate,
runoff, aging and world-linked regional generation remain later stages. A context
bundle is geographic input, not a generated terrain parent.

## In the editor

1. Open a current `.dmworld.json`, or import and assign a world using the
   [world-source guide](terrain-worlds.md). Confirm its established frame and radius.
2. Open **Geographic context** under **More tools**. Choose the grid: **Coarse**,
   **Standard** or **Fine** have 90, 180 or 360 latitude rows. Longitude uses twice
   as many columns: 2°, 1° or 0.5° angular cells respectively. The planet does not
   need context; the Geology step offers it as a background, and the Ocean floor
   and Local terrain tools use it.
3. Click **Generate context**. The worker validates the current inputs and shows
   row progress in the status bar. **Cancel** stops at a checkpoint. Individual SVG/GEOS
   operations cannot be interrupted mid-call; cancellation is cooperative.
4. Choose **Context** above the map, then pick **Source**, **Land coverage**, **Connected water**,
   **Resolution support**, **Water openings**, **Shore distance**, **Water exposure**
   **Exposure support**, and **Water connectivity**. The compass selector changes
   the initial look direction
   for exposure layers without regeneration or input edits. Zoom and pan inspect the same
   cells. Source outlines remain visible over exposure/distance and connectivity layers;
   those outlines do not increase numeric resolution. Hover shows
   land fraction, the dominant water ID and whether local support is mixed. In
   Water openings, hover reports the longest north/east/south/west openings in km.
5. **Export context…** creates a new result directory. It includes the complete
   input snapshot, numeric arrays, previews and a manifest with hashes. Existing
   directories are never overwritten. A cancelled or failed export has no
   completed `context.json`; its partial files remain available for inspection.
6. **Open context…** selects a completed `context.json`, checks its manifest,
   source, output hashes and numeric contract, then restores the inputs and
   layers. The source snapshot inside that bundle is never the editor's Save
   target: Save prompts for a separate `.dmworld.json` when starting from context.

Changing the source, assignments, frame or context resolution invalidates the
in-memory result. An obsolete worker result cannot become current. Saving the
world saves its authored source, while Export context saves the derived result
and its resolution. Reopening a source-only world still requires context generation;
Open context restores the separately exported numeric result without regenerating it.
Failed or cancelled opening retains the current workspace. Generation does not mark
an unchanged source project dirty.

## Headless generation

From the installed repository environment:

```powershell
.\.venv\Scripts\dmtools.exe world context examples/world/four-shores.dmworld.json --output artifacts/four-shores-context --latitude-cells 180
```

The CLI accepts 4–360 latitude rows for bounded controls and generation. The UI
exposes the three useful overview choices. Source/runtime changes during a build
prevent completion. Exporting an in-memory result after software changes requires
regeneration. No stochastic stage or seed is involved in this geographic analysis.

## Bind context to rough terrain

In the World workspace, generate or open context before using the **Local terrain** tool; the
current matching context is passed automatically. The CLI accepts a completed
manifest or its directory:

```powershell
.\.venv\Scripts\dmtools.exe world terrain examples/world/four-shores.dmworld.json --continent Southmere --context artifacts/four-shores-context --output artifacts/southmere-terrain
```

Preparation requires the exact retained world, projection and optional geology
recipe. It transforms a fixed support grid over the bounded AEQD terrain domain and
stores the immutable samples in terrain project v9. Each axis is capped at 129
samples; unsupported polar stencils fail instead of extrapolating beyond the source
latitude-cell centres. Selecting a continent may include physically connected
neighbours; domains beyond local projection/support limits are rejected, and M1
does not produce an accepted world parent.

Land fraction and the eight exposure/support fractions use bilinear interpolation.
Water IDs and flags use nearest source support for display/provenance only. No water
graph or raster land mask is interpolated: the projected source vectors remain the
terrain land/coast authority. Shore distance retains a continuous conservative
interval. Rough relief consumes only
`min(projected-vector distance, spherical upper bound)`, which can reduce projection
overestimates resolved by context and often has little or no effect on compact
worlds. The lower bound is retained for review and never drives height.

The saved binding separates three identities: `context_numeric_sha256` covers
geographic metadata and actual arrays, independent of previews/container bytes;
`producer_runtime_sha256` records the geographic producer runtime; and
`binding_sha256` covers the transferred metadata and sampled fields. Climate,
runoff, aging, bathymetry coupling and water transport are explicitly unsupported.

Verify an existing result from a manifest or directory:

```powershell
.\.venv\Scripts\dmtools.exe world inspect-context artifacts/four-shores-context
```

Viewing retains the recorded producer runtime and accepts a supported current
format even if this installation's code/dependencies differ. The CLI reports that
mismatch. Export still requires the exact producing runtime: regenerate to create
new results under changed software. Reopening also rebuilds water incidence from
source: a changed geometry runtime that produces different ordered graph arrays
requires regeneration. Context v1-v3 are superseded; regenerate from retained world
snapshots. Recreate v3-linked bathymetry recipes/results against current geography.
There is no compatibility loader or migration.

## What the layers mean

| Layer | Meaning |
|---|---|
| Land coverage | Area-weighted land fraction from 0 to 1 in each spherical cell. Tiny islands and water holes remain in these fractions. |
| Connected water | Water regions derived from continuous prepared vectors, joined across the longitude seam. Cell colour uses the body with the greatest aggregated water area within that cell. |
| Water openings | Blue edges: fully open; orange: partial opening; dark: closed. Three display pixels per cell reveal the shared edges when zoomed. Hover supplies physical widths. |
| Water connectivity | Blue: one water piece; gold: several; green: dry. Pink marks pieces whose source region has unresolved connectivity. Hover lists piece IDs, source regions and incident interval counts. |
| Shore distance | Cream at 0 km to purple at 3,000+ km; nearest sampled shoreline from the cell centre, including inland shores. Grey means no shoreline exists. Hover includes the distance overestimate bound. |
| Water exposure | Tan at 0% to blue at 100% distance-weighted water along the selected initial look direction. Land does not block the ray. |
| Exposure support | Dark at 0% to gold at 100% of exposure quadrature weight falling in mixed coastal cells. Not a numerical error bound. |
| Resolution support | Orange: land absent at the cell centre. Cyan: water absent at the centre. Violet: disconnected water pieces within one cell. Amber is other mixed coverage. |

Water IDs are ranked by area, with deterministic geometric tie-breaking. They
are derived IDs for one input/algorithm, not persistent names for oceans or lakes.
A named sea may be part of a much larger connected body. Small bodies retain
measured areas even when no cell displays their ID. The source remains available
at full retained vector detail.

Connectivity follows positive-length water openings across the seam. A point
contact, including at a pole, does not connect two bodies through a land barrier.
A narrow source strait can connect water globally while remaining unresolved by
this grid. A dominant water ID must never be used as an unqualified cell-to-cell
flow link. The flags conservatively expose mixed geometry. Edge widths are measured
separately, as described below; neither product specifies transport capacity.

## Water openings

Each cell stores the longest continuous wet interval along its east and south
shared edges. Land is removed using prepared source vectors; separate gaps are
not added into one opening. At the longitude seam the interval must be open on
both sides. The last east column links to the first; the last south row is zero,
since the pole has no finite-length edge. Northern values come from the cell
above, with zero at the north pole; western values come from the previous column.

For a meridian interval, length is `R * delta_phi`. For a latitude-circle interval
at latitude phi, it is `R * cos(phi) * delta_lambda`; angles are radians, radius and
output are kilometres. These are lengths along cell faces, not great-circle chords.
The seam comparison pins both edge geometries to the exact same source x coordinate,
avoiding roundoff in `x1 - (x1 - x0)` without moving any land geometry.

Fully dry cells have exact land fraction one and water ID zero. When clipping
leaves only a zero-area boundary remainder, generation uses that geometry to
remove floating-point phantom water/support flags. It does not round away real
positive-area water with a fraction cutoff.

A positive opening is evidence of a shared wet edge. It is **not** a strait's
minimum width, a navigable passage, depth, sill height, or discharge capacity.
Several face openings can touch different disconnected water pieces inside a
cell. The split-water flag remains authoritative: joining all those faces through
one raster node would create false routes. Use the separate water-piece graph
below for incidence. Physical sill/capacity geometry and conservation gates are
still required before a flow solver uses these data. [Bathymetry](world-bathymetry.md) now supplies explicit depth scenarios,
but its centre samples alone cannot establish exchange capacity.

## Water-piece connectivity

Each disconnected positive-area part of water inside a cell has its own node,
even when it belongs to the same ocean as another piece. Links require a shared
open boundary interval of positive length. Separate gaps between the same node
pair remain separate links. Each undirected link is stored once, from west to
east or north to south; the east seam joins the last column to the first. There
are no diagonal or polar point links. No proximity bridge or minimum-width cutoff
is applied. An interior sample point identifies a piece for inspection; connecting
sample points with straight lines would not establish an in-water route.

Clipped pieces retain spherical areas in km² and source water-body IDs. Their
areas match geographic cell water area within `max(cell area * 1e-9, 1e-8 km²)`;
per-body area uses relative tolerance 1e-9 and absolute tolerance 1e-8 km².
Area agreement does not prove connectivity. Connected-component labels are
computed separately and checked against vector region membership.

Some source slivers are thinner than floating-point clipping can represent at a
cell face. Their graph can have more components than the continuous source.
`fragmented_bodies` records those source IDs: retain their pieces and areas, show
pink support in the preview and declare transport unsupported for those regions.
Generation does not erase the water or join it by an epsilon. Component membership
across different source regions, lost area beyond tolerance, nonpositive piece
areas and exceeded complexity limits still reject generation. A future transport
consumer must inspect this support before accepting any region.

The pipeline retains boundary traces for only the current and previous rows,
with analytic full-water cells. Admission caps are 500,000 pieces, 1,000,000
shared intervals, 4,096 pieces in one cell, 2,000,000 clipped polygon vertices
and 8,192 intervals per piece face. These are geometry/work bounds, not an OS
memory or native-call deadline. Cancellation is cooperative at rows and cell
chunks. The Context summary is scrollable in compact windows; the preview stays
at its generated grid resolution when zoomed.

This is two-dimensional incidence. No water volume, sill depth, exchange rate,
flow direction, heat storage or climate is inferred. See
[ADR-0078](adr/0078-retain-water-piece-connectivity.md) and
[implementation evidence](research/2026-09-25-water-piece-connectivity.md).

## Shore distance and directional exposure

Shore distance is measured on the declared sphere, including lake shores and
water-cell distances to land. Artificial map-frame and polar edges are removed;
land/water differences across the longitude seam are true shores. The source is
not moved. Source-linear curves are sampled with gaps bounded by the smaller of
25 km and one quarter of north-south cell spacing. An exact 3D nearest-sample
query gives an upper estimate of true retained-shore distance; its overestimate
is at most half the largest gap, apart from roundoff. The displayed bound does
not include SVG flattening error. A shore-free world has NaN distances throughout.

Exposure looks along great circles in eight initial compass directions, clockwise
from true north. The maximum range is 3,000 km, or pi*R/2 on smaller worlds. Water
fraction at each sample comes from its containing context cell. Nearer samples
receive more weight, exp(-3*d/range), normalized over the sampled ray. This is
geographic context, not a prediction of wind or rainfall and not uninterrupted
open-water fetch. Inland water contributes; land does not stop the ray.

There are 32–256 midpoint samples per ray, targeting one quarter of north-south
cell spacing until capped. The manifest records the actual range and step. The
support layer shows the weighted share of samples in mixed coastal cells. A ray
can miss narrow islands or straits even where support is zero, so this is not an
error bound. Pole crossings and the seam are handled on the sphere. A finer
preview zoom adds no information; compare context resolutions for sensitivity.

Shoreline admission is capped at 500,000 samples. Distance queries process 4,096
centres at a time and exposure processes 1,024 origins per chunk. SciPy's spatial
index avoids all-pairs distance work. These allocation/work limits and cooperative
cancellation do not cap native geometry call time or OS process memory.

## Numeric and geographic contract

The grid covers the declared full-sphere Plate Carrée frame, with cell centres
strictly between the poles. Longitude is periodic. For latitude edges phi_n and
phi_s and longitude width delta_lambda in radians, cell area is
`R² * delta_lambda * (sin(phi_n) - sin(phi_s))`. Rows run north to south; columns
follow the source frame west to east. Stored longitudes wrap into [-180°, 180°)
around the declared central meridian and need not be numerically sorted.

Coastal cell intersections use the same source-linear spherical boundary integral
as world preparation, with reference subtraction and compensated summation for
tiny pockets. Land fractions are physical area fractions, not flat-page fractions. All cell areas sum to the sphere; land coverage and connected water
must conserve prepared source area to `max(sphere area * 1e-9, 1e-8 km²)`.
Numeric roundoff within 1e-9 of a fraction bound is clipped to [0, 1]. Curved SVG
boundaries still have the retained importer's documented flattening error.

The largest supported grid contains 259,200 cells. Geometry is intersected one
row at a time and pure cells avoid per-cell coastline operations. This bounds
numeric grid allocation; it is not an OS memory cap on native geometry operations.
North-south cell width is `pi * R / latitude_rows`; east-west width varies with
latitude. This context does not reuse the local terrain endpoint-node grid.

## Export contract

[Context v4](../schemas/world/context-v4.schema.json) owns the manifest. It records
`spherical-geography-v5`, importer/preparation identities, the canonical complete
input hash, software/runtime identity, frame, grid, settings, area checks, water
regions, support counts, gateway semantics/counts, shoreline error bound, exposure
range/quadrature semantics, graph counts/registration/fragmentation support and SHA-256/byte counts for every
output. `context_sha256` fingerprints the entire canonical manifest excluding
that field; `input_sha256` identifies the complete source/settings/algorithm.

| Product | Contents |
|---|---|
| `world.dmworld.json` | Portable original SVG, assignments, frame and source identity. |
| `geography.npz` | Numeric arrays listed below; load with `allow_pickle=False`. |
| `land.png`, `water.png`, `support.png`, `gateways.png` | Derived previews; gateways use three pixels per cell to show shared faces. |
| `exposure.npz` | Float64 `shore_distance_km` [rows, columns]; Float32 `water_exposure` and `exposure_mixed_support` [8, rows, columns]. Bearings follow N, NE, E, SE, S, SW, W, NW. |
| `shore-distance.png`, `exposure-north.png`, `exposure-support-north.png` | Cell-resolution previews; exposure PNGs show north. The numeric archive retains every direction. |
| `connectivity.npz` | Typed piece and shared-interval arrays below; graph algorithm `cell-water-pieces-v1`. |
| `connectivity.png` | Cell-resolution piece count and unresolved-region support preview. |
| `context.json` | Completion manifest, published last with an atomic rename. |

Geography NPZ fields: `land_fraction` Float64 [rows, columns], `water_body` Int32
[rows, columns] (0 means no assigned water), `support_flags` UInt8 [rows, columns],
`cell_area_km2` Float64 [rows] (broadcast across columns), and Float64 centre
coordinates `latitude_deg` [rows], `longitude_deg` [columns]. `east_opening_km` and
`south_opening_km` are Float64 [rows, columns]. Multibyte arrays are little-endian,
C-order numeric NPY entries, with no object/pickle payloads. Flags are bitwise:
1 mixed land/water, 2 disconnected water pieces, 4 land absent at centre,
8 water absent at centre. A cell can carry several flags.

Connectivity arrays use `N` pieces and `M` links:

| Field | Type and shape | Meaning |
|---|---|---|
| `cell_offsets` | Int32 [rows*columns + 1] | Row-major cell ranges into piece arrays; starts at 0, ends at N |
| `water_body` | Int32 [N] | Positive vector water-region IDs |
| `area_km2` | Float64 [N] | Spherical area of each water piece |
| `sample_uv` | Float64 [N, 2] | Interior point in the unit source frame, u eastward and v southward; not a centroid or routing segment |
| `link_nodes` | Int32 [M, 2] | Zero-based piece indices, stored once in east or south orientation |
| `link_axis` | UInt8 [M] | 0 east including seam, 1 south |
| `link_interval` | Float64 [M, 2] | Increasing [lo, hi] on a unit face: north-to-south on east faces, west-to-east on south faces |
| `link_width_km` | Float64 [M] | Positive physical length of that shared interval |

Derived component labels and incident-interval counts are rebuilt, not persisted.
The manifest records fragmented source IDs and the unsupported-transport policy.
Piece/link counts are admitted before allocation; every ordered graph array is
compared with a reconstruction from retained source geometry. Rehashed links that
cross land or connect the wrong faces are rejected. The scalar longest-opening
arrays remain diagnostics, not replacements for this graph.

Opening checks exact output/member names, product lengths and hashes, canonical
input/manifest identity, supported algorithm/importer/preparation, source geometry,
coordinate and area consistency, water IDs, support flags, finite numeric ranges,
edge-length bounds, exposure fractions, shoreline distance/nodata, sampling bounds
and preview dimensions. It rechecks files before accepting
the captured snapshot. Manifest input is capped at 4 MiB, world input at 32 MiB,
connectivity NPZ at 64 MiB, and other products at 24 MiB each. NPY shape/dtype/order and exact payload length
are checked before allocation; each compressed entry is bounded by its admitted
array size plus 10,000 header bytes. These are allocation guards, not an OS memory cap.

Verification establishes internal consistency, not authenticity or an independent
rerun of every geometric measurement. Preview layers are rebuilt from verified
arrays when displayed. Loaded arrays are read-only.

Generated results do not alter the world source. A matching result may be embedded
as bounded support for experimental M1 rough terrain, but it is not an accepted
world parent or a climate solver result. [Geology inputs](world-geology.md) can be drawn
over this read-only context in a separate editor/recipe.
[Bathymetry](world-bathymetry.md) consumes matching geography to build explicit
ocean-floor hypotheses, refreshing the geographic producer when necessary.
Full context bundles retain water-piece incidence; M1 does not transfer or solve
that graph. Physical transport/capacity and geology forcing remain later work. See
[the staged plan](strategy/world-context.md),
[water-piece evidence](research/2026-09-25-water-piece-connectivity.md) and the
[M1 binding report](research/2026-09-28-context-bound-rough-terrain.md).
