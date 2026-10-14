# ADR-0021: Correct broad valleys with MFD convergence

**Status:** Accepted
**Date:** 2026-09-04
**Deciders:** Project owner and Map Maker maintainers

## Context

ADR-0016 uses a D8 receiver tree to provide one connected generated channel
centreline and repeated masked smoothing to provide its broad shoulders. The
tree is useful for topology and downstream floor conditioning, but a single
steepest neighbour is directionally quantized. In a smooth synthetic valley it
can place parallel branches on either side of the true convergence minimum.
The seven-pass shoulder blur hides part of that gap, but it is an image-space
operation rather than a hydrologic observation and can spread toward a nearby
divide.

The same routing stage already computes multiple-flow-direction (MFD)
contributing area. MFD represents broad convergence without requiring a second
network or a new dependency. The question is how much of that continuous field
should affect visible incision without replacing the connected and conditioned
D8 channel contract.

## Decision

- Keep the selected D8 channel, two-pass near shoulder, seven-pass trunk
  shoulder, detail-suppression field, and downstream floor correction.
- Normalize MFD area logarithmically from the existing channel-area threshold
  to the largest MFD catchment on the canonical grid.
- Raise that progression to `2.5`, then multiply it by the existing bounded
  slope response. This concentrates the correction on established convergent
  trunks instead of widening headwaters prematurely.
- Add the resulting convergence field to generated incision with a weight of
  `0.04`. It corrects broad cross-section placement but does not become a
  second centreline or receive independent floor authority.
- Leave residual-detail suppression unchanged. MFD changes the broad generated
  valley shape only; it does not erase additional authored or stochastic
  relief.
- Continue applying the coastline gate, local-elevation incision limit, and
  bounded D8 floor conditioning after the combined field is formed.

## Options Considered

| Option | Benefit | Failure or cost | Decision |
|---|---|---|---|
| Keep only D8 plus isotropic smoothing | Preserves current results | Retains the measurable D8 centre gap | Rejected |
| Assign every hillslope cell to its first downstream D8 channel | Cannot cross a D8 divide | Leaves real convergence minima blank when D8 branches straddle them | Rejected |
| Replace the broad trunk kernel with MFD progression | Removes the broad image blur | Regressed Tharkeniss coarse sinks, connectivity, and fill volume | Rejected |
| Add a high-order, low-weight MFD correction | Improves convergence placement while retaining the conditioned tree | Deliberately modest; does not eliminate isotropic shoulders | Accepted |

## Trade-off Analysis

This is a conservative hybrid rather than a pure flow-connected cross-section
solver. A HAND-inspired downstream association was prototyped first, but the
unique D8 tree made it too brittle: cells on the actual synthetic valley
minimum could reach a selected channel only much farther downstream and
received no local shoulder. MFD was already the less directionally biased
signal for that case.

A full MFD replacement passed local shape tests but worsened the completed
Tharkeniss diagnostic. The accepted 4% correction is intentionally small. It
raises incision at the known synthetic D8 centre gap from 3.50 m to 6.23 m
while preserving downstream widening. In the two-valley fixture, both valleys
remain incised and the intervening divide receives exactly zero automatic
incision and detail suppression.

## Consequences

- Generated broad valleys respond to actual MFD convergence as well as the D8
  channel hierarchy; D8 remains the unique network used for connectivity and
  downstream floor guarantees.
- On default Tharkeniss at the aligned 257 grid, terminal cells remain 94,
  basin candidates remain 80, direct connectivity changes from 88.1663% to
  88.1663% at displayed precision, and estimated fill volume changes from
  1,578.99 to 1,579.01 km3.
- The standard 129-grid report retains 22 terminal cells, 22 basin candidates,
  and 88.4108% direct connectivity. Estimated fill volume changes from
  1,093.60 to 1,104.18 km3, illustrating that coarse resampling remains
  sensitive to narrow elevation differences.
- Generated elevations change and are not numerically compatible with builds
  made before this decision.
- The broad shoulder still includes a masked smoothing component. Replacing it
  requires a cross-section solver that handles D8 aliasing without worsening
  completed-surface drainage.

## Action Items

1. [x] Add the bounded MFD convergence correction and fixtures for the D8
   centre gap, downstream widening, and an intervening divide.
2. [ ] Add an inspection overlay for D8 channels, MFD convergence, and their
   combined generated-valley field.
3. [ ] Compare D-infinity or contour-aware cross-sections before removing the
   remaining broad smoothing kernel.

## Evidence

- Prescott et al.,
  [A comparison of flow-routing algorithms for digital elevation models](https://esurf.copernicus.org/articles/13/239/2025/),
  compares single- and multiple-flow-direction routing behavior.
- Rennó et al.,
  [HAND, a new terrain descriptor using SRTM-DEM](https://doi.org/10.1016/j.rse.2008.03.018),
  motivates flow-connected height relationships while also showing why such a
  descriptor is not itself a valley-generation law.
- Pelletier,
  [A robust, two-parameter method for the extraction of drainage networks from high-resolution digital elevation models](https://doi.org/10.1029/2012WR012452),
  supports combining drainage area with local topographic evidence rather than
  treating a single raster threshold as complete valley geometry.
