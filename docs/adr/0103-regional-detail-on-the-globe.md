# ADR-0103: Show opened regional maps on the globe where it is zoomed in on them

- Status: accepted (experimental product path)
- Date: 2026-10-18
- Builds on: [ADR-0101](0101-interactive-globe-views.md) (the globe's sampler)
  and [ADR-0088](0088-nested-regional-detail-levels.md) (nested regional levels).

## Context

The globe shows the app's world-frame map, 2,048 pixels wide, or 4,096 for
Detailed and Fine planets. On Aethelara's 6,000 km radius a 2,048-pixel map has
a texel of about 18 km, while a zoom-16 globe in a 1,000-pixel window shows about
0.8 km per pixel at its centre. Beyond 2-4x zoom the globe therefore magnifies
the map and blurs. Drawing a 4,096-pixel map in the background whenever a view
zoomed in was rejected (D28, 2026-10-18): the atlas took 25 s and its inputs
peaked at 5.1 GB.

Regional windows the user has opened ([ADR-0086](0086-regional-planet-detail-from-blended-tiles.md),
ADR-0088) already hold much finer images of the same themes, 900 pixels across.
That is about 1.3 km a pixel for a 600 km region, 0.33 km for a 150 km province
and 67 m for a 30 km local window. Before this decision the globe only outlined
them.

## Decision

1. **Drapes are the regional images already drawn.** Where an opened level has
   an image of the theme the globe shows (atlas, relief, topographic or
   parchment, the themes regional levels draw), globe and polar views show that
   image over the world map. Nothing is drawn for the globe. A region drawn
   only in atlas adds nothing to a relief globe until relief is shown in it.
2. **Same geometry as the window.** A window image is an azimuthal
   equidistant square about the window's centre on the planet sphere, its sides
   `radius_m / planet_m` of arc from the centre. The sampler maps each pixel's
   longitude and latitude into that plane with the window's east and north
   axes and the great-circle distance, as `inverse_aeqd` placed the window's
   pixels, and samples there. Only the inscribed disc, where the window has
   relief, is shown.
3. **Each drape is filtered like the world map.** A drape gets its own mip
   levels by 2x2 averaging. It needs no latitude prefilter: the projection's
   scale is 1 along radii and `θ / sin θ` across them, 1.13 at most even for a
   5,000 km region on Aethelara. Before averaging, the corners outside the disc
   take the colour 1.5 pixels inside the rim along the same radius, so neither
   mip levels nor bilinear samples bring the window's outside colour in. The
   level comes from the pixel's ground footprint, as for the world map, counted
   in window texels.
4. **A soft seam.** A drape's opacity falls from 1 at 96 per cent of its radius
   to 0 at the rim, along a smoothstep, so it fades into the map below over 24
   km of a 600 km region.
5. **The deepest level wins.** Drapes lie in level order. They are combined
   front to back from the deepest, and once one covers a pixel neither
   shallower drapes nor the world map are sampled there.
6. **Pixel footprints decide whether drapes are used.** A pixel that covers at
   least one world texel skips the drapes and is drawn exactly as before. Below
   one texel the drapes' opacity rises linearly and is full at half a texel, so
   they fade in as the world map starts to be magnified, without a jump while
   zooming. With a 2,048-pixel map a whole globe is untouched in windows up to
   about 680 pixels tall; larger windows already magnify the map at the centre.
7. **Cheap away from drapes.** Each drape also carries a latitude and longitude
   box around its circle (`asin(sin a / cos φ)` of longitude either side, or all
   longitudes where the circle reaches a pole). Pixels outside every box skip
   the trigonometry that places a point in a drape's plane.
8. **Prepared once per set.** `DrapeTextures` packs every drape's levels and
   geometry for the compiled sampler (`pipeline/sphere_views.py`). The globe
   canvas rebuilds it only when the shown drapes change; that took 19 ms for
   three 900-pixel images on Aethelara.
9. **Outlines give way to the maps.** The globe outlines opened regions until
   the view's centre is fine enough for drapes to show in full (half a world
   texel a pixel). From there a region whose map lies over the view is shown by
   that map, not by a line across it. A region without an image of the shown
   map stays outlined.

## Alternatives considered

- **A finer world map on zoom.** Rejected before (D28): seconds of drawing and
  gigabytes of inputs for detail that is still coarser than a region's.
- **Regional maps redrawn for the globe on demand.** Drawing every theme of
  every level when the globe shows it would make the globe wait for slow
  regional rendering on the same workers as its frames. Showing only what is
  drawn keeps frames independent of regional jobs.
- **Fading by footprint so a drape's edge never meets the outside colour.**
  It would make the visible circle shrink with zoom and stop matching the
  window; filling the corners keeps the seam where the window ends.
- **A hard switch by zoom.** Regional colours can differ slightly from the
  world map's, so a switch would flash while zooming; the opacity ramp over one
  octave of footprint avoids it.
- **Handing the drapes the globe's unit vectors.** The projection pass already
  has each pixel's point on the sphere, and passing it on saved the sampler
  about 4 ms at 16x. Writing and reading the extra 18 MB a frame cost more than
  that, so whole frames got slower; drapes recompute the point from longitude
  and latitude.

## Consequences

- Zooming the globe over an explored area shows the regional relief, rivers and
  vegetation instead of the magnified world map, and nested levels sharpen in
  turn as the view closes in. At 16x a pixel still covers about 0.8 km of
  Aethelara, so province and local windows are seen minified; their own maps
  show them in full.
- Where regional colours differ from the world map's, the fade shows the
  region's edge as a soft change of tone, most visibly between a region's
  sharper detail and the magnified map around it.
- Pixels inside drapes cost more. On Aethelara in the app (Standard planet, a
  region, province and local window open, 1,500 x 1,000 frames on a shared
  16-thread desktop), a frame entirely inside the drapes at 16x took 18.0-19.8
  ms against 12.6-14.8 ms without them (the fastest of 30 frames, in two runs;
  a busier run took 28.1 against 19.7 ms). At 4x, with the region in part of
  the view, frames took 2.5-2.7 ms more. Frames whose pixels are coarser than a
  world texel are unchanged pixel for pixel.
- Regional parchment maps are drawn without the sheet frame, whose lines crossed
  the window's disc where it touches the square's sides.
- Saved globe images include the drapes, as they match the screen. Globe models
  (`.glb`, ADR-0102) and `world view` still show the world map alone.
