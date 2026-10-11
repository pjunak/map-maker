# ADR-0090: Add coast detail below the drawing's precision at regional levels

- Status: accepted (experimental product path)
- Date: 2026-10-11
- Extends ADR-0088 (nested regional levels). Refines the coast rule of ADR-0085
  for regional levels only.

## Context

Regional levels used the exact vector coastline. A world drawing is precise only
to about one drawing unit (13 km for a 2,880-unit-wide Earth-size frame), and
traced drawings carry stair-step corners at that scale. At province (1 km) and
local (200 m) zoom the coast was a smooth curve or a straight run with sharp
tracing corners, so coastal places looked artificial.

## Decision

1. **The planet keeps the exact coast.** Planet builds, their images and every
   world-scale product use the drawn coastline unchanged.
2. **Regional levels use a refined coast.** It is the drawn coast:
   - smoothed along each ring by a Gaussian of 0.3 drawing units, so tracing
     corners do not appear at every zoom (rings shorter than 2.4 units, and the
     frame edges at the antimeridian and poles, keep their drawn shape);
   - then detailed by a domain warp: each point is displaced by rotated noise
     octaves before the inside test. Octaves start at 8 drawing units with an
     amplitude of 0.6 units, follow amplitude ∝ wavelength^0.4, and are capped
     at 0.25 × wavelength, so the coast stays rugged and self-similar at every
     scale instead of becoming either smooth or noisy.
3. **Nesting.** A level includes every octave down to twice its spacing; a
   window includes octaves down to three pixels. A finer level only adds
   octaves, so it refines the coast of the level above. The coast depends only
   on the world, the master seed (stage `planet.coast`) and position.
4. Tiles, level parents and windows all use it. The regional tile algorithm
   becomes `planet-blended-tiles-v6`.

## Consequences

- Regional coasts have bays, headlands, skerries and coves at every zoom, and
  rivers drain to the refined coast.
- The regional coast departs from the drawing by up to about one drawing unit,
  which is below what the drawing resolves. Places drawn closer to the coast
  than that can end up inland or offshore at regional zoom.
- The roughness is the same everywhere; it does not yet follow coast type
  (rocky, uplifted coasts against smooth sedimentary ones).
- Islets and coastal ponds can appear where the warp folds; ponds are drawn as
  shallow sea.
