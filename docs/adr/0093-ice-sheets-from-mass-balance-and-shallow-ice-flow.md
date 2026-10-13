# ADR-0093: Grow ice sheets from mass balance by shallow-ice flow

- Status: accepted (experimental product path)
- Date: 2026-10-13
- Extends ADR-0085 (planet relief) and the provisional climate; applies the
  outline refinement of ADR-0090 and ADR-0092 to ice margins.

## Context

Ice was the climate's ice-cap class: nodes whose warmest month stays below 0 °C.
Maps drew it where that class, interpolated linearly on the mesh, passed 0.5, on
a perfectly plastic dome over a 150 km-smoothed bed. On Aethelara's polar
continent the result was a white band whose edge followed a line of latitude,
broken into straight triangle facets, with tundra holes inside it and lakes on
it. It ignored snowfall, ice flow and the ice's own height, so dry polar plains
froze and wet ones did not, and nothing could explain Antarctica-like sheets on
land with warm summers. Regional windows drew no ice at all: rivers and lakes
crossed the bed under a snow colour.

## Decision

1. **Mass balance.** Ice grows where snowfall outweighs melt at the ice surface.
   Melt is the precipitation that balances a glacier at its equilibrium line
   for the warmest-month temperature (Ohmura et al. 1992), the relation the
   snowline display already uses. The surface is colder by the lapse rate and
   drier by 7 % per degree of cooling. Large sheets cool their summers by up to
   5 °C through albedo, by the ice share within 300 km.
2. **Regional climate.** Summers wander by about 1.6 °C (one standard
   deviation) over 250–1,000 km (stage `planet.ice`), standing in for the
   stationary waves and sea-ice patterns the zonal climate model lacks, so
   equilibrium lines and margins meander.
3. **Flow.** The shallow-ice approximation with Glen's law (n = 3, A = 1e-16
   Pa⁻³ yr⁻¹) on the mesh's cotangent weights, integrated explicitly from no ice
   for 100 kyr in 10-year steps. Diffusivity is capped where that step would be
   unstable, which binds only on steep, thick mountain ice the mesh does not
   resolve. Ice calves where it reaches the sea; there are no ice shelves.
4. **Stored on the build.** `planet.npz` carries `ice_m` (thickness) and
   `ice_balance_m` (mass balance on land). Lakes do not form under ice; rivers
   are not drawn on it. The climate algorithm becomes `planet-climate-v7` and the
   relief algorithm `sphere-mesh-stream-power-v25`, since lakes follow the ice.
5. **Ice sheets are drawn with their own surface.** A body of at least
   100,000 km² whose mean thickness is at least four times its bed's relief
   between neighbouring ice nodes is an ice sheet. Maps draw it where its surface,
   on the bed smoothed over 0.6 mesh spacings, lies above their detailed
   relief, inside a margin refined by the nested warp of ADR-0090 (6 spacings,
   0.6-spacing amplitude, stage `planet.ice-outline`). Thickness near the
   margin follows Nye's plastic profile. Firn shows above the equilibrium line,
   bluish bare ice below it, with world-anchored undulations and boosted
   hillshade. Smaller or rugged bodies, mountain icefields the mesh does not
   resolve, keep the per-pixel snow and glacier colour.

## Revision (2026-10-13)

Point 5 first measured the bed's relief as the difference between neighbouring
ice nodes. That difference shrinks on finer meshes: at 3.2 million nodes the
polar sheet scored 21.8 instead of 11.7, and two mountain icefields (132,000 and
170,000 km²) passed the test and were drawn as flat white sheets over their
ranges. Relief is now the bed's standard deviation within about 50 km, which does
not change with the mesh once the mesh resolves it: the polar sheet scores 10.5
at both 800k and 3.2 million nodes, and every mountain body stays below 3.

## Consequences

- On Aethelara the polar sheet is up to 2.4 km thick, covers the land poleward
  of 80 °S and most of it to 75 °S, and ends on land along its meandering
  equilibrium line, with an ablation band and meltwater rivers at its margin in
  regional windows.
- Dry, cold ground can stay bare, and wet uplands can carry ice caps.
- A sheet's margin on a broad plain stays smooth at world scale: with dry polar
  snowfall the ablation zone is about one mesh spacing wide, so the margin
  follows the regional climate rather than ice dynamics.
- The model adds about 11 s to an 800k-node build.
- Mountain ice is modelled but drawn as snow and glaciers, so a range can hide
  rivers under ice that its map shows as snowy rock.

## Alternatives considered

- **A warmest-month threshold (the old class).** Rejected: it ignores snowfall,
  flow and the ice's height.
- **A fixed point of balance flux and Nye's profile.** Tried first: ice was where
  routed accumulation exceeded melt, on a plastic surface from the margin. It
  never settled: margin nodes flipped every iteration, and after a monotone
  growth phase each trim removed fewer nodes without stopping (587, 364, 172 …
  35 after ten).
- **Spatially varying flow (soft-bed sliding) for lobes.** Tried: the margin did
  not move, because it sits on the equilibrium line where the ablation zone is
  narrow.
- **Every ice body drawn as a sheet.** Rejected: mountain icefields became flat
  white blobs over whole ranges.
