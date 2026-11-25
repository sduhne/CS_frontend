#!/usr/bin/env python3
"""Build guide/spin.js: the quick guide's tables for spins (three players, one prize, no ante).

    python3 tools/build_spin_guide.py                 # every table, about 45 minutes on four processors
    python3 tools/build_spin_guide.py --quick         # a few stacks and one opponent type, for testing
    python3 tools/build_spin_guide.py --only s_open,s_allin

The page's Spin choice reads these tables the way it reads the tournament ones (tools/build_guide.py): each is
the engine's answer (``preflop.advise``, on chips) for the 169 hands of one spot.  The spot is a spin: three
players (or two, heads-up), a small blind of half a big blind, no ante, and the stacks the user enters.

Stacks.  Of three stacks only two numbers matter: the chips the biggest has over the second biggest never
change hands, so the biggest is cut down to the second (``spin_exact.reduce``).  A configuration is then two
players with ``X`` big blinds and one with ``Y`` (no more than ``X``) in one of the three seats, or three equal
stacks; heads-up, one number, the smaller stack.  The configurations are those the exact solution was solved
at (tools/build_spin_exact.py), so the all-ins and the calls of all-ins are its numbers, not a line between
two of them.  In the keys a configuration is one token: "10" (all three 10bb), "10_3_0" (two at 10bb, the big
blind at 3bb; the last number is the short seat's players behind: 2 the button, 1 the small blind, 0 the big
blind), and heads-up "h10".

Seats are numbers of players behind, as in the tournament tables: three players 2 the button, 1 the small
blind, 0 the big blind; heads-up 1 the small blind (the button), 0 the big blind.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import json
import os
import sys
import time
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_guide as B                                    # noqa: E402
from poker_coach import preflop as P                      # noqa: E402
from poker_coach import ranges as R                       # noqa: E402
from poker_coach import spin_exact as SX                  # noqa: E402
from poker_coach.cards import COMBO_COUNT, HANDS, format_range, parse_range, range_pct   # noqa: E402

VERSION = 1
OUT = os.path.join(ROOT, "guide", "spin.js")
CACHE = os.path.join(ROOT, "guide", ".spincache")
RAISES = (2.0, 2.5, 3.0, 4.0)               # a raise before you, in big blinds (the page lets the user pick)
RERAISE_TIMES = (2.5, 3.0, 4.0, 5.0)        # a re-raise of your raise, as a multiple of your raise
DEEP = 10.0                                 # re-raises that are not all-in are asked about from this many big blinds
NAMES3 = {2: "BTN", 1: "SB", 0: "BB"}
NAMES2 = {1: "SB", 0: "BB"}
QUICK_X = (4.0, 10.0, 20.0)                 # --quick: these X only, and their equal stacks and a short big blind
STYLES = ("win",)                           # one prize: chips are money, so the page plays to win (the Tight style is
                                            # the tournament's, built to survive until a prize)
FAMILY_VERSION = {}                         # a family whose questions changed gets a new number: its jobs are asked again


# ---- the configurations ----------------------------------------------------------------------------------

def configs3(quick: bool = False):
    """(token, stacks by players behind {2: button, 1: small blind, 0: big blind}, X)."""
    xs, ys = SX.x_grid(), SX.y_grid()
    if not xs:
        raise SystemExit("poker_coach/data/spin_exact.json is missing: python3 tools/build_spin_exact.py --work DIR")
    for x in xs:
        if quick and x not in QUICK_X:
            continue
        yield f"{x:g}", {2: x, 1: x, 0: x}, x
        for y in ys:
            if y >= x or (quick and y not in (1.0, 3.0)):
                continue
            for short in (2, 1, 0):
                if quick and short != 0:
                    continue
                st = {2: x, 1: x, 0: x}
                st[short] = y
                yield f"{x:g}_{y:g}_{short}", st, x


def configs2(quick: bool = False):
    for e in SX.hu_grid():
        if quick and e not in QUICK_X:
            continue
        yield f"h{e:g}", {1: e, 0: e}, e


def engine_stacks(st: dict, players: int) -> list[float]:
    """Stacks by players behind -> the engine's order (first to act first)."""
    return [st[nb] for nb in range(players - 1, -1, -1)]


def own_raise(nb: int, st: dict, players: int) -> float:
    """The size of your own raise first in, as the engine makes it (``first_in``)."""
    behind = [st[j] for j in range(nb)]
    eff = min(st[nb], max(behind))
    if players == 2:
        return 2.0 if eff < 25 else 2.2
    return R.open_size_bb(eff, nb, False)


# ---- the families ------------------------------------------------------------------------------------------

POSTED = {2: 0.0, 1: 0.5, 0: 1.0}           # what each seat of three has in before the cards (heads-up: 1 the small blind)


def behind(nb: int, st: dict, players: int = 3) -> float:
    """Chips a seat still has after its blind: a player with none is all-in already and cannot raise, call
    or move in (a big blind of 1bb is all-in from posting it)."""
    posted = POSTED[nb] if players == 3 else (0.5 if nb == 1 else 1.0)
    return st[nb] - posted

def q(hero: int, st: dict, facing: str, players: int = 3) -> dict:
    names = NAMES3 if players == 3 else NAMES2
    return dict(hero=names[hero], stacks=engine_stacks(st, players), facing=facing, players=players)


def fam_open(quick):
    for tok, st, _x in configs3(quick):
        for h in (2, 1):
            yield (h, tok), q(h, st, "")


def fam_limp(quick):
    # [you, who called, configuration]: the small blind behind a button that called (1); the big blind behind
    # the small blind only (0), the button only, the small blind folding (1), or both (2)
    for tok, st, _x in configs3(quick):
        # a limp leaves the player chips behind: with a big blind or less it would be an all-in
        if st[2] > 1.0:
            yield (1, 1, tok), q(1, st, "BTN limp")
            yield (0, 1, tok), q(0, st, "BTN limp")
            if st[1] > 1.0:
                yield (0, 2, tok), q(0, st, "BTN limp, SB limp")
        if st[1] > 1.0:
            yield (0, 0, tok), q(0, st, "SB limp")


def fam_raise(quick):
    # [raiser, you, callers, size, configuration]
    for tok, st, _x in configs3(quick):
        for zi, size in enumerate(RAISES):
            if size < st[2]:
                yield (2, 1, 0, zi, tok), q(1, st, f"BTN raise {size}bb")
                yield (2, 0, 0, zi, tok), q(0, st, f"BTN raise {size}bb")
                if size < min(st[1], st[2]):
                    yield (2, 0, 1, zi, tok), q(0, st, f"BTN raise {size}bb, SB call")
            if size < st[1]:
                yield (1, 0, 0, zi, tok), q(0, st, f"SB raise {size}bb")


def fam_allin(quick):
    # [all-in from, you, configuration]
    for tok, st, _x in configs3(quick):
        yield (2, 1, tok), q(1, st, "BTN allin")
        yield (2, 0, tok), q(0, st, "BTN allin")
        if behind(1, st) > 0:
            yield (1, 0, tok), q(0, st, "SB allin")


def fam_two(quick):
    # the big blind, the button all-in and the small blind all-in too: [configuration]
    for tok, st, _x in configs3(quick):
        if behind(1, st) > 0:
            yield (tok,), q(0, st, "BTN allin, SB allin")


def fam_raise_allin(quick):
    # the big blind, the button raised its usual size and the small blind moved all-in: [configuration]
    for tok, st, _x in configs3(quick):
        size = own_raise(2, st, 3)
        if size < st[2] and behind(1, st) > 0:
            yield (tok,), q(0, st, f"BTN raise {size:g}bb, SB allin")


def fam_raise3(quick):
    # the big blind, the button raised, the small blind re-raised three times it: [configuration]
    for tok, st, x in configs3(quick):
        size = own_raise(2, st, 3)
        if x >= DEEP and 3 * size < min(st[1], st[2]):
            yield (tok,), q(0, st, f"BTN raise {size:g}bb, SB raise {round(3 * size, 1):g}bb")


def fam_re3(quick):
    # you raised and were re-raised, not all-in: [you, by whom, size (place in RERAISE_TIMES), configuration]
    for tok, st, x in configs3(quick):
        if x < DEEP:
            continue
        for h, by in ((2, 1), (2, 0), (1, 0)):
            mine = own_raise(h, st, 3)
            for zi, times in enumerate(RERAISE_TIMES):
                to = round(times * mine, 1)
                if to < min(st[h], st[by]):
                    yield (h, by, zi, tok), q(h, st, f"hero raise {mine:g}bb, {NAMES3[by]} raise {to:g}bb")


def fam_re_allin(quick):
    # you raised and a player behind moved all-in: [you, who, configuration]
    for tok, st, _x in configs3(quick):
        for h, by in ((2, 1), (2, 0), (1, 0)):
            mine = own_raise(h, st, 3)
            if mine < st[h] and behind(by, st) > 0:
                yield (h, by, tok), q(h, st, f"hero raise {mine:g}bb, {NAMES3[by]} allin")


def fam_re3_allin(quick):
    # you raised from the button, the small blind re-raised, the big blind moved all-in: [configuration]
    for tok, st, x in configs3(quick):
        mine = own_raise(2, st, 3)
        if x >= DEEP and 3.8 * mine < min(st[1], st[2]):
            yield (tok,), q(2, st, f"hero raise {mine:g}bb, SB raise {round(3.8 * mine, 1):g}bb, BB allin")


def fam_sq_allin(quick):
    # a raise, you re-raised, the raiser moved all-in: [raiser, you, configuration]
    for tok, st, _x in configs3(quick):
        for o, h in ((2, 1), (2, 0), (1, 0)):
            size = own_raise(o, st, 3)
            to = round((3.0 if h == 1 else 3.8) * size, 1)
            if to < min(st[h], st[o]):
                yield (o, h, tok), q(h, st, f"{NAMES3[o]} raise {size:g}bb, hero raise {to:g}bb, {NAMES3[o]} allin")


def fam_hu(kind):
    def make(quick):
        for tok, st, e in configs2(quick):
            mine = own_raise(1, st, 2)
            if kind == "open":
                yield (tok,), q(1, st, "", 2)
            elif kind == "limp":
                if e > 1.0:
                    yield (tok,), q(0, st, "SB limp", 2)
            elif kind == "raise":
                for zi, size in enumerate(RAISES):
                    if size < e:
                        yield (zi, tok), q(0, st, f"SB raise {size}bb", 2)
            elif kind == "allin":
                yield (tok,), q(0, st, "SB allin", 2)
            elif kind == "re3":
                for zi, times in enumerate(RERAISE_TIMES):
                    to = round(times * mine, 1)
                    if e >= DEEP and to < e:
                        yield (zi, tok), q(1, st, f"hero raise {mine:g}bb, BB raise {to:g}bb", 2)
            elif kind == "re_allin":
                if mine < e and e > 1.0:
                    yield (tok,), q(1, st, f"hero raise {mine:g}bb, BB allin", 2)
            elif kind == "sq_allin":
                to = round(3.0 * mine, 1)
                if to < e:
                    yield (tok,), q(0, st, f"SB raise {mine:g}bb, hero raise {to:g}bb, SB allin", 2)
    return make


FAMILIES = {
    "s_open": ("first in: [you, configuration]", fam_open),
    "s_limp": ("a limp before you: [you, who called (0 the small blind only, 1 the button, 2 both), configuration]", fam_limp),
    "s_raise": ("a raise before you: [raiser, you, callers, size (place in sizes.raise), configuration]", fam_raise),
    "s_allin": ("an all-in before you: [all-in from, you, configuration]", fam_allin),
    "s_two": ("the big blind, two all-ins: [configuration]", fam_two),
    "s_raise_allin": ("the big blind, a raise and an all-in: [configuration]", fam_raise_allin),
    "s_raise3": ("the big blind, a raise and a re-raise: [configuration]", fam_raise3),
    "s_re3": ("you raised and were re-raised: [you, by whom, size (place in sizes.reraise), configuration]", fam_re3),
    "s_re_allin": ("you raised and a player moved all-in: [you, who, configuration]", fam_re_allin),
    "s_re3_allin": ("you raised from the button, a re-raise and an all-in: [configuration]", fam_re3_allin),
    "s_sq_allin": ("a raise, you re-raised, the raiser moved all-in: [raiser, you, configuration]", fam_sq_allin),
    "s_hu_open": ("heads-up, you are the small blind: [configuration]", fam_hu("open")),
    "s_hu_limp": ("heads-up, the small blind only called: [configuration]", fam_hu("limp")),
    "s_hu_raise": ("heads-up, the small blind raised: [size (place in sizes.raise), configuration]", fam_hu("raise")),
    "s_hu_allin": ("heads-up, the small blind moved all-in: [configuration]", fam_hu("allin")),
    "s_hu_re3": ("heads-up, you raised and were re-raised: [size (place in sizes.reraise), configuration]", fam_hu("re3")),
    "s_hu_re_allin": ("heads-up, you raised and the big blind moved all-in: [configuration]", fam_hu("re_allin")),
    "s_hu_sq_allin": ("heads-up, you re-raised and the small blind moved all-in: [configuration]", fam_hu("sq_allin")),
}
# Families whose answers do not change with the style: only all-ins are in front, and those ranges are solved.
SAME_IN_EVERY_STYLE = {"s_allin", "s_two", "s_hu_allin"}


# ---- one table -------------------------------------------------------------------------------------------

def table(hero: str, stacks: list[float], facing: str, opp: str, players: int) -> dict:
    """Ask the engine about every hand of one spot.  -> {"a": 169 letters, and what the page shows beside them}."""
    hero_idx = P.pos_to_index(hero, players)
    spot = P.quick_spot(0, None, stacks[hero_idx], players, hero, facing, ante=False, stacks=stacks)
    spot.types = [opp] * players
    letters, sizes, first, through, bb = [], set(), None, [], None
    with B.one_solve_per_spot():
        for h in range(169):
            adv = P.advise(dataclasses.replace(spot, hand=h))
            letters.append(B.code_of(adv))
            if first is None:
                first = adv
            if "fold_equity" in adv.data:
                through.append((COMBO_COUNT[h], adv.data["fold_equity"]))
            if bb is None and "bb_realised" in adv.data:
                bb = adv.data
            for word in adv.action.replace("(", " ").split():
                if word.endswith("bb") and word[:-2].replace(".", "", 1).isdigit():
                    sizes.add((adv.action.split()[0].upper(), float(word[:-2])))
    out = {"a": "".join(B.pairs_in_order(letters))}
    by_kind = {}
    for kind, size in sorted(sizes):
        by_kind.setdefault(kind, size)
    if by_kind:
        out["z"] = by_kind
    facts = B.P_facts(first)
    if len(through) == 169:
        facts["fe"] = round(sum(c * fe for c, fe in through) / 1326.0, 3)
    if bb is not None and not facts.get("x"):
        facts.update(bb_facts(bb, hero_idx, stacks, facing, opp, players, facts.get("vp")))
    if facts:
        out["f"] = facts
    return out


def bb_facts(bb: dict, hero_idx: int, stacks: list[float], facing: str, opp: str, players: int, vp) -> dict:
    """The big blind's call of a raise, as the engine tested it (``vs_open``): the page shows what the hand
    needed, need = (price + margin) / share.  {"p": the price, "m": the style's margin (the page shrinks it
    with callers in the pot), "ip": 1 when the big blind acts last, "vr": the raiser's hands, "cv": the
    callers' hands (169 marks each)}."""
    words = facing.split(", ")
    opener = P.pos_to_index(words[0].split()[0], players)
    o_nb = players - 1 - opener
    callers = [w.split()[0] for w in words[1:] if w.split()[1] == "call"]
    out = {"p": round(bb["bb_call_need"] * bb["bb_realised"] - bb["bb_over"], 4),   # = the call / the pot after it
           "m": P._BB_MARGIN[R.style()]}
    if o_nb == 1 and not callers and players > 2:
        out["ip"] = 1
    eff = min(stacks[hero_idx], stacks[opener])
    rng = R.villain_open_range(o_nb, opp, eff, heads_up=players == 2)
    if vp is not None and abs(range_pct(rng) - vp) <= 0.6:
        out["vr"] = format_range(rng)
    if callers:
        out["cv"] = ["".join("1" if w >= 0.5 else "0" for w in P.flat_range(o_nb, players - 1 - P.pos_to_index(c, players)))
                     for c in callers]
    return out


# ---- the jobs ----------------------------------------------------------------------------------------------

def spots_of(family: str, quick: bool):
    return FAMILIES[family][1](quick)


def work(job):
    style, opp, family, quick = job
    R.set_style(style)
    started = time.time()
    rows = [(key, table(opp=opp, **question)) for key, question in spots_of(family, quick)]
    return job, rows, time.time() - started


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", help="families, comma separated")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--cache", default=CACHE)
    a = ap.parse_args()
    families = [f for f in FAMILIES if not a.only or f in a.only.split(",")]
    opponents = B.OPPONENTS[:1] if a.quick else B.OPPONENTS
    jobs = [(style, opp, fam, a.quick) for fam in families for opp in opponents for style in STYLES
            if not (fam in SAME_IN_EVERY_STYLE and style != STYLES[0])]
    os.makedirs(a.cache, exist_ok=True)

    def cache_path(job):
        style, opp, fam, quick = job
        return os.path.join(a.cache, f"{fam}.{opp}.{style}.{'quick' if quick else 'full'}.v{FAMILY_VERSION.get(fam, 1)}.json")

    todo = [job for job in jobs if not os.path.exists(cache_path(job))]
    print(f"{len(jobs)} jobs, {len(todo)} to compute", flush=True)
    started = time.time()
    if todo:
        size = {job: sum(1 for _ in spots_of(job[2], job[3])) for job in todo}
        with Pool(a.jobs) as pool:
            for job, rows, seconds in pool.imap_unordered(work, sorted(todo, key=lambda j: -size[j])):
                with open(cache_path(job), "w") as fh:
                    json.dump([[list(key), tab] for key, tab in rows], fh)
                print(f"  {job[2]:14s} {job[1]:8s} {job[0]:5s} {len(rows):6d} tables {seconds:7.1f}s   ({time.time() - started:6.0f}s)", flush=True)

    unique, index, data, ranges, range_index = [], {}, {}, [], {}

    def marks_id(marks: str) -> int:
        if marks not in range_index:
            range_index[marks] = len(ranges)
            ranges.append(marks)
        return range_index[marks]

    for job in jobs:
        style, opp, fam, quick = job
        with open(cache_path(job)) as fh:
            rows = json.load(fh)
        asked = {tuple(key) for key, _ in spots_of(fam, quick)}
        for key, tab in rows:
            if tuple(key) not in asked:
                continue
            tab["a"] = B.pack("".join(B.pairs_in_order(tab["a"])))
            facts = tab.get("f") or {}
            if "vr" in facts:               # as 169 marks: the page works hero's equity out of it
                facts["v"] = marks_id("".join("1" if w >= 0.5 else "0" for w in parse_range(facts.pop("vr"))))
            if facts.get("cv") and isinstance(facts["cv"][0], str):
                facts["cv"] = [marks_id(marks) for marks in facts["cv"]]
            text = json.dumps(tab, sort_keys=True)
            if text not in index:
                index[text] = len(unique)
                unique.append(tab)
            for st in (STYLES if fam in SAME_IN_EVERY_STYLE else (style,)):
                data.setdefault(fam, {}).setdefault(st, {}).setdefault(opp, {})[",".join(str(k) for k in key)] = index[text]
    doc = {"version": VERSION, "kind": "spin", "hands": list(HANDS), "codes": B.CODES, "close": B.CLOSE,
           "actions": list(B.ACTIONS), "styles": list(STYLES), "opponents": list(opponents),
           "x": list(SX.x_grid()), "y": list(SX.y_grid()), "hu": list(SX.hu_grid()), "deep": DEEP,
           "families": {name: FAMILIES[name][0] for name in families}, "tables": unique, "index": data, "ranges": ranges,
           "sizes": {"raise": list(RAISES), "reraise": list(RERAISE_TIMES)},
           "quick": bool(a.quick)}
    with open(a.out, "w") as fh:
        fh.write("/* Made by tools/build_spin_guide.py: do not edit. */\nwindow.SPIN_DATA = ")
        json.dump(doc, fh, separators=(",", ":"))
        fh.write(";\n")
    with open(os.path.splitext(a.out)[0] + ".json", "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    cells = sum(len(v) for fam in data.values() for st in fam.values() for v in st.values())
    print(f"{cells} spots, {len(unique)} different tables, {os.path.getsize(a.out) / 1e6:.2f} MB -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
