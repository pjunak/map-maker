# Groundwater, canyon formation and terrain architecture reassessment

2026-09-25. **Research and plan revision; no new terrain solver or groundwater
simulation executed.** Reviewed implementation baseline: `97ae47a`. Existing
failure measurements are indexed in the living
[method decision register](terrain-method-decisions.md); their dated reports
remain authoritative. The [strategy](../strategy/README.md) owns execution order.

## Recommendation and evidence boundary

Keep geological aging, but change the next experiment from adding isolated river
constraints to constructing a connected landscape. Generated initial relief and
automatic channels should be able to evolve together before publication. Authored
coasts, final heights and protected boundaries keep their declared meanings.
Compare river-aligned local valley patches first; investigate another process
representation only if measured delivery limits justify it. Keep Python and the
existing workbench, world import, immutable parents and Float32 DEM products.

Groundwater is a useful addition for drainage density, springs, losing streams and
some headward erosion. It cannot justify arbitrary underground exits for unwanted
raster pits. For varied canyons, surface incision, uplift/base-level history, rock
layers and lateral bank erosion are a broader first target. Karst dissolution and
cave collapse are separate capabilities, conditional on suitable geology.

These are project design inferences from the sources below and the failed local
experiments, not a demonstrated quality gain. Neither the groundwater nor canyon
proposal has passed a numerical or visual comparison in Map Maker.

## What the research supports

### Groundwater can change which streams survive

[Luijendijk (2022)](https://esurf.copernicus.org/articles/10/1/2022/) couples
groundwater capture and incision: a deepening stream can drain neighbouring
catchments and dry their channels. Higher transmissivity reduced drainage density
in the studied humid setting. Its model is a two-dimensional aquifer cross-section
with straight parallel streams, steady groundwater and simplified surface flow;
it does not generate a complete branching world network. Use it to motivate a
controlled density experiment, not a universal density formula.

[Romon, Lajeunesse and Metivier (2026)](https://esurf.copernicus.org/articles/14/517/2026/),
published 7 July, demonstrate branching seepage-driven networks in a laboratory
aquifer and relate growth to groundwater supply. This supports a headward-erosion
mechanism. The erodible laboratory material and recharge arrangement do not
calibrate hard-rock canyons or whole continents.

**Project implication:** test substrate and recharge alongside the current
area/slope initiation rule. Show actual active discharge separately from potential
valley geometry and cartographic visibility. A dry valley need not disappear from
the terrain; a smaller river can remain hidden at overview scale without changing
its physical existence.

### Underground flow follows hydraulic head

[USGS groundwater principles](https://pubs.usgs.gov/circ/circ1139/htdocs/boxa.htm)
and [stream-aquifer exchange](https://pubs.usgs.gov/sir/2012/5062/section4.html)
describe head gradients and gaining/losing reaches. Water can move locally upward
in elevation while moving downward in total hydraulic head. Subsurface catchments
can differ from surface catchments; a surface ridge is not automatically an
impermeable aquifer boundary.

**Project implication:** surface receivers and subsurface links need separate
identity and accounting. Pressure-driven flow is not permission to ignore an
unexplained surface barrier. A resolved connection needs inlet/outlet elevations,
head, capacity, storage and geology. A one-height-per-position DEM cannot represent
a cave roof and floor; a portal/conduit graph can precede optional 3-D cave geometry.

### Canyons need more than downward cutting

[Langston and Tucker (2018)](https://esurf.copernicus.org/articles/6/1/2018/)
model lateral bedrock erosion alongside incision to address valley width and strath
formation. Landlab exposes this through
[LateralEroder](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.lateral_erosion.lateral_erosion.html).
This is a candidate mechanism for width, not proof that our reconstruction will
preserve its banks or channels.

[Lamb and colleagues' Malad Gorge study](https://lamb.caltech.edu/documents/19636/Lamb_et_al_2013_PNAS.pdf)
links particular amphitheatre-headed basalt canyons to megaflood erosion rather
than the previously proposed seepage origin. Canyon shape alone is therefore
insufficient to choose groundwater sapping. This does not prescribe megafloods for
all canyons or add a flood solver to the immediate batch.

**Project implication:** compare plateau incision after uplift/base-level change,
contrasting resistant layers and bounded lateral retreat. Keep bank collapse,
seepage and exceptional floods as explicit later mechanisms. Dissolved rock,
mechanically transported sediment and imposed terrain composition need separate
ledgers. [SPACE (Shobe et al., 2017)](https://gmd.copernicus.org/articles/10/4577/2017/)
provides a conservation-based bedrock/alluvium reference for the sediment stage.

### Karst is a coupled network problem

[Perne, Covington and Gabrovsek (2014)](https://hess.copernicus.org/articles/18/4617/2014/)
combine conduit hydraulics, solute transport and dissolution, including transitions
between pressurized and free-surface flow. Their work shows why underground paths
and their enlargement require more than a hidden downhill line.

The [USGS Conduit Flow Process](https://www.usgs.gov/software/conduit-flow-process-cfp-program-simulate-turbulent-or-laminar-groundwater-flow-conditions)
couples porous groundwater and discrete pipes, or uses preferential-flow layers,
with laminar/turbulent behavior. This is a MODFLOW-2005 extension, not a built-in
MODFLOW 6 feature. It is a possible future hydraulic reference, not a terrain or
cave-dissolution generator to drop into our current loop.

**Project implication:** start R24 with explicit suitable substrate, losing-stream
portals, spring destinations and a conservative connection. Test dissolution only
after this hydraulic contract works. A closed or dry basin remains a legitimate
alternative; never insert a conduit merely because the surface candidate fails.

### Terrain and drainage can be constructed together

[Cordonnier et al. (2016)](https://diglib.eg.org/items/13e52c36-0200-4652-aacf-17aa3098c5fd)
combine uplift and stream-power erosion on a stream graph, then construct a DEM
using graph-derived landform kernels. This supports separating process/network
state from final raster representation. The primary abstract was reviewed; the
large author PDF could not be fetched in this session. This is not a reproduced
implementation or evidence that its method satisfies our authored constraints.

[Genevaux et al. (2013)](https://cs.purdue.edu/homes/bbenes/papers/Genevaux13ToG.pdf)
and the existing [bank report](2026-09-25-valley-bank-feasibility.md) motivate local
river, cross-section and junction primitives. The next comparison should construct
these features as terrain, then test what survives quantization and reconstruction.
A visually smoothed polyline is insufficient.

For accidental pits, [Lindsay (2016)](https://jblindsay.github.io/ghrg/pubs/2016_Lindsay_HP.pdf)
provides constrained/selective breaching alternatives to filling everything.
Treat a bounded breach or reroute as a generation-stage comparator with unchanged
protected regions and real-basin semantics. It does not establish realistic
landscape evolution or authorize cutting every depression to the sea.

## Existing tools and local availability

| Option | Best use in this project | Evidence and boundary on 2026-09-25 |
|---|---|---|
| Landlab GroundwaterDupuitPercolator | Small unconfined-aquifer and return-flow reference | Import/API checked locally; no model run. Shallow, depth-integrated approximation, not conduits or dissolution. |
| Landlab LateralEroder and Lithology | Layered canyon/valley-width experiment | Both import locally; calibration, coupling, stability and delivered geometry untested. |
| Landlab SpaceLargeScaleEroder | Later conserved mobile-sediment comparison | Imports locally; existing LE4 gate remains. No new sediment experiment here. |
| GOEMod | Reproduce groundwater-capture hypothesis | Published research code; not installed or run. Cross-section assumptions limit direct reuse. |
| MODFLOW / CFP | Independent groundwater/conduit oracle if simpler models fail | Established specialized flow tooling; no local execution or packaging validation. Too much scope for the first density experiment. |
| Graph/local patches; optional constrained mesh | Process-aware terrain construction | Papers plus our rejected fits motivate it; no new patch/mesh implementation in this batch. |

The existing ignored reference environment imports all four listed Landlab classes
under Python 3.14.7 / Landlab 2.11.0. Checked with `inspect.signature` after importing
from `landlab.components`. Imports establish availability only, not correctness,
performance or compatibility when components are coupled. No packages were added.
The [dependency register](../DEPENDENCIES.md) retains the MIT Landlab versus GPL
`py-richdem` transitive-stack distinction; the full stack remains research-only.

[GroundwaterDupuitPercolator's documentation](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.groundwater.dupuit_percolator.html)
assumes shallow unconfined flow over an impermeable base, with small vertical-flow
and capillary effects. It uses depth-integrated flux and adaptive stepping. Default
units are metres and seconds. It is not a full variably saturated 3-D groundwater
model; component defaults must not become geological calibration by accident.

[GOEMod's current license](https://github.com/ElcoLuijendijk/goemod/blob/master/LICENSE.txt)
is LGPL v3, whereas the 2022 paper describes its code as GPL v3. Record the chosen
revision and its actual license before any reuse; the publication alone is not a
current dependency audit. No GOEMod source was copied or adopted here.

Established mathematical tools still require project-specific evaluation. The
2026 laboratory results and graphics constructions are useful research directions;
neither substitutes for our source constraints, Float32 checks or held-out maps.

## Proposed structural change

Separate three responsibilities within the existing domain/pipeline/application
layout. These are proposed boundaries, not new modules or a public schema yet:

1. **Authored specification:** coast/land mask, present-day hard targets, persistent
   boundaries, initial relief, epoch forcing, material hypotheses and soft guidance.
   Every input has a role; generated noise and automatic guides are not hard targets
   merely because they were computed first.
2. **Process state:** evolving elevation, supported rock layers and the water/network
   state needed by the selected model. Start with surface evolution; add aquifer
   storage/heads or conduit edges only for an explicitly supported experiment.
   Surface and groundwater networks exchange water but are not the same graph.
3. **Published terrain:** deterministic reconstruction, accepted Float32 DEM,
   supported water products, provenance and immutable parent state. Sampling or
   zoom does not advance history. Failed composition/rerouting prevents publication.

Use a coarse bounded evolution state for broad structure and river-aligned local
patches for valley, junction and mouth geometry. Compare both continuous patches
and the actual raster reconstruction used by consumers. A process mesh or graph
may be internal while the delivered DEM stays authoritative; changing that output
contract requires its own evidence and ADR. Avoid a generic plugin/solver framework.

The [existing input-role policy](../strategy/landscape-evolution.md#authored-intent-and-geographic-boundaries)
already distinguishes initial relief, forcing, persistent boundaries and final
hard targets. The change is to exercise it in the next comparison, rather than
continuing to fit every automatic path into an immutable procedural surface.

The native automatic-incision cap is also not a geological cumulative-erosion law.
[Regional incision](../../src/map_maker/terrain/pipeline/landforms.py) limits a cut to
a fraction of recipe relief; the [hydrology budget](../../src/map_maker/terrain/pipeline/hydrology.py)
derives a background ceiling from elevation and variability.
Keep those exact limits on the existing fixed-state comparison. A **separate fresh
construction/history case** needs a prospectively declared elevation, displacement,
volume and cumulative-process envelope. It must preserve genuinely authored hard
limits. Its improvement is not a pass on the old fixed-source fixture, nor may its
construction volume be reported as physically simulated erosion.

Do not replace every raster algorithm now. If aligned local patches fail only at
raster delivery, test a bounded channel-conforming triangulation or different
reconstruction against the same figures, authoring and cost gates. Smooth splines
or RBF interpolation alone do not guarantee monotonic channels or absence of sinks.
Retire superseded production code only after one replacement is accepted; keep
reproducible comparison code as research evidence, not a legacy runtime mode.

## Minimum mathematical contracts

For a first porous-aquifer comparator, use explicit units and a documented
approximation. One flat-base, unconfined model can be written as:

```text
h = hydraulic head [m]; b = impermeable base elevation [m]
T = K_h * max(h - b, 0)                  [m^2/s]
q_g = -T * grad(h)                      [m^2/s, depth-integrated flux]
S_y * dh/dt = R - ET_g - q_ex - div(q_g) [m/s]
```

Here K_h is hydraulic conductivity [m/s], S_y is dimensionless specific yield,
R is recharge and ET_g groundwater evapotranspiration [m/s]. q_ex is distributed
exchange positive toward the surface. This is an illustrative proposed comparator,
not an exact transcription of every Landlab slope/base option. Resolve dry cells,
seepage faces and boundaries explicitly. Stream exchange can use conductance times
`(h - stream_stage)`; convert the resulting volume rate to the same control areas.
An infiltration limit partitions supplied rainfall; it must not create additional
recharge on top of rainfall already counted as surface runoff.

The combined ledger is change in surface plus aquifer storage = precipitation and
boundary inputs minus evapotranspiration and boundary outputs. Stream-aquifer
exchange cancels exactly once. A later conduit ledger joins the same balance.
Use seconds for hydrological steps and explicitly convert geological durations;
quasi-steady groundwater between slow erosion steps is allowed only after a
relaxation/time-scale comparison, not by assuming all storage is instantaneous.

For incision, start from the existing stream-power reference, with discharge and
material-dependent resistance explicitly identified. Later mechanical sediment
transport and dissolved mass are distinct outputs. Groundwater exchange may alter
surface discharge; head differences alone are not a canyon erosion-rate law.

The present no-rise channel gate belongs to its declared gravity-routing model.
Real flow over a locally rising bed can involve water depth/backwater; groundwater
can also be pressure-driven. Supporting either exception requires an explicit
stage/head and energy/storage model. Do not weaken current checks without that
capability, and do not infer hydraulic behavior from a blue line.

## Implementation sequence and stop rules

These experiments reuse `benchmarks/evolution` and existing public controls. IDs
below subdivide B/C/R24/LE work; they do not establish another parallel roadmap.

| Stage | Work and unchanged control | Acceptance / stopping decision |
|---|---|---|
| B1 - Input roles and connected local patches | Keep the current two-catchment, four-head fixture and exact hard constraints. Build explicit cross-sections, junctions, mouths and bounded transitions. Add a separately identified fresh-construction case with generated guides movable inside declared corridors. | Admitted fixed open-draining cases: all four heads captured, zero new interior sinks relative to the original source, hard heights/divide/native caps preserved. If impossible, retain the witness and record failure; success on the fresh case cannot erase it. |
| B2 - Representation and co-evolution decision | Compare accepted patch behavior against delivered Float32 routing, then integrate with the existing two-epoch reference. Only if delivery is the isolated blocker, compare a small channel-conforming mesh/reconstruction. | Hold-out seeds, non-cardinal orientation, process spacing, complete catchment coverage, worst-case profiles and cost. A representation change needs evidence of improvement before broader adoption. |
| G1 - Groundwater density experiment | In the existing isolated environment, first test a flat-base aquifer, dry/no-recharge and no-flow boundaries. Then compare low/high transmissivity under identical recharge, initial terrain and declared streams. | Close combined storage/flux balance; compare an analytic steady solution and space/time refinement. Only then measure channel survival/spacing, spring flow and erosion. No groundwater added to failing B1 control. |
| C1 - Layered canyon experiment | Following B acceptance, compare the same plateau under constant versus changed uplift/base level, with homogeneous versus layered resistance and vertical-only versus lateral erosion. | Coherent rim/width/bed geometry, flow capture, bounded mass export, sensible layer transitions and no grid-oriented cliffs. Do not add unlimited downcutting or treat one canyon silhouette as process validation. |
| K1 - Explicit karst connection | After G1 water accounting, add suitable substrate, one losing-stream inlet and one spring, a head/capacity-limited conduit and a no-conduit control. | Inlet/outlet/storage balance, no invented flow without supply, supported head loss and stable exchange. Keep valid closed basins. Chemical enlargement, roof collapse and 3-D cave rendering remain separate experiments. |
| Integration | Adopt only accepted mechanisms into one generation path, update contracts/provenance/editor, then WC2-WC4 and D/WC5. | Reproduce authored constraints, frozen parents, common world time and inherited boundary flux. New inputs are pre-generation only; no output editing or compatibility branches. |

B1 is next. After B2 selects a useful surface path, run G1 as a small independent
mechanism comparison; C1 does not depend on karst or full groundwater acceptance.
Detailed chemistry and whole-world groundwater are not prerequisites for rough
terrain. The authoritative strategy can admit proven subsets without waiting for
every research extension.

For G1's simplest analytic check, set aquifer base to zero, uniform recharge R,
constant conductivity K, no-flow divide at x=0 and prescribed head h_b at x=L.
The steady solution satisfies `h(x)^2 = h_b^2 + (R/K)*(L^2-x^2)` where the aquifer
remains unconfined and below the surface. Freeze numerical tolerances and budgets
before the erosion comparison. Include a paired zero-recharge run with the same
boundary heads; drain initial storage honestly rather than expecting immediate
zero flux. No-flow plus zero recharge and uniform head is the zero-flux control.

Retain full network coverage and intended terminal classes in all comparisons.
A separate lake/dry-basin/karst fixture can terminate in storage or an explicitly
modeled spring system; an open-draining control cannot acquire those exceptions
retroactively. Compare active drainage length per land area, matched catchment
coverage and actual ground, not just the number of displayed rivers. Fixed-network
profile comparisons and evolving-network structural comparisons have different
denominators and must be reported separately.

Freeze wall-time, node, step and memory budgets before each run; preserve incomplete
outputs and rejection causes. The earlier fine-grid timeout is a reason to test
process scale or selective support, not to launch an unbounded global simulation.
After one bounded representation alternative, make a recorded accept/defer/reject
decision rather than indefinitely adding point constraints to the same failed fit.

## Verification of this reassessment

Reviewed the current native incision formulas, implemented world/local boundaries,
existing source reports and primary scientific/tool references. The local check
imported Landlab components and inspected their APIs only. It did not run aquifer,
karst, canyon or new terrain comparisons, change dependencies, or regenerate the
private world. Documentation validation covers local links, the complete inventory,
diff hygiene and consistency with the inspected code; runtime test results from
older reports remain historical evidence.
