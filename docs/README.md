# Documentation

A reading guide. The [file inventory](FILE_INDEX.md) lists every document.

## Use the tools

| Goal | Read |
|---|---|
| Import, map and review an SVG world | [World guide](terrain-worlds.md) |
| Generate whole-planet relief, climate, maps, views and regional detail | [Planet guide](world-planet.md) |
| Add fantastical landmarks, at random or by hand | [Wonder guide](wonders.md) |
| Generate geographic context (coverage, water, shore distance, exposure) | [Context guide](world-context.md) |
| Author geology provinces and landform intent | [Geology guide](world-geology.md) |
| Generate ocean-depth hypotheses | [Bathymetry guide](world-bathymetry.md) |
| Use the local terrain editor | [Terrain tool guide](../src/dmtools/terrain/README.md), [cancellation](terrain-generation-control.md) |
| Build local terrain headlessly | [Builds](terrain-builds.md), [GeoTIFF](terrain-geotiff.md), [coordinates](terrain-coordinates.md), [seeds](terrain-seeds.md) |
| Author local water, drainage, regions and profiles | [Water](terrain-water.md), [water budget](terrain-water-budget.md), [drainage](terrain-drainage.md), [basins](terrain-basins.md), [regions](terrain-regions.md), [line profiles](terrain-structure-profiles.md) |
| Sample or refine local builds | [Regional sampling](terrain-regional-sampling.md), [verified parents](terrain-parent-regions.md), [memory admission](terrain-regional-memory.md) |

## Develop

- [Implementation plan](strategy/README.md): execution order and the same-commit
  update checklist.
- [Current status](research/status.md): what works now, with limits.
- [Decision catalog](research/decision-catalog.md): methods used, deferred or
  rejected, and when to revisit them. Failed trials are in the
  [method register](research/terrain-method-decisions.md).
- [Architecture](architecture/README.md): dependency direction and data flow.
- [ADRs](adr/README.md): accepted decisions (append-only).
- [Research index](research/README.md): dated reports with their measurements.
- [Backlog](../TODO.md), [schemas](../schemas/README.md),
  [examples](../examples/README.md), [dependencies and licenses](DEPENDENCIES.md).
- Supporting strategy: [world-context stages](strategy/world-context.md),
  [landscape evolution](strategy/landscape-evolution.md) and the
  [quality reference](strategy/terrain-quality.md).

## Which document wins

Current behaviour is defined, in order, by code, public schemas, tests and
accepted ADRs. The plan owns order of work; the backlog is a categorized list,
not a sequence. Dated research keeps its original evidence and may go stale.
Promote a chosen method into an ADR and tests, and never rewrite old research to
make a later decision look as if it had always been known.
