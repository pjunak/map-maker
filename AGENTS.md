# AGENTS.md — DM Tools

Read this file before changing anything in this repository. More specific
`AGENTS.md` files add constraints within their subtrees.

## Read by task and validate

For terrain changes anywhere in source, tests, schemas, examples, benchmarks or
documentation, read [the terrain instructions](src/dmtools/terrain/AGENTS.md).
This root routing rule covers paths outside that file's physical subtree.
Use [the documentation index](docs/README.md) to find the current architecture,
coordinate, seed and export contracts; [README](README.md) owns setup.
For terrain planning or implementation, follow the single order and same-commit
update checklist in [the living implementation plan](docs/strategy/README.md).

After installing the existing development extras when missing or stale, run
these checks using the active Python 3.14 environment from the repository root:

~~~text
python -m pytest
python -m ruff check .
python -m pyright
~~~

Use focused tests during development. Run the three checks for Python or public
schema behavior changes; inspect the changed workbench flow for visible UI work.
For numeric algorithms, add the relevant reproducibility/invariant or benchmark
evidence without turning performance measurements into fragile timing assertions.
Documentation-only changes need a diff review, link check and verification of
changed claims.

## Purpose

DM Tools is a local-first collection of reusable worldbuilding and tabletop
utilities. Tools must work without a hosted service. A future web application
may expose the same application interfaces, but it must not become the only way
to use or reproduce a tool.

The first tool is a deterministic, constraint-driven terrain generator. It
turns authored geographic constraints and a versioned profile into numeric
elevation data and derived cartographic products.

## Delivery boundary

This is a local application. CI validates the Python tool and retains test
reports; there is no production Compose stack, image dispatch or server rollout
in `pjunak/infra`. Keep generated terrain builds local and reviewable. The
separate TTRPG `addon-dm-tools` package has its own host installation lifecycle.

## Repository contract

- Use CPython 3.14 for project-owned Python code.
- Keep the reusable engine independent of CLI, filesystem, GIS-library, and
  future HTTP concerns.
- Treat files under `src/dmtools/` as product code, `tests/` as executable
  contracts, `schemas/` as public data contracts, and `examples/` as small,
  reviewable demonstrations.
- Do not commit generated terrain builds. Small purpose-built fixtures are
  allowed under `tests/fixtures/` when their provenance is documented.
- Keep user-authored constraints authoritative. Generated output must never
  silently overwrite an input project. The editor changes generation inputs;
  completed maps are read-only references. Changes take effect through a new build.
- Zoom-driven local enrichment is planned generation, not manual DEM editing.
  Preserve its parent identity, coordinate frame and consistency requirements;
  see ADR-0048. Do not remove this capability when excluding output sculpting.
- Record architectural decisions under `docs/adr/`; supersede decisions rather
  than rewriting their history.

## Early-development policy

- Prioritize implementing and improving the current product. Backward
  compatibility, legacy features and old saves are explicitly out of scope.
- Remove obsolete code, settings, schemas, examples and tests when replacing
  behavior. Do not add compatibility modes, old-format loaders, migrations or
  deprecation periods unless the user explicitly requests them.
- Update current examples and documentation together with implementation.
  Record intentional changes; use Git history for superseded implementation.
- Keep version and algorithm identifiers for build provenance and clear
  rejection of unsupported inputs, not as a promise to support old versions.
- Test current correctness and reproducibility. Do not preserve old generated
  output at the cost of better algorithms or simpler foundations.

## Architecture boundaries

The expected dependency direction is:

```text
interfaces -> application pipeline -> domain model
                    |
                    v
                 adapters
```

- Domain code owns units, coordinates, constraints, profiles, grids, manifests,
  and validation rules. It must not depend on CLI or web frameworks.
- Pipeline code orchestrates deterministic stages and depends on domain
  contracts, not concrete file formats.
- Adapters implement GeoPackage, GeoTIFF, image, external-process, and future
  service boundaries.
- Rendering is derived from numeric elevation data; visual products are never
  the authoritative terrain model.

Avoid a plugin system, task queue, database, or web framework until a concrete
requirement justifies one.

## Reproducibility

A numeric seed alone is not a reproducibility contract. Completed builds must
satisfy the current build schema linked from [the schema index](schemas/README.md)
and [the headless build contract](docs/terrain-builds.md). Preserve authored-input
and profile identity, named stage seeds, coordinate/units/nodata policy,
runtime and algorithm identity, and authoritative output hashes as required by
that contract. Record unimplemented extensions in the existing TODO instead of
describing them as completed provenance. Keep version values in their owner.

Changing the order of unrelated pipeline stages must not perturb existing
random streams. Derive stage seeds from stable stage identifiers rather than
sharing one mutable random-number generator.

## Scientific and cartographic integrity

- Store horizontal distances and elevations with explicit units.
- Never run distance-sensitive algorithms directly in angular or page
  coordinates. Use an appropriate metric working projection.
- Distinguish hard constraints, soft guidance, generated hypotheses, and
  derived display layers.
- Validate coastline elevation, authored height constraints, finite values,
  drainage behavior, and shared-coordinate consistency across output grids.
- Describe generated terrain as plausible or process-informed unless the model
  and evidence support a stronger scientific claim.

## Dependencies and licenses

- Prefer mature, maintained libraries over project-owned implementations of
  interpolation, projection, raster I/O, and numerical primitives.
- Keep optional scientific engines behind adapters so the core remains usable
  when an engine does not support Python 3.14 or the current platform.
- Record the package version, license, purpose, and distribution implications
  before adding a restrictive, copyleft, non-commercial, or source-available
  dependency.
- Add dependencies only with an immediate use; do not preload the full research
  shortlist into the base environment.

## Validation and Git

- Add or update tests with behavior changes. Prefer small deterministic fixtures
  and invariant/property tests over large golden rasters.
- Run the narrowest relevant checks while iterating, then the documented
  repository checks before committing.
- Commit logical, validated changes locally. Do not push, publish packages,
  deploy services, or rewrite shared history without explicit authorization.
- Preserve unrelated worktree changes and never commit generated outputs,
  private maps, credentials, or local tool state.
