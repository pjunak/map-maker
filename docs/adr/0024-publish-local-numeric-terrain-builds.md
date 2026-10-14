# ADR-0024: Publish local numeric terrain builds before changing algorithms

**Status:** Accepted
**Date:** 2026-09-05

## Context

The workbench saves authored projects and PNG previews, but its Float32 DEM
exists only in memory. The research comparisons need preserved numeric output,
actual sampling distances, provenance and spatial measurements. Introducing
new noise or geological processes before preserving this baseline would make
their effects harder to assess and reproduce.

The existing generator maps the dissolved SVG's longest dimension to
`object_scale_km`. Coordinates start at the minimum source x/y and increase
right/down. This is an endpoint-node local plane, with no established world
CRS or planetary radius. A georeferenced export must not invent those values.

## Decision

- Add `map-maker terrain build PROJECT --output NEW_DIRECTORY`, using the same
  project loader and generation pipeline as the desktop workbench.
- Save lossless, pickle-free NPY arrays: little-endian Float32 metre elevations,
  a boolean land mask and two little-endian Float64 coordinate vectors in km.
  Retain NaN outside land. This is a local numeric build format; GeoTIFF remains
  the planned GIS interchange format after the world-coordinate contract.
- Save both existing PNG styles and a read-only diagnostic report. The report
  separates canonical drainage measurements from statistics on the delivered
  DEM. Directional height differences and semivariances use requested 25,
  100 and 400 km distances, rounded to the nearest interval (half upward) on
  each axis. Record actual distances and pair counts; reject pairs spanning
  masked samples. Unsupported distances return null, not a fabricated zero.
- Publish the version-1 completion manifest last. Reserve a new destination
  exclusively; reject existing directories and leave failed builds without a
  manifest. Do not delete partial products or overwrite authored material.
- Record exact project/SVG hashes, effective input geometry/settings, runtime
  versions, installed Python-source fingerprint, algorithm identifiers, output
  hashes, local coordinate conversion and actual routing/diagnostic spacing.
  Recheck input hashes and runtime/source identity before completion.
- Keep existing generator math and shared macro/detail seed behavior. Record
  that legacy coupling explicitly; separately derived stage seeds need a
  versioned future change. New algorithm identifiers start at this baseline.
- Derive build identity from sorted, indented JSON (UTF-8, default ASCII escaping,
  finite JSON values, trailing newline), excluding only `build_id` itself.
  Omit timestamps and destination paths so identical inputs/source/runtime
  produce identical products and manifests on repeated local runs.

## Limits and consequences

The manifest is a completion/provenance contract, not a promise of physical
realism, cross-platform bitwise equality, parent/child consistency or world
georeferencing. Readers must verify product hashes before trusting a build.
The package-source fingerprint includes all installed package Python files and
their relative names; even non-numeric source changes can change build identity.
Dependency version records do not archive dependency binaries or capture every
machine-level floating-point configuration.

`inputs.json` is an effective-state provenance snapshot, not a portable project
bundle or a new import format. The original saved project and SVG remain the
supported regeneration inputs. No source project schema changes or migrations
are required.

Directional measures use raw heights without detrending or resampling and
equally weighted samples rather than cell areas. Their raw spatial structure
is complementary to elevation distributions, not a single realism score.
Rotation-normalized, arbitrary-angle, geological and peak/pass measurements
remain research. The output-grid diagnostic does not replace canonical drainage
or claim that rivers on the exported DEM are fully validated.

## Validation

Tests cover exact DEM/mask/coordinate round trips, repeated file and manifest
identity, unchanged inputs, existing-directory rejection, failed publication,
input edits during generation/export, physical lag rounding, rotated ramps,
identical histograms with different spatial structure, masked gaps, missing
support and invalid land/spacing. The pre-change public example at 64-pixel
resolution has Float32 byte SHA-256
`9d688cef915815cea39a1b1052a5080f15c95688f6105ef5bcc53d68382c467f`;
compare this baseline after implementation without making it a cross-platform
golden test.

Implementation validation on Windows / CPython 3.14.7: all 96 tests passed,
including Draft 2020-12 manifest validation using an offline project-schema
registry. Ruff and Pyright passed. The pre-change DEM hash matched exactly,
and the actual CLI built the public example at its saved 768-pixel setting.
