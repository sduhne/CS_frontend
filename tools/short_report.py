#!/usr/bin/env python3
"""The numbers PLAYBOOK.md gives for the exact short-stack solution, worked out again from the data.

    python3 tools/short_report.py tables             # the playbook's tables (first in, calling an all-in), as it prints them
    python3 tools/short_report.py precision          # what every pass did and what its numbers are good to, table by table
    python3 tools/short_report.py line               # a straight line between stacks: 10bb drawn from 8 and 12bb
    python3 tools/short_report.py itself [DIR]       # what the trained strategies give up to the best reply
    python3 tools/short_report.py engine             # the engine's own solver beside the exact answers (a few minutes)
    python3 tools/short_report.py builds OTHER.json  # two builds of the data file, each trained on its own: how far apart

Everything is read from poker_coach/data/short.json but "itself", which needs the strategies: the solver's
output in tools/short_solutions (or another work folder of tools/build_short.py).  tests/test_short.py
holds the playbook's tables to "tables", so a new build of the data shows there.
"""
from __future__ import annotations

import dataclasses
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from poker_coach import short as S                                     # noqa: E402
from poker_coach.cards import COMBO_COUNT, format_range                # noqa: E402

DATA = os.path.join(ROOT, "poker_coach", "data", "short.json")
SEATS = ("UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB")
GRID = (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16, 20)
KINDS = ("first in", "one all-in", "two all-ins")
# the playbook's own choice of rows: who calls, and whose all-in
CALLS = ((1, 0), (6, 0), (6, 5), (7, 6), (8, 0), (8, 5), (8, 6), (8, 7))
HANDS_AT = (3, 6, 10)


def pct(evs) -> str:
    return f"{S.width(evs):.0f}%"


def tables() -> list[str]:
    """The tables of PLAYBOOK.md, "All-ins of 20bb or less: solved exactly", line by line."""
    out = ["| Seat | " + " | ".join(f"{s}bb" for s in GRID[:9]) + " |", "|---|" + "---|" * 9]
    for p in range(8):
        out.append(f"| {SEATS[p]} | " + " | ".join(pct(S.node(float(s), p, 0)) for s in GRID[:9]) + " |")
    for stack in HANDS_AT:
        out += ["", f"With {stack}bb{', the hands' if stack == HANDS_AT[0] else ''}:", "", "| Seat | All-in with |", "|---|---|"]
        for p in range(8):
            out.append(f"| {SEATS[p]} | {format_range([1.0 if e > 0 else 0.0 for e in S.node(float(stack), p, 0)])} |")
    out += ["", "| You, and the all-in from | " + " | ".join(f"{s}bb" for s in GRID) + " |", "|---|" + "---|" * 12]
    for hero, shover in CALLS:
        out.append(f"| {SEATS[hero]}, {SEATS[shover]} | " + " | ".join(pct(S.node(float(s), hero, 1 << shover)) for s in GRID) + " |")
    out += ["", "| Players | " + " | ".join(f"{s}bb" for s in GRID) + " |", "|---|" + "---|" * 12]
    for n in (9, 6, 5, 4, 3):               # the big blind against an all-in from the button, at each table
        out.append(f"| {n} | " + " | ".join(pct(S.node(float(s), n - 1, 1 << (n - 3), n)) for s in GRID) + " |")
    return out


def precision(path: str = DATA) -> None:
    with open(path) as fh:
        d = json.load(fh)
    for k, spec in enumerate(d["passes"], start=1):
        print(f"pass {k}: {spec}")
    for players in sorted(d["games"], key=int, reverse=True):
        g = d["games"][players]
        stacks = [f"{s:g}" for s in g["stacks"]]
        print(f"\n{players} players           " + " ".join(f"{s + 'bb':>7}" for s in stacks) + "    all")
        for name, key, places in (("hands again", "again", ("pass 2", "pass 3")), ("changed sides", "moved", ("pass 2", "pass 3")),
                                  ("in from a seat, out from the next", "crossed", ("after 1", "after 2", "after 3"))):
            for k, place in enumerate(places):
                row = [g[key][s][k] for s in stacks]
                print(f"  {name + ', ' + place:42.42} " + " ".join(f"{x:7d}" for x in row) + f" {sum(row):6d}")
        print("  good to, in big blinds (the middle one of the standard errors of the numbers a pass left, and the largest):")
        for k in range(len(d["passes"])):
            for count in range(len(g["noise"][stacks[0]][k])):
                for j, what in enumerate(("middle", "largest")):
                    row = [g["noise"][s][k][count] for s in stacks]
                    print(f"  {f'pass {k + 1}, {KINDS[count]}, {what}':42.42} "
                          + " ".join(f"{r[j]:7.4f}" if r else "      -" for r in row))


def line(path: str = DATA) -> None:
    """The answers at a solved stack drawn from its two neighbours as if it had not been solved."""
    with open(path) as fh:
        g = json.load(fh)["games"]["9"]["nodes"]
    for lo, mid, hi in ((8, 10, 12), (12, 16, 20), (6, 8, 10), (4, 5, 6)):
        t, out = (mid - lo) / (hi - lo), {}
        for key, evs in g[str(mid)].items():
            a, b = g[str(lo)][key], g[str(hi)][key]
            other = [h for h in range(169) if (a[h] + (b[h] - a[h]) * t > 0) != (evs[h] > 0)]
            o = out.setdefault(bin(int(key.split(":")[1])).count("1"), [0.0, 0.0, 0])
            o[0] += sum(COMBO_COUNT[h] for h in other) / 1326
            o[1] += sum(COMBO_COUNT[h] * abs(evs[h]) / 100.0 for h in other) / 1326
            o[2] += 1
        calls = [out[1][k] + out[2][k] for k in range(3)]
        print(f"{mid}bb from {lo} and {hi}bb: " + "; ".join(
            f"{name} {100 * v[0] / v[2]:.1f}% of hands on the other side, {v[1] / v[2]:.4f}bb a decision"
            for name, v in (("first in", out[0]), ("one all-in", out[1]), ("two all-ins", out[2]), ("the calls together", calls))))


def itself(work: str) -> None:
    """At a decision point the strategy goes in with a hand a share f of the time, and going in earns e over
    folding.  The best reply goes in exactly when e > 0, so the strategy gives up f * max(0, -e) +
    (1 - f) * max(0, e), weighted by the ways the hand can be dealt."""
    import build_short as B
    for players in B.GAMES:
        for stack in B.STACKS:
            path = os.path.join(work, f"n{players}_s{stack}.json")
            if not B.kept(path):
                continue
            sol = B.read(path)
            B.fine(None, sol, path, False)
            out = {}
            for nd in sol["nodes"]:
                if B.all_ins(nd["mask"]) <= S.MOST_ALL_IN:
                    out.setdefault(B.all_ins(nd["mask"]), []).append(sum(
                        c * (f / 100 * max(0.0, -e / 100) + (1 - f / 100) * max(0.0, e / 100))
                        for c, f, e in zip(COMBO_COUNT, nd["freq"], nd["ev"])) / 1326)
            print(f"{players} players, {stack}bb: " + "; ".join(
                f"{KINDS[count]} {min(v):.4f} to {max(v):.4f}bb (the middle one {statistics.median(v):.4f})" for count, v in sorted(out.items())))


def engine() -> None:
    """Nine players with the ante: the width of the engine's own solver, the exact one, and the difference."""
    from poker_coach import preflop as P, ranges as R
    from poker_coach.cards import range_pct
    from poker_coach.icm import Prizes
    from poker_coach.pushfold import HandSetup
    R.set_style("win")
    exact = S.answer

    def own(fn):                        # the engine with the exact answers switched off
        S.answer = lambda *a, **k: None
        try:
            return fn()
        finally:
            S.answer = exact

    def first_in(stack, seat):
        setup = HandSetup([float(stack)] * 9, 0.5, 1.0, 0.0, 1.0)
        return range_pct(own(lambda: P.solve_open_shove(setup, seat, Prizes())).shove_range)

    def calls(stack, hero, shover):
        spot = P.quick_spot(0, None, float(stack), 9, SEATS[hero], f"{SEATS[shover]} allin")
        return own(lambda: sum(c for h, c in enumerate(COMBO_COUNT)
                               if P.advise(dataclasses.replace(spot, hand=h)).action.startswith("CALL")) / 13.26)

    print("first in: the engine's solver / the exact answer (the difference), in points of hands")
    for stack in (3, 6, 7, 8, 9, 10, 12, 16, 20):
        print(f"  {stack}bb: " + ", ".join(
            f"{SEATS[seat]} {mine:.0f}/{theirs:.0f} ({mine - theirs:+.0f})"
            for seat in range(8) for mine, theirs in [(first_in(stack, seat), S.width(S.node(float(stack), seat, 0)))]))
    print("calling an all-in")
    for stack in (3, 6, 7, 8, 9, 10, 12, 16, 20):
        print(f"  {stack}bb: " + ", ".join(
            f"{SEATS[hero]} against {SEATS[shover]} {mine:.0f}/{theirs:.0f} ({mine - theirs:+.0f})"
            for hero, shover in ((6, 0), (8, 0), (8, 5), (8, 6), (8, 7))
            for mine, theirs in [(calls(stack, hero, shover), S.width(S.node(float(stack), hero, 1 << shover)))]))


def builds(other: str, path: str = DATA) -> None:
    """Hands that are in in one build and out in the other, and how far the widths are apart."""
    with open(other) as fh:
        old = json.load(fh)["games"]
    with open(path) as fh:
        new = json.load(fh)["games"]
    for players in sorted(set(old) & set(new), key=int, reverse=True):
        print(f"{players} players")
        total = {}
        for stack in old[players]["nodes"]:
            row = {}
            for key, x in old[players]["nodes"][stack].items():
                y = new[players]["nodes"].get(stack, {}).get(key)
                if y is None:
                    continue
                r = row.setdefault(bin(int(key.split(":")[1])).count("1"), [0, 0, 0.0, 0.0, 0.0])
                other_side = [h for h in range(169) if (x[h] > 0) != (y[h] > 0)]
                r[0] += len(other_side)
                r[1] += 1
                r[2] += sum(COMBO_COUNT[h] for h in other_side) / 13.26
                r[3] = max(r[3], abs(S.width([e / 100 for e in x]) - S.width([e / 100 for e in y])))
                r[4] = max([r[4]] + [min(abs(x[h]), abs(y[h])) / 100 for h in other_side])
            for count, r in row.items():
                t = total.setdefault(count, [0, 0, 0.0, 0.0, 0.0])
                t[0] += r[0]; t[1] += r[1]; t[2] += r[2]; t[3] = max(t[3], r[3]); t[4] = max(t[4], r[4])     # noqa: E702
            print(f"  {stack:>2}bb: " + "; ".join(
                f"{KINDS[count]} {r[0]} hands ({r[2] / r[1]:.2f} points of hands a decision point; widths apart by {r[3]:.1f} at most)"
                for count, r in sorted(row.items())))
        print("  all: " + "; ".join(
            f"{KINDS[count]} {t[0]} hands at {t[1]} decision points ({t[2] / t[1]:.2f} points a decision point; widths apart by "
            f"{t[3]:.1f} at most; the clearest of them {t[4]:.2f}bb from zero in both)" for count, t in sorted(total.items())))


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "tables":
        print("\n".join(tables()))
    elif what == "precision":
        precision()
    elif what == "line":
        line()
    elif what == "itself":
        itself(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "tools", "short_solutions"))
    elif what == "engine":
        engine()
    elif what == "builds" and len(sys.argv) > 2:
        builds(sys.argv[2])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
