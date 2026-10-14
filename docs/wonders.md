# Wonders

Wonders are fantastical landmarks beyond Earth's extremes. They are opt-in: a
planet has none unless you choose some.

- **At random.** Tick the kinds under **Wonders** in the Generate step, or pass
  `--wonders` to `map-maker world planet` with a comma-separated list of kinds or
  `all`. Random wonders land in the same places at every mesh resolution, so a
  quick preview shows where the final build puts them.
- **By hand.** Place them under **Landmarks** in the Geology step
  ([geology guide](world-geology.md#place-wonders-by-hand)). Placed wonders of a
  kind replace the random ones of that kind.

Wonders form after erosion and climate, so they keep their sharp shapes, and
every map draws them at its own scale, from the world atlas down to local maps.
Lakes form in them where the climate is wet and salt pans where it is dry. Rivers
that drop over a wonder's cliffs fall as waterfalls, drawn as white spray, and
hovering over a wonder on the map names it.

| Kind | `--wonders` name | What it is | Size when placed by hand |
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

- **For the whole planet:** choose **Age** under **Wonders** in the Generate step
  (fresh, weathered, old or ancient) or pass `--wonder-age` in million years.
- **For one landmark:** set its **Age** (million years) under Landmarks in the
  Geology step; blank uses the planet's age.

Craters, chasms, great cliffs and tepuis age; volcanoes, oases and rivers stay
young; tepuis and great cliffs wear slowly, as a hard caprock does. Each aged
wonder is eroded on its own patch around it, about a minute each, and is drawn
from its eroded surface ([ADR-0091](adr/0091-age-wonders-on-their-own-patches.md)).

The science behind each shape, and what was tried before, is in the
[volcanism and wonders report](research/2026-10-08-volcanism.md).
