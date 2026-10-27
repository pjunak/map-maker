# Display valleys on world cells, and shared tile corrections — 2026-10-27

Decision: [ADR-0112 revision](../adr/0112-regional-waters-on-sphere-cells.md#revision-2026-10-27-display-valleys-on-the-cells).
Register: [T24](terrain-method-decisions.md#t24---share-uplift-corrections-between-overlapping-regional-tiles).
Catalog entry: D25 in the [decision catalog](decision-catalog.md).

## Question

After ADR-0112 and ADR-0113, two parts of the regional maps still worked in a
frame of their own:

- **Display valleys.** A window shades its relief with valleys carved by a few
  stream-power steps routed D8 over its own pixels.
- **Uplift corrections.** Each tile fitted its uplift correction for itself, the
  disagreement that remained between overlapping tiles
  ([world-fixed tile nodes](2026-10-26-world-fixed-tile-nodes.md#what-still-differs)).

Would moving either onto a field fixed to the world help, as moving tiles and
waters onto the sphere did?

## Display valleys on the routing cells

**Change.** At composition, the window samples its roughened relief at the
routing cells its hydrology has just built. It carves them with the same implicit
stream-power steps (`graph_carve`), and brings the incision back to the pixels from
the four nearest cells. Shading cuts that incision into the roughened relief as
before: capped at the detail amplitude, faded on flats and blurred. On a raster's
own pixels the graph kernel gives the pixel kernel's result exactly.

**Look.** Aethelara `planet-3200k-v31` at 56.869° E 30.703° N, cached
`planet-blended-tiles-v20` tiles:

- A 20 km province map (39 m pixels) had straight grooves at 0°, 45° and 90° down
  every smooth slope; on the cells they branch like gullies.
- A 30 km region map (58 m pixels) had vertical combs; on the cells it has
  dendritic gullies.
- At the usual scales, a 150 km province and a 600 km region, the maps look the
  same as before.
- The local map's basin plain has nothing to carve either way.

**Cost** (1,024 or 900 pixels, seconds; compose is a cached window's second run):

| Window | HEAD compose / relief render | Cells compose / relief render |
|---|---:|---:|
| Region, 30 km | 17.1 / 6.4 | 18.5 / 2.9 |
| Province, 20 km | 16.9 / 4.8 | 20.1 / 3.9 |
| Province, 150 km | 13.7 / 1.2 | 16.2 / 0.7 |
| Region, 600 km | 10.2 / 0.9 | 11.5 / 0.4 |

Carving moves from every render to composition. A window and its first map take
about as long as before, and every later theme renders faster. Carving a
1,024-pixel window's 0.93M cells takes 1.1 s, against 0.7 s on its pixels.
Triangulating such a disc alone took 1.8 s, which is why the hydrology's own cells
are reused.

**The world map** carves its longitude–latitude raster D8 too. At its 9 km pixels
on Aethelara the blurred incision shows no grid grooves at 30° or 66° N, so it was
left alone.

## Shared uplift corrections

**Trial.** Pass 1 builds tiles as now. Pass 2 erodes each tile once more with
the corrections of every tile covering its nodes, blended in log space with the
relief blend's weights: a field fixed to the world, identical wherever tiles
overlap.

Synthetic test planet, level 1 (four tiles around its land centre, three
calibration iterations), overlapping tiles' mean height difference at shared
nodes:

| Pair | Pass 1 | Pass 2 |
|---|---:|---:|
| 178–186 | 25.9 m | 18.9 m |
| 178–191 | 8.0 m | 0.8 m |
| 178–199 | 20.6 m | 37.0 m |
| 186–199 | 27.4 m | 8.9 m |
| 191–199 | 12.6 m | 23.5 m |
| Final calibration error per tile (RMS) | 18–31 m | 30–39 m |

Aethelara province tiles (18 covering tiles in pass 1):

| Pair | Pass 1 mean / max | Pass 2 mean / max |
|---|---:|---:|
| 7810–7954 (the worst) | 521 / 1,643 m | 259 / 879 m |
| 7954–8098 | 107 / 588 m | 111 / 644 m |
| 7865–8098 | 287 / 992 m | 312 / 729 m |

Calibration RMS per tile went 179 → 164, 233 → 226, 136 → 218 and 156 → 182 m, with
bias up to 48 m. A shared correction helps some pairs and hurts others. Each
tile's own correction had partly made up for its own drainage and domain, so a
borrowed one calibrates worse and moves the disagreement instead of removing it.
It would also need tiles built in two phases, with a ring of neighbours first.
Not adopted.

## A larger halo

Same four synthetic tiles, three iterations, halo 200 km (the test setting), 400
and 600 km:

| Halo | Nodes per tile | Pooled mean difference | 186–199 |
|---|---:|---:|---:|
| 200 km | 8,564 | 18.0 m | 27.4 m |
| 400 km | 11,089 | 15.9 m | 28.7 m |
| 600 km | 13,913 | 15.3 m | 29.8 m |

Catchments cut off at a tile's ring account for little of the difference. A larger
halo costs nodes in proportion and leaves the worst pair as it was. Not adopted.

## Conclusion

The display valleys were the last map layer worked out on window pixels, and the
same trick removes their grid grooves. The remaining tile disagreement has no such
fix: it comes from how sensitive erosion and calibration are, not from frames or
geometry. Closing it would take a joint solve or iterated exchange between
neighbouring tiles.

## Files

Kept locally in `artifacts/research-notes/tile-grid/`:

- `proto_carve.py`, `carve_check.py` and `carve_timing.py`, with images in
  `carve/` and `carve-prod/`;
- `shared_correction.py` and `halo_test.py`, with logs.
