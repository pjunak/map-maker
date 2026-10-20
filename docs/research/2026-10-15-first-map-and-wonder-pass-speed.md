# First map and wonder pass speed — 2026-10-15

Catalog entries: D23a and D28 in the [decision catalog](decision-catalog.md).
Decisions: [ADR-0091](../adr/0091-age-wonders-on-their-own-patches.md#revision-2026-10-15)
(creep) and [ADR-0097](../adr/0097-wonders-as-a-layer-on-a-base-planet.md).

## Question

Apply in the Wonders step took minutes on the example world, and every run drew all
twelve maps before showing one. Where did the time go?

## Inputs

- `examples/world/four-shores.world.json` with its four placed wonders
  (`four-shores.wonders.json`). Only the 220 km crater is aged (20 Myr); the others
  keep the default age 0.
- 12k and 50k-node planets with default settings, maps at 2,048 px.
- Python 3.14 with Numba on the development desktop. Runs on a lightly loaded or
  idle machine are marked; earlier loaded figures are not used.

## Drawing every map (5bde61c)

After a run the app drew all twelve themes before showing one. On 50k nodes at
2,048 px, unloaded, over three rounds:

| | Time |
|---|---:|
| All twelve maps (before) | 11.0–11.3 s |
| First map, relief (after) | 3.8–4.0 s |
| First map, atlas (after) | 5.8–5.9 s |

Shared rasters take 0.9–1.0 s and the shared display fields 2.7 s. Single themes:
parchment 3.2 s, atlas 2.2 s, topographic 0.7 s, geology 0.33 s, relief 0.27 s,
basins 0.26 s, the rest 0.16 s or less.

The app now draws the shown theme first and the others when first chosen, from the
same painters, so pixels are identical to before (D28). Builds still write every
theme.

## The wonder pass (3cae433)

cProfile of `finish_planet` at 12k nodes on an idle machine: 422.5 s in all, 420.1 s
of it in `planet_aging.creep`. Everything else took about 2.4 s (evolve 0.75 s, the
patch mesh 0.63 s, ice 0.29 s).

- **Cause.** Creep took 99,059 explicit substeps on the crater's 120,361-node
  aging patch, where about 52 would do at the median node's rate. The patch mesh
  (`planet_patch.regional_mesh`) jitters nodes by 0.35 spacings, which puts a few
  pairs metres apart: the shortest edge is 1.6 m against a median of 1,687 m. Their
  cotangent weights reach 1,490 (typically about 1), so the stiffest node's weight
  over its area is 1,900 times the median, and that node sets the stable step.
- **Not the cause.** Numba recompiling, or the planet's node count: the patch, and
  so the cost, does not depend on it. The jitter depends only on the seed and the
  grid's shape, so with the default seed every first aged wonder hit it.
- **Fix.** Creep takes 25 backward-Euler steps with one sparse LU factorisation
  (SciPy `splu`), about 1 s. Against the explicit result on the crater's patch the
  difference is at most 0.84 m (RMS 0.085 m) on changes of up to 110 m. The error is
  first order, about 21 m divided by the number of steps, and does not depend on
  age. Relief id `sphere-mesh-stream-power-v29`. The patch mesh is unchanged, since
  regional tiles use it too and do not run explicit diffusion.

| Lightly loaded machine | Before | After |
|---|---:|---:|
| Wonder pass, 12k nodes | 422.5 s | 3.0 s |
| Apply, 50k nodes (wonder pass, relief map at 2,048 px, map readout) | 409.1 s | 7.7 s, 8.0 s |

"Before" for Apply ran the same call with the old creep patched back in. Two 12k
runs gave the same output digest. The 50k base planet built in 7.4 s; an earlier
279 s figure was taken while two unrelated jobs held the CPU.

## Disposition

Both fixes are in. Each aged wonder now takes a few seconds
([wonder guide](../wonders.md)), and the first map after a run takes 4–6 s instead
of 11 s.
