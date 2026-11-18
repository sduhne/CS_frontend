# Menlo poker coach: the table app. Build spec (the lead's rulings)

This file decides. The four proposals and four engine maps in this folder carry the detail;
where they disagree with this file, this file wins.

- `proposal-rules.md`   the data model, the hand state machine, 45 test cases (reference model: `rules_proto.py`, `rules_verify.py`, `rules_fuzz.py`, `rules_cases*.py`)
- `proposal-speed.md`   keys, mouse paths, every mid-game operation
- `proposal-advice.md`  which engine call answers what, the survival guard, the panel, 31 acceptance rows (`proto.py`, `accept.py`, `goals.py`)
- `proposal-visual.md`  tokens, layouts at 1440 / 1024 / 560, components, cards, contrast (mock: `../visual-work/mock.py`, `shot-*.png`)
- `engine-state.md`, `engine-preflop.md`, `engine-postflop.md`, `engine-formats.md`   interface maps of the existing engine, with gotchas
- `fonts/pick/`  the seven woff2 files and two licence texts to copy into `poker_coach/app/static/fonts/`

## 1. What it is

A manual table tracker and coach for study and play money. The user types or clicks what they
see; nothing reads the screen and nothing clicks for them. `python -m poker_coach app` starts a
server on 127.0.0.1 (standard library only) and opens the browser. Works offline: no CDN, no
build step, no new Python dependency. Python 3.10+, Windows first (paths with spaces, CRLF-safe).

Three modes, each with its own saved session: `tournament` (2 to 9 seats), `spin` (3 seats,
heads-up after a bust, winner takes all), `aof` (GGPoker All-In or Fold: 4 seats, 8bb cap).

The user's priorities, in order: correct advice, speed of entry mid-hand, every mid-game edit
one or two actions away, a clean menlo.bet look, code that is easy to read and change.

## 2. Files

```
poker_coach/app/__init__.py
poker_coach/app/defaults.py    everything a user may want to edit: blind ladders, starting stacks, key map, raise presets
poker_coach/app/amounts.py     one parser for every typed amount (proposal-speed §4)
poker_coach/app/model.py       the session, seats and positions, the hand as an event list, replay(), pots, intents, undo, saving
poker_coach/app/advice.py      the adapter to the engine: headline, reason, numbers, guard, warnings, chart
poker_coach/app/server.py      http.server: static files, /api/view, /api/intent, /api/advice
poker_coach/app/static/        index.html, app.css, app.js (plain JS, may be split into a few files), fonts/
tests/test_app_model.py, tests/test_app_advice.py, tests/test_app_server.py
```

CLI: `python -m poker_coach app [--port N] [--no-browser]` (add to `poker_coach/cli.py`).
Sessions are saved to `tournament/app/<mode>.json` (the packaged program: `~/PokerCoach/app/`;
follow the `sys.frozen` rule already in `poker_coach/state.py`). Write atomically after every
accepted intent.

Code style: plain, readable, commented where a rule of poker is being applied. Small functions.
No cleverness. A reader who knows poker and a little Python must be able to follow `model.py`.

## 3. Rulings where the proposals differ

1. **Hero is always seat 1.** Seats are numbered clockwise from hero, 1 to `size`. There is no
   "change hero's seat"; a table move is `new_table`. The seat's key on the keyboard is its number.
2. **Seat labels** are the table in proposal-rules §2 (UTG, UTG+1, UTG+2, LJ, HJ, CO, BTN, SB, BB;
   heads-up BTN/SB and BB). Also fix the engine so every module agrees: make
   `poker_coach/ranges.py position_name` return this table for 2 to 9 players and make
   `poker_coach/preflop.py pos_to_index` accept these names; update the tests that encode the old
   names; the whole suite (`python3 -m unittest discover -s tests`) must stay green.
3. **Friendly on top of strict.** `replay()` is strict (proposal-rules §4). The `act` intent is
   friendly (proposal-speed rules 2, 3, 5): an action on a seat that is not next to act first
   gives every seat before it the implied action (check if free, else fold); a bet above the
   stack becomes all-in; a call with nothing owed becomes a check; a raise below the minimum is
   lifted to the minimum unless it is all-in. Only the impossible is refused (duplicate card,
   an action by a seat not in the hand), with one plain sentence saying why.
4. **Tab is left to the browser** (proposal-visual §9). "Next opponent" is the seat digit or a click.
5. **Default style "Survive, then win"** exactly as proposal-advice §4: prize model `balanced`,
   survival guard on before the money. Styles: `cash` (itm + guard), `survive` (default),
   `maxev` (balanced, no guard). Re-entry open and Spin use chip EV, no guard.
6. **One-ink deck by default**, four-colour deck as a setting (proposal-visual §6).
7. **Undo is one snapshot per accepted intent** (cap 200), across hands. No confirmation dialogs;
   destructive actions show an Undo toast.

## 4. Scope

Must have (this build):

- The three modes, each remembering its own table. Mode tabs in the header.
- Table: seats with position names, names, stacks (chips and bb), bets, dealer button; move the
  button back / forward / onto any seat; edit one stack, sweep all stacks; add, clear, bust, sit
  out / back, rename, type tag, note; table size 2 to 9; new table (table move) keeping hero and
  the tournament.
- Blinds: one click down / up along a ladder, type them by hand (`300/600/75`, or `600` alone),
  ante kind (none, every player, big blind), ladder presets per mode and a custom ladder pasted
  in settings.
- Tournament strip: players left (−1 / +1, and typed), places paid, entrants, starting stack,
  average stack (computed when it can be), buy-in, payouts (`auto` or `1:1000 2:600 4-6:200`),
  style, plan (full / all-in or fold), table-wide opponent type, re-entry open, bounty.
- A hand from deal to result (proposal-speed §3): new hand, hero's cards as a class (AKs) or exact,
  actions with implied folds, streets and board, pot and to-call computed, result with side pots,
  skip hand, discard hand, edit or delete an earlier event, undo / redo.
- The advice panel (proposal-advice §9, proposal-visual §7): verb, size in bb and chips, how sure,
  one reason, key number and what flips it, source line (ICM level, guard verdict), plan lines,
  warnings; the range chart with hero's hand marked; stage, gear, fold clock.
- Keyboard map with a mouse path for everything; `?` shows the keys.
- Spin: game tally (games, wins). All-In or Fold: 8bb cap at the deal, fee, session net in bb.
- Hand history list for the session (cards, the advice shown, what hero did, "deviated"), copy as text.
- Settings: chips / bb display (`v`), deck, ladder, the play-money notice once.

Later (do not build now): command palette, what-if spot, several tables, level clock, paste of
stack lists, hero re-entry flow beyond "new table".

## 5. The server

- Bind 127.0.0.1 only. Refuse requests whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>`.
- `GET /` and static files from `static/` (correct content types; no directory listing).
- `GET /api/view` -> the view (§6). `POST /api/intent` with JSON `{"op": "...", ...}` -> `{"view": ...}` on
  success, or `{"error": {"message": "...", "fix": "..."}, "view": ...}` with nothing changed.
- `GET /api/advice?rev=N` -> the advice (§7) for revision N; if N is not the current revision,
  `{"status": "stale"}`. Compute on request, cache by revision, never block `/api/intent` on it.
- One lock around the model. `ThreadingHTTPServer`. The port defaults to 8765; if it is taken,
  try the next ones; print the address; open the browser unless `--no-browser`.

## 6. The view (what the browser renders)

The browser holds no poker rules: it renders this and sends intents. Every amount is in chips
(All-In or Fold: big blinds) with a ready-made `*_bb` beside it where shown. Shape:

```json
{"rev": 128, "mode": "tournament", "unit": "chips", "deck": "one-ink",
 "can": {"undo": true, "redo": false},
 "strip": {"level": {"number": 12, "sb": 300, "bb": 600, "ante": 75, "ante_kind": "player", "pending": null},
           "remaining": 96, "paid": 75, "entrants": 500, "start_stack": 10000, "buyin": 11,
           "avg_stack": 52100, "avg_bb": 86.8,
           "stage": {"code": "approach", "label": "21 FROM THE MONEY"},
           "icm": "estimated", "style": "survive", "plan": "full", "opponents": "unknown",
           "reentry_open": false, "bounty": false,
           "tally": null},
 "table": {"size": 8, "button": 2,
   "seats": [{"seat": 1, "empty": false, "is_hero": true, "name": "You", "pos": "CO", "is_button": false,
              "stack": 12900, "stack_bb": 21.5, "stale": false, "status": "active", "type": "unknown", "note": "",
              "in_hand": true, "folded": false, "all_in": false, "bet": 0, "bet_bb": 0,
              "is_target": true, "delta": null}]},
 "hand": {"no": 42, "phase": "preflop", "needs": "action",
          "hero_cards": ["Ah", "Kd"], "hero_class": "AKo", "board": [],
          "pot": 1500, "pot_bb": 2.5, "to_call": 600, "to_call_bb": 1.0,
          "target": 1, "target_is_hero": true,
          "legal": {"fold": true, "check": false, "call": 600, "bet": null,
                    "raise": {"min": 1200, "max": 12900, "default": 1320}, "allin": 12900},
          "presets": [{"label": "2.2x", "to": 1320}, {"label": "3x", "to": 1800}, {"label": "All-in", "to": 12900}],
          "line": [{"i": 0, "kind": "cards", "text": "AhKd"},
                   {"i": 1, "kind": "act", "seat": 7, "pos": "UTG+2", "name": "Hal", "verb": "raise", "to": 1320,
                    "text": "Hal raise 2.2bb", "auto": false}],
          "pots": [{"amount": 1500, "eligible": [1, 7]}], "result": null},
 "history": [{"no": 41, "cards": "7c2d", "pos": "HJ", "advice": "FOLD", "did": "fold", "deviated": false, "net": -75, "text": "..."}],
 "toast": null}
```

- `table.seats` has one entry per seat 1..size, empty ones too (`"empty": true`).
- `hand` is `null` between hands. `phase`: preflop, flop, turn, river, showdown, done.
- `needs` tells the browser what to ask for now: `cards` (hero's cards missing), `action`,
  `board` (a street's cards), `result` (who won), `next` (hand settled: press N).
- `strip.tally`: Spin `{"games": 12, "wins": 5}`; All-In or Fold `{"net_bb": 3.4}`; else null.
- `strip.stage.code`: unknown, early, middle, approach, bubble, itm, final.
- `strip.icm`: off, estimated, on, exact (proposal-advice §5).

Intents (final names; arguments as in proposal-rules §6 and proposal-speed §10, text parsed in Python):
`new_session`, `set_mode`, `set_tournament`, `remaining`, `set_config`, `level_up`, `level_down`,
`set_level`, `set_ante_kind`, `set_ladder`, `set_size`, `new_table`, `set_button`, `button_step`,
`seat_player`, `clear_seat`, `bust`, `set_stack`, `set_stacks`, `set_status`, `rename`, `set_type`,
`note`, `deal`, `set_cards`, `act`, `close_round`, `edit_event`, `remove_event`, `award`,
`skip_hand`, `discard_hand`, `new_game` (Spin), `undo`, `redo`.

## 7. The advice (what `/api/advice` returns)

```json
{"rev": 128, "status": "ready",
 "headline": {"verb": "RAISE", "size_text": "TO 2.2BB · 1,320", "qualifier": "", "tone": "attack",
              "sure": "standard", "follow": {"kind": "raise", "to": 1320}},
 "spot": "AhKd in the cutoff, 21.5bb, folded to you",
 "reason": "The blinds are tight and you cover both. A raise keeps the fold option against an all-in.",
 "tiles": [{"label": "OPEN RANGE HERE", "value": "26%", "note": "A9o+ is inside it", "sign": 0},
           {"label": "FOLD TO AN ALL-IN", "value": "-2.2bb", "note": "unless TT+, AQ+", "sign": -1}],
 "flip": "All-in instead under 16bb.",
 "also": "All-in is close behind: +0.31bb.",
 "source": "ICM estimated · the all-in table agrees",
 "plans": ["If BB (28bb) shoves: FOLD"],
 "warnings": [{"code": "icm_estimated", "text": "Payouts are estimated: enter the smallest prize for exact ICM."}],
 "chart": {"title": "CUTOFF, FIRST IN, 21.5BB", "share": 26, "hero": "AKo",
           "cells": [["r", "r", "..."]], "numbers": null,
           "legend": [{"code": "r", "label": "Raise"}, {"code": "c", "label": "Call"}, {"code": "x", "label": "Close"}, {"code": "f", "label": "Fold"}]},
 "context": {"stage": "Approaching the money: keep stealing, refuse marginal all-in calls.",
             "gear": "16-25bb: raise-fold and re-shove.", "fold_clock": "You can fold into the money."}}
```

- `status`: ready, none (nothing to advise: no cards, not hero's turn; `spot` says what is awaited), stale.
- `tone`: attack (raise, bet, all-in), passive (call, check), fold, wait.
- `follow` is the intent arguments that carry out the advice (`Space`), or null.
- `tiles[].sign`: +1 a gain (green), −1 a loss (red), 0 neutral. Green and red are used for nothing else.
- `chart.cells` is 13 rows of 13 codes in the usual grid (row and column A to 2; suited above the
  diagonal): r raise or all-in, c call, x close or mixed, f fold. `numbers` optionally holds a
  13x13 of short strings (EV or equity) for the cell tooltips.
- Seat names in every text are the app's (ruling 2). Chips are formatted with thousands separators.
- The adapter must never raise: on an engine error it returns status ready with verb "NO ADVICE",
  tone wait, and the error as the reason.

Acceptance: the 31 rows of proposal-advice §11 become tests (headline verb and, where given, the
guard verdict), plus "never raises" over random legal hands.

## 8. The interface

Follow proposal-visual in full: tokens, type, layouts at 1440 / 1024 / 560, seat slots, components,
states, the slab, the chart, contrast, microcopy. Follow proposal-speed for keys and flows, with
ruling 4. In addition:

- Everything is reachable by mouse: clicking a seat opens its menu (stack, name, type, note, sit
  out, button here, bust, clear); clicking a value in the strip edits it in place; clicking a chip
  on the hand line selects that event (edit amount, delete).
- The strip values that matter for ICM (left, paid) show a small "set" prompt when empty.
- A settings sheet (menu icon): tournament form, style, plan, opponents, ladder, unit, deck, new
  tournament, history, keys, the notice "For study and play money. Real-money sites ban real-time help."
- First run (no session): a short setup form per mode with sensible defaults, one button to start.
- Errors from an intent show as a one-line toast; nothing is lost.
- The page must stay usable with the keyboard alone and with the mouse alone.
- No external requests of any kind. No emoji. Suits and icons are inline SVG.

## 9. Tests and checks

- `tests/test_app_model.py`: the 45 cases of proposal-rules §9 and the fuzz property (stacks +
  pots constant; always a next actor, a showdown or done) on a few thousand random hands.
- `tests/test_app_advice.py`: the acceptance rows; no exception on random hands in all three modes.
- `tests/test_app_server.py`: start on a free port, drive a hand through `/api/intent`, read
  `/api/view` and `/api/advice`, static files served, bad Host refused.
- The existing suite stays green: `python3 -m unittest discover -s tests`.
- Browser check with Playwright (already installed; `require('playwright')` works from any
  directory, chromium.launch() needs no options): play a hand with the keyboard only and one with
  the mouse only at 1440, 1024 and 560 wide, in each mode; screenshots; no console errors.
