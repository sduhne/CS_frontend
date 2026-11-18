# Engine map: advice after the flop

Source: `poker_coach/postflop.py`, `equity.py`, `evaluator.py`, `cards.py`; adapters: `cli._postflop_from_args`, `live/decide._postflop`. Every example and number was run here (Python 3.13, Linux, 4 cores).

## 1. Encodings and helpers

```python
from poker_coach.cards import parse_cards, parse_hand, cards_str, class_of, HANDS, format_range, range_pct
from poker_coach.ranges import parse, norm_type
from poker_coach.postflop import PostflopSpot, Villain, range_from_spec, parse_line, advise_postflop
from poker_coach.evaluator import describe, board_texture
from poker_coach.equity import hand_equity
```

- Card: int `rank*4 + suit`, ranks `23456789TJQKA`, suits `cdhs`. `parse_cards("AhKd") -> [50, 45]`; also takes `"Ah Kd"`, `"10s"`, `"K♦"`. Raises `ValueError` on a bad card or a duplicate inside the same string.
- `parse_hand("AhKd") -> (13, (50, 45))`, `parse_hand("AKo") -> (13, None)`. After the flop the two exact cards are required.
- Range: 169 weights 0..1 on the `HANDS` grid (`HANDS[0]=="AA"`, `[1]=="AKs"`, `[13]=="AKo"`). `parse("77+, AJs+, KQs")`, `format_range(w)`, `range_pct(w)` (4.8 for that range).
- `describe(hole, board) -> {made, category, strength 0..9, draws, outs, flags, texture}`; `texture = {wet 0..3, label, paired, maxsuit, high}` (`high` is a rank index, 10 = queen). Instant: a live label before any opponent is entered.
- `hand_equity(hero, board, [range, ...], iters=6000, seed=7) -> {equity, win, tie, method, n}`.

## 2. What `PostflopSpot` needs

```python
Villain(weights, ptype="unknown", line=[], label="")
PostflopSpot(hero, board, pot, to_call=0.0, hero_stack=0.0, villain_stack=None, villains=[],
             in_position=True, hero_pfr=False, facing=None, bb=1.0, risk_premium=0.0, stage="", iters=6000)
advise_postflop(spot) -> Advice
```

| Field | Exact meaning |
|---|---|
| `board` | 3, 4 or 5 cards **in deal order** (flop first). Earlier-street actions are replayed on `board[:3]` and `board[:4]`. |
| `pot` | Every chip in the middle now, **including the bet hero faces** and chips in front of players. Price used: `to_call / (pot + to_call)`. |
| `to_call` | Extra chips hero must add; 0 when checked to hero. Not capped: the adapter caps it at hero's stack. |
| `hero_stack` | Hero's chips **behind, before calling**. Default 0. |
| `villain_stack` | Main opponent's chips behind **after** his bet. Effective stack = `min(hero_stack, villain_stack + to_call)`; `None` means hero's stack. With `to_call > 0` and `villain_stack <= 1%` of the pot, `facing` becomes `"shove"`. |
| `villains` | `villains[0]` is the main opponent: the player whose bet hero faces, else (as `decide.py` does) the biggest stack. Only he gets the current bet added to his line, his `ptype` drives the passive / station rules, and the "ahead of X%" line is about him. |
| `Villain.weights` | His range from how he entered the pot (section 3). |
| `Villain.line` | `[(street, action, size)]`, street `flop/turn/river`, action `check/call/bet/raise/shove`, size = the bet as a **fraction of the pot before it** (0.66) or `None`. For a call, the size of the bet called. Ignored for raise and shove. |
| `in_position` | Hero acts last among all players left. |
| `hero_pfr` | Hero made the last raise before the flop. |
| `facing` | `"bet"`, `"raise"` (hero bet and was raised) or `"shove"`. `None` means `"bet"` when `to_call > 0`. |
| `bb` | Display only. Above 1.5 sizes print as chips, otherwise as big blinds (pass 1.0 when the table is kept in big blinds). |
| `risk_premium` | `Prizes.risk_premium(stacks, hero_idx, villain_idx)`, each stack = behind + bet this street. Pass 0 for chip EV (a spin). |
| `stage` | Never read. |

Units are free (chips or bb) as long as all four amounts agree.

## 3. Ranges for opponents

`range_from_spec(spec, n_players=9, ptype="unknown", hero_pos_nb=None) -> (weights, label)`; `hero_pos_nb` is the number of players behind hero's preflop seat (BB 0, SB 1, BTN 2, CO 3...). Sizes measured (8 players, unknown type):

| Spec | Range | Note |
|---|---|---|
| `open:CO` / `open:UTG` | 25.5% / 11.6% | `n_players` only matters for UTG (6 players: 16.7%). nit 16.7%, maniac 53.2% from CO. |
| `call:BB` | 32.6% (hero CO), 15.4% (hero early) | **Assumes hero opened** from `hero_pos_nb`. `ptype` ignored. |
| `flat:BTN` | 8.5% (hero HJ) | same assumption |
| `call:SB` | 1.3% | the chart re-raises or folds there |
| `3bet` | 6.7% (nit 3.0%) | against an open from hero's seat; text after `:` ignored |
| `limp`, `any`, `35%`, `"77+, AJs+"` | 37.7%, 100%, 35%, 4.8% | anything else raises `ValueError` |

When a third player opened, copy `decide._range_for(role, behind, opener_behind, ptype)`: it passes the real opener, widens callers for loose types and repairs the near-empty small-blind call.

`parse_line("flop=call turn=bet66 river=xr") -> [('flop','call',None), ('turn','bet',0.66), ('river','raise',None)]` (text takes percent, the tuple holds a fraction).

## 4. A call, and what comes back

```python
w, label = range_from_spec("open:UTG", 8, "unknown", 0)
spot = PostflopSpot(hero=parse_hand("AhKd")[1], board=parse_cards("Ks7d2c"), pot=4500, to_call=1500,
                    hero_stack=20000, villain_stack=18000, villains=[Villain(w, "unknown", [], label)],
                    in_position=False, bb=600)
print(advise_postflop(spot).render())
```
```
>>> CALL   [clear]
AhKd on Ks7d2c (flop, rainbow, K-high): top pair, strong kicker (A) | pot 7.5bb, 32.5bb behind (SPR 4.3)
  why: you have the equity for the price against the hands that bet this way
  num: equity vs their range after this line: 80% (vs the range they started with: 84%)
  num: right now you are ahead of 84% of their range, behind 9%; they hold: pair 70%, high card 25%, three of a kind 5%
  num: to call 1,500 (2.5bb, 50% pot): pot odds need 25%, +2 pts safety -> need 27%, have 80%
```

`Advice`: `action`, `confidence` (`clear | standard | close`), `situation`, `why[]`, `numbers[]`, `alt[]`, `warnings[]`, `data = {equity, raw_equity, strength, spr}`. `dataclasses.asdict` of both `Advice` and `PostflopSpot` is JSON-safe. `need`, `target` and the bet amount exist only inside strings.

Every action string (all produced here):

| Facing a bet | Checked to hero |
|---|---|
| `FOLD` | `CHECK` |
| `CALL` | `BET 990 (1.6bb, 33% pot)` |
| `RAISE to 5,400 (9.0bb, 120% pot)` | `BET 1,800 (3.0bb, 60% pot) (semi-bluff)` |
| `RAISE ALL-IN` | `BET 990 (1.6bb, 33% pot) (c-bet)` |
| `RAISE ALL-IN (semi-bluff)` | `BET ALL-IN`, `BET ALL-IN (semi-bluff)` |

With `bb <= 1.5` sizes read `BET 1.7bb (33% pot)`, `RAISE to 9.0bb (120% pot)`. Amounts are the chips hero puts in now (call included), not rounded to chip values; "ALL-IN" means the effective stack. Classify with `action.split()[0]` plus `"ALL-IN" in action`.

## 5. Speed

Median of 9 calls, typical ranges, opponent 1 bets and the others called (milliseconds):

| | 1 opponent | 2 | 3 |
|---|---|---|---|
| Flop | 38 | 37 | 39 |
| Turn | 7 | 31 | 41 |
| River | 1 | 21 | 21 |

Worst single call seen (any-two-cards ranges): 78 ms. Eight opponents: 27 to 46 ms. Cold process: import 40 ms, first range 15 ms, first advice 50 ms. Time is linear in `iters` (24,000: 190 ms). Heads-up turn and river are exact; everything else is Monte Carlo with a fixed seed, so the same spot always returns the same answer (on the flop, seed-to-seed spread is 1.7 points heads-up and 2.3 three-way). Forty calls from four threads matched the single-thread result. It can be recomputed on every state change.

## 6. What moves the answer most

AhJd on Js8s4c2d, pot 9,000 including a 3,000 bet, 24,000 behind, opponent opened the cutoff and bet the flop: equity 70%.

| Input changed | Effect |
|---|---|
| Preflop range: `3bet` 48%, `open:UTG` 59%, `open:BTN` 78%, `limp` 83%, `"JJ+, AK"` 15% (FOLD) | 15 to 83% |
| `facing="raise"` 36%; line `flop=raise` 35%; `shove` 46% | halves |
| Type: nit 60%, unknown 70%, station 77%, maniac 80% | 20 points |
| Opponents: 2 gives 60%, 3 gives 52% (and +3 points needed) | 18 points |
| Bet size: 33% pot 72%, 200% pot 59% (price 20% to 40%) | 13 points |
| `hero_pfr` true: 68%. Out of position: equity unchanged, 2 points more needed | 2 points |

River bluff-catcher (KhTd on Ks8s4c2d7h after two barrels): FOLD against nit (3%), unknown (17%) and station (25%); CALL against maniac (56%) or an `any` range (48%).

`risk_premium` only counts when the call is 25% or more of `hero_stack`: QhQd facing a shove for 6,000 of 9,000 goes CALL (0, 0.05) to FOLD (0.10, 0.18). From 0.06 it also removes semi-bluffs and c-bets. Stack size decides between CALL and RAISE ALL-IN (24,000 behind CALL, 6,000 RAISE ALL-IN).

## 7. Where it is weak (warn in the app)

- Equity is showdown equity against a rule-narrowed range. There is no fold-equity or EV calculation, no river bluff, no bluff raise, no check-raise, one fixed size per situation.
- The range guess dominates (section 6) and the callers' ranges assume hero opened.
- A flop bet from an opponent is read as a continuation bet (wider) whenever `hero_pfr` is false, even when he only called before the flop.
- Multiway: ranges are independent, only `villains[0]` carries the bet, hero never bluffs.
- ICM never touches hero's own value shoves: `BET ALL-IN` and `RAISE ALL-IN` came back unchanged at `risk_premium=0.2`.
- The tests are four behaviour checks and a no-crash fuzz of 70 spots. Label the answer an estimate.

## 8. Gotchas

1. **Nothing is validated.** A hero card repeated on the board is accepted (`AhKd on AhKs7d` gave BET). Check duplicates across hero and board yourself.
2. **No opponents or an empty range means 100% equity**: `villains=[]`, all-zero weights, `range_from_spec("")`, or a range fully blocked (AA against AhAd on As). Refuse to advise instead.
3. **`hero_stack` left at 0** turns every value bet into `BET ALL-IN` (SPR 0.0).
4. **`ZeroDivisionError`** when `pot == to_call`, when `bb == 0`, and when `pot == 0` with a hand worth betting. A board without 3, 4 or 5 cards raises `ValueError`.
5. **`to_call` above hero's stack** is priced as given (FOLD at 43% needed; capped, the same spot is a CALL at 20%). Cap it and take the uncalled part out of `pot`.
6. **Board order**: the same four cards as `2d4c8sJs` instead of `Js8s4c2d` turned CALL (35%) into FOLD (24%) with `flop=raise` in the line.
7. **Check-raise**: the bet hero faces is added to `villains[0]` only when his line has no entry for the current street. `flop=check` plus `facing="raise"` gave 75%; with `flop=check flop=raise50` 57%. Add the raise yourself.
8. **Other opponents get nothing automatic.** Add their call or check on this street.
9. **Line tuples are not checked.** An unknown action (`"Bet"`, `"fold"`) is silently treated as a shove; an unknown street raises `KeyError`; a size of 50 instead of 0.5 is accepted.
10. **Trust `action`, not the numbers.** The commitment rule returned `CALL [close]` beside "need 20%, have 16%".
11. Two opponents on one remaining combo return equity 0.5 (`no valid samples`) with no warning.
12. Unknown seat names fall back silently (`open:UTG+3` becomes the hijack range).

## 9. The adapter pattern in `live/decide.py`

Acting order after the flop: small blind first, button last (heads-up: big blind first). `in_position = all(rank[hero] > rank[s] for s in opponents)`. Main opponent = the bettor, else the biggest stack. Size of a bet = bet / pot before this street's bets; a call carries `None`. `facing` is set only when hero already has chips in and was raised (`"shove"` if that player has nothing behind). `risk_premium` uses behind + bet for every stack against the main opponent. With the preflop action unknown, every opponent is read as a caller and a warning says so.
