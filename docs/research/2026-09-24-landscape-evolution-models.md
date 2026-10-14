# Landscape evolution: models, existing tools and selection

Research date: 2026-09-24. Status: **researched proposal; no evolution engine
installed, executed, benchmarked or adopted**. The package-resolution probe below
is the only new executable experiment. This report extends the
[progress reassessment](2026-09-24-progress-and-generation-strategy.md), without
changing its dated measurements. The living
[implementation plan](../strategy/landscape-evolution.md) owns the proposed work;
[strategy](../strategy/README.md) owns its place in the overall sequence.

## Recommendation

Test an authored sequence of geological epochs using a modest landscape-evolution
model: prescribed uplift, effective runoff, river incision and hillslope transport.
Recompute drainage as terrain changes. Start with a Landlab reference in an
isolated research environment and compare it with the current generator before
choosing a production implementation. Add conserved mobile sediment only after
the simpler model produces convincing, controllable relief.

This is a recommendation from the evidence, not a measured winner. It directly
addresses the hypothesis that drainage and terrain should develop together.
Neither erosion nor a scientific library automatically removes D8 grid bias,
fixes final-surface reconstruction, or respects this application's authored inputs.
R48's shared terrain/channel contract remains necessary whichever method wins.

Keep Python. Defer whole-planet tectonics, atmosphere simulation, particle water,
GPU requirements and new editor tools until a small, meaningful result exists.
A mountain-to-lowland test can answer the first quality question without those
systems. Geological time is a scenario parameter, not a dated history inferred
from the map or new campaign canon.

## Primary papers and what they contribute

| Source | Relevant evidence | Decision for Map Maker |
|---|---|---|
| [Braun and Willett, 2013: efficient implicit stream-power solver](https://doi.org/10.1016/j.geomorph.2012.10.008) | A graph-ordered implicit incision method with linear work for the solver pass | First river-incision reference; routing and all time steps still have a cost |
| [Cordonnier et al., 2016: uplift and fluvial terrain generation](https://onlinelibrary.wiley.com/doi/10.1111/cgf.12820) ([author PDF](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Cordonnier-Computer_Graphics_Forum-2016-Large_Scale_Terrain_Generation_from_Tectonic_Uplift_and_Fluvial_.pdf)) | User-painted uplift drives a stream graph and related terrain reconstruction | Strong precedent for author-controlled generation through geological processes; useful design reference, not an exact-constraint guarantee |
| [Campforts, Schwanghart and Govers, 2017: TTLEM 1.0](https://esurf.copernicus.org/articles/5/47/2017/) | Numerical diffusion can smear transient cliffs and knickpoints; compares a higher-order TVD finite-volume method | Include a retreating-step fixture and time/grid convergence; stability alone cannot accept a history model |
| [Shobe, Tucker and Barnhart, 2017: SPACE 1.0](https://gmd.copernicus.org/articles/10/4577/2017/) | Couples eroding bedrock, mobile cover and sediment flux | Preferred second-stage sediment comparison; measure material storage/export before claiming floodplains |
| [Barnhart et al., 2019: terrainbento 1.0](https://gmd.copernicus.org/articles/12/1267/2019/) | Landlab-based comparison of alternative landscape models with common forcing/boundary machinery | Borrow controlled model comparison and explicit forcing; avoid adopting a second application framework |
| [Cordonnier, Bovy and Braun, 2019: routing through depressions](https://esurf.copernicus.org/articles/7/549/2019/) | Basin graphs and spanning trees support efficient receiver correction; different depression treatments give different erosion patterns | Compare only if routing cost/quality warrants it. A corrected receiver graph does not prove a physically open valley or stored lake water |
| [Barnes, Callaghan and Wickert, 2021: Fill–Spill–Merge](https://esurf.copernicus.org/articles/9/105/2021/) | Depression hierarchies distribute finite runoff through filling, spilling and merging | Later lake/storage reference. Retaining depressions is a different problem from eliminating minima for an incision solver |
| [Tzathas et al., 2024: analytical erosion](https://www-sop.inria.fr/reves/Basilic/2024/TGSC24/) ([author PDF](https://www-sop.inria.fr/reves/Basilic/2024/TGSC24/Analytical_Terrains_EG.pdf)) | Analytical incision enables rapid age exploration; section 7.4 explicitly limits temporal continuity and extension to deposition/nonlinear slope laws | Alternative for fast single-stage maturity control; time stepping is the better first comparison for ordered epochs |
| [Schott et al., 2024: multiscale erosion](https://h-schott.github.io/p/mserosion/) | Erosion across scales targets enriched terrain structure | Regional-detail candidate after the global model; shared parent, crop and flow guarantees still need project tests |
| [McDonald and Cordonnier, 2026: stochastic geomorphological transport](https://erosiv.studio/publications/stochastic-geomorphological-transport) | A newer transport approach aimed at richer channel/sediment behavior | Later comparison for resolved alluvial forms; retain R17's conservation, hardware and repeatability gates |

The 2024 analytical method still couples a two-dimensional network and surface
iteratively. Its age parameter is not a guarantee that independent outputs are
successive states of one evolving drainage system. Chaining analytical results
is an experiment with its own assumptions, not an established replacement for a
multi-epoch evolution loop.

## Existing implementations

### First reference: Landlab components

[Landlab's component tutorial](https://landlab.csdms.io/tutorials/component_tutorial/component_tutorial.html)
provides an existing flow/incision/diffusion/uplift workflow.
[FastscapeEroder](https://landlab.csdms.io/generated/api/landlab.components.stream_power.fastscape_stream_power.html)
accepts erodibility fields and a discharge field; its default uses drainage area.
Use an explicit adapter and one-cell runoff checks rather than relying on defaults.
The chosen package must be tested with the exact time and distance units used here.

For sediment, inspect
[SpaceLargeScaleEroder](https://landlab.csdms.io/generated/api/landlab.components.space.space_large_scale_eroder.html)
and the pinned implementation. Its documented treatment of flooded depressions
and unhandled pits differs. It does not supply an adaptive stepper. The
[published source](https://landlab.csdms.io/_modules/landlab/components/space/space_large_scale_eroder.html)
rejects route-to-multiple receiver arrays. Therefore the first reference uses
single-receiver routing; the existing MFD capture arrays cannot simply be supplied.

There is documentation drift even upstream: the class prose and initializer
source disagree about the flooded-node keyword, and a discharge parameter is
labelled L²/T while its described rainfall-times-area construction is volumetric.
Pin the source version, inspect actual field calculations and test flooded nodes,
zero flow, units and export. This is a validation requirement, not a confirmed
numerical defect in an engine we have not run.

### Alternatives and why they are not the first integration

| Tool | Verified or documented capability | Role and outstanding work |
|---|---|---|
| [Fastscapelib C++/Python](https://fastscapelib.readthedocs.io/en/latest/guide_eroders.html) | Current eroder guide covers bedrock stream power and raster linear diffusion | Strong performance comparator if needed; GPL package, no matching current Python 3.14 Windows wheel found |
| [Fastscapelib Fortran](https://fastscape.org/fastscapelib-fortran/) | Separate implementation with a broader surface-process scope | Do not attribute its sediment capabilities to the C++ package; build/integration feasibility untested |
| [terrainbento](https://terrainbento.readthedocs.io/) | Framework for controlled LEM alternatives | Experiment-design reference; do not replace our application/persistence with it |
| [Badlands](https://badlands.readthedocs.io/en/latest/api.html) | Long-term landscape-to-marine-basin evolution, with Python and compiled components | Broader reference if source-to-sink sediment becomes central; no current Windows/Python installation or dependency audit performed here |
| [goSPL](https://gospl.readthedocs.io/en/stable/) and [user guide](https://gospl.readthedocs.io/en/stable/user_guide/) | GPL global landscape/basin model; spatial/temporal forcing and parallel execution | Relevant to the full geological-history idea, but excessive as our first desktop integration; PETSc/MPI stack and packaging remain untested |
| [MultiScaleErosion](https://github.com/H-Schott/MultiScaleErosion) | Existing multiscale reference | Keep in R15's local-detail comparison rather than using independent cropped runs as global history |
| [geotransport](https://github.com/erosiv/geotransport) | Existing 2026 transport reference | R17 remains experimental; distinguish this reference from its separate runtime dependencies and GPU backend |

The current recommendation is based on component fit and the cheapest useful
comparison, not a claim that Landlab is faster or produces better terrain than
these alternatives. No paper's published speedup is a Map Maker benchmark.

## Windows and Python dependency probe

Environment: this repository's CPython 3.14.7 virtual environment on Windows,
with NumPy 2.5.2 as the current numeric dependency. Ran a wheel-only resolver
without installation:

```powershell
.\.venv\Scripts\python.exe -m pip install --dry-run --ignore-installed --no-cache-dir --only-binary=:all: --report artifacts/landscape-evolution-dependency-probe-20260924.json landlab==2.11.0 scipy==1.18.1 numpy==2.5.2
```

Result: successful resolution, **45 distributions**, including Windows CPython
3.14 wheels for Landlab, SciPy and NumPy. The ignored local JSON report has SHA-256
`43f974a8f0f14aaa06db3d33da57d3b20cec4917d1ac91e32ace9d984203935a`.

| Resolved package | Version | Material observation |
|---|---|---|
| Landlab | 2.11.0 | Root package metadata: MIT; direct dependency on `py-richdem` |
| SciPy | 1.18.1 | Compatible wheel resolved; includes its own bundled-library notices |
| NumPy | 2.5.2 | Current project version retained in the trial resolution |
| py-richdem | 2.2.0rc3 | GPL-3.0-only; prerelease selected by the resolver |
| wrapt | 2.5.0rc1 | Prerelease selected transitively |
| Fastscapelib | 0.3.0 | Separate PyPI metadata check: GPL-3.0, no `cp314` Windows release wheel |

Afterward Landlab, Fastscapelib and SciPy were still absent from the project
environment. This demonstrates resolvable wheel metadata, not import success,
numerical correctness, complete license review or release-ready packaging.
The resolver was intentionally isolated from installed-package state and does
not prove coexistence with every application dependency. The prototype should
use a disposable environment, record exact versions and file hashes, and inspect
why prereleases were selected. A stable compatible set is preferable if available.
Do not delete required dependencies or downgrade the application to make the
comparison appear successful. Distribution choices need a dependency/license
review before an engine is bundled; the root MIT label is not the whole stack.

## What a useful first model will and will not explain

| Desired result | First useful mechanism | Limit to retain |
|---|---|---|
| Connected mountain valleys and drainage divides | Uplift plus repeatedly recomputed incision and hillslope transport | Coarse D8 still has eight directions; reconstructed terrain must agree with channels |
| Old rounded uplands beside younger relief | Separate uplift/erosion epochs and spatial forcing | Age alone does not determine shape; starting relief, substrate, climate and boundary levels matter |
| Resistant ridges and softer valleys | Spatial erodibility contrast | Two-dimensional resistance is a first approximation; exposed layered geology is later R10 work |
| Alluvial plain or fan | Mobile sediment, deposition and downstream export | Incision-only erosion exports material; it cannot honestly claim to have simulated a depositional plain |
| Lakes and dry basins | Retention plus explicit spill/storage policy | Depression correction for a flow solver is not lake hydrology |
| Desert region | Low effective runoff now; later world moisture/aridity fields | A desert is not the automatic end state of old eroded mountains; see [USGS desert types](https://pubs.usgs.gov/gip/deserts/types/) |
| Small streams visible at zoom | Resolved local drainage with inherited boundary flow | More image pixels do not create finer hydrology |

Prescribed uplift represents a geological forcing hypothesis, not a mantle or
plate-tectonic solution. Uniform effective runoff is a transparent first input,
not a climate model. Channel slope in this first incision model is a bed-slope
assumption; it does not simulate backwater, ponds or flood hydraulics.

## Selection and stopping rules

1. Establish dimensions, boundary conditions and analytic controls before using
   visual plausibility as evidence. Compare equivalent physical quantities across
   engines; area, runoff, discharge and per-width flux are different inputs.
2. Run one sequential two-epoch uplift/incision/diffusion candidate against the
   current generator. Show stage snapshots, identical-scale images, river profiles,
   structural measures, direction controls and complete process cost.
3. Continue only if the candidate improves coherent landforms on held-out cases
   and has a credible route to authored constraints and useful desktop runtime.
   Rejected experiments remain research, not permanent runtime modes.
4. Test constraint-aware surface reconstruction and basin semantics before
   adopting the evolution stage. A good reference raster is not sufficient to
   replace the current pointwise terrain contract.
5. Compare SPACE once the basic evolution result works. Consider analytical
   erosion if time stepping is too expensive; consider native/GPU kernels only
   after profiling identifies a dominant cost. Do not implement every candidate.

The next concrete deliverable is LE1/LE2 in the
[implementation plan](../strategy/landscape-evolution.md): an isolated, reproducible
mountain-to-lowland comparison with explicit acceptance and rejection evidence.
