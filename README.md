# Poker coach

A tournament no-limit hold'em coach: it tracks your table from the pictures
you send and answers "call, raise or fold?" with a tight-aggressive strategy
tuned to get you into the money.

It has two parts:

- **The engine** (`poker_coach/`, pure Python, no dependencies): hand
  evaluator, equity calculator, ICM model, push/fold equilibrium solver,
  preflop charts, postflop advisor and a table tracker.
- **The coach** (Claude, following `CLAUDE.md` and `PLAYBOOK.md`): reads your
  pictures, keeps the table up to date, runs the engine and gives you the
  answer in one line.

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
the 169 hands, far from the money. The all-in lists are the all-in or fold
tournament tables. The rules are in [PLAYBOOK.md](PLAYBOOK.md).

## Spins (3 players, winner takes all)

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
python3 -m unittest discover -s tests        # about 80 tests, under a minute
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
python3 tools/build_tag.py          # tight-aggressive sheet for 6, 7 and 8 players, about 5 minutes
python3 tools/build_spin.py         # spin tables (3 players and heads-up), about 7 minutes
python3 tools/spin_sim.py           # whole spin games played with those tables, about 6 minutes
```
