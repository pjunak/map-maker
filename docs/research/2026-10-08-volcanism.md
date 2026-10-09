# Volcanism — 2026-10-08

Status: **implemented, experimental.** Volcanoes are placed by the plate model
from [plate tectonics and sediment](2026-10-08-plate-tectonics-and-sediment.md)
and drawn as young constructional landforms.

## Settings

| Setting | Placement | Kinds | Earth reference |
|---|---|---|---|
| Subduction arc | Land within ±40 km of a band ~130 km inland of strongly leading-edge coasts. Spaced at least 70 km apart. Noise gaps stand for flat-slab segments. | Stratovolcano, 12 % calderas | Andes, Cascades, Japan. Arc volcanoes are 50–70 km apart (de Bremond d'Ars et al. 1995). |
| Hotspot | 8 fixed plumes. The active volcano sits over the plume, and older ones trail in the direction of plate motion every 140 km, for up to 70 Myr or 4,000 km. They age and subside along the track. | Shield or caldera on land, seamount or guyot at sea | Hawaii–Emperor, Yellowstone, Tibesti (Wilson 1963) |
| Continental rift | Within 70 km of divergent boundaries inside continents, at least 120 km apart | Strato- and shield volcanoes | Kilimanjaro, Kenya, Eifel |
| Intraplate | Random seamounts, one per 300,000 km² of deep ocean | Seamount | About 10⁵ seamounts taller than 1 km (Wessel et al. 2010) |

## Shapes and sizes

- **Heights.**
  - **Distributions.** Lognormal: about 2.3 km median on arcs and 2 km on
    rifts; hotspot volcanoes are 2.5 km on land and 4.5 km at sea when fresh.
  - **Summit cap.** Summits stay at most about 5.3–6.9 km (each volcano has its
    own ceiling), because big edifices do not stack on high ranges. Ojos del
    Salado, the highest volcano, is 6.9 km.
- **Flank slopes** (height / basal radius): stratovolcanoes 0.18–0.3,
  shields 0.06–0.1, seamounts 0.12–0.2.
- **Profiles.** Stratovolcanoes have concave flanks, (1 − s)^1.8; shields are
  convex, (1 − s²)^0.7.
- **Calderas** have a flat floor 300–800 m below the rim, with a radius of
  4–15 km but at most 45 % of the basal radius.
- **Sea.** Volcanoes at sea stop 150 m below the surface, like guyots, because
  the coastline is authored: there are no new islands.

## Pipeline

- **Placement.** Volcanoes are placed after erosion and basin fill, from their
  own named stage seed, `planet.volcanism`.
- **Mesh.** The mesh carries cones widened to 1.5 mesh spacings (volume kept),
  so rivers, lakes and climate see them. Caldera floors can hold lakes.
- **Images.**
  - **Sharpness.** World and regional images redraw cones at pixel resolution.
  - **Colour.** Summits get dark lava and ash, which vegetation covers in wet
    climates. Lapse-rate cooling of the sharp summit gives snow caps.
- **Regional tiles.** These exclude the volcanoes from their calibration
  target, so volcanoes are not eroded into hills.
- **Fix found on the way.** Bare-rock and bare-dryland slope thresholds now
  scale with pixel size (3.5× in regional windows). Ordinary 10–15° volcano
  and hill flanks had turned to rock at 0.5 km pixels.
- **Outputs.** `volcanoes.geojson` lists each volcano with its kind, setting,
  activity, age, summit, edifice height, basal radius and caldera size. The
  manifest gains a `volcanoes` summary. `planet.npz` stores the volcano arrays
  and `volcanic_m`.
- **Provenance.** The relief algorithm identifier is now
  `sphere-mesh-stream-power-v9`.

## Aethelara at 800k nodes

- **Total.** 1,917 volcanoes: 540 arc, 184 rift, 163 hotspot and 1,030
  intraplate seamounts.
- **Activity.** 474 are active.
- **Location.** 794 are on land.
- **Arc count.** Arcs are about 2× Earth's continental-arc density. Aethelara's
  indented coasts give more leading-edge coastline.

## Flood basalts

- **Plumes.** Mantle plumes now live in the plate model (`Tectonics.plumes`,
  with plate heading and speed over each plume), so hotspot tracks and flood
  basalts share them.
- **Placement.** A plume's first arrival erupts a large igneous province at the
  far, old end of its track, about 65 Myr of plate motion away (Deccan, Siberian
  Traps, Paraná). Where that point is on land at least 200 km inland, the
  forcing adds a lobed plateau of about 450 km radius.
  - **Rock.** Erodibility is 0.35×, for resistant stacked lava flows.
  - **Uplift.** 0.15 mm/yr for lava thickness and plume-head uplift.
- **Aethelara.** One province of about 370,000 km² lands on the southern polar
  continent. It overlaps an active collision belt, so it reads only as a
  gently raised tableland.
- **Drawn.** The trap cover is stored (forcing, `planet.npz` field
  `flood_basalt`) and rendered: dark basaltic clay soils, like the Deccan's
  black cotton soil, which forest hides. Regional windows add stepped benches of
  150 m lava-flow packages where the relief crosses them.
- **Provenance.** The relief algorithm identifier is now
  `sphere-mesh-stream-power-v10` (v14 once the trap cover was stored).

## In the app

- **Layer.** A "Planet volcanoes" layer shows the atlas with land volcanoes
  marked (red for active, dark for extinct). It is written as `volcanoes.png`.
- **Hover.** The inspector names the volcano under the cursor, with its kind,
  setting, activity and edifice height.

## Limits and next steps

- **No volcanic islands.** Island arcs and ocean islands would need new land.
- **Fixed shapes.** Volcano shape does not age beyond height loss along hotspot
  tracks; old volcanoes keep cone profiles.
- **No eruptions.** Activity is a static label: no eruption history, tephra or
  climate effects.
