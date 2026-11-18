# Proposal: input speed and every mid-game operation

Lens: a multi-tabling tournament player with a clock running. Layout and visual treatment are left to the other proposals; this one fixes what each key and click does.

## 1. Seven rules

1. **No submit step.** Every key or click is one intent. The table redraws and the advice refreshes after each one (engine calls measured here: 0.08 to 0.2 s, interpreter start included).
2. **Nobody is entered unless they did something.** A skipped player takes the passive default: fold when facing a bet, check otherwise.
3. **The target is hero** whenever hero still owes a decision in the betting round; otherwise it is the next player to act. A seat digit retargets one action.
4. **Defaults are the likeliest value, pre-selected.** Typing overwrites, Enter accepts.
5. **Convert, do not reject.** A bet above the stack becomes all-in, a call with nothing to call becomes a check, actions entered out of order are sorted by seat. Only the impossible (a duplicate card) is refused, with one line saying why.
6. **No confirmation dialogs.** Everything is undoable; destructive steps show an Undo toast for six seconds.
7. **A hand is a list of intents replayed by a pure Python function.** Undo pops one, an edit replaces one and replays. The same list is the hand history.

## 2. Four input states

Digits are seat keys in two states and card ranks in a third, so the state is always explicit and CARDS leaves by itself.

| State | Entered by | Keys mean | Left by |
|---|---|---|---|
| TABLE | start; a settled hand | seat digits, management letters | `n` |
| CARDS | `n`; a closed betting round; a click on a card slot | ranks `2-9 t j q k a`, suits `s h d c`, `s`/`o` for a class | the slot group filling; `Esc` |
| ACTION | hero's cards complete | verbs, seat digits, management letters | the hand settling |
| FIELD | `r`, `b`, `s`, `e`, `m` and the tournament strip | text | `Enter` accepts, `Esc` cancels |

**Seat keys.** Seats are numbered clockwise with hero as 1, drawn bottom centre, in the same ring as the poker client. Each seat shows its position name large (UTG, UTG+1, LJ, HJ, CO, BTN, SB, BB), recomputed whenever the button or the occupancy changes, and its digit as a small keycap. Pressing a digit highlights the seat and opens a small menu of its keys, so the map teaches itself. `Esc` drops the highlight; there is no timeout.

## 3. A hand from the deal to the result

| # | Step | Keys | Mouse | Result |
|---|---|---|---|---|
| 1 | New hand | `n` | Next hand | The previous hand is settled (hero folded if he had not acted), the button moves to the next occupied seat, antes and blinds are posted, the cursor is in hero's cards |
| 2 | Hero's cards, as a class | `a k s`, `a k o`, `7 7` | one cell of a 13 x 13 grid | Enough before the flop. Advice for "folded to you" shows at once |
| 2b | Hero's cards, exact | `a h k d` | two cards in a 4 x 13 grid | Needed after the flop. A class hand is asked for its suits when the flop comes: one key if suited, two otherwise |
| 3 | A player in front acted | `4 r Enter` (default 2.2bb, or 3 times the last raise), `4 r 1500 Enter`, `4 c` call or limp, `4 a` all-in | click the seat, then a verb on the action bar | Everyone between is folded. Advice is computed on the provisional default before Enter. With the default untouched, a verb key accepts it too |
| 4 | Hero acts | `Space` = what the coach says; or `f`, `c`, `x`, `r Enter`, `a` | Follow, or the action bar | `r` is pre-filled with the coach's size. A different action marks the hand "deviated" for review |
| 5 | Players behind | `Enter` = the rest fold; `6 c`, `8 r 4200 Enter`, `8 a` | the same | A round closes itself when the last player able to act has acted; otherwise `Enter` closes it. A raise behind puts the target back on hero with new advice |
| 6 | Flop | `k s 7 d 2 c` | three clicks | Target: hero if he owes a decision, else the first to act |
| 7 | Bets | `x`, `b 1500 Enter`, `b Enter`, `c`, `f`, `r 4500 Enter`, `a`; `4` or `Tab` targets a villain | action bar with third, half, two-thirds, pot, all-in | Pot and amount to call are computed, never typed. Hero's bet is pre-filled with the advised size, a villain's with half the pot |
| 8 | Turn, river | two keys each | one click each | As steps 6 and 7 |
| 9 | Result | nothing when all but one folded; at a showdown `w` hero wins, `l` hero loses a heads-up pot, `4 w` seat 4 wins, `Shift+W` split | Won, Lost, Split; or click the winner | Stacks settled, uncalled bet returned, side pots worked out; a second winner is asked only when a side pot needs one |
| 10 | All-in before the river | `Enter` skips the board | Skip | Straight to step 9 |

`Space` is refused while the advice is stale (each answer carries the intent number it was computed for).

Keystroke budgets, counted from the deal:

| Spot | Keys | Count |
|---|---|---|
| Folded to hero, fold | `n 7 2 o` (the next `n` records the fold) | 4 |
| Folded to hero, open, all fold | `n a k s Space Enter` | 6 |
| A raise in front | `n q q 4 r` | 5 |
| An all-in in front | `n a j o 4 a` | 6 |
| Continuation bet, villain folds | `k s 7 d 2 c Space f` | 8 |

## 4. One amount parser

Every amount field (stack, bet, blinds, average stack) uses it.

| Typed | Means |
|---|---|
| `1300`, `1,300` | chips (in All-In or Fold: big blinds) |
| `12.5k`, `1.2m` | thousands, millions |
| `25bb`, `2.2b` | times the big blind |
| `3x` | three times the bet being raised |
| `66%` | of the pot (bets only) |
| `+3k`, `-1500` | relative to the current value (stacks only) |
| `Up`, `Down` | next or previous preset: minimum, third, half, two-thirds, pot, all-in |

`v` flips every number on screen between chips and big blinds.

## 5. Corrections

The hand line is a strip of chips, one per intent: `AsKs | CO r 2.2 | you r 6.5 | Ks 7d 2c | CO x | ...`. `Left` and `Right` walk it; a click selects.

| Mistake | Keys | Mouse | Result |
|---|---|---|---|
| The last step | `Backspace` (also `z`, `Ctrl+Z`); `Ctrl+Y` redoes | Undo | One intent at a time, across hand boundaries and between-hand edits |
| Amount of the last bet | `e`, number, `Enter` | click the amount | Replayed |
| A hero or board card | `Left` to it, retype | click the card | Replayed, advice refreshed |
| Action on the wrong seat | `Left` to it, the right digit | click it, click the seat | Moved |
| A player marked who did nothing | `Left` to it, `Delete` | the x on the chip | Back to the default |
| A caller forgotten in front of hero | `3 c` | click seat, Call | Inserted in seat order |
| Entered out of order | nothing | | Order comes from the seats |
| Button on the wrong seat | `[` or `]` | drag the button | The hand is replayed with new positions and blinds; cards and actions stay with their seats |
| A stack was wrong | `4 s 12.5k Enter` | click the stack | Start-of-hand stack changed, hand replayed |
| Wrong winner | `Backspace` | Undo | Stacks return, choose again |
| The hand is garbage | `Ctrl+Backspace` | Discard hand | Start-of-hand stacks, button unchanged |

When a replay makes later intents impossible they are dropped and named in the toast.

## 6. Automatic and confirmed

| Automatic | One key from the user | Never automatic |
|---|---|---|
| Antes and blinds posted (heads-up: the button posts the small blind) | The winner at a showdown | Raising the blind level: the level clock only pulses "+" |
| Pot, amount to call, effective stacks | The winner of a side pot the first winner is not in | Players left for eliminations at other tables |
| Folds and checks of skipped players, round closing | Hero busting: place, re-enter or new tournament | Hero's own action: it is always typed |
| Stacks after a result, uncalled bets | | |
| A stack at zero: seat cleared, players left minus one | | |
| Button to the next occupied seat on `n` | | |
| Hero's blinds and antes when he folds | | |
| Stage, average stack, fold clock, bubble distance | | |
| Saving, after every intent | | |

When hero folds and the outcome is not entered: if exactly one opponent raised and nobody called, he is assumed to take the pot (logged, undoable). Otherwise the forced bets are deducted, the pot is left unassigned and the seats involved show `~` on their stack until it is typed again. Hero's stack is always exact; villains' are as fresh as the last correction.

## 7. Every operation

Seat operations follow a seat digit and work in TABLE and ACTION. Clicking a seat opens the same list.

| Operation | Keys | Mouse | Notes |
|---|---|---|---|
| Button forward, back | `]`, `[` | drag the button | No hand is played; `n` plays one |
| Button on a seat | `4 d` | seat menu | |
| One stack | `4 s 12.5k Enter`; hero `s 9800 Enter` | click the stack | Mid-hand too |
| All stacks | `Shift+S`, then value `Enter` per seat, clockwise | Edit stacks | Blank keeps, `-` empties the seat, `Esc` ends. Pasting a list of numbers fills the seats in order |
| Clear a seat | `4 Delete` | seat menu | Player left; players left unchanged |
| Bust a player | `4 k` | seat menu | Seat cleared, players left minus one |
| Add a player | digit of an empty seat, stack, `Enter` | click the empty seat | Name optional |
| Sit out, back | `4 o`; hero `o` | seat menu | The engine treats an absent player's blind as free |
| Rename | `4 e` | click the name | |
| Player type | `4 t`, then `n` nit, `t` tight, `g` tag, `l` lag, `o` loose, `s` station, `m` maniac, `u` unknown | click the type pill | Moves that player's ranges |
| Note | `4 m`, text, `Enter` | seat menu | Shown on hover and in advice context |
| Hero's seat | `4 h` | seat menu | The ring turns so hero is at the bottom |
| Table size | `{` removes, `}` adds a seat | stepper in the header | 2 to 9 |
| Table move | `/move` | Table move | Clears every villain, keeps hero and the tournament, then asks size, button and runs the stack sweep |
| Blinds up, down | `+` or `=`, `-` | the arrows beside the blinds | One step on the ladder; ante follows the ante kind |
| Blinds by hand | `Shift+B`, `300/600/75` or `600`, `Enter` | click the blinds | `600` alone fills the small blind and the ante |
| Ante kind | `Shift+A` cycles none, every player, big blind | click the ante | |
| Blind ladder | `/ladder` | Settings | Paste one level per line; presets per mode |
| Level clock | `p` pauses and resumes | click the clock | Pause also stops the bust-rate clock |
| Players left | `,` minus one, `.` plus one; `<`, `>` by ten; `i`, number | arrows; click the number | Each change is time-stamped: the fold clock needs the rate |
| Places paid, entrants, average stack, start stack, buy-in, payouts, pace | `i` opens the tournament strip, `Tab` between fields | click a field | Payouts as `1:1000 2:600 4-6:200` or `auto` |
| Goal | `g` cycles cash first, balanced, chips | click the goal pill | |
| Chips or big blinds | `v` | toggle | |
| Hypothetical spot | `q` | What if | Hand, seat, stack, action in front; touches nothing |
| Re-enter | `/reenter` | on the bust panel | Start stack, entrants plus one |
| New tournament | `/new` | New | One form, every field optional; the old one is archived |
| Switch mode | `Alt+1`, `Alt+2`, `Alt+3` | header tabs | Each mode keeps its own table |
| Save | nothing | | Written after every intent |
| Load | `/load` | Tournaments | Archived tournaments, newest first |
| Hand history | `y` | History | Every hand with the advice shown and what hero did; filter "deviated"; replay read-only; copy as text |
| Several tables at once (optional, later) | `/table` | tabs in the header | One saved state per table |
| Everything else | `/` and a few letters | | Command palette; `?` shows the key map |

## 8. The three modes

One hand machine, three sets of defaults.

| | Tournament | Spin & Go | All-In or Fold |
|---|---|---|---|
| Seats | 2 to 9 | 3, heads-up after a bust | 4: CO, BTN, SB, BB |
| Amount unit | chips | chips | big blinds |
| Blinds | ladder with `+`/`-`, three ante kinds | the Spin ladder (10/20, 15/30, 20/40, 30/60 ...) | fixed |
| New game | `/new` form | `n` after a finished game: 300 chips each (x2, x3: 92.5% of games); `Shift+N`: 500 (x4 and up) | none |
| A player in front | `4 r Enter`, `4 c`, `4 a` | `2 a`, `2 r Enter`, `2 c` | the digit alone toggles "all-in" |
| Hero | `Space`, `f c x r a` | the same; advice is ALL-IN, CALL, CHECK or FOLD | `Space`, `a`, `f` |
| After the flop | full | full (free flops in the big blind) | none; `Enter` goes to the result |
| Result | step 9 | step 9; one player left ends the game | `w`, `l`, `4 w`, `Shift+W` |
| After the result | busts lower players left | win or loss is added to the session tally (games, wins, win rate against the 35.9% break-even) | stacks above 8bb are cut to 8bb; an empty seat refills at 8bb (a setting) |
| Tournament strip | players left, paid, entrants, payouts, goal | hidden | hidden |
| `g` | goal | opponents: solid, loose, very loose | the same |

## 9. Key map

| Keys | TABLE and ACTION | CARDS |
|---|---|---|
| `1`-`9` | seat prefix | rank |
| `f c x b r a` | fold, call, check, bet, raise, all-in (ACTION) | `c` club, `a` ace |
| `w`, `l`, `Shift+W` | winner, hero lost, split | |
| `Space` | follow the coach | |
| `Enter` | accept; close the round; skip the board | leave |
| `n` | next hand | next hand |
| `Backspace`, `z`, `Ctrl+Z`, `Ctrl+Y` | undo, redo | delete the last card |
| `e`, `Left`, `Right`, `Delete` | edit on the hand line | |
| `Tab` | next live opponent | next slot |
| after a digit: `s e t m o d h k Delete` | stack, name, type, note, sit out, button, hero, bust, clear | |
| `[ ]`, `{ }` | button; table size | the same |
| `+ = -`, `, .`, `< >` | blinds; players left | the same |
| `Shift+S`, `Shift+B`, `Shift+A` | stack sweep, blinds, ante kind | |
| `i g v p q y / ?` | tournament strip, goal, unit, pause, what-if, history, palette, help | `/ ?` |
| `Esc` | cancel the prefix or field | leave |

Keys are captured on the document. An open amount field takes digits and its suffix letters; an open text field takes everything but `Enter` and `Esc`.

## 10. Intents the browser sends

`new_hand`, `cards {slot, text}`, `act {seat, verb, amount?}`, `close_round`, `result {winners[]}`, `edit {index, ...}`, `remove {index}`, `undo`, `redo`, `discard_hand`, `button {seat | step}`, `stack {seat, text}`, `stacks {values[]}`, `seat {seat, op, value?}`, `level {step | text | ante_kind}`, `tournament {field, text}`, `table {size | move}`, `mode {name}`, `new {fields}`, `load {id}`. Text is parsed in Python, so the browser holds no poker rules.

## 11. Checked in the repository

- `cards.parse_hand` already accepts `AKs`, `kao`, `77` and exact cards; `parse_cards` refuses duplicates.
- `state._num` reads `12.5k`, `1.2m` and `12,500` but not `25bb`; `preflop.parse_amount` reads `bb` and `x`. The app needs the single parser of section 4.
- `preflop.parse_actions` defaults to 2.2bb for a first raise and 3 times the bet for a re-raise: the same defaults as step 3.
- Seat names disagree between modules: `ranges.position_name` prints `UTG(LJ)` six-handed and `UTG+2` for the second seat eight-handed, where `binary.seats` prints `LJ` and `UTG+1`. The app needs one label table keyed by players behind and should translate at the adapter.
- `state.record_remaining` time-stamps each change of players left and feeds `bust_rate` and `fold_clock`; the `,` `.` keys must go through it.
- `state.advance_button` and `action_order` already skip empty seats and make the heads-up button the small blind.
- The Spin ladder and starting stacks are in `tools/spin_sim.py`; `aof.POSITIONS[4]` is CO, BTN, SB, BB.
- Not verified: that an All-In or Fold seat refills at 8bb. It is a setting for that reason.
