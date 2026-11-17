#!/usr/bin/env python3
"""Build poker_coach/data/binary.json: the all-in or fold tables for a whole tournament.

One set of tables per table size (6, 7 and 8 players); about two minutes in
all.  See poker_coach/binary.py for what the tables mean.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from poker_coach import binary as B                                   # noqa: E402
from poker_coach import latereg as L                                  # noqa: E402
from poker_coach.cards import format_range, range_pct                 # noqa: E402
from poker_coach.equity import eq_vs_range                            # noqa: E402
from poker_coach.icm import Prizes, default_payouts                   # noqa: E402
from poker_coach.pushfold import HandSetup, solve_open_shove, solve_reshove   # noqa: E402
from poker_coach.ranges import PLAYER_TYPES, open_size_bb, scale_range, villain_open_range   # noqa: E402

COMMITTED_BB = 7.5      # at this stack or less a raiser never folds to the all-in


def antes(players: int) -> float:
    """Ante money in the pot, in big blinds: every player antes an eighth of a big blind."""
    return players * B.PLAYER_ANTE


def setup(stack: float, players: int) -> HandSetup:
    # the antes are posted as one big-blind ante of the same total: one big blind at eight players
    return HandSetup([float(stack)] * players, 0.5, 1.0, 0.0, antes(players))


def money_prizes(stack: float, players: int) -> Prizes:
    e = B.ENTRY
    pays = default_payouts(e["entrants"], int(e["entrants"] * e["paid"]))
    return Prizes(pays, B.MONEY_LEFT - players, float(stack))


def entry_plan(players: int, speed: str | None = None, policy: str = "ev") -> L.Plan:
    """The plan that earns the most prize money for a late entry (latereg policy ``ev``)."""
    e = B.ENTRY
    remaining, paid = int(e["entrants"] * e["alive"]), int(e["entrants"] * e["paid"])
    sp = L.SPEEDS[speed or e["speed"]]
    blinds = L.Blinds(sp["growth"], sp["hands_per_level"], 0.0, ())
    avg_bb = e["stack_bb"] * e["entrants"] / remaining
    fc = L.forecast(remaining, paid, avg_bb, blinds, players, L.BUST_CONSTANT)
    blinds = fc.blinds or blinds
    pays = L.payouts_with_min_cash(e["entrants"], paid, e["entrants"] * (1.0 - e["fee"]), L.MIN_CASH_MULTIPLE)
    reward = L.bubble_reward(e["entrants"], paid, pays, 1.0, remaining * avg_bb)
    return L.solve(e["stack_bb"], fc, blinds, players, "normal", reward=reward, policy=policy)


def to_limits(table: dict[float, list[float]]) -> list[int]:
    """Deepest solved stack at which each hand is an all-in, ignoring one-stack blips."""
    out = []
    for h in range(169):
        seq = [1 if table[s][h] >= 0.5 else 0 for s in B.STACKS]
        for i in range(1, len(seq)):
            alone = seq[i] and not seq[i - 1] and (i == len(seq) - 1 or not seq[i + 1])
            if alone:
                seq[i] = 0
        deepest = max((i for i, v in enumerate(seq) if v), default=None)
        out.append(0 if deepest is None else int(B.STACKS[deepest]))
    return out


def first_in(plan: L.Plan, players: int) -> dict:
    out = {"before": {}, "money": {}}
    for nb in B.seats(players):
        out["before"][str(nb)] = to_limits({s: plan.shove_range(0, nb, float(s)) for s in B.STACKS})
        table = {}
        for s in B.STACKS:
            sol = solve_open_shove(setup(s, players), players - 1 - nb, money_prizes(s, players),
                                   caller_prizes=Prizes(), use_types=False)
            margin = B.SAFETY_PER_BB * max(0.0, s - 10.0)
            table[s] = [1.0 if sol.ev_bb(h) > margin else 0.0 for h in range(169)]
        out["money"][str(nb)] = to_limits(table)
    return out


def reshove(plan: L.Plan, players: int) -> dict:
    """All-in over one raise.  Hero is on the button over an early or late raise, and in the
    big blind over a steal.

    Before the money the early and late rows are the plan's own.  The other rows are the ICM
    solver on the pay ladder; the steal row, which the plan does not have, is used in both
    stages.  With COMMITTED_BB or less nobody folds, so the hand goes to a showdown against
    the raiser's whole range and is priced as a call (the solver's one-caller-at-a-time
    shortcut is wrong when several players call).
    """
    out = {"before": {}, "money": {}}
    for key, _label, o_nb in B.raisers(players):
        h_nb = 0 if key == "steal" else 2
        money = []
        for _b, s in B.BANDS:
            opener = villain_open_range(o_nb, "unknown", s)
            if s <= COMMITTED_BB:
                posted = 1.0 if h_nb == 0 else 0.0
                # pot at showdown: both stacks, the antes and the blinds of the players who folded
                pot = 2.0 * s + antes(players) + (0.5 if h_nb == 0 else 1.5)
                need = (s - posted) / pot + B.NORMAL_PREMIUM
                rng = [1.0 if eq_vs_range(h, opener)[0] >= need else 0.0 for h in range(169)]
            else:
                sol = solve_reshove(setup(s, players), players - 1 - h_nb, players - 1 - o_nb,
                                    open_size_bb(s, o_nb, True), money_prizes(s, players),
                                    opener_range=opener, caller_prizes=Prizes(), use_types=False)
                rng = [1.0 if sol.ev_bb(h) > 0.10 else 0.0 for h in range(169)]
            money.append(format_range(rng) or "nothing")
        out["money"][key] = money
        if key == "steal":
            out["before"][key] = list(money)
        else:
            out["before"][key] = [format_range(plan.shove_range(0, 2, s, True, key)) or "nothing" for _b, s in B.BANDS]
    return out


def call(players: int) -> dict:
    """Calling one all-in.  Hero is on the button against an early or late all-in, in the small
    blind against the button's and in the big blind against the small blind's."""
    out = {"normal": {}, "bubble": {}}
    for key, _label, s_nb in B.shovers(players):
        hero_nb = {"early": 2, "late": 2, "button": 1, "small": 0}[key]
        rows = {"normal": [], "bubble": []}
        for _b, s in B.BANDS:
            st = setup(s, players)
            shover, hero = players - 1 - s_nb, players - 1 - hero_nb
            sol = solve_open_shove(st, shover, Prizes(), use_types=False)
            pct = min(100.0, max(1.5, range_pct(sol.shove_range) * PLAYER_TYPES["unknown"]["shove_mult"]))
            rng = scale_range(sol.ev, pct)
            bets = {shover: float(s)}
            win, lose, fold = st.showdown(hero, shover, hero, bets), st.showdown(hero, shover, shover, bets), st.fold_out(shover, bets)
            need = (fold[hero] - lose[hero]) / (win[hero] - lose[hero])
            behind = len([j for j in range(hero + 1, players) if j != shover])
            need += 0.008 * behind
            eqs = [eq_vs_range(h, rng)[0] for h in range(169)]
            for name, premium in (("normal", B.NORMAL_PREMIUM), ("bubble", B.BUBBLE_PREMIUM)):
                rows[name].append(format_range([1.0 if eqs[h] >= need + premium else 0.0 for h in range(169)]) or "nothing")
        for name in rows:
            out[name][key] = rows[name]
    return out


def model_results(players: int) -> dict:
    """What the model says a late entry earns with this plan, by blind speed, and how often a
    chip-EV push/fold chart cashes in the same tournaments."""
    out = {}
    for speed in ("hyper", "turbo", "regular"):
        plan = entry_plan(players, speed)
        chart = entry_plan(players, speed, "nash")
        out[speed] = {"cash": round(plan.itm, 4), "return": round(plan.prize - 1.0, 4), "chart_cash": round(chart.itm, 4)}
    return out


def main() -> None:
    t0 = time.time()
    d = {"version": B.DATA_VERSION, "stacks": list(B.STACKS), "entry": B.ENTRY, "tables": {}}
    for players in B.TABLES:
        plan = entry_plan(players)
        d["tables"][str(players)] = {
            "entry_result": {"cash": round(plan.itm, 4), "return": round(plan.prize - 1.0, 4)},
            "model": model_results(players),
            "first_in": first_in(plan, players), "reshove": reshove(plan, players), "call": call(players)}
        print(f"{players} players: late entry with this plan in the model: cash {plan.itm:.0%}, "
              f"return {plan.prize - 1:+.0%}   ({time.time() - t0:.0f}s)", flush=True)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poker_coach", "data", "binary.json")
    with open(path, "w") as fh:
        json.dump(d, fh, separators=(",", ":"), sort_keys=True)
    print(f"wrote {os.path.normpath(path)} ({os.path.getsize(path) / 1024:.0f} KB) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
