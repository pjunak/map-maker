# Terrain method decisions and failed experiments

Updated 2026-10-19 through T23 one river course through regional levels.
This is the living record of
material generation approaches that were rejected, constrained or retained only
as references. A failed method does not remove its desired feature from the plan.
The [strategy](../strategy/README.md) owns execution order; dated reports own the
original measurements, source identities, commands and validation boundaries.
The [decision catalog](decision-catalog.md) indexes used, deferred and untested
method families. M1-M4 integration now precedes further isolated refinement;
T entries preserve failure evidence and the requirements for adopting a replacement.
Supporting sampling/convergence and performance rejections remain indexed in
[research status](status.md), including the slower
[coast-index candidate](2026-09-05-selective-terrain-sampling.md). This register
concentrates on methods that change the generation-quality decision.
The [groundwater and architecture reassessment](2026-09-25-groundwater-and-terrain-architecture.md)
explains the replacement proposals. Groundwater, karst and lateral erosion remain
untested here; T09-T13 measure valley construction, automatic placement, bounded
raster delivery and exploratory feature preservation.

## How to maintain this record

For each substantive numerical experiment, update this register, its dated report,
the affected [catalog decision](decision-catalog.md), [status](status.md) and
[TODO](../../TODO.md) checkpoint together using the main plan's update checklist.
Record the hypothesis, unchanged control, input roles, measured outcome, diagnosed
cause versus unresolved explanation, reusable work, disposition and revisit gate.
Keep stable IDs below. Add later evidence to the disposition; never rewrite a
historical report to imply a failed candidate was accepted.

Distinguish unsupported input, a proven constraint conflict, solver failure,
budget exhaustion and a completed candidate failing quality. Only a verified
conflict witness establishes infeasibility. Tests passing means the experiment
behaves as specified, not that its terrain is realistic. New methods need new
identities and prospective gates; a changed fixture is not a repair of an old result.

## T01 - Replace D8 valley shoulders with flow signals

**Tried:** fully flow-connected D8 shoulders and full MFD replacement. The
[algorithm report](2026-09-03-terrain-algorithm-options.md) records retained D8 gaps
for the former and worse finished-surface drainage diagnostics for the latter.

**Why / boundary:** a better accumulation signal did not establish a connected
continuous valley. This evidence rejects those replacements, not MFD accumulation
as a hydrological tool. A small, major-trunk-gated MFD correction was retained.

**Replacement / revisit:** construct shared bed, bank and junction geometry (B/R48),
using accumulation as an input. Compare contributing-area accuracy separately from
surface capture; merely increasing the MFD blend is not the next experiment.

## T02 - Use stream order or lower density as the main quality fix

**Tried:** direct Horton-Strahler width and 3%/1% depth adjustments in the
[algorithm report](2026-09-03-terrain-algorithm-options.md). Width violated the
synthetic downstream-width invariant; depth increased coarse diagnostic fill on
Tharkeniss. A later default density of 0.75 failed the existing shoulder-width
control in the [connected-review batch](2026-09-24-connected-drainage-review.md).

**Why / boundary:** topology alone is not a material/confinement/flow model;
changing initiation also changes actual incision. Fewer visible lines cannot
establish better ground. These results do not reject authored density controls.

**Retained:** order as a descriptor, explicit density with default 1.0, connected
scale-aware inspection. **Replacement:** discharge, material and confinement for
width; recharge/transmissivity as a separate drainage-density hypothesis (R18/R24).
Revisit against the original invariants plus complete-network coverage and actual
terrain, rather than accepting a less crowded screenshot.

## T03 - Preserve parent means with bilinear bubble detail

The [parent-cell experiment](2026-09-23-parent-cell-preservation.md) preserved nodes,
bilinear boundaries and cell means to Float32 rounding, with exact same-density
overlaps. It nevertheless lost source structure, moved authored heights by up to
29.161 m, changed shared samples across densities and worsened eight sampled
channel edges. Rejected for runtime use.

**Why / boundary:** preserving statistics relative to a bilinear reconstruction
was not preservation of the actual authored field or inherited hydrology.
**Retained:** explicit restriction tests, immutable-parent identity and overlap
controls. **Replacement / revisit:** condition on accepted parent landforms,
constraints and boundary flux; preserve supported structure through a deterministic
reconstruction and test coarse-scale agreement and channels together (D/R34/LE6).
The implemented residual-detail tools remain experimental, not accepted history replay.

## T04 - Evolve a landscape, then deliver its D8 nodes bilinearly

The [first history comparison](2026-09-24-landscape-evolution-reference.md) completed
22 cases and demonstrated useful chronology, uplift and resistance response.
Endpoint-descending diagonal channels still had internal rises of 37.51-45.48 m
in the 625 m examples; a 312.5 m case retained a 24.64 m rise. Cardinal controls
were clean. A 156.25 m, 197,505-node run stopped at the 60 s solver budget and
has no accepted final state.

**Why / boundary:** delivered interpolation and grid-direction sensitivity remain
problems even when solver controls pass. Float32 rounding was much smaller than
these rises. The budget stop is a cost observation, not proof the physical model
is wrong or that additional resolution would pass.

**Retained:** isolated Landlab reference, chronological forcing, analytic tests,
material accounting and complete/incomplete publication. **Replacement / revisit:**
co-evolving terrain/network plus hydrologically supported reconstruction; separate
process scale from export resolution. Revisit on fixed quality/cost gates. Do not
respond only by globally refining the grid or raising the runtime ceiling.

## T05 - Require routing diagonals in a triangle reconstruction

The [frozen comparison](2026-09-24-frozen-channel-reconstruction.md) retained all
1,183 full routes across 22 states. All 1,030 nodally nonascending routes had zero
sampled ascent at 100 m and 25 m station spacing. The 153 routes with nodal climbs
remained unresolved. This uses saved Float64-snapshot routing, not the first
history report's rerouted delivery graph; those totals are not a direct before/after.

**Why not adopted:** unchanged D8 directions, slope creases, off-grid target errors
and reconstruction-volume changes. Exact nodes are insufficient to preserve a
continuous authored height field. **Retained:** numerical control and full-route
accounting. **Replacement / revisit:** shared physical valley geometry with explicit
hard-target evaluation and a separate composition-volume ledger (B/R32/R48).

## T06 - Deform paths and ground together on a bounded mesh

The [physical-path comparison](2026-09-25-physical-channel-paths.md) retained all
1,183 routes without new uphill routes and reduced D8-aligned length to 56.99%.
All 22 cases failed sampled no-fill admission; 17 exceeded the diagnostic 30 m cut
limit. That limit was not the later native regional-cap implementation. Spacing
changes also moved many receivers/outlets at shared physical locations.

**Why / boundary:** geometry improvement required inadmissible surface changes;
native authoring/divide acceptance was not established. Long straight pieces and
creases remained. **Retained:** coupled geometry and receiver/outlet diagnostics.
**Replacement / revisit:** constrained construction before freezing the surface,
with generated relief distinguished from authored hard targets. Preserve this
fixed-state comparison rather than relabeling its cuts as geological erosion.

## T07 - Fit a downhill network into a fixed raster under native caps

The [network-led fit](2026-09-25-constrained-network-surface.md) preserved native
cut/no-fill bounds, protected heights and divide, and removed 34.7356 m of sampled
network ascent. Independent routing on a common 125 m grid still found 16 interior
sinks at 500 m process spacing and 19 at 250 m; zero of four heads reached their
intended mouths. The source had zero interior sinks.

**Why / boundary:** a descending guide is not necessarily a transverse minimum,
nor a connected valley that surrounding water reaches. More samples on that guide
cannot by themselves address the missing surface geometry. An ambiguous L1 fit
was replaced by a unique quadratic objective; fixing optimization ambiguity did
not fix capture.

**Replacement / revisit:** river-aligned cross-sections, confluences and coastal
transitions, checked in both the local field and delivered raster. Keep this hard
fixture as a control; use a separately identified fresh-construction case to test
movable automatic guides. Native limits are not silently widened (B/R48).

## T08 - Add bank endpoint inequalities to the fixed surface

The [bank experiment](2026-09-25-valley-bank-feasibility.md) added 525 physical
probes, nearest-reach junction ownership and a sea-level mouth taper. All endpoint
checks passed in feasible 500/250 m cases, but 255/273 inward cross-sections still
climbed and no head reached its mouth. Sinks changed from 16 to 15 at 500 m and
19 to 30 at 250 m. At 1,000 m, six bank pairs were locally infeasible under the
conservative bounds. A separate pinned-bed conflict had a verified shortfall.

**Why / boundary:** bank endpoint drops do not constrain the intervening surface.
The report's limited bilinear-cell argument explains a representation restriction
for exact straight oblique minima; it does not prove that rasters or other valley
representations cannot work. Conservative incident-cell bounds can over-restrict a
candidate; local infeasibility is not geological impossibility.

**Assumptions corrected:** constant positive bank drop at a zero-height mouth
contradicted the no-fill/nonnegative constraints; tapering removed that conflict.
Junction probes needed ownership by the nearest network reach. A solver returning
invalid ground is an execution failure, not evidence that authored inputs conflict.

**Retained / replacement:** keep conflict diagnostics and the manufactured positive
control. Stop expanding endpoint inequalities as the main strategy. Test connected
local patches, then bounded alternate representation if delivery itself remains
the blocker. An open-draining control still needs four captured heads and zero new
sinks; groundwater is not an exemption for this fixture.

## T09 - Construct connected local valleys then deliver a raster

**Tried:** analytic rounded valley unions, explicit coastal transitions and compact
hard-height support, followed by bounded Float32 raster projection. The
[report](2026-09-26-connected-valley-patches.md) keeps the fixed/native control and
a separately declared 600 m / 120 km3 fresh-construction envelope. The same guides
are retained; automatic relocation and history evolution are not yet tested.

**Measured:** fresh local routing on the common 125 m grid captures 4/4 heads with
zero interior sinks. At 250 m, raster delivery captures 3/4 with one sink; at
500/1,000 m it captures none. Fixed/native quality remains rejected. One fresh
local guide route, 29/525 inward sections and six bank endpoints still fail, so
successful capture does not accept the complete local field. Removing only the
mouth transition changes fresh local capture to 0/4 with four sinks. Repeat and
quarter-turn checks pass; no general-angle or world-scale result is claimed.

**Why / boundary:** coastal approach geometry affects actual capture. The remaining
250 m raster blockage is near a hard-height correction of up to 121.756 m; the
local field routes around that neighbourhood. This diagnoses a layout/support/
delivery interaction, not proof that the hard target is impossible or rasters are
unsuitable. Uniform refinement does not resolve the coarse failures by itself.

**Failed assumptions corrected:** node cut bounds allowed 376/262/210 inter-node
violations of a nonlinear fresh cap. Conservative incident-cell bounds remove
them without increasing budgets. Computing pin corrections from an unclipped
proposal also falsely rejected a feasible case; use the admitted field as the
base. Regression controls and hard-admission checks cover both errors. Genuine
constraint conflicts and unsupported overlapping pin cells remain explicit.

**Retained / replacement:** retain analytic sections, shared junctions, the
coastal transition, separate composition accounting and local/delivery diagnostics.
Keep production rejection. Next compare hard-target-aware layout and bounded
automatic guide movement, then one local reconstruction if delivery still blocks
quality. Preserve the fixed control, hard targets, coast/divide and declared
envelopes. Require guide/bank/capture acceptance on actual delivery before coupling
history, expanding the cohort or adopting LE3/WC2. Groundwater cannot hide this
open-drainage failure.

## T10 - Move automatic guides around hard height targets

**Tried:** explicitly automatic-edge relocation within a 1,500 m corridor, with
1,000 m pin clearance and at most 25% reach-length growth. The
[report](2026-09-26-hard-target-valley-layout.md) preserves every original vertex,
head, junction, mouth and reach ownership, the same broad source, all hard targets
and the previous fresh envelope. Fixed/native controls are rerun unchanged.

**Measured:** an 800 m detour changes 250 m raster capture from 3/4 to 4/4, interior
sinks from one to zero, unresolved guide routes from one to zero and interior
samples missing the coast from 1,115 to zero. Repeat and quarter-turn checks pass.
All hard-input gates remain intact. Local banks still have 21/575 inward failures;
the raster has 222/575, and coarser delivery still fails. The control's 525 bank
probes and candidate's 575 are different denominators, not matched-pair counts.

**Why / boundary:** a generated guide need not intersect the neighbourhood used
to represent a genuine height target. The correction remains large (126.313 m at
250 m), but the relocated channel avoids it. No target was lowered, and no river
outlet was dropped. Four-head capture and coast coverage do not establish bank
shape, prescribed basin areas or realism on unseen landscapes.

**Rejected alternatives:** a sine-squared candidate family could not clear the
pin within the same corridor; this was search exhaustion, not global infeasibility.
A sampled-envelope bed lift worsened local inward failures from 21 to 25 despite
fewer endpoint errors. It is not retained. The dated report preserves these
exploratory observations separately from the controlled final cohort.

**Retained / replacement:** retain bounded automatic placement and original-route
matching. Finish bank construction at heads/junctions/cap transitions; compare a
bounded channel-conforming reconstruction only after separating local shape from
delivery loss. Keep coarse failures and native-control rejection visible. Require
complete bank/guide/capture and held-out evidence before adopting this replacement
for default generation. M3-M4 can integrate the existing history reference
experimentally; this result does not justify a whole backend rewrite.

## T11 - Construct head and mouth sections before raster delivery

**Tried:** a cap-aware generated head adjustment ending at its first confluence,
perpendicular mouth sections and an explicit inland outlet wedge. The
[report](2026-09-26-valley-heads-and-mouths.md) keeps the same 575 bank pairs,
60.732 km graph, source, hard heights and 600 m / 120 km3 fresh envelope.

**Measured:** ordinary local inward/endpoint failures change from 21/5 to 0/0.
An added <=2.5 m bank check also passes the existing 1 cm tolerance; maximum local
rise is 0.006195 m. Local capture and the 250 m raster capture remain 4/4, with zero
sinks. All hard-input gates pass. Raster banks still fail: at 250 m, 217/575
ordinary and 241/575 dense inward sections, plus five endpoints. Coarser raster
capture remains zero. Twelve control cases retain their previous numeric hashes.

**Why / boundary:** the source-minus-cut floor tilted one clipped head bank
uphill; the coastal-plane taper tilted oblique sections away from the channel.
Changing the generated profile/section geometry fixes those local cases without
moving a hard target. Raster delivery still combines conservative cap projection
and interpolation loss. Sampled success is not a continuous or world-scale proof.

**Rejected alternatives:** local radial-envelope lifts remove the main head
failure but create new bend defects. A whole-tributary cubic taper passes 25 m
stations but fails three sections when sampled more densely. Quintic and
straight-tail-only tapers also leave defects. A linear taper adds constant grade
without the cubic's steeper middle. The first perpendicular-mouth trial left an
outlet-plane edge defect; preserving relief in the inland wedge removes it. Do
not restore any of these recipes as hidden fallbacks or loosen the dense check.

**Retained / replacement:** retain the local head/mouth component, matched bank
profiles, dense guard and original capture controls. T12 now isolates and reduces
cap-projection loss while preserving whole-cell protection. T13 subsequently
isolates representation loss and prioritizes a feature-preserving query boundary.
Keep production rejection until complete delivered bank/guide/capture, held-out
and broader orientation gates pass. No history, groundwater or product engine
was added by this experiment.

## T12 - Protect cell interiors with tighter delivery capacities

**Tried:** one-sided curvature allowances for the smooth rectangular-divide cap,
with constant whole-cell protection where subtracting the allowance would create
negative capacities. The [report](2026-09-27-cell-safe-terrain-delivery.md) derives
the bilinear interior bound and retains the same graph, local field, 575 bank
pairs, hard targets and fresh budgets. Five separate rectangle controls exercise
unaligned corners, a thin footprint and domain boundaries.

**Measured:** worst 250 m dense bank rise falls from 54.062 to 0.316 m; ordinary /
dense failures from 217/241 to 214/238, endpoints from five to two. Capture remains
4/4, with zero sinks and descending guides. Hard-input and cap checks pass;
repeat and quarter-turn delivery match exactly. The maximum envelope correction
falls from 93.045 to 18.175 m, but the hard-height correction remains 118.714 m.
Coarse routing and complete delivered bank quality remain rejected.

**Why / boundary:** the incident-cell minimum safely overprotected large areas.
A second-order interpolation allowance removes the large artificial head rise.
Bilinear sampling still displaces many bank minima, so smaller error amplitude
is insufficient. The proof covers this cap and bilinear field, not arbitrary
geometry, another interpolator, a native-limit policy or a new landscape.

**Rejected alternatives:** nodal caps alone violate the interior limit. Clipping
negative curvature-adjusted capacities also breaks the bound beside a quadratic
zero; valid nodes do not prove valid cells. The regression retains that explicit
counterexample. Omitting cap or hard-height projection is not a delivery option.

**Retained / replacement:** retain the tighter capacities and matched evidence.
T13 supplies representation evidence before the proposed large bilinear bank
solve: analytic alignment changes bank quality at similar height error, and
preserved features retain the local field through reopening. Keep local
feasibility checks and defer larger solves until their cell layout can represent
the requirements. Establish a new interior bound for any changed interpolator.
Complete delivered and held-out acceptance still precedes normal generation,
history coupling or LE3/WC2.

## T13 - Preserve features instead of reconstructing them from nodes

**Tried:** seven analytic valley orientations, bounded single-cell bank feasibility,
quadratic/cubic interpolation of the current network, and trusted numeric storage
of prepared valley fields. The [report](2026-09-27-feature-preserving-terrain-delivery.md)
records exact settings, sources, hashes and short timings. These are exploratory
ignored scripts; no supported benchmark API or product reader was added.

**Measured:** world-bilinear analytic sampling fails 114/238 profiles, while a
river-aligned strip fails none at similar maximum height error. On the network,
quadratic interpolation reduces dense failures from 238 to 25 but raises the
worst excursion from 0.316 to 5.195 m and loses all four outlets. Cubic and
bounded hard-pin variants also fail. Prepared-field saving/reopening exactly
preserves all 575 profiles, common Float32 heights and sampled quality gates at
three background spacings plus a quarter turn. Bilinear delivery after reopening
restores 267 / 251 / 238 / 238 failures.

**Why / boundary:** scalar height accuracy does not determine whether the intended
bed remains a transverse minimum. Higher-order interpolation can overshoot and
move extrema; restoring sampled caps and pins does not restore capture. The
one-cell witness supports the existing limited bilinear restriction, not global
infeasibility. Roundtrip equality preserves an already passing local fixture;
it is not unseen-landscape, safe-reader, tile/LOD or continuous-field acceptance.

**Disposition / replacement:** reject the tested generic spline substitutions.
The [guarded snapshot follow-up](2026-09-27-prepared-feature-snapshots.md) now
retains geometry and background parameters in a formal benchmark artifact, with
complete network reopening, deterministic identity and bounded validation. All
575 dense profiles and original metrics remain exact; query order, batches and
same-field tile/halo agreement pass. A returned-metadata ownership issue was
fixed and covered by a regression. Keep held-out geometry, irregular mouths and
real parent/detail filtering as the next gates. These overlap results do not
certify newly generated detail or replace raster authority. Prefer local analytic
patches, with channel-aligned strips or constrained triangles as measured
fallbacks. Defer the full bilinear solve behind representability checks. Current
Float32 DEM authority remains in force; any richer source requires an ADR and
coherent schema/consumer changes. Keep history and world integration gated.
Consult the user before longer tests; the completed probes took 0.855 / 20.625 s.

### T13 follow-up: wider geometry and product priority

The [world-to-terrain report](2026-09-27-world-to-terrain-workflow.md) records a
12.07 s exploratory probe of four modified layouts. Capture, hard controls and
bounds passed; 1–4 inward sections failed per case, with 0.106–0.606 m excursions
and no endpoint failures. The cause of each small excursion remains unisolated.
This is evidence against general acceptance of the current patch family, not
proof that the underlying feature is impossible. Retain analytic patches with
aligned strips or constrained triangles as fallback candidates.

The user chose a usable world-to-terrain workflow next. Further small bank tuning
is deferred behind major features; it remains required when adopting the new
construction model. The handoff uses the existing terrain engine and preserves
the Float32 authority contract.

## T14 - Treat semantic continent pieces as separate physical terrain

The [world handoff report](2026-09-27-world-to-terrain-workflow.md) records a
projection-centre change caused solely by splitting identical physical land
into unequal ownership pieces. Separate selection would additionally make an
internal border a coastline. Dissolve connected physical land before both
projection-centre selection and terrain generation. Exact mask and Float32
equality now guard equivalent ownership partitions.

Source offsets are a distinct cause: matching native border curves displaced
by 0.0015-0.0101 map units retained false coastal grooves even after connected
components were selected. Confirmed source repairs remove those slivers.
Globally buffering or closing every narrow water gap was rejected because it
would alter genuine straits. The native export API was unavailable; a precise
SVG segment correction preserved all other imported features. Private source
repair is not an automatic importer heuristic or a new erosion model.

The same batch replaced a false continental-area subtraction check with direct
MultiPolygon topology validation; its 0.05078125 m² roundoff was not overlap.
Retain these workflow fixes while keeping regional projection support and
physical generation acceptance as separate next gates.

## T15 - Use inward region fades as a complete geological partition

The [landform transfer report](2026-09-27-geological-landform-guidance.md) records
a 5.088 s public paired build with the same world, coast and mask. Explicit controls
reach the terrain and preserve nested overrides, but visible polygon-shaped rims
remain. Every inward weight reaches zero at a shared recipe boundary, exposing
the generic background; equal settings avoid this after dissolving.

The [replacement comparison](2026-09-27-shared-landform-blending.md) now separates
coverage fades from neighboring-recipe weights. Its flat plain/plateau seam changes
from 4,000 m background to 1,225 m between 250/2,200 m recipes; the transect is
monotone and remains inside their height envelope. Blank holes and established
enclave interiors are retained. Accept this composition fix, not general realism.

A normalized signed-distance-only probe gave 513.514 m in an established 250 m
enclave, because the parent's wider support retained weight. Reject that variant;
the implemented core term suppresses outside recipes in established interiors.
Slope bounds, thin-region feedback and connected terrain structure remain open.
Scientific cut-limit support changes the range/lowland fixture to @2; @1 physical
bank results stay historical. Calibrated forcing and aging remain separate.

The full-suite follow-up records a mixed drainage result on regional seed 42:
mean cardinal excursion increases from 0.165912 to 0.237557 m with the changed
river population, while the worst all-direction excursion falls from 55.721313
to 48.008911 m. The old 70% relative floor-improvement check fails; the current
empirical envelope requires a two-thirds reduction plus a 0.25 m absolute mean
ceiling. This is an explicit threshold revision, not a repaired floor algorithm.
A smooth-core-union trial still misses the original ratio and is not adopted.
The isolated diagonal correction's aggregate ratio also misses its old target
(0.402153 versus 0.4), but its affected diagonal population improves by 75.17%
while cardinal channels are exactly unchanged. Apply that stage's existing 60%
reduction gate to diagonals, with unchanged counts/cardinals and combined-mean
improvement required. This scopes the empirical gate; it is not a runtime repair.
Preserve all hard physical/canonical gates and the unresolved drainage-quality
status; do not report a complete realism gain from smoother regional borders.

Triangulation and implicit category/age conversion were rejected design shortcuts,
not executed failed experiments. Triangulation would introduce artificial fade
edges under the current rule; age conversion would invent unreviewed coefficients.

## T16 - Use proximity alone to own connected ridge profiles

Point-derived profiles remain useful, but absolute points can affect multiple
nearby lines and relative points detach on an ambiguous nearest match. This is
an ownership limitation for deliberate peak/pass/spur control, not a failed
physical model. [Line-owned profiles](2026-09-27-line-owned-terrain-profiles.md)
now provide explicit ownership and reuse the existing shape-preserving curve.
A replacement noise carrier was considered but not executed or adopted.

The public connected example exposes a remaining composition limit: its requested
2,800/1,400/2,400 m crest controls deliver about 2,482/1,429/2,173 m after other
line influences combine, although isolated-line controls meet their targets.
Do not treat ownership as exact network junction solving. Shared junction
constraints and generated branching were left open at that checkpoint; no acceptance
threshold was relaxed. T17 below implements the next absolute-ridge slice; the
river/history gates remain open.

## T17 - Blend ridge targets and round connected lines independently

Gaussian ridge-target averaging shifted authored crests by up to 244.800 m in
the bounded scale comparison. Independent smoothing moved a main ridge 75 km
away from an attached branch at a corner. The
[shared-crest follow-up](2026-09-27-shared-ridge-crests.md) replaces target averaging
with stable distance-based crest ownership and preserves exact authored contacts
through smoothing. Tested control errors and that contact gap fall to zero.

Retain the limited scope: explicit absolute ridges only. Conflicting contact
heights and ambiguous loops/shared spans are rejected; no snapping, automatic
graph editing or branch generation is implied. Valleys and hard points keep
later authority, and broad smooth shoulders/sharp junction turns remain visible.

## T18 - Take extrema from the nearest four context-distance cones

The first M1 transfer bounded a query by taking the maximum lower cone and minimum
upper cone from the four active support vertices. Each interval was conservative,
but changing the bilinear stencil could abruptly replace the winning vertex. A
public vertical-edge probe only `0.000002 km` wide produced a
`16.078688316394533 km` upper-bound jump. The bound was valid and unsuitable as a
continuous terrain input.

The accepted replacement convex-combines the four valid per-vertex intervals with
the same nonnegative bilinear weights used for continuous context fields. At the
geographic-to-support step each source node contributes lower
`shore - source_error - distance` and upper `shore + distance`; at metric queries
the retained node's lower/upper interval replaces that source form. Clamp the
weighted lower bound to zero. A departing vertex's weight reaches zero at a cell
edge, so adjacent stencils meet continuously while the convex combination retains
conservative validity. The corrected edge probe differs by only
`0.000002333701814904998 km`.

The intervals can be slightly wider than pointwise extrema. Keep exact projected
vector distance and use `min(vector distance, context upper bound)` for the coastal
terrain consumer. Do not use the lower bound as a height driver: that would create
a false zero-height strip near coarse support. Revisit only if tighter continuous
bounds have a measured terrain benefit and preserve the same proof, edge continuity
and source-coast zero behavior. See the
[M1 report](2026-09-28-context-bound-rough-terrain.md).

## T19 - Find ice extent as a fixed point of balance flux and a plastic profile

**Hypothesis.** Ice lies where accumulation routed down its surface outlasts melt,
on Nye's perfectly plastic profile from the resulting margin; iterating the two
reaches a self-consistent extent without time stepping.

**Control and inputs.** Aethelara 800k nodes, the planet's climate and relief, the
same mass balance later adopted (Ohmura melt, lapse, drying, albedo share).

**Outcome.** No fixed point. About 345 margin nodes flipped every iteration as
routing changed with the surface. A monotone growth phase settled after 95
iterations at 8,164 nodes; trimming unsupported nodes then removed 587, 364, 172,
107, 77, 62, 46, 43, 41 and 35 nodes in turn without stopping.

**Diagnosed cause.** Extent is binary while flux, surface and routing respond
continuously: removing a margin node lowers its neighbours' plastic surface and
their balance, which unsupports the next ring.

**Disposition.** Replaced by shallow-ice time stepping, which converges by time
([ADR-0093](../adr/0093-ice-sheets-from-mass-balance-and-shallow-ice-flow.md),
[report](2026-10-13-ice-sheets.md)). Revisit only for a steady-state solver with a
continuous margin (for example a level set) that is cheaper than time stepping.

## T20 - Straighten regional rivers in routing, over display detail or by a plain warp

**Hypothesis.** Level-1 windows drew big rivers as long straight runs with
right-angle junctions because of how they are routed, so routing changes or
routing over the display relief would bend them.

**Control and inputs.** Aethelara `planet-3200k-v30`, 56.869° E 30.703° N, a 250 km
level-1 window of 1,024 pixels (488 m) and a 20 km level-3 window; every
`grid_flow` input captured from the unchanged window. Measure: the share of the
cells of rivers over 2,000 km² in runs of ten or more identical D8 steps.

**Outcome.**
- Flat resolution (Barnes et al. 2014: towards the outlet, away from the shore)
  across filled depressions: 0.15 to 0.19 at level 1, 0.07 to 0.20 at level 3,
  with 45° and 0° lines and parallel channels across flats. Fill cells with an
  exactly level neighbour were 21 river cells at level 1 and none at level 3.
- Routing over the display relief before carving: 0.15 to 0.08, but filled
  ground rose from 1 % to 11 % of the land, small rivers changed course and a
  deep tile valley kept a straight 40-pixel tributary.
- A plain domain warp of the tile relief (`displace`, rotated octaves from 20 km):
  0.156 to 0.128 at steepness 0.08; at 0.15 (0.102) its Jacobian fell to zero,
  so it folds the relief.

**Diagnosed cause.** Fill depth along the straight runs is 0. Rivers follow valleys
of the triangle-linear tile relief, straight between nodes and along straight
12-30 km planet river segments the tiles inherit; 72 % of the run cells lie on
creases and 23 % on planar facets. Routing reproduces them faithfully.

**Disposition.** Relief is sampled along an area-preserving curl-noise flow, which
bends valleys without folding, filling or moving heights
([ADR-0106](../adr/0106-wind-regional-valleys-below-the-tile-mesh.md),
[report](2026-10-12-straight-display-lines.md#straight-regional-rivers--2026-10-18)).
Revisit routing only with relief that resolves valley floors below the window
pixel, and display-relief routing only with a lake and pond policy for its hollows.

## T21 - Hold regional basin plains at the sampled parent surface, or refill them

**Hypothesis.** Regional tiles eroded sediment-basin plains far below the planet's,
which fills its basins after erosion. Holding basin land at the parent surface
while tiles erode, or filling it back up afterwards, would keep the plain, and the
big rivers crossing it would carry through every level.

**Control and inputs.** Aethelara `planet-3200k`, a 36 km box at 56.869° E
30.703° N whose planet surface is a basin plain (1,187 of 1,369 points in full
basins), and 20 km province and local windows there; tiles of levels 1-3
regenerated in scratch caches for each variant, first on the level plains of
`sphere-mesh-stream-power-v30` (681 m), then on the graded plains of `-v31`. On
the test planet, the four largest inland rivers crossing full basins, in 400 km
tiles of 20 km spacing.

**Outcome.**
- A floor at the smooth parent surface held the plains, but 49, 56 and 59 m above
  the planet's at levels 1-3. Where the plain's river leaves between two planet
  nodes, the tile samples a 60-80 m sill from a higher third corner. The floor
  held it, and the two level-1 tiles filled the plain to their own sills at 741 m
  and 760 m.
- Breaching those sills in the floor alone left the level-1 plain 18 m high
  (median 19 m above the parent). Tiles started from the unbreached surface, so
  the plain first filled like a lake, and at 3 % of the erodibility it kept most
  of the fill.
- Breached floor and start held the plains within a few metres at every level,
  but on v30's level plains nothing marked a river's course. In the province
  window's parent the 160,000 km² river entered 53 km from the centre and left
  through the boundary 14 km away, five nodes later, and the province window
  drew no big river. Each level routed the flat plain in its own flood order.
- Channels as deep as a narrow channel lowers a coarse cell on average (0.2 m at
  level 1 for that river) were lost among the plain's centimetre differences once
  the next level resampled them; channels cut through nodes merely near a link
  had gaps that let the water out sideways. Full bankfull channels traced along
  connected paths, walls at level parents' entries and floodplain corridors kept
  the river in the province and local parents, but on v30 the windows still lost
  it: their relief put the channel's crossing of the rim 2.5 km from where the
  parent's river enters, beyond the entry walls.
- On v31's graded plains the same design carried the river across the province
  and local windows (161,000 and 155,000 km² entering, one exit each). Cutting the
  channels along the planet's links at every level instead lost it again 146
  pixels (6 km) after the province window's entry.
- Filling basins back to the parent's plain after erosion, on the test planet,
  dammed valleys just outside basins that had graded to the eroded plain: up to
  5 nodes per tile filled flat by 8-29 m on two of four tiles. The margin stayed
  lower than with a floor during erosion (-41 m against -29 m mean).

**Diagnosed cause.** A sampled parent surface does not drain on a finer mesh, and
a plain that barely erodes keeps every metre it is started or filled above its
outlet. A plain held level carries no river course to the level below; HEAD's
tiles carried it by incising the plain hundreds of metres. A fill to a tile's own
spill level, as the planet fills, was not run: the spill would be set by each
tile's ring, the disagreement being removed.

**Disposition.** The planet grades its basin plains (D06,
`sphere-mesh-stream-power-v31`). Tiles start from the breached parent surface
with the parent rivers' bankfull channels cut in, basin land never erodes below
the planet's plain (less a margin ramp), basins start without random roughness,
and level parents wall their boundary where planet rivers enter
([ADR-0086 revision](../adr/0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-19-sediment-basin-plains)).
At levels 2-3 the river then took another branch at a junction than level 1 and
the planet; [T23](#t23---carry-a-big-rivers-course-through-every-regional-level)
carries one course through every level.

## T22 - Draw planet relief between nodes with cubics or along a twist

**Hypothesis.** World maps draw the planet triangle-linear between nodes, so
Standard builds show triangular facets. Clough-Tocher cubics, with or without the
regional clip, or ADR-0106's area-preserving twist would rebuild ground closer to
the truth than straight lines do.

**Control and inputs.** `benchmarks/planet/interpolation.py`: a truth is sampled
at the nodes of coarse meshes of 200k and 800k nodes (50 and 25 km) and rebuilt
in 600 km windows at 1/8 of the spacing. The control is linear. There are two
truths:
- a 3.2M-node (12.6 km) build of the synthetic test world, eight windows;
- NOAA ETOPO 2022 at 60″, nine Earth windows, downloaded for the run and deleted
  afterwards.

The pass rules were set before the runs
([report](2026-10-19-curved-interpolation.md#pass-rules-set-before-any-run)).

**Outcome.**
- **On Earth, curves are less accurate and look no closer.**
  - Height error is 4.7 % and 8.8 % higher for the clipped cubic, 6.4 % and
    11.1 % for the free one.
  - Hillshade likeness stays at 0.34 (+0.001 to +0.004), and slope error rises
    1–2 %.
  - At 50 km the clipped cubic matches rivers worse (F1 0.408 against 0.435).
- **On the synthetic planet, cubics are slightly better.** Hillshade likeness
  rises by 0.026–0.040, river F1 by 0.07–0.13 and height error falls up to 3 %,
  but slope error drops by at most 1.2 %, short of the 5 % rule.
- **Mesh lines go in both.** The crease ratio falls from 10,000–29,000 to about
  2. Straight contours fall from 0.23–0.29 to 0.05–0.09, against the truth's
  0.014 on Earth.
- **The twist is the least accurate.** It is the least straight (0.04–0.05), but
  height error rises 8–21 %, hillshade likeness falls by 0.05–0.16 and river F1
  by 0.04–0.08. Points move 16 km at 50 km and 8 km at 25 km.

**Diagnosed cause.** Earth's relief between 25–50 km nodes is rough: valleys
5–15 km apart make node heights nearly independent samples. Cubic gradients
estimated from neighbours therefore add slope in the wrong places. The generated
planet is smoother below its spacing (height error 45 m against Earth's 212 m at
50 km), so it favours cubics a little. Hillshade likeness stays low (0.34 on
Earth) for every interpolant, because what the eye sees lies below the spacing.
A twist moves features away from the drawn rivers, which are routed on the
unwarped mesh.

**Disposition.** Rejected trial for world-map relief (D33). The planet keeps
triangle-linear relief (ADR-0085), with no planet-level twist. Regional seeding
(ADR-0086) and the regional twist (ADR-0106) are unaffected. Revisit when nodes
carry more than heights (erosion's own slopes or receivers for a Hermite surface),
or to compare a smoother look for Standard builds against display detail.

## T23 - Carry a big river's course through every regional level

**Hypothesis.** On a held basin plain the province and local maps took a big river
by another branch than the region and the planet. If every level cut its channels
along the planet's links where its relief carries them, instead of along its level
parent's own routing, tiles would agree on the channel and every level on the
course.

**Control and inputs.** Aethelara `planet-3200k-v31`; a 30 km region window and
20 km province and local windows at 56.869° E 30.703° N, where the 160,000 km²
river crosses a full basin; tiles of every level regenerated in scratch caches
for each variant. A course is the routed path from the biggest inflow, compared
with the region's inside 20 km of the centre (control: 5.1 and 4.5 km from it on
average at levels 2 and 3, leaving the circle 30 km from where the region does).
On the synthetic test planet, two overlapping finer tiles and six pairs of
overlapping level-1 windows.

**Outcome.**
- Channels along the planet's links, at tile nodes carried into the planet's
  relief through the level parents' warps, brought the two province tiles over
  the window from 3.1 km apart on average (10.6 km at most) to 0.7 km.
- Each link had been traced by stepping to the neighbour nearest its receiver,
  which drifts off the line by about an eighth of the link's length: 20-30 km on
  a 200 km test link, 1.4 km on a 12 km planet link. Tracing along the line, and
  from where a link crosses into the region, brought the tiles to 0.5 km.
- With those channels the province window's river ran back out of the window
  7 km after its entry. Routing the level parents in the same channels changed
  nothing there, nor later in the final design, and was dropped. Sampling the
  held plain at the same carried points let the river cross the window, but by
  the northern branch, 7.4 km from the region's course on average.
- That branch came from a dam. Downstream, the planet's river runs between nodes
  at 682.9 and 681.1 m through a gap between hills, where the smoothly sampled
  surface rises to 710-714 m. Province tile 7577 (252 km across) breached its
  plain over its own ring beside the river's entry, at 695.7 m, and filled
  2,400 km² to that level; region tiles, 1,260 km across, breach the sill. Beds
  graded along each link, from the planet's height at one node to the next less
  the channel's depth, removed the dam. Province and local courses then lay 2.0
  and 1.2 km from the region's and left the window within 0.5 km of where it does.

**Diagnosed cause.** Each level re-derived a big river's course: tiles from their
level parent's routing on a lattice of their own, and their plains from the
outlets their own rings offered. A held plain carries only the planet's links and
heights, so every level has to take both from the planet, at the same places.

**Disposition.** Every level traces the planet's links of at least its process
area at its nodes carried into the planet's relief, samples the held plain there,
and grades channel beds along the links; level parents let planet rivers in where
the warps carry them
([ADR-0086 revision](../adr/0086-regional-planet-detail-from-blended-tiles.md#revision-2026-10-19-one-river-course-through-every-level),
`planet-blended-tiles-v18`). Not chosen: channels along the planet's links at the
nodes' own places (T21), stepping towards the receiver, and routing level parents
in the channels. Rivers the planet does not resolve still take each tile's own
course; revisit with tile boundary exchange.

## What the failures change

Preserve the feature goals: believable rivers, geological aging, useful zoom detail
and varied valleys. Change the construction method when an experiment isolates a
representation or input-policy restriction. Separate authored requirements from
procedural guesses before fitting; test coupled relief and network evolution before
freezing a final DEM. Keep the application and Python implementation boundaries.

Groundwater, karst and lateral erosion are **new, untested hypotheses here**, not
explanations established by T01-T13. They need independent controls and budgets.
The [reassessment's staged experiments](2026-09-25-groundwater-and-terrain-architecture.md#implementation-sequence-and-stop-rules)
retain proposed comparisons and larger-change criteria. The current M1-M8 plan
selects when to run them; its integration priority supersedes that older ordering.
