# Build and inspect numeric terrain

Generate a saved project without opening the desktop workbench:

```powershell
.\.venv\Scripts\map-maker.exe terrain build examples/terrain/example.terrain.json --output artifacts/example-build
```

Choose a **new output directory** for every build. The command rejects an
existing file or directory and returns a nonzero exit code on failure. It
uses the project's saved settings and constraints with the same generator as
the workbench. No input file or generator setting is changed.

Before a detailed water build, use the read-only
[water-budget forecast](terrain-water-budget.md) to inspect shoreline and
potential internal-network sample demand. It does not create a build or replace
its water review.

For a finer bounded window of the unchanged field, use the separate
[regional sampling command](terrain-regional-sampling.md). Its artifact is not a
full terrain build and does not include the reviews listed below.
To reuse a finished build, use [verified-parent regional generation](terrain-parent-regions.md).

## Products

| File | Meaning |
|---|---|
| `elevation.tif` | Same Float32 DEM in local-metric GeoTIFF with embedded valid-data mask |
| `elevation.npy` | Authoritative little-endian Float32 elevations in metres; NaN outside land |
| `land-mask.npy` | Authoritative boolean land membership, separate from zero elevation |
| `x-km.npy`, `y-km.npy` | Authoritative Float64 coordinate vectors in kilometres |
| `inputs.json` | Typed portable input snapshot v4: dissolved geometry, settings, constraints, authoring state and optional immutable world-context samples |
| `cartographic.png`, `scientific.png` | The two existing display styles derived from this DEM |
| `basin-flow.npz` | Internal basin receivers/flat ranks/path climbs, collected/retained nodes and contributing-area transfer |
| `water.npz` | Authored lake surface, depth and footprint IDs on the delivered grid |
| `routing.npz` | Canonical planning and final-field elevations, mask, coordinates, receivers, contributing area, channels, heads, orders, outlets, incision and its effective limit |
| `drainage.png` | Four-panel planning, uphill-channel, conflict-context and basin/spill review |
| `diagnostics.json` | Delivered-surface quality measurements and separately labelled canonical drainage diagnostics |
| `manifest.json` | Completion record, input/runtime identities, coordinates, output sizes and SHA-256 hashes |

The input snapshot has its own [v4 schema](../schemas/terrain/input-snapshot-v4.schema.json).
It retains effective inputs without external paths; build provenance still records
the original project/SVG hashes. `inputs.snapshot_schema_version` identifies it.
The saved-project format is v9.

The NPY files contain numeric arrays only and need no pickle loading. The
GeoTIFF carries the same elevations with local metric coordinates and an
embedded mask; see the [export contract](terrain-geotiff.md). The current plane maps the longest SVG
dimension to the authored object size, with x increasing right and y increasing
down. Samples include both extent endpoints. For a world-derived project, that
object size is fixed by its retained metric projection. A context-bound manifest
retains projection parameters and radius as provenance, but the numeric rasters and
GeoTIFF remain local and are not world-georeferenced. Keep the prepared source SVG
with the project for complete correspondence. Do not import these arrays directly
as longitude/latitude. Numeric input snapshots preserve effective geometry.
For context-bound projects they additionally preserve the bounded sampled context
and its world/projection/geology identities. The source SVG remains the owner of the
complete prepared-world metadata.
The [coordinate contract](terrain-coordinates.md) explains the shared frame,
endpoint registration and distinct output versus shared routing/diagnostic spacings.

Example numeric inspection from the repository root:

```python
from pathlib import Path
import numpy as np

build = Path("artifacts/example-build")
elevation_m = np.load(build / "elevation.npy", allow_pickle=False)
land = np.load(build / "land-mask.npy", allow_pickle=False)
x_km = np.load(build / "x-km.npy", allow_pickle=False)
y_km = np.load(build / "y-km.npy", allow_pickle=False)
print(elevation_m.dtype, elevation_m.shape)
print(float(elevation_m[land].min()), float(elevation_m[land].max()))
```

`inputs.json` is for provenance; it is not accepted by **Open project**.
Retain the original `.terrain.json` and its SVG to regenerate through the
supported loader. Portable project bundles remain separate future work.

## Read the diagnostics

`delivered_surface_quality` measures the saved output grid. Elevation minimum,
maximum, mean and standard deviation use valid land samples with equal weight;
they are not area-weighted estimates. Directional records report:

- requested distance and effective rounded distance in kilometres;
- axis and integer lag in sample intervals;
- number of supported sample pairs;
- average absolute height difference in metres; and
- semivariance in square metres, half the mean squared height difference.

The current requested distances are 25, 100 and 400 km. Each axis rounds
independently to the nearest interval, with half intervals rounding upward
and a minimum of one interval. No interpolation or detrending is performed.
Every sample along the pair's axis-aligned segment must be land; comparisons
cannot jump across a masked coast or hole. An unsupported lag has zero pairs
and null statistics. Zero semivariance with supported pairs means equal
heights, which is different from insufficient support.

Use the effective distances and pair counts when comparing grids. A 25 km
request cannot measure 25 km structure on a grid spaced 60 km apart. These
raw axis measurements distinguish orientation and spatial disorder; they are
not a complete landform classifier or a realism score.

`canonical_drainage` evaluates a separate diagnostic surface on the same
257-longest-side grid as planning. Dimensions and spacing are recorded in the
manifest. Neither becomes finer merely because output resolution increases.

## Inspect planned drainage

`routing.npz` is a numeric-only archive (`np.load(path, allow_pickle=False)`).
All 2D arrays use the manifest's `routing_grid`; `x_km` and `y_km` give endpoint
coordinates. `source_elevation_m` is authored macro terrain before automatic
incision. `filled_routing_elevation_m` is its Priority-Flood copy;
`final_elevation_m` is the finished Float32 field evaluated on the same nodes,
stored as Float64 for analysis. These three surfaces use zero outside land:
apply the archive's `land_mask`, not an elevation threshold.

`receivers` contains row-major flat D8 indices, with -1 for terminals and sea.
`outlet_mask` identifies terminal land nodes on the filled routing graph.
Build v20 includes `retention_terminal_mask`, identifying absorbing authored basin
nodes among those terminals. Their D8 receiver is -1 and MFD area stays there;
other nodes can deliver incoming area to them. Eligible lake outlets transfer
captured area afterward in the separate `basin-flow.npz` product; this avoids
changing ground or conflating automatic incision with finished-water flow.
`accumulation_km2` is MFD contributing area; channels and Strahler order follow
the distinct D8 tree. It is not a calibrated water discharge or a watershed ID.

`incision_m` includes the automatic floor and steepness corrections.
`incision_limit_m` records their effective upper bound on each routing node,
combining available elevation, the global correction reserve and the regional
relief budget. Both arrays are zero outside land, and incision must not exceed
its limit. The limit does not bound authored valleys or residual-detail
suppression. Its semantics are identified by the automatic-valley algorithm in
the manifest; this adds a derived array without changing project or manifest
structure.

`routing_agreement` in diagnostics compares planned channel receivers against
Priority-Flood routing of the finished field. It also counts edges rising more
than 0.001 m on the unfilled finished surface and records their maximum rise.
Receiver differences can be harmless; an uphill edge is review guidance, not
a claim about whether a lake should exist. `routing_sha256` binds these metrics
to the archive, alongside the delivered `elevation_sha256`.

`drainage.png` compares planning and finished terrain with the same planned
channels. The workbench's **Drainage review** uses scale-selected connected blue
reaches and keeps every sampled uphill edge red. **All channels** shows the full
network. Lines redraw at viewport resolution, while their routing samples remain
canonical. These are diagnostic reviews, not validated river maps. No display
operation changes an input or DEM; see the [drainage guide](terrain-drainage.md).

## Completion and reproducibility

Only a successfully published `manifest.json` marks completion. Failed builds
can retain partial files or `.manifest.pending`; use a new directory when
retrying. Source edits detected during a build abort completion. The source
project, SVG and installed Python package files are fingerprinted; runtime and
dependency versions are recorded. No network service is needed to build.

For a context-bound project, `manifest.json.world_context` labels the binding
`experimental-rough-terrain`. It distinguishes consumed coastal support from
retained latitude/fraction/water/exposure fields and explicitly lists climate,
runoff, aging, bathymetry coupling and water transport as unsupported. The binding
digest covers the immutable samples used by base generation, automatic drainage,
regional sampling and verified-parent replay.

Consumers must validate the manifest and verify product hashes. Register the
[current build schema](../schemas/terrain/build-v20.schema.json) and
[current project schema](../schemas/terrain/project-v9.schema.json) locally by
`$id` for offline validation. Older formats are unsupported. The
[seed contract](terrain-seeds.md) describes the single named-stage algorithm.

The build ID is SHA-256 of the manifest serialized with sorted keys, two-space
indentation, default JSON ASCII escaping and a trailing newline, excluding
the `build_id` field itself. It includes product hashes and excludes timestamps
and destination paths. Two runs of identical inputs, installed source and
runtime should reproduce the same files and ID. Changing display code can
change this identity even when DEM samples remain equal; compare the
`elevation.npy` hash to distinguish that case. These records do not guarantee
cross-platform bitwise equality or archive dependency binaries.

See [ADR-0024](adr/0024-publish-local-numeric-terrain-builds.md) for the accepted
scope and the [development strategy](strategy/README.md) for world placement
and terrain-algorithm work that follows.

## Channel conflict context

`diagnostics.json` now includes `channel_conflicts`, with algorithm and tolerance
identity plus overlapping context counts. `routing.npz` includes the UInt8
`channel_conflict_flags` mask and metre arrays `channel_rise_m`,
`receiver_cut_deficit_m`, `final_adjustment_rise_m` and `final_fill_depth_m`.
See [ADR-0032](adr/0032-classify-channel-conflicts.md) for bit values and formulas.
`drainage.png` shows planning, finished uphill channels, conflict context and basin extents.
Colours have a display priority; the archive retains every flag. These products
support review and do not carve a breach or create a lake.


## Inspect basin extents and spill candidates

Canonical drainage now uses the same finished Float32 samples and routing grid
as channel review. `basin_labels`, `conditioned_final_elevation_m`,
`conditioned_final_receivers`, `nonland_class` and `boundary_flags` are retained
in `routing.npz`. Candidate records in `canonical_drainage` contain extent IDs,
the deepest/floor locations and a representative exit, spill and terminal.
See the [complete basin contract](terrain-basins.md) for data types, ties and units.

The fourth review panel shows purple extents, white deepest nodes, and yellow
routes/spill diamonds for the eight deepest candidates. The workbench's
**Drainage review** toggle displays the same products alongside planned channels.
They do not assign lake levels, classify authored dry basins or modify terrain.


## Authored water products

Build v20 includes `water.npz` with delivered-grid Float32 water surfaces/depths and
UInt32 footprint IDs. `routing.npz` adds canonical `basin_intent_ids`;
`diagnostics.json` records `authored_water` and `water_sha256`. Ground elevations
remain in the DEM and GeoTIFF. Cartographic relief shows wet lake samples, while
scientific elevation shows the ground beneath them. See the
[water contract](terrain-water.md) for retention rules and unresolved flow conflicts.


Build v20 requires `basin-flow.npz` on the canonical routing grid and records
`basin_outflow` plus `basin_flow_sha256` in diagnostics. It includes Int64
`internal_receivers`, UInt32 `flat_rank` and Float64 `internal_path_uphill_m`
alongside `catchment_class` and the
retained, source, throughput and terminal area arrays. Diagnostics partition
collected/retained samples, count resolved flat donors and report the signed
outlet-ground-minus-water difference. The finished-ground
review panel shows the basin classifications. These describe captured area and
additional delivery from connected outlets, not total river flow.
See [the water contract](terrain-water.md#outflow-products-and-conservation)
for field definitions and the conservation equation.

Build v20 includes shoreline, short water/outlet-attachment and complete
inspected downstream profiles in `diagnostics.json`. Each records metric positions,
Float32 heights, baseline spacing, added feature-sample count, smallest local
refinement spacing and completeness. Downstream evidence maps canonical vertices
into its profile, separates terminal reach from ground availability and reports
the largest climb from an earlier low. Low-boundary indices and crest positions
support review markers. See the
[finer water evidence contract](terrain-water.md#finer-water-evidence).

Build v20 includes internal `wet_links` review to each basin diagnostic. Per-link
maxima, locations, sample counts and refinement limits show which contained
water links passed or were removed. The network records the number reaching the
selected contact and whether its shared sample budget was resolved. Earlier
ineligible basins have null evidence; excessive networks have no accepted prefix.
See the [internal water evidence](terrain-water.md#internal-water-link-evidence).

Build v20 includes `dry_links` evidence and Float64 `internal_path_uphill_m` in
`basin-flow.npz`. Candidate dry descents and exact flats receive bounded finer
profiles before selection. Complete selected paths must also pass the cumulative
0.01 m head-rise gate before collecting area. A dry-network budget failure retains
all dry area while verified water can still drain. Read the
[water contract](terrain-water.md#finer-dry-collection-paths) for orientation,
water-head, witness, alternative-path and retained-suffix semantics. Current
review identities are `authored-basin-water-review@10` and
`captured-mfd-reviewed-d8-outlets@8`. Build v20 and input snapshot v4 record
project v9 settings, line profiles and optional bounded world context. Generator @21
and automatic valleys @15 identify the context-aware pipeline. Superseded formats
are unsupported; numeric archive layouts are unchanged by the profile inputs.
