# Turbo cheat sheet (8-handed, with ante)

**Order of seats:** UTG, (UTG+1), LJ, HJ, CO, BTN, SB, BB. Count your stack in big blinds (bb) first.

## 1. Folded to you

| Stack | Do this |
|---|---|
| **25bb+** | Raise to 2.2x (2.3x from 40bb) with the OPEN range |
| **16–25bb** | Raise to 2x with the OPEN range; fold to a shove unless you hold TT+, AQ+ |
| **under 16bb** | ALL-IN with the SHOVE range, otherwise fold. Never raise-fold |

### OPEN (30bb)
- **UTG:** 66+, ATs+, A5s-A4s, KTs+, QTs+, JTs, T9s, AJo+, KQo
- **HJ:** 33+, any suited ace, K9s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, ATo+, KJo+, QJo
- **CO:** any pair, any suited ace, K7s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, A9o+, KTo+, QTo+, JTo
- **BTN:** any pair, any ace, any suited king, Q5s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, K8o+, Q9o+, J9o+, T9o
- **SB:** any pair, any suited ace, K4s+, Q7s+, J7s+, T7s+, 97s+, 86s+, 76s, 65s, A4o+, K9o+, Q9o+, J9o+, T9o

### SHOVE (folded to you)
| Seat | 15bb | 12bb | 8bb |
|---|---|---|---|
| **UTG** | 44+, A7s+, A5s-A2s, K9s+, QTs+, JTs, AJo+, KJo+ | 33+, A7s+, A5s-A2s, K9s+, Q9s+, J9s+, ATo+, KJo+ | any pair, any suited ace, K9s+, Q9s+, J9s+, A8o+, KJo+, QJo |
| **HJ** | any pair, any suited ace, K8s+, Q8s+, J8s+, T8s+, A8o+, KJo+, QJo | + 87s, A5o+, KTo+, JTo | + any ace, KTo+, QTo+ |
| **CO** | any pair, any suited ace, K7s+, Q8s+, J8s+, T8s+, A3o+, KTo+, QTo+, JTo | + K6s, 76s, any ace | + K3s+, Q6s+, K8o+ |
| **BTN** | any pair, any ace, K4s+, Q6s+, J7s+, T7s+, 96s+, K9o+, QTo+, J9o+ | + any suited king, Q5s+, K8o+ | + Q3s+, any king, Q8o+ |
| **SB** | any ace, any king, any suited queen/jack, most connected cards, Q5o+, J7o+ | about 70% of hands | almost anything except the worst trash |

These are chip-EV ranges: right in the money, or when the blinds will finish you first. **Before the money the coach's own all-in lists are about half as wide** (`python3 -m poker_coach tag-sheet --players 8`, part 1).

## 2. Someone opened (raised) before you

| Your stack | Do this |
|---|---|
| **over 45bb** | 3-bet: QQ+, AK vs UTG and UTG+1; add JJ, AQs vs LJ/HJ; add TT, AJs, KQs, AQo vs CO/BTN. Call in position: the pairs down to 77 and AQs, AJs, KQs that are not a 3-bet. Rest folds |
| **26–45bb** | 3-bet small only what calls an all-in over it: JJ+, AK (QQ+, AK vs UTG and UTG+1). TT, AQ and the like: ALL-IN where it clearly earns, otherwise call in position or in the BB; in the SB the weaker ones (KQs, AJs, AQo) fold. No bluff 3-bets |
| **15–25bb** | **Re-shove or fold.** vs UTG/HJ open: 88+, ATs+, AJo+, KQs. vs CO/BTN open: 33+, A8s+, ATo+, KTs+, QTs+, KQo. In BB vs BTN: any pair, any ace, suited kings, broadways |
| **under 15bb** | Shove what you'd shove first-in from that seat, a bit tighter vs early opens |

## 3. Someone went all-in before you

| Shover's seat | Call with (about 15bb deep) |
|---|---|
| UTG / early | 99+, AQ+ |
| HJ / CO | 66+, ATs+, AJo+, KQs |
| BTN / SB (vs your BB) | 22+, A2+, KTs+, KQo |

Shorter shover → call wider. Bigger shover or tight player → tighter. **Near the money: tighten all of this a lot; ask me.**

## 4. After the flop, rules of thumb
- Heads-up as the raiser on a dry board: bet 1/3 pot once, give up if called and you missed.
- A check-raise, a raise on the turn or river, or a big river bet (60% of the pot or more) against your one pair = **fold**, unless the player is wild.
- Top pair or better and less than 1.5x the pot behind = you're committed, get it in.

**Ask me for:** re-raises, all-ins near the money, and big pots after the flop.
