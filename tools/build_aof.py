#!/usr/bin/env python3
"""Build poker_coach/data/aof.json: All-In or Fold solutions on a stack grid.

    python3 tools/build_aof.py            # compiles the solver and runs the grid (about 35 minutes)
    python3 tools/build_aof.py --quick    # coarse run for testing (about 3 minutes)

Two families are solved, for 2, 3 and 4 players with equal stacks:

* ``cash``: the ring-game format with a fixed fee taken from every pot
  (0.1 big blinds), stacks 2 to 8 big blinds (the table cap is 8);
* ``chips``: no fee, stacks 2 to 20 big blinds, the baseline for All-In or
  Fold tournaments.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "poker_coach", "data", "aof.json")
CASH_FEE = 0.1
CASH_STACKS = [2, 3, 4, 5, 6, 7, 8]
CHIP_STACKS = [2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20]
TRAIN = {2: 60_000_000, 3: 100_000_000, 4: 150_000_000}


def main() -> int:
    quick = "--quick" in sys.argv
    work = tempfile.mkdtemp(prefix="aof-")
    solver = os.path.join(work, "aof_solver")
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-o", solver,
                           os.path.join(ROOT, "tools", "aof_solver.c"), "-lm"])
    jobs = [("cash", CASH_FEE, s, n) for s in CASH_STACKS for n in (4, 3, 2)]
    jobs += [("chips", 0.0, s, n) for s in CHIP_STACKS for n in (4, 3, 2)]
    solutions = []
    for k, (family, fee, stack, n) in enumerate(jobs, 1):
        train = TRAIN[n] // (15 if quick else 1)
        refine = 2000 if quick else 20000
        if family == "cash" and stack == 8 and n == 4 and not quick:
            train, refine = 400_000_000, 40000     # the format everybody actually plays
        stacks = ",".join([str(stack)] * n)
        raw = subprocess.check_output([solver, stacks, str(fee), "1", str(train), "4000000", str(refine)])
        sol = json.loads(raw)
        solutions.append({
            "family": family, "n": n, "stack": stack, "fee": fee,
            "value": [round(v, 3) for v in sol["value"]],
            "nodes": {f"{nd['player']}:{nd['mask']}": {"f": nd["freq"], "e": nd["ev"]} for nd in sol["nodes"]},
        })
        print(f"[{k}/{len(jobs)}] {family} n={n} stack={stack}", flush=True)
    with open(OUT, "w") as fh:
        json.dump({"version": 1, "solutions": solutions}, fh, separators=(",", ":"))
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
