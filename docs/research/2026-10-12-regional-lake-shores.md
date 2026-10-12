# Regional lake shores — 2026-10-12

Decision: [ADR-0092](../adr/0092-regional-lakes-fill-the-regional-relief.md).
Catalog entry: D30 in the [decision catalog](decision-catalog.md).

## Problem

Level-1 windows of the Aethelara 800k build (`planet-800k-final`, parent spacing
23.8 km) drew lakes and salt pans with straight shores 25–50 km long. The test
window is centred at 85.76°, 22.74°, radius 250 km, 900 pixels (556 m), in an
impact crater. Its three pale pans on the crater floor are closed lakes of one
or two parent nodes each.

## Causes found

- **The shore was the parent cover contour.** Around two of the three pans,
  95–97 % of the pixels just outside the shore were excluded by the cover gate
  (cover ≤ 0.15, or ≤ 0.01 in the crater zone), not by height: the relief there
  lay a median 180–250 m below the lake level. One node's triangle-linear cover
  is a hexagonal pyramid, so the shore was a hexagon or two.
- **Tiles held crater lakes in the wrong frame.** Tiles erode the surface without
  young landforms (crater relief −1,330 to −1,370 m at these nodes) but held
  lake nodes at the full level. Window relief inside the pans was 15–1,230 m
  below the level (1st–99th percentile; median 560 m). Tiles eroded towards
  these pits, which made the surrounding crater floor rugged, with
  straight-sided facets.
- **Tile lake flats trace the parent contour.** Held nodes are those with cover
  above 0.5, so even shores drawn from the relief alone followed the parent's
  straight contour at tile resolution.

## Measurements

The straightness measure bins shore pixels (lake pixels next to dry land, not
the window edge) into 1.5-pixel bands in 180 directions. It reports the longest
run along one band with gaps of at most 2 pixels, and the share of shore pixels
in runs of at least 25 pixels. Windows are 900 pixels at level 1; the crater
window has 556 m pixels, the others 333 m.

| Window | Before (`-v6`) | Relief flood, frame fix | Plus refined outlines (`-v7`) |
|---|---|---|---|
| Crater pans (85.76°, 22.74°) | 55.5 %, 54 px | 7.9 %, 31 px | 6.5 %, 33 px |
| Open lake, 17 nodes (69.11°, 45.05°) | 25.4 %, 65 px | 17.8 %, 38 px | 13.7 %, 37 px |
| Open lakes, 24 nodes (73.51°, 58.48°) | — | 22.0 %, 47 px | 19.4 %, 39 px |
| Open lake, 14 nodes (93.33°, 32.51°) | — | 28.7 %, 35 px | 22.2 %, 32 px |

The remaining runs lie on smooth or planar slopes of the level-1 relief, for
example the east shore of a crater pan on a uniform 5 m-per-pixel ramp.

Other findings:

- **Spill test.** Without it, the 14-node open lake ran down its outlet valley:
  7 % more water, reaching 1.48 instead of 1.12 parent spacings from a lake node.
- **Closed lakes as sinks.** Once the pits were gone, the crater trough became
  one closed basin 960 m deep. The playa rule (the lowest quarter of a basin)
  then covered 68,000 pixels of trough floor. Routing into the closed lakes
  leaves playas only in other hollows (4,300 pixels; 1,900 before the change).
- **Lake area.** The window's four closed lakes cover 13,200 pixels after the
  change, against 20,500 before; their six parent nodes span 10,700 pixels.

The images are local artifacts, not tracked in the repository
(`artifacts/aethelara/lake-shores-*.png`).

## Open-lake shores — 2026-10-13

Open lakes whose window basin spills above the lake's level drew a pale playa
ring along the shore where it is dry, and a band of pond water where it is wet.
Routing passes through open lakes, so their basin filled up to its pour point,
and the ground from the shore to 10 m below that point counted as ponds. Ponds
are now measured with every lake as a sink.

That alone exposed rivers crossing the filled basin towards the pour point,
some running along the shore for over 100 km instead of entering the lake.
Routing now lowers each open lake's outflow to the lake's level: up the basin
floor from the lake to the pour point, then along the routed path until the
filled relief is down to the shore. The floor path follows receivers with
every lake a sink, from the pour point down into the lake. Lowering the routed
path across the basin instead left the valley floor beside it draining back
towards the lake, so two rivers ran in parallel for about 200 pixels.

Level-1 windows of radius 150 km, 900 pixels (333 m). *Ringed* is the share of
open-lake shore pixels within 2 pixels of playa or pond water. *Shore rivers*
counts river pixels within 4 pixels of an open lake.

| Window | Before | Ponds with every lake a sink | Plus lowered outflows |
|---|---|---|---|
| 69.11°, 45.05° (dry) | ringed 100 %; playa 26,385 px; shore rivers 12 px | 0 %; 0; 189 px | 0 %; 0; 80 px |
| 73.51°, 58.48° (wet) | ringed 92 %; pond water 25,636 px, playa 3,989 px; shore rivers 88 px | 0 %; 0; 386 px | 0 %; 0; 52 px |

- All but one of the 56,013 removed playa or pond pixels were connected to an
  open lake.
- The ring had hidden most shore rivers, hence the low counts before.
- Wet ponds no longer widen open lakes: water in the 73.51° window fell from
  163,415 to 137,779 pixels, the open lakes alone.
- The crater window (85.76°, 22.74°), whose lakes are all closed, is
  pixel-identical.

Images: `artifacts/aethelara/lake-ring-*.png`.

## Limits and follow-ups

- Shores are as fine as the level's relief and outline octaves: level 1 is
  smooth below about 10 km.
- An open lake's outflow is lowered for routing only. Where its window basin
  spills above the lake's level, the outflow river crosses a pass that the
  displayed relief does not cut.
