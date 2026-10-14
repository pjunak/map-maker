# Geological structure and terrain composition — 2026-09-05

Status: **research and proposed experiments**. This continues the
[prototype contracts](2026-09-04-terrain-prototype-contracts.md), refines R09–R11,
R25 and R37, and adds R40–R44 to [TODO](../../TODO.md). It does not change the
generator, public schema, authored geography or accepted architecture.

The strongest direction is to give regions coherent internal structure and
meaningful relationships to their neighbours. A mountain belt, plateau and
plain should differ in arrangement, cross-sections and drainage, not merely
in maximum height or noise strength. Geological tools can inform those
controls without requiring a reconstruction of an entire planet's history.

## Scope and evidence

Reviewed local baseline `1bcc3cf`, particularly the
[domain types](../../src/map_maker/terrain/domain/models.py),
[authoring state](../../src/map_maker/terrain/domain/project.py), and
[generation pipeline](../../src/map_maker/terrain/pipeline/generate.py).
Public structure kinds remain ridge and valley. The pipeline already smooths
structure lines, preserves compatible junction widths and attaches profile
anchors. Geological materials and typed fault/divide/plateau objects are not
implemented domain concepts; proposals should extend the existing architecture.

External evidence consists of research abstracts, an author-team project
summary, the full HTML LoopStructural paper, and official tool documentation
and repository descriptions. This is not a full-text review of every cited
paper. A small NumPy descriptor probe was run locally. No external geological,
GIS or topology package was installed or benchmarked.

## 1. Compose connected regions rather than independent texture patches

**Proposal, R40:** define optional relationships between authored terrain
regions: continuity of a mountain belt, a plateau margin facing a basin, a
valley crossing a boundary, or a sediment-receiving plain below an upland.
These are editable design hypotheses. They should report conflicts with
existing coastlines and constraints, not automatically move those inputs.

| Regional recipe | Structural controls worth comparing | Observable result |
|---|---|---|
| Folded mountain belt | Belt axis, asymmetric flanks, fold wavelength, exposed resistant units | Directional ridges with related spacing and cross-sections |
| Dissected plateau | Cap height/thickness, plateau boundary, escarpment side, incision corridors | Broad surviving uplands adjoining incised valleys |
| Tilted layered region | Bedding orientation, unit thickness, resistance contrast | Related asymmetric ridges and drainage corridors |
| Fault-bounded basin | Fault trace/side, offset hypothesis, basin boundary, outlet and fill | A coherent steep margin and sediment-receiving lowland |
| Alluvial plain | Upstream flux, valley confinement, sediment cover, water/outlet levels | Low-gradient connected floors with locally appropriate channels |

These recipes are not universal rules for interpreting Earth geology. Similar
surface forms can have different histories. Compare a few explicit hypotheses
and retain the author's selected geography as the fixed input.

*Sculpting Mountains: Interactive Terrain Modeling Based on Subsurface Geology*
demonstrates a geological authoring approach combining plate deformation,
stratigraphy, uplift and erosion. Its relevance is coordinated structure and
author control, rather than a promise that arbitrary authored coasts and peaks
can be reproduced by its simulation.
[Author-team research summary](https://radar.inria.fr/report/2018/imagine/uid47.html).

The earlier *Large Scale Terrain Generation from Tectonic Uplift and Fluvial
Erosion* is a relevant upstream research reference for R11/R14. Its publication
was verified here; implementation and parameter behavior were not audited in
this pass. [Institutional publication record](https://gfzpublic.gfz.de/pubman/item/item_1945962).

## 2. Geological layers need spatial meaning and event order

LoopStructural models geological features through implicit fields and explicit
relationships between events. Its time-aware reconstruction builds recent
features first to constrain older ones. The paper describes evaluating both
field values and gradients at coordinates, which is useful for querying
material identity and orientation without first extracting a dense mesh.
[LoopStructural 1.0 paper](https://gmd.copernicus.org/articles/14/3915/2021/index.html).

**Proposal refining R10/R11:** start with a small analytical substrate reference:
one horizontal or tilted package of layers and one optional fault. Query the
material at the evolving bedrock surface, keep mobile sediment separate, and
record event ordering. A reconstruction library's reverse-time ordering must
not be confused with forward process simulation or arbitrary pipeline order.

For planar bedding in an x–z cross-section, a useful synthetic coordinate is
`q = z*cos(dip) - x*sin(dip)` with x and z both in metres. Layer intervals in q
then have true normal thickness. Using `z - x*tan(dip)` without rescaling
instead gives vertical separation. The distinction matters as dip changes.

A 100 m thick bed dipping 30 degrees intersects horizontal ground in a strip
200 m wide (`thickness / sin(dip)`). The existing default 4,000 km / 256-interval
drainage grid has 15,625 m spacing: that strip is only 0.0128 intervals wide.
This analytical example is not a terrain simulation. It shows why thin layers
cannot be represented by treating each coarse process sample as one resolved
rock band. Compare effective coarse resistance with explicit local contacts;
choose refinement from feature width and convergence, not preview pixels.

Additional experiment requirements:

- Keep material coordinates separate from current elevation. Erosion can
  expose an older layer; it should not drag the entire stratigraphy downward.
- Distinguish fault displacement of substrate from an authored surface
  escarpment. They may interact, but neither determines the other exactly.
- Use a contact/outcrop overlay to verify geometry before applying erosion.
  Cross-sections should check true thickness, dip, offset and event ordering.
- Treat erodibility as model-specific. A dimensionless artistic resistance is
  not automatically a physical stream-power coefficient or rock strength.
- Keep caves/overhangs outside the single-valued DEM contract. A volumetric
  material field does not require changing the surface output to a voxel model.

[LoopStructural](https://github.com/loop3d/LoopStructural) is an MIT-licensed
Python reference for folds, faults and implicit interpolation. Its broader
model and optional visualization/export stack are unnecessary for the first
analytical fixture. Complete Windows/Python 3.14 compatibility and performance
remain untested here.

## 3. Preserve different meanings of terrain and water networks

The 2023 paper *Surface network and drainage network: towards a common data
structure* explicitly distinguishes morphological ridges from drainage divides
and thalwegs from streams. It extends a surface network with additional
relationships and flow direction, rather than treating the original graphs
as interchangeable. Its comparisons also identify sensitivity in flat or
slightly convex areas.
[Journal abstract and publication](https://josis.org/index.php/josis/article/view/240).

**Proposal, R42:** record typed relationships among authored ridge/valley lines,
derived surface ridges/thalwegs, drainage divides, and active channels. Retain
source surface, algorithm, scale and depression policy. A line can have several
roles, but that must be established rather than implied by its name.

Suggested fixtures are a broad rounded divide, a saddle between two peaks,
a dry valley, a flat basin with an outlet, and an authored river crossing a
ridge constraint. Compare topology before and after height restoration. Keep
the current D8/MFD comparison and intentional-basin semantics; a new graph
representation is not a reason to replace them wholesale.

The authors' [SurfaceNetwork implementation](https://github.com/ericguilbert/SurfaceNetwork)
is a GPL-3.0 reference using NumPy, Shapely and GDAL-related I/O. Its README
states that holes are treated as low areas belonging to the connected domain.
That differs from general ocean/nodata/lake semantics. It belongs in an
isolated comparison until mask behavior, dependencies and licensing are
reviewed for the intended use. Do not copy it into the core as a shortcut.

## 4. Measure arrangement, orientation and observation scale

### A local counterexample to histogram-only scoring

On a 129 × 129 grid, construct a ramp from 0 to 1,000 m, transpose it, and
randomly permute its samples with seed 20260902. All three have exactly the
same sorted elevations, mean 500 m and standard deviation 290.921668 m.
Their spatial structure is very different:

| Surface | Mean neighbour height jump, m | X semivariance at lag 8, m² | Y semivariance at lag 8, m² |
|---|---:|---:|---:|
| X ramp | 3.906250 | 1953.125 | 0 |
| Y ramp | 3.906250 | 0 | 1953.125 |
| Shuffled heights | 336.519227 | 85558.896 | 84170.061 |

This is a diagnostic counterexample, not an Earth-analogue benchmark. The
neighbour statistic averages absolute differences along both axes; it is not
a slope until divided by physical spacing. Semivariance is half the mean
squared elevation difference at the given lag. Reproduce in the existing
NumPy environment from the repository root:

```python
import numpy as np
z = np.tile(np.linspace(0.0, 1000.0, 129), (129, 1))
rng = np.random.default_rng(20260902)
variants = [z, z.T, rng.permutation(z.ravel()).reshape(z.shape)]
for a in variants:
    assert np.array_equal(np.sort(a.ravel()), np.sort(z.ravel()))
    jump = (np.abs(np.diff(a, axis=0)).mean()
            + np.abs(np.diff(a, axis=1)).mean()) / 2
    gx = np.mean((a[:, 8:] - a[:, :-8])**2) / 2
    gy = np.mean((a[8:, :] - a[:-8, :])**2) / 2
    print(a.mean(), a.std(), jump, gx, gy)
```

**Proposal, R41:** add directional variograms or spectra over several physical
lag distances to R25's analogue descriptors. Record whether broad trend was
removed, valid-pair counts near masks, angular sampling and physical units.
Report orientation-sensitive and rotation-normalized comparisons separately:
one checks an authored belt direction, the other compares terrain character.
Do not demand an isotropic result from a deliberately directional range.

*Multi-scale characterization of topographic anisotropy* presents
every-direction variogram analysis for direction and scale dependence. Its
abstract supports this measurement choice; it does not establish a unique
geological history from a measured orientation signature.
[Paper abstract](https://doi.org/10.1016/j.cageo.2015.09.023).

### Classifications must name their observation scale

GRASS `r.geomorphon` uses search distance and angular flatness thresholds;
its `-m` option accepts distance parameters in metres. The documentation
discusses changes with observation radius and limitations of coarse DEMs.
The `comparison` setting also affects threshold/tie handling. Record these
settings rather than storing an unexplained label such as "plain".
[Official manual](https://grass.osgeo.org/grass-stable/manuals/r.geomorphon.html).

`r.param.scale` supplies a complementary quadratic-fit approach for slope,
curvature and feature classification at a chosen window size. Its aspect
convention differs from the usual expectation: west is zero, with signed
angles through north/south. Adapter fixtures must check orientation and
curvature conventions before comparing results.
[Official manual](https://grass.osgeo.org/grass-stable/manuals/r.param.scale.html).

**Proposal, R43:** retain landform descriptors at several world-unit radii,
including unavailable/insufficient-support states at coasts and small islands.
A locally flat patch may lie on a plateau or valley floor. Condition R37's
process masks on broader context and water/substrate evidence as well as local
shape. Use a halo at least sufficient for the chosen neighbourhood, record
effective rounded windows, and test rotations and resolution changes.

### Significant peaks and passes need more than a raw count

TTK provides persistence diagrams, merge trees, Morse–Smale complexes and
topological simplification on scalar fields. Its tutorials explain pairing
critical features by elevation difference. This supplies a reference for
separating small bumps from substantial peak/saddle structure.
[Toolkit and interfaces](https://topology-tool-kit.github.io/),
[terrain persistence explanation](https://topology-tool-kit.github.io/persistentHomologyDummies.html).

**Proposal, R44:** compare persistence and peak/saddle relationships before
and after detail, erosion and refinement. Use metre-valued thresholds and
explicit boundary/mask rules; study plateaus, tied elevations and disconnected
islands. Do not assume an arbitrary persistence pairing is exactly the desired
geographic prominence convention. Preserve authored passes even when their
numeric persistence is small. Initially use TTK read-only: simplification
must not silently edit the delivered DEM. Its BSD-licensed C++/ParaView/Python
tooling is an optional reference, with local runtime compatibility unverified.

## Recommended additions to the existing experiments

| Existing experiment | Addition | Acceptance evidence |
|---|---|---|
| A: Regional mountain character | Compare connected mountain/plateau/plain recipes; add one tilted substrate fixture | Distinct cross-sections, resolved contacts, directional descriptors and bounded transition errors |
| B: Sediment-filled valley | Separate material exposure from cover; distinguish valley and active-channel graphs | Correct source layers, sediment ledger, valid outlet and explicit dry/active channel semantics |
| C: Regional refinement | Compare world-scale descriptor curves and significant landmarks | Stable large features, explained new local features, no unsupported coastal labels or lost authored passes |

Start with the analytical layer and descriptor counterexamples, then a small
recipe gallery with fixed geography. Use LoopStructural, SurfaceNetwork, GRASS
and TTK only for the particular comparison each can answer. No evidence here
justifies loading all four into the base environment or promoting geological
reconstruction ahead of the strategy's coordinate and numeric-output work.
