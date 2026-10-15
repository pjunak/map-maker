# ADR-0098: Describe each wonder kind's settings once, in the catalog

- Status: accepted (experimental product path)
- Date: 2026-10-15
- Extends: [ADR-0097](0097-wonders-as-a-layer-on-a-base-planet.md) (wonders as a layer)

## Context

A placed wonder could fix only its position, size and age; the generator chose
everything else, such as a chasm's side canyons or a tepui's plan, from the
wonder's seed. The Wonders step placed wonders on the source drawing, so their
setting in the generated relief was invisible until the planet was made. Each
new setting would otherwise need its own field in the document, its own
validation and its own form entry.

## Decision

1. **The catalog declares each kind's settings.** `WonderSpec.options` lists them
   with a name, label, unit, range, whether it is a count, and a line on what it
   means and what blank does. Validation (`WorldWonder`), the wonder document's
   `options` object (wonders v2, whose allowed names come from the catalog) and
   the Wonders step's fields are all made from that list.
2. **Blank is automatic.** A fixed setting replaces the value the generator would
   choose. The wonder's random stream still makes every draw, so fixing one
   setting leaves the rest as they were drawn.
3. **The first settings** are what the generators already chose: the volcanoes'
   heights, a crater's depth, a chasm's depth cap, side canyons and parallel
   troughs, a tepui's height, elongation and orientation, and a splitting river's
   share of water. A crater depth the ground cannot hold is an error, since the
   floor must stay above sea level; a chasm's depth stays a cap, shallower where
   the ground is lower.
4. **Wonders are placed on the planet.** Once a planet exists, the Wonders step's
   map offers its maps under the wonder symbols, the relief by default, with the
   planet read out under the cursor. The maps show the planet as last made;
   applying shows changed wonders in them.

## Consequences

- Wonder documents are format v2; v1 files do not open (early development).
- Wonders without settings, and random wonders, are generated exactly as before:
  on the four-shores example the random wonders still give bit-identical planets.
- A setting the generator cannot honour exactly is reported or documented in its
  help line rather than silently changed.
- Not yet: a shattered volcano's breach direction, which follows from its position
  and is not stored with the volcano; suggested sites to keep or reject.

## Alternatives considered

- **A typed field per setting on `WorldWonder`.** Rejected: every new setting
  would touch the domain type, the document, the schema and the form separately.
- **Redrawing the whole shape when a setting changes.** Rejected: fixing one value
  would then reshuffle the others, which defeats placing a wonder deliberately.
