# Context-bound rough terrain — 2026-09-28

## Outcome

M1 now connects verified spherical geographic context to experimental rough
terrain. The desktop passes its currently generated or opened context through
**World → Terrain**; the CLI accepts `world terrain --context`. The saved project,
portable input snapshot and completed build retain one self-contained immutable
sample binding. Reopening, regional sampling, automatic drainage and verified
parent replay use that same context.

This is a bounded integration result. It is not terrain-quality acceptance, a
climate/runoff model, landscape aging, bathymetry coupling, water transport or an
accepted world parent. Those capabilities remain explicit unsupported metadata.
[ADR-0084](../adr/0084-bind-geographic-context-to-rough-terrain.md) owns the decision.

## Implemented contract

- Terrain preparation requires the exact retained world fingerprint, projected
  coastline bounds/projection and optional geology recipe. A mismatch fails before
  project publication.
- The binding stores at most 129 × 129 samples over the bounded metric AEQD domain.
  Every projected support query must lie between the first and last source
  latitude-cell centres, so its four interpolation nodes exist; unsupported polar
  domains reject rather than extrapolate.
- Shore lower/upper bounds, latitude/longitude, land fraction, water ID, support
  flags, eight water-exposure values, exposure support, water-body records and
  fragmented-body IDs are immutable. Fractions/exposures are bilinear; IDs/flags
  are nearest-support classifications. The water graph and a raster land mask are
  never interpolated.
- Source vector coastline and land mask remain authoritative. The numerical
  consumer is `min(projected-vector distance, conservative spherical upper bound)`.
  It can only reduce the broad coastal-distance input where available context
  resolves projection overestimate. Final DEM differences need not all be decreases
  because automatic drainage can reroute after the base field changes.
- `context_numeric_sha256` hashes geographic metadata and actual arrays, independent
  of preview images or bundle-container bytes. Producer runtime identity stays
  separate. `binding_sha256` covers the transferred metadata and sampled fields.
- Project v9, input snapshot v4 and build v20 carry the optional binding.
  `coastline-constraint-terrain@21` and `regional-budget-mfd-d8-valleys@15`
  identify the consuming terrain pipeline. Geographic context remains format v4;
  `spherical-geography-v5` adds zero-tolerance canonicalization that removes
  collinear ownership-split vertices before shoreline sampling.

The consumer is shared by base/macro fields, automatic drainage and relative-valley
preparation, points, regional sampling and parent replay. Source masks and hard
constraints keep their existing authority. The separate authored bathymetry result
is retained outside this binding until M2 defines a real consumer.

## Continuous conservative shoreline bounds

The first implementation took the maximum lower and minimum upper distance cones
from the nearest four support nodes. Each result remained a valid interval, but the
winning vertex could change discontinuously with the stencil. A public probe across
a `0.000002 km` vertical support edge measured a
`16.078688316394533 km` upper-bound jump.

The accepted implementation convex-combines valid node intervals using the same
nonnegative bilinear weights as the continuous fields. A vertex's contribution
reaches zero as it leaves the stencil, giving C0 continuity while retaining
conservative validity. The corrected probe differs by
`0.000002333701814904998 km`. Intervals may be slightly wider. The upper bound is
the terrain consumer; using the lower uncertainty bound would create a false
zero-height strip near coarse support. [T18](terrain-method-decisions.md#t18---take-extrema-from-the-nearest-four-context-distance-cones)
retains the failed method and revisit gate.

For source shoreline sample `s_i`, source error `E`, query-to-source distance
`d_i` and bilinear weight `w_i`, the first transfer uses:

```text
lower = max(0, sum_i w_i (s_i - E - d_i))
upper =        sum_i w_i (s_i     + d_i)
```

The metric support-to-terrain query applies the same weighted construction to the
retained per-node lower/upper intervals plus node-to-query distance.
Distance to a fixed shoreline is 1-Lipschitz: moving a query by distance `d`
changes its true distance by at most `d`. Each shifted interval therefore contains
the same query distance, so a convex combination also contains it. In the supported
AEQD domain, planar node-to-query distance bounds the spherical distance; using
that larger distance preserves validity at the second sampling stage.

## Continuous land across ownership borders

A physically identical rectangle split between two continent labels initially
changed source shoreline sampling by up to `0.4894432802196995 km`. Redundant
collinear vertices at the ownership join changed how boundary segments were
subdivided. Zero-tolerance simplification and canonical ordering of the physical
land union remove that representation dependency without moving its boundary.
The split and unsplit controls now produce bitwise-identical shoreline distances,
bound shoreline upper values and generated ground. Ownership still remains in
source identity; it does not become a coast or change the numerical result.

## Public paired control

The final control uses a synthetic rectangular continent in a full-world frame on a
1,000 km-radius sphere, longitude ±70° and latitude ±30°. Geographic context is
72 × 144 cells. The selected land projects to a 2,443.4609527920607 km longest
extent with maximum sampled AEQD scale 1.3297574762703228. Source shoreline error
is 5.45415391248228 km; the transferred support grid is 70 × 129.

Both terrain runs use seed 42, resolution 65, maximum elevation 4,500 m, largest
feature 450 km, six detail levels, roughness 0.55, coastal rise 400 km, variability
0.75 and drainage density 1.0. The rectangular domain yields a 35 × 65 DEM with
1,803 land samples. Context changes 910 samples; maximum absolute difference is
122.50662231445312 m and mean absolute difference over land is
2.6880269050598145 m. The identical land outline and small visible change establish
the intended numerical connection, not terrain quality or river acceptance.

| Evidence | SHA-256 / identity |
|---|---|
| Context-off DEM | `fc53a0716a23328c39e96e6908e38fb7a3e2c12d30f686816a4c21205e4514b6` |
| Context-on DEM | `a81fd203e2f3fd823c4a6098477dae0dad66669c116bbbcd448875b7253a5542` |
| Bound context | `835f44110fd59cacf9eaa87e128464c7ca258f147ee8dc96ded73588f1853e84` |
| Installed source | `e0b4296b42a082ccb8761a0b7a4b1b84b3e125e0ea23f63ee5234399501b7ceb` |

The measured runtime was map-maker 0.1.0 on CPython 3.14.7 / Windows 11 AMD64,
NumPy 2.5.2, SciPy 1.18.1, Pillow 12.3.0, Shapely 2.1.2, svgelements 1.9.6,
Rasterio 1.5.1, affine 3.0.1, GEOS 3.13.1, GDAL 3.12.4 and PROJ 9.8.1.
No dependency was added.

## Validation and limits

All ten context integration tests pass, covering conservative bounds, numerical
consumption, unchanged masks and hard constraints, immutable serialization,
source mismatch rejection, CLI/build/parent replay, regional consistency, ownership
splits and continuity at both interpolation stages. Six real-Tk world-workspace
tests pass, including generated-context handoff, save/reopen and terrain generation.
All 12 public schemas pass meta-schema validation, and all 18 JSON examples validate.
Ruff and Pyright pass with zero type errors. The Tk checks instantiate the actual
widgets with the root withdrawn; interactive visual acceptance remains untested.

**Final full pytest result: 1,905 passed, 1 skipped in 614.86 seconds.** The
skipped evolution-reference test requires its isolated scientific environment;
that engine was not changed or exercised by this batch. An earlier full run found
15 stale schema/version assertions and reference-sampler call signatures. Those
were corrected without changing runtime code, passed focused reruns and then
passed the clean complete suite. All 211 Markdown files have valid local targets.
The numerical comparison image was inspected; this does not establish general
terrain or river quality acceptance.

The current scope deliberately excludes climate, runoff, aging, selected-ocean
transport, bathymetry consumption and global/polar process domains. Context water
IDs are display labels, exposure is all-water geographic exposure rather than
rainfall or connected-ocean fetch, and mixed exposure is support information rather
than an error bound. M2 must preserve these distinctions.
