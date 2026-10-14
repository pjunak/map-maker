# Generate an ocean-floor hypothesis

Bathymetry is now a separate, inspectable WC1 product. Choose which connected
waters represent oceans and specify a shelf, slope and basin profile. The
result preserves the source coastline and continent ownership. It does not yet
change land terrain, drainage, climate or erosion.

## Try it in the workbench

1. Open a world in **World**. The planet makes its own sea floor; this tool is a
   hand-tuned alternative.
2. Open **Ocean floor** under **More tools** and click **Open the ocean-floor
   editor…**. It works on geographic context: if none is open, the tool generates
   it first at the Geographic context page's grid. The largest connected water region
   is initially selected as a suggestion. Review it; Ctrl/Shift selects several.
   Connected regions are not automatically classified as oceans or lakes.
3. Set the latitude rows, shelf width/depth, slope width and basin depth. Starting
   values (100 km, 200 m, 200 km, 4,000 m) are illustrative hypotheses, not measured
   or calibrated values for your world.
4. Choose **Generate ocean floor**. An older producer or changed row count triggers
   fresh geographic context. Generation and reopening run in the background and
   show progress and **Cancel** in the status bar; the previous result stays available
   on failure/cancel.
5. Compare **Ocean floor**, **Distance error** and **Resolution support**. Hover
   reads sample values under the map. Wheel zoom, drag to pan and **Fit** aid
   inspection; zoom does not generate more samples.
6. **Save inputs** writes a separate `.bathy.json` recipe. **Export result…**
   asks for a new directory and includes a complete geographic dependency.
   **Open result…** verifies the saved result and restores its input snapshot for
   review; Save asks for an authored destination, never automatically overwriting
   that generated snapshot.

Changing an input marks the retained preview **PREVIOUS RESULT** and blocks
export until regeneration. Closing/replacing the world includes the bathymetry
unsaved-input guard. Save uses atomic replacement and rejects external file
changes. Input save is a short indivisible operation; cancellation applies to
background reads, generation and export. No post-generation painting is offered.

## Headless example

From the repository root with the existing environment:

```powershell
.\.venv\Scripts\map-maker.exe world bathymetry examples/world/four-shores.bathy.json --output artifacts/four-shores-ocean
.\.venv\Scripts\map-maker.exe world inspect-bathymetry artifacts/four-shores-ocean
```

The output directory must not exist. The public example selects Water 1 and uses
90 latitude rows. Its embedded source is the synthetic Four Shores world.

## Numeric meaning and limits

The grid has 4–360 latitude rows and twice as many columns. These are cell-centre
samples on the [context sphere](world-context.md), not terrain endpoint nodes or
area-average depths. Widths use kilometres; positive authored depths use metres.
Generated bed elevations are negative metres relative to the coast datum, zero
at the ideal vector coast. Land and unselected water are NaN. Sea membership comes
from the source water geometry, never from elevation sign.

For offshore distance `d`, shelf width `w`, slope width `v`, shelf depth `h` and
basin depth `b`, the positive depth profile is:

```text
S(t) = t² (3 − 2t), with t clamped to [0, 1]
D(d) = h S(d/w) + (b − h) S((d − w)/v)
```

The profile is continuous with continuous first derivative, monotone and bounded
by `b` before Float32 rounding. Basin depth must be at least shelf depth. Widths
and depths must each be finite, between 1 and 100,000 in their stated units; these
are admission bounds, not geological calibration. There is one profile for all
selected waters in this first implementation. No randomness or ocean-age inference
is used. Constant abyssal depth and simplified margins will look schematic.

The geographic distance `u` is an upper bound from sampled retained shoreline,
with recorded maximum overestimate `E`. Evaluate `D(max(0, u − E))` to avoid
claiming a deeper resolved margin than the geographic sampling supports. This
creates a deliberate shallow/zero strip near the coast. The separate error field
bounds the possible depth difference within that distance interval, including
Float32 rounding; its conversion rounds outward. **It is not geological model
uncertainty**, survey accuracy or a tolerance on the imported source curve.
The distance preview scale runs from zero to the authored basin depth.

Actual centre membership is recomputed against water polygons. A mixed cell's
dominant ocean ID cannot assign depth to a land or lake centre. Tiny selected
waters with no centre samples are listed explicitly. Context mixed/split/subcell
flags remain visible, even where no depth sample exists. A zero flag does not
certify that the chosen physical shelf is resolved. Increasing display zoom
cannot resolve a shelf narrower than the geographic sampling.

The product does not establish ocean volume, water capacity, sill depth, a
transport graph, mixed-layer heat storage, ocean currents, plate ages, ridges,
trenches, or land erosion. Those require separate representations and validation.
Ocean-column depth must not be used as seasonal mixed-layer depth. The existing
land DEM zero-clipping contract is unchanged.

## Portable input and result contracts

[Inputs v1](../schemas/world/bathymetry-inputs-v1.schema.json) retain the complete
world snapshot and its canonical fingerprint, the current geographic algorithm,
sorted explicit water IDs and numeric profile. World identity includes source,
frame, radius and assignments. Input files are limited to 40 MiB. The application
checks identities and cross-field rules beyond JSON Schema. Only current formats
are supported.

[Result v1](../schemas/world/bathymetry-v1.schema.json) contains:

| File | Meaning |
|---|---|
| `input.bathy.json` | Exact generation input snapshot; never the automatic Save target |
| `geography/` | Independently verifiable current context bundle and retained world |
| `bathymetry.npz` | Little-endian Int32 `centre_water_body`; Float32 `bed_elevation_m` and `distance_depth_error_m` on the same grid |
| `bed.png`, `distance-error.png`, `support.png` | Derived grid-resolution previews |
| `bathymetry.json` | Completion manifest, input/runtime identity, units/nodata, sample/support summaries and product hashes |

The completion manifest is published last. A failed/cancelled folder has no
completed outer manifest, even if its nested geography finished. Reopening checks
bounded numeric headers before allocation, hashes, full geographic dependency,
actual centre membership, the profile's numeric values, summaries and PNG sizes.
Manifest limits are 4 MiB, the numeric archive 8 MiB and each preview 4 MiB. Source
geometry/native-library memory and nested context have their own limits; these
file caps are not a process-memory guarantee.

Older producer runtimes of the current format can be inspected; exports must
match the producing runtime. Regeneration refreshes geography when software or
requested resolution differs. See [ADR-0077](adr/0077-generate-authored-ocean-depths.md),
[implementation evidence](research/2026-09-25-authored-world-bathymetry.md) and
[the remaining WC plan](strategy/world-context.md).


Current geographic dependency: context v4 / `spherical-geography-v5`, including
water-piece incidence and unresolved-region support. Recreate bathymetry recipes/results linked to earlier context algorithms
from the retained world; no migration is provided.
Depth generation remains a centre-sample hypothesis and does not consume graph
links as volume, sill or transport coefficients.
