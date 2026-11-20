# Engine map: preflop decisions (`poker_coach`)

Every example below was run against the repository; outputs are verbatim, trimmed. Example table: 8 players, blinds 500/1000, big-blind ante 1000, stacks in action order `[30000, 22000, 41000, 18000, 26000, 12000, 35000, 20000]`.

## 1. The model

- **Index, not seat.** Players are indexed in preflop action order: `0` acts first, `n-2` is SB, `n-1` is BB (heads-up: `0` = SB/button, `1` = BB). `n_behind = n-1-index`: 0 BB, 1 SB, 2 BTN, 3 CO, 4 HJ, 5 LJ.
- **Units.** `HandSetup` and `Act` accept chips or big blinds, provided stacks, blinds and amounts share one unit (same answer both ways, checked). `binary.*` is always big blinds. Advice text is always in bb.

```python
HandSetup(stacks, sb, bb, ante=0.0, bb_ante=0.0)   # pushfold.py; start-of-hand stacks, n >= 2
#   .n .start .antes .blinds .live (= start - ante)
Act(idx, kind, amount)   # kind: limp | call | raise | allin ("fold" is ignored)
                         # amount = TOTAL chips in front after acting ("raise to")
Spot(setup, hero, hand, cards=None, names=[], types=[], away=[], prizes=Prizes(),
     field_prizes=Prizes(), acts=[], stage={}, desperate=False, notes=[])
advise(spot) -> Advice   # preflop.py
```

`hand` is a class index 0-168: `cards.parse_hand("AhKd") -> (13, (50, 45))`, `parse_hand("AKo") -> (13, None)`; `"AKx"` raises `ValueError`. `cards` matter only against two all-ins. `types` and `away` are lists by index. `stage` is read only for `stage["label"]`. `notes` end up in `warnings`.

## 2. Building a Spot from a tracked table

What `cli._state_spot` does. These functions work on a plain dict; only `S.load` / `S.save` touch `tournament/current.json`.

```python
from poker_coach import state as S
st = S.blank_state()
S.set_seat(st, seat_no, name, stack, status, ptype)   # status "away" = sitting out
st["table"].update(hero=5, button=6)
st["level"].update(sb=500, bb=1000, ante=0, bb_ante=1000)
st["tournament"].update(entrants=500, paid=75, remaining=96, start_stack=10000)
setup, order = S.hand_setup(st)                  # order[i] = seat number at index i
hero = order.index(5)
prizes = S.build_prizes(st, goal)                # "itm" | "balanced" | "chips"
field = Prizes(prizes.raw_payouts, prizes.field_n, prizes.field_stack) \
        if not prizes.chip_ev else Prizes()      # what opponents play for
spot = Spot(setup=setup, hero=hero, hand=h, cards=c, names=..., types=..., away=...,
            prizes=prizes, field_prizes=field, stage=S.stage(st), desperate=d, acts=acts)
```

`desperate` is set by the CLI, not the engine: fold-clock verdict `"short"` with 6bb or less, or 3bb or less while more than 3 places from the money (or the distance is unknown). It switches the solver to chip EV. `S.fold_clock` has no verdict until `S.record_remaining` has seen players-left fall over time.

Actions before hero (hero is index 4, CO 26bb, unless another seat is named):

| Situation | `acts` | Ran: hand, seat -> `action [confidence]` |
|---|---|---|
| Folded to hero | `[]` | AJo CO -> `RAISE to 2.2bb [clear]`; A8o BTN 12bb -> `ALL-IN [clear]` |
| Limper(s) | `[Act(1,"limp",1000)]` | 77 BTN 12bb -> `ALL-IN`; AQs CO, two limpers -> `RAISE to 5bb` |
| Raise | `[Act(1,"raise",2200)]` | 99 CO -> `ALL-IN [standard]` |
| Raise and call | `[Act(1,"raise",2200), Act(3,"call",2200)]` | AQs BTN -> `ALL-IN [clear]` |
| All-in | `[Act(5,"allin",setup.live[5])]` | KTs BB -> `CALL [clear]` |
| Raise and re-raise | `[Act(0,"raise",2200), Act(2,"raise",6600)]` | QQ BTN -> `ALL-IN [clear]` |
| Raise and all-in | `[Act(0,"raise",2200), Act(3,"allin",18000)]` | JJ SB -> `RE-RAISE ALL-IN (isolate)` |
| Two all-ins | `[Act(3,"allin",18000), Act(5,"allin",12000)]` | TT SB -> `CALL [standard]`, warning "side pots are approximated" |
| Hero raised, re-raised | `[Act(4,"raise",2200), Act(7,"raise",6600)]` | AQs -> `ALL-IN [standard]` |
| Hero raised, all-in | `[Act(4,"raise",2200), Act(5,"allin",12000)]` | JJ -> `CALL [clear]` |
| Hero raised, only called | `[Act(4,"raise",2200), Act(5,"call",2200)]` | `WAIT` |
| Hero is BB, all folded | `[]` | `CHECK / take the walk` |

Router rules:

- List acts in true order, **including hero's own earlier raise**; leave folds out. A later-acting player listed before hero has acted is still answered, with the warning "BB acts after you preflop but is listed as acting before you".
- An all-in amount is `setup.live[i]` (stack minus ante). A raise to the whole stack is promoted to all-in; a raise of 40% or more of the raiser's stack is answered as one (`ALL-IN` replaces `CALL`). A short all-in below the current bet counts as a caller.
- `preflop.parse_actions("UTG raise 2200, HJ call", setup, hero, resolve, chips=True)` returns `[(0,'raise',2200.0), (3,'call',2200.0)]`; a raise without an amount becomes 2.2bb, then 3x.

## 3. `Advice`

`dataclasses.asdict(adv)` is JSON-ready.

| Field | Meaning |
|---|---|
| `action` | Seen: `FOLD`, `CHECK`, `CHECK / take the walk`, `CALL`, `CALL (limp behind)`, `ALL-IN`, `RAISE to 2.2bb`, `RAISE to 2.0bb and call any all-in`, `RAISE to 5bb`, `3-BET to 6.9bb`, `3-BET to 6.9bb (semi-bluff, fold to a 4-bet)`, `3-BET to 14bb (puts the opener all-in)`, `4-BET to 21bb`, `RE-RAISE ALL-IN (isolate)`, `RE-RAISE to 38bb (isolate)`, `WAIT`. Classify by prefix. |
| `confidence` | `clear`, `standard` or `close` |
| `situation` | `"AJo in CO with 26.0bb, folded to you | NEAR THE BUBBLE (21 from the money)"` |
| `why`, `numbers`, `alt`, `warnings` | Lists of sentences: reasons, the maths, acceptable alternatives, cautions |
| `data` | Floats, by route: first in up to 20bb `shove_ev_bb, shove_pct`; a raise with 25bb or less `reshove_ev_bb`; one all-in `equity, need, villain_pct, breakeven_pct`; otherwise `{}` |

## 4. What decides each route

Stacks are effective, in bb.

- **First in.** Up to 10bb: solver, `ALL-IN` when shove EV > 0. 10 to 16bb (20 in the SB or heads-up): QQ+/AK raise and call, otherwise `ALL-IN` when EV > 0.05bb. Deeper: the opening ladder `ranges.rfi_range`, shifted by ICM and reads. Everyone behind away: raise any two.
- **Limpers.** Up to 16bb: `ALL-IN` when EV > 0.15bb, else `FOLD` (`CHECK` in the BB). Deeper: raise 3bb + 1 per limper (4bb + 1 from the blinds), limp behind with 25bb+, else fold or check.
- **A raise.** Up to 25bb: re-shove when EV > 0.15bb; the BB may `CALL` (close). Deeper: chart 3-bet, call, fold.
- **All-in.** Equity against the modelled range versus pot odds plus ICM; `numbers` includes "calling is right whenever they shove at least ~26% of hands".
- **Raise and re-raise.** KK+ always, JJ+/AK when the shove earns over 0.5bb.
- **Hero re-raised.** Up to 45bb all-in or fold; deeper 4-bet, call, fold.

## 5. Goal and player types

`S.build_prizes` returns chip EV unless `remaining` and one of `payouts`, `paid`, `entrants` are set (players left plus places paid is enough; payouts are then estimated). `itm` adds the minimum cash to every prize until the bubble bursts; `balanced` is plain ICM; `chips` is chip EV.

| Spot (500 entrants, 75 paid) | itm | balanced | chips |
|---|---|---|---|
| A9o first in, CO 26bb, 300 left | FOLD | RAISE to 2.2bb | RAISE to 2.2bb |
| same, 96 left | FOLD | FOLD | RAISE |
| same, 60 left (in the money) | RAISE | RAISE | RAISE |
| BB A9o against a 12bb button all-in, 78 left: equity needed | 53% | 50% | 43% |

Types: `unknown nit tight tag lag loose station maniac` (`ranges.PLAYER_TYPES`; aliases fish, reg, rock, whale; anything else silently becomes `unknown`). Measured: a 12bb button all-in is modelled as 24% of hands (nit), 36% (unknown), 40% (tag), 50% (lag), 63% (maniac); an early opener as 11% (nit) to 20% (maniac). Both blinds nit or tight: open one notch wider. A lag or maniac with 8 to 25bb behind: one notch tighter (K8s in the CO goes from RAISE to FOLD).

## 6. `binary.decide` (all-in or fold tables)

```python
binary.decide(hand, n_behind, stack_bb, stage="before", facing="", facing_seat=None,
              allin_bb=None, bubble=False, players=8) -> (action, reason)
```

| Situation | Call | Ran |
|---|---|---|
| First in | `decide(h, 2, 12)` | `('ALL-IN', 'A8o from BTN is an all-in up to 21bb before the money')` |
| In the money | `stage="money"` | KTs CO 14bb -> ALL-IN, "up to 24bb in the money" |
| Close to the money | pass twice the stack | A8o BTN, `24` -> FOLD |
| BB, no raise | `decide(h, 0, 12)` | `CHECK` |
| A limper | the seat before: `decide(h, n_behind+1, stack)`; BB passes 1 and reads FOLD as CHECK | equals `tag.table(8)["limpers"]` (checked) |
| A raise | `facing="raise", facing_seat=3` | 99 BTN 15bb -> `('ALL-IN', 'over a raise from CO with 12 to 16bb: 66+, ATs+, AJo+')` |
| An all-in | `facing="allin", facing_seat=4, allin_bb=9` | AJo BB -> CALL "44+, A3s+, KTs+, A7o+, KJo+"; on the button "66+, A9s+, ATo+" |
| Bubble call | add `bubble=True` | "88+, ATs+, AJo+" |
| Two all-ins, or a raise and an all-in | `facing="allins"` (no seat; `allin_bb` = the bigger) | TT 10bb -> CALL; with `bubble=True` -> FOLD "KK+" |
| Six or seven players | `players=6` | A9o LJ 10bb -> ALL-IN |

`stack_bb` is the smaller of hero's stack and the biggest stack still to act. No goal, no player types, no other stacks.

## 7. The chart behind an answer

A range is 169 weights; cell `row*13+col` over `cards.GRID = "AKQJT98765432"`, suited above the diagonal, offsuit below; `cards.HANDS[i]` names it.

| Want | Helper |
|---|---|
| Text to weights and back, share | `cards.parse_range`, `format_range`, `range_pct` |
| ASCII 13x13 | `cli._grid(weights)`; `binary.grid_text(stage, n_behind, players)` (deepest all-in stack per hand) |
| Opening range | `ranges.rfi_range(n_behind, eff_bb, shift)`; shift = `preflop._chart_shift(spot, behind)[0]` |
| Solver all-in range | `pushfold.solve_open_shove(setup, hero, prizes, caller_prizes=, types=, away=)` -> `.shove_range`, `.ev_bb(hand)`, `.callers[k].call_range` (ran: 39.7%, A8o +1.57bb) |
| Chip-EV reference | `pushfold.nash_push_range(n_behind, stack_bb, has_ante)`, `push_limit_bb` |
| All-in or fold | `binary.first_in_range(stage, n_behind, stack_bb, players)`, `limits(...)`; as text `reshove(stage, raiser_kind(nb), stack_bb, players)`, `call(shover_kind(nb), allin_bb, bubble, big_blind, players)` |
| Whole sheet | `tag.table(players)`: `first_in, limpers, vs_raise, reshove, bb_call, cold, reraised, shoved_on, call` |
| Opponent's range in an answer | Only inside `numbers`: `re.search(r"\[(.+?)\]", line)`, then `parse_range` (round trip checked) |

## Gotchas

1. **Two naming schemes.** At 8 players `ranges.position_name` (all Advice text, `S.positions`) says `UTG, UTG+2, LJ...`; `binary.seat_name` says `UTG, UTG+1, LJ...`. At 6 the engine prints `UTG(LJ)`, heads-up `SB/BTN`. `pos_to_index("UTG+1", 8)` returns 0, so `python -m poker_coach binary --pos UTG+1 --players 8` answers for UTG (ran: FOLD A9s 10bb, while `decide(h, 6, 10)` says ALL-IN). Label seats with `binary.seat_name(n_behind, n)` (works for 2 to 9), pass indices, never names, and rewrite the engine's labels in displayed text.
2. **`binary.decide` knows only `""`, `"raise"`, `"allin"`, `"allins"`.** Any other string, such as `"limp"`, is silently answered as a call of an all-in.
3. **`binary` and `tag` exist for 6, 7 and 8 players** (`ValueError` otherwise). Five or fewer: `players=6` with the real `n_behind`. Tables cover 2 to 40bb, deeper is AA, KK only; a stack is in range up to limit + 0.5. `stage="bubble"` is an alias of `before`; only `bubble=True` changes anything, and only for calls.
4. **`advise` on chip EV is far wider than `binary`.** Equal 12bb stacks, CO: QTs, JTs, 22, A2o are ALL-IN for `advise`, FOLD for `binary`. House rule: before the money follow `binary`; in the money or when desperate follow `advise`.
5. **`build_prizes` ignores `tournament.avg_stack`** unless `total_chips` (or entrants x start stack) is set; otherwise the field gets the table's average.
6. `itm` tightens even early (6% risk premium with 300 of 500 left).
7. Hero's own limp is not priced; over-calls are ignored; two all-ins are approximate; no straddles. Drop seats without chips before building `HandSetup`.
8. Timing: 0 to 400 ms per `advise` (9 players with ICM, first in at 18bb: 360 ms), deterministic; `binary.decide` under 1 ms.
9. Preflop only. Spin and All-In or Fold have their own modules (`spin.py`, `aof.py`).
