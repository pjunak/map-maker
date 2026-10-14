# Geological landform guidance: implementation and limits

Date: 2026-09-27. Starting revision: `4b691d8`. This is a product integration batch,
using the existing Python regional generator. No new scientific paper comparison,
physical aging model or river construction method was tested.

## Delivered

The geology editor now has separate **Geological history** and **Landform guidance**
tabs. Defaults and provinces accept plain/hills/plateau/mountains plus base elevation,
relief, physical feature/transition sizes and projected orientation. Presets require
an explicit action. Unknown/background landforms remain distinct from a named setting.

World → Terrain accepts a saved recipe, displays its path and rereads it at creation.
Closing the geology editor exposes its saved recipe in this panel. The CLI adds
`--geology`. Canonical world identity rejects stale recipes while allowing reordered
equivalent records. Existing world/terrain guards and cancellation remain in force.

Compilation resolves priority before projection, selects only physical land in the
handoff, and merges equal controls across administrative/age boundaries. Nested
overrides become hole rings in editable terrain regions. All ring outlines, canvas
selection, whole-region/vertex moves, geometry checks and undo preserve those holes.
The prepared source retains the original recipe even after ordinary terrain edits.

Projection sampling is now shared in `adapters/world_geometry_projection.py`;
compilation is in `adapters/world_landforms.py`; strict landform parsing and its
world form have separate modules. Formats are terrain project v7, geology v2 and
prepared source v2. Current examples and referencing schemas are updated; no
compatibility loader or private-map rewrite is included.

## Small public comparison

Inputs are the committed [example world](../../examples/world/landform-world.world.json)
and [recipe](../../examples/world/landform-world.geology.json): two contiguous
continent labels, an island, a western mountain belt, eastern plateau and nested
lowland. The world radius is 2,000 km; seed 42, 257 pixels and coastal rise 80 km.
These invented inputs are demonstrations, not Aethelara lore or physical calibration.

Two end-to-end transfers/builds took 5.088 s together on this checkout:
background 1.809 s, guided 3.272 s. The guided result has five region components.
Coastline values and raster land masks match exactly. Mean absolute height change
on land is 1,091.247 m; 98.858% of land samples change by more than 1 m.
These show that inputs reach generation; they are not realism or performance gates.

Ignored local artifacts: `artifacts/geology-landforms-2026-09-27/`, including
`comparison.png`, `validation.json`, two portable projects and two numeric builds.
The comparison enlarges native pixels for display; it generates no extra detail.

## What did not meet the desired quality

The rendered guided surface exposes polygon-shaped rims and abrupt-looking terrain
character changes. The mechanism is visible in the regional weighting code:
every recipe fades inward, so the shared boundary between different recipes returns
to the generic background. With low plains beside higher terrain this can leave
an unintended raised band. Equal controls are already dissolved and do not have
that administrative-boundary problem.

**Disposition:** accept the explicit authoring/transfer feature; do not call its
output naturally realistic or accept geological/drainage quality from this preview.
The next high-value landform task is continuous shared-boundary blending with
controlled transitions and preserved priority cutouts. Compare a replacement on
these fixed inputs and numeric controls before changing the existing composition
contract. Narrow polygons also need honest transition-support feedback.

No triangulation trial was run. It was rejected during design because the current
fade rule would expose internal triangle edges. No age-to-height or implicit
setting-to-process conversion was implemented. Ages remain metadata for future
physical histories. Existing river bank/representation failures remain in the
[method register](terrain-method-decisions.md), with their original evidence.

## Validation

Focused tests cover exact split/unsplit terrain equality, different relief with
identical mask/coast, deterministic repetition, nested blank and explicit overrides,
longitude seam continuity, canonical reordered worlds, portable recipe provenance,
current schemas and strict fields, cancellation/no-publication, CLI, real Tk controls,
minimum editor layout, pending edits/history and hole hit-testing/dragging.
Pyright and Ruff pass during implementation.

The first integration checks passed 80 tests in 14.90 s. The final focused run
passed **184 tests in 61.95 s**, including numeric build reproducibility and
portable parent snapshots. Final Ruff and Pyright report no errors. Changed
document links, UTF-8 text and diff whitespace pass; the inventory contains
201 documentation files and 213 unique entries including machine-readable contracts.

After the approved long-test run, the full repository suite passed **1,844
tests with one expected skip in 560.53 s** (9 min 20 s). The skipped Landlab
reference test requires its separate scientific environment; this run does not
claim validation of that optional engine. The run used `--maxfail=1` and
finished within the agreed 12-minute limit.

The complete log is retained locally at
`artifacts/geology-landforms-2026-09-27/full-suite-20260927-164913.log`,
with timing and exit status in the adjacent JSON report. Ruff and Pyright
already passed on the same source; only this validation record changed afterward.
