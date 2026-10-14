# ADR-0011: Separate cartographic and scientific elevation styles

**Status:** Accepted
**Date:** 2026-09-03
**Deciders:** Repository owner and project maintainer

## Context

ADR-0010 made the scientifically ordered `oleron` land sequence the default
colour relief. It solved the ambiguous repeated browns in the original ramp,
but its steady dark-green-to-pale progression produces a restrained analytical
view rather than the expressive shaded-relief maps preferred for everyday
worldbuilding.

The chosen visual reference uses a different grammar: saturated green
lowlands, a short yellow-green transition, ochre and brown uplands, dark rocky
mountains, pale highest summits, and much stronger relief shading. This style is
easy to read cartographically, but its middle-range lightness reversals mean it
should not replace the ordered scientific view for numerical inspection.

## Decision

- Provide two switchable rendering styles in the preview toolbar:
  `Cartographic relief` and `Scientific elevation`.
- Make `Cartographic relief` the everyday default. Use an original Map Maker
  hypsometric ramp with green lowlands, yellow transition terrain, brown
  uplands, dark high mountains, and pale highest summits.
- Apply stronger render-only vertical exaggeration and hillshade contrast to
  the cartographic style. Do not modify the elevation array or generation
  settings to obtain the visual effect.
- Preserve the complete Oleron land sequence and subtle hillshade as the
  `Scientific elevation` style.
- Re-render an existing DEM immediately when the style selector changes. Both
  the legend and exported PNG must follow the selected style.
- Record the render style and palette identifier in PNG metadata.
- Keep render style out of version-1 terrain projects. It is a derived display
  choice, not authored geography or an input to the authoritative DEM.

This supersedes ADR-0010 only where it selected Oleron as the everyday default.
Its scientific-palette research, attribution, and accessibility rationale
remain applicable to the scientific inspection style.

## Consequences

- The default preview more closely resembles a traditional illustrated relief
  map without copying the reference artwork or its data.
- The palette alone cannot create the reference's drainage texture, ridge
  structure, or river overlay. Those depend on higher-resolution terrain,
  erosion and hydrology stages, and separate vector products.
- The cartographic style is intentionally not perceptually uniform. Users can
  switch to the ordered scientific style when comparing numeric elevation.
- Stronger hillshade can visually exaggerate steepness. It is explicitly a
  render parameter and never changes metre values.
- A later preference store may remember the last selected style without adding
  it to the authored terrain-project schema.

## Validation

- Palette tests verify green, brown, dark-rock, and pale-summit anchors.
- Scientific-palette tests continue to verify strictly increasing relative
  luminance.
- Tests cover high-to-low legends and render-style/palette PNG metadata.
- Both styles are visually checked on the same generated Tharkeniss DEM so
  differences are isolated to rendering.
