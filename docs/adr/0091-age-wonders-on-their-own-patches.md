# ADR-0091: Age wonders by eroding each on its own patch

- Status: accepted (experimental product path)
- Date: 2026-10-12
- Extends ADR-0085 (planet relief) and ADR-0088 (nested regional levels) for
  wonders only.

## Context

Wonders (craters, chasms, great cliffs, tepuis) are drawn on top of the eroded
relief from analytic shapes, so every map draws them sharply at its own scale.
They are therefore always fresh: no gullies cut their walls, no sediment fills
their floors and their rims never round. Fresh shapes look young; most of
Earth's large landforms are millions of years old. Regional tiles cannot erode
them either, because the tiles' erosion fills every closed hollow and would erase
a crater or a chasm at once.

## Decision

1. **An age per wonder.** Planet settings carry a wonder age for random wonders
   (0 = fresh); a hand-placed landmark may carry its own. Volcano wonders and
   eruptions stay young.
2. **Each aged wonder is eroded on its own patch.** The patch is a jittered
   hexagonal mesh centred on the wonder, covering it and its surroundings, with
   about 120,000 nodes (1 km spacing or more). It is fixed to the wonder, so it
   does not depend on the planet mesh or on any map window.
3. **The erosion is the planet's.** The patch starts as the eroded ground plus
   the fresh wonder and runs the planet's implicit stream-power model with no
   uplift, a quarter of the planet's erodibility (it was tuned against uplift)
   and the planet's runoff, for the wonder's age in at most 100 steps. Raised
   wonders wear more slowly: tepuis keep a quartzite caprock (a quarter of that
   erodibility) and great cliffs hard layers (40 %). Linear creep (0.5 m²/yr)
   then rounds rims, about 4 km over 30 Myr.
4. **Hollows fill gradually.** The model fills every closed hollow to its spill
   level at once. Only a share of that fill is kept, 1 − exp(−age / 50 Myr), so
   crater and chasm floors fill with sediment over tens of millions of years
   instead of vanishing.
5. **The change is stored, not the result.** The build keeps each patch's nodes
   and the aged-minus-fresh change. Every map, the planet mesh included, adds the
   interpolated change to the fresh shape it draws at its own scale, so all
   scales agree on the aged wonder and keep fine detail.

## Revision (2026-10-12)

Point 5 first added the interpolated change to the fresh, pixel-sharp shape. At
a steep edge erosion moves a wall back horizontally, which a smooth vertical
change on a kilometre grid cannot express: the fresh edge survived as a narrow
ridge and the lowering bled into the foot as a moat of ponds (seen around an
aged tepui at province zoom). Each patch now keeps the aged wonder's relief and
records which wonder it belongs to; inside the patch maps draw that relief in
place of the wonder's own fresh shape, fading to the fresh shape at the patch
rim. Aged wonders are therefore smooth at the patch spacing, and the base
terrain's detail textures them.

## Consequences

- Aged wonders gain gully networks on their walls, rounded rims and partly
  filled floors; an ancient crater fades to a ghost ring, as Earth's oldest
  astroblemes have.
- Aging costs about a minute per wonder and 100 steps; builds with fresh wonders
  are unchanged.
- An aged wonder is resolved at the patch spacing (1–5 km); finer maps show it
  smoothly, textured by the base terrain's detail.
- Erosion does not deposit downstream of the patch, and the patch boundary is
  held fixed; both are acceptable at the scale of one wonder.

## Alternatives considered

- **Eroding wonders with the regional tiles.** Rejected: tile erosion fills
  closed hollows, changes every tile near a wonder and its cache, and depends on
  the tile level.
- **Procedural aging (noise gullies, blurred rims).** Rejected: gullies drawn by
  noise do not drain or join, which is the artificial look aging should remove.
- **Keeping the deepest floors as fixed sinks.** Tried first: the sinks pulled
  an erosion wave out across the whole plain within 5 Myr.
