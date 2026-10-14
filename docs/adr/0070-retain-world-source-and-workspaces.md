# ADR-0070: Retain world sources in a dedicated workspace

- Status: Accepted
- Date: 2026-09-25

## Context

The existing terrain importer dissolves land and repairs selected gaps/holes for
local generation. It loses semantic continent identity and derives scale from
local bounds. Applying it to an entire world cannot satisfy the WC0 contract:
source geography, continent/island membership and planetary placement must survive
before any physical land union, climate model or erosion history is introduced.

## Decision

Add a World workspace alongside local Terrain in the same Tk window. World owns
source import, continent assignment, explicit full-sphere Plate Carrée metadata,
validation and a portable `.world.json` project. Terrain retains its local
input/generation workflow. Startup flags and keyboard actions select the active
document; dirty-state guards cover both. Future stage names explain direction
without exposing generation controls whose backend does not exist.

`domain/world.py` owns immutable frame/source/assignment/project values and
spherical conversion/distance rules. `adapters/world_svg.py` parses original SVG
into retained shapes with separately sampled inspection geometry. It never uses
the local importer's dissolve/repair path. The original UTF-8 source is embedded
with a hash, preserving hierarchy, transforms and element IDs. Anonymous IDs are
deterministic for geometry/group context; stable authored IDs are preferred.

`pipeline/world.py` validates wrapped geometry and ownership and measures sampled
land on the declared sphere. It uses typed values and Shapely, matching existing
numerical geometry stages. File reads/writes remain in adapters, coordinated by
`application/world.py`; the domain performs no I/O. Rendered previews are bounded
to the viewport with independently masked holes and clipped periodic copies.

The world schema is independent of the local terrain schema. Every retained shape
is assigned or explicitly excluded; all continents have land. Invalid rings,
unsupported clipping, ambiguous IDs, overlapping land, unsupported projections
and altered source identity fail rather than silently repair or reinterpret.
Touching semantic continents remain distinct. Source longitude may cross the
seam continuously; derived copies split at it without duplicating area. Full
world latitude bounds, radius and central meridian are explicit inputs.

Save reparses/verifies the snapshot, validates topology and atomically replaces
only a `.world.json` destination. Open reparses the embedded source; it needs no
external SVG. Save/open/import failures preserve the current document or existing
file. Ownership undo/redo and dirty guards operate independently of Terrain.
Background operations own results; Tk callbacks and images are released on close.

## Consequences and limits

WC0 source import is usable without adopting a climate/tectonic engine or adding
runtime dependencies. The source project is not a generated parent and cannot be
fed to local generation as if it supplied a projection or climate context.
WC1 onward must build on its stable geometry/ownership, explicit units and frame.
Local terrain output coordinates and schemas do not change in this decision.

Inspection boundaries approximate curves and area depends on that approximation.
The spherical area integral follows source-linear segments, not geodesic chords.
Only a full-world spherical Plate Carrée source is supported; no partial-world,
raster/native Affinity import or metric regional projection is implied.
Styles/layers that cannot be interpreted safely need explicit vector export or
exclusion. Saving incomplete mapping drafts and cancelling world-import jobs are
follow-ups; the first project format deliberately accepts validated sources only.

The public four-continent fixture and regression tests cover touching owners,
owned islands, holes/fill rules, transforms, offset frames, seam and pole behavior,
malformed inputs, schema/hash/atomic-save rules and both workspaces' lifecycle.
The [WC0 implementation report](../research/2026-09-25-world-source-workspace.md)
records executed checks and measurements. The [user guide](../terrain-worlds.md)
owns the actual workflow and current limits.
