# ADR-0100: Smooth polar land east-west so drawn shapes do not become radial fingers

- Status: accepted (experimental product path)
- Date: 2026-10-17
- Refines: [ADR-0094](0094-planet-polar-land-in-true-distance.md) (polar land in true
  distance). ADR-0090 still refines the result at regional levels.

## Context

ADR-0094 removes polar land and water narrower than the drawing's north-south
precision, so traced stair-steps no longer become streaks. Larger shapes still
change their proportions. A plate carrée drawing squeezes a drawing unit
east-west to `cos(latitude)` of a unit north-south, so a shape that looks
ordinary on the flat map is thin and radial in true distance:

- Aethelara's southern coast is drawn as a comb of teeth about 11 by 21 drawing
  units. At 70–80° south these become fingers about 50 km wide and 280 km long.
- Island chains drawn along that coast become radial slivers.

Polar views showed those coasts, and the ice sheet that covers them, as radial
bristles. The user asked for polar land reshaped so that drawn shapes do not
become thin radial fingers, with the overall coast kept where it was drawn.

## Decision

1. **East-west smoothing first.** Before the ADR-0094 steps, polar land is
   smoothed along latitude circles only:
   - The exact land share is taken along scan lines 0.125 drawing units apart, in
     cells 0.25 units wide.
   - Each scan line is blurred by a periodic Gaussian. Its true width is
     `4 drawing units × (1 − cos φ / cos 55°)`, measured in equator units: nothing
     at the zone edge, 52 km at Aethelara's pole. In drawing units the width is
     that divided by `cos φ`.
   - Land is where the blurred share is at least a half.
2. **The drawn coast stays where smoothing barely moves it.** North-south positions
   are untouched, because nothing is smoothed north-south.
   - Where the smoothed coast lies within one scan line of the drawn coast, the
     drawn coast is kept.
   - Elsewhere the smoothed coast replaces it: fingers narrower than their gaps
     are removed, and fjords narrower than their walls are filled.
3. **Islets the smoothing would delete keep their drawn shape,** as in ADR-0094.
4. The relief algorithm becomes `sphere-mesh-stream-power-v30`.

## Alternatives considered

- **A larger isotropic opening and closing near the pole.** Rejected. It also
  removes features the projection does not distort, such as islands that run
  east-west and narrow straits.
- **Stretching deleted islets east-west to restore their flat-map proportions.**
  Rejected. On Aethelara the only islet deleted whole is 50 by 69 km and well
  shaped; restoring proportions would have made it 103 by 33 km.
- **Rasterising with a GIS library.** Not chosen. Scan lines across the ring edges
  give the exact land share in the pipeline without a raster dependency, which
  belongs to adapters.

## Consequences

- Polar coasts keep no east-west detail finer than the smoothing width. At 75° the
  Gaussian's true sigma is 29 km on Aethelara.
- Aethelara's polar zones (poleward of 52°) change little in drawn area: the south
  loses 1.0 % and the north gains 0.4 %.
- The step costs about 2 s per pole on Aethelara.
- `metrics.pole_cover` reports the land the cover adds, the cap and the pockets
  it fills (386,456 km² on Aethelara). It used to report the net change of polar
  land, which would now also count the smoothing.
- The authored world, the Source view and world-context products still show the
  drawn land. `world refine-coast` exports the reshaped polar coast, as it already
  exported the ADR-0094 result.
- Builds made before this change differ near the poles; regenerate them.
