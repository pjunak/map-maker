# ADR-0076: Author world geology inputs independently of generated context

- Status: Accepted
- Date: 2026-09-25
- Extends [ADR-0075](0075-measure-spherical-geographic-exposure.md) with authored
  hypotheses; does not supersede world-source v1 or geographic context v3.

## Decision

Introduce a portable, current-only `.geology.json` v1 input recipe. Retain its
complete world-source snapshot and canonical document fingerprint. Require one
profile per continent and explicit, independently named polygon provinces.
Resolve these against the existing prepared world coverage, without moving
coastlines, repairing invalid province polygons or inferring tectonic plates
from continent names.

A profile contains a geological setting and three independent optional Ma
values: crust age, time since rejuvenation and requested evolution duration.
All use a single common present; duration is not an age. Unknown values remain
unknown. Do not encode erosion coefficients, epoch forcing or calibrated
physical transitions until a consuming model establishes their contracts.

A province replaces a complete default profile, including unknown values.
Highest priority wins; equal-priority overlap on land remaining after higher
priorities is an error. Boundary-only contacts are permitted. Stable province
IDs order exact boundary inspection. Retain empty effective provinces with zero
area. Report effective spherical areas and check their sum against prepared land.
This is a categorical input partition, not an imposed elevation seam.

Use simple source-linear rings with a declared seam convention: first vertex
within the frame, north/south coordinates within its extent, width at most one
world, edges at most half a world. Unwrapped x coordinates cross the seam;
intersect shifted copies with the world frame before land coverage. Reject
self-crossings, repeated vertices and degeneracies. Limit to 128 provinces,
256 vertices per province, ages up to one million Ma and a 40 MiB input file.
These are admission limits, not physical calibration or a hard memory cap.

The dedicated owned editor draws these pre-generation instructions over source,
read-only context or effective geology. It owns separate dirty/save state,
20-step history, drawing/redrawing/deletion, background resolution and cooperative
cancellation. World replacement/close includes its unsaved guard. Saves verify
retained geometry, flush a temporary sibling and atomically replace only the
expected destination state. No backward-compatible loader or migration is added.

## Alternatives and consequences

Putting hypotheses in generated context would mix editable instructions with
immutable products; extending the world-source document would conflate source
geography with optional generation scenarios. A separate portable recipe allows
several explicit scenarios for one world, at the cost of duplicating embedded
source bytes and needing an explicit matching world in the editor.

Per-field inheritance and automatic conflict tie-breaking would make the winning
profile harder to inspect. Complete replacement and explicit priority are the
first contract. Multipart geometry, vertex manipulation, soft physical tapers,
world rebasing, bathymetry, forcing compilation and history consumption remain
separate work. The existing terrain pipeline consumes none of these fields yet.

## Validation

Public controls cover cross-continent and seam belts, source-unit changes,
analytic spherical area, inland holes, priority/tie behavior, independent ages,
invalid geometry and strict file identity. Real Tk tests cover editing/history,
failed edits, pointer-based seam drawing, cancellation, context/source isolation,
external file changes and save-on-close. See the
[implementation report](../research/2026-09-25-authored-world-geology.md).
