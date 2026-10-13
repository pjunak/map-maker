# Schemas

Only the current formats are supported:

- [World project v1](world/project-v1.schema.json): portable `.dmworld.json` source
  snapshot, full-sphere frame/radius and explicit continent/island assignments.
  This is a validated source, not a climate/terrain build or generated parent.

- [World terrain source v2](world/terrain-source-v2.schema.json): metadata embedded
  in a canonical prepared SVG, retaining the world, selected/connected ownership,
  metric polygons, custom-sphere projection and optional original geology recipe. Project v9 references this SVG
  normally; runtime loading also checks its canonical visible paths and fixed scale.

- [World context v4](world/context-v4.schema.json): generated spherical coverage using
  `spherical-geography-v5`, separate water-piece connectivity/support,
  vector-derived water regions, shared-edge widths, shore distance, eight-direction
  water exposure, resolution support and hashes of the numeric
  arrays, previews and original world snapshot. This is not a terrain parent.

- [World geology v2](world/geology-v2.schema.json): separate `.dmgeology.json`
  input recipe with retained world identity, continent defaults, priority provinces
  and independent ages/duration, plus optional explicit landform controls. Terrain
  creation consumes those controls; categories/ages do not imply physical forcing.

- [Bathymetry inputs v1](world/bathymetry-inputs-v1.schema.json): portable
  `.dmbathy.json` world snapshot, explicit water IDs and shelf/slope/basin assumptions.
- [Bathymetry v1](world/bathymetry-v1.schema.json): negative ocean-floor centre
  samples, numerical error/support, a retained verified geographic dependency and
  result hashes. Neither a land DEM nor physical transport/heat capacity.

- [Planet build v1](world/planet-build-v1.schema.json): experimental whole-planet relief
  (`sphere-mesh-stream-power-v25`), provisional climate and ice sheets
  (`planet-climate-v7`). Node elevation on the sphere mesh is authoritative;
  world-frame GeoTIFF/images are derived. Not a world parent.

- [Planet region v1](world/planet-region-v1.schema.json): experimental regional detail
  window (`planet-blended-tiles-v7`) from cached tiles of a planet build; local
  azimuthal-equidistant GeoTIFF and previews.

- [Terrain context v1](terrain/context-v1.schema.json): bounded geographic support
  serialized as a verified compressed sample binding, plus the metadata report
  retained by a completed terrain build. It does not redefine the terrain land mask.
- [Project v9](terrain/project-v9.schema.json): authored `.dmterrain.json` inputs,
  including hole rings, line-owned ridge/valley profiles and an optional nullable
  frozen world-context binding.
- [Build v20](terrain/build-v20.schema.json): numeric products, coordinates,
  algorithm identities, named stage seeds, output hashes and the nullable context
  consumption/retention report.
- [Regional samples v3](terrain/regional-samples-v3.schema.json): bounded
  unchanged-field windows, source/runtime identity, halo/crop coordinates and
  explicit capability limits.
- [Input snapshot v4](terrain/input-snapshot-v4.schema.json): portable effective
  geometry, typed constraints, settings, authoring state and the nullable frozen
  world-context binding for current builds.
- [Parent region v1](terrain/parent-region-v1.schema.json): verified-parent samples
  or explicit experimental detail, fixed cell moments and hydrology limits.

Register all current schemas locally by `$id` for validation. The project,
input snapshot and build reference the shared terrain-context definitions. The build
references project settings; regional samples reuse current project settings
and the build's runtime, seed and file-identity definitions. None depends on
obsolete formats.
Terrain numeric arrays use an endpoint-node SVG-local plane. GeoTIFF records the
same samples in local metres with an upward y axis; neither raster format has
a world CRS. A prepared world-derived SVG and an optional bound world context retain
source projection and planetary scale; this is not encoded as build/GeoTIFF georeferencing.
See the [build guide](../docs/terrain-builds.md) and
[seed contract](../docs/terrain-seeds.md).

The [world guide](../docs/terrain-worlds.md) describes the implemented source
format and its independent geographic contract. The
[context guide](../docs/world-context.md) owns the implemented geographic result.
The [world-context plan](../docs/strategy/world-context.md) specifies future shared
climate/history and regional boundary products. Those later products have no
public schema yet; do not add placeholders to source or terrain formats.

During early development, replace obsolete formats and update the current
example, tests and documentation. Version identifiers record provenance and
reject unsupported input; old saves, compatibility loaders and migration paths
are out of scope. Superseded schemas are available in Git history.
