# Table app: design notes

How the manual table tracker and coach under `poker_coach/app/` was designed.

- `SPEC.md` is the build spec: scope, files, the JSON the page renders, the
  advice JSON, and the rulings where the proposals disagreed.
- `proposal-rules.md`, `proposal-speed.md`, `proposal-advice.md`,
  `proposal-visual.md`: the four design proposals the spec was merged from
  (poker rules and state, input speed and every mid-game operation, decision
  quality, brand and layout).
- `engine-*.md`: interface maps of the existing engine, with the gotchas a
  caller meets.
- `reference/`: the scratch scripts behind the proposals' numbers (a
  reference model of the betting rules with its checks, the advice router
  prototype with its acceptance rows, the static mock of the screen). They
  are records, not part of the program, and some paths in them point to a
  scratch folder that no longer exists.
