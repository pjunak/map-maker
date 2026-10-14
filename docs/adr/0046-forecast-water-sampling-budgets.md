# ADR-0046: Forecast water-sampling budgets

- Status: Accepted
- Date: 2026-09-13
- Extends: ADR-0042, ADR-0043 and ADR-0045
- Corrects: the wet-network limit stated in ADR-0044 and ADR-0045

## Context

The public five-detail flat-outlet fixture fits the current dry-network budget;
its six-detail variant does not. A full build previously had to generate the
delivered DEM before reporting that limit. Settings-only estimates cannot know
which canonical nodes are wet or which vector-contained dry links qualify.
Duplicating candidate and profile logic would let a forecast drift from review.

## Decision

Expose `map-maker terrain water-budget PROJECT` as a read-only application
operation. Share immutable terrain-field preparation with normal generation,
then evaluate the finished Float32 canonical ground without a delivered raster.
Share normalized shoreline vertices, vector-contained basin neighbours, wet/dry
candidate selection and bounded profile planning with the actual review paths.

Report per-basin shoreline and potential wet/dry-network demand, baseline
stations, candidate/visited profile counts, applicable limits and the first
limiting budget. Successful complete plans have exact counts. Budget failures
remain lower bounds because refinement or remaining profiles may be unvisited.
Count repeated stations exactly as runtime does; allocate no fine profile
station arrays or ground evidence in this operation.

Potential networks are conditional on existing outlet, shoreline and wet
connectivity gates. Plan them even if a full review might skip them; do not claim
eligibility or clearance. Closed lakes have shoreline demand only; dry basins
have neither shoreline nor outlet-network demand. Report sub-grid footprints
without inventing usable nodes. Do not forecast external routes/contacts,
unique evaluation count, exports, runtime or whole-project total demand yet.

Bind the result to verified saved-project/SVG hashes and installed source/runtime
before and after planning. Print text on stdout and return success for a
completed forecast, including excessive demand; reject missing/changed/invalid
inputs on stderr. Do not add a machine-readable format, build product, automatic
pre-build pass or workbench control in this slice.

## Correction of budget documentation

The implemented limits are **65,536 per profile, 65,536 per wet network and
262,144 per dry network**, with batches of 4,096 evaluation positions. ADR-0042
and the original internal-water-link report already stated the wet limit
correctly. ADR-0044, ADR-0045 and the detail/context report mistakenly generalized
the dry-network cap to wet networks. This corrects prose; no limit is raised.

Terrain, authored settings, incision/capture, stations, full review evidence,
transfer gates and array layouts remain unchanged. Keep generator @8, water
@10, outflow @8, sampler @4, project v5 and build v16. The installed source hash
records the refactor and new operation. No legacy path or dependency is added.

## Validation and consequences

Compare forecasts with executed profiles on connected, flat, blocked and
closed/dry fixtures, including genuine detail-induced budget exhaustion.
Validate all numeric hashes and complete water-evidence hashes against the
pre-refactor controls. Check resolution/order independence, no fine sampling,
no input writes, stale-source rejection and atomic failure behavior.

Measure fresh-process forecast versus generation cost, including a large output
resolution; canonical preparation and conditional geometric planning still cost
time. This is an operator diagnostic, not a cheaper full review or a continuous
terrain-error bound. [The report](../research/2026-09-13-water-budget-forecast.md)
records measured costs and the remaining implementation order.
