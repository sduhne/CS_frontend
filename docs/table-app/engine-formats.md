# Engine map: Spin & Go, All-In or Fold, sit-out signal

Covers `poker_coach/spin.py`, `poker_coach/aof.py`, the sit-out part of `poker_coach/latereg.py`
and their callers in `cli.py` and `live/decide.py`. Every call below was run; outputs are pasted.

## 0. Shared conventions

```python
from poker_coach import spin as SP, aof as A, latereg as L
from poker_coach.cards import parse_hand, parse_range, HANDS, GRID
h = lambda text: parse_hand(text)[0]      # "K7s" -> index 0..168; "AhKd" -> (13, (50, 45))
```

- Both `decide` functions take the **integer** hand index; a string raises `TypeError`.
- Grid order: `HANDS[row*13 + col]`, `GRID = "AKQJT98765432"`. Row < col is suited (above the
  diagonal), row > col offsuit. `HANDS[1] == 'AKs'`, `HANDS[13] == 'AKo'`.
- Stacks are big blinds (sit-out signal: chips). Neither format's tables have antes or ICM.
- Cost: data loads in 4 ms (spin) and 15 ms (aof), cached; 1,000 decisions take 12 to 38 ms.

## 1. Spin & Go (`spin.py`)

```python
SP.decide(hand: int, spot: str, stack_bb: float, vs: str = "solid") -> tuple[str, str]   # (action, why)
```

| Hero | Before hero | Players | `spot` | Answers |
|---|---|---|---|---|
| BTN | nobody | 3 | `btn` | ALL-IN / FOLD |
| SB | BTN folded | 3 | `sb` | ALL-IN / FOLD |
| SB | BTN all-in | 3 | `sb_vs_btn` | CALL / FOLD |
| BB | BTN all-in | 3 | `bb_vs_btn` | CALL / FOLD |
| BB | SB all-in | 3 | `bb_vs_sb` | CALL / FOLD |
| BB | both all-in | 3 | `bb_vs_both` | CALL / FOLD |
| SB | BTN raised small | 3 | `sb_vs_btn_raise` | ALL-IN / FOLD |
| BB | BTN raised small | 3 | `bb_vs_btn_raise` | ALL-IN / FOLD |
| BB | SB raised small | 3 | `bb_vs_sb_raise` | ALL-IN / FOLD |
| BB | SB limped | 3 | `bb_vs_sb_limp` | ALL-IN / CHECK |
| SB (the button) | first to act | 2 | `hu_sb` | ALL-IN / FOLD |
| BB | SB all-in | 2 | `hu_bb` | CALL / FOLD |
| BB | SB raised small | 2 | `hu_bb_vs_raise` | ALL-IN / FOLD |
| BB | SB limped | 2 | `hu_bb_vs_limp` | ALL-IN / CHECK |

The eight solved rows are `SP.SPOTS`; the six limp and raise rows are `SP.OPENERS`.

**Seat and action to key:** `cli._spin_spot(ns)` reads `ns.pos` (BTN/SB/BB; BTN heads-up becomes
SB), `ns.players` (2 or 3), `ns.shoved` ("", "BTN", "SB", "BTN,SB") and `ns.facing` ("", "SB limp",
"BTN raise", "SB raise"). Anything else raises `ValueError`. The reference caller is
`live/decide.py::_preflop` (lines 366-386); it returns CHECK for a big blind with no raise and no
limp before the lookup.

**Effective stack is the caller's job** (`live/decide.py` 340-346), on start-of-hand stacks:

```python
rivals = players_still_to_act_behind_hero + players_who_limped_or_raised
eff = min(hero, max(stack[r] for r in rivals)) / bb
if all_ins:   eff = min(hero, max(min(a.amount, stack[a.idx]) for a in all_ins)) / bb
```

**Stack coverage.** Solved at `SP.STACKS = (2,3,4,5,6,7,8,10,12,15,20,25,30)`. Solved rows read
the **nearest** solved stack, ties to the smaller (`SP.nearest(9) == 8`), no interpolation, and
clamp silently outside 2 to 30. Limp and raise rows read a **band**: `SP.band(stack)`, edges
5.5 / 8.5 / 12.5 / 17.5 / 24.5. A small raise at `stack <= SP.COMMITTED_BB` (5.5) is answered as
the matching all-in row.

**Opponents:** `vs` is `"solid"`, `"loose"` (they call 1.5 times too wide), `"very-loose"` or
`"vloose"`; anything else raises `ValueError`.

```
SP.decide(h("K7s"), "btn", 12)
('ALL-IN', 'BTN, nobody has entered, 12bb effective: K7s earns +0.05bb against folding (table read at 12bb, against players who call correctly)')
SP.decide(h("A5o"), "bb_vs_btn", 9)
('CALL', 'BB, the button is all-in, 9bb effective: A5o earns +0.66bb against folding (table read at 8bb, against players who call correctly)')
SP.decide(h("72o"), "bb_vs_sb_limp", 14)
('CHECK', 'BB, the small blind limped, 13 to 17bb: all-in with 22+, A2s+, K2s+, Q5s+, ... T9o')
SP.decide(h("A2o"), "bb_vs_btn_raise", 5)
('CALL', 'a raise from a stack this short is an all-in. BB, the button is all-in, 5bb effective: A2o earns +0.95bb ...')
SP.decide(h("T5s"), "sb", 10, "loose") -> ('FOLD', '... earns -0.37bb against folding (... players who call 1.5 times too wide)')
SP.decide(h("K7s"), "btn", 45)         -> ('FOLD', '... earns -0.01bb against folding, close to a coin flip (table read at 30bb, ...)')
```

", close to a coin flip" appears when |edge| < 0.05bb.

**Whole range as a grid:**

```python
SP.play(spot, stack_bb, vs)        # 169 weights, exactly 0.0 or 1.0 (SPOTS only)
SP.edge(spot, stack_bb, hand, vs)  # bb earned against folding; index or "K7s"
SP.width(spot, stack_bb, vs)       # % of hands: ("btn", 12) = 31.2; loose 23.7
parse_range(SP.raise_rows()[spot][SP.band(stack_bb)])   # limp and raise rows: no EV
```

`SP.play` on a limp or raise row raises `KeyError`; apply `SP.AS_ALLIN[spot]` yourself at 5.5bb
or less.

**Money:** `SP.break_even()` = 0.359, `SP.roi(0.37)` = +0.029, `SP.roi(1/3)` = -0.07, `SP.PRIZES`,
`SP.FEE`, `SP.simulated_win("sheet", "solid")` = 0.331. `SP.sim()["blinds"]` and
`SP.sim()["structures"]` hold the simulation's blind ladder (`[[10,20],[15,30],[20,40],...]`),
start stacks (300 chips for x2 and x3, 500 above) and level minutes: usable as Spin presets, but
they come from guides, not from GGPoker.

## 2. All-In or Fold (`aof.py`)

```python
A.decide(hand: int, n: int, hero: int, mask: int = 0,
         stacks: list[float] | None = None, family: str = "cash") -> A.Answer
```

- **Seats:** `A.POSITIONS = {2: ['SB','BB'], 3: ['BTN','SB','BB'], 4: ['CO','BTN','SB','BB']}`.
  `n` is the players dealt in; `hero` is the index in that acting order.
  `A.position_index("BTN", 4) == 1`, `("BTN", 2) == 0` (heads-up the button is the small blind).
- **Who shoved:** bit k of `mask` is seat k. `A.parse_shovers("CO,BTN", 4, 3) == 3`,
  `("CO+SB", 4, 3) == 5`, `(None, 4, 0) == 0`. A seat behind hero raises `ValueError`.
- **Every situation is the same call.** `A.decision_points(4)` lists the 14 `(hero, mask)` pairs
  (6 three-handed, 2 heads-up); `A.describe_point(4, 3, 5) == 'BB - CO and SB all-in'`.
- **Stacks:** `n` stacks in acting order, in bb; `None` means 8 each. `decide` works out the
  effective stack: `A.effective_stack(stacks, hero, mask)` is `min(hero, biggest stack behind)`
  when nobody shoved, else `min(hero, biggest shover)`. `([8,6.5,8,5], 0, 0) == 8`;
  `([4,6.5,8,5], 2, 0b11) == 6.5`.
- **Mode and opponents:** `A.family_for(mode, vs)`: `("cash", None)` -> `"cash"`, `("cash","loose")`
  -> `"cash-loose"`, `("cash","very-loose")` -> `"cash-vloose"`, `("tournament", None)` -> `"chips"`.
  Loose with tournament raises `ValueError`.
- **Cash:** 0.1bb fee out of every pot, walks included; solved at 2,3,...,8bb with EV interpolated
  between (6.5bb works). Above 8 it answers for 8 with a note: the cap is not enforced, so the app
  must cut every stack to 8bb at the start of a hand.
- **Tournament (`chips`):** no fee, no ICM, solved at 2-8, 10, 12, 15, 20bb; clamps at 20 with a note.

`Answer` fields: `action` ("ALL-IN" or "FOLD", also when calling), `confidence` (clear if
|ev| >= 0.25, standard >= 0.05, else close), `ev`, `freq`, `hand`, `seat`, `n`, `shovers`, `stack`
(the one used), `family`, `range_weights` (1 where ev > 0), `notes`; `range_pct`; `render()`.
`dataclasses.asdict(ans)` is JSON-ready.

```
A.decide(h("A5s"), 4, 1, 1).render()
>>> FOLD   [clear]
A5s in BTN, 4-handed, 8bb effective, CO all-in | cash, 0.1bb fee
  num: shoving earns -0.28bb compared with folding
  num: the equilibrium calls 12.4% of hands here [55+, A8s+, KJs+, A9o+, KQo]

A.decide(h("Q4o"), 4, 2, 0, [8, 8, 8, 5.5])   -> ALL-IN [standard], 5.5bb effective, +0.12bb
  !!   stacks differ: answered for the effective stack, an approximation
A.decide(h("22"), 2, 1, 1, [15, 15], "tournament")   -> FOLD [standard], -0.14bb
  !!   chip EV only: near the money, call all-ins tighter than this
A.decide(h("T5s"), 4, 2, 0, None, "cash")       -> ALL-IN [standard] +0.06bb (58.7% of hands)
A.decide(h("T5s"), 4, 2, 0, None, "cash-loose") -> FOLD [clear] -0.38bb (45.7%)
  !!   assumes every opponent calls too wide; against solid players use the solved table
A.decide(h("A5s"), 4, 0, 0, [12]*4)   -> !!   stack 12bb is outside the solved range; answered for 8bb
```

**Whole range as a grid:**

```python
weights, ev, used = A.node_range(family, n, hero, mask, stack)   # stack = the effective stack
# weights: 1.0 ev > +0.05bb, 0.5 within 0.05bb (coin flip), 0.0 fold; ev in bb per hand
A.node_range("cash", 4, 2, 1, 8.0)   # 31 hands at 1.0; A4s, KJo, 33 at 0.5; used == 8.0
```

`A.matrix()` holds the `aof-compare` numbers (bb per 100 hands and swing), keys such as
`'solved|solid'` (-2.5) and `'cash-loose|cash-vloose'` (+4.23); 4-handed 8bb only.

## 3. Sit-out signal (`latereg-safe`)

```python
L.zone(stack, avg, remaining, paid) -> (name, cover, text)   # chips, chips, players left, places paid
L.describe_zone(stack, avg, remaining, paid) -> str
L.sit_out_line(avg, remaining, paid); L.expected_cost(avg, remaining, paid); L.cash_chance(cover)
```

`cover` is stack / sit-out line. Zones: `safe` (1.0 or more), `close` (0.5), `short` (0.2), `far`.

```
L.zone(14000, 52000, 180, 150) -> ('short', 0.2648, 'one pot short: all-in with the tight chart')
L.describe_zone(14000, 52000, 180, 150)
>>> KEEP PLAYING   stack 14,000 = 26% of the sit-out line (52,867)
  180 left, 150 paid (1.20 per paid place): the line is 1.02 average stacks of 52,000
  waiting is expected to cost about 27,576 in blinds and antes
  zone: SHORT - one pot short: all-in with the tight chart
  short by 38,867; rough chance of cashing from here 33%
L.describe_zone(60000, 52000, 140, 150) -> '>>> IN THE MONEY: the bubble has burst'
```

The average stack is an input; `state.avg_stack(st)` derives it from total chips / remaining.

## Gotchas

1. **Spin has two rounding rules.** `decide` and `play` read the nearest solved stack; the printed
   sheet (`SP.rows()`, PLAYBOOK) reads bands at 4/7/10/15/20/30bb. At 9bb the BTN range differs
   by 3 hands, at 13bb by 14. Use `decide` + `play` for both answer and grid.
2. **Spin clamps without a warning**; stack 0 or negative answers as 2bb. Validate first.
3. **Spin `vs` is ignored on limp and raise rows.** Call rows change by a hand or two with `loose`
   at short stacks, despite the docs.
4. **Spin action and number can disagree:** the action comes from the tidied range, the number
   from raw EV (21 cells; SB 30bb K8s is ALL-IN, "earns -0.05bb").
5. **Spin spots with no table** (`ValueError`): a BTN limp, hero acting a second time. A small
   raise plus an all-in is read as the all-in alone (`bb_vs_sb`), ignoring the raiser.
6. `_spin_spot` lives in `cli.py` and takes an argparse-style namespace: wrap or copy it.
7. **AoF never says CALL**, and `render()` says "shoving earns" for calls: relabel in the UI.
8. **AoF big blind with nobody all-in:** `decide` raises `ValueError`, `node_range` `KeyError '3:0'`.
9. **AoF seat names:** "UTG" and "EP" always mean index 0; "CO" does not exist three-handed;
   5 players raises `ValueError`.
10. **AoF effective stack** ignores bigger stacks behind once somebody has shoved. The exact answer
    needs the C solver, not available at run time.
11. **AoF loose tables** are cash only and assume every opponent is loose.
12. Use `node_range` for the grid (it has the 0.5 band); `Answer.range_weights` does not.
13. **`L.zone` returns `('safe', 99.0)` when `paid` is 0 or `remaining <= paid`**; `describe_zone`
    raises `ZeroDivisionError` when `paid` or `avg` is 0. Require all four inputs and
    `remaining > paid`. Small fields: 25 left, 8 paid puts the line at 9.4 average stacks; say
    it is out of reach.
14. `L.reference_charts(players)` (the charts the zones name) takes 1.5 s for 8 players and 16 to
    20 s for 6 or 7 on first call, cached after: never in the intent path.
15. `parse_hand("AK")` is AKo without complaint; `"AhAh"` and `"AKx"` raise `ValueError`.
