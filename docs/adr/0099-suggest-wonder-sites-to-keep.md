# ADR-0099: Suggest plausible wonder sites for the user to keep or reject

- Status: accepted (experimental product path)
- Date: 2026-10-15
- Extends: [ADR-0097](0097-wonders-as-a-layer-on-a-base-planet.md) (wonders as a layer)
  and [ADR-0098](0098-wonder-settings-from-the-catalog.md) (settings per kind)

## Context

Wonders were either random, one draw per kind and no say over where, or placed by
hand, which needs the user to know where a kind of landform would fit. Neither
helps a user who wants to choose among good places. A random wonder's place also
rests only on eligibility (inland, high ground, a desert); nothing says why one
place suits it better than another.

## Decision

1. **Candidates come from the random placers.** For each kind, the random placer
   is run from eight sub-streams of a new stage seed (`planet.wonder-suggestions`),
   kept clear of the candidates before it where the placer allows. Candidates are
   therefore drawn as random wonders are, by continuous draws that a mesh
   resolution does not change.
   Splitting rivers are found, not drawn: the best low divides of the largest
   rivers, one per river.
2. **Each candidate is scored by what the planet is like there.** A score from 0
   to 1 combines factors that stand for a stated hypothesis:
   - craters survive on old, stable crust in dry country;
   - chasms open where plates pull apart or on high plateaus, and deep cuts count;
   - great cliffs mark a step between high and low country;
   - tepuis stand on old shields in the wet tropics;
   - a titan needs a mantle plume, far inland;
   - shattered volcanoes belong on arcs, active giants among active volcanoes;
   - oases lie in deep desert below mountains that feed their springs;
   - the largest rivers make the most striking divided rivers.

   The reason names the strong factors. Scores rank places; they do not claim a
   place would really hold such a wonder.
3. **The best four of each kind are suggested**, at least 400 km apart, from the
   planet without wonders. The Wonders step lists them by kind with their scores,
   draws them as dashed ghosts and says why the selected one fits.
4. **Keep and Reject.** Keeping a suggestion adds an ordinary placed wonder at its
   place and size with a new seed; the user can then change it like any other.
   Rejecting hides it. Suggestions live in the session; the wonder document holds
   only kept wonders. Applying wonders keeps the planet without wonders, so the
   suggestions stay valid; a new one makes them stale.
5. **Random placement stays.** Random kinds remain the unattended way to add
   wonders (the Generate step and `--random-wonders`), unchanged and bit-identical.

## Consequences

- Choosing among good places takes one job of a few seconds (36 suggestions in
  3.3 s on a 50,000-point planet) instead of trial placements and rebuilds.
- Ranking reads mesh fields at each candidate, so near-equal scores may order
  differently at another mesh resolution even though the candidates are the same.
- A kept wonder is redrawn from its own seed, so its outline can differ from the
  random shape the suggestion was drawn with; its place and size are kept.

## Alternatives considered

- **Replace random wonders with the top suggestion per kind.** Rejected for now:
  it would change every existing random planet and drop the tuned random counts
  (one to three craters by land area, tepui groups, several oases).
- **Score every node and pick maxima.** Rejected: graded weights follow relief
  details that differ between mesh resolutions, which is why random placement uses
  eligibility and continuous draws.
- **Realise every suggestion in the relief.** Rejected: lakes, rivers and ice would
  be worked out around wonders the user then rejects, and aged ones cost minutes.
