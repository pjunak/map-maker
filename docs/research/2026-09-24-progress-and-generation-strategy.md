# Progress and generation strategy reassessment — 2026-09-24

Status: code review, current public-fixture measurements, and primary-source
research. This report recommends an execution order; it does not adopt a new
solver or claim that external engines were run. The active order is maintained
in the [strategy](../strategy/README.md); candidates remain in [TODO](../../TODO.md).

## Assessment

Map Maker is a functioning **research workbench and deterministic terrain
prototype**, still before a consistently convincing map generator. The editor,
reproducible builds, numeric exports, cancellation, regional requests and memory
ownership are substantial completed work. Drainage plausibility, coherent
landform structure and accepted zoom enrichment are still product milestones.
A percentage complete would obscure these very different levels of maturity.

| Area | Current position | What would make it a dependable product feature |
|---|---|---|
| Authoring and inspection | Usable input editor, save/undo, pan/zoom, elevation readout, progress/cancel, scale-aware diagnostic drainage | Paired comparisons, useful profile/conflict inspection, feature-resolution warnings; then targeted authoring conveniences |
| Numeric foundation | Deterministic local-metric Float32 builds, schemas, manifests, named seeds, current-format snapshots and verified parents | Keep these contracts; world placement is a separate dependency for geographic/climate claims |
| Drainage | Authored macro routing, cut limits, retention, inspected topology, density control and connected display | Feasible paths on finished ground, less grid bias, explicit unresolved routes and scale-dependent hydrology |
| Terrain character | Four regional recipes and authored ridge/valley profiles | Related ridges, passes, tributaries and valley floors; measured differences between landform families |
| Local enrichment | Bounded opt-in residual, repeatable overlaps, protected ground, shared-edge support and reusable sessions | Oblique structure, acceptable coarse-scale change, parent-view transitions, inherited flow and finer routing, then automatic zoom jobs |
| Water systems | Authored lake surfaces and finite outlet/collection checks | Runoff/discharge, controlling sills/storage, nested lakes and verified river-water products |
| Climate and ecology | Researched and planned | World coordinates and continuous climate fields, followed by separate biome/wetland/land-use views |

### How development has been progressing

The September 16–24 history contains useful terrain experiments, but the latest
sequence also spends considerable effort on validation, bounds, caching and
image ownership. These are not wasted: the September 23 rendering experiment
reduced a pathological tall-detail process peak from 1,078.2 to 157.0 MiB.
However, robustness and throughput are not evidence of more believable
landscapes. The last density/review change deliberately preserves default
terrain. See [rendering measurements](2026-09-23-bounded-terrain-rendering.md)
and [connected review](2026-09-24-connected-drainage-review.md).

The development risk is continuing to improve local corrections and proof
machinery around a representation that does not yet express a viable river
path. The previous strategy put full-field continuous bounds immediately after
generator improvements, while many unrelated backlog items also carried P0.
That made the next visible product milestone difficult to identify.

Change the delivery rule: each quality batch must improve a named observable
result on a fixed comparison set, preserve hard contracts, and record what got
worse. Support work should enable that batch or repair a demonstrated defect.
Keep unresolved sampling results honest, but do not require a universal
continuous-field proof before comparing better terrain representations.

At this revision `ui.py` has 3,235 lines, `pipeline/generate.py` 1,457, and TODO
1,292; there are 69 ADRs and 53 research Markdown files including indexes.
These counts indicate navigation/ownership pressure, not measured runtime cost.
Extract changed responsibilities as part of the next feature; avoid a broad
cleanup rewrite. This report and the shorter strategy provide a current entry
point without rewriting historical evidence.

## Current drainage evidence

Source reviewed: `8430d01`. A fresh run of the existing channel-profile benchmark
used the public example, regional, authored and outlet fixtures, seeds 42 and 7,
default density, and 65 stations along each selected D8 edge. Ground is evaluated
through the delivered Float32 field, including final constraints and detail.
The benchmark prepares the field; it is not a full UI/export performance run.

An endpoint-descending edge has a start more than 0.01 m above its end. Its
internal excursion is the greatest sampled rise above any earlier sampled
minimum along that directed edge. This exposes crests and dips hidden by an
endpoint-only check.

| Fixture / seed | Endpoint-descending edges | With internal rise >1 m | With internal rise >10 m | Largest internal rise, m |
|---|---:|---:|---:|---:|
| example / 42 | 2426 | 229 | 38 | 80.976 |
| example / 7 | 2312 | 268 | 40 | 64.777 |
| regional / 42 | 2536 | 273 | 25 | 55.721 |
| regional / 7 | 2346 | 311 | 47 | 131.812 |
| authored / 42 | 1859 | 301 | 47 | 58.643 |
| authored / 7 | 2355 | 294 | 40 | 49.358 |
| outlet / 42 | 1436 | 46 | 4 | 60.826 |
| outlet / 7 | 985 | 34 | 4 | 32.429 |

These are planned paths, **not verified river water**. The table excludes edges
whose endpoints already fail descent; the full report retains all finite
profiles. Counts are not directly comparable to the endpoint warnings in the
connected-review report. Finite probes can miss narrower extrema and do not
certify continuous clearance. No private Tharkeniss Veld build was regenerated.

### Causes supported by code, and remaining hypotheses

1. **Fixed process scale.** `_prepare_automatic_valley_field` uses 257 nodes along
   the longest axis independently of output pixels. On a 4,000 km extent that
   is 15.625 km between nodes. A 1025-pixel preview or zoom does not give it
   finer river routing. Explicit physical process spacing and unresolved-feature
   warnings are needed; simply making every grid much larger multiplies cost.
2. **Direction quantization.** D8 receivers constrain each edge to eight grid
   directions. Connected antialiased display removes thick pixels, but preserves
   those directions. Smoothing a drawn line alone would detach it from incision.
3. **Planning versus finished surface.** Routing uses the constrained macro
   surface; final evaluation reconstructs incision, retains residual detail,
   reapplies authored constraints and clips height. Cut limits can make the
   planned profile unattainable. More interpolation cannot resolve every
   conflict without a route, source, or terrain-generation decision.
4. **Flat handling is a comparison target.** Global Priority-Flood uses tiny
   successor-height increments with stable heap ordering. The basin subsystem
   already has a convergent integer-gradient primitive. Its global reuse may
   improve flat networks, but this audit did not measure how much of the visible
   straightness comes from flat handling versus D8 and terrain structure.
5. **Density is a separate control.** Fewer selected channels improve clutter,
   but do not establish runoff, physical widths, meanders or feasible paths.
   Channel selection, path geometry, ground shaping and display need separate
   measurements. MFD area and unique D8 area are not interchangeable discharge.

The immediate design recommendation is a hybrid: use existing coarse terrain
and authored geography to propose drainage structure, then jointly resolve
continuous channel paths and their surrounding surface. Retain the current
editor, build contracts and adapters. A completely river-first world generator
would impose a larger authoring change and is a comparison candidate, not an
accepted replacement.

## Research that changes the next decisions

### Networks and surface must be designed together

Génevaux et al. build a geometric drainage graph and use its watersheds and
river features to construct terrain. Fischer et al. similarly organize terrain
around artificial drainage basins and water bodies. These are stronger precedents
for our core problem than display smoothing. Their pipelines are not proof of
compatibility with our hard anchors, retention rules or local-detail contract.
[2013 author paper](https://cs.purdue.edu/homes/bbenes/papers/Genevaux13ToG.pdf),
[CGI 2022 author paper](https://cgvr.cs.uni-bremen.de/papers/cgi22/CGI22.pdf).

**Project experiment:** retain coarse catchment proposals; compare a bounded
terrain-guided path within each allowed corridor, with exact shared junctions,
terminal identity and sampled bed feasibility. Use the same path for floor
fitting, actual incision, diagnostics and display. Compare retaining a basin,
rerouting, or moving an automatic head before requesting an excessive cut.
Unreachable authored requirements remain visible conflicts. R09/R32/R48 own this
work; a full irregular-mesh generator is not required for the first experiment.

Barnes' flat-resolution method supplies convergent gradients; Tarboton's
D-infinity supplies continuous hillslope directions with split accumulation.
Test them separately against D8/MFD on controlled surfaces. Neither produces
realistic river meanders by itself. Straight reaches can be legitimate: the goal
is to remove grid dependence, not maximize curvature.
[Barnes et al.](https://arxiv.org/abs/1511.04433),
[Tarboton, 1997](https://digitalcommons.usu.edu/cee_facpub/2507/).

### Measure structure, rather than only height or smoothness

The 2025 terrain-descriptor survey connects graphics evaluation to relief,
curvature, drainage and peak/saddle measurements. Its authors provide a separate
reference application. Use a small nonredundant metric set plus visual comparison;
a single score can reward smooth but uninteresting terrain.
[Survey](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70080),
[author implementation](https://github.com/oargudo/terrain-descriptors).

Orometry-based synthesis uses peak/saddle structure and derives related drainage.
This motivates a branching-range fixture with meaningful passes and tributaries,
rather than another uniformly rough mountain preset. Morphological ridges,
drainage divides and channel beds still have different meanings.
[Argudo et al., 2019](https://perso.liris.cnrs.fr/apeytavi/website/publication/hal-02326472/).

**Project experiment:** extend the existing harness/gallery (R25/R27/R41/R43)
with physical-scale relief, slope/curvature, prominence/pass relationships,
network direction bias and scale-specific sinuosity. Add small provenance-recorded
bare-earth reference patches. USGS 3DEP is a useful public-domain starting point;
match extent and sampling scale, exclude artificial features when appropriate,
and use the examples as design references rather than mandatory Earth geology.
[3DEP products](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services),
[USGS data specification](https://pubs.usgs.gov/tm/11b9/tm11B9.pdf).

### Fast process-informed shaping is worth comparing

Tzathas et al. (2024) use analytical stream-power solutions with iterative
network/surface coupling and multigrid acceleration. This could provide useful
large-scale mountain/valley structure without long geological time stepping.
It is not a one-pass closed-form solution for arbitrary terrain. The paper
reports possible valley relocation when changing age and limitations around
sediment deposition and other erosion laws.
[Author paper, including section 7.4](https://www-sop.inria.fr/reves/Basilic/2024/TGSC24/Analytical_Terrains_EG.pdf).

**Project experiment:** after the path contract, compare one constrained
mountain/valley fixture using a limited stream-power/hillslope stage against
current shaping. Track stage deltas, preserved anchors, routing after restoration,
runtime and parameter sensitivity. Compare a sparse constrained surface solve
only if fitting the resulting bed/ridge targets remains the limiting problem.
SciPy's local-neighbor RBF is a useful interpolation control, not a solver for
all hard inequalities or drainage topology. R14/R16/R32 cover process work.
[SciPy RBF documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html),
[Landlab component tutorial](https://landlab.csdms.io/tutorials/component_tutorial/component_tutorial.html).

### Zoom detail needs processes and boundary context

Schott et al. (2024) combine erosion, thermal effects and deposition over
successive scales. Their public implementation is a more relevant detail
comparison than adding independent noise indefinitely. It does not establish
our exact shared-node, immutable-parent or local-flow guarantees.
[Paper/project](https://h-schott.github.io/p/mserosion/),
[reference code](https://github.com/H-Schott/MultiScaleErosion).

**Project experiment:** compare oblique terrain-conditioned residuals and a
bounded multiscale process on the same parent window. Provide inherited inflow,
trunks, lake identity and exits; evaluate downsampled change, slopes and spectral
leakage separately from exact overlaps. Accept numeric regional behavior before
adding automatic viewport jobs. Small-river display requires both resolved
local hydrology and appropriate on-screen size. R15/R34 remain open.

### Newer alternatives are useful, but not all belong in the critical path

| Candidate | Relevant opportunity | Decision for this plan |
|---|---|---|
| Huftier et al., iso-contours (2026) | Compact, intuitive elevation-band/plateau authoring | R12 comparison after core drainage. The paper itself identifies difficult river widths/slopes and vertical features; it does not solve our immediate river contract. Only pre-generation input use is in scope. |
| McDonald and Cordonnier, stochastic transport (2026) | Momentum-aware transport with meanders, braided rivers and fans | R17 regional comparison after runoff/material accounting; preserve seed ensembles and measure numerical repeatability. Do not assume a stochastic GPU simulation preserves parent samples or authored anchors. |
| FastFlow (2024) | GPU acceleration of flow/depression routing | R31 only after new representative profiles establish that routing dominates. Published hardware speedups are not forecasts for this application. |
| Learned terrain, external DCC tools | Reference character or alternate proposals | Existing R26/R29/R30, deferred; no core-model switch without editable controls, numeric interchange, rights and reproducibility evidence. |

Sources: [iso-contour paper](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70389)
and [code](https://github.com/Arches-Team/Contours);
[stochastic transport authors](https://erosiv.studio/publications/stochastic-geomorphological-transport)
and [code](https://github.com/erosiv/geotransport);
[FastFlow authors](https://www-sop.inria.fr/reves/Basilic/2024/JKGFC24/).
These update existing research candidates, not a claim that every paper is new
since our earlier research.

## Current tool and platform check

Checked on 2026-09-24 using public package metadata and wheel tags for this
CPython 3.14.7 / Windows AMD64 environment. SciPy, Landlab, Fastscapelib and
Numba are absent locally. No new package was installed or external engine run.
A matching wheel is packaging evidence only: complete dependency resolution,
imports, numerical behavior and redistribution review still require a trial.

| Tool | Current evidence | Role and adoption boundary |
|---|---|---|
| SciPy 1.18.1 | Matching cp314 Windows wheel; NumPy >=2.0,<2.8 admits installed 2.5.2; BSD project license with bundled notices | First optional surface-solver experiment, not a base dependency until useful |
| Landlab 2.11.0 | Matching wheel; MIT package, but current dependency list includes GPL-3.0-only `py-richdem` | Isolated external hydrology/process comparison; do not describe its complete dependency environment as MIT-only |
| py-richdem 2.2.0rc3 | PyPI current metadata points to a release candidate with a matching wheel; GPL-3.0-only | Pin and audit a chosen stable/reference environment before use; old `richdem` metadata does not describe this package |
| Numba 0.67.0 / llvmlite 0.49.0 | Matching wheels; Numba's NumPy >=1.22,<2.6 admits 2.5.2; BSD and LLVM-related notices | Measured kernel experiment after profiling, including cold compilation and warm cost |
| Fastscapelib 0.3.0 | GPL-3.0; no compatible wheel in the current release for this environment | Optional external/native reference; no requirement to downgrade the main application or build it now |
| terrain-descriptors | MIT reference code; upstream reports Windows builds and offers binaries; Qt application | External measurement reference; audit sample data and bundled dependencies separately |
| MultiScaleErosion | MIT reference code; upstream documents Windows/Linux and OpenGL >=4.3 | External R15 comparator; driver/runtime and numeric exchange untested here |
| Contours | MIT project code; documented Windows/MSVC/Qt6 setup, separate Qt terms | Optional authoring reference, not a Python library drop-in |
| GRASS | Documented D8/MFD watershed and depression handling | Independent external validation with matching masks, registration and boundary semantics; not a default runtime dependency |

Metadata sources: [SciPy](https://pypi.org/project/scipy/1.18.1/),
[Landlab](https://pypi.org/project/landlab/2.11.0/),
[py-richdem](https://pypi.org/project/py-richdem/2.2.0rc3/),
[Numba](https://pypi.org/project/numba/0.67.0/),
[llvmlite](https://pypi.org/project/llvmlite/0.49.0/),
[Fastscapelib](https://pypi.org/project/fastscapelib/0.3.0/).
Upstream tool evidence: [descriptor application](https://github.com/oargudo/terrain-descriptors),
[multiscale code](https://github.com/H-Schott/MultiScaleErosion),
[Contours build/license](https://github.com/Arches-Team/Contours),
[GRASS watershed manual](https://grass.osgeo.org/grass85/manuals/r.watershed.html).
The [runtime dependency register](../DEPENDENCIES.md) remains unchanged.

## Performance and maintainability decision

Keep Python. The largest current quality defect is algorithm/representation
mismatch; compiling the same grid paths does not remove it. Already-native
NumPy/Shapely/Rasterio work and the existing vectorization/caching improvements
also mean a whole-program language change would not accelerate everything.

Historical measured gains remain useful: the September 17 exact-output routing
optimization reduced 513-pixel public-fixture generation medians by 8.4–28.1%.
September 23 memory work fixed a serious extreme-aspect case. Neither describes
current full-project latency at a finer process grid. Connected review now has
separate preparation/draw timing, not a complete editor memory measurement.
[Routing evidence](2026-09-17-drainage-routing-cost.md),
[rendering evidence](2026-09-23-bounded-terrain-rendering.md),
[review evidence](2026-09-24-connected-drainage-review.md).

Profile the selected next algorithm at explicit physical spacing across a simple
coast, archipelago, many regions/constraints, connected water and repeated zoom
windows. Record generation, validation, display and export separately; include
cold/warm sessions, process peak and cancellation acknowledgement. Geometry
queries, final-field sampling, sequential graph passes and allocation/copying
are candidate costs, not a newly measured ranking. Do not add another cache or
index without a crossover and invalidation/ownership case.

Keep narrow array/graph/surface contracts so a measured kernel can move later.
Rust remains a credible future implementation option under R47, but no new
language migration is selected. During intentional algorithm changes, old-output
hash equality is not a quality goal; unchanged-output optimization controls and
current-run reproducibility remain separate requirements.

## Delivery recommendation

The [strategy](../strategy/README.md) defines batches A–F and their gates:

1. Establish one comparative quality report, add high-value inspection, and test
   convergent flats against a control. Do not build a second benchmark framework.
2. Implement shared terrain-guided channel paths and whole-path feasibility;
   accept a visible/numerical improvement before adding more river features.
3. Build one coherent range-to-lowland fixture using related peaks, passes,
   tributaries and valley shaping. Compare one process/surface alternative at a time.
4. Complete local detail and inherited hydrology; then wire bounded zoom jobs.
5. Add runoff-based water size, lake hierarchy and sediment-aware landforms.
6. Add source-world placement and climate/ecological layers when their dependency
   begins; a simple authored runoff field does not wait for a full climate model.

Supportive editor work in A/B is paired views, selected-channel profiles and
resolution/conflict feedback. Automatic low-resolution previews follow measured
cost; fewer output pixels alone do not reduce canonical routing and water work.
More polish, a Rust rewrite, broad infrastructure, universal bounds, and many
new landform presets are not the next critical path. They remain tracked where
useful. Post-generation editing remains only a potential separate feature.

## Reproduction and validation boundary

```powershell
.\.venv\Scripts\python.exe -m benchmarks.channel_profiles --case example regional authored outlet --seed 42 7 --stations 65 --output artifacts/progress-review-channel-profiles-20260924.json
```

Use a new output filename on repeat. The local report is complete and records
input/canonical/profile hashes, source and fixture identity, and
`continuous_clearance_certified: false`. Package source SHA-256:
`780b3eb721ad4f82038355c39d0a958169349fdf884c0421bfbb17d2cb3f88bc`.
Runtime: CPython 3.14.7, NumPy 2.5.2, Shapely 2.1.2, Pillow 12.3.0,
Rasterio 1.5.1, Windows AMD64. Compact package-check evidence is in the ignored
local `artifacts/progress-review-package-metadata-20260924.json`.

This reassessment changes documentation only. The fresh eight-case profile probe
completed; all 830 checked local Markdown file targets and all newly linked
section anchors resolve. Every published table row and the benchmark/fixture
source hashes were checked against the report. The latest
implementation report records 1,253 passing tests plus Ruff/Pyright, but that suite
was not rerun for this documentation-only change. No visual acceptance of a new
generator, continuous-water certification, external engine comparison, current
whole-application performance profile or private-map result is claimed.
