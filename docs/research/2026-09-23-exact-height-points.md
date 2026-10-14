# Exact overlapping height points - 2026-09-23

The shared terrain field now interpolates absolute height points even where their
influences overlap. The public lake fixture's 250 m point now evaluates to 250 m;
it previously evaluated to 331.149811 m. This fixes the parent-reference defect
found in the [local-detail experiment](2026-09-23-parent-cell-preservation.md).
The rejected parent-cell projection remains outside the runtime.

## Root cause and implementation

The previous final point stage blended nearby targets with ordinary Gaussian and
coast-conditioned weights. A point's own unit weight did not exclude neighbouring
weights, so its value was an average. Lake water did not cause this discrepancy:
the basin layer protects ground from automatic incision and classifies water over
it, while the error was already in absolute-point interpolation.

[generate.py](../../src/map_maker/terrain/pipeline/generate.py) now uses target
shares proportional to `w/(1-w)`, with a stable common rescaling instead of an
unbounded divide. A point dominates as its centre is approached. Canonical
coordinate/height/radius ordering keeps floating-point accumulation independent
of authored point order. Every query coordinate computes its own shares, so
batching and requested grid density do not define the terrain.

Exact-coordinate handling also retains zero-height targets and distinguishes
extremely close points whose weights can both round to one. Neighbouring values
are separately tested for convergence to each target; this is not an isolated
pixel overwrite. Existing terrain, structure and relative-guidance processing
still feeds the final absolute-point stage. The returned field retains the
existing zero/ceiling bounds and Float32 output policy.

Conflicting absolute heights at the same metric coordinate are rejected before
routing. Equal targets remain valid even with different radii. A nonzero absolute
point exactly on a sea-level land boundary is rejected; a zero target there is
consistent. Inputs and completed outputs remain unchanged; a new generation uses
the corrected field. Generator identity advances from @16 to @17, without adding
an old-behavior mode or changing the project/build schemas. The detailed decision
is [ADR-0060](../adr/0060-interpolate-overlapping-height-points.md).

## Exact-coordinate evidence

The before/after samples below use the public `water` fixture at seed 42 with two
detail bands. Coordinates are normalized authored positions. Targets and values
are metres. The numeric tests repeat all four anchors at seeds 42 and 7 with both
two and six bands:

| Point | Authored | Before | After |
|---|---:|---:|---:|
| (0.39, 0.43) | 400 | 385.559723 | 400 |
| (0.45, 0.49) | 250 | 331.149811 | 250 |
| (0.40, 0.55) | 500 | 424.038300 | 500 |
| (0.70, 0.51) | 400 | 399.663391 | 400 |

The public `authored` fixture already hit its 2200 m and 1000 m points with this
sampling setup. Both still do. For non-integral authored values, exactness means
the target rounded to Float32. A raster with no node at an authored coordinate
can still interpolate a different value when inspected between pixels; this fix
does not snap or modify neighbouring raster pixels after generation.

A separate overlapping synthetic case previously returned approximately
1788.207, 2097.647 and 2531.634 m for authored targets 0, 1700.123456 and 4500 m.
The new regression was observed failing before the change and passes afterward.
It tests those targets in both the prepared field and aligned DEM nodes, including
relative brush/valley guidance underneath them. Eight-direction probes approaching
each point from 10 m, 0.1 m and 1 mm distances verify the nearby limit. Further
checks cover reversed point order, shuffled 17-batch queries and common coordinates
on 65/129/257 windows.

## Whole-map numerical and cost checks

The existing public runner measures complete generation, quality and rendering
in fresh Python processes. Before and after use identical arguments:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.terrain --case example authored water --resolution 129 --seed 42 7 --repeats 2 --output artifacts/point-heights-before-or-after.json
```

The output must be a fresh filename; the measured files are
`artifacts/point-heights-2026-09-23-before.json` and
`artifacts/point-heights-2026-09-23-after.json`. The before source is `a5e818a`
(generator @16); the after source implements ADR-0060 (@17). Each report binds
its installed source, benchmark source, input hashes and runtime. Both use
Windows 11 AMD64, CPython 3.14.7 and NumPy 2.5.2. Performance runs are separate
from the correctness suite.

All six before/after case/seed pairs have identical input hashes. Numeric hashes
repeat exactly within each revision. Both `example` and `authored` also retain
all recorded numeric hashes across the change, at both seeds. The water case
changes ground, routing and sampled water as expected from corrected overlapping
heights. Its canonical lake wet-node count stays 1544 at seed 42 and changes
1610 to 1607 at seed 7. Basin issue lists remain empty; contributing-area balance
residuals across all cases remain below 1.9e-8 km2 in magnitude.

| Fixture/seed | Median generation before (s) | After (s) | Peak resident before/after (MiB) |
|---|---:|---:|---:|
| example / 42 | 0.651 | 0.600 | 90.4 / 90.4 |
| example / 7 | 0.650 | 0.598 | 90.3 / 90.6 |
| authored / 42 | 0.957 | 0.905 | 112.5 / 113.6 |
| authored / 7 | 0.974 | 0.926 | 112.5 / 113.5 |
| water / 42 | 0.665 | 0.612 | 94.4 / 94.4 |
| water / 7 | 0.666 | 0.584 | 94.6 / 95.1 |

No added generation-cost signal appears in these small matched runs. The after
medians are lower, but this short sequential comparison does not establish a
speedup. The highest reported peak grows by about 1.1 MiB in the authored case.

Canonical uphill diagnostic counts change from 23 to 24 (water/42) and from 60
to 61 (water/7); both controls retain their counts. A follow-up loaded the committed
baseline generator into an isolated module and required *every* numeric array
hash to match the original before/after benchmark before comparing the flags:

- Seed 42 adds source 27426 -> 27169 on the same selected edge. Its rise changes
  from 0.0009765625 to 0.0010986328 m, crossing the existing 0.001 m diagnostic
  threshold by one Float32 step. The threshold was not changed.
- Seed 7 adds two flagged edges, 20194 -> 20193 and 20195 -> 20194, that previously
  had the same receivers but were not selected as channels. Their rises actually
  decrease from 0.444824/4.864868 to 0.218018/0.115723 m. One previous flag is removed,
  giving the net count increase of one. Count changes alone are not a paired
  ground-profile comparison.

The water-case maximum cut deficits change 21.601196 to 21.607788 m (seed 42) and
78.120361 to 78.136230 m (seed 7). These unresolved diagnostic routes remain part
of the existing drainage work; exact authored heights do not certify rivers.
The follow-up evidence is local
`artifacts/point-heights-2026-09-23-channel-changes.json`. It is a comparison probe,
not a retained legacy implementation or an alternate runtime mode.


These are small public fixtures and two repetitions per case/seed. They are
checks for an obvious cost regression, not a scaling result or an overall speedup
claim. Timed generation excludes file export and publication; rendering is
measured separately. Peak memory includes native libraries and process imports.

## Validation and next development

- 1008 tests pass, including 15 new height-point regressions. Existing anchored
  structure, coastline, water and regional/full-source contracts pass.
- Repository-wide Ruff and Pyright pass without code or type findings.
- Twelve before and twelve after public runs complete, with stable repeated
  numeric results and matching inputs across revisions.
- The focused channel comparison reproduces all recorded numeric hashes for both
  water seeds, before classifying the changed flags.
- All 684 local file links across 133 Markdown documents resolve. The final
  source/runtime fingerprint still matches the completed after benchmark.
- A separate SVG-hole boundary check confirms that a nonzero absolute target on
  an inner sea-level boundary is rejected too.

The source of the incorrect parent heights is resolved. The next local-detail
step still needs a verified immutable prepared parent reference, explicit parent
moments, and added residuals whose conditioning does not depend on requested
sampling density. Authored heights, inherited channels and water need their own
preservation checks before any child can be presented as accepted enrichment.
The [TODO](../../TODO.md) retains those gates, finer hydrology and the resolution
requirements for small cartographic rivers.

This change does not establish a complete hard/soft constraint solver, continuous
terrain derivative bounds or downhill paths between arbitrary authored heights.
Very close points can demand steep transitions; the existing finite water-profile
checks are not certified continuous error bounds. No private map or interactive
editor acceptance was performed in this numerical slice.
