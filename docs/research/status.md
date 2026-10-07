# Current terrain research status

**2026-10-07 update:** planet and regional images now use
[natural colour and display-only sub-mesh detail](2026-10-07-natural-map-rendering.md)
(continuous vegetation, varying shelves, carved regional valleys, ridge-following snow).
Authoritative relief and exports are unchanged.

**2026-10-06 update:** the plan is world-first. An experimental
[whole-planet erosion harness](2026-10-06-whole-planet-erosion-relief.md) evolves
all land of a saved world on an irregular sphere mesh. It produces strictly
descending, direction-unbiased river networks whose relief statistics converge
with mesh density. It uses procedural forcing only. It is not yet a product
accepted parent. It is now the experimental product command `dmtools world planet`
([guide](../world-planet.md), ADR-0085). Geology recipes drive calibrated forcing, and
[climate v0](2026-10-06-planet-climate-v0.md) adds temperature, winds, precipitation,
runoff-weighted erosion and provisional biomes. The World tab has a Planet stage with layers,
hover inspection, export and a zoom into experimental regional detail from cached
blended tiles (ADR-0086). Next: runs on real authored worlds. Stable continents now erode into marginal swells and interior
basins, and [lakes](2026-10-06-planet-lakes-and-cratons.md) fill young depressions by
climate water balance (open or endorheic). The text below describes the state before this change.

Reconciled on 2026-09-28 through experimental M1 context-bound rough terrain.
Geographic context now has one bounded numerical terrain consumer; climate, runoff,
bathymetry coupling and application aging remain unimplemented.

The [M1-M8 plan](../strategy/README.md) owns execution order. The
[decision catalog](decision-catalog.md) owns technology/method conclusions and
revisit triggers; [TODO](../../TODO.md) owns the grouped scope. The
[method register](terrain-method-decisions.md) preserves failed trials, while dated
reports retain their original measurements, source/runtime identity and limitations.

**Next: M2 climate/runoff, then M3-M4 aging/coupling.** Matching generated or
reopened geographic context now reaches rough terrain through conservative coastal
distance support. Bathymetry remains a separate unconsumed product. The evolution
engine remains an isolated reference. M2-M4 will extend the
experimental application path; M5 requires quality acceptance before default use
or a reviewed world parent. See [stage connections](../strategy/world-context.md#first-integrated-application-slice).

The [progress reassessment](2026-09-24-progress-and-generation-strategy.md)
classifies the product as a usable research workbench with strong build
foundations, before consistently convincing drainage/landforms. Eight current
public cases still contain 32–132 m sampled internal rises on some planned
channels whose endpoints descend. Default density/review changes did not replace
D8 geometry. Shared terrain/channel agreement remains the quality milestone.
After minimal comparison/flat-routing evidence, the
[landscape-evolution plan](../strategy/landscape-evolution.md) brings a bounded
two-epoch uplift/incision/hillslope comparison forward before a large path-only
implementation. The [first batch](2026-09-24-landscape-evolution-reference.md)
now implements and measures that reference. Chronology is useful; D8/bilinear
channel profiles and whole-landscape grid sensitivity prevent product acceptance.

Verified-parent sampling, bounded sessions and shared-edge residual detail are
implemented, but cartographic/coarse-scale acceptance, parent-view transitions
and inherited fine hydrology are still open. Smaller diagnostic channels can
appear at zoom; real local river generation and automatic viewport jobs cannot
be claimed from that display behavior.

The recorded 2026-09-24 audit found SciPy and Numba Python 3.14 Windows wheels,
and a Landlab wheel whose dependency inventory includes GPL `py-richdem`. A subsequent
[wheel-only resolution](2026-09-24-landscape-evolution-models.md#windows-and-python-dependency-probe)
succeeds with 45 distributions, including two prereleases. The Landlab/SciPy
stack was subsequently installed in an isolated 53-wheel reference environment,
including plot/test tools and current application dependencies. Landlab/SciPy
execute and are benchmarked. SciPy is now also adopted in the application for
unit-sphere shoreline queries; the larger Landlab stack remains isolated.
The dependency register distinguishes this reference from a shipped engine.

## Implemented world source and geographic context

The [new source review](2026-09-24-world-context-enrichment.md) compares existing
geographic, tectonic and climate models, including the 2026 Generic-PCM reduced
ocean work. The [WC0-WC6 plan](../strategy/world-context.md) now advances world
import/placement and provisional context before world-informed terrain. Rough
relief feeds seasonal climate/runoff, followed by bounded history feedback and
a reviewed world parent. Ecological classifications remain downstream.

The [WC0 implementation](2026-09-25-world-source-workspace.md) now adds retained
SVG source import, explicit spherical frame/radius, semantic continent/island
assignments, portable saves and a World workspace. Its world-source schema is
independent of local terrain projects. Source-only import introduced no new
runtime dependency or scientific engine. The local terrain importer still dissolves geometry for its
own workflow. The [geographic WC1 batch](2026-09-25-geographic-world-context.md)
now generates spherical coverage, connected water, resolution support, previews
and reproducible exports. The [consumption/edge batch](2026-09-25-context-reopening-and-gateways.md)
adds verified reopening, physical shared-edge widths and the fractional-origin
seam correction. The [exposure batch](2026-09-25-geographic-exposure.md) adds
shoreline distance, eight directional water/support fields and inspection, using
SciPy KDTree. These measurements are not climate or transport links. The
[geology-input batch](2026-09-25-authored-world-geology.md) adds continent defaults,
independent provinces, explicit time/priority and an inspectable recipe/editor.
The [bathymetry batch](2026-09-25-authored-world-bathymetry.md) adds explicit ocean
selection, shelf/slope/basin depths, numerical bounds and independent editor/results.
The [water-piece batch](2026-09-25-water-piece-connectivity.md) adds individual
pieces, shared intervals, source-verified graphs, bounded work and visible support
for precision-limited source regions. A usable world-to-terrain handoff now
connects imported geography to current local generation. Explicit landform controls
now transfer from geology recipes, with priority holes and identical-guidance
dissolving across ownership labels. The
[shared-blending batch](2026-09-27-shared-landform-blending.md) replaces internal
background rims and rejects a distance-only kernel that weakens enclave interiors.
Continuous weights do not accept terrain realism or physical histories.
World climate, physical province histories and same-present regional geological
replay are not implemented. Existing local detail is not history replay. Source
and license checks for Climlab/GPlates/ExoPlaSim are not local execution evidence.
B/LE2's physical paths, authoring and resolution gates remain prerequisites to
production WC2; the new world plan does not promote the current history candidate.

The [import follow-up](2026-09-25-world-import-corrections.md) fixes ordinary
DOCTYPE handling, modern Affinity layer labels, anonymous wrapper ownership and
self-crossing SVG fill interpretation. Import/exclusion counts and selected
validation conflicts make remaining source defects visible. The importer identity
is now `retained-svg-v2`. The subsequent
[bounded preparation batch](2026-09-25-bounded-world-preparation.md) adds
`bounded-world-v1`: tiny polar overflow is clipped in derived coverage, shared
same-continent land is counted once, and narrow foreign border overlaps are
resolved within linear and cumulative area limits. The original SVG, frame and
assignments remain unchanged. The editor lists selectable adjustments; larger
conflicts still fail. Previous snapshots require reimport. Zoom-to-conflict,
broader export comparisons, draft saves and import cancellation remain follow-ups.

## Implemented world-to-terrain handoff

The [2026-09-27 workflow batch](2026-09-27-world-to-terrain-workflow.md) adds
connected-land selection, custom-radius metric projection, portable exact source
geometry, fixed terrain scale and World/CLI entry points. The existing local
generator can now consume actual world continents. Public end-to-end/Tk checks
and a private four-continent Tharkeniss handoff verify this workflow. Equivalent
physical land with different ownership splits produces identical masks/heights;
confirmed native border offsets were corrected separately in the source.
Geological forcing, climate, aging and a reviewed global terrain parent are not
implemented by it. Product feature work now leads; existing research gates remain
required before changing the generation authority or promoting a new solver.

The [landform transfer batch](2026-09-27-geological-landform-guidance.md) adds
editable controls and portable recipe provenance. Public paired builds preserve
coast/mask and change broad relief. Their polygon-shaped transition rims expose
the next quality blocker: inward fallback to the generic background. This validates
the workflow, not convincing natural terrain or a new physical model.

A short four-layout river probe retained capture and bounds but failed 1–4 dense
bank sections per layout (worst 0.106–0.606 m). The mechanism behind those remaining
small excursions was not isolated. This narrows the research gap without accepting
general terrain quality, and is not the next product-blocking refinement.

## Implemented experimental history model

The [reference command](../../benchmarks/evolution/README.md) owns public metric
fixtures, typed epochs/budgets, uplift/runoff/resistance fields, implicit incision,
conservative hillslope flux, adaptive full/half-step comparison with rollback,
Float32 rerouting, complete/incomplete publication, numeric/source hashes and
HTML/PNG inspection. LE1 controls pass, including steady slope-area and moving
knickpoints. The first LE2 matrix covers frozen seeds, chronology, ablations,
orientation, extent and process spacing. These are executable experiments, not
terrain-project settings or a default generation stage.

The [frozen reconstruction follow-up](2026-09-24-frozen-channel-reconstruction.md)
now compares bilinear ground with required-diagonal triangles using unchanged
Float32 nodes and saved Float64-snapshot routing. All 22 completed cases retain
identical network coverage. Candidate sampled ascent is zero on 1,030 nodally
nonascending full routes; 153 routes with nodal climbs remain unresolved. This
comparison uses a different explicit graph/station policy from the original
final metrics, so those numbers are not a direct before/after baseline.

The candidate remains research-only: D8 geometry and grid sensitivity persist,
slopes have creases, off-grid targets can fail and reconstruction changes volume.
The [physical-path follow-up](2026-09-25-physical-channel-paths.md) now measures
shared path/ground deformation and frozen receiver/outlet sensitivity. No new
uphill routes appear and D8-aligned length falls to 56.99%, but all cases fail the
sampled no-fill policy; 17 exceed the diagnostic cut limit. Grid spacing still
moves many outlets. The [constrained network-led follow-up](2026-09-25-constrained-network-surface.md)
now constructs downhill guides within native regional limits while preserving
hard heights and a protected divide. Rotation/repeat checks pass, but independent
common-grid routing misses mouths and exposes interior sinks. It is rejected for
production. The [bank-support comparison](2026-09-25-valley-bank-feasibility.md)
now preserves endpoint drops in feasible cases and reports local/joint conflicts.
Cross-sections still climb, all four heads miss their mouths and the 250 m sink
count worsens from 19 to 30. The [connected-patch follow-up](2026-09-26-connected-valley-patches.md)
now preserves that fixed control and measures a separate 600 m / 120 km3 fresh
construction. Rounded local valleys and a coastal transition capture 4/4 fresh
heads with no sinks, but 250 m raster delivery captures 3/4 with one sink near a
hard-height correction. Some guide/bank checks still fail locally. Incident-cell
caps fix an initial interpolated-cut violation without raising budgets. The guides
were unchanged in that comparison. The [automatic-layout follow-up](2026-09-26-hard-target-valley-layout.md)
now inserts a bounded detour while preserving all original nodes/reaches and hard
inputs. At 250 m the raster captures 4/4 with no sinks or uphill guide routes, and
all interior checking samples reach the coast. The
[head/mouth follow-up](2026-09-26-valley-heads-and-mouths.md) now passes all 575 matched
local bank pairs at ordinary and <=2.5 m stations, preserving the 1 cm tolerance.
The [cell-safe bound follow-up](2026-09-27-cell-safe-terrain-delivery.md) reduces
the worst 250 m raster bank rise from 54.062 to 0.316 m. Its interior-bound proof
and independent rectangle controls retain protected terrain. Ordinary/dense
failures fall from 217/241 to 214/238, endpoints from five to two; 4/4 capture
persists, while coarse delivery remains rejected. The
[short representation probes](2026-09-27-feature-preserving-terrain-delivery.md)
now retain all 575 local profiles through a trusted-field save/reopen experiment.
The same failures return after bilinear raster delivery. River-aligned analytic
controls pass, while generic network splines lose outlets and violate bounds.
The [guarded snapshot implementation](2026-09-27-prepared-feature-snapshots.md)
now reopens the complete graph and prepared field, preserving all 575 profiles
and original metrics exactly. Owned arrays, bounded decoding and same-field
query-order/batch/tile/halo checks pass. It is an experimental reader, not an
app build or a change to product DEM authority. Held-out/general-angle terrain,
irregular coasts and real parent/detail consistency still gate changing product
surface authority or accepting a world parent. They do not prohibit M1-M4
integration of the existing reference. No time evolution was added by the snapshot
work, and the separate fresh envelope cannot accept the rejected native fixed control.
Peak/pass structure and real basins/coasts remain open. Sediment, epoch editor
controls and evolved local enrichment remain later dependent work. No
post-generation modification is introduced.

## Groundwater and canyon research - not implemented

The new review supports G1's small aquifer/stream-capture comparison, C1's layered
and lateral canyon erosion, and K1's later explicit losing-stream/spring connection.
Groundwater is a candidate explanation for some density variation, not a hidden
outlet for unintended surface sinks. Existing open-draining controls keep their
gates; basin/karst cases need explicit storage, head and terminal semantics.

In the existing Python 3.14.7 / Landlab 2.11.0 reference environment,
GroundwaterDupuitPercolator, LateralEroder, Lithology and SpaceLargeScaleEroder import
and expose their APIs. This is only an availability check: no coupled model,
conservation, performance or generated-map result was measured. Dependencies and
current runtime contracts are unchanged by this review. The proposed split between
authored specification, evolving process state and frozen delivery is planning,
not a new engine or completed schema.

## Implemented baseline

| Area | Implemented behavior | Remaining boundary |
|---|---|---|
| World source (WC0) | Retained embedded SVG, full-sphere frame/radius, seam/polar/area controls, continent/island mapping, bounded preparation with selectable adjustments, independent World tab, portable atomic saves and CLI inspect ([guide](../terrain-worlds.md)) | Partial-draft save, cancel/checkpoint imports, other projections and wider world terrain with shared boundaries |
| Input editor | Retained reference with freshness, geographic pan/zoom, property/geometry edits, undo/redo, guarded Save/Save As, resolution presets, ground inspection and cooperative Cancel/Esc with elapsed stage progress ([ADR-0064](../adr/0064-cancel-generation-at-safe-checkpoints.md)) | Automatic draft preview, comparison views, vertex insertion/removal, climate-region inputs; individual native steps have no stop-latency bound |
| Geographic context and M1 binding | Spherical coverage, vector water topology, shared-edge widths, water-piece incidence/unresolved support, shore distance, directional water/support, verified portable exports/reopening, and immutable bounded metric samples consumed by experimental coastal rough relief ([guide](../world-context.md), [M1 evidence](2026-09-28-context-bound-rough-terrain.md)) | Bounded non-polar AEQD only; component-aware transport/capacity, climate/runoff, aging and bathymetry coupling remain unsupported; context labels/fractions do not define the terrain mask |
| Local numeric builds | Saved-project CLI, Float32 NPY/GeoTIFF, review NPZ, previews, diagnostics and completion hashes | World placement, vector products, external desktop GIS acceptance |
| Scale-aware water display | Cached sampled-pool screen areas, fading small lakes, fixed-size viewport rendering, native PNG policy and actual ground-spacing readout ([ADR-0057](../adr/0057-display-water-at-the-appropriate-scale.md)) | Physical river size/width model and resolution-gated local hydrology; connected scale selection and complete diagnostic review are implemented ([ADR-0069](../adr/0069-connect-and-scale-drainage-review.md)) |
| Zoom-driven local detail | Unchanged-field sampling, verified saved-parent replay and explicit experimental residual CLI/API; exact shared samples, terrain-weighted shared edges, protected authored/water/channel context, bounded cell support and serial parent/result sessions with freshness checks and shared admission estimates ([ADR-0061](../adr/0061-verify-parents-and-isolate-local-detail.md), [ADR-0062](../adr/0062-reuse-bounded-detail-cell-support.md), [ADR-0063](../adr/0063-reuse-verified-parent-region-sessions.md)) | Remaining grid direction, visual/coarse-power acceptance, parent-view transitions, broader slope/bound checks, finer inherited hydrology, small-river readiness, zoom jobs and broader native/application-memory calibration |
| Detail-band amplitudes (R34) | Fixed geometric coefficients, explicit finer-band tails and fixed regional shape carriers; base macro fields agree exactly across 2/6/12 bands ([ADR-0059](../adr/0059-preserve-noise-band-amplitudes.md)) | Coarse-cell averages and authored drainage still change; finished-parent restriction, coarse spectral power and route inheritance remain open |
| Coordinates/seeds (R01-R03) | Source/local round trips, endpoint grids, actual spacing metadata and portable named seeds | World-bound terrain CRS, configurable process spacing, cell-average/resampling policy |
| Authored macro routing (R04-R05) | Authored macro, regular crest probes and bounded carrier-root/tangent searches shape a shared Priority-Flood/D8/MFD graph; topology and finished-field conflicts are exported | Other hidden extrema, filled barriers and unresolved final-ground climbs remain; routes are not validated rivers |
| Network floor conditioning | Downstream cut limits propagate upstream before receiver cuts; finite nodal feasibility and signed cut corrections | Between-node conflicts, impossible source/cut intervals and route alternatives |
| Valley reconstruction | Bounded cubic fields, selected-diagonal shaping and sampled attainable floor targets; canonical nodes and cut ceilings preserved | D8 turns, hidden crests beyond cut limits, endpoint/retention conflicts and complete-field error bounds |
| Authored geology (WC1 inputs) | Retained-world recipes, continent defaults, independent provinces, priorities, separate ages/duration and effective coverage/editor ([guide](../world-geology.md)) | Calibrated forcing/tapers, epoch consumption and world terrain; no age-derived erosion coefficients |
| Bathymetry (WC1 hypothesis) | Explicit oceans, smooth shelf/slope/basin parameters, actual centre-water masks, conservative depth/error fields, support views and verified portable editor/CLI bundles ([guide](../world-bathymetry.md)) | Per-margin detail, model uncertainty, volume/flux integration, component-aware transport and downstream coupling |
| Regional landforms | Plain/hill/plateau/mountain recipes, orientation, transitions and regional cut limits | Distribution targets, transition-gradient validation, related geological regions |
| Structural authoring | Point-anchored and line-owned profiles, preserved compatible absolute-ridge contacts/crests, directed valleys and junction widths | Junction-aware editing, tangents, map-visible knots, asymmetric sides and generated branching |
| Basin intent and flow | Lake/dry footprints retain terrain and captured MFD area; eligible outlets transfer collected area conservatively | Runoff/discharge, equilibrium water levels, controlling sills, lake chains and nested depressions |
| Finer water review | Shoreline/contact/full-route profiles, regional transitions, procedural density, context shoulders, wet-link separation and dry-path checks | Residual blended/grazing extrema, continuous error bounds, complete-budget cost and off-grid/path alternatives |
| Measurements (R41) | Elevation min/max/mean/deviation and masked X/Y differences/semivariances at physical lags | Detrending, arbitrary direction, terrain atlas, multiscale/topological descriptors |
| Water demand forecast | Saved-project shoreline and potential internal-network plans, exact counts or bounded lower bounds, verified source identity | External routes/contacts, actual eligibility, whole-project cost and workbench access |
| Performance (R45-R47) | Selective sampling, exact water/guide reuse, ordered D8 array sweeps, streamed regional carriers and repeatable public-fixture benchmarks | Full many-region builds, larger grid/index crossover, export cost and native migration evidence |

The current format inventory lives in [schemas](../../schemas/README.md), and
algorithm identities, sample budgets and numeric evidence belong to the
[build](../terrain-builds.md) and [water](../terrain-water.md) contracts.
No new terrain/schema contract is implied by this status page.

R04 and R05 are complete as bounded routing/review slices. Other unchecked R IDs
may have partial foundations; their broader experiment is not complete merely
because related controls or exports exist. In particular, the four recipes do
not close regional distribution/geology research, and shared-point equality does
not prove cell-average equivalence. R07 remains open: dry-basin retention does not
enable negative land heights. Negative ocean depths use a separate bathymetry product.

The [cubic reconstruction comparison](2026-09-16-bounded-valley-reconstruction.md)
records reduced cell-edge slope breaks. The
[connected-diagonal follow-up](2026-09-16-connected-diagonal-valleys.md) reduces
scalloping and sampled climb size on eight baseline and three additional cases.
Canonical routing matched; water outcomes matched in the eight performance
cases. The [source-aware floor follow-up](2026-09-16-source-aware-channel-floors.md)
then fits cuts to the actual source between nodes, reducing cardinal as well as
diagonal climbs. Off-grid heights intentionally change; large hidden crests
beyond the current cut ceiling remain. The
[mountain-crest routing follow-up](2026-09-16-mountain-crest-routing.md) now observes
selected crest crossings and rebuilds the drainage graph around lower passes.
Canonical routing and derived cuts can change, under the same budget policy.
Complete-field clearance, other hidden extrema, full downstream conditioning,
grid-aligned turns and physical river validity remain open.

The [routing-cost follow-up](2026-09-17-drainage-routing-cost.md) reduces repeated
Python work and bounds temporary carrier storage. All measured numeric products
and diagnostic summaries match; broader terrain-quality and whole-project scale
questions remain separate from that optimization.

The [crest-refinement follow-up](2026-09-17-refined-mountain-crests.md) admits
same-sign candidates and searches observed crossings/tangent approaches. It
retains every earlier regular observation and sharply reduces understated
barriers against dense finite references. Finished-channel metrics remain mixed;
features within one unsampled interval and full-route validity remain open.

The [attainable-floor follow-up](2026-09-17-attainable-channel-floors.md) reduces
extra dips ahead of unremovable barriers and carries sampled source pits forward.
That change preserved canonical routing/floors and cut ceilings. At the recorded
revision, seed 7's diagnosed climb fell to approximately 50.93 m. The later
[band-policy change](2026-09-22-stable-detail-band-amplitudes.md) changes the source
terrain and that climb is now approximately 133.9 m in a 1025-station check.
Complete route alternatives and interactions across fixed canonical pins remain
open; the old height is not a current quality guarantee.

The [network-floor follow-up](2026-09-17-network-floor-conditioning.md) now
recovers unnecessary upstream cuts before conditioning receivers. Canonical
cuts/heights may change, while routing and ceilings remain fixed. Large sampled
climbs decrease overall, but some smaller rises and individual segments worsen;
full-path alternatives and joint nodal/interior conditioning remain open.

## Research that has not been adopted

Midpoint-residual refinement is implemented only in the research harness.
The [measured experiment](2026-09-13-adaptive-water-profile-refinement.md) exposes
false convergence against a denser finite reference, including an exactly zero
indicator that misses a 20 m peak. It is not a runtime clearance rule or a
continuous error bound. Conservative bounds for the complete blended field
remain an open prerequisite for certified adaptive stopping.

The [noise-component experiment](2026-09-13-noise-component-bounds.md) now provides
natural and polynomial/cell enclosures with explicit rounding allowances, a
Float32 field boundary and complete cell-work budgets. The current enclosure
method uses the same rounded fixed-band coefficients as production noise
([policy update](2026-09-22-stable-detail-band-amplitudes.md)); the earlier reports'
measurements retain their original normalized-noise revision. These bound the
isolated noise component under the documented arithmetic assumptions. They do not cover
coast weights, regional/constraint blending, longitudinal profiles or incision,
and have not been adopted for runtime water decisions. The subsequent
[profile-strip experiment](2026-09-14-noise-profile-bounds.md) restricts cell work
along the rounded affine path and adds conservative ordered-rise bounds. At that
recorded revision, all 864 profile trials fit its limits, including broad diagonal cases that
exhaust rectangle bounds. Fine spans are slower and the roughest tested field
still has a 66.43 m uphill gap at 4096 subdivisions. Geometry clipping alone
therefore does not supply a practical full-field stopping rule. The
[bounded-refinement follow-up](2026-09-16-bounded-noise-refinement.md) adds hybrid
rectangle/strip selection and adaptive subdivision using local extrema and
ordered-rise gaps. It accounts for every completed wave against cumulative
cell/strip/sample limits and publishes no accepted profile on exhaustion.
This is a bounded stopping contract for the isolated noise field; the full
terrain composition and its water decisions remain open.

Local RBF/screened-Poisson replacement, adopted history generation, bedrock/sediment
transport, coupled ridge/drainage generation, specialized glacial/wind/volcanic
families, Earth-analogue synthesis and learned proposals remain candidates.
WC0 source contracts and WC1 geographic coverage/topology are implemented and
tested. Geographic shore distance/exposure and authored province hypotheses are
implemented. Bathymetry now has a bounded scenario product. Physical forcing,
transport and climate/runoff remain WC1-WC4 work. Ecology follows WC6.
The input editor is followed by generation, including planned zoom-driven local
enrichment. [ADR-0048](../adr/0048-keep-zoom-driven-detail-generation.md) corrects
the earlier exclusion of regional generation; manual sculpting of completed
outputs remains out of scope. The complete alternatives and gates remain in TODO.

Landlab executes only in the separate reference environment. SciPy also runs
in the application for spherical shoreline queries. Fastscapelib and Numba
remain uninstalled here. The
[earlier source/platform audit](2026-09-24-progress-and-generation-strategy.md#current-tool-and-platform-check)
retains its pre-installation evidence, including the GPL dependency and missing
Fastscapelib wheel. GRASS, Whitebox, SPACE, HighMap, GPU transport, geological
engines and learned tools remain candidates, not successful product integrations.
The [reference report](2026-09-24-landscape-evolution-reference.md) owns subsequent
execution evidence and the selected router/precision decisions.

[The dependency register](../DEPENDENCIES.md) lists adopted packages. The local
application remains Python with NumPy/Shapely numerical and geometric work and
Rasterio/GDAL inside the export adapter. A future Rust port needs representative
measured benefit and packaging/workflow evidence; it is not the next prerequisite.

## Evidence and next experiments

The first history comparison, WC0/WC1 foundations and M1 context-bound rough terrain
are implemented. [M2-M4](../strategy/README.md#next-implementation-order) now prioritize
connecting runoff and aging to that experimental application path. M5 uses the
retained A/B/C and LE evidence to accept or replace the integrated candidate; M6
then handles world-linked regional enrichment. The [WC contract](../strategy/world-context.md)
and [LE contract](../strategy/landscape-evolution.md) provide model detail. The
entries below preserve evidence by topic, not a competing execution order.

- [Landscape-evolution research](2026-09-24-landscape-evolution-models.md) compares
  process models and tools for ordered geological epochs. LE0 research is complete;
  LE1 reference execution and the first LE2 comparison are implemented in the
  [subsequent batch](2026-09-24-landscape-evolution-reference.md). Product-quality
  acceptance, authored reconstruction, material transport and local flow are gated.

- [Progress reassessment](2026-09-24-progress-and-generation-strategy.md) records
  the fresh eight-case 65-station profile probe at `8430d01`. Endpoint descent
  does not establish an internally descending channel. Full-route feasibility,
  actual path geometry and final-surface agreement are the immediate priorities.

- [Verified-parent detail](2026-09-23-verified-parent-detail.md) implements portable
  build v19 snapshots, complete parent replay and separate sampling/enrichment
  commands. Fixed support avoids output-density drift; original reference
  structure, parent nodes, water and authored/channel cores are retained.
  [Shared-edge support](2026-09-23-shared-edge-detail.md) now carries additions
  across intermediate cell edges and measures smaller Float32 secant errors.
  Axis direction, spectral leakage and wholly protected windows remain limits.
  R34 and finer hydrology stay open; this is an opt-in experiment.

- [Exact overlapping height points](2026-09-23-exact-height-points.md) corrects
  ordinary target averaging at authored centres. Interpolating shares preserve
  individual targets, independent of point order and sampling density; coincident
  conflicts and nonzero sea-level-boundary targets are rejected. The public
  lake's 250 m target now evaluates to 250 m. This repairs the parent reference
  used by future enrichment; it does not implement that enrichment.

- [Parent-cell preservation](2026-09-23-parent-cell-preservation.md) implements
  a research-only bilinear/trapezoidal projection. All 18 density/case runs keep
  parent nodes and near-exact means, but authored heights move by up to 29.161 m,
  output density changes shared values and eight sampled channel edges worsen.
  Visible grid structure reinforces rejection. The later verified-parent
  experiment retains the reference and adds protected density-independent
  residuals. Its visual/coarse-power and finer-flow gates keep R34 open.

- [Stable detail-band amplitudes](2026-09-22-stable-detail-band-amplitudes.md)
  removes count-dependent coefficient shrinkage, separates broad regional shapes
  from fine texture, and updates isolated-noise enclosures. Four settings-growth
  cases still show coarse-cell drift; eight before/after terrain cases and dense
  regional profiles show mixed drainage effects, including a larger known crest.
  Finished-parent preservation and route validity remain separate work.

- [Bounded regional field sampling](2026-09-22-regional-field-sampling.md) records
  exact 65/129/257 nested and repeat results, complete-source context reuse and
  regional versus full finer-field cost. This closes the unchanged-field request
  foundation. The later parent-region operation adds saved-build replay and
  experimental residuals; accepted local enrichment and finer hydrology remain open.

- [Bound-driven refinement](2026-09-16-bounded-noise-refinement.md) compares hybrid
  geometry and selective subdivision against uniform refinement and strip-only
  controls across 144 fresh-process runs. Adaptive hybrid accepts 99/144 distinct
  input/tolerance combinations versus uniform's 80/144; on paired successful
  six-octave cases it saves about 70% of cell work. Rough/high-detail cases still
  exhaust cumulative budgets; this is not a full-field water-clearance result.

- [Rounded profile bounds](2026-09-14-noise-profile-bounds.md) compare three
  policies across 216 fresh-process runs. They preserve all previous control
  evidence, bound rises within and across intervals, and separate saved cell
  work from remaining local uncertainty and strip-planning overhead.
- [Procedural-noise bounds](2026-09-13-noise-component-bounds.md) compare component
  tightness and cost, verify rounding/finite-reference inclusion and fix the
  twelfth-octave hash overflow warning without changing generated noise values.

- [Prepared guide bounds](2026-09-13-water-guide-bounds.md) reject distant
  geometric candidates without changing sampling policy. The paired comparison
  covers 4/16 lakes, 16/64 points and broad overlap, with separate forecast,
  generation, review/planning and evidence-serialization measurements.
- [Adaptive profile refinement](2026-09-13-adaptive-water-profile-refinement.md)
  measures midpoint residuals, finite-reference errors and bounded exhaustion;
  apparent convergence does not authorize a new runtime sampling policy.
- [Water-budget forecasting](2026-09-13-water-budget-forecast.md) adds read-only
  saved-project demand planning and preserves the existing terrain/sampler.
- [Detail and context sampling](2026-09-13-detail-and-context-sampling.md) is
  the latest station-policy change: global/regional lattice scales and context
  shoulders guide the shared sampler. The expanded comparison covers oblique profiles,
  fixed-input field preservation, residual misses and complete-budget failures.
- [Regional guidance and convergence](2026-09-13-water-sampling-convergence.md)
  records the preceding 64-run matrix and regional barrier detection. Its
  procedural/tail misses motivated the current change; the original measurements
  remain historical evidence rather than current error claims.
- [Dry collection paths](2026-09-11-dry-collection-paths.md) records full-path
  head checks, preserved terrain/area and measured planning/sampling cost. Its
  fresh-process generation measurements are distinct from prepared-stage timings and full CLI-build timings.
- [Feature-guided sampling](2026-09-11-feature-guided-water-sampling.md) shows
  why regular quarter-grid stations miss narrow cores. Radius/4 guidance is a
  bounded sampling choice, not a terrain error bound. The later convergence
  matrix extends these measurements across regions, procedural detail and tails;
  broad geometric/feature distributions and accuracy bounds remain open.
- [Selective sampling](2026-09-05-selective-terrain-sampling.md) records a
  successful exact-output optimization and a slower rejected coast index.
  Neither result proves the best method for today's enlarged water workload.

Exact feature/sample reuse is now implemented with preserved station counts and
evidence; see the [measured follow-through](2026-09-13-water-sampling-reuse.md).
Prepared guide bounds also avoid unnecessary geometry calls; those spatial
bounds are not elevation-error bounds. Regional, procedural and context
guidance have finite-reference evidence.
The [water-budget command](../terrain-water-budget.md) now exposes shoreline
and potential internal-network demand using shared planning; the
[forecast report](2026-09-13-water-budget-forecast.md) measures its cost and verifies
unchanged terrain/evidence. It does not estimate whole-project or export cost.
For the separate continuous-bound research track, compare reusable refinement
work and tighter component correlation, then compose bounds beyond the isolated
noise term. This work is required before stronger certification claims; it is
not the next gate for every terrain/editor improvement. Measure whole-project
sampling cost and define sill/storage semantics before lake chains. Five detail
octaves keep the public flat-routing example within budget;
its six-octave regression deliberately retains every dry donor after exhaustion.
Do not present denser probes as continuous clearance or a physical lake model.
Keep the full roadmap instead of promoting every research direction into
immediate implementation.
