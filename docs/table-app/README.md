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

## What changed since the design notes

The notes are a record of the design and were not rewritten; where they and
the program disagree, the program and `CLAUDE.md` are right. The survival
guard has two strengths now ("Cash first" follows the all-in or fold chart,
"Survive, then win" folds only a thin edge), never folds a good price, and a
read lifts it only when it makes the play safer; a close answer before the
money shows the lower-variance side first. So the acceptance rows T5, T6, T9,
T13, P3, P4, A2 and A3 of `proposal-advice.md` have other answers, and the
answer has two more `guard` values (`edge`, `close`) and a `provisional`
key: `tests/test_app_advice.py` holds the current rows. After the flop the
playbook check is no longer the only rule and no longer for tagged players
only. In the table: the dealer button follows a rule (`button_rule`, "dead"
by default) and cannot be moved once a hand has an action; an action for a
player whose fold was only implied follows one rule (`model.py`, above
`_late_action`); every intent carries `rev` and a stale one is refused with
HTTP 409; the folder also holds `.bak` and `.unreadable-...` copies and
`app.lock`, and `/api/ping` lets a second start find the first. On the page
the plan is "Moves", the ladder "Blind levels", the one-ink deck "Two
colours" and the menu "Settings". The program calls itself Menlo Coach.
