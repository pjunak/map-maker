# AGENTS.md — Terrain tool

These rules govern `src/dmtools/terrain/`. The root `AGENTS.md` routes terrain
tests, schemas, examples, benchmarks and documentation here as well.

## Product contract

- The tool turns authored geography into deterministic elevation and map
  products. It never invents or silently changes canonical geography; adopting
  an alternative is the user's decision.
- **Build identity.** Authored inputs, settings, master seed, schema and algorithm
  versions, grid or mesh, and runtime together identify a build. The seed alone
  does not.
- **Authoritative surfaces.**
  - Planet builds: node elevation on the sphere mesh, with triangle-linear
    interpolation (ADR-0085).
  - Local terrain builds: a Float32 DEM in metres.
  - Everything else is derived and identifies its source build: rasters,
    contours, hillshade, map themes, rivers, regional windows.

## Source layout

- **`domain/`** holds dependency-light types, settings, invariants and units.
- **`pipeline/`** holds named deterministic stages and Numba kernels.
- **`adapters/`** holds files, GIS, rendering and map themes:
  - `map_views.py`: the theme registry;
  - `map_projection.py`: projections;
  - `map_*.py`: theme renderers.
- **`application/`** holds use cases for the CLI and UI: generate, export, region,
  views.
- **`*_ui.py`, `workbench.py`, `viewport.py`** hold the Tkinter interface. They
  call the application layer and never pipeline internals.
- **Public schemas** under `/schemas/terrain/` and `/schemas/world/` own
  serialized field names.

Domain code must not import adapters or UI frameworks. Stages take typed values,
not loose dictionaries or global settings.

## Stage rules

- Give every stochastic stage a stable identifier and its own derived seed.
- Make units, nodata, boundary conditions and projection explicit.
- Never mutate inputs or overwrite authored files. Write builds to new
  directories, with the manifest last.
- Keep new geometry, projection, serialization, orchestration and UI concerns in
  separate cohesive modules.

## Planning and testing

- **Planning.** Pick work from the [living plan](../../../docs/strategy/README.md)
  and check the [decision catalog](../../../docs/research/decision-catalog.md)
  before repeating an investigation. Update both in the same commit as the work.
- **Hard constraints.** Test them numerically, not only through images: finite
  values, land/sea masks, units, deterministic hashes, drainage where promised,
  and shared-coordinate agreement.
- **Fixtures.** Use small synthetic fixtures with known intent. Private world maps
  are not test data.
- **Changes to schemas, seeds, algorithms or tolerances.** Document them, and bump
  the owning identifier.
