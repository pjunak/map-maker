# Import and review a world map

The **World** workspace retains an authored world, assigns its continents and
islands, sets its planet and frame, and saves a portable source project. From
there it builds a whole planet ([planet guide](world-planet.md)).
[Geographic context](world-context.md) generates spherical coverage, connected water
and resolution support. The **Local terrain** tool transfers a selected continent
and connected land into a local metric terrain project, ready to use in the
**Terrain** workspace.

## The steps

The World workspace guides you through numbered steps down its left side. Each
shows a status line, and **Next** at the foot of a page moves on:

1. **Source map**: import the SVG and assign each shape to a continent.
2. **Planet**: name the world, set its radius and check how the map wraps the
   globe. **Next** checks the world.
3. **Geology** (optional): continent settings, provinces and landmarks
   ([geology guide](world-geology.md)). Skip it for automatic mountain ranges.
4. **Generate**: detail, seed and features; then **Generate planet**.
5. **Explore**: maps, projections, regional zoom and export.

**More tools** follow: [Geographic context](world-context.md),
[Ocean floor](world-bathymetry.md) and **Local terrain** (below). The map on the
right follows the open step; in the Geology step it shows the geology map.

## Try the public example

From the repository root after the installation in [README](../README.md):

```powershell
.\.venv\Scripts\map-maker.exe terrain gui --world examples/world/four-shores.world.json
.\.venv\Scripts\map-maker.exe world inspect examples/world/four-shores.world.json
```

The example has four invented continents, two touching mainlands, separately
owned islands, an inland hole, excluded map furniture and an island crossing the
longitude seam. Its 6,500 km sphere is a demonstration, not a default planet.
**Save As** creates your working copy. No original SVG is needed to reopen it.

`map-maker terrain gui` opens the World workspace. To start directly in Terrain:

```powershell
.\.venv\Scripts\map-maker.exe terrain gui --project examples/terrain/example.terrain.json
```

`--world` and `--project` are mutually exclusive startup choices. Both workspaces
remain available in the same window, with separate documents and dirty states.

## Create terrain from the world

1. Open or import your world and confirm its planet, frame and continents.
2. Optionally generate context, or open a completed matching context bundle, and
   set exact landforms in the [Geology step](world-geology.md).
   Open **Local terrain** under **More tools** and choose a continent. The page
   says which geology it takes from the Geology step. The currently generated or
   opened context is passed automatically.
3. Click **Create terrain project…** and choose a **new folder name**. The current
   world inputs are validated and retained; saving the world separately first is
   optional. The source drawing and any existing terrain work remain protected.
4. The new project opens in **Terrain**, initially at 257 pixels. Add mountain,
   valley, height or landform instructions, adjust generator settings, and click
   **Generate terrain**. The object scale is fixed by the world projection.
5. Save instructions normally. Use **Open it in the Terrain tab** in World to reopen
   the latest saved version; declining an unsaved-work prompt leaves the created
   folder available for later use.

The equivalent command is:

```powershell
.\.venv\Scripts\map-maker.exe world terrain examples/world/four-shores.world.json --continent Southmere --context artifacts/four-shores-context --output artifacts/southmere-terrain
.\.venv\Scripts\map-maker.exe terrain gui --project artifacts/southmere-terrain/terrain.terrain.json
.\.venv\Scripts\map-maker.exe terrain build artifacts/southmere-terrain/terrain.terrain.json --output artifacts/southmere-build
```

`--seed` and `--resolution` set the new project's initial generation settings.
Add `--geology PATH.geology.json` to transfer explicit landforms. This file must
match the current world; it is reread at creation. Continent defaults and priority
provinces become editable terrain regions, with nested cutouts preserved as holes.
The chosen recipe is retained inside the prepared source, so it is not another
external dependency when moving a created project.
Add `--context PATH` to bind a verified `context.json` or its containing folder.
The world, projection and optional geology recipe must match exactly. Preparation
resamples immutable context support into the saved terrain project, so the external
context bundle is not needed to reopen, build or replay it.
A continent ID may replace its name. Keep **coastline.svg** beside
**terrain.terrain.json** when moving the folder. The SVG contains visible
projected paths plus the original world snapshot, membership and projection;
the original world file is not needed to reopen the terrain project.

All islands assigned to the selected continent are included. Touching foreign
land is included transitively, across the longitude seam and poles as needed;
a foreign owner's disconnected islands are not automatically added. This avoids
treating an administrative boundary as a sea-level coast. Splitting the same
physical land among continent labels does not change its projection or terrain.
Matching inland borders must meet in the source drawing: a tiny positive gap
still describes water. Correct accidental offsets in the source and create a new
handoff; the importer does not silently fill genuine straits. The prepared source
keeps small holes and water gaps; their eventual visibility depends on terrain
and display resolution. An inland hole currently has the existing terrain
engine's coastline behavior, not a newly inferred lake level.

Projection uses an azimuthal equidistant plane on the declared custom sphere,
with an area-weighted centre. The panel reports the maximum sampled transverse
stretch. A single plane becomes unsuitable for very broad selections: domains
reaching beyond an 80-degree sampled radius or covering a hemisphere are
rejected with a request for regional domains. Splitting such land while retaining
neighbouring terrain boundary conditions is future work. Do not shrink the planet
or exclude connected land to disguise that limitation. **Southmere** works in the
public example; its much wider Westreach/Eastreach union needs that future support.

This is an experimental generation handoff. Explicit landform guidance is applied.
When supplied, geographic context can reduce the broad coastal-distance envelope
through a continuous conservative upper bound; the exact projected coastline and
land mask stay authoritative. Bathymetry, geological ages, climate, runoff and
aging do not drive terrain.
Recreating a project starts from the current world inputs; existing terrain
instructions are not automatically rebased onto changed geography. The produced
GeoTIFF remains in the existing local coordinate system; its world projection is
retained in the source SVG, not encoded as a global raster CRS.

## Import your own source

1. Export a UTF-8 SVG with explicit vector shapes and a numeric `viewBox` from
   your drawing application. Native Affinity documents and raster maps are not
   accepted. Exporting a copy leaves your drawing document untouched.
2. In **World**, choose **Import SVG map…**. The original SVG text, element IDs,
   transforms and group hierarchy are retained in an embedded snapshot. Import
   does not move geometry or infer planet size from display pixels.
3. Review the shape list. **Suggest from SVG groups** proposes continent names and
   ownership; it is an explicit, undoable action. It recognises `Land Shapes`,
   `islands` and `Map Furniture`. Affinity's original layer labels take precedence
   over generated IDs such as `Land-Shapes1`; anonymous transform wrappers do not
   become continent names. The group above `Land Shapes` owns its shapes. When
   land layers exist, other thematic layers are proposed as excluded. The summary
   reports exclusions explicitly. Inspect all proposals before accepting them.
4. Select shapes in the list or click the map. Use Ctrl-click or the list's
   extended selection for several shapes. Choose a **Continent** or type a new
   name, choose **Mainland** or **Island**, then **Assign**; **Exclude** keeps a
   shape out of the world. Every source shape needs one assignment or explicit
   exclusion: **Next** selects any that are left. Ungrouped or invalid shapes are
   not guessed into a continent.
5. In the **Planet** step, set the planet radius. It starts at Earth's 6,371 km;
   **Earth**, **Mars** and **Large** fill in common sizes. The line below says how
   many km one SVG unit is, and warns when the map edges are not twice as wide as
   tall. **Map edges** holds the exact projection bounds. The SVG `viewBox`
   supplies them as a suggestion, not proof of the frame: remove page margins,
   legends and scale bars from the geographic rectangle. The section opens by
   itself when the suggestion is not 2:1. Under **Coast detail · advanced**,
   leave **Coast detail already drawn** blank for a hand-drawn map. For a map
   that already carries refined coast detail, such as one exported from a
   planet's refined coast, enter the finest detail it carries in km (a
   `map-maker world refine-coast` export fills it in), so zoomed maps add only finer
   detail.
6. Click **Next** (or **Check now**). Tiny export overflow and narrow border
   overlaps are handled in derived coverage, and shared land within one continent
   is counted once. The **World check** lists continent areas and any import
   adjustments; selecting one highlights its original source shapes. Larger
   cross-continent conflicts, invalid shapes, unassigned objects and substantial
   out-of-frame land still require correction; the check then returns to the
   Source map step with those shapes selected.
7. **Save As** a `.world.json` file. Reopen it to review the same source and
   membership. Save rechecks the original snapshot and geometry before replacing
   an existing file atomically. Failed validation leaves the existing file intact.

For the public raw SVG, the world frame is left **10**, top **10**, width **360**,
height **180**, radius **6500 km**, longitude at the map's centre **0°**. The full page is
380 by 210 source units, with furniture outside the world frame. These values
are specific to the example; use your own map's established scale and projection.
The seam island's group suggestion initially uses Mainland; select `seam-island`
and assign **Island** to match the saved example's intended role.

A continent is a semantic owner. It can have multiple land pieces and can touch
another continent. Islands keep their chosen owner, not their nearest mainland.
**Rename continent…** preserves its ID and all membership. Assigning a
continent's last shape elsewhere removes that now-unused owner; Undo can restore it.

## Navigation and document handling

- Mouse wheel zooms around the pointer. Drag (any button) pans; a click without
  dragging selects. **Fit** or
  **F** restores the overview. Zoom inspects retained source geometry; it does
  not generate higher-resolution terrain.
- The pointer readout shows longitude/latitude once frame and radius are valid;
  before that it reports source positions. Grid lines show the declared sphere.
- Colours distinguish continent owners; selected outlines are gold, unassigned
  shapes grey and excluded shapes muted. Colours are reproducible for a given
  owner set, but may change when that set changes. IDs carry identity.
- Selecting a shape shows its source group path, exact ID and any import issue.
  Import problems are marked **Needs attention**, counted in the summary and
  selected after import. Validation selects out-of-frame or overlapping shapes
  and reports their group paths, IDs and bounds/overlap areas. A successful check,
  opening and saving fill the **World check** with bounded preparation changes.
  Editing inputs clears that report until the next check. **Show excluded shapes
  on the map** affects only the preview, never assignments or validation.
- **Ctrl+O**, **Ctrl+S**, **Ctrl+Shift+S**, **Ctrl+Z**, **Ctrl+Y**, **F** and
  **Ctrl+Enter** act on the active workspace. In World, Ctrl+Enter runs the open
  step's main action (**Next**, **Generate planet** or **Generate context**). In
  the Geology step, Ctrl+S saves and Ctrl+Z/Ctrl+Y undo and redo the geology recipe
  instead of the world. Native editing shortcuts still apply inside text fields.
- Ownership assignments and renames have Undo/Redo. Frame text uses normal text
  editing; it is not part of the ownership undo stack.
- Open/import/close guard unsaved changes. Both documents are checked on exit.
  Saving an incomplete world requires resolving its assignments/frame first;
  there is no partial-draft file format in this batch.
- Import, open, validation and saving use a background worker. Input controls
  lock during a job; wait for it to finish before closing. Long jobs (context,
  planet, regions, geology checks) show progress and **Cancel** in the status bar;
  import, open, check and save are short and cannot be cancelled.

## Geographic and source contract

The first supported projection is a **full-world spherical Plate Carrée** frame:
left/right span 360° and top/bottom span +90° to -90°. Radius is explicit in km;
central meridian is in [-180°, 180°). Other projections and partial-world sources
are unsupported. A rectangle's aspect ratio alone cannot establish its projection.
Custom planets are not labelled with an Earth EPSG code.

Longitude is periodic. A seam-crossing shape must use locally continuous source
coordinates, such as x=350..370 for a 0..360 frame, or be split into separate
source shapes assigned to the same continent. A path jumping directly from
x=359 to x=1 means a long source-space segment; the importer cannot infer that
you intended a short seam crossing. Polar vertices are supported and latitude
limits are checked; there is no polar climate or terrain solver here.

Original SVG text is authoritative and retained byte-for-byte through UTF-8
encoding, with a SHA-256 identity. Inspection geometry is separately flattened
at `max(viewBox width, height) / 32768` source units. Curved boundaries and derived
areas therefore have sampling error. Compound even-odd and nonzero fill rules,
holes, self-intersections, retraced edges and transforms are respected. The
importer nodes sampled linework and classifies its faces using the original
segments' winding numbers. This interprets SVG fill semantics; it does not heal
coastlines. Tiny gaps and holes are not repaired away.
The existing local terrain importer has a different dissolve/repair contract.

Derived coverage is wrapped and clipped at the declared longitude frame. The
preview continues to show the retained source, with selected shapes highlighted;
it is not a view of edited SVG paths. Source coordinates never change. Surface
areas integrate the prepared source-linear boundary on the declared sphere;
they are neither flat-page areas nor geodesic-chord polygon areas.

Preparation handles three cases and reports every affected shape:

- **Rounded world edge:** north/south overflow no greater than 0.001% of the
  shorter frame dimension is clipped in derived coverage. This tolerance scales
  with source units. The projection frame is never enlarged. Entirely outside
  shapes and larger overflow remain errors.
- **Shared land within one continent:** overlapping or contained filled shapes
  contribute their union once. Every original ID, role and ownership assignment
  remains present; a completely redundant shape has no independent prepared area.
  It is not changed to Exclude.
- **Narrow continent-border overlap:** shared coverage must lie within the same
  linear tolerance of both shape boundaries and occupy at most 0.01% of each
  shape's area. The union of all foreign overlaps must also fit that per-shape
  area budget. A tiny island inside a different continent and a small deep overlap
  therefore remain ownership conflicts.

Shared coverage goes to mainland before islands, then to the larger prepared
footprint, then to the stable feature ID to break a tie. This yields disjoint
coverage without losing the land union or double-counting spherical area.
Touching continents retain separate owners. Gaps and holes are not filled.
The report gives affected source IDs, group paths and shared/trimmed planar area
in square source units. These values are diagnostics, not physical square km.
See [ADR-0072](adr/0072-bound-world-source-imperfections.md) for the policy.

The source importer accepts at most 8 MiB, 30,000 XML elements, 4,096 shapes and
500,000 retained inspection points. These are input limits, not an OS memory
ceiling. SVG `use`, embedded/external images, nested SVG, scripts and foreign
objects must be exported to explicit paths first. Clipped/masked or open shapes
are visible import issues and must be fixed in the source or explicitly excluded.
Text is retained in the original SVG but is not treated as land. Ordinary SVG
`DOCTYPE` headers import automatically, including public/system declarations;
no DTD is downloaded or loaded from disk. The original header remains embedded
in the source snapshot. Internal DTD subsets and custom entity references are
rejected. Duplicate element IDs and indistinguishable anonymous shapes also
fail import. Give important shapes stable unique SVG IDs.

Both current Affinity (`https://www.affinity.studio/`) and Serif
(`http://www.serif.com/`) layer labels are recognised, along with Inkscape labels.
For precision-sensitive coastlines, export with more decimal places and flattened
transforms when available; rounded transform coefficients can displace a polar
edge or turn a shared border into a tiny overlap. Higher export precision cannot
remove genuine duplicate/overlapping shapes. The bounded preparation above handles
minor discrepancies automatically and reports them. For conflicts beyond its
limits, inspect the reported IDs and correct the source or ownership. Do not
enlarge the established world frame or rescale a continent to bypass validation.

The [world project schema](../schemas/world/project-v1.schema.json) owns current
serialized fields. Its `retained-svg-v2` importer identity records how inspection
geometry is reconstructed; `preparation: bounded-world-v1` identifies the derived
coverage rules. Reports and prepared geometry are recomputed from the retained
source and assignments on opening, validation and saving. Saved world files are
bounded to 32 MiB. Unsupported identities, projections and unknown fields fail
rather than fall back to a guessed format. Previous world snapshots must be
reimported from their original SVG; they are not migrated. This project has no
legacy-save compatibility policy. [ADR-0071](adr/0071-interpret-exported-svg-fills.md)
and [ADR-0072](adr/0072-bound-world-source-imperfections.md) record these identities.

## What follows

The [Context page](world-context.md) now implements spherical coverage, connected
water, shared-edge openings, shoreline distance, directional exposure, resolution
support and verified bundle reopening. The **Geology** step holds the
[geology inputs](world-geology.md): continent defaults, drawable provinces and
landmarks over source/context backgrounds, saved as their own recipe. The
**Ocean floor** tool opens the separate [ocean-depth workflow](world-bathymetry.md)
from matching geographic context: select oceans, author a margin profile, generate
and inspect depth/error/support, then export or reopen a verified result.
The [WC1](strategy/world-context.md) graph now retains separate water pieces and
finite shared intervals in full context bundles. M1 retains sampled water labels
and support flags, but does not transfer or solve that graph. Physical transport and geological
process forcing remain planned while preserving this source contract.
Accepted/wider world terrain, climate, shared history, world-linked regional generation and
local river enrichment require their own stage gates. Existing local terrain
builds remain in local metric coordinates; saving a world does not georeference
their DEMs or add climate fields to them. See [coordinates](terrain-coordinates.md),
[architecture](architecture/README.md) and [ADR-0070](adr/0070-retain-world-source-and-workspaces.md).
