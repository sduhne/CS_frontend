#!/usr/bin/env python3
"""An independent check of the exact short-stack solutions: the same game played out in plain Python.

    python3 tools/build_short.py --work work/        # keeps the solver's own output there
    python3 tools/check_short.py work/n9_s3.json     # a dozen decision points of that game, about two minutes
    python3 tools/check_short.py work/n9_s6.json 12000

Equal stacks, blinds 0.5 and 1, a big blind ante of 1 paid before the blind.  Everybody but the player
under test follows the solver's trained strategy (the "freq" tables of its output); the player under
test holds a given hand at a given decision point, goes in, and the result is compared with folding.
The pot and side-pot arithmetic here is written from the rules, not taken from the solver's code, the
hands are ranked by the engine's own evaluator, and a deal counts only when the players before did what
the decision point says, so what they folded is out of the deck here too.  With 6,000 deals a number is
good to about 0.05bb; the solver's own figure should be within that.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from poker_coach.cards import HANDS                 # noqa: E402
from poker_coach.evaluator import evaluate          # noqa: E402

RANKS = "23456789TJQKA"

def cls(c1, c2):
    """Index of the starting-hand class of two cards (0..51, rank * 4 + suit), aces first in the grid."""
    r1, r2 = c1 // 4, c2 // 4
    if r1 == r2:
        return (12 - r1) * 14
    hi, lo = max(r1, r2), min(r1, r2)
    row, col = 12 - hi, 12 - lo
    return row * 13 + col if c1 % 4 == c2 % 4 else col * 13 + row

def combos(h):
    name = HANDS[h]
    a, b = RANKS.index(name[0]), RANKS.index(name[1])
    out = []
    for s1 in range(4):
        for s2 in range(4):
            if len(name) == 2 and s1 < s2: out.append((a * 4 + s1, b * 4 + s2))
            elif len(name) == 3 and name[2] == "s" and s1 == s2: out.append((a * 4 + s1, b * 4 + s2))
            elif len(name) == 3 and name[2] == "o" and s1 != s2: out.append((a * 4 + s1, b * 4 + s2))
    return out

def settle(n, stack, ante, all_in, strength):
    """What each player ends up with, minus what he started with, when ``all_in`` is the set of players all-in."""
    live = [stack] * n
    live[n - 1] -= ante                      # the big blind pays the ante first
    blind = [0.0] * n
    blind[n - 2] = min(0.5, live[n - 2])
    blind[n - 1] = min(1.0, live[n - 1])
    put = [live[k] if k in all_in else blind[k] for k in range(n)]
    net = [-put[k] for k in range(n)]
    net[n - 1] -= ante
    if not all_in:                           # a walk
        net[n - 1] += sum(put) + ante
        return net
    levels = sorted({live[k] for k in all_in})
    before = 0.0
    for i, level in enumerate(levels):
        pot = sum(min(put[k], level) - min(put[k], before) for k in range(n)) + (ante if i == 0 else 0.0)
        can = [k for k in all_in if live[k] >= level - 1e-9]
        best = max(strength[k] for k in can)
        winners = [k for k in can if strength[k] == best]
        for k in winners:
            net[k] += pot / len(winners)
        before = level
    return net

def run(path, checks, deals, seed=1):
    sol = json.load(open(path))
    n, stack = sol["n"], sol["stacks"][0]
    freq = {(nd["player"], nd["mask"]): nd["freq"] for nd in sol["nodes"]}
    ev = {(nd["player"], nd["mask"]): nd["ev"] for nd in sol["nodes"]}
    rng = random.Random(seed)
    for hero, mask, hand in checks:
        h = HANDS.index(hand)
        mine = combos(h)
        total, done, tries = 0.0, 0, 0
        while done < deals and tries < deals * 400:
            tries += 1
            c1, c2 = rng.choice(mine)
            deck = [c for c in range(52) if c not in (c1, c2)]
            rng.shuffle(deck)
            hole = {hero: (c1, c2)}
            at = 0
            for k in range(n):
                if k != hero:
                    hole[k] = (deck[at], deck[at + 1]); at += 2
            board = deck[at:at + 5]
            # the players before hero must have done what the decision point says
            m, ok = 0, True
            for k in range(hero):
                went = rng.random() * 100.0 < freq[(k, m)][cls(*hole[k])]
                if went != bool(mask >> k & 1):
                    ok = False
                    break
                if went:
                    m |= 1 << k
            if not ok:
                continue
            strength = None
            results = []
            for goes in (True, False):
                mm = m | (1 << hero) if goes else m
                for k in range(hero + 1, n):
                    if k == n - 1 and mm == 0:
                        break
                    if rng.random() * 100.0 < freq[(k, mm)][cls(*hole[k])]:
                        mm |= 1 << k
                in_ = [k for k in range(n) if mm >> k & 1]
                if strength is None:
                    strength = {k: evaluate(list(hole[k]) + list(board)) for k in range(n)}
                results.append(settle(n, stack, 1.0, set(in_), strength)[hero])
            total += results[0] - results[1]
            done += 1
        mine_ev = total / max(1, done)
        print(f"  {n} players, {stack:g}bb, player {hero} with {hand} after all-ins {bin(mask)}: played out {mine_ev:+.2f}bb over {done} deals; "
              f"the solver says {ev[(hero, mask)][h] / 100:+.2f}bb")

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    deals = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
    with open(path) as fh:
        n = json.load(fh)["n"]
    first, late, sb, bb = 0, max(0, n - 4), n - 2, n - 1
    # first in from three seats; calling the first seat's all-in on the button; the big blind against one
    # all-in and against two
    checks = [(first, 0, "72o"), (first, 0, "A8o"), (first, 0, "KTo"), (first, 0, "55"), (late, 0, "T7s"), (sb, 0, "72o")]
    if n >= 4:
        checks += [(n - 3, 1 << first, "A2o"), (n - 3, 1 << first, "KTo")]
    checks += [(bb, 1 << late, "T8o"), (bb, 1 << late, "87o"), (bb, 1 << late, "A2o")]
    if n >= 5:
        checks += [(bb, (1 << first) | (1 << late), "QJs")]
    run(path, checks, deals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
