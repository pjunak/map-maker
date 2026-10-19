# ADR-0110: Save a turning globe as an animated WebP image

- Status: accepted (experimental product path)
- Date: 2026-10-19
- Builds on: [ADR-0101](0101-interactive-globe-views.md) (the globe's renderer),
  [ADR-0102](0102-globe-models-in-gltf.md) (globe models) and
  [ADR-0103](0103-regional-detail-on-the-globe.md) (regional maps on the globe).

## Context

A planet can be shown outside Map Maker as a still image (`world view`, **Save
image…**) or as a 3D model (`.glb`, ADR-0102). A model needs a 3D viewer, and a
still shows one side of the planet. To show a whole world in a web page, a chat
or a document, a short animation of the globe turning is the most widely playable
form, and the app's renderer draws a frame in a few milliseconds.

## Decision

1. **Format: animated WebP.** It plays in web browsers and in most chat and
   document tools, keeps full colour and is lossy-compressed. One file loops
   forever.
2. **One eastward turn.** Frame `k` of `n` shows the view with its centre
   meridian moved `360·k/n` degrees west, so the ground moves eastward as a
   planet turns: left to right on a globe, anticlockwise about the north pole
   and clockwise about the south pole. The last frame leads into the first.
   Latitude, zoom, graticule and regional maps are those of the view.
3. **Defaults.** 120 frames (3° each) over 6 seconds, 20 frames a second;
   720-pixel frames; WebP quality 80 with encoder method 4. On Aethelara's
   4,096-pixel atlas a 720-pixel turn is 3.9 MB; quality 90 would be 6.6 MB.
   8-720 frames and 1-120 seconds are accepted.
4. **Products.**
   - `map-maker world spin <build>` takes `world view`'s options for a globe or
     a polar view, plus `--frames` and `--seconds`, and writes a new `.webp`. It
     never replaces a file.
   - **Save the shown globe spinning…** in the Explore step saves the globe or
     polar view as shown, at its middle 720-pixel square, with the regional maps
     it shows. The view is captured on the Tk thread and drawn in a background
     job.
5. **Repeatable.** The frames are drawn by the deterministic renderer, and the
   same frames always encode to the same bytes with the installed libwebp
   (Pillow 12, libwebp 1.6).

## Alternatives considered

- **Animated GIF.** Plays everywhere, but its 256 colours band the atlas's
  shading, and the app's 120-frame turn of a Quick Aethelara planet took 29 MB
  as GIF against 4.4 MB as WebP.
- **Video (MP4, WebM).** Smaller and suited to presentations, but it needs a video
  encoder such as FFmpeg, a new dependency.
- **Animated PNG.** Full colour but lossless: the same turn took 49 MB.
- **A frame folder.** Leaves assembling the animation to the user.

## Consequences

- A turn takes about a second to draw and 5-10 seconds to encode on a 16-thread
  desktop; the app saves it as a background job.
- A spin shows only the side the view faces; a polar view turns about its pole.
- Older software without WebP support shows only the first frame, or nothing.
