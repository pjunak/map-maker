# AGENTS.md — Map Maker

Read this file before changing anything in this repository.
[`src/map_maker/terrain/AGENTS.md`](src/map_maker/terrain/AGENTS.md) adds the terrain
rules. It also governs terrain tests, schemas, examples, benchmarks and
documentation outside its own directory, so read it for any terrain change.

## Commands

Use the active Python 3.14 environment from the repository root. Install the
development extras as described in [README](README.md) when they are missing or
stale.

~~~text
python -m pytest            # full suite, about 13 minutes; use focused tests while iterating
python -m ruff check .
python -m pyright
map-maker terrain gui         # desktop app
map-maker world planet | region | view   # planet build, regional detail, projected views
map-maker world refine-coast             # the refined coast as a new SVG source map
~~~

- **Python or public-schema changes** need all three checks.
- **Visible UI work** needs the changed flow inspected in the running app.
- **Numeric algorithms** need reproducibility, invariant or benchmark evidence, never
  fragile timing assertions.
- **Documentation-only changes** need a diff review, a link check and verification
  of every changed claim.
- **Long experiments:** ask before ones expected to take more than about two
  minutes, unless the user has authorized long experiments. The full test suite is
  the documented gate.
- **No source edits during a test run:** do not change `.py` files under
  `src/map_maker/` or `benchmarks/` while pytest runs, including a background run.
  Builds and benchmark comparisons fingerprint those sources at start and finish
  and reject completion when they differ, so tests fail with "changed during".

## Where things are

- [Documentation index](docs/README.md).
- [Planet guide](docs/world-planet.md): `world planet`, `region` and `view`,
  outputs and limits.
- [Living plan](docs/strategy/README.md): execution order and the same-commit
  update checklist.
- [Decision catalog](docs/research/decision-catalog.md).
- [Schema index](schemas/README.md).
- [ADRs](docs/adr/README.md). Current product path:
  - ADR-0085: planet relief on a sphere mesh;
  - ADR-0086: regional tiles;
  - ADR-0087: map themes and projections.
- Code lives in `src/map_maker/terrain/`:
  - `domain/`, `pipeline/`, `adapters/` and `application/`;
  - the desktop UI in `*_ui.py`;
  - the map theme registry in `adapters/map_views.py`.

## Invariants

- **Local-first.** Every tool works without a hosted service. A future web app may
  reuse the application interfaces, but must not become the only way to use a tool.
- **Dependency direction.** Interfaces depend on the application layer, which
  depends on the pipeline, which depends on the domain. Adapters own files, GIS,
  rendering and external processes. Numba kernels belong to the pipeline
  (ADR-0085). Add no plugin system, task queue, database or web framework without a
  concrete need.
- **Authored inputs are authoritative.**
  - Outputs never overwrite an input project.
  - Builds go to new directories, and the manifest is written last.
  - A failed run never looks complete.
  - The editor changes inputs only; completed maps are read-only references.
- **Reproducibility** follows the [build schemas](schemas/README.md):
  - stage seeds are derived from stable stage identifiers, so reordering stages
    does not perturb other random streams;
  - bump the owning algorithm identifier whenever outputs change.
- **Scientific integrity.**
  - Use explicit units, and metric projections for distances.
  - Distinguish constraints, hypotheses and derived layers.
  - Call generated terrain plausible, not real.
- **Zoom.** Zoom-driven enrichment (ADR-0048) is planned generation, not DEM editing.
- **Early development.**
  - No compatibility modes, old-format loaders or migrations.
  - Remove obsolete code, settings, schemas, examples and tests when replacing
    behaviour.
  - Update examples and documentation in the same commit.
- **Dependencies.** Prefer mature libraries. Add a dependency only for an immediate
  use. Record version, license and distribution impact before adding a restrictive,
  copyleft or source-available one.
- **Decisions.** Record architectural decisions as ADRs under `docs/adr/`, and
  supersede them rather than rewriting them.

## Delivery and Git

- **Delivery.** This is a local application: CI validates and keeps test reports,
  and nothing is deployed.
- **Committing.** Commit validated, logical changes locally. Never push, publish
  or deploy without explicit authorization.
- **Never commit** generated builds (`artifacts/`), private maps, credentials or
  local tool state. Preserve unrelated work in the tree.
