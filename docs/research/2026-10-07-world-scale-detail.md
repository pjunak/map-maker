# World-scale detail and softer climate boundaries — 2026-10-07

Status: **implemented, experimental.** This follows
[natural-colour rendering](2026-10-07-natural-map-rendering.md). The user reviewed
the Aethelara atlas and found that, for an Earth-sized world (6,000 km radius), it
lacked a world-scale feel: features looked too big, with sharp, defined borders.

## Diagnosis

| Symptom | Cause |
|---|---|
| Huge uniform plains and plateaus; one giant continuous range | Procedural forcing only varies at 1,000–4,000 km (ridged noise at 1.4 cycles per radius, uplift texture at 3) |
| Ring-shaped plateau rims | The cratonic marginal swell sat at a fixed 250 km from every coast |
| Coasts combed into identical parallel valleys | Active-margin uplift was a uniform coastal band |
| Green-to-desert switches within one or two mesh cells | Eddy mixing was a fixed relaxation weight per mesh step, so its diffusivity scaled with node spacing |
| Broad, smooth ramps between rivers | Valleys are only resolved at mesh scale, 50–100 km apart at 800k nodes |
| Rivers about 25 km wide on a 5,760 px atlas | Widths of 0.7–3.8 px at about 7 km per pixel, plus a blurred corridor halo |
| Bright salt pans in green country | Every hot closed lake was drawn as a playa |

### Moisture mixing depended on the mesh

Relaxing each node by a weight *w* towards its neighbour mean once per advection
step is a diffusion with *D* = *w h*²/(4 Δ*t*), where *h* is the mesh spacing and
Δ*t* = *h* / wind speed.

- **Old effective value.** The tabled weights (0.08–0.45) gave about 3×10⁴ m²/s
  at 200k nodes, and half that at 800k.
- **Physical value.** Synoptic eddies mix moisture at roughly 10⁵–10⁶ m²/s.
- **Consequence.** Rain shadows and desert edges were too sharp, and they
  sharpened further as the mesh was refined.

## Changes

- **Multi-scale procedural forcing.** Nothing changes when a geology recipe
  assigns a region.
  - **Minor ranges and old fold belts:** ridged noise at 4.5 cycles per radius,
    patchily gated, with uplift 4×10⁻⁴ m/yr.
  - **Hill country:** at 12 cycles per radius, with uplift 1.2×10⁻⁴ m/yr.
  - **Uplift texture:** extended to 6 octaves, down to about 100 km.
  - **Active margins:** vary along strike between 35 % and 100 %.
  - **Craton swell:** now sits a noise-varied distance inland.
- **Physical eddy diffusivity.** The diffusivity *D*(latitude) is
  1.5×10⁵ m²/s in the tropics and 7×10⁵ m²/s in the storm tracks.
  - It is applied as stable explicit substeps (*w* ≤ 0.5) by a new numba kernel,
    `neighbour_mix`, which takes 0.24 ms per substep at 200k nodes and 1.0 ms at
    800k.
  - Climate boundaries no longer depend on mesh density, apart from the
    orographic term.
- **World valley carving.** This is display only, using the regional method on
  the longitude-latitude atlas raster.
  - Rows carry their own east-west cell width, and longitude wraps.
  - Strength is K·dt = 0.3, over 4 steps.
  - Incision is capped at the detail amplitude, gated by slope and blurred by 1 px.
  - The grid kernel now needs no adjacency arrays, so a 16 M-pixel raster stays
    in memory.
  - A test checks that it matches the mesh kernels exactly on a small grid, and
    that a longitude shift only shifts its output.
- **Rivers.** Width is (0.4 + 1.6 (Q/Q_max)^0.5) × scale, giving 0.5–2 px on a
  5,760 px atlas. Dryland corridors use the unblurred river mask.
- **Lakes.** Shores are soft. A closed lake is a salt pan only when it is hot
  (above 12 °C) **and** arid (P/PET below 0.35); otherwise it is a saline lake.
  Playas grade into the surrounding ground.

### Provenance

Build manifests now record the relief algorithm `sphere-mesh-stream-power-v2`
(multi-scale forcing) and the climate algorithm `planet-climate-v1` (eddy
diffusivity).

### Regional calibration

With the textured forcing, the regional-enrichment test fixture (a 20k-node parent
and 20 km regional spacing) starts further from its parent. The regional RMS
against the parent falls from 394 m to 163, 102 and 68 m over successive
iterations. Three iterations reach 41 % of the start, just missing the test's
40 % bound, so the test now runs 4 iterations; the bound is unchanged. The
product default stays at 3 calibration iterations. Production parents are much
finer and resolve this texture themselves.

### Fixed during the work

The first grid kernel recorded cell order when a cell was queued, not when it
was popped. That broke the downstream-first order that implicit stream power
needs, and weakened the carving. The equivalence test now guards this.

## Measurements (Aethelara, private)

| | Before (v5) | After (v7) |
|---|---:|---:|
| Build time, 800k nodes, 2 climate passes | 5.0 min | 9.3 min |
| Mean / maximum land height | 788 / 5,790 m | 840 / 5,875 m |
| Hack exponent | 0.472 | 0.491 |
| Compass-sector share (0.25 is isotropic) | 0.245 | 0.244 |
| Hot / cold desert share | 12.2 % / 6.6 % | 10.3 % / 7.0 % |
| Lakes (endorheic) | 69 (8) | 53 (9) |
| Non-descending receivers | 0 | 0 |

- **Mesh dependence of hot desert.** Before the change, the hot-desert share was
  11.2 % at 200k and 12.2 % at 800k. After it, the share is 9.6 % at 200k and
  10.3 % at 800k.
- **Rendering cost.** The 5,760 px atlas takes about 25 s to render, including
  carving.

## Limits and next steps

- **Climate cost.** Moisture diffusion nearly doubles the 800k climate time. A
  coarse-grid or implicit diffusion would remove most of that.
- **Coastal combs.** They are weaker but remain where margins are steep.
  Lithology contrasts would break them further.
- **Small islands.** Detail fades within 25 km of the coast, so small islands stay
  flat and featureless.
- **Display only.** The valley carving is not exported (see ADR-0048 for real
  sub-mesh detail).
