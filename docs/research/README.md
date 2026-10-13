# Research notes

**For conclusions by topic, start with the [research decision catalog](decision-catalog.md).**
It links tools, mathematical models, used/deferred/rejected choices and revisit
triggers to the dated evidence below. The [M1-M8 implementation plan](../strategy/README.md)
is the only current work order; reports retain their historical next steps.

This index preserves dated evidence: implementation rundowns, measured or
rejected prototypes, and candidate papers/tools. A research mention does not
mean a dependency or feature was adopted. The [current status](status.md) maps
these findings to implemented contracts and remaining TODO work; the
[development strategy](../strategy/README.md) owns execution order. The living
[method decision register](terrain-method-decisions.md) records what failed, why,
what was retained and which evidence would justify a replacement or revisit.

Notes are newest first. Measurements and package-support claims belong to their
recorded revision/date. Keep historical findings intact and record later changes
in the current status or a new dated report.

## Current reassessment

- [Refined world map — 2026-10-13](2026-10-13-refined-world-map.md) builds Aethelara from
  its planet land traced back into vector form: the same geography with cleaner coasts,
  whose level-1 coast detail regional levels add a second time.

- [Polar land — 2026-10-13](2026-10-13-polar-land.md) works the planet's polar land in true
  distance and covers a pole the drawn land touches, so the south polar ice sheet domes over
  the pole instead of ending in a spike.

- [Ice sheets — 2026-10-13](2026-10-13-ice-sheets.md) grows ice sheets from snowfall
  against melt by shallow-ice flow, with height, albedo and regional climate feedbacks,
  and draws large sheets with their own surface inside refined margins, on the atlas
  and in regional windows.

- [Regional lake shores — 2026-10-12](2026-10-12-regional-lake-shores.md) draws regional
  lakes as water filling the regional relief, holds crater lakes in the tiles' own frame
  and refines lake outlines below the parent spacing, so shores lose the parent mesh's
  straight edges. Open lakes drain their window basin, so no playa ring lines their
  shores.

- [Straight display lines — 2026-10-12](2026-10-12-straight-display-lines.md) traces straight
  hillshade lines on regional plains to display carving across filled depressions and to
  stepped ridged detail; depressions now drain along their thalweg and the detail is continuous.

- [Regional coast detail — 2026-10-11](2026-10-11-regional-coast-detail.md) smooths the
  traced coast at its drawing precision and adds nested fractal detail at regional levels,
  so province and local maps show rugged shores instead of straight traced runs.

- [Continentality and Köppen zones — 2026-10-08](2026-10-08-continentality-and-koppen.md)
  carries maritime air downwind for seasonal ranges, keeps seasonal rainfall and classifies
  Köppen–Geiger zones (new climate-zones layer); vegetation follows growing-season water.

- [Volcanism — 2026-10-08](2026-10-08-volcanism.md) places arc, hotspot, rift and intraplate
  volcanoes from the plate model, draws cones, calderas and seamount chains sharply, and
  exports a volcano gazetteer.

- [Plate tectonics and sediment — 2026-10-08](2026-10-08-plate-tectonics-and-sediment.md)
  places collision belts, rifts, active margins and trenches from 18 rotating plates, with
  old orogens kept as welded sutures.

- [Orogens, glaciers and speed — 2026-10-08](2026-10-08-orogens-glaciers-and-speed.md)
  surveys methods (analytic stream power, deposition, tectonics, climate, cartographic
  shading). It adds composite orogens with strike-aligned rock, a glacial buzzsaw,
  Horton/sinuosity gates and openness shading. It records three rejected deposition trials,
  and Numba noise and conditional flooding cut 3.2M builds to 4.9 min.

- [Earth-scale landforms — 2026-10-07](2026-10-07-earth-scale-landforms.md) compares range
  widths, valley spacing and river lengths with Earth (Hovius spacing, Hack's law, river and
  fjord data). It narrows ranges to explicit widths, keeps shields smooth, and adds an
  inherited surface and 3.2M-node builds with climate on coarser meshes.

- [World-scale detail and softer climate boundaries — 2026-10-07](2026-10-07-world-scale-detail.md)
  adds multi-scale procedural forcing and a mesh-independent eddy diffusivity for moisture
  (the old mixing sharpened with mesh density). It also carves display valleys into the
  world atlas, and makes rivers thinner and playas arid-only.

- [Natural-looking planet and regional maps — 2026-10-07](2026-10-07-natural-map-rendering.md)
  replaces biome-class colours and uniform shelves with continuous natural colour, and adds
  sub-mesh display detail. Regional windows get valleys carved over the detail by grid stream
  power, real bathymetry and a ridge-following snowline.

- [First authored world through the planet — 2026-10-06](2026-10-06-first-authored-world-planet.md)
  runs a private 9-continent world at 200k/800k nodes and regional zoom, fixes lakes and
  rivers on ice sheets, and records staircase-coast and placeholder-geology findings.

- [Regional enrichment and blended tiles — 2026-10-06](2026-10-06-regional-enrichment-tiles.md)
  regenerates planet regions at 5 km with parent-calibrated uplift. Overlapping windows
  disagree (238 m RMS), so fixed blended tiles give window-independent detail.

- [Planet cratons and lakes — 2026-10-06](2026-10-06-planet-lakes-and-cratons.md)
  replaces central-dome cratons with marginal swells and interior sags, and adds young
  depressions with climate-balanced open/closed lakes and discharge-based rivers.

- [Planet climate v0 and coupling — 2026-10-06](2026-10-06-planet-climate-v0.md)
  adds explainable temperature, winds, moisture transport, runoff and provisional
  biomes on the planet mesh, couples runoff to erosion and retains the failed
  calibration steps; windward/leeward control test.

- [Whole-planet erosion relief — 2026-10-06](2026-10-06-whole-planet-erosion-relief.md)
  evolves a whole synthetic world on an irregular sphere mesh with implicit stream
  power; resolution sweep, isotropy, Hack exponent and zero non-descending rivers.

- [Context-bound rough terrain — 2026-09-28](2026-09-28-context-bound-rough-terrain.md)
  records the experimental M1 world/context binding, conservative continuous
  coastal-distance consumer, public paired control, failed discontinuous bound and
  explicit unsupported climate/runoff/aging/bathymetry boundaries.

- [Shared ridge crests — 2026-09-27](2026-09-27-shared-ridge-crests.md) preserves
  authored ridge contacts and compatible crest heights, with paired seed/scale
  evidence, a repaired corner gap and explicit remaining geometry/process limits.

- [Line-owned terrain profiles — 2026-09-27](2026-09-27-line-owned-terrain-profiles.md)
  adds explicit crest/pass/floor ownership and a curve editor, preserving failed
  assumptions about proximity ownership and multi-line target composition.


- [World-to-terrain workflow — 2026-09-27](2026-09-27-world-to-terrain-workflow.md)
  delivers continent-to-project creation through the editor and CLI, with connected
  land, fixed world scale and exact retained source geometry. Records the real-map
  area-roundoff failure and fix, focused validation, feature-first priorities and
  remaining bank failures in four short geometry probes.


- [Prepared terrain snapshots — 2026-09-27](2026-09-27-prepared-feature-snapshots.md)
  implements bounded numeric storage/reopening, full graph/segment consistency
  and owned queries. All 575 banks and original metrics survive reopening;
  same-field query-order and overlapping-tile checks pass. Records format guards,
  the rejected raster control, timings and remaining held-out/detail gates.

- [Feature-preserving terrain delivery — 2026-09-27](2026-09-27-feature-preserving-terrain-delivery.md)
  tests river-aligned analytic sampling, rejects generic network splines and
  preserves all 575 local bank profiles through trusted-field saving/reopening.
  Records short timings, limited bilinear feasibility, existing methods and the
  next guarded feature/query experiment. Product DEM authority is unchanged.

- [Cell-safe terrain delivery — 2026-09-27](2026-09-27-cell-safe-terrain-delivery.md)
  implements curvature-bounded bilinear cut capacities, an explicit interior bound
  and independent corner/thin-area controls. The worst 250 m inward rise falls
  from 54.062 to 0.316 m; 238/575 dense bank sections still fail. Records rejected
  node-only/clipped-negative bounds and the next constrained reconstruction.

- [Valley heads and mouths — 2026-09-26](2026-09-26-valley-heads-and-mouths.md)
  implements head profiles that respect the cut envelope and perpendicular mouth
  sections. All 575 matched local banks pass ordinary and dense checks; raster
  bank delivery remains rejected. Records rejected tapers, the outlet wedge,
  preserved controls and the next bounds-projection/reconstruction comparison.

- [Hard-target-aware valley layout — 2026-09-26](2026-09-26-hard-target-valley-layout.md)
  implements bounded relocation of explicitly automatic guides while preserving
  all original vertices, hard heights, topology and envelopes. At 250 m capture
  improves from 3/4 to 4/4 with no sinks or uphill guide routes. Bank and coarse-grid
  failures remain; records rejected detour/bed-lifting attempts and the next gate.

- [Connected valley patches and raster delivery — 2026-09-26](2026-09-26-connected-valley-patches.md)
  implements fixed/fresh construction, analytic valley unions, coastal transitions
  and bounded Float32 delivery. Fresh local capture is 4/4, while 250 m delivery
  captures 3/4; fixed/native and guide/bank quality remain rejected. Records the
  mouth ablation, inter-node cap correction and next hard-target-aware comparison.

- [Groundwater, canyons and terrain architecture — 2026-09-25](2026-09-25-groundwater-and-terrain-architecture.md)
  reviews porous groundwater, seepage, karst, lateral erosion and joint terrain/network
  construction. Revises input-role and representation comparisons, with staged
  analytic/capture/material gates. Local component imports succeeded; no new
  simulation or product engine was adopted.

- [Valley-bank feasibility — 2026-09-25](2026-09-25-valley-bank-feasibility.md)
  implements fixed physical bank support, junction ownership, mouth taper and
  native-bound/hard-height conflict diagnostics. Feasible endpoint checks pass;
  intervening rises and actual capture fail, with more sinks at 250 m. The later
  connected-patch report above follows it with explicit input roles, local valley
  construction and a separate fresh-construction envelope.

- [Constrained network-led terrain — 2026-09-25](2026-09-25-constrained-network-surface.md)
  implements a unique surface fit with hard heights, native cut/no-fill limits,
  protected divides and whole-cell channel descent. Independent finer-grid routing
  exposes failed capture and interior sinks; the bank comparison above follows it.

- [Coupled physical channel paths — 2026-09-25](2026-09-25-physical-channel-paths.md)
  implements a shared path/ground mesh, complete route comparison, cut/fill and
  anchor rejection controls and shared-coordinate receiver/outlet diagnostics.
  Reduced direction locking did not pass authoring or landform gates; it motivated
  the constrained network-led comparison above, before LE3/WC2.

- [Water-piece connectivity — 2026-09-25](2026-09-25-water-piece-connectivity.md)
  implements separate pieces and shared intervals, source-verified graph products,
  explicit precision-limit support and Context inspection. Records synthetic and
  private-world controls and isolated graph performance; terrain quality comes next.

- [Authored world bathymetry — 2026-09-25](2026-09-25-authored-world-bathymetry.md)
  implements explicit ocean selection, conservative shelf/slope/basin depths,
  numerical error and unresolved support, with independent inputs/editor/verified
  results. Records analytic tests, visible review and normal/maximum-grid cost.

- [Authored world geology — 2026-09-25](2026-09-25-authored-world-geology.md)
  adds retained-world recipes, continent defaults, cross-label/seam provinces,
  independent ages and priority coverage, with editor/save/history controls.
  These inputs do not yet drive rough terrain, climate or erosion.

- [Geographic exposure — 2026-09-25](2026-09-25-geographic-exposure.md)
  adds bounded spherical shoreline distance, eight directional water-exposure and
  mixed-support fields, current-format reopening and editor inspection. The later
  authored-geology and bathymetry batches are linked above; physical transport remains.

- [Context reopening and water openings — 2026-09-25](2026-09-25-context-reopening-and-gateways.md)
  implements verified context loading, finite shared-face widths, seam-roundoff
  correction and editor inspection. The later exposure batch is linked above.

- [Geographic world context — 2026-09-25](2026-09-25-geographic-world-context.md)
  implements WC1 spherical coverage, vector-derived water topology, mixed/subcell
  support, Context generation/preview/cancellation and reproducible exports.
  Records numeric/UI controls and measured cost; climate/terrain remain later work.

- [Bounded world preparation — 2026-09-25](2026-09-25-bounded-world-preparation.md)
  handles minor edge/border discrepancies and same-owner shared land in derived
  coverage, retaining original source with selectable adjustment reports.

- [World SVG import corrections — 2026-09-25](2026-09-25-world-import-corrections.md)
  fixes exported headers, semantic layer labels and self-crossing fill semantics;
  makes exclusions and source geometry conflicts visible for review.

- [World-source workspace — 2026-09-25](2026-09-25-world-source-workspace.md)
  implements and validates WC0 source import, spherical placement, semantic
  mapping, portable saves and World/Terrain navigation. Records public-fixture
  checks and bounded timing observations; world context/terrain remain planned.

- [World-context enrichment — 2026-09-24](2026-09-24-world-context-enrichment.md)
  evaluates retained world import, geography/oceans, tectonic hypotheses, seasonal
  climate and same-present regional aging; compares established tools and newer
  2026 ocean work. The [WC0-WC6 plan](../strategy/world-context.md) moves minimum
  world context forward while retaining terrain-quality gates. Source research
  only: no new engine installed, numerical climate run or application feature.

- [Landscape-evolution models and tools — 2026-09-24](2026-09-24-landscape-evolution-models.md)
  compares primary papers, mathematical assumptions and existing engines for
  authored geological epochs; records a Windows wheel-only dependency probe.
  The [detailed implementation plan](../strategy/landscape-evolution.md) specifies
  the proposed comparison, integration and acceptance gates. No engine was run.

- [Progress and generation strategy — 2026-09-24](2026-09-24-progress-and-generation-strategy.md)
  audits the working product, measures hidden channel-profile rises on eight
  current public cases, refreshes primary sources and platform/license evidence,
  and reorders work around terrain quality. No external engine was run or adopted.

## Implemented and measured work

- [Frozen terrain/channel reconstruction — 2026-09-24](2026-09-24-frozen-channel-reconstruction.md)
  measures a drainage-aligned triangle surface on all 22 completed history/control
  states: preserved route coverage and zero sampled ascent on nodally descending
  routes, with nodal climbs, direction bias, authoring conflicts and composition
  volume retained as explicit limits. Runs without the optional scientific stack.

- [Landscape-evolution reference — 2026-09-24](2026-09-24-landscape-evolution-reference.md)
  implements LE1 and the first LE2 comparison: ordered uplift/runoff/incision/
  hillslope transport, numerical controls, pinned reference, figures and cost.
  Chronology responds, but continuous profiles and grid acceptance remain open.

- [Connected drainage review and authored density - 2026-09-24](2026-09-24-connected-drainage-review.md)
  measures connected scale selection, viewport redraws and explicit density
  controls; records the remaining D8 geometry and finer-hydrology limitations.

- [Shared-edge terrain detail - 2026-09-23](2026-09-23-shared-edge-detail.md)
  connects experimental detail using terrain-slope weights, preserves parent nodes
  and moments, and measures quantized slopes, coarse leakage and remaining grid direction.

- [Preview image ownership - 2026-09-23](2026-09-23-preview-image-ownership.md)
  tiles water composition, removes duplicate one-shot ground images and closes
  editor/export buffers; records isolated native/viewport peaks and Tk lifecycle checks.

- [Bounded terrain rendering - 2026-09-23](2026-09-23-bounded-terrain-rendering.md)
  tiles native ground shading, bounds regional comparison panels and releases
  owned images on cancellation; measures near-limit and extreme-aspect regions.

- [Regional memory admission - 2026-09-23](2026-09-23-regional-memory-admission.md)
  reserves estimated parent/job memory, removes oversized file-read allocations
  and bounds detail intersection batches; compares fresh-process resident peaks.

- [Verified parent-region sessions - 2026-09-23](2026-09-23-parent-region-sessions.md)
  retains verified parent work and byte-bounded numeric results with automatic
  freshness checks; compares complete artifact writes and explicit release.

- [Bounded detail-cell reuse - 2026-09-23](2026-09-23-detail-cell-reuse.md)
  reuses scalar cell support across regional requests with explicit limits and
  eviction; measures exact cached/uncached results and local sampling cost.

- [Verified parent and experimental local detail - 2026-09-23](2026-09-23-verified-parent-detail.md)
  adds portable completed-parent replay, separate regional artifacts and bounded
  residual generation; measures consistency/cost while retaining explicit visual
  and hydrological acceptance limits.

- [Exact overlapping height points - 2026-09-23](2026-09-23-exact-height-points.md)
  fixes the authored-height defect found during parent-preservation research,
  validates smooth approach to each target and records numerical/performance
  effects before returning to local-detail generation.

- [Parent-cell preservation - 2026-09-23](2026-09-23-parent-cell-preservation.md)
  measures a research-only projection and rejects runtime adoption despite exact
  parent nodes: the reference loses terrain structure, authored heights drift,
  density changes shared values and inherited channel profiles worsen.

- [Stable detail-band amplitudes - 2026-09-22](2026-09-22-stable-detail-band-amplitudes.md)
  removes count-dependent noise normalization, separates regional shapes from
  finer bands, and measures remaining coarse-cell and drainage changes.

- [Bounded regional field sampling — 2026-09-22](2026-09-22-regional-field-sampling.md)
  verifies unchanged-field 65/129/257 windows, overlap/repeat consistency,
  completion provenance and the cost of local versus complete finer sampling.

- [Water display scale — 2026-09-17](2026-09-17-water-display-scale.md)
  checks scale-aware sampled lake visibility, viewport caching and local
  rendering cost; small rivers remain gated on future regional detail.
- [Network floor conditioning - 2026-09-17](2026-09-17-network-floor-conditioning.md)
  carries cut-limited floors through tributaries, measures large-climb reductions
  and smaller-rise regressions, and retains path alternatives as research.

- [Attainable channel floors - 2026-09-17](2026-09-17-attainable-channel-floors.md)
  diagnoses a cut-limited route and compares sparse floor profiles that reduce
  extra dips while retaining canonical routing, pins and budgets.

- [Refined mountain crests - 2026-09-17](2026-09-17-refined-mountain-crests.md)
  compares broader candidate selection and bounded crest searches against dense
  finite references, finished-channel profiles and fresh-process runtime.

- [Drainage routing cost - 2026-09-17](2026-09-17-drainage-routing-cost.md)
  measures faster generation with identical numerical products and bounded
  mountain-carrier working storage through 128 overlapping regions.

- [Mountain-crest routing - 2026-09-16](2026-09-16-mountain-crest-routing.md)
  compares alternate routes and targeted observations, with additional seeds,
  unchanged budget policy, measured runtime cost and mixed drainage diagnostics.

- [Source-aware channel floors - 2026-09-16](2026-09-16-source-aware-channel-floors.md)
  fits cuts to actual sampled terrain within existing ceilings and diagnoses
  hidden mountain crests that reconstruction alone cannot remove.

- [Connected diagonal valleys - 2026-09-16](2026-09-16-connected-diagonal-valleys.md)
  reduces between-node scalloping within existing caps and adds repeatable
  finite channel-profile measurements, including three additional dense checks.

- [Bounded valley reconstruction - 2026-09-16](2026-09-16-bounded-valley-reconstruction.md)
  measures smoother automatic shaping between canonical nodes, preserved cut
  limits and routing, finite channel profiles, runtime and memory.

- [Bound-driven noise-profile refinement - 2026-09-16](2026-09-16-bounded-noise-refinement.md)
  compares hybrid geometry and adaptive/uniform refinement with local extrema,
  ordered-rise tolerances and cumulative limits; full-field adoption remains open.

- [Rounded noise-profile bounds - 2026-09-14](2026-09-14-noise-profile-bounds.md)
  measures grid-strip clipping, complete work limits and ordered uphill bounds;
  broad diagonals cost fewer cells, while fine-path overhead and full-field
  uncertainty remain open.

- [Rounded bounds for procedural noise - 2026-09-13](2026-09-13-noise-component-bounds.md)
  compares natural and polynomial/cell enclosures with explicit roundoff,
  finite-reference checks and complete work budgets; full terrain bounds remain open.

- [Prepared bounds for water-sampling guides - 2026-09-13](2026-09-13-water-guide-bounds.md)
  records exact candidate rejection, lake/constraint scaling, paired runtime
  measurements and preserved station/numeric/evidence identities.

- [Adaptive water-profile refinement - 2026-09-13](2026-09-13-adaptive-water-profile-refinement.md)
  measures a research-only midpoint experiment, false convergence, sample demand
  and explicit exhaustion; the heuristic is not adopted for runtime clearance.

- [Water-sampling budget forecast - 2026-09-13](2026-09-13-water-budget-forecast.md)
  records shared demand planning, unchanged output/evidence and fresh-process cost.

- [Procedural detail and context sampling - 2026-09-13](2026-09-13-detail-and-context-sampling.md)
  measures lattice-scale/shoulder guidance, residual misses and complete-budget cost.
- [Water-profile convergence and regional guidance - 2026-09-13](2026-09-13-water-sampling-convergence.md)
  records nested/shifted real-field comparisons, detected regional barriers,
  measured remaining extrema misses and bounded implementation cost.

- [Exact water-sampling reuse - 2026-09-13](2026-09-13-water-sampling-reuse.md)
  records shared feature preparation/evaluation, preserved evidence and measured cost.

- [Dry collection paths - 2026-09-11](2026-09-11-dry-collection-paths.md)
  records dry barriers, alternate routes, cumulative head checks and measured cost.
- [Internal water links - 2026-09-11](2026-09-11-internal-water-links.md)
  records finer pool separation, alternate paths, batching and preserved ground.
- [Complete downstream outlet profiles - 2026-09-11](2026-09-11-downstream-outlet-profiles.md)
  records a missed downstream climb, retained area, exported evidence and measured cost.
- [Feature-guided water sampling - 2026-09-11](2026-09-11-feature-guided-water-sampling.md)
  records narrow-core detection, convergence probes, preserved ground and measured cost.
- [Finer water connections - 2026-09-11](2026-09-11-finer-water-connections.md)
  records detected shoreline gaps, contact barriers, exported profiles and measured cost.
- [Basin flat routing - 2026-09-11](2026-09-11-basin-flat-routing.md)
  records exact-flat routing, preserved pits, exported paths and measured cost.
- [Basin catchment review - 2026-09-11](2026-09-11-basin-catchment-review.md)
  maps collected/retained nodes and records outlet-level evidence and next steps.
- [Connected lake outflow - 2026-09-11](2026-09-11-connected-lake-outflow.md)
  records conservative outlet transfer, a real rejected route, validation and runtime.
- [Basin retention and outlet assessment - 2026-09-11](2026-09-11-basin-retention-and-outlets.md)
  records conserved basin area, downstream evidence, validation and runtime.
- [Authored water implementation - 2026-09-10](2026-09-10-authored-water.md)
  records lake/dry-basin retention, validation and measured runtime limits.
- [Basin extent and outlet topology - 2026-09-10](2026-09-10-basin-outlet-topology.md)
  unifies diagnostic grids and records explicit escape routes and water-boundary context.
- [Depressions and channel conflicts - 2026-09-10](2026-09-10-depressions-and-channel-conflicts.md)
  compares retention, constrained breaching and outlet mapping, and records
  overlapping conflict diagnostics and the zero-height flow fix.
- [Selective terrain sampling — 2026-09-05](2026-09-05-selective-terrain-sampling.md)
  records the Python benchmark harness, exact-output optimization, timing/memory
  comparisons and rejected indexing probe for the first R45 slice.
## Candidate research and historical assessments

- [Language and performance — 2026-09-05](2026-09-05-language-and-performance.md)
  measures the generator at that date, recommends a bounded foundation/performance
  pass in Python, compares a future Rust migration and records R45–R47 gates.
- [Geological structure and terrain composition — 2026-09-05](2026-09-05-geological-structure-and-terrain-composition.md)
  adds R40–R44: related regional recipes, material-coordinate and event-order
  requirements, distinct terrain/water graphs, directional measurements,
  multiscale landform classification and significant peak/pass comparisons.
- [Terrain prototype contracts — 2026-09-04](2026-09-04-terrain-prototype-contracts.md)
  narrows the first experiments with measured noise/grid effects, source audits
  of SPACE and GPU references, landform suitability, numeric exchange gates,
  and focused meander/delta alternatives. Adds R34–R39 to the roadmap.
- [Terrain realism and landform diversity — 2026-09-04](2026-09-04-terrain-realism-and-landform-diversity.md)
  extends the roadmap with R01–R33: regional composition, sediment, specialized
  landforms, scale contracts, recent papers, external tools, and comparison
  experiments. It also corrects the earlier procedural-pattern paper title
  and revisits the blanket preference against particle erosion.
- [Technology and world systems — 2026-09-04](2026-09-04-technology-and-world-systems.md)
  refreshes numerical, GIS, hydrology, storage, climate-model, classification,
  and licensing options and turns them into staged recommendations.
- [Terrain algorithm options — 2026-09-03](2026-09-03-terrain-algorithm-options.md)
  compares base-surface solvers, drainage methods, landscape processes,
  multiresolution implications, validation fixtures, and candidate libraries.
- [Elevation colour ramp — 2026-09-03](2026-09-03-elevation-colour-ramp.md)
  evaluates ordered elevation display and selects the accessible `oleron` land
  sequence for scientific inspection.
- [Cartographic relief style — 2026-09-03](2026-09-03-cartographic-relief-style.md)
  decomposes the preferred illustrated relief look and separates it from the
  ordered scientific inspection view.

Scope note: dated proposals preserve the questions studied at their original date.
[ADR-0048](../adr/0048-keep-zoom-driven-detail-generation.md) corrects the overly
broad regional-generation exclusion in ADR-0047. Zoom-driven local detail and
adaptive numerical sampling remain active generation work; direct sculpting of
completed outputs remains outside the product scope.
