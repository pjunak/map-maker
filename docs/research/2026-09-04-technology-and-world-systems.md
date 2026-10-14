# Technology and world-systems research — 2026-09-04

This note refreshes the available terrain, geospatial, storage, climate, and
classification options for the next development strategy. It is dated evidence,
not an accepted dependency list or implementation contract.

## Evaluation criteria

Candidates were evaluated for deterministic use, Python 3.14 and Windows
availability, numerical transparency, local-first operation, licensing,
interchange with standard GIS tools, and usefulness to the current roadmap.
Packages should solve a demonstrated need rather than replace understandable
in-project algorithms merely because they are mature.

## Numerical surface tools

### SciPy

SciPy 1.18.1 requires Python 3.12 or newer and publishes CPython 3.14 Windows
wheels under a BSD license. Relevant primitives include sparse linear solvers,
Euclidean distance transforms, and `RBFInterpolator`. The RBF implementation
also supports a local-neighbour mode; this matters because an unrestricted RBF
system has quadratic memory growth in the number of observations.

Recommendation: add SciPy only when implementing the measured local-RBF versus
sparse screened-Poisson spike. Make neighbour selection, solver tolerances,
iteration limits, and failure diagnostics explicit so determinism does not
depend on hidden defaults.

Sources: [SciPy package](https://pypi.org/project/scipy/),
[`RBFInterpolator`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html),
[sparse linear algebra](https://docs.scipy.org/doc/scipy/reference/sparse.linalg.html),
and [Euclidean distance transform](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.distance_transform_edt.html).

## Geospatial interchange

### Rasterio, pyproj, and GDAL

Rasterio 1.5.1 requires Python 3.12 or newer and publishes CPython 3.14 Windows
wheels. It is the best-fitting Python adapter for writing the authoritative
Float32 GeoTIFF without coupling the terrain domain to GDAL objects. pyproj
3.7.2 also advertises Python 3.14 wheels and should own explicit coordinate
transform operations when those become necessary.

GDAL remains the interoperability reference: its GeoTIFF driver supports
Float32 raster data and its contour tool can derive vector contours from a DEM.
The command-line tools are useful independent validation even when Rasterio is
the application adapter.

Recommendation: adopt Rasterio when GeoTIFF export is implemented, keep CRS and
world-coordinate choices in domain metadata, and validate sample files with
GDAL. Do not make rendered PNG or SVG output authoritative.

Sources: [Rasterio package](https://pypi.org/project/rasterio/),
[pyproj history](https://pyproj4.github.io/pyproj/stable/history.html),
[GDAL GeoTIFF driver](https://gdal.org/en/stable/drivers/raster/gtiff.html), and
[GDAL raster contours](https://gdal.org/en/stable/programs/gdal_raster_contour.html).

## Hydrology and landscape processes

### Landlab

Landlab 2.11.0 requires Python 3.11 or newer, publishes a CPython 3.14 Windows
wheel, and uses the MIT license. Its grid, flow-routing, depression-handling,
and landscape-evolution components make it the lowest-friction Python
comparison adapter for the in-project hydrology and future stream-power spikes.
Its data model should not replace the public Map Maker domain model.

Source: [Landlab package](https://pypi.org/project/landlab/).

### GRASS GIS

GRASS `r.watershed` and `r.terraflow` provide mature single- and multiple-flow
direction, accumulation, watershed, and terrain-flow references. The Python
`grass.tools` API is still documented as experimental until GRASS 8.6, and the
GPL distribution boundary is materially different from a permissive Python
library.

Recommendation: use version-pinned GRASS commands for external fixture
comparison, not as an implicit core runtime.

Sources: [GRASS `r.watershed`](https://grass.osgeo.org/grass-stable/manuals/r.watershed.html)
and [GRASS `r.terraflow`](https://grass.osgeo.org/grass-stable/manuals/r.terraflow.html).

### Whitebox and Fastscape

Whitebox exposes useful breaching, filling, D8, D-infinity, and FD8 tools, but
the wider product family mixes open components with licensed products and an
EULA. Any selected executable or package therefore needs a component-specific
license and redistribution review. Fastscape is a useful BSD-licensed landscape
evolution reference, but the latest package information found does not provide
the same current Python 3.14 confidence as Landlab.

Recommendation: retain both as references. Prefer Landlab for the first
executable comparison and audit Whitebox only if one of its algorithms proves
uniquely valuable.

Sources: [Whitebox Python tool reference](https://www.whiteboxgeo.com/manuals/api/python/api-tools-reference.html),
[Whitebox terms](https://www.whiteboxgeo.com/terms.html),
[Fastscape package](https://pypi.org/project/fastscape/), and
[Fastscape stream-power process](https://fastscape.readthedocs.io/en/stable/_api_generated/fastscape.processes.DifferentialStreamPowerChannel.html).

## Multidimensional and chunked data

xarray 2026.7 provides named dimensions and coordinates over array data and is
a natural fit for monthly climate variables such as `temperature[month, y, x]`.
Zarr 3.3 provides compressed, chunked multidimensional storage and advertises
Python 3.14 support. Both add useful abstractions, but neither is required by
the current single-DEM pipeline.

Recommendation: keep GeoTIFF as the initial authoritative exchange format.
Evaluate xarray when the climate prototype has several seasonal fields; adopt
Zarr only if profiling shows that partial regional reads or full-world array
size justify it.

Sources: [xarray package](https://pypi.org/project/xarray/),
[xarray terminology](https://docs.xarray.dev/en/stable/user-guide/terminology.html),
and [Zarr package](https://pypi.org/project/zarr/).

## Climate fields before climate zones

A useful fantasy-world climate generator should model continuous variables
before assigning labels. Latitude and orbital assumptions provide seasonal
insolation; elevation applies a lapse-rate response; distance from ocean and
transport direction create continentality; terrain redirects moist airflow and
creates orographic precipitation and lee-side rain shadow.

The Smith-Barstad linear theory is attractive for an interactive first model
because it represents airflow, conversion and advection of condensed water,
and downslope evaporation with an efficient spectral solution. FAO
Penman-Monteith provides a standard potential-evapotranspiration formulation
when radiation, temperature, humidity, and wind fields exist. A Budyko-style
aridity relation is a useful long-term water/energy-balance diagnostic, not a
substitute for seasonal simulation.

Sources: [Smith and Barstad linear orographic precipitation](https://doi.org/10.1175/1520-0469(2004)061%3C1377:ALTOOP%3E2.0.CO;2),
[FAO Penman-Monteith](https://www.fao.org/4/X0490E/x0490e06.htm), and
[Budyko water-balance review](https://pmc.ncbi.nlm.nih.gov/articles/PMC8244049/).

## Climate software

### Climlab and xclim

Climlab 0.9.2 is an MIT-licensed process-oriented climate-model toolkit with
energy-balance, insolation, radiation, and transport components. It is valuable
for formulas and comparison experiments, but optional compiled components and
the complete Windows/Python 3.14 path require a local spike. xclim 0.62 is an
Apache-licensed xarray-based climate-indicator library with Python 3.14 listed;
it computes indicators from climate data but does not generate a fantasy
planet's climate.

Recommendation: use both as references and possible validation adapters. Keep
the first interactive model small, explicit, and owned by Map Maker.

Sources: [Climlab package](https://pypi.org/project/climlab/) and
[xclim package](https://pypi.org/project/xclim/).

### ExoPlaSim

ExoPlaSim is a real three-dimensional general circulation model with a Python
API. It is GPL-licensed, requires C and Fortran tooling, and documents Windows
operation through WSL. Such a model is operationally much heavier than the
interactive terrain tool and can exhibit sensitivity that makes it unsuitable
as the source of stable authoring feedback.

Recommendation: treat ExoPlaSim as an optional external plausibility experiment
for a few frozen world configurations, not as the production climate backend.

Sources: [ExoPlaSim repository](https://github.com/alphaparrot/ExoPlaSim) and
[ExoPlaSim documentation](https://exoplasim.readthedocs.io/en/stable/source/exoplasim.html).

## Zones, biomes, and environmental categories

Köppen–Geiger climate classes are a recognizable visualization of temperature
and precipitation regimes. Holdridge life zones relate biotemperature,
precipitation, and potential-evapotranspiration ratio more directly to broad
ecological expectations. Both are derived classifications and neither should
replace the continuous climate fields.

Biome generation should add elevation, growing season, wetness, slope, aspect,
substrate, disturbance, and authored ecological exceptions. Boundaries should
start as suitability or confidence fields rather than falsely precise cell
edges.

Bog, plain, tundra, and field do not belong in one mutually exclusive list:

- a **bog** is a wetland/ecosystem controlled by hydrology and substrate;
- a **plain** is a landform measured from relief and slope;
- **tundra** is a biome or life-zone outcome; and
- a **field** is cultural land use constrained by suitability and human choice.

Store and render them as overlapping derived layers. This is both more
scientifically honest and more useful for worldbuilding queries.

Sources: [Köppen–Geiger map and classification paper](https://doi.org/10.1038/sdata.2018.214),
[USDA Holdridge life-zone data](https://research.fs.usda.gov/iitf/products/dataandtools/holdridge-life-zones-puerto-rico-usvi),
[NOAA climate-classification overview](https://www.climate.gov/maps-data/climate-data-primer/how-do-scientists-classify-different-types-climate), and
[WorldClim reference variables](https://www.worldclim.org/data/worldclim21.html).

## Resulting recommendation

The next work should not begin with named biomes. First stabilize reproducible
terrain output and regional refinement. Then build a deterministic, inspectable
global climate-field prototype and validate it against simple Earth analogs.
Only after those continuous fields behave plausibly should versioned climate
classifications, ecological suitability, wetlands, landforms, and cultural
land-use layers be derived.
