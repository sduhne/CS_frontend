"""Build the tables of the quick guide (guide/data.js).

The quick guide is a page that answers a spot before the flop at once: seat, stack, cards, what happened.
It computes nothing: every answer is looked up in tables made here, by asking the engine
(``poker_coach.preflop.advise``, on chips) about each of the 169 hands of every spot.

    python3 tools/build_guide.py                 # everything, about 40 minutes on four processors
    python3 tools/build_guide.py --quick         # a small set (three stacks, one opponent type), a few minutes
    python3 tools/build_guide.py --only open,vsraise --jobs 4

What a table is: 169 characters, one per hand in the order of ``poker_coach.cards.HANDS``; each character is
an action and how sure it is (``CODES``); in the data file a run of four or more equal characters is written
as the character and the count (``pack``).  Tables that turn out equal are stored once.  The page finds a table
by family and by a list of numbers (style, opponents, seats, stack); ``FAMILIES`` below is the one place that
says what those numbers are, and the page reads the same description from the data file.

A raise before you comes in five sizes (``RAISE_SIZES``) and a re-raise of your raise in four
(``RERAISE_TIMES``): the size is one of the numbers of the key, and the page starts from the engine's own
size (``usual_sizes``).

Seats are named by the players still to act behind them, at a table of nine: 8 is the first to act, 2 the
button, 1 the small blind, 0 the big blind.  A smaller table has the last seats of that row, so one set of
tables serves every table size from three to nine; two players are a family of their own ("hu").
The big blind pays an ante of one big blind for the table.  Stacks are equal (the effective stack).
"""
from __future__ import annotations

import argparse
import base64
import contextlib
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
from poker_coach import short                             # noqa: E402
from poker_coach.cards import COMBO_COUNT, HANDS, format_range, parse_range, range_pct   # noqa: E402

VERSION = 3                             # of the data file: 2 added the size of a raise and of a re-raise; 3 the stacks of a few
                                        # big blinds from the exact solution, with a family of their own for two all-ins
# Finished jobs are kept by family and reused: a family whose questions changed gets a new number here,
# and only its jobs are asked again.
FAMILY_VERSION = {"vsraise": 2, "hu_vsraise": 2, "re3": 2, "hu_re3": 2}
RAISE_SIZES = (2.0, 2.2, 2.5, 3.0, 4.0)         # a raise before you, in big blinds: the page lets the user pick
RERAISE_TIMES = (2.5, 3.0, 4.0, 5.0)            # a re-raise of your raise, as a multiple of your raise
COMMITS = 0.4                                   # preflop.vs_open: a raise of this share of the raiser's stack is priced as an all-in
BUBBLE = 0.10                                   # the page's Bubble stage: a call of an all-in needs this much equity to spare
                                                # (guide.js, BUBBLE_POINTS; a test holds the two together)
PART = {"vsraise": 3}                           # a big family is asked in parts: one job for each value of this key number
STYLES = ("win", "tight")               # the page's "Play to win" and "Tight" (ranges.STYLES: both test the big blind's call
                                        # by what the hand realises; "tight" has the engine's default rows)
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


_table = N          # the table the family generators name their seats at (``sized`` below changes it for a moment)


def seat(nb: int) -> str:
    """The name of the seat with ``nb`` players behind; "?" for a seat the table does not have."""
    return R.position_name(nb, _table) if nb < _table else "?"


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


_SOLVERS = ("solve_open_shove", "solve_reshove", "build_shove_spot", "_shover_solution")
_plain_solve_shove = P.solve_shove


def _memoized(name):
    plain = getattr(P, name)

    def wrapped(*args, **kw):
        key = (name, _key(args), _key(kw))
        if key not in _memo:
            _memo[key] = plain(*args, **kw)
        return _memo[key]

    return wrapped


def _solve_shove(v_fold, v_steal, callers, **kw):
    key = ("solve_shove", id(v_fold), id(v_steal), id(callers), _key(kw))
    if key not in _memo:
        _memo[key] = _plain_solve_shove(v_fold, v_steal, callers, **kw)
    return _memo[key]


@contextlib.contextmanager
def one_solve_per_spot():
    """The solver's answers do not depend on hero's cards: inside this, one solve serves the 169 hands of a spot.

    The engine is given back as it was on the way out.  (Left in place, the kept answers would be handed to
    whatever asks the engine next: importing this file once made ten tests of other parts fail.)"""
    saved = {name: getattr(P, name) for name in _SOLVERS + ("solve_shove",)}
    _memo.clear()
    P._COLD_MEMO.clear()
    try:
        for name in _SOLVERS:
            setattr(P, name, _memoized(name))
        P.solve_shove = _solve_shove
        yield
    finally:
        for name, plain in saved.items():
            setattr(P, name, plain)
        _memo.clear()
        P._COLD_MEMO.clear()


def table(hero_nb: int, stack: float, facing: str, opp: str, players: int = N, hero_seat: str | None = None) -> dict:
    """Ask the engine about every hand of one spot.  -> {"a": 169 letters, and what the page shows beside them}."""
    name = hero_seat or seat(hero_nb)
    spot = P.quick_spot(0, None, float(stack), players, name, facing)
    spot.types = [opp] * players
    letters, sizes, first, through, spare = [], set(), None, [], []
    with one_solve_per_spot():
        for h in range(169):
            adv = P.advise(dataclasses.replace(spot, hand=h))
            letters.append(code_of(adv))
            if first is None:
                first = adv
            if "fold_equity" in adv.data:
                through.append((COMBO_COUNT[h], adv.data["fold_equity"]))
            if "exact_edge" in adv.data:
                spare.append(adv.data["exact_edge"] >= BUBBLE)
            for word in adv.action.replace("(", " ").split():
                if word.endswith("bb") and word[:-2].replace(".", "", 1).isdigit():
                    sizes.add((adv.action.split()[0].upper(), float(word[:-2])))
    out = {"a": "".join(pairs_in_order(letters))}
    by_kind = {}
    for kind, size in sorted(sizes):
        by_kind.setdefault(kind, size)
    if by_kind:
        out["z"] = by_kind              # the size of a raise or a re-raise, in big blinds
    facts = P_facts(first)
    if len(through) == 169:             # first in with a stack that can move all-in: how often everybody folds
        facts["fe"] = round(sum(c * fe for c, fe in through) / 1326.0, 3)
    if len(spare) == 169:
        # a call read from the exact solution has no one number for what it needs, so the page cannot add the
        # bubble's points to it: the table says hand by hand which calls have them to spare
        facts["bk"] = mask(pairs_with_spare(spare))
    if facts:
        out["f"] = facts
    return out


def mask(flags) -> str:
    """169 yes-or-no answers as base64 of 22 bytes: hand h is bit h % 8 of byte h // 8."""
    raw = bytearray(22)
    for h, yes in enumerate(flags):
        if yes:
            raw[h >> 3] |= 1 << (h & 7)
    return base64.b64encode(bytes(raw)).decode()


def unmask(text: str) -> list[bool]:
    raw = base64.b64decode(text)
    return [bool(raw[h >> 3] >> (h & 7) & 1) for h in range(169)]


def pairs_with_spare(flags) -> list[bool]:
    """``pairs_in_order`` for the bubble's mask: a pair has the points to spare where a lower pair has them."""
    out = list(flags)
    for i in range(11, -1, -1):
        if out[14 * (i + 1)]:
            out[14 * i] = True
    return out


def pairs_in_order(letters) -> list[str]:
    """A pair never folds where a lower pair plays: it takes the lower pair's play.

    Against a narrow all-in range two neighbouring pairs are worth the same, and the engine's equities carry
    a little noise, so now and then tens called where jacks folded (47 of 37,692 spots).  The answer is as
    good either way; a chart must not show it."""
    out = list(letters)
    for i in range(11, -1, -1):                 # kings against queens last: 14 * i is a pair, aces first
        if out[14 * i] in "fF" and out[14 * (i + 1)] not in "fF":
            out[14 * i] = out[14 * (i + 1)]
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
    if adv.data.get("exact"):
        # a stack of a few big blinds, read from the exact solution: what a call needs there is not one
        # number (it is the price and the players who can still call, hand by hand), so none is given
        facts["x"] = 1
        return facts
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


def own_table(size: float, stack: float, callers: int = 0) -> bool:
    """Does a raise of this size before the user get a table of its own at this stack?

    Not when it is the whole stack: that is an all-in, and the page reads the all-in table.  Not behind callers
    when it commits the raiser (COMMITS of the stack, which with 5bb or less is every raise): the engine prices
    that with dealt-out boards, 14 seconds a spot.  The page does not offer such a size there; with 5bb or
    less it reads a raise and a call as two all-ins."""
    if size >= stack:
        return False
    return not (callers and (stack <= 5 or size >= COMMITS * stack))


def fam_vsraise():
    for o in range(8, 0, -1):
        for h in range(o - 1, -1, -1):
            for callers in (0, 1, 2):
                if o - h - 1 < callers:
                    continue
                for zi, size in enumerate(RAISE_SIZES):
                    for s in STACKS:
                        if not own_table(size, s, callers):
                            continue
                        acts = [f"{seat(o)} raise {size}bb"] + [f"{seat(o - k)} call" for k in range(1, callers + 1)]
                        yield (o, h, callers, zi, s), dict(hero_nb=h, stack=s, facing=", ".join(acts))


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
                villain = h - 1
            else:
                if h <= who:
                    continue
                villain = who
            for zi, times in enumerate(RERAISE_TIMES):
                for s in DEEP:
                    size = open_size(s, h)
                    yield (h, who, zi, s), dict(hero_nb=h, stack=s,
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


def fam_two_short():
    """Two all-ins before you with a stack the exact game answers: there your own seat matters (the big
    blind has most of his stack in already, the button has nothing in and players behind), and the exact
    answers have every seat.  The second all-in is the seat after the first, as the page draws it."""
    for o in range(8, 1, -1):
        for h in range(o - 2, -1, -1):
            for s in STACKS:
                if s <= short.top():
                    yield (o, h, s), dict(hero_nb=h, stack=s, facing=f"{seat(o)} allin, {seat(o - 1)} allin")


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


def hu_open_size(stack: float) -> float:
    return 2.0 if stack < 25 else 2.2


def fam_hu(kind):
    def make():
        if kind == "vsraise":
            for zi, size in enumerate(RAISE_SIZES):
                for s in STACKS:
                    if own_table(size, s):
                        yield (zi, s), dict(hero_nb=0, stack=s, facing=f"SB raise {size}bb", players=2, hero_seat="BB")
            return
        if kind == "re3":
            for zi, times in enumerate(RERAISE_TIMES):
                for s in STACKS:
                    if s >= 12:
                        size = hu_open_size(s)
                        yield (zi, s), dict(hero_nb=1, stack=s, facing=f"hero raise {size}bb, BB raise {round(times * size, 1)}bb",
                                            players=2, hero_seat="SB")
            return
        for s in STACKS:
            if kind == "open":
                yield (s,), dict(hero_nb=1, stack=s, facing="", players=2, hero_seat="SB")
            elif kind == "limp":
                yield (s,), dict(hero_nb=0, stack=s, facing="SB limp", players=2, hero_seat="BB")
            elif kind == "allin":
                yield (s,), dict(hero_nb=0, stack=s, facing="SB allin", players=2, hero_seat="BB")
            elif kind == "re_allin" and s >= 4:
                yield (s,), dict(hero_nb=1, stack=s, facing=f"hero raise {hu_open_size(s)}bb, BB allin", players=2, hero_seat="SB")
    return make


def bb_price(family: str, key) -> dict:
    """The price of the big blind's call of a raise, exactly: {"p": share of the pot after the call, "ip": 1 if it acts last}."""
    if family == "hu_vsraise":
        size, callers, small_blind_in, last = RAISE_SIZES[key[0]], 0, True, False
    else:
        o, _h, callers, zi = key[:4]
        size = RAISE_SIZES[zi]
        small_blind_in = o == 1 or o - callers <= 1 <= o - 1         # the small blind raised, or is one of the callers
        last = o == 1 and callers == 0
    pot = 1.0 + (0.0 if small_blind_in else 0.5) + 1.0 + size * (1 + callers)     # the ante, the blinds, the raise and the calls
    out = {"p": round((size - 1.0) / (pot + size - 1.0), 4)}
    if last:
        out["ip"] = 1
    return out


def usual_sizes() -> dict:
    """The size the page starts from when the user has not picked one: the engine's own, as a place in the lists."""
    def nearest(value, options):
        return min(range(len(options)), key=lambda i: (abs(options[i] - value), i))
    return {
        # a raise before you, by stack: [from a seat that is not a blind, from the small blind, two players]
        "raise": {str(s): [nearest(open_size(s, 3), RAISE_SIZES), nearest(open_size(s, 1), RAISE_SIZES),
                           nearest(hu_open_size(s), RAISE_SIZES)] for s in STACKS},
        # your own raise, in big blinds, the same three: what a re-raise is a multiple of
        "open": {str(s): [open_size(s, 3), open_size(s, 1), hu_open_size(s)] for s in STACKS},
        # ... and the re-raises of it the tables were asked about, in big blinds: one list per kind of raise
        "reraise_to": {str(s): [[round(times * mine, 1) for times in RERAISE_TIMES]
                                for mine in (open_size(s, 3), open_size(s, 1), hu_open_size(s))] for s in STACKS},
        # a re-raise of your raise: from a seat behind you three times, from a blind four times
        "reraise": {"2": RERAISE_TIMES.index(3.0), "1": RERAISE_TIMES.index(4.0), "0": RERAISE_TIMES.index(4.0)},
    }


FAMILIES = {
    "open": ("you are first in: [players behind you, stack]", fam_open),
    "limp": ("players only called: [players behind you, callers, stack]", fam_limp),
    "limp_sb": ("big blind, the small blind only called: [stack]", fam_limp_sb),
    "vsraise": ("a raise before you: [players behind the raiser, behind you, callers, size (place in sizes.raise), stack]", fam_vsraise),
    "raise3": ("a raise and a re-raise before you: [players behind the first raiser, stack]", fam_raise3),
    "re3": ("you raised and were re-raised: [players behind you, by whom (2 a seat behind, 1 small blind, 0 big blind), size (place in sizes.reraise), stack]", fam_re3),
    "re_allin": ("you raised and a player moved all-in: [players behind you, behind that player, stack]", fam_re_allin),
    "allin": ("an all-in before you: [players behind that player, behind you, stack]", fam_allin),
    "raise_allin": ("a raise and an all-in before you: [players behind the raiser, stack]", fam_raise_allin),
    "two_allin": ("two all-ins before you: [players behind the first, stack]", fam_two_allin),
    "two_short": ("two all-ins before you, a stack solved exactly: [players behind the first, behind you, stack]", fam_two_short),
    "re3_allin": ("you raised, a re-raise and an all-in followed: [players behind you, stack]", fam_re3_allin),
    "sq_allin": ("a raise, you re-raised, the raiser moved all-in: [players behind the raiser, behind you, stack]", fam_sq_allin),
    "hu_open": ("two players, you are the small blind and act first: [stack]", fam_hu("open")),
    "hu_vsraise": ("two players, the small blind raised: [size (place in sizes.raise), stack]", fam_hu("vsraise")),
    "hu_limp": ("two players, the small blind only called: [stack]", fam_hu("limp")),
    "hu_allin": ("two players, the small blind moved all-in: [stack]", fam_hu("allin")),
    "hu_re_allin": ("two players, you raised and the big blind moved all-in: [stack]", fam_hu("re_allin")),
    "hu_re3": ("two players, you raised and the big blind re-raised: [size (place in sizes.reraise), stack]", fam_hu("re3")),
}
# Families whose answers do not change with the style: only all-ins are in front, and those ranges are
# solved, not read from an opening row.  (A raise and an all-in is not one of them: the all-in is priced
# against the raiser's row.  A test asks a sample of every family again in a style drawn at random.)
SAME_IN_EVERY_STYLE = {"allin", "two_allin", "two_short", "hu_allin"}

# Tables of three to six players have an exact solution of their own for the stacks ``short`` covers
# (the nine-player one counts the missing seats as players who folded, and what they folded is out of the
# deck: at six players the big blind then calls an all-in about ten points too tight).  Each family whose
# answers are read from that solution has a second set of tables, "name@players", for those stacks; the
# page reads it when the table is that size and falls back to the family itself everywhere else.
SMALL = tuple(n for n in short.games() if n < N)
SIZED = ("open", "limp", "limp_sb", "allin", "two_short", "vsraise")


def sized(name: str, players: int):
    """The spots of a family at a table of ``players``, for the stacks solved exactly."""
    def make():
        global _table
        _table = players
        try:
            spots = list(FAMILIES[name][1]())
        finally:
            _table = N
        for key, question in spots:
            if key[-1] > short.top() or question["hero_nb"] >= players or "?" in question["facing"]:
                continue
            # against a raise only one that commits the raiser is read from the exact game (as his all-in), and a
            # player who only called with a stack he is committed with.  (A raise that commits and an all-in are
            # two all-ins: the page reads that family.)
            if name == "vsraise" and (key[2] or RAISE_SIZES[key[3]] < COMMITS * key[4]):
                continue
            if name in ("limp", "limp_sb") and key[-1] > P._LIMP_COMMITS:
                continue
            yield key, dict(question, players=players, hero_seat=R.position_name(question["hero_nb"], players))
    return make


for _name in SIZED:
    for _n in SMALL:
        FAMILIES[f"{_name}@{_n}"] = (f"{FAMILIES[_name][0]}, at a table of {_n}", sized(_name, _n))
        if _name in SAME_IN_EVERY_STYLE:
            SAME_IN_EVERY_STYLE.add(f"{_name}@{_n}")


def spots_of(family: str, part, quick: bool = False):
    """The questions of one job: a family, or one part of a big family."""
    for key, question in FAMILIES[family][1]():
        if part is not None and key[PART[family]] != part:
            continue
        if quick and key[-1] not in (10, 20, 40):
            continue
        yield key, question


def parts_of(family: str):
    if family not in PART:
        return [None]
    return sorted({key[PART[family]] for key, _ in FAMILIES[family][1]()})


def work(job):
    style, opp, family, quick, part = job
    R.set_style(style)
    started = time.time()
    rows = [(key, table(opp=opp, **question)) for key, question in spots_of(family, part, quick)]
    return job, rows, time.time() - started


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
                for part in parts_of(family):
                    jobs.append((style, opp, family, a.quick, part))
    os.makedirs(a.cache, exist_ok=True)

    def cache_path(job):
        style, opp, family, quick, part = job
        name = family if part is None else f"{family}-{part}"
        # "tight" answers as the default style ("tag") does wherever the big blind's call test is not asked:
        # the jobs finished under that name are those answers
        kept_as = "tag" if style == "tight" and family not in FAMILY_VERSION else style
        return os.path.join(a.cache, f"{name}.{opp}.{kept_as}.{'quick' if quick else 'full'}.v{FAMILY_VERSION.get(family, 1)}.json")

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
        size = {job: sum(1 for _ in spots_of(job[2], job[4], job[3])) for job in todo}
        with Pool(a.jobs) as pool:
            for job, rows, seconds in pool.imap_unordered(work, sorted(todo, key=lambda j: -size[j])):
                style, opp, family, quick, part = job
                with open(cache_path(job), "w") as fh:
                    json.dump([[list(key), tab] for key, tab in rows], fh)
                name = family if part is None else f"{family}-{part}"
                print(f"  {name:12s} {opp:8s} {style:4s} {len(rows):5d} tables {seconds:7.1f}s   ({time.time() - started:6.0f}s)", flush=True)

    # assemble: equal tables are stored once, and so are the ranges hero is up against
    unique, index, data, ranges, range_index = [], {}, {}, [], {}
    def marks_id(marks: str) -> int:
        if marks not in range_index:
            range_index[marks] = len(ranges)
            ranges.append(marks)
        return range_index[marks]

    asked = {}
    for job in jobs:
        style, opp, family, quick, part = job
        with open(cache_path(job)) as fh:
            rows = json.load(fh)
        if (family, part, quick) not in asked:       # a finished job may hold spots the family no longer asks about
            asked[family, part, quick] = {key for key, _ in spots_of(family, part, quick)}
        for key, tab in rows:
            if tuple(key) not in asked[family, part, quick]:
                continue
            tab["a"] = pack("".join(pairs_in_order(tab["a"])))       # jobs finished before that rule keep raw answers
            facts = tab.get("f") or {}
            if family in ("vsraise", "hu_vsraise") and "vp" in facts and "vr" not in facts:
                # the engine prints the size of the raiser's range, not the hands: ask for them the way it does
                R.set_style(style)
                rng = R.villain_open_range(key[0] if family == "vsraise" else 1, opp, float(key[-1]),
                                           heads_up=family == "hu_vsraise")
                if abs(range_pct(rng) - facts["vp"]) <= 0.6:
                    facts["vr"] = format_range(rng)
            raised_to = RAISE_SIZES[key[3] if family == "vsraise" else key[0]] if family in ("vsraise", "hu_vsraise") else 0.0
            if family in ("vsraise", "hu_vsraise") and (family == "hu_vsraise" or key[1] == 0) and "vp" in facts \
                    and raised_to < COMMITS * key[-1]:
                # the big blind's call test (preflop.bb_realised): the page shows what the hand needed, so it is
                # given the exact price, the margin of the style, whether the big blind acts last, and the
                # hands of the players who called (their chips are in the price).  Not for a raise that commits
                # the raiser: that is priced as an all-in, and the page shows what a call of it needs.
                facts.update(bb_price(family, key))
                facts["m"] = P._BB_MARGIN[style]
                if family == "vsraise" and key[2]:
                    R.set_style(style)
                    facts["cv"] = [marks_id("".join("1" if w >= 0.5 else "0" for w in P.flat_range(key[0], key[0] - k)))
                                   for k in range(1, key[2] + 1)]
            if "vr" in facts:               # as 169 marks: the page works hero's equity out of it
                facts["v"] = marks_id("".join("1" if w >= 0.5 else "0" for w in parse_range(facts.pop("vr"))))
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
           "ranges": ranges, "eq": eq, "pairs": pairs, "quick": bool(a.quick), "partial": bool(a.assemble_only),
           "sizes": {"raise": list(RAISE_SIZES), "reraise": list(RERAISE_TIMES), "commit": COMMITS}, "usual": usual_sizes(),
           "short": {"top": short.top(), "tables": list(SMALL)}}      # stacks up to this are read from the exact solution;
                                                                      # tables of these sizes have "family@size" tables there
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
