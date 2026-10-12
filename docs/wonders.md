# Wonders

Wonders are fantastical landmarks beyond Earth's extremes. They are opt-in: a
planet has none unless you choose some.

- **At random.** Tick the kinds under **Wonders** on the Planet page, or pass
  `--wonders` to `dmtools world planet` with a comma-separated list of kinds or
  `all`. Random wonders land in the same places at every mesh resolution, so a
  quick preview shows where the final build puts them.
- **By hand.** Place them in the geology editor's **Landmarks** tab
  ([geology guide](world-geology.md#place-wonders-by-hand)). Placed wonders of a
  kind replace the random ones of that kind.

Wonders form after erosion and climate, so they keep their sharp shapes, and
every map draws them at its own scale, from the world atlas down to local maps.
Lakes form in them where the climate is wet and salt pans where it is dry.

| Kind | `--wonders` name | What it is | Size when placed by hand |
|---|---|---|---|
| Titan volcano | `titan` | An ice-capped shield volcano about 10 km high, with a cliff around its base and radial valleys. | Diameter 200–1,200 km, usually 560 km. |
| Impact crater | `crater` | A fresh crater 180–300 km across with a central plateau and a ring trough that may hold a lake. One to three at random. | Diameter 20–600 km, usually 240 km. |
| Great chasm | `chasm` | A rift canyon system 900–2,200 km long and up to 3 km deep, with parallel troughs, side canyons and uplifted shoulders. | Width 10–200 km, usually 60 km; placed by its two ends, 100–4,000 km apart. |

The science behind each shape, and what was tried before, is in the
[volcanism and wonders report](research/2026-10-08-volcanism.md).
