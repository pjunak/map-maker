# AGENTS.md — Terrain tool

These instructions govern `src/dmtools/terrain/`. The root `AGENTS.md` also
explicitly routes terrain tests, schemas, examples, benchmarks and documentation
here; they are not automatically discovered from this sibling directory.

## Product contract

The terrain tool compiles authored constraints into deterministic elevation
products. It does not invent or silently change canonical
geography. A run may offer alternatives, but adopting one remains a user
decision.

The build identity is the combination of authored inputs, effective profile,
master seed, schema and generator versions, working grid, algorithm versions,
and runtime environment. Never describe the seed alone as sufficient for exact
reproduction.

## Source boundaries

- `domain/` owns dependency-light types, invariants, units, errors, and ports.
- `pipeline/` owns named deterministic stages and orchestration.
- `adapters/` owns concrete files, GIS libraries, rendering libraries, and
  external processes.
- This `README.md` owns the current terrain-tool overview. Public schemas under
  `/schemas/terrain/` and `/schemas/world/` own serialized field names and
  validation rules for their respective project/product families.

Dependencies point inward. Domain modules must not import adapters or interface
frameworks. Pipeline stages operate on typed domain values rather than loose
dictionaries or global settings.

## Authoritative data

- Vector constraints express coastlines, water levels, spot heights, ridges,
  valleys, divides, breaklines, and terrain-character regions.
- A Float32 raster DEM in metres is the authoritative generated elevation
  surface for a local terrain build. Whole-planet builds instead use node
  elevation on the sphere mesh with triangle-linear interpolation (ADR-0085);
  their rasters and images are derived.
- Contours, hillshade, colour relief, drainage, catchments, and meshes are
  derived outputs and must identify their source DEM.
- Editing changes authored generation inputs only. A generated map may remain
  visible as a read-only placement reference, with explicit stale/current status.
  Regenerate from inputs to apply changes; never patch a completed DEM.
- Zoom-driven local enrichment remains in scope as a planned generation operation.
  Its immutable parent context, coordinate frame, overlap/downsample tolerances
  and inherited hydrology require explicit validation; shared samples alone do
  not establish the complete contract. See ADR-0048.
- Keep numerical sampling and shared-coordinate checks separate from user editing.

## Current delivery priorities

Follow [M1-M8 and its update checklist](../../../docs/strategy/README.md).
Connect context, rough terrain, runoff and aging into a testable experimental
workflow before further isolated refinements. Keep hard correctness checks;
full quality acceptance governs default adoption, not every integration step.
Consult the [research decision catalog](../../../docs/research/decision-catalog.md)
before repeating an investigation, and update decisions/status/backlog with evidence.
Keep new geometry, projection,
serialization, application orchestration and UI responsibilities in cohesive
separate modules. Consult the user before tests expected to exceed roughly two
minutes or with uncertain long duration; state purpose, estimate and stop limit.

## Stage rules

- Give every stochastic stage a stable identifier and a separately derived
  seed.
- Make units, nodata behavior, boundary conditions, and projection explicit.
- Do not mutate input objects or overwrite authored files.
- Write build artifacts to a new output directory and publish the manifest only
  after all authoritative outputs succeed.
- A failed run must not look complete.

## Testing

- Test hard constraints numerically, not only through image snapshots.
- Include invariants for finite values, land/sea masks, units, deterministic
  hashes, drainage connectivity where promised, and shared-coordinate agreement.
- Use small synthetic fixtures with known intent. Large private world maps are
  not test data.
- Document changes to schemas, seed derivation, algorithms and numeric
  tolerances. Follow the root early-development policy: remove superseded
  behavior and test the current implementation without legacy support.
