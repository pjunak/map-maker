# Authored world geology

The World workspace now has a **Geology…** editor for pre-generation instructions.
It resolves continent defaults and explicit provinces into inspectable land
coverage. Optional explicit landform controls now transfer into ordinary terrain
projects through the World workspace's **Terrain** stage or `world terrain --geology`. These are
procedural generation instructions, not reconstructed Earth history or implemented
uplift, erosion, climate or a reviewed global terrain parent.

## Try it

1. Open a saved world, or import and validate its source/frame/assignments.
2. Choose **Geology…**. The world stays fixed while this editor is open.
3. Select a continent default. Choose a geological setting and optional ages;
   **Apply** validates the complete coverage. Blank ages mean unknown.
   In **Landform guidance**, choose plain, hills, plateau or mountains. **Use starting
   values** fills editable base height, relief, feature size, transition and direction.
   **Use background terrain** explicitly leaves this region to normal generation.
4. Choose **Draw province**, click at least three vertices, enter a name and
   priority, then **Apply / finish polygon** or press Enter on the map.
   Backspace removes the last vertex; Escape or **Revert / cancel** discards the draft.
5. Review **Geology coverage** colours, effective land area and numeric hover.
   Use **Source** or an available geographic context layer as the background.
   **Look** selects the direction for exposure/support backgrounds. The original
   Context page owns their numeric scales and geographic limitations.
6. Save a separate **`.dmgeology.json`** recipe. **Open recipe…** restores it against
   the currently open world. The editor remembers the last saved recipe during
   the application session and rechecks its file when reopened.
7. Close the geology editor and open the **5 Terrain** stage. Its recipe selection shows the
   saved file; **Choose geology recipe…** can select another and **Clear** disables it.
   Creation rereads and validates the file against the current world.
8. Generate in the Terrain workspace. Transferred landforms are ordinary editable
   instructions; editing them and generating again leaves the saved world recipe
   and earlier output unchanged.

To use the synthetic example, open
[`four-shores.dmworld.json`](../examples/world/four-shores.dmworld.json), choose
**Geology… → Open recipe…**, and open
[`four-shores.dmgeology.json`](../examples/world/four-shores.dmgeology.json).
Use Save As for experiments. It has an active belt crossing two continent labels
and a rift crossing the longitude seam; its old-crust/young-rejuvenation values
are invented examples, not defaults for another world.

```powershell
dmtools terrain gui --world examples/world/four-shores.dmworld.json
dmtools world inspect-geology examples/world/four-shores.dmgeology.json
```

Use the tree or click resolved land to select a region. **Redraw** replaces a
province boundary after validation; **Delete** removes it. Defaults cannot be
deleted, and continent names/ownership are edited in the World workspace.
Twenty accepted edits are retained for Undo/Redo during a session. Apply or revert
an unfinished edit before changing selection or using history. Zoom and pan move
the view, not the authored geometry. There is no output sculpting.

## Try a complete landform example

Open [landform-world.dmworld.json](../examples/world/landform-world.dmworld.json),
then load [landform-world.dmgeology.json](../examples/world/landform-world.dmgeology.json)
in **Geology…**. It contains two contiguous continent labels, plain defaults,
a western mountain belt, an eastern plateau and a higher-priority lowland inside
the plateau. The geometry is deliberately simple so its guidance can be inspected.

```powershell
dmtools world terrain examples/world/landform-world.dmworld.json --continent Westreach --geology examples/world/landform-world.dmgeology.json --output artifacts/landform-demo
dmtools terrain gui --project artifacts/landform-demo/terrain.dmterrain.json
```

The command creates a project; **Generate terrain** produces its preview. Choose
a fresh output folder for another transfer. Source, projected scale and physical
land are identical with or without the optional recipe.

## Place wonders by hand

The **Landmarks** tab places [wonders](wonders.md) where you want them. Choose a
kind; the tab describes it and its size range. Optionally give a name and a size
(a diameter, a width or a height, depending on the kind; blank uses the usual
size). An age (**Age Myr**) erodes craters, chasms, cliffs and tepuis ([wonder guide](wonders.md#age)); blank uses the planet's.
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
Vertex dragging, multipart/holed provinces, polar winding
conventions, per-field inheritance and rebasing to an edited world are follow-ups.

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
form/draft. Atomic saves finish before closing. Closing or replacing world input
also checks this editor's unsaved work. Save applies a valid pending edit first;
invalid input cannot disappear through a Save confirmation.

See [ADR-0080](adr/0080-transfer-geological-landform-guidance.md),
[landform transfer evidence](research/2026-09-27-geological-landform-guidance.md),
[ADR-0076](adr/0076-author-world-geology-inputs.md),
[validation evidence](research/2026-09-25-authored-world-geology.md), and the
[WC0–WC6 plan](strategy/world-context.md) for the remaining generation work.
