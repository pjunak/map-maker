# Documentation

## Where to start

1. To import and review a whole world, read the [world guide](terrain-worlds.md).
   To generate whole-planet relief, climate and biomes from it, read the
   [planet guide](world-planet.md).
   To generate local terrain, read the
   [terrain tool guide](../src/dmtools/terrain/README.md).
   For stopping work safely, read [generation cancellation](terrain-generation-control.md).
2. To contribute or choose the next implementation, read the
   [ordered implementation plan](strategy/README.md). To see what has already been
   researched and why a method was used or deferred, start with the
   [decision catalog](research/decision-catalog.md); individual failed trials live
   in the [terrain method register](research/terrain-method-decisions.md).
3. To understand the present dependency direction and data flow, read the
   [architecture overview](architecture/README.md).
4. To inspect categorized future work, use the
   [terrain tool roadmap](../TODO.md).
5. For public file contracts and runnable inputs, see
   [schemas](../schemas/README.md) and [examples](../examples/README.md).
6. To generate and compare numeric output, use the
   [headless build guide](terrain-builds.md); estimate shoreline/internal sampling
   with the [water-budget forecast](terrain-water-budget.md). Sample a bounded
   finer window with the [regional sampling command](terrain-regional-sampling.md),
   or try [verified parents and experimental local detail](terrain-parent-regions.md).
   Saved-parent jobs use [shared memory admission](terrain-regional-memory.md).
7. For source/local conversion, endpoint grids and world-positioning limits,
   read the [coordinate contract](terrain-coordinates.md).
8. For portable named stage seeds, read the
   [seed contract](terrain-seeds.md).

For the requested full-world workflow, follow M1-M8 in the main plan, then use the
[WC0-WC6 connection/model reference](strategy/world-context.md) and its
[primary-source/tool review](research/2026-09-24-world-context-enrichment.md).
WC0 world import/mapping and the [geographic subset of WC1](world-context.md) are
implemented, including verified reopening, shared-edge water measurements,
shore distance, directional exposure and separate water-piece links with explicit
unresolved support. [Authored geology](world-geology.md) now
adds a separate province/default recipe and editor. [Bathymetry](world-bathymetry.md)
now generates an explicit ocean-depth hypothesis with its own inputs, previews and
verified result. [World → Terrain](terrain-worlds.md#create-terrain-from-the-world)
now creates a usable local project from connected world land, with retained
projection and physical scale. M1 can embed matching context and consume conservative
coastal support in experimental rough terrain. Climate/runoff, geology epochs,
bathymetry coupling and aging remain planned.

The [complete documentation file inventory](FILE_INDEX.md) lists every tracked
Markdown document and legal notice individually, with purpose and current versus
historical role. It also lists the public machine-readable schemas and isolated
reference dependency lock separately. This page remains the selective reading guide.

## Document roles and authority

Implemented code, public schemas, tests, and accepted ADRs define current
behavior. The main strategy owns implementation order; architecture describes
implemented and explicitly planned responsibilities.
The roadmap is a categorized backlog rather than an execution sequence. Dated
research preserves evidence and may become stale as packages and measurements
change.

- [`strategy/`](strategy/README.md) gives the current dependency-aware order of
  work and the mandatory same-commit update checklist. Its linked
  [quality reference](strategy/terrain-quality.md) retains A-F controls without
  making them a competing implementation queue.
- [`architecture/`](architecture/README.md) describes the current system and
  intended dependency direction.
- [`adr/`](adr/README.md) preserves accepted decisions, alternatives, and
  consequences; accepted ADRs are append-only history.
- [`research/`](research/README.md) indexes implemented, measured results and
  candidate investigations. Its [decision catalog](research/decision-catalog.md)
  gives searchable conclusions and revisit triggers. Its [status page](research/status.md) distinguishes
  shipped work, partial experiments and work not yet run. The living
  [method register](research/terrain-method-decisions.md) links failed candidates
  to replacement/revisit gates; dated evidence stays historical.
- [`DEPENDENCIES.md`](DEPENDENCIES.md) records packages and assets actually used
  at runtime, with purposes and licenses.

Promote a selected solver, file-format contract, or external engine into an ADR
and tests. Do not rewrite old research to make it appear that a later decision
was already known.

For numeric GIS exchange and its local-coordinate limits, read the
[GeoTIFF export guide](terrain-geotiff.md).

For regional terrain authoring and its first four recipes, read the
[landform region guide](terrain-regions.md).

For explicit peaks, passes and descending spur/floor controls, read the
[line profile guide](terrain-structure-profiles.md) and
[profile implementation evidence](research/2026-09-27-line-owned-terrain-profiles.md).
For connected ridge heights and preserved contacts, read the
[shared-crest comparison](research/2026-09-27-shared-ridge-crests.md).

For authored lake levels, dry-basin retention and their review, read the
[water guide](terrain-water.md).

For drainage-density inputs and connected scale-aware inspection, read the
[drainage guide](terrain-drainage.md).

For basin extents, spill candidates and water-boundary limits, read the
[basin review contract](terrain-basins.md).

For the current progress, quality gaps, refreshed research and delivery plan,
read the [2026-09-24 reassessment](research/2026-09-24-progress-and-generation-strategy.md).
For the experimental uplift/erosion history model, read the
[primary-source and tool comparison](research/2026-09-24-landscape-evolution-models.md)
and [detailed implementation plan](strategy/landscape-evolution.md). The
[first executable batch](research/2026-09-24-landscape-evolution-reference.md)
includes numerical controls and measured comparisons; production acceptance
remains open. The [frozen reconstruction follow-up](research/2026-09-24-frozen-channel-reconstruction.md)
measures surface/path agreement without rerunning erosion. The
[physical-path follow-up](research/2026-09-25-physical-channel-paths.md) adds shared
path/ground geometry and grid/time diagnostics, with failed constraint gates kept
visible. The [constrained-network follow-up](research/2026-09-25-constrained-network-surface.md)
preserves native limits and hard heights, but independent rerouting rejects its
valley capture. The [bank-support follow-up](research/2026-09-25-valley-bank-feasibility.md)
adds physical banks and conflict diagnostics, but endpoint success still fails
cross-sections and capture. Subsequent
[connected patches](research/2026-09-26-connected-valley-patches.md),
[automatic layout](research/2026-09-26-hard-target-valley-layout.md) and
[head/mouth construction](research/2026-09-26-valley-heads-and-mouths.md) now restore
capture and pass the matched local bank checks. The
[cell-safe bound comparison](research/2026-09-27-cell-safe-terrain-delivery.md)
removes large raster head artifacts while protecting cell interiors. Actual bank
delivery remains rejected. The
[feature-preservation probes](research/2026-09-27-feature-preserving-terrain-delivery.md)
now retain the local field through trusted saving/reopening, while generic
splines fail capture and bounds. The
[guarded snapshot comparison](research/2026-09-27-prepared-feature-snapshots.md)
now provides bounded reopening and exact same-field query/tiling checks. Held-out
geometry and real parent/detail consistency remain research gates; product DEM
authority is unchanged. The [world-to-terrain batch](research/2026-09-27-world-to-terrain-workflow.md)
records the user-selected feature priority, the working handoff, and four short
held-out layouts that still fail small inward-bank checks. The
[geological landform batch](research/2026-09-27-geological-landform-guidance.md)
connects explicit recipes to that workflow. The
[shared blending replacement](research/2026-09-27-shared-landform-blending.md) removes
internal background rims while retaining blank cutouts and established interiors;
connected landform structure and physical slope/support feedback remain open.
The [reference guide](../benchmarks/evolution/README.md) owns setup and runnable commands.
The [2026-09-13 audit](maintenance/2026-09-13-documentation-and-research-status.md)
and [2026-09-10 checkpoint](maintenance/2026-09-10-sanity-and-performance.md)
retain earlier documentation, structure and performance evidence.
