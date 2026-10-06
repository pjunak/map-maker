# Runtime dependency register

The terrain application uses the following runtime dependencies. The
version range in `pyproject.toml` is authoritative; versions below are the
minimum accepted versions when the dependency was adopted.

This register lists adopted runtime packages and data, development-only
validation tooling, and the explicitly isolated research environment below. Evaluated
candidates are indexed in the [decision catalog](research/decision-catalog.md),
with [dated evidence](research/README.md). The [implementation plan](strategy/README.md)
orders their evaluation; adoption still requires an immediate
need, supported-platform validation, and a completed license review.

| Dependency | Minimum | Purpose | License |
|---|---:|---|---|
| CPython Tk/ttk | 3.14 / Tk 9 | Native desktop widgets, progress, and file dialogs | PSF / Tcl-Tk BSD-style |
| NumPy | 2.5.2 | Deterministic array computation and Float32 elevation grids | BSD-3-Clause |
| SciPy | 1.18.1 | Exact unit-sphere shoreline queries; bounded research surface feasibility/quadratic fitting | BSD-3-Clause; retain bundled native notices |
| Pillow | 12.3.0 | In-app raster preview and PNG export | MIT-CMU |
| Shapely | 2.1.2 | Polygon validity, land mask, and distance-to-coast queries | BSD-3-Clause |
| svgelements | 1.9.6 | SVG shape/path parsing, transforms, and curve evaluation | MIT |
| Rasterio | 1.5.1 | Local-metric Float32 GeoTIFF I/O through GDAL | BSD-3-Clause |
| Affine | 3.0.1 | Explicit sample-to-raster affine mapping | BSD-3-Clause |

Primary references:

- [Python Tkinter documentation](https://docs.python.org/3/library/tkinter.html)
- [NumPy licensing](https://numpy.org/doc/stable/license.html)
- [Pillow licensing](https://github.com/python-pillow/Pillow/blob/main/LICENSE)
- [Shapely project documentation](https://shapely.readthedocs.io/)
- [svgelements package page](https://pypi.org/project/svgelements/)

## Development-only schema validation

`jsonschema >=4.25,<5` (MIT) validates the current build manifest and its project
schema reference in tests. Version 4.26.0 and its dependency stack were verified
on Windows / CPython 3.14.7. It is installed through the `dev` extra and is not
needed by the build command or desktop runtime. Its `referencing` dependency
provides the offline schema registry used by those tests.
See the [validator documentation](https://python-jsonschema.readthedocs.io/en/stable/validate/).

## Development and research kernels

`numba >=0.68,<1` (BSD-2-Clause) with its `llvmlite` dependency (BSD-2-Clause with
LLVM's Apache-2.0-with-LLVM-exception notices) compiles the graph kernels of the
[planet relief harness](../benchmarks/planet/README.md). Numba 0.68.0 / llvmlite
0.50.0 were installed from Windows x64 CPython 3.14 wheels and exercised with
NumPy 2.5.2. It is in the `dev` extra only; promoting the planet core to the
application will move it to runtime dependencies with this entry updated.

## Vendored data assets

| Asset | Version | Purpose | License |
|---|---:|---|---|
| Scientific Colour Maps `oleron` land lookup table | 8.0 | Perceptually ordered, colour-vision-deficiency-safe elevation tint | MIT; Copyright (c) 2023 Fabio Crameri |

The terrain renderer includes entries 128–255 of the `oleron` RGB table rather
than adding a plotting-library dependency. See the
[upstream palette](https://github.com/callumrollo/cmcrameri/blob/main/cmcrameri/cmaps/oleron.txt),
[Scientific Colour Maps](https://www.fabiocrameri.ch/colourmaps/), and the
[vendored license notice](licenses/SCIENTIFIC_COLOUR_MAPS_LICENSE.txt).

The repository itself still needs a distribution license before a public
release. Dependency permissions do not license project-owned code.

## GeoTIFF runtime

Rasterio 1.5.1 and Affine 3.0.1 passed local Windows / CPython 3.14.7 checks.
The environment rechecked on 2026-09-13 reports GDAL 3.12.4 and PROJ 9.8.1. Build manifests
record these package/native versions. Rasterio and Affine are runtime
requirements because every headless build writes a GeoTIFF; native I/O stays
inside adapters. Domain and numerical generation do not import them.

The upstream [Rasterio license](https://github.com/rasterio/rasterio/blob/main/LICENSE.txt)
and [Affine license](https://github.com/rasterio/affine/blob/main/LICENSE.txt)
permit redistribution with attribution/notice retention. GDAL uses an
[MIT-style license](https://gdal.org/en/stable/license.html); PROJ has its own
[MIT-style notice](https://proj.org/en/stable/about.html#license).
When packaging native wheels, retain their bundled third-party notices too.


## Spherical distance runtime

SciPy 1.18.1 was installed from its Windows x64 CPython 3.14 wheel and exercised
with NumPy 2.5.2 for [geographic exposure](world-context.md). The installed license
permits redistribution under BSD-3-Clause and includes bundled native notices.
Retain all applicable wheel notices when packaging; no SciPy source is vendored.
Runtime identity includes its version. See [ADR-0075](adr/0075-measure-spherical-geographic-exposure.md)
and the [KDTree API](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.KDTree.html).
This does not adopt Landlab, py-richdem or the rest of the reference environment.

## Isolated landscape-evolution reference

The repository-only [evolution experiment](../benchmarks/evolution/README.md)
now runs an isolated Landlab stack on Windows x86-64 / CPython 3.14.7. The reference stack is
installed under ignored `artifacts/`, separately from the application. SciPy is
also an application dependency for the independent geographic use above. The [wheel lock](../benchmarks/evolution/requirements-windows-py314.txt)
pins all 53 distributions and SHA-256 hashes used by the experiment, including
plotting and test tooling and existing application dependencies.

| Reference package | Tested version | Immediate use | License / boundary |
|---|---|---|---|
| Landlab | 2.11.0 | D8/depression routing, implicit incision and conservative hillslope reference | MIT; not the license of the whole stack |
| SciPy | 1.18.1 | Landlab numerical dependency | BSD-3-Clause; wheel includes additional native notices |
| Matplotlib | 3.11.2 | Standalone scientific comparison figures | Matplotlib/PSF-style license; retain bundled notices if distributed |
| py-richdem | 2.2.0rc3 | Landlab-declared dependency; selected model does not call it | GPL-3.0-only, prerelease; research environment only |
| wrapt | 2.5.0rc1 | Resolved transitive dependency | BSD-2-Clause, prerelease |

Versions/licenses were checked against the installed wheel metadata and license
files. Primary package references: [Landlab](https://pypi.org/project/landlab/2.11.0/),
[py-richdem](https://pypi.org/project/py-richdem/2.2.0rc3/),
[SciPy license](https://github.com/scipy/scipy/blob/main/LICENSE.txt), and
[Matplotlib license](https://matplotlib.org/stable/project/license.html).
The [2026-09-25 groundwater/canyon review](research/2026-09-25-groundwater-and-terrain-architecture.md)
also checked imports and signatures for GroundwaterDupuitPercolator, LateralEroder,
Lithology and SpaceLargeScaleEroder in this existing environment. No new packages
were installed and no new groundwater/canyon simulation was run. GOEMod and
MODFLOW/CFP remain external research candidates, not dependencies.

An isolated reference installation is not adoption or redistribution approval.
LE3 must select the actual production implementation and review all shipped
transitive/native notices before bundling. The project distribution-license
question above remains open.
