# World-to-terrain handoff and feature priorities

Date: 2026-09-27. Baseline: `0c3edc8`; implementation in the accompanying change.
The user chose the world-to-terrain workflow and asked for larger product gains,
separate maintainable modules, and consultation before longer tests.

## Delivered behavior

World now offers **Terrain…**: choose a continent, create a new project folder,
then author and generate using the existing Terrain workspace. The matching CLI
is `map-maker world terrain WORLD --continent NAME_OR_ID --output NEW_FOLDER`.
It validates the current world, includes the continent's islands and physically
connected neighbouring land, dissolves internal ownership boundaries, and projects
coastlines into metres on the declared custom sphere. The ordinary terrain
project's scale is fixed to the projected extent. Reopening follows the latest
saved project and existing unsaved-work guards.

The canonical prepared SVG retains the original world snapshot, assignments,
projection, exact projected rings and visible paths. It avoids the generic local
SVG importer's morphological closing and small-hole removal. That existing
import path is useful for ordinary sources but unsuitable for a lossless world
handoff. Source metadata has its own schema; terrain project v6 is unchanged.
Separate modules own selection, projection, source format, orchestration and UI.
No new dependency or terrain solver was introduced.

## Model and existing implementation basis

Use the existing Rasterio binding to PROJ's spherical azimuthal equidistant
projection, with explicit radius and an area-weighted Cartesian centre.
[PROJ's AEQD documentation](https://proj.org/en/stable/operations/projections/aeqd.html)
defines the projection and custom-radius parameters;
[Rasterio's transform API](https://rasterio.readthedocs.io/en/stable/api/rasterio.warp.html)
supplies the existing adapter boundary.

Source-linear rings are densified to at most 0.25-degree steps, then refined when
quarter/midpoint samples depart from their projected chords by more than 25 m.
The maximum sampled angular radius and transverse scale are retained. Refuse
hemisphere-sized land or sampled radius beyond 80 degrees; use separate regional
domains with shared boundary conditions in a later feature. This is a bounded
local projection, not a global distance-preserving terrain grid.

## Validation and a failed first real-world attempt

The public regressions exercise connected foreign land versus distant islands,
tiny holes/gaps, periodic seams, polar caps, radius scaling, deterministic
projection, lossless save/reopen, folder relocation, fixed scale, cancellation,
existing-output protection, metadata schema and a complete normal terrain build.
Tk tests exercise the actual creation action, automatic opening, protected unsaved
terrain, errors, fixed-scale controls and reopening updated saved instructions.

A real Tharkeniss Veld transfer initially failed a component-overlap check.
The 20 projected components formed a valid MultiPolygon, but subtracting two
roughly 25.7-trillion-square-metre area totals left 0.05078125 m² of roundoff.
An absolute 0.01 m² subtraction threshold falsely rejected the map. Replaced it
with direct MultiPolygon topology validation; added a continental-scale multipart
roundtrip regression. This fixes validation, without moving or merging land.

The initial private-world transfer and reopening completed in 8.40 s, and its
257-pixel build in 10.43 s. That preliminary example used an older saved world's
full-page frame and included only Veld/Dra; it is superseded by the corrected
frame and connected-land example below. It remains evidence of the initial
workflow, not the current geography or an assessment of terrain realism.

### Semantic borders and source precision

An asymmetric ownership split initially moved the projection centre even when
the physical land was identical: a 40-by-40-degree rectangle changed from
(0, 15) degrees to approximately (0.0241, 15.2067). Computing a weighted centre
from semantic pieces caused this. Dissolve physical land before choosing the
centre, remove only exactly redundant collinear vertices, and normalize ring
ordering. Regressions now require identical projection/coastline, land masks and
Float32 elevations for equivalent whole/split land. Three-owner transitive
connectivity and a genuine narrow strait have separate regressions.

Actual authored geometry needs the same distinction. Native Affinity inspection
found matching cubic border sequences displaced by small constant translations:
about 0.01010 source units at Dra/Kel, 0.00416 at Veld/Dra and 0.00147 at Kel/Oul.
The user confirmed continuous Dra/Kel land and required shared continent borders
to remain inland. These were drawing offsets, not just export rounding.
Backed-up native sources and their independent continent copies were corrected
only along those shared sequences and adjoining endpoint handles. Native counts,
strokes, hierarchy and the 2914-by-1440 spread remain unchanged; Veld's northern
bound moved by 0.00328 source units as a direct consequence of its border repair.

Affinity's native file-export API refused both workspace and documented Desktop
destinations with PERMISSION_DENIED. No application permissions were changed.
The existing SVG was instead updated at those exact shared segments using its
existing rounded reference curves; all 182 other imported features and all
assignments were verified unchanged. The saved world was refreshed explicitly.
No importer-wide buffer, tolerance-based gap closing or inference about genuine
straits was added. Private repair scripts, before/after geometry checks, renders,
hashes and recoverable source copies stay in the campaign workspace.

The definitive source uses its documented frame (17, 0)-(2897, 1440), excluding
the page margins, and radius 6,000 km. The final handoff includes Veld, Dra, Kel
and Oul, retains 20 components and spans 12,001.392 km in the projected plane.
Transfer plus independent reopening took 6.10 s; the ordinary 257-pixel build
took 14.39 s. Its 66.799-degree maximum sampled radius implies 26.844% maximum
transverse stretch. This is usable workflow evidence with a substantial known
projection limitation; regional domains remain necessary for better physical
fidelity. The final preview no longer shows the artificial Veld/Dra coastal
groove. Existing generated examples and contexts retain their older input
snapshots and must not be described as current-world results.

### Regression result

All 20 new workflow tests pass. The full suite completed in 570.46 s with
1,819 passes, one expected isolated-Landlab skip and one failure: an older test
constructed TerrainApp with __new__ but did not initialize its coastline source.
Initializing that fixture's source to None fixes the failure; all 43 settings
and world-handoff checks then pass. No runtime code changed after the full run,
and the successful unrelated checks were reused instead of repeating a long
suite solely for the test fixture. Ruff and full Pyright pass. Documentation
links and inventory are checked (198 Markdown documents plus one legal notice).

These checks establish the handoff and shared-land contracts. They do not
establish better drainage physics or geological realism.

## Short river follow-up retained as evidence

Before the feature priority was selected, a 12.07 s exploratory probe changed
four network layouts at 500 m background spacing and retained the existing
fresh-construction envelopes. All four layouts passed head capture, no interior
sinks, hard targets, divide, cut/volume and longitudinal gates. Dense inward-bank
profiles still failed:

| Layout | Failed inward sections | Worst inward excursion |
|---|---:|---:|
| Tight bends | 4 | 0.606384 m |
| Short tributary | 1 | 0.105858 m |
| Lateral junction | 4 | 0.461243 m |
| Short steep head | 1 | 0.235489 m |

All four passed endpoint-bank support. These are exploratory variations of one
synthetic network, not independent landscapes or a production acceptance set.
The precise mechanism behind each remaining small bank excursion was not isolated;
passing outlet capture does not prove bank shape. Ignored probe files remain under
`artifacts/river-layout-probe-20260927`. Keep this failure visible and revisit
analytic patches, channel-aligned strips or constrained triangles when promoting
the construction model; do not make another round of small bank tuning a prerequisite
for users testing the current generator on their own continents.

## Remaining major features

The current generator is unchanged: world climate, province histories, geological
aging and globally consistent rough relief are not consumed yet. Build rasters
remain local; world correspondence lives in the prepared source. Wide connected
continents require regional domains, and fine islands may disappear at coarse
output resolution. No post-generation ground editing was introduced.

Next prioritize consuming authored geological regions to create related broad
ranges, plateaus and lowlands, with visible effects in this working continent
workflow. Preserve explicit hypothetical forcing and authored controls. Shared
rough-world relief, runoff/history coupling and accepted regional parents remain
separate milestones with the existing physical quality gates.
