# ADR-0104: Zoom the globe past 16x into opened regional maps, until their pixels fill the screen's

- Status: accepted (experimental product path)
- Date: 2026-10-18
- Refines: [ADR-0101](0101-interactive-globe-views.md) (zoom from 1 to 16) and
  [ADR-0103](0103-regional-detail-on-the-globe.md) (regional maps on the globe).

## Context

ADR-0101 let the globe zoom to 16x, about the ground scale of the flat map's
deepest zoom. Beyond that it only magnified the planet map. ADR-0103 then draped
the opened regional windows over the globe, but kept the limit. On Aethelara
(6,000 km radius) a 16x globe in a 1,000-pixel-tall view shows about 0.8 km a
pixel at its centre. A 900-pixel province window (150 km radius) has 0.33 km
texels and a local window (30 km) 67 m texels, so the globe showed them at less
than half and a twelfth of their resolution. Only their own flat maps showed them in
full.

## Decision

1. **The limit follows the ground under the cursor.** Zooming in towards a point
   inside the circle of a draped window may continue until a texel of the finest
   such window spans one screen pixel at the view's centre, where the
   orthographic globe is true to scale. A window `width` pixels across, of
   angular radius `a` (window radius over planet radius), reaches that at zoom
   `width / (0.96 × a × shorter side)` (`drape_zoom`). Elsewhere the limit stays
   16. In a 1,000-pixel-tall view on Aethelara that is 37.5x for a 150 km
   province, 187.5x for a 30 km local window and about 940x for the app's
   smallest, 6 km, local window. A 600 km region reaches one texel a pixel below
   16x and changes nothing.
2. **Only the point being zoomed counts.** The wheel zooms towards the ground
   under the cursor and the keys towards the centre (ADR-0101); that point must
   lie inside the window. A window visible elsewhere in the view does not extend
   the zoom, so zooming beside it stops at 16x.
3. **Zooming out is always possible, and turning keeps the zoom.** A view deeper
   than the limit at its zoom point, because it was turned away from its window
   or the window's map is no longer shown, keeps its zoom; zooming in there does
   nothing, and zooming out works as usual.
4. **Projections no longer carry the limit.** `MapProjection` checks only that a
   globe's zoom is finite and at least 1; `zoomed` applies the limit, given the
   drapes. `world view` shows the planet map alone, so its `--zoom` stays 1-16.
5. **Arrow keys turn by screen pixels.** A key turned the globe by an eighth of
   its radius, about a whole view at 16x and eleven views at 187.5x. It now turns
   by an eighth of half the view's shorter side, as at zoom 1, at any zoom.
6. **Double precision suffices.** Screen positions, `grab` and the kernels'
   per-pixel longitude and latitude use the same orthographic formulas in 64-bit
   floats. At 2,000x, round trips from screen to ground and back, grabs and the
   kernel's pixel positions agree within 1e-9 pixels at mid-latitudes and 2e-6
   pixels within 0.01° of a pole, where `asin` near 1 loses digits as the square
   of the zoom; at 20,000x the worst was 7e-5 pixels.

## Alternatives considered

- **A fixed higher limit**, such as 256x. It would magnify the planet map into
  blur wherever no window lies, and still stop short of small local windows.
- **The limit from any drape on screen.** Zooming beside a window would go on
  into the magnified planet map around it.
- **Clamping the zoom when the view turns away from a window.** The view would
  jump out in the middle of a drag, and the grabbed ground would leave the
  cursor.
- **Magnifying windows beyond one texel a pixel.** Their own flat maps already
  do; the globe's purpose here is to show them at their resolution in place.

## Consequences

- Province and local windows can be seen on the globe at their full resolution,
  inside the province and region around them and with the curvature, graticule,
  limb shading and hover of the globe.
- At a local window's limit the province around it is magnified about five
  times, the region twenty and the planet map 140 to 280 times (4,096 or 2,048
  pixels wide). Deep views make sense
  over the windows only, which the zoom rule enforces when zooming in.
- The zoom readout and the scale bar need no change; they read, for example,
  187.5x and 5 km at a local window's limit.
- Frames cost the same at any zoom: every pixel is sampled once, and inside a
  drape a deeper zoom only picks finer mip levels. In the app on Aethelara
  (Standard planet, a region, province and local window open about 56.9° E,
  30.7° N, an 853 x 600 map), the province reached one texel a pixel at 62.5x
  and the local window at 312.5x. The fastest of 20 frames took 9.8-10.5 ms at
  16x, 10.3 ms at 62.5x and 10.2 ms at 312.5x.
