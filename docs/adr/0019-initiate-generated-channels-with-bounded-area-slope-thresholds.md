# ADR-0019: Initiate generated channels with bounded area-slope thresholds

**Status:** Accepted
**Date:** 2026-09-04
**Deciders:** Project owner and Map Maker maintainers

## Context

ADR-0015 and ADR-0016 select generated valley centres wherever D8 contributing
area exceeds one continent-wide threshold. This produces connected downstream
structure, but it treats steep mountain hollows and broad gentle plains alike.
Channel-head research instead observes an inverse relation between source area
and local slope, and DEM extraction methods commonly test a function of area
and slope.

Applying an unbounded `A*S^2` rule is not safe for this generator. The canonical
grid covers heterogeneous fantasy continents without climate, soil, lithology,
or runoff inputs. A steep range can set a reference that prevents even very
large low-gradient rivers from initiating in adjacent plains. Local slope is
also grid-scale and imperfect. The result needs the useful direction of the
relation without claiming a universal physical threshold.

## Decision

- Retain the fixed 257-cell-longest-side Priority-Flood routing surface and D8
  receiver tree.
- Smooth D8 receiver slope once on land before evaluating channel initiation.
- Use the 65th percentile of eligible positive slopes as a deterministic
  within-continent reference, with a minimum reference grade of 0.001.
- Start from the existing area threshold and scale it by
  `(reference_slope / local_slope)^2`, but clamp that area multiplier to
  `[0.35, 4.0]`. Steep source terrain can therefore initiate with less area,
  while sufficiently large gentle drainage always remains eligible.
- Require at least four canonical cells or 0.025% of land area before a cell
  can initiate a channel. This keeps single-cell slope noise from creating
  continental valleys.
- Trace every initiated cell downstream through the existing D8 receivers.
  The final channel mask is the union of those paths, including low-gradient
  trunk reaches that do not independently pass the headwater criterion.
- Add a bounded 0-8% logarithmic relief ramp between the minimum source area
  and the established area threshold. Above it, retain the existing hierarchy.
  Newly selected steep headwaters therefore gain visible relief without becoming
  as broad as downstream trunks.
- Define channel heads as selected cells without an upstream selected donor.
  Retain channel and head masks as internal typed diagnostics for tests.

## Options Considered

| Option | Complexity | Headwater realism | Large plain rivers | Determinism | Decision |
|---|---:|---:|---:|---:|---|
| One contributing-area threshold | Low | Low | Strong | Strong | Replaced |
| Unbounded `A*S^2` threshold | Low | Medium in calibrated terrain | Poor across heterogeneous terrain | Strong | Rejected |
| Bounded area-slope threshold plus downstream closure | Medium | Better | Preserved | Strong | Accepted |
| Curvature or learned channel-head classifier | High | Potentially high | Unknown | Input-dependent | Deferred until finer terrain and calibration data exist |

## Trade-off Analysis

The accepted rule is process-informed rather than calibrated hydrology. Its
bounded slope multiplier prevents extreme local gradients from dominating the
network, and downstream closure makes connectivity an invariant instead of an
accidental consequence of thresholding. The cost is a small set of explicit
empirical constants. Those constants remain internal until climate, lithology,
and local-refinement profiles can justify public controls.

## Consequences

- Steeper convergent terrain develops channel heads with smaller contributing
  areas than otherwise comparable gentle terrain.
- Large rivers continue through low-gradient reaches and every non-outlet
  channel cell has a selected downstream receiver.
- Generated valley locations change, so the automatic-valley algorithm is not
  numerically compatible with builds produced before this decision.
- D8 direction bias and the fixed canonical scale remain. Local-map drainage
  still requires a buffered finer hierarchy tied to the parent network.
- The rule does not model rainfall, infiltration, substrate failure, perennial
  flow, or actual river discharge.

## Action Items

1. [x] Implement bounded area-slope initiation, downstream closure, typed
   channel/head masks, and deterministic fixtures.
2. [ ] Expose drainage-density controls only through a versioned terrain
   profile with explicit scale and process meaning.
3. [ ] Compare channel heads and drainage density against selected real DEMs or
   mature GIS adapters before assigning Earth-like interpretations.

## Evidence

- Montgomery and Dietrich,
  [Channel initiation and the problem of landscape scale](https://doi.org/10.1126/science.255.5046.826),
  1992, identifies a topographic channelization threshold separating smooth
  hillslopes from valley bottoms.
- Montgomery and Dietrich,
  [Source areas, drainage density, and channel initiation](https://doi.org/10.1029/WR025i008p01907),
  1989, reports the inverse relation between channel-head slope and source area.
- Orlandini et al.,
  [Prediction of channel heads in complex alpine terrain](https://doi.org/10.1029/2010WR009648),
  2011, reviews contributing-area and `A*S^k` channel-initiation criteria.
