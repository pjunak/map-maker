# Forecast water-sampling demand

For a saved project, run this before committing time to a detailed build:

```powershell
.\.venv\Scripts\map-maker.exe terrain water-budget examples/terrain/flat-outlet.terrain.json
```

The command reads the current project and its verified SVG, prepares the same
terrain field as generation, and evaluates finished Float32 ground only on the
canonical routing grid. It plans station demand without creating a delivered
DEM, evaluating fine water profiles, exporting files, or changing the project.
It still needs canonical terrain preparation and geometric planning; it is not
an instant settings-only estimate. Saving workbench edits first is necessary.

## Read the report

Each basin reports its canonical footprint and wet-node counts, followed by:

- **Shoreline:** the lake's normalized boundary profile, including closed lakes.
- **Potential wet network:** vector-contained links between canonical wet nodes
  of a lake with an authored outlet.
- **Potential dry network:** eligible dry descents/flats and dry-to-water links
  for the same outlet lake. Dry basins have no internal outlet networks.

Internal demand is conditional. A full review can skip those networks because
of an outlet-route, shoreline, footprint or water-connectivity failure. Even a
wet-network budget failure does not prevent the forecast from reporting the
separate potential dry demand. No candidate total proves that a network will
be evaluated, will connect, or will collect area.

An **exact** count means the complete profile/network plan fits the existing
budgets. **At least** is a required lower bound after bounded planning stops;
unvisited links still contribute their coarse baseline. The report identifies
whether the network or an individual profile exceeded its limit and how many
profiles were visited. Even if an excessive count happens to be complete, it
is conservatively presented as a lower bound.

Counts include repeated stations, including common link endpoints. They match
runtime budget accounting, not the smaller number of unique field evaluations
after exact per-call reuse. The current limits are:

| Scope | Requested stations |
|---|---:|
| Each profile | 65,536 |
| Each eligible wet network | 65,536 |
| Each eligible dry network | 262,144 |

Runtime evaluation remains batched at 4,096 positions. The forecast does not
allocate profile station arrays, lower detail, raise limits, or retain an
accepted prefix of an excessive network. The sampler remains
`feature-guided-float32-water-checks@4`.

## Example and limits

The public flat-outlet fixture at five detail levels requests 2,195 shoreline,
6,475 wet-network and 199,188 potential dry-network stations. Changing only its
detail level to six makes dry planning stop at a lower bound of 262,150,
exceeding the 262,144 network cap. This is the same failure reported by full
review. Changing delivered pixel resolution does not change these plans; the
canonical grid and physical sampling guides own this demand.

External outlet routes, attachment/contact profiles, terrain clearance,
contributing-area transfer, unique evaluation cost and export/serialization
cost are not forecast. There is no whole-project station total or promised
runtime. Ineligible networks can make this command do planning that full review
would skip. A small footprint with no canonical node is explicitly unresolved.
See the [forecast measurements](research/2026-09-13-water-budget-forecast.md)
for the initial cost, the [guide-bounds comparison](research/2026-09-13-water-guide-bounds.md)
for later planning improvements, and the [water guide](terrain-water.md) for
actual review semantics.

The command prints project, coastline and installed-generator source SHA-256
identities and rejects inputs/runtime that change during forecasting. A completed
report exits with status 0 even when it forecasts budget exhaustion; malformed,
missing or changed inputs exit with status 1 on stderr. Output is human-readable
text, not a versioned JSON/build artifact. The headless build and workbench do
not run this extra pass automatically. No project/build schema changed.
