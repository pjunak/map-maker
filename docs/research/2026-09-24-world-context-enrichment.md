# World context before continental terrain: research and recommendation

2026-09-24. Research and source inspection only: no new climate, ocean or tectonic
engine was installed or run. This report refines the requested workflow and
supports the [world-context implementation plan](../strategy/world-context.md).
The [main strategy](../strategy/README.md) owns execution order.

## Recommendation

Adopt **world context as an upstream generation product**, followed by rough
world terrain, accepted continental histories and bounded regional detail.
Preserve imported coastlines, continent membership and geographic placement.
Use one shared planet and climate context with different geological provinces;
do not generate each continent as an isolated random island.

The sequence needs a controlled feedback step: preliminary context supplies
initial terrain hypotheses; rough relief changes rainfall and circulation;
climate/runoff then inform landscape evolution. Freeze a reviewed world parent
before independent high-resolution jobs. A detailed job inherits the parent's
present day and history; it must not age an already aged parent a second time.
These are proposed product decisions, not claims that the current code does this.

## What the existing program can and cannot supply

Source inspection at `ed2a23a` confirms:

- The SVG adapter dissolves closed shapes. That is useful for physical land masks,
  but it discards original continent/group boundaries as semantic objects.
- `LocalMetricFrame` assigns a longest-side scale to source bounds. It does not
  retain a declared planetary projection, radius, latitude or world placement.
- The current terrain-project schema has no world, continent, ocean or climate
  context fields. Importing a full map today would not establish those semantics.
- Stable seeds, typed grids, immutable parents, provenance, completion-last
  publication, regional admission and read-only output inspection can be reused.
- Ordered uplift/incision/diffusion histories and frozen reconstruction comparisons
  execute as research. Grid direction, authoring and spatial acceptance remain
  open. The existing local-detail command is not a historical refinement solver.

The world-map workflow therefore requires a world-source contract and retained
identities, not merely a larger value for the existing object scale. A campaign's
external map/projection contract remains authoritative; the reusable application
must not embed private campaign geometry or hard-code one world's coordinates.

## Scientific interpretation of the idea

| Input or relationship | Useful consequence | Limit that the design must retain |
|---|---|---|
| Latitude, orbit, obliquity and rotation | Insolation and seasonal/circulation priors | A climate-zone label is a derived summary, not enough physical forcing |
| Continental area, shape and position | Interior distance from moisture, land/ocean contrast, wind exposure | Continents at equal latitude need not have equal climate; size alone is insufficient |
| Ocean connectivity, gateways and upwind water exposure | Moisture supply and permitted heat-transport pathways | Nearest-ocean area is not an adequate predictor; remote basins can matter |
| Shelf, slope and deep-ocean geometry | Coastal setting and later circulation constraints | Shorelines do not uniquely determine bathymetry |
| Ocean surface mixed-layer depth | Effective seasonal heat storage | Full seabed depth is not the mixed-layer heat capacity |
| Uplift, rock resistance and forcing history | Contrasting mountains, basins and erosion response | A continent is neither one rock unit nor one tectonic plate |
| Geological age | Prior for material/history hypotheses | Crust age, time since uplift and duration of erosion are different quantities |
| Local high-resolution generation | Better valley, ridge and channel expression | Resolution increases information only when new resolved processes/context are supplied |

GPlates explicitly needs rotations and feature/plate associations to reconstruct
positions; a coastline supplies neither a unique past nor those inputs. Treat
proposed geology as authored or generated hypotheses, not recovered historical
truth. [GPlates primer](https://www.gplates.org/docs/pygplates/pygplates_primer)

Landscape experiments show that tectonic forcing, precipitation and vegetation
histories interact. This supports separate process controls rather than one
universal erosion-age slider. It does not calibrate a fictional continent's age.
[Uplift, precipitation and vegetation experiment](https://esurf.copernicus.org/articles/9/1045/2021/)

## Established models worth using or comparing

### Geometry and physical scale

Retain the source projection and radius explicitly. A Plate Carree display is
not a uniform metric plane: source-to-sphere conversion, spherical cell areas,
longitude wrapping and polar handling precede distance-sensitive calculations.
Use PROJ/GDAL through established adapters for reprojection and independently
check distances and round trips. Never label a custom planet as Earth EPSG:4326.
RFC 7946 GeoJSON specifies WGS 84; a custom-body exchange needs an explicit
format/metadata policy rather than an undocumented substitution.
[PROJ Plate Carree](https://proj.org/en/stable/operations/projections/eqc.html),
[geodesics](https://proj.org/en/stable/geodesic.html),
[RFC 7946](https://www.rfc-editor.org/info/rfc7946/)

For a first low-resolution climate experiment, a spherical latitude/longitude
finite-volume grid with proper areas and explicit pole treatment is simpler than
rewriting the terrain engine onto a globe mesh. An equal-area or cubed-sphere
alternative becomes justified if polar stability or rotated-world tests fail.
JIGSAW(GEO) demonstrates existing variable-resolution spherical meshing; using it
would add an unstructured numerical backend, not a free replacement for raster
algorithms. [NASA's JIGSAW(GEO) overview](https://www.giss.nasa.gov/tools/jigsaw/)

### Tectonic and ocean hypotheses

GPlates/pyGPlates are established tools for specified plate histories and global
geometry. GPlately adds analysis and seafloor-age grids from reconstruction
inputs. They are appropriate optional references/import sources, not automatic
solutions to finding the history of an arbitrary finished map.
[pyGPlates reconstruction](https://www.gplates.org/docs/pygplates/generated/pygplates.reconstruct),
[GPlately SeafloorGrid](https://gplates.github.io/gplately/latest/sphinx/html/generated/gplately.SeafloorGrid.html)

Karlsen and colleagues generate seafloor ages using tracers and defined moving
plate boundaries. The paper links those ages to inferred bathymetry and sea
level. This offers a later stronger bathymetry path once plate histories exist;
it does not infer depth from ocean width alone.
[Karlsen et al., published 2020](https://doi.org/10.1016/j.cageo.2020.104508),
[author manuscript](https://arxiv.org/abs/1910.03351)

Recommended first approximation: derive connected water geometry, then combine
explicit shelf widths, active/passive-margin hypotheses, basin-depth priors,
ridges and trenches into a bounded ocean field. Mark every inferred parameter.
Keep the coastline immutable and report coarse unresolved straits/islands.
Topographic oceans are context; coupling deep circulation is a separate model.
Detailed coastal deposition, emergent islands and moving sea level would change
the authored land boundary and are outside the first fixed-shoreline workflow.

### Seasonal climate and rainfall

Climlab provides tested building blocks and instructional energy-balance models.
Its seasonal zonal example demonstrates the effect of effective heat capacity
and obliquity. A zonal example alone cannot distinguish east and west coasts or
resolve rain shadows; it is a reference control for part of a two-dimensional
world model. [Climlab seasonal example](https://climlab.readthedocs.io/en/latest/courseware/Seasonal_cycle_and_heat_capacity.html)

Smith and Barstad's linear orographic precipitation model includes airflow,
condensed-water transport and evaporation on descending slopes. Compare it on
small regional fixtures with a simpler moisture-advection/upwind-relief model.
Its linear, steady assumptions limit where it applies; it is not a global
circulation solver and should not be applied unmodified across poles or the
whole sphere. [Smith and Barstad, 2004](https://journals.ametsoc.org/view/journals/atsc/61/12/1520-0469_2004_061_1377_altoop_2.0.co_2.xml)

ExoPlaSim accepts a supplied land mask and topography, planetary/orbital settings
and mixed-layer depth. It is an existing route for comparing a few complete
world climates, including circulation missing from prescribed-wind heuristics.
Its documented native requirements and Windows-via-WSL route make it a heavier
external reference, not the interactive baseline.
[API inputs](https://exoplasim.readthedocs.io/en/latest/source/exoplasim.html),
[setup](https://exoplasim.readthedocs.io/en/latest/),
[model paper](https://arxiv.org/abs/2107.07685)

Recommended initial world model: seasonal energy balance, documented prevailing
wind scenarios, bounded moisture transport and a soil-water/runoff budget.
Generate temperature/precipitation/runoff fields before deriving climate classes.
Provide uncertainty or scenario differences for circulation assumptions; do not
present a prescribed-wind field as a simulated monsoon, jet or hurricane climate.
Detailed formulas, units and gates belong to the implementation plan.

### Newer and more ambitious options

The 2026 Generic-PCM dynamical slab-ocean paper is especially relevant. It compares
a reduced ocean heat-transport model with aquaplanet and modern-Earth cases, using
wind-driven and eddy-transport parameterizations. Code and experiment data are
archived. This is a promising intermediate comparator between prescribed ocean
heat transport and a full ocean model. Its reported low additional cost is within
that GCM configuration, not evidence of desktop performance in Map Maker or a
ready arbitrary-bathymetry plugin. Published 24 April 2026.
[Bhatnagar et al., 2026](https://gmd.copernicus.org/articles/19/3285/2026/),
[archived code and data](https://doi.org/10.5281/zenodo.18771594)

GEOCLIM7 (2025) addresses climate/geochemical evolution over millions of years and
supports different paleogeographic ocean configurations coupled to GCM inputs.
It shows why long geological climates cannot be inferred from today's latitude
alone. Carbon-cycle, weathering and ocean-chemistry feedbacks are a later research
branch; prescribing epoch climate assumptions is more bounded for the first tool.
[Maffre et al., 2025](https://gmd.copernicus.org/articles/18/6367/2025/)

Isca offers a hierarchy of atmospheric model complexity; NASA ROCKE-3D includes
coupled atmosphere, land and ocean models for planetary configurations. Both
are credible high-fidelity reference options. Neither should become a prerequisite
for importing a map, and neither was installed or benchmarked in this review.
[Isca paper](https://gmd.copernicus.org/articles/11/843/2018/),
[NASA ROCKE-3D](https://www.giss.nasa.gov/projects/astrobio/)

## Tool selection and dependency boundary

| Option | Recommended role | Deployment/license evidence and remaining boundary |
|---|---|---|
| Existing NumPy/Shapely/Rasterio/SVG stack | World metadata, geometry and bounded first context experiments | Already adopted; spherical semantics and world-grid tests are new work |
| PROJ/GDAL | Custom-body coordinates, projected working regions, exchange | Existing Rasterio native stack; new world operations still need validation |
| Climlab | Reference insolation/energy-balance controls | MIT; optional scientific/compiled paths and Windows/Python 3.14 installation not tested here |
| GPlates / pyGPlates / GPlately | Optional specified tectonic-history import and comparison | GPL-2.0 declarations; isolate evaluation, check exact distributed stack and Python compatibility before adoption |
| ExoPlaSim | External small frozen-world climate cohort | GPL; documented C/Fortran and Windows via WSL; no local installation or timing result here |
| Generic-PCM reduced ocean | New research comparison for ocean transport | Paper/code archive inspected; exact dependency/license inventory and local execution remain unverified |
| Isca / ROCKE-3D / GEOCLIM7 | Later high-fidelity or long-time reference | Full engine setup, data and licenses need separate evaluation; not application dependencies |
| WorldEngine + platec | Existing procedural workflow and result comparator | WorldEngine MIT; platec LGPL-3.0. Its published pipeline creates plate-based worlds; it does not establish our exact coastline/continent-preservation contract |
| Tectonics.js | Interactive global-process/UI reference | Author's site declares CC BY 4.0; not a validated Python engine or fixed-coast reconstruction method |
| JIGSAW(GEO) | Conditional spherical-mesh comparison | NASA describes its purpose; package/license/runtime audit deferred until an actual mesh experiment |

License facts are from the owners:
[Climlab](https://github.com/climlab/climlab/blob/main/LICENSE),
[GPlates](https://www.gplates.org/),
[GPlately](https://github.com/GPlates/gplately),
[WorldEngine](https://github.com/Mindwerks/worldengine),
[platec](https://github.com/Mindwerks/plate-tectonics),
[Tectonics.js](https://davidson16807.github.io/tectonics.js/blog/index.html).
The [dependency register](../DEPENDENCIES.md) continues to list adopted packages
and the existing isolated erosion stack. No new dependency was added here.

## Alternatives and decision

| Approach | Advantage | Reason to accept or defer |
|---|---|---|
| Independent continent presets | Cheapest implementation | Reject as the world feature: no shared climate or cross-border history |
| Latitude bands plus distance to sea | Useful transparent control | Retain as baseline only; lacks circulation, gateways, topographic rainfall and history |
| Fixed geography plus constrained context/histories | Preserves authored map and scales incrementally | Recommended product approach; hypotheses and conservation limits must stay visible |
| Freely evolving whole-planet tectonics | Emergent global history | Defer: moving plates/coasts conflicts with preserving the supplied present map |
| Full GCM plus dynamic ocean for every revision | Stronger physics in its validated regime | External reference first; setup, data, calibration and cost do not serve rapid authoring |
| Learned surrogate | Potential acceleration after a validated model exists | Defer: needs a suitable training domain, held-out fantasy configurations and constraint tests |

This is a constrained forward-design problem, not a unique inverse solution.
Generate a small number of reproducible, explainable context candidates, allow
pre-generation adjustment/locking, then derive terrain from the selected inputs.
A user-authored continent split is semantic ownership; geology and catchments
can cross it. Visual and numerical seams must not follow that administrative line.

## Failure cases that shape the plan

1. Independently rescaling continents destroys ocean adjacency and latitude.
2. Treating a continent as a plate invents incompatible mountain belts and margins.
3. Deriving all ocean depth from coastal distance makes different ocean histories
   indistinguishable and does not model heat transport.
4. Fixing climate before relief prevents mountain rain shadows and runoff feedback.
5. Applying today's climate for millions of years without labelling that assumption
   falsely implies reconstructed paleoclimate.
6. Aging already evolved coarse terrain again at each zoom changes the world with
   request order and duplicates geological time.
7. Solving each continent's climate separately creates contradictory boundary data.
8. Losing a narrow strait at coarse resolution changes basin connectivity and may
   change the context globally. Preserve topology or declare it unresolved.
9. Restoring hard targets after hydrology can invalidate drainage. Composition
   corrections need their own ledger and revalidation, as the current research shows.
10. A world-size raster at regional resolution is not a viable storage or job model.
    Global coarse context and bounded requested detail need separate resolutions.

## Roadmap consequence

Move minimum world import, geographic placement and shared-context contracts
forward from the old final climate phase. Keep the existing physical-path and
landscape acceptance work active. Coarse climate/runoff becomes upstream input
to world-informed aging, while ecological classifications remain downstream.
The linked WC0-WC6 plan supplies concrete milestones, outputs, review actions,
mathematical interfaces, budgets, cross-continent consistency and acceptance
controls. It extends R01/R02/R07/R10/R11/R15/R33/R34/R48 and adds R49 as the
owner of the world-context workflow; it does not duplicate the evolution engine.
