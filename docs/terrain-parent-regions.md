# Generate a region from a verified parent

Two commands now consume completed terrain builds. `sample-parent` samples the
parent's unchanged prepared field more densely. `enrich-region --experimental`
adds a small, protected residual to that field. Each writes a separate result;
neither changes the parent or any authored input. Workbench zoom jobs are still
planned. Small rivers remain unavailable until finer hydrology is implemented.

The [world-context plan](strategy/world-context.md) adds a future hierarchy of
world → continent/region with shared climate, histories and one geological present.
WC5/LE6 historical refinement requires time-dependent parent boundary/forcing;
it must not age a completed parent again. Neither command below supplies that
capability, world placement or a continent-history model.

## Quick public example

The [local-detail project](../examples/terrain/local-detail.terrain.json) uses
the existing public coastline and landform instructions with a small 65-node
longest-side parent and two detail bands. From the repository root, choose new
output directories:

```powershell
.\.venv\Scripts\python.exe -m map_maker terrain build examples/terrain/local-detail.terrain.json --output artifacts/detail-parent
.\.venv\Scripts\python.exe -m map_maker terrain sample-parent artifacts/detail-parent --output artifacts/parent-window --bounds-km 1375 800 1875 1300 --refine 16
.\.venv\Scripts\python.exe -m map_maker terrain enrich-region artifacts/detail-parent --output artifacts/detail-window --bounds-km 1375 800 1875 1300 --refine 16 --amplitude-m 40 --experimental
```

Open `artifacts/detail-window/comparison.png`: left is the verified reference,
middle is experimental ground, and right is the actual added height in metres
(blue lowers, red raises). The reference and detailed panels use the same height
scale; the difference panel uses the largest absolute change in this result.
Each comparison panel fits within 1024 by 1024 pixels without upscaling; a
footer and PNG metadata identify reduced previews and their native dimensions.
The maximum added height comes from the native samples before resizing.
`scientific.png` retains the full requested core size and contains only the
detailed ground. Nothing is loaded into the workbench automatically.

Use `--amplitude-m` in (0, 100]; the default is 12 m. This is an upper residual
budget, not a calibrated geological parameter. Parent settings and their noise
bands are unchanged. Broad cell protections can produce a region with no added
heights; check `detail.evidence.changed_samples` in its manifest. The explicit
experimental flag is required because this formula has not passed visual,
spectral or hydrological acceptance.

## Verified parent contract

Only [current build v20](../schemas/terrain/build-v20.schema.json) from the exact
current source/runtime is accepted. Rebuild after changing installed source or
dependencies. Old builds have no compatibility loader.

The loader checks completion, manifest identity, all required product names,
sizes and hashes, runtime, algorithms, settings and coordinates. Numeric headers,
dtypes and shapes are checked before allocation; object arrays are forbidden.
The [typed input snapshot](../schemas/terrain/input-snapshot-v4.schema.json)
contains full coastline geometry, explicitly typed constraints, settings and
saved authoring controls. Original project/SVG files need not remain available.
Their hashes remain provenance; the snapshot does not pretend to recreate their
original file bytes.

Preparation reconstructs the full input-defined field, then checks **every**
delivered Float32 ground, land, water and basin-ID sample. It also checks the
canonical axes, land mask, source/final heights, receivers, channels, accumulation
and incision budgets actually reused by the operation. A mismatch rejects the
parent. Read-only owned arrays retain this prepared reference across API calls.
This is reconstruction and verified replay, not a serialized Python cache.

File hashes are checked again before publication, as is runtime identity. Existing
destinations and outputs inside the parent directory are rejected. A failure may
leave partial output files but no completed manifest. A parent-region artifact
cannot itself be used as a parent build: recursive enrichment is not implemented.

## Sampling, budgets and outputs

Bounds use the parent's original local kilometres, x right and y down. No world
projection is introduced. Requests round outward to globally anchored fine-grid
nodes and include one halo cell. The existing [regional request rules](terrain-regional-sampling.md)
apply: power-of-two refinement and at most 2,000,000 delivered nodes including
halo. Experimental detail requires refinement at least 8 and at most 4,096
parent cells including a one-parent-cell support halo around the buffered window,
clipped to the parent frame. This support halo is separate from the fine-node
output halo. A formerly fitting request can now exceed the preparation limit;
choose smaller bounds. Original parent nodes are exact.

Each eligible cell uses a fixed 17 by 17 probe lattice, independently of output
resolution. Thus an uncached request adds at most 1,183,744 probes. The pointwise
output uses batches of at most 65,536. Full-parent replay and complete-source geometry,
constraints and routing still cost work outside the window; these limits do not
claim a hard total-memory/time bound for arbitrary input geometry.

| Product | Content |
|---|---|
| `samples.npz` | Buffered ground/mask, axes, sampled water and basin IDs; detail mode also includes reference ground, actual added heights, addressed cell budgets and fixed reference/detailed moments |
| `inputs.json` | Portable typed parent inputs, unchanged |
| `scientific.png` | Ground shaded with the halo, then cropped to the requested core |
| `comparison.png` | Reference/detail/added-height review; each panel at most 1024 by 1024, experimental mode only |
| `manifest.json` | Parent identities and replay counts, request/grids, runtime, stage seed, detail evidence, capability limits, file hashes and completion identity |

Load NPZ with `allow_pickle=False`. `core_slice.rows` and `.columns` contain
exclusive-stop Python slices. Ground is Float32 metres and NaN off land. Added
heights are zero off land. `cell_columns`/`cell_rows` address the original parent
cells; protected cells have zero amplitude and NaN moments because no probes
were needed. Some otherwise eligible cells can also have zero amplitude when
the observed terrain reaches its height bounds. `active_cells` counts nonzero
local budgets; a cell surrounded by protected neighbors can still receive no
addition. `changed_samples` reports actual delivered changes.

The [parent-region v1 schema](../schemas/terrain/parent-region-v1.schema.json)
explicitly distinguishes `reference-samples` from `experimental-detail`.
Completion means the described experiment finished; it does not mean the detail
is accepted for cartography. `refines_hydrology` and `small_rivers_ready` are
always false. The parent's existing diagnostic routing is not upgraded to rivers.

## Experimental preservation rule

The existing prepared field is retained everywhere; there is no bilinear
replacement of its interior structure. Only a new additive residual is generated.
Coefficients depend on the named `terrain.local-detail` seed and global parent
edge addresses. Both cells use the same shape and budget at a shared edge.
Fixed-probe terrain slopes weight the horizontal and vertical contributions;
this is a limited directional preference, not arbitrary ridge orientation.
The added field has zero analytic mean in every parent cell and retains exact
parent nodes. Its values and first/second derivatives agree across shared edges
in real arithmetic. Cell-edge values may now differ from the unchanged parent.
The fixed trapezoidal reference moments come from the prepared field, not four
sparse corner heights. Float32 storage introduces small measured moment errors.
[ADR-0068](adr/0068-share-terrain-detail-across-edges.md) supersedes the old
cell-interior formula; there is no compatibility mode.

Whole cells touching authored point/line cores, basin footprints or buffered
planned channel edges are protected. Cells near the coastline are also excluded.
This conservatively keeps authored heights, sampled lake ground and inherited
planned channel corridors unchanged, including between original nodes. These
protections are fixed against the full source, not recomputed from a cropped
catchment.

Amplitude uses half the smallest observed distance from zero/the elevation
representable Float32 ceiling on the fixed probes, capped by the requested budget.
An edge uses the smaller adjacent budget, so an excluded cell also suppresses
its shared edges. Those probes do not certify unseen extrema: if a delivered
point exceeds a bound, the request fails instead of clipping and changing its
moments. Whole and partial-cell window boundaries must be displayed with another
result of the same detail field; even a parent-cell edge need not meet an
unenriched parent. A display transition has not yet been implemented.

[Paired measurements](research/2026-09-23-shared-edge-detail.md) show connected
additions and smaller quantized boundary slope errors, with some increased
coarse-scale spectral leakage. Grid direction and protected gaps remain visible.
Oblique terrain support, cartographic/spectral acceptance, transitions to the
unenriched parent, partial coastal/basin detail, inherited outlet paths and
upstream flow, finer routing, broader memory calibration and workbench requests
remain open.
[Cooperative cancellation](terrain-generation-control.md) is now implemented. Read
[ADR-0061](adr/0061-verify-parents-and-isolate-local-detail.md), the
[measurements](research/2026-09-23-verified-parent-detail.md) and [TODO](../TODO.md).

Python callers can reuse `prepare_verified_parent(...)` and its regional sampler,
then `prepare_regional_detail(...)` across windows. File loading belongs to
`load_terrain_parent(...)`; `sample_parent_region(...)` owns completion checks
and publication. A cached caller must retain and verify the corresponding parent
and runtime identities before publishing any result.

## Reuse fixed cell preparation

`prepare_regional_detail(parent, settings, cache_cells=4096)` owns a private
least-recently-used cache. Each entry stores only the protection flag, amplitude,
terrain-direction weight and reference/detailed means for one globally addressed
parent cell, including support-halo cells. A halo-only cell has no detailed mean
until first delivered; that first delivery samples its reference probes again.
Subsequent windows reuse complete records across overlaps and refinement levels.
During preparation, a temporary Float32 probe bank holds at most 4.52 MiB while
adjacent budgets become available; it is released before delivery and included
in memory admission. Neither probes nor delivered terrain arrays enter this
scalar cache. Ground delivery and its height checks run for every request.

Choose an integer capacity from 0 through 4,096; zero disables reuse. The bound
applies to scalar entries per context, not total application memory. Eviction
only causes recomputation. `context.clear_cache()` frees the entries and resets
counts; `context.cache_info()` reports capacity, retained cells, hits, misses
and evictions. Use a context serially. Creating or replacing a context starts a
fresh cache, so changed parents/settings cannot inherit another context's values.

Artifact evidence stays independent of cache history: `parent_cells` counts
cells touched by the output, `support_cells` includes the preparation halo, and
`probe_samples` counts fixed probes for all eligible support cells, including
cached support. It is not the number of evaluations performed on this visit.
Cache counters are operational and are never serialized in the result.
The CLI creates one context per invocation; reuse currently benefits Python
callers that retain it across requests. Parent/runtime checks before publication
remain required. See [ADR-0062](adr/0062-reuse-bounded-detail-cell-support.md) and
the [measurements](research/2026-09-23-detail-cell-reuse.md).

## Write several artifacts in one verified session

Use the application session to reuse parent replay, cell support and bounded
numeric results while retaining automatic file/runtime checks:

```python
from pathlib import Path
from map_maker.terrain.application.parent_region import ParentRegionSession
from map_maker.terrain.domain.regional import RegionalDetailSettings

with ParentRegionSession(Path("artifacts/detail-parent")) as session:
    for name, refinement in (("near", 8), ("closer", 16), ("revisit", 8)):
        manifest = session.write(
            Path("artifacts") / name,
            (1375.0, 800.0, 1875.0, 1300.0),
            refinement,
            detail_settings=RegionalDetailSettings(40.0),
        )
        print(manifest, session.cache_info())
```

Choose new output directories for every write. Omit `detail_settings` to sample
the unchanged parent field. Experimental detail retains all acceptance limits
above. The session validates files when opened and numerically replays the parent
on its first valid request. Each subsequent write verifies file hashes and runtime
again, including cache hits. Source/runtime changes close the session and discard
retained data; open a new session only after restoring/rebuilding a valid parent.

`result_cache_bytes` defaults to 64 MiB, accepts integers from zero through 256 MiB,
and is paired with a fixed 32-entry limit. The cache charges complete backing
numeric allocations, not merely a small view's apparent size. Oversized requests
still generate normally but are not retained. `cache_info()` reports the byte
budget, retained bytes, entry count, hits, misses, evictions and bypasses.

`clear_cache()` releases results and scalar cell support while keeping the prepared
parent. `close()` and context-manager exit release all session references.
Pass `cancellation=CancellationToken()` to an individual write to allow a
controlling thread to request a stop. Cancelled numeric work is never cached;
valid completed results can survive an export-time cancellation for a retry to
a new destination. Use a fresh token for that retry. See the
[cancellation lifecycle](terrain-generation-control.md).

Retain and use each session serially. Its public API returns artifact paths, keeping
cache arrays private. Equal aligned requests can share numeric data even when their
original bounds differ; each manifest retains the bounds supplied for that write.

One loaded/prepared parent and one detail context remain resident while open.
The result byte limit excludes parent/geometry storage, scalar cell records,
active generation/rendering scratch and Python metadata; it is not a process-wide
memory limit. A separate [shared admission budget](terrain-regional-memory.md)
now reserves estimates for those components before loading and generation/export.
Default sessions share 1024 MiB; the saved-parent CLI accepts `--memory-mib`.
Inspect `memory_info()` / `estimate_write()` for estimates and `cache_info()` for
actual retained numeric results. `clear_cache()` keeps reserved capacity for reuse.
Separate CLI invocations use temporary sessions with result retention disabled.
Read [ADR-0063](adr/0063-reuse-verified-parent-region-sessions.md)
and the [measurements](research/2026-09-23-parent-region-sessions.md).
