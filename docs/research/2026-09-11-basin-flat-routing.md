# Basin flat routing: implementation and next steps

Date: 2026-09-11. Accepted decision:
[ADR-0038](../adr/0038-route-basin-flats-with-integer-gradients.md).
Current usage and exports: [authored water](../terrain-water.md).

## Result

Exact flat ground inside an eligible lake footprint can now deliver captured
area through real exits. Separate integer ranks resolve equal-head steps; the
authored DEM and original MFD capture graph remain intact. Closed flats and
paths ending in lower closed pits keep their contributions. Every internal
segment must remain inside the authored polygon, even between sampled nodes.

The same contained graph also fixes strict downhill selection at concave
boundaries: choose the steepest eligible neighbour rather than stopping when
the best raster neighbour crosses a gap. Missing graph links are not outlets.
Wet receivers use water surface height instead of submerged bed depth.

Build v11 replaces v10 and adds canonical `internal_receivers` and `flat_rank`
arrays. Basin details shows all resolved flat donors and the subset reaching
connected water. These counts exclude strictly downhill upstream nodes that
may also benefit from a later flat step; they are not contributing-area totals.
The existing green/amber overlay reflects the resulting collection/retention.

## Research decision

[Barnes, Lehman and Mulla, Computers & Geosciences 62 (2014), 128-135](https://arxiv.org/html/1511.04433v1)
provides the separate integer-gradient approach. Its flat-processing stages
are linear in the number of cells and avoid representational changes to the
DEM. Our bounded graph, explicit water terminals and retained-pit policy adapt
that method to authored footprints. No supplemental implementation was copied.
The full collection pipeline also includes vector geometry and a sort, so the
paper's complexity and speed claims do not describe end-to-end generation.

The choice keeps iteration in Python and isolates numeric routing behind an
array interface suitable for later profiling or a Rust port. There is no new
runtime dependency. Lake stability still needs separate physical assumptions;
flat routing does not infer runoff volumes, storage or a controlling sill.

## Validation and measurements

The public [flat-outlet example](../../examples/terrain/flat-outlet.terrain.json)
has a canonical 257 by 152 grid. It uses a zero-relief plateau and narrower
height influences to produce exact Float32 flats alongside retained pockets.

| Footprint | Collected water samples | Collected dry samples | Retained samples |
|---|---:|---:|---:|
| A1: closed dry basin | 0 | 0 | 1,672 |
| A2: connected lake | 111 | 4,162 | 167 |

Of 1,507 resolved dry flat donors, 1,362 reach connected water and 145 end in
retained ground. Including upstream nodes with a later flat step, 1,365
collected samples depend on flat routing. Their captured contribution is
663,117.717311 km2. Tracing the exported graph while stopping at equal-head
steps leaves 760,290.256709 km2 collected; enabling those steps delivers
1,423,407.974020 km2. This is a graph comparison on the same generated terrain,
not a timing comparison or a previous-version run of this new example.

The connected lake retains 40,959.020577 km2 and the closed dry basin retains
2,444,994.495718 km2. Full land-area balance agrees within the existing tolerance.
These use the equal-node contributing-area convention, not runoff volume or
surveyed area. Lake level remains imposed at 750 m and exact outlet ground at
221.705353 m; stability is unmodeled.

- **333 tests passed**, including independent exported-path tracing, conserved
  area, correct water/pit terminals, unchanged ground, resolution and constraint
  order independence, closure/revalidation and repeated builds. The 11 flat
  tests also passed after strengthening the concave-boundary fallback assertion.
- Ruff, strict Pyright and all 170 local file links in the 11 changed Markdown
  files passed on the completed implementation.
- Hidden Tk checks passed for connected, closed and blocked details and all 12
  combinations of the existing review toggles. No new toolbar controls were added.
- The public headless build completed; its four-panel drainage image was visually
  inspected. The connected footprint is largely green, with retained ground
  visible in amber. Automated builds check the current schema and numeric exports.
- An isolated single-exit flat spanning 65, 129 and 257 square grids routed all
  nonterminal nodes acyclically without changing any head. Two calls at each
  size took 0.020/0.020 s, 0.078/0.078 s and 0.310/0.311 s. The largest case has
  66,049 nodes and 66,043 resolved flat donors. These kernel timings exclude
  graph construction, vector geometry, collection sorting and export.

CPython 3.14.7 on Windows, 768 px, seed 42, two fresh processes per scene:

| Scene | Generation seconds | Highest generation process peak (MiB) |
|---|---:|---:|
| Authored | 2.267 / 2.223 | 124.3 |
| Archipelago | 2.494 / 2.544 | 105.6 |
| Regional | 1.568 / 1.564 | 130.8 |
| Water | 1.519 / 1.493 | 136.4 |
| Outlet | 1.575 / 1.583 | 135.7 |
| Flat outlet | 1.639 / 1.634 | 136.2 |

All 26 recorded numeric hashes repeat exactly per scene. All 24 existing
hashes for the five previous scenes match the preceding implementation,
including DEM, routing, water and contributing-area products. The two new
hashes cover internal receivers and flat ranks. Retaining those arrays costs
12 bytes per canonical node, 0.447 MiB for the public example, independently
of delivered resolution; temporary arrays and renderer buffers are additional.

Evidence: `artifacts/basin-flats-performance-20260911.json`,
`artifacts/basin-flats-validation-20260911.json`,
`artifacts/basin-flats-ui-smoke-20260911.json`, and
`artifacts/basin-flats-final-20260911/`. Benchmarks ran without competing tests
or terrain generation. The small apparent timing improvement is not a proven
speedup: there was no interleaved cross-revision experiment. Many-outlet stress,
file export, review rendering and 4096 px generation were not benchmarked.
Campaign-scale geographic acceptance remains untested by this synthetic fixture.

## Next gains

1. Refine water/ground contact and shoreline openings between canonical samples;
   derive controlling-sill evidence with explicit inflow/storage assumptions.
2. Connect explicitly authored lake chains with compatible levels and acyclic
   dependencies. Current outlet routes still reject every intervening basin.
3. Compare constrained breach/reroute proposals over their complete paths,
   retaining regional cut budgets and authored anchors.
4. Add per-vertex ridge/valley profiles and passes, then regional process controls
   and selected-region refinement under explicit parent/halo contracts.

The public fixture tests routing, not natural lake equilibrium or river shape.
No private campaign map was changed. The wider backlog and active priorities
remain in [TODO](../../TODO.md) and the [strategy](../strategy/README.md).
