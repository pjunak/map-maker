# Authored world geology

The World workspace's **Geology** step holds the pre-generation instructions
for a world. It resolves continent defaults and explicit provinces into
inspectable land coverage. The planet turns each region's setting, ages and
landform into soft height targets and rock hardness ([planet guide](world-planet.md)).
Explicit landform controls also transfer into ordinary terrain projects through the
**Local terrain** tool or `world terrain --geology`. These are procedural generation
instructions, not reconstructed Earth history.

The step is optional: without a recipe, mountain ranges are placed automatically.

## Try it

1. Open a saved world, or import one and assign its continents.
2. Open the **Geology** step and click **Create a geology recipe** (or **Open a
   recipe…**). The step's map replaces the world map while it is open.
3. Select a continent default. Choose its **Geological setting**; the line below it
   says what the setting means, and the key under **Regions** gives its map
   colour. **Automatic** leaves the region to the generator. **Crust age** and
   **Time since uplift** are in million years; blank means unknown. Crust older
   than 1,000 million years erodes more slowly, and older uplift leaves lower,
   smoother ranges. **Apply changes** validates the complete coverage.
   Under **Exact landform (optional)**, choose plain, hills, plateau or mountains
   to set heights directly instead of the setting's usual ones. **Use starting
   values** fills editable base height, relief, feature size, transition and
   direction. **Use background terrain** leaves this region to the setting.
4. Choose **Draw province**, click at least three corners, enter a name and
   priority, then **Apply changes** or press Enter on the map.
   Backspace removes the last corner; Escape or **Revert** discards the draft.
5. Review **Geology coverage** colours, effective land area and numeric hover.
   Use **Source** or an available geographic context layer as the background.
   **Look** selects the direction for exposure/support backgrounds. The
   Geographic context page owns their numeric scales and geographic limitations.
6. **Save** a separate **`.geology.json`** recipe. **Open…** restores one against
   the currently open world.
7. **Next** goes to the Generate step, which uses the recipe as it stands in this
   step, saved or not. An edit that is not applied yet stops generation with a
   message rather than being left out. **Remove geology** goes back to automatic
   ranges.
8. The **Local terrain** tool uses the same recipe. In the Terrain workspace,
   transferred landforms are ordinary editable instructions; editing them and
   generating again leaves the world recipe and earlier output unchanged.

Editing the world after making geology (renaming it, changing its radius or
frame, or reassigning shapes) does not lose the recipe: when you return to the
Geology step it follows the edited world. Continent defaults stay with their
continents, new continents start Automatic, and provinces and landmarks stay where
they were drawn on the map. Save the recipe again to keep that version; the file
on disk still names the world it was saved with. A recipe drawn on another source
map is closed when that map is imported.

To use the synthetic example, open
[`four-shores.world.json`](../examples/world/four-shores.world.json), choose
**Geology → Open a recipe…**, and open
[`four-shores.geology.json`](../examples/world/four-shores.geology.json).
Use Save As for experiments. It has an active belt crossing two continent labels
and a rift crossing the longitude seam; its old-crust/young-rejuvenation values
are invented examples, not defaults for another world.

```powershell
map-maker terrain gui --world examples/world/four-shores.world.json
map-maker world inspect-geology examples/world/four-shores.geology.json
```

Use the tree or click resolved land to select a region. **Redraw outline** replaces
a province boundary after validation; **Delete** removes it. Defaults cannot be
deleted, and continent names/ownership are edited in the Source map step.
Twenty accepted edits are retained for Undo/Redo during a session. Apply or revert
an unfinished edit before changing selection or using history. Zoom and pan move
the view, not the authored geometry. There is no output sculpting.

## Try a complete landform example

Open [landform-world.world.json](../examples/world/landform-world.world.json),
then load [landform-world.geology.json](../examples/world/landform-world.geology.json)
in the **Geology** step. It contains two contiguous continent labels, plain defaults,
a western mountain belt, an eastern plateau and a higher-priority lowland inside
the plateau. The geometry is deliberately simple so its guidance can be inspected.

```powershell
map-maker world terrain examples/world/landform-world.world.json --continent Westreach --geology examples/world/landform-world.geology.json --output artifacts/landform-demo
map-maker terrain gui --project artifacts/landform-demo/terrain.terrain.json
```

The command creates a project; **Generate terrain** produces its preview. Choose
a fresh output folder for another transfer. Source, projected scale and physical
land are identical with or without the optional recipe.

## Place wonders by hand

**Landmarks**, at the foot of the Geology step, places [wonders](wonders.md) where
you want them. Choose a kind; the text below describes it and its size range.
Optionally give a name and a size in km (a diameter, a width or a height,
depending on the kind; blank uses the usual size). An **Age** in million years
erodes craters, chasms, cliffs and tepuis ([wonder guide](wonders.md#age)); blank
uses the planet's.
Click **Place on map**, then a point on land. Wonders placed by their two
ends, such as a chasm, take a second click for the other end. Select a landmark
in the tree to rename, resize (**Update**) or **Delete** it. Undo and redo cover
landmarks too.

When the planet is generated with this recipe, placed wonders replace the random
wonders of their kind. The planet reports an error if a landmark, or either end
of a two-ended one, lies at sea. Landmarks are saved in the recipe's optional
`landmarks` list, each with `kind`, `position`, `size_km`, an optional
`age_myr` and, for two-ended wonders, `end` ([schema](../schemas/world/geology-v2.schema.json)). Recipes
without landmarks still open.

## Values and overlap rules

- `setting`: unspecified, stable-interior, active-belt, rift, volcanic, or
  sedimentary-basin. These categorical hypotheses carry no implicit physical coefficients.
- `crust_age_ma`: optional age of the crust, in million years before the common present.
- `rejuvenation_age_ma`: optional time since uplift/rejuvenation, in the same units.
- `evolution_duration_ma`: optional requested simulation duration ending at that
  common present. It is not a crust age, an instruction to run a solver now, or
  permission to advance a refined region beyond its parent present.

Each age/duration value is finite and in 0–1,000,000 Ma, or null/blank. This broad
admission bound is not geological calibration. Zero is distinct from unknown.
The fields are independent: old crust may carry recent rejuvenation. No
age-to-erodibility conversion, lithology or epoch schedule is inferred.
Explicit `landform` controls use the existing [regional terrain recipe](terrain-regions.md):
nonnegative base/relief in metres, positive feature/transition lengths in kilometres,
and direction from 0 up to 180 degrees in the resulting local projected plane
(0 east-west, 90 north-south). These are artistic physical-unit controls, not
geological coefficients. Selecting a setting or changing an age never creates
landform guidance automatically.

Each continent has one complete default profile. A province overrides that
**entire profile**, including unspecified settings, blank ages and background-only
landforms. Higher
integer priority wins (0–100). Equal-priority provinces that compete for the
same effective land are rejected with their names. Boundary-only contact is
allowed; exact shared-edge inspection uses stable IDs. A higher-priority
province may mask a lower-priority conflict; removing that mask must resolve
without ambiguity or the deletion is rejected. Ocean-only overlap is harmless.

Province boundaries are independent of continent labels. Authored footprints
can include water, but only their intersection with prepared land receives
geology. A fully masked or ocean-only province is retained and reports zero
square kilometres; it is not silently deleted. The resolved regions cover all
prepared land exactly once, including existing source preparation adjustments.
Areas use the declared custom sphere, not pixel counts.

## Coordinates and limits

A province is a simple source-linear polygon with 3–256 distinct vertices,
without a repeated closing point or holes. Each edge, including closure, spans
at most half a world width in longitude; use intermediate vertices for longer
boundaries. The first vertex is inside the declared longitude frame. Subsequent
x coordinates may be unwrapped by one world width to cross its seam; the whole
ring spans at most one world width. Latitudes remain inside the world frame.
The editor unwraps each click to the nearest previous longitude. The closing
edge is checked rather than guessed; an unsupported winding must be redrawn.
Self-intersections and degenerate polygons fail without geometric repair.

There are at most 128 provinces. Coverage is a hard categorical partition.
Its boundary is **not** an elevation discontinuity or a physical forcing taper.
The terrain handoff resolves this partition first, merges equal landform controls
across ownership/age boundaries, then projects its pieces through the exact same
bounded projection as the coast. Priority cutouts become terrain-region holes.
Adjacent recipes now blend through their shared boundary; only the outside of
connected assigned coverage fades toward generic background. Blank overrides
stay background, and established enclave interiors retain their own guidance.
This is procedural composition, not calibrated geological forcing; large height
contrasts can still form steep polygon-shaped slopes. See the
[blending evidence](research/2026-09-27-shared-landform-blending.md).
Vertex dragging, multipart/holed provinces, polar winding conventions and
per-field inheritance are follow-ups. An open recipe follows edits of its own world
(see [Try it](#try-it)); opening a file still requires its exact world.

## Persistence and cancellation

The [current v2 schema](../schemas/world/geology-v2.schema.json) embeds the
retained world and a canonical SHA-256 identity of its entire source document:
SVG bytes, importer/preparation, frame/radius/meridian, names and assignments.
A different world is rejected, even if it reuses the same SVG. Reordered world
records have the same identity. Geographic context v4 and world-source v1 remain
separate formats; no generated bundle is modified when saving geology.

A prepared terrain source v2 embeds the chosen recipe and
`explicit-geology-landforms@1` transfer identity. The projected coast is unchanged.
Later edits to ordinary terrain-region inputs intentionally do not rewrite that
original recipe snapshot. Terrain project v7 adds hole rings to those regions.
Old geology/terrain/prepared-source formats are rejected; no migration is provided.
World source projects keep their current format.

Recipes are limited to 40 MiB; their embedded world still has its 32 MiB limit.
Unknown fields, duplicate JSON keys and unsupported versions fail. Saving
validates geometry and retained source, writes a temporary sibling, flushes it,
then replaces the target. A loaded file's byte hash is checked before replacement;
an external edit or deletion requires reopening or Save As to another path.
This guard is not a cross-process filesystem lock.

Coverage/open jobs run off the Tk thread and support cooperative cancellation
between bounded geometry operations; an individual GEOS call or SVG parse is
not interruptible. Cancellation/failure retains applied inputs and the current
form/draft. Geology jobs share the World workspace's status bar and its one job at a
time. Atomic saves finish before closing. Closing or replacing world input
also checks the recipe's unsaved work. Save applies a valid pending edit first;
invalid input cannot disappear through a Save confirmation.

See [ADR-0080](adr/0080-transfer-geological-landform-guidance.md),
[landform transfer evidence](research/2026-09-27-geological-landform-guidance.md),
[ADR-0076](adr/0076-author-world-geology-inputs.md),
[validation evidence](research/2026-09-25-authored-world-geology.md), and the
[WC0–WC6 plan](strategy/world-context.md) for the remaining generation work.
