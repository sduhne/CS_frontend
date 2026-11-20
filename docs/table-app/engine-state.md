# Engine state map: `poker_coach/state.py`

For the builders of the table app. Read from `state.py` (676 lines) and the table commands in `cli.py`. Every example was run on 2026-11-18 against a scratch state file; the repository was not changed.

## 1. What it is

`from poker_coach import state as S`. The state is one plain, JSON-serialisable dict. There are no classes: functions take the dict and most mutate it in place. None of them saves, checkpoints or validates; the CLI does that around them.

It stores the table **between hands**: seats, stacks, button, level, tournament facts. It has no hand in progress (no cards, pot, bets, street, whose turn) and no blind schedule. Those belong to the new app.

## 2. The dict

`S.blank_state()` after one `apply_snapshot` (seats trimmed):

```json
{"version": 1, "created": 1795023691.0,
 "tournament": {"name": "", "buyin": null, "entrants": 500, "remaining": 96, "paid": 75,
                "payouts": null, "prize_pool": null, "start_stack": 10000.0,
                "avg_stack": null, "total_chips": null},
 "level": {"sb": 300.0, "bb": 600.0, "ante": 75.0, "bb_ante": 0, "number": null},
 "table": {"max_seats": 9, "button": 3, "hero": 5,
   "seats": {"1": {"name": "Bob", "stack": 21000.0, "status": "active", "type": "unknown", "notes": []},
             "3": {"name": "Carl", "stack": 48000.0, "status": "away", "type": "unknown", "notes": []}}},
 "config": {"goal": "itm", "pace": "online"},
 "history": [{"t": 1795023691.0, "remaining": 96}],
 "log": [{"t": 1795023691.0, "msg": "blinds now 300/600 ante 75"}],
 "undo": []}
```

- Seat keys are **strings**; `button` and `hero` are **int** seat numbers or `null`.
- `status`: `active` and `away` are dealt in; any other value is not. `type`: unknown, nit, tight, tag, lag, loose, station, maniac. `notes`: list of strings.
- `payouts`: prizes from 1st down; may be shorter than `paid`. `total_chips` is written only as average stack x remaining.
- `level.number` is a label; nothing reads it.
- `config.goal`: `itm`, `balanced`, `chips` (`S.GOALS`). `config.pace`: `online` 55 seconds a hand, `fast` 35, `live` 120; an optional `config.sec_per_hand` overrides it.
- A blank state has every tournament field `null`, `sb` and `bb` `null`, no seats.

## 3. Functions

| Signature | Returns | Mutates |
|---|---|---|
| `blank_state()` | new dict | |
| `load(path=None)` | dict from the file, missing keys filled one level deep; a blank state if the file is absent | |
| `save(state, path=None)` | `None`; atomic write, creates the folder | file |
| `exists(path=None)` | bool | |
| `archive(path=None)` | new path `archive-YYYYmmdd-HHMMSS.json` beside it, or `None` | renames the file |
| `checkpoint(state)` | `None` | appends a deep copy of everything but `undo`; keeps 15 (`MAX_UNDO`) |
| `undo(state)` | the **previous dict**, or `None` | pops `state["undo"]` |
| `log(state, msg)` | `None` | appends `{"t","msg"}`; keeps 400 |
| `seats(state)` | the live `table.seats` dict | |
| `occupied(state)` | sorted ints: status active or away **and** stack > 0 | |
| `find_seat(state, who)` | int or `None`. Takes an int, `"3"`, `"s3"`, `"seat3"`, `"#3"` (returned even if that seat is empty), `hero`/`me`/`i`, an exact name, or a partial name if unique | |
| `set_seat(state, seat, name=None, stack=None, status=None, ptype=None)` | the live seat dict; a new seat starts as `{"name": "SeatN", "stack": 0, ...}`; `None` leaves a field alone | the seat; raises `max_seats` to `seat` |
| `remove_seat(state, seat, reason="busted")` | the name, or `None` | deletes the seat, logs |
| `next_occupied(state, seat)` | next occupied seat above, wrapping | |
| `advance_button(state)` | new button seat, or `None` with no players | `table.button` |
| `action_order(state)` | seats in preflop order: first to act ... SB, BB | |
| `positions(state)` | `{seat: label}` | |
| `blinds(state)` | `(sb, bb, ante, bb_ante)` floats; `sb` defaults to `bb/2`; all 0.0 when unset | |
| `orbit_cost(state)` | `sb + bb + ante * max(2, n) + bb_ante` | |
| `hero_stack(state)` | float, or `None` if hero is unset or the seat is gone | |
| `total_chips(state)`, `avg_stack(state)` | float or `None` | |
| `paid_places(state)`, `payouts(state)` | int, list, or `None` | |
| `stage(state)` | `{"remaining","paid","hero_bb","code","label","to_money"}` | |
| `record_remaining(state, n)` | `None` | appends `{"t","remaining"}` to `history` if changed; keeps 200 |
| `bust_rate(state)` | eliminations a minute, or `None` | |
| `fold_clock(state)` | dict or `None` | |
| `build_prizes(state, goal=None)` | `icm.Prizes` | |
| `hand_setup(state)` | `(pushfold.HandSetup, order)`; `ValueError` without a big blind or with fewer than two players | |
| `apply_snapshot(state, snap)` | list of change sentences | everything; logs each change |
| `render(state)` | the text table the CLI prints | |

`S.STATE_PATH` is fixed at import: `$POKER_COACH_STATE`, else `tournament/current.json`. Pass your own `path`.

## 4. Seats, button, positions

Clockwise is ascending seat number, wrapping. After the button come SB, BB, then the first to act. Heads-up the button is the small blind and acts first. Labels come from players behind (`ranges.position_name`). Ran with the button on seat 1 (`action_order`, then labels in that order):

```
2 [1, 2]                         ['SB/BTN', 'BB']
3 [1, 2, 3]                      ['BTN', 'SB', 'BB']
4 [4, 1, 2, 3]                   ['UTG(CO)', 'BTN', 'SB', 'BB']
5 [4, 5, 1, 2, 3]                ['UTG(HJ)', 'CO', 'BTN', 'SB', 'BB']
6 [4, 5, 6, 1, 2, 3]             ['UTG(LJ)', 'HJ', 'CO', 'BTN', 'SB', 'BB']
7 [4, 5, 6, 7, 1, 2, 3]          ['UTG', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB']
8 [4, 5, 6, 7, 8, 1, 2, 3]       ['UTG', 'UTG+2', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB']
9 [4, 5, 6, 7, 8, 9, 1, 2, 3]    ['UTG', 'UTG+1', 'UTG+2', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB']
```

- **No button:** the highest occupied seat plays as the button; `advance_button` then sets the lowest.
- **Button on an empty seat** (its player busted): the occupied seat before it is labelled BTN, and `advance_button` moves to the next occupied seat after it. Ran: 6 seats, button 3, seat 3 removed gives `{6: 'UTG(HJ)', 1: 'CO', 2: 'BTN', 4: 'SB', 5: 'BB'}`; advance gives button 4.
- Away players keep their seat, position and blinds; the CLI passes an `away` flag to the engine.

## 5. Blinds and antes

`ante` is paid by every player, `bb_ante` by the big blind alone. Both can be set; they add. Ran, four players at 300/600:

```
ante 75      orbit_cost 1200.0  HandSetup.antes [75.0, 75.0, 75.0, 75.0]  blinds [0.0, 0.0, 300.0, 600.0]
bb_ante 600  orbit_cost 1500.0  HandSetup.antes [0.0, 0.0, 0.0, 600.0]    blinds [0.0, 0.0, 300.0, 600.0]
```

`HandSetup` lists players in `action_order`, takes start-of-hand stacks and caps a blind by the stack.

## 6. Money facts

- `paid_places`: `paid` (or the payout list's length if longer), else the length of an estimated table from `entrants` (15% of the field; a third at 10 entrants or fewer), else `None`.
- `payouts`: the stored list, padded to `paid` with the last prize; else `default_payouts(entrants, paid, pool)` with pool = `prize_pool`, or `buyin * entrants`, or one unit per entrant. With `paid` but no `entrants` it assumes `max(paid * 7, remaining)` entrants. `None` with neither.
- `total_chips`: the stored field, else `entrants * start_stack`. `avg_stack`: total / remaining, else the stored `avg_stack`, else the table's mean.
- `stage` needs `remaining` and paid places. Ran with 75 paid, 8 seated:

```
263 early | 262 middle | 150 approach | 97 near_bubble | 78 bubble | 75 itm | 10 itm | 9 final_table
```

  The limits: middle at 3.5x paid or fewer, approach at 2x, near_bubble at 1.3x, bubble when `to_money <= max(2, round(0.04 * paid))`. `final_table` needs `remaining <= max(9, max_seats)` and `remaining <= seated + 1`. Without the two numbers the code is `middle` (`early` over 60bb) with the label "stage unknown ...", or `unknown` with no hero stack.
- `fold_clock`: `None` without a hero stack or blinds. Else `{"orbits", "minutes", "eta", "verdict"}`. `eta` and `verdict` stay `None`, and `rate` is absent, unless the money is still ahead and there is a bust rate. The verdict is `safe` over 1.5x the ETA, `tight` over 1x, else `short`. The rate needs two `history` entries at least a minute apart by wall clock, with `remaining` lower. Ran (rounded): 6,000 chips, 300/600/75, 110 to 96 players in 10 minutes gives `{'orbits': 4.0, 'minutes': 29.3, 'eta': 19.5, 'verdict': 'safe', 'rate': 1.4}`.
- `build_prizes`: chip EV (`Prizes(label="chip EV")`) when the goal is `chips`, or `remaining` or payouts are unknown. Otherwise ICM over the seated stacks plus `remaining - seated` field players of an estimated stack. Goal `itm` adds the minimum cash to every prize until `remaining <= paid`. Ran: `ICM (96 left, 75 paid, ITM-first)`, `field_n` 92.

## 7. Undo, log, files

Every CLI command does `st = S.load(); S.checkpoint(st); ...change...; S.save(st)`. Undo is `prev = S.undo(st); S.save(prev)`: use the **returned** dict. A checkpoint also holds `log` and `history`, so undo rewinds them. Ran: 20 checkpoints keep 15; a full log with 15 checkpoints is a 660 KB file.

## 8. `apply_snapshot` accepts

`blinds` (`[sb, bb]`, `[sb, bb, ante]` or a dict), `sb`, `bb`, `ante`, `bb_ante`, `level`, `name`, `buyin`, `entrants`, `paid`, `prize_pool`, `start_stack`, `avg_stack`, `payouts`, `remaining`, `goal`, `pace`, `max_seats`, `seats`, `complete`, `busted`, `hero`, `button`. Numbers may be `"21k"`, `"1.2m"`, `"$11"`, `"1,200"`.

`seats` is `{"3": value}` or a list of dicts with `"seat"`. A value is `[name, stack]`, `[name, stack, status]`, a bare stack, `{"name","stack","status","type","note","hero"}`, or `null` / `"empty"` / status `out`, `empty`, `busted` to remove. `complete: true` removes unlisted seats, only when `seats` is present. `hero` and `button` take a seat number or a name.

## 9. Rules that live in `cli.py`, not here

- A bust lowers `remaining` by one and records history (`cmd_bust`, `cmd_sync`).
- `set bb=` also sets `sb = bb/2` unless `sb=` is given.
- `new` sets `remaining = entrants` unless `--remaining` is given.
- `_resolve` also accepts position names (`BTN`, `CO`) through `preflop.pos_to_index`.
- `payouts 1:1000 2:600 4-6:200` gives an unlisted place the prize of the next listed place below it (ran: 3rd got 200). It does not set `paid`. `auto` clears the list.
- `_state_spot` is the bridge to `advise`: `hand_setup`, `build_prizes`, `stage`, `fold_clock`, and `desperate` (verdict `short` at 6bb or less; or 3bb or less with more than 3 places to the money, or the distance unknown).

## Gotchas

1. **Nothing validates.** `button=9` or `hero=9` on an empty seat, `goal="win"`, `status="sitting"` are stored as given. An unknown status silently drops the player from `occupied`; an unknown type becomes `unknown`; an unknown hero or button name is ignored.
2. **`apply_snapshot` is not atomic.** `{"blinds": [100, "abc"]}` raises `ValueError` after earlier keys were applied. Apply to a deep copy.
3. **Snapshot `bb` alone keeps the old small blind.** Ran after 300/600: `{"bb": 800}` gives 300/800. Send both.
4. **Zero stack means not seated.** `set_seat(st, 8)` creates `Seat8` with 0 chips: listed, no position. A hero at 0 gives `hero_stack` 0.0, `hero_bb` `None` and no fold clock.
5. **Labels differ from the sheets.** Eight-handed the second seat is `UTG+2` (no `UTG+1`); under seven players the first is `UTG(LJ)`, `UTG(HJ)`, `UTG(CO)`; heads-up `SB/BTN`. `binary` and `tag` say `UTG+1` and `LJ`. Key seats by players behind and label them yourself.
6. **One seated player** gets the label `BB`; `hand_setup` raises "need at least two seated players". No big blind raises "blinds are not set".
7. **A removed hero** leaves `table.hero` pointing at the empty seat; `hero_stack` is `None`.
8. **A renamed player is a new player.** A snapshot name that does not match (`Bob` to `B0b` did not) replaces the seat and drops type and notes. Rename with `set_seat(name=...)`.
9. **`total_chips` sticks** and wins over `entrants * start_stack`. It is set only when `avg_stack` arrives while `remaining` is known; an average sent first never becomes a total.
10. **`remaining` of 0 or `None` is "unknown"**: chip EV, no stage.
11. **Final table needs every remaining player seated**: 6 left with 4 seated reads `itm`.
12. **A spin (3 left, 1 paid) reads `BUBBLE (2 from the money)`.** One prize keeps the ICM linear (risk premium 0.0), but use goal `chips` and hide the stage for spins and All-In or Fold.
13. **`cmd_sync` subtracts every listed bust**, found or not: `{"busted": ["Ann", "Ghost"]}` took 2 off `remaining`.
14. **`save("bare.json")` raises `FileNotFoundError`**: the path needs a folder.
15. **`set_seat` and `seats` return live dicts**: copy before comparing. Keep `undo` out of what the browser receives.
