#!/usr/bin/env python3
"""Build poker_coach/data/short.json: all-ins of 2 to 20 big blinds, solved exactly (see poker_coach/short.py).

    python3 tools/build_short.py                 # compiles the solver and runs it for both kinds of ante: about four hours
                                                 # on four processors for the big blind ante (14 minutes a stack for nine
                                                 # players, 2 for the smaller tables together, 40 minutes for the second
                                                 # pass) and seven for the ante of every player, which has two tables more
                                                 # (eight players: 7 minutes a stack, seven players: 4)
    python3 tools/build_short.py --work DIR      # keeps the solver's own output there, and uses what is there already
    python3 tools/build_short.py --work DIR --ante player   # that kind only: the other is kept as the data file has it
    python3 tools/build_short.py --work DIR --fine-only     # the second pass for the solutions that are in DIR, no more
    python3 tools/build_short.py --work DIR --pack          # the finished tables of DIR, packed into tools/short_work/

The solver's own output is kept, packed, in tools/short_work/ (one archive for each kind of ante and table:
both passes of every stack, 4 MB in all for the ante of every player; the big blind ante's was not kept when
it was solved).  A run unpacks what is there into its work folder first and solves only what is missing, so
with the archives the ante of every player is assembled in a minute; ``--fresh`` leaves them alone and solves
again, which is what a change to the solver or to the game asks for.  tools/check_short.py reads the same
files.

Equal stacks and a small blind of half a big blind; every player moves all-in or folds.  Two games, one
for each kind of ante (ANTES): the big blind pays one big blind for the table ("bb"), or every player
pays an eighth of a big blind ("player", GGPoker's).  The solver (tools/aof_solver.c) deals real cards,
so every showdown and side pot is exact, and so is what the folded hands take out of the deck.  Kept:
what going in earns over folding, hand by hand, for every player with at most two players all-in before
him.

The tables (GAMES).  With a big blind ante: 9, 6, 5, 4 and 3 players; 7 and 8 are read from the last
seats of the nine, where the same big blind of ante is in the pot.  With an ante from every player the
pot goes with the number of players (1.125bb at nine, 1bb at eight, 0.875bb at seven), so 8 and 7 are
solved as well: read from the nine, a table of eight would play for an eighth of a big blind that is
not there.

Two passes.  The first solves the game and samples every hand of every decision point 10,000 times: a
number is then good to about 0.06bb first in and 0.1bb for a call with 6 to 10bb, more with a deeper
stack (an all-in of 20bb swings more).  That is plenty for a hand that is clearly in or out and too little
for the hands at the edge of a range, which are the ones a chart is read for.  So the second pass takes
every hand the first left near zero, at the decision points with nobody or one player all-in, and samples
it 100,000 times against the same solved strategies: a third of the noise.  (On a trial stack, nine
players with 8bb and a big blind ante, 82 of the 1,070 hands it took changed sides, and the five hands
that were in from one seat and out from the next were gone.)  With two players all-in a decision point
comes up too rarely to sample that often: there the first pass stands, and the engine calls a wider band
close (short.CLOSE_TWO).
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
ANTES = {"bb": (0.0, 1.0), "player": (S.PLAYER_ANTE, 0.0)}     # kind -> (the ante of every player, the ante of the big blind)
GAMES = {"bb": (9, 6, 5, 4, 3),             # tables solved as such; 7 and 8 players are read from the last seats of the nine
         "player": (9, 8, 7, 6, 5, 4, 3)}   # ... which an ante from every player does not allow: the pot is another one
STACKS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16, 20)   # big blinds: every stack of the push-or-fold zone, and three deeper
                                # ones that the stacks between are drawn from (an all-in is weighed up to 20bb)
TRAIN, EVAL, REFINE = 40_000_000, 2_000_000, 10_000
FINE = 100_000                  # the second pass: samples for a hand the first pass left near zero ...
FINE_ALL_INS = 1                # ... at the decision points with at most this many players all-in before
BAND = (0.05, 0.04)             # near zero: within 0.05bb and 0.04bb for each big blind of the stack, about four
                                # times the noise of the first pass (which grows with the stack: 0.01bb a big blind)


def band(stack: float) -> float:
    return BAND[0] + BAND[1] * stack


def work_path(work: str, kind: str, players: int, stack: int) -> str:
    """Where the solver's own answer for one game is kept: the kind of ante, the players, the stack."""
    return os.path.join(work, f"{kind}_n{players}_s{stack}.json")


def solve(solver: str, kind: str, stack: int, work: str, quick: bool, players: int = S.PLAYERS) -> tuple[dict, str]:
    path = work_path(work, kind, players, stack)
    if not os.path.exists(path):
        stacks = ",".join([str(stack)] * players)
        train, refine = (TRAIN // 20, REFINE // 10) if quick else (TRAIN, REFINE)
        each, big_blind = ANTES[kind]
        # stacks, fee, fee mode, training deals, evaluation deals, samples a hand, ante of every player,
        # ante of the big blind, precision pass up to this many all-ins
        raw = subprocess.check_output([solver, stacks, "0", "1", str(train), str(EVAL), str(refine), f"{each:g}", f"{big_blind:g}",
                                       str(S.MOST_ALL_IN)])
        with open(path + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(path + ".tmp", path)
    with open(path) as fh:
        return json.load(fh), path


def is_game(sol: dict, kind: str, players: int, stack: float) -> bool:
    """Is a kept answer the one for this game?"""
    each, big_blind = ANTES[kind]
    return sol["n"] == players and abs(sol.get("ante", 0.0) - each) < 1e-9 and abs(sol.get("bb_ante", 0.0) - big_blind) < 1e-9 \
        and all(abs(x - stack) < 1e-9 for x in sol["stacks"])


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
        # decision points with at most this many all-ins, the hands.  The antes are the solution's own.
        raw = subprocess.check_output([solver, "br", stacks, "0", "1", str(FINE // (10 if quick else 1)), base + ".strategy.txt",
                                       f"{sol.get('ante', 0.0):g}", f"{sol.get('bb_ante', 0.0):g}", str(FINE_ALL_INS),
                                       base + ".hands.txt"])
        with open(out + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(out + ".tmp", out)
    with open(out) as fh:
        again = {(nd["player"], nd["mask"]): nd["ev"] for nd in json.load(fh)["nodes"]}
    nodes = {(nd["player"], nd["mask"]): nd for nd in sol["nodes"]}
    for i, m, c in hands:
        nodes[i, m]["ev"][c] = again[i, m][c]
    return len(hands)


def build(solver: str, kind: str, work: str, quick: bool, tables=None, started: float | None = None) -> dict:
    """One kind of ante, both passes, every table and stack -> its part of the data file."""
    t0 = started or time.time()
    games = {}
    for players in tables or GAMES[kind]:
        nodes, values, again = {}, {}, {}
        for stack in STACKS:
            sol, path = solve(solver, kind, stack, work, quick, players)
            if not is_game(sol, kind, players, stack):
                raise SystemExit(f"{path}: the kept answer is for another game")
            again[f"{stack:g}"] = fine(solver, sol, path, quick)
            kept = {}
            for nd in sol["nodes"]:
                if bin(nd["mask"]).count("1") <= S.MOST_ALL_IN:
                    if nd["samples"] <= 0:
                        raise SystemExit(f"{kind}, {players} players, {stack}bb, player {nd['player']}, mask {nd['mask']}: "
                                         "the precision pass found no deal")
                    kept[f"{nd['player']}:{nd['mask']}"] = nd["ev"]
            nodes[f"{stack:g}"] = kept
            values[f"{stack:g}"] = [round(v, 3) for v in sol["value"]]
            print(f"{kind} ante, {players} players, {stack}bb: {len(kept)} decision points, {again[f'{stack:g}']} hands sampled "
                  f"again   ({time.time() - t0:.0f}s)", flush=True)
        games[str(players)] = {"stacks": list(STACKS), "value": values, "nodes": nodes, "again": again}
    each, big_blind = ANTES[kind]
    slow = 10 if quick else 1
    return {"ante": each, "bb_ante": big_blind, "train": TRAIN // (20 if quick else 1), "samples": REFINE // slow,
            "fine": {"samples": FINE // slow, "all_ins": FINE_ALL_INS, "band": list(BAND)}, "games": games}


KEPT = os.path.join(ROOT, "tools", "short_work")      # the solver's own answers, packed: "<kind>_n<players>.tar.xz"
PACKED = (".json", ".fine.json", ".hands.txt")        # of each stack: the first pass, the second, and the hands the second sampled


def table_done(work: str, kind: str, players: int) -> bool:
    """Are both passes of every stack of one table in the work folder?"""
    return all(os.path.exists(work_path(work, kind, players, stack)[:-len(".json")] + end) for stack in STACKS for end in PACKED)


def pack(work: str, kind: str, players: int) -> str:
    """One table's answers from the work folder into its archive.  The same files give the same archive."""
    import io
    import lzma
    import tarfile
    os.makedirs(KEPT, exist_ok=True)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for stack in STACKS:
            for end in PACKED:
                path = work_path(work, kind, players, stack)[:-len(".json")] + end
                info = tarfile.TarInfo(os.path.basename(path))
                info.size, info.mtime, info.mode = os.path.getsize(path), 0, 0o644
                with open(path, "rb") as fh:
                    tar.addfile(info, fh)
    out = os.path.join(KEPT, f"{kind}_n{players}.tar.xz")
    with open(out, "wb") as fh:
        fh.write(lzma.compress(raw.getvalue(), preset=9 | lzma.PRESET_EXTREME))
    return out


def unpack(work: str) -> int:
    """The kept answers into the work folder, where a file is not there yet.  -> how many files that was."""
    import tarfile
    count = 0
    for name in sorted(os.listdir(KEPT)) if os.path.isdir(KEPT) else []:
        if not name.endswith(".tar.xz"):
            continue
        with tarfile.open(os.path.join(KEPT, name)) as tar:
            for member in tar.getmembers():
                target = os.path.join(work, os.path.basename(member.name))
                if member.isfile() and not os.path.exists(target):
                    with tar.extractfile(member) as src, open(target + ".tmp", "wb") as dst:
                        dst.write(src.read())
                    os.replace(target + ".tmp", target)
                    count += 1
    return count


def kept_from_file(kind: str) -> dict:
    """A kind of ante as the data file has it now, for a run that solves the other one only."""
    try:
        with open(OUT) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    if d.get("version") != S.DATA_VERSION or kind not in d.get("antes", {}):
        raise SystemExit(f"{OUT} has no {kind} ante of version {S.DATA_VERSION} to keep: solve it as well (--ante {kind})")
    return d["antes"][kind]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", help="folder for the solver's output (kept, and reused when it is there)")
    ap.add_argument("--ante", default=",".join(S.KINDS),
                    help="the kinds of ante to solve, comma separated (bb, player); a kind left out is kept as the data file has it")
    ap.add_argument("--quick", action="store_true", help="a coarse run for testing: a twentieth of the deals")
    ap.add_argument("--fine-only", action="store_true",
                    help="run the second pass for the solutions that are in the work folder, write nothing else")
    ap.add_argument("--pack", action="store_true",
                    help="pack the finished tables of the work folder into tools/short_work/, write nothing else")
    ap.add_argument("--fresh", action="store_true", help="do not use the answers kept in tools/short_work/: solve again")
    a = ap.parse_args()
    wanted = [k.strip() for k in a.ante.split(",") if k.strip()]
    if not wanted or any(k not in S.KINDS for k in wanted):
        raise SystemExit(f"--ante: one or more of {', '.join(S.KINDS)}")
    work = a.work or tempfile.mkdtemp(prefix="short-")
    os.makedirs(work, exist_ok=True)
    if a.pack:
        for kind in wanted:
            for players in GAMES[kind]:
                if table_done(work, kind, players):
                    out = pack(work, kind, players)
                    print(f"{kind} ante, {players} players: {out} ({os.path.getsize(out) / 1024:.0f} KB)")
        return 0
    if not a.fresh and not a.quick:
        count = unpack(work)
        if count:
            print(f"{count} files of the solver's kept answers unpacked into {work}", flush=True)
    solver = os.path.join(work, "aof_solver")
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-o", solver,
                           os.path.join(ROOT, "tools", "aof_solver.c"), "-lm"])
    t0 = time.time()
    if a.fine_only:
        for kind in wanted:
            for players in GAMES[kind]:
                for stack in STACKS:
                    path = work_path(work, kind, players, stack)
                    if os.path.exists(path) and not os.path.exists(path[:-len(".json")] + ".fine.json"):
                        with open(path) as fh:
                            sol = json.load(fh)
                        count = fine(solver, sol, path, a.quick)
                        print(f"{kind} ante, {players} players, {stack}bb: {count} hands sampled again   ({time.time() - t0:.0f}s)",
                              flush=True)
        return 0
    antes = {kind: build(solver, kind, work, a.quick, started=t0) if kind in wanted else kept_from_file(kind) for kind in S.KINDS}
    data = {"version": S.DATA_VERSION, "sb": 0.5, "bb": 1, "antes": antes}
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
