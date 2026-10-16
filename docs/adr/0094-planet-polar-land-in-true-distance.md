# ADR-0094: Work the planet's polar land in true distance and cover touched poles

- Status: accepted (experimental product path)
- Date: 2026-10-13
- Refines the coast rule of ADR-0085 near the poles. ADR-0090 still refines the
  result at regional levels.
- Refined by [ADR-0100](0100-smooth-polar-land-east-west.md): polar land is first
  smoothed east-west, so drawn shapes do not become radial fingers.

## Context

Worlds are drawn on a plate carrée frame, which fails near the poles:

- **Streaks.** One drawing unit east-west shrinks to `cos(latitude)` of a unit
  north-south, a few hundred metres near a pole. Traced stair-steps there become
  thin radial streaks tens of kilometres long.
- **Wedges.** Land drawn down to the frame's polar edge along only part of its
  width meets the pole as a wedge, with straight meridian edges that meet exactly
  on the pole.

On Aethelara the southern continent touches the south pole along about 160° of
longitude. The planet and its ice sheet therefore converged to a spike at the
pole, streaked radially.

## Decision

1. **The planet sees a derived world.** The authored world and its prepared land
   are unchanged. Planet generation and loaded planet builds use
   `planet_world(world, seed)`, which has the same features and continents.
2. **Polar land is worked in a polar azimuthal-equidistant plane, in metres,**
   poleward of 55°, using the coast down to 52° so the edge sees real geography.
   Equatorward of 55° the land is exactly the prepared land.
3. **Smoothing.** An opening and a closing with a radius of 0.25 drawing units
   (3.3 km on Aethelara) remove land and water narrower than half a unit, the
   drawing's north-south precision. Islets the opening would delete keep their
   drawn shape.
4. **Covering a pole.** When land touches a pole along part of the frame's edge,
   a cap of about 4° around the pole joins it:
   - its outline has eight broad lobes (amplitude ∝ mode^−1.3, up to ±40 % in
     log radius);
   - a domain warp from half the cap radius down to 8 km, at 0.25 × wavelength,
     shapes coves and headlands without radial bias;
   - pockets are filled with a 0.5 × radius closing only where the cap meets drawn
     land;
   - the seed comes from stage `planet.poles`.
5. **Ownership and reporting.** Each feature keeps its remaining land. Added land
   goes to the nearest feature in the polar zone. A `pole_cover` world adjustment
   names the owners and the added area, and the build's `metrics.pole_cover` lists
   it. The relief algorithm becomes `sphere-mesh-stream-power-v26`.

## Consequences

- A touched pole is covered, so the ice sheet grows as a dome over it instead of
  a spike. On Aethelara, 403,000 km² are added around the south pole.
- Polar coasts on the planet differ from the drawing by up to about a quarter of a
  drawing unit, plus the cap. The authored world view and world-context products
  still show the drawn land.
- Added cap land has no geology province, so it takes its continent's default
  profile.
- Loading an older build with this code applies the derived world to regional
  detail although that build's mesh did not use it. Regenerate older builds.
