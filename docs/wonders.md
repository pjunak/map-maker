# Wonders

Wonders are fantastical landmarks beyond Earth's extremes. They are opt-in: a
planet has none unless you choose some.

Wonders are a layer on top of the planet ([ADR-0097](adr/0097-wonders-as-a-layer-on-a-base-planet.md)).
The planet is first made without them: erosion, climate, volcanoes, ice, lakes and
the sea floor. Wonders are then added to its ground, and only ice, lakes, rivers
and the sea floor are worked out again. Changing wonders therefore never erodes the
planet again, and regional detail already built for the planet stays valid.

- **At random.** Tick the kinds under **Wonders** in the Generate step, or pass
  `--random-wonders` to `map-maker world planet` with a comma-separated list of
  kinds or `all`. Random wonders land in the same places at every mesh resolution,
  so a quick preview shows where the final build puts them.
- **By hand.** Place them in the **Wonders** step, which keeps them in their own
  `.wonders.json` file beside the world. Pass that file to
  `map-maker world planet` with `--wonders`. Placed wonders of a kind replace the
  random ones of that kind.
- **From suggestions.** Once a planet exists, the Wonders step suggests plausible
  sites for every kind; keep the ones you want ([below](#suggested-sites)).

Wonders form after erosion and climate, so they keep their sharp shapes, and
every map draws them at its own scale, from the world atlas down to local maps.
Lakes form in them where the climate is wet and salt pans where it is dry. Rivers
that drop over a wonder's cliffs fall as waterfalls, drawn as white spray, and
hovering over a wonder on the map names it. The climate does not see them: a
titan volcano casts no rain shadow.

## Place wonders by hand

1. Open the **Wonders** step and click **Place wonders** (or **Open wonders…**).
   The step's map replaces the world map while it is open. Once a planet exists it
   shows the planet's relief, or any other of its maps chosen above it, and reads
   out the ground under the cursor; before that it shows your source drawing.
2. Choose a **Kind**; the text below describes it and its size range. Optionally
   give a **Name**, a **Size** in km (a diameter, a width or a height, depending on
   the kind; blank uses the usual size), an **Age** in million years and the kind's
   **Settings** (below). Blank settings are left to the generator.
3. Click **Place on map**, then a point on land. Wonders placed by their two ends,
   such as a chasm, take a second click for the other end. Escape cancels.
4. Select a wonder in the list to change it (**Update**), give it a **New shape** or
   **Delete** it. Undo and redo cover every edit; **Save** writes the file.
5. Generate the planet, or, if it already exists, click **Apply to the planet**.
   Generating again with unchanged inputs and planet settings also only adds the
   wonders.

Each placed wonder draws its shape from its own seed, stored in the file. Adding,
removing or moving other wonders, or changing the planet's seed, does not redraw
it; only its depth follows the ground it is cut into. **New shape** draws it from a
new seed. The planet reports an error if a
wonder, or either end of a two-ended one, lies at sea, and if a splitting river has
no large river near it. The file follows edits of its world, as a geology recipe
does ([schema](../schemas/world/wonders-v2.schema.json)).

The map under the wonders shows the planet as it was last made: apply to see
changed wonders in it.

### Settings

Each kind's settings come from the catalog ([ADR-0098](adr/0098-wonder-settings-from-the-catalog.md)).
Fixing one leaves the others as the wonder's seed draws them.

| Kind | Setting | Range | Blank |
|---|---|---|---|
| Titan volcano | Height | 6,000–14,000 m | About 10 km, more for a larger one. |
| Shattered volcano | Height | 2,000–6,000 m | From its size, 2.5–6 km. |
| Giant active volcano | Height | 3,000–9,000 m | From its size, 3–9 km. |
| Impact crater | Depth, rim crest to trough floor | 100–6,000 m | About 0.9 % of its diameter. A depth the ground cannot hold above sea level is an error. |
| Great chasm | Depth | 300–6,000 m | 3,000 m. Always a cap: shallower where the ground is lower. |
| Great chasm | Side canyons | 0–10 | Three to six. |
| Great chasm | Parallel troughs | 0–5 | One to three. |
| Tepui | Height | 500–4,000 m | From its size, 1–2.8 km. |
| Tepui | Elongation, long axis over short | 1–3 | 1–2.2. |
| Tepui | Orientation of the long axis, from north towards east | 0–180° | Any. |
| Splitting river | Water taken by the other basin | 10–50 % | 25–45 %. |

Great cliffs and oases have no settings beyond their size.

## Suggested sites

In the Wonders step, after generating a planet, click **Suggest sites**. For every
kind it lists the best four places found on the planet, each at least 400 km from
the others, with how well the place fits, and draws them on the map as dashed
ghosts ([ADR-0099](adr/0099-suggest-wonder-sites-to-keep.md)). Select one to see
why it fits; **Keep** turns it into a placed wonder at that place and size, which
you can then change like any other, and **Reject** hides it. Apply to see kept
wonders in the planet.

Candidates are drawn as random wonders are, then scored by what the planet is like
there. The scores rest on hypotheses, not proof:

| Kind | Fits best |
|---|---|
| Impact crater | Old, stable crust in dry country, where craters survive erosion. |
| Great chasm | Where plates pull apart or on a high plateau, cut deep. |
| Great cliff | Where high and low country meet. |
| Tepui | An old shield in the wet tropics, like the Guiana Shield. |
| Titan volcano | Over a mantle plume, far inland. |
| Shattered volcano | On an arc of volcanoes or in a volcanic province. |
| Giant active volcano | Among active volcanoes, or over a mantle plume. |
| Oasis | Deep desert below mountains that feed its spring. |
| Splitting river | The largest rivers with a low divide; one per river. |

Suggestions belong to the planet they were found on: applying wonders keeps them,
generating a new planet clears them. They are not saved; only kept wonders are.

## The catalog

| Kind | `--random-wonders` name | What it is | Size when placed by hand |
|---|---|---|---|
| Titan volcano | `titan` | An ice-capped shield volcano about 10 km high, with a cliff around its base and radial valleys. | Diameter 200–1,200 km, usually 560 km. |
| Shattered volcano | `shattered` | A volcano 3.5–5 km high that blew itself apart: a horseshoe amphitheatre with a rounded head at the summit caldera opens to one side, and a hummocky debris lobe runs out to 2.6 times its radius beyond the breach. | Diameter 20–200 km, usually 70 km. |
| Giant active volcano | `active` | An erupting stratovolcano 6.5–8.5 km high with a glowing lava lake in its vent, branching lava flows (older ones weathered grey) and an ash blanket downwind. | Diameter 30–250 km, usually 130 km. |
| Impact crater | `crater` | A fresh crater 180–300 km across with a central plateau and a ring trough that may hold a lake. One to three at random. | Diameter 20–600 km, usually 240 km. |
| Great chasm | `chasm` | A rift canyon system 900–2,200 km long and up to 3 km deep, with parallel troughs, side canyons and uplifted shoulders. | Width 10–200 km, usually 60 km; placed by its two ends, 100–4,000 km apart. |
| Great cliff | `cliff` | A fault scarp 1.5–3.5 km high and 300–1,200 km long. Its raised block tilts gently back from a steep, buttressed face; talus lies below it and a trough along its foot. At random it rises on the side that already stands higher. | Height 0.5–6 km, usually 2.5 km; placed by its two ends, 50–3,000 km apart, with the high side to the left going from the first end to the second. |
| Tepui | `tepui` | A table mountain 1–2.8 km high, walled by sheer cliffs, with a lobed, elongated plan and detached outliers. At random two to five stand in a group. | Diameter 10–300 km, usually 70 km; larger ones stand higher. |
| Oasis | `oasis` | A spring-fed pond in a hollow, ringed by palms and gardens. Random oases (two to five, at least 300 km apart) lie in hot deserts, where rain is under 15 % of the potential evaporation; they need a climate. | Diameter 2–60 km, usually 15 km. |
| Splitting river | `fork` | A large river at least 150 km inland divides on a low divide (at most 300 m above it), its two courses reaching the sea at least 400 km apart, and sends a quarter to nearly half of its water to the sea by another basin, like the Casiquiare joining the Orinoco to the Amazon. Every map draws the branch. | No size; place it near a large river and it splits where another basin is close and the divide lowest. |

## Age

Wonders are drawn fresh, as if they formed just now. An age erodes them: rivers
cut gullies into their walls, creep rounds their rims and their floors fill with
sediment. A crater 10 million years old keeps its shape with a worn, gullied
rim; at 60 million years it is a faint ring, as Earth's oldest craters are.

- **For every wonder:** choose **Age** under **Wonders** in the Generate step
  (fresh, weathered, old or ancient) or pass `--wonder-age` in million years.
- **For one placed wonder:** set its **Age** (million years) in the Wonders step;
  blank uses the age above.

Craters, chasms, great cliffs and tepuis age; volcanoes, oases and rivers stay
young; tepuis and great cliffs wear slowly, as a hard caprock does. Each aged
wonder is eroded on its own patch around it, about a minute each, and is drawn
from its eroded surface ([ADR-0091](adr/0091-age-wonders-on-their-own-patches.md)).

The science behind each shape, and what was tried before, is in the
[volcanism and wonders report](research/2026-10-08-volcanism.md).
