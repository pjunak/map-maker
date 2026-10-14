# Documentation and research-status audit - 2026-09-13

Scope: the standalone `map-maker` terrain application, starting from `14c1087`.
The source worktree was clean. Campaign geography and historical ADR/research
findings are outside the edit scope.

## Corrections

- Replaced the root's removed project-v4 link with the current schema index.
- Updated product, architecture, adapter and test overviews for implemented
  regions, authored lake/dry intent, GeoTIFF, numeric reviews and durable builds.
- Distinguished numeric drainage review from river-vector/physical validation,
  and point-anchored profiles from deferred per-vertex authoring.
- Removed implications of world projection or completed parent/child refinement.
  GeoTIFF nodata now explicitly distinguishes SVG non-land from ground beneath
  authored water; that lake ground remains in the DEM.
- Split completed canonical routing from unfinished physical drainage policy in
  TODO; removed stale basin-label, authored-water and build-report backlog claims.
  Corrected benchmark coverage, partial regional controls and absent comparison UI.
- Consolidated duplicated tool-guide descriptions into links to their owners.
  Added [current research status](../research/status.md), retaining stable R IDs
  and dates of prior measurements/candidate support assessments.

## Verified current boundary

Project v5 and build v16 are the supported schemas. Water review and area transfer
are sampled, conservative review products, not physical lake storage/discharge.
Canonical routing/review still uses 257 nodes on its longest axis; finer output
pixels do not change that topology. Regional cuts and authored heights retain
their existing authority. No algorithm or file-format behavior changed here.

The checked runtime is Windows, CPython 3.14.7, NumPy 2.5.2, Pillow 12.3.0,
Shapely 2.1.2, svgelements 1.9.6, Rasterio 1.5.1 and Affine 3.0.1, with GDAL
3.12.4 and PROJ 9.8.1. SciPy, Landlab and Numba are not installed. Candidate
external research was classified by actual implementation/runtime evidence;
its upstream support and paper shortlist were not freshly re-researched.

## Validation and follow-through

Checked 377 local links (including five heading anchors) across all 92 Markdown
documents, including the two new reports; reviewed changed prose and
contract claims against schemas/source/tests, inspected Windows CI gates, and
verified `map-maker terrain build --help`. Accepted ADRs and dated research remain
historical evidence; no obsolete schema or compatibility loader was restored.
Prose-only validation does not imply a new GUI/GIS acceptance run.

The development follow-through targets repeated water-network preparation first.
The fresh-process baseline is recorded separately before code changes. Keep all
requested probes, complete budgets, Float32 heights, conservation and failure
records, and accept reuse only after focused/full tests and matching-input
performance comparisons. Broader sampling convergence, sill/storage and lake
chains remain the next behavior work in the [strategy](../strategy/README.md).


The [development follow-through](../research/2026-09-13-water-sampling-reuse.md)
records the subsequent implementation and its separate validation. The audit
above describes documentation reconciliation before that runtime change.
