# Bounded terrain rendering - 2026-09-23

## Finding and implementation

Stress testing the saved-parent memory policy exposed a display allocation that
was disproportionate to the numeric request. A 3 by 262145 core produced a
900 by 262201 comparison canvas because each panel retained a 300-pixel minimum
width at native height. Experimental-detail export peaked at **1078.2 MiB**.

Ground rendering now shades 256 by 256 cores with one-node gradient halos and
the original grid spacing. Its palette and hillshade scratch no longer scales
with the whole raster. The final native image remains allocated. Both scientific
and cartographic callers use this path. Saved-parent comparison rendering now
has its own adapter, tiled difference colouring and panels bounded to 1024 on
each axis without upscaling. Only the review product is resized; `samples.npz`
and native `scientific.png` remain full resolution. Native extrema determine the
difference scale even when a reduced preview averages a small feature away.

Cancellation tests also found that an in-memory Pillow image's context exit does
not free its pixel buffer. These render/export paths now explicitly close owned
tiles, crops, comparison images and native buffers, including exceptional exits.
Borrowed source images stay open. Saved-parent jobs check cancellation between
tiles and panels; a single PNG encode or resize still runs to its next checkpoint.

The admission estimate now charges native images, a bounded halo tile and the
bounded review canvas. It remains a policy estimate, not a process RSS ceiling.
See [ADR-0066](../adr/0066-bound-terrain-rendering-scratch.md) and the
[current accounting](../terrain-regional-memory.md).

## Reproduction and scope

Windows 11 AMD64, CPython 3.14.7, NumPy 2.5.2, Pillow 12.3.0 and Shapely 2.1.2.
The source identity before the change was
`1f5851a682325c40c151cf6ae5f7d2ca4bbd7b7869c74d50693911c2e1ed8b37`;
the updated identity is
`70f46a39fe16b6a8530614a89471bc1ca9087d2bc80cf4551a740fa09572a916`.

Use the public `example.terrain.json` with seed 42, two detail bands and
65 longest-side nodes (65 by 39). Save and build a fresh parent for each source
revision; saved parents require the exact current runtime. The benchmark uses
a 40 m experimental residual and a 64 MiB numeric result cache. No private map
is needed. Extend the existing fresh-process harness with exact core dimensions:

```powershell
python -m benchmarks.regional_memory --parent artifacts/parent --refine 128 --window-samples 1409 1409 --mode reference detail --output artifacts/render-square.json
python -m benchmarks.regional_memory --parent artifacts/parent --refine 65536 --window-samples 3 262145 --mode reference detail --output artifacts/render-tall.json
python -m benchmarks.regional_memory --parent artifacts/parent --refine 65536 --window-samples 262145 3 --mode reference detail --output artifacts/render-wide.json
```

Each parent/mode/shape gets a new process with one cold and one cached export.
A lifetime peak includes imports, parent decoding/replay, native allocations and
allocator retention; it is not an isolated render allocation. Parent building
happens outside these workers. Before runs explicitly admitted 2048 MiB so the
old tall-detail path could run; all after runs use the default 1024 MiB policy.
The larger baseline budget does not change generation or allocations. There
were no concurrent tests or other terrain benchmarks during measurement.

The square has 1,990,921 buffered nodes, including its halo; each thin case has
1,310,735. All remain under the two-million-node regional limit. Refinement
65536 stresses aspect ratio, not scientifically meaningful detail at that spacing.
These runs do not certify the experimental detail formula's visual realism.

## Measurements

MiB means 2^20 bytes. These are single fresh-worker observations per mode/shape,
not confidence intervals or cross-machine performance guarantees.

| Core / mode | Previous process peak MiB | Updated process peak MiB | Previous peak reservation MiB | Updated peak reservation MiB |
|---|---:|---:|---:|---:|
| 1409 by 1409 / reference | 313.5 | 142.1 | 634.6 | 407.0 |
| 1409 by 1409 / detail | 352.2 | 211.5 | 673.5 | 422.2 |
| 3 by 262145 / reference | 234.8 | 129.1 | 462.1 | 400.6 |
| 3 by 262145 / detail | 1078.2 | 157.0 | 1372.3 | 410.6 |
| 262145 by 3 / reference | 235.9 | 128.8 | 462.1 | 400.6 |
| 262145 by 3 / detail | 356.3 | 142.0 | 649.1 | 410.6 |

The tall-detail peak fell by about **85%**. Square-detail peak fell about 40%.
The paired thin cases show why sample count alone did not bound a captioned
comparison image. Their updated comparison sizes are 900 by 1080 (tall) and
3072 by 57 (wide), versus full-resolution scientific cores in both cases.
The square review is 3072 by 1080 with three 1024-square panels.

| Detail core | Previous cold / cached seconds | Updated cold / cached seconds |
|---|---:|---:|
| Square | 5.345 / 0.890 | 5.248 / 0.754 |
| Tall | 4.241 / 1.279 | 3.621 / 0.480 |
| Wide | 3.788 / 0.778 | 4.623 / 0.587 |

Tiling adds loop overhead on extreme shapes. The wide cold write was slower in
this observation; the implementation is a memory improvement, not a universal
speedup claim. Cold time includes parent preparation and numeric generation;
cached time still includes freshness checks and complete artifact publication.

A separate updated public parent was built at **4096 by 2427**, 9,940,992 delivered
nodes, using the same seed and two bands. The complete build took 24.86 seconds
in a single untuned observation. A fresh worker then exported the same 1409-square
core shape at refinement 128:

| Mode from 4096 parent | Process peak MiB | Peak reservation MiB | Cold / cached seconds |
|---|---:|---:|---:|
| Reference | 261.7 | 530.3 | 21.864 / 0.358 |
| Detail | 335.1 | 545.5 | 22.257 / 0.833 |

Loaded numeric storage was 125.2 MiB. These rows have no paired old-renderer
4096-parent baseline. They validate a larger saved-parent workload, not the full
4096 by 4096 node maximum or complex-source/editor peak memory. The different
parent grid also makes this a different physical region, not a same-terrain
resolution comparison.

## Correctness and visual checks

All 14 workers (six before, eight after) verified exact cold/cached artifact and
manifest hashes and zero reservations after session close. Loaded array estimates
matched unique owned allocations; retained prepared arrays stayed within their
allowance.

For all six paired 65-parent workloads, `samples.npz` and `inputs.json` were
byte-identical before and after, and native scientific RGBA pixels matched
exactly. Their PNG provenance naturally differs because source/parent identity
changed. The 65-parent scientific, cartographic and drainage PNG pixels also
matched their original controls. Comparison layout/metadata intentionally changed.

Regression tests cover both palettes, arbitrary tile boundaries, two-node axes,
NaN coast pixels, non-square physical spacing, input immutability, cancellation
buffer release and bounded admission. The actual saved-parent export test
verifies a 3 by 2049 native scientific image, its complete numeric grid, a
900 by 1080 comparison PNG, preview metadata and valid product hashes.

Visual inspection covered the square comparison and tall strip: captions and
reduction footer are present, source panels stay aligned and difference scaling
retains native extrema. Very thin maps necessarily become one-pixel strips;
scientific output and numeric samples remain the inspection source for details.
The residual's regular cell pattern is still visible. This work does not solve
its visual/spectral acceptance or inherited hydrology.

## Evidence and next gates

Reports and PNG/NPZ outputs stay in ignored `artifacts/`. Report digests:

| File (under artifacts/) | SHA-256 |
|---|---|
| `render-memory-20260923-before-square.json` | `30b25d3e19ff2af4321215bb5394a11b5902e17f46ff03dad4065220d408d7ec` |
| `render-memory-20260923-before-tall.json` | `535f36e96846448a306c3cb9a8d3695d472c4b9b4bd3ee3183b10e162c02e186` |
| `render-memory-20260923-before-wide.json` | `f73d08adaddb3fa5835da9c70471f205a04f95bc144de8e18ba71ff149ded757` |
| `render-memory-20260923-after-square.json` | `fee486af5062a359b5cb56fc0c5bcc662159329f82b98588d6bfadf5358ee342` |
| `render-memory-20260923-after-tall.json` | `669bba9bd69807eadc0f5c9912de78294474190d45fb9a2bfaba7240a8314728` |
| `render-memory-20260923-after-wide.json` | `6bc4a7760b7e42b94124a31034547405153f672bdce3050b20cf56c0366977bd` |
| `render-memory-20260923-after-large-parent.json` | `066e104b4e79c17caf3bd38dbb6d683ec545f73d326cab05dce1aecaafd097bd` |
| `render-memory-20260923-output-equivalence.json` | `a0ef2e336bac02879d747596614bc7af06a8fe51e6d2165447102f89ca0ae05b` |

Keep the broader memory gate open: dense/overlapping geometry, maximum node
counts, simultaneous jobs, long session churn, decoder expansion and all editor
images/whole-map ownership still need calibration. Full-raster water, composition
and diagnostic rendering have separate allocations. The next scheduler must
account for them; no automatic viewport scheduling or small-river generation is
introduced here. The [TODO](../../TODO.md) records these remaining items.
