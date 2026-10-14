# Generation progress and cancellation

The workbench shows the current generation stage and elapsed time. During a
build, **Generate terrain** becomes **Cancel generation**. Click it or press
**Esc** to request a stop. The button then shows **Cancelling…** and stays
disabled until the worker acknowledges the request. Input controls remain locked
until then; the last successful map, authored inputs and undo history stay intact.

Cancellation is a normal outcome and shows no failure dialog. It also wins when a
finished result is queued but has not yet been accepted by the UI. Events from a
previous job cannot replace the map or complete a newer request. A failed build
still reports its error. Start a new generation normally after either outcome.

## Cooperative stopping

Stops are checked before generation, around progress callbacks, between field,
replay and local-detail batches, while sampling channel/water profiles, and before
artifact publication. Saved-parent exports also check between ground/difference
render tiles and comparison panels, releasing derived pixel buffers on exit.
Workbench generation also passes its token through ground-rendering tiles and
checks around whole-pool water-area preparation. The image adapter's explicit
water-render/composition API checks between colour tiles. Native component
classification itself remains one cooperative operation.
A request arriving during an individual NumPy, Shapely, rendering,
hashing or file-writing operation waits for the next checkpoint. There is no
promised maximum stop latency, forced thread termination or rollback of file I/O.
Import/open/save operations do not yet have a Cancel control.

No terrain formula, sample count, seed or output schema changes. Progress messages,
timers and cancellation state never contribute to numeric or artifact identity.
Saved parents still require the exact current package source/runtime identity;
rebuild a parent after updating the generator package.

## Python API

`generate_terrain`, `build_terrain_project`, `sample_terrain_region`,
`sample_parent_region` and `ParentRegionSession.write` accept an optional
`cancellation` keyword. Use a new token for each request:

```python
from pathlib import Path
from map_maker.terrain.application.parent_region import ParentRegionSession
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled

stop = CancellationToken()
# The controlling UI/thread may call stop.cancel() while write is running.
with ParentRegionSession(Path("artifacts/detail-parent")) as session:
    try:
        manifest = session.write(
            Path("artifacts/new-window"),
            (1375.0, 800.0, 1875.0, 1300.0),
            16,
            cancellation=stop,
        )
    except GenerationCancelled:
        print("Stopped before publishing a completed regional artifact.")
```

Tokens are one-way and thread-safe. They control only the current operation;
prepared fields, cached samples and sessions do not retain them. Reusing a
cancelled token rejects the next request immediately. Session methods themselves
remain serial; only requesting cancellation is intended from another thread.

Cancellation before numeric completion caches no partial result. Valid scalar
cell support may remain reusable. If cancellation happens after numeric work has
completed, such as during export or a cache-hit callback, the valid cached result
can be retried with a new token and a new output directory. Existing destinations
are never reused. Parent/runtime checks still apply to every retry.

An interrupted export can leave partial files, but no completed manifest. The
last cancellation check is before manifest publication; once publication begins,
that completed operation wins a later stop request. Completed parents and earlier
artifacts are immutable. Saved-parent jobs release their temporary
[memory reservations](terrain-regional-memory.md) on cancellation while keeping
valid retained work charged. Zoom scheduling and finer hydrology remain separate. See
[ADR-0064](adr/0064-cancel-generation-at-safe-checkpoints.md).
