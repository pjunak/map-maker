# Cartographic relief style analysis — 2026-09-03

## Visual target

The preferred reference is an illustrated shaded-relief elevation map. Its
readability comes from several layers working together rather than from one
colour gradient:

- medium and dark greens clearly reserve low terrain;
- a relatively narrow yellow-green band separates plains from uplands;
- ochre and brown dominate hills and mountains;
- the darkest brown is used around high, strongly incised terrain;
- pale stone and near-white are limited to the highest crests; and
- high-contrast hillshade exposes drainage texture and long ridge forms.

Blue-green rivers add another major cue in the reference, but they are not part
of its elevation ramp. Map Maker should add them later from derived hydrology,
not bake blue drainage-like marks into the DEM colouring.

## Implementation interpretation

The cartographic style uses an original multi-stop ramp that follows this visual
ordering without sampling or reproducing the reference artwork. It deliberately
allows lightness to peak around the yellow transition, darken through mountain
browns, and rise again for the highest summits. That is effective as a map
style, but it is not a perceptually uniform measurement scale.

For that reason the previous Oleron implementation remains available as the
`Scientific elevation` style. The two views answer different questions:

| Style | Primary question |
|---|---|
| Cartographic relief | Where do plains, uplands, mountain masses, and highest crests read naturally? |
| Scientific elevation | How does elevation change continuously without lightness reversals? |

The cartographic hillshade uses stronger vertical exaggeration than the
scientific view. This changes only the derived image; all Float32 metre values,
constraints, seeds, and resolution behavior stay identical.

## Aethelara height calibration

Aethelara's working cartographic maximum is 10,000 m: high enough to exceed
Earth's 8,848.86 m Everest while remaining recognizably terrestrial in scale.
The cartographic ramp is therefore fixed to absolute metre stops instead of
being stretched to each terrain generation's configured ceiling. This makes a
7,000 m summit the same dark red on every continent and prevents an ordinary
4,500 m regional maximum from being painted white.

Brown covers ordinary mountains through 6,000 m. Additional anchors at 6,500,
7,000, and 7,500 m carry it gradually through warm umber and brown-red into a
muted red at 8,200 m, avoiding a visually dense dark band. Lighter reds appear
from 9,000 m through 9,600 m, and white is reserved for terrain at 10,000 m or
above. The scientific style intentionally remains normalized to the active
elevation ceiling because its purpose is inspecting relative variation within
a generated surface.

## Limits of palette matching

The reference is based on a real high-resolution elevation model with mature
drainage networks and finely incised valleys. A palette and stronger hillshade
can make existing detail clearer, but cannot create missing geomorphology. A
closer structural match requires the planned drainage conditioning, erosion,
ridge/valley hierarchy, and local-resolution work.
