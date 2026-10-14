# Authored lakes and dry basins

Draw a **Lake** or **Dry basin** area with three or more corners, then choose
**Finish area**. Lake controls specify water level in metres. Enable **Outlet at
first vertex** before finishing a draining lake; otherwise it has closed-basin
intent. Its first corner becomes the explicit outlet marker. Undo removes the
last area using the existing authoring workflow.

Generate terrain to apply retention. Enable **Basin catchments** to locate
retained areas and the water/land feeding an outlet; teal lines show its connected
route. **Basin details** reports collected and retained sample counts, contributing
areas, outlet ground versus water level, shoreline findings and downstream routes. The public
[water example](../examples/terrain/basin-water.terrain.json) contains one lake
and one dry basin on the synthetic public coastline.

For saved projects, the read-only [water-budget command](terrain-water-budget.md)
reports shoreline and potential internal-network sample demand before a build.
It shares actual planning, but does not test terrain clearance or water connectivity.

## What changes terrain

Every authored basin footprint excludes automatic incision and automatic detail
suppression. The canonical incision budget is zero inside it, and exact vector
membership also gates continuous sampling so reconstructed fields cannot leak
a cut into the protected area between routing nodes. Authored height points,
brushes, ridges and valleys still apply; protection is against generated cutting.
It does not erase an authored valley crossing a dry basin.

A lake stores water separately from ground elevation. Its drawn polygon is the
maximum permitted water extent, not an instruction to flatten or excavate the
entire polygon. Land below the water level minus 0.01 m is wet; higher ground
remains exposed. A lake can therefore contain islands or multiple pools.
Changing only water level or outlet leaves its ground DEM unchanged. Changing
a footprint changes its automatic-cut protection and may change nearby terrain.

Cartographic relief displays sampled lake pools in blue according to their
screen area: hidden at or below 9 output pixels squared, fading to full opacity
at 36. Small pools appear as the view moves closer; native-size exports use their
own pixel scale. This only filters presentation; numeric water stays complete.
Water colour calculations now use bounded tiles. Native export composes these
directly onto ground, retaining the same pixels without a full-size water overlay.
Viewport rendering keeps the original whole-viewport nearest-neighbour transform
for categorical areas; panning cannot change a pool's visibility. Component-area
preparation still processes the complete water raster. See
[ADR-0067](adr/0067-own-preview-images-and-tile-water.md).
Scientific elevation continues to show ground height, including the lake bed.
The generated Float32 DEM and GeoTIFF remain ground elevations; a water surface never replaces an exact height
anchor or bathymetry sample. The separate drainage/outlet review remains visible
at all scales. Physical river products and their zoom-driven local generation
are planned in [ADR-0057](adr/0057-display-water-at-the-appropriate-scale.md).

## Authored and derived data

Current project v6 supports `lake` and `dry_basin` records to `constraints`. Both store
closed normalized `points`, `water_level_m` and `outlet`. A lake requires a finite
non-negative level no higher than the generation ceiling; its outlet is a
normalized boundary point or null. A dry basin requires null for both fields.
`authoring.tools.lake` remembers level and the first-vertex outlet checkbox.

Footprints must be valid, simple polygons entirely on land, excluding SVG holes.
They cannot overlap or touch, avoiding ambiguous ownership of protected samples.
Outlets must lie on the footprint boundary within 1e-9 times the longest metric
extent. Geometry checks run before generation; malformed footprints are not
silently repaired. Only the current project/build formats are supported.

The generation result retains water products and a review on the shared
257-longest-side canonical grid. Intent IDs are one-based, deterministically
sorted by kind, level, outlet and points. They identify this result and can change
when inputs change; they are distinct from derived depression candidate IDs.

Build v16 includes `water.npz`, sharing the delivered DEM's grid and axes:

| Field | Meaning |
|---|---|
| `surface_m` | Float32 lake level at wet samples; NaN everywhere else |
| `depth_m` | Float32 water surface minus ground at wet samples; zero elsewhere |
| `intent_ids` | UInt32 authored footprint ID, including dry portions; zero outside footprints |

`routing.npz` includes `basin_intent_ids` and `retention_terminal_mask` on its
canonical grid. All marked terminals have receiver -1.
`diagnostics.json` adds `authored_water` and `water_sha256`; existing DEM/routing
hashes and the completion manifest bind all products together. The water review
contains each ID's authored record, counts/flags, retained contributing area and
outlet-route evidence, connection state, captured/retained/exported contributing
area and uncontrolled shoreline counts. `collected_wet_cell_count`,
`collected_dry_cell_count` and `retained_cell_count` partition each footprint's
canonical samples. These counts are not contributing areas: a single sample can
capture a large area from outside the footprint. No pickle loading is needed.

## Planned retention and contributing area

Every canonical node in an authored footprint is an absorbing terminal in the
planning graph. Priority-Flood uses these nodes as additional seeds without
raising them. D8 assigns no outgoing edge, and MFD distributes none of their
area onward. Incoming planned channels end at their first footprint node.
Each interior node retains its own local contribution; this does not invent
an internal lake channel, a shared basin floor or overflow between pools.

`captured_contributing_area_km2` sums the MFD area at that intent's terminals.
`retained_contributing_area_km2` is the portion left after any outlet transfer.
Across all terminal land nodes, the sum equals land-node count times canonical
x/y spacing, within floating-point tolerance. This is the existing equal-node
contributing-area convention, not exact vector polygon area or water volume.
The review reports `unexpected_planned_basin_exit` if a channel violates the
terminal contract. No footprint node may receive automatic cutting or detail
suppression. Geometry smaller than the grid can resolve still needs refinement.

This automatic-incision graph continues to absorb lake area during terrain
generation. The finished-ground outflow layer connects eligible declared
outlets afterward. Changing a lake level or outlet leaves ground and the
automatic-incision graph unchanged; its derived water connection can change.
The separate `canonical_drainage` analysis still fills a diagnostic copy toward
land boundaries to inventory natural depressions. Its conditioned receivers
are candidate topology; they do not override authored retention.

## Candidate outlet review

The exact authored outlet is evaluated on the finished field, rounded to
Float32. `outlet_ground_minus_water_m` records ground elevation minus the authored
water level: positive is above water, negative is below, null means no evaluated
outlet. A difference within 0.01 m is treated as equal for review findings.
`outlet_above_water` blocks connection; `outlet_below_water` is an informational
finding and does not block it. Submerged ground does not establish a controlling
sill or a stable water level. The tool never moves the outlet or changes the
water level to erase this difference.

Within one grid diagonal, the nearest outward land node supplies a
candidate attachment; row-major order breaks distance ties. The attachment
must stay on vector land, leave its own footprint, and avoid other footprints.
Selection happens before downstream success is known, so an obstruction is not
hidden by choosing a farther node. A wet sample within the same distance and
connected by a segment inside the footprint is required for sampled water contact.

The water-contact node, exact outlet and selected outside attachment form a
short connection profile. Re-evaluate the finished ground between those points,
rounding each value to Float32. Spacing is at most one quarter of the shorter
canonical axis step; every nonzero segment also includes an interior sample.
Authored narrow cores receive additional feature-guided stations as described below.
A sampled height above water plus 0.01 m blocks the connection. A submerged
crest can remain passable. The largest sampled ground height and its position
are evidence for this selected connection, not a surveyed controlling sill.

The review follows the finished field's conditioned D8 receivers to a terminal
or the first invalid step. It inspects **unfilled** ground heights along the
entire visited route, including the attachment from the lake's water level.
It records canonical flat indices, reviewed length in kilometres, uphill step
count, maximum rise, maximum height above lake level, terminal index and boundary
flags. The maximum height above water includes the finer connection and
external profiles; uphill counts and `maximum_rise_m` still describe adjacent
coarse steps, starting from the lake level at the attachment. Statistics cover
the inspected prefix if geometry or a graph error blocks further tracing;
they are not a complete breach estimate.

The full inspected external path, from the first outside attachment to its
candidate terminal, receives one feature-guided ground profile with a shared
65,536-sample budget. Every canonical vertex remains exact, and its sampled
height must match the canonical Float32 ground or generation fails. Record the
largest rise from any earlier sampled low: `max(h - cumulative_minimum(h))`.
A rise above 0.01 m blocks transfer, even if each small step is below tolerance
or the whole path stays below the lake level. Its crest index identifies
the first maximum excursion; its low index identifies the first preceding minimum.

This extends the conservative non-rising-ground review; it is not a hydraulic
flow test. Flow across adverse bed slopes depends on water-surface, energy and
storage assumptions that are not modeled. A blocked rise calls for explicit
pool/level review, not automatic excavation or a claim that real flow is impossible.
Early tracing failures mark the inspected prefix with `reaches_terminal=false`.
A true value means the candidate graph reached a terminal; existing checks can
still reject that terminal's geometry or unknown boundary level.

Every segment is checked against vector land and every authored footprint, so
a gap or protected area between raster nodes cannot be silently jumped. Re-entry,
cycles, invalid receivers, inland terminals, uphill steps above 0.01 m and an
outlet above water are reported. Enclosed SVG-hole terminals and raster-edge
terminals without exterior-water adjacency need an explicit boundary level.

`outlet_route.status` is `sampled_clear`, `blocked` or `unresolved` (no eligible
attachment). `sampled_clear` means this candidate has no detected obstruction
at the sampled spacing across both the short connection and inspected external
path. Ocean levels and unsampled river gradients remain unresolved. Connection
additionally requires the water and shoreline checks below. Every regeneration reassesses
the route on the current finished field; no stale connected state is persisted.

## Connecting an eligible outlet

An outlet is `closed` when absent, `blocked` when its route or lake checks fail,
and `connected` when its sampled path and water connection are usable. The
explicit outlet is the authorization to derive this connection; the process
adds no new authored geography and changes no ground height.

A connected lake must have one wet component reaching the selected contact
node, with vector-contained D8 links between water samples. Eligible lakes now
also check the finished ground between each pair of wet neighbours. A link whose
sampled maximum exceeds water plus 0.01 m is removed in both directions. Submerged
crests and changes within the tolerance remain passable. Clear alternate wet
paths can keep the pool connected; a blocked link alone does not block its outlet.

Keep the previously selected contact, chosen before finer internal success was
known. If any wet node cannot reach that contact after rejected links are removed,
the whole outlet stays blocked and all captured area stays retained. Do not
choose a farther contact, drain just one newly separated pool or connect pools
through dry nodes. This preserves the existing single-pool requirement.

The network reuses feature-guided profile plans, with one 65,536-sample budget
for all candidate links in a lake, including repeated endpoints. The baseline
count is checked first, then refinement plans are added before any positions or
ground are evaluated. An excessive plan returns no per-link evidence or reachable
count and cannot activate partial transfer. Samples share batches of at most
4,096 across links; each endpoint must match canonical Float32 ground exactly.
A single wet contact with no wet links needs zero additional samples.

All low shoreline
edges outside the declared outlet opening block connection. The opening is
bounded to one canonical grid diagonal from the exact outlet: both endpoints
of an exempt low edge must be within that distance. Raster-edge leakage is
never exempt. This aperture remains a declared sampling allowance, not an
estimated channel width.

The exact polygon boundary also receives finer ground samples at the spacing
above. Every drawn corner is included, with canonical ring orientation/start.
Any boundary sample below water minus 0.01 m outside the allowed opening blocks
connection, even when no coarse wet node reveals it. Closed lakes receive the
same review with no permitted opening; dry basins have no water-boundary review.
A low boundary sample is potential uncontained water, not proof that a particular
interior pool reaches it. The conservative gate does not merge isolated pools.

Each profile permits at most 65,536 requested sample stations. Ground evaluation
uses batches of at most 4,096 distinct positions. If the requested count exceeds that budget, it returns unresolved
with empty evidence and blocks connection. It never silently loosens spacing.
These are deterministic checks, independent of delivered DEM resolution; they
cannot rule out unsampled terrain between probes. The baseline alone cannot
resolve narrow authored cores; the local refinement below targets those cores.

Dry footprint nodes transfer captured area only when their internal D8 path
reaches connected lake water. Each link must stay entirely inside the authored
polygon, including between samples. The steepest eligible downhill neighbour
wins; slopes use metric axis spacing and fixed D8 order for ties. Wet receivers
use lake surface height, not submerged bed depth. These dry-to-dry and
dry-to-water ground checks still use canonical endpoints; the finer internal
review applies only to links whose two endpoints are wet.

Exact equal-height areas with exits gain separate integer routing ranks toward
lower ground and away from higher ground. A flat edge always decreases rank;
a strict downhill edge always decreases head. Elevations are never nudged or
filled. All downhill exits participate, including paths ending in lower closed
pits. No exit is invented at the polygon or grid boundary, and nearly equal
Float32 heights are not rounded together. Closed flats and dry pits retain
their contributions. An exposed height anchor can remain an island.

This bounded adaptation of the Barnes/Lehman/Mulla method is recorded in
[ADR-0038](adr/0038-route-basin-flats-with-integer-gradients.md). Internal flat
routing runs only after the declared outlet and connected water pass review;
it cannot make a blocked outlet usable.

The connected wet and dry nodes supply captured MFD area to the reviewed
outlet path. Every path node receives that amount as additional throughput;
its final boundary receives it once. Routes avoid all authored basins, so
self-return and inter-basin cycles cannot be activated. Connections between
lakes remain unsupported. Shared downstream segments add the contributions of
independent outlets without adding local source area a second time.

This is a derived transfer layer over the existing MFD capture model. It does
not resize or cut the downstream channel, recompute all terrain runoff, or
certify the other planned rivers. **Drainage review** shows connected outlet
paths in teal; ordinary relief and the DEM remain ground/water-surface products.

## Finer water evidence

Build v16 stores the additional evidence in `diagnostics.json`, under
`authored_water`; numeric archives retain their existing layouts.
`sampling_algorithm_id` identifies `feature-guided-float32-water-checks@4`.

Each lake's `shoreline` contains a `profile`, `opening_radius_km`,
`low_sample_count`, `uncontrolled_low_sample_count` and
`uncontrolled_low_sample_indices`. The last field indexes the profile directly;
counts include its repeated closing endpoint. A dry basin has null shoreline.
`outlet_route.connection_profile` is null without both a selected water contact
and an outside attachment.

Boundary, connection and external downstream profiles use the same fields:

| Field | Meaning |
|---|---|
| `status` | `sampled` or `budget_exceeded` |
| `spacing_limit_km` | Maximum requested spacing in local kilometres |
| `requested_sample_count` | Exact count when sampled; required lower bound when over budget |
| `feature_sample_count` | Added stations beyond the baseline, or null when unresolved |
| `feature_spacing_limit_km` | Smallest active feature/detail spacing limit used in the plan, or null |
| `positions_km` | Ordered local metric coordinate pairs, including exact vertices |
| `ground_m` | Matching Float32 ground values represented as JSON numbers |
| `minimum_ground_m`, `maximum_ground_m` | Sample extrema, null when unresolved |
| `maximum_position_km` | First position attaining the sampled maximum, or null |

Unresolved profiles contain empty position/height lists. All evaluated values
must be finite; an invalid sampler result fails generation. All profiles share
the current final-field evaluator and preserve source constraints, ground arrays
and the original capture graph.

`outlet_route.downstream` is null when no external path node was inspected.
Otherwise it contains:

| Field | Meaning |
|---|---|
| `profile` | Full inspected path evidence, or empty over-budget evidence |
| `reaches_terminal` | Candidate graph reached a terminal; does not certify its water level |
| `path_vertex_sample_indices` | Profile index for each `path_flat_indices` entry, in order; empty over budget |
| `maximum_uphill_excursion_m` | Largest sampled rise from any earlier low; zero for no rise, null unresolved |
| `rise_from_sample_index`, `rise_to_sample_index` | Earlier low and later crest; null for zero rise or unresolved |

A topologically incomplete path has `reaches_terminal=false` even if its prefix
profile was fully sampled. An over-budget complete path can have a true value
with no ground evidence. Neither state can clear a blocked route. The budget
applies once to the whole inspected path, never independently to each edge.

The baseline stations remain present. Each prepared point, brush segment or
smoothed ridge/valley segment whose narrowest core radius divided by four is
less than the baseline spacing can request refinement. Intersect a conservative
corridor extending two nominal influence radii around that geometry with the
profile; include closest approaches, projected endpoints and corridor ends.
Sample the intersecting intervals with spacing no greater than one quarter of
the narrowest core radius. Use the evaluator's 0.35 endpoint taper and 0.82
minimum width variation for structures, and its 0.45 attached absolute-point
radius factor. Attached relative points act through a structure profile; they
do not add a separate local core.

Regional polygons also guide every water profile. Within conservative corridors
extending twice the inward transition distance around their boundary segments,
request spacing no greater than transition/4 when finer than the baseline.
Intersect the path with the region and refine the portions inside those corridors
to at most one quarter of each contained interval's length. This catches thin
crossed regions even when their nominal transition is broad. Include each such
interval's midpoint if it lies in the corridor. Deep interiors need no extra transition probes; procedural guidance below
may still refine them. Tangencies add no zero-length interval, and concave regions retain
every separate crossing. Polygon vertex clearance is not used as physical width.
See [ADR-0044](adr/0044-guide-water-profiles-through-regional-transitions.md).

Procedural guidance requests a maximum physical gap of half the finest active
noise lattice cell: `largest_feature_km / 2**detail_levels` for the global field.
This also applies when global variability is zero but ridge/valley widths still
use global detail. Nonzero-relief regions request
`feature_size_km / 2**max(2, detail_levels)` only inside their polygons; regional
recipes always contain at least two macro octaves. Combine overlapping requests
at the finest spacing. A zero-relief region adds no regional noise request, but
does not cancel global guidance: global detail can still change structure widths.

Point and line context shoulders use the same radius factors as the evaluator.
For structures, use the maximum variable radius (1.18 times nominal); attached
absolute points use their 0.45 radius factor. Narrow contexts request context/4
spacing within conservative twice-context-radius corridors, retaining every
crossing. Broad contexts already fit baseline spacing: add one interior closest-
approach station to the complete normalized geometry within twice the context
radius, without buffering each segment. Attached relative points remain part of
the structure profile. See
[ADR-0045](adr/0045-sample-procedural-detail-and-context-shoulders.md).

These are finite sampling choices, not spectral cutoffs or continuous terrain
error bounds. Gaussian tails extend beyond the chosen corridors, blended extrema
can lie between probes, and a single broad-context closest approach does not
locate every longitudinal peak. The
[detail/context comparison](research/2026-09-13-detail-and-context-sampling.md)
records the residual errors and complete-budget failures alongside the gains.

Normalize and split feature geometry once per immutable prepared feature,
keeping every crossing. Merge overlapping interval requirements using the finest
active spacing and retain deterministic station order. Duplicate guidance does not
increase sample counts. The profile count is checked before allocating the
refined positions or evaluating ground. If the baseline alone exceeds the
budget, its count is a lower bound and feature planning is skipped. Otherwise
the count includes the complete merged refinement plan. Neither failure returns
partial ground evidence. The smallest local spacing is not a global uniform
resolution or an accuracy guarantee. Context-only anchors can add stations
without lowering the baseline spacing limit.

**Basin details** reports boundary counts, the highest sampled connection
ground and the largest downstream climb, plus extra feature samples and the
smallest local spacing limit. It distinguishes a candidate-terminal profile from
a prefix and reports exceeded budgets. Orange dots mark low boundary samples
outside the opening; red diamonds mark above-water connection ground and the
crest of a blocked downstream climb. The climb crest may differ from the path's
global maximum. Both review toggles and the finished-terrain review show these
markers. The complete evidence remains in the diagnostic file.

### Exact reuse and count meaning

Within one profile/network sampling call, identical pairs of Float64 coordinate
bytes share one pointwise ground evaluation. Signed zero and distinct neighbouring
coordinates remain distinct. Every requested station receives its original
Float32 value in its original order, including repeated endpoints, before
canonical checks or link/path diagnostics run. No value cache persists between
calls, lakes or generations.

`requested_sample_count`, per-link `sample_count` and feature-added counts still
count logical station occurrences, including shared endpoints. They are the
unchanged inputs to complete-budget decisions, not counts of evaluator calls or
distinct positions. Reuse cannot admit an otherwise excessive profile/network.
Sampled maxima, failure witnesses, full link records and area accounting are
unchanged. See the [reuse measurements](research/2026-09-13-water-sampling-reuse.md).

## Internal water-link evidence

Build v16 includes `wet_links` to each basin diagnostic. It is null for closed/dry
basins and when an earlier eligibility check prevented collection review. Null
means unreviewed, not clear. Only vector-contained pairs whose endpoints are wet
are candidates, recorded once with ascending canonical flat indices.

| Field | Meaning |
|---|---|
| `status` | `sampled` or `budget_exceeded` |
| `spacing_limit_km` | Quarter of the shorter canonical axis spacing |
| `candidate_link_count` | Number of undirected wet links in this contained graph |
| `requested_sample_count` | Exact station count when sampled; required lower bound when unresolved |
| `blocked_link_count` | Links with above-water ground, or null unresolved |
| `contact_reachable_wet_cell_count` | Wet nodes reachable from the existing contact, or null unresolved |
| `links` | Per-link evidence; empty for an excessive whole-network plan |

Each link records `first_flat_index`, `second_flat_index`, `sample_count`,
`feature_sample_count`, `feature_spacing_limit_km`, `maximum_ground_m`,
`maximum_position_km` and `blocked`. The maximum position is the first sampled
maximum from the lower flat index toward the higher one. This is undirected
connectivity evidence, not a preferred water-flow direction. Complete profiles
are not duplicated into JSON for every internal link; their decision maxima and
sampling provenance are retained, including for clear links.

`wet_component_count` remains the coarse raster-component count. The new reachable
count can be smaller even when that coarse count is one. Counts measure canonical
water nodes and requested probes, not pool area, barrier width or water volume.
**Basin details** explains the blocked-link count, contact reach and budget status.
Red diamonds mark the high ground, including when alternate paths keep a lake
connected. The clipped water surface and ground DEM remain unchanged by review.

## Finer dry collection paths

After water reaches the selected contact, review every vector-contained D8 link
that could descend or cross an exact flat from dry ground. Wet nodes use the
imposed water surface as head; other nodes use canonical Float32 ground. For a
link ending at wet water, profile head is `max(ground, water level)`. A submerged
bed rise therefore does not act as an exposed obstruction. Dry-to-dry profiles
use ground even if intermediate samples fall below the lake level; this does
not silently add an unreviewed wet connection.

Unequal-head links are oriented downhill. Equal-head dry links must pass in
both directions to preserve the symmetric graph used for flat routing. Remove
both directions when a sampled rise from an earlier low exceeds 0.01 m. Route
the remaining graph using the existing metric steepest-descent and integer-flat
rules. Every eligible exit participates, including those ending in closed pits;
removing a link can change flat ranks and redistribute both collected and retained
area. Neither a lower closed pit nor an authored obstacle is filled away.

Compose the selected profiles in reverse flow order to measure their complete
uphill excursion. A low on one link may precede a crest many links later, even
when each link passes separately. If the combined excursion exceeds 0.01 m,
retain that donor and its upstream paths. Valid downstream donors can still
collect. This last gate does not search other complete paths; local alternatives
are chosen during the earlier link screening. The review is conservative terrain
evidence, not a storage model or proof of hydraulic impossibility.

Dry links share a separate 262,144-sample budget per eligible lake, including
repeated endpoints. Baseline and feature refinement plans must all fit before
any ground evaluation. Samples share batches of at most 4,096. Failed plans
export no partial evidence or dry receivers and retain every dry donor; already
verified water can still feed the outlet. Each profile retains the existing
65,536-sample limit. Increasing delivered resolution does not increase any of
these budgets or refine canonical routing topology.

`dry_links` in each basin review is null when earlier outlet/water checks stop
collection. Otherwise it records status, quarter-grid spacing, candidate count,
requested samples (a lower bound after early budget failure), blocked count and
`cumulative_uphill_cell_count`. Each sampled link records oriented canonical
indices, sample/feature counts, finest feature spacing, maximum uphill excursion
and the low/crest positions supporting it. For equal dry heads, the larger of
both directions supplies the witness. Positions refer to the Float32-derived
head profile; submerged values may have been clipped to water level.

`path_barriers` records where a chosen path first exceeds the accumulated-rise
limit while its downstream suffix still passes. The per-node excursion archive
below includes upstream inheritance too. **Basin details** explains both stages
and the budget result. The review draws up to 12 strongest dry-link/path crests
per basin, at least 16 display pixels apart; every candidate remains in exported
diagnostics. These markers report sampled evidence, not a complete ridge map.
The [dry-barrier example](../examples/terrain/dry-collection-barrier.terrain.json)
adds a relative +150 m point with 100 m influence radius. Finer probes expose a
131.44 m climb and a clear alternative still carries the donor's contribution.

## Outflow products and conservation

Build v16 includes `basin-flow.npz`, using the canonical axes in `routing.npz`:

| Array | Type | Meaning |
|---|---|---|
| `internal_receivers` | Int64 | Canonical row-major flat index of the internal receiver; -1 for terminals or no derived route |
| `flat_rank` | UInt32 | Positive integer rank at resolved flat donors; zero for other nodes |
| `internal_path_uphill_m` | Float64 | Maximum rise from an earlier low over each selected complete internal head path; zero for terminals, outside or no derived route |
| `catchment_class` | UInt8 | 0 outside footprints; 1 retained; 2 collected water; 3 collected dry ground |
| `retained_km2` | Float64 | Captured MFD area still held at each footprint terminal; zero elsewhere |
| `source_km2` | Float64 | Captured MFD area removed from eligible footprint terminals |
| `throughput_km2` | Float64 | Additional area carried along connected outlet paths; shared segments sum |
| `terminal_km2` | Float64 | Additional area delivered once at each downstream boundary terminal |

Every footprint node has exactly one class. Closed lakes, dry basins and blocked
outlets retain all nodes. A connected lake collects its reachable wet and dry
nodes; dry nodes without a downhill or resolved-flat path to connected water
stay retained. Internal receivers describe a separate graph, not the original
MFD capture graph or the external outlet path. Water nodes are terminals in
this internal graph. Closed/blocked basins have receivers -1 and ranks zero.
A positive flat rank does not by itself imply collection: its path can still
end in a closed pit. A retained donor can also have a receiver path ending at
water when its `internal_path_uphill_m` exceeds 0.01 m; valid suffix donors can
still collect. A zero excursion alone does not imply a derived route or collection.

Per-basin diagnostics report `flat_routed_cell_count` for all resolved dry flat
donors and `collected_flat_cell_count` for those reaching water. These count
flat steps, not every upstream node benefiting from them. **Basin details**
shows both. Diagnostics also record `flat_routing_algorithm_id`.

`source_km2 + retained_km2` equals the original captured MFD area at each footprint
terminal and is zero outside. The `retained_km2` sum matches the retained-area
summary. The classification is a footprint review, not a delineation of the
entire upstream watershed. **Basin catchments** uses cyan for collected water,
green for collected land and amber for retained nodes. Colours use nearest
canonical nodes and preserve endpoint alignment when resized. The finished-ground
panel in `drainage.png` shows the same fills; they never recolour the ground DEM.

`throughput_km2` is not total river discharge and must not be summed as a
catchment area or added to every old terminal balance. Source and terminal
sums must agree. Diagnostics include the outflow algorithm ID and accounting:

`land-node source area = retained basin area + direct MFD boundary area + outlet boundary area`

An imbalance outside the floating-point tolerance fails the build. Per-basin
captured area equals retained area plus `outlet_contributing_area_km2`. The
`basin_flow_sha256` and manifest bind the archive to the other products.

The [connected-outlet example](../examples/terrain/connected-outlet.terrain.json)
authors a narrow valley all the way to the public coast. Part of its captured
area drains through the lake; isolated dry pockets remain retained. The
[flat-outlet example](../examples/terrain/flat-outlet.terrain.json) adds a
zero-relief plateau and narrower height influences to exercise exact flat
routing alongside retained pits. It uses five detail octaves so the complete dry
network fits the current sample budget. At six octaves, finer width-detail probes
exceed that budget: every dry donor stays retained while verified wet flow
survives. Tests cover both cases; increasing raster export resolution does not
change either review.

## Shoreline findings and remaining work

- `shoreline_low_ground`: finer boundary samples fall below water outside the
  permitted opening; connection is blocked despite any clear coarse route.
- `shoreline_sampling_unresolved`: the whole boundary exceeds the sample budget.
- `outlet_connection_above_water`: the short contact/outlet/attachment profile
  finds above-water ground; recorded on the candidate route.
- `outlet_connection_unresolved`: the connection profile exceeds the sample budget.
- `outlet_downstream_uphill`: the external profile climbs more than 0.01 m from
  an earlier low, requiring pool/level assumptions before transfer.
- `outlet_downstream_unresolved`: the whole external path exceeds the sample budget.
- `low_boundary`: wet land borders below-level ground beyond its drawn polygon
  by D8, or reaches the raster edge. An intended outlet can explain part of
  this evidence; other shoreline sections still need review.
- `exposed_height_anchor`: an absolute height point is at or above lake level
  within the polygon. It may be an intentional island; its height stays.
- `outlet_above_water`: the exact outlet ground is above the authored level.
- `outlet_below_water`: the exact outlet ground is below the authored level;
  informational, with the measured signed difference. Sill stability is unmodeled.
- `unresolved_footprint`, `no_water_at_level` and `disconnected_water`: the
  canonical grid resolves no area, no wet ground or multiple separate pools.
- `outlet_shoreline_uncontained`, `outlet_water_disconnected` and
  `outlet_route_blocked`: connection is blocked by extra shoreline openings,
  water separated by the footprint or sampled high ground, or downstream findings.
- `dry_link_barrier`: fine head rises remove candidate dry links; clear
  alternatives may still drain their donors.
- `dry_link_sampling_unresolved`: all dry area stays retained after a whole-network
  budget failure, while already verified water can still drain.
- `dry_path_uphill`: some chosen dry paths exceed the cumulative 0.01 m rise
  limit even though every selected link passes separately.
- `wet_link_barrier`: above-water ground removes one or more internal water
  links; alternate clear paths may still connect all water to the contact.
- `wet_link_sampling_unresolved`: the internal network exceeds its sample budget;
  all captured area stays retained with no accepted partial network.
- `outlet_partial_catchment`: the outlet connects, but dry ground that cannot
  reach its water surface retains part of the captured contributing area.

The water surface remains an authored, clipped level preview. No runoff,
water budget, automatic spill, breach, sediment or nested depression hierarchy
is simulated. Next, measure residual blended/grazing extrema and whole-project
sampling cost, then define controlling-sill and storage assumptions before
explicit lake chains. Full constrained
breach/reroute proposals must preserve budgets and authored anchors. See
[ADR-0043](adr/0043-review-dry-collection-paths.md).

For measured results and the prioritized next steps, read the
[sampling rundown](research/2026-09-13-detail-and-context-sampling.md).
