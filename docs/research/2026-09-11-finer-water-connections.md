# Finer water connections: implementation and next steps

Date: 2026-09-11. Accepted decision:
[ADR-0039](../adr/0039-sample-shorelines-and-outlet-connections.md).
Usage and numeric evidence: [authored water](../terrain-water.md).

## Result

Finer checks now detect some shoreline openings and outlet-connection barriers
that fall between canonical nodes. The ground field is evaluated at additional
metric points, with Float32 heights and recorded spacing. The selected short
water/outlet/attachment path and every polygon boundary corner receive checks;
canonical ground, MFD capture, regional budgets and authored inputs remain intact.

An above-water connection sample blocks transfer. A submerged crest can remain
passable. Low boundary samples outside the existing outlet allowance also block
transfer; unresolved sampling budgets never yield a connected lake. Complete
profiles and failure locations are exported in build v12. The workbench and
review image mark low shoreline points in orange and connection barriers with
red diamonds. Basin details reports measured counts, spacing and ground maxima.

## Research decision

The USACE [HEC-RAS subgrid bathymetry reference](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/6.0/theoretical-basis-for-one-dimensional-and-two-dimensional-hydrodynamic-calculations/2d-unsteady-flow-hydrodynamics/subgrid-bathymetry)
describes extracting cell and face properties from finer terrain while keeping
a coarser computational mesh. Our inference is narrower: local ground evidence
can improve connection review without globally increasing the routing grid.
We do not implement its hydraulic property tables or fluid solver, and our
point-sampling spacing is an explicit project choice, not a method prescribed
by that reference.

[Fill-Spill-Merge (Barnes, Callaghan and Wickert, 2021)](https://esurf.copernicus.org/articles/9/105/2021/esurf-9-105-2021.html)
uses a depression hierarchy, water volumes and overflow/merge relationships.
It remains a reference for future storage and lake-chain work. Our contributing
area transfer and sampled connection maximum do not provide those quantities or
establish a stable level. No external implementation or new package was added.

Profiles are bounded to 65,536 points, evaluated in batches of 4,096. A complete
profile records all coordinates and heights; over-budget profiles retain only
the request count and unresolved status. This costs more than endpoint-only
checks, but avoids silently coarsening complex boundaries. Python remains the
implementation language, with a typed sampler separating terrain evaluation
from profile geometry and review decisions.

## Validation and measurements

The public [shoreline-gap fixture](../../examples/terrain/shoreline-gap.terrain.json)
adds an absolute zero-height point with a 2 km influence radius at normalized
position (0.425, 0.28), on the existing lake boundary. The coarse candidate route
remains clear and the coarse uncontrolled-opening count remains zero. Finer
sampling finds two boundary points at 545.199402 m and 544.818848 m, below the
imposed 750 m level and outside the declared opening. The outlet is blocked;
its 2,069,615.059935 km2 of captured contributing area stays retained. The full
land-area balance error is -9.3e-10 km2. Area uses the existing equal-node proxy,
not a water volume or surveyed area.

Each public lake boundary has 1,082 recorded points including the repeated
closing endpoint, with spacing at most 3.90625 km on its canonical 257 by 152
grid. The exact zero-height point lies between finer samples too; detecting the
opening does not imply finding its exact minimum. This illustrates the remaining
sampling limit rather than hiding it.

The flat-outlet example still connects, delivering 1,423,407.974020 km2 and
retaining 40,959.020577 km2. Its short connection's sampled maximum is
222.206406 m, slightly higher than the exact outlet ground of 221.705353 m, and
well below its imposed 750 m water level. Neither value proves level stability.

- **350 tests passed** on the final source, plus Ruff and strict Pyright. All
  178 local file links in the 11 changed Markdown files also passed.
  Tests cover inner and outer between-node barriers, extra openings, submerged
  crests, tolerance, over-budget retention, nonfinite samples, exact vertices,
  bounded spacing/batches, ring direction, resolution and constraint order,
  per-node area conservation, deterministic exports and visible marker locations.
- Synthetic obstruction tests preserve every canonical ground value while
  changing finer evidence. The route's maximum height-above-water summary also
  includes a discovered finer barrier; coarse uphill counts retain their meaning.
- Hidden Tk checks passed for connected, closed and shoreline-blocked details
  and all 12 combinations of the existing review toggles. A separate synthetic
  barrier check verified the red marker and above-water explanation.
- Both final public headless builds completed. The shoreline-gap review image
  was visually inspected: the retained lake footprint is amber and its narrow
  opening has an orange marker. Final image bytes match the inspected version.

CPython 3.14.7 on Windows, 768 px, seed 42, two fresh processes per scene:

| Scene | Generation seconds | Highest generation process peak (MiB) |
|---|---:|---:|
| Authored | 2.483 / 2.365 | 124.0 |
| Archipelago | 2.534 / 2.504 | 104.7 |
| Regional | 1.597 / 1.676 | 130.9 |
| Water | 1.538 / 1.591 | 136.6 |
| Outlet | 2.118 / 2.008 | 136.3 |
| Flat outlet | 2.068 / 2.082 | 135.8 |
| Shoreline gap | 1.891 / 1.875 | 135.9 |

All 26 numeric hashes and complete water-review records repeat exactly per
scene. All 26 preceding numeric hashes match for each of the six established
scenes; the new scene has no previous-version baseline. New diagnostics and
review images intentionally differ. Numeric archives keep their existing layout.

A separate instrumented run isolates the added profile checks:

| Scene | Boundary checks (ms) | Connection profile (ms) |
|---|---:|---:|
| Water | 5.25 | 0.00 |
| Outlet | 5.33 | 1.30 |
| Flat outlet | 6.44 | 1.56 |
| Shoreline gap | 5.56 | 1.53 |

Those checks took roughly 5-8 ms per scene, including terrain sampling and
profile construction. These four probes share a process; they exclude JSON
serialization and review rendering and do not establish a many-basin cost bound.
The complete diagnostic files are 500,893 bytes for flat-outlet and 343,567 bytes
for shoreline-gap, including all other existing diagnostics.

Fresh-process generation timings varied between runs; there was no interleaved
cross-revision experiment, so their differences must not be attributed entirely
to finer sampling. No speedup is claimed. Benchmarks and the instrumented probes
ran without competing tests or terrain generation. Complex many-lake boundaries,
4096 px generation, export cost and renderer cost were not benchmarked. The
per-profile sample budget is tested; it is not a bound on total project cost.

Evidence: `artifacts/water-sampling-performance-final-20260911.json`,
`artifacts/water-sampling-validation-20260911.json`,
`artifacts/water-sampling-ui-smoke-20260911.json`,
`artifacts/water-sampling-outlet-final-20260911/` and
`artifacts/water-sampling-shoreline-final-20260911/`.

## Next gains

1. Target narrow authored influences and crossings, and measure convergence.
   Quarter-grid sampling can still miss a feature between every probe; the
   exact maximum cannot be certified from these samples alone.
2. Extend finer evidence to internal wet links and complete downstream routes.
   Current wet connectivity and the external path beyond the first attachment
   remain canonical; the circular opening allowance is not a channel-width model.
3. Define controlling-sill geometry and inflow/storage/boundary assumptions,
   then connect explicit lake chains with compatible levels and acyclic routes.
4. Compare full constrained breach/reroute proposals while retaining regional
   budgets and authored anchors; then improve ridge/valley profiles and passes.

The current change improves review and transfer correctness, not lake equilibrium
or overall river shape. Campaign geography was not edited. These boundaries and
future improvements are logged in [TODO](../../TODO.md) and the
[current strategy](../strategy/README.md).
