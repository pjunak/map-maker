# Complete documentation file inventory

Updated 2026-09-28. Scope: every version-controlled Markdown document in DM Tools,
plus the vendored license notice, including world-source implementation and
export-import correction, bounded preparation and geographic context documents. Generated builds, caches, dependency
documentation and private campaign files are excluded. The public JSON schemas and reference dependency
lock are listed separately as supporting contracts, not counted as prose docs.

**211 Markdown files + 1 legal notice = 212 documentation files.**
Each file appears once below, including this inventory. Document titles describe
their subject; the group description identifies their role and authority.

For implementation order, start with the main M1-M8 plan; for prior conclusions,
start with the research decision catalog. Follow links into the WC/LE model plans,
quality reference and original reports on demand. The selective reading guide
remains the entry point for normal use. Every document is linked below.

| Group | Files |
|---|---:|
| Project entry and guidance | 4 |
| Active plans and indexes | 13 |
| User guides and current contracts | 19 |
| Developer and reference guides | 8 |
| Architecture decision records | 84 |
| Dated research reports | 81 |
| Maintenance reports | 2 |
| Legal notice | 1 |
| **Total** | **212** |

## Project entry and guidance (4)

Contribution instructions and repository entry points; these are not terrain settings.

| File | Purpose or document title |
|---|---|
| [AGENTS.md](../AGENTS.md) | Repository contribution, scientific integrity, validation and Git instructions. |
| [README.md](../README.md) | Product status, installation, launch commands and repository layout. |
| [TODO.md](../TODO.md) | Complete grouped feature/research backlog, including R01-R49 and WC/LE checkpoints. |
| [src/dmtools/terrain/AGENTS.md](../src/dmtools/terrain/AGENTS.md) | Terrain-specific contracts and implementation/testing instructions. |

## Active plans and indexes (13)

Current direction and navigation. Plans mark unimplemented features explicitly; code, schemas, tests and accepted decisions own shipped behavior.

| File | Purpose or document title |
|---|---|
| [docs/DEPENDENCIES.md](DEPENDENCIES.md) | Adopted runtime assets/packages and isolated research dependencies; licenses. |
| [docs/FILE_INDEX.md](FILE_INDEX.md) | Exhaustive documentation inventory, including this file. |
| [docs/README.md](README.md) | Selective reading guide and document authority. |
| [docs/adr/README.md](adr/README.md) | Architecture-decision index and the append-only decision policy. |
| [docs/architecture/README.md](architecture/README.md) | Current runtime structure and explicitly planned world-stage ownership. |
| [docs/research/README.md](research/README.md) | Dated research index, separating source review from executed experiments. |
| [docs/research/decision-catalog.md](research/decision-catalog.md) | Searchable technology/math conclusions, used/deferred/rejected scope, evidence and revisit triggers. |
| [docs/research/terrain-method-decisions.md](research/terrain-method-decisions.md) | Living failed-method record, causes, retained work, alternatives and revisit gates. |
| [docs/research/status.md](research/status.md) | Current implemented, experimental and unimplemented research status. |
| [docs/strategy/README.md](strategy/README.md) | Sole M1-M8 implementation order, stage connections, completion checks and continuous-update rule. |
| [docs/strategy/terrain-quality.md](strategy/terrain-quality.md) | Detailed A-F quality and specialized-feature controls, subordinate to the main order. |
| [docs/strategy/landscape-evolution.md](strategy/landscape-evolution.md) | LE0-LE6 evolution, authoring, conservation and regional-history gates. |
| [docs/strategy/world-context.md](strategy/world-context.md) | WC0-WC6 full-world import, shared context, climate and regional-history plan. |

## User guides and current contracts (19)

Current user workflows and numeric/file semantics, with future limits labelled in each guide.

| File | Purpose or document title |
|---|---|
| [docs/terrain-basins.md](terrain-basins.md) | Basin and spill review |
| [docs/terrain-builds.md](terrain-builds.md) | Build and inspect numeric terrain |
| [docs/terrain-coordinates.md](terrain-coordinates.md) | Terrain coordinate and grid contract |
| [docs/terrain-drainage.md](terrain-drainage.md) | Drainage density and network review |
| [docs/terrain-generation-control.md](terrain-generation-control.md) | Generation progress and cancellation |
| [docs/terrain-geotiff.md](terrain-geotiff.md) | Local-metric GeoTIFF export |
| [docs/terrain-parent-regions.md](terrain-parent-regions.md) | Generate a region from a verified parent |
| [docs/terrain-regional-memory.md](terrain-regional-memory.md) | Regional memory admission |
| [docs/terrain-regional-sampling.md](terrain-regional-sampling.md) | Sample a finer regional window |
| [docs/terrain-regions.md](terrain-regions.md) | Shape terrain with landform regions |
| [docs/terrain-structure-profiles.md](terrain-structure-profiles.md) | Edit line-owned crest, pass, spur and valley-floor controls before generation. |
| [docs/terrain-seeds.md](terrain-seeds.md) | Reproducible terrain seeds |
| [docs/terrain-water-budget.md](terrain-water-budget.md) | Forecast water-sampling demand |
| [docs/terrain-water.md](terrain-water.md) | Authored lakes and dry basins |
| [docs/terrain-worlds.md](terrain-worlds.md) | Import, map, validate and save retained world sources; geographic and workflow limits. |
| [docs/world-planet.md](world-planet.md) | Experimental whole-planet relief, climate and biomes: command, options, outputs, alignment with the SVG and limits. |
| [docs/world-bathymetry.md](world-bathymetry.md) | Explicit ocean selection, shelf/slope/basin hypotheses, numerical depth/error/support and portable input/result workflow. |
| [docs/world-context.md](world-context.md) | Generate spherical geography, inspect water/resolution support and export context products. |
| [docs/world-geology.md](world-geology.md) | Author continent defaults and independent province hypotheses; priority, time, coverage and portable recipe contracts. |
| [src/dmtools/terrain/README.md](../src/dmtools/terrain/README.md) | Current desktop authoring workflow, tools and shortcuts. |

## Developer and reference guides (8)

Subsystem, fixture, schema, test and benchmark guidance.

| File | Purpose or document title |
|---|---|
| [benchmarks/README.md](../benchmarks/README.md) | Public performance/quality probes, commands and measurement boundaries. |
| [benchmarks/evolution/README.md](../benchmarks/evolution/README.md) | Isolated evolution setup, runnable comparisons and current limits. |
| [benchmarks/planet/README.md](../benchmarks/planet/README.md) | Whole-planet sphere-mesh erosion harness, synthetic test worlds and metrics. |
| [benchmarks/planet/scale_metrics.py](../benchmarks/planet/scale_metrics.py) | Landform scale and realism-gate metrics of a planet build: river lengths vs basin area, Horton ratios, sinuosity, mountain-belt widths, valley and mouth spacing. |
| [examples/README.md](../examples/README.md) | Public example projects and their supported behaviors. |
| [schemas/README.md](../schemas/README.md) | Current world-source, geographic-context and local-terrain formats. |
| [src/dmtools/terrain/adapters/README.md](../src/dmtools/terrain/adapters/README.md) | File-format/render/export adapter responsibilities. |
| [src/dmtools/terrain/domain/README.md](../src/dmtools/terrain/domain/README.md) | Dependency-light domain values and validation responsibilities. |
| [src/dmtools/terrain/pipeline/README.md](../src/dmtools/terrain/pipeline/README.md) | Numeric generation and inspection responsibilities. |
| [tests/README.md](../tests/README.md) | Test organization, commands and verification expectations. |

## Architecture decision records (84)

Accepted historical decisions. Preserve their original context; consult the current status and implementation for later changes. The ADR index is listed among active indexes.

| File | Purpose or document title |
|---|---|
| [docs/adr/0001-python-3-14.md](adr/0001-python-3-14.md) | ADR-0001: Use Python 3.14 for the application and terrain engine |
| [docs/adr/0002-tk-svg-terrain-workbench.md](adr/0002-tk-svg-terrain-workbench.md) | ADR-0002: Build the first terrain workbench with Tk and SVG input |
| [docs/adr/0003-map-authored-constraints.md](adr/0003-map-authored-constraints.md) | ADR-0003: Author topography on the map and condition the base surface |
| [docs/adr/0004-soft-elevation-brush.md](adr/0004-soft-elevation-brush.md) | ADR-0004: Paint soft elevation guidance as vector strokes |
| [docs/adr/0005-relative-relief.md](adr/0005-relative-relief.md) | ADR-0005: Separate absolute elevation from relative relief |
| [docs/adr/0006-versioned-terrain-project.md](adr/0006-versioned-terrain-project.md) | ADR-0006: Persist authored terrain as versioned JSON with a verified SVG reference |
| [docs/adr/0007-shape-preserving-structure-profiles.md](adr/0007-shape-preserving-structure-profiles.md) | ADR-0007: Use shape-preserving longitudinal profiles for anchored structures |
| [docs/adr/0008-relative-structure-profile-anchors.md](adr/0008-relative-structure-profile-anchors.md) | ADR-0008: Interpret relative points as relative structure profile anchors |
| [docs/adr/0009-multipart-svg-land-geometry.md](adr/0009-multipart-svg-land-geometry.md) | ADR-0009: Dissolve multipart SVG land geometry before generation |
| [docs/adr/0010-use-oleron-land-colours-for-elevation.md](adr/0010-use-oleron-land-colours-for-elevation.md) | ADR-0010: Use Oleron's ordered land colours for elevation relief |
| [docs/adr/0011-separate-cartographic-and-scientific-relief-styles.md](adr/0011-separate-cartographic-and-scientific-relief-styles.md) | ADR-0011: Separate cartographic and scientific elevation styles |
| [docs/adr/0012-fix-cartographic-colour-scale-at-ten-kilometres.md](adr/0012-fix-cartographic-colour-scale-at-ten-kilometres.md) | ADR-0012: Fix the cartographic colour scale at ten kilometres |
| [docs/adr/0013-preserve-structure-width-at-junctions.md](adr/0013-preserve-structure-width-at-junctions.md) | ADR-0013: Preserve authored structure width at junctions |
| [docs/adr/0014-condition-valley-floors-downstream.md](adr/0014-condition-valley-floors-downstream.md) | ADR-0014: Condition valley floors from head to outlet |
| [docs/adr/0015-route-automatic-valleys-on-canonical-grid.md](adr/0015-route-automatic-valleys-on-canonical-grid.md) | ADR-0015: Route automatic valleys on a canonical hydrology grid |
| [docs/adr/0016-scale-generated-valley-width-downstream.md](adr/0016-scale-generated-valley-width-downstream.md) | ADR-0016: Scale generated valley width downstream |
| [docs/adr/0017-report-canonical-drainage-diagnostics.md](adr/0017-report-canonical-drainage-diagnostics.md) | ADR-0017: Report canonical drainage diagnostics without repairing the DEM |
| [docs/adr/0018-group-diagnostic-fill-regions-into-basin-candidates.md](adr/0018-group-diagnostic-fill-regions-into-basin-candidates.md) | ADR-0018: Group diagnostic fill regions into basin candidates |
| [docs/adr/0019-initiate-generated-channels-with-bounded-area-slope-thresholds.md](adr/0019-initiate-generated-channels-with-bounded-area-slope-thresholds.md) | ADR-0019: Initiate generated channels with bounded area-slope thresholds |
| [docs/adr/0020-condition-generated-channel-floors-downstream.md](adr/0020-condition-generated-channel-floors-downstream.md) | ADR-0020: Condition generated channel floors downstream |
| [docs/adr/0021-correct-broad-valleys-with-mfd-convergence.md](adr/0021-correct-broad-valleys-with-mfd-convergence.md) | ADR-0021: Correct broad valleys with MFD convergence |
| [docs/adr/0022-bound-extreme-generated-channel-steepening.md](adr/0022-bound-extreme-generated-channel-steepening.md) | ADR-0022: Bound extreme generated-channel steepening |
| [docs/adr/0023-derive-strahler-order-without-forcing-valley-width.md](adr/0023-derive-strahler-order-without-forcing-valley-width.md) | ADR-0023: Derive Strahler order without forcing valley width |
| [docs/adr/0024-publish-local-numeric-terrain-builds.md](adr/0024-publish-local-numeric-terrain-builds.md) | ADR-0024: Publish local numeric terrain builds before changing algorithms |
| [docs/adr/0025-centralize-local-frames-and-endpoint-grids.md](adr/0025-centralize-local-frames-and-endpoint-grids.md) | ADR-0025: Centralize local frames and endpoint grids |
| [docs/adr/0026-version-named-terrain-stage-seeds.md](adr/0026-version-named-terrain-stage-seeds.md) | ADR-0026: Version named terrain stage seeds |
| [docs/adr/0027-develop-current-behavior-without-legacy-support.md](adr/0027-develop-current-behavior-without-legacy-support.md) | ADR-0027: Develop current behavior without legacy support |
| [docs/adr/0028-export-local-metric-geotiff.md](adr/0028-export-local-metric-geotiff.md) | ADR-0028: Export local-metric GeoTIFF |
| [docs/adr/0029-route-drainage-over-authored-terrain.md](adr/0029-route-drainage-over-authored-terrain.md) | ADR-0029: Route drainage over authored terrain |
| [docs/adr/0030-author-regional-landforms.md](adr/0030-author-regional-landforms.md) | ADR-0030: Author regional landforms before constraints and drainage |
| [docs/adr/0031-bound-incision-by-regional-relief.md](adr/0031-bound-incision-by-regional-relief.md) | ADR-0031: Bound automatic incision by regional relief |
| [docs/adr/0032-classify-channel-conflicts.md](adr/0032-classify-channel-conflicts.md) | ADR-0032: Classify planned-channel conflicts without changing authored terrain |
| [docs/adr/0033-map-basin-spill-candidates.md](adr/0033-map-basin-spill-candidates.md) | ADR-0033: Map basin extents and conditioned spill candidates |
| [docs/adr/0034-author-lakes-and-dry-basins.md](adr/0034-author-lakes-and-dry-basins.md) | ADR-0034: Author lakes and dry-basin retention |
| [docs/adr/0035-retain-basin-flow-and-assess-outlets.md](adr/0035-retain-basin-flow-and-assess-outlets.md) | ADR-0035: Retain basin flow and assess downstream outlets |
| [docs/adr/0036-connect-lake-outflow-with-area-transfer.md](adr/0036-connect-lake-outflow-with-area-transfer.md) | ADR-0036: Connect lake outflow with conservative area transfer |
| [docs/adr/0037-expose-basin-catchment-outcomes.md](adr/0037-expose-basin-catchment-outcomes.md) | ADR-0037: Expose basin catchment outcomes and outlet-level evidence |
| [docs/adr/0038-route-basin-flats-with-integer-gradients.md](adr/0038-route-basin-flats-with-integer-gradients.md) | ADR-0038: Route basin flats with integer gradients |
| [docs/adr/0039-sample-shorelines-and-outlet-connections.md](adr/0039-sample-shorelines-and-outlet-connections.md) | ADR-0039: Sample shorelines and outlet connections |
| [docs/adr/0040-refine-water-profiles-around-authored-features.md](adr/0040-refine-water-profiles-around-authored-features.md) | ADR-0040: Refine water profiles around authored features |
| [docs/adr/0041-review-complete-downstream-outlet-profiles.md](adr/0041-review-complete-downstream-outlet-profiles.md) | ADR-0041: Review complete downstream outlet profiles |
| [docs/adr/0042-review-internal-water-links.md](adr/0042-review-internal-water-links.md) | ADR-0042: Review internal water links |
| [docs/adr/0043-review-dry-collection-paths.md](adr/0043-review-dry-collection-paths.md) | ADR-0043: Review dry collection paths |
| [docs/adr/0044-guide-water-profiles-through-regional-transitions.md](adr/0044-guide-water-profiles-through-regional-transitions.md) | ADR-0044: Guide water profiles through regional transitions |
| [docs/adr/0045-sample-procedural-detail-and-context-shoulders.md](adr/0045-sample-procedural-detail-and-context-shoulders.md) | ADR-0045: Sample procedural detail and context shoulders |
| [docs/adr/0046-forecast-water-sampling-budgets.md](adr/0046-forecast-water-sampling-budgets.md) | ADR-0046: Forecast water-sampling budgets |
| [docs/adr/0047-edit-generation-inputs-only.md](adr/0047-edit-generation-inputs-only.md) | ADR-0047: Edit generation inputs only |
| [docs/adr/0048-keep-zoom-driven-detail-generation.md](adr/0048-keep-zoom-driven-detail-generation.md) | ADR-0048: Keep zoom-driven detail generation in scope |
| [docs/adr/0049-navigate-and-save-authored-inputs.md](adr/0049-navigate-and-save-authored-inputs.md) | ADR-0049: Navigate and save authored terrain inputs |
| [docs/adr/0050-reconstruct-valleys-with-bounded-cubics.md](adr/0050-reconstruct-valleys-with-bounded-cubics.md) | ADR-0050: Reconstruct automatic valleys with bounded cubics |
| [docs/adr/0051-connect-diagonal-valley-shaping.md](adr/0051-connect-diagonal-valley-shaping.md) | ADR-0051: Connect diagonal valley shaping |
| [docs/adr/0052-fit-channel-cuts-to-sampled-terrain.md](adr/0052-fit-channel-cuts-to-sampled-terrain.md) | ADR-0052: Fit channel cuts to the sampled terrain |
| [docs/adr/0053-observe-mountain-crests-in-drainage.md](adr/0053-observe-mountain-crests-in-drainage.md) | ADR-0053: Observe mountain crests in the drainage graph |
| [docs/adr/0054-refine-observed-mountain-crests.md](adr/0054-refine-observed-mountain-crests.md) | ADR-0054: Refine observed mountain crests |
| [docs/adr/0055-prepare-attainable-channel-floor-profiles.md](adr/0055-prepare-attainable-channel-floor-profiles.md) | ADR-0055: Prepare attainable channel-floor profiles |
| [docs/adr/0056-condition-network-floors-in-both-directions.md](adr/0056-condition-network-floors-in-both-directions.md) | ADR-0056: Condition network floors in both directions |
| [docs/adr/0057-display-water-at-the-appropriate-scale.md](adr/0057-display-water-at-the-appropriate-scale.md) | ADR-0057: Display water at the appropriate scale |
| [docs/adr/0058-sample-bounded-regional-windows.md](adr/0058-sample-bounded-regional-windows.md) | ADR-0058: Sample bounded regional windows |
| [docs/adr/0059-preserve-noise-band-amplitudes.md](adr/0059-preserve-noise-band-amplitudes.md) | ADR-0059: Preserve noise-band amplitudes |
| [docs/adr/0060-interpolate-overlapping-height-points.md](adr/0060-interpolate-overlapping-height-points.md) | ADR-0060: Interpolate overlapping absolute height points |
| [docs/adr/0061-verify-parents-and-isolate-local-detail.md](adr/0061-verify-parents-and-isolate-local-detail.md) | ADR-0061: Verify saved parents and isolate experimental local detail |
| [docs/adr/0062-reuse-bounded-detail-cell-support.md](adr/0062-reuse-bounded-detail-cell-support.md) | ADR-0062: Reuse bounded detail-cell support |
| [docs/adr/0063-reuse-verified-parent-region-sessions.md](adr/0063-reuse-verified-parent-region-sessions.md) | ADR-0063: Reuse verified parent-region sessions |
| [docs/adr/0064-cancel-generation-at-safe-checkpoints.md](adr/0064-cancel-generation-at-safe-checkpoints.md) | ADR-0064: Cancel generation at safe checkpoints |
| [docs/adr/0065-admit-regional-memory-estimates.md](adr/0065-admit-regional-memory-estimates.md) | ADR-0065: Admit regional memory estimates before allocation |
| [docs/adr/0066-bound-terrain-rendering-scratch.md](adr/0066-bound-terrain-rendering-scratch.md) | ADR-0066: Bound terrain rendering scratch |
| [docs/adr/0067-own-preview-images-and-tile-water.md](adr/0067-own-preview-images-and-tile-water.md) | ADR-0067: Own preview images and tile water |
| [docs/adr/0068-share-terrain-detail-across-edges.md](adr/0068-share-terrain-detail-across-edges.md) | ADR-0068: Share terrain detail across parent-cell edges |
| [docs/adr/0069-connect-and-scale-drainage-review.md](adr/0069-connect-and-scale-drainage-review.md) | ADR-0069: Connect and scale drainage review |
| [docs/adr/0070-retain-world-source-and-workspaces.md](adr/0070-retain-world-source-and-workspaces.md) | Retain world sources in a dedicated workspace. |
| [docs/adr/0071-interpret-exported-svg-fills.md](adr/0071-interpret-exported-svg-fills.md) | Interpret exported SVG headers, labels and complex filled paths. |
| [docs/adr/0072-bound-world-source-imperfections.md](adr/0072-bound-world-source-imperfections.md) | Bound minor export imperfections in derived coverage and report adjustments. |
| [docs/adr/0073-generate-spherical-geographic-context.md](adr/0073-generate-spherical-geographic-context.md) | Generate spherical coverage and periodic vector-water topology with explicit support limits. |
| [docs/adr/0074-verify-context-and-measure-water-openings.md](adr/0074-verify-context-and-measure-water-openings.md) | Verified context reopening, physical shared-face widths and immutable source-save handling. |
| [docs/adr/0075-measure-spherical-geographic-exposure.md](adr/0075-measure-spherical-geographic-exposure.md) | Spherical shoreline sampling bounds, directional geographic exposure, support and the historical v3 product format. |
| [docs/adr/0076-author-world-geology-inputs.md](adr/0076-author-world-geology-inputs.md) | Separate retained-world geology recipes, priority coverage and independent time semantics. |
| [docs/adr/0077-generate-authored-ocean-depths.md](adr/0077-generate-authored-ocean-depths.md) | Separate authored bathymetry, conservative depth bounds, actual water-centre membership and immutable verified products. |
| [docs/adr/0078-retain-water-piece-connectivity.md](adr/0078-retain-water-piece-connectivity.md) | Separate water pieces, finite shared intervals, source verification and explicit unresolved transport support. |
| [docs/adr/0079-project-world-land-into-terrain.md](adr/0079-project-world-land-into-terrain.md) | Connected world land, metric projection, portable source and guarded terrain handoff. |
| [docs/adr/0080-transfer-geological-landform-guidance.md](adr/0080-transfer-geological-landform-guidance.md) | Explicit geological landforms, priority holes, portable provenance and current-format cutover. |
| [docs/adr/0081-blend-adjoining-landform-regions.md](adr/0081-blend-adjoining-landform-regions.md) | Shared regional weighting, blank holes, established interiors and matching probe/cut support. |
| [docs/adr/0082-own-structure-profiles.md](adr/0082-own-structure-profiles.md) | Explicit line profile ownership, sampling support, editor and current-format contracts. |
| [docs/adr/0083-preserve-shared-ridge-crests.md](adr/0083-preserve-shared-ridge-crests.md) | Preserved ridge contacts, compatible heights, centreline ownership and remaining graph limits. |
| [docs/adr/0086-regional-planet-detail-from-blended-tiles.md](adr/0086-regional-planet-detail-from-blended-tiles.md) | Window-independent regional detail from fixed blended tiles, tile cache, lapse-corrected biomes and limits. |
| [docs/adr/0085-generate-planet-relief-on-a-sphere-mesh.md](adr/0085-generate-planet-relief-on-a-sphere-mesh.md) | Whole-planet relief by uplift/stream-power erosion on an irregular sphere mesh; node+TIN authority; Numba runtime. |
| [docs/adr/0084-bind-geographic-context-to-rough-terrain.md](adr/0084-bind-geographic-context-to-rough-terrain.md) | Bounded immutable geographic context, conservative coastal-distance consumption and explicit unsupported M1 fields. |

## Dated research reports (81)

Primary-source reviews, experiments and implementation evidence at their recorded date/revision. A title or citation is not evidence that a tool was adopted. Current status is listed above.

| File | Purpose or document title |
|---|---|
| [docs/research/2026-10-08-continentality-and-koppen.md](research/2026-10-08-continentality-and-koppen.md) | Wind-driven continentality, seasonal rainfall, Köppen–Geiger classes, outputs and limits. |
| [docs/research/2026-10-08-volcanism.md](research/2026-10-08-volcanism.md) | Arc, hotspot, rift and intraplate volcanoes: placement, shapes, rendering, export and limits. |
| [docs/research/2026-10-08-plate-tectonics-and-sediment.md](research/2026-10-08-plate-tectonics-and-sediment.md) | Plate-driven collision belts, rifts, leading-edge margins and trenches; old orogens; results and limits. |
| [docs/research/2026-10-08-orogens-glaciers-and-speed.md](research/2026-10-08-orogens-glaciers-and-speed.md) | Methods survey; composite orogens, strike lithology, glacial buzzsaw, Horton gates, openness shading, speed-ups and rejected deposition trials. |
| [docs/research/2026-10-07-earth-scale-landforms.md](research/2026-10-07-earth-scale-landforms.md) | Earth reference sizes of ranges, valleys, rivers and fjords; measured mismatch; explicit-width belts, shield erodibility, inherited surface, coarse climate and coupling meshes. |
| [docs/research/2026-10-07-world-scale-detail.md](research/2026-10-07-world-scale-detail.md) | Multi-scale procedural forcing, physical moisture eddy diffusivity, world display valley carving, river widths and playa rules, with before/after metrics. |
| [docs/research/2026-10-07-natural-map-rendering.md](research/2026-10-07-natural-map-rendering.md) | Natural-colour atlas, varying shelves, display detail, regional valley carving and snowline, with slope measurements and the calibration-test regime fix. |
| [docs/research/2026-10-06-first-authored-world-planet.md](research/2026-10-06-first-authored-world-planet.md) | First run on a real authored world: timings, metrics, ice-sheet lake/river fix and authored-source findings. |
| [docs/research/2026-10-06-regional-enrichment-tiles.md](research/2026-10-06-regional-enrichment-tiles.md) | Parent-conditioned regional enrichment, secant calibration, rejected overlapping windows and window-independent blended tiles. |
| [docs/research/2026-10-06-planet-lakes-and-cratons.md](research/2026-10-06-planet-lakes-and-cratons.md) | Craton marginal-swell profile, uplift texture, young depressions and climate-balanced lakes with controls and limits. |
| [docs/research/2026-10-06-planet-climate-v0.md](research/2026-10-06-planet-climate-v0.md) | Planet climate v0 (temperature, winds, moisture, runoff, provisional biomes), erosion coupling, failed calibration steps and limits. |
| [docs/research/2026-10-06-whole-planet-erosion-relief.md](research/2026-10-06-whole-planet-erosion-relief.md) | Whole-planet uplift/erosion on an irregular sphere mesh: resolution sweep, isotropy, Hack exponent and limits. |
| [docs/research/2026-09-28-context-bound-rough-terrain.md](research/2026-09-28-context-bound-rough-terrain.md) | M1 context binding, continuous conservative shoreline support, paired public control and validation limits. |
| [docs/research/2026-09-27-shared-landform-blending.md](research/2026-09-27-shared-landform-blending.md) | Replacement of background seams, rejected enclave-leaking kernel, paired evidence and remaining slope limits. |
| [docs/research/2026-09-27-shared-ridge-crests.md](research/2026-09-27-shared-ridge-crests.md) | Paired crest-height and corner-gap improvements, failed assumptions and graph/process limits. |
| [docs/research/2026-09-27-line-owned-terrain-profiles.md](research/2026-09-27-line-owned-terrain-profiles.md) | Connected-range authoring slice, owned profile evidence and unresolved multi-line composition. |
| [docs/research/2026-09-27-geological-landform-guidance.md](research/2026-09-27-geological-landform-guidance.md) | Historical recipe-transfer evidence and polygon-boundary rims motivating ADR-0081. |
| [docs/research/2026-09-27-world-to-terrain-workflow.md](research/2026-09-27-world-to-terrain-workflow.md) | Working world-to-terrain handoff, real-map roundoff failure/fix, feature priorities and exploratory bank failures. |
| [docs/research/2026-09-27-prepared-feature-snapshots.md](research/2026-09-27-prepared-feature-snapshots.md) | Bounded feature snapshots, exact reopening/query/halo checks, failed raster control and remaining adoption gates. |
| [docs/research/2026-09-27-feature-preserving-terrain-delivery.md](research/2026-09-27-feature-preserving-terrain-delivery.md) | Short orientation/feasibility probes, rejected splines, exact trusted-field roundtrip and proposed feature-preserving delivery. |
| [docs/research/2026-09-27-cell-safe-terrain-delivery.md](research/2026-09-27-cell-safe-terrain-delivery.md) | Curvature-bounded capacities, cell-interior protection, matched raster gains, rejected shortcuts and remaining interpolation defects. |
| [docs/research/2026-09-26-valley-heads-and-mouths.md](research/2026-09-26-valley-heads-and-mouths.md) | Cap-aware heads, perpendicular mouths, matched dense bank checks, rejected tapers and remaining raster delivery failures. |
| [docs/research/2026-09-26-hard-target-valley-layout.md](research/2026-09-26-hard-target-valley-layout.md) | Automatic guide relocation, preserved hard targets, restored 250 m capture, remaining bank/coarse failures and rejected alternatives. |
| [docs/research/2026-09-26-connected-valley-patches.md](research/2026-09-26-connected-valley-patches.md) | Connected local valleys, fixed/fresh controls, coastal ablation, rejected raster delivery and hard-target follow-up. |
| [docs/research/2026-09-25-groundwater-and-terrain-architecture.md](research/2026-09-25-groundwater-and-terrain-architecture.md) | Primary-source groundwater/canyon review, local API availability, revised construction architecture and staged experiments. |
| [docs/research/2026-09-25-valley-bank-feasibility.md](research/2026-09-25-valley-bank-feasibility.md) | Physical bank support, local/joint conflict diagnostics, failed inward profiles/capture and the next river-aligned patch gate. |
| [docs/research/2026-09-25-constrained-network-surface.md](research/2026-09-25-constrained-network-surface.md) | Native-bounded terrain fit, preserved hard inputs and failed actual valley capture; next feasibility gates. |
| [docs/research/2026-09-25-physical-channel-paths.md](research/2026-09-25-physical-channel-paths.md) | Coupled path/ground prototype, full-cohort constraints and receiver/outlet sensitivity; next generation decision. |
| [docs/research/2026-09-25-water-piece-connectivity.md](research/2026-09-25-water-piece-connectivity.md) | Topology implementation, precision-limit support, synthetic/private validation and graph performance. |
| [docs/research/2026-09-24-world-context-enrichment.md](research/2026-09-24-world-context-enrichment.md) | World context before continental terrain: research and recommendation |
| [docs/research/2026-09-25-context-reopening-and-gateways.md](research/2026-09-25-context-reopening-and-gateways.md) | Saved-context and gateway implementation, analytic/UI checks and measured cost. |
| [docs/research/2026-09-25-authored-world-bathymetry.md](research/2026-09-25-authored-world-bathymetry.md) | Bathymetry implementation, analytic/file/editor controls, visible review and normal/maximum-grid measurements. |
| [docs/research/2026-09-25-authored-world-geology.md](research/2026-09-25-authored-world-geology.md) | Authored-geology implementation, numeric/file/editor controls and remaining physical-model limits. |
| [docs/research/2026-09-25-geographic-exposure.md](research/2026-09-25-geographic-exposure.md) | Exposure implementation, analytic controls, dependency adoption, UI inspection and measured resource limits. |
| [docs/research/2026-09-25-geographic-world-context.md](research/2026-09-25-geographic-world-context.md) | WC1 geographic implementation, UI/contract validation and bounded grid measurements. |
| [docs/research/2026-09-25-bounded-world-preparation.md](research/2026-09-25-bounded-world-preparation.md) | Bounded world preparation, source retention, overlap controls and UI/save evidence. |
| [docs/research/2026-09-25-world-import-corrections.md](research/2026-09-25-world-import-corrections.md) | SVG import corrections, regression evidence and source-quality limits. |
| [docs/research/2026-09-25-world-source-workspace.md](research/2026-09-25-world-source-workspace.md) | WC0 implementation, UI/contract validation and bounded world import/render timings. |
| [docs/research/2026-09-24-progress-and-generation-strategy.md](research/2026-09-24-progress-and-generation-strategy.md) | Progress and generation strategy reassessment — 2026-09-24 |
| [docs/research/2026-09-24-landscape-evolution-reference.md](research/2026-09-24-landscape-evolution-reference.md) | First executable landscape-evolution batch |
| [docs/research/2026-09-24-landscape-evolution-models.md](research/2026-09-24-landscape-evolution-models.md) | Landscape evolution: models, existing tools and selection |
| [docs/research/2026-09-24-frozen-channel-reconstruction.md](research/2026-09-24-frozen-channel-reconstruction.md) | Frozen terrain/channel reconstruction comparison |
| [docs/research/2026-09-24-connected-drainage-review.md](research/2026-09-24-connected-drainage-review.md) | Connected drainage review and authored density — 2026-09-24 |
| [docs/research/2026-09-23-verified-parent-detail.md](research/2026-09-23-verified-parent-detail.md) | Verified parent replay and experimental local detail |
| [docs/research/2026-09-23-shared-edge-detail.md](research/2026-09-23-shared-edge-detail.md) | Shared-edge terrain detail - 2026-09-23 |
| [docs/research/2026-09-23-regional-memory-admission.md](research/2026-09-23-regional-memory-admission.md) | Regional memory admission and bounded loading |
| [docs/research/2026-09-23-preview-image-ownership.md](research/2026-09-23-preview-image-ownership.md) | Preview image ownership and water composition - 2026-09-23 |
| [docs/research/2026-09-23-parent-region-sessions.md](research/2026-09-23-parent-region-sessions.md) | Verified parent-region sessions - 2026-09-23 |
| [docs/research/2026-09-23-parent-cell-preservation.md](research/2026-09-23-parent-cell-preservation.md) | Parent-cell preservation experiment - 2026-09-23 |
| [docs/research/2026-09-23-exact-height-points.md](research/2026-09-23-exact-height-points.md) | Exact overlapping height points - 2026-09-23 |
| [docs/research/2026-09-23-detail-cell-reuse.md](research/2026-09-23-detail-cell-reuse.md) | Bounded detail-cell reuse - 2026-09-23 |
| [docs/research/2026-09-23-bounded-terrain-rendering.md](research/2026-09-23-bounded-terrain-rendering.md) | Bounded terrain rendering - 2026-09-23 |
| [docs/research/2026-09-22-stable-detail-band-amplitudes.md](research/2026-09-22-stable-detail-band-amplitudes.md) | Stable detail-band amplitudes |
| [docs/research/2026-09-22-regional-field-sampling.md](research/2026-09-22-regional-field-sampling.md) | Bounded regional field sampling — 2026-09-22 |
| [docs/research/2026-09-17-water-display-scale.md](research/2026-09-17-water-display-scale.md) | Water display scale check — 2026-09-17 |
| [docs/research/2026-09-17-refined-mountain-crests.md](research/2026-09-17-refined-mountain-crests.md) | Refined mountain-crest observations |
| [docs/research/2026-09-17-network-floor-conditioning.md](research/2026-09-17-network-floor-conditioning.md) | Network-wide channel-floor conditioning |
| [docs/research/2026-09-17-drainage-routing-cost.md](research/2026-09-17-drainage-routing-cost.md) | Drainage routing cost and bounded regional working storage |
| [docs/research/2026-09-17-attainable-channel-floors.md](research/2026-09-17-attainable-channel-floors.md) | Attainable channel-floor profiles |
| [docs/research/2026-09-16-source-aware-channel-floors.md](research/2026-09-16-source-aware-channel-floors.md) | Source-aware channel floor reconstruction |
| [docs/research/2026-09-16-mountain-crest-routing.md](research/2026-09-16-mountain-crest-routing.md) | Mountain-crest observations for drainage routing |
| [docs/research/2026-09-16-connected-diagonal-valleys.md](research/2026-09-16-connected-diagonal-valleys.md) | Connected diagonal valleys - 2026-09-16 |
| [docs/research/2026-09-16-bounded-valley-reconstruction.md](research/2026-09-16-bounded-valley-reconstruction.md) | Bounded valley reconstruction - 2026-09-16 |
| [docs/research/2026-09-16-bounded-noise-refinement.md](research/2026-09-16-bounded-noise-refinement.md) | Bound-driven noise-profile refinement - 2026-09-16 |
| [docs/research/2026-09-14-noise-profile-bounds.md](research/2026-09-14-noise-profile-bounds.md) | Rounded profile bounds through grid strips - 2026-09-14 |
| [docs/research/2026-09-13-water-sampling-reuse.md](research/2026-09-13-water-sampling-reuse.md) | Exact water-sampling reuse - 2026-09-13 |
| [docs/research/2026-09-13-water-sampling-convergence.md](research/2026-09-13-water-sampling-convergence.md) | Water-profile convergence and regional guidance - 2026-09-13 |
| [docs/research/2026-09-13-water-guide-bounds.md](research/2026-09-13-water-guide-bounds.md) | Prepared bounds for water-sampling guides - 2026-09-13 |
| [docs/research/2026-09-13-water-budget-forecast.md](research/2026-09-13-water-budget-forecast.md) | Water-sampling budget forecast - 2026-09-13 |
| [docs/research/2026-09-13-noise-component-bounds.md](research/2026-09-13-noise-component-bounds.md) | Rounded bounds for the procedural-noise component - 2026-09-13 |
| [docs/research/2026-09-13-detail-and-context-sampling.md](research/2026-09-13-detail-and-context-sampling.md) | Procedural detail and context sampling - 2026-09-13 |
| [docs/research/2026-09-13-adaptive-water-profile-refinement.md](research/2026-09-13-adaptive-water-profile-refinement.md) | Adaptive water-profile refinement - 2026-09-13 |
| [docs/research/2026-09-11-internal-water-links.md](research/2026-09-11-internal-water-links.md) | Internal water links - 2026-09-11 |
| [docs/research/2026-09-11-finer-water-connections.md](research/2026-09-11-finer-water-connections.md) | Finer water connections: implementation and next steps |
| [docs/research/2026-09-11-feature-guided-water-sampling.md](research/2026-09-11-feature-guided-water-sampling.md) | Feature-guided water sampling - 2026-09-11 |
| [docs/research/2026-09-11-dry-collection-paths.md](research/2026-09-11-dry-collection-paths.md) | Dry collection paths: research and implementation rundown |
| [docs/research/2026-09-11-downstream-outlet-profiles.md](research/2026-09-11-downstream-outlet-profiles.md) | Complete downstream outlet profiles - 2026-09-11 |
| [docs/research/2026-09-11-connected-lake-outflow.md](research/2026-09-11-connected-lake-outflow.md) | Connected lake outflow: implementation and next steps |
| [docs/research/2026-09-11-basin-retention-and-outlets.md](research/2026-09-11-basin-retention-and-outlets.md) | Basin retention and downstream outlet assessment |
| [docs/research/2026-09-11-basin-flat-routing.md](research/2026-09-11-basin-flat-routing.md) | Basin flat routing: implementation and next steps |
| [docs/research/2026-09-11-basin-catchment-review.md](research/2026-09-11-basin-catchment-review.md) | Basin catchment review: implementation and next steps |
| [docs/research/2026-09-10-depressions-and-channel-conflicts.md](research/2026-09-10-depressions-and-channel-conflicts.md) | Depression handling and channel conflicts - 2026-09-10 |
| [docs/research/2026-09-10-basin-outlet-topology.md](research/2026-09-10-basin-outlet-topology.md) | Basin extent and outlet research, 2026-09-10 |
| [docs/research/2026-09-10-authored-water.md](research/2026-09-10-authored-water.md) | Authored water implementation and measurements, 2026-09-10 |
| [docs/research/2026-09-05-selective-terrain-sampling.md](research/2026-09-05-selective-terrain-sampling.md) | Selective terrain sampling — 2026-09-05 |
| [docs/research/2026-09-05-language-and-performance.md](research/2026-09-05-language-and-performance.md) | Language and performance — 2026-09-05 |
| [docs/research/2026-09-05-geological-structure-and-terrain-composition.md](research/2026-09-05-geological-structure-and-terrain-composition.md) | Geological structure and terrain composition — 2026-09-05 |
| [docs/research/2026-09-04-terrain-realism-and-landform-diversity.md](research/2026-09-04-terrain-realism-and-landform-diversity.md) | Terrain realism and landform diversity — 2026-09-04 |
| [docs/research/2026-09-04-terrain-prototype-contracts.md](research/2026-09-04-terrain-prototype-contracts.md) | Terrain prototype contracts — 2026-09-04 |
| [docs/research/2026-09-04-technology-and-world-systems.md](research/2026-09-04-technology-and-world-systems.md) | Technology and world-systems research — 2026-09-04 |
| [docs/research/2026-09-03-terrain-algorithm-options.md](research/2026-09-03-terrain-algorithm-options.md) | Terrain algorithm options — 2026-09-03 |
| [docs/research/2026-09-03-elevation-colour-ramp.md](research/2026-09-03-elevation-colour-ramp.md) | Elevation colour-ramp research — 2026-09-03 |
| [docs/research/2026-09-03-cartographic-relief-style.md](research/2026-09-03-cartographic-relief-style.md) | Cartographic relief style analysis — 2026-09-03 |

## Maintenance reports (2)

Historical documentation, structure and performance audit evidence.

| File | Purpose or document title |
|---|---|
| [docs/maintenance/2026-09-10-sanity-and-performance.md](maintenance/2026-09-10-sanity-and-performance.md) | Repository sanity and performance review - 2026-09-10 |
| [docs/maintenance/2026-09-13-documentation-and-research-status.md](maintenance/2026-09-13-documentation-and-research-status.md) | Documentation and research-status audit - 2026-09-13 |

## Legal notice (1)

Attribution/license documentation for a vendored asset.

| File | Purpose or document title |
|---|---|
| [docs/licenses/SCIENTIFIC_COLOUR_MAPS_LICENSE.txt](licenses/SCIENTIFIC_COLOUR_MAPS_LICENSE.txt) | Scientific Colour Maps attribution and redistribution license text. |

## Supporting machine-readable contracts (13)

These are operational specifications rather than prose documentation. They
are included for a complete route from plans to the current usable formats.

| File | Purpose |
|---|---|
| [schemas/terrain/build-v20.schema.json](../schemas/terrain/build-v20.schema.json) | Current numeric build manifest, optional experimental world-context report and runtime provenance. |
| [schemas/terrain/context-v1.schema.json](../schemas/terrain/context-v1.schema.json) | Immutable geographic sample binding, numeric identity and explicit consumed/retained/unsupported-field report. |
| [schemas/terrain/input-snapshot-v4.schema.json](../schemas/terrain/input-snapshot-v4.schema.json) | Portable effective input snapshot with optional immutable context for verified parent replay. |
| [schemas/terrain/parent-region-v1.schema.json](../schemas/terrain/parent-region-v1.schema.json) | Current parent sampling/experimental detail artifact contract. |
| [schemas/terrain/project-v9.schema.json](../schemas/terrain/project-v9.schema.json) | Current authored local terrain project format with optional bounded world context. |
| [schemas/terrain/regional-samples-v3.schema.json](../schemas/terrain/regional-samples-v3.schema.json) | Current bounded unchanged-field sampling artifact contract. |
| [schemas/world/bathymetry-inputs-v1.schema.json](../schemas/world/bathymetry-inputs-v1.schema.json) | Retained-world ocean selection and explicit physical shelf/slope/basin assumptions. |
| [schemas/world/planet-region-v1.schema.json](../schemas/world/planet-region-v1.schema.json) | Experimental regional detail window: parent identity, tiles, settings, local CRS and output hashes. |
| [schemas/world/planet-build-v1.schema.json](../schemas/world/planet-build-v1.schema.json) | Experimental planet build manifest: settings, stage seeds, inputs, mesh/raster mapping, calibration, metrics and output hashes. |
| [schemas/world/bathymetry-v1.schema.json](../schemas/world/bathymetry-v1.schema.json) | Completed depth/error arrays, verified geography dependency and source/runtime/product identity. |
| [schemas/world/context-v4.schema.json](../schemas/world/context-v4.schema.json) | Spherical context products, source/runtime identity, coverage/topology/support, shared-edge widths, water-piece incidence/unresolved support, shore distance, exposure and hashes. |
| [schemas/world/geology-v2.schema.json](../schemas/world/geology-v2.schema.json) | Authored continent profiles, explicit landform controls and priority polygons with retained world identity and a common present. |
| [schemas/world/terrain-source-v2.schema.json](../schemas/world/terrain-source-v2.schema.json) | Canonical prepared SVG metadata with retained world, projection, optional geological recipe and exact metric polygons. |
| [schemas/world/project-v1.schema.json](../schemas/world/project-v1.schema.json) | Portable retained world-source snapshot, explicit spherical frame/radius and semantic ownership. |
| [benchmarks/evolution/requirements-windows-py314.txt](../benchmarks/evolution/requirements-windows-py314.txt) | Hashed isolated Windows/Python 3.14 scientific reference environment. |

## Maintaining this inventory

When adding or removing documentation, compare this list with `git ls-files`
for Markdown files and `docs/licenses/*.txt`; include this file in the count.
Keep historical decisions/reports in their groups and update active status
instead of rewriting old evidence. Update schema rows only when the owning
implemented format changes. This inventory does not promote proposed world
products into public formats.
