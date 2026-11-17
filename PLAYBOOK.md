# Tight-aggressive tournament playbook

The strategy the coach plays by. The engine (`poker_coach/`) holds the exact
ranges and does the maths for each spot; this is the plan behind it.

## The plan in one paragraph

Play few hands, play them in position, and play them by betting and raising
rather than calling. Early, protect the stack and wait for strong hands.
Once antes are in, keep the stack alive by stealing blinds and re-shoving, not
by gambling in big pots. Approaching the bubble, survival is worth more than
chips: stop calling off your stack, keep attacking players who are trying to
fold into the money. Once in the money, switch back to building a stack.

## Gear by stack depth (effective big blinds)

| Stack | Gear | What you do |
|---|---|---|
| 40bb+ | Full poker | Open 2.2-2.5x from the chart, 3-bet for value, set-mine and flat suited hands in position |
| 25-40bb | Careful poker | Open 2.2x, no set-mining with small pairs, 3-bets commit you: only with hands that want to get it in |
| 16-25bb | Raise-fold / re-shove | Open 2x and fold to a shove unless you hold TT+/AQ+. Your weapon is the **re-shove** over late-position opens |
| 10-16bb | Shove-or-fold (mostly) | Shove profitable hands; min-raise only QQ+/AK to induce. Never raise-fold |
| under 10bb | Pure push/fold | Shove or fold preflop, by the solver. No limping, no calling raises |
| under 5bb | Emergency | Shove before the blinds hit you, while a fold from the blinds is still possible |

Never let the stack drift below 10bb by folding: at 12-15bb a shove still makes
everyone fold; at 5bb it does not.

## Stage plan (objective: reach the money, then climb)

- **Early (deep, no pressure).** Tight in early position, value-heavy. Do not
  bluff big, do not pay off big bets with one pair. Doubling early is worth far
  less than busting costs.
- **Middle (antes in).** Steal from CO/BTN/SB whenever it is folded to you.
  Re-shove 12-25bb over late opens. Avoid flat-calling out of position.
- **Approaching the money (within about 2x the paid places).** Keep stealing
  from people who are tightening. Start refusing marginal all-in calls.
- **Bubble.** Calling all-ins needs a premium (often QQ+/AK against a stack
  that covers you). Shoving is still fine where nobody can call profitably.
  Do not fight the big stack. If you are short, check the **fold clock**: if
  the blinds will not eat you before the bubble bursts, folding is correct;
  if they will, shove while you still have fold equity.
- **In the money.** The brake comes off: steal and re-shove again, and look at
  the next pay jump before calling off against a bigger stack.
- **Final table.** Every jump is large. Let shorter stacks bust first, lean on
  medium stacks, call tighter than chip maths says.

## Opening ranges (folded to you, 30bb+)

Identify your seat by how many players are still to act behind you.

| Seat (players behind) | Opens | Range |
|---|---|---|
| UTG (8) | 11% | 77+, ATs+, A5s, KTs+, QTs+, JTs, AJo+, KQo |
| UTG+1 (7) | 12% | 66+, ATs+, A5s-A4s, KTs+, QTs+, JTs, T9s, AJo+, KQo |
| UTG+2 (6) | 13% | 55+, A9s+, A5s-A4s, KTs+, QTs+, JTs, T9s, 98s, AJo+, KQo |
| LJ (5) | 17% | 44+, A8s+, A5s-A3s, K9s+, Q9s+, J9s+, T9s, 98s, 87s, ATo+, KJo+ |
| HJ (4) | 20% | 33+, A2s+, K9s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, ATo+, KJo+, QJo |
| CO (3) | 26% | 22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, A9o+, KTo+, QTo+, JTo |
| BTN (2) | 41% | 22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, A2o+, K8o+, Q9o+, J9o+, T9o |
| SB (1) | 36% | 22+, A2s+, K4s+, Q7s+, J7s+, T7s+, 97s+, 86s+, 76s, 65s, A4o+, K9o+, Q9o+, J9o+, T9o |

A short-handed table is the same chart: first to act six-handed has 5 behind,
so it opens the LJ range. Tighten one row under ICM pressure or with an
aggressive re-shover behind; loosen one row when the blinds are tight, sitting
out, or under bubble pressure while you cover them.

Sizes: 2x under 25bb, 2.2x to 40bb, 2.3-2.5x deeper, 3x from the small blind.

## Facing a raise

- **Out of position: 3-bet or fold** (the big blind may also call at a good price).
- **Value 3-bets:** QQ+/AK against early position; add JJ, AQs against middle;
  add TT, AQo, AJs, KQs against CO/BTN steals.
- **Calls in position:** medium pairs, AQs/AJs/KQs, suited broadways. Small
  pairs only with 15x the raise behind (set-mining).
- **25bb or less: re-shove or fold.** The solver prices it. With 15-20bb the
  profitable re-shoves are roughly: from the button over a cutoff open 15%
  (33+, A8s+, ATo+, KTs+, QTs+, KQo); from the big blind over a button steal
  30% (any pair, any ace, suited kings, broadways); over an early-position
  open only 9% (77+, ATs+, AJo+, KQs).
- **A raise and a re-raise in front:** KK+ only; QQ/AK only when both players
  are loose or stacks are short.
- **You opened and got 3-bet:** under 45bb it is shove or fold: QQ+/AK shove,
  the rest folds unless the 3-bettor is wild.

## Push/fold: how wide to shove (9-handed, with antes)

Share of hands that are a profitable shove when folded to you:

| Seat | 6bb | 8bb | 10bb | 12bb | 15bb |
|---|---|---|---|---|---|
| UTG | 22% | 19% | 17% | 16% | 13% |
| UTG+2 | 30% | 24% | 20% | 18% | 16% |
| HJ | 35% | 32% | 30% | 27% | 23% |
| CO | 44% | 36% | 34% | 32% | 30% |
| BTN | 53% | 48% | 44% | 40% | 37% |
| SB | 83% | 77% | 74% | 70% | 65% |

At 10bb that means roughly:

- **UTG:** 33+, A7s+, A5s-A2s, K9s+, Q9s+, J9s+, T9s, ATo+, KJo+
- **HJ:** 22+, A2s+, K8s+, Q8s+, J8s+, T8s+, 98s, 87s, A3o+, KTo+, QTo+, JTo
- **CO:** 22+, A2s+, K5s+, Q8s+, J8s+, T7s+, 97s+, 86s+, 76s, A2o+, K9o+, QTo+, JTo
- **BTN:** 22+, A2s+, K2s+, Q4s+, J7s+, T6s+, 96s+, 86s+, 75s+, 65s, 54s, A2o+, K5o+, Q9o+, J9o+, T9o
- **SB:** almost any ace, king, queen, any suited hand down to 52s, most connected offsuit hands

These are chip-EV numbers. On the bubble the coach recomputes them with ICM
for the real stacks: shove ranges shrink when players who cover you will call,
and the coach assumes opponents call wider than a perfect ICM player would.

## Calling an all-in

1. Price: equity needed = call / (pot after you call).
2. Add the **risk premium**: the extra equity ICM demands because chips you
   lose are worth more than chips you win. Early it is 1-3 points, near the
   bubble 5-10, on the bubble against a covering stack 15-20.
3. Compare with your equity against the range they actually shove.

Shortcuts: a 10bb shove from late position is wide (30-45%): call with 55+,
A8+, KJ+ on chips alone. A shove from early position or from a tight player is
strong: 99+, AQ+. On the bubble subtract most of that.

## After the flop

- **Heads-up as the preflop raiser:** bet small (1/3 pot) on dry high boards
  (K72, A83, Q-Q-5) with everything; check boards that hit callers (9-8-7
  two-tone) unless you have a hand or a draw.
- **Multi-way:** bet only real hands and strong draws.
- **Value bet** top pair good kicker or better; size up (2/3 pot) on wet
  boards and on the turn.
- **One pair is a two-street hand.** Facing a turn raise or a big river bet
  with one pair: fold, especially against passive players.
- **Draws:** call when the price is right, shove strong draws (12+ outs) when
  the stack is 4x the pot or less and they can fold.
- **Commitment:** with top pair or better and less than 1.5x the pot behind,
  the hand goes to showdown. Decide that before betting, not after.
- **ICM:** near the bubble no multi-street bluffs and no thin hero calls for
  a third of your stack or more.

## Reads

| Type | What you see | Adjustment |
|---|---|---|
| nit | folds for orbits, shows only premiums | steal their blinds; fold to their raises without a premium |
| tight | few hands, rarely 3-bets | steal more; respect their 3-bets and shoves |
| tag | solid, positional | default assumptions |
| lag | opens and 3-bets a lot | tighten opens in front of them, re-shove and call lighter |
| loose / station | limps, calls too much | no bluffs; value bet thinner and bigger |
| maniac | shoves and raises constantly | wait, then call with a wider value range |

## Leaks that cost cashes

- Calling off a stack with AJ/KQ/small pairs on the bubble.
- Blinding down to 5bb waiting for a hand.
- Raise-folding 12bb.
- Flat-calling raises out of position "to see a flop".
- Paying off river bets from passive players with one pair.
- Bluffing calling stations.

## Late-registration min-cash plan

The idea: buy in at the very end of late registration, play all-in or fold
with one aim (the first paid place), and sit out as soon as the stack can be
blinded down safely. A min-cash pays about twice the price, so cashing more
than half the time would be profitable. `python3 -m poker_coach latereg`
rates a tournament for it.

### What the evidence says

- **The payout premise holds.** On GGPoker a non-bounty min-cash is about 1.9
  to 2.15 times the full price (8% fee included), so min-cashes alone break
  even at 47% to 52%. Bounty formats pay only 1.15 to 1.5 times: never use
  them for this.
- **The 50% does not, in ordinary tournaments.** Registration closes when a
  fresh stack is 10 to 13 big blinds, with 37% to 49% of entries alive and
  about 15% paid. The newcomer holds 40% to 50% of an average stack and would
  need more than four average stacks to fold into the money. Standard
  shove-or-fold cashes 12% to 16% from there; this plan about 18% in a turbo
  and 13% at regular speed.
- **Two numbers decide it:** the share of entries that gets paid, and the
  share still alive when registration closes. Chance of cashing for a fresh
  11 big blind stack that plays the charts below exactly:

| Turbo (5-6 minute levels) | 15% paid | 20% paid | 25% paid | 30% paid |
|---|---|---|---|---|
| 50% alive at the close | 18% | 26% | 36% | 47% |
| 40% alive | 19% | 29% | 39% | **54%** |
| 30% alive | 21% | 32% | 47% | |
| 25% alive | 22% | 35% | | |
| 20% alive | 25% | | | |

| Regular (10-12 minutes) | 15% paid | 20% paid | 25% paid | 30% paid |
|---|---|---|---|---|
| 50% alive at the close | 13% | 20% | 29% | 38% |
| 40% alive | 14% | 22% | 32% | 47% |
| 30% alive | 16% | 27% | 43% | |
| 25% alive | 18% | 32% | | |
| 20% alive | 21% | | | |

  So the plan needs about 30% of the entries paid, or 25% with a very late
  close. A later close helps less than it looks: fewer players stand between
  you and the money, but a fresh stack is a smaller share of the average.
- **Where that could happen.** Flights in which a fixed share advances to a
  paid Day 2 (The Weekender, $50: 20% of each flight, so 20% to 35% above);
  flights that end a few levels after registration closes with every Day 2
  seat paid (rate them with `--levels-left`; "Day 2 is in the money" is not a
  general rule); and overlays, where the min-cash is a bigger multiple of the
  price. Each has to be checked in the lobby.
- **It gives up money.** The same late stack played for chips returned 10 to
  14 points more per entry in every structure tested (ordinary turbo: -24%
  against -38%), because about 70% of a prize pool sits above the bottom
  prize. Those returns are pessimistic for both, since the model's player can
  only move all-in or fold; published ICM work puts a well-played late stack
  near break-even after the fee.

### Why waiting is expensive

A table loses a player at a rate of about 3 divided by the average stack in
big blinds per hand, so a folding player pays about 0.83 chips for every chip
the average stack grows. That holds whatever the speed of the blinds. But
inside the last 10% before the money the field tightens to about a quarter of
that speed, and during hand-for-hand to a tenth, while the blinds keep rising:
the last tenth of the eliminations costs about as much as all the others.

### The sit-out line

The stack, in average stacks, from which folding every hand still cashes at
least 95 times in 100:

| Players left / paid | 1.02 | 1.05 | 1.10 | 1.20 | 1.30 | 1.50 | 2.00 | 3.00 |
|---|---|---|---|---|---|---|---|---|
| Line (average stacks) | 0.50 | 0.65 | 0.85 | 1.00 | 1.15 | 1.55 | 2.45 | 4.40 |

In a field that pays fewer than 160 places, add 40 / places paid - 0.25
average stacks (50 paid: +0.55; 20 paid: +1.75): with few players left to
bust, the timing of the bubble is a lottery. Under about 20 places paid the
line is out of reach, so do not plan on sitting out.

Your share = your stack / (line x average stack). Work it out again at every
level.

| Share of the line | What to do | Cashes about |
|---|---|---|
| 100% or more | Sit out | 98 in 100 |
| 50% to 100% | Fold everything; aces only, and only when nobody has raised | 8 to 9 in 10 |
| 20% to 50% | Tight chart | 4 to 5 in 10 |
| under 20% | Wide chart; short-stack chart under 6 big blinds | 1 to 2 in 10 |

The lower figure is regular speed, the higher a turbo.

### The charts (all-in when nobody has raised, 8-handed)

| Seat | Wide (6 to 20bb) | Short stack (under 6bb) | Tight |
|---|---|---|---|
| UTG | 66+, ATs+, KQs, AJo+ | 22+, A2s+, K7s+, QTs+, A2o+, K9o+, QJo | 99+, AQs+, AQo+ |
| UTG+1 | 55+, ATs+, KQs, ATo+ | 44+, A2s+, K9s+, QJs, A5o+, KTo+ | 99+, AQs+, AQo+ |
| LJ | 55+, A9s+, KQs, ATo+ | 55+, A3s+, K9s+, A7o+, KTo+ | 99+, AJs+, AQo+ |
| HJ | 44+, A7s+, KQs, A8o+ | 55+, A3s+, K9s+, A7o+, KTo+ | 88+, ATs+, AJo+ |
| CO | 33+, A2s+, KTs+, A7o+, KQo | 55+, A2s+, K8s+, QTs+, A5o+, KTo+ | 77+, A9s+, ATo+ |
| BTN | 22+, A2s+, K8s+, QTs+, JTs, A2o+, KTo+ | 44+, A2s+, K6s+, Q9s+, JTs, A4o+, K9o+, QTo+ | 55+, A6s+, KJs+, A8o+, KQo |
| SB | 22+, A2s+, K2s+, Q4s+, J8s+, T8s+, A2o+, K2o+, Q8o+, J9o+ | 33+, A2s+, K2s+, Q5s+, J8s+, T9s, A2o+, K5o+, Q8o+, J9o+ | 44+, A2s+, K8s+, QTs+, A3o+, K9o+ |

Under the gun with a short stack is wide because the big blind arrives on the
next hand.

Over a raise, all-in or fold, never just call:

| The raise came from | Wide | Short stack | Tight |
|---|---|---|---|
| CO, BTN or SB | 66+, A9s+, KJs+, ATo+, KQo | 77+, ATs+, KQs, ATo+ | TT+, AKs |
| An earlier seat, or an all-in | 88+, AQs+, AQo+ | 99+, AQs+, AQo+ | JJ+ |

With more than 20 big blinds: all-in with QQ+ and AK only (KK+ over an early
raise).

These are far tighter than chip-EV push/fold. The reason: a called loss ends
the tournament, and the blinds a steal wins are small next to what the stack
still needs, so with many hands left it is better to wait for a hand that
wins when called. That is right while the table calls a 10 big blind all-in
about half the time; against a table that folds to every all-in, steal wider
from the cutoff, button and small blind. Once the bubble has burst the aim
changes back: stop sitting out, play the standard shove chart and climb.

### Limits

- Cash rates are a model fitted to 13 GGPoker fields ($300 to $2,500 events)
  and checked against an independent simulation; read them as plus or minus 5
  points. Hyper-turbos were not measured, and bubbles in fields that pay fewer
  than about 150 places are extrapolated.
- The turbo advantage rests on an assumption that was not measured: that
  shallow fields keep busting on the bubble. When in doubt, use the regular
  numbers.
- The printed charts cash 3 to 7 points less than perfect all-in or fold
  play; the calculator shows both.
- One player sitting out is within GGPoker's rules. Agreeing a sit-out with
  anyone, or stalling, is not. Late entries get no Bubble Protection, and
  registration can close before the time in the lobby.
- Where the plan does not clear 50%, ordinary play with the coach's default
  goal (cash first, then climb) is the better use of a buy-in.

## All-in or fold for a whole tournament

One decision per hand: move all-in, or fold. `python3 -m poker_coach binary`
answers a spot from the tables below, and `binary-chart` prints the full
hand-by-hand grid for a seat.

### Does it work?

- **As a way to play: yes, while the stack is short.** Under about 15 big
  blinds all-in or fold is how strong players play as well, and an entry at
  the close of late registration starts with 10 to 13. Before that a player
  restricted to all-in or fold would be folding everything except aces and
  kings, so entering late costs this plan nothing.
- **As a way to win: not by the chart alone.** In the tournament model a late
  entry played this way cashes about 16% of the time and returns -24% per
  entry in a turbo, -11% in a hyper-turbo (not measured) and -39% at regular
  speed. The model counts no edge after the bubble and is on the low side;
  published ICM work puts a late entry at about break-even after the fee.
  Either way the profit has to come from fields that play badly, not from
  the table.
- **Standard push/fold charts are too wide for it.** In the same model a
  chip-EV chart cashed 6% to 8%. The weak half of such a chart earns almost
  nothing per all-in, so the few points of survival value a stack has before
  the money, and tables that call as usual, turn it into a loss. The plan
  below is about half as wide.
- **Where to use it.** Late entry, turbo levels or faster, no bounty, small
  buy-ins with big fields. Slow structures bleed it.

### Nobody has raised

Share of hands that move all-in, by seat and stack (8-handed). The stack is
the smaller of yours and the biggest stack still to act.

| Seat | 6bb | 8bb | 10bb | 12bb | 15bb | 20bb | 25bb | 30bb | 40bb |
|---|---|---|---|---|---|---|---|---|---|
| UTG | 14% | 10% | 8% | 7% | 6% | 4% | 3% | 3% | 1% |
| UTG+1 | 15% | 12% | 10% | 8% | 6% | 5% | 4% | 3% | 3% |
| LJ | 17% | 13% | 11% | 10% | 8% | 6% | 5% | 3% | 3% |
| HJ | 20% | 17% | 14% | 12% | 10% | 7% | 6% | 4% | 3% |
| CO | 26% | 24% | 21% | 15% | 12% | 10% | 7% | 6% | 3% |
| BTN | 32% | 30% | 27% | 25% | 20% | 15% | 10% | 8% | 5% |
| SB | 53% | 49% | 44% | 39% | 34% | 28% | 24% | 17% | 10% |

The hands themselves, by stack (s = suited, o = offsuit; A9s+ is A9s and
better, 66+ is 66 and every higher pair):

| Seat | up to 7bb | 8 to 11bb | 12 to 16bb | 17 to 24bb | 25 to 40bb |
|---|---|---|---|---|---|
| UTG | 33+, A7s+, KJs+, A8o+ | 66+, ATs+, KQs, AJo+ | 88+, AJs+, AQo+ | TT+, AQs+, AKo | QQ+, AKs, AKo |
| UTG+1 | 33+, A5s+, KJs+, A8o+, KQo | 55+, A9s+, KQs, ATo+ | 88+, AJs+, AQo+ | 99+, AQs+, AQo+ | JJ+, AKs, AKo |
| LJ | 33+, A3s+, KTs+, A7o+, KQo | 55+, A8s+, KQs, A9o+ | 77+, ATs+, AJo+ | 88+, AJs+, AQo+ | TT+, AKs, AKo |
| HJ | 33+, A2s+, KTs+, QJs, A5o+, KJo+ | 33+, A7s+, A5s, KJs+, A8o+ | 55+, A9s+, KQs, ATo+ | 77+, AJs+, AJo+ | TT+, AQs+, AKo |
| CO | 22+, A2s+, K8s+, QTs+, A2o+, K9o+ | 22+, A2s+, KTs+, QJs, A5o+, KJo+ | 44+, A7s+, KQs, A9o+ | 66+, A9s+, KQs, ATo+ | 88+, AQs+, AQo+ |
| BTN | 22+, A2s+, K4s+, Q8s+, JTs, A2o+, K7o+, QTo+ | 22+, A2s+, K8s+, QTs+, JTs, A2o+, K9o+, QJo | 22+, A2s+, KTs+, A5o+, KJo+ | 44+, A5s+, KJs+, A8o+, KQo | 77+, ATs+, AJo+ |
| SB | 22+, A2s+, K2s+, Q2s+, J4s+, T7s+, 98s, A2o+, K2o+, Q4o+, J7o+, T8o+ | 22+, A2s+, K2s+, Q4s+, J8s+, T8s+, 98s, A2o+, K2o+, Q7o+, J9o+ | 22+, A2s+, K2s+, Q8s+, J9s+, A2o+, K6o+, QTo+ | 22+, A2s+, K7s+, QTs+, JTs, A2o+, K9o+, QJo | 33+, A3s+, KJs+, A7o+, KQo |

Close to the money use the column for twice your stack. Over 40 big blinds
only AA and KK move all-in.

### Stage by stage

| Stage | Players left per paid place | What changes |
|---|---|---|
| Far from the money | more than 2 (1.5 at regular speed) | The table above as it is |
| Close to the money | down to 1.3 (1.2) | The column for twice your stack |
| Bubble | under 1.3 (1.2) | The late-registration plan takes over: its sit-out line and tight chart |
| In the money | | The table again, counting your stack 2bb smaller (4bb in the small blind) |
| Final table | | The same; call from the bubble table when the all-in player covers you |

### A raise before you: all-in or fold

| The raise came from | up to 7bb | 8 to 11bb | 12 to 16bb | 17 to 24bb | 25 to 40bb |
|---|---|---|---|---|---|
| UTG, UTG+1 or LJ | 88+, AJs+, AQo+ | 88+, AQs+, AQo+ | 99+, AQs+, AQo+ | TT+, AQs+, AKo | JJ+, AKs, AKo |
| HJ or CO | 55+, A7s+, KTs+, A9o+, KQo | 66+, A9s+, KJs+, ATo+, KQo | 66+, ATs+, AJo+ | 77+, AJs+, AJo+ | 99+, AQs+, AKo |
| BTN or SB (you are in the blinds) | 22+, A2s+, K4s+, Q8s+, J9s+, A2o+, K8o+, QTo+, JTo | 33+, A2s+, K9s+, QTs+, A5o+, KTo+ | 22+, A2s+, KTs+, QTs+, JTs, T9s, A4o+, KJo+ | 22+, A2s+, KTs+, QTs+, J9s+, T9s, A7o+, KJo+ | 22+, A4s+, KTs+, Q9s+, J9s+, T9s, ATo+, KQo |

In the money add KQs, and over a raise from HJ or CO also KJs and QJs. Never
just call. If the raiser has put in a third of their stack they will not
fold: use the all-in table.

### An all-in before you: call or fold

Away from the bubble, by the size of the all-in (or your stack, if smaller):

| The all-in came from | up to 7bb | 8 to 11bb | 12 to 16bb | 17 to 24bb | 25 to 40bb |
|---|---|---|---|---|---|
| UTG, UTG+1 or LJ | 55+, A8s+, A9o+ | 88+, AJs+, AQo+ | 99+, AQs+, AKo | TT+, AKs, AKo | QQ+, AKs, AKo |
| HJ or CO | 44+, A3s+, KTs+, A7o+, KJo+ | 66+, A9s+, ATo+ | 77+, ATs+, ATo+ | 88+, AJs+, AJo+ | TT+, AQs+, AKo |
| BTN | 22+, A2s+, K6s+, QTs+, JTs, A2o+, K8o+, QJo | 44+, A5s+, KTs+, A7o+, KJo+ | 66+, A8s+, A9o+ | 77+, ATs+, ATo+ | 88+, AJs+, AJo+ |
| SB (you are the big blind) | 22+, A2s+, K2s+, Q2s+, J3s+, T6s+, 97s+, 87s, A2o+, K2o+, Q2o+, J7o+, T8o+ | 22+, A2s+, K3s+, Q8s+, J9s+, A2o+, K6o+, Q9o+, JTo | 44+, A2s+, K8s+, QTs+, A4o+, K9o+ | 55+, A4s+, K9s+, A7o+, KTo+ | 66+, A8s+, KQs, A9o+ |
| Two all-ins | 77+, AJs+, AQo+ | TT+, AKs, AKo | JJ+ | QQ+ | KK+ |

On the bubble, and at a final table when the all-in player covers you:

| The all-in came from | up to 7bb | 8 to 11bb | 12 to 16bb | 17 to 24bb | 25 to 40bb |
|---|---|---|---|---|---|
| UTG, UTG+1 or LJ | 99+, AJs+, AQo+ | JJ+ | QQ+ | QQ+ | KK+ |
| HJ or CO | 88+, ATs+, AJo+ | TT+, AQs+, AKo | JJ+, AKs | JJ+ | QQ+ |
| BTN | 77+, A8s+, KQs, A9o+ | 99+, AJs+, AQo+ | TT+, AQs+, AKo | TT+, AKs | JJ+ |
| SB (you are the big blind) | 44+, A2s+, K6s+, Q9s+, JTs, A3o+, K8o+, QTo+ | 77+, A8s+, KTs+, ATo+, KQo | 88+, ATs+, AJo+ | 99+, AJs+, AQo+ | TT+, AKs, AKo |
| Two all-ins | QQ+ | KK+ | KK+ | KK+ | AA |

In the big blind the price is better: read both tables one column to the
left (the small-blind row already counts it).

**Two all-ins** is the row for two players all-in before you; a raise and an
all-in counts the same. Three hands see the board, so you need less than a
third of the pot, but the second player has shown a hand strong enough to
call an all-in, and on the bubble a fold often moves you up a place for
free. With 11 big blinds or less it is a call with far more than aces and
kings; from 17 it is queens or better. If the two stacks differ, the size is
the bigger one you would have to match.

### Six and seven players

A seat is the number of players still to act behind it, so the names shift
with the table: the first to act is UTG at eight and seven players and LJ at
six. With fewer players the blinds come round sooner, which widens the
ranges, and there is less ante money to win, which tightens them; the two
nearly cancel, so each seat stays within a notch of the eight-handed row
with the same players behind. The tables are solved for each size all the
same (`--players 6` or `--players 7` on every `binary` command).

Seven players, nobody has raised:

| Seat | up to 7bb | 8 to 11bb | 12 to 16bb | 17 to 24bb | 25 to 40bb |
|---|---|---|---|---|---|
| UTG | 33+, A4s+, KTs+, A7o+, KQo | 55+, A9s+, KQs, ATo+ | 88+, AJs+, AQo+ | 99+, AQs+, AQo+ | JJ+, AKs, AKo |
| LJ | 33+, A3s+, KTs+, A7o+, KJo+ | 44+, A8s+, KQs, A9o+ | 77+, ATs+, AJo+ | 88+, AJs+, AQo+ | JJ+, AKs, AKo |
| HJ | 33+, A2s+, KTs+, QJs, A5o+, KJo+ | 44+, A7s+, KJs+, A8o+ | 66+, ATs+, KQs, ATo+ | 77+, AJs+, AJo+ | TT+, AQs+, AKo |
| CO | 22+, A2s+, K8s+, QTs+, A2o+, K9o+ | 33+, A2s+, KTs+, A6o+, KQo | 44+, A8s+, KQs, A9o+ | 66+, ATs+, KQs, ATo+ | 88+, AQs+, AQo+ |
| BTN | 22+, A2s+, K4s+, Q8s+, JTs, A2o+, K7o+, QTo+ | 22+, A2s+, K8s+, QTs+, JTs, A2o+, KTo+ | 33+, A2s+, KTs+, A7o+, KQo | 44+, A7s+, A5s, KJs+, A8o+, KQo | 66+, ATs+, ATo+ |
| SB | 22+, A2s+, K2s+, Q2s+, J4s+, T7s+, 97s+, A2o+, K2o+, Q4o+, J7o+, T8o+ | 22+, A2s+, K2s+, Q4s+, J8s+, T8s+, 98s, A2o+, K2o+, Q7o+, J9o+ | 22+, A2s+, K3s+, Q9s+, JTs, A2o+, K7o+, QTo+ | 22+, A2s+, K7s+, QTs+, JTs, A2o+, K9o+, QJo | 33+, A3s+, KJs+, A7o+, KQo |

Six players, nobody has raised:

| Seat | up to 7bb | 8 to 11bb | 12 to 16bb | 17 to 24bb | 25 to 40bb |
|---|---|---|---|---|---|
| LJ | 22+, A2s+, KTs+, QJs, A5o+, KJo+ | 44+, A8s+, KJs+, A9o+ | 77+, ATs+, AJo+ | 88+, AJs+, AQo+ | JJ+, AKs, AKo |
| HJ | 22+, A2s+, K9s+, QTs+, A3o+, KTo+ | 33+, A5s+, KJs+, A8o+, KQo | 55+, A9s+, KQs, ATo+ | 77+, AJs+, AJo+ | TT+, AQs+, AKo |
| CO | 22+, A2s+, K7s+, QTs+, JTs, A2o+, K9o+, QJo | 22+, A2s+, KTs+, QJs, A5o+, KJo+ | 44+, A8s+, KQs, A9o+ | 66+, ATs+, KQs, ATo+ | 88+, AQs+, AQo+ |
| BTN | 22+, A2s+, K3s+, Q8s+, JTs, A2o+, K7o+, QTo+ | 22+, A2s+, K8s+, QTs+, JTs, A2o+, KTo+ | 33+, A2s+, KTs+, A7o+, KQo | 44+, A7s+, KJs+, A8o+ | 77+, ATs+, AJo+ |
| SB | 22+, A2s+, K2s+, Q2s+, J5s+, T7s+, 98s, A2o+, K2o+, Q4o+, J7o+, T8o+ | 22+, A2s+, K2s+, Q5s+, J8s+, T9s, A2o+, K2o+, Q8o+, J9o+ | 22+, A2s+, K4s+, Q9s+, JTs, A2o+, K7o+, QTo+ | 22+, A2s+, K8s+, QTs+, JTs, A2o+, K9o+, QJo | 44+, A5s+, KJs+, A8o+, KQo |

The raise and all-in tables for six and seven players differ from the ones
above by a notch here and there: `binary-sheet --players 6` prints them. A
late entry earns about the same at every table size in the model (turbo:
-26% at six players, -26% at seven, -24% at eight).

### Small print

- **A limper before you:** use the range of the seat before yours.
- **Big blind, no raise:** check. After the flop move all-in with top pair or
  better, or a draw with 12 outs, when the stack is 4 pots or less;
  otherwise check, and fold to a bet.
- **How the numbers were made.** Before the money: the play that earns the
  most prize money in the late-registration model (blinds to pay until the
  bubble, opponents who call as they usually do). In the money and for
  calls: the ICM solver on a standard pay ladder, with a safety margin of
  0.02 big blinds per big blind of stack over 10. Stacks are taken as equal.
  Read every range as plus or minus one notch, and price real stacks with
  `advise` when there is time.

## Every preflop situation (6, 7 and 8 players)

Normal tight-aggressive play at any stack, entering at any point.
`python3 -m poker_coach tag-sheet --players 8` (or 7, or 6) prints every hand
list as text; the printed sheet has the same seven parts. It is organised by
what has happened before you act. Stacks are effective, in big blinds.

| Before you act | 17bb or more | 16bb or less |
|---|---|---|
| Nobody has entered | Raise the opening range of your seat (17 to 24bb: without the small suited connectors) | All-in with the all-in or fold hands of your seat. QQ+ and AK may raise 2bb at 12 to 16bb and call any all-in |
| Players only called | Raise to 3bb plus 1bb per caller (4bb plus 1bb from the blinds) with the opening range of the seat one line tighter for each caller, and always with 99+, AJs+, AQo+, KQs. Otherwise fold; the big blind checks | All-in with the all-in hands of the seat before yours (big blind: the small blind's). Otherwise fold; the big blind checks |
| One raise | 25bb or more: re-raise, call or fold by where the raise came from and where you sit | 24bb or less: all-in or fold, from the raise table of the all-in or fold section |
| A raise and a call | The same hands; the re-raise is one raise bigger for each caller | The same all-in hands |
| A raise and a re-raise | The table below | The table below |
| You raised and were re-raised | The table below | (you do not raise small this short) |
| You raised and met an all-in | Call with the hands of your opening range that beat the pot odds by 6 points, 16 on the bubble. Against 7bb or less: every hand you raised | |
| An all-in, or two | The call tables of the all-in or fold section, by the size of the all-in | The same |

A raise and a re-raise before you (everything else folds):

| The first raise came from | Re-raise, more than 60bb | All-in, 25 to 60bb | All-in, up to 24bb |
|---|---|---|---|
| UTG or UTG+1 | KK+ | KK+, AKs | JJ+, AKs, AKo |
| LJ or HJ | KK+, AKs | KK+, AKs, AKo | JJ+, AKs, AKo |
| CO or BTN | KK+, AKs, AKo | JJ+, AKs, AKo | JJ+, AKs, AKo |

You raised and were re-raised, not all-in (everything else folds):

| You raised from | All-in, 45bb or less | Re-raise, more than 45bb | Call, more than 45bb |
|---|---|---|---|
| UTG or UTG+1 | KK+, AKs | KK+ | QQ, AKs |
| LJ or HJ | QQ+, AKs, AKo | KK+ | QQ-JJ, AKs |
| CO or BTN | TT+, AQs+, AKo | KK+ | QQ-44, AJs+, AKo |
| SB | TT+, AQs+, AKo | KK+ | QQ-22, ATs+, AKo |

- **Calling along** behind players who only called: with 25bb or more, from
  the cutoff, the button or the small blind, when the hand is not on the
  raise list: 22-88, A2s-A9s, K9s, KTs, Q9s, QTs, J9s, JTs, T9s, 98s, 87s, 76s, 65s, 54s.
- **Big blind, players only called:** raise from the list or check. A check
  costs nothing; never fold. After the flop bet top pair or better and
  strong draws, otherwise check and fold to a bet.
- **Big blind against one raise of 2.5bb or less, with 9 to 24bb:** instead
  of folding it may call with any pair, any suited hand, any ace, K9o+, Q9o+, J9o+ and T9o.
  The engine's own list is close to any two cards; the sheet keeps the part
  that makes top pair or a real draw.
- **You only called and a player raised:** fold. With a pair and 15 times
  the raise behind you may call once.
- **Where the hands come from.** The raise, call and re-raise lists are what
  `advise` answers far from the money for each of the 169 hands; a test
  checks it. Every all-in list is taken from the all-in or fold section, so
  it is tighter than the chip-EV push/fold table earlier in this playbook.
  That chip-EV table is still what opponents are assumed to play, and what
  the coach leans to when survival does not matter.
- **Limits.** Stacks are taken as equal and every player posts an ante.
  Three stack columns stand for every stack under 17bb. With the table
  tracked, `advise` prices the real stacks and prizes.

## Spins: three players, one prize

A spin (GGPoker Spin & Gold) is a three-player sit & go. A random multiplier
sets the prize and in 97.6% of games the winner takes all of it.
`python3 -m poker_coach spin` answers a spot from the tables below and
`spin-odds` does the money.

### Does the idea hold?

The idea: the game pays about 1 to 1, players call too wide, so aggressive
all-in play wins more than half the games and makes money. Checked against
GGPoker's own prize tables, published results and a simulation of whole games:

- **The prizes.** The site keeps 7%, so three buy-ins pay back
  2.79 on average. The winner gets 2 buy-ins in 47.9%
  of games and 3 in 44.6%. x4 and x5 come in 2.6% and 2.5% of games, x10 (8
  and 2 buy-ins for first and second) in 2.4%, anything bigger about once in
  8,000 games.
- **Winning half does not happen.** Equal players win 33.3% each and lose 7%
  a game. Break-even is 35.9% of games. The best regulars report 38% to 39%
  over 10,000 to 40,000 games, worth 1% to 8% a game before rewards. Half
  the games would be +38% a game, and nobody reports it. Over 30 games a 36%
  player shows half or better about one time in twenty, which is why it can
  look possible.
- **All-in or fold is right only when short.** Under about 8 big blinds it
  is how solvers play. Deeper, they raise small or just call with most
  hands: heads-up at 10 big blinds the small blind plays 88% of hands and
  moves all-in with 22%. In the solved all-in or fold game the small blind
  loses 0.05 big blinds a hand at 10 big blinds, 0.13 at 15 and 0.19 at 20,
  where a player with every move makes it a winning seat. GGPoker's x2 and
  x3 games (92.5% of all games) start at 15 big blinds with 1 and 2 minute
  levels, so stacks are under 10 big blinds within a few hands and the cost
  is small. In the x4 to x10 games, which start at 25, it is larger.
- **Loose callers call for tighter all-ins, not wider.** When they call too
  much the weak steals stop working and the strong hands get paid. The best
  reply drops the bottom of the first-in ranges: at 10 big blinds the button
  goes from 33% of hands to 26%, the small blind from 57% to 43%.
- **What weak players really do.** In one professional's database of over a
  million hands they move all-in about half as often as a solver (button at
  9 big blinds: 15% against 30%), raise small or limp instead, and then call
  an all-in far too often (65% against 26% after a small raise). The all-in
  over a limp or a small raise is where the money is against them.
- **The tournament tables.** They are built to survive until a prize; here a
  chip won is worth exactly what a chip lost costs, so against players who
  call correctly they are too tight (32.0% of games against 33.1%).
  Against weak players they do about as well as the loose table, because
  tight is the right answer to players who call too much.

What the tables won: whole games with GGPoker's blind levels, everybody
all-in or fold, 200,000 games of each common kind, weighted by how often
each multiplier comes. Share of games won, and the return per game:

| Opponents | Standard table | Loose table | Tournament sheet |
|---|---|---|---|
| They call correctly | 33.1% (−8%) | 33.0% (−8%) | 32.0% (−10%) |
| They call 1.5 times too wide | 34.0% (−5%) | 34.8% (−3%) | 34.2% (−4%) |
| They call twice too wide | 35.6% (−1%) | 36.4% (+2%) | 36.1% (+1%) |
| They call 1.5 times too wide and move all-in half as often | 35.5% (−1%) | 36.5% (+2%) | 37.0% (+3%) |

An x2 game lasts about 10 hands and an x3 game about 12, which leaves
little room for an edge to add up. So: these tables are the correct base for
the format. They lose the fee against competent players and get to about
break-even against players who call far too much. The step from there to the
38% of a winning regular is everything all-in or fold leaves out: small
raises, limps and play after the flop with 10 to 25 big blinds.

### Three players

The stack is the effective one: the smaller of yours and the biggest stack
that can still call; against an all-in, its size or your stack if smaller.

**BTN, nobody has entered: all-in with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q4s+, J7s+, T7s+, 97s+, 87s, A2o+, K4o+, Q8o+, J9o+ |
| 6 to 8bb | 22+, A2s+, K3s+, Q6s+, J7s+, T7s+, 97s+, 86s+, 76s, A2o+, K9o+, Q9o+, JTo |
| 9 to 12bb | 22+, A2s+, K6s+, Q8s+, J7s+, T7s+, 97s+, 86s+, 76s, A2o+, KTo+, QTo+, JTo |
| 13 to 17bb | 22+, A2s+, K9s+, Q9s+, J8s+, T8s+, 98s, 87s, A8o+, KTo+, QJo |
| 18 to 24bb | 22+, A2s+, K9s+, Q9s+, J8s+, T9s, 87s, A9o+, KTo+, QJo |
| 25bb or more | 55+, A4s+, K9s+, Q9s+, JTs, T9s, ATo+, KJo+ |

**SB, the button folded: all-in with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 84s+, 74s+, 64s+, 53s+, A2o+, K2o+, Q2o+, J2o+, T6o+, 96o+, 87o, 76o |
| 6 to 8bb | 22+, A2s+, K2s+, Q2s+, J4s+, T4s+, 95s+, 85s+, 74s+, 64s+, 53s+, A2o+, K2o+, Q4o+, J7o+, T8o+, 97o+, 87o, 76o |
| 9 to 12bb | 22+, A2s+, K2s+, Q2s+, J3s+, T3s+, 95s+, 84s+, 74s+, 63s+, 54s, 43s, A2o+, K2o+, Q7o+, J8o+, T8o+, 98o, 87o |
| 13 to 17bb | 22+, A2s+, K2s+, Q5s+, J5s+, T6s+, 96s+, 85s+, 75s+, 65s, 54s, A2o+, K8o+, Q9o+, J9o+, T8o+, 98o |
| 18 to 24bb | 22+, A2s+, K4s+, Q6s+, J8s+, T6s+, 96s+, 86s+, 76s, 65s, A2o+, K9o+, Q9o+, J9o+, T9o, 98o, 87o |
| 25bb or more | 22+, A2s+, K5s+, Q6s+, J7s+, T7s+, 96s+, 87s, 65s, A2o+, KTo+, QJo, JTo, T9o |

**SB, the button is all-in: call with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q7s+, J8s+, T8s+, 98s, 87s, 76s, A2o+, K7o+, Q9o+, JTo |
| 6 to 8bb | 22+, A2s+, K9s+, Q9s+, JTs, A4o+, KTo+, QJo |
| 9 to 12bb | 33+, A3s+, KTs+, QTs+, A7o+, KJo+ |
| 13 to 17bb | 44+, A7s+, KJs+, A8o+, KQo |
| 18 to 24bb | 55+, A9s+, KQs, ATo+ |
| 25bb or more | 88+, AJs+, AQo+ |

**BB, the button is all-in: call with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q2s+, J2s+, T3s+, 95s+, 84s+, 74s+, 64s+, 53s+, 43s, A2o+, K2o+, Q5o+, J7o+, T7o+, 98o, 87o, 76o |
| 6 to 8bb | 22+, A2s+, K4s+, Q8s+, J9s+, T9s, A2o+, K9o+, QTo+, JTo |
| 9 to 12bb | 22+, A2s+, K9s+, QTs+, A4o+, KTo+, QJo |
| 13 to 17bb | 44+, A4s+, KTs+, QJs, A8o+, KJo+ |
| 18 to 24bb | 55+, A9s+, KJs+, ATo+, KQo |
| 25bb or more | 77+, ATs+, AJo+ |

**BB, the small blind is all-in: call with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 93s+, 85s+, 74s+, 64s+, 54s, A2o+, K2o+, Q2o+, J2o+, T6o+, 96o+, 87o |
| 6 to 8bb | 22+, A2s+, K2s+, Q2s+, J6s+, T7s+, 98s, A2o+, K2o+, Q6o+, J8o+, T9o |
| 9 to 12bb | 22+, A2s+, K2s+, Q7s+, J9s+, T9s, A2o+, K6o+, Q9o+, JTo |
| 13 to 17bb | 33+, A2s+, K8s+, QTs+, JTs, A2o+, K9o+, QJo |
| 18 to 24bb | 33+, A2s+, K9s+, QTs+, A6o+, KTo+ |
| 25bb or more | 44+, A5s+, KJs+, A8o+, KQo |

**BB, both are all-in: call with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q2s+, J3s+, T4s+, 95s+, 84s+, 74s+, 63s+, 52s+, 43s, A2o+, K6o+, Q8o+, J8o+, T8o+, 98o, 87o, 76o, 65o |
| 6 to 8bb | 33+, A4s+, K9s+, Q8s+, J8s+, T8s+, 98s, 87s, 76s, A9o+, KTo+, QJo |
| 9 to 12bb | 44+, A9s+, KTs+, QTs+, JTs, T9s, ATo+, KQo |
| 13 to 17bb | 66+, ATs+, KQs, AQo+ |
| 18 to 24bb | 88+, AJs+, AQo+ |
| 25bb or more | TT+, AKs, AKo |

### Two players left

Heads-up the button is the small blind and acts first.

**SB (button), first to act: all-in with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 93s+, 84s+, 74s+, 64s+, 53s+, A2o+, K2o+, Q2o+, J2o+, T5o+, 96o+, 86o+, 76o |
| 6 to 8bb | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 94s+, 84s+, 74s+, 64s+, 53s+, A2o+, K2o+, Q3o+, J7o+, T7o+, 97o+, 87o, 54o |
| 9 to 12bb | 22+, A2s+, K2s+, Q2s+, J3s+, T6s+, 95s+, 84s+, 74s+, 64s+, 53s+, A2o+, K2o+, Q6o+, J8o+, T7o+, 97o+, 87o |
| 13 to 17bb | 22+, A2s+, K2s+, Q6s+, J6s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A2o+, K6o+, Q8o+, J8o+, T8o+, 98o, 87o |
| 18 to 24bb | 22+, A2s+, K3s+, Q6s+, J7s+, T7s+, 96s+, 85s+, 76s, 65s, 54s, A2o+, KTo+, QTo+, J8o+, T8o+ |
| 25bb or more | 22+, A2s+, K4s+, Q6s+, J7s+, T8s+, 97s+, 86s+, 76s, 65s, A4o+, KTo+, QJo, JTo |

**BB, the small blind is all-in: call with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 93s+, 84s+, 75s+, 64s+, 53s+, 43s, A2o+, K2o+, Q2o+, J2o+, T6o+, 96o+, 86o+ |
| 6 to 8bb | 22+, A2s+, K2s+, Q2s+, J5s+, T7s+, 97s+, 87s, A2o+, K2o+, Q6o+, J8o+, T9o |
| 9 to 12bb | 22+, A2s+, K2s+, Q6s+, J8s+, T9s, A2o+, K5o+, Q9o+, JTo |
| 13 to 17bb | 33+, A2s+, K7s+, Q9s+, JTs, A2o+, K9o+, QJo |
| 18 to 24bb | 33+, A2s+, K9s+, QTs+, A5o+, KTo+, QJo |
| 25bb or more | 44+, A5s+, KTs+, A8o+, KQo |

### Against players who call too much

Only the first-in ranges change; the call tables stay as they are.

**BTN, nobody has entered: all-in with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 33+, A2s+, K2s+, Q5s+, J7s+, T8s+, 98s, A2o+, K5o+, Q8o+, J9o+ |
| 6 to 8bb | 22+, A2s+, K5s+, Q9s+, J9s+, A2o+, K8o+, QTo+ |
| 9 to 12bb | 22+, A2s+, K9s+, QTs+, JTs, A2o+, KTo+, QJo |
| 13 to 17bb | 22+, A2s+, KTs+, A7o+, KJo+ |
| 18 to 24bb | 44+, A4s+, KJs+, A9o+, KQo |
| 25bb or more | 55+, ATs+, KQs, ATo+ |

**SB, the button folded: all-in with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 95s+, 85s+, 76s, A2o+, K2o+, Q2o+, J2o+, T5o+, 96o+, 87o |
| 6 to 8bb | 22+, A2s+, K2s+, Q2s+, J5s+, T6s+, 97s+, A2o+, K2o+, Q3o+, J7o+, T8o+, 98o |
| 9 to 12bb | 22+, A2s+, K2s+, Q5s+, J8s+, T9s, A2o+, K2o+, Q7o+, J9o+ |
| 13 to 17bb | 22+, A2s+, K4s+, Q8s+, J9s+, T9s, A2o+, K7o+, QTo+, JTo |
| 18 to 24bb | 22+, A2s+, K6s+, QTs+, JTs, A2o+, K9o+, QTo+ |
| 25bb or more | 22+, A2s+, KTs+, QTs+, A5o+, KJo+ |

**SB (button), first to act: all-in with**

| Effective stack | Hands |
|---|---|
| up to 5bb | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 94s+, 85s+, 75s+, A2o+, K2o+, Q2o+, J2o+, T5o+, 96o+, 87o |
| 6 to 8bb | 22+, A2s+, K2s+, Q2s+, J3s+, T6s+, 97s+, 87s, A2o+, K2o+, Q3o+, J7o+, T8o+ |
| 9 to 12bb | 22+, A2s+, K2s+, Q4s+, J8s+, T8s+, 98s, A2o+, K2o+, Q7o+, J9o+ |
| 13 to 17bb | 22+, A2s+, K2s+, Q8s+, JTs, T9s, A2o+, K7o+, QTo+, JTo |
| 18 to 24bb | 22+, A2s+, K6s+, Q9s+, JTs, A2o+, K9o+, QJo |
| 25bb or more | 22+, A2s+, KTs+, QTs+, T9s, A4o+, KJo+ |

### A limp or a small raise before you

All-in with these hands; otherwise fold to a raise and check when the small
blind only called. Never just call a raise.

| You are, and before you | up to 5bb | 6 to 8bb | 9 to 12bb | 13 to 17bb | 18 to 24bb | 25bb or more |
|---|---|---|---|---|---|---|
| SB, the button raised small (3 players) | as an all-in | 22+, A2s+, K4s+, Q8s+, J9s+, T9s, A2o+, K7o+, QTo+, JTo | 22+, A2s+, K7s+, Q9s+, J9s+, T9s, A2o+, KTo+, QJo | 22+, A2s+, K9s+, Q9s+, J9s+, T8s+, 98s, A4o+, KJo+, QJo | 22+, A2s+, K9s+, Q9s+, J9s+, T8s+, 98s, A7o+, KJo+, QJo | 22+, A5s+, K9s+, Q9s+, J9s+, T9s, 98s, ATo+, KQo |
| BB, the button raised small (3 players) | as an all-in | 22+, A2s+, K2s+, Q7s+, J8s+, T9s, A2o+, K6o+, Q9o+, JTo | 22+, A2s+, K3s+, Q8s+, J8s+, T8s+, 98s, A2o+, K8o+, QTo+, JTo | 22+, A2s+, K6s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, A2o+, KTo+, QTo+, JTo | 22+, A2s+, K9s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, A2o+, KTo+, QTo+, JTo | 22+, A2s+, K9s+, Q9s+, J8s+, T8s+, 98s, 87s, A8o+, KJo+, QJo, JTo |
| BB, the small blind raised small (3 players) | as an all-in | 22+, A2s+, K2s+, Q5s+, J8s+, T8s+, A2o+, K4o+, Q8o+, J9o+ | 22+, A2s+, K2s+, Q6s+, J8s+, T7s+, 97s+, 87s, 76s, A2o+, K5o+, Q9o+, JTo | 22+, A2s+, K4s+, Q8s+, J8s+, T7s+, 97s+, 86s+, 76s, 65s, A2o+, K9o+, QTo+, JTo | 22+, A2s+, K6s+, Q8s+, J8s+, T7s+, 97s+, 86s+, 76s, 65s, A2o+, KTo+, QTo+, JTo | 22+, A2s+, K9s+, Q9s+, J8s+, T8s+, 98s, 87s, A4o+, KTo+, QTo+, JTo |
| BB, the small blind limped (3 players) | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 94s+, 85s+, 75s+, 64s+, 54s, A2o+, K2o+, Q2o+, J3o+, T6o+, 96o+, 87o | 22+, A2s+, K2s+, Q2s+, J3s+, T5s+, 95s+, 85s+, 74s+, 64s+, 53s+, A2o+, K2o+, Q5o+, J8o+, T8o+, 98o, 87o | 22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 95s+, 85s+, 74s+, 64s+, 53s+, A2o+, K2o+, Q8o+, J9o+, T8o+, 98o | 22+, A2s+, K2s+, Q5s+, J7s+, T6s+, 96s+, 85s+, 75s+, 65s, 54s, A2o+, K9o+, QTo+, J9o+, T9o | 22+, A2s+, K4s+, Q8s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, A2o+, KTo+, QTo+, JTo, T9o | 22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 87s, A7o+, KTo+, QTo+, JTo |
| BB, the small blind raised small (heads-up) | as an all-in | 22+, A2s+, K2s+, Q4s+, J7s+, T8s+, 98s, A2o+, K2o+, Q8o+, J9o+, T9o | 22+, A2s+, K2s+, Q4s+, J7s+, T7s+, 97s+, 87s, 76s, A2o+, K3o+, Q9o+, J9o+, T9o | 22+, A2s+, K2s+, Q6s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, A2o+, K8o+, QTo+, JTo, T9o | 22+, A2s+, K4s+, Q8s+, J8s+, T7s+, 97s+, 86s+, 76s, 65s, A2o+, KTo+, QTo+, JTo | 22+, A2s+, K8s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, A3o+, KTo+, QTo+, JTo |
| BB, the small blind limped (heads-up) | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 84s+, 74s+, 64s+, 53s+, A2o+, K2o+, Q2o+, J2o+, T5o+, 96o+, 86o+, 76o | 22+, A2s+, K2s+, Q2s+, J2s+, T3s+, 95s+, 84s+, 74s+, 64s+, 53s+, 43s, A2o+, K2o+, Q3o+, J7o+, T7o+, 97o+, 87o, 76o | 22+, A2s+, K2s+, Q2s+, J4s+, T4s+, 95s+, 85s+, 74s+, 64s+, 53s+, 43s, A2o+, K2o+, Q8o+, J8o+, T8o+, 98o, 87o | 22+, A2s+, K2s+, Q5s+, J7s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A2o+, K8o+, QTo+, J9o+, T9o, 98o | 22+, A2s+, K4s+, Q7s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, A2o+, KTo+, QTo+, J9o+, T9o | 22+, A2s+, K7s+, Q8s+, J8s+, T7s+, 97s+, 87s, 76s, A4o+, KTo+, QTo+, JTo |

These rows assume the button raises about 45% of hands and the small blind
raises 55% to 60% and limps 70% to 75%. Against a player who only raises
strong hands, use the all-in tables. A raise of a third of the raiser's stack
or more is an all-in in practice. After a free flop in the big blind: all-in
with top pair or better or a draw with 12 outs, otherwise check and fold to a
bet.

### Limits

- Pages 1 to 3 of the sheet (the tables above) are the exact solution of the
  all-in or fold game with real cards, for equal stacks. Unequal stacks are
  read at the effective stack, which is an approximation; the simulation
  plays it that way, so its cost is in the numbers.
- The simulation's opponents also play all-in or fold. Real ones raise small
  and limp. Good players gain from that against an all-in or fold player;
  weak ones lose more with it.
- Prizes and the fee are GGPoker's own tables (November 2026). Starting
  stacks and level lengths come from two 2026 guides, whether there is an
  ante is not confirmed, and 3 hands a minute is assumed (2 to 4 moves the
  win rate by 0.3 points).
- In the 2.4% of games that pay second place the ranges are not adjusted.
- Swings: at a 36% win rate a run of 13 lost games comes about once in 1,000
  games and a drop of 60 buy-ins is ordinary. Published bankroll advice is
  120 to 300 buy-ins.
- GGPoker forbids charts during play. The sheet is a study aid.
