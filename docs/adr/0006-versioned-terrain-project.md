# ADR-0006: Persist authored terrain as versioned JSON with a verified SVG reference

**Status:** Accepted
**Date:** 2026-09-03
**Deciders:** Repository owner and project maintainer

## Context

The terrain workbench can now accumulate meaningful user-authored constraints
and independent tool settings, but they previously existed only for the life of
the window. Persisting that state creates the first durable public data contract
in the repository. It must remain readable by a future command-line and hosted
interface without coupling either one to Tk or Python dataclass layout.

The coastline is already an authored SVG source. Copying its 4,096 sampled
points into every project would duplicate authority and obscure whether later
SVG edits changed the geography against which normalized constraints were
authored. Embedding generated rasters would likewise mix authored input with
derived output.

## Decision

- Use UTF-8 JSON files ending in `.terrain.json` for the first terrain-project
  contract.
- Identify the contract with `schema: map-maker.terrain-project` and the integer
  `schema_version: 1`. Publish its structure as
  `schemas/terrain/project-v1.schema.json`.
- Store the coastline as an external SVG path plus the SHA-256 of its exact
  bytes. Write a path relative to the project file when the files share a
  filesystem volume; otherwise write an absolute path.
- Verify the SHA-256 before accepting a project. Also refuse to save if the SVG
  changed after it was imported into the current workbench.
- Persist generator settings, ordered authored constraints, the selected tool,
  and the independent settings for all four authoring tools.
- Keep normalized constraint coordinates and explicit elevation modes in the
  public document. Do not serialize private Python class names.
- Keep the Float32 DEM, previews, and future contours outside the project as
  derived build products.
- Validate version 1 strictly, including unknown fields. A future incompatible
  shape requires a new schema version and an explicit migration path.
- Write through a temporary file in the destination directory and atomically
  replace the target after the complete JSON document reaches disk.
- Limit project input to 16 MiB in this initial local implementation. This is
  ample for the current vector constraints while bounding accidental or hostile
  input before a hosted interface exists.

## Options considered

### External SVG reference with a content hash

This keeps one authoritative coastline, makes changes detectable, and produces
small reviewable project files. Moving a project without its SVG breaks the
reference, so both files must be moved together while preserving their relative
layout.

### Embed sampled coastline geometry in JSON

This makes the project self-contained, but creates two competing coastline
sources and bakes an implementation sampling density into authored data.

### Store a ZIP-style project bundle

A bundle could be portable and self-contained, but is harder to inspect and
version in Git. It is unnecessary until projects own more source assets.

### Serialize Python objects directly

Pickle or implementation-shaped JSON is quick to add but unsafe or brittle for
long-lived files, other interfaces, and future non-Python consumers.

## Consequences

- Users can close and reopen a continent without losing constraints or
  per-tool settings.
- Git diffs show meaningful authored changes and no generated binary payload.
- A missing or changed SVG produces an explicit error instead of silent terrain
  drift.
- The project contract can be consumed later by a CLI or HTTP adapter.
- Renaming or moving the SVG separately requires repairing the recorded path;
  changing its bytes requires a deliberate re-import and save.
- Version migration, portable bundles, and generated build manifests remain
  separate future work.

## Validation

- Contract tests round-trip all current constraint kinds and authoring settings.
- Tests verify relative SVG paths, version and unknown-field rejection, load
  failure after SVG modification, and save failure after the imported SVG
  changes.
- Ruff, strict Pyright, the full pytest suite, and a Tk interaction smoke test
  cover the implementation before commit.
