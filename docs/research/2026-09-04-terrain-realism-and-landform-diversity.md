# Terrain realism and landform diversity — 2026-09-04

**Status: working research and prototype proposals.** This pass extends the
[algorithm research](2026-09-03-terrain-algorithm-options.md) and
[technology survey](2026-09-04-technology-and-world-systems.md). It does not
select a new engine or change generated terrain. The actionable register is
in [TODO.md](../../TODO.md#realism-research-register--2026-09-04), with stable
`R01`–`R33` identifiers used below. The
[development strategy](../strategy/README.md) still owns execution order.

The best improvement is a combination of coherent regional structure,
material-aware landforms, and detail that belongs to its parent landscape.
Increasing noise or applying one erosion filter everywhere cannot deliver all
three. Start with regional character, drainage reconciliation, and measurable
scale contracts; use specialized processes where they add recognizable forms.

## Evidence and scope

Local baseline inspected: commit `f1ffc69`, a clean worktree, the generation,
noise, hydrology, and domain modules, their guides, tests documentation, and the
current roadmap. External evidence was checked on 2026-09-04 using publisher
pages, author project pages, official repositories, and vendor documentation.
Paper results and vendor claims below are reported evidence, not measurements
reproduced in Map Maker. No candidate engine was installed or benchmarked.

The comparison covers established GIS/scientific tools, commercial terrain
applications, research implementations, real elevation data, and learned
generation. It is a bounded shortlist, not an exhaustive inventory of every
terrain product or geomorphology paper. Climate has an existing separate
research note; this pass adds its terrain-facing runoff interface only.

## What the current implementation implies

These are code observations, followed by proposed consequences, rather than a
claim that a particular screenshot has been diagnosed.

| Observed baseline | Implication and proposed improvement |
|---|---|
| `_base_elevation_fields` uses the same coast-distance envelope and value-noise family across a project. | Terrain-character regions should alter broad height distribution as well as detail. Allow low continental interiors and high coastal ranges. R06, R08, R10. |
| `_prepare_automatic_valley_field` evaluates an unconstrained macro surface before authored features; its signature accepts no authored constraints. | An authored mountain or valley can invalidate the earlier generated catchment. Route against accepted macro constraints and report incompatible authored routes. R04. |
| Automatic drainage has 257 samples along the longest dimension; the final diagnostic has 129. | At the default 4,000 km extent, spacing is 15.625 km and 31.25 km respectively. These describe broad drainage, not individual small rivers, dunes, or cliffs. R02. |
| The output samples a continuous field; the automatic-valley result retains incision and detail suppression, not the full routing graph. | Public hydrography needs explicit topology and source-surface provenance. Increasing output pixels alone does not refine that graph. R05, R15. |
| `_metric_polygon` scales coastline bounds to an object width, with a local origin; no planetary location is supplied. | A distance-labelled local plane does not automatically retain the source world's latitude, origin, or projection distortion. Define georeferencing before calling exports geographically correct. R01. |
| The pipeline clips terrain to nonnegative elevations in several places. | Dry depressions below sea level, submerged fjord beds, and bathymetry require a deliberate elevation/water contract change. R07. |
| Equal shared-coordinate samples are tested, but point equality is not area-average preservation. | Choose raster sampling semantics and filtered export rules before promising parent/child conservation. R03. |

Relevant code: [generation](../../src/map_maker/terrain/pipeline/generate.py),
[hydrology](../../src/map_maker/terrain/pipeline/hydrology.py),
[noise](../../src/map_maker/terrain/pipeline/noise.py), and
[models](../../src/map_maker/terrain/domain/models.py).

For the current Aethelara source, the fixed 6,000 km sphere and world projection
were checked against the source workspace's `Maps/SCALE_AND_PROJECTION.md`.
Keep those constants in project inputs, not as Map Maker defaults. Returning a
processed regional DEM to that frame must preserve coastline coordinates;
regional metric processing must account for latitude-dependent distortion.

## Highest-value changes to visible landforms

### Give regions different structure, not just different noise

Make terrain-character regions express a target lowland/upland proportion,
relief scale, directional grain, rock resistance, and process mix. A plateau
should have a broad elevated interior and a deliberate margin; an old range
should differ from a young dissected range even at the same maximum height.
Transition widths should be in world units. Compare the existing global field
against a small set of authored province recipes before inventing many knobs.

Use ridge/divide and drainage graphs together. Secondary spurs should occupy
the spaces between tributaries, with coherent junctions and passes, rather
than being generated independently and later crossing channels. Rock layers
and resistant caps are candidates for mesas, cuestas, escarpments, and canyon
walls. These are design proposals, not deductions of a world's true geology.
R08–R11 extend the existing region, branching, and lithology backlog.

### Model where eroded material goes

Current generated valley work is primarily incision. A bedrock surface plus
nonnegative mobile sediment would support flatter valley floors, alluvial fans,
and depositional basins without globally smoothing the mountains. First compare
one bedrock/sediment channel, then a fan at a mountain-to-plain transition.
Report eroded, deposited, stored, and exported material separately. Clipping or
restoring an authored height is an external correction and belongs in that
ledger; it must not appear to conserve sediment automatically. R16, R32.

Meanders, braided channels, and deltas need different semantics from the
current one-receiver D8 drainage tree. Keep a catchment tree for broad routing;
represent local channels and distributaries separately where needed. Width
should consider discharge, slope, bank material, and valley confinement.
Strahler order alone already regressed measured valley behavior here. R18.

### Add distinctive processes selectively

The following are proposed families, each restricted to suitable regions and
resolutions. A full simulation is one option; a transparent, validated shape
recipe may be enough for authored fantasy geography.

| Family | Visible outcome | Required context and rejection checks | TODO |
|---|---|---|---|
| Glacial | U-shaped and hanging valleys, cirques, overdeepened lakes, fjord approaches | Authored former ice extent/flow or climate history; water exceptions; protect divides and lake outlets | R20 |
| Debris flow and mass wasting | Scars, scree aprons, debris cones, irregular steep slopes | Material and slope assumptions; deposition may obstruct channels and must trigger diagnostics | R21 |
| Wind and sand | Oriented dune fields, sand sheets, lee deposits | Wind regime, mobile sand supply, transport scale; no blanket dunes over every dry region | R22 |
| Volcanic and impact | Cones, calderas, shield forms, lava plateaus, crater rims | Explicit authored origin and scale; separate volcanic and impact recipes; preserve coast and surrounding relief | R23 |
| Karst | Closed depressions, disappearing streams, spring outlets | Soluble substrate and authored underground connections; closed sinks may be intentional | R24 |
| Episodic river history | Terraces, incised meanders, abandoned valley levels | Recorded changes to uplift, base level, or sediment supply; preserve ordering of events | R11, R19 |
| Coast and basin margins | Coastal mountains, broad plains, cliffs, inland below-sea-level floors | Separate coast elevation from inland profile; lake beds and water surfaces have different meanings | R06, R07 |

A heightfield stores one elevation at each horizontal position. Caves, arches,
and overhangs therefore require a separate mesh/volume or semantic layer; they
cannot be made physically complete by modifying the DEM alone. Surface karst
and authored underground connectivity are a useful bounded first step. The
[NPS karst overview](https://www.nps.gov/subjects/caves/karst-landscapes.htm)
supports treating sinkholes and underground drainage as connected phenomena.

## Papers worth prototyping

Each entry separates what the source contributes from the proposed Map Maker
use. Listed code availability does not establish installability or license
compatibility of its entire dependency stack.

| Paper and primary source | Evidence contribution | Proposed use and limitation |
|---|---|---|
| Grenier et al., [Real-time Terrain Enhancement with Controlled Procedural Patterns](https://onlinelibrary.wiley.com/doi/full/10.1111/cgf.14992), 2024 issue, first online 2023 | Phasor-based detail follows terrain orientation and drainage; patterns cascade across scales. | First detail experiment for the existing anisotropy backlog. Check branching coherence, valley-floor protection, and tile boundaries; appearance is not proof of valid drainage. |
| Tzathas et al., [Physically-based analytical erosion for fast terrain generation](https://www-sop.inria.fr/reves/Basilic/2024/TGSC24/), 2024 | Uses analytical stream-power relationships with multigrid-accelerated iteration and hillslope processes. | R14: compare an interactive erosion-age control with time stepping. The 2D implementation is not simply a closed-form one-pass formula, and its inferred history is not unique. |
| Schott et al., [Terrain Amplification using Multi-Scale Erosion](https://h-schott.github.io/p/mserosion/), 2024 | Couples refinement with erosion, thermal effects, and deposition at multiple scales. | R15: stronger refinement reference than adding noise alone. Published hydrological coherence does not establish our exact parent/downsample contract. |
| McDonald and Cordonnier, [Stochastic Geomorphological Transport for Terrain Erosion Simulation](https://erosiv.studio/publications/stochastic-geomorphological-transport), 2026, DOI 10.1145/3811336 | A stochastic transport formulation incorporates momentum; examples include meanders, braided rivers, deltas, and fans, with resolution comparisons. | R17: a high-interest regional experiment. Test convergence statistically and repeated GPU runs numerically; published resolution invariance is not bitwise nested-grid equality. |
| Shobe et al., [SPACE 1.0](https://gmd.copernicus.org/articles/10/4577/2017/), 2017 | Separates sediment transport and bedrock erosion in landscape evolution. | R16: established first sediment comparison. A landscape model is not automatically a resolved meander or delta simulator. |
| Jain et al., [Efficient Debris-flow Simulation for Steep Terrain Erosion](https://www-sop.inria.fr/reves/Basilic/2024/JBC24/), 2024 | Couples debris and fluvial erosion/deposition to generate scars and debris cones. | R21: assess steep areas poorly represented by uniform slope relaxation. Recheck drainage after deposition. |
| Cordonnier et al., [Forming Terrains by Glacial Erosion](https://www-sop.inria.fr/reves/Basilic/2023/CJPBCBGGG23/), 2023 | Combines glacier evolution, learned ice-flow estimation, erosion, and debris transport; shows hanging valleys, fjords, and lakes. | R20: reference morphology and optional external experiment. Full ice dynamics and learned components are substantially heavier than a U-shaped valley recipe. |
| Rosset et al., [Windblown sand around obstacles](https://www-sop.inria.fr/reves/Basilic/2024/RDBC24/), 2024 | Iterates wind and sand transport; compares deposition patterns with controlled observations. | R22: later regional/local reference. The obstacle-scale validation does not justify applying its parameters across a continent. |
| Argudo et al., [Terrain Descriptors for Landscape Synthesis, Analysis and Simulation](https://diglib.eg.org/items/a7833e48-561c-4607-a704-458bf0a7f3f0), 2025 | Reviews and implements terrain metrics and compares cost/correlation. | R25: extend the quality harness with complementary measures instead of many redundant scores. Roughness, relief, and steepness should not be conflated. |
| Perche et al., [Vector-Based Terrain Modelling](https://diglib.eg.org/items/1701ed03-a449-41d3-ae0f-fa771c9c7cb8), 2025 | Vectorizes terrain with a chosen error and supports skeleton-guided deformations. | R13: investigate editing a whole range while preserving its internal structure. Preserve explicit authored constraints and validate reconstruction error. |
| Huftier et al., [Terrain Synthesis and Authoring based on Iso-Contours](https://h-schott.github.io/p/isos/), 2026 | Nested authored contours guide growth and TIN reconstruction. | R12: useful plateau, shelf, and basin authoring. The paper identifies river-width and slope limitations; it is not a complete hydrological replacement. |
| Jain et al., [FastFlow](https://www-sop.inria.fr/reves/Basilic/2024/JKGFC24/), 2024 | GPU flow and depression routing improves throughput in the authors' benchmarks. | R31: investigate only after higher-resolution routing becomes a measured bottleneck. Faster routing alone does not add landform realism. |
| Borne--Pons et al., [MESA](https://arxiv.org/abs/2504.07210), 2025 MORSE workshop | Text-conditioned terrain samples trained from global elevation data; introduces Major TOM Core-DEM data. | R29: proposal and reference generation. Exact authored heights, catchment continuity, and reproducibility need independent enforcement. |
| Borg et al., [Authoring Terrestrial Planets with Diffusion Models](https://github.com/Oliver-Borg/PlanetDiffusion), 2026, DOI 10.1111/cgf.70390 | Provides planetary authoring/inference code and pretrained-model setup. | R29: later global-context comparison. The documented environment uses Python 3.10 and Earth-relative radius steps; it is not a drop-in fit for Python 3.14 or a fixed custom planet. |

Two updates to the earlier research matter. DOI `10.1111/cgf.14992` has the
title shown above, rather than the descriptive title used in the September 3
note. Also, the new stochastic-transport work means particle-based methods
should not be dismissed as a class. The relevant distinction is documented
transport, scaling, and validation versus an uncalibrated visual filter.
Earlier dated notes are retained as historical evidence.

## Tool shortlist and integration boundaries

### Established tools and practical comparisons

| Tool | Useful role | Integration assessment |
|---|---|---|
| NumPy and a focused SciPy addition | Field evaluation, interpolation, sparse solves, filters and metrics | Keep the current core. The previous solver comparison remains worthwhile, but a smoother interpolant alone will not create diverse geology. |
| Landlab, especially SPACE and hillslope components | Compare routing, bedrock/sediment evolution, runoff and diffusion | Best first scientific adapter. [PyPI](https://pypi.org/project/landlab/) lists MIT Landlab 2.11.0 and a `cp314-cp314-win_amd64` wheel. This verifies distribution availability, not complete dependency installation or correct execution here. |
| GDAL/Rasterio, pyproj and QGIS | Numeric exchange, coordinate transforms, inspection and independent renders | Follow the existing GeoTIFF strategy. Preserve units, datum, extent, sample registration and nodata; never infer heights from tinted PNGs. |
| GRASS GIS | Independent routing and landform classification | [r.geomorphon](https://grass.osgeo.org/grass-stable/manuals/r.geomorphon.html) supplies a useful scale-dependent landform view. Use an external version-pinned comparison, retaining the existing GPL boundary. |
| Whitebox / Fastscape | Additional hydrology or landscape-evolution comparisons | Retain the component-specific licensing and compatibility gates in the [technology survey](2026-09-04-technology-and-world-systems.md). No new install recommendation from this pass. |

The current [Landlab SPACE guide](https://landlab.readthedocs.io/en/latest/tutorials/landscape_evolution/space/SPACE_user_guide_and_examples.html)
provides concrete sediment and bedrock examples. Begin with those fields and
known boundaries rather than introducing the entire Landlab model into the
public Map Maker project schema.

### Commercial tools as bounded reference workflows

| Tool and official source | What to learn or compare | Boundary |
|---|---|---|
| [Houdini HeightField Erode 3.0](https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode) | Erosion feature size independent of display resolution; multiple erosion scales; explicit erosion/deposition controls | Strong controllable comparison if available. Freeze the node graph, frame, version and layers; vendor claims of similar features are not our determinism test. |
| [Gaea Erosion](https://docs.gaea.app/reference/nodes/simulate/erosion) | Spatially varying softness/precipitation, deposited material, and separate wear/deposit/flow maps | Useful visual and data-layer reference. Documentation warns parallel processing can change results and describes deterministic single-core operation. |
| [World Machine water workflow](https://help.world-machine.com/topic/water/) | Combine authored major rivers with generated tributaries and water surfaces | A good authoring pattern for R04/R18. Validate resulting DEM and channels rather than accepting a river overlay as proof. |
| [World Creator export](https://docs.world-creator.com/reference/export/conventional-export) | Optional external terrain comparison through heightmaps and influence maps | Disable or record automatic normalization; record actual metres and extent. Otherwise the imported terrain can silently acquire different relief. |

These are proprietary applications evaluated through documentation, not
dependencies selected for purchase or embedding. R30 captures an explicit
exchange adapter and evaluation. Export precision, edition restrictions,
automation rights, and a locally reproducible build must be checked before an
actual trial. The engine remains usable without them.

### Research and open-source implementations

| Candidate | Verified availability or constraint | Disposition |
|---|---|---|
| [MultiScaleErosion](https://github.com/H-Schott/MultiScaleErosion) | MIT code; documented Windows/Linux CMake build; OpenGL 4.3 compute shaders | High-value isolated R15 experiment; local compilation and numeric repeatability untested. |
| [geotransport](https://github.com/erosiv/geotransport) | MIT minimal stochastic-transport reference, not the full erosion simulator. [PyPI](https://pypi.org/project/geotransport/) lists a Windows `cp312-abi3` wheel tagged Python 3.12+. | The wheel tag suggests Python 3.14 ABI eligibility; CUDA/runtime support and actual import still need a test. R17. |
| [soillib](https://github.com/erosiv/soillib) | Fuller GPU simulation toolbox; C++23/CUDA/Python bindings; README reports Windows/Linux; LGPL-3.0 | Evaluate separately from the MIT reference. Hardware, dependencies, license boundary and reproducibility are unresolved locally. R17/R31. |
| [HighMap](https://github.com/ottolink-dev/HighMap) and its Python binding | C++ heightmap library. [License](https://github.com/ottolink-dev/HighMap/blob/main/LICENSE) contains LGPL-2.1 terms; inspect [third-party notices](https://github.com/ottolink-dev/HighMap/blob/main/THIRD_PARTY_LICENSES.md). [pyHighMap](https://github.com/otto-link/pyHighMap) documents Linux-only support. | Reference toolbox or isolated experiment; not a native Windows Python dependency recommendation. R30. |
| [terrain-descriptors](https://github.com/oargudo/terrain-descriptors) | Authors' metric implementation, MIT | Compare a small diagnostic subset; do not assume it is a packaged Python library. R25. |
| [Contours](https://github.com/Arches-Team/Contours) and [vector-based terrain](https://github.com/Arches-Team/vector-based_terrain_modelling) | Author-linked source exists; Contours shows MIT licensing but minimal README/setup information | Study editing representations first. Build instructions, dependency licenses and runtime behavior need separate review. R12/R13. |
| [Inria terrain prototypes](https://www-sop.inria.fr/members/Guillaume.Cordonnier/code.html) | Author links for analytical erosion, FastFlow, debris flow, glacier and wind work | Code pointers verified; individual build and license audits remain open. R14/R20–R22/R31. |

## Real terrain as a reference, not an unquestioned template

Use a small, varied atlas to measure what makes landscapes distinct: an old
rounded range, a sharp alpine range, a dissected plateau, an alluvial plain,
a glacial valley, a volcanic region, and a dune field. Match physical extent
and sample spacing before comparing relief, curvature, drainage density,
hypsometry, peak prominence, and directional spectra. Record vertical datum,
resampling, crop, data quality and provenance. R25–R27.

[USGS 3DEP](https://www.usgs.gov/3d-elevation-program) offers elevation products
without use restrictions and is a good first source for this atlas.
[Copernicus DEM](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)
adds global coverage, but is a surface model including vegetation and built
features, not a uniformly bare-earth model. Preserve its attribution terms and
quality masks. Buildings, radar artifacts, or vegetation should not become a
desired geological texture. Data can inform descriptors without copying an
entire recognizable real region into the setting.

Example-based synthesis is a separate experiment: fit a patch's broad surface
and boundary to authored constraints, then transfer selected residual detail.
Test seams, duplicate motifs, altered drainage, and sensitivity to rotation.
Likewise, learned terrain proposals must remain disposable alternatives until
the author accepts them and the numeric gates pass. Code, weights, and training
data can each have different terms; a code license is not a weight license.

## Presentation that makes existing relief readable

Compare single-direction lighting with
[GDAL's multidirectional and other hillshade variants](https://gdal.org/en/stable/programs/gdal_raster_hillshade.html),
plus coarse/fine relief shading. R28 should retain the fixed elevation palette,
make vertical exaggeration explicit, and keep every visual mode derived from
the same DEM. A polished render is useful for judging composition, but cannot
validate height or drainage. Show the numerical landform and drainage layers
beside it. Rock, scree, wet ground, vegetation, and snow need separate evidence
or authored materials; they must not be inferred from elevation colours alone.

## Experiments and decision gates

This is an experiment order within the existing strategy, not authorization to
implement all candidates. Complete the build identity and coordinate decisions
first; emit a reusable numeric fixture and report for every experiment.

| Order | Small experiment | Baseline and comparison | Accept only if |
|---|---|---|---|
| 1 | Regional composition and oriented detail | Existing field versus province-controlled height distribution and slope/drainage-aligned detail; same authored constraints and fixed seeds | Regions are measurably distinct; floors remain connected; exact anchors hold; no new seams or grid alignment |
| 2 | Authored mountain crossing a generated catchment | Current pre-authored routing versus a constrained macro routing stage | Divides, outlet reachability and authored intent agree, or conflicts are reported; deterministic termination |
| 3 | Mountain valley opening onto a plain | Current incision versus Landlab SPACE, with a material ledger | Deposits form in plausible locations, sediment stays nonnegative, mass residual is bounded, and outlet topology remains valid |
| 4 | One nested mountain-valley window | Existing interpolation versus multi-scale amplification | Parent elevations meet a declared restriction tolerance; boundary slopes match; inherited inflows are conserved; no new upstream catchment is invented |
| 5 | Broad lowland channel and fan | Deterministic stream-power baseline versus 2026 stochastic transport | Added forms survive seed ensembles and refinement; hard constraints hold; cost, GPU variance and transport balance are reported |
| 6 | One selected special region | Glacial, debris, dune, volcanic or karst recipe/model | The intended landform signature improves and required environmental assumptions are recorded; no unsupported world history is asserted |

Use nested 65/129/257 grids for small solver checks and a separate,
physically-resolved regional patch for narrow landforms. Run multiple fixed
seeds, rotated fixtures, and at least two timestep sizes for evolving models.
GPU algorithms need repeat-run and device/runtime reporting; statistical
convergence and identical hashes are distinct claims.

Every report should include hard/soft constraint residuals, finite values,
land/water validity, outlet connectivity, conditioning deltas, clipped area,
material balance where applicable, stage time/memory, and parent/child errors.
Measure both the canonical process surface and the exported surface. Restoring
hard constraints at the end can recreate a pit; restoring parent averages can
reverse a channel. If both requirements cannot be satisfied, report a conflict
instead of alternating silently until the image looks acceptable. R32.

Judge interest using several independent properties, not one realism score:
regional contrasts, connected ranges, useful passes, river hierarchy, and
recognizable landform families. A small comparison gallery should offer varied
valid candidates for review. R27 preserves control over which alternative
becomes authored geography.

## Recommended next work

The first implementation should make terrain builds measurable and reusable,
then test **regional height distributions and oriented residual detail** against
the current output. This has a direct visual payoff with fewer new scientific
assumptions than a complete erosion engine. Next reconcile generated drainage
with authored macro geography, then compare sediment-aware valleys and local
multi-scale refinement. Keep analytical erosion as a competing process option
and stochastic transport as a promising measured research branch. Specialized
ice, sand, karst, and volcanic models follow where the author wants those
landforms. A whole-planet simulation or learned generator is unnecessary for
the first substantial improvement.
