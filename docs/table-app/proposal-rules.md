# Table app: poker rules and state model

Section 9's numbers were computed by a reference model (`rules_proto.py`, `rules_verify.py`, `rules_fuzz.py` in this folder); cases 33 to 35 and 37 are specified only.

## 1. Ground rules

1. **A hand is an event list.** `hand.events` plus the frozen start is the only stored truth; pot, to-call, next to act and stacks come from one pure function, `replay(hand) -> view`.
2. **Every amount is a street total ("to")**, as the client shows it and as `preflop.Act.amount` expects.
3. **A hand freezes its cast.** Order, start stacks, blinds and button are copied at the deal. Table edits change the next hand.
4. **Strict by default, the screen wins.** Illegal actions are rejected with a suggested fix; `force: true` records what the user saw. `set_stack` is always allowed.
5. **The engine gets indices, never seat labels.**
6. **Certain changes are applied, uncertain ones are flagged, nothing is guessed.**

## 2. Seats and positions

Seats are numbered 1 to `table.size` (2 to 9), clockwise. **Dealt in** = status `active` or `away`, stack above zero or unknown. Labels depend only on the dealt-in count `n` and the preflop order.

| n | Preflop order, first to act on the left |
|---|---|
| 2 | BTN/SB, BB |
| 3 | BTN, SB, BB |
| 4 | CO, BTN, SB, BB |
| 5 | HJ, CO, BTN, SB, BB |
| 6 | LJ, HJ, CO, BTN, SB, BB |
| 7 | UTG, LJ, HJ, CO, BTN, SB, BB |
| 8 | UTG, UTG+1, LJ, HJ, CO, BTN, SB, BB |
| 9 | UTG, UTG+1, UTG+2, LJ, HJ, CO, BTN, SB, BB |

- This equals `binary.seat_name(n_behind, n)` for 3 to 9.
- `ranges.position_name` differs (`UTG(CO)`, `UTG(HJ)`, `UTG(LJ)` at 4 to 6 players, `UTG+2` for the second seat at 8) and `preflop.pos_to_index("UTG+1", 8)` returns 0. The adapter passes the order index (`n_behind = n - 1 - index`) and rewrites seat names in engine text; better, make `position_name` return this table.
- Order: dealt-in seats clockwise after the button; the first two are SB and BB and act last. Heads-up the button is the SB and acts first. After the flop: SB first, button last; heads-up the BB first.
- The button may sit on an empty seat; "BTN" is then the last player to act.

## 3. Session JSON

```json
{"version":1, "mode":"tournament",
 "rules": {"ante":"player", "short_post":"ante_first", "allin_or_fold":false, "cap_bb":null, "fee_bb":0},
 "tournament": {"name":"", "buyin":11, "entrants":500, "remaining":96, "paid":75, "payouts":null,
                "start_stack":10000, "avg_stack":null, "reentry_open":false, "multiplier":null, "history":[]},
 "config": {"goal":"itm", "pace":"online", "opponents":"unknown"},
 "structure": {"levels":[{"sb":100, "bb":200, "ante":25, "bb_ante":0, "minutes":6}], "index":0, "pending":null},
 "table": {"size":8, "button":1, "hero":5, "seats": {
   "1": {"name":"Carl", "stack":48000, "status":"active", "type":"lag", "notes":[], "as_of":41}}},
 "hand": {"no":42, "level":{"sb":100,"bb":200,"ante":25,"bb_ante":0},
   "button":1, "order":[4,5,6,1,2,3], "away":[],
   "start":{"4":10000}, "posts":{"4":{"ante":25,"blind":0}}, "dead":0,
   "hero_cards":"AhKd", "board":[], "shown":{},
   "events":[{"street":"preflop", "seat":4, "kind":"raise", "to":500, "allin":false, "auto":false, "forced":false}],
   "result":null, "synthetic":null},
 "hands":[], "journal":{"undo":[],"redo":[]}}
```

`as_of` is the hand at which the stack was last exact. `hands` keeps finished hands: pots, ranking, net per seat, busts. View phases: `idle`, `preflop`, `flop`, `turn`, `river`, `showdown` (betting closed, result wanted), `done`.

## 4. Hand state machine

**Posting.** A deal needs two dealt-in seats, a big blind and a button. Order: per-player antes (away seats too), BB ante, SB, BB. Each post is `min(amount, stack)`; a stack at zero is all-in. `short_post: "blind_first"` posts the big blind before its ante; the default matches `pushfold.HandSetup`. The BB ante goes to `dead`.

**Betting.** `in_front` is a seat's street total.

| Rule | Definition |
|---|---|
| Opening | Preflop `bet_to = bb` (the full big blind even if the BB posted less), `last_raise = bb`. Later streets `bet_to = 0`, minimum bet `bb` |
| To call | `owe = min(stack, bet_to - in_front, biggest total a live opponent can reach - in_front)`, at least 0 |
| Full raise | `to - bet_to >= last_raise`; then `last_raise = to - bet_to`. `min_raise_to = bet_to + last_raise` |
| Incomplete all-in | Above `bet_to`, short of a full raise: lifts `bet_to`, leaves `last_raise` |
| Right to raise | Not yet acted this street, or `bet_to` has risen by `last_raise` or more since his last action (one full raise, or short all-ins adding up); and an opponent with chips can call |
| Call for less | All-in at or under `bet_to`. An all-in nobody can call back is recorded as a call |
| Needs to act | Live with chips, and owes, or has not acted and may raise |
| Implied action | Check when free, otherwise fold: away seats, seats being cleared, seats skipped by `fold_to` |

**When nobody needs to act:**

1. Uncalled chips return: highest `in_front` minus the second highest (folded seats count).
2. One live player: `done`; he takes every pot, no intent needed.
3. Fewer than two live players with chips, or the river closed: `showdown`; only cards and `award` are accepted (the run-out).
4. Otherwise the next street.

**Pots.**

```
total[s] = ante[s] + live[s]                  # per-player ante counts, the BB ante does not
levels   = distinct totals of players not folded, ascending
pot[k]   = sum over ALL players of min(total, level[k]) - min(total, level[k-1])
eligible = not folded and total >= level[k]
pot[0] += dead; folded chips above the top level join the last pot;
pots with the same eligible players merge
```

A BB all-in for the ante only has `total = 0` and plays for the dead money alone. Invariant after every event: stacks + pots = chips at the deal (minus the All-In or Fold fee).

**Result.** One form: `award {ranking: [[seats], [seats]]}`, best hand first, ties in one tier. Each pot goes to the first tier with an eligible player, split equally, odd chips clockwise from the button's left. A contested pot that no tier resolves rejects the intent and names the pot. `award_auto` builds the ranking with `evaluator` when the cards are known.

## 5. Around the hand

| Situation | Rule |
|---|---|
| Sitting out | `away`: dealt in, posts, implied action at its turn |
| Seat cleared mid-hand | Chips stay in the pot, implied action, seat removed at `done` |
| Bust | At `done` a zero stack is removed and listed in `result.busted`; tournament `remaining` drops by one each. Hero busts: session over, or `seat_player` while re-entry is open |
| Button | `deal` moves it to the next dealt-in seat clockwise; `set_button`, `button_next`, `button_prev` correct it |
| Blinds | `level_up`, `level_down` move `structure.index`; past the list the ladder continues (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, then times ten), ante ratio kept. `set_level` edits the current entry |
| Edits during a hand | Before the first voluntary event, a change of level, button, hero or seats re-posts the hand. After it, a level waits in `structure.pending`; the others are rejected with "restart hand" |
| Unknown stack | `null`: no all-in is inferred; `allin` without `to` covers the biggest live opponent; the stack stays `null`. The adapter substitutes the average stack and names the seat in the advice |
| Stack typed mid-hand | The value is chips behind now; start = behind + posted + committed |
| Hand not recorded | `skip_hand`: seats that folded on record lose exactly what they put in; hero counts as folded unless told otherwise; seats still in keep their start stack, marked stale; the button moves |
| Joining mid-hand | `set_spot {street, pot, in, bets, to_act}`: a synthetic hand; stacks are chips behind now, the unexplained pot is dead money for everyone in |
| `undo`, `redo` | A snapshot before every accepted intent; a new intent clears `redo`. Restores busts, `remaining`, button, level. The session file is rewritten atomically each time |

## 6. Intents

Reply: the new view, or `{error: {code, message, fix}}` and no change. `skip_hand`, `set_spot`, `undo`, `redo`: section 5.

| Intent | Arguments | Validation |
|---|---|---|
| `new_session` | mode, size, start_stack, level, hero | defaults per mode (section 8) |
| `set_tournament` | remaining, paid, entrants, payouts, avg_stack, buyin, goal | integers from 0; warn when paid > entrants |
| `set_level`, `level_up`, `level_down` | sb, bb, ante, bb_ante | bb > 0, sb <= bb |
| `seat_player`, `clear_seat`, `move_seat`, `new_table`, `set_button`, `button_next`, `button_prev`, `set_hero` | seat, name, stack, type | seat within size; `new_table` keeps hero and tournament; mid-hand rule above |
| `set_stack`, `set_stacks`, `set_status`, `set_type`, `note` | seat, value | stack from 0 or null, never rejected for conservation; type from `ranges.PLAYER_TYPES` |
| `deal` | hero_cards | an open hand needs `award` or `skip_hand` first |
| `set_cards` | hero, board, shown | no duplicate card; a street's cards only once it is reached |
| `act` | seat, kind (fold, check, call, bet, raise, allin), to, force | seat is next to act; check only when nothing is owed; `to` above `bet_to`, within the stack, at least `min_raise_to` unless all-in or forced |
| `fold_to`, `close_round` | seat; callers | implied action for every seat before it; listed seats call, the rest take it |
| `edit_event` | index, kind, to | replays; events that become illegal are dropped and reported |
| `award`, `award_auto` | ranking | phase `showdown`; every contested pot resolved |

## 7. What the engine receives

Advice is requested only when hero is next to act, keyed by (hand, event count, cards, tournament fields); a stale answer is discarded.

| Case | Call | Inputs from the state |
|---|---|---|
| Tournament, preflop | `preflop.advise(Spot)` | `HandSetup(start stacks in order, sb, bb, ante, bb_ante)` with `antes`, `blinds`, `live` overwritten by the real posts; `acts = [Act(index, limp/call/raise/allin, in_front)]`, folds left out; `away`, `types`; prizes from `state.build_prizes` |
| After the flop | `advise_postflop(PostflopSpot)` | pot with the bet faced, `owe`, chips behind, `in_position`, `hero_pfr`; one `Villain` per live opponent, entry and line from the events |

## 8. Spin & Go and All-In or Fold

| | Spin & Go | All-In or Fold |
|---|---|---|
| Seats | 3, then heads-up | 4 (2 to 4 dealt in) |
| Ante | none (editable) | none |
| Prizes | always chip EV, never ICM | chip EV, `family="cash"` |
| Unit | chips | big blinds, step 0.1; blinds 0.5 / 1 |

- **Spin.** Ladder from `tools/spin_sim.py`: 10/20 to 1500/3000; 300 chips (x2, x3) or 500 (x4 up); levels of 1, 2, 2, 3 minutes, x10 every 10 hands; the clock only proposes `level_up`. Opponents limp and raise small, so the machine stays full hold'em and only the advice is all-in or fold: `spin.decide(hand, spot, eff_bb, vs)`, `spot` from `n`, hero's index and the events (`btn`, `bb_vs_sb_limp`...), else `advise` with goal `chips`. One stack holding every chip ends the game; games and wins are logged.
- **All-In or Fold.** `call` after an all-in means all-in; `raise`, `bet`, `check` are rejected. `fee_bb` (0.1) leaves the first pot of every hand, walks included. At `deal` a stack above `cap_bb` big blinds is cut to the cap, the excess added to `banked`. Advice: `aof.decide(hand, n, index, mask, stacks_bb, family)`, bit `k` of `mask` set when order index `k` is all-in.

## 9. Test cases

**Table A:** seats 1 to 6, 10,000 each, 100/200, no ante, button s1: LJ s4, HJ s5, CO s6, BTN s1, SB s2, BB s3. "X 500" = X makes it 500; "min" = minimum raise-to. Brackets change Table A.

Setup

1. Deal A: pot 300; LJ to act, to call 200, min raise to 400.
2. Seats 1, 2, 4, 5, button s2, `deal`: button s4; CO s2, SB s5, BB s1.
3. Heads-up s1 (button), s2, 50/100: s1 BTN/SB, to call 50, min 200. s1 calls, s2 checks: flop pot 200, s2 first.
4. Three seats, button s1, s2 busts, `deal`: s3 BTN/SB, s1 BB.
5. [ante 25]: pot 450; LJ 9,975, SB 9,875, BB 9,775.
6. [BB 120]: LJ to call 200, min 400. Folded to SB: to call 20, no raise.
7. [BB 120] LJ calls, rest fold: showdown, 80 back to LJ, pot 340. BB wins: BB 340, LJ 9,880.
8. [ante 25, HJ 20] LJ 500, BB calls, rest fold: main 120 (LJ, HJ, BB), side 1,125.
9. [BB ante 200, BB 300]: ante first: dead 200, BB live 100. Blind first: live 200, dead 100. Pot 400.
10. [BB ante 200, BB 150] folded to SB: no decision, 100 back to SB, showdown for 150.
11. [ante 25, BB 100] LJ calls, rest fold: 100 back to LJ; main 375, 50 for LJ alone. BB wins: BB 375, LJ 9,925.

Betting

12. LJ 500, folds to BB: pot 800, to call 300, min 800. BB folds: LJ 10,300.
13. LJ, BTN, SB call: BB to call 0, min 400. BB checks: flop pot 800, SB first.
14. LJ 500, HJ 1,300: CO to call 1,300, min 2,100; CO 2,000 rejected. CO 2,100: BTN min 2,900, pot 4,200.
15. [HJ 700] LJ 500, HJ all-in: CO to call 700, min 1,000. Folded to LJ: to call 200, raise rejected. LJ calls: showdown, pot 1,700.
16. As 15 but CO 1,000, rest fold: LJ to call 500, may raise, min 1,300.
17. [HJ 700, CO 850] LJ 500, HJ all-in, CO all-in, BTN calls, blinds fold: LJ to call 350, may raise (350 >= 300), min 1,150. LJ calls: main 3,100, side 450.
18. [LJ 300]: LJ 500, HJ fold out of turn, LJ check: all rejected. LJ all-in: HJ to call 300, min 500.
19. [LJ 150] LJ all-in, all fold: BB no decision, 50 back, pot 400.
20. LJ 500, BTN and BB call. Flop: BB checks, LJ 600, BTN calls: BB min 1,200 (1,000 rejected). BB 1,200, LJ folds, BTN calls: turn pot 4,600.

Pots and results

21. [BTN 3,000] LJ 500, BTN all-in, BB and LJ call: flop pot 9,100. BB checks, LJ 2,000, BB calls, checked down: main 9,100, side 4,000.
22. After 21, `[[BTN],[LJ]]`: BTN 9,100, LJ 9,000, BB 5,000. `[[BB]]`: BB 18,100, BTN busts.
23. After 21, `[[BTN]]`: rejected, side pot unresolved. `[[BTN,LJ],[BB]]`: BTN 4,550, LJ 13,550.
24. [BB 3,000] folded to SB, SB all-in: BB to call 2,800. Call: 7,000 back to SB, pot 6,000, showdown at once, `act` rejected. BB wins: BB 6,000, SB 7,000.
25. [LJ 1,000, HJ 2,500, CO 6,000] all three all-in, rest fold: 3,500 back to CO; main 3,300, side 3,000. `[[LJ],[HJ],[CO]]`: 3,300 / 3,000 / 3,500.
26. After 25, `[[CO]]`: CO 9,800, `remaining` 96 to 94. `[[LJ,HJ],[CO]]`: LJ 1,650, HJ 4,650.
27. Three seats, 25/50: BTN 125, BB calls, checked down, tie: pot 275, BB 138 (odd chip), BTN 137.
28. [SB 60] LJ 500, BB calls. Flop: BB checks, LJ 600, BB folds: 600 back; main 180, 880 for LJ alone. SB best: SB 180, LJ 10,380.
29. [LJ 2,000] LJ 500, BTN and BB call. Flop: BB checks, LJ all-in, both call: turn pot 6,100, BB to act. BB 1,000, BTN folds: 1,000 back, showdown.
30. [BB ante 200] BTN 450, blinds fold: BTN 10,500.
31. Property (fuzzed, 40,000 hands): random legal events keep stacks + pots constant and always leave a next actor, a showdown or `done`.

Edits

32. [BB away] BTN 400, SB folds: BB folds itself, BTN 10,300. Folded to SB, SB calls: BB checks itself, flop.
33. `clear_seat` CO after CO called 500: chips stay, CO folds at its turn, seat gone at `done`.
34. `level_up` before any event: re-posted. After LJ acts: pending, hand stays 100/200.
35. Undo after 26's `[[CO]]`: showdown, pots 3,300 / 3,000, `remaining` 96. Redo repeats it.
36. `edit_event` in 14, HJ to 900: CO's 2,100 stands. HJ to 1,900: CO's raise dropped and reported.
37. `skip_hand` after hero (CO) folded to LJ 500: hero and HJ exact; LJ, BTN, SB, BB stale; button s2.

Spin & Go

38. 300 each, 10/20: BTN all-in, SB folds, BB calls, BTN wins: BTN 610, BB busts, heads-up.
39. Heads-up s1 620, s2 280 (button), 15/30: s2 all-in, s1 calls and wins: s1 900, game logged.
40. As 38: BTN folds, SB calls, BB all-in: SB to call 280, folds: BB 320. BB's spot was `bb_vs_sb_limp`.
41. BTN 450, SB 150, BB 300, 20/40: BTN 80, SB all-in, BB all-in: BTN to call 220, no raise. Call: main 450, side 300. `[[SB],[BTN]]`: SB 450, BTN 450.

All-In or Fold (big blinds, fee 0.1)

42. Four at 8.0: pot 1.5; CO `raise 2.5` rejected. Walk: BB 8.4.
43. BTN all-in, all fold: BTN 9.4; at `deal` 8.0, banked 1.4.
44. [SB 5.5] CO, BTN, SB all-in, BB folds: main 17.5, side 5.0. `[[SB],[BTN]]`: SB 17.4, BTN 5.0.
45. [SB 5.5] SB all-in, BB all-in: a call of 4.5; pot 11.0; SB wins: SB 10.9, BB 2.5.
