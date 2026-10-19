# ADR-0111: Carry opened regional maps into globe models as lifted, pre-faded surfaces

- Status: accepted (experimental product path)
- Date: 2026-10-20
- Builds on: [ADR-0102](0102-globe-models-in-gltf.md) (globe models) and
  [ADR-0103](0103-regional-detail-on-the-globe.md) (regional maps on the globe).
  It removes ADR-0103's consequence that globe models show the world map alone.

## Context

The app's globe shows the regional maps a user has opened over the world map, with
their rims faded into it (ADR-0103). A globe model saved from the app (ADR-0102)
showed only the world map, so the detail of an explored area was lost when the
planet left Map Maker. A glTF model has no drapes: each surface is a mesh with one
texture, drawn by the viewer's depth test and, for transparent materials, its own
sorting.

## Decision

1. **One surface per regional map.** The app's **Save the shown map as a 3D
   globe…** adds a primitive for each regional map the globe shows for that map,
   in level order (`globe_model.globe_surfaces(..., drapes)`). `world globe` is
   unchanged: builds carry no regional maps.
2. **A polar grid over the window's disc.** Rings from the window's centre to its
   rim and vertices around each ring: at least 32 rings and 128 sectors, and
   cells no wider than 0.005 radians of arc. Positions come from `inverse_aeqd`;
   texture coordinates are the window's own azimuthal equidistant ones, so each
   vertex shows the pixel the window drew there. Only the inscribed disc is
   covered.
3. **Lifted, so the deeper level wins.** Level `n` lies `n × 0.2 mm` above the
   1 m sphere. On a 1 m globe that is invisible, yet several depth-buffer steps
   at ordinary viewing distances, so a province stays on top of its region from
   every angle.
4. **Opaque, with the fade drawn in.** The rim fade is the app globe's
   (`sphere_views.drape_weights`: full at 96 % of the radius, gone at the rim). It
   is drawn into the surface's image against the colours the model shows beneath
   it: the band, a polar cap or the regional map below, each read bilinearly as
   a viewer reads it. The surface is then an ordinary opaque material, and its
   rim pixels match what lies under them.
5. **The save says so.** The status line names how many regional maps the model
   carries, and the button's hint mentions them.

## Alternatives considered

- **Blended (`alphaMode: BLEND`) surfaces with transparent rims.** three.js's
  glTF loader turns depth writes off for blended materials and sorts them by
  the distance to each part's centre, so a region would paint over its province
  once the globe was turned.
- **Masked (`alphaMode: MASK`) surfaces.** They cut a hard edge through the
  middle of the fade.
- **Cutting holes in the band and caps.** Retriangulating the sphere around each
  disc would make the surfaces meet exactly, but it is far more geometry code
  for a seam the pre-faded rim already hides.
- **Polygon offset.** glTF has no depth-bias setting; the lift does its work.

## Consequences

- A model carries each regional map at its window's resolution (900 pixels), so
  explored areas stay sharp in any viewer.
- Three 900-pixel windows added about 1.8 s to a save and a few megabytes to the
  file.
- The rim of each surface matches what lies under it to within one colour level
  in a bilinear reader; a viewer's mip filtering may soften it at a distance.
- A regional map drawn only in another theme adds nothing to this map's model,
  as on the globe.
