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
