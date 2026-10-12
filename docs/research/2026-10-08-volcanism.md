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

## Opt-in volcanic islands

The authored coastline is authoritative, so volcanoes at sea stop 150 m below
the surface by default. With `volcanic_islands` (CLI `--volcanic-islands`,
Planet page checkbox) they may break the surface.

- **Hotspot islands.** Ocean volcanoes on hotspot tracks get a planned summit
  of 4,200 e^(−age/10 Myr) − 600 m. They rise from the local sea floor as
  broad shields while young and drown to guyots after about 20 Myr, as from
  Hawaii to Midway and the Emperor chain.
  - **Track.** Spacing along the track varies ±30 % and volcanoes step up to
    25 km off its axis.
  - **Vents.** Islands with summits above 1,500 m gain two satellite shield
    vents 40–75 km away, so islands coalesce from several volcanoes, like
    Hawaii's Big Island.
- **Island arcs.** Ocean–ocean convergent boundaries closing faster than
  2 cm/yr get arc volcanoes 160 km behind the trench, on the overriding plate,
  at least 90 km apart with gaps (Marianas, Aleutians, Lesser Antilles). Their
  summits are lognormal with a median of 900 m.
- **Shapes.**
  - **Lobes.** Shields and islands have lobed outlines: their radius varies
    ±35 % with noise at 80 km and 25 km, for rift zones and coalesced vents.
  - **Slopes.** Island shields have a slope of about 0.09 and arc islands
    about 0.12.
- **Drawing.** Coastlines come from the volcano shapes at pixel resolution on
  the volcano-free sea floor, at world scale and in regional windows. Islands
  appear in `elevation.tif`, in the atlas and in the climate layers.
- **Climate.** Island nodes keep the simulated moisture of the surrounding
  ocean. Their temperature is lapse-corrected, and PET, runoff, biome and
  Köppen class are recomputed as land.
- **Not on islands.** Islands get no rivers or lakes on the world mesh; they
  are too small for it. Regional windows route rivers on them.
- **Aethelara at 800k nodes.** 238 emergent volcanoes form the islands, most of
  them small arc islands, plus a few large coalesced hotspot islands.
- **Off by default.** With the option off, builds are unchanged except for the
  lobed outlines of land shield volcanoes.
- **Provenance.** The relief identifier is now `sphere-mesh-stream-power-v15`.
- **Manifest.** It reports island volcanoes and the island area drawn on the
  raster.

## Opt-in wonders: the titan shield

With `wonders` (CLI `--wonders`, a Planet-page checkbox), a few fantastical
landmarks go beyond Earth's extremes while keeping plausible forms. The first
is a titan: one giant shield volcano, an Earth-sized Olympus Mons (on Mars,
22 km high, 600 km across, with 5° flanks and a basal cliff up to 8 km).

- **Placement.** It stands at least `TITAN_MIN_COAST_M` (350 km) inland, chosen
  by area with the volcanism stage seed.
- **Size.** The edifice is about 10 km high (±10 %) with a basal radius of about
  280 km. It is exempt from the 6.6 km summit ceiling of real volcanoes.
- **Caldera.** A 30 km-radius summit caldera sits 2.5 km below its rim.
- **Basal cliff.** The flank breaks into a cliff beyond 88 % of the radius.
- **Valleys.** Glaciers and rivers cut the flanks into about 32 radial valleys
  (Mount Kenya, Kohala). Their spacing is uneven, they wander downslope, and
  their depth varies, reaching up to 12 % of the summit height at mid-flank.
- **Build data.** It is a volcano with the setting `titan`, so it appears in
  the gazetteer, the archive and regional windows.
- **Downstream effects.** Like other volcanoes it rises after erosion and
  climate. Lakes and rivers route around it: on Aethelara it dams a lake.

The second wonder is impact craters (`planet_wonders.py`). They are fresh
complex craters 180–300 km across, beyond Earth's largest preserved structures
(Vredefort ~250 km and Chicxulub ~180 km, both eroded or buried).

- **Count.** One crater per 4×10⁷ km² of land, from 1 to 3.
- **Placement.** Each lies wholly inland (coast at least 2 radii away) and
  prefers high ground, away from the titan and from other craters.
- **Depth.** Rim crest to trough floor is 0.9 % of the diameter, limited so the
  floor stays above sea level. Below-sea-level basins are not supported yet.
- **Shape.** The shape follows an eroded large crater such as Manicouagan:
  - a central uplift plateau;
  - an annular trough;
  - walls slumped into irregular blocks;
  - a noisy raised rim;
  - an ejecta apron falling as (r/R)⁻³.
- **Level floor.** The impact excavates and refills the interior at once, so the
  floor is levelled to the mean height of the ground it was cut into.
- **Timing.** Craters are cut into the eroded relief before lakes form, so the
  climate decides what fills them. On Aethelara a humid crater holds a ring lake
  around its central plateau. A hot desert crater has a salt pan in its trough,
  and a semi-arid one stays a dry basin.
- **Atlas.** The atlas redraws craters, and their lakes, at pixel scale from the
  crater shape.
- **Manifest.** `metrics.craters` lists each crater's position, diameter and
  depth.

The third wonder is a great chasm (`planet_wonders.py`), a rift canyon like a
smaller Valles Marineris (on Mars 4,000 km long, up to 200 km wide and 7 km
deep). Earth's largest canyons are far smaller: the Grand Canyon is 446 km long
and 1.8 km deep, and the Yarlung Tsangpo gorge about 5 km deep.

- **Size.** One chasm system, 900–2,200 km long; the main chasm is 60 km wide
  from rim to rim.
- **Axis.** Rifts grow from segments offset en echelon, so the axis runs between
  its ends in straight stretches of about six widths (360 km), each shifted
  sideways by up to 1.2 widths and joined by diagonal jogs, with a smoothed
  random walk on top so no two stretches repeat.
- **Placement.** It starts on high ground (at least 1 km where there is some) and
  lies wholly inland, at least two widths from the coast and away from the titan
  and the craters. The first trial whose mean depth reaches 1.2 km is taken, or
  else the deepest of 120 (at least 300 m). On Aethelara about a quarter of the
  trials that stay on land reach 1.2 km.
- **Depth.** Up to 3 km from rim to floor. Land stays above sea level, so the
  floor keeps 100 m above it: a chasm runs shallower through lowland. The
  deepest cut follows the lowest ground within two widths either way and eases
  along the axis, so the floor neither steps nor dips to the sea. Below-sea-level
  floors, like the Dead Sea's rift, are not supported yet.
- **The system.** Around the main chasm:
  - one to three parallel troughs, half to most of its width, run alongside a
    quarter to six tenths of its length on their own bends, like the chasmata of
    Valles Marineris: they merge with it into basins or stand apart behind
    plateau ridges;
  - three to six side canyons branch from the middle seven tenths, a third to
    half as wide, 6–18 % of its length, hanging at half to two thirds of the
    floor's depth and growing shallower towards rounded heads; up to two
    tributaries fork near each head;
  - each end stops at a rounded headwall and dies out in one or two smaller
    troughs offset en echelon, as rift tips splay.
- **Shape of each trough.**
  - narrows and basins: the width varies from 0.6 to 1.5 times along the length;
  - a floor across the middle half or more, raised towards the walls by talus
    and slumps and roughened by hummocks;
  - steep walls with patchy benches where resistant layers crop out; one wall is
    gentler and its shoulder higher, like a half-graben whose master fault swaps
    sides along the rift;
  - rift shoulders: the flanks are uplifted by about 30 % of the depth and fall
    away over two widths, as flexure lifts the shoulders of Earth's large rifts
    by 1–2 km. Gullies notch them just behind the rim;
  - a domain warp: every point is displaced by fractal noise (up to about 0.45
    widths) before its distance to the axes is measured, so rims, walls, bends
    and ends are irregular without a repeating pattern. Maps draw the warp down
    to their own scale (a pixel of the atlas, the detail of a regional level), so
    nested maps agree on the large shapes and add finer ones.
  Inside, the deeper floor wins; outside, the higher shoulder.
- **Earlier versions looked artificial.** A cross-section swept along one axis
  gave parallel walls, ruled benches, needle-point ends and a ribbon-like plan;
  smooth sine bends looked like a worm; rim noise with sharp ridges cut evenly
  spaced teeth; short box canyons as separate paths curled into hooks; and
  troughs copied from the main axis looked like rails. The warp replaced most of
  these hand-made details.
- **Timing.** Like the craters, a chasm is cut into the eroded relief before lakes
  form. Where it is wet its closed floor holds a long rift lake, as Lake Baikal and
  Lake Tanganyika fill rift valleys; where it is dry, playas lie in the lowest parts.
- **Build data.** Craters and chasms form one overlay (`Wonders`). The archive keeps
  each path's axis and depth profile; `metrics.chasms` lists every path (the main
  chasm first, then troughs, side canyons and splays) with its ends, length,
  width and depth.

Great cliffs and tepuis (`planet_scarps.py`) are raised rather than cut.

- **Great cliff.** A fault scarp 1.5–3.5 km high and 300–1,200 km long, beyond
  Earth's tallest fault scarps (the Sierra Nevada's eastern face rises about
  3 km) and closer to Verona Rupes on Miranda.
  - Its foot follows a segmented axis like the chasm's. The raised block stands
    the full height at the edge and tilts back to the plain over 35 times the
    height, as tilted fault blocks do.
  - The face is about 60 degrees, shifted along its length into buttresses and
    gullies; talus heaps below it, and a trough up to 12 % of the height runs
    along the foot where it may hold lakes.
  - The scarp dies out over the last sixth of its length at each end.
  - At random it rises on the side whose mean ground along the scarp already
    stands higher, as escarpments face the lower country; a near tie (within
    50 m) is settled by a coin drawn before the comparison, so meshes agree.
- **Tepui.** A table mountain like Roraima and Auyan-tepui: 1–2.8 km of sheer
  walls (larger ones stand higher) around a nearly flat summit, with talus
  below. Its plan is stretched up to 2.2 times along a random direction and
  domain-warped by up to 0.65 of its radius, which cuts re-entrant bays and
  leaves detached outliers; a first version with a weaker warp looked like
  round pancakes. At random two to five tepuis stand in a group a few of their
  widths apart, as on the Gran Sabana.

Two more volcano wonders live with the other volcanoes (setting `wonder`):

- **Shattered volcano.** A stratovolcano 3.5–5 km high that blew itself apart,
  like Mount St Helens in 1980 or Bezymianny in 1956, at a giant scale. Its
  flank slid away in a landslide and the summit blew out: a horseshoe
  amphitheatre with a rounded head at the summit caldera widens to its mouth at
  the base, with a floor ramping down to the plain. A hummocky debris lobe
  (20–300 m of hummocks, like Socompa's 600 km² field) starts on the lower flanks
  inside the mouth and ends in a lobed front about 2.6 radii out. The breach
  direction is fixed by the volcano's position, and the shape is domain-warped
  so its edges are organic. A first version cut a straight-sided box and a
  trapezoid of debris.
- **Giant active volcano.** An erupting stratovolcano 6.5–8.5 km high, taller than
  any on Earth (Ojos del Salado reaches 6.9 km above sea level), with flanks of
  0.10–0.13. Its eruptions (`planet_eruptions.py`) are:
  - five to nine lava flows straight down the flanks, bending gently, each
    widening into a broad toe, with up to two branches split off where lava
    spilled over levees; older flows are weathered grey, fresh ones black, and
    the tongues stand 30 m proud. A first version wandered like worms and then
    looked like a starfish;
  - an ash blanket 2.5–5 volcano radii long downwind of the vent, from the
    annual wind at the vent (trade winds or westerlies without a climate),
    widening downwind and patchy, that greys the ground and thins vegetation;
  - a lava lake in the vent, a small irregular patch that glows orange on maps.

Two water wonders follow (`planet_waters.py`):

- **Oasis.** A spring pond in a 25 m hollow, ringed by palms and gardens, fed by
  groundwater rather than rain (Siwa, Ubari, Huacachina). Maps green a lobed,
  patchy ring of its radius and paint the pond as water. Random oases lie in hot
  deserts: precipitation under 15 % of potential evapotranspiration and a mean
  temperature above 14 °C, at least 60 km from the coast and 300 km apart.
- **Splitting river.** A river bifurcation like the Casiquiare, whose upper
  Orinoco loses part of its water across a swampy divide to the Amazon. Once
  lakes and rivers are known, candidates are nodes on rivers carrying at least
  2 % of the largest discharge (not at their mouths), with a neighbour across a
  divide at most 300 m higher that drains to the sea by another outlet. The best
  candidates favour large rivers and low divides; a random one is drawn from
  the best five, and a hand-placed one takes the best within 300 km. A quarter
  to nearly half of the water and drainage area moves from the main stem's
  course to the branch's, so the atlas draws a thinner main stem and the
  branch, and regional maps route the branch's share from where it crosses.
  Both maps draw the short link across the divide.

The wonder kinds are placed in a fixed order (titan, shattered and active
volcanoes, craters, chasm, cliff, tepuis, oases, and the splitting river once
rivers are known), each from its own random stream, and each keeps clear of the
wonders placed before it.

Wonders are placed by rejection sampling of continuous positions on the sphere
(`draw_site`), from their own random streams, with yes/no eligibility tests.
Picking mesh nodes, or weighting by relief that differs between resolutions,
moved them between a 800k preview and a 3.2M build. Now the titan and the
craters land in the same places at 200k and 800k nodes, and so does the chasm.
Only depth, which is limited by the local ground, varies.

Regional windows draw craters and chasms too. Their target surface leaves out
volcanoes and wonders, as regional erosion would otherwise fill a crater or a
chasm, and each window adds the sharp shapes back. Crater and chasm lakes fill the
sharp floor to the parent level. The
regional tile algorithm became `planet-blended-tiles-v4`. Closed hollows deeper than
10 m (crater troughs among them) fill with lakes where it is wet. Where it is dry, a
playa lies in the lowest quarter of the basin's depth (20–400 m).

Volcanoes rise after the climate is simulated, but the atlas and regional
windows had lapse-corrected only the sharp detail above the mesh's widened
cones. Big edifices therefore kept the temperature of the plain they stand on.
Whole edifices are now lapse-corrected, so high volcanoes carry snow and ice:
the titan wears an ice cap, and 5–6 km stratovolcanoes are snow-capped.

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
