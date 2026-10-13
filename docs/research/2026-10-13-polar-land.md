# Polar land in true distance — 2026-10-13

Decision: [ADR-0094](../adr/0094-planet-polar-land-in-true-distance.md).
Catalog entry: D32 in the [decision catalog](decision-catalog.md).

## Problem

Aethelara's polar ice looked wrong in polar views. On a fresh 3.2M-node build of
`213a0c5`, the south polar ice sheet was a fan that ended in a spike on the pole,
streaked radially. There were two causes, both in how the plate carrée drawing
meets the poles:

- **The pole was a wedge tip.** The southern continent reaches the frame's
  bottom edge along about 160° of longitude and is sea along the rest. Within 1°
  of the pole, 46 % of the planet's mesh nodes are land, and they agree with the
  drawing exactly. The land is a pie wedge whose straight meridian edges meet on
  the pole.
- **Traced steps become streaks.** One drawing unit east-west is
  `cos(latitude)` of a unit north-south: about 1.5 km at 80° on Aethelara, against
  13 km. Traced stair-steps there become thin radial streaks.

Further out, the continent also has N–S peninsulas 50–400 km long, which point at
the pole on a globe. They are drawn features and were left alone.

## Trials (land masks in polar projection)

| Trial | Result |
|---|---|
| Arc-length Gaussian smoothing of the polar rings in metres, σ = 0.4 units | Removed little (271 source units² of change). Teeth stay as wide as drawn and only their tips round off, as the regression test shows. |
| Cap from a radius function of angle, 256–512 modes, amplitude ∝ k^−1.0 to k^−1.3 | A starburst of radial spikes, the very look being removed. |
| Same cap with a closing over the whole cap | A smooth round blob. |
| **Chosen:** opening + closing with radius 0.25 units in the polar plane; cap with 8 lobes plus an isotropic domain warp from half its radius down to 8 km; pockets filled only where the cap meets drawn land | Streaks narrower than half a unit disappear. The cap reads as coast, with coves and headlands and no radial bias. |

A sign error first made each polar strip run from 55° on one side to the other
pole. That cost 20 s and left 20,000 slivers. With the strips correct, the planet
world takes 3.7 s on Aethelara and is cached per world and seed. Land equatorward
of 55° is unchanged: 0 of 200,000 random points between 54.5°S and 54.5°N differ.

## Aethelara result (3.2M nodes, same settings as the before build)

- The south pole is covered: 403,066 km² are added (`metrics.pole_cover` in
  the manifest). The adjustment's owner is the southern continent's feature only.
- The ice sheet now domes over the pole, with a lobed margin. Before, it ended
  in a spike on the pole. The flat atlas shows ice across the full width of
  its bottom rows.
- The north polar zone has land only to 72°N. It is smoothed and needs no cap.
- Region windows (level 1) use the same land. One of 400 km radius at 86.5°S
  lies wholly on the ice dome. One of 300 km at the cap's sea side
  (−170°, −86°) shows a lobed, rugged ice coast with a shallow shelf.

Images are local artifacts (`artifacts/aethelara/poles/`), not tracked.

## Limits and follow-ups

- The ice margin still shows short radial brush marks near the pole in polar
  views. They come from the atlas, which is drawn on the flat world raster and
  then reprojected; their exact source was not investigated. A suspect is the
  shading gradient, whose east-west pixel spacing tends to zero at the pole.
- The cap has no geology province of its own and takes its continent's default
  profile.
