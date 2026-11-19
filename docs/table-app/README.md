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
the program disagree, the program and `CLAUDE.md` are right.

**The advice.** The survival guard has two strengths now ("Cash first"
follows the all-in or fold chart, "Survive, then win" folds only a thin
edge), never folds a good price, and a read lifts it only when it makes the
play safer; a close answer before the money shows the lower-variance side
first. A thin edge is not one number any more: an all-in must earn 0.20bb
plus 0.02bb for every big blind at risk above 10 (`thin_bar`), and the
source line of a clear edge says what it needed. So the acceptance rows T5,
T6, T9, T13, P3, P4, A2 and A3 of `proposal-advice.md` have other answers,
and the answer has two more `guard` values (`edge`, `close`) and a
`provisional` key: `tests/test_app_advice.py` holds the current rows. The
big blind's call of a raise shows the engine's own test ("Need / have"),
"close" is said of it under 7 points, and a hand off the sheet's list with
more to spare is a "SHEET FOLD". Two readings come before the engine: a
short all-in that another player raised over is passed on as a call
(`preflop_acts`), and after a call of the user's own a raise at 5 to 1 or
better is called (`cheap_call_after_calling`). In the all-in plan a call at
a good price is not folded, against an all-in only. Close to the money a
chart limit is said in the user's own chips. Very large fields are not in
the notes: above 1,000 paid places still to reach, the same prize model is
worked out in closed form (`icm.large_field_equity`, `Prizes(large=True)`),
so that an answer stays quick. After the flop the playbook check is no
longer the only rule and no longer for tagged players only. In the engine, a
fold from the opening chart beside a positive all-in number carries a second
reason and `data["fold_by_chart"]`, the rows of the sheet's part 3 carry
`seats` (what the other seat of a pair changes), and `tag.ASKED` and
`tag.CALL_FROM` name the stack each list was asked at: `engine-preflop.md`
does not have these.

**The table.** The dealer button follows a rule (`button_rule`, "dead" by
default) and cannot be moved once a hand has an action; an action for a
player whose fold was only implied follows one rule (`model.py`, above
`_late_action`), and while a street's cards are wanted a fold for a player
whose check was only implied is refused like a bet; every intent carries
`rev` and a stale one is refused with HTTP 409; the folder also holds `.bak`
and `.unreadable-...` copies and `app.lock`, and `/api/ping` lets a second
start find the first. The view has `hand.allin_matched`. The history text
has a "Seats:" line and every bet in chips, enough to play the hand again.
The answer for the table on screen never waits behind one that went stale
(`server.py`, `AT_WORK`: two at most are worked out at a time), and
`POKER_COACH_ADVICE_DELAY` holds answers back for trials. The table's own
sentences call a player "they"; three of the coach's warnings in `advice.py`
still say "he" or "him".

**The page.** The plan is "Moves", the ladder "Blind levels", the one-ink
deck "Two colours" and the menu "Settings". An answer for an earlier
revision is never drawn: the slab says "Updating" (`ui.grace`: the panel
that says where the tournament stands stays, dimmed, for a moment), and news
of the saved files stays until it is dismissed or the table changes (a toast
with `stay`). A box, `#region-scroll`, stands around the table: in a window
shorter than the page it scrolls and the answer and the action bar stay in
place (`app.css`, section 16, with the heights from which each form applies;
`restTable` in `render.js`); in the one-column short form the Why button is
in the slab (`.whybtn`). The move buttons carry `data-for`, the seat they
record for, and a pointer click counts only when the same button has stood
in its place for 400 ms and no change is on its way. `view.toast.redo` is
also read by the page, to bring a finished hand's seat names back after an
undo. The program calls itself Menlo Coach.
