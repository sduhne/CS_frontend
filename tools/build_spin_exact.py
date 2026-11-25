#!/usr/bin/env python3
"""Build poker_coach/data/spin_exact.json: spins (three players, winner takes all) solved exactly, stacks unequal.

    python3 tools/build_spin_exact.py --work DIR     # about two and a half hours on four processors; DIR keeps
                                                     # the solver's output, and what is there is used again
    python3 tools/build_spin_exact.py --work DIR --quick    # a coarse run for testing

The game of a spin: three players (or two, once one is out), a small blind of half a big blind, no ante, and
one prize, so chips are money and the right answer is the chip game's.  Every player moves all-in or folds;
``tools/aof_solver.c`` solves that with real cards and every side pot.  (See poker_coach/spin_exact.py for
what the engine takes from it and why above about 12bb it is only the all-in's part of the answer.)

Stacks.  Of three stacks only two numbers matter: the chips the biggest stack has over the second biggest can
never be won or lost in the hand, so the biggest is cut down to the second, and what is left is two players
with the same stack ``X`` and one with ``Y`` (no more than ``X``), in one of the three seats.  That is the grid
solved here: every ``X`` of X_GRID, every ``Y`` of Y_GRID under it, and the short stack on the button, in the
small blind or in the big blind; and the three equal stacks.  Heads-up only the smaller stack matters.

For each of them, three answers:
* ``solid``: the equilibrium (nobody can do better against it), and what going in earns, hand by hand;
* ``loose``: the best reply to opponents who move all-in first in as solved but call with half as many
  hands again (the common mistake of low-stakes spins);
* ``tight``: the best reply to opponents who move all-in and call with four fifths of the solved hands (a
  third fewer made the best reply move in with three hands in four from the button with 10bb: too far to
  follow against players who are only a little tight).
The best replies are sampled 20,000 times a hand; the equilibrium 50,000 times a hand at every decision.

Some decisions never come in the equilibrium: with 1bb in the small blind a player calls every all-in, so
"the small blind folded" never happens.  Real opponents do fold there, so the solver trains such a decision
as if it were reached now and then, and samples it with the earlier players' hands trembling (each action at
least 2% likely); the configuration lists them under ``never``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from poker_coach.cards import COMBO_COUNT                             # noqa: E402

OUT = os.path.join(ROOT, "poker_coach", "data", "spin_exact.json")
VERSION = 1
X_GRID = (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25, 30)      # the two biggest stacks, in big blinds
Y_GRID = (1, 1.5, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25)  # the short stack, under X
HU_GRID = (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25, 30)
SEATS = ("BTN", "SB", "BB")                                             # three players, in the order they act
TRAIN, EVAL, REFINE, BR = 20_000_000, 1_000_000, 50_000, 20_000
PROFILES = {"loose": (1.0, 1.5), "tight": (0.8, 0.8)}                 # opponents: (first-in all-ins, calls) as a
                                                                        # multiple of the solved number of hands


def configs() -> list[tuple[int, float, float, int]]:
    """(players, X, Y, the short stack's seat): heads-up as (2, E, E, -1), equal stacks with seat -1."""
    out = [(2, float(e), float(e), -1) for e in HU_GRID]
    for x in X_GRID:
        out.append((3, float(x), float(x), -1))
        for y in Y_GRID:
            if y < x:
                for seat in range(3):
                    out.append((3, float(x), float(y), seat))
    return out


def stacks_of(players: int, x: float, y: float, seat: int) -> list[float]:
    if players == 2:
        return [x, x]
    out = [x, x, x]
    if seat >= 0:
        out[seat] = y
    return out


def key_of(players: int, x: float, y: float, seat: int) -> str:
    return f"{x:g}" if players == 2 else (f"{x:g}" if seat < 0 else f"{x:g},{y:g},{SEATS[seat]}")


def strategy(evs: dict[str, list[int]], shove_k: float, call_k: float) -> dict[str, list[int]]:
    """Opponents who play the solved hands in order of what they earn, ``shove_k`` times as many when first in
    and ``call_k`` times as many when somebody is all-in already (first-in: mask 0)."""
    out = {}
    for key, ev in evs.items():
        k = shove_k if key.endswith(":0") else call_k
        base = sum(c for e, c in zip(ev, COMBO_COUNT) if e > 0)
        take, acc = [0] * 169, 0.0
        for h in sorted(range(169), key=lambda h: -ev[h]):
            if acc >= k * base - 1e-9:
                break
            take[h] = 1
            acc += COMBO_COUNT[h]
        out[key] = take
    return out


def write_strategy(path: str, strat: dict[str, list[int]]) -> None:
    with open(path, "w") as fh:
        fh.write(f"{len(strat)}\n")
        for key, vals in strat.items():
            player, mask = key.split(":")
            fh.write(f"{player} {mask} " + " ".join(str(v) for v in vals) + "\n")


def run(solver: str, args: list[str], path: str) -> dict:
    if not os.path.exists(path):
        raw = subprocess.check_output([solver] + args)
        with open(path + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(path + ".tmp", path)
    with open(path) as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True, help="folder for the solver's output (kept, and reused when it is there)")
    ap.add_argument("--quick", action="store_true", help="a coarse run for testing: a tenth of the deals")
    ap.add_argument("--assemble-only", action="store_true",
                    help="write the data file from the solutions that are in the work folder, solve nothing")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    solver = os.path.join(a.work, "aof_solver")
    if not a.assemble_only:         # (a run may be using the binary: assembling leaves it alone)
        subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-o", solver,
                               os.path.join(ROOT, "tools", "aof_solver.c"), "-lm"])
    q = 10 if a.quick else 1
    games: dict = {"2": {}, "3": {}}
    t0 = time.time()
    todo = configs()
    for i, (n, x, y, seat) in enumerate(todo):
        st = stacks_of(n, x, y, seat)
        csv = ",".join(f"{s:g}" for s in st)
        name = f"n{n}_" + "_".join(f"{s:g}" for s in st)
        if a.assemble_only and not all(os.path.exists(os.path.join(a.work, f"{name}{part}.json"))
                                       for part in ("", ".loose", ".tight")):
            continue
        # stacks, fee, fee mode, training deals, evaluation deals, samples a hand, ante of every player, ante of the
        # big blind, precision pass up to this many all-ins (all of them: three players have at most two before)
        sol = run(solver, [csv, "0", "1", str(TRAIN // q), str(EVAL // q), str(REFINE // q), "0", "0", "2"],
                  os.path.join(a.work, name + ".json"))
        if any(abs(u - v) > 1e-9 for u, v in zip(sol["stacks"], st)) or sol.get("ante") or sol.get("bb_ante"):
            raise SystemExit(f"{name}: the kept answer is for another game")
        solid = {f"{nd['player']}:{nd['mask']}": nd["ev"] for nd in sol["nodes"]}
        if any(nd["samples"] <= 0 for nd in sol["nodes"]):
            raise SystemExit(f"{name}: the precision pass found no deal for a decision")
        entry = {"value": [round(v, 4) for v in sol["value"]], "solid": solid}
        never = [f"{nd['player']}:{nd['mask']}" for nd in sol["nodes"] if nd.get("trembled")]
        if never:
            entry["never"] = never          # decisions the equilibrium never reaches: answered for a trembling opponent
        for prof, (shove_k, call_k) in PROFILES.items():
            path = os.path.join(a.work, f"{name}.{prof}.txt")
            write_strategy(path, strategy(solid, shove_k, call_k))
            br = run(solver, ["br", csv, "0", "1", str(BR // q), path, "0", "0", "2"],
                     os.path.join(a.work, f"{name}.{prof}.json"))
            # a decision these opponents never let happen keeps the solved answer
            entry[prof] = {f"{nd['player']}:{nd['mask']}": (nd["ev"] if nd["samples"] > 0 else solid[f"{nd['player']}:{nd['mask']}"])
                           for nd in br["nodes"]}
        games[str(n)][key_of(n, x, y, seat)] = entry
        if i % 20 == 0 or i == len(todo) - 1:
            print(f"{i + 1}/{len(todo)} {name}   ({time.time() - t0:.0f}s)", flush=True)
    data = {"version": VERSION, "sb": 0.5, "bb": 1, "ante": 0, "train": TRAIN // q, "samples": REFINE // q,
            "br_samples": BR // q, "x": list(X_GRID), "y": list(Y_GRID), "hu": list(HU_GRID), "seats": list(SEATS),
            "profiles": {k: list(v) for k, v in PROFILES.items()}, "games": games}
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
