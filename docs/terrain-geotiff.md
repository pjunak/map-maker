# Local-metric GeoTIFF export

Every headless build now writes `elevation.tif` alongside the numeric NPY
products. It contains the same Float32 DEM, with no elevation resampling or
image colour conversion. Use `map-maker terrain build PROJECT --output NEW_DIRECTORY`.
The desktop workbench still exports PNG; use the saved project build command
for GeoTIFF.

## Coordinate meaning

This is a **local engineering coordinate system**, not a planetary projection.
The source's minimum x/y is the local origin. The authored object scale still
sets the longest dimension in kilometres. The TIFF uses metres, with local
Easting increasing source-right and local Northing increasing source-up:

```text
Easting  =  1000 * x_km
Northing = -1000 * y_km
```

Rows and elevation values keep their original order. The negative y scale in
the TIFF transform makes the first row the top of the map without flipping
arrays. There is no EPSG world CRS, ellipsoid, latitude/longitude or planetary
radius. Do not assign an Earth CRS or infer campaign-world placement from the
local kilometre scale alone. World-derived terrain sources now retain a custom
sphere, working projection and source origin in their prepared SVG; see the
[coordinate contract](terrain-coordinates.md#world-derived-terrain-sources).
That correspondence has not yet been transferred into raster georeferencing.

## Sample registration

The generator produces endpoint nodes. GeoTIFF marks them `PixelIsPoint`
(`AREA_OR_POINT=Point`); GDAL's affine transform describes pixel outer corners.
For sample origin `(x0, y0)` and spacings `(dx, dy)`, all in metres after the
axis conversion, the top-left outer corner is half a sample outward. This
keeps pixel center `(column + 0.5, row + 0.5)` on the original numeric node.

Consequently raster outer bounds extend half a spacing past the first and
last sample on every side. Never use the node extent directly as the TIFF
outer bounds. This implements the [GDAL point-registration convention](https://gdal.org/en/stable/development/rfc/rfc33_gtiff_pixelispoint.html).

The manifest's `coordinates` block retains the generator's kilometres and
downward y axis. Its `geotiff` block records the local CRS WKT, six affine
coefficients in Rasterio/Affine order `(a, b, c, d, e, f)`, raster outer bounds
`(west, south, east, north)` in metres, axis directions and point registration.

## Values, masks and provenance

- One Float32 band stores elevation in metres, with band unit `m`.
- Finite land elevations include zero-height coastlines and ground beneath
  authored lake water. SVG non-land (ocean and enclosed gaps) is NaN nodata
  and invalid in the embedded mask; lake-water coverage does not mask the DEM.
- DEFLATE compression and floating-point prediction preserve numeric values.
  Blocks are 256 by 256; no external mask or PAM sidecar is required.
- Tags identify the local coordinate model, unspecified world position,
  sibling `manifest.json`, and SHA-256 of sibling `elevation.npy`.
- The completion manifest hashes the TIFF and records Rasterio, Affine, GDAL
  and PROJ versions. The TIFF links to the manifest by filename; embedding the
  final build hash would create a circular hash dependency.

The NPY and TIFF containers represent the same authoritative surface; NPY
remains convenient for NumPy analysis. A failed TIFF export never publishes a
complete manifest. Existing destinations are rejected. The adapter rejects
nonuniform coordinate axes, mismatched masks, nonfinite land elevations and
finite values outside land instead of silently repairing or resampling them.

## Inspect

```python
from pathlib import Path
import rasterio

with rasterio.open(Path("artifacts/example-build/elevation.tif")) as dem:
    elevation_m = dem.read(1)
    land = dem.read_masks(1) != 0
    print(dem.crs, dem.transform, dem.bounds)
    print(dem.xy(0, 0), dem.units, dem.tags())
```

Tests compare bytes against NPY, verify unequal spacing and translated origins,
read raw scale/tiepoint/registration tags with Pillow independently of GDAL's
coordinate interpretation, and check embedded masks, repeat builds and failures.
Rasterio 1.5.1's `rio info` CLI cannot inspect this engineering CRS: it
unconditionally requests Earth longitude/latitude. The direct Python inspection
above works and avoids that unsupported transformation. This is a CLI limitation,
not a reason to label the data with an invented Earth CRS. A desktop GIS
display/reprojection workflow has not yet been manually verified.
See [Rasterio georeferencing](https://rasterio.readthedocs.io/en/latest/topics/georeferencing.html)
and [ADR-0028](adr/0028-export-local-metric-geotiff.md).
