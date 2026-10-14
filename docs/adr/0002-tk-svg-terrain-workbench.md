# ADR-0002: Build the first terrain workbench with Tk and SVG input

**Status:** Accepted; single-object SVG restriction superseded by ADR-0009
**Date:** 2026-09-02
**Deciders:** Repository owner and project maintainer

## Context

The terrain engine needs a usable local vertical slice before its full project
schema, GIS output stack, and process-informed terrain stages are settled. The
first interface must let the user tune every implemented value, see progress,
inspect a result, and export it. It must also preserve the engine's future use
from a CLI or hosted interface.

The first authored input is one continuous closed coastline. Affinity and most
vector editors can export that geometry as SVG without requiring a heavy GIS
application or a proprietary document parser.

## Decision

- Use Python's bundled Tk/ttk for the first desktop interface.
- Launch it through `map-maker terrain gui`; keep UI state and widgets outside the
  terrain domain and pipeline.
- Accept SVG files containing exactly one valid closed drawable object.
- Define object scale as the longest SVG bounding-box dimension in kilometres.
- Flatten SVG curves deterministically, then validate the resulting polygon.
- Generate a coordinate-addressed Float32 raster with NumPy and Shapely.
- Render and export a transparent colour-relief PNG with Pillow.
- Keep the numeric elevation grid authoritative in memory. Treat the PNG as a
  visual preview, not a DEM interchange format.
- Run generation outside the Tk event loop and report stage progress through a
  queue.

## Options considered

### Tk/ttk desktop workbench

It is bundled with the chosen Python distribution, has native file dialogs and
accessible controls, and keeps the first slice entirely local. Its visual and
web-deployment options are more limited than a browser interface.

### CustomTkinter

It offers more themed widgets but adds a nonessential UI dependency and does
not improve the engine or future hosted boundary.

### Local web application

It would more closely resemble a future hosted product, but requires a server,
browser lifecycle, API contract, and frontend toolchain before the numerical
workflow has been validated.

### GIS desktop integration

QGIS or another GIS application will eventually be valuable for inspecting
GeoTIFFs and vector constraints. Making it the first UI would impose much more
environment and plugin complexity than the single-coastline workflow needs.

## Consequences

- The tool is immediately usable on the supported Windows Python 3.14 runtime.
- UI concerns do not enter the deterministic generator.
- SVG is an authoring interchange format, not yet a complete terrain-project
  format.
- The first PNG export cannot substitute for a georeferenced Float32 DEM.
- Holes, islands, spot heights, regional refinement, and scientific terrain
  processes remain explicit follow-up work.
- The coordinate-addressed generator can be sampled at nested resolutions and
  in future regional windows without changing values at shared coordinates.

## Validation

- Closed, open, multi-object, and self-intersecting SVG fixtures cover the
  import contract.
- Deterministic, changed-seed, nested-resolution, query-order, alpha-mask, and
  PNG-metadata tests cover the first pipeline.
- Tk 9 was verified in the repository's CPython 3.14.7 environment.
