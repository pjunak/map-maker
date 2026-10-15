# ADR-0097: Add wonders as a separate layer on a base planet

- Status: accepted (experimental product path)
- Date: 2026-10-15
- Extends: [ADR-0085](0085-generate-planet-relief-on-a-sphere-mesh.md) (planet relief),
  [ADR-0086](0086-regional-planet-detail-from-blended-tiles.md) (regional tiles) and
  [ADR-0091](0091-age-wonders-on-their-own-patches.md) (aged wonders)
- Refines: [ADR-0096](0096-guided-world-steps.md) (a Wonders step joins the guided steps)

## Context

Wonders were made inside the planet build, after erosion and climate. Random kinds
and their age were planet settings; hand-placed wonders were landmarks in the
geology recipe. That coupled them to everything else:

- Any wonder change rebuilt the whole planet. On the four-shores example a
  Standard build (200,000 nodes) took 49 s, of which erosion and climate took
  43 s and placing every wonder, ice, lakes and the sea floor about 5 s.
- Moving a landmark changed the geology recipe, so the build identity of the
  erosion changed although erosion never used landmarks.
- Regional tiles were cached under the whole planet's identity, so toggling a
  wonder discarded every tile. They were also enriched from the finished planet,
  whose lakes and routing include the wonders, so they did depend on them.
- Hand-placed wonders of one kind shared one random stream: removing the first
  chasm reshaped the second.

## Decision

1. **A base planet and a wonder pass.** `generate_base` makes the planet without
   wonders: erosion, climate, filled basins, ordinary volcanoes, and then ice,
   lakes and the sea floor. It keeps the ground before lakes. `finish_planet` adds
   wonders to that ground: wonder volcanoes, wonders and their aging, eruptions,
   then ice, lakes, splitting rivers and the sea floor again. Without wonders the
   base planet is the result. Random wonders use the same streams as before and
   land in the same places.
2. **Wonders are their own inputs.** Random kinds and the default age move from
   `PlanetSettings` to `WonderSettings`. Hand-placed wonders move from the geology
   recipe to a `.wonders.json` document (`map-maker.world-wonders` v1), bound to its
   world as a geology recipe is. The geology recipe loses its optional landmarks
   (format v2 without that field); a recipe that still has them is refused with a
   pointer to the new document.
3. **Each placed wonder has its own seed.** Its random draws come from its seed and
   its kind, so adding, removing or reordering other wonders, or changing the
   planet seed, does not redraw it; only its depth follows the ground it is cut
   into. A new seed gives the same wonder another shape.
4. **Two identities.** The base identity hashes the world and geology inputs, the
   planet settings and the runtime. The planet identity adds the wonder settings
   and the wonder document. A build records both (`base_sha256` and
   `build_sha256`), the wonder settings and a copy of the wonder document; its
   format becomes planet build v2.
5. **Regional tiles come from the base.** Tiles enrich the planet without wonders
   and are cached under the base identity, so wonder edits keep every tile. Windows
   draw the wonders on top, as before, and add the crater-floor levelling
   (`crater_floor_m`) so crater floors stay level. A build with wonders archives the
   base fields that tiles need: surface, routing, lakes and volcanic relief.
6. **The app keeps the base.** Generating again with unchanged inputs and planet
   settings reruns only the wonder pass. A **Wonders** step after Generate edits the
   wonder document on the source map, with its own file, history and **Apply to the
   planet**, which also reruns only the wonder pass.

## Consequences

- A wonder edit costs the wonder pass and the map drawing instead of a build. On
  the four-shores example at Standard detail the pass took about 5 s against 49 s
  for the whole build, and drawing every map at 2,048 px about 13 s; at Fine
  detail the saving is far larger. Aging adds about 3 s per aged wonder
  (ADR-0091).
- Random and fresh wonders give bit-identical planets to the single-pass build on
  that example, with and without every random kind.
- The app holds the base beside the finished planet. Most arrays are shared; the
  rest is a few fields per node (about 26 MB each at 3.2 million nodes).
- Hand-placed wonders change shape once (`sphere-mesh-stream-power-v28`). Tiles near
  wonders change: they no longer hold a crater's lake or carry a splitting river's
  extra water (`planet-blended-tiles-v9`).
- Placing wonders on the generated relief, per-kind settings and suggested sites
  are later steps; this decision gives them a fast pass to build on.

## Alternatives considered

- **Keep wonders in the build and only polish the editor.** Rejected: every edit
  would still rebuild the planet and discard the tiles.
- **Key tiles by the full planet identity.** Rejected: tiles would be discarded on
  every wonder edit, and they would still depend on wonder lakes and routing.
- **Put random kinds in the wonder document too.** Deferred: random wonders are to
  become suggested sites that the user keeps, which replaces them.
