# Planet build speed and finer meshes — 2026-10-19

Catalog entry: D27 in the [decision catalog](decision-catalog.md). Backlog: R47 in
[TODO](../../TODO.md).

## Question

Would rewriting the planet core in a much faster language such as Rust make a
much finer planet mesh possible in reasonable time?

## Method

- **Machine.** AMD Ryzen 7 9800X3D (8 cores, 16 threads), 31 GB RAM, Windows 11,
  Python 3.14.7, 16 Numba threads.
- **Build.** The full `build_planet` path that `map-maker world planet` runs, at
  `3443ff2` from a frozen copy:
  - the synthetic fractal world with its sample geology;
  - default settings: one climate pass, 30 Myr in 100 kyr steps;
  - maps and files at 4,096 px.
- **Runs.** A 20k-node warm-up filled the Numba cache first (147 s, including
  compilation and 72 s of maps). Then one build each at 200k, 800k and 3.2M nodes.
  Each stage's time runs from its first progress message to the next. Peak memory
  is the process high-water mark.
- **Where time goes.** A separate cProfile of 200k and 800k builds at `64574be`
  shows it. Profiling slows Python code, so its totals are not used.
- **Load.** Other sessions ran Python on the machine throughout. Stages doing the
  same work differed by up to 2× between runs: climate always runs on 200k nodes,
  yet took 46–81 s. Read the scaling, not single numbers.

## Results

| Stage (seconds) | 200k (50 km) | 800k (25 km) | 3.2M (12 km) | Mesh used |
|---|---:|---:|---:|---|
| Mesh, forcing and the first geology calibration | 13 | 25 | 58 | full; calibration on at most 100k |
| Erosion, both passes | 11 | 73 | 172 | at most 800k, then full (148 s of it at 3.2M) |
| Climate and the second geology calibration | 81 | 77 | 46 | at most 200k and 100k |
| Ice-sheet flow | 4 | 17 | 119 | full |
| Lakes and measuring | 1 | 2 | 9 | full |
| Maps and files (4,096 px) | 70 | 73 | 95 | — |
| **Total** | **189 (3.2 min)** | **277 (4.6 min)** | **508 (8.5 min)** | |
| Peak memory | 5.4 GiB | 5.8 GiB | 7.7 GiB | |

**Already multi-resolution.** The pipeline caps every stage that does not need
the full mesh (`pipeline/planet.py`):
- geology calibration runs on at most 100k nodes;
- climate on at most 200k (`CLIMATE_NODES`), because its explicit eddy diffusion
  grows faster than the node count;
- the climate-coupled erosion passes on at most 800k.

Only the final erosion pass, ice flow, lakes and the fields that maps sample use
the full mesh. Maps cost the same at any mesh size.

**Where the time goes:**

| Stage | Runs as | What a rewrite could gain |
|---|---|---|
| Erosion | Numba kernels, compiled to machine code through LLVM: `steepest_receivers`, `priority_flood`, `downstream_order`, `accumulate` and the implicit stream-power step `erosion_step`. The profile puts the routing and step functions at 47 s of the 800k build. | Rust compiles through LLVM too, so the same algorithms run at about the same speed per core. Pit filling, drainage ordering, accumulation and the implicit step follow the drainage tree and run on one core; only receiver selection runs in parallel. Parallel routing would gain more than the language. |
| Ice-sheet flow | 10,000 explicit 10-year steps over every active node | It grew 7× from 800k to 3.2M nodes. A faster language shortens each step but not their number; implicit steps or a coarser mesh would cut it more. |
| Mesh building | Qhull and NumPy | Modest; these are compiled libraries. |
| Maps and files | NumPy, SciPy, Pillow and Shapely, all compiled | Modest. |

**Memory** grew 1.8 GiB from 800k to 3.2M nodes, about 0.8 KB per node on top of
about 5 GiB for maps and libraries.

## Finer meshes

The node limit is 4M (`MAX_PLANET_NODES`). Beyond it, estimates use each full-mesh
stage's growth from 800k to 3.2M (mesh 2.4×, full-mesh erosion pass 4.7×, ice
4–7×). None of these was run.

| Nodes | Spacing (6,000 km radius) | Python today (estimate) | Memory (estimate) |
|---|---|---|---|
| 3.2M | 12 km | 8.5 min (measured) | 7.7 GiB (measured) |
| 12.8M | 6 km | 25–35 min | about 15 GiB |
| 51M | 3 km | 1.5–3 h | about 45 GiB, more than this machine has |
| 450M | 1 km | a day or more | hundreds of GiB |

- **6 km is within reach today** on these estimates. It needs the node limit
  raised, not a new language.
- **3 km is mainly a memory problem.** A native core using 32-bit fields and
  compact neighbour lists might fit it in 31 GB.
- **1 km is out of reach for a whole planet** in any language on a desktop.

A finer planet mesh also adds little by itself. The planet treats drainage under
600 km² (`--process-km2`) as below its resolution, so results do not depend on the
mesh. Finer valleys need that lowered and the erosion re-tuned. Regional levels
already add detail at 5, 1 and 0.2 km where the map is opened. Node density does
matter for how well a mesh carries real relief: in
[T22](2026-10-19-curved-interpolation.md), halving the spacing from 50 to 25 km
cut height error on Earth by 35 %.

## Conclusion

A Rust port would not by itself allow a much finer mesh.
- **Speed.** The heavy loops are already compiled, and the rest runs in compiled
  libraries. Expect a constant factor, perhaps 2–3× overall, which is about one
  refinement step (12 → 6 km) in the same time.
- **Memory.** Its larger gain would be memory, which decides whether 3 km fits on
  this machine.

What would help more:
1. **Ice-sheet flow on a coarser mesh or with implicit steps.** It grows fastest
   of all stages, and at 3.2M it already takes nearly as long as the final erosion
   pass.
2. **Parallel drainage routing** (level sets) for the serial tree kernels, on 8
   cores.
3. **Raising the node limit** for 6 km builds, once those two make them quick.

## Hosting on a server (estimate)

Would a hosted version on a rented root server need the Rust port? Nothing was run
for this. The server's specifications are not in the infra repository, so the
estimate assumes 2–4 cores for the app's container, each half to two-thirds as fast
as the desktop's. The infra Compose files already allow the other services up to
about 7.6 GB together (`mem_limit`, 4 GB of it for Music).

| Job | Desktop now | Server, Python | Server, native core |
|---|---|---|---|
| Standard planet, 200k nodes | about 3 min | about 4–6 min | about 2–3 min |
| Fine planet, 3.2M nodes | 8.5 min | about 15–30 min | about 6–12 min |
| Region, province and local maps at a new place | about 11 min | about 20–45 min | about 8–20 min |
| Peak memory, 3.2M nodes | 7.7 GiB | the same | lower, but maps still dominate |

The regional row is a rough figure from recent runs, not timed for this estimate.

- **A port is not required.** Builds take minutes in any language, so a hosted app
  needs a background worker that runs one build at a time and reports progress.
- **Memory decides more than speed.** About 5 GiB of the 5.4–7.7 GiB peak is maps
  and libraries, which do not grow with the mesh; a build draws every theme at
  4,096 px. Drawing on demand, in tiles or with 32-bit fields can be done in Python
  and might bring a build to 2–3 GiB.
- **Results are reusable.** The same inputs give the same planet, so a cache of
  finished builds and regional tiles pays each cost once.
- **Python deploys.** Numba runs in a Linux container. Baking its compiled cache
  into the image avoids about a minute of compilation on the first build after
  each deploy.
- **The interface is the larger job.** The app is a Tkinter desktop program; a
  hosted app needs a web front end over the application layer, and the desktop app
  stays (local-first).

The port becomes worth it with several users at once, paid CPU time, or 6 km planets
built on the server: the same constant factor and lower memory as on the desktop.

## Limits

- One run per size under shared load, as described under Method.
- No Numba-against-Rust kernel comparison was run (R46).
- The estimates assume each stage keeps growing as it did from 800k to 3.2M.
- The 0.8 KB per node is a peak-memory difference that includes temporary
  arrays.
- The hosting figures assume the server's speed; none were measured there.

## Disposition

The native core stays an M5 item (D27, R47), expected to give a constant factor
and lower memory, not kilometre-scale planets. Finer detail stays the job of
regional levels. The ice-flow cost is a new backlog item under M2. A hosted version
would need a background worker, a result cache and lower map memory before it needs
the port.
