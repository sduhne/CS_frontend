#!/usr/bin/env python3
"""Build poker_coach/data/short.json: all-ins of 2 to 20 big blinds, solved exactly (see poker_coach/short.py).

    python3 tools/build_short.py                 # compiles the solver and runs it: about four hours on four processors
                                                 # (14 minutes a stack for nine players, 2 for the smaller tables
                                                 # together, and 40 minutes for the second pass)
    python3 tools/build_short.py --work DIR      # keeps the solver's own output there, and uses what is there already
    python3 tools/build_short.py --work DIR --fine-only     # the second pass for the solutions that are in DIR, no more

Equal stacks, a small blind of half a big blind and a big blind ante of one; every player moves all-in
or folds; tables of 9, 6, 5, 4 and 3 players.  The solver (tools/aof_solver.c) deals real cards, so every
showdown and side pot is exact, and so is what the folded hands take out of the deck.  Kept: what going
in earns over folding, hand by hand, for every player with at most two players all-in before him.

Two passes.  The first solves the game and samples every hand of every decision point 10,000 times: a
number is then good to about 0.06bb first in and 0.1bb for a call with 6 to 10bb, more with a deeper
stack (an all-in of 20bb swings more).  That is plenty for a hand that is clearly in or out and too little
for the hands at the edge of a range, which are the ones a chart is read for.  So the second pass takes
every hand the first left near zero, at the decision points with nobody or one player all-in, and samples
it 100,000 times against the same solved strategies: a third of the noise.  (On a trial stack, nine
players with 8bb, 82 of the 1,070 hands it took changed sides, and the five hands that were in from one
seat and out from the next were gone.)  With two players all-in a decision point comes up too rarely to
sample that often: there the first pass stands, and the engine calls a wider band close (short.CLOSE_TWO).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from poker_coach import short as S                                    # noqa: E402

OUT = os.path.join(ROOT, "poker_coach", "data", "short.json")
GAMES = (9, 6, 5, 4, 3)         # tables solved as such; 7 and 8 players are read from the last seats of the nine
STACKS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16, 20)   # big blinds: every stack of the push-or-fold zone, and three deeper
                                # ones that the stacks between are drawn from (an all-in is weighed up to 20bb)
TRAIN, EVAL, REFINE = 40_000_000, 2_000_000, 10_000
FINE = 100_000                  # the second pass: samples for a hand the first pass left near zero ...
FINE_ALL_INS = 1                # ... at the decision points with at most this many players all-in before
BAND = (0.05, 0.04)             # near zero: within 0.05bb and 0.04bb for each big blind of the stack, about four
                                # times the noise of the first pass (which grows with the stack: 0.01bb a big blind)


def band(stack: float) -> float:
    return BAND[0] + BAND[1] * stack


def solve(solver: str, stack: int, work: str, quick: bool, players: int = S.PLAYERS) -> tuple[dict, str]:
    path = os.path.join(work, f"n{players}_s{stack}.json")
    if not os.path.exists(path):
        stacks = ",".join([str(stack)] * players)
        train, refine = (TRAIN // 20, REFINE // 10) if quick else (TRAIN, REFINE)
        # stacks, fee, fee mode, training deals, evaluation deals, samples a hand, ante of every player,
        # ante of the big blind, precision pass up to this many all-ins
        raw = subprocess.check_output([solver, stacks, "0", "1", str(train), str(EVAL), str(refine), "0", "1", str(S.MOST_ALL_IN)])
        with open(path + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(path + ".tmp", path)
    with open(path) as fh:
        return json.load(fh), path


def near_zero(sol: dict) -> list[tuple[int, int, int]]:
    """The hands of a first pass that the second samples again: (player, mask, hand)."""
    limit = 100.0 * band(sol["stacks"][0])
    return [(nd["player"], nd["mask"], c) for nd in sol["nodes"]
            if bin(nd["mask"]).count("1") <= FINE_ALL_INS and nd["samples"] > 0
            for c, e in enumerate(nd["ev"]) if abs(e) < limit]


def fine(solver: str, sol: dict, path: str, quick: bool) -> int:
    """The second pass on one solution, in place: the hands near zero get the numbers of FINE samples.
    -> how many hands that was."""
    base = path[:-len(".json")]
    hands = near_zero(sol)
    out = base + ".fine.json"
    if not os.path.exists(out):
        with open(base + ".strategy.txt", "w") as fh:           # the solved strategies, as the solver reads them back
            fh.write(f"{len(sol['nodes'])}\n")
            for nd in sol["nodes"]:
                fh.write(f"{nd['player']} {nd['mask']}\n" + " ".join(f"{f / 100:.2f}" for f in nd["freq"]) + "\n")
        with open(base + ".hands.txt", "w") as fh:
            fh.write(f"{len(hands)}\n" + "".join(f"{i} {m} {c}\n" for i, m, c in hands))
        stacks = ",".join(f"{x:g}" for x in sol["stacks"])
        # br: stacks, fee, fee mode, samples a hand, the strategies, ante of every player, ante of the big blind,
        # decision points with at most this many all-ins, the hands
        raw = subprocess.check_output([solver, "br", stacks, "0", "1", str(FINE // (10 if quick else 1)), base + ".strategy.txt",
                                       "0", "1", str(FINE_ALL_INS), base + ".hands.txt"])
        with open(out + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(out + ".tmp", out)
    with open(out) as fh:
        again = {(nd["player"], nd["mask"]): nd["ev"] for nd in json.load(fh)["nodes"]}
    nodes = {(nd["player"], nd["mask"]): nd for nd in sol["nodes"]}
    for i, m, c in hands:
        nodes[i, m]["ev"][c] = again[i, m][c]
    return len(hands)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", help="folder for the solver's output (kept, and reused when it is there)")
    ap.add_argument("--quick", action="store_true", help="a coarse run for testing: a twentieth of the deals")
    ap.add_argument("--fine-only", action="store_true",
                    help="run the second pass for the solutions that are in the work folder, write nothing else")
    a = ap.parse_args()
    work = a.work or tempfile.mkdtemp(prefix="short-")
    os.makedirs(work, exist_ok=True)
    solver = os.path.join(work, "aof_solver")
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-o", solver,
                           os.path.join(ROOT, "tools", "aof_solver.c"), "-lm"])
    t0 = time.time()
    if a.fine_only:
        for players in GAMES:
            for stack in STACKS:
                path = os.path.join(work, f"n{players}_s{stack}.json")
                if os.path.exists(path) and not os.path.exists(path[:-len(".json")] + ".fine.json"):
                    with open(path) as fh:
                        sol = json.load(fh)
                    count = fine(solver, sol, path, a.quick)
                    print(f"{players} players, {stack}bb: {count} hands sampled again   ({time.time() - t0:.0f}s)", flush=True)
        return 0
    games = {}
    for players in GAMES:
        nodes, values, again = {}, {}, {}
        for stack in STACKS:
            sol, path = solve(solver, stack, work, a.quick, players)
            if sol["n"] != players or sol.get("bb_ante") != 1 or any(abs(x - stack) > 1e-9 for x in sol["stacks"]):
                raise SystemExit(f"{work}: the kept answer for {players} players and {stack}bb is for another game")
            again[f"{stack:g}"] = fine(solver, sol, path, a.quick)
            kept = {}
            for nd in sol["nodes"]:
                if bin(nd["mask"]).count("1") <= S.MOST_ALL_IN:
                    if nd["samples"] <= 0:
                        raise SystemExit(f"{players} players, {stack}bb, player {nd['player']}, mask {nd['mask']}: "
                                         "the precision pass found no deal")
                    kept[f"{nd['player']}:{nd['mask']}"] = nd["ev"]
            nodes[f"{stack:g}"] = kept
            values[f"{stack:g}"] = [round(v, 3) for v in sol["value"]]
            print(f"{players} players, {stack}bb: {len(kept)} decision points, {again[f'{stack:g}']} hands sampled again"
                  f"   ({time.time() - t0:.0f}s)", flush=True)
        games[str(players)] = {"stacks": list(STACKS), "value": values, "nodes": nodes, "again": again}
    quick = 10 if a.quick else 1
    data = {"version": S.DATA_VERSION, "sb": 0.5, "bb": 1, "bb_ante": 1,
            "train": TRAIN // (20 if a.quick else 1), "samples": REFINE // quick,
            "fine": {"samples": FINE // quick, "all_ins": FINE_ALL_INS, "band": list(BAND)},
            "games": games}
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
