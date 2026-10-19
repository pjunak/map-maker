# Curved against straight interpolation — 2026-10-19

Register entry: [T22](terrain-method-decisions.md#t22---draw-planet-relief-between-nodes-with-cubics-or-along-a-twist).
Catalog entry: D33 in the [decision catalog](decision-catalog.md).

## Question

Would map-maker describe geography better with curves instead of straight lines?
"Straight lines" here means triangle-linear interpolation between mesh nodes.

What is curved and what is straight today:

| Curved | Straight |
|---|---|
| Regional tiles are seeded from Clough-Tocher C1 cubics of their parent, held within each parent triangle's corner values (`smooth_sampler`, ADR-0086). | The planet surface itself: node heights, triangle-linear between nodes (ADR-0085). Every world map, globe texture and export samples it this way, so a Standard 200k build at 4,096 px shows its 50 km triangles as about 5 px facets. |
| Regional windows sample their tile blend along an area-preserving flow, a planar twist (`swirl`, ADR-0106). It bends valleys that ran straight along mesh edges. | Regional tile blends: triangle-linear on the tile mesh, though bent by the twist. |
| Regional rivers meander (D28); world-map rivers are Chaikin-smoothed. | Planet rivers follow mesh edges (`rivers.geojson`). |
| Coasts, lake shores, basin fronts and ice margins are noise-warped below the mesh spacing. | — |

The planet level has no twist. The question this report tests: would cubics or a
twist make the planet's relief, as world maps draw it, closer to real ground?

## Method

`benchmarks/planet/interpolation.py`
([command](../../benchmarks/planet/README.md)) hides detail and asks which
interpolant rebuilds it best.

1. **Sample.** A truth surface is sampled at the nodes of a coarse jittered
   Fibonacci mesh (seed 20261019, which no build uses). As on world maps, sea
   nodes hold 0.
2. **Rebuild.** Each variant rebuilds the surface on a raster in a 600 km
   window's azimuthal plane, at 1/8 of the coarse spacing.
3. **Score.** Rebuilds are scored on land at least one coarse spacing from the
   sea, inside the window circle.

Variants:

| Variant | What it is |
|---|---|
| **linear** | Triangle-linear, as world maps draw today (`sample_field`) |
| **cubic** | The product's clipped Clough-Tocher sampler (`smooth_sampler`) |
| **cubic-free** | The same cubics without the clip |
| **twist** | Linear, sampled along ADR-0106's flow (octaves at 2 and 1 coarse spacings, 0.15 of their wavelength) |
| **cubic-twist** | Clipped cubic, sampled along the same flow |

Metrics:

| Metric | Measures |
|---|---|
| Height RMSE; slope-vector RMSE; median slope over the truth's | Plain accuracy |
| Hillshade correlation with the truth | Likeness as the world map draws it: the product's `shading()` at its exaggeration of 13 |
| Crease ratio | Mean \|Laplacian\| within one pixel of a coarse triangle edge, over that inside triangles; the truth is about 1 |
| Straight-contour share | Share of sloped pixels (over 0.002) whose contours curve less than a circle of 10 coarse spacings |
| Pits per 10,000 km², filled share | False hollows |
| Overshoot | Height beyond the corner values of the pixel's coarse triangle (99th percentile) |
| River F1 | Agreement of D8 rivers routed over each surface (`grid_flow`, cells draining at least 5 coarse node areas) with the truth's, within 2 px |
| Straight-river share | Share of river cells whose next 8 steps keep one direction |

### Truths

- **Synthetic planet.** The fractal test world (`WorldSpec(seed=7)`) with its
  sample geology, built at 3.2M nodes (12.6 km) at `64574be`:
  - relief algorithm `sphere-mesh-stream-power-v31`, build `ed03c496…`;
  - coarse meshes of 200k nodes (50.5 km, the Standard preset) and 800k (25.2 km,
    Detailed): 4 and 2 times the truth's spacing;
  - eight windows, starting from the highest node at least 250 km inland, each
    then as far as possible from the others.

  The plan had an 800k truth with 50k and 200k coarse meshes. A finer truth
  against the app's own presets tests more.
- **Earth.** NOAA ETOPO 2022 60″ surface elevation:
  - file `ETOPO_2022_v1_60s_N90W180_surface.tif`, 465,969,062 bytes, sha256
    `9d27d4b8…fd08e`, public domain, doi:10.25921/fd45-gt74, from
    `https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO2022/data/60s/60s_surface_elev_gtif/`;
  - read bilinearly on a 6,371 km sphere, land above 0 m;
  - coarse meshes of 200k (50.5 km) and 800k (25.3 km);
  - nine windows: Alps, Himalaya front, central Andes, Appalachian
    Ridge-and-Valley, Zagros, Tibesti, Amazon lowland, Norway and the East African
    Rift.

  The DEM was downloaded for this run and deleted afterwards. It is not in Git.

### Pass rules, set before any run

A curved variant improves the results for world-map relief only if all four
rules hold, for both truths and both spacings, judged by the median over windows:

1. **Looks closer.** Hillshade correlation rises by at least 0.02, and slope-vector
   RMSE falls by at least 5 %.
2. **Fewer mesh lines.** The crease ratio and straight-contour share each close at
   least half the gap from linear to the truth.
3. **No harm.**
   - Height RMSE at most 2 % worse.
   - Pits at most 1.1 times the larger of linear's and the truth's.
   - River F1 at most 0.02 lower.
   - The free cubic's overshoot at most 50 m above the truth's own.
4. **Earth controls.** In the Appalachian and Zagros windows, which have real
   straight ridges, the straight-contour share stays within 20 % of the truth's.

Two refinements were made on the analytic test fixtures before any experiment ran:
- **Overshoot is compared with the truth's own.** Smooth hills already rise up to
  380 m above their triangle's corners between nodes, so excess over the corners
  alone is not an error.
- **The twist uses ADR-0106's actual octaves**, from 2 spacings down to 1. The plan
  had said down to 2 pixels, which misreads the ADR.

Twist variants move features, so no pass rule applies to them. Their
straight-line statistics are reported, with their accuracy as the cost.

## Results

**Earth**, nine windows, medians:

| At 50.5 km (200k) | Truth | Linear | Cubic | Cubic, free | Twist | Cubic + twist |
|---|---:|---:|---:|---:|---:|---:|
| Height RMSE (m) | 0 | 212 | 222 | 226 | 246 | 258 |
| Slope RMSE | 0 | 0.0202 | 0.0205 | 0.0205 | 0.0219 | 0.0225 |
| Hillshade correlation | 1 | 0.342 | 0.343 | 0.340 | 0.248 | 0.249 |
| Crease ratio | 0.99 | 29,319 | 2.00 | 1.88 | 1.21 | 1.08 |
| Straight-contour share | 0.014 | 0.227 | 0.058 | 0.053 | 0.040 | 0.041 |
| Pits per 10,000 km² | 9.2 | 0.92 | 0.18 | 0.68 | 1.37 | 0.34 |
| River F1 | 1 | 0.435 | 0.408 | 0.430 | 0.353 | 0.361 |
| Straight-river share | 0.011 | 0.127 | 0.071 | 0.059 | 0.041 | 0.025 |
| Overshoot p99 (m) | 533 | 0 | 0 | 112 | — | — |

| At 25.3 km (800k) | Truth | Linear | Cubic | Cubic, free | Twist | Cubic + twist |
|---|---:|---:|---:|---:|---:|---:|
| Height RMSE (m) | 0 | 139 | 151 | 154 | 155 | 158 |
| Slope RMSE | 0 | 0.0331 | 0.0338 | 0.0339 | 0.0340 | 0.0347 |
| Hillshade correlation | 1 | 0.337 | 0.339 | 0.341 | 0.279 | 0.290 |
| Crease ratio | 1.00 | 12,837 | 1.95 | 1.86 | 1.25 | 1.08 |
| Straight-contour share | 0.014 | 0.226 | 0.060 | 0.057 | 0.040 | 0.041 |
| Pits per 10,000 km² | 24.8 | 3.37 | 0.58 | 2.65 | 5.09 | 1.07 |
| River F1 | 1 | 0.431 | 0.440 | 0.432 | 0.395 | 0.404 |
| Straight-river share | 0.013 | 0.110 | 0.055 | 0.061 | 0.038 | 0.040 |
| Overshoot p99 (m) | 349 | 0 | 0 | 74 | — | — |

**Earth findings:**
- **Curves are less accurate.** The clipped cubic fits real ground worse in all
  nine windows at 50 km, by 1–8 %. At 25 km only Tibesti (−8.5 %) and the Rift
  (−0.6 %) gained. Inland windows lose as well, so it is not leakage from sea nodes
  held at 0.
- **They look no closer.** Hillshade likeness is unchanged, at 0.34.
- **The twist moves features off where they are.** Points move 16 km at 50 km
  and 7.8 km at 25 km.

**Synthetic planet**, eight windows, medians:

| At 50.5 km (200k) | Truth | Linear | Cubic | Cubic, free | Twist | Cubic + twist |
|---|---:|---:|---:|---:|---:|---:|
| Height RMSE (m) | 0 | 44.9 | 44.7 | 45.1 | 53.4 | 53.4 |
| Slope RMSE | 0 | 0.00455 | 0.00455 | 0.00455 | 0.00481 | 0.00484 |
| Hillshade correlation | 1 | 0.595 | 0.620 | 0.629 | 0.483 | 0.487 |
| Crease ratio | 1.00 | 21,341 | 1.91 | 1.71 | 1.21 | 1.04 |
| Straight-contour share | 0.030 | 0.266 | 0.086 | 0.083 | 0.050 | 0.050 |
| Pits per 10,000 km² | 1.14 | 0.50 | 0.08 | 0.35 | 0.76 | 0.18 |
| River F1 | 1 | 0.598 | 0.666 | 0.683 | 0.516 | 0.576 |
| Overshoot p99 (m) | 70 | 0 | 0 | 22 | — | — |

| At 25.2 km (800k) | Truth | Linear | Cubic | Cubic, free | Twist | Cubic + twist |
|---|---:|---:|---:|---:|---:|---:|
| Height RMSE (m) | 0 | 30.6 | 29.6 | 29.7 | 34.1 | 33.0 |
| Slope RMSE | 0 | 0.00473 | 0.00468 | 0.00467 | 0.00503 | 0.00493 |
| Hillshade correlation | 1 | 0.755 | 0.790 | 0.796 | 0.596 | 0.618 |
| Crease ratio | 1.00 | 10,653 | 1.85 | 1.61 | 1.15 | 1.04 |
| Straight-contour share | 0.100 | 0.293 | 0.091 | 0.090 | 0.049 | 0.050 |
| Pits per 10,000 km² | 2.23 | 1.45 | 0.24 | 0.89 | 2.41 | 0.43 |
| River F1 | 1 | 0.622 | 0.720 | 0.755 | 0.545 | 0.596 |
| Overshoot p99 (m) | 31 | 0 | 0 | 11 | — | — |

**Synthetic findings:** the generated planet favours cubics a little. Hillshade
likeness rises by 0.026–0.040, river agreement by 0.07–0.13, and height error
falls by up to 3 %. Slopes do not improve.

### Against the rules

| Variant | Truth | Looks closer | Fewer mesh lines | No harm | Controls |
|---|---|---|---|---|---|
| cubic | Earth 50 / 25 km | no (+0.001 / +0.003; slopes +1.2 / +2.0 %) | yes | no (height +4.7 / +8.8 %; F1 −0.027 at 50 km) | no |
| cubic | Synthetic 50 / 25 km | no (+0.026 / +0.035; slopes 0 / −1.0 %) | yes | yes | — |
| cubic-free | Earth 50 / 25 km | no | yes | no (height +6.4 / +11.1 %) | no |
| cubic-free | Synthetic 50 / 25 km | no (+0.034 / +0.040; slopes 0 / −1.2 %) | yes | yes | — |

**Verdict: curves do not improve the results.** No variant passes "looks closer"
on either truth, and on Earth they do harm.

The control rule failed, but it is uninformative at these spacings. The
Appalachian and Zagros ridges lie 5–15 km apart, below either mesh spacing. The
truth's straight-contour share there (0.014–0.023) is no higher than elsewhere,
so the rule cannot show whether curves erase straight ridges. Linear interpolation
is further from it (0.22–0.26) than the cubics (0.05–0.07).

The crops (truth, then each variant's hillshade; the harness writes them with `--crops`) show the same:
- On the Alps at 25 km, linear draws triangular facets, the cubics a smooth but
  blobby surface, and the twist crumpled swirls. None shows the Alps' ridge and
  valley grain.
- On the synthetic planet the cubics round volcanic cones closer to the truth,
  and the twist warps them.

## What this answers

- **Why curves don't help.** A mesh knows its nodes only, and real ground
  between 25–50 km nodes is rough. Valleys 5–15 km apart make node heights nearly
  independent samples, so cubic gradients estimated from neighbours add slope in
  the wrong places: median slopes rise from 0.49–0.50 to 0.53–0.59 of the truth's while
  accuracy falls. The generated planet is smoother below its spacing (45 m against
  Earth's 212 m height error at 50 km), so cubics help it slightly. Earth, the
  reference for realism, says no.
- **What curves would change.** Only the look of the mesh. Creases vanish (crease
  ratio 12,800–29,300 down to about 2) and straight contours fall from 0.23 to
  0.06, against Earth's 0.014. The world map would trade triangle facets for a
  smoother, rounder surface no closer to real ground. The atlas already covers the
  facets in part with display detail and valley carving, which add sub-mesh relief
  rather than smoothness.
- **What the twist would change.** It is the straightest-looking option (0.04,
  nearest to the truth) but the least accurate. At planet level it would also
  separate drawn rivers from their valleys: rivers are routed on the unwarped mesh,
  and river F1 drops by 0.04–0.08 on Earth. ADR-0106 works regionally because
  windows route their rivers after the twist.
- **Where realism comes from instead.** Information, not interpolation: finer
  builds (height error falls 35 % from 50 to 25 km on Earth), and sub-mesh detail
  from processes, which regional levels make.

## Limits

- Only the base surface is scored. World maps add display detail and valley
  carving on top, which these numbers leave out.
- The synthetic truth is itself triangle-linear at 12.6 km, a quarter and a half
  of the coarse spacings. Its own facets raise its straight-contour share at 25 km
  (0.10). At 60″ (1.85 km), ETOPO smooths what lies below 2 km.
- One seed per mesh; medians over eight and nine windows. Inner land is
  6.7–8.1 million km² per run.
- Run times: the 3.2M-node truth build took about 15 minutes; each scoring run took
  about a minute (`2be72aff…` source hash, Python 3.14.7).

## Disposition

**Rejected trial** for world-map relief: neither curved variant passed, on either
truth (T22, D33). The planet keeps triangle-linear relief (ADR-0085), and no
twist is added at planet level. Regional seeding (ADR-0086) and the regional twist
(ADR-0106) are unaffected.

Revisit when nodes carry more than heights, such as erosion's own slopes or
receivers for a Hermite surface. Revisit also if a smoother look is wanted for
Standard builds: compare it against display detail, not against the truth.
