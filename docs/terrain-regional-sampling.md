# Sample a finer regional window

The `sample-region` command evaluates the existing terrain field more densely
inside a chosen source-local rectangle. It reuses the complete coastline,
authored constraints, regional recipes, prepared valley profiles and canonical
routing context. This is the first executable foundation for zoom-driven local
generation. Automatic workbench requests remain planned. A separate
[verified-parent operation](terrain-parent-regions.md) now provides finished-build
replay and opt-in experimental added detail.

## Try the public example

From the repository root, choose a new output directory:

```powershell
.\.venv\Scripts\python.exe -m map_maker terrain sample-region examples/terrain/landform-regions.terrain.json --output artifacts/regional-demo --bounds-km 1000 800 2000 1800 --refine 4
```

Bounds are `x0 y0 x1 y1` in kilometres in the project's existing local plane:
x increases right and y increases down from the source's minimum coordinates.
The requested bounds must lie inside the complete source frame. This command
reads the saved project, independently of any unsaved workbench edits. Open
`scientific.png` in the result directory to inspect the ground.

`--refine 4` subdivides each interval of the project's saved output grid four
ways along each axis. Powers of two from 1 through 65536 are accepted. Resolution
controls sampling density; the saved detail settings and all terrain algorithms
stay unchanged. A new process prepares the global field once. Python callers
can retain `prepare_regional_sampler(...)` and reuse its `sample(request)` method
for several windows without repeating preparation.

## Coordinates and bounds

The request records inclusive integer addresses on this globally anchored finer
grid. Metric bounds round outwards to covering nodes. The delivered extent can
therefore be slightly larger than the requested rectangle. Each request includes
a one-cell sampling halo, clipped at the full source boundary; the Python
request type accepts 0 through 32 halo cells.

Original reference nodes retain their exact coordinates. New points subdivide
individual original intervals, so nested refinement levels, overlapping windows
and repeat visits reuse the same positions. Read the exported Float64 axes:
reconstructing an axis independently with `linspace` can introduce tiny rounding
differences. Grid spacing in the manifest describes the nominal endpoint grid.

Requests exceeding **2,000,000 nodes including the halo** fail before global
preparation or output creation. Evaluation batches contain at most 65,536 points.
Only regional axes and output arrays are allocated at the finer resolution.
Preparation still covers the full source's canonical context, so this is a sample
budget, not a hard total-memory or wall-time guarantee for arbitrary geometry.

## Products and provenance

| File | Contents |
|---|---|
| `samples.npz` | Buffered Float32 ground and water surfaces in metres, boolean land mask, Float64 x/y axes in kilometres, UInt32 basin-intent IDs |
| `scientific.png` | Ground elevation colours and hillshade, computed with the halo before cropping to the core window |
| `inputs.json` | Full effective source geometry, settings, constraints and authoring-state snapshot |
| `manifest.json` | Completion record, source/runtime/algorithm identities, grids, request, crop slices and output hashes |

Load the NPZ with `allow_pickle=False`. Ground is NaN outside land. Water is
NaN wherever no authored lake surface lies above ground by the existing 0.01 m
water tolerance. Dry basins retain IDs without receiving water. Footprint IDs
keep their complete-source ordering across windows. These are sampled water
levels; no local shoreline/flow acceptance is claimed.

The manifest's `core_slice.rows` and `.columns` contain Python start/stop pairs
with an exclusive stop. Use them on the buffered two-dimensional arrays to
extract the core. Corresponding slices select y and x axes. The PNG already
contains only the core; its metadata identifies the numeric archive and field.
Scientific ground omits lake colouring, avoiding classification of a cropped
lake as a complete water body.

[Regional samples v3](../schemas/terrain/regional-samples-v3.schema.json) is a
separate artifact contract from [full builds](terrain-builds.md). Its source
field ID hashes full inputs and numeric algorithm identities. The artifact ID
also binds request, runtime, source-file hashes, seeds and output hashes. The
application checks source files and runtime again before publishing completion.
Existing destinations are rejected. Failure can leave partial files, but no
completed manifest. No project or completed terrain is modified.

## Remaining generation work

The reference is the input-defined global field and its output grid. This
operation does not consume or condition against an immutable finished parent
DEM. It adds samples, with no additional noise/detail bands or refined local
hydrology. Canonical routing still uses its complete-source 257-longest-side
grid. Its extent remains the whole source even when a window is far smaller.

Noise bands now retain their amplitudes when more bands are selected
([ADR-0059](adr/0059-preserve-noise-band-amplitudes.md)). This command still uses
unchanged settings; it does not add bands. Next work must define parent
restriction/downsampling and height/slope tolerances, preserve upstream flow
and outlet boundaries during finer hydrology, and keep whole-lake identity.
R34 remains open because stable coefficients do not preserve finished terrain
or its coarse-cell averages. The
[parent-cell experiment](research/2026-09-23-parent-cell-preservation.md) rejects
one bilinear/trapezoidal conditioning candidate: exact parent nodes and means
still alter existing structure, authored heights and channel profiles. The next
candidate now retains a verified parent reference and constrains only added
residuals independently of output sampling density in the separate
[parent-region experiment](terrain-parent-regions.md). It is not part of this
unchanged-field API; visual/spectral acceptance and finer hydrology remain open.
Small cartographic rivers require that finer terrain/hydrology evidence.
[Cooperative cancellation](terrain-generation-control.md) is implemented for this
API. Workbench zoom scheduling and memory admission for this input-defined API
remain open. Separate [parent sessions](terrain-parent-regions.md) provide
freshness-checked numeric caching and [shared admission estimates](terrain-regional-memory.md). See [TODO](../TODO.md), [ADR-0058](adr/0058-sample-bounded-regional-windows.md)
and the [measurements](research/2026-09-22-regional-field-sampling.md).
