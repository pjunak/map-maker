# DM Tools

DM Tools is a local-first set of worldbuilding and tabletop tools. Its terrain
tool turns a world you have drawn (an SVG coastline plus optional geology) into
deterministic, plausible relief, climate and maps. It runs in Python on your
computer; any future web interface would call the same engine.

Everything here is experimental early-development software. Old saves and
obsolete features are not supported.

## What it does

- **Whole-planet maps:** `dmtools world planet`. Your coastline is never changed.
  The planet's relief comes from plate-driven uplift and river erosion on a sphere
  mesh. That includes mountain belts, rifts, volcanoes, an ocean floor with
  ridges and trenches, lakes and rivers. A provisional climate adds winds,
  rainfall, biomes and Köppen zones. Opt-in extras add volcanic islands and
  fantastical *wonders*. See the [planet guide](docs/world-planet.md).
- **Map views:** `dmtools world view` and the app's World map view. Any map theme
  (natural atlas, relief, topographic, parchment, climate, plates, sea-floor age,
  drainage basins, geology) can be shown as a flat world, a globe, or a polar view.
- **Regional detail:** `dmtools world region` and **Zoom to region / province / local** in
  the app.
  About 5 km detail for part of the planet, from cached tiles that agree
  wherever they overlap.
- **World authoring:** World workspace in the app. Import and map an SVG world,
  generate geographic context, and author geology and ocean-depth hypotheses
  ([world guide](docs/terrain-worlds.md)).
- **Local terrain:** Terrain workspace and `dmtools terrain build`. The original
  composed generator and editor for one landmass, with a Float32 DEM, water
  review and headless builds ([builds](docs/terrain-builds.md)).

## Quick start

You need CPython 3.14 with Tk (included in the official Windows installer) and
Git.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\dmtools.exe terrain gui --world examples/world/four-shores.dmworld.json
```

The same planet from the command line:

```powershell
dmtools world planet examples/world/four-shores.dmworld.json --output artifacts/four-shores
dmtools world view artifacts/four-shores --theme atlas --projection globe --lat 20 --output globe.png
dmtools world region artifacts/four-shores --lon 10 --lat 5 --radius-km 400 --output artifacts/region
```

Run the checks with `python -m pytest`, `python -m ruff check .` and
`python -m pyright`. CI runs the same on Windows with Python 3.14.

## Documentation

- [Documentation index](docs/README.md): guides, architecture, decisions and
  research.
- [Current status](docs/research/status.md) and the
  [implementation plan](docs/strategy/README.md).
- [Terrain tool guide](src/dmtools/terrain/README.md): editor controls and the
  local generator.
- [Schemas](schemas/README.md), [ADRs](docs/adr/README.md),
  [backlog](TODO.md) and [dependencies and licenses](docs/DEPENDENCIES.md).

## Repository layout

| Path | Responsibility |
|---|---|
| `src/dmtools/terrain/` | Domain, pipeline, adapters, application layer and desktop UI |
| `schemas/` | Versioned public input and manifest schemas |
| `examples/` | Small public example projects |
| `tests/` | Unit, contract, integration and deterministic regression tests |
| `benchmarks/` | Development-only experiments, synthetic worlds and probes |
| `docs/` | Guides, architecture, ADRs, strategy and dated research |

## Design principles

- Local use is complete use; hosting would be an additional interface.
- Authored geography is never silently changed. You edit inputs and regenerate;
  completed maps are read-only references.
- Numeric terrain is authoritative. Images and map themes are derived from it.
- Reproduction needs matching inputs, algorithm versions, runtime and named stage
  seeds, not the seed alone.
- Zoomed detail must agree with its parent and its neighbours
  ([ADR-0048](docs/adr/0048-keep-zoom-driven-detail-generation.md)).
- The scientific language stays honest about what the model does and does not
  show.

## Licensing

No distribution license is declared yet; one must be chosen before a public
release. Dependency licenses are recorded in the
[dependency register](docs/DEPENDENCIES.md).
