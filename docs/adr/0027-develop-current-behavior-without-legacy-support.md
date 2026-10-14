# ADR-0027: Develop current behavior without legacy support

**Status:** Accepted
**Date:** 2026-09-06
**Decider:** Explicit user instruction.

## Decision

Map Maker is in early development. Implement and improve the current product;
remove obsolete behavior instead of maintaining legacy features, old saves,
compatibility switches, migration tools or deprecation periods. Keep authored
source safety and current correctness checks. Old code remains in Git history.

Format and algorithm identifiers still identify build inputs and behavior.
They do not promise support for previous versions. Update the current example,
schemas, tests and documentation whenever behavior changes. Test deterministic
current results and scientific invariants; old-output equality is not a gate
against deliberate improvements.

This supersedes ADR-0026's opt-in and legacy support decision and any earlier
commitment to preserving obsolete formats or algorithms. Its named seed
encoding remains the current implementation.

## Immediate implementation

- Use named stage derivation for every terrain build; remove the direct-master
  seed branch, configurable seed policy and workbench compatibility selector.
- Keep one project/build format, version 3, with no old-format dispatch.
  Remove the four v1/v2 schema files and their cross-version references.
- Use the single current public example; remove the alternative seed example.
- Keep seed identity and resolved stage seeds in build metadata. Current
  settings need only the numeric master seed.
- Replace dual-version tests with current round trips, schema validation,
  unsupported-input rejection, seed reference values and terrain invariants.

## Consequences

Old v1/v2 saves are unsupported and must be recreated. No migration is supplied.
Default generated terrain changes because named derivation now always applies.
Future improvements may change it again. This removes maintenance paths now
while keeping reproducibility within an identified implementation.

The alternative of keeping legacy support was explicitly rejected by the user.
Removing all version identifiers would obscure build provenance without
improving iteration speed, so identifiers remain.

## Validation

All 160 current tests, Ruff and strict Pyright pass. Validated 167 local
Markdown links and initialized the Tk workbench with a withdrawn window.
Current save/build round trips and schema validation use only version 3.
Three geometry checks now use a controlled noise fixture; their assertions
and tolerances are unchanged, and the peak/pass fixture explicitly verifies
that surrounding terrain starts below its lowest crest. Separate tests still
exercise stochastic generation, portable seed values and nested samples.
