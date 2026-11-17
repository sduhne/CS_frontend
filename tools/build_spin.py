#!/usr/bin/env python3
"""Build poker_coach/data/spin.json: all-in or fold for 3-player winner-take-all sit & gos.

    python3 tools/build_spin.py            # about 7 minutes (it compiles and runs the C solver)
    python3 tools/build_spin.py --quick    # coarse, for testing

A spin (GGPoker "Spin & Gold", PokerStars "Spin & Go") is three players and,
in the common games, one prize: chips are money, so there is no ICM and the
exact all-in or fold solution of the chip game is the right table.  This
takes the 3-handed and heads-up chip solutions already in aof.json (2 to 20
big blinds), solves 25 and 30 big blinds, and for every depth adds the best
reply to opponents who shove normally but call 1.5 times (``loose``) or twice
(``vloose``) too many hands, with what each strategy earns against each kind
of opponent.  The rows for a limp or a small raise in front, which the all-in
or fold game does not have, come from the Python push/fold solver.

See poker_coach/spin.py for how the data is read.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_aof_exploit as X                                          # noqa: E402
from poker_coach import spin as S                                      # noqa: E402
from poker_coach.cards import format_range                             # noqa: E402
from poker_coach.icm import Prizes                                     # noqa: E402
from poker_coach.pushfold import HandSetup, build_shove_spot, solve_shove   # noqa: E402
from poker_coach.ranges import play_order                              # noqa: E402
from poker_coach.cards import top_percent                              # noqa: E402

AOF = os.path.join(ROOT, "poker_coach", "data", "aof.json")
OUT = os.path.join(ROOT, "poker_coach", "data", "spin.json")
TRAIN = {2: 60_000_000, 3: 100_000_000}


def main() -> int:
    quick = "--quick" in sys.argv
    t0 = time.time()
    work = tempfile.mkdtemp(prefix="spin-")
    solver = os.path.join(work, "aof_solver")
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-o", solver,
                           os.path.join(ROOT, "tools", "aof_solver.c"), "-lm"])

    def run(*args: str) -> dict:
        return json.loads(subprocess.check_output([solver, *args]))

    with open(AOF) as fh:
        stored = {(s["n"], float(s["stack"])): s for s in json.load(fh)["solutions"] if s["family"] == "chips"}

    def solution(n: int, stack: float) -> dict:
        """The equal-stack chip solution: {"player:mask": EVs of moving all-in (or calling), in big blinds}."""
        if (n, stack) in stored:
            return {key: node["e"] for key, node in stored[(n, stack)]["nodes"].items()}
        csv = ",".join([f"{stack:g}"] * n)
        sol = run(csv, "0", "1", str(TRAIN[n] // (15 if quick else 1)), "4000000", "2000" if quick else "20000")
        return {f"{nd['player']}:{nd['mask']}": nd["ev"] for nd in sol["nodes"]}

    def evaluate(csv: str, hero: dict, opp: dict) -> list[float]:
        hp, op = os.path.join(work, "hero.txt"), os.path.join(work, "opp.txt")
        X.write_strategy(hp, hero)
        X.write_strategy(op, opp)
        return [round(v, 4) for v in run("eval", csv, "0", "1", "400000" if quick else "4000000", hp, op)["value"]]

    games: dict = {}
    for n in (3, 2):
        games[str(n)] = {}
        for stack in S.STACKS:
            csv = ",".join([f"{stack:g}"] * n)
            evs = solution(n, float(stack))
            fake = {key: {"e": e} for key, e in evs.items()}
            strat = {"solid": {key: S.tidy(ev) for key, ev in evs.items()}}
            opp = {"solid": {key: [1 if e > 0 else 0 for e in ev] for key, ev in evs.items()}}
            ev_out = {"solid": evs}
            for name, k in S.PROFILES.items():
                if name == "solid":
                    continue
                opp[name] = X.opponent_strategy(fake, k)
                path = os.path.join(work, "opp.txt")
                X.write_strategy(path, opp[name])
                br = run("br", csv, "0", "1", "2000" if quick else "20000", path)
                # a situation these opponents never create keeps the solved answer
                ev_out[name] = {f"{nd['player']}:{nd['mask']}": (nd["ev"] if nd["samples"] >= 200 else evs[f"{nd['player']}:{nd['mask']}"])
                                for nd in br["nodes"]}
                strat[name] = {key: S.tidy(ev) for key, ev in ev_out[name].items()}
            value = {}
            for hero_name in S.PROFILES:
                for opp_name in S.PROFILES:
                    value[f"{hero_name}|{opp_name}"] = evaluate(csv, strat[hero_name], opp[opp_name])
            games[str(n)][f"{stack:g}"] = {
                "play": {name: {key: "".join(map(str, v)) for key, v in st.items()} for name, st in strat.items()},
                "calls": {name: {key: "".join(map(str, v)) for key, v in st.items() if not key.endswith(":0")}
                          for name, st in opp.items() if name != "solid"},
                "ev": {name: {key: [round(e, 2) for e in ev] for key, ev in table.items()} for name, table in ev_out.items()},
                "value": value,
            }
            print(f"n={n} stack={stack:g}: best reply to loose callers earns "
                  f"{sum(value['loose|loose']) / n:+.3f} bb a hand ({time.time() - t0:.0f}s)", flush=True)

    data = {"version": S.DATA_VERSION, "stacks": list(S.STACKS), "profiles": S.PROFILES, "games": games,
            "raise": raise_rows()}
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1024:.0f} KB) in {time.time() - t0:.0f}s")
    return 0


# --------------------------------------------------------------------------
# A limp or a small raise in front: all-in or fold (the all-in or fold game has
# no such move, so these come from the Python solver, on chips)
# --------------------------------------------------------------------------

def raise_rows() -> dict:
    """{situation: [range per stack band]}.

    The opponent's range is an assumption (S.OPENERS): the share of hands they
    limp or raise with from that seat.  They then call the all-in whenever the
    price is right for the hand they hold.
    """
    out = {}
    order = list(play_order())
    for key, (n, opener_nb, hero_nb, bet, share, _label) in S.OPENERS.items():
        rng = top_percent(share, order)
        row = []
        for _band, stack in S.BANDS:
            setup = HandSetup([float(stack)] * n, 0.5, 1.0, 0.0, 0.0)
            hero, opener = n - 1 - hero_nb, n - 1 - opener_nb
            behind = [j for j in range(hero + 1, n) if j != opener]
            v_fold, v_steal, callers = build_shove_spot(
                setup, hero, Prizes(), bets={opener: bet}, priors={opener: rng},
                caller_order=behind + [opener], fold_winner=opener, use_types=False)
            sol = solve_shove(v_fold, v_steal, callers, unit=1.0)
            row.append(format_range(S.tidy([sol.ev_bb(h) - 0.05 for h in range(169)])) or "nothing")
        out[key] = row
    return out


if __name__ == "__main__":
    raise SystemExit(main())
