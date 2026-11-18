# Advice adapter and learning panel (lens: decision quality)

Every number here comes from running the repository's engine in memory; no repository file was changed. The scratch router behind the acceptance rows: `proto.py` and `accept.py`, beside this file.

## 1. Five decisions

1. **Default style "Survive, then win".** The prize model is plain ICM (`balanced`), not `itm`. Survival comes from a guard: before the money, a play that risks the stack needs the all-in or fold table to agree. From the money on, the engine decides alone.
2. **Tables answer all-in questions, the engine the rest.** Tournament has two plans; Spin uses the solved tables to 16bb and the chip-EV engine above; All-In or Fold uses `aof` only.
3. **Actions reach the engine by seat index, never by seat name.** The engine's own naming is wrong at 8 players (section 10).
4. **After the flop every input is exact**: pot, bet, chips behind, each opponent's role and line come from the action record.
5. **Advice never blocks on missing inputs.** It answers and names what it assumed.

## 2. Adapter shape

`poker_coach/app/advice.py`, pure functions, no I/O:

- `advise_table(table, hand_record, style) -> dict`: the headline. Measured: 0.05 to 0.3s before the flop (worst 0.7s), 0.11s after it at 20,000 iterations.
- `chart_for(table, hand_record) -> dict`: the range chart, fetched separately.

`to_engine_state(table)` builds the dict `state.py` expects, so `stage()`, `fold_clock()`, `build_prizes()` and `hand_setup()` are reused unchanged.

- Stacks are start-of-hand stacks. An action is `Act(index in acting order, kind, total chips in front)`.
- Sitting-out seats are `away`; when hero acts a second time, so are seats behind that folded.
- "Folded to you" is computed as soon as the cards are in; answers for an old table version are dropped.

## 3. Which function answers what

**Tournament, Full plan (default)**

| Before hero acts | Engine call | By depth |
|---|---|---|
| Nobody entered | `advise` → `first_in` | 10bb or less: solver shove or fold with ICM. To 16bb (20bb small blind, heads-up): shove, or QQ+/AK raise and call. Deeper: opening chart moved by ICM and reads, with "if X shoves" lines to 40bb |
| Callers only | `vs_limp` | raise, call along, all-in |
| One raise | `vs_open` | 25bb or less: re-shove solver (needs +0.15bb) or a big-blind call. Deeper: 3-bet, call, fold charts |
| All-in; raise and all-in; two all-ins | `vs_shove`, `multi_allin` | equity against the modelled range versus price plus ICM |
| Raise and re-raise | `cold_vs_3bet` | |
| Hero raised, then re-raise or all-in | `vs_3bet`, `vs_shove(hero_open)` | 45bb or less: all-in or fold |
| Hero called, then a raise | sheet rule, not the engine | fold; a pair with 15 raises behind may call |
| After the flop | `advise_postflop` | section 7 |

**Tournament, All-in or fold plan**

| Situation | Call |
|---|---|
| Any preflop spot | `binary.decide`, table for 8, 7 or 6 players (fewer: the 6 table by players behind; 9: the 8 table, flagged) |
| Callers in front | range of the seat before; big blind: the small blind's range, else CHECK |
| Stage | over 2 players left per paid place (1.5 at regular speed): `before`. Down to 1.3 (1.2): stack doubled. Below: `latereg.zone` picks sit out, aces only, tight or wide chart. In the money: `money`; at a final table the bubble call table when the shover covers hero |
| Free flop in the big blind | playbook rule on `evaluator.describe`: all-in with top pair or better, or 12 outs, at 4 pots or less |
| Second line, always | `advise` on the real stacks and prizes (over 20bb it shows the Full plan's raise) |

**Spin & Go** (chips are money: `Prizes()`, no ICM, no guard)

| Situation | Call |
|---|---|
| First in, 16bb or less (20bb small blind, heads-up) | `spin.decide`: the exact solution, to the depth where the engine itself stops being push or fold |
| First in, deeper | `advise` on chip EV: small raise. Table shown as "all-in instead: +0.01bb" |
| Facing all-ins | `spin.decide` call rows at every depth |
| Limp or small raise in front | the raise rows; above 16bb a big blind may CALL when the chip-EV engine says so |
| No row (button limp, raise and call, hero raised and met an all-in) | `advise` on chip EV, flagged |
| Loose tables | `--vs loose` only when every player left to act is loose |

**All-In or Fold**: `aof.decide(hand, n, hero, mask, stacks, family)`, 2 to 4 seated players, stacks capped at 8bb, `cash` family, loose families as in Spin. The answer reads CALL when somebody has shoved; a big blind with no shove gets "walk".

## 4. Aim to win: prize model and survival guard

Engine output, 8 players, 1,000 entrants, 150 paid:

| Spot | Goal | 800 left | 260 | 185 | 152 (bubble) | 100 (money) |
|---|---|---|---|---|---|---|
| A8o BTN 12bb first in: shove EV in bb | itm | +1.32 | +0.81 | +0.44 | 0.00 FOLD | +0.96 |
| | balanced | +1.38 | +0.95 | +0.66 | +0.20 | +0.96 |
| | chips | +1.57 | +1.57 | +1.57 | +1.57 | +1.57 |
| AJo BB 18bb, BTN (25bb) all-in: equity needed (hero has 58%) | itm | 47% | 53% | 59% FOLD | 66% FOLD | 51% |
| | balanced | 47% | 51% | 55% | 60% FOLD | 51% |
| | chips | 45% | 45% | 45% | 45% | 45% |
| BTN 10bb: % of hands shoved | itm / balanced / chips | 42 / 42 / 44 | 35 / 37 / 44 | 32 / 34 / 44 | 20 / 27 / 44 | 36 / 36 / 44 |

- `chips` never brakes: it calls AJo on the bubble at 45% where the prizes ask for 60%.
- `itm` and `balanced` are identical after the bubble and within 0.1bb early. In six spots their answers differed only at 185 and 152 left, where `itm` counts the smallest prize twice; about 70% of a pool sits above that prize (playbook).
- So **`balanced` is the goal for a player who aims to win**: it charges exactly what a bust costs. `itm` stays one click away.

**Survival guard**, a second opinion instead of a distorted prize table. Tournament, Full plan, before the money, when the engine's answer puts a third or more of hero's stack in preflop (first-in all-in, all-in over a raise, call of an all-in): the same spot is read in `binary` (stage rules of section 3). Table agrees: the engine's answer stands. Table folds: the headline is FOLD, tagged SURVIVAL FOLD, with the engine's answer and EV as the second line.

Lifted when: in the money or at the final table; the engine's `desperate` flag (3bb or less, or 6bb with the fold clock short); near the bubble with the fold clock on CANNOT; the opponent the play depends on carries a read; re-entry open; style Max EV.

Cost on six first-in spots (8 to 15bb): the guard removes 8 to 13% of hands (25% from the small blind), valued by the solver at a median +0.11 to +0.22bb each; 0 to 2% of hands (6% in the small blind) are worth +0.35bb or more. The table's range sat inside the engine's but for one hand. Cheap insurance against callers wider than a solver's, and it still works when tournament numbers are missing or stale; no goal setting does.

| Style | Prize model | Guard |
|---|---|---|
| Cash first | `itm` | on |
| **Survive, then win** (default) | `balanced` | on before the money |
| Max EV | `balanced` | off |
| automatic: re-entry open, Spin | `chips` | off |

| Stage | Players left per paid place | What decides |
|---|---|---|
| Early, middle | over 2 | ICM (close to chips), guard with the `before` table |
| Approaching | 2 to 1.3 | ICM; guard reads the column for twice the stack |
| Bubble | under 1.3 | ICM; bubble call table; fold clock and sit-out line |
| In the money | 1 or less | engine alone |
| Final table | | engine alone on exact ICM; warns when it calls a covering stack the bubble table folds |

## 5. ICM inputs

| Level shown | Needs | What the engine uses |
|---|---|---|
| ICM OFF | no players left, or neither places paid nor entrants | chip EV, stage unknown |
| ICM ESTIMATED | players left and places paid (entrants alone: 15% paid assumed) | typical top-heavy payouts; field stack = table average |
| ICM | plus average stack, or entrants and starting stack | real field stack |
| ICM EXACT | plus the smallest prize and the final-table prizes | the real ladder |

The same shove (A8o BTN 12bb, 185 left) is +1.57bb with ICM off, +0.69 with players left and paid, +0.88 once a 40bb average is entered. With inputs missing the panel still answers and puts the missing field inline; the guard treats the hand as before the money. Players left carries its age: a warning after 10 hands, after 3 on the bubble. The fold clock needs two updates of players left a minute apart; until then it shows orbits and minutes of blinds, plus the share of the sit-out line (`latereg.zone`) when the average stack is known.

## 6. Opponent types and notes

A table-wide default (unknown, loose, tight) fills untagged seats; a seat tag overrides it.

| Type field | Moves |
|---|---|
| `open_shift` | the opening range hero faces, and which 3-bet chart applies |
| `shove_mult` | width of the all-in range hero calls against (nit 0.6, maniac 1.6) |
| `call_adj`, `icm_aware` | who calls hero's all-in in the solver |
| postflop `bluff_mult`, `call_shift` | how a bet or call narrows their range |
| tight blinds / an aggressive 8 to 25bb stack behind | hero opens a notch wider / tighter |

A read on the player a decision depends on lifts the guard. Notes are text, shown on the seat and in the panel when that player is in the hand. The app may suggest a tag after 15 recorded hands; it never tags by itself.

## 7. After the flop: roles and lines from the record

| Recorded before the flop | Role and range |
|---|---|
| First raise | `villain_open_range(players behind, type)` |
| Re-raise | `threebet_range(opener's seat, type)`; a further re-raise: the same with type nit |
| Called a raise | call, set-mine and deep rows of `vs_open_chart` plus a quarter of the value hands; wider for loose types |
| Limped or completed | `villain_limp_range` |
| Big blind checked | any two cards |
| Raised, then called a re-raise | stays an opener |
| Nothing recorded | caller, with a warning |

- **Line**: per opponent and street, the strongest action (check, call, bet, raise, shove), sized as chips put in over the pot before it. The current street is included, so the engine does not add it again.
- `villains[0]` is the player whose bet hero faces, else the last aggressor, else the biggest stack. `facing` is "raise" when hero had bet this street, "shove" when the bettor has nothing behind.
- `hero_pfr`: hero made the last preflop raise. `in_position`: hero acts last among those left.
- `pot`, `to_call`, `hero_stack`, `villain_stack`: from the ledger. `risk_premium`: `prizes.risk_premium` on the start stacks; 0 in Spin.
- **Playbook check**, the only override: one pair facing a river bet of 60% of the pot or more, or a turn or river raise, from a player tagged nit, tight, loose or station, is FOLD unless under 1.5 pots are behind. The engine calls there (row P3).

## 8. Warnings

| Code | When | Text |
|---|---|---|
| `icm_off`, `icm_estimated` | section 5 | "ICM off: chip EV. Enter players left and places paid" |
| `left_stale` | age rule of section 5 | "Players left is 12 hands old" |
| `close` | engine says close | both sides with the margin; before the money the lower-variance side leads |
| `outside_tables` | no row, 9 players, over 40bb in the all-in plan, unequal stacks in Spin or All-In or Fold | "Answered for the effective stack" |
| `reentry_open` | toggle | "Re-entry open: chip EV, guard off" |
| `blinds_up` | 3 hands or fewer to the next level, under 20bb | second run at the next level: "After the rise: ALL-IN" |
| `bounty` | toggle | "Bounties are not priced" |

The engine's own warnings pass through. Two show; the rest fold into a count.

## 9. What the panel shows

1. **ACTION and size** (bb and chips), with CLEAR, STANDARD or CLOSE.
2. One sentence of reason, seats in the app's naming.
3. **Key number** and **what flips it**: shove EV and "all-in up to 21bb from this seat"; "need 53%, have 60%: a call whenever they shove 12% or more, modelled 26%; FOLD against a nit".
4. Source line: prize level, then AGREES, SURVIVAL FOLD (engine: ALL-IN +0.15bb) or GUARD OFF.
5. Plan lines under a raise ("if BB (28bb) shoves: FOLD"), then warnings.

Opened on demand:

| Route | Chart, hero's hand ringed | Number in the cell |
|---|---|---|
| Solver shove, re-shove | hands with positive EV | EV in bb |
| Opening and 3-bet charts | raise, call, 3-bet, fold | none |
| Facing an all-in | hands whose equity beats the need | equity |
| `binary` | first-in range for seat and stack | deepest stack that moves in |
| `spin`, `aof` | the row's range; close hands outlined | bb against folding |

A second tab shows the range hero is up against. Below: the stage (`STAGE_PLAN`), the gear for the stack (`tag.GEARS`), the fold clock (orbits, minutes, bubble estimate, verdict), the sit-out line share, the stack in bb at the next level.

## 10. Engine traps the adapter must handle

- **Seat names.** `ranges.position_name` calls the second seat of 8 "UTG+2" (`binary` and the sheet say "UTG+1"), and `pos_to_index("UTG+1", 8)` returns seat 0. Label seats with `binary.seat_name`, pass indexes, rename engine text before display.
- **Heads-up, 10 to 20bb**: the engine only shoves or folds (K5o on the button, 18bb: FOLD; 22bb: RAISE to 2bb). Warn, or let the heads-up raise chart apply from 10bb.
- **Big blind behind callers**, all-in plan: `binary.decide` returns CHECK before reading any range.
- **Bubble charts are slow cold**: `latereg.reference_charts` took 1.6s for 8 players, 19s for 7, 14s for 6. Warm it in a background thread; until then use the doubled-stack column.
- **Hero opened, a caller, then an all-in**: the engine ignores the caller still behind. Flag it.

## 11. Acceptance spots

Tournament rows: 8 players in acting order UTG to BB, blinds 500/1,000, ante 125 each, 1,000 entrants, 150 paid, goal `balanced`, opponents unknown, folded to hero unless an action is listed. Stacks in bb: A = 30/25/18/40/22/12/15/20, B = 30/25/18/40/14/22/16/28.

| # | Spot | Engine answer (run) | Headline |
|---|---|---|---|
| T1 | QJs BTN 35bb, 400 left (30/25/18/40/15/35/16/28) | RAISE to 2.2bb [clear]; "if BB (28bb) shoves: FOLD" | RAISE to 2.2bb |
| T2 | A8o BTN 12bb, 400 left (A) | ALL-IN [clear] +1.20bb; table ALL-IN (to 21bb) | ALL-IN |
| T3 | K9s CO 14bb, 400 left (B) | ALL-IN [standard] +0.15bb; table FOLD | FOLD, survival |
| T4 | QQ CO 14bb, 400 left (B) | RAISE to 2.0bb and call any all-in [clear] | same |
| T5 | A8o BTN 12bb, 152 left (A) | balanced ALL-IN +0.20 [standard]; itm FOLD 0.00 [close]; table FOLD | FOLD, survival; Max EV: ALL-IN |
| T6 | A5o BTN 12bb, 260 left (A) | ALL-IN [clear] +0.55bb; table at 24bb FOLD (all-in to 15bb) | FOLD, survival |
| T7 | TT HJ 22bb vs UTG raise 2.2bb, 400 left (35/25/18/22/15/25/16/18) | FOLD [close], re-shove +0.05bb; table ALL-IN; 800 left: ALL-IN +0.38 | FOLD (close) |
| T8 | K9o BB 20bb vs BTN raise 2bb, 400 left (30/25/18/40/22/25/15/20) | CALL [close], re-shove -0.44bb | CALL |
| T9 | 99 BB 20bb vs CO all-in 15bb (30/25/18/40/15/22/16/20): 400 left; 152 left; 152 left, CO tagged maniac | CALL [clear] 60% vs 47%, table CALL; CALL [clear] 60% vs 53%, table FOLD (TT+, AQs+, AKo); CALL [clear] 64% vs 53% | CALL; FOLD, survival; CALL (read) |
| T10 | AJo BB 18bb vs BTN all-in 25bb (30/25/18/40/15/25/16/18), 152 left, then 100 | FOLD [close] 58% vs 60%; CALL [clear] 58% vs 51% | FOLD; CALL |
| T11 | JJ BTN 20bb, HJ raise 2.2, CO all-in 14bb, 400 left (30/25/18/40/14/20/16/18) | RE-RAISE ALL-IN (isolate) [clear] 61% vs 50%; table CALL | RE-RAISE ALL-IN |
| T12 | QQ BTN, UTG raise 2.3, HJ re-raise 7, all 50bb, 800 left | FOLD [clear], 45% vs JJ+, AQs+, AKo | FOLD |
| T13 | TT BTN 12bb, HJ all-in 40, CO all-in 22, 185 left (A) | CALL [clear] 39% vs 28%; table FOLD | FOLD, survival |
| T14 | A9s SB 15bb, BB 40bb, 8 left (A with BB 40) | ALL-IN [clear] +1.83bb | ALL-IN, guard off |
| T15 | Q7o UTG 2.5bb, 400 left (A with UTG 2.5) | ALL-IN [clear] +1.31bb, desperation mode | ALL-IN |
| T16 | K5o button heads-up, 18bb vs 30bb, 2 left | FOLD [standard] -0.13bb | FOLD, heads-up warning |
| B1 | All-in plan: 99 BTN 15bb vs CO raise | ALL-IN: 66+, ATs+, AJo+ | ALL-IN |
| B2 | All-in plan: TT BTN 10bb, two all-ins | CALL: TT+, AKs, AKo | CALL |
| B3 | All-in plan: J9s, then T7o, BB 15bb, BTN limps | small blind's 15bb range holds J9s, not T7o | ALL-IN; CHECK |
| B4 | All-in plan: A9o, then K9s, BTN 8bb, 165 left, average 30bb | zone short (31% of the line); tight chart 55+, A6s+, KJs+, A8o+, KQo | ALL-IN; FOLD |
| P1 | AhKd on Ks7d2c; hero raised CO, BB called and checked; pot 5.6bb, 27.5bb behind | BET 1.8bb (33% pot) [standard], equity 91% | same |
| P2 | QhJh on Th9h2c; BB vs BTN opener's bet 1.9bb into 5.6bb, 22bb behind | RAISE ALL-IN (semi-bluff) [standard], equity 64% | same |
| P3 | AsTd on Tc7h4s2dKh; station called twice, bets 12bb into 18bb | CALL [clear] 55% vs 35% | FOLD, playbook check |
| P4 | AhQd on Qs8d3c; CO opener shoves 14bb into 10bb, risk premium 15% | CALL [close] 60% vs 58% | CALL (close) |
| S1 | Spin: K7s BTN 12bb | ALL-IN, +0.05bb | ALL-IN |
| S2 | Spin: A5o BB 9bb, BTN all-in | CALL, +0.66bb | CALL |
| S3 | Spin: T5s SB 10bb, solid then loose | ALL-IN +0.07bb; FOLD -0.37bb | ALL-IN; FOLD |
| S4 | Spin: K7s BTN 25bb | table FOLD (+0.01bb); engine on chips RAISE to 2.2bb | RAISE to 2.2bb |
| A1 | AoF: A5s BTN, CO all-in, 8bb each | FOLD [clear] -0.28bb | FOLD |
| A2 | AoF: Q4o SB 8bb, BB 5.5bb | ALL-IN [standard] +0.12bb at 5.5bb effective | ALL-IN, approximation note |
| A3 | AoF: JTs BB, SB all-in | ALL-IN [clear] +0.89bb | CALL |
