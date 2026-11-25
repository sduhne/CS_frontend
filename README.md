# Poker coach

A tournament no-limit hold'em coach: it tracks your table from the pictures
you send and answers "call, raise or fold?" with a tight-aggressive strategy
tuned to get you into the money.

It has three parts:

- **The engine** (`poker_coach/`, pure Python, no dependencies): hand
  evaluator, equity calculator, ICM model, push/fold equilibrium solver,
  preflop charts, postflop advisor and a table tracker.
- **The coach** (Claude, following `CLAUDE.md` and `PLAYBOOK.md`): reads your
  pictures, keeps the table up to date, runs the engine and gives you the
  answer in one line.
- **The table app** (`poker_coach/app/`): the same engine behind a page in
  your browser, for when you want to run it yourself.
- **The quick guide** (`guide/`): a page that looks the play up from tables
  made by the engine. No program runs behind it. It comes first below.

## The quick guide

Cards, seat, stack in big blinds, what happened before you: the play, one
sentence of why, the numbers behind it and the whole chart, at once. Nothing
is worked out while you play: every answer is read from tables that
`tools/build_guide.py` made by asking the engine about each of the 169 hands
of every spot before the flop (109,188 spots, 42,881 different tables: every seat, 28 stack
sizes, five sizes of a raise and four of a re-raise, three kinds of opponent, two styles), and
for spins its own tables (47,868 spots, below).

**To open it:** double-click `guide/index.html` ("Open Quick Guide.bat" on
Windows). It is a page on your own computer: no Python, no internet. On a
web server it is a folder of files (`deploy/README.md`).

**To use it:**

- **Game:** Tournament, or Spin & Go (three players, no ante, one prize:
  "Spin & Go" below).
- **Your cards:** tap two ranks, then Suited or Offsuit; or tap the hand in
  the chart. On a keyboard: `a k s` is ace-king suited, `o` offsuit,
  Backspace clears, the arrows move the stack, `n` is the next hand.
- **Before you:** nobody in, limpers, a raise (and who raised, with how many
  callers), an all-in, a raise and a re-raise, a raise and an all-in, two
  all-ins. If you already raised: a re-raise, an all-in, or a re-raise and
  an all-in behind you. If you re-raised: the raiser moved all-in.
- **How much they raised:** under a raise, "Raised to" 2bb, 2.2bb, 2.5bb,
  3bb or 4bb+ (read as 4bb). It starts from the usual size for the stack
  and stays as you set it for the next hands. When your own raise is
  re-raised, "Re-raised to" has four sizes: 2.5, 3, 4 and 5 times your
  raise.
- **Your seat** and the number of players (2 to 9). "Next hand" moves your
  seat on by one and clears the cards. Its button, with Reset, is in the bar
  at the top, which stays in the window while the page scrolls; once the
  answer has scrolled out of sight the bar shows it in one line (a tap on
  it goes back up).
- **The table map** under the seats: the table from above with your seat at
  the bottom, every seat's name, the dealer button (D) and who has raised,
  called or moved all-in in the spot you chose. Play goes clockwise. Where
  the spot asks who raised or moved all-in, tap that seat on the map.
- **Reset:** the round arrow beside "Next hand", or "Reset everything" under
  the choices, puts every choice back to the start. For eight seconds, or
  until you choose something else, the same button says Undo.
- **Stack in big blinds:** the smaller of yours and the biggest stack that
  can still call you. Against an all-in, its size.
- **Opponents** (Standard, Tight, Loose), **Style** (Play to win, Tight) and
  **Stage** (Normal, Bubble).
- **Blinds** (Regular, Turbo, Hyper): how fast the levels go. It changes no
  answer (see "Turbo and hyper-turbo" below); it turns on the blinds clock.

**What it shows:**

- The play and its size, and whether it is close.
- "They raise 36%. You have about 37%. The price is 18%. This hand needs
  32%": the range the table assumes, your equity against it, the price of
  the call and, in the big blind, what this hand needs once the part of
  its equity it keeps after the flop is counted.
- **If the hand goes on:** what to do with the same hand if you are
  re-raised, if a player moves all-in behind you, or both. One tap opens
  that chart.
- **The blinds clock** (Turbo and Hyper): your stack now, when the big
  blind reaches you, and after a whole round of folding, each counted in
  the big blinds of that moment; and how often an all-in from your seat
  gets through now and then.
- **Your hand at every stack:** under the answer, the same hand in the same
  spot from 2bb to 100bb ("2 to 15bb all-in, 16bb and more raise"). A tap
  sets that stack.
- **The chart:** all 169 hands of the spot, coloured by play, with the share
  of hands for each. A cut corner marks a close one. **Every stack** turns
  it into a push/fold sheet: for each hand the deepest stack at which it
  still goes in for everything (moves all-in, or calls an all-in). A dot
  marks a hand that folds at some shorter stack too, a yellow line one that
  is still played with a deeper stack, by a raise or a call.
- **After the flop:** rules of thumb from the playbook, by your hand, the
  bet you face, the street, the board and the chips behind.

**What the answers are.** The engine's, counting chips only (no prizes), with
a big blind ante and equal stacks. **Play to win** opens wider than the
coach's tight ranges and, from the cutoff and the button, calls and
re-raises a raise with more hands (`PLAYBOOK.md`, "Play to win"); **Tight**
keeps the tight ranges. In both, the big blind's call of a raise is tested
hand by hand against its price, at every stack: a small raise is called
with many hands, a big one with few (the same section, with a solver's
numbers beside it). **Bubble** folds the close plays and asks 10 points of
equity more before calling an all-in: a rule of thumb, not a prize
calculation. For real stacks and prizes the table app is exact.

**Turbo and hyper-turbo.** With the same stack, seat and action in front,
the right play is the same in a hyper-turbo as in a slow tournament: the
cards, the blinds and the antes of the hand are the same. So there is one
set of tables for every speed, and the Blinds choice changes no answer.
What a fast structure changes is which stacks you play (short ones), what a
fold costs, and how much a thin edge is worth passing. The guide answers
each of the three:

- **Short stacks are where the tables had to be right, and under 10bb they
  were not.** The engine's solver, like the usual push-or-fold chart, sets
  an all-in against one caller at a time and deals every opponent a hand
  from a full deck. With a few big blinds neither holds. A short all-in is
  often called twice: with 3bb and nine players the tables moved all-in
  first to act with 84% of hands where the exact answer is 26%. And the
  players who folded hold mostly middle and low cards, which are then
  rarer on the board: with 6bb the big blind called a cutoff all-in with
  65% of hands where the answer is 47%. All-ins of 20bb or less are now
  read from an exact solution of the game (real cards, every showdown and
  side pot, tables of 3, 4, 5, 6 and 9 players, solved at 2 to 10bb and at
  12, 16 and 20bb: `poker_coach/short.py`, `tools/build_short.py`). Up to
  10bb, where every hand is an all-in or a fold, that is the whole answer;
  from 11 to 20bb it is what an all-in earns first in and every call of an
  all-in. Those tables say "Solved exactly".
- **The clock.** A round of folding costs the two blinds and the ante, and
  the blinds rise meanwhile: 12bb on the button of an eight-handed table is
  8.3bb a round later at regular speed, 7.2bb in a turbo and 5.3bb in a
  hyper. The levels are taken as about 12, 6.5 and 3.5 hands, each about a
  fifth higher (the coach's tournament model, fitted to GGPoker fields;
  hyper-turbos were not measured).
- **Close plays.** A play the tables mark close is worded "take it" in a
  turbo or a hyper: there is no better spot to wait for.

`PLAYBOOK.md`, "Turbo and hyper-turbo", has the numbers and what they were
checked against.

**Spin & Go.** The Game choice at the top switches to spins: three players
(two once one is out), no ante, one prize, so chips are money. You type
every seat's stack, as the table shows it (tap a seat's name, then the
numbers set that seat); "Next hand" moves the stacks on with the players.
The tournament tables are made with a big blind ante, 2.5bb in the pot
before the cards where a spin has 1.5bb, and are much too loose for a spin:
with 9, 6 and 5bb the button moves in with 49% of hands there and 38% in a
spin, and the big blind with 5bb calls that all-in with 89% there and 42% in
a spin. Being the chip leader changes nothing (the chips over the second
stack never change hands), nor does the buy-in. The spin tables
(`guide/spin.js`, loaded the first time the game is chosen) are the
engine's answers at every configuration of an exact solution of the spin's
all-in or fold game with unequal stacks (`poker_coach/spin_exact.py`,
`tools/build_spin_exact.py`): two stacks of X and one of Y in any seat, X 2
to 30bb, Y from 1bb, heads-up 1 to 30bb, 491 games, with the best replies to
loose callers and to tight players for Opponents. Up to about 10bb that is
the whole answer; deeper, the all-ins and calls of all-ins, beside the
engine's raises, calls and limps (checked against published spin solver
figures). Play to win only. Games that pay second place (x10 and up) are
not covered: the table app with the prizes typed. `PLAYBOOK.md`, "Spin & Go
in the quick guide", has the numbers and the checks.

**Limits.** Stacks are taken as equal. Spots with three players in the pot
are made for the big blind and four first seats, and the page says so when
yours is read from a neighbour; two all-ins with 20bb or less have a table
for every seat, from the exact solution. A stack between two of the 28 on
the grid is read at the nearest. A raise bigger than 4bb is read as 4bb. A
raise of two fifths of the raiser's stack or more is priced as an all-in,
with the hands that player moves all-in with, so the answers step there (2bb
into a 5bb stack, against 2bb into 6bb); behind callers the page does not
offer that size (read it as two all-ins). The wider opening rows are written
by hand from standard ranges, not solved, and the share of its equity a hand
keeps in the big blind is a formula set against a solver's published fold
rates, not a solver. After the flop it is rules, not a solver. The exact
answers for all-ins of 20bb or less are for a big blind ante (GGPoker's ante
is paid by every player: the same money at eight players, a slightly
different game with 2 to 4bb and at a short-handed table). First in they are
for players who call correctly: the Opponents choice does not move them. It
moves the calls, through the hands an all-in player is taken to hold: with
Standard the solved range itself up to 10bb, and a little tighter from
there, a tenth at 20bb, as the deeper tables assume. Their numbers come from
dealing cards: every hand 10,000 times, and the hands that came out near
zero another 100,000 times, which leaves those good to about 0.02bb with
6bb, 0.03bb with 10bb and 0.06bb with 20bb. A play within 0.05bb (0.1bb with
20bb) is marked close, and inside that band a hand can still be in from one
seat and out from the next. With two players all-in before you only the
first pass was run: those numbers are good to 0.05bb with a few big blinds
and 0.2bb with 20, and a play within 0.15bb or more is marked close. Between
two solved stacks (11, 13 to 15, 17 and 18bb) the numbers are read off a
straight line. Tables of 7 and 8 players are read from the nine-player
solution (at eight that costs about 0.001bb a hand). Behind a player who
only called with 6bb or less, they are that player's all-in with a caller's
hands in its place. On the Bubble stage a call read from them must have 10
points of equity to spare, hand by hand. Checked in headless Chromium on
Linux only.

It is a chart. Most real-money sites forbid charts and outside help while
you play: use it to study, to review hands and where help is allowed.

```bash
python3 tools/build_short.py                 # the exact answers for all-ins of 2 to 20bb -> poker_coach/data/short.json, about four hours (needs gcc)
python3 tools/build_guide.py                 # all the tables again -> guide/data.js, about 40 minutes on four processors
python3 tools/build_guide.py --only open --styles win    # some of them; finished jobs are kept in guide/.cache
python3 tools/build_guide_page.py out/       # the page as one file, with data.json and spin.json beside it
python3 tools/build_spin_exact.py --work DIR     # spins solved exactly with unequal stacks -> poker_coach/data/spin_exact.json, about two and a half hours (needs gcc)
python3 tools/build_spin_guide.py            # the Spin & Go tables -> guide/spin.js, about an hour and a half on four processors
python3 -m unittest tests.test_guide tests.test_short tests.test_spin_exact   # about a minute
python3 -m poker_coach clock --stack 12 --pos BTN --players 8 --speed hyper    # the blinds clock in words
```

## The table app

A page in your browser where you enter the table by hand, typing or clicking
what you see, and the coach answers each of your decisions: the action and
its size, one reason, the number that decides it and the range chart. Nothing
reads the screen, nothing clicks for you and nothing leaves the computer: the
program is a small server on 127.0.0.1 written with Python's standard library
alone, and the page is plain HTML, CSS and JavaScript with its fonts beside
it. It is for study and play money; real-money sites ban real-time help.
The program calls itself Menlo Coach: that is the name on the page, the
title the starter gives its black window, and the name in the small window
of the .exe. The files keep "Poker Coach" in their names.

**Start it.** On Windows, double-click `Start Poker Coach.bat`: it needs
Python 3.10 or newer, installs nothing and works offline (`START HERE.txt`
says the same in a few lines). Anywhere:

```bash
python3 -m poker_coach app                      # http://127.0.0.1:8765/, and the browser opens on it
python3 -m poker_coach app --port 9000 --no-browser --folder ~/my-tables
python3 -m poker_coach app --verbose            # also print every request, and the detail when the coach cannot answer
```

A black window stays open while it runs; closing it, or Ctrl+C in it, stops
the coach. When port 8765 is taken it moves to the next free one and says so.
Started a second time on the same folder of tables, it opens the page of the
copy that is running and ends: two copies would save over each other.
`Build exe.bat` (or `python tools/build_exe.py --check`, with `pip install
pyinstaller`) makes `dist/PokerCoach.exe`: the same app as one program that
needs no Python. It has no black window; a small one shows the address and
a Stop button. Build it on the computer you use it on.

**Three modes**, each with its own saved table (the tabs in the header, or
Alt+1, Alt+2, Alt+3):

| Mode | The table | What answers |
|---|---|---|
| Tournament | 2 to 9 seats, blind levels, players left, places paid, payouts | The engine with ICM, as `advise` does, and before the money the survival guard (see the styles below) |
| Spin & Gold | 3 seats or 6 (6-Max), down to heads-up as players go out, winner takes all unless you type the prizes, a tally of games and wins | Three players or two: the spin tables on chips; the engine above 16 big blinds (20 from the small blind and heads-up). Four to six players: the engine with all moves, on chips. With two prizes or more typed: the engine by ICM |
| All-In or Fold | 4 seats, stacks cut to 8 big blinds at the deal, the fee, the session's result in big blinds | The solved All-In or Fold tables |

You are always seat 1, and seats count clockwise from you.

**A hand.** `N` deals. Type your two cards (`a k s` is ace-king suited,
`a h k d` the exact cards), then what happens, player by player. The seat
whose turn it is at the table is yellow, and the row above the action bar
names it: RECORDING with that player's position and seat, or YOUR ACTION
when the turn is yours. The letters `f c x b r a` record that player's
action and the yellow seat moves on. The order is the table's: before the
flop it starts with the player after the big blind, after the flop with the
first player after the button (the small blind, when that player is still
in). `Enter` gives the players in front of you their fold (or check) at
once and the letters are yours; `Esc` takes that back. A seat's digit first
gives one action to that player, whatever the row says. An opponent's bet
or raise is taken at the usual size and `E` changes the amount; your own is
typed. The coach's answer is on screen from the start. While players in
front of you have not acted it says what it takes for granted ("If they
fold", "if BB and CO check"), and `Space` does what it says and records
their folds or checks with your play. After the flop type the board
(`k s 7 d 2 c`); the coach then needs your exact cards. Undo is
`Backspace`, as often as you like, back to the first table of the session.

If you would rather be asked for your own decision at once, choose "My
decision first" under Order of action in Settings: the players in front of
you are then taken to fold or check until you type an action for them.

**The keys.** `?` on the page lists them; the list is made from
`poker_coach/app/defaults.py`, so it is always the current one.

| Key | What it does |
|---|---|
| `N` | New hand, next hand. Spin & Gold: a new game of 300 chips once one is over (`Shift+N`: of 500 chips) |
| `Space` | Do what the coach says |
| `F` `C` `X` `B` `R` `A` | Fold, call, check, bet, raise, all-in. Your own bet or raise: type the amount, then `Enter` |
| `Enter` | Before your action: the players in front of you fold (or check) and the keys are yours. After it: the rest fold (or check). While a street's cards are wanted: skip the board. While a split is ticked: split |
| `W` `L` `Shift+W` | You won the pot; you lost a heads-up pot; split pot (three or more players: tick who shares it with the seat numbers, then `Enter`) |
| `Backspace` `Z` `Ctrl+Z` | Undo. `Ctrl+Y` or `Ctrl+Shift+Z`: redo. `Ctrl+Backspace`: discard the hand |
| `Left` `Right` | Previous and next step of the hand. `E` changes the amount of the selected bet (or of the last one), `Delete` deletes the selected action |
| `[` `]` | Dealer button one seat back, one seat forward |
| `{` `}` | One seat fewer, one seat more |
| `+` (or `=`) `-` | Blinds up, blinds down. `Shift+B`: type the blinds (`300/600/75`, or `600` alone). `Shift+A`: ante none, every player, big blind |
| `,` `.` `<` `>` | Players left minus one, plus one, minus ten, plus ten |
| `S` `Shift+S` `O` | Your own stack; every stack, clockwise; sit out and back in |
| `I` `G` `V` | Players left, typed in place (Spin & Gold and All-In or Fold: the settings); style (Spin & Gold and All-In or Fold: the opponents); chips or big blinds |
| `Y` `?` | Hand history; the list of keys |
| `Alt+1` `Alt+2` `Alt+3` | Tournament, Spin & Gold, All-In or Fold |
| `Esc` | Cancel, close. In a field: the old value comes back and nothing is sent |
| `1` to `9` | A seat, counted clockwise from you: its menu opens and the next key is for that player. In All-In or Fold, during a hand, the digit alone is that player's all-in (again takes it back) |
| then `F` `C` `X` `B` `R` `A` | That player folds, calls, checks, bets, raises, moves all-in. `W`: that player won the pot |
| then `S` `E` `T` `M` | Stack, name, type, note |
| then `O` `D` `K` `Delete` | Sit out or back in; dealer button here (an empty seat too); bust (the seat is cleared and one player fewer is left); clear the seat (the player left the table) |
| after `T` | `N` nit, `T` tight, `G` tight-aggressive, `L` loose-aggressive, `O` loose, `S` calling station, `M` maniac, `U` unknown |
| Cards | `a k s`, `a k o`, `7 7`: your hand as a class. `a h k d`: exact cards (suits `s` `h` `d` `c`, `t` is the ten). The flop is three cards, the turn and river one. Once the flop is out and your hand was typed as a class, only its suits are asked. `Backspace` goes back one step, `Enter` skips the board when the action is not on you, `Esc` leaves the cards |

**The seat that is up is yellow.** The player the next action is recorded
for, you or anybody else, has the Menlo yellow frame, and the line above the
action bar names that seat in yellow. A white frame is a seat that is only
selected (its menu is open).

**With the mouse.** Everything has a button. The tabs in the header change
the mode; the strip under it has `-` and `+` for the level and for players
left, and a click on the level, players left or places paid lets you type
it. At the top right are Undo, Redo and Settings (the three lines); the
style and moves at the head of the coach's answer open Settings too. A click
on a seat opens its menu: stack, name, type, note, Sit out, Button, Bust,
Clear, and Save (a seat's stack, name and note are saved with `Enter` or
Save, never by clicking elsewhere). Table tools, at the table, has Button
back and forward, - Seat and + Seat, Every stack, New table (a table move:
you and the tournament stay), Skip a hand and Discard hand. The action bar
has six places that never move: Follow (Next hand once you have folded or
the hand is over), the four moves, and Rest fold. A click on the bar counts
once the button under the pointer has stood there for a moment (400 ms), and
not while a change is still on its way: a double-click on Next hand deals
one hand, and a double-click on Fold folds one player. A button that does
not take a click yet is drawn dimmer while the pointer is on the bar. For a row of folds
use Rest fold or the keys. A click on a step of the hand line selects it
(Amount, Delete); on a fold the app made for a player it offers Called and
Raised. Under the answer, Why and Range show the reasons and the range
chart. The hand history has Copy as text, and a click on one hand shows its
text with Copy this hand.

**In a small window.** When the window is shorter than the page (half a
screen beside another program, or a zoomed page), the answer stays at the
top and the action bar at the foot. The table takes a shorter form first:
in one column the line under the answer gives its row to the table and its
button, Why, moves into the answer's first row; from 852 wide and at most
660 high the answer stands beside the table. What still does not fit
scrolls inside the table's own box, which rests on your cards, the board
and the pot. A seat you aim at comes into sight, and the menus open over
the head of the page. A 1440x900 screen at 150% (a window of 960x600) shows
the whole table.

**Typing amounts.** `1300`, `12.5k`, `1.2m`, `25bb`, `3x` (three times the
bet being raised), `66%` (of the pot, for bets), `+3k` and `-1500` (a stack).
`12.500` and `12,500` are twelve thousand five hundred; a bare `12.5` is
refused with the spellings that work. With numbers in big blinds (`V`) a
bare number in a stack or bet field is big blinds. All-In or Fold counts
everything in big blinds, with decimals. What cannot be read stays in its
field with the reason under it.

**What the table does for you, and what it refuses.**

- An action typed for a player the app had folded for you puts that player
  back: on the street being played it takes the place of the fold; from an
  earlier street the fold becomes a call there, and one undo takes it back. A fold you
  typed yourself is changed on the hand line. Nothing of this ever changes
  an action of your own.
- While a street's cards are wanted, a forgotten call or check can still be
  added to the round just closed. A bet, raise or all-in for such a player
  is refused: "Type the flop first (K S 7 D 2 C), then record the bet." So
  is a fold for a player whose check in that round the app only assumed:
  "Type the turn first (5 H), then record the fold."
- The dealer button moves by the dead-button rule (Settings, Table): after
  a bust the big blind still moves on by one player, so the button can
  stand on an empty seat for a hand. The other choice is a forward-moving
  button. After a bust in the blinds the page says where the button is;
  check it against your table, and `[` `]` move it from player to player
  (onto an empty seat, a dead button: that seat's number, then `D`). A dead small blind
  cannot be entered. Once a hand has an action the button cannot be moved:
  undo, or discard the hand.
- A change made in another window is noticed: "The table had changed: look
  again and repeat."

**The tournament settings** (Settings: the three lines at the top right;
`I` goes straight to players left, `G` to the style). Players left and places paid tell the coach how far the money
is; without them it counts chips only and says so. A typed payout list
(`1:1000 2:600 4-6:200`) replaces the typical prizes. In a very large field
(more than 1,000 paid places still to reach) the same prize maths is worked
out by a closed formula, so that an answer still comes in under half a
second: nine players at 150,000 entrants were measured. Nothing is
merged, so three places from the money are three places. From 8,000 to
150,000 entrants the formula was within 0.02 points of risk premium of the
exact maths. On the command line `advise`, `quick` and `icm` use the same
formula under the same condition.

*Styles.* What differs is what happens before the money, when a play would
put a third or more of your chips at risk. The coach then also looks the
hand up in the all-in or fold chart, which is built to reach the money.

- *Survive, then win* (the default). If the chart would fold and the play
  is worth little by the numbers, the answer is FOLD and the play by the
  numbers is the second line. Little is: an all-in worth less than 0.20 big
  blinds against folding, plus 0.02 for every big blind at risk above 10
  (0.24 with 12 at risk, 0.42 with 21, 0.60 with 30); a play the numbers
  themselves call close; a call only a few points better than its price.
  A play with a clear edge is made. With 17 big blinds or more, a fold of
  an all-in becomes the sheet's small raise where the sheet has one. A
  close answer shows the lower-variance side first.
- *Cash first*. Stricter: such a play is made only when the chart makes it
  too, and a min-cash counts double until the bubble bursts.
- *Max EV*. Plain prize maths: no guard, and a close answer is shown as the
  numbers have it.

Switch to Max EV when you play to win and a min-cash means little, or to
see what the numbers alone say. Switch to Cash first when reaching the
money is the aim. In every style a good price is never folded (3 to 1 or
better), the guard is off in the money and while re-entry is open, and a
read on a player lifts it only when it makes the play safer.

Close to the money the chart is read at twice your stack, and its limit is
said in your own chips: "all-in up to 10.5bb this close to the money (21bb
far from it)", under a chart headed "24.8bb (twice your 12.4bb)".

*Moves.* All moves, or All-in or fold only: one decision a hand, from the
all-in or fold charts, with the play with all moves as the second line.
Against an all-in, a call that the play with all moves makes for less
than a third of your stack at a good price is made in that plan too.

*How the coach reads the table.* An all-in under 3 big blinds (or of less
than a full raise) that another player raised over counts as a call, so
that raise is the first raise and not a re-raise. A blind that is all-in
from posting is not counted as a caller. Two players who are both in for
your whole stack are read as two all-ins. When you may not raise and nobody
left in the hand can match more than the call, an all-in would only be
that call, and the answer says CALL. And when you called earlier in the
hand, a raise that costs a fifth of the pot or less (5 to 1 or better) is
called whatever the hand. Not on the bubble for a third or more of your
chips: there the coach folds and the small line says why.

**The small line under an answer** says how much of the prize money is
counted and where the answer comes from. In that line "table" means the
all-in or fold chart.

| It says | It means |
|---|---|
| ICM off · chip EV | Players left or places paid are missing: only chips are counted |
| ICM estimated | Prizes are the typical ones and the other tables' stacks are guessed: enter the average stack |
| ICM, ICM exact | Your numbers are in; exact with a prize typed for every paid place |
| the engine decides | The play by the numbers; the guard had nothing to say |
| the all-in table agrees | The play risks a third of your chips and the chart makes it too |
| CLEAR EDGE (engine +0.50bb, needs +0.42bb): played although the all-in table folds | The chart would fold; the edge is over what this stack at risk takes, so the play is made (Survive, then win) |
| SURVIVAL FOLD (engine: ALL-IN +0.13bb) | The chart folds and so does the coach; the bracket is the play by the numbers |
| SURVIVAL RAISE (...), SURVIVAL CALL (...) | The sheet's small raise, or the big blind's sheet call, in place of an all-in |
| CLOSE: before the money the lower-variance side leads (engine: ...) | Two plays worth about the same: the quieter one is shown first |
| SHEET FOLD (engine: CALL, 41% against 33%): before the money the big blind calls with the sheet's short list only | Big blind against a raise: a call by the price with 7 points or more to spare, but not a hand on the sheet's list |
| a call at 5 to 1 or better after calling is never folded | You called earlier in the hand and the raise costs a fifth of the pot or less |
| the sheet's rule (on the bubble the price alone is no call for a third or more of your chips) | You called earlier and the raise is cheap, but on the bubble that call would cost a third or more of your chips |
| the plan made with your call before the flop: the stack goes in with an overpair, top pair or better | You called a re-raise before the flop on that plan and hold such a hand: no fold |
| GUARD OFF (why) | The guard is off or steps aside: in the money, final table, Max EV style, re-entry open, too short to wait, the fold clock says you cannot fold, a good price, a read that makes the play safer |
| after the flop: equity against an estimated range, a rule-based line | Every other answer after the flop |

**While the coach works** on a new spot the answer panel says "Updating".
An answer made for an earlier table is never shown over a new one.

**When an answer looks wrong.** Open the hand history (`Y`), press Copy as
text (or click the hand and Copy this hand) and send it with the style and
moves, players left and places paid, and the small line under the answer.
The text has the blinds, a "Seats:" line with every player's seat, position
and stack before the hand, and every bet in chips ("raise to 1,320
(2.2bb)"): enough to play the hand again. After the flop, say whether the
players in front of you had acted. NO ADVICE means the coach could not read
the spot: start the program with `--verbose` and send the lines the black
window prints after "the coach could not answer a spot:".

**Where things are saved.** In `tournament/app/` in this folder, after every
change:

- `tournament.json`, `spin.json`, `aof.json`: one per mode (the table, the
  hand, the undo steps, the last 500 hands);
- `<mode>.json.bak`: that table one change earlier. It is used, and the page
  says so, when the main file is damaged or missing;
- `<mode>.json.unreadable-<date-time>`: a damaged file, set aside. When
  there was no good copy to go on from, the page says so, on the first-run
  form too, and the notice stays until you dismiss it or change something;
- `app.json`: the mode on screen, chips or big blinds, the deck;
- `app.lock`: there while the program runs, so that a second start finds
  the first.

The next start goes on from there. To start a mode from nothing use New
tournament (New game) in Settings, or delete that mode's file and its
`.bak`. `--folder <path>` saves somewhere else, and so does the
`POKER_COACH_APP` variable (`--folder` wins). The packaged program saves in
`PokerCoach/app` in your home folder.

**Changing it.** What a user would want to change is plain data in
`poker_coach/app/defaults.py`, with a comment on every line:

- the blind levels (`REGULAR_LEVELS`, `TURBO_LEVELS`, `SPIN_LEVELS`: small
  blind, big blind and ante of each level) and which a new session starts
  on. One tournament's own levels need no edit: paste them under Blind
  levels in Settings and press Use these levels;
- starting stacks and table sizes (`START_STACK`, `TABLE_SIZE`), the All-In
  or Fold cap and fee (`AOF_CAP_BB`, `AOF_FEE_BB`), who pays the ante, the
  dealer-button rule (`BUTTON_RULE`);
- the bet and raise sizes offered as buttons (`OPEN_SIZES_BB`,
  `RERAISE_SIZES`, `BET_SIZES`), the default style and moves (`STYLE`,
  `PLAN`);
- the key map (`KEYS_TABLE`, `KEYS_SEAT`, `KEYS_TYPE`): change a key there
  and both the page and its `?` list follow.

Start the program again after an edit (and build `PokerCoach.exe` again: the
file is inside it). The numbers the coach itself uses (when the guard looks,
what a thin edge is, how close "close to the money" is) are at the top of
`poker_coach/app/advice.py`.

**The code.** `model.py` holds the table and the rules of a hand (every
change is one intent, such as `{"op": "deal"}`, and a hand is replayed from
its list of events), `advice.py` turns the table into the engine's question
and the engine's answer into the panel, `server.py` serves the page and four
addresses (`/api/view`, `/api/intent`, `/api/advice`, `/api/ping`),
`static/` is the page. The design notes are in `docs/table-app/`.

```bash
python3 -m unittest tests.test_app_model tests.test_app_advice tests.test_app_server tests.test_app_package   # about 500 tests, three minutes
```

**Limits.**

- It has been checked in headless Chromium on Linux only. It has never been
  run on Windows: not the .bat files, not a Windows `PokerCoach.exe`, and no
  other browser. `Build exe.bat` ends with a check that starts the program
  it built and asks it for the page, the fonts and an answer in each mode,
  and says what failed. If it does not start, the text in the black window
  says why; if the page misbehaves, the browser's console (F12) does.
- Window sizes, in that same browser only: 960x600, 853x533 and 683x650
  show the whole nine-seat table. 560x600 and 1093x514 (a 1366x768 screen at 125%) hide the two seats at
  the table's upper edge until you scroll its box, 1024x476 the upper four. Under about 480 high the
  table's box is a strip, and under 544 wide the page scrolls sideways.
- Advice after the flop is heuristic: your equity against an estimated
  range, then rules. It is a baseline, not a solver.
- A dead small blind cannot be entered.
- Spin & Gold after the flop uses the tournament's range charts.
- The PDF sheets printed in earlier sessions are older than the rebuilt
  tight-aggressive sheet. The text from `tag-sheet` is the current one.
- Study and play money only. It does not read the screen, click for you or
  hide from a poker client, and it is not meant to.

**On your own site.** The same program can run on a server, behind a web
server that asks for a login, at an address such as
`https://menlo.bet/coach/`: [deploy/README.md](deploy/README.md) has the
steps, a systemd unit and the Caddy lines. The answers are the same; the
tables are then kept on the server, so a phone and a computer see the same
table. It keeps one table per mode for one user and has no login of its own.

## How to use it

Open a Claude Code session on this repository and talk to it.

1. **Start of the tournament.** Send a picture of the table, and if you can,
   the lobby (entrants, places paid, starting stack, payouts). Say which
   player is you if it is not obvious.
2. **When something changes.** Send a new picture: a player busts or sits
   down, blinds go up, you change table, the lobby shows fewer players left.
   One picture every level or two is enough; send more near the bubble.
3. **When you want help.** Send the picture of the hand, or just type it:
   "AJo on the button, folded to me", "99, UTG raised to 1300",
   "AK on K72, he bets 1500 into 3000". You get the action first, then the
   one-line reason.
4. **Tell it what you notice.** "Seat 3 raises every hand", "Carl only shows
   aces": the coach tags the player and the ranges it assumes for them change.

Things worth knowing:

- The coach needs **players left** and **places paid** to know how close the
  money is. Without them it plays on chip maths only.
- It assumes stacks as of the last picture. If your stack changed a lot, say so
  or send a picture.
- The default goal is `itm`: before the bubble bursts, cashing counts double,
  so the coach folds more marginal all-ins than a pure prize-money calculation
  would. Say "play to win" (or `set goal=balanced` / `goal=chips`) to change it.

## What the engine does

| Piece | What it gives you |
|---|---|
| Equity | Exact preflop all-in equity for any hand against any range (precomputed 169x169 table), exact turn/river and Monte Carlo flop equity |
| ICM | Tournament value of your stack for any field size: your table's stacks exactly, the rest of the field as average stacks. Matches brute-force Malmuth-Harville |
| Push/fold solver | Finds the shoving and calling ranges that are best responses to each other for the real stacks, positions and payouts; also re-shoves over a raise |
| Preflop | Open, 3-bet, call, re-shove, call-a-shove decisions by position, stack depth, ICM and player type |
| Postflop | Your equity against the opponent's range, narrowed by what they did on each street; pot odds, implied odds, commitment and ICM |
| Table tracker | Seats, stacks, button, blinds, players left; who busted since the last picture; a fold clock that says whether you can fold into the money |

Try it directly:

```bash
python3 -m poker_coach quick --hand AJo --stack 11.5 --pos CO
python3 -m poker_coach quick --hand AQo --stack 25 --pos BB --facing "BTN allin" \
    --remaining 78 --paid 75 --entrants 500
python3 -m poker_coach chart push --pos BTN --stack 12
python3 -m poker_coach equity --hand AKo --vs "QQ+, AKs"
python3 -m poker_coach --help
```

`CLAUDE.md` lists every command the coach uses; `PLAYBOOK.md` is the strategy
in plain words, worth reading once before you play.

## All-In or Fold

A second, self-contained part for the All-In or Fold format (four players, 8bb
stacks, shove or fold only). The game is small enough to solve outright:
`tools/aof_solver.c` finds the equilibrium with real cards, multi-way all-ins
and the per-hand fee, and the answers ship in `poker_coach/data/aof.json`.

```bash
python3 -m poker_coach aof --hand A5s --pos BTN --shoved CO   # all-in or fold, and by how much
python3 -m poker_coach aof-chart --pos SB --shoved CO          # the whole range for one situation
python3 -m poker_coach aof-sheet                               # all 14 ranges on one page
python3 -m poker_coach aof-quiz                                # drill in the terminal
```

`aof_trainer.html` is the same thing as a page: open it in a browser to drill
random hands and browse the charts, offline.

The solved table assumes opponents who call correctly. Real tables call too
much, so there are two more sets of ranges, each the best reply to opponents
who shove normally but call 1.5 times (`--vs loose`) or twice (`--vs
very-loose`) too many hands. `python3 -m poker_coach aof-compare` shows what
each set earns against each kind of opponent. The trainer page has the same
choice under Opponents.

Three things to know about this format:

- **It is a memory game.** There are only 14 situations. Learn the ranges with
  the trainer; there is no time to look anything up at the table, and sites
  forbid it.
- **The fee is the opponent.** About 0.1bb leaves every pot. If all four
  players played perfectly, each would lose about 2.5bb per 100 hands. You
  only win what the others give away by shoving and calling badly.
- **Approximations.** Unequal stacks are answered for the effective stack.
  Tournament mode is chip EV with no ICM. The fee is modelled as 0.1bb from
  every pot; it varies a little by stake.

## Late-registration min-cash plan

A calculator for one specific plan: enter at the very end of late registration,
play all-in or fold with the single aim of the first paid place, and sit out
once the stack can be blinded down safely.

```bash
python3 -m poker_coach latereg --stack-bb 12 --left 400 --paid 150 --entries 1000 --buyin 27.6 --fee 2.4 --min-cash 60
python3 -m poker_coach latereg-safe --stack 14000 --avg 52000 --left 180 --paid 150   # sit out yet?
python3 -m poker_coach latereg-chart                                                    # the wide, short-stack and tight charts
```

`latereg` forecasts how many hands pass before the bubble bursts (fitted to
how fast 13 GGPoker fields shrank, including the slowdown near the money),
adds up the blinds a folding player pays over them, and plays the printed
all-in charts hand by hand to get the chance of cashing; a solver's best
all-in or fold play is shown beside it. The short version of what it finds:
in an ordinary tournament (15% of entries paid, 40% to 50% still alive when
registration closes) the plan cashes about 18% in a turbo and 13% at regular
speed, and it needs 50%. It gets there only where about 30% of the entries
are paid. The details are in [PLAYBOOK.md](PLAYBOOK.md).

## All-in or fold for a whole tournament

For a player who wants one decision per hand. Three tables cover it: the
deepest stack at which each hand moves all-in when nobody has raised, the
hands that move all-in over a raise, and the hands that call an all-in.

```bash
python3 -m poker_coach binary --hand A8o --pos BTN --stack 12
python3 -m poker_coach binary --hand 99 --pos BTN --stack 15 --facing "CO raise"
python3 -m poker_coach binary --hand AJo --pos BB --stack 20 --facing "HJ allin 9"
python3 -m poker_coach binary-chart --pos BTN
python3 -m poker_coach binary-sheet --players 6        # the tables for a 6-handed table (6, 7 or 8)
```

Before the money the ranges are the play that earns the most prize money in
the late-registration model; in the money they come from the ICM solver.
Both are about half as wide as a chip-EV push/fold chart. It is a sound way
to play a short stack, which is what an entry at the close of late
registration has, and not a proven winner: the model has a late entry
returning -24% in a turbo. The details are in [PLAYBOOK.md](PLAYBOOK.md).

## Tight-aggressive sheet (6, 7 and 8 players)

Every preflop situation of normal tournament play as text, one sheet per
table size: nobody has entered, players only called, a raise, a raise and a
re-raise, your own raise re-raised or met by an all-in, and an all-in in
front, each by seat and stack.

```bash
python3 -m poker_coach tag-sheet --players 8      # or 7, or 6
```

The raise, call and re-raise lists are the engine's own answers for each of
the 169 hands, far from the money. Each list is the answer at one stack,
named in the sheet (against a raise: 60 big blinds). The all-in lists first
in and over a raise, and the calls of an all-in, are the all-in or fold
tournament tables. The rules are in [PLAYBOOK.md](PLAYBOOK.md). The lists
were rebuilt after the engine changed: PDF sheets printed before that are
older, and where they differ this text is right.

## Spins (3 players, or 6; winner takes all)

GGPoker Spin & Gold and games like it: three players, a random multiplier,
and in almost every game one prize. With one prize chips are money, so the
tables are the exact all-in or fold solution of the chip game, for three
players and heads-up at 2 to 30 big blinds, with a second set for tables
that call too much and rows for a limp or a small raise in front.

```bash
python3 -m poker_coach spin --hand K7s --pos BTN --stack 12
python3 -m poker_coach spin --hand A5o --pos BB --stack 9 --shoved BTN
python3 -m poker_coach spin --hand Q8o --pos SB --stack 11 --players 2 --vs loose
python3 -m poker_coach spin --hand KJo --pos BB --stack 14 --facing "SB limp"
python3 -m poker_coach spin-sheet
python3 -m poker_coach spin-odds --win 37
```

What the evidence says: the winner gets 2 buy-ins in 48% of games and 3 in
45%, the site keeps 7%, and break-even is 35.9% of games. In a simulation of
whole games the tables won 33.1% against players who call correctly and
36.4% at best against players who call far too much. Winning regulars
report 38% to 39%, and get there with small raises and play after the flop,
which all-in or fold leaves out. The details are in [PLAYBOOK.md](PLAYBOOK.md).

**Six players (GGPoker's 6-Max Spin & Gold).** In the table app, choose
"6 players (6-Max)" when you start a Spin & Gold session, or Table tools,
"New game: 6 players". The winner takes all at x4, x6 and x8, which is 95%
of the games; an x10 or x20 game pays two places. Type the prizes of such a
game where the strip says "Prizes" (first place first, `8 2`; in a narrow
window in Settings, `I`), and the coach counts them by ICM until two players
are left. With four to six players the answers come from the engine on chips
with all moves; from three players on, with one prize, from the spin tables.
Break-even is 17.9% of games (an even player wins 16.7%). The command line
has no six-player spin chart: `quick --players 6 --goal chips` answers a
spot. Prize splits and stacks come from one 2026 guide: read the prizes in
the lobby.

## Live table reader (play money and research)

The older program, from before the table app. It did not read the poker
client it was made for well enough, which is why the table app is entered by
hand. On Windows it starts with `Start Screen Reader (old).bat`.

A small program that watches a poker table on your screen and shows, in a
window that stays on top, what the coach would do. It never clicks: you
decide. It only gives advice at tables that show a play-money marker
("Play Money", "Play chips", "Practice"...); at any other table it says why
it is not reading. Real-money sites, and GGPoker and PokerStars even at
play-money tables, forbid real-time help.

How it works: it looks at the table several times a second and reads it
**on your computer**: no internet, no API key, no cost. The poker client
draws the same digits, card corners and dealer button every time, so the
reader compares each box on the table with examples you gave it once. The
same engine as `advise` (or the all-in or fold tables) turns the reading into
an action. A reading takes about 30 ms.

What the window shows when it is your turn:

```
ALL-IN
AKo · CO · 25bb · 6 players · UTG raises to 2.5bb        <- your cards, seat, stack, what happened before you
re-shoving wins the pot often enough, and you have real equity when called
their opening range ~17%; your equity vs it 59%; pot odds to call 34%
```

After the flop the yellow line is `AhKd on Ks7d2c · CO · 18bb behind · pot
15.2bb · checked to you · flop`, and the advice uses what it saw earlier in
the hand: who raised before the flop, who bet or called on each street.

```bash
pip install -r requirements-live.txt               # Pillow, mss, pydantic (+ tkinter, see the file)

python3 -m poker_coach live-app                    # one window: set up, teach, check, start

# or step by step:
python3 -m poker_coach live-setup --seats 6        # mark the table and every box on it, then label them
python3 -m poker_coach live-test --screen          # print what it reads right now: check it against the table
python3 -m poker_coach live-teach                  # label what it has not learned yet (--log: from the last session)
python3 -m poker_coach live                        # run (--mode binary or spin; --opponents loose)
python3 -m poker_coach live-setup --redo pot,s3_bet   # mark some boxes again
```

- **Setup.** Draw a box around: the play-money marker, the area where your
  Fold / Call / Raise buttons appear (when it is not your turn), the corner
  of each of your cards and of the five board cards (rank and suit), the pot,
  the dealer button itself and one opponent's face-down cards; then for each
  seat, clockwise from you: the stack, where its bet appears, where the
  dealer button sits when it is that seat's, and where its cards show. Press
  G for a new screenshot when you need cards on the board, S to skip an
  optional box, Backspace to go back. Keep the table window the same size
  and place afterwards, and keep the coach's windows off the table (what
  covers the table cannot be read; the window warns you).
- **Teaching.** It shows each box and you type what it says (12,450 · Ah ·
  Pot: 1,250). If a box has something that is not text (a chip icon) or
  digits that touch, it asks piece by piece. The same digit drawn a fraction
  of a pixel to the side is still recognised.
- **It never guesses.** A bet, a card or your stack that it is not sure of
  stops the advice: the window says NO ADVICE and what to teach. An unknown
  bet is never read as "nobody bet".
- **It waits for the table.** It advises after two readings in a row agree,
  and again when the spot changes. If your buttons show while a player
  before you still has cards and no chips in, it says WAIT (Read now
  overrides; Not my turn teaches it that look of the buttons).
- **Blinds and ante** are learned from the chips in front of the blinds
  before the flop; a raise and a re-raise from the blinds are not mistaken
  for a new level.
- **Opponents.** `--opponents loose` (or the launcher's choice) for tables
  that call too much, which is most play-money tables: ranges widen, bluffs
  go down.
- **The one program for Windows.** `python tools/build_exe.py` (with
  `pip install pyinstaller`) builds `dist/PokerCoach.exe`: no Python needed
  to run it. Double-clicked it starts the table app; `PokerCoach.exe
  live-app` opens this launcher, if Pillow, mss and pydantic were installed
  when it was built. It keeps its files in `PokerCoach` in your home folder.
  Build it on the computer you use it on.
- **Checked how.** On a drawn table, not a real client: 6,000 numbers in 15
  fonts and sizes at random sub-pixel offsets, none misread (unsure ones are
  asked); a whole hand followed street by street; random spots on every
  street with no crash and no illegal move. Your first setup on your client
  is the real test: use step 3, Check what it reads now.
- **Claude's vision instead** (`--reader vision`): sends the screenshot to
  Claude and needs an API key (`pip install anthropic`, `ANTHROPIC_API_KEY`).
  No box setup, about 2 to 3 cents a reading with the default model.
- **Session log.** Every advised reading goes to
  `tournament/live-log/<time>/reads.jsonl`, with the screenshots
  (`--no-save` keeps only the text), for review and for teaching.
- **Play money only.** At setup you box your client's play-money marker and
  type what it says; it must be one of the play-money words. Every reading
  checks the marker is still there, and without it there is no advice. Add
  your client's words with `--marker "Fun Table"`.
- **What it cannot see.** Player names (seats are numbered clockwise from
  you), checks (they leave no chips), and hands it was not running for. If
  it starts in the middle of a hand it treats opponents as callers and says
  so. Cards must have light faces, the usual deck.

## Limits

- Opponent ranges are estimates from position, stack and the type you (or the
  coach) tag them with. The answer is only as good as those reads.
- Postflop advice is rule-based on top of exact equity; it is a strong
  baseline, not a solver.
- ICM does not know the blinds are about to hit you. The fold clock covers
  that for short stacks.
- No strategy guarantees a cash. Tournaments pay about 15% of the field, so
  even strong players miss the money most of the time; this is built to stop
  the mistakes that cost cashes, not to promise one.

## Fair play

Most real-money online poker sites forbid real-time assistance, and using a
tool like this during a hand there can get an account closed and winnings
confiscated. Use it where outside help is allowed (home games that agree to
it, play money, training), and for studying spots and reviewing hands after
you play.

## Development

```bash
python3 -m unittest discover -s tests        # about 790 tests, eight minutes
```

The data files in `poker_coach/data/` are generated:

```bash
gcc -O3 -march=native -fopenmp -o gen tools/gen_preflop_equity.c
./gen 1500000 > poker_coach/data/preflop_equity.json          # about 10 minutes
python3 -c "from poker_coach.pushfold import build_charts; build_charts()"
python3 tools/build_aof.py          # All-In or Fold tables, about 35 minutes
python3 tools/build_aof_exploit.py  # ranges against loose tables, about 10 minutes
python3 tools/build_aof_page.py     # aof_trainer.html from those tables
python3 tools/build_latereg.py      # late-registration shove spots, about a minute
python3 tools/build_binary.py       # all-in or fold tournament tables, half a minute
python3 tools/build_tag.py          # tight-aggressive sheet for 6, 7 and 8 players, about a minute and a half
python3 tools/build_spin.py         # spin tables (3 players and heads-up), about 7 minutes
python3 tools/spin_sim.py           # whole spin games played with those tables, about 6 minutes
python3 tools/build_guide.py        # the quick guide's tables (guide/data.js), about 40 minutes; after any change to the engine before the flop
python3 tools/build_spin_exact.py --work DIR   # spins solved exactly with unequal stacks, about two and a half hours
python3 tools/build_spin_guide.py   # the quick guide's Spin & Go tables (guide/spin.js); after any change to the engine with three players or two
```
