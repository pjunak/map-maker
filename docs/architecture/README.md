# Architecture overview

Map Maker is a modular Python application with local desktop and command-line
interfaces. A future service could wrap the same application operations, but
hosting is not a committed delivery step for the current local tool.

## System boundary

```text
Tk UI / CLI
     |
     +--> application: world / planet / region / views / local build / sampling
     |           |
     +-----------+--> numeric generation pipeline --> domain values
                 |
                 +--> project / SVG / render / map themes / GeoTIFF / build adapters
```

The workbench also calls generation and adapters directly. There is no generic
adapter-port framework. Domain modules are dependency-light; numeric pipeline
modules currently use NumPy and Shapely geometry. File formats, rendering and
publication remain in adapters outside generation.

The domain and pipeline must remain usable without a web server. Adapters may
depend on Rasterio, GDAL, GeoPackage drivers, image renderers, or external
scientific engines; core contracts must not depend on those concrete libraries.

## Planet path (current product path)

```text
<name>.world.json (+ geology recipe, + wonder document)
   -> pipeline/planet.py: sphere mesh, plates and forcing, uplift + stream-power
      erosion, climate coupling, lakes and volcanoes make the base planet; a
      separate pass adds wonders and works out ice and lakes again (ADR-0097)
   -> PlanetResult (node elevation is authoritative, ADR-0085)
   -> adapters/planet_build.py: planet.npz, GeoTIFF, rivers, lakes, manifest
   -> adapters/map_views.py: theme registry; planet_maps.py draws each theme on
      the world frame with map_*.py and planet_natural.py, in the app only when
      it is first shown; map_projection.py shows any theme as a flat world,
      globe or polar view (ADR-0087), drawn by pipeline/sphere_views.py (ADR-0101);
      globe_model.py writes it as a glTF globe model (ADR-0102)
   -> application/planet_region.py: fixed blended tiles enriched from the
      verified build without its wonders (pipeline/planet_regional.py,
      planet_tiles.py), composed into
      regional windows (adapters/planet_region.py, ADR-0086); deeper levels are
      enriched from level parents built from the coarser tiles
      (pipeline/planet_levels.py, ADR-0088)
```

Stages take typed values and named stage seeds. Display detail in images is derived
and never feeds back into relief, rivers or climate.

## Proposed generation responsibility split

The [2026-09-25 reassessment](../research/2026-09-25-groundwater-and-terrain-architecture.md#proposed-structural-change)
proposes a clearer boundary between authored specification, evolving process state
and frozen published terrain. It is not implemented by the pipeline below.
Initial procedural relief and automatic networks may co-evolve; authored final
heights, coasts and persistent protections keep their declared roles. The
[local-valley comparator](../research/2026-09-26-connected-valley-patches.md) is now
implemented under `benchmarks/evolution`, with separate local-field and raster
checks; its production quality is rejected. The
[automatic-layout comparator](../research/2026-09-26-hard-target-valley-layout.md)
now preserves hard targets while moving only explicitly automatic guides within
bounded corridors. It restores 250 m capture but leaves bank/coarse failures.
The [head/mouth comparator](../research/2026-09-26-valley-heads-and-mouths.md) now
passes all 575 matched local bank pairs, including dense checks. The
[cell-safe delivery comparator](../research/2026-09-27-cell-safe-terrain-delivery.md)
now bounds interpolation excess using curvature, retaining whole-cell protection
with much smaller 250 m bank artifacts. Raster banks still fail. The
[feature-preservation probes](../research/2026-09-27-feature-preserving-terrain-delivery.md)
retain the prepared local field through trusted-data saving/reopening, with exact
profile and common-ground equality. Generic spline reconstruction instead loses
outlets and bounds. The
[guarded snapshot implementation](../research/2026-09-27-prepared-feature-snapshots.md)
now owns numeric copies, verifies complete network/segment identity and bounds
archive loading and metric queries. Original profiles and same-field tile/halo
queries match exactly after reopening. This benchmark component does not yet
provide a general terrain representation, regional generation or filtered LOD.

A potential structural change is to publish an immutable numeric feature surface
and derive declared-resolution rasters from it. That is a proposal: it requires
an ADR, explicit build/schema identities, bounds, parent/LOD checks and changes
to every numeric consumer before adoption. Keep a single authoritative surface;
a rendered river line cannot substitute for ground. A changed interpolator needs
its own interior-bound argument. Current product Float32 DEM authority and the
application pipeline below remain unchanged.

Groundwater, if accepted, needs aquifer head/storage and separate subsurface links;
surface receivers alone cannot own that state. Cave roof/floor geometry requires a
separate representation. Add only state required by an accepted mechanism inside
the current domain/pipeline/application layers, not a general solver framework.
Sampling an immutable result never advances geological time. See the
[method register](../research/terrain-method-decisions.md) for the failures motivating
these proposals and the [strategy](../strategy/README.md) for adoption gates.

## Terrain pipeline

The current implemented path is:

1. Load and validate an SVG or versioned terrain project. Ordinary SVG import
   dissolves closed land geometry; a prepared world-derived SVG restores its
   already projected polygons exactly, including small holes and gaps.
2. Convert normalized authored constraints into the source-bounds local metric
   frame shared by mainland and islands. This is scaling, not a world projection.
3. Compose regional full/macro fields, prepare stable valley profiles and apply
   authored macro constraints before canonical routing. Lake/dry footprints
   absorb flow; regional relief limits automatic incision.
4. Reapply final authored semantics and restore permitted coordinate-addressed
   detail. Return Float32 ground without filling it to the routing surface.
5. Review finished ground on the shared canonical grid, retaining basin labels,
   spill paths, topology and unresolved channel conflicts. `diagnostics.py`
   owns read-only review; `hydrology.py` owns flow and incision primitives.
6. Derive clipped lake water and review shorelines, outlet attachments, full
   external paths and internal wet/dry links against finer Float32 samples.
   `water_sampling.py` owns probe plans; `link_planning.py` shares vector-contained
   candidates and bounded internal-network planning. `outlet_profiles.py`,
   `wet_links.py` and `dry_links.py` own path/link checks. `basin_flow.py` conserves captured
   area while transferring only eligible collections. These checks do not
   establish physical lake equilibrium, discharge or a complete river network.
7. The workbench renders derived relief/review overlays and exports PNG.
   Cartographic water is a separate scale-aware layer: cached whole-pool areas
   drive visibility independently of viewport clipping; scientific ground and
   numeric water remain unchanged. [ADR-0057](../adr/0057-display-water-at-the-appropriate-scale.md)
   also specifies future resolution-gated river visibility during local generation.
   The shared headless build operation writes NPY/NPZ, local-metric GeoTIFF, both
   preview styles, diagnostics and a completion-last manifest through adapters.

The read-only [water-budget operation](../terrain-water-budget.md) shares field
preparation and finished canonical ground with generation. Its pipeline planner
uses the same shoreline/candidate/profile plans, then returns demand without
fine evaluation, transfer, raster output or exports. Application code owns saved
input/runtime verification; the CLI labels internal demand as conditional.

The [regional sampling operation](../terrain-regional-sampling.md) also reuses
full field preparation. Its dependency-light request binds a source identity,
reference endpoint grid, nested fine window and halo before any expensive work.
The pipeline evaluates only bounded regional arrays while retaining complete
canonical context. Separate adapters publish numeric samples and a cropped
scientific ground preview; no full-build reviews or finer hydrology are implied.
Prepared samplers can be reused across requests; GUI jobs remain future work.
The [parent-region operation](../terrain-parent-regions.md) adds
portable snapshot decoding and file/runtime checks in adapters/application,
complete numeric replay in `pipeline/parent.py`, and an opt-in protected residual
in `pipeline/detail.py`. Detail only changes a new regional result. File formats
and publication stay outside those numerical stages; experimental acceptance
and hydrology capability flags stay explicit in the artifact contract.
Each prepared detail context owns bounded scalar cell support with explicit
eviction and clearing; this pipeline cache retains no output arrays. Context
replacement resets that cache. See
[ADR-0062](../adr/0062-reuse-bounded-detail-cell-support.md) for
identity ownership and scalar limits. `application/parent_region.py` now owns
serial sessions retaining one parent/detail context and byte-bounded numeric
results. Files and runtime are checked on every write, including cached requests;
changed provenance closes the session. Cache arrays stay private, while `close`
releases all session references. [ADR-0063](../adr/0063-reuse-verified-parent-region-sessions.md)
defines this lifecycle. `application/region_memory.py` adds shared admission
reservations for staged loading, retained context and active generation/export;
see [ADR-0065](../adr/0065-admit-regional-memory-estimates.md). Estimates are
separate from exact cache bytes and do not impose an OS process-memory ceiling.
`adapters/render.py` shades full native ground in tiles with one-node halos;
`adapters/regional_review.py` owns bounded comparison layouts and tiled difference
colouring. The admission estimator uses the same tile/layout limits. Explicit
image ownership releases scratch on completion and cancellation. This changes
neither numerical stages nor native scientific resolution; see
[ADR-0066](../adr/0066-bound-terrain-rendering-scratch.md).

The [World workspace](../terrain-worlds.md) now adds a separate implemented source
path: retained SVG → explicit full-sphere frame and semantic assignments → topology
and area validation → portable world source. `domain/world.py` owns immutable
inputs and sphere conversions; `pipeline/world.py` owns bounded preparation,
non-overlapping coverage, spherical areas and typed adjustment reports;
`adapters/world_svg.py`, `world_project.py` and `world_render.py` own concrete
formats/previews. `application/world.py` verifies the snapshot and coordinates
open/save. `world_ui.py` supplies background jobs, mapping and document guards.
The CLI exposes `terrain gui --world` and `world inspect`. No new runtime
dependency or numerical terrain stage is introduced. See
[ADR-0070](../adr/0070-retain-world-source-and-workspaces.md).

The [world-to-terrain handoff](../terrain-worlds.md#create-terrain-from-the-world)
is a separate application operation, not a new terrain solver.
`domain/world_terrain.py` owns projection/source values;
`pipeline/world_landmass.py` collects physically connected prepared land;
`adapters/world_projection.py` uses Rasterio/PROJ to produce a metric coast.
`adapters/world_terrain_source.py` owns canonical visible SVG plus lossless,
schema-versioned world/projection metadata. Ordinary terrain projects reference
this source through the existing SVG path/hash contract. `application/world_terrain.py`
reserves a new folder and publishes the project last, after source verification.
`world_terrain_ui.py` owns the selection/actions panel; existing workspaces own
background execution, fresh project loading and unsaved-work guards.
No climate/geology forcing or accepted world parent is implied.
See [ADR-0079](../adr/0079-project-world-land-into-terrain.md).

The [geographic context stage](../world-context.md) is now implemented separately:
`domain/world_context.py` owns spherical grid/settings, `pipeline/world_context.py`
owns area-conserving coverage and vector-derived periodic water topology, and
`pipeline/world_gateways.py` measures finite shared-edge water openings in km.
`pipeline/world_connectivity.py` retains spherical water pieces and separate shared
intervals through split cells; `adapters/world_connectivity.py` verifies stored
incidence against retained source. Graph labels expose precision-limited source
fragmentation, which later transport consumers must reject.
`pipeline/world_exposure.py` measures shoreline distance through a SciPy unit-sphere
index and directional water/support fractions through bounded great-circle sampling.
`application/world_context.py` owns generation/export and verified reopening.
The adapters write numeric/previews and a last-published context manifest;
`world_context_load.py` checks captured products before immutable consumption.
`numeric.py` shares bounded NPY decoding with the terrain-parent adapter. Context
arrays are cell coverage, centre-based measurements and support, not terrain endpoint elevations. No climate,
depth or physical transport is inferred from connected-water IDs.

The [geology input slice](../world-geology.md) adds `domain/world_geology.py`
for profiles/provinces and a common time convention; `pipeline/world_geology.py`
resolves priority into conservative prepared-land coverage. Dedicated adapters
own bounded JSON, full-world fingerprints, atomic persistence and preview colours.
`application/world_geology.py` validates source/geometry at the file boundary.
`world_geology_ui.py` owns an independent recipe editor, background jobs and
history; the parent World workspace includes its unsaved guard. This categorical
input product does not feed the local terrain pipeline or modify context bundles.

The [bathymetry slice](../world-bathymetry.md) adds typed ocean-selection and
margin inputs, actual vector water-centre classification and conservative spherical
distance-to-depth evaluation. Separate adapters own bounded recipes, grid previews
and verified nested-geography bundles. Application jobs refresh older geographic
producers and own cancellation/publication. `world_bathymetry_ui.py` owns independent
input/result state and the parent unsaved guard. `pipeline/world_context.py` exposes
the shared `water_topology` helper so water IDs are consistent across stages.
These cell-centre values are not a land DEM, volume integral or transport capacity.

The remaining [world workflow](../strategy/world-context.md) changes future stage
ownership: retained world source and explicit geography → provisional context →
rough relief/bathymetry → bounded climate/runoff and history feedback → reviewed
immutable world parent → regional refinement to the same present. Ecological
classes are downstream views; climate forcing also informs terrain evolution.
This is not implemented by the current local pipeline above.

Adapters now retain world source groups/IDs before derived wrapped land views;
source ownership is separate from physical connectivity. Domain values own the
explicit source frame/radius and authored geology ages/duration. Future values
add physical forcing and epoch histories;
application operations will own staged jobs, parent/dependency verification and
publication. Numerical stages consume arrays and explicit boundary/forcing data,
not UI state or implicit world globals. Exact public formats arrive with their
implementations. Terrain project v9, input snapshot v4 and build v20 can contain
bounded immutable world-context support for experimental M1 rough terrain; this is
not a climate, water-transport or accepted world-parent contract.
The independent world-source schema contains geography and assignments only.

Continent identity is not a closed solver boundary. Shared climate, catchments and
histories can cross it. Final-state detail and historical refinement have different
capabilities: the latter needs time-dependent parent context and a common target
present. Preserve immutable parents, overlap and hard constraints; keep correction
budgets separate and reject unsupported capabilities. Derived GIS and explicit
hard/soft/inequality projection remain planned contract work.

Source-to-local conversion and uniform endpoint grids are dependency-light
domain values shared by generation, routing, diagnostics, rendering and build
metadata. NumPy axis construction stays in the pipeline. Read the
[coordinate contract](../terrain-coordinates.md) and
[ADR-0025](../adr/0025-centralize-local-frames-and-endpoint-grids.md).

Each stage receives explicit inputs and configuration. It must not obtain
randomness, time, environment settings, or coordinate assumptions implicitly.
The [named seed policy](../terrain-seeds.md) resolves stable stage identifiers
from a master without mutable RNG state. Base coarse and detailed relief remain views of the same stage. The experimental
added cell residual owns a distinct `terrain.local-detail` stage.
There is no alternative seed mode.

Completed-field sampling separates the pointwise evaluator from land masking
and output scattering. It omits ocean coordinates while preserving complete
canonical hydrology grids and precomputed valley profiles. Neighbor-dependent
algorithms must stay outside that pointwise evaluator. The repository-only
[benchmark harness](../../benchmarks/README.md) records stage time, process
memory and numerical identities without adding timing state to the engine.

## Interfaces

The first useful interface is a Tk/ttk desktop workbench launched through the
CLI. It maps controls to typed domain settings, then delegates to the same
pipeline and adapters used by the non-interactive build operation.
A future HTTP service can call those operations while adding job management,
storage, authentication, and resource limits outside the engine.

The current terrain-project adapter translates the public JSON contract into
domain models. It resolves the external SVG relative to the project, verifies
its content hash, then delegates coastline parsing to the SVG adapter. Neither
the domain nor the generation pipeline reads project files directly.

The SVG adapter turns one or more closed land shapes into dissolved polygonal
land geometry. Shared subcontinent edges are removed before generation;
disconnected islands and retained enclosed water use the same metric extent and
coordinate-addressed field. The pipeline therefore receives geometry, not SVG
layer or path boundaries.

## Planned contracts and remaining decisions

The [M1-M8 plan](../strategy/README.md) is the sole delivery order. M1-M4 connect
existing products into an experimental application workflow before further isolated
refinements; M5 accepts the wider world result. This is planned work, not an
additional implemented path in the pipeline above.

| Responsibility | Planned connection / owner |
|---|---|
| Specification and identity | Typed world/context/geology/history inputs in `domain`; matching, freshness and publication in `application`. |
| Physical preparation | Reuse world projection/landmass adapters; add context sampling/support and initial relief preparation in focused numeric modules. |
| Climate and runoff | Separate `pipeline` stages with explicit units, source-water identity, masks and ledgers; no UI or file reads inside numerical code. |
| Evolution | Narrow adapter to the existing reference runtime; shared typed process state and input-role contracts; no benchmark-runner dependency in the core. |
| Candidate delivery | Application-owned stage orchestration, cancellation and bounded feedback; adapters own artifacts; UI/CLI expose real consuming operations. |
| Reviewed parent and regions | Accept in M5; M6 consumes immutable state plus boundary/forcing history and shared present. Sampling never advances time. |

The [world connection table](../strategy/world-context.md#first-integrated-application-slice)
and [evolution adapter contract](../strategy/landscape-evolution.md#experimental-application-integration)
provide data and acceptance details. Additional decisions remain:

- WC1 physical geology forcing and component-aware transport after delivered
  geographic measurements, verified products, geology inputs, bathymetry and
  water-piece incidence/support;
  per-margin depth scenarios and conservative integration when a consumer needs them;
  later WC2-WC5 coupled products and historical parent context
- Generated branches, graph editing, controlled tangents and asymmetric sides
  (point-anchored/line-owned profiles and compatible shared ridge crests are implemented)
- Inter-lake transfer, constrained repair and nested depression policy
  (lake levels, retention, outlet checks and conservative area transfer are implemented)
- River/catchment vector products and external hydrology validation
  (numeric routing, footprint collection and basin review archives are implemented)
- Visual/spectral acceptance of experimental regional detail, inherited finer
  hydrology, zoom scheduling and broader native/application-memory calibration
  (saved-parent admission estimates are implemented)
- WC3 shared seasonal climate/runoff contracts, followed by WC6 ecological
  classification; neither is present in the current runtime
- Web framework, queue, storage, and frontend
- Public project license

These belong in ADRs when enough evidence exists to make the decision. The
[current development strategy](../strategy/README.md) gives their recommended
dependency order; the roadmap remains grouped by product area.

## Input editor and generated reference

The workbench edits immutable domain constraints through a session-local
`InstructionHistory`. Selection changes the controls; Apply replaces one authored
instruction, and undo/redo restores input tuples. Geometry dragging previews an
immutable candidate, validates placement/topology on release and commits once.
`move_instruction` keeps closed rings and lake outlet edge positions consistent.
Opening a project resets history.
A per-job cancellation token identifies worker events and guards UI acceptance.
Cancelled/old results release their images and cannot replace the reference; the
worker retains its slot until it acknowledges the stop. Progress shows elapsed
time and the current stage. Application operations check cancellation before
manifest publication, and reusable sessions retain only valid completed numeric
work. See [ADR-0064](../adr/0064-cancel-generation-at-safe-checkpoints.md).

A `GenerationInputs` snapshot accompanies each worker result. The UI compares it
with current coastline, settings and constraints before treating the result as
current or enabling PNG export. Retained images and review products belong to the
last successful build and never feed back into generation as editable surfaces.
See [ADR-0047](../adr/0047-edit-generation-inputs-only.md), with the regional
scope correction in [ADR-0048](../adr/0048-keep-zoom-driven-detail-generation.md).

Planned local enrichment is a generation operation. It may consume immutable
parent boundary and flow context to create a finer regional result, with stable
coordinates, explicit consistency tests and bounded work. The current whole-map
worker and input history do not yet implement viewport-driven regional jobs.

`MapViewport` owns normalized centre, magnification and visible bounds independently
of the generated raster. All placement/hit testing uses its map transform. The
image adapter renders only a canvas-sized raster. Basin review rasters and the
prepared channel graph are cached by result and review toggles; channel paths
are redrawn at viewport scale, with a separate All channels inspection option.
Navigation does not invalidate inputs or request new terrain. The UI explicitly
owns ground and cached pool-area images until a successful replacement, project
reset or shutdown. Review caches clear on replacement or when Drainage review,
Depressions and Basin catchments are all off; temporary viewport images close
after Tk copies them. Old Tk photo references and the owned poll callback are
released as well.
A failed style render preserves the previous image, water and legend. Water
colour scratch is tiled, and native composition avoids a full overlay. One-shot
rendering returns its owned ground; export of a retained reference makes one
copy. See [ADR-0067](../adr/0067-own-preview-images-and-tile-water.md) and
[the drainage review contract](../terrain-drainage.md). These graph paths still
follow D8; the [strategy](../strategy/README.md) proposes shared terrain-guided
geometry but does not describe it as implemented.

A separate saved `GenerationInputs` snapshot owns dirty-state comparison. Drafts
and pending property/geometry edits also count as unsaved work. Open/import/close
can continue after saving only when the completed save still matches the current
inputs. Worker operations disable input controls; save failure clears the pending
continuation. Tool defaults and navigation alone do not make the document dirty.
See [ADR-0049](../adr/0049-navigate-and-save-authored-inputs.md).
