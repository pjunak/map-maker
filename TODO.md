# Terrain tool backlog

The categorized backlog of open work. The [implementation plan](docs/strategy/README.md)
owns the order; [status](docs/research/status.md) says what already works, and Git
history and the [dated reports](docs/research/README.md) keep completed work.
Failed trials and revisit gates are in the
[method register](docs/research/terrain-method-decisions.md).

Labels: **P0** is a prerequisite within its feature; **P1** is high value once its
P0 exists; **P2** is a later extension; **Research** means compare approaches on
small synthetic terrain before choosing one.

## Current milestones (open items)

See the [plan](docs/strategy/README.md) for states and evidence.

- [ ] **M2 planet relief:**
  - [ ] Conserving sediment deposition with flexure (a per-node G term was rejected).
  - [ ] Analytic steady-state finish or level-set parallel routing (faster fine builds).
  - [ ] Use the bathymetry product as the ocean floor, or record why not.
- [ ] **M3 climate:** monthly outputs, below-sea-level basins and an energy-balance check.
- [ ] **M4 workflow:** compare and regenerate in the World tab.
- [ ] **M5 adoption:**
  - [ ] Reference-world quality gates and an accepted planet parent.
  - [ ] Port the stable kernels to a native core.
  - [ ] Decide what replaces the local composed generator.
- [ ] **M6 regional and local zoom:**
  - [ ] Rivers exactly identical across windows (routing over a padded window
    leaves only pixel-grid differences, about 4 % near edges).
  - [ ] Check drainage realism at fine levels: rock texture now follows each level's
    spacing and level-3 tiles branch; compare against reference terrain.
  - [ ] Tile boundary exchange (domain decomposition); regional lakes and climate.
- [ ] **Map views (ADR-0087):** political and civilization views from authored
  overlays.

### World-context checkpoint

Open world-context work from the [WC0-WC6 plan](docs/strategy/world-context.md).
World import, context and planet climate are implemented; see [status](docs/research/status.md).

- [ ] **WC0 source-quality follow-up:** add zoom-to-conflict navigation and broader
  native/high-precision export comparison when needed. Current reports highlight
  affected shapes but do not automatically zoom or diagnose every export setting.
  Draft mapping saves and bounded import cancellation remain separate follow-ups.
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
- [ ] **WC3 — Couple climate/runoff and coarse history** (R33/R49): seasonal budgets,
  explicit epoch forcing, bounded feedback and visible nonconvergence.
- [ ] **WC4 — Select a verified world parent** (R49/LE3/LE5): staged editor workflow,
  continent defaults/province overrides, shared present and stale-child tracking.
- [ ] **WC5 — Refine regional history to the same present** (R15/R34/LE6): sufficient
  parent trajectory, inherited flux, exact overlaps and no double aging.
- [ ] **WC6 — Derive ecology and compare richer processes:** classifications after
  continuous fields; advanced oceans/GCMs/plate histories only for a specific gap.

### Geological-history checkpoint

Open items of the isolated [landscape-evolution reference](docs/strategy/landscape-evolution.md)
(research only; the planet pipeline is the product path).

- [ ] **LE2 — Accept a two-epoch landscape** (R11/R14/R40/R43). The comparison
  command, current/constant/reversed controls, three-seed cohort, process ablations,
  resistance, rotation/extent/spacing checks and figures are implemented. The
  D8/bilinear candidate fails the continuous-profile quality gate; keep chronology
  as a useful candidate while resolving grid sensitivity and surface/path agreement.
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

Open drainage work for the local terrain path.

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

- [ ] **P1 — Verify local GeoTIFF import in desktop GIS and standalone GDAL.**
  Rasterio numeric reads and Pillow TIFF-tag checks pass. Desktop display is
  unverified; Rasterio 1.5.1 `rio info` assumes an Earth-coordinate conversion
  and fails for the current engineering CRS.
- [ ] **P0 — Add explicit source-to-world placement and projected export.**
  Declare the planetary model, source correspondence and metric working
  projection; validate distortion and coordinate round trips. Local TIFF
  coordinates do not yet place a continent on a world map.
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
- [ ] **Research — Compare path-aware alternatives after a cumulative rejection.**
  Local blocked links already admit other descents and flat exits. A composed
  path exceeding tolerance retains that donor and its upstream paths; it does
  not search different downstream choices. Compare bounded state-aware methods
  without favouring lake exits over closed pits or perturbing the DEM.
- [ ] **P1 — Measure remaining network planning and evidence overhead.** Compare
  feature indexing on many-constraint scenes, project-scale profile memory and
  compact diagnostic serialization. Retain every required probe, complete budget
  decision and reviewable failed link; exact per-call reuse is already implemented.
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
- [ ] **P1 — Author climate-region guidance before generation.** Once consumed by
  a backend, let the user specify intended aridity/desert areas over the previous
  map, with conflicts and uncertainty visible. Do not expose a no-op paint tool.
- [ ] **P0 — Preserve world-to-region consistency.** Share one parent revision,
  global present, history and boundary forcing. Changes to macro relief or gateways
  can invalidate distant climates. Local aging must not replay time twice.
- [ ] **P2 — Add versioned climate-zone classification views.** Köppen–Geiger exists
  on the planet; add an ecological Holdridge-like view from continuous fields;
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

### Realism research register (R01–R48)

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

- [ ] **P1 — Reflow long World source summaries in compact windows.** The separate
  nine-continent source summary below the map can still clip horizontally at
  1160 x 760; bind its wrapping width or give it a bounded scrollable region.

### Editing and navigation

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
- [ ] **P1 — Add switchable inspection overlays.** Include contours, hillshade,
  slope, curvature, influence extents, hard-constraint residuals, drainage,
  catchments and clipped-elevation warnings. Drainage and basin catchment
  toggles are implemented; the other listed overlays remain open.
- [ ] **P0 — Extend terrain inspection for quality comparisons.**
  Add local slope, active constraint contributions and a cross-section through the selected ridge or valley.
  Start with a selected-channel longitudinal profile of actual finished ground,
  cut limits and unresolved intervals, and show effective process spacing.
- [ ] **P1 — Make relative-versus-absolute behavior visible.** Use concise
  tooltips and preview labels that state target height, signed displacement,
  ridge relief, or valley incision in the correct terms.
- [ ] **P0 — Add before/after and seed comparison views (R27).** Compare a changed
  constraint, profile, or seed without relying on memory of the previous image.
- [ ] **P2 — Add tint-only and hillshade-only display modes.** Keep these as
  derived inspection choices that never change the authoritative DEM.

### Project safety and everyday workflow

- [ ] **P1 — Audit closed editor ownership and callback retention.** A separate
  shutdown probe retains a closed workbench through Tcl variable traces until
  those traces are removed. Establish deterministic release of callbacks and
  resources at editor/application shutdown, including jobs finishing after close.
  The test-isolation correction does not establish a runtime lifecycle fix.

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
