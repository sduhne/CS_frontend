"""Build the tables of the quick guide (guide/data.js).

The quick guide is a page that answers a spot before the flop at once: seat, stack, cards, what happened.
It computes nothing: every answer is looked up in tables made here, by asking the engine
(``poker_coach.preflop.advise``, on chips) about each of the 169 hands of every spot.

    python3 tools/build_guide.py                 # everything, about an hour on four processors
    python3 tools/build_guide.py --quick         # a small set (three stacks, one opponent type), a few minutes
    python3 tools/build_guide.py --only open,vsraise --jobs 4

What a table is: 169 characters, one per hand in the order of ``poker_coach.cards.HANDS``; each character is
an action and how sure it is (``CODES``); in the data file a run of four or more equal characters is written
as the character and the count (``pack``).  Tables that turn out equal are stored once.  The page finds a table
by family and by a list of numbers (style, opponents, seats, stack); ``FAMILIES`` below is the one place that
says what those numbers are, and the page reads the same description from the data file.

Seats are named by the players still to act behind them, at a table of nine: 8 is the first to act, 2 the
button, 1 the small blind, 0 the big blind.  A smaller table has the last seats of that row, so one set of
tables serves every table size from three to nine; two players are a family of their own ("hu").
The big blind pays an ante of one big blind for the table.  Stacks are equal (the effective stack).
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

from poker_coach import preflop as P                      # noqa: E402
from poker_coach import ranges as R                       # noqa: E402
from poker_coach.cards import HANDS, format_range, parse_range, range_pct   # noqa: E402

VERSION = 1
STYLES = ("win", "tag")                 # the page's "Play to win" and "Tight"
OPPONENTS = ("unknown", "tight", "loose")
STACKS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 22, 25, 28, 30, 35, 40, 50, 60, 80, 100)
SHORT = tuple(s for s in STACKS if s <= 40)               # an all-in in front: bigger ones are read at 40
DEEP = tuple(s for s in STACKS if s >= 12)                # a re-raise that is not all-in needs chips behind
MULTI = (4, 6, 8, 10, 12, 15, 20, 25, 30, 40)             # three players all-in: priced with dealt-out boards (slow)
SEATS = ("UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB")      # index i has 8 - i players behind
N = 9

# One character per hand: the action, and whether the engine calls it close.
ACTIONS = ("FOLD", "CHECK", "CALL", "LIMP", "RAISE", "RAISE_CALL", "RERAISE", "RERAISE_BLUFF", "ALLIN", "ISOLATE", "ISOLATE_ALLIN")
CODES = "fxclrRtbaiI"                   # lower-case letters; the same letter in upper case... is another action, so:
CLOSE = "FXCLQWTBAJK"                   # the same eleven actions when the answer is close


def seat(nb: int) -> str:
    return SEATS[8 - nb]


def open_size(stack: float, nb: int) -> float:
    return R.open_size_bb(stack, nb, True)


def code_of(adv) -> str:
    """The engine's answer as one character."""
    a = adv.action.upper()
    if a.startswith("FOLD"):
        k = 0
    elif a.startswith("CHECK"):
        k = 1
    elif a.startswith("CALL (LIMP"):
        k = 3
    elif a.startswith("CALL"):
        k = 2
    elif a.startswith("RE-RAISE ALL-IN"):
        k = 10
    elif a.startswith("RE-RAISE TO"):
        k = 9
    elif a.startswith("ALL-IN") or "PUTS THE OPENER ALL-IN" in a:
        k = 8
    elif a.startswith("RAISE") and "CALL ANY ALL-IN" in a:
        k = 5
    elif a.startswith("RAISE"):
        k = 4
    elif (a.startswith("3-BET") or a.startswith("4-BET")) and "BLUFF" in a:
        k = 7
    elif a.startswith("3-BET") or a.startswith("4-BET"):
        k = 6
    else:
        raise ValueError(f"an action the guide has no letter for: {adv.action!r}")
    return (CLOSE if adv.confidence == "close" else CODES)[k]


def pack(letters: str) -> str:
    """169 letters with the runs counted: "fff" stays, "ffff" becomes "f4".  The page undoes it."""
    out, i = [], 0
    while i < len(letters):
        j = i
        while j < len(letters) and letters[j] == letters[i]:
            j += 1
        out.append(letters[i] * (j - i) if j - i < 4 else f"{letters[i]}{j - i}")
        i = j
    return "".join(out)


def unpack(packed: str) -> str:
    import re
    return "".join(ch * int(count or 1) for ch, count in re.findall(r"([A-Za-z])(\d*)", packed))


# ---- one spot -> one table --------------------------------------------------------------------------

_memo: dict = {}


def _key(value):
    if isinstance(value, (list, tuple)):
        return tuple(_key(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _key(v)) for k, v in value.items()))
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return id(value)                    # the hand's setup and prize objects: one object for all 169 hands of a spot


def _memoized(name):
    """The solver's answers do not depend on hero's cards: one solve serves the 169 hands of a spot."""
    plain = getattr(P, name)

    def wrapped(*args, **kw):
        key = (name, _key(args), _key(kw))
        if key not in _memo:
            _memo[key] = plain(*args, **kw)
        return _memo[key]

    setattr(P, name, wrapped)


for _name in ("solve_open_shove", "solve_reshove", "build_shove_spot", "_shover_solution"):
    _memoized(_name)
_plain_solve_shove = P.solve_shove


def _solve_shove(v_fold, v_steal, callers, **kw):
    key = ("solve_shove", id(v_fold), id(v_steal), id(callers), _key(kw))
    if key not in _memo:
        _memo[key] = _plain_solve_shove(v_fold, v_steal, callers, **kw)
    return _memo[key]


P.solve_shove = _solve_shove


def table(hero_nb: int, stack: float, facing: str, opp: str, players: int = N, hero_seat: str | None = None) -> dict:
    """Ask the engine about every hand of one spot.  -> {"a": 169 letters, and what the page shows beside them}."""
    _memo.clear()
    P._COLD_MEMO.clear()
    name = hero_seat or seat(hero_nb)
    spot = P.quick_spot(0, None, float(stack), players, name, facing)
    spot.types = [opp] * players
    letters, sizes, first = [], set(), None
    for h in range(169):
        adv = P.advise(dataclasses.replace(spot, hand=h))
        letters.append(code_of(adv))
        if first is None:
            first = adv
        for word in adv.action.replace("(", " ").split():
            if word.endswith("bb") and word[:-2].replace(".", "", 1).isdigit():
                sizes.add((adv.action.split()[0].upper(), float(word[:-2])))
    out = {"a": "".join(letters)}
    by_kind = {}
    for kind, size in sorted(sizes):
        by_kind.setdefault(kind, size)
    if by_kind:
        out["z"] = by_kind              # the size of a raise or a re-raise, in big blinds
    facts = P_facts(first)
    if facts:
        out["f"] = facts
    return out


def P_facts(adv) -> dict:
    """What does not depend on hero's cards: the range hero is up against and the price of a call."""
    import re
    text = " | ".join(adv.numbers)
    facts = {}
    found = re.search(r"(?:their range|their opening range|their 3-bet range|3-bettor's range) ~(\d+(?:\.\d+)?)%(?: \[([^\]]*)\])?", text)
    if found:
        facts["vp"] = float(found.group(1))
        if found.group(2):
            facts["vr"] = found.group(2)
    if "need" in adv.data and "equity" in adv.data:
        facts["need"] = round(adv.data["need"], 3)
    found = re.search(r"pot odds(?: to call)? (\d+)%", text)
    if found and "need" not in facts:
        facts["odds"] = int(found.group(1)) / 100
    return facts


# ---- the families -------------------------------------------------------------------------------------
# name -> (what the numbers of a key mean, the keys, a function that makes the engine's question from a key)

def fam_open():
    for nb in range(8, 0, -1):
        for s in STACKS:
            yield (nb, s), dict(hero_nb=nb, stack=s, facing="")


def fam_limp():
    # limpers sit in the seats just before hero; hero in the big blind with one limper: the small blind ("limp_sb")
    for nb in range(7, -1, -1):
        for count in (1, 2, 3):
            first = nb + count if nb > 0 else 1 + count      # big blind: the limpers are before the small blind
            seats = [nb + k for k in range(count, 0, -1)] if nb > 0 else [1 + k for k in range(count, 0, -1)]
            if max(seats) > 8:
                continue
            del first
            for s in STACKS:
                yield (nb, count, s), dict(hero_nb=nb, stack=s, facing=", ".join(f"{seat(x)} limp" for x in seats))


def fam_limp_sb():
    for s in STACKS:
        yield (s,), dict(hero_nb=0, stack=s, facing="SB limp")


def fam_vsraise():
    for o in range(8, 0, -1):
        for h in range(o - 1, -1, -1):
            for callers in (0, 1, 2):
                if o - h - 1 < callers:
                    continue
                for s in STACKS:
                    if callers and s <= 5:      # a raise and a call this short are two all-ins: the page reads "two_allin"
                        continue
                    size = open_size(s, o)
                    acts = [f"{seat(o)} raise {size}bb"] + [f"{seat(o - k)} call" for k in range(1, callers + 1)]
                    yield (o, h, callers, s), dict(hero_nb=h, stack=s, facing=", ".join(acts))


def fam_raise3():
    # a raise and a re-raise in front; the re-raiser is the next seat, hero the big blind (hero's seat changes little)
    for o in range(8, 1, -1):
        for s in STACKS:
            if s < 6:
                continue
            size = open_size(s, o)
            yield (o, s), dict(hero_nb=0, stack=s, facing=f"{seat(o)} raise {size}bb, {seat(o - 1)} raise {round(3 * size, 1)}bb")


def fam_re3():
    # hero raised first and was re-raised, not all-in: by a player behind who is not a blind (2), the small blind (1), the big blind (0)
    for h in range(8, 0, -1):
        for who in (2, 1, 0):
            if who == 2:
                if h < 3:
                    continue
                villain, times = h - 1, 3.0
            else:
                if h <= who:
                    continue
                villain, times = who, 3.8
            for s in DEEP:
                size = open_size(s, h)
                yield (h, who, s), dict(hero_nb=h, stack=s,
                                        facing=f"hero raise {size}bb, {seat(villain)} raise {round(times * size, 1)}bb")


def fam_re_allin():
    # hero raised first and a player behind moved all-in
    for h in range(8, 0, -1):
        for v in range(h - 1, -1, -1):
            for s in STACKS:
                if s < 4:
                    continue
                yield (h, v, s), dict(hero_nb=h, stack=s, facing=f"hero raise {open_size(s, h)}bb, {seat(v)} allin")


def fam_allin():
    for o in range(8, 0, -1):
        for h in range(o - 1, -1, -1):
            for s in SHORT:
                yield (o, h, s), dict(hero_nb=h, stack=s, facing=f"{seat(o)} allin")


def fam_raise_allin():
    # a raise, then an all-in by the next player; hero is the big blind
    for o in (8, 5, 3, 2):
        for s in MULTI:
            yield (o, s), dict(hero_nb=0, stack=s, facing=f"{seat(o)} raise {open_size(s, o)}bb, {seat(o - 1)} allin")


def fam_two_allin():
    for o in (8, 5, 3, 2):
        for s in MULTI:
            yield (o, s), dict(hero_nb=0, stack=s, facing=f"{seat(o)} allin, {seat(o - 1)} allin")


def fam_re3_allin():
    # hero raised, one player re-raised and another moved all-in
    for h in (8, 5, 3, 2):
        for s in MULTI:
            if s < 10:
                continue
            size = open_size(s, h)
            yield (h, s), dict(hero_nb=h, stack=s,
                               facing=f"hero raise {size}bb, {seat(1)} raise {round(3.8 * size, 1)}bb, {seat(0)} allin")


def fam_sq_allin():
    # a raise, hero re-raised, the raiser moved all-in
    for o in range(8, 0, -1):
        for h in range(o - 1, -1, -1):
            for s in DEEP:
                size = open_size(s, o)
                times = 3.0 if h >= 2 else 3.8
                yield (o, h, s), dict(hero_nb=h, stack=s,
                                      facing=f"{seat(o)} raise {size}bb, hero raise {round(times * size, 1)}bb, {seat(o)} allin")


def fam_hu(kind):
    def make():
        for s in STACKS:
            if kind == "open":
                yield (s,), dict(hero_nb=1, stack=s, facing="", players=2, hero_seat="SB")
            elif kind == "vsraise":
                yield (s,), dict(hero_nb=0, stack=s, facing=f"SB raise {2.0 if s < 25 else 2.2}bb", players=2, hero_seat="BB")
            elif kind == "limp":
                yield (s,), dict(hero_nb=0, stack=s, facing="SB limp", players=2, hero_seat="BB")
            elif kind == "allin":
                yield (s,), dict(hero_nb=0, stack=s, facing="SB allin", players=2, hero_seat="BB")
            elif kind == "re_allin" and s >= 4:
                yield (s,), dict(hero_nb=1, stack=s, facing=f"hero raise {2.0 if s < 25 else 2.2}bb, BB allin", players=2, hero_seat="SB")
            elif kind == "re3" and s >= 12:
                size = 2.0 if s < 25 else 2.2
                yield (s,), dict(hero_nb=1, stack=s, facing=f"hero raise {size}bb, BB raise {round(3.8 * size, 1)}bb", players=2, hero_seat="SB")
    return make


FAMILIES = {
    "open": ("you are first in: [players behind you, stack]", fam_open),
    "limp": ("players only called: [players behind you, callers, stack]", fam_limp),
    "limp_sb": ("big blind, the small blind only called: [stack]", fam_limp_sb),
    "vsraise": ("a raise before you: [players behind the raiser, behind you, callers, stack]", fam_vsraise),
    "raise3": ("a raise and a re-raise before you: [players behind the first raiser, stack]", fam_raise3),
    "re3": ("you raised and were re-raised: [players behind you, by whom (2 a seat behind, 1 small blind, 0 big blind), stack]", fam_re3),
    "re_allin": ("you raised and a player moved all-in: [players behind you, behind that player, stack]", fam_re_allin),
    "allin": ("an all-in before you: [players behind that player, behind you, stack]", fam_allin),
    "raise_allin": ("a raise and an all-in before you: [players behind the raiser, stack]", fam_raise_allin),
    "two_allin": ("two all-ins before you: [players behind the first, stack]", fam_two_allin),
    "re3_allin": ("you raised, a re-raise and an all-in followed: [players behind you, stack]", fam_re3_allin),
    "sq_allin": ("a raise, you re-raised, the raiser moved all-in: [players behind the raiser, behind you, stack]", fam_sq_allin),
    "hu_open": ("two players, you are the small blind and act first: [stack]", fam_hu("open")),
    "hu_vsraise": ("two players, the small blind raised: [stack]", fam_hu("vsraise")),
    "hu_limp": ("two players, the small blind only called: [stack]", fam_hu("limp")),
    "hu_allin": ("two players, the small blind moved all-in: [stack]", fam_hu("allin")),
    "hu_re_allin": ("two players, you raised and the big blind moved all-in: [stack]", fam_hu("re_allin")),
    "hu_re3": ("two players, you raised and the big blind re-raised: [stack]", fam_hu("re3")),
}
# Families whose answers do not change with the style (no opening row and no bar of the style is in them)
SAME_IN_EVERY_STYLE = {"allin", "raise_allin", "two_allin", "hu_allin"}


def work(job):
    style, opp, family, quick = job
    R.set_style(style)
    rows = []
    started = time.time()
    for key, question in FAMILIES[family][1]():
        if quick and key[-1] not in (10, 20, 40):
            continue
        rows.append((key, table(opp=opp, **question)))
    return style, opp, family, rows, time.time() - started


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true", help="three stacks and one opponent type only")
    ap.add_argument("--only", help="families, comma separated")
    ap.add_argument("--styles", help="compute these styles only, comma separated (to redo part of the cache)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(ROOT, "guide", "data.js"))
    ap.add_argument("--cache", default=os.path.join(ROOT, "guide", ".cache"), help="finished jobs are kept here")
    ap.add_argument("--assemble-only", action="store_true", help="write the data file from the jobs that are finished")
    a = ap.parse_args()
    families = [f for f in FAMILIES if not a.only or f in a.only.split(",")]
    opponents = OPPONENTS[:1] if a.quick else OPPONENTS
    jobs = []
    for family in families:
        for opp in opponents:
            for style in STYLES:
                if family in SAME_IN_EVERY_STYLE and style != STYLES[0]:
                    continue
                jobs.append((style, opp, family, a.quick))
    os.makedirs(a.cache, exist_ok=True)

    def cache_path(job):
        style, opp, family, quick = job
        return os.path.join(a.cache, f"{family}.{opp}.{style}.{'quick' if quick else 'full'}.v{VERSION}.json")

    todo = [job for job in jobs if not os.path.exists(cache_path(job))]
    if a.styles:
        todo = [job for job in todo if job[0] in a.styles.split(",")]
        jobs = [job for job in jobs if job[0] in a.styles.split(",") or os.path.exists(cache_path(job))]
    print(f"{len(jobs)} jobs, {len(todo)} to compute", flush=True)
    started = time.time()
    if a.assemble_only:
        jobs = [job for job in jobs if os.path.exists(cache_path(job))]
        todo = []
    if todo:
        with Pool(a.jobs) as pool:
            for style, opp, family, rows, seconds in pool.imap_unordered(work, sorted(todo, key=lambda j: -len(list(FAMILIES[j[2]][1]())))):
                with open(cache_path((style, opp, family, a.quick)), "w") as fh:
                    json.dump([[list(key), tab] for key, tab in rows], fh)
                print(f"  {family:12s} {opp:8s} {style:4s} {len(rows):5d} tables {seconds:7.1f}s   ({time.time() - started:6.0f}s)", flush=True)

    # assemble: equal tables are stored once, and so are the ranges hero is up against
    unique, index, data, ranges, range_index = [], {}, {}, [], {}
    for job in jobs:
        style, opp, family, quick = job
        with open(cache_path(job)) as fh:
            rows = json.load(fh)
        for key, tab in rows:
            tab["a"] = pack(tab["a"])
            facts = tab.get("f") or {}
            if family in ("vsraise", "hu_vsraise") and "vp" in facts and "vr" not in facts:
                # the engine prints the size of the raiser's range, not the hands: ask for them the way it does
                R.set_style(style)
                rng = R.villain_open_range(key[0] if family == "vsraise" else 1, opp, float(key[-1]))
                if abs(range_pct(rng) - facts["vp"]) <= 0.6:
                    facts["vr"] = format_range(rng)
            if "vr" in facts:               # as 169 marks: the page works hero's equity out of it
                marks = "".join("1" if w >= 0.5 else "0" for w in parse_range(facts.pop("vr")))
                if marks not in range_index:
                    range_index[marks] = len(ranges)
                    ranges.append(marks)
                facts["v"] = range_index[marks]
            text = json.dumps(tab, sort_keys=True)
            if text not in index:
                index[text] = len(unique)
                unique.append(tab)
            styles = STYLES if family in SAME_IN_EVERY_STYLE else (style,)
            for st in styles:
                data.setdefault(family, {}).setdefault(st, {}).setdefault(opp, {})[",".join(str(k) for k in key)] = index[text]
    # hand against hand, for the page's "you have 47% against their range": equity in 1/250, and how many
    # pairs of holdings the two classes can form at once (the engine's own card-removal weights)
    from poker_coach.equity import matrix
    m = matrix()
    eq = base64.b64encode(bytes(min(250, max(0, round(250 * e))) for row in m.eq for e in row)).decode()
    pairs = base64.b64encode(bytes(min(255, c) for row in m.n for c in row)).decode()
    doc = {"version": VERSION, "hands": list(HANDS), "codes": CODES, "close": CLOSE, "actions": list(ACTIONS),
           "styles": list(STYLES), "opponents": list(opponents), "stacks": list(STACKS), "seats": list(SEATS),
           "families": {name: FAMILIES[name][0] for name in families}, "tables": unique, "index": data,
           "ranges": ranges, "eq": eq, "pairs": pairs, "quick": bool(a.quick), "partial": bool(a.assemble_only)}
    with open(a.out, "w") as fh:
        fh.write("/* Made by tools/build_guide.py: do not edit. */\nwindow.GUIDE_DATA = ")
        json.dump(doc, fh, separators=(",", ":"))
        fh.write(";\n")
    with open(os.path.splitext(a.out)[0] + ".json", "w") as fh:        # the same, for a page that fetches it
        json.dump(doc, fh, separators=(",", ":"))
    cells = sum(len(v) for fam in data.values() for st in fam.values() for v in st.values())
    print(f"{cells} spots, {len(unique)} different tables, {os.path.getsize(a.out) / 1e6:.2f} MB -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
