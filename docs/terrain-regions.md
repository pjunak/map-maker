# Shape terrain with landform regions

Select **Region** in the workbench. Choose plain, hills, plateau or
mountains, adjust its controls, click at least three polygon corners and choose
**Finish area** (or right-click). Generate to apply it. Undo removes the last
corner while drawing, then reverses the last completed input edit. Use **Select**
to pick an existing region, change its properties and choose **Apply edit**.
Drag the selected polygon or one of its vertices to move or reshape the input;
regenerate to see the result. New-tool controls apply to the next polygon.

Try [the regional example](../examples/terrain/landform-regions.terrain.json),
which references the same small public coastline as the empty example project.
Regions and the active tool controls are included in project save/open.

## Controls and effects

| Control | Meaning |
|---|---|
| Character | A terrain recipe, independent of climate, biomes and land use |
| Base height | The regional elevation reference in metres before coastal conditioning |
| Relief | Scale of height variation; not a guaranteed peak-to-valley range |
| Feature size | Characteristic size in kilometres; larger values give broader features |
| Transition | Distance inward from the polygon edge over which regional influence reaches full strength |
| Direction | Rotation in the local map plane; 0 degrees is horizontal, 90 is vertical |

Plains use little fine detail. Hills have more local height variation and
texture. Plateaus use a raised, comparatively level interior and a transition
at the region boundary. Mountain belts use elongated ridged relief, varying
crest heights and stronger small-scale detail; direction controls their long
axis. Other recipes rotate their texture without imposing a preferred axis.
These are controllable procedural landforms, not tectonic or erosion simulations.

Regional shapes and mountain summit variation use a fixed two-band carrier with
weights 2/3 and 1/3. Fine texture uses only bands three and above, with fixed
geometric amplitudes. At two detail levels the regional full and macro fields
match; increasing levels adds texture without changing the base macro field.
Blending, authored constraints and drainage still affect finished terrain. See
[ADR-0059](adr/0059-preserve-noise-band-amplitudes.md) for the current recipe and
[measured changes](research/2026-09-22-stable-detail-band-amplitudes.md).

Changing character loads its starting values. Each saved polygon stores its
complete effective settings. The defaults are:

| Recipe | Base m | Relief m | Feature km | Transition km |
|---|---:|---:|---:|---:|
| Plain | 250 | 100 | 150 | 50 |
| Hills | 700 | 900 | 100 | 70 |
| Plateau | 2200 | 200 | 200 | 40 |
| Mountains | 1000 | 3500 | 120 | 100 |

## Boundaries and authoring priority

A simple polygon may cross the coastline; only land is generated. Holes and
sea keep their existing mask. The region must cover some land and its base
height cannot exceed the global ceiling. Coastline heights remain zero.

Adjacent recipes now blend across their shared boundary without a band of
generic background terrain. The outside edge of their connected coverage still
fades inward to background. Unassigned holes stay background, and disconnected
regions do not influence each other. Equal settings are dissolved for generation,
so splitting or duplicating the same recipe does not create a seam.

Transition distance controls compact neighboring support and the fade toward
unassigned terrain. A recipe's established interior excludes outside recipes;
thin regions may never reach that strength. True overlaps use normalized weights
in stable order, not last-drawn precedence. Large height differences can still
produce steep slopes even with continuous weights. There is no global histogram
remapping. [ADR-0081](adr/0081-blend-adjoining-landform-regions.md) defines the rule.

Regions shape the base before brush, ridge, valley and height-point constraints.
The regional base enters relative-valley references, automatic drainage planning
and the final field. Exact height anchors retain their existing authority.
A region can influence neighboring recipes within its transition distance.
Its base influence remains inside connected assigned coverage; drainage can
respond farther away.

The new stage uses the named `terrain.landforms` seed. Shared metric coordinates
produce identical values across display resolutions and sampling chunks. The
routing grid remains 257 nodes on its longest axis. The review overlay now draws
thin D8 segments at display size rather than enlarging canonical raster cells;
its topology and uphill-conflict meaning are unchanged. Straight/grid-aligned
routes are still present and should not be mistaken for finished river geometry.

## Regional automatic valleys

Automatic valley depth now follows regional relief. At full regional influence,
its total cutting budget is 15% of relief for plains, 40% for hills, and 25%
for plateaus and mountains. Default plains therefore allow at most 15 m and
plateaus at most 50 m. These are procedural safeguards, not measured erosion
rates or a simulation of rock resistance.

Budgets use the same shared-boundary and coverage weights as landform shape.
They cannot exceed the global automatic-cut budget. Zero relief at full
influence disables automatic cutting. The initial valley shape is scaled to
this budget; downstream floor and steepness corrections must respect it too.
Authored height points and valleys retain their authority. These limits bound
automatic incision, not the combined effect of authored features, coastal
conditioning and residual-detail suppression.

Shallower cuts can leave more uphill edges in the planned channel graph. The
Drainage review continues to flag these conflicts; increasing cuts until every
filled route is downhill would erase the intended landform. Authored lakes/outlets now have separate review and conservative area transfer;
automatic channel reconciliation is still needed. Completion status now reports cut-limit
and depression context counts; the headless build adds a coloured context panel
and numeric edge evidence ([ADR-0032](adr/0032-classify-channel-conflicts.md)). See
[ADR-0031](adr/0031-bound-incision-by-regional-relief.md) for fixture results.

## Water-path review

Regional boundaries now guide finer ground checks on shorelines and water
paths. Narrow transitions and thin crossed regions receive local probes while
authored ground remains unchanged. A detected crest can block collection or
outlet transfer. See the [water sampling contract](terrain-water.md#finer-water-evidence)
and [measured convergence](research/2026-09-13-water-sampling-convergence.md).
This is finite profile evidence, not a guarantee that every regional or
procedural extremum has been found.

## Current limits

There are no regional sediment, rock-resistance, runoff or drainage-density
controls yet. Lowland-fraction and peak-density targets,
asymmetric escarpments and connected mountain spurs remain in [TODO](../TODO.md).
[Authored lakes and dry basins](terrain-water.md) now protect their footprints;
river reconciliation remains incomplete. Use Drainage review to inspect remaining uphill conflicts.

Only current project/build formats are supported; see the [schema index](../schemas/README.md).
[ADR-0030](adr/0030-author-regional-landforms.md) records the implementation.


## World-derived regions and nested cutouts

World → Terrain can transfer a saved geology recipe into these same instructions.
See [world geology](world-geology.md). A region can now have hole rings; an enclave
assigned to a higher-priority province or to background terrain remains excluded
from the surrounding recipe. Outlines, hit-testing, whole-region moves and vertex
dragging include those holes. Property edits and Undo/Redo retain them. Polygon
drawing still creates one outer ring; nested world provinces are the current
authoring path for cutouts. Invalid ring intersections are rejected by the geometry checks.

Equal landform controls are dissolved before transfer, including across continent
labels and different geological ages. Different adjoining recipes use the shared
blend described above. Blank cutouts remain background; explicit enclaves blend
at their edges and keep their established interiors. Project v8 serializes holes;
regional-landforms@4 records the new composition and support rules. See the
[paired comparison](research/2026-09-27-shared-landform-blending.md).
