# ADR-0089: Show every world map in one view with drill-down levels

- Status: accepted (experimental product path)
- Date: 2026-10-11
- Refines: [ADR-0087](0087-map-themes-and-projections.md) (its separate globe window); shows the levels of [ADR-0088](0088-nested-regional-detail-levels.md)

## Context

The World workspace showed planet maps in three places:

- the flat map, with one selector mixing source, context and planet layers;
- a globe-and-polar window;
- a new window for every regional zoom.

Generation, globe frames, regional rendering and the hover search tree ran on the
Tk thread, so the app froze for 0.2–2 s on common actions. Nested detail levels
(region → province → local, ADR-0088) needed a place in the app.

## Decision

1. **One map view** (`world_view.py`) shows everything. Three controls choose what it
   shows:
   - **data**: Source, Context or Planet;
   - **map**: the registry themes a build rendered, listed with no per-theme code;
   - **projection**: flat world, globe or polar, from `map_projection.PROJECTIONS`.

   The legend and the readout under the cursor sit below the map.
2. **Drill-down levels.** *Zoom to region* picks a point on the world map, and
   *Zoom to province* and *Zoom to local* pick one on the level above. Each opens in
   the same view as a deeper level. A breadcrumb (World / Region / Province /
   Local) leads back, and each larger map outlines the smaller ones.

   A level holds:
   - its run;
   - the themes it can show (`application/region_views.py`);
   - its rendered images;
   - its own pan and zoom.

3. **No heavy work on the Tk thread** (`ui_jobs.py`):
   - Long jobs (generate, export, open, region) run one at a time, with progress
     and Cancel in the status bar. Only a successful job installs its result.
   - Globe frames and regional themes render in a latest-wins worker. Dragging
     shows quick low-resolution frames.
   - The flat map draws from an image pyramid.
4. **Shared presentation.** Colours, fonts and ttk styles live in `ui_style.py`.
   Reusable widgets live in `ui_components.py` and `map_canvas.py`.

## Consequences

- A new theme appears in the app once a build renders it, with no UI changes.
- Hover on globe and polar views uses `map_projection.displayed_lonlat`, the
  pixel positions exactly as `reproject` draws them.
- Detail levels offer only the themes `region_views` can render: atlas and
  parchment (with climate), relief and topographic. Other themes stay world-level
  until they render from shared map fields.
- The geology and bathymetry editors stay separate windows (they edit their own
  documents) but use the same map canvas, legend and readout strip, job runner and
  status bar.
