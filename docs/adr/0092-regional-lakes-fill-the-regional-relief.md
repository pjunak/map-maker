# ADR-0092: Fill regional lakes on the regional relief, with refined outlines

- Status: accepted (experimental product path)
- Date: 2026-10-12
- Extends ADR-0086 (blended tiles) and ADR-0088 (nested levels); applies the
  outline refinement of ADR-0090 to lakes.

## Context

Regional windows drew a parent lake where the parent's lake cover exceeded 0.15
and the window relief lay no higher than the lake level. The cover is
triangle-linear on the parent mesh (about 24 km at 800k nodes), so its contours
are straight inside each parent triangle. Wherever the relief stayed below the
level beyond that contour, shores became straight edges 25–50 km long. Inside
wonder zones the gate was widened to the parent triangles touching the lake,
whose outer edges are straight too.

Tiles also fix parent lake nodes as water. They held them at the full lake
level, but tiles erode the surface without volcanoes and wonders, which windows
add back. A crater lake was therefore held a crater's depth too low in the
tile's frame, and appeared up to about 1,200 m below its own level in the
window. Tiles then eroded towards these pits.

Finally, the fixed lake area is the parent cover above 0.5, so tile lake flats
traced the same straight parent contours.

## Decision

1. **Lakes fill the window relief.** A lake is the window ground at or below
   its level (within 2 m) that is connected to the lake's core (where tiles hold
   the parent lake) and lies in a basin spilling no lower than the level. Shores
   are contours of the regional relief, and open lakes do not run down their
   outlet valleys. The wonder-zone widening is removed: crater and chasm lakes
   follow the sharp relief through the same rule.
2. **Closed lakes are sinks.** Where a window holds a closed lake, river and
   pond routing ends in it, so its basin drains into it instead of filling to
   its rim, and no playa is drawn above it.
3. **Tiles hold lakes in their own frame.** A lake node is held at the lake level
   minus the young relief (volcanoes and wonders) the tile leaves out. Level
   parents carry the planet's young relief on top of their surface, as the planet
   does, so levels 2 and 3 agree.
4. **Lake outlines are refined below the parent spacing.** The parent lake cover
   is sampled at points displaced by the nested domain warp of ADR-0090. Octaves
   start at 4 parent spacings with an amplitude of 0.25 spacings (stage
   `planet.lake-outline`) and stop at twice the level spacing. Every level
   samples the planet's lakes, so a finer level only adds octaves.
5. The regional tile algorithm becomes `planet-blended-tiles-v7`.

## Consequences

- Lake and salt-pan shores bend with the relief and with outline detail at every
  level; the parent's straight triangle edges no longer appear.
- A lake can move by up to about half a parent spacing from its parent nodes,
  which the parent does not resolve. The world map keeps the parent outline.
- Lakes are bounded by the regional relief: one can shrink where the window
  relief drains it, or grow over low ground beside it, compared with the parent.
- Where the relief is smooth or planar at the level's resolution, shores are
  smooth too; finer detail comes from finer levels.
- Crater regions lose the rugged relief that tiles had eroded towards the pits.
