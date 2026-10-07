# Terrain tool roadmap

This is the working backlog for the deterministic terrain tool. It collects the
possibilities identified during the initial research and implementation without
treating every idea as an accepted design. Items marked **Research** need a
small prototype or architecture decision before they become implementation
commitments.

The [current development strategy](docs/strategy/README.md) is the authoritative
dependency-aware execution order. The sections below are grouped by product
area; their visual order is not a promise that every feature precedes algorithm
or UI work.

Priority labels:

- **P0** — prerequisite within its feature; only the active strategy batch is next;
- **P1** — high-value work after the relevant P0 contract exists;
- **P2** — useful later extension; and
- **Research** — compare approaches and validate with small synthetic terrain
  before selecting one.

The current baseline already includes deterministic coordinate-addressed
detail, dissolved multipart SVG land geometry, absolute and relative
brush/point/line constraints, per-tool settings, project save/open, colour
preview and PNG export. Numeric builds, regional recipes, authored basin
retention and sampled outlet transfer are also implemented as recorded below.
Input editing now retains the last generated reference, supports selection and
property changes, and provides undo/redo for committed instructions.
The [research status](docs/research/status.md) separates completed slices from
partially addressed research goals; unchecked broad items may contain completed
substeps. The [living method decision register](docs/research/terrain-method-decisions.md)
records attempted methods, measured failures, causes, retained work and revisit
gates. Update it alongside dated evidence and this backlog after each substantial
experiment; do not mark a desired feature complete merely because its trial ended.

## Current execution focus — 2026-10-06

**M2 is active: whole-planet relief by uplift and erosion on a sphere mesh.** The
plan is now world-first; follow the single
[M1-M8 implementation order](docs/strategy/README.md#next-implementation-order).
The [research harness](benchmarks/planet/README.md) already evolves a whole world
with converged, isotropic, strictly descending rivers
([evidence](docs/research/2026-10-06-whole-planet-erosion-relief.md)). Climate
moves to M3 on the same mesh. Further isolated local ridge/bank refinements stay
deferred; existing hard correctness checks apply throughout.

The [research decision catalog](docs/research/decision-catalog.md) is the first
lookup for evaluated tools/math, conclusions and revisit triggers. The
[method register](docs/research/terrain-method-decisions.md) retains failed trials;
[status](docs/research/status.md) distinguishes available features from experiments.
Update them with the affected milestone and evidence in every substantive batch.

### Delivered foundations

- [x] **World-to-terrain handoff:** World panel and CLI; connected neighbours,
  islands/holes/seams, bounded custom-sphere projection, retained source identity,
  fixed physical scale, portable folder, cancellation and guarded editor opening.
- [x] **Shared-land independence:** dissolve ownership before projection and verify
  exact mask/Float32 equality for the same land with different continent splits;
  retain actual narrow straits. Correct confirmed private drawing offsets at source.
- [x] **Geological landform transfer:** explicit controls in the geology editor,
  optional recipe selection in World/CLI, identical-guidance dissolving across
  labels/ages, priority holes and portable provenance. Public numeric/GUI checks
  and a paired build demonstrate visible range/plateau/lowland differences.
  See the [report](docs/research/2026-09-27-geological-landform-guidance.md).
- [x] **Shared landform transitions:** replace internal background bands with
  connected-coverage blending; retain blank holes, established enclave interiors,
  hard heights and coast/mask. Water/crest probes and cut bounds follow the same
  support. See [evidence and rejected kernel](docs/research/2026-09-27-shared-landform-blending.md).
- [x] **Line-owned peak/pass/floor profiles:** explicit metre values along a ridge
  or valley, dedicated curve editor, undo, current-format replay and bounded
  narrow-feature water sampling. See [evidence and limits](docs/research/2026-09-27-line-owned-terrain-profiles.md).
- [x] **Shared absolute ridge crests:** preserve authored contacts through smoothing,
  retain separate crest heights, report incompatible profiles and verify public
  corner/branch examples. See [evidence](docs/research/2026-09-27-shared-ridge-crests.md).

### Integration and later work

- [x] **M1 / WC1-WC2:** verified world/context binding, bounded non-polar AEQD
  domain, immutable context support, context-consuming coastal relief and portable
  application/CLI/build provenance. Experimental; see
  [evidence](docs/research/2026-09-28-context-bound-rough-terrain.md).
- [ ] **M2 / WC2 / R01 / R02 / R07 — ACTIVE:** whole-planet relief on an irregular
  sphere mesh: uplift + implicit stream power with the coast as base level, fixed
  process scale, ocean floor, geology-driven forcing, product command and
  world-placed exports.
  - [x] Research harness, synthetic fractal test worlds, realism metrics and
    resolution sweep ([evidence](docs/research/2026-10-06-whole-planet-erosion-relief.md)).
  - [x] Geology settings/ages/landform intent → uplift and erodibility with calibrated
    elevation targets (research harness).
  - [x] Promote to `src` with stage seeds, cancellation, CLI (`dmtools world planet`),
    manifest-last build, schema and ADR-0085.
  - [x] World-tab Planet stage: generate, cancel, atlas/relief/rainfall/temperature
    layers, hover inspection, export; stale results discarded on edit.
  - [x] First real authored world end to end (9 continents; ice-sheet fix).
  - [x] Natural-colour atlas and regional display detail with carved valleys
    ([evidence](docs/research/2026-10-07-natural-map-rendering.md)).
  - [x] World-scale relief and climate detail: multi-scale forcing, physical moisture
    mixing, carved display valleys ([evidence](docs/research/2026-10-07-world-scale-detail.md)).
  - [x] Cheaper moisture transport: coarse climate and coupling meshes
    ([evidence](docs/research/2026-10-07-earth-scale-landforms.md)).
  - [x] Earth-scale range widths, valley spacing and river lengths (3.2M-node builds).
  - [ ] Parallel sub-ranges, foothills and longitudinal valleys (more medium-long rivers).
  - [ ] Bathymetry product as the ocean floor.
- [ ] **M3 / WC3:** declared temperature/wind/moisture/runoff model on the planet
  mesh, consuming its relief; provisional biome labels.
  - [x] Research-harness climate v0, runoff-weighted erosion coupling, atlas render and
    windward/leeward control ([evidence](docs/research/2026-10-06-planet-climate-v0.md)).
  - [x] Young depressions and climate-balanced open/closed lakes; discharge-based rivers
    ([evidence](docs/research/2026-10-06-planet-lakes-and-cratons.md)).
  - [ ] Monthly/seasonal outputs, below-sea-level basins, energy-balance check.
- [ ] **M4 / WC3-WC4:** runoff-weighted erosion with bounded climate feedback, lakes,
  World-tab stage, comparison, cancellation and stale-result handling.
- [ ] **M5 / adoption:** reference-world quality gates, accepted planet parent, native
  core port of the stabilised kernels, and a decision on the local composed generator.
  Connected ranges/spurs/passes, junction editing, cross-sections and transition
  support follow measured needs here rather than leading integration.
- [ ] **M6 / WC5/LE6:** same-present regional enrichment, inherited hydrology and zoom.
  - [x] Research: parent-calibrated regional enrichment on fine meshes and
    window-independent blended tiles ([evidence](docs/research/2026-10-06-regional-enrichment-tiles.md)).
  - [x] Product: verified planet build reader, tile cache, `dmtools world region`,
    World-tab zoom viewer and export, lapse-corrected regional biomes (ADR-0086).
  - [ ] Tile boundary exchange (domain decomposition), regional lakes and climate.
  See M7/M8 for selected materials, specialized landforms and ecological extensions.

### Generation-quality evidence retained

The [quality reference](docs/strategy/terrain-quality.md) retains A-F comparisons
and scientific adoption controls. T01-T18 in the method register link the actual
failed and successful trials, including raster-bank limits and prepared-field
checks. Those results are not accepted drainage/history. They guide M5 and any
specific M1-M4 blocker; they no longer form a blanket ban on experimental coupling.
Existing P0 labels below mean prerequisites within their feature, not a new queue.
Consult before tests expected to exceed roughly two minutes or with uncertain
long duration; report purpose, estimate and a stop condition.

### World-context checkpoint

The [new source/tool review](docs/research/2026-09-24-world-context-enrichment.md)
and [WC0-WC6 plan](docs/strategy/world-context.md) refine the full-world workflow.
This advances world placement and forcing from the former final climate phase;
WC0 source import, the World workspace and M1's bounded context-to-relief binding
are implemented. Climate and continent-history generation remain planned.

- [x] **Research and plan:** compare geographic/tectonic/climate models and existing
  tools; define fixed-coast import → provisional context → rough relief → bounded
  climate/history feedback → reviewed parent → same-present regional refinement.
- [x] **WC0 — Retain the world source** (R01/R49): explicit full-sphere
  Plate Carrée frame/radius, continent/island mapping, source preview, portable
  SVG snapshot and guarded saves. See the [guide](docs/terrain-worlds.md) and
  [validation report](docs/research/2026-09-25-world-source-workspace.md).
- [x] **WC0 import corrections:** accept ordinary external SVG DOCTYPE metadata
  without resolving it, retain modern Affinity labels and classify self-crossing
  paths with SVG winding rules. Show import/exclusion counts and select shapes
  responsible for validation failures. See the
  [follow-up report](docs/research/2026-09-25-world-import-corrections.md).
- [x] **WC0 bounded source preparation:** tolerate tiny polar export overflow,
  count same-continent shared coverage once, and resolve thin cross-continent
  border overlaps within linear and aggregate area limits. Keep the original
  source/frame/assignments, record preparation identity, and expose selectable
  adjustments in the editor and CLI. See the
  [validation report](docs/research/2026-09-25-bounded-world-preparation.md).
- [ ] **WC0 source-quality follow-up:** add zoom-to-conflict navigation and broader
  native/high-precision export comparison when needed. Current reports highlight
  affected shapes but do not automatically zoom or diagnose every export setting.
  Draft mapping saves and bounded import cancellation remain separate follow-ups.
- [x] **WC1 geography batch:** bounded spherical cell grid, fractional land
  coverage, vector-derived periodic water connectivity, explicit mixed/subgrid
  support flags, Context preview, cancellation and reproducible context exports.
  Area conservation, seam/pole behavior, islands/straits and source/runtime identity
  controls pass. See the [guide](docs/world-context.md) and
  [evidence report](docs/research/2026-09-25-geographic-world-context.md).
- [x] **WC1 consumption/edge batch:** verified context reopening, finite shared-edge
  water openings in km, editor preview/hover and source-save isolation. Corrected
  fractional-origin seam closure; bounded archive and analytic/UI controls pass.
  See [evidence](docs/research/2026-09-25-context-reopening-and-gateways.md).
- [x] **WC1 exposure batch:** cell-centre spherical shore distance with a retained-curve
  error bound, eight-direction water exposure and mixed-cell support, direction
  previews/hover and verified current-format export/reopen. Public analytic, seam/pole,
  orientation, island/interior, bounds and UI controls pass. See
  [evidence](docs/research/2026-09-25-geographic-exposure.md).
- [x] **WC1 geology inputs:** separate portable recipe, continent defaults and
  cross-continent/seam provinces, explicit priorities and unknowns, independent
  ages/duration at one common present, effective coverage preview, guarded
  undo/save/reopen and cancellation. See the [guide](docs/world-geology.md) and
  [evidence](docs/research/2026-09-25-authored-world-geology.md). Explicit landform
  controls now drive ordinary terrain through the new handoff; categories and
  ages still do not imply erosion, uplift or climate.
- [x] **WC1 bathymetric hypotheses:** explicit ocean selection, shelf/slope/basin
  inputs, conservative spherical coast-distance profile and numerical depth bound.
  Actual water-centre membership excludes land/unselected lakes; unresolved support
  and unsampled waters remain visible. Independent editor/input saves, verified
  nested-context result bundles, CLI and schema controls are implemented. See the
  [guide](docs/world-bathymetry.md) and
  [evidence](docs/research/2026-09-25-authored-world-bathymetry.md).
- [x] **WC1 water-piece topology:** separate positive-area pieces per cell, finite
  shared intervals, periodic seam and closed polar/corner contacts, spherical areas,
  bounded geometry and source-verified current context v4. Preview/hover and CLI
  expose split pieces and precision-limited fragmented source regions. Those regions
  retain their water and remain unsupported for transport. See the
  [guide](docs/world-context.md) and [evidence](docs/research/2026-09-25-water-piece-connectivity.md).
- [x] **B/R48 physical-path comparison:** shared bounded path/ground geometry,
  exact graph coverage, sampled authoring/budget rejection and frozen receiver/outlet
  sensitivity are now measured. See the [report](docs/research/2026-09-25-physical-channel-paths.md).
  This is an experimental comparator; native generation is not changed.
- [x] **B/C constrained network-led comparison:** one public range/valley/lowland
  fixture, hard divide/off-grid heights, native cut/no-fill limits, whole-cell
  descent constraints and repeat/rotation controls. Independent routing at common
  125 m spacing rejects capture; see the [report](docs/research/2026-09-25-constrained-network-surface.md).
- [x] **B/C bank feasibility and capture comparison:** physical probes,
  junction ownership, coastal taper and local/joint conflict witnesses. Feasible
  endpoint checks pass; cross-sections and capture fail, with more sinks at 250 m.
  See the [measured report](docs/research/2026-09-25-valley-bank-feasibility.md).
- [x] **B1 connected valley patches:** local valley/confluence/coastal construction,
  fixed versus fresh input roles, conservative delivery caps and hard-height
  projection are measured. Fresh local capture is 4/4; 250 m raster capture is
  3/4, and some guide/bank checks still fail. See the
  [report](docs/research/2026-09-26-connected-valley-patches.md).
- [x] **B1 hard-target-aware automatic layout:** bounded guide relocation now
  preserves every original vertex/reach and hard input, restoring 4/4 capture,
  zero sinks and descending guide profiles in the 250 m raster. See the
  [report](docs/research/2026-09-26-hard-target-valley-layout.md).
- [x] **B1 head/mouth bank construction:** cap-aware head transitions and
  perpendicular mouth sections pass all 575 local bank pairs at 25 m and <=2.5 m
  stations. Same guides, targets and envelopes; 250 m raster banks still fail.
  See the [report](docs/research/2026-09-26-valley-heads-and-mouths.md).
- [x] **B1 cell-safe delivery bounds:** one-sided curvature allowances plus
  constant handling beside protected areas reduce the worst 250 m bank rise from
  54.062 to 0.316 m; five independent rectangle controls retain interior safety.
  Raster quality remains rejected. See the
  [report](docs/research/2026-09-27-cell-safe-terrain-delivery.md).
- [x] **B1 short representation probes:** river-aligned analytic control and
  trusted-field roundtrip preserve banks; generic splines lose outlets and bounds.
  See the [report](docs/research/2026-09-27-feature-preserving-terrain-delivery.md).
- [x] **B1 guarded feature delivery:** bounded snapshots, complete network
  reopening, owned numeric arrays and query-order/batch/overlap checks are
  implemented. All 575 banks and original gates survive reopening in the matched
  four cases; raster controls still fail. See the
  [report](docs/research/2026-09-27-prepared-feature-snapshots.md).
- [ ] **M5 quality follow-up — B1 held-out geometry and detail consistency.**
  Test new bends, tributaries, junctions and oblique layouts, then irregular
  mouths and actual parent/detail filtering. Same-field tile agreement does not
  establish independently generated detail. A separate ADR/contract decision
  remains required before changing product authority or accepting a WC4 parent;
  M1-M4 can integrate the existing reference without that representation change.
- [ ] **WC1 transport follow-up:** consume finite-face incidence only after support
  admission, conservative area/depth integration, explicit sill/capacity geometry
  and paired flux/storage budgets. Add a stable local-coordinate or exact-predicate
  comparison for source slivers if a real consumer needs them; never infer an
  epsilon bridge. Bathymetry centre samples alone cannot establish water volume.
- [ ] **WC1 bathymetry follow-ups:** per-margin profiles and optional ridge/trench
  guidance when a consumer requires them; physical-resolution/convergence controls,
  conservative water-area/depth integration and model-uncertainty scenarios. Keep
  column depth distinct from seasonal mixed-layer depth and geometry-derived
  numerical error. Never infer ocean age from width.
- [ ] **WC1 geology follow-ups:** physical forcing compilation and calibrated tapers
  when a terrain consumer exists; multipart/holed or polar-winding provinces,
  vertex manipulation, explicit world rebasing, optional per-field inheritance
  and broader complexity/memory controls only as needed. Current inputs have a
  hard categorical partition, simple rings and complete-profile replacement.
- [ ] **WC1 exposure follow-up:** compare alternate geographic ranges/weighting
  when downstream scenarios need them; distinguish connected-ocean fetch from
  the current all-water geographic score. Retain coarse-cell and quadrature
  aliasing limits, including features missed without a mixed-support flag.
- [x] **WC1 — Generate provisional context** (R07/R10/R11/R49): ocean topology and
  exposure, bathymetric hypotheses, geological provinces and inspectable defaults.
  Spherical coverage and periodic connected-water inspection are delivered.
  Shore distance, directional geographic exposure, authored geology and a separate
  bathymetry hypothesis product are delivered. M1 now consumes matching geographic
  coastal support; physical transport and bathymetry/climate coupling remain follow-ups.
- [x] **WC2 / M1 slice — Produce bounded rough physical terrain** (R02/R48/R49):
  one supported connected landmass, fixed metric scale, authored macro relief and
  conservative context-bound coastal distance are reproducible and portable.
  Wider/polar domains, physical forcing and evolution remain M2-M5 work; B/C and LE
  quality acceptance govern default adoption and WC4 in M5.
- [ ] **WC3 — Couple climate/runoff and coarse history** (R33/R49): seasonal budgets,
  explicit epoch forcing, bounded feedback and visible nonconvergence.
- [ ] **WC4 — Select a verified world parent** (R49/LE3/LE5): staged editor workflow,
  continent defaults/province overrides, shared present and stale-child tracking.
- [ ] **WC5 — Refine regional history to the same present** (R15/R34/LE6): sufficient
  parent trajectory, inherited flux, exact overlaps and no double aging.
- [ ] **WC6 — Derive ecology and compare richer processes:** classifications after
  continuous fields; advanced oceans/GCMs/plate histories only for a specific gap.

### Geological-history checkpoint

The [source/tool review](docs/research/2026-09-24-landscape-evolution-models.md)
and [detailed LE0–LE6 plan](docs/strategy/landscape-evolution.md) specify this work.
These checkpoints group existing R IDs. The
[first implementation report](docs/research/2026-09-24-landscape-evolution-reference.md)
records execution and its remaining gates; the simulation is still research-only.

- [x] **LE0 — Research models and existing implementations.** Compare stream power,
  hillslope transport, SPACE, analytical erosion, depression routing and larger
  frameworks. Record the successful 45-package Windows/Python wheel dry run,
  GPL dependency and prereleases. That initial report predates execution.
- [x] **LE1 — Validate an isolated reference** (R11/R14/R41). A 53-wheel Windows
  lock, typed inputs, bounded adaptive solver, physical ledgers and analytic
  controls are implemented. Steady channels, knickpoint time/grid refinement,
  dry/flooded cases, Float64 runoff and incomplete publication are tested.
- [ ] **LE2 — Accept a two-epoch landscape** (R11/R14/R40/R43). The comparison
  command, current/constant/reversed controls, three-seed cohort, process ablations,
  resistance, rotation/extent/spacing checks and figures are implemented. The
  D8/bilinear candidate fails the continuous-profile quality gate; keep chronology
  as a useful candidate while resolving grid sensitivity and surface/path agreement.
- [x] **LE2 evidence — Make experiments inspectable and reproducible.** New output
  directories contain epoch images, numeric states, profiles, input/runtime hashes,
  fresh-process timing/memory, conservation checks and explicit incomplete results.
- [x] **Reconstruction experiment — Compare frozen terrain and complete paths**
  (R48/R32). The [measured follow-up](docs/research/2026-09-24-frozen-channel-reconstruction.md)
  preserves every selected edge/head/terminal on 22 completed cases. A triangle
  control removes sampled ascent on all 1,030 nodally nonascending routes at
  100 m/25 m spacing; 153 nodally uphill routes remain unresolved. Hash checks,
  paired ground figures, crossing rejection, off-grid anchor conflicts, separate
  reconstruction volume and whole-climb affected length are implemented.
  This closes the experiment, not the broader authoring or production gate.
- [x] **Physical valley/path experiment and capture diagnostics** (R48/R32/R02).
  The [measured prototype](docs/research/2026-09-25-physical-channel-paths.md) keeps
  all 1,183 routes and introduces no new uphill routes; D8-aligned length falls
  to 56.99%. All 22 cases fail the sampled no-fill policy, 17 exceed the diagnostic
  30 m cut budget, and spacing changes move many sampled outlets. Native regional
  constraints and rerouted catchment geography are not yet preserved.
- [x] **Constrained catchment/network-led surface experiment** (R48/R32/R02).
  The [public comparison](docs/research/2026-09-25-constrained-network-surface.md)
  delivers a unique quadratic fit with native bounds, protected heights/divide,
  descending physical guides and explicit infeasible-route rejection. Complete
  profiles pass; independently rerouted catchments fail. This closes the bounded
  experiment, not the production drainage gate.
- [x] **Physical bank/confluence feasibility experiment** (R48/R32/R02).
  Fixed physical support, explicit mouth taper, native-bound and joint-height
  conflict diagnostics, and independent inward-profile/capture checks are measured.
  The [report](docs/research/2026-09-25-valley-bank-feasibility.md) rejects promotion:
  525 endpoint constraints pass in feasible cases, but no required head is captured
  and the 250 m candidate adds sinks. No fixed constraint was softened.
- [x] **Reassess failed methods and alternative processes** (R24/R32/R48).
  The [method register](docs/research/terrain-method-decisions.md) records eleven
  groups of failed/restricted approaches and their replacement gates. The
  [groundwater/canyon review](docs/research/2026-09-25-groundwater-and-terrain-architecture.md)
  checks primary models and existing component APIs; no new simulation was run.
- [x] **B1 input-role audit and connected-patch comparison** (R48/R32/R02).
  [Measured](docs/research/2026-09-26-connected-valley-patches.md): fixed/native and
  separate fresh construction, rounded valley unions, explicit coastal transition,
  local versus Float32 checks and inter-node envelope protection. Fresh local
  routing captures 4/4 heads with no sinks; 250 m raster captures 3/4 with one sink.
  Removing the mouth transition gives 0/4 and four sinks. Both modes retain hard
  targets; fixed/native quality and some fresh guide/bank checks remain rejected.
  That comparison held guides fixed; automatic relocation is covered below.
  No time evolution was simulated.
- [x] **B1 hard-target-aware guide placement** (R48/R32/R02).
  [Measured](docs/research/2026-09-26-hard-target-valley-layout.md): an explicit
  automatic-edge mask, bounded clearance/corridors/length, unchanged original
  nodes and reach ownership, no new crossings and repeat/rotation checks. The
  250 m raster captures 4/4 with no sinks or uphill guide routes; all interior
  checking samples reach the coast. Hard targets and fresh/native controls are
  preserved. Local/raster banks and 500/1,000 m delivery still fail. Rejected
  sine-squared detours and sampled-envelope bed lifting are documented.
- [x] **B1 head and mouth transitions** (R48/R32/R02).
  [Measured](docs/research/2026-09-26-valley-heads-and-mouths.md): the same 575 bank
  pairs change from 21 local inward failures and five endpoint failures to zero.
  All local gates also pass with <=2.5 m stations and the unchanged 1 cm tolerance.
  250 m raster delivery keeps 4/4 capture but has 217/575 ordinary and 241/575 dense
  inward failures, plus five endpoint failures. Coarser delivery remains rejected.
  Rejected head tapers, envelope lifting and the initial mouth wedge are recorded.
- [x] **B1 curvature-bounded raster capacities** (R48/R32/R02).
  [Measured](docs/research/2026-09-27-cell-safe-terrain-delivery.md): the maximum
  250 m inward rise drops from 54.062 to 0.316 m; ordinary/dense failures change
  from 217/241 to 214/238 and endpoints from five to two. Capture stays 4/4.
  Whole-cell protection has an explicit bound and independent corner/thin-area
  controls. Node-only and clipped-negative shortcuts remain rejected. Coarse
  routing and delivered bank quality still fail.
- [x] **B1 representation and trusted-field roundtrip probes** (R48/R32/R02).
  [Measured](docs/research/2026-09-27-feature-preserving-terrain-delivery.md): seven
  analytic orientations give 114/238 world-bilinear bank failures and none for a
  river-aligned strip at similar maximum height error. Generic splines reduce
  failure counts but increase rises and lose capture. Stored prepared fields
  preserve all 575 profiles and common-grid heights exactly at three background
  spacings plus a quarter turn. These are ignored exploratory scripts, not a
  supported reader or accepted product representation.
- [x] **B1 feature-preserving artifact and query boundary** (R48/R32/R02).
  [Implemented and measured](docs/research/2026-09-27-prepared-feature-snapshots.md):
  owned arrays, deterministic snapshots, bounded non-pickle loading, complete
  graph/segment consistency and query-order/batch/tile/halo checks. All 575 dense
  banks and original quality metrics match after reopening at three background
  spacings plus a quarter turn. Current application generation is unchanged.
- [ ] **M5 — B1 held-out geometry and parent/detail checks** (R48/R32/R02/R15).
  Add bounded new bends, short tributaries, junctions, hard-height proximity and
  oblique layouts. Explicitly extend or reject irregular coasts; the reader still
  supports only the fixture's straight zero coast. Check filtered/coarse means,
  retained structure and inherited flow before independently generated zoom detail.
  Keep all bank, capture and hard-input gates. Compare aligned strips or
  constrained triangles only for measured patch limitations. The large bilinear
  bank solve stays deferred behind local representability checks.
- [ ] **B1 representation adoption decision:** if the richer surface passes,
  record an ADR and change authoritative numeric source, build/schema identities,
  export/cache roles and consumers together. Current Float32 DEM authority stays
  in force until then. Keep parent/downsample/zoom contracts explicit; no visual
  overlay may replace failed ground. No legacy loaders or runtime rewrite.
  Do not raise cut budgets, soften targets or uniformly refine the world.
- [ ] **B2 — Terrain/network replacement comparison in M5** (R48/R14).
  Compare a construction/delivery pair against the M3-M4 integrated reference.
  Measure held-out seeds, oblique orientation, complete catchment coverage,
  actual-ground figures and cost before adopting the replacement.
- [ ] **G1 — Test groundwater capture and drainage density** (R24/R33).
  After B's surface decision, compare an analytic shallow aquifer and combined
  storage/flux controls, then paired transmissivity/recharge cases in the existing
  isolated environment. Measure channel survival and spring flow; underground
  routes are not exemptions for surface reconstruction errors.
- [ ] **C1 — Compare layered canyon and lateral erosion** (R09/R18/R19).
  Following B acceptance, compare plateau/base-level history, rock resistance
  and vertical-only versus lateral erosion. Validate width/rims, capture, material
  accounting and grid sensitivity. Full groundwater/karst is not a prerequisite;
  advanced collapse and dissolution remain separate candidates.
- [ ] **LE2 follow-up — Complete structural acceptance** (R40/R41/R43). Add the
  missing peak/pass and matched physical-route scorecard, resolve long D8 grooves
  and quantify capture sensitivity. The finest-grid budget failure is a stopping
  result, not permission to increase limits until it finishes.
- [ ] **LE3 — Preserve authored intent and shared terrain/channel geometry**
  (R02/R32/R48). Separate initial, persistent and final constraints; validate
  reconstruction, basin semantics, Float32 profiles and frozen-state sampling.
- [ ] **LE4 — Compare conserved bedrock/mobile sediment** (R16/R18/R33). Account
  for porosity, storage, deposition, fines, boundary exchange and corrections.
- [ ] **LE5 — Expose experimental history, then accept it** (R11/R27/R32).
  M3-M4 connect current schemas/provenance/replay and the editor with explicit
  experimental status; M5 requires full acceptance before default adoption.
  No legacy modes or output sculpting. Sediment controls depend on LE4 acceptance.
- [ ] **LE6 — Condition local enrichment and refine shared history** (R15/R34/R49).
  Validate overlap/downsample and inherited flux before zoom jobs/small rivers.
  WC5 additionally requires time-dependent parent context and replay to one present;
  final-state conditioning alone does not satisfy regional historical refinement.

### Drainage inspection checkpoint

- [x] Add an authored automatic drainage-density multiplier with deterministic,
  downstream-connected channel initiation and current-format persistence.
- [x] Derive connected reaches and unique D8 contributing areas for network
  inspection; keep MFD capture and physical incision budgets separate.
- [x] Draw drainage at viewport resolution, reveal tributaries by scale, and
  retain an all-channel review plus every sampled uphill conflict. A separate
  Depressions toggle keeps coarse basin polygons out of the default channel view.
- [x] Record public-fixture density, connectivity, unchanged-default-reference,
  zoom-rendering and performance evidence before accepting the changes.
- [ ] **P0 — Reduce D8 direction bias in actual terrain generation (R48).** Compare
  terrain-guided subgrid paths shared by routing, floor fitting and rendering;
  preserve junctions, authored divides, incision limits and lake terminals.
  Display-only smoothing cannot satisfy this requirement.
  [Current guide](docs/terrain-drainage.md) and
  [public measurements](docs/research/2026-09-24-connected-drainage-review.md)
  record the completed inspection/density work and its limits.
- [ ] **Research — Compare convergent flat routing for global filled depressions.**
  Reuse the existing basin integer-gradient primitive only after validating
  global topological order, barrier reachability, retention and MFD capture.
- [ ] **Research — Compare D-infinity and scale-specific sinuosity metrics.**
  Measure direction bias and network shape at matching physical scales; a new
  accumulation scheme alone does not supply realistic continuous river paths.

## Features

### Durable data and output products

- [x] **P0 — Define the versioned build manifest.** Record project and input
  hashes, generator and schema versions, master and stage seeds, effective
  parameters, working extent and units, runtime/dependency versions, warnings,
  and authoritative output hashes.
  Completed builds record named stage seeds, numeric product hashes,
  and explicit local-only NPY/GeoTIFF coordinates. World-bound terrain placement
  remains open; WC0 source placement is implemented separately.
- [x] **P0 — Export the authoritative Float32 DEM as local-metric GeoTIFF.**
  Implemented point registration, metre units, NaN nodata, embedded masks,
  numeric-source hashes and manifest linkage. See the
  [export contract](docs/terrain-geotiff.md).
- [ ] **P1 — Verify local GeoTIFF import in desktop GIS and standalone GDAL.**
  Rasterio numeric reads and Pillow TIFF-tag checks pass. Desktop display is
  unverified; Rasterio 1.5.1 `rio info` assumes an Earth-coordinate conversion
  and fails for the current engineering CRS.
- [ ] **P0 — Add explicit source-to-world placement and projected export.**
  Declare the planetary model, source correspondence and metric working
  projection; validate distortion and coordinate round trips. Local TIFF
  coordinates do not yet place a continent on a world map.
- [x] **P1 — Add a non-interactive build command.** Let
  `dmtools terrain build <project.dmterrain.json>` use the same domain,
  pipeline, and adapters as the desktop workbench.
  Implemented with required `--output NEW_DIRECTORY`, lossless NPY arrays,
  both existing preview styles, diagnostics and completion-last publication.
- [ ] **P1 — Derive contour vectors from a completed DEM.** Make interval,
  index-contour cadence, smoothing, and minimum feature size explicit; identify
  the source DEM in metadata.
- [ ] **P1 — Export hillshade and reusable elevation-colour images separately.**
  Keep both derived from the numeric DEM rather than from one another.
- [ ] **P2 — Export meshes and additional GIS vector products.** Possible
  outputs include drainage lines, catchments, ridgelines, slope classes, and
  local-relief layers.

### Authored geography

- [ ] **P0 — Add an explicit pass/saddle constraint.** Give it a location,
  elevation mode, saddle elevation or relative depth, influence along the
  parent ridge, and optional preferred crossing direction.
- [ ] **P0 — Give ridge and valley lines per-vertex profiles.** Vertices should
  optionally carry elevation, relative relief/depth, width, and transition
  length instead of forcing one value onto an entire structure.
- [ ] **P1 — Add asymmetric structure sides.** Let the two sides of a ridge,
  escarpment, or valley use different widths, steepness, and profile shapes.
- [ ] **P1 — Add divides, rivers, faults, escarpments, and general breaklines.**
  Define the semantics of each constraint before extending the project schema;
  a drawn line must not imply more geological certainty than the user supplied.
- [x] **P1 — Add first terrain-character regions.** Polygon authoring,
  plain/hills/plateau/mountain recipes, base height, local relief, feature size,
  orientation and shared recipe transitions feed both terrain and routing.
  See [the region guide](docs/terrain-regions.md) and ADR-0030.
- [x] **P1 — Bound automatic incision by regional relief.** Plains and
  plateau interiors now receive smaller budgets with the same regional
  transitions. Floor/steepness corrections respect those limits; numeric builds
  retain the effective limits and exact authored anchors remain authoritative.
  See [ADR-0031](docs/adr/0031-bound-incision-by-regional-relief.md).
- [x] **P1 — Classify channels blocked by regional cutting limits.** Retained
  edge evidence reports depression contact, remaining-cut deficits, final
  adjustment and regional transitions. Counts overlap; they are not causes.
  Read-only diagnostics now have their own module. See
  [ADR-0032](docs/adr/0032-classify-channel-conflicts.md).
- [x] **P1 — Map depression extents and spill/outlet candidates.** A shared
  257-node routing/review grid replaces the coarse separate inventory. Numeric
  labels, conditioned receivers, representative exit/spill/terminal records and
  exterior/enclosed boundary context support the workbench and four-panel review.
  See [ADR-0033](docs/adr/0033-map-basin-spill-candidates.md).
- [x] **P1 — Author lake levels, outlets and dry-basin footprints.** Polygon
  authoring, saved lake controls, automatic-cut retention, separate water/ground
  exports and shoreline/anchor/outflow review are implemented. See
  [ADR-0034](docs/adr/0034-author-lakes-and-dry-basins.md).
- [x] **P1 — Terminate planned flow inside authored basin footprints.**
  Canonical footprint nodes now absorb both D8 and MFD flow; contributing area
  is conserved and exported per intent; eligible outlet transfer follows below. See
  [ADR-0035](docs/adr/0035-retain-basin-flow-and-assess-outlets.md).
- [x] **P1 — Assess candidate downstream lake outlets on finished ground.**
  Review nearest outward attachments, whole candidate paths, uphill steps,
  basin re-entry, vector coastline gaps, cycles and terminal boundary context.
  Export sampled path evidence; clearance alone is insufficient for transfer
  until shoreline, wet/dry collection and whole-route gates also pass.
- [x] **P1 — Connect eligible lake outlets and transfer retained area.**
  Finished-ground routes now carry captured MFD area from connected lake water
  and dry nodes that drain into it. Extra shoreline openings and invalid routes
  block connection; isolated pockets stay retained. Shared path segments add
  area once per source, and full terminal accounting is checked. See
  [ADR-0036](docs/adr/0036-connect-lake-outflow-with-area-transfer.md).
- [x] **P1 — Show collected and retained basin nodes.** The workbench and
  finished-ground review now map collected water, collected dry ground and
  retained nodes. Build v18 exports the classification and retained contribution
  at each footprint node; sample counts and area accounting remain distinct.
  Exact outlet ground minus water level is reported, including submerged outlets,
  without treating a clear sampled route as proof of a stable lake level. See
  [ADR-0037](docs/adr/0037-expose-basin-catchment-outcomes.md).
- [x] **P1 — Route internal flats with known exits.** Integer ranks now route
  exact flats without editing the DEM. Every link is vector-contained, real
  downhill alternatives take precedence, and paths to closed pits stay retained.
  Build v18 exports internal receivers and ranks; details separate resolved flat
  donors from those reaching lake water. The public flat-outlet fixture covers
  both outcomes. See [ADR-0038](docs/adr/0038-route-basin-flats-with-integer-gradients.md)
  and the [measured rundown](docs/research/2026-09-11-basin-flat-routing.md).
- [x] **P1 — Check shorelines and outlet contact between canonical nodes.**
  Bounded profiles now sample every boundary corner and the water/outlet/first
  attachment connection. Low boundary openings and above-water connection ground
  block transfer; exports retain positions/heights and the review marks failures.
  The public shoreline-gap fixture catches a real narrow opening missed by the
  coarse review. See [ADR-0039](docs/adr/0039-sample-shorelines-and-outlet-connections.md)
  and the [measured rundown](docs/research/2026-09-11-finer-water-connections.md).
- [x] **P1 — Target narrow authored cores and crossings.** Local intervals now
  refine to the evaluator's narrowest core radius, preserve every baseline probe,
  merge overlaps and reject excessive plans before evaluation. The public
  narrow-shoreline-gap fixture detects a 200 m influence missed by the fixed
  3.90625 km profile; ground and incoming flow stay unchanged. See
  [ADR-0040](docs/adr/0040-refine-water-profiles-around-authored-features.md) and
  the [measured rundown](docs/research/2026-09-11-feature-guided-water-sampling.md).
- [x] **P1 — Review complete downstream outlet profiles.** External candidate
  paths now receive bounded feature-guided Float32 profiles, canonical vertex
  mappings and cumulative uphill evidence. Unresolved profiles block transfer;
  details and red crest markers explain the result. A public 100 m point fixture
  catches a 43.85 m climb missed by canonical nodes without changing its DEM.
  See [ADR-0041](docs/adr/0041-review-complete-downstream-outlet-profiles.md) and
  the [measured rundown](docs/research/2026-09-11-downstream-outlet-profiles.md).
- [x] **P1 — Complete internal wet-link evidence.** Batched feature-guided
  checks now remove links with above-water ground, preserving alternate wet paths.
  All wet nodes must reach the unchanged selected contact; separated pools and
  excessive whole-lake sample budgets retain captured area. Builds retain each
  candidate link's maximum, location and sample provenance; the review marks
  barriers. See [ADR-0042](docs/adr/0042-review-internal-water-links.md) and the
  [measured rundown](docs/research/2026-09-11-internal-water-links.md).
- [x] **P1 — Check dry collection links between canonical nodes.** Batched
  profiles now reject dry-to-dry, dry-to-water and exact-flat climbs before
  routing; clear alternatives and lower closed pits remain eligible. Complete
  chosen paths also check cumulative rises before collecting area. Build v18
  exports per-link evidence and path excursions. A public narrow point catches
  a 131.44 m climb and reroutes without changing ground. See
  [ADR-0043](docs/adr/0043-review-dry-collection-paths.md) and the
  [measured rundown](docs/research/2026-09-11-dry-collection-paths.md).
- [ ] **Research — Compare path-aware alternatives after a cumulative rejection.**
  Local blocked links already admit other descents and flat exits. A composed
  path exceeding tolerance retains that donor and its upstream paths; it does
  not search different downstream choices. Compare bounded state-aware methods
  without favouring lake exits over closed pits or perturbing the DEM.
- [x] **P1 — Reuse exact water-sampling work.** Prepared features now retain
  normalized parts, and each profile/network call evaluates duplicate coordinate
  bytes once before restoring every station. Budgets, Float32 ground, endpoint
  checks, routing and complete evidence remain unchanged. See the
  [measured comparison](docs/research/2026-09-13-water-sampling-reuse.md).
- [x] **P1 — Reject distant sampling guides before geometry queries.** Immutable
  guide bounds now cover core/context corridors and polygon interiors, with
  outward rounding and unchanged exact checks for possible contacts. Shared
  runtime/forecast plans retain every station and budget decision. Three opt-in
  fixtures add 4/16 lakes, 16/64 points and broad overlap; see the
  [measured comparison](docs/research/2026-09-13-water-guide-bounds.md).
- [ ] **P1 — Measure remaining network planning and evidence overhead.** Compare
  feature indexing on many-constraint scenes, project-scale profile memory and
  compact diagnostic serialization. Retain every required probe, complete budget
  decision and reviewable failed link; exact per-call reuse is already implemented.
- [x] **P1 — Compare nested and shifted finished-ground profiles.** A read-only
  five-case runner now measures regional transitions, global/regional procedural
  detail, context tails and overlapping points across scales, directions and seeds.
  Shared positions/Float32 ground must match exactly; unresolved budgets remain
  explicit. The initial 64-run matrix is finite-reference evidence, not an error bound.
  See the [convergence report](docs/research/2026-09-13-water-sampling-convergence.md).
- [x] **P1 — Guide water probes through regional transitions.** Polygon boundary
  corridors and local contained intervals now expose a 950 m plateau rise missed
  by regular probes on a 4000 km object. Preserve ground, baseline stations,
  complete budgets and existing wet/dry/outlet gates. See
  [ADR-0044](docs/adr/0044-guide-water-profiles-through-regional-transitions.md).
- [x] **P1 — Add procedural detail and context-shoulder sampling.** Global and
  regional density now follows half the finest active noise lattice cell; local
  context guidance uses evaluator radii and closest approaches. The expanded
  matrix includes oblique paths and a rotated regional-detail case, with fixed-
  input controls and complete-budget failures. See
  [ADR-0045](docs/adr/0045-sample-procedural-detail-and-context-shoulders.md) and
  the [measured report](docs/research/2026-09-13-detail-and-context-sampling.md).
- [x] **P1 — Measure bounded midpoint refinement and false convergence.** The
  research runner retains production probes, enforces complete-wave/depth limits
  and checks apparent convergence against a denser nested reference. A narrow
  20 m peak defeats an exactly zero midpoint residual. This indicator is not
  adopted for runtime clearance; see the
  [adaptive experiment](docs/research/2026-09-13-adaptive-water-profile-refinement.md).
- [x] **P1 — Establish and measure rounded procedural-noise component bounds.**
  The research harness compares natural intervals with monotone polynomial and
  bilinear-cell enclosures, including derived binary64 error allowances and final
  Float32 conversion. Complete cell budgets, exact-rational checks, finite
  references and replay hashes are enforced. The twelfth-octave hash now wraps
  explicitly without overflow warnings or changed values. See the
  [component report](docs/research/2026-09-13-noise-component-bounds.md).
- [x] **P1 — Restrict noise-bound work to rounded profile strips.** A separate
  research policy clips the original affine path through major-axis grid strips,
  preserves rounding at contacts and enforces complete strip/cell limits. Ordered
  uphill bounds include possible rises hidden within one interval. All 864 profile
  trials fit the comparison limits, while fine-path overhead and rough-field
  uncertainty remain; see the [profile report](docs/research/2026-09-14-noise-profile-bounds.md).
- [x] **P1 — Compare bound-driven noise refinement and geometry selection.** Hybrid
  geometry uses rectangles for spans touching at most two minor-axis cells and
  clipped strips elsewhere. Adaptive refinement preserves completed intervals,
  targets local extrema and both contributors to ordered-rise uncertainty, and
  enforces cumulative cell/strip/sample limits. Uniform and strip-only controls
  use the same acceptance contract. See the
  [refinement report](docs/research/2026-09-16-bounded-noise-refinement.md).
- [ ] **P1 — Reduce unresolved high-detail bound work.** Compare retaining reusable
  octave/lattice work across refinement waves, intersecting child ranges with
  retained parent bounds, and tighter within-cell/cross-octave correlation.
  Measure full cumulative cost and complete profiles,
  including rough long diagonals; do not reset budgets or accept a prefix.
  Evaluate rounding floors and exact constant-coordinate cases before lowering
  requested tolerances. These noise experiments still do not authorize full-field
  water clearance.
- [ ] **P1 — Bound residual blended and grazing sampling errors.** Establish
  conservative interval/gradient bounds for the complete field before using
  adaptive stopping to certify clearance. Account for procedural octaves, coast
  weights, regional/constraint blends, longitudinal profiles, incision and
  Float32 rounding; measured secants and midpoint residuals are not such bounds.
  Compare their tightness and cost before adopting a branch-and-bound method.
  Sweep roughness, feature scales and grazing distances, including narrow
  off-grid 2D passages. Keep whole-profile/network budgets and explicit unresolved
  results. Rounded geometry selection and bound-driven local/ordered refinement
  now exist for noise only, with explicit unresolved outcomes. Within-cell path
  correlation, correlated octave bounds, full-field stopping tolerances,
  coast/region/constraint composition and rounding of distance/exponential
  operations remain open. Neither component bounds nor the
  completed midpoint experiment close the full-field contract.
- [x] **P1 — Expose sampling demand before high-detail water reviews.**
  `terrain water-budget PROJECT` shares canonical terrain preparation and actual
  shoreline/internal-link planning. It reports exact counts or bounded required
  lower bounds and distinguishes potential networks from executed review. No fine
  profiles, delivered raster or source writes are needed. The five/six-detail
  flat fixtures match actual review demand. See the
  [command guide](docs/terrain-water-budget.md),
  [ADR-0046](docs/adr/0046-forecast-water-sampling-budgets.md) and
  [measured report](docs/research/2026-09-13-water-budget-forecast.md).
- [ ] **P1 — Extend cost forecasts only with measured workflow value.** Evaluate
  saved-project forecast access in the workbench and an explicit exportable report;
  preserve input identity and distinguish saved from unsaved edits. Measure
  route/contact demand, conditional network work and unique evaluations before
  introducing whole-project cost estimates or automatic settings advice.
- [ ] **P1 — Measure broader project-scale sampling limits.** Extend the current
  numeric stress fixtures to complex many-lake projects, alternate boundary shapes
  and total profile/export cost before adding a spatial index, shared-path reuse,
  a project-wide budget or larger per-profile limits. The completed 4/16-lake,
  16/64-point comparison now covers distributed and broad overlapping guides;
  larger counts, more boundary/constraint types and export cost remain. Preserve exact evaluation,
  complete budgets and deterministic evidence. Current guidance is a sampling
  policy, not a continuous terrain error bound.
- [ ] **P1 — Define controlling sills and physical lake-level assumptions.**
  The exact outlet height and sampled connection maximum are now visible. Derive
  the controlling opening/crest across relevant paths and define inflow, storage
  and boundary assumptions before claiming stable levels. Do not drain isolated
  pockets solely because they share an authored polygon.
- [ ] **P1 — Connect explicit lake chains.** Require compatible water levels,
  reviewed incoming/outgoing paths and acyclic basin dependencies; keep closed
  and dry basins terminal. Current outlet paths reject every intervening basin.
- [ ] **P1 — Reconcile blocked channels through explicit water/outlet choices.**
  The ADR-0032 plain fixture recorded 253 uphill edges; all exceeded remaining
  receiver cut and 234 touched depressions (historical diagnostic baseline). Spill candidates and exterior/enclosed raster
  boundaries are mapped, and lake/dry-basin intent now protects authored areas.
  Closed basins retain flow and eligible outlets now transfer captured area.
  Classify ocean boundaries and compare full paths before applying
  constrained breaches or rerouting. Measure full route depth/length,
  anchor preservation and downstream closure; never silently expand budgets.
- [ ] **P1 — Extend regional process controls.** Add drainage density,
  runoff and erosion resistance with measurable effects and authored authority.
- [x] **P1 — Render drainage review at viewport size.** Connected reaches are
  redrawn with bounded antialiasing at each view scale, with monotone catchment
  selection and All channels review. Every red conflict remains visible.
  Routing accuracy is unchanged; grid-aligned paths still need geometry work.
- [x] **P1 — Support adjacent mainland sections and disconnected islands.** SVG
  land objects are dissolved into one polygonal mask, sub-sampling border
  slivers are repaired, and all components share one metric field and seed.
- [ ] **P1 — Classify SVG water holes and ocean boundaries.** Declare ocean
  levels and enclosed-water semantics. Authored lake/dry-basin footprints are
  implemented; an enclosed SVG gap still has no inferred lake level or intent.
- [ ] **P2 — Add direct basin outlet relocation.** Selection, vertex/whole-basin
  movement and level/outlet-enable edits are implemented for pre-generation
  instructions. Moving corners keeps existing outlets on their boundary edge;
  newly enabled outlets use the first vertex. Explicitly choosing another outlet
  position remains open.
- [ ] **P2 — Refine retention boundaries and shoreline products.** Measure
  slopes where automatic incision resumes outside protected areas; soften the
  exterior transition if needed while preserving zero cuts inside. Derive
  vector shorelines and higher-resolution containment checks from numeric water.
  Test narrow footprint fingers and crossings between canonical nodes; sampled
  retention alone cannot resolve every authored polygon feature. Compare refined
  2D wet components and narrow off-grid water passages against canonical D8 links
  before treating sampled disconnection as a complete shoreline model.
- [ ] **P2 — Add reusable terrain profiles/presets.** Profiles should be
  versioned authored inputs with their own content hashes and should expose the
  effective values used by a build.

### Zoom-driven local detail generation

This is a core planned generation capability. It is separate from directly
editing a finished DEM; see [ADR-0048](docs/adr/0048-keep-zoom-driven-detail-generation.md).

- [x] **P0 — Add bounded unchanged-field regional sampling.** The saved-project
  `sample-region` command binds full input/algorithm identity, reference grid,
  power-of-two subdivision, a globally aligned window and a clipped halo. It
  rejects over-budget requests before preparing the shared field; samples only
  the requested finer nodes; preserves global constraints, routing context and
  basin IDs; and publishes numeric products, ground preview and completion-last
  provenance. Public 65/129/257 windows, overlaps and repeat visits agree exactly.
  See [ADR-0058](docs/adr/0058-sample-bounded-regional-windows.md) and the
  [measurements](docs/research/2026-09-22-regional-field-sampling.md).
- [x] **P0 — Keep existing noise-band weights when adding detail.** Each band
  owns a fixed geometric amplitude share. Regional shapes use a separate fixed
  two-band carrier and add only finer bands as texture. Base macro fields stay
  exact when moving from 2 to 6 or 12 bands. This does not preserve a finished
  parent DEM: measured coarse-cell averages still change, and authored guidance
  can redirect drainage. See [ADR-0059](docs/adr/0059-preserve-noise-band-amplitudes.md)
  and [the comparison](docs/research/2026-09-22-stable-detail-band-amplitudes.md).
- [x] **P0 — Measure an explicit parent-cell preservation candidate.** The
  all-land projection keeps parent nodes, bilinear edges and cell means within
  Float32 rounding, with exact same-density overlaps. Public 65/129/257 trials
  reject it for runtime use: the bilinear reference loses existing structure,
  authored heights move by up to 29.161 m, shared coordinates drift across
  densities and eight sampled channel edges worsen. See the
  [experiment](docs/research/2026-09-23-parent-cell-preservation.md).
- [x] **P0 — Bind regional requests to a verified immutable parent.** Build v18
  contains typed portable inputs; `sample-parent` verifies completion, hashes,
  frame, runtime and all delivered ground/water values plus reused routing.
  Original source files are no longer needed. Requests and separate output
  artifacts bind the parent ID and preserve its frame. See
  [ADR-0061](docs/adr/0061-verify-parents-and-isolate-local-detail.md).
- [x] **P0 — Add a bounded experimental residual on the retained reference.**
  `enrich-region --experimental` conditions only an added smooth residual,
  with globally addressed edge coefficients, fixed 17-by-17 preparation probes,
  parent-node equality and measured zero-added-mean moments. Authored cores,
  basin footprints, coastal margins and planned channel corridors are protected.
  65/129/257, overlap/revisit, water and bounds checks pass on public fixtures.
  [The measurements](docs/research/2026-09-23-verified-parent-detail.md) also expose
  regular cell support and windows completely excluded by protection. This is
  an executable experiment, not accepted cartographic terrain or finer hydrology.
- [x] **P1 — Connect experimental detail across parent-cell edges.**
  Shared deterministic edge modes replace isolated cell-interior stamps. Fixed
  terrain slopes weight horizontal/vertical contributions; adjacent cell budgets
  and protections agree. A one-cell support halo counts against the unchanged
  4096-cell limit, and the temporary probe bank is included in admission.
  [Paired measurements](docs/research/2026-09-23-shared-edge-detail.md) cover three
  public projects, three seeds and 65/129/257 outputs: exact nodes/overlaps,
  cell means, final Float32 edge secants and coarse spectral power. Shared edges
  carry detail; there is no old-formula compatibility path. See
  [ADR-0068](docs/adr/0068-share-terrain-detail-across-edges.md).
- [ ] **P0 — Complete parent/child and neighboring-window acceptance.**
  Remove remaining grid direction with oblique, terrain-character-aware support;
  set acceptance tolerances for coarse spectral leakage and final Float32 slopes
  across more physical scales and seeds, including a scale-dependent amplitude/
  slope budget for small parent cells. Preserve the prepared reference and
  density-independent moments/protections. Define transitions to the unchanged
  parent for both whole-cell and partial-cell views: shared-edge detail no longer
  returns to zero at every parent-cell boundary. Cover oblique boundaries and
  extreme detail scales. Fixed probes do not certify unseen extrema; observed
  violations reject a request. R34 remains open.
- [x] **P1 — Reuse fixed detail-cell preparation under a bounded budget.** Each
  prepared detail context now retains at most 4,096 scalar protection/amplitude/
  terrain-direction/moment records with least-recently-used eviction, explicit
  clearing and an uncached control. Overlap, refinement, eviction and retry preserve numeric
  results, evidence and artifacts exactly. See
  [ADR-0062](docs/adr/0062-reuse-bounded-detail-cell-support.md) and the
  [measurements](docs/research/2026-09-23-detail-cell-reuse.md).
- [x] **P1 — Reuse verified parents and bounded numeric results in sessions.**
  A serial application session owns one loaded/prepared parent, one detail context
  and at most 32 numeric results under an explicit byte budget. Every write checks
  parent/runtime freshness; changed identities close the session. Cache keys bind
  aligned requests and detail settings; artifact bounds remain caller-specific.
  Clearing and close release retained work. See
  [ADR-0063](docs/adr/0063-reuse-verified-parent-region-sessions.md).
- [x] **P1 — Cancel regional requests without losing reusable parent work.**
  One-way tokens stop at preparation/sampling/export checkpoints; cancelled
  numeric work cannot become a cached result or a completed artifact. Valid
  completed results can be retried to a new destination, with fresh source/runtime
  checks. See [ADR-0064](docs/adr/0064-cancel-generation-at-safe-checkpoints.md).
- [x] **P1 — Admit saved-parent jobs against shared memory estimates.** Default
  sessions share 1024 MiB of estimated capacity, charging staged parent decoding,
  loaded/prepared arrays, complete-source geometry allowances, cache capacity and
  active sampling/rendering. Reject before expensive work, release on all exits,
  and preserve valid reusable work. Bounded file reads avoid allocating the product
  safety ceiling; detail protection queries batch all intersections without
  dropping features. See [ADR-0065](docs/adr/0065-admit-regional-memory-estimates.md).
- [x] **P1 — Bound ground-rendering scratch and regional comparison canvases.**
  Tile both ground styles with exact gradient halos; keep native scientific and
  numeric outputs. Cap review-only comparison panels at 1024 per side, retaining
  native difference extrema and explicit preview metadata. Close owned pixel
  buffers and check saved-parent cancellation between tiles. Thin-region detail
  peaks fell from 1078 to 157 MiB in the public stress case; see
  [ADR-0066](docs/adr/0066-bound-terrain-rendering-scratch.md) and the
  [measurements](docs/research/2026-09-23-bounded-terrain-rendering.md).
- [x] **P1 — Bound water-colouring scratch and release editor image owners.**
  Native water composition now uses 256-square tiles without a full water overlay;
  one-shot rendering reuses its owned ground image. Preserve exact display pixels
  and current visibility thresholds. Close old ground, water and diagnostic caches
  on replacement/reset/shutdown; release viewport images after Tk transfer and
  keep the old view/legend on failed style changes. Synthetic 4096 composition
  peaks fell from 639 to 257 MiB. See
  [ADR-0067](docs/adr/0067-own-preview-images-and-tile-water.md) and the
  [measurements](docs/research/2026-09-23-preview-image-ownership.md).
- [ ] **P1 — Finish total local-generation memory calibration and ownership.**
  Shared admission is implemented for saved-parent application jobs, not an OS
  memory cap. The [rendering follow-up](docs/research/2026-09-23-bounded-terrain-rendering.md)
  adds near-limit square/thin requests and a 4096-longest-side public parent.
  Extend to maximum node counts, dense/overlapping geometry, simultaneous jobs,
  decoder expansion and long sessions. Include editor images,
  whole-map jobs and unrelated retained work before adding a viewport scheduler.
  Recursive enrichment is not implemented.
- [ ] **P1 — Preserve hydrological context during local enrichment.** Keep
  authored constraints and inherited upstream flow; a local rectangle or halo
  must not invent an independent catchment. Validate drainage after detail and
  constraint/parent consistency corrections.
- [ ] **P1 — Connect zoom to regional generation requests.** Keep navigation
  responsive and distinguish image magnification, denser field sampling and
  newly generated detail. Define automatic thresholds or an explicit generate
  action, result freshness and total memory budgets before wiring jobs.
  Cooperative cancellation, verified serial sessions and saved-parent admission
  estimates now supply foundations; application-wide memory calibration remains.
  No viewport scheduler or recursive enrichment is implemented.

- [x] **P1 — Make sampled lake visibility follow display scale.** Classify
  each connected wet pool independently; hide pools at or below 9 output pixels
  squared and fade to full opacity at 36. Cache whole-pool areas before viewport
  clipping; retain small pools in numeric water and show ground sample spacing.
  Scientific ground, authored instructions and diagnostic overlays remain
  complete. Native-size PNG exports use the same rule independently of zoom.
  See [ADR-0057](docs/adr/0057-display-water-at-the-appropriate-scale.md).
- [ ] **P1 — Couple small-river visibility to local generation.** Distant views
  should show only major water bodies and accepted trunk rivers. Define physical
  width/runoff or explicitly ranked size evidence, screen-size thresholds and
  connected network selection. Smaller rivers require finer local terrain and
  hydrology, inherited upstream flow/outlets, parent/neighbor consistency and
  explicit ready/insufficient-detail status; enlarged coarse pixels do not
  qualify. Preserve whole-lake identity/importance across cropped child results.
  Test overview-to-local transitions, tributary joins, repeat visits and request
  order without modifying completed terrain. Current blue/red D8 and teal
  outflow lines remain all-scale diagnostics, not this cartographic river layer.

### Project portability

- [ ] **P2 — Evaluate a portable project bundle.** A bundle could package the
  JSON and authored source assets while retaining readable hashes; plain JSON
  plus relative files remains the default until portability justifies it.
- [ ] **P2 — Expose the engine through a hosted interface.** Keep local use
  complete and put job management, limits, authentication, and storage outside
  the deterministic engine.
- [ ] **P1 — Select a public project license before distribution.** Recheck the
  licenses and distribution implications of every optional scientific engine
  included in a hosted or downloadable build.

### Potential separate feature

Direct sculpting or manual patching of completed maps could belong in a
separate module or program. This is a possibility only, with no implementation
plan or dependency on the active input editor.

### World context, climate and environmental layers

[World-context plan and WC0-WC6](docs/strategy/world-context.md) now bring source-world
contracts and provisional context forward. Coupled climate/runoff follows rough
terrain acceptance; ecological interpretations remain downstream. R49 owns the
workflow, with shared numeric responsibilities in R01/R02/R07/R10/R11/R15/R33/R34.

- [x] **P0 — Preserve full-world import and continent identities.** World source
  snapshots retain SVG groups/IDs, islands, holes and explicit frame/radius.
  Derived wrapped views validate physical overlap without dissolving ownership.
  Continents are not connected components, plates or watersheds.
- [ ] **P1 — Extend world-source usability after measured need.** Checkpoint/cancel
  long imports, profile dense curved coastlines and decide whether incomplete
  mapping drafts need a separate format. The current world save requires valid
  geography and complete assignments. Regional extraction waits for metric
  projection/context contracts; never feed spherical page coordinates to erosion.
- [ ] **P1 — Generate inspectable ocean and geological context.** Record connected
  water, gateways, upwind exposure, shelf/basin hypotheses and province histories.
  Keep bathymetry separate from effective mixed-layer depth and ocean heat transport.
- [ ] **P1 — Define shared climate and epoch forcing.** Inputs include orbital,
  rotational and atmospheric assumptions, rough relief, ocean scenarios and
  authored overrides. Outputs need seasonal units, validity, budgets, provenance
  and uncertainty. Fixed modern geography is an explicit historical assumption.
- [ ] **P1 — Prototype deterministic continuous climate fields.** Compare seasonal
  temperature, precipitation, coastal moderation, continentality, rain shadows,
  potential/actual evapotranspiration, aridity and runoff before named zones.
  Re-evaluate them after rough mountains; cap feedback and report nonconvergence.
- [ ] **P1 — Author climate-region guidance before generation.** Once consumed by
  a backend, let the user specify intended aridity/desert areas over the previous
  map, with conflicts and uncertainty visible. Do not expose a no-op paint tool.
- [ ] **P0 — Preserve world-to-region consistency.** Share one parent revision,
  global present, history and boundary forcing. Changes to macro relief or gateways
  can invalidate distant climates. Local aging must not replay time twice.
- [ ] **P2 — Add versioned climate-zone classification views.** Derive familiar
  Köppen–Geiger-like and ecological Holdridge-like views from continuous fields;
  keep thresholds, limitations and classification-version metadata explicit.
- [ ] **P2 — Generate biome suitability and display classes.** Use climate,
  elevation, growing season, slope, aspect, wetness, substrate and authored
  exceptions, preserving fuzzy transitions or confidence.
- [ ] **P2 — Generate separate overlapping environmental layers.** Bogs/wetlands
  are hydrology/ecosystem results, plains are landforms, tundra is a biome and
  fields are cultural land use. Forest, desert, marsh, fen, floodplain, alpine and
  coastal types belong only in layers with the corresponding semantics.
- [ ] **Research — Compare optional world engines when a specific gap warrants it.**
  Climlab supplies energy controls; GPlates/GPlately need specified plate histories;
  ExoPlaSim is an external full-climate comparator. Evaluate reduced ocean heat
  transport, GEOCLIM7, Isca/ROCKE-3D, alternate spherical meshes or learned
  surrogates only behind their own data, license, cost and validation gates.

## Algorithm and result improvements

The [2026-09-03 algorithm research](docs/research/2026-09-03-terrain-algorithm-options.md)
proposed a measurement harness and solver/process comparisons. The harness and
substantial drainage work are now implemented. RBF/Poisson replacement and
landscape-evolution experiments remain candidates; the current strategy owns
execution order.

### Constraint-conditioned base surface

- [ ] **P0 — Create a quantitative terrain-quality fixture suite.** Include a
  range with two peaks and a pass, a branching mountain system, a high-altitude
  valley, a broad lowland river valley, an escarpment, and multiple output
  resolutions of the same inputs. Record expected invariants rather than
  subjective image snapshots alone. The two-peak/one-pass ridge, connected-structure junction,
  and authored branch-root fixtures are complete; full branch topology and
  statistics and the other landform fixtures remain. Batch A adds paired physical-
  scale views and rotated oblique-valley/flat/coastal controls. Reuse the existing
  harness; freeze cases, seeds, tolerances and coverage before tuning candidates.
  The new [profile baseline](docs/research/2026-09-24-progress-and-generation-strategy.md#current-drainage-evidence)
  exposes between-node rises that endpoint checks miss.
- [ ] **Research — Compare surface solvers for the low-frequency base.** Test
  the current smooth-response model against feature-curve diffusion/Poisson
  solving, radial-basis interpolation, and hydrologically conditioned
  interpolation. Compare constraint error, slope continuity, runtime, and
  nested-resolution behavior before replacing the current model. The first
  spike should compare deterministic local RBF and sparse screened-Poisson
  correction stages; use ANUDEM as a behavior and diagnostic reference rather
  than attempting a full clone.
- [ ] **P0 — Separate hard constraints, soft guidance, and inequalities in the
  solver contract.** Exact spot heights and water levels must remain exact;
  ridge minima, valley maxima, relative displacement, and brush guidance should
  retain their different meanings. The overlapping absolute-point defect
  exposed by parent-preservation research is fixed separately below; a complete
  mixed-constraint solver and its conflict diagnostics remain open.
- [x] **P0 — Preserve overlapping absolute height points.** Interpolating
  target shares now keep every point exact and make nearby terrain converge to
  it. Conflicting coincident targets and nonzero sea-level-boundary targets fail
  before routing. The public lake fixture's 250 m point is now 250 m; its former
  331.149811 m value came from point averaging, not basin precedence. See
  [ADR-0060](docs/adr/0060-interpolate-overlapping-height-points.md) and
  [the measurements](docs/research/2026-09-23-exact-height-points.md).
- [ ] **P1 — Make transitions aware of surrounding terrain.** Estimate the
  stable low-frequency reference surface entering a stage, then adapt shoulder
  reach and blending to local slope and relief without using an order-dependent
  moving neighbourhood.
- [ ] **P1 — Add terrain-character-aware residual detail.** Control spectral
  slope, anisotropy, roughness, and amplitude by region so plains, plateaus,
  rolling hills and mountain belts do not share one texture. The first four
  regional recipes already vary detail and mountain orientation. Experimental
  local detail now weights horizontal/vertical modes using fixed terrain slopes;
  oblique orientation, exposed spectral targets and suitability controls remain open.
- [ ] **P1 — Preserve authored constraints after every optional process stage.**
  Reproject or solve back to hard constraints after erosion/diffusion and report
  the remaining residual for soft constraints.

### Mountain systems, ridges, and passes

- [x] **P0 — Solve a continuous longitudinal ridge profile.** Interpolate
  authored peaks and passes along arc length, enforce minimum crests where
  requested, and avoid circular point stamps or abrupt changes at vertices.
  Absolute point anchors on absolute structures now use a shape-preserving
  cubic profile with controlled shoulders.
- [ ] **P0 — Generalize passes beyond absolute structure anchors.** An attached
  absolute point now forms a validated geometric saddle, lower along the ridge
  and higher across it. Relative points now shape the relief/depth profile of
  the uniquely nearest relative ridge or valley. Explicit crossing direction,
  mixed-mode attachment, and the dedicated pass constraint remain.
- [ ] **P1 — Vary ridge width and cross-section continuously.** Support broad
  old ranges, narrow alpine crests, rounded ridges, sharp crests, asymmetric
  escarpments, and smooth transitions between authored vertex values.
- [ ] **P1 — Add hierarchical ridge branching.** Generate secondary ridges and
  spurs from an authored main divide with deterministic branch identity,
  decreasing scale, plausible junction angles, and no isolated mountain blobs.
  Authored compatible ridge and valley segments now retain full width where
  their endpoints join; explicit parent/child topology and generated branches
  remain.
- [ ] **P1 — Correlate detail along and across structures differently.** Use
  anisotropic fields so ridge grain follows the range rather than cutting across
  it as isotropic noise.
- [ ] **P2 — Add optional geological provinces and uplift fields.** Use faults,
  plate-boundary-like guides, domes, basins, or directional compression as
  simplified causes of broad relief; label the result process-informed rather
  than tectonically simulated unless a stronger model is implemented.
- [ ] **Research — Evaluate diffusion-based feature-curve terrain fitting.**
  The approach in the feature-based terrain research may provide smoother
  networks and explicit slope control, but must be tested for determinism,
  coastline boundaries, exact anchors, and output-resolution consistency. Start
  with a regular-grid sparse solve and postpone multigrid until measurements justify
  the added implementation complexity.

### Valleys, rivers, and hydrology

- [x] **P0 — Give valleys a downstream longitudinal profile.** Enforce
  non-increasing flow toward an outlet except where an authored lake or basin
  permits otherwise; let high-terrain valleys remain high while retaining
  relative incision. Valleys are now ordered head-to-outlet and use a stable
  pre-valley metric reference profile plus downstream-only floor correction. Authored
  lake/dry-basin retention limits automatic cuts only; explicit valley floors
  still apply inside those footprints. Water-aware valley exceptions remain open.
- [x] **P1 — Reduce reconstruction creases in generated valleys.** Shared
  bounded cubic derivatives now reconstruct incision and detail suppression
  between unchanged routing nodes. Existing cut ceilings and retention remain
  authoritative. [ADR-0050](docs/adr/0050-reconstruct-valleys-with-bounded-cubics.md)
  and the [measurements](docs/research/2026-09-16-bounded-valley-reconstruction.md)
  record improvement, cost and remaining D8/cap artifacts.
- [x] **P1 — Connect diagonal valley shaping between samples.** Compact,
  metric corrections now connect incision and suppression along selected D8
  diagonals while preserving cell edges, canonical nodes and cut ceilings.
  [ADR-0051](docs/adr/0051-connect-diagonal-valley-shaping.md) and the
  [comparison](docs/research/2026-09-16-connected-diagonal-valleys.md) record
  reduced scalloping and climb size, including additional dense checks.
- [x] **P1 — Fit channel cuts to the sampled source.** Classification found
  source humps, artificial cut pits and large cap-limited mountain crests.
  Cardinal/diagonal corridors now adjust cuts toward canonical floor targets
  using the actual macro height and retained detail, within unchanged cut
  ceilings. [ADR-0052](docs/adr/0052-fit-channel-cuts-to-sampled-terrain.md) and the
  [measurements](docs/research/2026-09-16-source-aware-channel-floors.md) record
  profile, canonical-authority, visual and performance checks.
- [x] **P1 — Observe hidden mountain crests before routing.** Shared regional
  carrier signs now select bounded interior probes. Priority-Flood relaxes
  alternate passes, and both D8 and MFD respect the same sampled barriers.
  Regional/global cut-budget policy remains unchanged; routing and its derived
  shaping can change. [ADR-0053](docs/adr/0053-observe-mountain-crests-in-drainage.md)
  and the [comparison](docs/research/2026-09-16-mountain-crest-routing.md) record
  rejected local swaps, exhaustive-probe cost and the adopted targeted method.
- [x] **P1 — Reduce crest-aware routing overhead and bound region storage.**
  Ordered D8 array sweeps, shared metric/scalar work and streamed regional
  candidate masks preserve numeric outputs. The [comparison](docs/research/2026-09-17-drainage-routing-cost.md)
  records 8-28% faster generation on ten case/seed pairs and an 83.7% reduction
  in observed peak allocation at 128 overlapping regions. Full many-region
  builds and larger grids remain performance work; see R46 below.
- [x] **P1 — Refine observed mountain-crest positions.** Source-scale screening
  now admits same-sign endpoints; bounded carrier searches target observed
  crossings and tangent approaches before full macro evaluation. Shared regular
  probes remain, with streamed regions and bounded batches. The
  [comparison](docs/research/2026-09-17-refined-mountain-crests.md) records fewer
  underestimated barriers, mixed finished-channel outcomes and added cost;
  [ADR-0054](docs/adr/0054-refine-observed-mountain-crests.md) owns the policy.
- [x] **P1 — Avoid extra channel dips around unattainable floors.** Seventeen
  source/ceiling observations per eligible segment now carry obstacles upstream
  and unfillable pits downstream. Sparse cubic targets preserve canonical pins,
  routing, cut ceilings and authored authority. At that implementation revision,
  the diagnosed seed-7 climb fell to approximately 50.93 m; see
  [ADR-0055](docs/adr/0055-prepare-attainable-channel-floor-profiles.md) and the
  [comparison](docs/research/2026-09-17-attainable-channel-floors.md).
- [x] **P1 — Condition network floors in both directions.** Propagate downstream
  cut limits through tributaries before adjusting receivers; recover unnecessary
  upstream excavation within source bounds. Routing and cut ceilings stay fixed,
  while generated nodal cuts can change. Compare large-climb reductions and new
  smaller rises with severity counts; see
  [ADR-0056](docs/adr/0056-condition-network-floors-in-both-directions.md) and the
  [comparison](docs/research/2026-09-17-network-floor-conditioning.md).
- [ ] **P1 — Complete between-node channel geometry.** Extend observation to
  unresolved sub-probe extrema, other recipes, authored features and blended-field
  maxima. Define explicit source-scale/process-grid contracts beyond the current
  bounded finite carrier search. Couple nodal and interior floor decisions
  and smooth D8 turns; separate remaining cap-limited barriers, source pits,
  endpoint tapers and retention boundaries. Preserve divides, anchors and budget
  policy. After the fixed-band change, seed-7 edge 9958 -> 9702 requires about
  133.9 m of ascent with its current pins and cut ceiling; even releasing the
  complete upstream cut leaves a sampled 12.95 m obstruction. See the
  [current measurement](docs/research/2026-09-22-stable-detail-band-amplitudes.md).
  Compare joint nodal/interior and whole-path alternatives instead of exceeding
  the cap. Segment envelopes do not condition across fixed canonical
  pins. The nodal network correction can introduce new interior rises, so measure
  full profiles and individual regressions. Compare breach/reroute candidates
  using complete path depth/length, source limits and retained basin boundaries;
  preserve authored anchors. Finite profiles do not certify rivers.
- [ ] **P1 — Add variable valley cross-sections.** Support narrow V-shaped
  valleys, glacial U-shaped valleys, broad floodplains, terraces, and smooth
  width/depth changes along a line. Generated fluvial valleys now widen and
  smooth downstream with drainage hierarchy. A high-order, low-weight MFD
  convergence correction now reduces D8 cross-section gaps without cutting
  across a synthetic drainage divide. The generated D8 tree now carries
  Horton-Strahler order, but measured regressions rejected using it as a direct
  width or depth control without valley character or confinement; authored
  per-vertex shape, glacial forms, floodplains, and terraces remain.
- [x] **P0 — Derive canonical drainage direction and flow accumulation.**
  Priority-Flood, MFD accumulation and a complementary D8 tree drive automatic
  valleys; initiation, downstream closure, Strahler order and bounded floor/
  steepness corrections have numeric fixtures. Builds retain basin labels,
  topology and finished-field conflicts on the same 257-node review grid.
  Authored lake/dry intent absorbs area and eligible outlets transfer it.
- [ ] **P1 — Complete physical drainage policy and river products.** Define
  nested depressions, controlling sills, ocean semantics and constrained repair;
  add exportable river/catchment vectors and regional density/runoff controls.
  Global authored density and in-memory connected reaches are implemented;
  scale-aware diagnostic display does not establish real river water or widths.
  Canonical topology and sampled outlet clearance do not certify every river
  or every point of the delivered surface.
- [ ] **P1 — Reconcile authored rivers with generated drainage.** Rivers should
  descend to a valid outlet and occupy a local valley; report conflicts rather
  than silently moving an authored route.
- [ ] **P1 — Validate basins, outlets, and drainage connectivity.** Detect
  unintended inland sinks, uphill river segments, disconnected channels, and
  coastline outlets that fail to reach sea level. A resolution-independent
  257-node shared routing/review grid reports strict-D8 boundary connectivity,
  potential sinks, fill depth/volume and largest catchment without changing terrain.
  Significant fill components now retain extent labels and representative
  exit/spill/terminal routes, plus raster exterior/enclosed-water boundary context. Authored lake/dry classification, finer outlet/link profiles and
  conservative area transfer are implemented. A full nested depression
  hierarchy and physical river validation remain.
- [ ] **Research — Compare a mature hydrology adapter with selected in-project
  primitives.** Candidates already considered include ANUDEM-style
  hydrological conditioning and established GIS flow/depression tooling. Keep
  optional engines behind adapters and measure Python 3.14/platform support,
  determinism, license implications, and resolution sensitivity. The dated source
  audit shortlisted Landlab; the isolated evolution reference now runs its
  D8/depression components and records a discharge-precision correction. Product
  hydrology adoption and authored-basin comparisons remain open. GRASS and Whitebox remain
  external comparison tools with explicit license/version boundaries.

### Landscape processes and validation

- [ ] **Research — Prototype deterministic hydraulic or stream-power erosion.**
  Start with an optional generation stage that respects fixed coastline and
  elevation anchors; reject it if it merely adds noisy gullies or makes results
  resolution-dependent. Prefer stream-power incision plus explicit flow
  routing over a visual particle or droplet erosion filter. The first bounded
  area-and-slope incision proxy is implemented for automatic broad valleys;
  time-stepped stream power, hillslope flux and analytic convergence controls now
  run in the isolated reference. Whole-landscape resolution sensitivity and
  authoring-safe product integration remain open.
- [ ] **Research — Prototype thermal erosion/talus relaxation.** Use it only
  where material and slope assumptions are explicit, and verify that it does
  not erase authored passes, ridges, or valley floors.
- [ ] **P2 — Add simplified lithology/erosion-resistance fields.** Let rock
  resistance influence valley density, escarpment retention, and slope limits
  without pretending to reconstruct full geological history.
- [ ] **P1 — Add measurable result diagnostics.** Report constraint residuals,
  slope and curvature distributions, hypsometry, coastline correctness,
  drainage statistics, and the fraction of terrain clipped by elevation bounds.
  The first compact drainage summary now travels with generated terrain and PNG
  metadata. Internal generated-channel results now also report total and
  steepness-only floor corrections, excessive normalized-steepness ratios, and
  unresolved uphill edges. Durable build diagnostics include elevation min/max/mean/deviation and
  masked X/Y directional measurements. Full constraint residuals, slope/curvature
  distributions, clipping fractions, hypsometry and profile statistics remain open.
- [ ] **P1 — Add explicit prominence and saddle analysis.** Keep this derived
  measurement separate from the current relative-relief controls.
- [x] **P0 — Record algorithm and stage identifiers in each build.** Record
  generator, noise, automatic-valley and diagnostic IDs plus source hashes.
  Deliberate improvements may change outputs; update identifiers and tests.
- [x] **P0 — Preserve hashed SVG inputs across Git checkouts.** Explicit LF
  attributes keep public project coastline hashes valid on Windows. Regression
  tests load every example after real Git checkout conversion with automatic
  line-ending conversion enabled and disabled.
- [x] **P0 — Derive stable named seeds.** All generation uses
  `named-stage-sha256@1` with `terrain.relief` and `terrain.landforms`. Macro/full detail stay
  views of one relief field. Portable reference values and current generation
  checks exercise the [seed contract](docs/terrain-seeds.md).
- [x] **P0 — Remove early-development compatibility overhead.** Removed the
  original seed mode, policy selector, old-save loaders, four superseded
  schemas, duplicate example and dual-version tests. Only current project/build
  formats are supported. Keep obsolete code in Git history, not active support paths.
- [ ] **P0 — Profile memory and runtime by stage.** Establish repeatable draft,
  regional and maximum-resolution benchmarks with simple and complex coasts,
  authored constraints and multiple seeds. Separate generation, rendering,
  diagnostics, I/O, startup and peak memory; distinguish native calls from
  Python loops. The first public-example timing/profile is recorded in the
  [language assessment](docs/research/2026-09-05-language-and-performance.md);
  it predates the representative harness and native peak-memory measurements.
  The [repeatable harness](benchmarks/README.md) now offers 13 default cases and
  three opt-in lake/constraint scaling cases, selectable seeds/resolutions,
  generation stages, CPU time, quality,
  rendering, process peak memory and numerical hashes in isolated repetitions.
  The [2026-09-10 review](docs/maintenance/2026-09-10-sanity-and-performance.md)
  adds regional landforms, retained routing identities and CPU profiles. The
  [dry-path follow-up](docs/research/2026-09-11-dry-collection-paths.md) measures
  the newer connected-water workload; older coast profiles are not current
  end-to-end cost estimates.
  The [guide-bounds comparison](docs/research/2026-09-13-water-guide-bounds.md)
  adds larger lake/constraint scenes and separates forecast planning from
  generation and evidence serialization. The
  [rendering follow-up](docs/research/2026-09-23-bounded-terrain-rendering.md)
  adds a 4096-longest-side public build and larger saved-parent exports.
  Broader end-to-end export timings, maximum-resolution terrain/constraint mixes
  and agreed latency/memory budgets remain.
- [ ] **P1 — Optimize measured boundary-distance cost.** Prototype indexed
  coast-segment distance queries on complex coasts before a native rewrite;
  the prior simple-coast STRtree probe was slower. Preserve exact masks,
  shared samples, numeric hashes and routing products. Compare simple coasts,
  islands, holes and many authored regions; retain peak memory evidence.
- [ ] **P1 — Calibrate aggregate preview and preparation memory.** Ground and
  water-colouring scratch are tiled; native water composition avoids full overlays;
  editor/headless image lifetimes now have explicit cleanup. Complete-source wet
  component polygonization/rasterization, retained native/viewport images, complex
  diagnostic construction and old-reference/new-worker coexistence still need
  representative whole-application measurements and admission policy. The isolated
  display benchmark does not establish a total desktop budget.
- [ ] **P1 — Split growing modules along the next feature boundaries.** Extract
  structure-profile preparation from generation and workbench controls/drawing
  as those features change. Basin/conflict diagnostics are now extracted;
  keep typed values and one owner per operation.

### Realism research register — 2026-09-04

These additions extend the existing region, hydrology, and
diagnostic items. They are possible improvements, not a commitment to implement
every process. `R01`–`R33` are stable references into the
[landform-diversity research](docs/research/2026-09-04-terrain-realism-and-landform-diversity.md),
which records primary sources, tool boundaries, and proposed experiments.
The [prototype-contract follow-up](docs/research/2026-09-04-terrain-prototype-contracts.md)
refines those items with local measurements and source audits, and adds
`R34`–`R39`. All IDs remain stable; source inspection is not runtime validation.
The [geological-composition follow-up](docs/research/2026-09-05-geological-structure-and-terrain-composition.md)
adds `R40`–`R44` and refines geological, graph and measurement requirements.
The [language and performance assessment](docs/research/2026-09-05-language-and-performance.md)
adds `R45`–`R47` and brings stage profiling forward before a language migration.
Priorities remain conditional on the current strategy's prerequisites.

#### Coordinate, scale, and drainage contracts

- [ ] **P0 — R01: Preserve source-world georeferencing.** Extend the local
  longest-dimension model with source origin, planetary model, projection and
  regional working CRS. Check ground-distance distortion and a world/region
  round trip. A metric label alone must not imply geographic accuracy.
  The [shared coordinate contract](docs/terrain-coordinates.md) now preserves
  source/local inverse conversion and explicit grid extents. WC0 adds a separate
  full-world frame/radius, spherical conversion and seam/area controls. Regional
  working projections, distortion checks and world-bound terrain exports remain open.
- [ ] **P0 — R02: Expose effective process and diagnostic spacing.** Record the
  shared 257-sample routing/diagnostic grid in the build report;
  flag landforms too small to resolve. Define versioned process resolution
  independently of PNG pixels and test small-island/coastal-channel coverage.
  Local build manifests now expose actual routing, diagnostic and output grid
  spacing. Feature-resolution warnings and a public process-resolution control
  remain unfinished.
- [ ] **Research — R03: Define point samples versus cell averages.** Choose
  raster registration, integration/resampling, and anti-aliasing policy. Test
  coordinate round trips and cell integration separately from existing
  bit-identical shared-point tests; do not silently weaken those tests.
  For endpoint-node grids test `2*(N-1)+1` sampling, not doubled node counts;
  shared-node equality does not imply equal coarse-cell averages.
  Endpoint registration, interval-based grid subdivision, axis-specific spacing
  and current stage shape rounding now have a shared domain implementation and
  numerical tests. Cell averages and resampling remain open.
- [x] **P0 — R04: Route on currently authored macro geography.** Brush, ridge,
  point and prepared valley constraints now participate in canonical routing.
  Relative valley profiles use a stable pre-incision reference, with one
  planning pass and existing final constraint precedence. Lake levels and dry
  retention intent are implemented; explicit river/divide entities remain open.
  See ADR-0029 and the [water contract](docs/terrain-water.md).
- [x] **P1 — R05: Retain inspectable drainage topology.** Builds retain source
  and filled routing DEMs, final-field samples, D8 receivers, MFD accumulation,
  stream order, channels, heads and outlets with coordinates, mask and hashes.
  Same-grid receiver differences and uphill edges are reported; the workbench
  overlay and headless review image expose planned channel conflicts.
- [ ] **P1 — Reconcile remaining planned/final channel conflicts.** Quantify
  hard-anchor conflicts separately from residual-detail and depression effects.
  Compare matched directed edges separately from changed channel selection:
  [the exact-point fix](docs/research/2026-09-23-exact-height-points.md) produces
  both a Float32 threshold crossing and newly selected edges with reduced rises.
  Preserve authored intent; do not treat filled routes as validated rivers.
  ADR-0029 recorded 390 uphill edges among 2455 planned channel edges
  (maximum rise 135.07 m) for its seed-42 authored baseline. Re-measure the
  current fixture before comparing changes; that result is not acceptance.
- [ ] **P1 — R06: Separate coastline height from coastal terrain character.**
  Compare regional coastal plains, steep mountain coasts, cliff approaches and
  plateau margins with the uniform exponential rise. Keep the authored shore
  fixed and test estuary/outlet continuity. Shelf/bathymetry work depends on R07.
- [ ] **Research — R07: Support below-sea-level terrain deliberately.** Separate
  land mask, bed elevation, water surface and sea datum before allowing dry
  inland depressions, overdeepened lake beds or bathymetry. Audit all zero
  clipping; test inland isolation, ocean connection and nodata semantics.

#### Regional composition and authoring

- [ ] **P1 — R08: Control regional height distributions.** Add soft targets for
  lowland fraction, plateau height, local relief and peak density to the
  terrain-character design. Compare equal-height-ceiling regions, and reject
  global histogram remapping that alters hard anchors or drainage.
- [ ] **Research — R09: Couple ridge and drainage skeletons.** Generate spurs
  between tributaries, preserve divides and saddle connections, and measure
  network crossings, orphan peaks, junction angles and branch scale. Build on
  authored structure profiles and junctions; generated ridge branching remains open.
  Preserve the distinct surface-ridge, divide, thalweg and channel meanings
  described by R42 rather than assuming the two skeletons are exact duals.
  Batch C compares one connected range-to-lowland system. Use hydrology-led and
  orometric synthesis as references; a completely river-first world generator
  remains a larger alternative if the bounded hybrid fails, not an adopted rewrite.
- [ ] **Research — R10: Add layered substrate to lithology regions.** Evaluate
  resistant caps, bed thickness, dip and differential erodibility for mesas,
  cuestas, escarpments and canyon walls. Distinguish geometry from decorative
  strata colours; keep weathered/mobile cover separate from bedrock.
  Prototype material-coordinate queries at the eroding bedrock surface. Check
  true versus vertical thickness, contact geometry and process-grid support;
  compare effective coarse resistance with resolved regional layers.
- [ ] **Research — R11: Represent regional process histories.** Compare a short
  authored sequence of uplift, incision, deposition and glacial episodes with
  one uniform erosion-age parameter. Record order, units and assumptions;
  label the history a design hypothesis rather than inferred canon.
  LE1/LE2's sequential uplift/incision/hillslope reference and two resistance
  regions now execute, with constant/reversed/ablated controls and a held-out seed. Separate initial conditions, time-varying forcing,
  persistent boundaries and final hard targets; do not silently pin present-day
  heights throughout history. Record corrections and geological work separately.
  Geological histories are pre-generation hypotheses, not output editing.
  LoopStructural/inverse reconstruction remain later references, distinct from
  the immediate forward-evolution experiment.
- [ ] **Research — R12: Prototype contour-guided authoring.** Compare the 2026
  iso-contour approach for plateaus, basin margins and elevation bands. Reject
  crossing/contradictory contours and quantify DEM reconstruction, river-floor
  and hard-anchor errors. Exported contours remain derived products. The
  refreshed 2026 source review finds useful pre-generation controls, but the
  method's river-width/slope limitations keep it outside the first drainage batch.
- [ ] **Research — R13: Prototype skeleton-preserving deformation.** Use the
  2025 vector-terrain work to assess moving/stretching a range while retaining
  internal structure. Preview changes, keep authoring editable, and measure
  geometry, drainage and reconstruction errors before accepting a deformation.

#### Erosion, deposition, and recognizable landforms

- [ ] **Research — R14: Compare analytical erosion with time stepping.** Use
  the 2024 analytical stream-power method as a bounded candidate for fast
  terrain-age control. Test uplift/base-level assumptions, convergence,
  authored anchors and runtime against the current incision baseline. Its 2D
  network/surface coupling still iterates; changing age can relocate valleys and
  deposition is not covered generally. The implemented LE1/LE2 reference measures
  sequential epochs before product integration; analytical erosion is a conditional
  speed/maturity alternative. Test time-step accuracy and knickpoint diffusion,
  not only solver stability. LE3 then enforces authored/shared-path semantics and
  checks drainage after constraint-aware reconstruction.
- [ ] **Research — R15: Evaluate multi-scale erosion amplification.** Compare
  the previously researched MIT reference with current residual detail on a
  generated local mountain/valley window. Preserve the fixed parent, inherited
  inflow and boundary gradients; measure deposition, seams and repeatability.
  Verify runtime, numeric height exchange and fixed-step operation before
  adopting any engine. This is a generation experiment, not an output editor.
- [ ] **Research — R16: Prototype bedrock plus mobile sediment.** Start with a
  Landlab SPACE comparison on a channel opening onto a plain. Track erosion,
  storage, deposition and export; verify nonnegative cover and bounded balance
  error before adding floodplain or alluvial-fan presets.
  The audited large-scale SPACE component needs single-receiver routing;
  start with a D8 reference, explicit discharge units, porosity/control-volume
  accounting and explicit flooded-node behavior rather than passing MFD data.
  LE4 adds closed/dry controls, boundary/fines flux and numerical-refinement
  checks. Upstream prose/source discrepancies require pinned-code tests;
  dependency resolution is not runtime or conservation validation.
- [ ] **Research — R17: Evaluate 2026 stochastic geomorphological transport.**
  Compare resolved regional meanders/fans with a stream-power baseline.
  Distinguish MIT `geotransport` reference code from LGPL/CUDA `soillib`;
  verify Windows/Python runtime, seed ensembles, GPU repeatability, transport
  conservation and resolution behavior before proposing adoption.
  Measure floating-point atomic-reduction variance independently of seed
  repeatability; package metadata alone does not prove runtime compatibility.
- [ ] **Research — R18: Separate catchment trees from channel regimes.** Define
  confined bedrock, alluvial, meandering, braided and delta/distributary
  networks. Relate width to discharge/material/confinement, not Strahler order
  alone. Test connectivity, split/join flux and source-DEM consistency. C1 compares
  layered canyon incision and lateral erosion before broader channel families;
  see the [process reassessment](docs/research/2026-09-25-groundwater-and-terrain-architecture.md).
- [ ] **Research — R19: Generate terraces from explicit events.** Compare
  base-level or uplift episodes with authored terrace benches. Require ordered
  levels, coherent valley continuity and a valid modern outlet; do not terrace
  the entire elevation field by quantization.
- [ ] **Research — R20: Add glacial landform options.** Compare a bounded
  authored U-valley/cirque recipe with the 2023 glacial-erosion reference.
  Include hanging valleys and overdeepened basins only with explicit former
  ice context, water semantics, and sufficient regional resolution.
- [ ] **Research — R21: Add mass-wasting and debris-flow options.** Evaluate
  the 2024 debris-flow work for scars, scree aprons and cones. Verify material
  movement, authored crest/pass preservation and downstream blockage after
  deposition; compare with the existing thermal-relaxation proposal.
- [ ] **Research — R22: Add wind-shaped terrain selectively.** Use the 2024
  wind/sand study to compare dune and lee-deposit recipes or simulations.
  Require wind direction/variability, sand availability and world-unit scale;
  test boundary flux and avoid treating all deserts as sand seas.
- [ ] **Research — R23: Add authored volcanic and impact families.** Evaluate
  cones, shields, calderas, lava plateaus and impact rims as distinct recipes
  with optional weathering. Validate radial profiles, rim continuity,
  surrounding transitions and coast preservation; no automatic canon changes.
- [ ] **Research — R24: Model groundwater and explicit karst connections.**
  First test G1's porous aquifer, recharge, storage and gaining/losing exchange
  against analytic controls; then measure groundwater capture and active stream
  density. Keep hydraulic conductivity/storage distinct from erodibility and
  chemical solubility. K1 later adds an explicit head/capacity-limited connection
  between a losing stream and a spring in suitable substrate, with a combined
  water budget. Surface and subsurface divides can differ. Do not invent conduits
  for accidental raster pits. Dissolution, collapse and 3-D cave geometry are
  separate follow-ups; a DEM cannot contain cave roofs and floors. See the
  [models, tool checks and staged gates](docs/research/2026-09-25-groundwater-and-terrain-architecture.md).

#### Comparison tools, rendering, and scientific limits

- [ ] **P0 — R25: Build an Earth-analogue descriptor atlas.** Use small,
  provenance-recorded USGS 3DEP and optional Copernicus samples at matched
  extent/resolution. Compare relief, curvature, hypsometry, prominence,
  directional spectrum and drainage; use terrain-descriptors/GRASS as
  references. Separate DSM vegetation/buildings from desired terrain texture.
  Batch A starts with a small licensed/provenance-recorded bare-earth set and
  the 2025 descriptor reference. Do not block B on a comprehensive atlas or use
  histogram matching as a substitute for connected landscape structure.
- [ ] **Research — R26: Compare example-based residual synthesis.** Transfer
  selected terrain character from reference patches after fitting broad relief
  and boundaries to authored geography. Measure repeated motifs, seams,
  constraint errors and drainage changes; retain source data rights/hashes.
- [ ] **P0 — R27: Add a reproducible candidate comparison gallery.** Build on
  benchmark fixtures and relief styles with fixed-seed ensembles,
  before/after views, region descriptors and multiple valid alternatives.
  The workbench has no seed/before-after comparison view yet. Keep visual
  interest separate from hard
  validity; adoption is an explicit author choice, not one opaque quality score.
  Pair fixed lighting, elevation colours, extents and physical sampling. Report
  worst cases, unresolved routes and affected catchment coverage alongside
  matched-path ascent/shape; do not improve scores by removing troublesome rivers.
- [ ] **P1 — R28: Compare multiscale and multidirectional relief rendering.**
  Use GDAL hillshade variants and coarse/fine shading at the same DEM and fixed
  elevation colours. Record exaggeration; test rotated ranges, flat areas and
  coasts. Material/snow overlays require their own fields or authored inputs.
- [ ] **Research — R29: Evaluate learned terrain as proposals only.** Compare
  MESA and PlanetDiffusion for regional inspiration or global-context research.
  Audit code/weights/data separately, pin the environment and sample settings,
  preserve the custom planet scale, and validate height/drainage/scale
  after conditioning. Do not replace the local deterministic authoring core.
- [ ] **Research — R30: Define a bounded external-tool comparison adapter.**
  Assess Houdini, Gaea, World Machine, World Creator and HighMap only where
  useful. Exchange numeric heights, extent, datum, masks and settings; detect
  normalization or coast movement. Verify exact component license, automation
  rights and runtime; the dated pyHighMap audit reported Linux-only support; recheck before use.
- [ ] **Research — R31: Benchmark GPU routing/process backends after profiling.**
  Compare FastFlow, compute-shader and CUDA candidates only for a demonstrated
  bottleneck. Record hardware, drivers, precision and repeat-run variance;
  retain an inspectable CPU reference and distinguish numeric tolerances from
  bitwise reproducibility.
- [ ] **P0 — R32: Audit constraint and generation-process corrections together.**
  Extend the measurement harness with per-stage deltas and material accounting.
  Recheck drainage after hard-height restoration or generation stages, and
  report incompatible requirements. Separate intentional basins from numeric
  sinks and canonical-grid checks from exported-surface checks.
- [ ] **Research — R33: Weight runoff before assigning river size.** Define an
  optional authored runoff field and future climate-derived discharge adapter.
  Keep contributing area distinct from water flux. Test wet/dry catchments of
  equal size, seasonal assumptions and upstream boundary flux. WC3 now plans
  shared seasonal climate/runoff before world-informed aging; an authored runoff
  control remains useful without a climate engine. Raw rainfall is not runoff.

#### Prototype findings and additional improvement candidates

- [ ] **Research — R34: Preserve coarse terrain while adding detail.** Fixed
  geometric band budgets now replace count-dependent normalization; the former
  default 2-to-6-band coefficient loss of 28.26% is removed. Regional broad
  carriers and finer texture are separate. The
  [measured comparison](docs/research/2026-09-22-stable-detail-band-amplitudes.md)
  still finds 43-91 m RMS coarse-cell changes across four public fixtures, and
  some drainage regressions. The
  [parent-cell experiment](docs/research/2026-09-23-parent-cell-preservation.md)
  now rejects a bilinear/trapezoidal candidate despite precise node/mean results:
  it loses parent structure and authored heights, depends on output density and
  worsens inherited channels. The verified-parent residual experiment now binds
  the prepared reference and fixed moments. Shared-edge terrain weighting now
  reduces quantized edge slope errors while measuring some increased coarse
  leakage; [the paired evidence](docs/research/2026-09-23-shared-edge-detail.md)
  leaves visual/coarse-power and finer-flow acceptance open. Continue with
  oblique support and physical-scale tolerances; constrain only added residuals
  independently of display sampling and protect authored/water/channel constraints.
  Stable weights or preserved cell means alone do not close R34.
- [ ] **Research — R35: Constrain regional transition gradients.** Match
  province reference levels and budget the extra slope from blending surfaces
  at different heights. Measure slope/curvature across flat, plateau and
  mountain boundaries; smooth blend weights alone do not prevent escarpments.
- [ ] **Research — R36: Stabilize oriented-detail reference fields.** Compare
  ridge-axis and directed-flow orientation, define low-slope confidence and
  fallback, and test saddles, crest reversals and phase seams. Keep the
  reference field independent of preview resolution and tile boundaries.
- [ ] **Research — R37: Gate processes by landform suitability.** Combine
  authored landform, slope/relief, substrate and confinement to select detail
  recipes. The controlled-pattern paper is a mountain-detail candidate with
  explicit plateau/cliff/floodplain limitations. Test masks and transitions;
  expose uncertainty and keep alternate valley/plateau recipes available.
- [ ] **Research — R38: Prove external numeric exchange before comparisons.**
  Round-trip an asymmetric signed metre ramp with nodata, unequal axis spacing
  and explicit registration. Detect normalization, quantization, transposition
  and half-cell shifts. Record engine commit, settings, step counts, scale,
  offset and output identity; visual exports alone cannot validate elevation.
- [ ] **Research — R39: Compare focused meander and delta references.** Evaluate
  Apache-2.0 meanderpy against a bounded authored corridor, and MIT pyDeltaRCM
  against a distributary recipe. Check cutoff semantics, valley confinement,
  inlet/outlet continuity, sediment flux and domain boundaries. Audit material
  assumptions and runtime support; keep coast/river changes reviewable.

#### Geological composition and structural measurements — 2026-09-05

- [ ] **Research — R40: Compose related terrain regions.** Add optional,
  editable relationships between belts, plateau margins, basins, valley
  corridors and receiving plains. Compare coherent recipes with independent
  regional textures; measure cross-sections, transitions and outlet alignment.
  Surface conflicts with authored geography instead of silently relocating it.
- [ ] **Research — R41: Measure directional structure over physical scales.**
  Extend analogue comparisons with directional variograms/spectra, physical
  lag distances, mask support and explicit detrending. Separate orientation
  agreement from rotation-normalized character. Include identical-histogram
  ramp/shuffle fixtures so distribution matching cannot masquerade as realism.
  Local builds now report masked X/Y semivariances and height differences at
  requested 25/100/400 km lags, including effective rounded distances and pair
  counts. Rotation-normalized, arbitrary-angle and detrended comparisons remain.
  Batch A prioritizes controlled oblique valleys, network direction/turn bias and
  scale-specific sinuosity. Real straight valleys should remain straight; visual
  waviness alone is not an acceptance criterion.
- [ ] **Research — R42: Type terrain and drainage graph relationships.** Keep
  authored lines, morphological ridges/thalwegs, divides and active channels
  distinct, with source-surface and depression-policy provenance. Compare
  SurfaceNetwork externally on saddles, dry valleys, flats and outlet basins;
  audit its GPL boundary and hole semantics before reuse.
- [ ] **Research — R43: Retain landform measurements at several scales.**
  Compare GRASS geomorphons and quadratic-fit descriptors at world-unit radii.
  Record thresholds, rounded windows, orientation/curvature conventions and
  support/halo limits. Test local flatness on plateaus versus valley floors,
  rotated fixtures and small coastal islands before driving process masks.
- [ ] **Research — R44: Track significant peaks and passes across stages.**
  Compare persistence and peak/saddle relationships using TTK as a read-only
  reference. Specify metre thresholds, prominence conventions, ties, masks and
  island boundaries. Protect authored passes even when persistence is small;
  distinguish added local detail from unwanted changes to large landmarks.

#### Performance and language migration

- [ ] **Research — R45: Reduce geometry-query work before changing language.**
  Compare exact indexed boundary-segment queries, reusable distance fields and
  avoiding unnecessary off-land samples against the current GEOS calls.
  Key caches by geometry, coordinates and algorithm identity. Any approximate
  distance field needs an explicit error budget, coastline/constraint checks,
  and shared-coordinate tests; never simplify authored geometry silently.
  The first implementation skips ocean samples in the delivered field and
  diagnostic sampling while preserving full canonical routing grids. Exact
  indexed segment queries were slower on the public coastline in a small probe;
  they have not been adopted. Exact feature preparation and per-call water-sample
  reuse and conservative spatial rejection of distant sampling guides are now
  implemented; broader indexing/caching comparisons remain. Guide bounds preserve
  finite sampling policy and do not bound the complete elevation field.
- [ ] **Research — R46: Compare compiled kernels on demonstrated bottlenecks.**
  Start with fused noise evaluation and allocation reduction; test hydrology
  loops when representative profiles justify them. Compare existing NumPy,
  a bounded Numba experiment and an optional Rust proof using identical inputs.
  Include cold/warm latency, memory, transfer costs and complete-generation
  speedup. Verify Python/NumPy/Windows compatibility before installing anything.
  Profiled D8 selection now uses ordered NumPy sweeps, MFD/Priority-Flood reuse
  scalar work, and crest observation streams regional carriers. The current
  [Python optimization](docs/research/2026-09-17-drainage-routing-cost.md) preserves
  numeric products; full many-region builds and larger grids still need scaling
  measurements before selecting another kernel or native-language experiment.
  The 2026-09-24 metadata audit finds matching SciPy/Numba/llvmlite Python 3.14
  Windows wheels; no package was installed or kernel comparison run. Include
  dependency resolution and cold compilation in any future experiment.
- [ ] **Research — R47: Define the evidence gate for a Rust migration.**
  Stabilize units, grids, constraint priority, seeds, stage boundaries and
  numerical tolerances first. Require representative fixtures, an end-to-end
  measured benefit and a tested native-library/Windows packaging path. Explicitly
  choose a temporary Python/Rust bridge or a complete runtime replacement;
  a kernel port does not establish full project, CLI or desktop workflow parity.

#### Shared channel geometry — 2026-09-24

- [ ] **P0 — R48: Generate terrain and channels from the same prepared paths.**
  Compare bounded terrain-guided subgrid paths against D8, retaining coarse
  catchment context, exact junctions, terminals, divides and incision budgets.
  Share geometry across source probes, longitudinal floor fitting, actual DEM
  shaping, diagnostics and rendering; viewport-only smoothing does not qualify.
  Classify whole-route feasibility and compare rerouting, retention and moving
  automatic heads before excessive cuts. Authored contradictions stay visible.
  Use fixed physical station spacing, matched source-to-terminal routes and
  complete-network coverage when segmentation changes. Batch B's acceptance
  targets and measured network-led construction are in the strategy.
  Process spacing remains independent of output pixels. LE2's executable
  co-evolution reference shows chronology response; the frozen triangle comparison
  now removes sampled rises on unchanged nodally descending paths. It retains
  D8 bias and fails general authoring constraints, so use it as a numerical
  control for physical paths and capture/grid analysis. LE3 must meet the same
  final surface/path contract. The network-led fit now preserves hard heights,
  native bounds and downhill guides. Bank/confluence feasibility is now measured:
  endpoint support passes in feasible cases, but intervening rises and capture fail.
  B1 now measures connected patches and bounded automatic guide relocation under
  that fixed control and a separate 600 m / 120 km3 fresh-construction envelope.
  Fresh 250 m raster capture is 4/4 with no sinks or uphill guide routes; hard
  inputs and all original vertices remain fixed. Bank shape and coarse delivery
  still fail. Local banks now pass; T13 preserves them through trusted-field
  reopening and isolates loss when reduced to raster samples. Guarded snapshots
  and same-field query/tiling checks now pass; held-out geometry and real detail
  consistency remain requirements for M5 representation adoption, not a ban on
  M3-M4 history integration. Changing product
  authority needs an ADR and complete consumer changes. Preserve genuine authored
  requirements and distinguish composition from erosion. See the
  [failure register](docs/research/terrain-method-decisions.md) for revisit gates.
  Do not count changed automatic D8 edges as matched route improvements. Remove
  superseded runtime paths after acceptance; preserve current inputs/contracts
  without legacy support.

#### Shared world context — 2026-09-24

- [ ] **P0 — R49: Generate continents from a retained, shared world context.**
  Follow the [WC0-WC6 plan](docs/strategy/world-context.md) for full-world import,
  provisional context, rough terrain, bounded climate/history feedback and an
  immutable world parent. Preserve coastline vectors and semantic identities;
  no independent continent rescaling or automatic plate assignment. Track
  ocean topology/bathymetry and surface heat storage separately. Use continent
  defaults with province overrides and one global present; keep crust age,
  uplift chronology and simulated erosion duration distinct. Regional history
  requires sufficient time-dependent parent boundary/flux, exact shared samples,
  deterministic request order and explicit correction budgets. Add staged input
  review and global invalidation where dependencies cannot yet be bounded.
  Run public spherical/topology, continentality, rain-shadow, water/heat budget,
  old-crust/young-belt and no-double-aging controls before production adoption.
  Existing solutions and optional alternatives are recorded in the
  [source review](docs/research/2026-09-24-world-context-enrichment.md). WC0 source
  handling and its [schema](schemas/world/project-v1.schema.json) are implemented
  without new runtime dependencies. WC1 geographic context and its
  [schema](schemas/world/context-v4.schema.json) now include shore distance,
  directional water/support and separate water-piece incidence using SciPy.
  Separate province inputs and
  [authored bathymetry](docs/world-bathymetry.md) are implemented. M1 binds matching
  geographic context to bounded rough terrain with explicit unsupported fields.
  Climate/runoff, physical forcing, component-aware transport, wider domains and
  WC3-WC6 products/acceptance remain open.

## UI / UX improvements

WC0's source/mapping workspace and WC1 geographic preview/export/reopening and
shared-edge water, water-piece connectivity, shore-distance and exposure measurements are
delivered, together with independent geology and bathymetry input editors.
M1-M4 include the minimum working stage controls, result comparison and failure/
resolution feedback for the integrated experiment. Do not wait for M5 scientific
acceptance to make that workflow testable; retain its experimental label. A control
must have a real backend consumer. Broader editor polish remains deferred.
[ADR-0047](docs/adr/0047-edit-generation-inputs-only.md) defines input editing;
[ADR-0048](docs/adr/0048-keep-zoom-driven-detail-generation.md) keeps local enrichment in scope.
[ADR-0049](docs/adr/0049-navigate-and-save-authored-inputs.md) records navigation,
geometry movement and project-saving behavior.

- [x] **P1 — Scroll long World context summaries in compact windows.** The Context
  details use a read-only scrollable text region; jobs and legends remain visible
  at 1160 x 760. Larger windows expose more details without changing the map.
- [ ] **P1 — Reflow long World source summaries in compact windows.** The separate
  nine-continent source summary below the map can still clip horizontally at
  1160 x 760; bind its wrapping width or give it a bounded scrollable region.

### Editing and navigation

- [x] **P0 — Keep generated terrain as a read-only authoring background.** Input
  edits retain the previous map and its review overlays. Exact worker snapshots
  control current/stale status and PNG export; regeneration uses authored inputs
  only. No brush, area tool or property edit writes into generated heights.

- [x] **P0 — Select and edit generation instructions.** Choose any instruction
  with Select, the list or Ctrl+click on the map. Edit properties with the existing
  controls, Apply, then regenerate. Regions and lake levels/outlet enablement are
  included. White handles identify the selected geometry.
- [x] **P0 — Add instruction undo and redo.** Immutable input history restores
  additions, property edits, movement, deletion and clear-all. Draft vertices
  still use backstep Undo; opening a project/coastline resets history. Generator
  settings and draft redo are outside this completed slice.
- [x] **P0 — Add pan and zoom.** Pointer-anchored wheel zoom, middle/Space drag,
  Fit and toolbar buttons preserve the normalized geographic frame. The view
  exposes visible bounds, km/display-pixel and local cursor coordinates. Brush
  size uses Shift+wheel; strength uses Ctrl+Shift+wheel. Raster allocation stays
  bounded to the canvas and diagnostic layers are cached. Navigation alone adds
  no terrain detail.
- [x] **P1 — Drag instructions and vertices.** Whole-input moves and individual
  handles work across all instruction families. Commit once per completed drag;
  reject off-land, self-crossing or overlapping-basin geometry atomically.
  Closed rings and attached lake outlets follow their moved boundary edges.
- [ ] **P1 — Insert/remove vertices and enter precise coordinates.** Extend the
  implemented dragging with topology-safe vertex insertion/removal and numeric
  local/normalized coordinates.
- [ ] **P1 — Add explicit peak and pass handles along ridge profiles.** Show
  their along-line order, elevation mode, influence length, and saddle or peak
  role. The line-owned profile dialog now edits positions and heights; direct
  handles on the map remain to implement.
- [ ] **P1 — Extend the instruction list into a layers panel.** Selection and
  deletion are implemented. Add names, reorder where order is meaningful,
  per-instruction hide/show, lock and duplication. A global Instructions toggle
  now hides input overlays and suspends painting for unobstructed inspection.

### Feedback and terrain inspection

- [ ] **P1 — Add a fast draft preview after measuring complete draft cost.**
  Debounce edits and regenerate a low-resolution preview in the background while retaining an explicit full-quality
  Generate action. Explicit Quick test (257 px) and Detail (1025 px) resolution
  presets are implemented; these change the saved setting, not a hidden preview.
  Lower output resolution does not reduce fixed canonical routing or all water
  work. Debounce/cancel only after a useful latency budget is demonstrated.
- [x] **P0 — Add stage-aware progress and cancellation.** The workbench shows
  elapsed time, stage and Cancel/Esc status. It retains the previous map, waits
  for worker acknowledgement and rejects cancelled/old queued results. Headless
  application operations check tokens before completion publication. Stops are
  cooperative; individual native operations and file writes have no latency bound.
  See [the guide](docs/terrain-generation-control.md).
- [ ] **P1 — Add switchable inspection overlays.** Include contours, hillshade,
  slope, curvature, influence extents, hard-constraint residuals, drainage,
  catchments and clipped-elevation warnings. Drainage and basin catchment
  toggles are implemented; the other listed overlays remain open.
- [x] **P1 — Show ground elevation under the cursor.** Read the nearest sample
  of the last reference DEM, including water/no-ground status and local x/y km.
  Reference freshness stays visible; water surfaces are not reported as ground.
- [ ] **P0 — Extend terrain inspection for quality comparisons.**
  Add local slope, active constraint contributions and a cross-section through the selected ridge or valley.
  Start with a selected-channel longitudinal profile of actual finished ground,
  cut limits and unresolved intervals, and show effective process spacing.
- [ ] **P1 — Make relative-versus-absolute behavior visible.** Use concise
  tooltips and preview labels that state target height, signed displacement,
  ridge relief, or valley incision in the correct terms.
- [ ] **P0 — Add before/after and seed comparison views (R27).** Compare a changed
  constraint, profile, or seed without relying on memory of the previous image.
- [x] **P2 — Add separate cartographic and scientific elevation styles.** Use
  expressive hypsometric tint and stronger relief for everyday mapping while
  retaining an ordered, colour-vision-deficiency-safe inspection view.
- [ ] **P2 — Add tint-only and hillshade-only display modes.** Keep these as
  derived inspection choices that never change the authoritative DEM.

### Project safety and everyday workflow

- [x] **Collect closed Tk test cycles on their owning thread.** The full
  [head/mouth batch](docs/research/2026-09-26-valley-heads-and-mouths.md) reproduced
  a save-on-close timeout twice, with off-main-thread variable finalization.
  The test protocol now collects released UI cycles after pytest drops fixture
  references; ordinary fixture teardown is too early. Existing deadlines and
  save assertions are unchanged; no application garbage-collection policy is added.
- [ ] **P1 — Audit closed editor ownership and callback retention.** A separate
  shutdown probe retains a closed workbench through Tcl variable traces until
  those traces are removed. Establish deterministic release of callbacks and
  resources at editor/application shutdown, including jobs finishing after close.
  The test-isolation correction does not establish a runtime lifecycle fix.

- [x] **P0 — Track unsaved changes.** A title marker compares authored inputs
  against the saved snapshot, including unfinished instructions. Open/import/close
  offer Save / Discard / Cancel; cancellation, failure or a newer input snapshot
  prevents a save continuation. Navigation/tool defaults alone do not mark dirty.
- [x] **P0 — Add Save, Save As, and keyboard shortcuts.** Save updates the known
  path atomically. Open/save/generate, undo/redo, delete, apply/finish and cancel
  have shortcuts; instruction undo/delete shortcuts leave text entry alone.
  GUI --project opens
  an existing project on startup.
- [ ] **P1 — Add recoverable autosave.** Keep autosave outside the authored
  project, identify recovery state clearly, and never treat recovery data as a
  completed user save.
- [ ] **P1 — Help relink a moved or deliberately changed SVG.** Display the old
  path and hash, preview whether bounds/topology changed, and require explicit
  acceptance before reusing normalized constraints.
- [ ] **P1 — Add recent projects and clear validation summaries.** Surface
  missing inputs, unsupported versions, constraint conflicts, and output paths
  in language useful to a map author.
- [ ] **P1 — Add named tool presets and sensible per-continent defaults.** Keep
  settings separate for every tool and make copying values deliberate.
- [ ] **P2 — Improve keyboard and accessibility support.** Provide focus order,
  non-mouse authoring alternatives where practical, scalable text, sufficient
  contrast, and controls that do not depend on colour alone.
- [ ] **P2 — Prepare a hosted UI without changing the engine contract.** Reuse
  the same project schema and build operation; add upload, job, quota, and
  download UX only at the service boundary.

## Related decisions and research

- [Living terrain method decisions](docs/research/terrain-method-decisions.md)
  records failures, reasons, useful retained work, alternatives and revisit gates.
- [Groundwater, canyons and architecture reassessment — 2026-09-25](docs/research/2026-09-25-groundwater-and-terrain-architecture.md)
  reviews existing models and proposes connected construction, explicit input
  roles, groundwater capture, layered/lateral canyons and bounded karst tests.
  Component APIs were checked; no new solver simulation or product adoption.
- [World-context enrichment — 2026-09-24](docs/research/2026-09-24-world-context-enrichment.md)
  reviews primary geographic, tectonic and climate models, existing tools and
  deployment limits. The [WC0-WC6 plan](docs/strategy/world-context.md) advances
  world inputs/context and specifies shared-time regional history refinement.
- [Valley-bank feasibility — 2026-09-25](docs/research/2026-09-25-valley-bank-feasibility.md)
  records physical support and conflict diagnostics, failed cross-sections/capture
  and the next river-aligned local surface-patch experiment.
- [Constrained network-led terrain — 2026-09-25](docs/research/2026-09-25-constrained-network-surface.md)
  records successful hard constraints but failed actual drainage capture.
- [Coupled physical channel paths — 2026-09-25](docs/research/2026-09-25-physical-channel-paths.md)
- [Frozen terrain/channel reconstruction — 2026-09-24](docs/research/2026-09-24-frozen-channel-reconstruction.md)
  records complete-route profile gains, remaining nodal failures, authoring limits,
  explicit composition volume and base-environment cost on the frozen cohort.
- [Landscape-evolution reference implementation — 2026-09-24](docs/research/2026-09-24-landscape-evolution-reference.md)
  records the executed first batch, isolated command, numerical controls,
  public comparisons and failed product-quality gates.
- [Landscape-evolution models and tools — 2026-09-24](docs/research/2026-09-24-landscape-evolution-models.md)
  compares primary papers and existing engines; records a wheel-only dependency
  probe. The [detailed implementation plan](docs/strategy/landscape-evolution.md)
  owns LE0–LE6, equations, integration boundaries and acceptance/rejection gates.

- [Progress and generation strategy reassessment — 2026-09-24](docs/research/2026-09-24-progress-and-generation-strategy.md)
  records the current eight-case profile baseline, research/tool refresh and
  quality-first batches A–F; adds R48 and refines existing candidate gates.

- [ADR-0025](docs/adr/0025-centralize-local-frames-and-endpoint-grids.md) centralizes
  source/local conversion and endpoint grids while preserving existing terrain.

- [Selective terrain sampling — 2026-09-05](docs/research/2026-09-05-selective-terrain-sampling.md)
  records implemented profiling and ocean-sample elimination, exact numeric
  comparisons, runtime/memory results and the remaining measurement limits.
- [Language and performance — 2026-09-05](docs/research/2026-09-05-language-and-performance.md)
  records generation timings, native geometry/noise bottlenecks, a foundations-
  first recommendation, language tradeoffs and proposed migration gates R45–R47.
- [Geological structure and terrain composition — 2026-09-05](docs/research/2026-09-05-geological-structure-and-terrain-composition.md)
  connects geological controls, network semantics, measured descriptor limits
  and optional structural/topology tools to R40–R44 and existing experiments.
- [Terrain prototype contracts — 2026-09-04](docs/research/2026-09-04-terrain-prototype-contracts.md)
  records measured noise/grid effects, external source audits, R34–R39 and
  historical prototype proposals. The current strategy and ADR-0047 determine
  which proposals remain in product scope.
- [Terrain realism and landform diversity — 2026-09-04](docs/research/2026-09-04-terrain-realism-and-landform-diversity.md)
  connects R01–R33 to code limitations, scientific papers, tool/runtime
  boundaries, real-data comparisons and ordered prototype gates.
- [Current development strategy](docs/strategy/README.md) orders work by
  dependencies and records the evidence gates for adopting evaluated tools.
- [Technology and world systems — 2026-09-04](docs/research/2026-09-04-technology-and-world-systems.md)
  refreshes numerical, GIS, hydrology, storage, climate, classification, and
  licensing options.

- [Terrain algorithm options — 2026-09-03](docs/research/2026-09-03-terrain-algorithm-options.md)
  records the current solver, hydrology, erosion, multiresolution, validation,
  tooling, and license findings without accepting an implementation.

- [ADR-0003](docs/adr/0003-map-authored-constraints.md) records the initial
  feature-curve conditioning decision and diffusion/process-informed options.
- [ADR-0004](docs/adr/0004-soft-elevation-brush.md) explains why authored brush
  guidance remains vector-based rather than resolution-bound raster paint.
- [ADR-0005](docs/adr/0005-relative-relief.md) defines absolute versus relative
  semantics and links the existing terrain-interpolation research.
- [Terrain tool guide](src/dmtools/terrain/README.md) documents the implemented
  behavior that this roadmap builds on.
