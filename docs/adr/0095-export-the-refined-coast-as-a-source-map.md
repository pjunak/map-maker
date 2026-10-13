# ADR-0095: Export the refined coast as a source map

- Status: accepted (experimental product path)
- Date: 2026-10-13
- Builds on ADR-0090 (regional coast detail, with its 2026-10-13 revision),
  ADR-0094 (polar land in true distance) and ADR-0070 (retained world source).

## Context

Zoomed maps draw a world's coast with detail below the drawing's precision, and
the planet works polar land in true distance. That coast exists only inside the
pipeline: the author cannot see it in their drawing program, edit it, or adopt
it. A one-off script traced Aethelara's refined coast into an SVG that imported
as a cleaner source map with the same geography, but it had to be imported by
hand, labelled 160 of its 180 shapes as mainland (its island groups were not
named `islands`), and merged continents that share a land border.

## Decision

1. **`dmtools world refine-coast`** traces a world's coast as zoomed maps draw it,
   down to a chosen detail (10 km by default), including the planet's polar land,
   and writes it as a new SVG source map. The master seed is the planet's, since
   the detail depends on it. The destination must not exist.
2. **Ownership by territory.** Every traced cell belongs to the drawn shape it
   lies in, or the nearest one. These territories, simplified as one coverage,
   cut the traced land, so continents that share a land border stay apart and
   every shape keeps its continent and role.
3. **Round trip.** The SVG keeps the source's view box and its continent,
   *Land Shapes*, *mainland* and *islands* groups, and declares the detail it
   carries on its root (`data-dmtools-coast-detail-km`). Importing it fills in
   the world's coast detail (ADR-0090 revision), so zoomed maps add only finer
   detail. The export is refused if the importer could not read it back (point
   or size limits), and checked by parsing it before it is written.
4. **Adoption stays the author's.** The export is a new file; the authored world
   is unchanged until the author imports the export as a world.

## Consequences

- On Aethelara (45–55 s): 195 shapes (185 islands), about 400,000 points; every
  continent keeps its area within 0.2 %, except the southern one, which gains
  the land the planet adds at the pole; the import needs no adjustments.
- An imported export can be refined again to finer detail; its coast detail is
  then the finer of the two.
- Exports carry land only. Other layers of a drawing are not copied.
- Drawing programs may drop the root declaration when they re-save; the World
  tab then needs the coast detail entered by hand.

## Alternatives considered

- **Assigning each traced shape to the drawn shape it overlaps most.** Rejected:
  it gives continents that share a land border to one of them.
- **Smoothing each continent's outline separately.** Rejected: shared borders
  would open gaps or overlaps; one coverage keeps them identical.
