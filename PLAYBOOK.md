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
out, or under bubble pressure while you cover them. With a blind sitting out
the coach counts only the players still active behind you, and never uses a
tighter row than your seat's own: the button keeps the button's row.

Sizes: 2x under 25bb, 2.2x to 40bb, 2.3-2.5x deeper, 3x from the small blind.

## Facing a raise

- **Out of position: 3-bet or fold** (the big blind may also call at a good price).
- **Value 3-bets:** QQ+/AK against early position; add JJ, AQs against middle;
  add TT, AQo, AJs, KQs against CO/BTN steals.
- **26 to 45bb: re-raise small only with a hand that calls an all-in over
  it** (about JJ+ and AK; against an early raise QQ+ and AK). TT, AQ and
  hands like them move all-in where that clearly earns; otherwise they call
  in position or in the big blind, and from the small blind the weaker ones
  (KQs, AJs, AQo) fold. Bluff re-raises start above 45bb.
- **Calls in position:** medium pairs, AQs/AJs/KQs, suited broadways. Small
  pairs only with 15x the raise behind (set-mining).
- **25bb or less: re-shove or fold.** The solver prices it. With 15-20bb the
  profitable re-shoves are roughly: from the button over a cutoff open 15%
  (33+, A8s+, ATo+, KTs+, QTs+, KQo); from the big blind over a button steal
  30% (any pair, any ace, suited kings, broadways); over an early-position
  open only 9% (77+, ATs+, AJo+, KQs).
- **A raise and a re-raise in front:** KK+ and AKs; against a first raise
  from LJ or HJ also AKo, and QQ with 24bb or less; against CO or BTN JJ+
  and AK. Never just call.
- **An all-in and a raise over it:** the player who raises over a short
  all-in does it with many more hands than a re-raise over a full raise.
  With 45bb or less a hand moves all-in when it is ahead of those hands
  (55% or more against all of them, and at least even against the better
  half) and the all-in's number clears +1bb: against a 5bb all-in and a
  raise to 11bb about 99+ and AQ; against a 12bb all-in and a raise to 26bb
  still JJ+ and AK only. Against a raiser tagged nit or tight only JJ+ and
  AK play.
- **You raised, a player re-raised and another moved all-in over both:**
  that all-in is the narrowest range before the flop, and the re-raiser is
  still behind you. Deep, only AA and KK go on. With 40bb QQ is close and
  AK folds. With 25bb or less QQ+ and AK go on, and JJ after a raise from
  CO or later; with about 12bb also TT and AQs. Against a tight player one
  notch fewer, against a loose one a notch more.
- **You opened and got 3-bet:** with 45bb or less the all-in goes by the
  seat you raised from: KK+ and AKs from UTG or UTG+1; QQ+ and AK from LJ
  or HJ; TT+, AQs+ and AKo from CO, BTN or SB. TT+, AQs+ and AKo are not
  folded to one re-raise while they have 10 points of equity over the price
  of the call (with prizes: over the price and the risk premium), and AA
  and KK never: where the all-in does not earn enough they call, and move
  all-in instead when the call would leave less than the pot behind. After
  such a call the stack goes in with an overpair, top pair or better. With
  fewer points than that the fold is close, and the coach says so. The rest
  folds unless the 3-bettor is wild. Deeper than 45bb QQ+ and AK never fold
  to one re-raise: KK+ re-raise again; QQ and AK call in position, and out
  of position move all-in with 60bb or less and call when deeper; JJ, TT
  and AQs call as well while they have those 10 points.

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
- **Multi-way:** bet only real hands and strong draws. A strong draw is 12
  outs or more: bet it when you raised before the flop or act last, away
  from the bubble.
- **Value bet** top pair good kicker or better; size up (2/3 pot) on wet
  boards and on the turn. A bet that would take two thirds or more of what
  is behind is made as the all-in. Top pair's small bet as the raiser is a
  value bet too: fold it to a raise unless the player is aggressive.
- **A strong made hand is never a bluff.** Top pair with a good kicker or
  better that is not far enough ahead to bet for value checks, and calls one
  reasonable bet.
- **One pair is a two-street hand.** Facing a turn raise or a big river bet
  with one pair: fold, especially against passive players. The table app
  folds there against every player not tagged lag or maniac, except with an
  overpair or top pair after you called a re-raise before the flop on the
  plan to play for stacks.
- **No pair and no draw:** fold to a bet of half the pot or more from a
  player who did not raise before the flop. Only the raiser's flop bet is a
  continuation bet.
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
left (the small-blind row already counts it). An all-in bigger than 40bb is
read from the 25 to 40bb column.

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
- **A cheap call of an all-in:** the call tables read the size of the
  all-in, not the price. When the play with all moves calls, for less than
  a third of your stack and at 3 to 1 or better (or with 15 points of
  equity to spare), the table app calls in this plan too.
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
| Nobody has entered | Raise the opening range of your seat (17 to 24bb: a little tighter up to the cutoff, mainly without the small suited connectors; the button and the small blind keep theirs) | All-in with the all-in or fold hands of your seat. QQ+ and AK may raise 2bb at 12 to 16bb and call any all-in |
| Players only called | Raise to 3bb plus 1bb per caller (4bb plus 1bb from the blinds) with the opening range of the seat one line tighter for each caller (from the blinds: counted from the cutoff's line), and always with 99+, AJs+, AQo+, KQs. With 17 to 24bb the lists lose T8s and the suited connectors below T9s (UTG+1 also T9s; the button keeps them). Four callers or more: fewer hands again with each caller. Otherwise fold; the big blind checks | All-in with the all-in hands of the seat before yours (big blind: the small blind's). Otherwise fold; the big blind checks |
| One raise | 25bb or more: re-raise, call or fold by where the raise came from and where you sit | 24bb or less: all-in or fold, from the raise table of the all-in or fold section |
| A raise and a call | The same hands; the re-raise is one raise bigger for each caller | The same all-in hands |
| A raise and a re-raise | The table below | The table below |
| You raised and were re-raised | The table below | (you do not raise small this short) |
| You raised and met an all-in | Call with the hands of your opening range that beat the pot odds by 6 points, 16 on the bubble. Against 7bb or less: every hand you raised (on the bubble without the smallest suited connectors) | |
| An all-in, or two | The call tables of the all-in or fold section, by the size of the all-in | The same |

A raise and a re-raise before you (everything else folds):

| The first raise came from | Re-raise, more than 60bb | All-in, 25 to 60bb | All-in, up to 24bb |
|---|---|---|---|
| UTG or UTG+1 | KK+ | KK+, AKs | KK+, AKs |
| LJ or HJ | KK+, AKs | KK+, AKs, AKo | QQ+, AKs, AKo |
| CO or BTN | KK+, AKs, AKo | JJ+, AKs, AKo | JJ+, AKs, AKo |

You raised and were re-raised, not all-in (everything else folds):

| You raised from | All-in, 45bb or less | Call, 45bb or less | Re-raise, more than 45bb | Call, more than 45bb |
|---|---|---|---|---|
| UTG or UTG+1 | KK+, AKs | QQ | KK+ | QQ, AKs, AKo |
| LJ or HJ | QQ+, AKs, AKo | JJ (seven and eight players) | KK+ | QQ-JJ, AKs, AKo |
| CO or BTN | TT+, AQs+, AKo | | KK+ | QQ-44, AJs+, AKo |
| SB | TT+, AQs+, AKo | | KK+ | QQ-TT, AQs+, AKo |

TT+, AQs+ and AKo are not folded to one re-raise while they have 10 points
of equity over the price (with prizes: over the price and the risk premium),
and AA and KK never: where the all-in does not earn enough they call. With
less than the pot behind after the call they move all-in instead, unless
that all-in loses. After the flop the stack goes in with an overpair, top
pair or better.

These lists are for a re-raise from the big blind, where you act last after
the flop in every row but the small blind's. Out of position (the small
blind's row, or a re-raise from a seat behind you that is not a blind) QQ,
AKs and AKo move all-in with 46 to 60bb instead of calling.

- **Calling along** behind players who only called: with 25bb or more, from
  the cutoff, the button or the small blind, when the hand is not on the
  raise list: 22-88, A2s-A9s, K9s, KTs, Q9s, QTs, J9s, JTs, T9s, 98s, 87s, 76s, 65s, 54s.
- **Big blind, players only called:** raise from the list or check. A check
  costs nothing; never fold. After the flop bet top pair or better and
  strong draws, otherwise check and fold to a bet.
- **Big blind against one raise of 2.5bb or less, with 9 to 24bb:** instead
  of folding it may call with any pair, any suited hand, any ace, K9o+, Q9o+, J9o+ and T9o.
  The engine's own list comes from one price test for every hand and is
  wider in offsuit hands: about half of all hands against an early raise,
  about 70% against the hijack or cutoff and about 80% against the button
  or small blind. The sheet keeps the part that makes top pair or a real
  draw. In the table app a close call before the money stays only for a
  hand on this list (with 25bb or more it must also be on the sheet's own
  list for the big blind). "Close" is said there when the hand has fewer
  than 7 points over what the call needs; with more, a hand on the list is
  a plain call and a hand off it is the sheet's fold.
- **Big blind against one raise, with 25bb or more:** the sheet's lists are
  the answers to a raise of 2.3bb from UTG, HJ and CO. Against LJ a few
  offsuit calls go (K8o-K6o, Q9o, J9o, T9o at eight players), against the
  button a few come (K2o, Q7o-Q4o, J8o-J7o, T8o-T7o, 97o+, 87o); the sheet
  prints both. The call goes by the price: a smaller raise adds a few
  hands, a bigger one takes some away.
- **You only called and a player raised:** fold. With a pair and 15 times
  the raise behind you may call once. The table app also calls, whatever
  the hand, a raise that costs a fifth of the pot or less (5 to 1 or
  better): the rule is for a real raise. On the bubble it does not make
  that call for a third or more of your chips.
- **Where the hands come from.** The raise, call and re-raise lists are what
  `advise` answers on chips alone (no prizes counted, an ante of an eighth
  of a big blind from each player) for each of the 169 hands; a test checks
  it. With players left and places paid entered the answers are tighter. Each list is the answer at one stack, which the sheet names:
  first in 50 and 22bb, behind callers 40 and 20bb, against a raise 60bb, a
  raise and a re-raise 20, 40 and 100bb, re-raised 35 and 70bb. Against a
  raise every row is one question, so each hand played there is on one
  list; with 26 to 45bb the hands of a re-raise list that cannot call an
  all-in move all-in or call ("Facing a raise" has the rule), and the bluff
  lists fold. The all-in lists first in and over one raise, and the calls
  of an all-in, are taken from the all-in or fold section, so they are
  tighter than the chip-EV push/fold table earlier in this playbook.
  That chip-EV table is still what opponents are assumed to play, and what
  the coach leans to when survival does not matter.
- **Limits.** Stacks are taken as equal. The ante is an eighth of a big
  blind for each player; for the raise, call and re-raise lists the big
  blind posts it for the table. Three stack columns stand for every stack
  under 17bb, and a list that stands for a band of stacks or a pair of
  seats is exact only at the stack and seat it was asked for. With the
  table tracked, `advise` prices the real stacks and prizes. The PDF sheets
  were printed before these lists were rebuilt: where they differ, the text
  from `tag-sheet` is right.

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

The first-in ranges change most, and they are printed here. The calls shift
as well: the small blind calls the button's all-in tighter (a loose big
blind is still behind), and the big blind calls two all-ins wider.
`spin-sheet --vs loose` prints them.

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

### Six players (6-Max)

GGPoker also runs Spin & Gold with six players. Six buy-ins pay back 5.58 on
average (the same 7% fee), so an even player wins 16.7% of games and
break-even is 17.9%.

| Multiplier | Share of games | Paid | Starting stack | Blinds go up |
|---|---|---|---|---|
| x4 | 47.9% | winner only | 300 chips (15bb) | every minute |
| x6 | 44.6% | winner only | 300 chips (15bb) | every 2 minutes |
| x8 | 2.65% | winner only | 500 chips (25bb) | every 2 minutes |
| x10 | 2.5% | two places | 500 chips (25bb) | every 3 minutes |
| x20 | 2.35% | two places | 500 chips (25bb) | every 10 hands |
| x100, x200 | 0.012% | four places | 800 chips (40bb) | every 15 hands |

- **One prize in 95% of the games**, so chips are money there as well, and
  the game starts like a six-handed push/fold tournament without antes:
  tight from the first seats, wide from the button and the small blind. The
  table app answers with the engine on chips (the push/fold solver on the
  real stacks, the opening chart of the seat above 16bb) while four to six
  players are in, and with the tables above once three are left.
- **Two prizes (x10, x20):** type them in the table app and it counts them
  by ICM. Three players left is then a real bubble: call all-ins tighter,
  and keep moving in on the players who can still go out before the money.
  Heads-up both have the second prize, and it is chips again.
- **Not measured.** No simulation of whole six-player games was run, so
  there is no win rate to quote for these answers. The prize split of the
  x10 and x20 games was not found in print (one guide says two places, an
  older article says three): read the prizes in the lobby. Stacks, level
  lengths and the shares above come from one 2026 guide; the big blinds
  assume the 10/20 first level of the three-player game.

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


## Play to win: the quick guide's wider ranges

The quick guide (`guide/`) has two styles. `Tight` is everything above.
`Play to win` is the same engine with these changes, for a player who finds
the tight ranges give up too many pots. It counts chips only: no prizes.

Opening ranges, folded to you, 30bb or more:

| Seat (players behind) | Opens | Range |
|---|---|---|
| UTG (8) | 13% | 55+, A9s+, A5s-A3s, KTs+, QTs+, J9s+, T9s, 98s, AJo+, KQo |
| UTG+1 (7) | 17% | 44+, A7s+, A5s-A2s, K9s+, Q9s+, J9s+, T9s, 98s, 87s, ATo+, KJo+ |
| UTG+2 (6) | 20% | 33+, A2s+, K8s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, ATo+, KJo+, QJo |
| LJ (5) | 23% | 22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, ATo+, KTo+, QJo |
| HJ (4) | 27% | 22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 76s, 65s, 54s, A9o+, KTo+, QTo+, JTo |
| CO (3) | 36% | 22+, A2s+, K2s+, Q6s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, A7o+, A5o, K9o+, Q9o+, J9o+, T9o |
| BTN (2) | 50% | 22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 95s+, 85s+, 74s+, 64s+, 53s+, A2o+, K7o+, Q8o+, J8o+, T8o+, 98o, 87o |
| SB (1) | 50% | 22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A2o+, K5o+, Q8o+, J8o+, T8o+, 98o |

With 25bb or less every seat up to the cutoff loses its small suited
connectors and weakest suited hands (the cutoff keeps J9s and T9s and drops
J8s, T8s, 97s, 86s, 76s and below). The button opens the tight row there:
22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, A2o+, K8o+,
Q9o+, J9o+, T9o (41%). The small blind keeps its row.

Why the button: a solver's opening width with 20bb (nine players, a big
blind ante, chips only) is 15.6% from the first seat, 31.2% from the cutoff
and 41.5% from the button (36.1% as a raise, 5.4% as an all-in). The rows
give 12%, 32% and 41%; the full button row made it 50%.

- **Opponents are taken to open the same rows.** So re-raises and all-ins
  over their raises get wider with them: there is more to fold out. Against
  a table that opens tighter than this, set Opponents to Tight. With 25bb
  or less a raise from the cutoff or the button is read as that seat's
  short row (32% and 41%), not the deep one (36% and 50%); the seats before
  them keep their full rows, which are no wider than a solver's with 20bb.
- **13 to 16bb, first in:** a hand of the row that is not a profitable
  all-in is raised to 2bb, and folded to an all-in unless the plan under it
  says call. The tight style folds it.
- **Against a raise from the cutoff or the button:** more calls and
  re-raises than the tight chart. Against a raise from the first seats 13%
  of hands instead of 9% (call JJ-66, AQs-ATs, KQs, KJs, QJs, JTs and AQo;
  small pairs with 15 times the raise behind; deeper than 45bb re-raise
  A5s and A4s as a bluff). Against the hijack 16% instead of 12%; on the
  button against the cutoff 20% instead of 15% (adds 44, A9s, A8s, 87s and
  KJo to the calls). A solver plays about 25% on the button against a
  first-seat raise with 100bb: this goes half of the way. The hijack and
  earlier seats, and the small blind's calls, keep the tight chart.
- **In position against a raise, 15 to 25bb:** a hand the chart plays that
  is no profitable all-in calls, with 10 points over the price.
- **You raised and were re-raised:** the all-in needs half as much (0.25bb,
  and 42% when called); TT+, AQs+ and AKo go on with 5 points over the
  price; in position with 25bb or more 77+, ATs+, KTs+, QTs+ and JTs call
  with 3 points over the price after an 8% discount on their equity.
- **The all-in bars are the tight style's.** The width comes from the rows
  and the calls, not from thinner all-ins.
- **Limits.** The rows are written by hand from standard modern ranges, not
  solved, and nothing here has been measured against results. They are
  right for a table that plays back the way these ranges assume; against
  players who never fold, drop the bottom of each row.

### The big blind against a raise (both styles of the guide)

One test for every hand, at every stack:

    equity against the raiser's range  x  the share of it the hand keeps
        must be at least  the price of the call + 3 points   (Tight: 5)

- **The price** is the call as a share of the pot after it. With a big
  blind ante and the small blind out: a raise to 2bb asks for 18%, 2.2bb
  20%, 2.5bb 23%, 3bb 27%, 4bb 32%. That is the whole effect of the size of
  the raise, and it is large: the guide asks how much they raised.
- **The share a hand keeps.** Out of position a hand folds some flops it
  would have won, so it turns only a part of its equity into chips: more
  when it is suited, connected or high.

  | Hand | Keeps | Hand | Keeps | Hand | Keeps |
  |---|---|---|---|---|---|
  | AA | 100% | AKs, KQs | 105% | KQo | 92% |
  | 77 | 86% | T9s | 104% | AJo, T9o | 84% |
  | 22 | 76% | A5s | 95% | K7o | 70% |
  | | | 76s | 93% | Q5o | 66% |
  | | | K7s | 90% | 72o | 54% |
  | | | 32s | 76% | | |

  Offsuit hands keep 2 points less each time the stack doubles over 25bb.
  Against a raise from the small blind the big blind acts last and every
  hand keeps 22 points more (110% at most).
- **Or an all-in.** With 25bb or less a hand moves all-in when that earns
  0.15bb or more; in Play to win only when it also earns more than the call
  is worth (the kept equity times the pot, less the call).
- **Every stack.** The coach's default style calls a raise only when it
  costs 12% of the stack or less and moves all-in or folds below that: with
  9bb it folds 63% of hands to a button raise of 2bb. The guide's styles do
  not. The price is the same 18% at 8bb, the big blind folds the same 16%
  of hands, and after a call this short the flop decides it: all-in with
  any pair or any draw, otherwise give up.
- **Against a solver.** How often the big blind folds: GTO Wizard's numbers
  as PokerNews printed them in 2026, and the guide's tables.

  | Raise from | to | Stack | Solver | Play to win | Tight |
  |---|---|---|---|---|---|
  | First seat of eight | 2bb | 25bb | 27% | 31% | 47% |
  | First seat of eight | 3bb | 25bb | 71% | 69% | 79% |
  | First seat of eight | 2bb | 50bb | 32% | 33% | 50% |
  | First seat of eight | 3bb | 50bb | 73% | 69% | 80% |
  | First seat of eight | 2.1bb (guide: 2.2bb) | 100bb | 37% | 45% | 62% |
  | First seat of eight | 3bb | 100bb | 73% | 70% | 82% |
  | Cutoff | 2.2bb | 100bb | 23% | 33% | 46% |
  | Cutoff | 3bb | 100bb | 47% | 57% | 69% |
  | Small blind | 2bb | 25bb | next to none | 1% | 9% |
  | Small blind | 2bb | 100bb | 1% | 5% | 14% |

  Against the small blind's 3.5bb with 100bb the solver calls 57% and
  re-raises more; Play to win folds 32% to 3bb and 47% to 4bb. So Play to
  win is within 4 points of the solver against an early raise with 25 to
  50bb and folds about 10 points more often against the cutoff with 100bb;
  Tight folds 10 to 17 points more than Play to win.
- **At the table.** Q5o in the big blind calls a cutoff raise to 2bb with
  20bb and folds to 2.5bb. A call that looks too loose is usually the
  answer for a smaller raise than the one that was made: check the size.
- **Callers in the pot.** The price counts their chips, so the equity
  counts their hands: each opponent by his odds against the hand (three
  hands of the same strength win a third each; against the cards dealt out
  this is right to a point on average, and 3 points low for suited
  connectors). The margin shrinks with the fair share of the pot: 2 points
  with one caller, 1.5 with two. The big blind then folds more than
  heads-up, although the price is better: with 40bb against a cutoff raise
  to 2bb Play to win folds 22% of hands, 39% when the button has called,
  52% when the small blind has called too. What still calls is suited,
  connected or high; offsuit hands like Q5o and J4o go. A player who
  called is taken to hold what his seat's chart calls with; a small blind
  who called, the button's calls (his own chart re-raises or folds).
- **Limits.** The share is a formula set against those ten numbers, not a
  solver, and nothing above has been set against a solver for pots with
  callers in.

## Turbo and hyper-turbo

The quick guide has a Blinds choice (Regular, Turbo, Hyper) and one set of
tables behind all three. This section says why, what the fast formats do
change, and what the tables were checked against.

### The play does not change with the speed

With the same stack, seat and action in front of you, the right play is the
same in a hyper-turbo as in a slow tournament: the cards, the blinds and the
antes of the hand are the same, and so is what each play wins and loses.
There are no "turbo ranges" for 15bb on the button that differ from the
regular ones. Published advice says the same: "we play the same range we
always do, but the faster the structure, the less we should pass marginal
spots". What the speed changes is around the hand:

- **The stacks you play.** A regular tournament is played at 30bb and more
  for hours. A turbo is at 15 to 25bb within an hour, a hyper at 5 to 15bb
  nearly from the start. The tables that matter are the short ones.
- **What a fold costs.** Blinds paid, and blinds grown by the time you play
  again (the clock, below).
- **Close plays.** Passing a thin edge to wait for a better one only makes
  sense when there is time to wait. In a turbo or a hyper, take the plays
  the guide marks close.
- **Prizes come sooner and with shorter stacks.** The bubble of a hyper is
  played with 5 to 10bb. The guide's Bubble stage is a rule of thumb
  (fold the close ones, 10 points more to call an all-in); with the stacks
  and prizes entered, `advise` or the table app is exact.

### What folding costs: the blinds clock

Eight players, from the button. One round of folding costs the two blinds
and the ante (2.5bb), and the blinds rise while it is paid. The stack after
that round, counted in the big blinds of that moment:

| Stack now | Regular | Turbo | Hyper |
|---|---|---|---|
| 30bb | 24.5bb | 21.5bb | 16.7bb |
| 20bb | 15.5bb | 13.6bb | 10.4bb |
| 15bb | 11.0bb | 9.6bb | 7.2bb |
| 12bb | 8.3bb | 7.2bb | 5.3bb |
| 10bb | 6.5bb | 5.6bb | 4.1bb |
| 8bb | 4.7bb | 4.0bb | 2.8bb |
| 6bb | 2.9bb | 2.4bb | 1.5bb |
| 4bb | 1.2bb | 0.8bb | 0.3bb |

Levels are taken as about 12 hands (regular, 10 to 12 minutes), 6.5 hands
(turbo, 5 to 6 minutes) and 3.5 hands (hyper, 3 minutes), each 17%, 20% and
22% higher than the one before: the coach's tournament model, fitted to
GGPoker fields. Hyper-turbos were not measured. `python3 -m poker_coach
clock --stack 12 --pos BTN --players 8 --speed hyper` gives the numbers for
any seat; the guide shows them under the answer.

What it means at the table:

- **A stack is worth what it will be when you next want to use it.** 12bb
  on the button of a hyper is 5bb a round later. First in from the button,
  an all-in gets through 56% of the time with 12bb and 18% with 5bb.
- **Under about 6bb the fold is gone.** The big blind has a third of the
  pot or less to call and calls with most of his hands. From there a hand
  has to win at a showdown, so the ranges below are tighter from the first
  seats than most players expect, and far wider from the small blind.
- **Do not pass a play the chart gives you** when a round of folding would
  leave less than 10bb. The plays are already the ones that earn chips;
  what waits behind a fold is a smaller stack, not a better spot.

### All-ins of 20bb or less: solved exactly

The usual push-or-fold chart, and the engine's own solver, leave two things
out, and with a short stack both count:

- **A short all-in is often called twice.** The solver sets the player who
  moves in against one caller at a time: when two would call, the first is
  the hand to beat and the other's chips are dead money. With a few big
  blinds the big blind calls with nearly everything and a second caller is
  the rule. With 3bb and nine players the old tables moved all-in first to
  act with 84% of hands where the answer is 26%, called an all-in on the
  button with 76% where it is 23%, and moved in behind a player who only
  called with 98%.
- **What was folded is out of the deck.** The solver deals every opponent
  from a full deck. But at a full table seven players have folded, and what
  they folded is mostly middle and low cards: those cards are rarer on the
  board and in the hands still to come, the aces and kings are not. Against
  an all-in a hand like T8o or 87o is about three points worse than its
  plain odds say, a small pair a little worse, a small ace a little better.
  With 6bb and nine players the old tables had the big blind call a cutoff
  all-in with 65% of hands where the answer is 47%. From 12bb up the two are
  within about 4 points of hands everywhere but the small blind first in
  (70% of hands for 63% with 12bb, 55% for 48% with 20bb).

So these all-ins are not left to that solver. The game (equal stacks, a
small blind of half a big blind, a big blind ante of one, every player
all-in or fold) is solved with real cards, every showdown and every side
pot (`tools/aof_solver.c`, the solver of the All-In or Fold tables, run by
`tools/build_short.py`), for tables of 9, 6, 5, 4 and 3 players, at every
stack from 2 to 10bb and at 12, 16 and 20bb (a stack between two of them is
read off the straight line between). Tables of 7 and 8 are read from the
last seats of the nine; two players are left to the engine's solver, which
is exact heads-up.

The numbers come from dealing cards, so they carry noise, and the hands a
chart is read for are the ones near zero. Each solution is therefore made in
two passes: every hand of every decision point is dealt 10,000 times, and
then every hand that came out near zero (within about four times the noise:
one hand in seven) is dealt another 100,000 times against the same solved
strategies. At a full table the second pass moved about a hundred hands a
stack to the other side of zero (1,140 over the twelve stacks). The hands
that were in from one seat and out from the next, three to eleven a stack
after the first pass, were gone with 7bb or less, and one to three were left
with 8 to 12bb, each inside the band where either play is right. After it a
number near zero is good to about 0.02bb with 6bb, 0.03bb with 10bb and
0.06bb with 20bb.

What the engine takes from the solution:

- **Up to 10bb, the whole answer.** Every hand is an all-in or a fold, and
  the solved game is the game.
- **From 11 to 20bb, the all-in.** There are small raises as well, and
  which hands raise is the opening range's business; but what an all-in
  earns first in, and whether to call one or two, is read from the exact
  numbers.
- **Who moved in.** With 10bb or less an all-in is the solved range itself.
  Deeper a player has other plays, and his all-in is taken a little
  tighter: a tenth tighter at 20bb, which is what the deeper tables have
  always assumed of a player with no read. Opponents (Tight, Loose) moves
  that range and so the calls; the all-ins first in are the same against
  everybody.

First in at a table of nine: the share of hands that are a profitable
all-in.

| Seat | 2bb | 3bb | 4bb | 5bb | 6bb | 7bb | 8bb | 9bb | 10bb |
|---|---|---|---|---|---|---|---|---|---|
| UTG | 29% | 26% | 23% | 21% | 20% | 18% | 17% | 16% | 15% |
| UTG+1 | 31% | 28% | 25% | 24% | 22% | 20% | 20% | 18% | 17% |
| UTG+2 | 36% | 30% | 28% | 28% | 24% | 23% | 22% | 20% | 19% |
| LJ | 39% | 33% | 31% | 29% | 29% | 27% | 25% | 24% | 22% |
| HJ | 41% | 36% | 33% | 32% | 32% | 30% | 29% | 28% | 25% |
| CO | 48% | 42% | 40% | 37% | 35% | 33% | 33% | 31% | 32% |
| BTN | 57% | 51% | 48% | 46% | 46% | 43% | 41% | 40% | 38% |
| SB | 100% | 96% | 85% | 79% | 76% | 75% | 73% | 67% | 68% |

With 3bb, the hands:

| Seat | All-in with |
|---|---|
| UTG | 44+, A2s+, K6s+, Q8s+, J9s+, T8s+, 98s, A7o+, A5o, KTo+, QTo+, JTo |
| UTG+1 | 44+, A2s+, K5s+, Q8s+, J8s+, T8s+, 98s, A7o+, A5o-A4o, KTo+, QTo+, JTo |
| UTG+2 | 44+, A2s+, K4s+, Q8s+, J8s+, T8s+, 98s, A4o+, K9o+, QTo+, JTo |
| LJ | 33+, A2s+, K3s+, Q8s+, J8s+, T8s+, 98s, A2o+, K9o+, Q9o+, JTo |
| HJ | 33+, A2s+, K2s+, Q6s+, J7s+, T8s+, 98s, A2o+, K8o+, Q9o+, J9o+ |
| CO | 22+, A2s+, K2s+, Q4s+, J7s+, T7s+, 97s+, A2o+, K5o+, Q8o+, J9o+, T9o |
| BTN | 22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 97s+, 87s, A2o+, K2o+, Q6o+, J8o+, T8o+ |
| SB | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 82s+, 72s+, 62s+, 52s+, 42s+, 32s, A2o+, K2o+, Q2o+, J2o+, T2o+, 92o+, 82o+, 72o+, 63o+, 53o+, 43o |

With 6bb:

| Seat | All-in with |
|---|---|
| UTG | 33+, A2s+, K9s+, Q9s+, J9s+, T9s, A8o+, KJo+, QJo |
| UTG+1 | 22+, A2s+, K9s+, Q9s+, J9s+, T9s, A7o+, KTo+, QJo |
| UTG+2 | 22+, A2s+, K9s+, Q9s+, J9s+, T9s, A5o+, KTo+, QJo |
| LJ | 22+, A2s+, K7s+, Q9s+, J9s+, T9s, A2o+, KTo+, QTo+, JTo |
| HJ | 22+, A2s+, K5s+, Q8s+, J8s+, T8s+, A2o+, K9o+, QTo+, JTo |
| CO | 22+, A2s+, K2s+, Q7s+, J8s+, T8s+, 98s, A2o+, K8o+, Q9o+, JTo |
| BTN | 22+, A2s+, K2s+, Q3s+, J7s+, T7s+, 97s+, 87s, A2o+, K2o+, Q8o+, J9o+, T9o |
| SB | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 84s+, 74s+, 64s+, 53s+, 43s, A2o+, K2o+, Q2o+, J2o+, T3o+, 96o+, 86o+, 76o |

With 10bb:

| Seat | All-in with |
|---|---|
| UTG | 44+, A7s+, A5s, K9s+, Q9s+, J9s+, T9s, ATo+, KQo |
| UTG+1 | 33+, A3s+, K9s+, Q9s+, J9s+, T9s, ATo+, KJo+ |
| UTG+2 | 22+, A3s+, K9s+, Q9s+, J9s+, T9s, A9o+, KJo+ |
| LJ | 22+, A2s+, K8s+, Q9s+, J9s+, T8s+, 98s, A8o+, KTo+, QJo |
| HJ | 22+, A2s+, K9s+, Q9s+, J9s+, T9s, A4o+, KTo+, QJo |
| CO | 22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 98s, 87s, A2o+, KTo+, QTo+, JTo |
| BTN | 22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 97s+, 87s, 76s, A2o+, K9o+, Q9o+, J9o+, T9o |
| SB | 22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 94s+, 84s+, 74s+, 64s+, 53s+, 43s, A2o+, K2o+, Q2o+, J5o+, T7o+, 97o+, 87o, 76o |

Calling one all-in at a table of nine: the share of hands that call, in the
solved game.

| You, and the all-in from | 2bb | 3bb | 4bb | 5bb | 6bb | 7bb | 8bb | 9bb | 10bb | 12bb | 16bb | 20bb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| UTG+1, UTG | 23% | 17% | 14% | 12% | 11% | 9% | 8% | 8% | 8% | 6% | 4% | 4% |
| BTN, UTG | 30% | 23% | 20% | 16% | 13% | 11% | 10% | 10% | 8% | 6% | 5% | 5% |
| BTN, CO | 38% | 31% | 29% | 24% | 22% | 19% | 18% | 17% | 16% | 15% | 12% | 10% |
| SB, BTN | 77% | 55% | 44% | 36% | 33% | 31% | 29% | 26% | 26% | 22% | 18% | 15% |
| BB, UTG | 100% | 100% | 95% | 60% | 36% | 27% | 21% | 17% | 12% | 10% | 5% | 5% |
| BB, CO | 100% | 100% | 95% | 67% | 47% | 36% | 31% | 28% | 27% | 25% | 18% | 13% |
| BB, BTN | 100% | 100% | 96% | 73% | 52% | 45% | 36% | 33% | 31% | 28% | 23% | 18% |
| BB, SB | 100% | 100% | 97% | 79% | 70% | 61% | 56% | 50% | 48% | 43% | 34% | 30% |

The same seats at a smaller table, where fewer players have folded. The
big blind against an all-in from the button:

| Players | 2bb | 3bb | 4bb | 5bb | 6bb | 7bb | 8bb | 9bb | 10bb | 12bb | 16bb | 20bb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 9 | 100% | 100% | 96% | 73% | 52% | 45% | 36% | 33% | 31% | 28% | 23% | 18% |
| 6 | 100% | 100% | 100% | 82% | 61% | 47% | 43% | 38% | 33% | 29% | 23% | 18% |
| 5 | 100% | 100% | 100% | 85% | 63% | 50% | 45% | 37% | 35% | 29% | 24% | 21% |
| 4 | 100% | 100% | 100% | 86% | 66% | 54% | 46% | 39% | 36% | 31% | 24% | 18% |
| 3 | 100% | 100% | 100% | 89% | 70% | 56% | 48% | 41% | 37% | 31% | 25% | 20% |

- **The first seats are tight and stay tight.** A quarter of the hands with
  3bb: pairs from 44, any suited ace, the big offsuit aces and kings, the
  suited cards that make straights. 7-2, 9-4 and their like are folds
  with any stack: they do not win a three-way pot often enough.
- **The small blind moves in with almost anything** up to 4bb, and with
  three hands in four up to 8bb: only the big blind is left, and he has a
  large part of his stack in already.
- **The big blind calls nearly every all-in up to 4bb** (he has two of his
  big blinds in), and from there his calls shrink fast: at a full table
  with 8bb about a third of his hands against the button.
- **Everybody between them calls far tighter than the price says.** On the
  button against a first-seat all-in of 3bb the price is 35%, and a hand
  needs 40 to 45% against the all-in alone: the blinds behind come along
  too often.
- **Short-handed, everybody plays more hands**, the big blind most of all:
  fewer players have folded, so more of the middle cards are still in the
  deck.
- **A player who only calls with 6bb or less is not folding.** The spot is
  answered as his all-in, with a caller's weaker hands in place of the
  hands of an all-in. In the big blind the other choice is a free flop,
  worth about a fifth of the pot: the weakest hands check.
- **On the bubble** (the guide's Bubble stage) a call read from these
  tables must have 10 points of equity to spare over everything it needs,
  hand by hand; the close ones are folded as everywhere.

### What it was checked against

- **The solver against a second program.** `tools/check_short.py` plays the
  same game out in plain Python (its own pot and side-pot arithmetic, the
  engine's hand evaluator, the other players following the solver's
  strategy) and compares what a hand earns with the solver's figure: at 71
  decision points (tables of four, six and nine players, 3 to 16bb) the two
  agree within the noise of both: 0.1bb with 6,000 deals up to 8bb, where
  the one gap of 0.2bb closed to 0.03bb with 40,000 deals; with 16bb, on
  hands far from zero, which only the first pass sampled, gaps of 0.3bb,
  which is that pass's noise there.
- **The solver against itself.** At every decision point with nobody or one
  player all-in, the strategy it trained gives up 0.001 to 0.004bb each time
  the decision comes up (0.01 to 0.03bb with two players all-in, where a
  spot comes up rarely) to the best reply.
- **A straight line between stacks.** The answers at 10bb, drawn from 8bb
  and 12bb as if 10bb had not been solved: 1.4% of hands change sides first
  in and 0.7% of the calls, all of them at the edge of a range (0.0005bb a
  decision). That gap is the widest there is below 12bb and the same as
  between 12, 16 and 20bb.
- **Heads-up, against the published equilibrium** (HoldemResources, no ante,
  1.5 to 20bb): the engine's all-in range differs on 0.3% of hands and its
  calling range on 0.1%.
- **Two to four players, against the exact solver** (no ante, 4 to 20bb): 2
  to 4% of hands differ, each worth 0.15bb at most to either side.
- **The engine's own solver against it**, nine players with the ante, at the
  stacks where both can be asked: first in it was within 4 points of hands
  from the first five seats at every stack from 8 to 20bb, and too wide from
  the cutoff, the button and the small blind: by 4 to 10 points with 7 to
  9bb (the button 50% of hands for 43% with 7bb), by up to 7 points with 12
  to 20bb. Its calls of an all-in were 5 to 9 points too wide in the big
  blind with 7 and 8bb and within 4 points from 9bb up.
- **Against a solver's opening widths with 20bb** (nine players, a big blind
  ante, chips only): 15.6% from the first seat, 31.2% from the cutoff, 41.5%
  from the button, where the guide's Play to win opened 12%, 31% and 50%.
  The button now opens 41% with 25bb or less, and a raise from the cutoff or
  the button at those stacks is read as 32% and 41%, not as the deep 36% and
  50%. Against the button's 2bb raise with 20bb the solver's big blind folds
  15.5% of hands; the guide's folds 19.9% in Play to win and 27% in Tight.
- **The tables against the engine, and the page against the tables.** The
  tests ask a sample of every family again and compare; a browser run asks
  the page 700 random spots at their real table size and compares each
  answer with the engine's.

### Limits

- The exact tables are for a big blind ante. GGPoker's ante is paid by every
  player: the same money at eight players, but the big blind keeps one big
  blind more behind, which matters a little with 2 to 4bb, and at a
  short-handed table there is less ante in the pot than the tables count.
- They are for equal stacks, or for players behind who cover you. With a
  shorter stack still to act, with prizes counted, or with a strong read on
  a player, the engine's solver answers as before and says in a warning that
  it reads weak hands too well at this depth.
- First in they are an equilibrium: every player calls correctly, and the
  Opponents choice does not move them.
- Above 10bb the solved game is not the whole game: its all-in ranges stand
  for players who, in a real game, also raise small. That is the same
  reading of an all-in as before, with better arithmetic.
- Tables of 7 and 8 players are read from the nine: the seats that are not
  there count as players who folded. At eight players that costs about
  0.001bb a hand (the big blind calls 2 to 6 points of hands too few).
- Their numbers carry noise from dealing cards. After the second pass a
  number near zero is good to about 0.02bb with 6bb, 0.03bb with 10bb and
  0.06bb with 20bb; a play within 0.05bb (0.1bb with 20bb) is marked close,
  and inside that band a hand can be in at one stack and out at the next.
  With two players all-in before you only the first pass was run: those
  numbers are good to 0.05bb with a few big blinds and 0.2bb with 20, and a
  play within 0.15bb or more is marked close.
- Against a raise that does not commit the raiser, and behind a player who
  only called with 7bb or more, the engine's solver answers, with neither of
  the two effects above. What that costs can be read off the check above: a
  few points of hands too wide from the late seats and in the big blind.
- The small blind first in with 13 to 20bb moves all-in or folds, half its
  hands at 20bb. That is the equilibrium for a seat that may only do that; a
  solver with every play open moves all-in with a tenth of its hands there
  and calls or raises small with most of the rest. The all-in is the best
  play the guide has for those hands, and it swings.
- The clock's levels are averages. A real structure has its own steps.
- Nothing here has been measured against results at the table.

## Spin & Go in the quick guide

The quick guide's Game choice has a second game besides the tournament:
Spin & Go (GGPoker's Spin & Gold, PokerStars' Spin & Go). Same page, same
controls; what changes is the game behind the tables. This section says
what is different, why, and what it was checked against.

### What matters in a spin, and what does not

- **The game.** Three players (two once one is out), blinds of a half and
  one big blind, no ante, and one prize in nearly every game (all of
  GGPoker's x2 to x5 games, 97.6% of them). With one prize, chips are
  money: the play that wins the most chips is the right one.
- **The buy-in does not change the play.** A $1 spin and a $50 spin are
  the same game; the buy-in only tells you what kind of players you meet.
- **The multiplier does not change it either**, except in the games that
  pay second place (GGPoker x10 and up, about one game in forty). There
  prizes are counted (ICM) and the guide's tables are not the answer: call
  all-ins tighter while a shorter stack can still bust first, and use the
  table app with the prizes typed for the exact answer.
- **Being the chip leader is no reason to play tighter.** The chips the
  biggest stack has over the second biggest can never change hands, so a
  leader with 8bb against 6bb and 5bb plays exactly as if he had 6bb. And
  with one prize a chip lost costs what a chip won is worth: there is no
  survival bonus to protect.
- **Play to win only.** The guide's Tight style is the tournament's,
  built to survive until a prize. In a spin there is nothing to survive
  for, so the Style choice is not offered.

### Why it plays tighter than the tournament tables

The tournament tables are made with a big blind ante of one big blind: 2.5bb
in the pot before the cards, where a spin has 1.5bb. Every all-in that gets
through wins two thirds more there, so every range is wider: the tournament
tables at three players are too loose for a spin, and most of all in the
calls. Share of hands, three equal stacks, tournament table / spin:

| Spot | 3bb | 4bb | 5bb | 6bb | 8bb | 10bb | 12bb | 16bb | 20bb |
|---|---|---|---|---|---|---|---|---|---|
| Button first in | 57 / 43 | 55 / 43 | 54 / 39 | 49 / 38 | 48 / 36 | 43 / 33 | 40 / 30 | 34 / 25 | 33 / 23 |
| Small blind first in | 100 / 76 | 92 / 73 | 85 / 69 | 82 / 70 | 77 / 61 | 71 / 55 | 67 / 52 | 60 / 44 | 54 / 40 |
| Small blind calls the button | 72 / 47 | 58 / 35 | 46 / 31 | 42 / 28 | 35 / 22 | 29 / 18 | 26 / 16 | 20 / 13 | 15 / 10 |
| Big blind calls the button | 100 / 89 | 100 / 60 | 89 / 44 | 70 / 37 | 48 / 29 | 37 / 23 | 31 / 21 | 25 / 15 | 20 / 11 |
| Big blind calls the small blind | 100 / 89 | 100 / 70 | 92 / 60 | 80 / 50 | 64 / 44 | 54 / 36 | 47 / 33 | 38 / 25 | 33 / 20 |
| Big blind calls both | 100 / 81 | 96 / 54 | 75 / 37 | 59 / 29 | 37 / 17 | 27 / 13 | 19 / 10 | 13 / 7 | 11 / 6 |

(First in from 12bb up, the share whose all-in earns; beside it both games
also raise small with other hands.)

That is the "very aggressive" of the tournament guide used for a spin.

### Unequal stacks, solved exactly

Stacks in a spin are rarely equal, and the short stack is often short in
big blinds too. So the spin tables are not made for "the effective stack"
but for every player's stack:

- **Two numbers matter.** The biggest stack is cut down to the second, and
  what is left is two players with the same stack `X` and one with `Y`
  (no more than `X`), in one of the three seats, or three equal stacks.
  Heads-up only the smaller stack matters.
- **The grid.** `X` of 2 to 10bb in steps of one, then 12, 14, 16, 18, 20,
  25 and 30bb; `Y` of 1, 1.5, 2 to 10bb, 12 to 20bb in steps of two, and
  25bb, under `X`; the short stack on the button, in the small blind or in
  the big blind. Heads-up 1 to 30bb. 491 games in all
  (`tools/build_spin_exact.py`, about two and a half hours on four
  processors), each solved by the solver of the All-In or Fold tables
  (`tools/aof_solver.c`: real cards, every showdown and side pot) with 20
  million training deals, and then every hand of every decision dealt
  50,000 times against the solved strategies (`poker_coach/spin_exact.py`,
  `data/spin_exact.json`).
- **Decisions that never come.** With 1bb in the small blind a player calls
  every all-in, so "the small blind folded" never happens in the solution.
  Real players do fold there, so such a decision is trained as if it came
  now and then and sampled with the earlier players' hands trembling (each
  play at least 2% likely).
- **What the engine takes from it.** With about 10bb or less every hand is
  an all-in or a fold and the solved game is the whole answer. Deeper, an
  all-in first in and every call of one or two all-ins are read from it
  (up to 30bb); the small raises and the calls of a raise are the engine's
  opening rows and price tests, as in the tournament tables. `advise` and
  `quick --spin --stacks "BTN=12,SB=8,BB=5"` read it whenever the game is a
  spin's: two or three players, no ante.

The chip leader who is short in big blinds plays the short game. Stacks of
9, 6 and 5bb, the leader on the button: the tournament tables (6bb, a big
blind ante) move in with 49% of hands, a spin with 38%; the big blind with
5bb calls that all-in with 89% of hands in the tournament tables and with
42% in a spin. How much the other stacks change a play when they are not
equal:

- **The button first in with 10bb** moves all-in with 33% of hands when
  both blinds have 10bb, 35% when either blind has 3 to 6bb (a short blind
  calls more, but can only win his stack), and 24% when the big blind has
  1bb: he is all-in already, calls every time, and the small blind comes
  along cheaply.
- **The small blind first in with 10bb** moves in with 55% of hands against
  a big blind of 10bb, 70% against 5bb, 78% against 3bb and every hand
  against 1bb.
- **A short button against deep blinds** (15bb each): with 3bb the big
  blind calls his all-in with 94% of hands, with 6bb with 38%, with 10bb
  with 24%.

### The players you meet

The Opponents choice reads three solved answers:

- **Standard** is the equilibrium: nobody can do better against it.
- **Loose** is the best reply to players who move all-in as the solution
  does but call an all-in with half as many hands again: the common
  mistake of low-stakes spins. The weak steals go, the strong hands stay:
  fewer all-ins first in (with 10bb the button 26% of hands instead of 33%,
  as the spin command's loose table has it); the calls stay about the same,
  a few more against two all-ins.
- **Tight** is the best reply to players who move in and call with a fifth
  fewer hands: far more all-ins, fewer calls. A best reply goes all the way:
  against callers a third tighter the button would move in with three hands
  in four with 10bb, which costs a lot if the table is only a little tight,
  so the gentler model was chosen. Use it for a table that has been seen
  folding a lot.

Share of hands, three equal stacks, Standard / Loose / Tight:

| Spot | 4bb | 6bb | 8bb | 10bb | 12bb | 16bb | 20bb |
|---|---|---|---|---|---|---|---|
| Button first in | 43 / 40 / 52 | 38 / 35 / 58 | 36 / 29 / 51 | 33 / 26 / 51 | 30 / 23 / 44 | 25 / 16 / 31 | 23 / 15 / 30 |
| Small blind first in | 73 / 70 / 96 | 70 / 57 / 99 | 61 / 50 / 88 | 55 / 44 / 86 | 52 / 38 / 73 | 44 / 32 / 72 | 40 / 27 / 66 |
| Small blind calls the button | 35 / 39 / 33 | 28 / 27 / 22 | 22 / 23 / 18 | 18 / 18 / 14 | 16 / 15 / 13 | 13 / 11 / 10 | 10 / 11 / 9 |
| Big blind calls the button | 60 / 63 / 54 | 37 / 36 / 30 | 29 / 30 / 24 | 23 / 23 / 18 | 21 / 19 / 15 | 15 / 13 / 11 | 11 / 12 / 10 |
| Big blind calls the small blind | 70 / 72 / 60 | 50 / 55 / 44 | 44 / 43 / 33 | 36 / 36 / 28 | 33 / 33 / 27 | 25 / 25 / 18 | 20 / 22 / 15 |
| Big blind calls both | 54 / 56 / 49 | 29 / 33 / 24 | 17 / 23 / 14 | 13 / 16 / 11 | 10 / 13 / 9 | 7 / 9 / 7 | 6 / 8 / 4 |

Every player around you has to be of that kind (Opponents sets them all);
with one solid player behind, Standard is the answer.

### Deeper than about 10bb

The solved game has only all-ins. Deeper, spins are played with small
raises and limps, and there the tables are the engine's own plays, in the
Play to win style, with the exact all-in numbers beside them. Against
published solver figures for three-player spins without an ante (GTO
Gecko's):

| Spot | Solver | Guide |
|---|---|---|
| Button first in, 25bb | raises about 40% | {BTN25} |
| Big blind against the button's min-raise | defends 65 to 70% | {BBDEF} |
| Heads-up, the button first in, 15 to 25bb | plays 70 to 80% | {HUSB} |
| Heads-up, the big blind against a min-raise | defends about 70% | {HUBB} |
| Small blind against the big blind | plays about two hands in three, many as a limp | {SBVBB} |

Three things were wrong for three players or two, and were changed. The
first holds in tournaments too and changed the tournament guide's heads-up
tables, which were built again; the other two hold in a spin only (no ante,
three players or two), so the tournament tables, made for nine players and
read by smaller tables, stay the engine's answers:

- **The heads-up raise.** Heads-up the engine took a raise from the button
  to be a small blind's raise at a full table (36 to 50% of hands); it is
  now the heads-up button's 80% (`ranges.villain_open_range`, `heads_up`).
  The big blind's defence went from 57% to the figure above.
- **A small re-raise.** It was taken from the full table's ranges: about 7%
  of hands, mostly strong ones, so a button that raised folded 96% of hands
  to a re-raise to 6bb with 20bb. Three-handed and heads-up a re-raise is
  much wider (a spin guide puts the big blind's against the button at 10
  to 15%): an unknown player is now taken to re-raise 12.5% of hands
  three-handed and 16% heads-up, a tight one a step less, a loose-aggressive
  one a step more (`ranges.threebet_range` with `players`), and the all-in
  over it goes by what it earns. The button now goes on with 10% of hands
  there (4% before), about a quarter of the hands it raised.
- **The small blind behind a limp.** The full-table rule limps behind only
  with small pairs and suited cards from 25bb, so the small blind folded
  three hands in four behind the button's limp, where completing costs half
  a big blind for a pot of three. Three-handed with 17bb or more it now
  completes every hand whose equity against the limper and the big blind,
  times the share of it a hand keeps out of position, beats the price by
  4 points (the big blind raises two limpers about a fifth of the time):
  {SBLIMP}. With 16bb or less it moves all-in or folds, as before.

The small blind first in is the gap left: the guide raises or folds there,
and a solver also limps with most of the hands the guide folds.

### What it was checked against

- **The solver against a second program.** `tools/check_short.py` plays the
  game out in plain Python with the real stacks and no ante: at nine setups (three players with the short stack in each seat, 4 to
  12bb, and heads-up with 20bb), the two hands nearest zero and one clear
  hand at every decision, 153 numbers. With 4,000 to 6,000 deals the check
  is good to about 0.1bb (0.15bb with 12bb), and 148 of them are within
  twice that, as many as noise allows. The largest gaps (0.26bb with 9bb,
  0.4 and 0.5bb with 12bb) were checked again with fresh sets of 30,000 to
  40,000 deals and the solver's number sampled 400,000 times: the two then
  agree within 0.1bb.
- **The solver against itself.** At all 2,842 decisions the trained strategy gives
  up 0.001bb on average (half that, the median) each time the decision
  comes up, to the best reply. Fourteen give up more than 0.01bb and the
  most is 0.04bb, all of them decisions that rarely come (a big blind
  facing two all-ins of 25 to 30bb, a small blind of 1.5bb who folded).
  Twenty-eight never come in the solution and were answered with trembling
  hands.
- **Against the older spin tables.** The spin command's tables
  (`tools/build_spin.py`, equal stacks, made earlier and separately): with
  the same equal stacks the new solution differs on 1 to 4% of hands, all
  at the edge of a range.
- **The page against the engine.** {CROSS}
- **The tables against the engine.** `tests/test_spin_exact.py` holds the
  engine to the solution, and `tests/test_guide.py` asks a sample of the
  spin tables again.

### Limits

- The page reads the nearest solved stacks, in the same proportion, and
  says so under the answer. The engine (`advise`, `quick`) draws the
  answers between them in a straight line.
- A short stack under one big blind is read as one big blind.
- Above 30bb the page reads 30bb. In the x2 and x3 games (15bb to start)
  no effective stack is ever that deep.
- Games that pay second place (x10 and up) are not covered: prizes count
  there, and the table app with the prizes typed answers by ICM.
- Six-player spins (6-Max) are not in the guide: `quick --players 6 --goal
  chips`, or the table app.
- A limp and then a raise (the small blind limps, the big blind raises)
  has no table.
- Every number comes from dealing cards, each hand 50,000 times at every
  decision (the Loose and Tight answers 20,000 times): a call is good to
  about 0.004bb for each big blind of the stack, 0.05bb with 12bb, as a
  check with 400,000 deals showed. A play within twice that (at least
  0.05bb; 0.1bb with 12bb, 0.16bb with 20bb; half again for Loose and
  Tight) is marked close, and inside that band a hand can fall either way.
- The deeper plays (small raises, limps, calls of a raise) are the
  engine's rules, not a solver's; the table above is how far they are
  from one.
- Checked in headless Chromium on Linux only. Nothing here has been
  measured against results at the table.
