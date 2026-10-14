# Terrain tool

The terrain tool generates reproducible elevation data from an authored
geographic skeleton. Editing specifies the inputs for the next generation;
completed terrain is a read-only result.

## Run the workbench

```powershell
.\.venv\Scripts\map-maker.exe terrain gui
```

The window opens with **World** and **Terrain** tabs. World retains complete SVG
source maps, continental ownership and an explicit spherical geographic frame.
Read the [world guide](../../../docs/terrain-worlds.md), or try
`map-maker terrain gui --world examples/world/four-shores.world.json`.
Its guided steps run down the left (Source map, Planet, Geology, Generate, Wonders, Explore;
see [the steps](../../../docs/terrain-worlds.md#the-steps)) beside one map view that
shows source, context and planet maps in any projection, with drill-down to regional
detail ([planet guide](../../../docs/world-planet.md)). Long jobs show progress and
**Cancel** in the status bar. The optional **Geology** step edits the
[province/default recipe](../../../docs/world-geology.md) in place, with its own
recipe saves and source/context backgrounds; the planet uses it as it stands. The
optional **Wonders** step places [wonders](../../../docs/wonders.md) by hand in their
own file and applies them to a generated planet without eroding it again.

**More tools** follow the steps. **Geographic context** generates spherical coverage,
connected water and resolution support, shared-edge openings, separate water-piece
links, shore distance and exposure, with verified saved-context inspection; see
[geographic context](../../../docs/world-context.md). **Ocean floor** opens a separate
[ocean-floor workflow](../../../docs/world-bathymetry.md) from matching context,
with explicit ocean selection, shelf/slope/basin inputs, numerical error/support
views and independent saves/results. **Local terrain** selects a continent and
creates a local terrain project with connected neighbours, retained world identity
and fixed projected scale. Explicit landform controls and matching geographic
context can affect that experimental rough terrain; geology ages do not. When
context is currently generated or opened, Terrain embeds bounded immutable samples
and labels the coastal consumer experimental. It opens in Terrain ready for the
workflow below.

`--project` opens a local terrain file directly in that tab.

The Terrain workspace imports closed SVG land shapes, dissolves adjacent
mainland sections, and retains disconnected islands in the same map. It exposes
numeric generator settings as sliders and steppers, and lets
the user draw absolute/relative height points, ridges and valleys, landform
regions, lakes and dry basins. A terrain brush
paints broad soft elevation guidance directly over the continent. Import
validation and generation run on background workers with progress reporting.
Generation also shows elapsed time: click **Cancel generation** or press **Esc**
to stop at the next checkpoint. The previous map and authored inputs are retained;
controls unlock when the worker acknowledges the stop. Read the
[cancellation guide](../../../docs/terrain-generation-control.md) for limits.
The result is previewed and can be exported as a transparent colour-relief PNG.
The same window can save and open authored `.terrain.json` projects.
Every build uses named stage seeds derived from the numeric master Seed.
See the [seed contract](../../../docs/terrain-seeds.md). Only the current save
format is supported; older saves must be recreated.

For saved projects, `map-maker terrain build PROJECT --output NEW_DIRECTORY`
uses the same pipeline without opening the GUI. It saves the Float32 DEM,
mask, coordinates, both PNG styles, inspectable drainage and a completion manifest.
Use `map-maker terrain water-budget PROJECT` to inspect shoreline and potential
internal-network demand before a build; see the
[forecast guide](../../../docs/terrain-water-budget.md).
Saved-parent regional commands and sessions now support explicit
[memory admission budgets](../../../docs/terrain-regional-memory.md).
See the [numeric build guide](../../../docs/terrain-builds.md). The coordinate
model for generated terrain remains the local SVG plane. Builds include a
[local-metric GeoTIFF](../../../docs/terrain-geotiff.md); world-derived sources retain their projection, while raster world georeferencing remains planned.

[`examples/terrain/example.terrain.json`](../../../examples/terrain/example.terrain.json)
is a small public project for trying the complete workflow; its referenced
[`coastline.svg`](../../../examples/terrain/coastline.svg) can also be imported
directly.

Automatic drainage now plans its route over the authored broad terrain.
Relative valley floors are prepared before generated incision. Exact point
anchors retain their final authority. Use **Drainage review** to see planned
channels in blue and segments that rise on the finished terrain in red.
This is a canonical-grid review, not a guarantee of valid rivers. See
[the stage decision](../../../docs/adr/0029-route-drainage-over-authored-terrain.md).

Use **Region** to draw plains, hills, plateaus and mountain belts.
The [region guide](../../../docs/terrain-regions.md) explains controls, overlap,
transitions and the [public example](../../../examples/terrain/landform-regions.terrain.json).

## Edit instructions over a generated reference

1. Generate a map from the coastline and current instructions.
2. Keep that result visible while adding guidance: for example, choose **Region**,
   select **mountains**, draw the area, then **Finish area**.
3. To revise an existing instruction, choose **Select**, pick it in the list,
   or **Ctrl+click** its point, line or area. Drag a white handle to move a vertex;
   drag the line or the interior of an area to move the whole instruction.
   Change properties and press **Apply edit**. A completed drag is one undo step.
   Invalid geometry is rejected without changing the instruction.
4. Choose **New instruction / cancel edit**, or a tool button, to resume drawing.
   Switching selection/tools discards unapplied property values and unfinished
   geometry. **Generate** and **Save** require the current edit to be applied or
   the draft to be finished/cancelled.
5. Press **Generate terrain** again. The generator uses the revised inputs;
   it never uses the displayed image or previous DEM as editable terrain.

**Delete**, **Clear**, **Undo**, and **Redo** operate on committed instructions.
Undo first removes an unfinished vertex when drawing. Committed additions,
property changes, moves, deletions and clear-all are reversible; draft vertices and
numeric generator settings do not have redo history. Opening another project or
coastline starts a new instruction history. Existing lake outlets keep their
position when editing the water level; a newly enabled outlet uses the first vertex.
Moving a lake moves its outlet too. Moving a boundary corner keeps an existing
outlet at the same fraction of its edge. Direct outlet relocation is still planned.

The banner distinguishes a matching map from a previous-generation reference.
Changing generator settings also makes the reference stale. PNG export is enabled
only when the last successful result matches the applied inputs. Failed generation
keeps the previous reference, and completion is checked against the worker's exact
input snapshot. Drainage/catchment overlays and basin details describe that last
result, even while new instructions are drawn above it.

The reference image and undo history last for the current workbench session.
Project saves continue to contain authored inputs only; reopening requires
regeneration to obtain a background. Pan/zoom preserves normalized map coordinates
and exposes the visible geographic bounds. It currently magnifies existing samples;
automatic zoom-driven enrichment remains planned. Separate
[verified-parent CLI commands](../../../docs/terrain-parent-regions.md) now provide
regional replay and explicitly experimental added detail, under
[ADR-0061](../../../docs/adr/0061-verify-parents-and-isolate-local-detail.md).
Desert/biome instructions require the future climate input contract; the current
region tool provides plain, hills, plateau and mountains.

## Quick testing and navigation

Open the public regional example directly from the repository root:

```powershell
.\.venv\Scripts\map-maker.exe terrain gui --project examples/terrain/landform-regions.terrain.json
```

Use **Save As** to make a working copy, choose **Quick test · 257 px**, then
**Generate terrain**. These presets set the actual output resolution saved in the
project: **Detail · 1025 px** requests a denser whole-map build. Neither button
adds hidden detail bands or implements a regional generation job.

| Action | Control |
|---|---|
| Zoom around the pointer | Mouse wheel; toolbar **+ / -** zoom around the centre |
| Pan | Middle-button drag, or focus the map and hold **Space** while dragging |
| Restore the overview | **Fit**, or **F** outside a text field |
| Inspect terrain without input overlays | Uncheck **Instructions**; painting/selection is suspended |
| Inspect location and ground | Move the pointer: local x/y km from the map's top-left and the nearest reference DEM sample |
| Adjust brush width / strength | **Shift+wheel** / **Ctrl+Shift+wheel** |
| Apply properties / finish a draft | **Enter** with the map focused |
| Cancel generation while running; otherwise cancel unapplied properties, draft or drag | **Esc** |
| Delete / undo / redo an instruction | **Delete** / **Ctrl+Z** / **Ctrl+Y** or **Ctrl+Shift+Z**, outside text fields |
| Open / Save / Save As | **Ctrl+O** / **Ctrl+S** / **Ctrl+Shift+S** |
| Generate | **Ctrl+Enter** |

The toolbar shows magnification relative to Fit, km per display pixel and the
current ground sample spacing. Zoom changes display scale; ground spacing stays
fixed until a new generation. The ground readout and review overlays belong to
the last result, including when it is stale; lake
water surfaces remain separate from the reported ground height. Coordinates are
local to this coastline, not latitude/longitude.

Pan/zoom renders only the visible window instead of allocating an enlarged
whole-map image. Drainage/catchment layers are cached per result and toggle
combination and released when both review toggles are off. Replacing a result,
changing render style, opening another project and closing the workbench release
obsolete image buffers. If a style render fails, the previous view and legend
remain active. Zoom can expose coarse review samples; it does not improve their
accuracy. Inspect **Drainage review** and **Basin details** when evaluating a run.

In cartographic relief, small lake pools fade out in distant views and become
visible as you zoom closer. Panning preserves their visibility, including when
most of a large lake leaves the screen. All generated water remains available
in numeric outputs; the ground readout still reports the lake bed. PNG exports apply visibility at the
exported image size, independently of the current zoom; scientific elevation
continues to show the lake bed. The blue/red planned channels and teal outlet
lines are diagnostic overlays, available at every scale. Small cartographic
rivers await finer local terrain and hydrology generation; see
[the scale-aware water plan](../../../docs/adr/0057-display-water-at-the-appropriate-scale.md).

## Saving and unfinished work

A **\*** in the title marks unsaved generation inputs or an unfinished instruction.
**Save** updates the known project path atomically; **Save As** chooses another
path. Open, replacement import and window close offer Save / Discard / Cancel
when inputs are unsaved. Choosing Save continues only after that exact snapshot
has saved successfully. Cancelling the file picker or a failed save leaves the
current project open. Apply/finish or press Esc before saving a staged edit.

Navigation, selection and changing defaults for a new drawing tool do not make
a saved input project dirty. Tool defaults are nevertheless included when you
save. Results, navigation and undo history are session-only. A failed load keeps
the existing project. Worker operations lock input controls; navigation remains
available during generation. A close request during an operation stays in the
workbench; close again after it finishes. Cancellation, autosave and before/after
comparison remain planned.

## SVG land-source contract

Open a saved project JSON or import an SVG land source. For SVG import:

- The coastline source must be SVG.
- If groups named `Land Shapes` exist, only drawable objects beneath those
  groups are land. Otherwise, every drawable object is treated as land.
- Every land object must contain exactly one continuous, closed subpath.
- Every loop must enclose positive area and must not self-intersect.
- SVG transforms are applied before the coastline is sampled.
- Overlapping or nearly touching land objects are dissolved. Their shared edges
  do not become coastlines or terrain-generation boundaries.
- Disconnected polygons become islands or other separate land components in one
  shared generation. Larger enclosed gaps remain water; sub-sampling slivers at
  separately drawn borders are repaired.
- SVG water gaps remain non-land; authored lake levels use separate basin constraints.

The combined land geometry's **longest bounding-box dimension** is the object
scale in kilometres. The shorter dimension keeps the SVG aspect ratio. This
convention is explicit so that the same source and scale always establish the
same metric coordinate system. Every mainland section and island is evaluated
in that one coordinate-addressed field and with the same stage seed.

## Authoring topography

After importing a coastline, select a drawing tool above the map:

- **Terrain brush** paints broad, soft elevation guidance.
- **Height point** places one local height or height offset.
- **Ridge line** establishes a crest or adds ridge relief.
- **Valley line** runs from an upstream head toward its outlet and establishes
  an outlet floor or adds relative incision.

Each tool keeps its own mode, elevation value, and radius or width while tools
are switched. Brush strength is also retained independently. The initial modes
are relative brush, absolute height point, relative ridge, and relative valley.

Brush, point, ridge and valley tools use one of two elevation modes:

| Mode | Meaning |
|---|---|
| **Absolute** | Specifies an absolute elevation in metres above the zero sea-level datum. A point is exact, a ridge is a minimum crest, a valley value is its downstream outlet floor, and a brush blends toward its target. |
| **Relative** | Specifies displacement from the terrain entering that pipeline stage. Positive point or brush values raise terrain, negative values lower it, ridge values add relief, and valley values add incision depth. |

Relative mode is deliberately local relief rather than true topographic
prominence. Prominence depends on the final summit and its key saddle, while a
relative constraint is a controlled deformation of the generated surface.

With the terrain brush selected, drag over the land to paint a continuous
stroke. The ordinary mouse wheel changes its full width. **Ctrl+wheel** changes
its strength in five-percent steps. The cursor ring and adjacent readout show
both values before paint is committed. A click without dragging creates one
circular brush mark.

In absolute mode, brush strength blends toward the target height. In relative
mode it scales the signed height offset. Overlapping absolute strokes combine as
weighted targets; overlapping relative strokes add their displacements. Both
behaviours are independent of stroke list order. Structural lines are applied
after brush guidance, and exact absolute points remain the final authority.
Overlapping absolute points retain their individual target heights at their
coordinates, with surrounding terrain approaching those values smoothly. Sampling
the point itself in a saved raster requires a grid node at that coordinate.
Conflicting absolute heights at the same location, and nonzero heights exactly on
a sea-level land boundary, are rejected. See
[ADR-0060](../../../docs/adr/0060-interpolate-overlapping-height-points.md).

Set the tool's elevation value and radius before placing a point or finishing a
line. The core radius is the half-width of the strongest response, not a hard
cut-off; a lower-amplitude geological shoulder continues beyond it. Ridge and
valley lines collect vertices until **Finish line** is pressed or the map is
right-clicked. **Undo** first removes unfinished vertices, then committed
features. Importing another coastline asks before clearing authored features.
Valleys must be drawn from their upstream head toward their downstream outlet;
the arrow at the final vertex makes this direction visible.

Polyline corners are gently rounded during generation, and their effective
width varies with the deterministic terrain field instead of producing a
perfect extrusion. Free ends taper. On a line without an explicit profile, a
height point close enough to a ridge or valley also becomes an elevation anchor
along that structure, so peaks, passes,
and floor heights bend its longitudinal profile rather than forming an
independent circular stamp. Absolute points attach to nearby absolute
structures. A relative point attaches only to the uniquely nearest relative
structure; if ownership is ambiguous or no compatible line is nearby, it keeps
its free-standing displacement behavior.

When several anchors lie on one compatible structure, a shape-preserving cubic
profile connects them along the line without overshooting adjacent targets.
Absolute anchors set absolute metre elevations. On a relative ridge, a point's signed
displacement is added to the line's base relief; on a relative valley, it is
subtracted from the base incision depth, so a positive point makes the floor
shallower and a negative point makes it deeper. A profile cannot reverse the
parent feature's kind. Two peaks surrounding a lower point can therefore create
a geometric saddle while the terrain still falls away across the ridge.
Conflicting targets at the same projected line position are rejected rather
than silently averaged.

For direct ownership, select a ridge or valley and choose **Profile...**. Add
positions/heights along that line, preview the curve, apply and regenerate.
Profiles support explicit peaks, passes and descending spur/floor values without
nearby-point attachment. See the [profile guide](../../../docs/terrain-structure-profiles.md)
and its public range/lowland example.

Explicit absolute ridge profiles retain each crest through ridge blending and
preserve actual shared contacts while their other corners are rounded. Incompatible
contact heights produce an error with the instruction numbers and profile positions.
The [connected crest example](../../../examples/terrain/connected-crests.terrain.json)
shows a descending spur attached at a protected range corner. Valleys and independent
height points retain later ground authority; see
[the measured limits](../../../docs/research/2026-09-27-shared-ridge-crests.md).

Before raster generation, every valley samples the stable terrain surface
entering the valley stage at resolution-independent metric positions. Relative
depth is subtracted from that reference, then a downstream-only correction
removes any uphill floor segment without ever raising terrain. This keeps a
valley through a high plateau high while still making its route drain toward
the authored outlet. Absolute floor anchors must already be non-rising in the
authored direction and are rejected if they conflict. Relative depth remains a
preferred minimum incision: the downstream correction may deepen it where that
is necessary to avoid an uphill floor. Authored lake/dry-basin retention applies to automatic channels; this explicit
valley profile remains authoritative inside those areas.

Constraints use normalized coastline-bounds coordinates while being authored
and are converted to explicit metric coordinates during generation. They are
kept separate from the imported coastline and are recorded in exported PNG
metadata.

## Saving terrain projects

**Save** writes the coastline reference, all generator settings, every
committed constraint, the active tool, and each tool's independent controls to
a readable JSON document ending in `.terrain.json`. **Open project** restores
that state. Apply or finish the current instruction, or cancel it with Esc, before
saving. See [saving and unfinished work](#saving-and-unfinished-work) for dirty
state, Save As and project-switch safeguards.

The SVG remains the authoritative coastline rather than being duplicated into
the project. Its path is relative to the project file whenever possible, and
the project records a SHA-256 fingerprint of the exact SVG bytes. Opening fails
clearly if the SVG is missing or changed. Saving also fails if the SVG changed
on disk after import; re-importing makes that geographic change deliberate.

Project files contain authored inputs plus optional immutable bounded world-context
samples. Generated terrain arrays and PNG previews are not embedded. Saves use a
temporary file followed by atomic replacement so
an interrupted write does not leave a partially written project. The current format is
strict: unknown fields or unsupported versions are rejected rather than
guessed. The public contract is
[`schemas/terrain/project-v9.schema.json`](../../../schemas/terrain/project-v9.schema.json)
and its rationale is recorded in
[ADR-0006](../../../docs/adr/0006-versioned-terrain-project.md).

## Drainage inspection and density

Enable **Drainage review** to see connected planned channels. At overview scale,
smaller tributaries fade out; zoom reveals the existing network. Lines are drawn
at screen resolution so their thickness does not grow with magnification.
**All channels** shows the entire planned network. Every sampled uphill edge
remains red in either view. Enable **Depressions** separately for basin/spill
polygons; it starts off to keep channel inspection clear.

For fewer generated channels, set **Drainage density** to 0.5 and generate again.
The default 1.0 retains the established terrain behavior. This is an input change,
so the previous result stays visible as a stale, read-only reference until generation.
Density controls channel initiation, not rainfall, physical river width or an
exact percentage of channels. See the [drainage guide](../../../docs/terrain-drainage.md).

Zooming the review does not generate finer hydrology. Canonical routes still use
an eight-direction grid; straight runs and angular turns remain a generation
limitation. The workbench shows its fixed routing spacing alongside the review.

## Generator settings

| Setting | Meaning | Start value |
|---|---|---:|
| Seed | Stable integer selecting the generated field | 20,260,902 |
| Object scale | Longest coastline-bounds dimension | 4,000 km |
| Output resolution | Pixels along the longest dimension | 768 px |
| Elevation ceiling | Upper bound used by the synthetic relief model | 4,500 m |
| Largest feature | Wavelength of the broadest noise band | 450 km |
| Detail levels | Number of successively halved spatial bands | 6 |
| Fine-detail strength | Ratio of each band amplitude to the preceding band | 0.55 |
| Coastal rise distance | Distance over which relief rises from sea level | 180 km |
| Elevation variability | Mix between an even interior and generated relief | 0.75 |
| Drainage density | Automatic channel initiation multiplier; 0.25–2, lower forms fewer channels | 1.0 |

Each noise band has a fixed share of the amplitude budget: band `k` has weight
`(1-r) * r^k`, where `r` is Fine-detail strength and `k` starts at zero. Selecting
more levels adds smaller bands without weakening existing ones. Unevaluated
bands keep their share: `N` levels use `1-r^N` of the budget. High fine-detail
strength with few levels therefore resolves less of the total variation.
Regional shape carriers remain fixed; finer texture starts at the third band.
This policy deliberately changes generated terrain. See
[ADR-0059](../../../docs/adr/0059-preserve-noise-band-amplitudes.md).

## Determinism and resolution

The stochastic component is coordinate-addressed. A stable integer hash maps
the seed, detail band, and absolute kilometre lattice coordinate to a value.
It does not consume a mutable random-number stream and does not depend on raster
dimensions or evaluation order.

With unchanged inputs and detail settings, if a finer grid includes the same
local-metric coordinate samples as a coarser grid, their values are bit-for-bit
equal; the finer grid only adds
samples between them. The test suite verifies this with nested 65 and 129 sample
grids. Arbitrary output dimensions do not necessarily share pixel positions,
but querying the same kilometre coordinates still gives the same terrain.

This is a sampling guarantee for independently generated output grids. It does
not imply equal cell averages or continuity between different input settings.

The [regional sampling command](../../../docs/terrain-regional-sampling.md) now
samples bounded windows on nested finer coordinates, using a clipped halo and
the unchanged full-source field. It reuses global constraints and canonical
routing context; the numeric samples and cropped ground preview have their own
provenance manifest. Public 65/129/257 windows, overlaps and repeat visits retain
exact shared values.

The [verified-parent workflow](../../../docs/terrain-parent-regions.md) now loads
current completed builds, replays every delivered sample and reused routing
field, and provides a separate experimental residual with fixed cell moments.
Nested coordinates and parent nodes remain exact; authored cores, basins and
planned channel corridors are protected. [Shared-edge detail](../../../docs/research/2026-09-23-shared-edge-detail.md)
connects additions using fixed terrain-slope weights and reduces boundary slope
errors. Cell edges may now differ from the unchanged parent. Directional pattern,
coarse spectral acceptance, transitions to the unenriched parent, finer inherited
hydrology and GUI request scheduling remain open. See
[ADR-0048](../../../docs/adr/0048-keep-zoom-driven-detail-generation.md),
[ADR-0058](../../../docs/adr/0058-sample-bounded-regional-windows.md) and the
[regional prototype](../../../docs/research/2026-09-04-terrain-prototype-contracts.md).

## Model and review limits

The surface combines coordinate-addressed relief, coastal conditioning, regional
recipes and authored guidance. Automatic valleys use contributing area and slope
on a fixed 257-longest-side routing grid. Regional relief caps bound generated
cuts; absolute anchors remain authoritative. Bounded cubic reconstruction softens
interpolation creases between routing samples; compact diagonal connections
reduce scalloping along selected channels. Source-aware fitting also adjusts
cuts along cardinal/diagonal floors to reduce humps and artificial pits within
the existing cut ceiling. Regenerate with **Detail (1025 px)** to inspect the
finer surface. Targeted mountain-crest observations now help routing avoid
barriers hidden between nodes; this changes the generated network under the new
algorithm, while display resolution still shares one canonical plan. D8 turns
and unobserved or unavoidable barriers remain; see the
[comparison](../../../docs/research/2026-09-16-mountain-crest-routing.md).
This is process-informed terrain,
not a simulation of tectonics, rock, sediment, climate or geological time.
Read [the pipeline overview](pipeline/README.md) for stage order and algorithms.

Finished-ground diagnostics use that same canonical grid. Priority-Flood works
on a copy and reports depression extents, fill measurements and representative
spill/terminal routes; it never replaces the ground DEM. **Drainage review**
shows the eight deepest candidates, plus planned channels and uphill conflicts.
These candidates do not automatically author lakes or form a nested depression
hierarchy. See [the basin contract](../../../docs/terrain-basins.md).

Authored water adds bounded, finer profiles between canonical nodes. Increasing
output image size does not refine the routing topology or prove that every
between-sample obstruction was found. Sampled outlet clearance and transferred
contributing area are review results, not physical discharge or lake equilibrium.

The generated elevation array is Float32 metres in memory. The PNG is a derived
visual product with transparent ocean, elevation tint, hillshade, source name,
settings, render style, palette, and colour-scale metadata. The preview toolbar
switches between **Cartographic relief**, the default fixed 0–10,000 m world
scale with stronger terrain shading, and **Scientific elevation**, the ordered
and colour-vision-deficiency-safe Oleron land sequence normalized to the active
generation ceiling. The cartographic scale uses green lowlands, yellow and
brown ordinary uplands, a gradual umber-to-muted-red transition from 6,000 to
8,200 m, progressively lighter red above 8,200 m, and near-white only at
10,000 m. Changing style re-renders the same DEM and does not regenerate or
alter elevation.

The **Elevation ceiling** remains a generation control, not a colour control.
Its default is 4,500 m and its UI range extends to 12,000 m for exceptional
terrain. Raising it does not stretch ordinary elevations into summit colours;
on every continent, a given metre elevation retains the same cartographic hue.

These colours express elevation only; they do not claim vegetation, exposed
rock, or snow. The PNG is not an authoritative DEM file; headless builds write
the numeric GeoTIFF and a completion manifest. The current display decisions are recorded in
[ADR-0011](../../../docs/adr/0011-separate-cartographic-and-scientific-relief-styles.md)
and [ADR-0012](../../../docs/adr/0012-fix-cartographic-colour-scale-at-ten-kilometres.md),
with supporting [cartographic-style analysis](../../../docs/research/2026-09-03-cartographic-relief-style.md)
and [scientific colour-ramp research](../../../docs/research/2026-09-03-elevation-colour-ramp.md).

## Saved inputs and build outputs

Projects persist the SVG reference and fingerprint, generator settings, authoring
defaults, brush/point/ridge/valley constraints, landform regions and lake/dry-basin
intent. Direct per-vertex profiles, new structural guide types, reusable profile
files and planetary placement remain in the [roadmap](../../../TODO.md).
Only current formats in the [schema index](../../../schemas/README.md) are supported.

Headless builds write authoritative Float32 ground as NPY and local-metric
GeoTIFF, masks/coordinates, routing/water/basin-flow archives, derived previews,
diagnostics and a completion manifest. The [build guide](../../../docs/terrain-builds.md)
owns the product list. Contour and river vectors, meshes and separate tint-only
or hillshade-only files are future products.

## Internal modules

| Module | Responsibility |
|---|---|
| `application/` | Shared saved-project build operation and completion checks |
| `domain/` | Units, coordinates, constraints, settings, projects, grids and seeds |
| `pipeline/` | Deterministic generation, numeric routing and review |
| `adapters/` | File formats, GIS libraries, renderers, and optional engines |

These are boundaries, not promises of immediate complexity. Add modules within
them only when an implemented behavior needs them.

## Next vertical slices

Follow the [current development strategy](../../../docs/strategy/README.md)
for the implementation order and evidence gates. The
[terrain roadmap](../../../TODO.md) tracks the wider backlog, including world
placement, input editing and contour exports.

Additional time-stepped processes need constraint, reproducibility and scale
validation; the bounded automatic-incision heuristic is already implemented.


## Authored lakes and dry basins

Use **Lake** or **Dry basin** to draw a closed area and choose **Finish area**.
Lake controls set an imposed water level and an optional first-vertex outlet.
Both footprints exclude automatic cuts and absorb planned contributing area;
authored heights and valleys still apply. Lake water is displayed separately
over its preserved ground DEM.

**Basin catchments** maps collected water, collected dry ground and retained
nodes. **Basin details** explains area accounting, flat routing, shoreline
openings, outlet-level differences and sampled wet/dry/path barriers. Orange
points mark uncontrolled low shorelines; red diamonds mark sampled barriers;
connected outlet paths appear in teal. Full evidence is exported even where the
display limits markers.

Eligible outlets transfer only area with reviewed paths. Closed pits and
unresolved dry donors retain their contributions; separated wet pools block the
whole outlet. Complete sampling budgets are checked before evaluation. Water
levels remain authored previews and inter-lake transfer is not implemented.

The [water guide](../../../docs/terrain-water.md) owns detailed semantics,
budgets and evidence fields. The [public examples](../../../examples/README.md)
cover closed basins, connected outlets, flats and narrow shoreline, downstream,
internal-water and dry-collection barriers.
