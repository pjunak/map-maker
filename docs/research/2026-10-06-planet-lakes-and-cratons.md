# Planet cratons, young depressions and climate-balanced lakes — 2026-10-06

Status: **experimental** (`dmtools world planet`, ADR-0085). Run on the 200k-node
fractal world with sample geology and one climate pass.

## Stable continents: from domes to basins

**Symptom.** Uniform uplift over large stable interiors eroded into smooth central
domes, drained by short rivers radiating outward. On the earlier craton model,
uplift also grew inland.

**Earth comparison.** Old continents usually show the opposite pattern:
- low interior basins, such as Congo and Hudson Bay;
- raised marginal swells and escarpments, such as southern Africa;
- a few large trunk rivers that breach the rim.

**Change** (`cratonic_profile`, `UPLIFT_TEXTURE`):
- Stable-continent uplift (procedural cratons and authored plains/hills) now follows a marginal swell. It peaks about 250 km inland and has a broad interior sag beyond 500–1,500 km.
- All uplift gets low-frequency texture with a log-amplitude of 0.6 (structural warps).

**Results:**
- The radial starbursts disappear, and divides and basins become irregular.
- Hack exponent 0.55, compass share 0.242, zero non-descending receivers.
- Calibrated targets stay within about 8 %. Mean land elevation is essentially unchanged (437 → 441 m).

A texture-only variant without the profile change mostly shifted divides off-centre; it is retained in this record only.

## Lakes

The evolution fills closed basins with sediment every step, so the eroded relief
has no lakes. Lakes come from depressions younger than that filling, imprinted on
the final relief:

| Source | Depth | Where |
|---|---:|---|
| Rift (geology setting) | 600 m | Region cores, smoothed over 120 km |
| Sedimentary basin (setting) | 160 m | Region cores |
| Interior sag (procedural) | up to 220 m | Noise-selected, at least 300–800 km from the coast |
| Glacial scour | up to 140 m | Lowlands below about 1,500 m with present warm-season temperature below about 14–19 °C |

All depressions fade out within 30–100 km of the coast, where scour would make
fjords, and land stays at least 1 m above sea level.

**Water balance (`balance_lakes`).** This follows Fill–Spill–Merge in spirit.
- Each depression receives the runoff of its whole catchment, summed over all of
  its exit nodes.
- If inflow is at least open-water evaporation (PET) over the full depression,
  the lake fills to its spill point and passes the surplus downstream.
- Otherwise a closed lake grows from the lowest node until evaporation balances
  inflow. Its water never reaches the sea, so it becomes a sink for later routing.
- The analysis iterates up to six times. Closing an upstream basin reduces
  downstream inflow, and the final pass only labels lakes.

Rivers are routed on the water surface. Discharge is runoff minus lake
evaporation, with no negative flow passed on. Rivers are drawn by discharge
(the `--river-km2` area at mean runoff), so arid regions show fewer rivers.

**Bug found by the controlled test.** Flat-rimmed depressions spill at several
nodes. The first version used the largest single exit flow and so underestimated
inflow: it marked a humid basin as closed and an arid one as dry. Summing all
exit flows fixed it.

**Glacial lakes and scale.** A 60 m scour at about 265 km wavelength produced no
lakes at 50 km spacing, because the regional river gradient over-topped it. With
140 m at about 200 km wavelength, lake districts appear in cool lowlands.
Small-lake districts are fundamentally sub-grid at world scale; they belong to
regional zoom.

| Version | Lakes | Closed | Land share |
|---|---:|---:|---:|
| Max-exit inflow, 60 m scour | 7 | 4 | 0.33 % |
| Max-exit inflow, 140 m scour | 62 | 13 | 0.64 % |
| Summed-exit inflow (current) | 31 | 6 | 0.42 % |

## Controls

`tests/test_planet.py` builds a 500 m plateau with a 300 m central basin:
- With 1,500 mm runoff and 900 mm evaporation it becomes an open lake at the spill.
- With 15 mm runoff and 2,200 mm evaporation it becomes a smaller, lower, closed lake.

In both cases every land receiver strictly descends on the water surface, and the
arid lake's water does not reach the sea.

## Limits

- Lake levels are a steady annual balance. There are no seasonal levels, salinity or sediment infill of lakes.
- Below-sea-level basins (Dead Sea, Caspian) are not represented; land is clamped to 1 m.
- Depressions are imprinted after erosion, so they do not shape the erosion history.
- Lake surfaces are not yet fed back into the climate.
