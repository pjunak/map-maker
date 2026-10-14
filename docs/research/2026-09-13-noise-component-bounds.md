# Rounded bounds for the procedural-noise component - 2026-09-13

Status: implemented research comparison, with a small runtime hash fix. This
follows the [midpoint experiment](2026-09-13-adaptive-water-profile-refinement.md)
and the separate [spatial-query optimization](2026-09-13-water-guide-bounds.md).
It bounds the existing noise component over supplied coordinate boxes. It does
not bound the finished terrain, authorize water clearance, or change sampling
budgets. [TODO](../../TODO.md) retains those remaining contracts.

## Scope and sources

The research modules are [noise_intervals.py](../../benchmarks/noise_intervals.py)
and [noise_bounds.py](../../benchmarks/noise_bounds.py). The measured field is
`Float32(2000 + 1000 * fractal_value_noise(x, y))`, with horizontal coordinates
in kilometres and field values in metres. Its four corner lattice values come
from the existing runtime hash. This is an isolated component fixture, not a
rendered map or the complete base-elevation formula.

The implementation uses two policies:

- `natural` follows the runtime arithmetic with outward intervals at every
  elementary operation. Repeated appearances of the same value lose their
  correlation, so inclusion can be very loose.
- `monotone_cell` uses monotonicity of the fade polynomial and the corner extrema
  of bilinear interpolation, plus explicit error allowances for the rounded
  runtime expressions. Octave accumulation still uses outward intervals.

[Perlin's Improving Noise paper](https://mrl.cs.nyu.edu/~perlin/paper445.pdf)
describes the quintic interpolation polynomial used by this project. Map Maker
uses hashed **value noise**; it does not implement the paper's gradient-noise
algorithm. The polynomial is a useful analytical building block, not evidence
that generated landforms are physically realistic.

[Rump's INTLAB overview](https://www.tuhh.de/ti3/rump/intlab/) provides a reference
for interval, affine and verified arithmetic methods. INTLAB is not installed
or adopted. This bounded experiment uses existing NumPy operations;
[`numpy.nextafter`](https://numpy.org/doc/stable/reference/generated/numpy.nextafter.html)
moves interval endpoints to adjacent representable numbers. The component
inclusion argument below is derived from this repository's exact expression
order. Finite probes independently check that implementation; they cannot prove
all-coordinate inclusion by themselves.

## Inclusion argument and rounding assumptions

The contract covers supplied binary64 coordinates inside closed, finite boxes.
It assumes binary64 round-to-nearest, ties-to-even elementary operations with
gradual underflow, the current NumPy expression order, and round-to-nearest
binary32 conversion.
It is not a promise about an arbitrary future native/fast-math implementation.

For each octave, coordinate division is rounded outward. The planner enumerates
every lattice cell intersecting the resulting box, including cells adjacent to
rounded boundary contacts. Fractional coordinates are bounded within each cell;
subtracting `floor(q)` gives a rounded fraction in `[0, 1]`. All scaled coordinate
bounds must have magnitude at most `2**50`, keeping cell origins and their next
integers exactly representable. Unsupported coordinates return
`coordinate_range_exceeded`, with no earlier-octave result.

Natural addition, subtraction, multiplication and positive division take outward
adjacent endpoints. Multiplication considers all four products. Thus every real
operation and its rounded runtime result are included. Known lattice values,
rounded amplitude constants and the rounded amplitude sum are taken directly
from the current algorithm. Each octave/cell range is unioned before the full
weighted accumulation and normalization; no unvisited cell contributes an
accepted partial range.

For the tighter method, let `u = 2**-53`. The exact polynomial
`f(t) = 6*t**5 - 15*t**4 + 10*t**3` has derivative
`30*t**2*(1-t)**2 >= 0` on `[0,1]`. Natural interval evaluation at the two endpoints
therefore bounds its **real** range. The runtime's seven-operation evaluation
needs an additional absolute rounding allowance:

| Quantity | Rounded magnitude bound | Cumulative absolute error bound |
|---|---:|---:|
| `t*t` | 1 | `u` |
| `(t*t)*t` | 1 | `2u` |
| `6*t` | 6 | `4u` |
| `6*t - 15` | 15 | `12u` |
| `t*(6*t - 15)` | 15 | `20u` |
| `t*(6*t - 15) + 10` | 10 | `28u` |
| final product with rounded `t**3` | 10 | `56u` |

The last bound is `10*2u + 28u + 8u`. The implementation uses `64u = 2**-47`,
then rounds its endpoint expansion outward. These are absolute errors, so the
allowance also covers subnormal operations. The rounded fade can slightly exceed
one near the boundary; a regression demonstrates why clipping it to `[0,1]`
would exclude actual runtime values.

For fixed lattice values, the real interpolant
`B(s,t) = top(s) + t*(bottom(s)-top(s))` is bilinear. Its extrema over a rectangle
of faded fractions occur at the four corners. Natural point-interval evaluation
of those corners bounds their real values. A separate allowance covers the nine
runtime interpolation operations: lattice values have magnitude at most one,
and actual faded fractions have magnitude below two. Each rounded top/bottom
lerp has magnitude at most five and error at most `12u`. Their rounded difference
has magnitude at most ten and error at most `32u`; multiplying by the other
fraction has magnitude at most twenty and error at most `80u`; the final addition
has error at most `108u`. The implementation uses `128u = 2**-46`, rounded outward.

The final affine field transform is also bounded through its operations. Conversion
to Float32 takes outward adjacent binary32 values and stores these as binary64
endpoints. This includes the quantization step; the bound need not converge to
zero width at a single point. These constants are specific to the stated
expression and input domains, not general error bounds for NumPy functions.

## Bounded work and reproducibility

The complete request is counted across all boxes and octaves before any lattice
hash evaluation or cell-array allocation. A research cap of 262,144 cell visits
is separate from production water-profile/network caps. Requests over the cap
return `cell_budget_exceeded`, their full required count and no enclosure.
Counts use Python integers so a huge rejected rectangle cannot overflow its
budget calculation. At most 65,536 boxes are accepted per request.

The harness reserves a fresh output path, runs each case/repeat in a fresh
process, verifies repeated input/evidence hashes, and publishes `complete` only
after all runs and source/runtime checks pass. A completed experiment can contain
explicitly unresolved trials. No generated project, source map or authored
constraint is read or written. The runtime and harness source identities are
recorded independently.

Each finite reference uses 65,537 fixed dyadic points. Subdivision anchors are
chosen independently of the reference heights, and their positions and Float32
values must match exactly. Every reference point is checked against the bound
for its own interval box. Cell visits count repeated cells across boxes/octaves;
they are not unique samples or a whole-project work forecast. The two policies
share each trial's endpoint samples. Timing uses fixed natural-then-polynomial
order, with no heavy concurrent work; it is component cost evidence, not a
production speedup claim. Process high-water memory includes imports, references
and both policies, and is not stage scratch memory.

## Measurements

The corrected matrix contains 108 parameter combinations, each repeated in a
fresh process: seeds 42/20260913, 1/6/12 octaves, roughness .25/.55/.9, horizontal
extents .5/4 km and horizontal/diagonal/oblique directions. Diagonal paths also
span the same distance in Y; oblique paths use Y/X = .37. Each run compares both
policies at 1/16/256/4096 subdivisions. Roughness has no effect with one octave;
those settings are controls, not additional independent terrain realizations.

Across 216 runs there are 1,728 policy trials: **1,608 bounded and 120 explicitly
over budget**. Every bounded interval contains all its independent reference
samples. Repeated input/evidence hashes and exact shared positions/Float32 values
match. All 864 policy pairs have identical cell counts, station identities and
budget outcomes; all 804 evaluated pairs have different bound hashes. The tighter
method never increases the maximum interval width in these comparisons.

The largest request is 22,386,012 cell visits, rejected before lattice evaluation;
the largest executed request is 130,694. All configurations fit at 256 and 4096
subdivisions. Smaller boxes can require fewer cells than one broad diagonal
rectangle, even though they create more intervals. These observations motivate
segment/cell clipping and correlated bounds, rather than increasing the cap.

For each trial, **extremum gap** means the larger of:
`maximum upper bound - sampled maximum` and
`sampled minimum - minimum lower bound`.
This is a component-wide extremum uncertainty relative to the fixed endpoint
samples. It is different from the width of the most uncertain interval.
The following summaries use 4096 subdivisions (4097 endpoint samples):

| Octaves | Median extremum gap, natural -> tighter | Worst tighter extremum gap | Largest tighter interval width | Median bound cost, natural -> tighter |
|---|---:|---:|---:|---:|
| 1 | 0.5903 -> 0.00964 m | 0.7034 m | 1.4512 m | 4.84 -> 6.28 ms |
| 6 | 3.6179 -> 0.1942 m | 3.4659 m | 11.0790 m | 26.96 -> 37.03 ms |
| 12 | 25.8552 -> 0.6872 m | 44.8145 m | 193.8953 m | 58.61 -> 79.34 ms |

The tighter method costs more computation. Its complete per-profile timing ranges
at this subdivision are 5.93-9.19 ms, 35.52-39.24 ms and 71.83-111.69 ms for
1/6/12 octaves respectively. Direct evaluation of just the 4097 endpoint samples
has corresponding medians 0.223/1.154/2.268 ms; it does not provide an interval
bound. The 65,537-point reference takes 5.07-61.96 ms across configurations.
Neither timing predicts the complete terrain evaluator or a water network.

At 4096 subdivisions, the tighter method puts the extremum gap at most 1 m in
84/108 configurations, at most .1 m in 48/108 and at most .01 m in 20/108. The natural
control reaches 32/108, 6/108 and 0/108 respectively. These are outcome counts for
this fixed matrix, not adaptive stopping results or universal guarantees.

The hardest tighter case has seed 20260913, twelve octaves, roughness .9 and a
4 km by 4 km diagonal. Its endpoint samples miss a reference peak by 7.3616 m;
its upper bound exceeds the finite reference peak by 37.4529 m, leaving 44.8145 m
of extremum uncertainty. Its most uncertain interval is 193.8953 m wide. Summing
independent octave ranges and enclosing a line in boxes still loses useful
correlation. A tighter global-extremum result also does not by itself bound an
ordered uphill excursion along the path.

Process high-water memory spans 69.96-129.21 MiB. It includes reference arrays,
imports and both policies. No runtime latency improvement, total export timing,
scratch-memory target or larger water budget is inferred from this experiment.

## Runtime correction and validation

The comparison exposed intentional unsigned overflow in the twelfth octave's
scalar hash multiplier. With normal NumPy settings it emitted warnings; with
`over="raise"` it could abort an otherwise supported twelve-detail evaluation.
The runtime now multiplies in Python integer arithmetic and explicitly masks to
64 bits before conversion. Hash mixing and generated values retain their meaning.

A direct comparison with the tracked parent noise implementation covers 48
combinations: four seeds, 1/6/11/12 detail levels and three roughness values,
with 10,001 coordinates each. All 480,048 binary64 noise values match byte for
byte. The old implementation emits 48 warnings across those cases; the corrected
one emits none. Twelve-detail evaluation also passes with overflow errors enabled.
This comparison isolates the changed primitive; it is not a private-map rebuild.

- Full pytest: **582 passed in 235.08 s**. The 59 focused checks also passed
  after correcting the comparison dispatch. The corrected 216-run matrix was
  then measured with the full test suite no longer running.
- Ruff passed for the repository; strict Pyright reported zero errors/warnings.
- All 151 local Markdown links in the six changed documents resolve; whitespace
  checks pass. The documented final matrix command completed successfully.
- Exact-rational tests cover interval arithmetic, cancellation/subnormals and
  the fade/lerp error allowances. Other regressions cover negative coordinates,
  lattice boundaries/interiors/corners, twelve octaves, sign/zero field amplitudes,
  box ordering/batching, Float32 conversion and complete budget/range failures.
- The comparison runner test verifies distinct policy bounds on a discriminating
  fixture, identical sampled inputs and refusal to overwrite a report.

The initial two-policy matrix had a dispatch defect: both labels selected the
tighter default. It is explicitly marked invalid and is not used above. Its
local companion `artifacts/noise-bounds-matrix-20260913.invalid.txt` records the
reason. The earlier natural-only pilot is also not the final comparison.

Ignored local evidence (not committed):

- `artifacts/noise-bounds-matrix-final-20260913.json`: corrected complete comparison;
  SHA-256 `814b312aee947dcda55d56989550f72e7be751d5310b7a67d949bd729c39a008`.
- `artifacts/noise-bounds-summary-final-20260913.json`: aggregates and paired identity checks;
  SHA-256 `7a684566cb1e876f641400bccde7b7daafc0b0cbe0897f744057515a0cb734ee`.
- `artifacts/summarize_noise_bounds.py`: aggregation helper;
  SHA-256 `3b0bae2ad42ab28ea19be232cc934fcef79c14d465e13813df26b27dfb03631c`.
- `artifacts/noise-hash-equivalence-20260913.json`: 48 unchanged-value comparisons;
  SHA-256 `9f074f904b16dab89b13952f2c0a1be6b19d0f7c77fead8a887abda95c7d527b`.

Runtime: Windows 11 AMD64, CPython 3.14.7 and NumPy 2.5.2. The report also records
the existing application dependencies; none was added. Installed engine-source
fingerprint: `f85b589b7da950e4e78994c6905fae708ad332ab6298e65fa96abe0765b20b44`.
Harness fingerprints are `8cd589adb16a53da9aa5bf5797191caa1260a7b6b1dd4b53f7af00ad742c6ca6`
for the runner and `1fca20a49e69149ee2790616b030ac1e39d29274afc71d64c15e59129bf3da18`
for the enclosure module. Project/build formats and numeric algorithm IDs remain
unchanged. The full tests exercise public builds; no Tharkeniss Veld rebuild or
workbench inspection was performed.

## Decision and remaining work

Keep `monotone_cell` as the preferred **research building block**, with `natural`
as a regression/comparison control. It provides substantially tighter component
bounds with a stated arithmetic argument, but the high-roughness results and
extra cost rule out treating it as a finished general clearance solver. Do not
raise water budgets or substitute this component for the complete evaluator.

First investigate segment-focused cells, correlated octave ranges and local
interval/ordered-rise uncertainty. Use measured benefit to decide whether further
noise tightening is worthwhile before expanding the composition. The current
finite station policy remains the runtime water-review contract.

The next component investigation must cover coast-distance/exponential weights,
regional and normalized constraint blends, longitudinal profiles and automatic
incision, including their domain boundaries and rounding. Bounds for a smooth
real formula alone are insufficient for the rounded implementation. A bound for
one component cannot authorize a water-clearance decision on their composition.
Keep complete-profile/network exhaustion explicit, and measure per-interval as
well as global-extremum uncertainty before selecting adaptive refinement.

The backlog also retains larger/complex water workloads, total export cost,
controlling-sill/storage assumptions and explicit lake chains. This experiment
does not change that hydrology model, add dependencies, or justify a Rust rewrite.
