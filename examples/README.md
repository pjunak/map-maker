# Examples

Examples are small, public, reproducible projects intended for learning,
documentation, integration tests, and performance comparisons.

Do not copy private campaign maps here. Every generated example artifact must be
rebuildable, and large outputs should remain outside Git.

## World

[`world/four-shores.dmworld.json`](world/four-shores.dmworld.json) embeds the
synthetic [`world/coastlines.svg`](world/coastlines.svg): four invented continents,
touching mainlands, owned islands, an inland hole, excluded furniture and a
periodic seam-crossing island. The source is purpose-built for this repository
and contains no campaign geography. Use **Save As** for your working copy.

```powershell
dmtools terrain gui --world examples/world/four-shores.dmworld.json
dmtools world inspect examples/world/four-shores.dmworld.json
```

The explicit full-sphere frame is (10, 10)..(370, 190), central meridian 0°,
radius 6,500 km. Its SVG display size intentionally differs from source units.
The [world guide](../docs/terrain-worlds.md) explains importing the raw SVG,
confirming ownership/frame. Use **Geographic context → Generate context** or the
[context command](../docs/world-context.md) to inspect this example's spherical
coverage, connected exterior water, inland hole and seam-island support.

The separate [`four-shores.dmgeology.json`](world/four-shores.dmgeology.json)
recipe adds invented stable-interior defaults, a cross-continent active belt and
an explicit seam-crossing rift. Open it with **World → Geology → Open a recipe…**
or inspect with `dmtools world inspect-geology examples/world/four-shores.dmgeology.json`.
The [geology guide](../docs/world-geology.md) explains priorities and age/duration
semantics. It does not run erosion or change the source coastlines.

The separate [`four-shores.dmbathy.json`](world/four-shores.dmbathy.json) selects
Water 1 with an illustrative 100 km / 200 m shelf, 200 km slope and 4,000 m basin,
at 90 latitude rows. Open it with **World → Ocean floor → Open the ocean-floor editor… → Open inputs…** after
matching context is available, or run
`dmtools world bathymetry examples/world/four-shores.dmbathy.json --output artifacts/four-shores-ocean`.
See the [bathymetry guide](../docs/world-bathymetry.md) for numerical limits and
reopening/export commands. The profile is a scenario, not calibrated geology.

## Terrain

[`terrain/example.dmterrain.json`](terrain/example.dmterrain.json) is a complete
versioned project that references
[`terrain/coastline.svg`](terrain/coastline.svg), a synthetic closed vector
object containing no campaign geography. Open the JSON to restore settings and
authored constraints, or import the SVG alone to begin a fresh project.

The example always uses the current project format and named stage seeds.
Update it with implementation changes; do not keep legacy variants.

Saved projects verify the exact SVG bytes with SHA-256. The repository
[Git attributes](../.gitattributes) preserve LF line endings for SVG files,
including fresh Windows checkouts with `core.autocrlf=true`.

The [landform region example](terrain/landform-regions.dmterrain.json) adds four
soft polygon recipes to the public terrain coastline. See the
[region guide](../docs/terrain-regions.md) for controls and limitations.


The [range/lowland example](terrain/range-lowland.dmterrain.json) adds line-owned
profiles for two peaks, a pass, a descending spur and a valley. Open it in the
Terrain workspace, generate, select a line and choose **Profile...**. The
[profile guide](../docs/terrain-structure-profiles.md) explains controls and limits.

The [local-detail example](terrain/local-detail.dmterrain.json) uses the public
landform inputs at 65 longest-side parent nodes and two detail bands. Follow the
[verified-parent guide](../docs/terrain-parent-regions.md) to sample the completed
parent or create a separate experimental detail result.

The [authored-water example](terrain/basin-water.dmterrain.json) adds a lake and
a dry-basin footprint, preserving their ground while exporting water separately.
It demonstrates closed-basin retention and review.

The [connected-outlet example](terrain/connected-outlet.dmterrain.json) adds an
explicit valley reaching the coast. Its eligible lake outlet transfers captured
area downstream while isolated dry pockets retain their contributions.

The [flat-outlet example](terrain/flat-outlet.dmterrain.json) uses a zero-relief
plateau, shorter coastal transition and narrower height influences. Its exact
Float32 flats exercise internal routing with exits, including paths to lower
closed pits. Basin details separates resolved flat samples from those that
reach connected water. This synthetic scene tests routing, not lake stability.

The [shoreline-gap example](terrain/shoreline-gap.dmterrain.json) adds a narrow
zero-height point on the connected example's lake boundary. Its coarse outlet
path remains clear and detects no uncontrolled opening, but finer boundary
samples reveal the gap. The outlet stays blocked and orange review dots locate
the low ground. This demonstrates a real generated feature, not a painted mask.

The [narrow-shoreline-gap example](terrain/narrow-shoreline-gap.dmterrain.json)
reduces that height point's influence radius to 200 m. Fixed quarter-grid probes
miss the opening entirely; local feature-guided probes now detect it and retain
the lake's captured area. It uses the same public coast and a 750 m imposed level.

The [downstream-barrier example](terrain/downstream-barrier.dmterrain.json) adds
an unattached relative height point (+50 m, 100 m influence radius) to the
connected outlet's external valley. Canonical nodes still descend, but the full
feature-guided profile finds a 43.85 m climb from an earlier low. Transfer stays
blocked and a red diamond locates the crest. The entire path is below the imposed
lake level; the example tests conservative ground review, not hydraulic flow.

The [internal-water-barrier example](terrain/internal-water-barrier.dmterrain.json)
adds a relative +1,500 m point with a 100 m influence radius inside the lake's
narrow wet channel. Canonical wet nodes remain one component, but finer checks
remove its single bridging link. All lake area stays retained; the selected
contact is unchanged and a red diamond marks the separating ground.

The [dry-collection barrier example](terrain/dry-collection-barrier.dmterrain.json)
adds a relative +150 m point with 100 m influence radius on a dry descent inside
the lake footprint. Feature-guided profiles expose a 131.44 m climb missed when
only that point's refinement is omitted. The donor takes a clear neighbouring
route and still contributes to the outlet. Both reviews use identical terrain
and captured MFD area; the point itself remains authored ground.

The [connected crest example](terrain/connected-crests.dmterrain.json) reuses the
public range/lowland square and joins a descending spur at a main ridge corner.
Its compatible absolute profiles retain the shared junction during smoothing;
see the [profile guide](../docs/terrain-structure-profiles.md).
