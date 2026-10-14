# ADR-0023: Derive Strahler order without forcing valley width

**Status:** Accepted
**Date:** 2026-09-04
**Deciders:** Project owner and Map Maker maintainers

## Context

The generated D8 channel mask is a connected tree, but its typed result records
only channel and channel-head membership. Contributing area controls the current
downstream width and depth progression. It does not explicitly describe whether
a reach lies below comparable tributaries or merely receives one small side
branch.

Horton-Strahler order supplies that topological distinction. First-order reaches
begin at channel heads. The order increases only when at least two tributaries
of the same highest order meet; a lower-order tributary joining a higher-order
reach leaves the downstream order unchanged. The measure is useful for network
inspection and later cartographic hierarchy, but it is sensitive to the chosen
channel-initiation threshold and does not by itself predict valley width.

An initial experiment added normalized order directly to the broad-valley
kernel. On the synthetic downstream-width fixture it widened an upstream
cross-section from five to six cells and erased the required downstream width
increase. Restricting order to a 3% centreline-depth term preserved that fixture
but raised the standard Tharkeniss diagnostic fill volume from 1,110.14 to
1,126.22 km3. Even a 1% term raised it to 1,115.50 km3. Those regressions are not
justified by a topology index alone.

## Decision

- Compute Horton-Strahler order on the selected generated D8 channel tree after
  channel initiation and downstream closure.
- Traverse cells in stable descending routing-surface order. Assign heads order
  one; propagate the largest donor order; increment it only when two or more
  donors share that largest order.
- Store zero outside the selected channel network and an unsigned 16-bit order
  inside it. Reject non-finite channel elevations, out-of-grid receivers, and
  channel receivers that do not descend on the routing surface.
- Retain the order raster in the internal typed `DrainageIncision` result for
  tests, future vector extraction, and later valley-character experiments.
- Do not change incision depth, shoulder width, residual-detail suppression, or
  the authoritative DEM from stream order in this decision. Drainage area and
  slope remain the active shaping controls.

## Options Considered

| Option | Topological information | Terrain risk | Decision |
|---|---|---|---|
| Continue with area alone | No explicit equal-tributary hierarchy | No new risk | Rejected as incomplete analysis |
| Use order as a second broad-width control | Explicit hierarchy affects visible valleys | Regresses the width fixture and can overstate extracted-network density | Rejected |
| Add a small centreline-depth boost | Explicit hierarchy affects visible valleys | Measurably worsens coarse Tharkeniss fill diagnostics | Rejected |
| Derive and retain order without shaping | Explicit, deterministic hierarchy | No numeric DEM change | Accepted |

## Trade-off Analysis

The accepted step improves the network model without pretending that topology
determines cross-section. Real valley and channel width also respond to
discharge, slope, confinement, lithology, sediment, tectonics, and bank
material. The current generator does not author those controls. Deferring the
visual effect therefore preserves the existing measured behavior while giving
future river export and terrain-character work a stable hierarchy primitive.

The order is relative to this generated channel mask, not an invariant property
of the landscape. Changing the area-slope initiation rule may change order even
when the underlying elevations remain identical. Consumers must keep the
channel-selection algorithm and threshold with the derived order.

## Consequences

- Equal-order tributaries and unequal tributary joins can now be distinguished
  deterministically in tests and later derived products.
- Existing generated elevations and Tharkeniss drainage metrics remain
  numerically unchanged.
- The typed internal result gains a stream-order raster, but no public project
  schema or authored source changes.
- A future visible-width experiment must combine hierarchy with explicit valley
  character or confinement and pass the downstream-width, rotated-network,
  nested-resolution, and Tharkeniss drainage gates.

## Action Items

1. [x] Implement and test deterministic Horton-Strahler ordering on the D8
   channel tree.
2. [ ] Include order in a future generated-river vector product and inspection
   overlay.
3. [ ] Add valley-character or confinement inputs before order can influence
   width or cross-section.
4. [ ] Measure order distributions when drainage-density profiles make the
   channel-initiation threshold user-configurable.

## Evidence

- Jasiewicz and Metz,
  [A new GRASS GIS toolkit for Hortonian analysis of drainage networks](https://doi.org/10.1016/j.cageo.2011.03.003),
  documents raster-network ordering algorithms and distinguishes Strahler,
  Horton, Shreve, and related hierarchies.
- Mileyko et al.,
  [Hierarchical Ordering of Reticular Networks](https://doi.org/10.1371/journal.pone.0036715),
  states the equal-order merge rule and places Horton-Strahler ordering in a
  general rooted-tree context.
- Buffington and Montgomery,
  [Geomorphic classification of rivers: An updated review](https://www.fs.usda.gov/rm/pubs_journals/2022/rmrs_2022_buffington_j001.pdf),
  notes that stream order provides a relative sense of channel conditions but
  depends on how the network is defined.

