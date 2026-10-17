# ADR-0101: Draw globe views with a compiled, mip-mapped sampler and turn them by grabbing the ground

- Status: accepted (experimental product path)
- Date: 2026-10-17
- Refines: [ADR-0087](0087-map-themes-and-projections.md) (map themes and
  projections). Themes are still rendered once on the world frame.
- Replaces the globe hover of [ADR-0089](0089-one-map-view-with-drill-down-levels.md),
  which looked positions up in per-pixel arrays (`displayed_lonlat`).

## Context

The app's globe resampled the world-frame theme image with SciPy for every frame.
A sharp 900-pixel frame took about 0.4 s, so dragging showed blurry
low-resolution frames and a sharp one only after release. The globe had a fixed
size: it could not zoom, it filled only a square in the middle of the window, and
it did not show the opened regions or the region about to be picked. Dragging
moved the centre a fixed angle per pixel, so the ground slid under the cursor,
especially near a pole.

Bilinear sampling also aliased. A 4,096-pixel theme image shown as a 900-pixel
globe is minified about 2:1 at the centre and much more towards the limb, so
coasts shimmered while turning. An equirectangular image is also anisotropic: at
latitude φ a pixel is `cos φ` as wide on the ground as it is high, so filtering
by image pixels blurs polar regions or aliases them.

The user asked for a full interactive globe view, with a sound representation and
mathematics and without unwanted complexity.

## Decision

1. **The texture stays the world-frame image.** The theme PNGs of a build, or
   the app's drawn themes, are the globe's only source. A `MapTexture` prepares
   one in about 0.1 s:
   - **Latitude prefilter.** Each row is box-averaged east-west over `1/cos φ`
     pixels, computed exactly as the integral of the piecewise-constant row,
     wrapping at the seam. Every texel then covers the same ground east-west as
     north-south.
   - **Mip levels.** The filtered image is halved by 2×2 averaging down to a few
     rows and packed into one array.
2. **Two compiled passes per frame** (`pipeline/sphere_views.py`, Numba):
   - **Projection.** Each pixel gets the longitude and latitude at its centre, by
     the inverse orthographic (globe) or azimuthal equidistant (polar)
     projection. It also gets its share on the map, so rims are anti-aliased, the
     limb darkening and the atmosphere glow.
   - **Sampling.** The pixel's footprint is taken from the differences to its
     neighbours, as a GPU does. It is measured on the ground: east-west steps
     count `cos φ` times their longitude. Two mip levels are blended at the
     footprint's `log2` in texels, half a level finer, the usual compromise
     against the extra blur of box-filtered levels. The graticule is drawn in the same pass,
     anti-aliased by its distance in pixels, and meridians fade out where they
     crowd together near a pole.
3. **Views fill the canvas.** A globe's radius is `0.48 × min(width, height) ×
   zoom`, with zoom from 1 (the whole globe) to 16. `MapProjection` carries the
   zoom, so `world view --zoom` and the app's saved images match the screen.
4. **Screen geometry is analytic.** `screen_lonlat` and `lonlat_screen` use the
   same formulas as the kernels. Hover, clicks, the overlays of opened and picked
   regions and dragging use them, with no per-pixel lookup arrays.
5. **Dragging grabs the ground, north up.** For the grabbed point (λ, φ) under
   the cursor at view position (x, y), `grab` solves the orthographic equations
   `x = cos φ sin(λ − λ0)` and `y = sin φ cos φ0 − cos φ cos(λ − λ0) sin φ0` for
   the view centre (λ0, φ0). Of up to four solutions it takes the visible one
   nearest the current centre. Where none exists, such as a pole dragged
   sideways, the view turns by the drag and grabs the ground then under the
   cursor. Polar views turn about the pole so the grabbed meridian follows the
   cursor. The wheel zooms a globe towards the cursor, as a zoom followed by a
   grab of the point that was under it.
6. **Every frame is full resolution.** A frame takes about 9 ms at 900 × 900 and
   13 ms at 1,500 × 1,000 on a 16-thread desktop, against 0.4 s before. The
   app's latest-request worker renders the newest view, so a drag shows about 55
   frames a second and never shows low-resolution frames. Kernels are compiled
   on first use and cached.

## Alternatives considered

- **A cube map.** Six gnomonic or equi-angular faces sample the sphere almost
  uniformly. Not chosen: each theme would need converting, the faces need
  bordered filtering at their seams, and that conversion samples the
  equirectangular image near the poles anyway. The latitude prefilter gives the
  same isotropic footprint on the existing image.
- **A tiled level-of-detail pyramid** (as in web globes). It only pays off when
  zooming beyond the build's resolution. Regional detail windows (ADR-0086,
  ADR-0088) already provide that, from real regional relief.
- **An OpenGL widget or a browser view.** It would add a GPU dependency to a Tk
  application, or make a hosted page part of using the tool (against the
  local-first rule). The compiled CPU sampler is fast enough.
- **Free trackball rotation.** It keeps any grabbed point under the cursor but
  rolls the map, so north is no longer up, and a view would need a third angle.
- **Larger GPU-style anisotropic filtering.** The prefilter removes the
  anisotropy of the projection; the remaining one near the limb only blurs a
  band the limb darkening already dims.

## Consequences

- Views still show the world-frame image, so their detail is bounded by its
  width. The app draws planet maps 2,048 pixels wide: a whole globe in a
  900-pixel window shows them at about 1.3 screen pixels per texel, and zoom 16
  magnifies them about 20 times, about the ground scale of the flat map's deepest
  zoom. Views of a 4,096-pixel build (`world view`) are twice as sharp. Deeper
  looks use regional detail.
- Very thin east-west lines in a theme image, such as river lines drawn a pixel
  wide near a pole, are spread to one ground texel. That is their true width on
  the sphere.
- Projected views are as sharp as before at the centre. Towards the limb and the
  poles coasts no longer step or shimmer, and the rim is anti-aliased. Views made
  before this change differ in pixel values.
- `pipeline/sphere_views.py` holds display kernels beside the planet kernels,
  following the rule that Numba kernels live in the pipeline.
