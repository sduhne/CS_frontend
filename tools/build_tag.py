#!/usr/bin/env python3
"""Build poker_coach/data/tag.json: every preflop situation of a tight-aggressive tournament
player, as text, for tables of 6, 7 and 8 players.

    python3 tools/build_tag.py            # about a minute and a half

The answers are the coach's own.  For each situation the engine (poker_coach.preflop.advise)
is asked what it does with each of the 169 hands, far from the money and on chips, and the
hands are grouped by the action it gives.  All-in decisions are not asked again: they are the
all-in or fold tournament tables (poker_coach.binary), which are built to reach the money and
are tighter than a chip-EV chart.  See poker_coach/tag.py for the layout of the data.

One stack for every list (``tag.ASKED``).  A row whose lists come from one question at one
stack cannot have a hole: every hand the engine plays there is on exactly one of them
(``place`` stops the build when the engine gives an action no list takes).  The first version
asked the re-raises with 30bb and the big blind's calls with 60bb, and KQs, which calls at one
depth and re-raises at the other, was on neither list.
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
from poker_coach.preflop import (Act, Spot, _call_numbers, _hand_kind, _scaled_range,   # noqa: E402
                                 _shover_solution, advise, bb_call_points)
from poker_coach.pushfold import HandSetup                                    # noqa: E402
from poker_coach.ranges import open_size_bb, rfi_range, villain_open_range    # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poker_coach", "data", "tag.json")

# The hands the engine is asked about.  All of them for the build; the sheet's test narrows it to a sample,
# so that it can go through every cell with this file's own code in seconds.
HANDS_ASKED: list[int] = list(range(169))


def setup(players: int, stack: float, stacks: dict[int, float] | None = None) -> HandSetup:
    """Equal stacks (``stacks`` overrides seats by players behind).  The ante is an eighth of a big blind
    for each player, posted by the big blind for the table: with 60bb the big blind plays 59bb at 8 players."""
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
    for h in HANDS_ASKED:
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


def both(a, b) -> list[float]:
    b = b or [0.0] * 169
    return [1.0 if x >= 0.5 and y >= 0.5 else 0.0 for x, y in zip(a or [0.0] * 169, b)]


def place(res: dict, lists: dict[str, tuple[str, ...]], where) -> dict[str, list[float]]:
    """The engine's answers at one stack as the lists of a row: {list: range}.

    ``lists`` names the actions each list takes.  Folding (and the big blind's free check) is on
    no list.  Any other action the engine gave stops the build: left out silently it would be a
    hole in the row, a hand the engine plays that the sheet folds."""
    taken = {action for actions in lists.values() for action in actions}
    stray = sorted(set(res) - taken - {"fold", "check"})
    if stray:
        raise RuntimeError(f"{where}: no list of the row takes the engine's {', '.join(stray)} "
                           f"({', '.join(text(res[k]) for k in stray)})")
    return {name: union(*(res.get(action) for action in actions)) for name, actions in lists.items()}


# --------------------------------------------------------------------------
# 1. Nobody has entered
# --------------------------------------------------------------------------

def first_in(players: int) -> dict:
    """The opening chart the engine raises from, at the two stacks of ``tag.ASKED`` (the test asks the engine
    itself there: a question costs two solved all-ins for every hand that raises, too slow for the build)."""
    deep, short = T.ASKED["first_in"]
    out = {}
    for nb in T.seats(players):
        out[str(nb)] = {
            "raise": [text(rfi_range(nb, deep)), text(rfi_range(nb, short))],
            "size": [f"{open_size_bb(100.0, nb):g}", f"{open_size_bb(30.0, nb):g}", f"{open_size_bb(20.0, nb):g}"],
            "allin": [text(B.first_in_range("before", nb, s, players)) for s in T.SHORT_STACKS],
        }
    return out


# --------------------------------------------------------------------------
# 2. Players only called
# --------------------------------------------------------------------------

def limpers(players: int) -> dict:
    """Hero in every seat that can have callers in front, with one, two and three of them.

    ``raise`` and ``call`` are one question with 40bb, ``mid`` one with 20bb (``tag.ASKED``)."""
    deep_stack, mid_stack = T.ASKED["limpers"]
    out = {}
    for nb in list(T.seats(players))[1:] + [0]:
        row = {"raise": [], "call": [], "mid": [], "allin": None}
        for k in (1, 2, 3):
            if nb + k > players - 1:
                break
            acts = [(nb + j, "limp", 1.0) for j in range(k, 0, -1)]
            where = (players, "limpers", nb, k)
            deep = place(ask(players, nb, deep_stack, acts), {"raise": ("raise", "allin"), "call": ("limp",)}, where)
            mid = place(ask(players, nb, mid_stack, acts), {"raise": ("raise", "allin")}, where + ("17 to 24bb",))
            row["raise"].append(text(deep["raise"]))
            row["call"].append(text(deep["call"]))
            row["mid"].append(text(mid["raise"]))
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


def group_seats(players: int, group: str) -> list[int]:
    """Every seat of a raiser group at this table, as players behind."""
    return {"early": list(range(players - 1, 5, -1)), "middle": [5, 4], "late": [3, 2], "sb": [1]}[group]


def raise_size(group: str, r_nb: int, stack: float) -> float:
    """The raise hero faces: the engine's own opening size for that seat and stack."""
    return open_size_bb(stack, 1 if group == "sb" else r_nb)


RAISE_LISTS = {"value": ("reraise", "allin"), "bluff": ("bluff",), "call": ("call",)}


def vs_raise(players: int) -> dict:
    """25bb or more: re-raise, call or fold, by where the raise came from and where hero sits.

    Every row is ONE question, with ``tag.ASKED["vs_raise"]`` big blinds (60): the hands the engine re-raises
    for value there (``value``), re-raises as a bluff (``bluff``) and calls.  So each hand it plays is on
    exactly one list and none it folds is on any.  The calls are then split by the stack they start at, and
    that split cannot lose or double a hand either: ``call`` holds the calls the engine already makes with 30bb,
    ``setmine`` those it makes with 40bb but not with 30bb (the small pairs: 15 times the raise behind), and
    ``button`` the rest (suited connectors from 50bb, on the button or after a caller).  Only a later seat has
    the last two; a blind's row with a hand in them stops the build.

    ``seats``: the same question for the other seats of the raiser's group.  The re-raises are the same for
    the whole group; the big blind's calls go by the price against that seat's range, so they can differ:
    ``more`` are calls against that seat only, ``less`` calls of the row that fold against it.

    With 26 to 45bb the engine plays some of the ``value`` hands another way (all-in, or a call) and folds the
    bluffs: the sheet says so in words under the rows, and the test checks the words."""
    stack = T.ASKED["vs_raise"]
    low_stack, mid_stack = T.CALL_FROM
    out = {}
    for group, r_nb in raiser_groups(players):
        heroes = [("bb", 0)] if group == "sb" else [("ip", 2), ("sb", 1), ("bb", 0)]
        for where, h_nb in heroes:
            key = f"{group}|{where}"

            def asked(depth: float, raiser: int = r_nb) -> dict:
                return ask(players, h_nb, depth, [(raiser, "raise", raise_size(group, raiser, depth))])

            deep = place(asked(stack), RAISE_LISTS, (players, key))
            low, mid = asked(low_stack), asked(mid_stack)
            core = both(deep["call"], low.get("call"))
            setmine = both(minus(deep["call"], core), mid.get("call"))
            button = minus(minus(deep["call"], core), setmine)
            row = {"value": text(deep["value"]), "bluff": text(deep["bluff"]), "call": text(core)}
            if where == "ip":
                row["setmine"], row["button"] = text(setmine), text(button)
            elif text(setmine) or text(button):
                raise RuntimeError(f"{players} {key}: calls that start deeper than {low_stack:g}bb "
                                   f"({text(union(setmine, button))}) have no list in a blind's row")
            row["seats"] = {}
            for other in group_seats(players, group):
                if other == r_nb or other <= h_nb:
                    continue
                there = place(asked(stack, other), RAISE_LISTS, (players, key, other))
                if there["value"] != deep["value"] or there["bluff"] != deep["bluff"]:
                    raise RuntimeError(f"{players} {key}: the re-raises differ against seat {other} of the group")
                row["seats"][str(other)] = {"more": text(minus(there["call"], deep["call"])),
                                            "less": text(minus(deep["call"], there["call"]))}
            out[key] = row
    return out


def bb_call_short(players: int) -> dict:
    """Big blind, 9 to 24bb, a raise to 2bb: the hands that get the price to call.

    One entry per row of the all-in table over a raise.  It is the engine's own test
    (``preflop.vs_open``: equity against the opening range, against the pot odds plus the points
    for the kind of hand, ``preflop.bb_call_points``), on chips, without the hands that move
    all-in at 20bb."""
    out = {}
    for key, _label, r_nb in B.raisers(players):
        open_rng = villain_open_range(r_nb, "unknown", 20.0)
        raise_to, to_call = 2.0, 1.0
        pot = players * B.PLAYER_ANTE + 0.5 + 1.0 + raise_to
        need = to_call / (pot + to_call)
        shove = parse_range(B.reshove("before", key, 20.0, players))
        acts_last = r_nb == 1 and players > 2           # a small blind's raise: the big blind acts last after the flop
        rng = [1.0 if eq_vs_range(h, open_rng)[0] - need - bb_call_points(_hand_kind(h), 0.0, 0, acts_last) >= 0
               and shove[h] < 0.5 else 0.0 for h in range(169)]
        out[key] = text(rng)
    return out


def cold(players: int) -> dict:
    """A raise and a re-raise before hero: {first raiser's group: [up to 24bb, 25 to 60bb, deeper]}.

    One question for each cell, with 20, 40 and 100bb (``tag.ASKED``), hero in the big blind: the engine moves
    all-in, re-raises small (more than 60bb) or folds, so one list holds every hand it plays."""
    out = {}
    for group, r_nb in raiser_groups(players):
        if group == "sb":
            continue
        three_nb = 2 if r_nb > 2 else 1
        row = []
        for stack in T.ASKED["cold"]:
            res = ask(players, 0, stack, [(r_nb, "raise", 2.2), (three_nb, "raise", 6.6)])
            row.append(text(place(res, {"play": ("allin", "reraise")}, (players, "cold", group, stack))["play"]))
        out[group] = row
    return out


# --------------------------------------------------------------------------
# 4. Hero raised first
# --------------------------------------------------------------------------

def reraised(players: int) -> dict:
    """Hero opened and was re-raised (not all-in): {hero's group: {allin, call_short, fourbet, call}}.

    The engine is asked with the big blind as the player who re-raised.  So hero acts last after
    the flop ("in position") in every row but the small blind's, where he acts first; against a
    re-raise from a seat behind him other than the blinds, hero is out of position and the engine
    calls less than the "call" lists (deeper than 45bb) say.

    Two questions for each row, with 35 and 70bb (``tag.ASKED``): with 35bb the engine moves all-in,
    calls (``call_short``: a hand too far ahead of the price to fold, whose all-in does not earn
    enough) or folds; with 70bb it re-raises, calls or folds."""
    out = {}
    for group, h_nb in raiser_groups(players):
        open_to, three = (3.0, 9.0) if group == "sb" else (2.2, 8.4)
        acts = [(h_nb, "raise", open_to), (0, "raise", three)]
        short_stack, deep_stack = T.ASKED["reraised"]
        short = place(ask(players, h_nb, short_stack, acts), {"allin": ("allin",), "call_short": ("call",)},
                      (players, "reraised", group, short_stack))
        deep = place(ask(players, h_nb, deep_stack, acts), {"fourbet": ("reraise",), "call": ("call",)},
                     (players, "reraised", group, deep_stack))
        out[group] = {"allin": text(short["allin"]), "call_short": text(short["call_short"]),
                      "fourbet": text(deep["fourbet"]), "call": text(deep["call"])}
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
