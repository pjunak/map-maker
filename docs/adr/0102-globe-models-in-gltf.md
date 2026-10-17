# ADR-0102: Save a planet map as a 3D globe model in glTF binary (.glb)

- Status: accepted (experimental product path)
- Date: 2026-10-17
- Builds on: [ADR-0087](0087-map-themes-and-projections.md) (themes on the world
  frame) and [ADR-0101](0101-interactive-globe-views.md) (the app's globe).

## Context

The app's globe ([ADR-0101](0101-interactive-globe-views.md)) shows a planet map
as a globe only inside Map Maker. The user wants to show the created map as a
full globe, and asked for the proper file format to do it, without unwanted
complexity. A file that others can open and turn needs:

- a standard that common tools read without plugins;
- one self-contained file, so it can be passed on;
- the map exactly as drawn, with no seams or pinched poles.

A sphere textured with the whole equirectangular map, the usual approach, fails
at the poles. Viewers filter textures by image pixels: near a pole the map is
squeezed east-west without limit, so they pick mip levels far coarser
north-south than the ground needs. On Aethelara's south polar ice sheet a
three.js viewer drew a starburst of radial streaks around the pole, even with
the map filtered by latitude first (ADR-0101). The app's own renderer measures
footprints on the ground and shows no streaks, but a file cannot tell viewers
to do that.

## Decision

1. **Format: glTF 2.0 binary (`.glb`).** glTF is the open, royalty-free format
   for 3D scenes of the Khronos Group, published as ISO/IEC 12113. A `.glb` holds
   the scene description (JSON) and the binary data, including the image, in one
   file. Blender, game engines and browser glTF viewers open it.
2. **The model is a desk globe.**
   - A smooth sphere one metre in radius; glTF units are metres.
   - North is +Y, the world frame's central meridian faces +Z (the side viewers
     show first) and east is +X.
   - The node's `extras` record the map's name, the model radius, the planet's
     true radius, the central meridian and, for builds, `build_sha256`.
3. **A band and two polar caps.** The sphere is one 1.5° latitude-longitude
   grid, split into three surfaces, each with its own image:
   - **The band, 60° N to 60° S, shows the map unchanged.** Its texture
     coordinates are exactly the world frame's, `u = (lon − west) / 360` and
     `v = (90 − lat) / 180`, with seam vertices doubled so `u` runs from 0 to 1.
     Its sampler repeats east-west. There the map is squeezed east-west at most
     two to one, which viewers filter well.
   - **Each cap, poleward of 60°, shows an azimuthal equidistant image** of the
     map out to 61.5°, drawn by the app's view renderer (ADR-0101) at the band's
     pixel density. A pole is an ordinary point of that image, so there is no
     singularity to filter: one vertex sits on the pole and the triangles fan
     out from it.
   - The caps and the band share their boundary vertices, so the sphere is
     closed. Along the boundary the two images differ by under one colour level
     on average on Aethelara's atlas (under 5 levels in 95 % of places).
   - A build's theme PNG is embedded in the band byte for byte after its hash is
     checked. The app embeds the map it has drawn, at its preview width of 2,048
     pixels.
4. **Material.** The map is the base colour of a matte, non-metallic material,
   with `KHR_materials_unlit` declared but not required. Viewers that support it
   show the map's own hillshade; others light the globe as a matte object.
5. **Products.**
   - `map-maker world globe <build> --theme <id> --output <file>.glb` writes a new
     file and never replaces one.
   - **Save the shown map as a 3D globe…** in the app's Explore step saves the
     whole-planet map currently chosen.
6. **No new dependency.** The writer is about 250 lines of NumPy, `json` and
   `struct`, and draws the caps with the existing view renderer.

## Alternatives considered

- **A self-contained HTML page with a WebGL globe.** Any browser could show it,
  but it would be a second renderer in JavaScript to maintain beside ADR-0101,
  and it is a page rather than a model other tools can use.
- **USDZ, FBX, OBJ + MTL or COLLADA.** USDZ is mainly for Apple's tools; FBX is
  proprietary; OBJ needs separate texture files and has no standard material
  model; COLLADA is XML and largely superseded by glTF.
- **The planet's own mesh with relief.** The sphere mesh carries the authoritative
  elevation (ADR-0085), but a textured globe needs its triangles split at the
  seam and its poles handled, and exaggerated relief would double the
  hillshade already drawn in the map. Displaced relief can be added later as an
  option on the same grid.
- **One equirectangular texture over the whole sphere.** The simplest model,
  rejected for the radial streaks at the poles described above. Filtering the map
  by latitude first did not remove them in three.js.
- **A cube-sphere with six face images.** It samples the sphere evenly
  everywhere, but packing faces into one texture needs guard pixels at every
  face edge for each mip level, and the band would no longer be the map itself.
  Two caps fix the only region that needs it.
- **True scale (6,000 km radius).** Many viewers handle such sizes poorly
  (clipping, navigation), so the model is a 1 m globe that records the true
  radius.

## Consequences

- A globe file is about 2 MB of geometry and cap images plus the map's PNG,
  about 9 MB in all for Aethelara's 4,096-pixel atlas.
- The globe shows the map's detail only. Poleward of 60° it shows the map as
  resampled for the caps, about as sharp as the band.
- The app's globe files are as sharp as its 2,048-pixel maps; `world globe` on an
  exported build embeds its full width (4,096 pixels by default), which current
  desktop GPUs accept. Much wider builds need viewers that accept such textures.
- Viewers decide lighting, background and controls. The model carries no
  graticule, labels or overlays.
