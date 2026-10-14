# Shape a ridge or valley along its length

Select a completed ridge or valley in the Terrain workspace, then choose
**Profile...**. The dialog edits generation inputs. Apply the profile, then
regenerate; the previous map remains a read-only placement reference.

Add or replace rows using **Position %** and **Value (m)**. Positions follow the
smoothed centreline in physical distance: 0% is the first endpoint, 100% the last.
The profile needs both endpoints, strictly increasing positions and at most
64 knots. It can be cleared to restore the line's base value and ordinary nearby
point attachment. **Flat profile** supplies the endpoints; **Two peaks and a pass**
supplies a starting ridge shape. Cancel discards dialog changes. Apply records one
undoable instruction edit, including any pending line properties.

| Line and mode | Profile value |
|---|---|
| Absolute ridge | Crest height above the sea-level datum, in metres. |
| Relative ridge | Added ridge relief, in metres; not a signed offset from the line's base value. |
| Absolute valley | Preferred floor height in metres, ordered non-increasing from head to outlet. |
| Relative valley | Preferred incision depth in metres; downstream floor conditioning still applies. |

Values replace the base line value along the whole profile. They must be finite
and nonnegative; absolute heights cannot exceed the terrain ceiling. Clear a
profile before changing its elevation mode, so its values cannot silently change
meaning. Moving the line or its vertices retains profile positions as fractions
of the new smoothed length.

The curve preview uses the engine's shape-preserving cubic. It does not overshoot
adjacent knots. Narrow knot spacing also requests finer local water-review
sampling through the existing bounded budget system; this is sampled evidence,
not a continuous clearance certificate.

An explicit profile belongs only to its line. Nearby height points do not attach
to it, but retain their independent final authority on ground.

**Connected absolute ridges:** each profile owns its crest through ridge blending.
Actual line intersections are preserved while the remaining corners are rounded.
Profiles meeting there must agree within 0.001 m; a generation error identifies
both instructions, the contact coordinates and positions along each profile.
Match those values using **Profile...**. Near misses are not automatically snapped.
Use one main crest with branches ending on it; closed/self-crossing profiled
absolute ridges and overlapping line spans are rejected with guidance.

Relative ridges keep their existing relief semantics. Valleys still cut after
the ridge stage, independent height points retain later ground authority, and
the coast remains at sea level. Exact ridge ownership does not override those
rules or impose a global slope limit. A junction's height is not automatically
propagated when you edit another branch. The
[shared-crest report](research/2026-09-27-shared-ridge-crests.md) records these limits.

## Try the public example

Open [range-lowland.terrain.json](../examples/terrain/range-lowland.terrain.json)
and generate. It contains a main ridge with two peaks and a pass, a descending
spur and a valley leading into a lowland region on a synthetic 1,000 km square.
It has no campaign geography. Select one of its lines and open **Profile...**.
For an isolated ridge junction, open
[connected-crests.terrain.json](../examples/terrain/connected-crests.terrain.json).
Its branch meets a protected corner of the main range; profile heights agree there.

```powershell
map-maker terrain gui --project examples/terrain/range-lowland.terrain.json
```

This is an authoring feature. Automatic branching, regional geology histories,
physical erosion and accepted river realism remain planned. The
[comparison report](research/2026-09-27-line-owned-terrain-profiles.md) records
what the current example demonstrates and where combined ground differs.

Current formats are project v9, input snapshot v4, build v20 and regional samples
v3. Ridge/valley inputs require a `profile` array, empty when no explicit profile
is authored. Old formats are unsupported; recreate terrain inputs through the
current world handoff or current examples and rebuild parents. There is no legacy
loader or migration workflow. [ADR-0082](adr/0082-own-structure-profiles.md)
defines the ownership and version contracts.
