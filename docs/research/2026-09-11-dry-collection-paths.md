# Dry collection paths: research and implementation rundown

Date: 2026-09-11. Public synthetic fixtures only; no campaign geometry changed.
Decision: [ADR-0043](../adr/0043-review-dry-collection-paths.md).

## Outcome

Dry collection now checks the finished Float32 field between canonical nodes,
then checks cumulative rises over complete selected paths. A narrow authored
feature in the new public fixture produces a 131.44 m climb missed by a control
that omits only that feature's extra probes. Node 18589 previously selects 18845;
the full review selects the clear neighbour 18846 and still collects its area.
The imposed 750 m lake level, terrain, MFD capture and incision limits do not
change between those reviews. The authored point itself changes terrain relative
to the scene without it; the review does not.

The [fixture](../../examples/terrain/dry-collection-barrier.terrain.json) adds
an unattached relative +150 m point with 100 m influence radius at normalized
(0.33058203125, 0.47927814569536425). The rejected link uses 32 samples, including
25 feature-guided extras and a 25 m local spacing limit. Its sampled low is at
(1322.916667, 1135.406942) km and crest at (1322.328125, 1135.998190) km.
These are sparse observations in a synthetic continent-scale scene, not surveyed
geography or a hydraulic solution.

## Routing and evidence

All candidate dry descents are considered before selecting metric steepest
receivers. Exact dry flats must pass in both directions; the surviving symmetric
graph feeds the existing integer-gradient routing. The flat method is adapted
from [Barnes, Lehman and Mulla](https://arxiv.org/abs/1511.04433), whose method
combines gradients toward lower exits and away from higher terrain. The new
sampling and cumulative gates are project decisions, not claims from that paper.
Closed pits remain eligible destinations and ground is never filled or nudged.

A dry-to-water profile clips submerged ground to the imposed water level; other
dry profiles use raw ground. This prevents deep lake beds from pulling donors
past a preferred pit and prevents submerged bed undulations from becoming false
exposed barriers. The wet/contact, shoreline and external checks remain separate.

A locally clear route can accumulate an excessive climb. A synthetic flat with
an 8 mm low on one link and an 8 mm crest on another passes each link but has a
16 mm total excursion. The upstream donor stays retained while its valid suffix
still collects. Selected paths remain exported alongside the complete excursion;
there is no new search over alternative downstream states at this final gate.

Dry planning has a separate 262,144-sample budget per eligible lake, checked before
any terrain evaluation. It preserves repeated endpoints and every baseline probe,
uses existing per-profile limits and batches at most 4,096 samples per call.
Failure retains every dry donor with no accepted prefix; verified wet contributions
can still drain. Wet-network failure continues to block the whole outlet.

Build v16 replaces v15. Each basin exports dry-link witnesses and cumulative
barrier origins. `basin-flow.npz` adds Float64 `internal_path_uphill_m`. Workbench
details explain retained area and sampling status; the review shows up to 12
strongest spatially separated dry crests per basin instead of flooding the map
with every rejected candidate. All link evidence remains in diagnostics.

## Validation and measurements

Final checks: **412 tests passed in 220.87 s**, Ruff passed and Pyright reported
zero errors. The first full run exposed a test still looking up the removed v15
schema ID; the reference was corrected and the full suite rerun successfully.
Independent synthetic checks reconstruct complete selected profiles and verify
acyclic sparse-flat routing. Real examples also check constraint-order and
output-resolution independence, closure, unchanged ground/capture/cuts and area
conservation. Repeated builds retain byte-identical diagnostics and manifests.

Hidden Tk checks passed **20 overlay combinations** over the barrier, flat,
dry-budget, wet-blocked and cumulative-detail states. The cumulative count uses
a controlled display fixture; engine behavior is independently tested with the
8 mm + 8 mm synthetic path. Two public CLI builds passed v16 schema validation,
every manifest hash, numeric dtype/finite checks and per-node area conservation.
Both four-panel drainage images were visually inspected: classes, captions and
bounded barrier markers are legible. These checks do not constitute acceptance
on the user's private Tharkeniss Veld project.

The performance harness ran eleven 768-pixel, seed-42 scenes, twice each in fresh
Python 3.14.7 processes on Windows, serially without competing tests or builds.
All **27 numeric hashes** repeated per case; the harness also checks repeated
review evidence. The comparison baseline is the preceding wet-link revision
`fb1831c`, measured earlier on this machine, not alternating revision runs.

| Public case | Previous median (s) | New runs (s) | New median (s) | Generation peak (MiB) |
|---|---:|---|---:|---:|
| authored | 2.388 | 2.363 / 2.301 | 2.332 | 124.1 |
| archipelago | 2.529 | 2.564 / 2.571 | 2.567 | 105.0 |
| regional | 1.612 | 1.614 / 1.605 | 1.610 | 131.2 |
| water | 1.525 | 1.555 / 1.605 | 1.580 | 136.6 |
| outlet | 1.732 | 2.730 / 2.671 | 2.700 | 136.3 |
| flat | 1.729 | 2.843 / 2.843 | 2.843 | 136.2 |
| shoreline | 1.621 | 1.689 / 1.655 | 1.672 | 136.0 |
| narrow | 1.647 | 1.649 / 1.596 | 1.622 | 136.5 |
| downstream | 1.635 | 1.653 / 1.593 | 1.623 | 136.2 |
| internal | 1.744 | 1.713 / 1.694 | 1.703 | 136.0 |
| dry | n/a | 2.732 / 2.716 | 2.724 | 136.1 |

For all ten shared scenes, input hashes match. Ground, original planning arrays,
incision/caps, masks and previous shoreline/outlet/wet-link evidence remain exact.
Only six existing collection arrays change in `outlet` and `flat`: receivers,
classes, retained area and transferred source/throughput/terminal area. The other
eight scenes keep all 26 previous numeric hashes; the extra hash identifies the
new path-excursion array. Dry collection is skipped when earlier checks block it.

Eligible examples add about **0.97 s (outlet)** and **1.11 s (flat)**, roughly
56% and 64% over the earlier medians. Peak process memory remains around 136 MiB;
this is the high-water mark including imports/preparation, not a statement that
the new stage allocates nothing. Generation timings exclude exports, encoding
and publication. Keep the additional cost explicit rather than treating unchanged
non-lake examples as representative of the new work.

| Lake fixture | Candidate links | Requested samples | Rejected links | Collected water / dry nodes | Retained nodes | Outlet area (km2) |
|---|---:|---:|---:|---|---:|---:|
| connected-outlet | 16,413 | 105,901 | 6,661 | 276 / 1477 | 2687 | 435,200.279379 |
| flat-outlet | 17,042 | 111,895 | 200 | 111 / 4147 | 182 | 1,406,028.847105 |
| dry-collection-barrier | 16,417 | 105,951 | 6,714 | 275 / 1458 | 2707 | 429,907.589868 |

Captured area stays 2,066,161.818656 km2 for the connected example and
1,464,366.994597 km2 for the flat example. Their former outlet areas were
649,077.696806 and 1,423,407.974020 km2. Finer dry checks now retain the extra area;
no new water, rainfall or terrain change accounts for the difference. The new
barrier fixture captures 2,064,996.550201 km2 and retains 1,635,088.960333 km2.
All reported whole-terrain balance errors have magnitude below 3e-9 km2.
These are the existing equal-node contributing areas, not exact polygon areas.

Prepared-field dry-stage probes repeated three times per fixture: medians were
0.927 s, 1.052 s and 0.983 s for connected, flat and barrier respectively. Their
105,901, 111,895 and 105,951 probes used **26, 28 and 26 terrain-evaluation batches**.
A separate instrumented pass preserved every review record and attributed about
0.34-0.37 s to profile planning, 0.11-0.12 s to preparing positions, 0.33-0.36 s to
terrain sampling and 0.002-0.010 s to the flat kernel. The remaining 0.17-0.22 s
covers graph preparation, witnesses, path composition and evidence construction.
These instrumented stage times are attribution probes, not substitutes for the
unprofiled generation medians. They support optimizing planning and repeated
sampling before replacing the flat solver or rewriting the runtime.

Complete single CLI runs, including process startup and all exports, took
3.832 s for the new barrier fixture and 3.658 s for flat. Their diagnostic JSON
files were 9,912,719 and 10,018,479 bytes; numeric basin-flow archives were only
16,123 and 16,315 bytes. Evidence serialization is now a material product-size
cost even though these local full builds remain short. Compact, reviewable
storage and shared probes deserve measurement before increasing network size.

Ignored local evidence is retained under `artifacts/`:
`dry-links-performance-20260911.json`, `dry-links-performance-summary-20260911.json`,
`dry-links-validation-20260911.json`, `dry-links-ui-20260911.json` and
`dry-links-build-validation-20260911.json`. The completed build directories are
`dry-links-dry-build-20260911` and `dry-links-flat-build-20260911`.
Generated builds and local profiling scripts are excluded from the commit.

## Prioritized next work

1. **Broader sampling convergence.** Compare interval reductions and shifted
   probes over procedural relief, regional transitions, overlapping features and
   Gaussian context tails. A smaller authored core spacing is not an accuracy
   guarantee for the whole field; fixed graph links also miss off-grid detours.
2. **Measured network efficiency.** Profile planning, repeated endpoint evaluation
   and diagnostic serialization. Consider shared stations and indexed feature
   candidates only with exact Float32/provenance and budget equivalence checks.
   Keep Python while these choices remain under active iteration.
3. **Path-aware alternatives and water assumptions.** Compare bounded complete-path
   selection without bias toward lake exits. Define controlling sill, storage and
   compatible level semantics before lake chains or automatic breach proposals.
4. **Visible landform controls.** Continue per-vertex ridge/valley profiles, explicit
   passes and asymmetric slopes once their routing interactions have clear tests.

The [TODO](../../TODO.md) records completion and these follow-ups; the
[strategy](../strategy/README.md) owns the dependency order. Terrain review still
simulates no discharge, equilibrium lake storage, sediment or changing coastlines.
