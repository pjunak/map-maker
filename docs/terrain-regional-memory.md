# Regional memory admission

Saved-parent sessions and the `sample-parent` / `enrich-region` commands now
reserve estimated memory before loading large inputs and before generating or
exporting a region. Rejected requests leave no output directory and do not
change numeric caches. There is no automatic reduction of detail or resolution.
This is an allocation policy, **not an operating-system memory ceiling**.

## Use the budget

All default `ParentRegionSession` instances in one process share a **1024 MiB**
budget. The two saved-parent CLI commands accept a positive integer override:

```powershell
map-maker terrain sample-parent artifacts/parent --output artifacts/region --bounds-km 1100 1100 1700 1700 --refine 8 --memory-mib 1024
```

Applications can share an explicit budget across related sessions:

```python
from pathlib import Path
from map_maker.terrain.application.parent_region import ParentRegionSession
from map_maker.terrain.application.region_memory import RegionalMemoryBudget

budget = RegionalMemoryBudget(1024 * 1024 * 1024)
with ParentRegionSession(Path("artifacts/parent"), memory_budget=budget) as session:
    bounds = (1100.0, 1100.0, 1700.0, 1700.0)
    print(session.memory_info())
    print(session.estimate_write(bounds, 8))
    manifest = session.write(Path("artifacts/region"), bounds, 8)
print(budget.info())  # No remaining reservations after all owners close.
```

`estimate_write` validates the same region and detail limits without preparing
terrain or changing caches/files. Its `total_bytes` is the additional active-job
estimate. `memory_info().retained` reports the session's reserved capacity and
component estimates; `active_job_bytes` reports its current job reservation.
`budget.info()` reports shared capacity, current/peak reservations and owner
count. `cache_info()` continues to report actual retained numeric cache bytes.
Do not confuse those three measurements with resident process memory.

When admission fails, `RegionalMemoryAdmissionError` gives the estimate,
combined reservations and budget. Retry after closing another session, choosing
smaller bounds/refinement, opening with a smaller result-cache capacity, or
explicitly selecting an appropriate larger shared budget. The pool never queues
work or cancels another owner's job. Distinct pools and separate processes do
not share accounting. Use sessions serially; conflicting writes/clear/close are
rejected. Reservations across different sessions are thread-safe.

## What is counted

Opening first reserves 8 MiB of bootstrap allowance plus configured result-cache
capacity. The loader requests admission before parsing the bounded input
snapshot and again before numeric decoding. It charges expected decoded shapes,
archive buffers and the largest decoded entry. The allocation is based on
uncompressed dimensions, not just compressed file sizes. Reads use observed
file size plus one byte to detect growth; declared product sizes are checked
before reading. The old 512 MiB product safety limit remains a file-size ceiling,
not a requested read-buffer size.

The session then reserves the following envelope until close, including work it
may prepare lazily:

| Component | Current accounting |
|---|---|
| Loaded arrays | Exact expected NPY/NPZ storage: 13 bytes per delivered node, 50 per routing node, Float64 axes |
| Inputs and serialization | 32 times snapshot bytes plus 8 MiB for text, Python objects and snapshot export |
| Prepared numeric fields | 512 bytes per canonical routing node plus 1 MiB |
| Complete-source geometry | 2048 bytes per source/authored coordinate, 64 KiB per authored feature, 4096 bytes per coastline ring |
| Optional detail context | 4096 bytes per potential protected feature/channel, 2048 per authored coordinate, 512 per each of the 4096 scalar cache slots |
| Numeric result cache | Full configured byte capacity, including unused capacity |
| Other session metadata | 1 MiB |

Geometry includes all source components, holes and authored features. Detail
protection count deliberately includes all authored features and channel nodes;
actual prepared protections may be fewer. These coefficients are explicit
engineering allowances, not exact measurements of GEOS or Python objects.
`clear_cache()` frees actual retained results/support but keeps their reserved
capacity available for reuse. Close the session to release that capacity.

A job additionally reserves its complete new numeric result (including halo,
reference/delta arrays and cell records where applicable), 16 MiB of I/O
allowance, and the largest of these serial stage allowances:

- Sampling: 2048 bytes per active sample, bounded by the 65,536-sample chunk or
  the 64-cell fixed-probe batch. Detail counts its one-parent-cell support halo
  against the 4096-cell limit and charges the temporary Float32 probe bank
  (289 values per cell), cell metadata and possible STRtree intersection pairs.
  Protection queries use at most 64 cells and
  release their pair array before the next batch.
- Cold preparation/replay: 4096 bytes per node of a 257 by 257 canonical grid,
  plus the geometry allowance. This reservation disappears for prepared sessions.
- Rendering: 8 bytes per buffered sample in reference mode or 32 in detail mode
  for native images/crops/resampling, plus 256 bytes per sample of one tile
  (at most 258 by 258 including the gradient halo). Detail also charges four
  bytes per pixel of its bounded three-panel comparison canvas, at most
  3072 by 1080. These are allocation allowances, not decoded image file sizes.

Cached writes retain an active export reservation. They use the same conservative
new-result allowance as uncached writes. These operational estimates and counters
never enter the terrain seed, schema or artifact identity.

Ground shading now processes 256 by 256 cores with one-node gradient halos.
It retains the original grid spacing and full native scientific output; there
is no resolution reduction of numeric terrain. Only `comparison.png` fits each
panel within 1024 by 1024, without upscaling. Difference colours and labels use
the native maximum absolute height change. Owned render buffers explicitly close
on success and cancellation; in-memory Pillow context exit alone does not free
them. See [ADR-0066](adr/0066-bound-terrain-rendering-scratch.md).

## Ownership and remaining limits

Temporary job reservations release on success, rejection, cancellation and
failure. Valid retained parent/cache work remains charged for retry. Source or
runtime drift closes the session and releases all reservations when the active
call unwinds. Explicit close/context exit is preferred; abandoned reservation
objects also release when garbage-collected. No immediate process-memory return
is promised: Python/native allocators can keep freed capacity.

This policy covers the saved-parent application API. Direct pipeline calls,
whole-map builds, `sample-region`, editor images and unrelated work are outside
its pool. Native geometry complexity, decoder/Python expansion and concurrent
application activity still require broader calibration. It neither discovers
available RAM nor enforces an OS limit. A scheduler, hard process isolation,
recursive enrichment and finer hydrology are not implemented. See the
[initial measurements](research/2026-09-23-regional-memory-admission.md),
[near-limit/thin-region rendering measurements](research/2026-09-23-bounded-terrain-rendering.md),
[ADR-0065](adr/0065-admit-regional-memory-estimates.md) and [TODO](../TODO.md).
