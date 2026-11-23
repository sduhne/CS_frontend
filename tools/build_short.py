#!/usr/bin/env python3
"""Build poker_coach/data/short.json: all-ins of 2 to 20 big blinds, solved exactly (see poker_coach/short.py).

    python3 tools/build_short.py                 # compiles the solver and runs it, hours on four processors
    python3 tools/build_short.py --work DIR      # keeps the solver's own output there, and uses what is there already
    python3 tools/build_short.py --work DIR --fine-only     # the later passes for the solutions that are in DIR, no more
    python3 tools/build_short.py --work DIR --report        # what every pass did, read from DIR: nothing is run or written
    python3 tools/build_short.py --work tools/short_solutions    # the data file again from the output the repository keeps

Equal stacks, a small blind of half a big blind and a big blind ante of one; every player moves all-in
or folds; tables of 9, 6, 5, 4 and 3 players.  The solver (tools/aof_solver.c) deals real cards, so every
showdown and side pot is exact, and so is what the folded hands take out of the deck.  Kept: what going
in earns over folding, hand by hand, for every player with at most two players all-in before him.

Three passes (PASSES).  The first solves the game and samples every hand of every decision point 10,000
times.  That is plenty for a hand that is clearly in or out and too little for the hands at the edge of a
range, which are the ones a chart is read for.  So the second pass takes every hand the first left near
zero and samples it 100,000 times against the same solved strategies, a third of the noise; and the third
takes, first in, the hands the second left within one and a half of their standard errors of zero and
samples them a million times.  Every pass deals from random numbers of its own, and the solver says what
each number is good to (its standard error): the data file keeps the middle and the largest of them for
the numbers of each pass, with how many hands each pass took and how many it moved to the other side.
"""
from __future__ import annotations

import argparse
import json
import lzma
import os
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from poker_coach import short as S                                    # noqa: E402

OUT = os.path.join(ROOT, "poker_coach", "data", "short.json")
KEPT = os.path.join(ROOT, "tools", "short_solutions")       # the solver's output behind OUT, packed: a work folder to start from
GAMES = (9, 6, 5, 4, 3)         # tables solved as such; 7 and 8 players are read from the last seats of the nine
STACKS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16, 20)   # big blinds: every stack of the push-or-fold zone, and three deeper
                                # ones that the stacks between are drawn from (an all-in is weighed up to 20bb)
TRAIN, EVAL = 40_000_000, 2_000_000
BAND = (0.05, 0.04)             # near zero after the first pass: within 0.05bb and 0.04bb for each big blind of the stack
# The passes, in order: how often a hand is dealt, at the decision points with at most "all_ins" players
# all-in before, and which hands.  The first is the solver's own and takes every hand.  A later one takes
# the hands the pass before left near zero: inside a "band" (a, b), which is a + b * stack big blinds, or
# "within" that many of the number's own standard errors.  "step" is what a number of the pass is kept to,
# in big blinds (a hundredth where nothing is said).
PASSES = (
    {"samples": 10_000, "all_ins": S.MOST_ALL_IN},
    {"samples": 100_000, "all_ins": 2, "band": BAND},
    {"samples": 1_000_000, "all_ins": 0, "within": 1.5, "step": 0.001},
)


def band(stack: float, spec: dict = PASSES[1]) -> float:
    return spec["band"][0] + spec["band"][1] * stack


def all_ins(mask: int) -> int:
    return bin(mask).count("1")


def kept(path: str) -> str | None:
    """A file of the solver's output as the work folder has it: itself, or packed with xz (the way the
    repository keeps them, in KEPT); None when it is not there."""
    return next((name for name in (path, path + ".xz") if os.path.exists(name)), None)


def read(path: str) -> dict:
    name = kept(path)
    with (lzma.open(name, "rt") if name.endswith(".xz") else open(name)) as fh:
        return json.load(fh)


def solve(solver: str, stack: int, work: str, quick: bool, players: int = S.PLAYERS) -> tuple[dict, str]:
    path = os.path.join(work, f"n{players}_s{stack}.json")
    train, refine = (TRAIN // 20, PASSES[0]["samples"] // 10) if quick else (TRAIN, PASSES[0]["samples"])
    if not kept(path):
        stacks = ",".join([str(stack)] * players)
        # stacks, fee, fee mode, training deals, evaluation deals, samples a hand, ante of every player,
        # ante of the big blind, precision pass up to this many all-ins
        raw = subprocess.check_output([solver, stacks, "0", "1", str(train), str(EVAL), str(refine), "0", "1",
                                       str(PASSES[0]["all_ins"])])
        with open(path + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(path + ".tmp", path)
    sol = read(path)
    check(sol, path, players, stack, train)
    return sol, path


def check(sol: dict, path: str, players: int, stack: int, train: int) -> None:
    """A kept answer must be this game's, trained as long, with the standard errors the later passes go by."""
    if sol["n"] != players or sol.get("bb_ante") != 1 or any(abs(x - stack) > 1e-9 for x in sol["stacks"]):
        raise SystemExit(f"{path}: the kept answer for {players} players and {stack}bb is for another game")
    if sol.get("train") != train:
        raise SystemExit(f"{path}: the kept answer was trained on {sol.get('train')} deals, not {train}")
    for nd in sol["nodes"]:
        if all_ins(nd["mask"]) <= S.MOST_ALL_IN:
            if nd["samples"] <= 0:
                raise SystemExit(f"{players} players, {stack}bb, player {nd['player']}, mask {nd['mask']}: "
                                 "the precision pass found no deal")
            if "se_milli" not in nd:
                raise SystemExit(f"{path}: made by an older solver, which kept no standard errors")


def near_zero(sol: dict, spec: dict = PASSES[1]) -> list[tuple[int, int, int]]:
    """The hands of a first pass that a pass with a band samples again: (player, mask, hand)."""
    limit = round(100.0 * band(sol["stacks"][0], spec), 6)     # in hundredths, as the numbers are kept (and no 21.000000000000004)
    return [(nd["player"], nd["mask"], c) for nd in sol["nodes"]
            if all_ins(nd["mask"]) <= spec["all_ins"] and nd["samples"] > 0
            for c, e in enumerate(nd["ev"]) if abs(e) < limit]


def still_near(hands: list, before: dict, spec: dict) -> list[tuple[int, int, int]]:
    """Of the hands a pass sampled, the ones the next takes: within so many of their standard errors of zero."""
    return [(i, m, c) for i, m, c in hands
            if all_ins(m) <= spec["all_ins"] and abs(before[i, m]["ev_milli"][c]) < spec["within"] * before[i, m]["se_milli"][c]]


def sample(solver: str | None, sol: dict, base: str, number: int, spec: dict, hands: list, samples: int) -> dict:
    """One later pass on one solution: ``hands`` dealt ``samples`` times each against the solved strategies.
    -> {(player, mask): the solver's answer for that decision point}.  A kept answer is used when it is
    this pass's: the same hands, as many deals, the same stream of random numbers."""
    out = f"{base}.pass{number}.json"

    def mine():
        if not kept(out):
            return None
        doc = read(out)
        nodes = {(nd["player"], nd["mask"]): nd for nd in doc["nodes"]}
        have = {(i, m, c) for (i, m), nd in nodes.items() for c, n in enumerate(nd.get("n", ())) if n > 0}
        if (doc.get("samples"), doc.get("stream")) != (samples, number) or have != set(hands):
            return None
        return nodes

    nodes = mine()
    if nodes is None:
        if solver is None:
            raise SystemExit(f"{out}: this pass has not been run for the hands the pass before it left")
        with open(base + ".strategy.txt", "w") as fh:           # the solved strategies, as the solver reads them back
            fh.write(f"{len(sol['nodes'])}\n")
            for nd in sol["nodes"]:
                fh.write(f"{nd['player']} {nd['mask']}\n" + " ".join(f"{f / 100:.2f}" for f in nd["freq"]) + "\n")
        listed = f"{base}.pass{number}.hands.txt"
        with open(listed, "w") as fh:
            fh.write(f"{len(hands)}\n" + "".join(f"{i} {m} {c}\n" for i, m, c in hands))
        stacks = ",".join(f"{x:g}" for x in sol["stacks"])
        # br: stacks, fee, fee mode, samples a hand, the strategies, ante of every player, ante of the big blind,
        # decision points with at most this many all-ins, the hands, the stream of random numbers (one a pass)
        raw = subprocess.check_output([solver, "br", stacks, "0", "1", str(samples), base + ".strategy.txt",
                                       "0", "1", str(spec["all_ins"]), listed, str(number)])
        with open(out + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(out + ".tmp", out)
        if os.path.exists(out + ".xz"):         # a packed answer of another pass by this name: the new one stands
            os.remove(out + ".xz")
        nodes = mine()
        if nodes is None:
            raise SystemExit(f"{out}: the solver did not sample the hands it was given")
    return nodes


def crossed(nodes: dict, players: int) -> int:
    """First in, the hands that go in from a seat and not from the next, up to the cutoff and the button
    (the small blind is another game)."""
    return sum(1 for p in range(players - 3) for a, b in zip(nodes[p, 0]["ev"], nodes[p + 1, 0]["ev"]) if a > 0 >= b)


def fine(solver: str | None, sol: dict, path: str, quick: bool) -> dict:
    """The later passes on one solution, in place: a hand they sampled gets the number of its last pass.

    -> what they did, a list with a place for each pass after the first under every key but "noise":
    "again" (the hands sampled), "moved" (how many of them changed sides), "crossed" (the hands in from
    one seat and out from the next, before the pass at 0 and after each), "short" (the hands that got fewer
    deals than asked, because the decision point comes up too rarely), "seconds", and "noise": for the
    numbers each pass left in the solution, first pass included, at decision points with nobody, one
    player and two players all-in before, [the middle one of their standard errors, the largest] in big
    blinds, or None where it left none.  With no solver, only what was kept is read."""
    base = path[:-len(".json")]
    players = sol["n"]
    nodes = {(nd["player"], nd["mask"]): nd for nd in sol["nodes"] if all_ins(nd["mask"]) <= S.MOST_ALL_IN}
    made_by = {key: [1] * 169 for key in nodes}                         # the pass each number is from
    error = {key: [x / 1000.0 for x in nd["se_milli"]] for key, nd in nodes.items()}      # and its standard error, bb
    did = {"again": [], "moved": [], "crossed": [crossed(nodes, players)], "short": [], "seconds": [], "ratio": []}
    hands, before = [], {}
    for number, spec in enumerate(PASSES[1:], start=2):
        samples = spec["samples"] // (10 if quick else 1)
        hands = near_zero(sol, spec) if "band" in spec else still_near(hands, before, spec)
        # how many of the first pass's standard errors a band is, for the report: [nobody, one player, two all-in]
        did["ratio"].append([round(band(sol["stacks"][0], spec) / statistics.median(inside), 1) if inside else None
                             for inside in ([error[i, m][c] for i, m, c in hands if all_ins(m) == count]
                                            for count in range(spec["all_ins"] + 1))] if "band" in spec else None)
        started = time.time()
        before = sample(solver, sol, base, number, spec, hands, samples) if hands else {}
        did["seconds"].append(round(time.time() - started))
        moved = short = 0
        for i, m, c in hands:
            got = before[i, m]
            if spec.get("step", 0.01) < 0.01:           # kept finer than a hundredth: the unrounded number, to a tenth of one
                value = round(got["ev_milli"][c] / 10.0, 1) + 0.0
            else:
                value = got["ev"][c]
            moved += (nodes[i, m]["ev"][c] > 0) != (value > 0)
            short += got["n"][c] < samples
            nodes[i, m]["ev"][c] = value
            made_by[i, m][c] = number
            error[i, m][c] = got["se_milli"][c] / 1000.0
        did["again"].append(len(hands))
        did["moved"].append(moved)
        did["short"].append(short)
        did["crossed"].append(crossed(nodes, players))
    noise = []
    for number in range(1, len(PASSES) + 1):
        row = []
        for count in range(PASSES[number - 1]["all_ins"] + 1):
            left = [error[key][c] for key in nodes if all_ins(key[1]) == count for c in range(169) if made_by[key][c] == number]
            row.append([round(statistics.median(left), 4), round(max(left), 4)] if left else None)
        noise.append(row)
    did["noise"] = noise
    return did


def report(work: str, quick: bool = False) -> int:
    """What the passes did to every solution kept in ``work``, in words; nothing is run."""
    names = ("nobody all-in", "one all-in", "two all-ins")
    for players in GAMES:
        for stack in STACKS:
            path = os.path.join(work, f"n{players}_s{stack}.json")
            if not kept(path):
                continue
            sol = read(path)
            check(sol, path, players, stack, TRAIN // (20 if quick else 1))
            did = fine(None, sol, path, quick)
            print(f"{players} players, {stack}bb: in from a seat and out from the next after each pass {did['crossed']}")
            for k, spec in enumerate(PASSES):
                what = "every hand" if k == 0 else \
                    f"{did['again'][k - 1]} hands again, {did['moved'][k - 1]} changed sides" + \
                    (f", {did['short'][k - 1]} with fewer deals than asked" if did["short"][k - 1] else "") + \
                    (f"; the band is {did['ratio'][k - 1]} of the first pass's standard errors" if "band" in spec else "")
                left = ", ".join(f"{names[count]} {row[0]:.4f} (at most {row[1]:.4f})"
                                 for count, row in enumerate(did["noise"][k]) if row)
                print(f"    pass {k + 1}, {spec['samples'] // (10 if quick else 1):,} deals: {what}\n"
                      f"        its numbers are good to (bb): {left or 'none left'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", help="folder for the solver's output (kept, and reused when it is there)")
    ap.add_argument("--quick", action="store_true", help="a coarse run for testing: a twentieth of the training, a tenth of the deals")
    ap.add_argument("--fine-only", action="store_true",
                    help="run the later passes for the solutions that are in the work folder, write nothing else")
    ap.add_argument("--report", action="store_true",
                    help="say what every pass did to the solutions in the work folder; run and write nothing")
    a = ap.parse_args()
    if a.report:
        if not a.work:
            ap.error("--report reads a work folder: give --work")
        return report(a.work, a.quick)
    work = a.work or tempfile.mkdtemp(prefix="short-")
    os.makedirs(work, exist_ok=True)
    solver = os.path.join(work, "aof_solver")
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-o", solver,
                           os.path.join(ROOT, "tools", "aof_solver.c"), "-lm"])
    t0 = time.time()
    quick = 10 if a.quick else 1

    def said(did: dict) -> str:
        return " + ".join(str(count) for count in did["again"]) + " hands sampled again"

    if a.fine_only:
        for players in GAMES:
            for stack in STACKS:
                path = os.path.join(work, f"n{players}_s{stack}.json")
                if kept(path):
                    sol = read(path)
                    check(sol, path, players, stack, TRAIN // (20 if a.quick else 1))
                    print(f"{players} players, {stack}bb: {said(fine(solver, sol, path, a.quick))}   ({time.time() - t0:.0f}s)", flush=True)
        return 0
    games = {}
    for players in GAMES:
        nodes, values, did = {}, {}, {}
        for stack in STACKS:
            sol, path = solve(solver, stack, work, a.quick, players)
            did[f"{stack:g}"] = fine(solver, sol, path, a.quick)
            kept = {f"{nd['player']}:{nd['mask']}": nd["ev"] for nd in sol["nodes"] if all_ins(nd["mask"]) <= S.MOST_ALL_IN}
            nodes[f"{stack:g}"] = kept
            values[f"{stack:g}"] = [round(v, 3) for v in sol["value"]]
            print(f"{players} players, {stack}bb: {len(kept)} decision points, {said(did[f'{stack:g}'])}"
                  f"   ({time.time() - t0:.0f}s)", flush=True)
        games[str(players)] = {"stacks": list(STACKS), "value": values, "nodes": nodes}
        for key in ("again", "moved", "crossed", "noise"):          # what the passes did, stack by stack (``fine``)
            games[str(players)][key] = {stack: d[key] for stack, d in did.items()}
    data = {"version": S.DATA_VERSION, "sb": 0.5, "bb": 1, "bb_ante": 1,
            "train": TRAIN // (20 if a.quick else 1),
            "passes": [dict(spec, samples=spec["samples"] // quick, **({"band": list(spec["band"])} if "band" in spec else {}))
                       for spec in PASSES],
            "games": games}
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
