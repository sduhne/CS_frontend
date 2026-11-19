"""All-in or fold for a whole tournament.

One decision per hand: move all-in, or fold.  The tables answer the three
situations that covers:

* nobody has raised: the deepest stack at which each hand is an all-in, by
  seat (``limit``);
* one player has raised: the hands that move all-in over the raise, by the
  raiser's seat and hero's stack (``reshove``);
* one player is all-in: the hands that call, by that player's seat and the
  size of the all-in (``call``).

There are two stages.  ``before`` the money, the ranges are the plan that
earns the most prize money for a late entry in the tournament model of
``latereg`` (policy ``ev``): blinds to pay until the bubble, a stack worth a
little less than twice as much when it doubles, and opponents who call as
they usually do.  In the ``money`` they are the ICM solver's ranges for the
real pay ladder, again against opponents who call on chips alone.  Both are
far tighter than a chip-EV push/fold chart: the weak half of such a chart
earns almost nothing, and a few points of survival value remove it.

The tables exist for 6, 7 and 8 players (``TABLES``).  A seat is the number
of players still to act behind it, so the names shift with the table: the
first to act is UTG at 8 and 7 players and LJ at 6.  With fewer players the
blinds come round sooner and there is less ante money in the pot, which is
why the ranges are solved again for each size instead of reusing a row.

``tools/build_binary.py`` writes ``data/binary.json``; everything here reads
that file.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from .cards import COMBO_COUNT, HAND_INDEX, HANDS, format_range, parse_range

_PATH = os.path.join(os.path.dirname(__file__), "data", "binary.json")
DATA_VERSION = 3

PLAYERS = 8                                          # the default table
TABLES = (6, 7, 8)                                   # table sizes the tables are solved for
STACKS = tuple(range(2, 26)) + (28, 30, 35, 40)      # big blinds the first-in ranges are solved at
TOP = STACKS[-1]                                     # deeper than this only the two fixed ranges apply
STAGES = ("before", "money")
STAGE_NAMES = {"before": "before the money", "money": "in the money"}
PLAYER_ANTE = 0.125                                  # GGPoker: every player antes an eighth of a big blind

# the tournament the "before the money" plan is solved for: a fresh stack at the
# close of late registration in an ordinary GGPoker turbo
ENTRY = {"stack_bb": 11.0, "entrants": 1000, "alive": 0.45, "paid": 0.15, "speed": "turbo", "fee": 0.08}
# the "in the money" ladder: the same tournament with 60 players left of 150 paid
MONEY_LEFT = 60

# stack bands of the printed tables: (label, stack the column is solved at)
BANDS = (("up to 7bb", 6.0), ("8 to 11bb", 10.0), ("12 to 16bb", 15.0), ("17 to 24bb", 20.0), ("25 to 40bb", 30.0))
NORMAL_PREMIUM = 0.06        # extra equity a call needs away from the bubble (3-4 points before the money, 6-8 in it)
BUBBLE_PREMIUM = 0.16        # ... and on the bubble or at a final table against a stack that covers hero
SAFETY_PER_BB = 0.02         # in the money a first-in all-in must earn this much per big blind of stack over 10:
                             # thin edges are not worth a deep stack (it removes, e.g., a 40bb all-in with A4s)
TWO_ALLINS = (5, 3)          # two all-ins in front are solved for these seats (players behind), hero on the button
TWO_LABEL = "Two all-ins, or a raise and an all-in"
DEEP_FIRST_IN = "AA, KK"     # deeper than TOP, nobody raised
DEEP_OVER_RAISE = "AA, KK"   # deeper than TOP, moving all-in over a raise (calls of an all-in keep the deepest row)


# --------------------------------------------------------------------------
# Seats
# --------------------------------------------------------------------------

def seat_name(n_behind: int, players: int = PLAYERS) -> str:
    """Seat label from the number of players still to act behind it (0 = big blind)."""
    fixed = {0: "BB", 1: "SB", 2: "BTN", 3: "CO", 4: "HJ", 5: "LJ"}
    if n_behind in fixed and n_behind < players:
        return fixed[n_behind]
    early = players - 1 - n_behind        # 0 = first to act
    return "UTG" if early <= 0 else f"UTG+{early}"


def seats(players: int = PLAYERS) -> dict[int, str]:
    """Every seat that can act first, from the first to act down to the small blind: {players behind: name}."""
    return {nb: seat_name(nb, players) for nb in range(players - 1, 0, -1)}


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def raisers(players: int = PLAYERS) -> tuple:
    """Rows of the raise table: (key, label, the seat the row is solved for as players behind)."""
    early = [seat_name(nb, players) for nb in range(players - 1, 4, -1)]
    return (("early", _join(early), min(6, players - 1)), ("late", "HJ or CO", 3),
            ("steal", "BTN or SB (you are in the blinds)", 2))


def shovers(players: int = PLAYERS) -> tuple:
    """Rows of the all-in tables: (key, label, the seat the row is solved for)."""
    early = [seat_name(nb, players) for nb in range(players - 1, 4, -1)]
    return (("early", _join(early), min(6, players - 1)), ("late", "HJ or CO", 3), ("button", "BTN", 2),
            ("small", "SB (you are the big blind)", 1))


SEATS = seats(PLAYERS)
RAISERS = raisers(PLAYERS)
SHOVERS = shovers(PLAYERS)


def raiser_kind(n_behind: int) -> str:
    return "early" if n_behind >= 5 else "late" if n_behind >= 3 else "steal"


def shover_kind(n_behind: int) -> str:
    return "early" if n_behind >= 5 else "late" if n_behind >= 3 else "button" if n_behind == 2 else "small"


# --------------------------------------------------------------------------
# The tables
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def data() -> dict:
    with open(_PATH) as fh:
        d = json.load(fh)
    if d.get("version") != DATA_VERSION:
        raise RuntimeError("data/binary.json is out of date: run python3 tools/build_binary.py")
    return d


def table(players: int = PLAYERS) -> dict:
    """Everything solved for one table size: ``first_in``, ``reshove``, ``call`` and ``entry_result``."""
    if players not in TABLES:
        raise ValueError(f"the all-in or fold tables exist for {_join([str(t) for t in TABLES])} players, not {players}")
    return data()["tables"][str(players)]


def limits(stage: str, n_behind: int, players: int = PLAYERS) -> list[int]:
    """Deepest stack (bb) at which each of the 169 hands is a first-in all-in; 0 = never."""
    return table(players)["first_in"][_stage(stage)][str(_seat(n_behind, players))]


def limit(stage: str, n_behind: int, hand: int | str, players: int = PLAYERS) -> int:
    h = HAND_INDEX[hand] if isinstance(hand, str) else hand
    return limits(stage, n_behind, players)[h]


def first_in_range(stage: str, n_behind: int, stack_bb: float, players: int = PLAYERS) -> list[float]:
    """The first-in all-in range (weights 0 or 1) for a seat and a stack."""
    if stack_bb > TOP:
        return parse_range(DEEP_FIRST_IN)
    need = max(1.0, stack_bb - 0.5)
    return [1.0 if lim >= need else 0.0 for lim in limits(stage, n_behind, players)]


def range_groups(rng: list[float]) -> tuple[str, str, str]:
    """A range as three strings: its pairs, its suited hands and its offsuit hands."""
    pairs = [w if h // 13 == h % 13 else 0.0 for h, w in enumerate(rng)]
    suited = [w if h // 13 < h % 13 else 0.0 for h, w in enumerate(rng)]
    offsuit = [w if h // 13 > h % 13 else 0.0 for h, w in enumerate(rng)]
    return format_range(pairs), format_range(suited), format_range(offsuit)


def first_in_rows(stage: str = "before", players: int = PLAYERS) -> dict[int, list[str]]:
    """The first-in all-in range of every seat for each stack band, as text (the printed table)."""
    return {nb: [format_range(first_in_range(stage, nb, s, players)) for _label, s in BANDS]
            for nb in seats(players)}


def band(stack_bb: float) -> int:
    """Index of the stack band of the printed tables (clamped to the deepest)."""
    tops = (7.5, 11.5, 16.5, 24.5)
    for i, top in enumerate(tops):
        if stack_bb <= top:
            return i
    return len(tops)


def reshove(stage: str, raiser: str, stack_bb: float, players: int = PLAYERS) -> str:
    """Hands that move all-in over one raise (``raiser``: early, late or steal)."""
    if stack_bb > TOP:
        return DEEP_OVER_RAISE
    return table(players)["reshove"][_stage(stage)][raiser][band(stack_bb)]


def call(shover: str, allin_bb: float, bubble: bool = False, big_blind: bool = False, players: int = PLAYERS) -> str:
    """Hands that call an all-in (``shover``: early, late, button or small; ``two`` when two
    players are all-in, or one raised and another moved all-in).

    ``allin_bb`` is what hero has to put in: the all-in, or hero's stack if
    smaller.  In the big blind the price is better, which is worth one stack
    band (the small-blind row already assumes hero is the big blind).

    An all-in of more than ``TOP`` big blinds is read from the deepest row
    (25 to 40bb): "aces and kings only" is the rule for moving all-in first
    with a stack that deep, and a call must not get tighter by one big blind
    of stack (at 41bb queens and ace-king would fold where A9o calls at 40).
    """
    i = band(allin_bb)
    if big_blind and shover != "small":
        i = max(0, i - 1)
    return table(players)["call"]["bubble" if bubble else "normal"][shover][i]


def _stage(stage: str) -> str:
    s = {"before": "before", "pre": "before", "bubble": "before", "money": "money", "itm": "money",
         "in": "money", "after": "money"}.get(str(stage).lower())
    if s is None:
        raise ValueError(f"stage must be 'before' or 'money', not {stage!r}")
    return s


def _seat(n_behind: int, players: int = PLAYERS) -> int:
    return max(1, min(players - 1, int(n_behind)))


def _in(text: str, hand: int) -> bool:
    return parse_range(text)[hand] >= 0.5


def decide(hand: int, n_behind: int, stack_bb: float, stage: str = "before", facing: str = "",
           facing_seat: int | None = None, allin_bb: float | None = None, bubble: bool = False,
           players: int = PLAYERS) -> tuple[str, str]:
    """(ALL-IN / CALL / FOLD / CHECK, the reason) from the printed tables.

    ``facing``: '' (nobody has raised), 'raise', 'allin' or 'allins' (two or more
    players all-in, or a raise and an all-in); ``facing_seat`` is that player's
    seat as players behind them (not needed for 'allins').
    """
    stage = _stage(stage)
    table(players)
    name = HANDS[hand]
    if not facing:
        if n_behind == 0:
            return "CHECK", "nobody raised: the big blind sees the flop for free (or takes the walk)"
        if stack_bb > TOP:
            ok = _in(DEEP_FIRST_IN, hand)
            return ("ALL-IN" if ok else "FOLD"), f"over {TOP}bb only {DEEP_FIRST_IN} move all-in first"
        lim = limit(stage, n_behind, hand, players)
        seat = seat_name(_seat(n_behind, players), players)
        if lim >= max(1.0, stack_bb - 0.5):
            return "ALL-IN", f"{name} from {seat} is an all-in up to {lim}bb {STAGE_NAMES[stage]}"
        if lim:
            return "FOLD", f"{name} from {seat} is an all-in only up to {lim}bb {STAGE_NAMES[stage]}"
        return "FOLD", f"{name} from {seat} is never an all-in {STAGE_NAMES[stage]}"
    if facing == "allins":
        size = min(stack_bb, allin_bb or stack_bb)
        rng = call("two", size, bubble, big_blind=(n_behind == 0), players=players)
        ok = _in(rng, hand)
        where = "on the bubble" if bubble else "away from the bubble"
        return ("CALL" if ok else "FOLD"), f"against two all-ins of {size:g}bb {where}: {rng}"
    if facing_seat is None:
        raise ValueError("facing a raise or an all-in needs that player's seat")
    them = seat_name(_seat(facing_seat, players), players)
    if facing == "raise":
        kind = raiser_kind(facing_seat)
        rng = reshove(stage, kind, stack_bb, players)
        label = BANDS[band(stack_bb)][0] if stack_bb <= TOP else f"over {TOP}bb"
        ok = _in(rng, hand)
        return ("ALL-IN" if ok else "FOLD"), f"over a raise from {them} with {label}: {rng}"
    size = min(stack_bb, allin_bb or stack_bb)
    kind = shover_kind(facing_seat)
    rng = call(kind, size, bubble, big_blind=(n_behind == 0), players=players)
    ok = _in(rng, hand)
    where = "on the bubble" if bubble else "away from the bubble"
    return ("CALL" if ok else "FOLD"), f"against an all-in of {size:g}bb from {them} {where}: {rng}"


# --------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------

def grid_text(stage: str, n_behind: int, players: int = PLAYERS) -> str:
    """The seat's first-in table: every hand by name with the deepest stack (bb) that moves all-in.

    The name says what the hand is: ``A5s`` suited, ``A5o`` offsuit, ``55`` a pair.  Pairs run down
    the diagonal, suited hands sit to their right and offsuit hands below them.
    """
    lim = limits(stage, n_behind, players)
    seat = seat_name(_seat(n_behind, players), players)
    lines = [f"{seat}, {STAGE_NAMES[_stage(stage)]}: each hand and the deepest stack (bb) that moves all-in",
             "  s = suited (right of the pairs), o = offsuit (below the pairs), . = fold"]
    for i in range(13):
        lines.append("  " + " ".join(f"{HANDS[i * 13 + j]:<3}{lim[i * 13 + j] or '.':>3}" for j in range(13)))
    return "\n".join(lines)


def width(stage: str, n_behind: int, stack_bb: float, players: int = PLAYERS) -> float:
    """Share of hands (percent) that move all-in first from a seat with a stack."""
    rng = first_in_range(stage, n_behind, stack_bb, players)
    return 100.0 * sum(c for c, w in zip(COMBO_COUNT, rng) if w >= 0.5) / 1326.0


def sheet_text(players: int = PLAYERS) -> str:
    d = table(players)
    names = seats(players)
    out = [f"ALL-IN OR FOLD, the whole tournament ({players}-handed)", ""]
    for stage in STAGES:
        out.append(f"Nobody has raised, {STAGE_NAMES[stage]}: share of hands that move all-in, by stack")
        out.append("  seat    " + " ".join(f"{s:>4}bb" for s in (6, 8, 10, 12, 15, 20, 25, 30, 40)))
        for nb, seat in names.items():
            out.append(f"  {seat:<6}  " + " ".join(f"{width(stage, nb, s, players):>5.0f}%" for s in (6, 8, 10, 12, 15, 20, 25, 30, 40)))
        out.append("")
        out.append(f"Nobody has raised, {STAGE_NAMES[stage]}: all-in with (s = suited, o = offsuit)")
        for nb, row in first_in_rows(stage, players).items():
            out.append(f"  {names[nb]}")
            for (b, _s), rng in zip(BANDS, row):
                out.append(f"    {b:<11} {rng}")
        out.append("")
    for stage in STAGES:
        out.append(f"One raise before you, {STAGE_NAMES[stage]}: all-in with")
        for key, label, _nb in raisers(players):
            out.append(f"  raise from {label}")
            for (b, _s), rng in zip(BANDS, d["reshove"][stage][key]):
                out.append(f"    {b:<11} {rng}")
        out.append("")
    for key, title in (("normal", "away from the bubble"), ("bubble", "on the bubble, or at a final table against a stack that covers you")):
        out.append(f"One all-in before you, {title}: call with")
        for skey, label, _nb in shovers(players):
            out.append(f"  all-in from {label}")
            for (b, _s), rng in zip(BANDS, d["call"][key][skey]):
                out.append(f"    {b:<11} {rng}")
        out.append(f"  {TWO_LABEL.lower()}")
        for (b, _s), rng in zip(BANDS, d["call"][key]["two"]):
            out.append(f"    {b:<11} {rng}")
        out.append("")
    out.append("In the big blind, read the all-in tables one stack band to the left (the small-blind row already does).")
    out.append(f"Over {TOP}bb: {DEEP_FIRST_IN} move all-in, first in or over a raise. "
               f"Calls of a bigger all-in are read from the {BANDS[-1][0]} column.")
    return "\n".join(out)
