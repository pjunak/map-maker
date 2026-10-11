# Regional coast detail below the drawing's precision — 2026-10-11

Decision: [ADR-0090](../adr/0090-regional-coast-detail-below-drawing-precision.md).
Catalog entry: D29 in the [decision catalog](decision-catalog.md).

## Problem

Regional windows tested land against the exact vector coastline. Aethelara's frame
is 2,880 drawing units for a 6,000 km radius, so one unit is 13.1 km. The SVG is a
smoothed pixel tracing: 35,444 cubic segments and 4,146 lines, flattened to 47,017
vertices about 0.78 units (10 km) apart. Its curves follow pixel steps about
2 units (25–30 km) long.

At province (1 km) and local (200 m) zoom this coast was a set of straight runs
with sharp tracing corners: horizontal and 45° segments tens of kilometres long.
This is 65 times finer than the drawing resolves.

## Method trials (land masks, 768 px windows of 300, 60, 12 and 3 km radius)

| Trial | Result |
|---|---|
| Domain warp, amplitude ∝ wavelength^0.75, top 50 km / 4 km | Too smooth at 60 km; tracing corners survive at every zoom. |
| Same, top 100 km / 8 km, Hurst 0.6 | Coast wobbles, but small octaves become blobby overhangs (amplitude/wavelength reaches 0.7 at 400 m). |
| Self-similar warp (amplitude = 0.12 × wavelength), top 64 km | No overhangs, but traced corners are carried into every zoom unchanged. |
| Plus arc-length Gaussian smoothing of the drawing, 0.3 units | Corners rounded; mid scales still look like a smooth curve with fine jaggies. |
| **Chosen:** top 8 units / 0.6 units, Hurst 0.4, capped at 0.25 × wavelength, smoothing 0.3 units | Rugged, self-similar coast at every window size; islets and coves appear; displacement within about one drawing unit. |

Smoothing the drawing takes 2.2–4.4 s once per world and process, and it is cached.
The warp costs 3 noise evaluations per octave and point.

A scale-free roughness measure counts the cells that a 4-pixel blur and
re-threshold would flip, which is few for a smooth curve. On the 512-column
synthetic test world, refined coasts score 3–8 times the drawn coast at four
coast points in 40 and 120 km windows. The regression test asserts more than 3
times.

## Aethelara before and after (3.2M-node build, level 2 and 3 windows)

The renders used the same planet build and settings. Before is commit `e5fed17`
(`planet-blended-tiles-v5`); after adds the refined coast (`-v6`). Both ran from
source snapshots.

- **Temperate west coast (−124.29°, 35.88°), province (40 km).** The before image
  shows a straight horizontal run and a 45° run with right-angle steps. After, the
  coast has a headland, a shallow bay and ragged rocky edges, with no straight run.
- **Same place, local (10 km).** Before, two straight edges meet in one corner.
  After, a ragged bay curves through the window. The coast lies a few kilometres
  landward of the drawn line here.
- **Northern coast (74.87°, 65.75°), province (40 km).** Before, the shore is
  faceted with 10–20 km straight edges. After, it is a continuous rugged shore
  with coves.
- **Same place, local (10 km).** Before, two straight edges meet at a corner.
  After, a ragged shore with small coves crosses the window.

The images are local artifacts, not tracked in the repository
(`artifacts/aethelara/coast/cmp-*.png`).

## Limits and follow-ups

- Roughness is uniform. Real rocky, uplifted coasts are more indented than
  sedimentary ones, and bays form at drowned valley mouths. Coupling roughness
  to a planet field must stay identical across levels, so it is deferred.
- Sea shading is flat up to the shore. A shallow shelf that follows the refined
  coast would make it read better.
- Places drawn within about one drawing unit of the coast can end up inland or
  offshore at regional zoom.
