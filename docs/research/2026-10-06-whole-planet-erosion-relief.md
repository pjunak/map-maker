# Whole-planet erosion relief on an irregular sphere mesh — 2026-10-06

Status: **experimental research harness** (`benchmarks/planet/`), not an accepted
world parent, and no change to local terrain builds.

> Later the same day the harness was promoted to `dmtools world planet`
> ([ADR-0085](../adr/0085-generate-planet-relief-on-a-sphere-mesh.md)) and its
> modules were removed. The commands and module paths below are historical; see
> Git history for the harness.

## Question

Can one process produce plausible relief **and** rivers that agree with it, for a
whole world (poles, longitude seam, ocean floor), directly from an imported world
coastline, without the grid bias and resolution dependence that blocked the
24 Sep Landlab reference (LE2) and the local channel-repair trials (T05–T13)?

## Method

1. **Test world.** `benchmarks/planet/synthetic_world.py` writes a deterministic
   fractal world SVG in the importer's full-sphere Plate Carrée convention and
   saves it through the normal `save_world` path. Seed 7: 6 continents, 30 % land
   coverage, a polar continent touching latitude 90°, inland seas, island chains
   and a seam-crossing landmass. The public examples are a few hand-placed
   polygons and cannot exercise these cases.
2. **Mesh.** Jittered Fibonacci nodes (0.35 node spacing tangent jitter),
   spherical Delaunay triangulation from their convex hull, CSR neighbours,
   great-circle edge lengths, barycentric dual areas and cotangent Laplacian
   weights. There is no pole, seam or preferred direction.
3. **Inputs on the mesh.**
   - Land is the vector point-in-polygon of prepared world land at each node.
   - Coast distance is a multi-source graph Dijkstra from land/water edge midpoints.
   - Forcing is procedural because the test world has no geology recipe:
     - ridged-noise orogenic belts faded within 150 km of the coast;
     - noise-gated active-margin strips;
     - weak craton uplift increasing inland;
     - log-normal erodibility variation of about ×3.
4. **Evolution**, every step (`benchmarks/planet/evolve.py`):
   - Priority-Flood from all water-adjacent nodes. Closed depressions are filled, as sediment-filled basins.
   - Steepest-descent receivers on the filled surface.
   - Drainage area accumulated in filled-elevation order.
   - Braun–Willett implicit stream power, n = 1, m = 0.45.
   - Water nodes are held at sea level and land is kept ≥ 1 m, so the authored coast cannot move.
5. **Process scale.** Each node adds a constant 10,000 km² sub-grid drainage area
   (`--process-km2`). The world level therefore resolves rivers above a fixed
   physical scale instead of above one mesh cell.
6. **Ocean floor.** Shelf, slope and abyss depth from coast distance, with ridge and hill noise. It is display-only and does not affect land evolution.
7. **Kernels.** Numba 0.68 compiled graph kernels. Runtime: Python 3.14.7, NumPy 2.5.2, SciPy 1.18.1, Windows, 16 logical CPUs.
8. **Metrics** (`benchmarks/planet/metrics.py`):
   - area-weighted land hypsometry;
   - flow-azimuth isotropy: share of flow within ±5.6° of the 8 compass directions, where 0.25 means unbiased and D8 means 1.0;
   - Hack's-law exponent of longest flow length against area;
   - count of receiver edges that do not descend.

## Results

### Without a process scale (run 001 and the first sweep)

The settings were K = 2·10⁻⁶ for 20 Myr in run 001, and K = 4·10⁻⁶ for 30 Myr in the sweep. Relief grows with resolution:

| Nodes | Spacing | Land mean | p95 | Max | Hack h | Compass share | Uphill edges | Evolve time |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50,000 | 101 km | 594 m | 2,406 m | 5,838 m | 0.560 | 0.246 | 0 | 1.4 s |
| 200,000 | 50.5 km | 698 m | 2,859 m | 7,491 m | 0.573 | 0.251 | 0 | 6.3 s |
| 800,000 | 25.3 km | 822 m | 3,349 m | 9,655 m | 0.593 | 0.245 | 0 | 30.9 s |

**Cause:** the head slope S = U / (K·A^m) depends on the smallest drainage area, which is one mesh cell.

### With a fixed 10,000 km² process scale (K = 4·10⁻⁶, 30 Myr, 300 steps)

| Nodes | Spacing | Land mean | Median | p95 | Max | Share > 2 km | Hack h | Compass share | Uphill edges | Evolve time |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50,000 | 101 km | 511 m | 184 m | 2,058 m | 5,270 m | 5.4 % | 0.565 | 0.244 | 0 | 1.4 s |
| 200,000 | 50.5 km | 518 m | 176 m | 2,136 m | 5,417 m | 5.9 % | 0.560 | 0.253 | 0 | 6.3 s |
| 800,000 | 25.3 km | 515 m | 175 m | 2,141 m | 5,775 m | 6.0 % | 0.531 | 0.243 | 0 | 31.4 s |

- **Convergence.** Across a 4× change in spacing, mean land elevation changes by 7 m and p95 by 83 m.
  - Only the maximum keeps rising slowly, which is expected: finer sampling resolves narrower summits.
  - The Landlab reference changed 42–52 m in mean and about 570 m in maximum between cell sizes, without converging.
- **Rivers.** Every land node has a strictly descending receiver at every resolution. Because routing uses mesh edges, triangle-linear (TIN) interpolation along any river edge is monotone, so the TIN surface has no hidden rises.
- **No grid bias.** The compass-sector share is 0.243–0.253 against 0.25 for unbiased flow.
- **Branching statistics.** Hack exponents of 0.53–0.57 fall in the commonly reported 0.5–0.6 range for natural basins.
- **Cost.** The whole planet takes seconds at 50 km and about 31 s at 25 km for 300 implicit steps. Mesh and fields take another 13 s at 800k nodes.

Run 001 image (200k nodes, no process scale): dendritic networks, eroded belt
flanks, seam-free polar and seam-crossing continents. Generated images remain in
ignored `artifacts/planet/`.

### Geology recipe as calibrated forcing

`benchmarks/planet/geology.py` maps each resolved geology region (province or
continent default) to forcing:

- **Uplift and erodibility.**
  - Setting erodibility factors: active belt 1.0, volcanic 0.8, stable interior 0.5, rift 1.4, sedimentary basin 2.5.
  - Crust older than 1,000 Ma takes a further ×0.7.
- **Elevation intent.** The intent is the explicit landform, or else a default implied by the setting:
  - plain: mean = elevation;
  - hills: mean = elevation + 0.4 × relief;
  - plateau: median = elevation;
  - mountains: p90 = elevation + 0.75 × relief.
- **Mountain-building age.** Relief is scaled by exp(−age / 120 Myr), with a floor of 0.12, so older belts are lower and smoother.
- **Plateaus** get a block uplift pulse in the final 20 % of the history. They therefore stay as uplifted, little-dissected surfaces whose edges are being incised.
- **Region boundaries** are smoothed over half the median transition width.
- **Calibration.** For n = 1, steady elevation is linear in uplift. Each calibration step rescales a region's uplift by target ÷ measured, clamped to ×0.33–×3.

Test: the sample recipe on the fractal world (`sample_geology.py`). It has two old stable continents, each with a young belt (15 Ma), a worn belt (320 Ma), a plateau and a sedimentary basin; the other continents stay procedural. Results at 200k nodes, with 4 runs (3 corrections) in 57 s in total:

| Region (Aldmark / Brennhal) | Target | After 1st run | After 3 corrections |
|---|---:|---:|---:|
| Plateau (median) | 2,200 m | 1,195 / 870 m | 2,203 / 2,200 m |
| Young belt (p90) | 3,018 m | 1,208 / 2,043 m | 3,025 / 3,016 m |
| Worn belt (p90) | 1,188 m | 748 / 789 m | 1,164 / 1,189 m |
| Sedimentary basin (mean) | 120 m | 19 / 34 m | 115 / 122 m |
| Continent default (mean) | 380 m | 341 / 317 m | 380 / 380 m |

Rivers still have zero non-descending receivers.

**Visible limitation:** uniform uplift over a large stable interior makes a smooth
dome drained by rivers running outward from the centre. This needs low-amplitude
uplift texture within regions.

## Limits and open questions

- Geology mapping constants are first choices, not calibrated against Earth data.
- Closed basins are always filled. There are no lakes, endorheic basins or arid retention.
- Runoff is uniform: no climate.
- At these scales hillslope diffusion is negligible and disabled.
- The ocean floor is a display model, with no coupling or isostasy.
- Erodibility and process scale set absolute relief. The settings here produce a mean of about 515 m and a maximum of about 5.5 km. They are calibration choices, not physical predictions.
- Tolerance-free determinism is shown on one machine only (an exact repeat test).
- The surface authority for a whole-planet product (mesh nodes plus TIN, rasters derived) needs an ADR before promotion.

## Conclusion

Adopt this process family as the M2 relief candidate, and promote it to the
application after it consumes geology recipes. The reasons:
- It addresses the integrated failures (river/ground disagreement, D8 bias, grid dependence, poles and seam) by construction rather than by repair.
- It is cheap enough to iterate in Python with compiled kernels.
