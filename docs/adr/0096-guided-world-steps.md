# ADR-0096: Guide world creation through numbered steps, with geology in the main window

- Status: accepted (experimental product path)
- Date: 2026-10-13
- Refines: [ADR-0089](0089-one-map-view-with-drill-down-levels.md) (the geology editor's
  separate window) and [ADR-0070](0070-retain-world-source-and-workspaces.md) (World
  workspace stages)

## Context

The World workspace grew stage by stage. Its left side had six tabs in the order
they were built, not the order of use: Shapes, Frame, an unnumbered Adjustments
tab, Context, Planet and Terrain. A **Validate world** button sat below all of
them. **Geology…** and **Bathymetry…** opened modal windows with their own map,
status bar and job runner. The Planet tab chose a geology recipe by file, so a
recipe had to be saved, and any later world edit (even a rename) made it belong
to "a different world" with no way to carry it over. Geographic context sat in
the main path although the planet does not use it. Fields were raw entries with
terse labels; the planet radius started blank.

## Decision

1. **Five numbered steps** in the order of use, each with a status line, run down
   the left: **Source map** (import, continents), **Planet** (name, radius, map
   edges, coast detail), **Geology** (optional), **Generate** and **Explore**.
   Every page has **Back** and **Next** in a footer that stays in view. **Next**
   from Planet checks the world; its result and any import adjustments show in the
   page, so the Adjustments tab and the Validate button go. Steps that cannot be
   used yet are disabled (Explore until a planet exists).
2. **More tools** follow the steps, unnumbered: **Geographic context**, **Ocean
   floor** (the bathymetry window; it generates missing context itself) and
   **Local terrain**.
3. **Geology is a step, not a window.** Its sidebar is the step page and its map
   replaces the world map while the step is open. It runs on the workspace's job
   runner, so there is one status bar and one job at a time (`JobRunner.start`
   takes per-job failure and cancel handlers for this).
4. **Generation uses the recipe in the step**, saved or not:
   `generate_planet_run` and `create_world_terrain_project` take a
   `WorldGeologyRecipe` instead of a path; the CLI reads files. An unapplied geology
   edit stops generation with a message rather than being left out.
5. **A recipe follows edits of its own world** (`domain.world_geology.follow_world`):
   continent defaults follow their continents by identity, new continents start
   unspecified, and provinces and landmarks stay in source coordinates. It applies
   only to the same source drawing; opening a recipe file still requires its exact
   world.
6. **Defaults and meanings.** The radius starts at Earth's 6,371 km with presets,
   and a live line gives km per SVG unit and warns when the map edges are not 2:1.
   Map edges and coast detail are collapsed sections (edges open themselves when the
   suggestion is not 2:1). Each field states its unit and meaning in a line below
   it. Detail presets give spacing and rough time; geological settings have names
   and one-line meanings (`SETTING_TEXT`). Shared widgets for this live in
   `ui_components.py`: `StepRail`, `ScrollPage`, `Collapsible`, `ChoiceList` and
   `field`.

## Consequences

- The steps match the world-first product path (ADR-0085): source, planet, optional
  geology, generation, exploration. Legacy and diagnostic tools stay available but
  out of the main path.
- A planet build's geology identity is the canonical hash of the recipe used, as
  before; an unsaved recipe can therefore produce a build whose recipe exists only
  in memory, like an unsaved world. Save both to reproduce a build.
- Save, undo and redo shortcuts act on the geology recipe while its step is open.
- The ocean-floor editor stays a separate window: it edits its own document and is
  not on the planet path.
- The Terrain workspace (the local composed generator) is unchanged; its future is
  M5's decision.
