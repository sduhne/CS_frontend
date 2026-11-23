#!/usr/bin/env python3
"""What the quick guide's Ante choice leaves as it is: the tables that are not read from the exact solution.

    python3 tools/check_guide_ante.py                   # tables of 9, 8, 6 and 3 players, 16 spots a group: about 15 minutes
    python3 tools/check_guide_ante.py 8 --spots 30      # one table size, more spots

With the ante of every player the guide has tables of its own for the stacks solved exactly, at every
table size, and for two players (tools/build_guide.py, EACH).  Every other spot is read from the table
made with a big blind ante, at nine players.  This asks the engine about such spots again with an eighth
of a big blind from every player, at the table's own size, and counts the hands whose play differs from
the page's table: of all 1326 holdings ("moved"), and of those not marked close on either side ("not
close").  The last column reads the page's table one stack deeper instead: where the big blind's stack is
the one played for he has paid an eighth and not a whole big blind, and that table is the nearer one.

The numbers in PLAYBOOK.md ("Turbo and hyper-turbo", Limits) and under ``AnteMoves`` in
tests/test_guide.py are this script's.
"""
from __future__ import annotations

import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_guide as B                                    # noqa: E402
from poker_coach import ranges as R                        # noqa: E402
from poker_coach import short                              # noqa: E402
from poker_coach.cards import COMBO_COUNT                  # noqa: E402


def exact(family: str, key) -> bool:
    """Is this spot read from the exact solution?  (Then the ante of every player has a table of its own.)"""
    stack = key[-1]
    if stack > short.top("player"):
        return False
    if family in ("open", "allin"):
        return True
    if family in ("limp", "limp_sb"):
        return stack <= B.P._LIMP_COMMITS
    return family == "vsraise" and key[2] == 0 and B.RAISE_SIZES[key[3]] >= B.COMMITS * stack


# (what it is, the family, which of its spots)
GROUPS = (
    ("a raise before you, big blind, 6 to 12bb", "vsraise", lambda k: k[1] == 0 and k[4] <= 12),
    ("a raise before you, big blind, 13 to 20bb", "vsraise", lambda k: k[1] == 0 and 13 <= k[4] <= 20),
    ("a raise before you, big blind, 22bb and more", "vsraise", lambda k: k[1] == 0 and k[4] >= 22),
    ("a raise before you, another seat, up to 20bb", "vsraise", lambda k: k[1] >= 1 and k[4] <= 20),
    ("a raise before you, another seat, 22bb and more", "vsraise", lambda k: k[1] >= 1 and k[4] >= 22),
    ("you raised, the big blind moved all-in, up to 20bb", "re_allin", lambda k: k[1] == 0 and k[2] <= 20),
    ("you raised, another seat moved all-in, up to 20bb", "re_allin", lambda k: k[1] >= 1 and k[2] <= 20),
    ("you raised, an all-in, 22bb and more", "re_allin", lambda k: k[2] >= 22),
    ("first in, 22bb and more", "open", lambda k: k[1] >= 22),
    ("players only called, 7 to 20bb", "limp", lambda k: 7 <= k[2] <= 20),
    ("players only called, 22bb and more", "limp", lambda k: k[2] >= 22),
    ("an all-in before you, 22 to 40bb", "allin", lambda k: k[2] >= 22),
    ("a raise and a re-raise before you", "raise3", lambda k: True),
    ("you raised and were re-raised", "re3", lambda k: True),
    ("a raise, you re-raised, the raiser all-in, up to 20bb", "sq_allin", lambda k: k[2] <= 20),
    ("a raise, you re-raised, the raiser all-in, 22bb and more", "sq_allin", lambda k: k[2] >= 22),
    ("a raise and an all-in before you, 6 to 20bb", "raise_allin", lambda k: 6 <= k[1] <= 20),
    ("a raise and an all-in before you, 25bb and more", "raise_allin", lambda k: k[1] >= 25),
    ("you raised, a re-raise and an all-in", "re3_allin", lambda k: True),
)


def moved(page: str, again: str) -> tuple[float, float]:
    """Percent of all holdings whose play differs between two tables: (all of them, those close on neither side)."""
    act = lambda ch: (B.CODES + B.CLOSE).index(ch) % len(B.CODES)      # noqa: E731
    hands = [h for h in range(169) if act(page[h]) != act(again[h])]
    return (sum(COMBO_COUNT[h] for h in hands) / 13.26,
            sum(COMBO_COUNT[h] for h in hands if page[h] in B.CODES and again[h] in B.CODES) / 13.26)


def measure(players: int, spots: int, seed: int = 9, style: str = "win") -> list[dict]:
    """-> one row a group: {"group", "spots", "moved", "most", "firm", "firm_most", "deeper"} in percent of hands."""
    rng = random.Random(seed)
    before = R.set_style(style)
    out = []
    try:
        for label, family, keep in GROUPS:
            asked = {key: question for key, question in B.FAMILIES[family][1]()}
            fit = [key for key in asked if keep(key) and not exact(family, key) and B.at_table(family, key, players)]
            rows = []
            for key in rng.sample(fit, min(spots, len(fit))):
                page = B.table(opp="unknown", **asked[key])["a"]                                  # nine seats, a big blind ante
                again = B.table(opp="unknown", **B.at_table(family, key, players, "player"))["a"]      # the game at this table
                row = list(moved(page, again))
                deeper = tuple(key[:-1]) + (B.STACKS[min(len(B.STACKS) - 1, B.STACKS.index(key[-1]) + 1)],)
                row.append(moved(B.table(opp="unknown", **asked[deeper])["a"], again)[0] if deeper in asked else None)
                rows.append(row)
            if rows:
                one_deeper = [r[2] for r in rows if r[2] is not None]
                out.append({"group": label, "spots": len(rows), "moved": sum(r[0] for r in rows) / len(rows), "most": max(r[0] for r in rows),
                            "firm": sum(r[1] for r in rows) / len(rows), "firm_most": max(r[1] for r in rows),
                            "deeper": sum(one_deeper) / len(one_deeper) if one_deeper else None})
    finally:
        R.set_style(before)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("players", nargs="*", type=int, default=[9, 8, 6, 3], help="table sizes (3 to 9)")
    ap.add_argument("--spots", type=int, default=16, help="spots asked in each group")
    ap.add_argument("--style", default="win", choices=B.STYLES)
    a = ap.parse_args()
    for players in a.players:
        rows = measure(players, a.spots, style=a.style)
        print(f"{players} players, the ante of every player against the page's table (percent of hands)")
        print(f"  {'':56s} spots   moved  most   not close  most   one stack deeper")
        for r in rows:
            deeper = f"{r['deeper']:6.2f}" if r["deeper"] is not None else "     -"
            print(f"  {r['group']:56s} {r['spots']:5d}  {r['moved']:6.2f} {r['most']:5.1f}      {r['firm']:5.2f} {r['firm_most']:5.1f}   {deeper}")
        count = sum(r["spots"] for r in rows)
        print(f"  {'all ' + str(count) + ' spots':56s} {count:5d}  {sum(r['moved'] * r['spots'] for r in rows) / count:6.2f}"
              f"            {sum(r['firm'] * r['spots'] for r in rows) / count:5.2f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
