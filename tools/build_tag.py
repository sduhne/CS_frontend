#!/usr/bin/env python3
"""Build poker_coach/data/tag.json: every preflop situation of a tight-aggressive tournament
player, as text, for tables of 6, 7 and 8 players.

    python3 tools/build_tag.py            # about 6 minutes

The answers are the coach's own.  For each situation the engine (poker_coach.preflop.advise)
is asked what it does with each of the 169 hands, far from the money and on chips, and the
hands are grouped by the action it gives.  All-in decisions are not asked again: they are the
all-in or fold tournament tables (poker_coach.binary), which are built to reach the money and
are tighter than a chip-EV chart.  See poker_coach/tag.py for the layout of the data.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from poker_coach import binary as B                                           # noqa: E402
from poker_coach import tag as T                                              # noqa: E402
from poker_coach.cards import format_range, parse_range                       # noqa: E402
from poker_coach.equity import eq_vs_range                                    # noqa: E402
from poker_coach.icm import Prizes                                            # noqa: E402
from poker_coach.preflop import (Act, Spot, _REALIZE, _call_numbers, _hand_kind, _scaled_range,   # noqa: E402
                                 _shover_solution, advise)
from poker_coach.pushfold import HandSetup                                    # noqa: E402
from poker_coach.ranges import open_size_bb, rfi_range, villain_open_range    # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poker_coach", "data", "tag.json")


def setup(players: int, stack: float, stacks: dict[int, float] | None = None) -> HandSetup:
    """Equal stacks (``stacks`` overrides seats by players behind); every player antes 1/8 bb."""
    chips = [float(stack)] * players
    for nb, s in (stacks or {}).items():
        chips[players - 1 - nb] = float(s)
    return HandSetup(chips, 0.5, 1.0, 0.0, players * B.PLAYER_ANTE)


def spot(players: int, hero_nb: int, stack: float, acts, hand: int, stacks=None) -> Spot:
    s = Spot(setup=setup(players, stack, stacks), hero=players - 1 - hero_nb, hand=hand,
             prizes=Prizes(), field_prizes=Prizes())
    s.acts = [Act(players - 1 - nb, kind, amount) for nb, kind, amount in acts]
    return s


def ask(players: int, hero_nb: int, stack: float, acts, stacks=None) -> dict[str, list[float]]:
    """What the engine does with every hand: {action: range}."""
    out: dict[str, list[float]] = {}
    for h in range(169):
        action = advise(spot(players, hero_nb, stack, acts, h, stacks)).action
        if "semi-bluff" in action:
            key = "bluff"
        elif action.startswith("3-BET") or action.startswith("4-BET"):
            key = "reraise"
        elif action.startswith("CALL (limp"):
            key = "limp"
        elif "ALL-IN" in action:
            key = "allin"
        else:
            key = action.split()[0].lower()            # raise, call, check, fold
        out.setdefault(key, [0.0] * 169)[h] = 1.0
    return out


def text(weights) -> str:
    """A range as text; an empty one is an empty string."""
    return format_range(weights) if weights and max(weights) >= 0.5 else ""


def minus(a, b) -> list[float]:
    b = b or [0.0] * 169
    return [1.0 if x >= 0.5 and y < 0.5 else 0.0 for x, y in zip(a or [0.0] * 169, b)]


def union(*ranges) -> list[float]:
    out = [0.0] * 169
    for r in ranges:
        if r:
            out = [max(x, y) for x, y in zip(out, r)]
    return out


# --------------------------------------------------------------------------
# 1. Nobody has entered
# --------------------------------------------------------------------------

def first_in(players: int) -> dict:
    out = {}
    for nb in T.seats(players):
        out[str(nb)] = {
            "raise": [text(rfi_range(nb, 100.0)), text(rfi_range(nb, 20.0))],
            "size": [f"{open_size_bb(100.0, nb):g}", f"{open_size_bb(30.0, nb):g}", f"{open_size_bb(20.0, nb):g}"],
            "allin": [text(B.first_in_range("before", nb, s, players)) for s in T.SHORT_STACKS],
        }
    return out


# --------------------------------------------------------------------------
# 2. Players only called
# --------------------------------------------------------------------------

def limpers(players: int) -> dict:
    """Hero in every seat that can have callers in front, with one, two and three of them."""
    out = {}
    for nb in list(T.seats(players))[1:] + [0]:
        row = {"raise": [], "call": [], "mid": [], "allin": None}
        for k in (1, 2, 3):
            if nb + k > players - 1:
                break
            acts = [(nb + j, "limp", 1.0) for j in range(k, 0, -1)]
            deep = ask(players, nb, 40.0, acts)
            mid = ask(players, nb, 20.0, acts)
            row["raise"].append(text(union(deep.get("raise"), deep.get("allin"))))
            row["call"].append(text(deep.get("limp")))
            row["mid"].append(text(union(mid.get("raise"), mid.get("allin"))))
        # 16bb or less: the all-in hands of the seat before (the big blind: the small blind's)
        row["allin"] = [text(B.first_in_range("before", nb + 1, s, players)) for s in T.SHORT_STACKS]
        out[str(nb)] = row
    return out


# --------------------------------------------------------------------------
# 3. A raise before you
# --------------------------------------------------------------------------

def raiser_groups(players: int) -> list[tuple[str, int]]:
    """(group, a seat of it) for the groups that exist at this table."""
    out = []
    if players - 1 >= 6:
        out.append(("early", players - 1))
    out += [("middle", 4), ("late", 3), ("sb", 1)]
    return out


def vs_raise(players: int) -> dict:
    """25bb or more: re-raise, call or fold, by where the raise came from and where hero sits."""
    out = {}
    for group, r_nb in raiser_groups(players):
        heroes = [("bb", 0)] if group == "sb" else [("ip", 2), ("sb", 1), ("bb", 0)]
        for where, h_nb in heroes:
            size = 3.0 if group == "sb" else 2.3
            deep = ask(players, h_nb, 60.0, [(r_nb, "raise", size)])
            mid = ask(players, h_nb, 40.0, [(r_nb, "raise", size)])
            low = ask(players, h_nb, 30.0, [(r_nb, "raise", 3.0 if group == "sb" else 2.2)])
            value = union(low.get("reraise"), low.get("allin"))
            core = low.get("call") if where != "bb" else deep.get("call")       # the big blind calls by the price
            row = {"value": text(value), "bluff": text(deep.get("bluff")), "call": text(core)}
            if where == "ip":
                row["setmine"] = text(minus(mid.get("call"), low.get("call")))
                row["button"] = text(minus(deep.get("call"), mid.get("call")))
            out[f"{group}|{where}"] = row
    return out


def bb_call_short(players: int) -> dict:
    """Big blind, 9 to 24bb, a raise to 2bb: the hands that get the price to call.

    One entry per row of the all-in table over a raise.  It is the engine's own test (equity
    against the opening range, times how much of it the hand realises out of position, against
    the pot odds), without the hands that move all-in at 20bb."""
    out = {}
    for key, _label, r_nb in B.raisers(players):
        open_rng = villain_open_range(r_nb, "unknown", 20.0)
        raise_to, to_call = 2.0, 1.0
        pot = players * B.PLAYER_ANTE + 0.5 + 1.0 + raise_to
        need = to_call / (pot + to_call)
        shove = parse_range(B.reshove("before", key, 20.0, players))
        rng = [1.0 if eq_vs_range(h, open_rng)[0] * _REALIZE[_hand_kind(h)] >= need + 0.01 and shove[h] < 0.5 else 0.0
               for h in range(169)]
        out[key] = text(rng)
    return out


def cold(players: int) -> dict:
    """A raise and a re-raise before hero: {first raiser's group: [up to 24bb, 25 to 60bb, deeper]}."""
    out = {}
    for group, r_nb in raiser_groups(players):
        if group == "sb":
            continue
        three_nb = 2 if r_nb > 2 else 1
        row = []
        for stack in (20.0, 40.0, 100.0):
            res = ask(players, 0, stack, [(r_nb, "raise", 2.2), (three_nb, "raise", 6.6)])
            row.append(text(union(res.get("allin"), res.get("reraise"))))
        out[group] = row
    return out


# --------------------------------------------------------------------------
# 4. Hero raised first
# --------------------------------------------------------------------------

def reraised(players: int) -> dict:
    """Hero opened and was re-raised (not all-in): {hero's group: {allin, fourbet, call}}."""
    out = {}
    for group, h_nb in raiser_groups(players):
        open_to, three = (3.0, 9.0) if group == "sb" else (2.2, 8.4)
        acts = [(h_nb, "raise", open_to), (0, "raise", three)]
        short = ask(players, h_nb, 35.0, acts)
        deep = ask(players, h_nb, 70.0, acts)
        out[group] = {"allin": text(short.get("allin")), "fourbet": text(deep.get("reraise")), "call": text(deep.get("call"))}
    return out


def shoved_on(players: int) -> dict:
    """Hero opened and one player moved all-in: {hero's group: {normal: [per band], bubble: [...]}}.

    The player all-in is the big blind with the band's stack; hero has at least as much.  Hero
    calls with the hands of the opening range that beat the pot odds by the usual margin."""
    out = {}
    for group, h_nb in raiser_groups(players):
        rows = {"normal": [], "bubble": []}
        for _label, s in B.BANDS:
            stack = max(float(s), 30.0)
            open_to = open_size_bb(stack, h_nb)
            sp = spot(players, h_nb, stack, [], 0, {0: float(s)})
            hero_range = rfi_range(h_nb, min(stack, float(s)))
            sol = _shover_solution(sp, players - 1, sp.hero, open_to, hero_range)
            rng, _pct = _scaled_range(sol, "unknown")
            _need, chip = _call_numbers(sp, players - 1, {sp.hero: open_to, players - 1: float(s)})
            opened = rfi_range(h_nb, 100.0)
            eqs = [eq_vs_range(h, rng)[0] if opened[h] >= 0.5 else 0.0 for h in range(169)]
            for name, premium in (("normal", B.NORMAL_PREMIUM), ("bubble", B.BUBBLE_PREMIUM)):
                rows[name].append(text([1.0 if eqs[h] >= chip + premium else 0.0 for h in range(169)]) or "nothing")
        out[group] = rows
    return out


# --------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    data = {"version": T.DATA_VERSION, "tables": {}}
    for players in T.TABLES:
        b = B.table(players)
        data["tables"][str(players)] = {
            "first_in": first_in(players),
            "limpers": limpers(players),
            "vs_raise": vs_raise(players),
            "reshove": {k: v[:4] for k, v in b["reshove"]["before"].items()},
            "bb_call": bb_call_short(players),
            "cold": cold(players),
            "reraised": reraised(players),
            "shoved_on": shoved_on(players),
            "call": b["call"],
        }
        print(f"{players} players done ({time.time() - t0:.0f}s)", flush=True)
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {os.path.normpath(OUT)} ({os.path.getsize(OUT) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
