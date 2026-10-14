# Terrain prototype contracts — 2026-09-04

Status: **research and proposed experiments**, not an accepted architecture or
implemented feature. This continues the
[landform-diversity survey](2026-09-04-terrain-realism-and-landform-diversity.md)
with source inspection and small local numerical probes. It refines R03,
R08–R18 and R30–R33 and adds R34–R39 in the [roadmap](../../TODO.md).

The useful next step is a controlled comparison of mountain detail, alluvial
valleys and regional refinement. These need different methods and success
criteria. More erosion everywhere is unlikely to create the desired diversity.

## What was actually checked

- Read the current noise and generation stages at repository baseline
  `72f9773`, including their separate full-detail and macro fields.
- Ran the existing Python 3.14/NumPy code on synthetic coordinates. The probes
  below are measurements of those functions, not a new full-map generation.
- Read the procedural-pattern paper, Landlab SPACE source, MultiScaleErosion
  shaders/resampling/export, and geotransport CUDA source.
- Inspected meanderpy and pyDeltaRCM documentation as specialized references.
  No external engine was installed, compiled, benchmarked or run. Windows and
  Python 3.14 compatibility remains an adoption gate for each complete stack.

## 1. Adding detail currently changes existing band weights

The [noise implementation](../../src/map_maker/terrain/pipeline/noise.py) divides
the accumulated octaves by the sum of their amplitudes. With roughness 0.55,
changing `detail_levels` from 2 to 6 scales the original two bands by
`(1 + 0.55) / sum(0.55**i for i in range(6)) = 0.7173568985`.
Their coefficient falls by **28.26%** while the new bands are introduced.

This is a parameter-change effect, not a failure of coordinate determinism:
the same settings still give the same values at shared coordinates. The
separately evaluated macro field also remains identical in this probe.
Nevertheless, a future refinement control cannot assume that increasing this
parameter adds only new frequencies. The nonlinear height mapping makes an
exact additive interpretation still less appropriate.

| Probe | Result | Interpretation |
|---|---|---|
| 129 × 129 points across 4,000 km, default seed/settings, 2 vs 6 bands | Noise RMS difference 0.1227075 | Includes changed old weights and added bands |
| Same points, artificial constant 500 km coast distance, base elevations | RMS difference 205.254 m | Pre-hydrology function probe; not a real coastline or full DEM |
| Separate macro outputs in that probe | Exactly equal | Macro routing input did not change here |
| 65 endpoint samples refined to 129 | Every second coordinate matches exactly | Nested node grid |
| 65 endpoint samples refined to 130 over 4,000 km | Maximum nearest-coordinate error 15.504 km | Doubling sample count does not nest endpoint grids |

Reproduce from the repository root using the existing environment:

```python
from dataclasses import replace
import numpy as np
from map_maker.terrain.domain import TerrainSettings
from map_maker.terrain.pipeline.generate import _base_elevation_fields
from map_maker.terrain.pipeline.noise import fractal_value_noise

s = TerrainSettings()
x, y = np.meshgrid(np.linspace(0, 4000, 129), np.linspace(0, 4000, 129))
args = dict(seed=s.seed, largest_feature_km=s.largest_feature_km,
            roughness=s.roughness)
n2 = fractal_value_noise(x, y, detail_levels=2, **args)
n6 = fractal_value_noise(x, y, detail_levels=6, **args)
ratio = sum(s.roughness**i for i in range(2)) / sum(
    s.roughness**i for i in range(6))
d = np.full_like(x, 500.0)
z2, m2, _ = _base_elevation_fields(x, y, d, replace(s, detail_levels=2))
z6, m6, _ = _base_elevation_fields(x, y, d, replace(s, detail_levels=6))
print(ratio, np.sqrt(np.mean((n6 - n2)**2)))
print(np.sqrt(np.mean((z6 - z2)**2)), np.array_equal(m2, m6))
c, f = np.linspace(0, 4000, 65), np.linspace(0, 4000, 130)
print(np.array_equal(c, np.linspace(0, 4000, 129)[::2]))
print(np.abs(c[:, None] - f).min(axis=1).max())
```

**Proposal, R34:** compare versioned fixed per-band amplitude budgets with the
existing normalized sum. Preserve old presets and algorithm identity. Measure
coarse-band power and parent restriction before and after height remapping,
constraint restoration and erosion; none of these preserves frequency bands
automatically.

## 2. Regional character needs boundaries and suitability rules

The paper *Real-time Terrain Enhancement with Controlled Procedural Patterns*
supports an oriented-detail experiment, but its limitations explicitly include
table mountains, cliffs, sedimentary valleys and floodplains. Slope alignment
can produce unsuitable linear patterns on nearly flat land, and the method
does not construct a globally coherent river network. Treat it as a candidate
for mountain surface detail within a suitable region.
[Paper, especially limitations](https://onlinelibrary.wiley.com/doi/full/10.1111/cgf.14992).

Three additional design questions follow; these are our proposals, not claims
that the paper already solves the Map Maker constraints:

- **R35 — Blend relief without creating accidental escarpments.** For
  `z = (1-w)zA + wzB`, the gradient includes `(zB-zA) grad(w)`. Even two flat
  surfaces separated vertically by 1,000 m acquire a maximum 3% slope when
  blended over 50 km with cubic smoothstep. This analytical example shows why
  smooth weights alone do not guarantee a smooth-looking province boundary.
  Match reference levels and measure transition slope/curvature separately.
- **R36 — Stabilize the orientation field.** Slopes are ambiguous near flat
  points; opposing directions meet on crests and around saddles. Compare a
  directionless ridge axis with directed downhill flow, define fallback and
  confidence rules, and test phase seams and singularities. Derive reference
  fields in stable world coordinates, independently of preview resolution.
- **R37 — Make process suitability explicit.** Combine authored landform,
  local slope/relief, substrate and drainage confinement to gate detail. A
  plateau top, alluvial floor and mountain flank should not share one recipe.
  Test transition bands and keep suitability inspectable rather than silently
  interpreting an uncertain classification as authored intent.

## 3. Sediment references serve different purposes

### Landlab SPACE: conservation-oriented valley comparison

The audited `SpaceLargeScaleEroder` at Landlab v2.11.0 rejects a
route-to-multiple receiver array. Its flow input cannot simply consume the
current MFD receiver representation; start a reference experiment with a
single-receiver D8 tree. It separates bedrock, soil depth and sediment fluxes;
field metadata gives water discharge in m³/s. Pass flooded-node behavior
explicitly because the constructor and nearby prose differ. The component
also exposes exported sediment quantities useful for an accounting check.
[Pinned component source](https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/space/space_large_scale_eroder.py),
[SPACE model paper](https://gmd.copernicus.org/articles/10/4577/2017/).

**Proposed R16 experiment:** one bedrock channel debouches onto a low-gradient
plain. Hold inlet water/sediment flux, outlet level, substrate and physical
duration fixed. Compare the current incision-only baseline with mobile-cover
transport; add an authored fan/valley-fill recipe as a cheap artistic baseline.

For equal solid density, use a solid-volume ledger such as
`delta mobile + exported bedload + exported fines - imported sediment
- eroded bedrock - external material = residual`.
Mobile storage is `sum((1-porosity) * cover_depth * node_area)`, with the
component's actual active/control-volume areas. Convert every flux to volume
over the timestep. Record uplift and any authoring/parent corrections
separately; do not mistake a sum of elevation differences for conserved mass.
Require nonnegative cover, finite fields, a measured balance residual,
downstream connectivity and a timestep-convergence comparison before claiming
physical behavior. Numeric tolerances must be selected and recorded before
comparing candidates, using simple conservation fixtures as calibration.

### MultiScaleErosion: promising visual process reference, adapter work needed

Audited commit: `64fe87d57d0ea904f54eb0ec24d19da08bebd737` of
[H-Schott/MultiScaleErosion](https://github.com/H-Schott/MultiScaleErosion).
This source inspection does not establish a runtime failure or benchmark.

| Static observation | Consequence for an experiment |
|---|---|
| README says OpenGL 4.3; window creation requests 3.3; inspected shaders declare GLSL 450 | Query actual driver/context, compile shaders and check required functions; a driver may return a newer context |
| Erosion shader initializes a flow contribution using cell-diagonal length | Treat the field as a model-specific proxy until units/scaling are established; do not label it drainage area or discharge |
| Deposition buffers begin independently; the deposition shader adds a stream-power sediment source | Do not assume deposition is a conserved reuse of material removed by the preceding erosion stage |
| A fractional `pow` is evaluated on a signed slope before positive-slope selection | Static numerical-portability concern: negative bases are undefined in GLSL `pow`; test finite outputs and driver behavior |
| GUI doubles node counts and resamples the same endpoint box | Its progressive refinement is not automatically the nested grid contract required here |
| DEM Save normalizes a copy and writes unsigned 16-bit PNG | Preserve scale/offset externally or add numeric export before comparing heights in metres |

Sources: [window context](https://github.com/H-Schott/MultiScaleErosion/blob/64fe87d57d0ea904f54eb0ec24d19da08bebd737/src/code/src/window.cpp),
[erosion shader](https://github.com/H-Schott/MultiScaleErosion/blob/64fe87d57d0ea904f54eb0ec24d19da08bebd737/data/shaders/erosion.glsl),
[deposition shader](https://github.com/H-Schott/MultiScaleErosion/blob/64fe87d57d0ea904f54eb0ec24d19da08bebd737/data/shaders/deposition.glsl),
[deposition initialization](https://github.com/H-Schott/MultiScaleErosion/blob/64fe87d57d0ea904f54eb0ec24d19da08bebd737/src/code/src/gpu_shader_deposition.cpp),
[GUI stepping/refinement](https://github.com/H-Schott/MultiScaleErosion/blob/64fe87d57d0ea904f54eb0ec24d19da08bebd737/src/code/src/main.cpp),
[resampling and Save](https://github.com/H-Schott/MultiScaleErosion/blob/64fe87d57d0ea904f54eb0ec24d19da08bebd737/src/code/src/scalarfield2.cpp),
[Khronos pow definition](https://registry.khronos.org/OpenGL-Refpages/gl4/html/pow.xhtml).

**Proposal, R38:** round-trip a signed, asymmetric metre-valued ramp before any
external visual comparison. Include a below-datum patch, nodata, unequal axis
spacing, explicit registration, extent and unit metadata. Detect min/max
normalization, quantization, flipped/transposed axes and shifted pixel centres.
For this reference, use fixed iteration counts rather than GUI elapsed time.

### Stochastic transport: seed control is only part of reproducibility

The audited geotransport CUDA path uses randomized walks and floating-point
`atomicAdd` to accumulate flux. Different addition orders can affect floating
point results; a fixed seed alone therefore does not establish bitwise
repeatability. This is a source-based concern, not observed repeat-run variance.
[Pinned CUDA path](https://github.com/erosiv/geotransport/blob/97e893502f7c2e45e4ffa3c93518a7dfd9aa9454/source/geotransport/path.cu),
[NVIDIA floating-point guidance](https://docs.nvidia.com/cuda/floating-point/index.html).

The inspected package metadata combines `requires-python >=3.8` with a
`cp312` wheel API setting. Neither alone proves the complete Windows/Python
3.14 runtime works. Keep R17 experimental and record wheel/build identity,
device/driver, precision, actual seed handling and repeat-run error. Compare a
deterministic reduction only if this backend becomes worth adopting.
[Pinned build metadata](https://github.com/erosiv/geotransport/blob/97e893502f7c2e45e4ffa3c93518a7dfd9aa9454/pyproject.toml).

## 4. Specialized alternatives for river character

| Candidate | What it adds | Appropriate boundary |
|---|---|---|
| meanderpy, Apache-2.0 | Curvature-driven centreline migration, cutoffs and channel-belt history | A confined regional channel experiment; its kinematic model does not solve the flow-velocity field |
| pyDeltaRCM, MIT | Reduced-complexity delta evolution using water/sediment parcel routing | A river-mouth window with inlet, receiving basin, sediment and sea-level conditions |

Sources: [meanderpy repository and model explanation](https://github.com/zsylvester/meanderpy),
[pyDeltaRCM repository](https://github.com/DeltaRCM/pyDeltaRCM),
[pyDeltaRCM hydrodynamics](https://deltarcm.org/pyDeltaRCM/info/hydrodynamics.html).

pyDeltaRCM documents conservation of total sediment during erosion, but not
separate sand/mud inventories: either category is available for erosion at
any location. Its stability guidance includes keeping the growing delta away
from the domain boundary. Those assumptions matter for lithology and small
regional windows. Its NetCDF coordinates also use `x` for downstream distance;
an adapter must not assume our displayed Cartesian axes.
[Morphodynamics and limitations](https://deltarcm.org/pyDeltaRCM/info/morphodynamics.html),
[output coordinates](https://deltarcm.org/pyDeltaRCM/info/outputfile.html).

**Proposal, R39:** compare meanderpy against an authored spline corridor before
considering a general transport engine. Measure bend wavelength, sinuosity,
cutoff handling, valley-wall intersection and outlet continuity. Keep endpoint
and grade constraints explicit. For deltas, compare a bounded distributary
recipe with pyDeltaRCM using fixed inlet and sea conditions; check split/join
flux, land/water semantics, domain truncation and exported sediment. Preserve
river-mouth relocation and coast change as reviewable proposals. These are
separate experiments, not two new mandatory dependencies.

## 5. Three experiments worth doing next

All experiments first need the strategy's coordinate, provenance and numeric
comparison foundations. Archive settings and stage results, use the same
colours/light/view, and report validity separately from visual preference.

| Experiment | Small fixture and variants | Measurements and stop conditions |
|---|---|---|
| A: Regional mountain character | Mountain flank adjoining a plateau and alluvial floor; existing noise, fixed-band noise, masked oriented detail; include rotated terrain and a saddle | Coarse-band power, relief/slope distributions, transition gradients, phase seams, hard-anchor errors and final drainage. Reject floor striping or broken authored passes |
| B: Sediment-filled valley | Channel opening onto a plain; current incision, bounded authored fill, SPACE bedrock/cover comparison | Solid-volume ledger, cover nonnegativity, valley cross-sections, deposition footprint, outlet continuity, convergence and runtime. Reject unaccounted correction volume |
| C: Regional refinement | Same world window at 65, 129 and 257 endpoint samples, with halo and fixed parent; include a channel crossing the boundary | Shared-node equality, explicit parent restriction, overlap slope/height, inherited inlet flux and rerouted final surface. Reject seams or hidden parent movement |

For C, endpoint-node refinement is `Nfine = 2*(Ncoarse-1)+1`; cell-centred
grids need their own registration/resampling rule. Shared nodes and equal
coarse-cell means are distinct requirements. As a simple counterexample,
piecewise-linear heights `[0,1,0,1,0]` agree with coarse `[0,0,0]` at shared
nodes but have interval mean 0.5 rather than 0. Decide which restriction
operator defines the product, then test it; do not silently replace existing
shared-point guarantees. Final constraint restoration can invalidate either
drainage or restriction, so check the actual delivered surface.

Recommended sequence: run A's band/boundary measurements first; proceed to the
masked visual comparison once they are stable. Use B to judge whether sediment
adds useful broad valleys beyond inexpensive authoring recipes. Run C before
adopting any method advertised as multiscale. Meander and delta engines remain
targeted follow-ups when those particular landforms are the desired result.
