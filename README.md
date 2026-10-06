# DM Tools

DM Tools is a local-first collection of reusable worldbuilding and tabletop
utilities. The project begins with a deterministic terrain generator: an engine
that turns authored coastlines, elevation guidance, landform regions, basin
intent, generator settings and a seed into a reproducible digital elevation model.

The application runs locally in Python. A future web
interface should call the same engine rather than replacing it.

## Status

**New (2026-10-06): whole-planet maps.** `dmtools world planet` turns a saved world
into whole-planet relief made by uplift and river erosion on an irregular sphere
mesh: poles, seam and ocean floor included, with rivers that always run downhill.
It can also produce a provisional climate and biome atlas. Your coastline is never
changed, and an optional geology recipe sets where ranges, plateaus and basins
stand. It is experimental. See the [planet guide](docs/world-planet.md) and the
world-first [implementation plan](docs/strategy/README.md).

```powershell
dmtools world planet examples/world/four-shores.dmworld.json --output artifacts/four-shores-planet
```

The earlier local-terrain status follows. The [ordered implementation plan](docs/strategy/README.md)
now puts whole-planet relief (M2) first, with climate (M3) on the same mesh.
The [research decision catalog](docs/research/decision-catalog.md) records what was
evaluated, why it was used or deferred, and when to revisit it. The capabilities
below describe what actually runs today; M1 is experimental rather than accepted
as the default world-parent workflow.

The desktop workbench now has **World** and **Terrain** workspaces.
[World import](docs/terrain-worlds.md) retains the original SVG, continent/island
ownership, an explicit spherical frame and planet radius in portable
`.dmworld.json` files. It provides mapping, validation, pan/zoom and saved-world
inspection. [Geographic context](docs/world-context.md) now adds spherical land
coverage, connected water, separate water-piece links, resolution support, preview layers and portable
exports. Separate [geology](docs/world-geology.md) and
[bathymetry](docs/world-bathymetry.md) workflows now author hypotheses and generate
bounded ocean-floor previews. Geographic context can now influence world-derived
rough terrain; shared climate, runoff, aging and accepted world parents remain planned.

The Terrain workspace imports and dissolves closed SVG land shapes; authors
absolute/relative brush, point, ridge and valley constraints; draws plain, hill,
plateau and mountain regions; and saves those inputs as `.dmterrain.json`.
The editor keeps the last result as a placement reference, supports instruction
selection, property/geometry edits and undo/redo, and marks changed inputs for
regeneration. Pan/zoom, ground inspection, resolution presets and guarded Save /
Save As support testing without editing a completed DEM. Generation now shows
elapsed stage progress and supports Cancel/Esc while retaining the previous map;
see [cancellation](docs/terrain-generation-control.md).
Authored lakes and dry basins retain ground and captured contributing area.
Reviewed lake outlets transfer eligible area downstream, with visible shoreline,
wet-link and dry-path evidence. Water levels are imposed previews, not simulated
lake equilibria.

Generation produces a Float32 ground DEM and separate derived water and drainage
review products. The workbench exports PNG. Headless builds also write NPY/NPZ,
local-metric GeoTIFF, both relief styles, diagnostics and a completion manifest.
A [regional sampling command](docs/terrain-regional-sampling.md) now evaluates
bounded windows more densely using the unchanged full-source field.
[Verified-parent commands](docs/terrain-parent-regions.md) now replay completed
builds and generate separate regional samples or explicitly experimental added
detail. Python sessions reuse verified parents and bounded numeric results with
freshness checks and [shared memory admission estimates](docs/terrain-regional-memory.md).
Visual/spectral acceptance, finer hydrology, workbench zoom jobs and broader
native/application-memory calibration remain open. World-linked terrain builds are
available experimentally when prepared with matching context; validated river
vectors remain future work. See the
[current research status](docs/research/status.md).

An [experimental landscape-evolution command](benchmarks/evolution/README.md)
now generates public comparison terrain through uplift and erosion epochs, with
inspectable snapshots and numerical checks. It uses a separate scientific
environment; history generation is not yet part of the desktop or saved-project CLI.

The [world-context workflow](docs/strategy/world-context.md) begins with the
implemented WC0 source workspace and the geographic subset of WC1: coverage,
connected water, shared-edge openings, shore distance, directional water exposure
and verified reopening. [Geology inputs](docs/world-geology.md) add continent
defaults and drawable provinces with separate ages and overlap priorities.
[Bathymetric hypotheses](docs/world-bathymetry.md) now provide explicit ocean
selection, a shelf/slope/basin depth model, error/support views and verified exports.
Separate water-piece connections and explicit unresolved support are now retained.
**World → Terrain…** now creates a usable terrain project for a selected continent
and its connected neighbours at the world's physical scale. It opens in Terrain
for input authoring and generation; `dmtools world terrain` provides the same
handoff from the CLI. Saved geology recipes can now supply explicit plains, hills,
plateaus and mountain belts; `--context` binds a matching context bundle, and the
desktop automatically uses its currently generated or opened context. The resulting
terrain regions remain editable inputs.
See the [world guide](docs/terrain-worlds.md) and
[landform example](docs/world-geology.md#try-a-complete-landform-example).
Context-bound coastal relief is experimental. Climate/runoff, bathymetry coupling,
aging and regional history replay remain planned; this does not make a reviewed
world parent.
See the [research review](docs/research/2026-09-24-world-context-enrichment.md).

## Requirements

- CPython 3.14
- Git
- Tk 9 (included with the official Windows CPython 3.14 distribution)

Runtime dependencies and their roles and licenses are recorded in
[the dependency register](docs/DEPENDENCIES.md).

## Quick start

Create a Python 3.14 virtual environment and install the project in editable
mode with its development tools:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Then open Map Workbench and run the tests:

```powershell
.\.venv\Scripts\dmtools.exe --help
.\.venv\Scripts\dmtools.exe terrain gui
.\.venv\Scripts\python.exe -m pytest
```

GitHub CI uses Windows and Python 3.14 to run the complete pytest suite, Ruff,
and strict Pyright checks, including the display-free Tcl settings tests.
Pytest reports are retained for 14 days. Secret scanning runs separately with
the complete Git history available.

Try the complete world-source workflow with
`dmtools terrain gui --world examples/world/four-shores.dmworld.json`; see the
[world guide](docs/terrain-worlds.md). With no startup file the World tab opens.
Select **Terrain** to generate local terrain.

Open the public
[`example.dmterrain.json`](examples/terrain/example.dmterrain.json) project or
import its [`coastline.svg`](examples/terrain/coastline.svg) directly for a first
generation. You can also launch directly with
`dmtools terrain gui --project examples/terrain/landform-regions.dmterrain.json`.
Use **Save As** for a working copy and **Quick test · 257 px** for a small first run.
**Save** updates that copy; **Open project** restores its coastline, generator
settings, constraints and per-tool controls. The
[editor guide](src/dmtools/terrain/README.md#quick-testing-and-navigation) lists
navigation, editing and keyboard controls.

## Current workflow

```text
authored constraints + terrain profile + master seed
                         |
                         v
               deterministic pipeline
                         |
          +--------------+---------------+
          |              |               |
          v              v               v
     Float32 DEM    numeric reviews   visual previews
```

Authored vector constraints and configuration remain inputs. A floating-point
raster DEM is the authoritative generated elevation surface. Water and drainage
reviews, hillshade and colour relief are derived products. Contour/river vectors
and meshes are planned.

Build the same saved project without opening the workbench:

```powershell
dmtools terrain build examples/terrain/example.dmterrain.json --output artifacts/example-build
```

Read the [numeric build guide](docs/terrain-builds.md) for products, coordinate
limits, diagnostics and completion checks. Builds include lossless NPY arrays
and [Float32 GeoTIFF](docs/terrain-geotiff.md) in an explicit local metric frame.
World placement of generated DEMs remains planned; saved worlds already retain
source-to-sphere coordinates independently of local terrain builds.

The current [project and build schemas](schemas/README.md) and
[named stage seed algorithm](docs/terrain-seeds.md) describe implemented behavior.
This project is in early development: obsolete features and old saves are not
supported. Current correctness and useful improvements take priority.

## Repository layout

| Path | Responsibility |
|---|---|
| `src/dmtools/` | Shared package and command-line interface |
| `src/dmtools/terrain/` | Terrain domain, pipeline, and adapters |
| `schemas/` | Versioned public input and manifest schemas |
| `examples/` | Small public example projects |
| `tests/` | Unit, contract, integration, and deterministic regression tests |
| `benchmarks/` | Repeatable development-only terrain timing and memory probes |
| `docs/architecture/` | Current system structure and data flow |
| `docs/adr/` | Append-only architecture decisions |
| `docs/strategy/` | Current dependency-aware development order |
| `docs/research/` | Dated evidence and prototype recommendations |

Start with [the current development strategy](docs/strategy/README.md), then see
[the documentation reading guide](docs/README.md) and
[complete file inventory](docs/FILE_INDEX.md),
[the architecture overview](docs/architecture/README.md), and
[the terrain tool guide](src/dmtools/terrain/README.md). The categorized
implementation backlog is maintained in the [terrain tool roadmap](TODO.md).
Use the [benchmark guide](benchmarks/README.md) to compare performance without
changing authored projects or introducing machine-dependent test thresholds.

## Design principles

- Local use is complete use; hosting is an additional interface.
- Reproduction requires matching inputs, algorithms, runtime and named seeds.
- User-authored geographic constraints are never silently mutated.
- Numeric terrain data is authoritative; rendered maps are derived.
- Edit generation inputs over a read-only generated reference, then regenerate.
  Completed DEMs are never sculpted or patched in the editor.
- Shared-coordinate values remain consistent across output grid sizes.
  Local enrichment must additionally preserve parent geography and match
  neighboring regional boundaries; see [ADR-0048](docs/adr/0048-keep-zoom-driven-detail-generation.md).
- Scientific language remains honest about what the model does and does not
  prove.

## Licensing

The repository does not yet declare a distribution license. Adopted dependency licenses
are recorded in the [dependency register](docs/DEPENDENCIES.md). A project license must be chosen before
the first public release.
