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

``tools/build_binary.py`` writes ``data/binary.json``; everything here reads
that file.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from .cards import COMBO_COUNT, HAND_INDEX, HANDS, format_range

_PATH = os.path.join(os.path.dirname(__file__), "data", "binary.json")
DATA_VERSION = 1

PLAYERS = 8
STACKS = tuple(range(2, 26)) + (28, 30, 35, 40)      # big blinds the first-in ranges are solved at
TOP = STACKS[-1]                                     # deeper than this only the two fixed ranges apply
STAGES = ("before", "money")
STAGE_NAMES = {"before": "before the money", "money": "in the money"}
SEATS = {7: "UTG", 6: "UTG+1", 5: "LJ", 4: "HJ", 3: "CO", 2: "BTN", 1: "SB"}

# the tournament the "before the money" plan is solved for: a fresh stack at the
# close of late registration in an ordinary GGPoker turbo
ENTRY = {"stack_bb": 11.0, "entrants": 1000, "alive": 0.45, "paid": 0.15, "speed": "turbo", "fee": 0.08}
# the "in the money" ladder: the same tournament with 60 players left of 150 paid
MONEY_LEFT = 60

# stack bands of the two "someone acted first" tables: (label, stack the row is solved at)
BANDS = (("up to 7bb", 6.0), ("8 to 11bb", 10.0), ("12 to 16bb", 15.0), ("17 to 24bb", 20.0), ("25 to 40bb", 30.0))
RAISERS = (("early", "UTG, UTG+1 or LJ", 6), ("late", "HJ or CO", 3), ("steal", "BTN or SB (you are in the blinds)", 2))
SHOVERS = (("early", "UTG, UTG+1 or LJ", 6), ("late", "HJ or CO", 3), ("button", "BTN", 2), ("small", "SB (you are the big blind)", 1))
NORMAL_PREMIUM = 0.06        # extra equity a call needs away from the bubble (3-4 points before the money, 6-8 in it)
BUBBLE_PREMIUM = 0.16        # ... and on the bubble or at a final table against a stack that covers hero
SAFETY_PER_BB = 0.02         # in the money a first-in all-in must earn this much per big blind of stack over 10:
                             # thin edges are not worth a deep stack (it removes, e.g., a 40bb all-in with A4s)
DEEP_FIRST_IN = "AA, KK"     # deeper than TOP, nobody raised
DEEP_OVER_RAISE = "AA, KK"   # deeper than TOP, over a raise or an all-in


@lru_cache(maxsize=1)
def data() -> dict:
    with open(_PATH) as fh:
        d = json.load(fh)
    if d.get("version") != DATA_VERSION:
        raise RuntimeError("data/binary.json is out of date: run python3 tools/build_binary.py")
    return d


def limits(stage: str, n_behind: int) -> list[int]:
    """Deepest stack (bb) at which each of the 169 hands is a first-in all-in; 0 = never."""
    return data()["first_in"][_stage(stage)][str(_seat(n_behind))]


def limit(stage: str, n_behind: int, hand: int | str) -> int:
    h = HAND_INDEX[hand] if isinstance(hand, str) else hand
    return limits(stage, n_behind)[h]


def first_in_range(stage: str, n_behind: int, stack_bb: float) -> list[float]:
    """The first-in all-in range (weights 0 or 1) for a seat and a stack."""
    if stack_bb > TOP:
        from .cards import parse_range
        return parse_range(DEEP_FIRST_IN)
    need = max(1.0, stack_bb - 0.5)
    return [1.0 if lim >= need else 0.0 for lim in limits(stage, n_behind)]


def band(stack_bb: float) -> int:
    """Index of the stack band of the reshove / call tables (clamped to the deepest)."""
    tops = (7.5, 11.5, 16.5, 24.5)
    for i, top in enumerate(tops):
        if stack_bb <= top:
            return i
    return len(tops)


def reshove(stage: str, raiser: str, stack_bb: float) -> str:
    """Hands that move all-in over one raise (``raiser``: early, late or steal)."""
    if stack_bb > TOP:
        return DEEP_OVER_RAISE
    return data()["reshove"][_stage(stage)][raiser][band(stack_bb)]


def call(shover: str, allin_bb: float, bubble: bool = False, big_blind: bool = False) -> str:
    """Hands that call one all-in (``shover``: early, late, button or small).

    ``allin_bb`` is what hero has to put in: the all-in, or hero's stack if
    smaller.  In the big blind the price is better, which is worth one stack
    band (the small-blind row already assumes hero is the big blind).
    """
    if allin_bb > TOP:
        return DEEP_OVER_RAISE
    i = band(allin_bb)
    if big_blind and shover != "small":
        i = max(0, i - 1)
    return data()["call"]["bubble" if bubble else "normal"][shover][i]


def raiser_kind(n_behind: int) -> str:
    return "early" if n_behind >= 5 else "late" if n_behind >= 3 else "steal"


def shover_kind(n_behind: int) -> str:
    return "early" if n_behind >= 5 else "late" if n_behind >= 3 else "button" if n_behind == 2 else "small"


def _stage(stage: str) -> str:
    s = {"before": "before", "pre": "before", "bubble": "before", "money": "money", "itm": "money",
         "in": "money", "after": "money"}.get(str(stage).lower())
    if s is None:
        raise ValueError(f"stage must be 'before' or 'money', not {stage!r}")
    return s


def _seat(n_behind: int) -> int:
    return max(1, min(PLAYERS - 1, int(n_behind)))


def _in(text: str, hand: int) -> bool:
    from .cards import parse_range
    return parse_range(text)[hand] >= 0.5


def decide(hand: int, n_behind: int, stack_bb: float, stage: str = "before", facing: str = "",
           facing_seat: int | None = None, allin_bb: float | None = None, bubble: bool = False) -> tuple[str, str]:
    """(ALL-IN / CALL / FOLD / CHECK, the reason) from the printed tables.

    ``facing``: '' (nobody has raised), 'raise' or 'allin'; ``facing_seat`` is
    that player's seat as players behind them.
    """
    stage = _stage(stage)
    name = HANDS[hand]
    if not facing:
        if n_behind == 0:
            return "CHECK", "nobody raised: the big blind sees the flop for free (or takes the walk)"
        if stack_bb > TOP:
            ok = _in(DEEP_FIRST_IN, hand)
            return ("ALL-IN" if ok else "FOLD"), f"over {TOP}bb only {DEEP_FIRST_IN} move all-in first"
        lim = limit(stage, n_behind, hand)
        seat = SEATS[_seat(n_behind)]
        if lim >= max(1.0, stack_bb - 0.5):
            return "ALL-IN", f"{name} from {seat} is an all-in up to {lim}bb {STAGE_NAMES[stage]}"
        if lim:
            return "FOLD", f"{name} from {seat} is an all-in only up to {lim}bb {STAGE_NAMES[stage]}"
        return "FOLD", f"{name} from {seat} is never an all-in {STAGE_NAMES[stage]}"
    if facing_seat is None:
        raise ValueError("facing a raise or an all-in needs that player's seat")
    if facing == "raise":
        kind = raiser_kind(facing_seat)
        rng = reshove(stage, kind, stack_bb)
        label = BANDS[band(stack_bb)][0] if stack_bb <= TOP else f"over {TOP}bb"
        ok = _in(rng, hand)
        return ("ALL-IN" if ok else "FOLD"), f"over a raise from {SEATS[_seat(facing_seat)]} with {label}: {rng}"
    size = min(stack_bb, allin_bb or stack_bb)
    kind = shover_kind(facing_seat)
    rng = call(kind, size, bubble, big_blind=(n_behind == 0))
    ok = _in(rng, hand)
    where = "on the bubble" if bubble else "away from the bubble"
    return ("CALL" if ok else "FOLD"), f"against an all-in of {size:g}bb from {SEATS[_seat(facing_seat)]} {where}: {rng}"


# --------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------

_RANKS = "AKQJT98765432"


def grid_text(stage: str, n_behind: int) -> str:
    """The seat's first-in table: each cell is the deepest stack (bb) that moves all-in."""
    lim = limits(stage, n_behind)
    lines = [f"{SEATS[_seat(n_behind)]}, {STAGE_NAMES[_stage(stage)]}: deepest stack (bb) that moves all-in "
             f"(suited above the diagonal, offsuit below; . = fold)",
             "    " + " ".join(f"{r:>2}" for r in _RANKS)]
    for i, r in enumerate(_RANKS):
        lines.append(f"  {r} " + " ".join(f"{lim[i * 13 + j] or '.':>2}" for j in range(13)))
    return "\n".join(lines)


def width(stage: str, n_behind: int, stack_bb: float) -> float:
    """Share of hands (percent) that move all-in first from a seat with a stack."""
    rng = first_in_range(stage, n_behind, stack_bb)
    return 100.0 * sum(c for c, w in zip(COMBO_COUNT, rng) if w >= 0.5) / 1326.0


def sheet_text() -> str:
    d = data()
    out = ["ALL-IN OR FOLD, the whole tournament (8-handed)", ""]
    for stage in STAGES:
        out.append(f"Nobody has raised, {STAGE_NAMES[stage]}: share of hands that move all-in, by stack")
        out.append("  seat    " + " ".join(f"{s:>4}bb" for s in (6, 8, 10, 12, 15, 20, 25, 30, 40)))
        for nb in sorted(SEATS, reverse=True):
            out.append(f"  {SEATS[nb]:<6}  " + " ".join(f"{width(stage, nb, s):>5.0f}%" for s in (6, 8, 10, 12, 15, 20, 25, 30, 40)))
        out.append(f"  example, {STAGE_NAMES[stage]}, 10bb: BTN {format_range(first_in_range(stage, 2, 10))}")
        out.append("")
    for stage in STAGES:
        out.append(f"One raise before you, {STAGE_NAMES[stage]}: all-in with")
        for key, label, _nb in RAISERS:
            out.append(f"  raise from {label}")
            for (b, _s), rng in zip(BANDS, d["reshove"][stage][key]):
                out.append(f"    {b:<11} {rng}")
        out.append("")
    for key, title in (("normal", "away from the bubble"), ("bubble", "on the bubble, or at a final table against a stack that covers you")):
        out.append(f"One all-in before you, {title}: call with")
        for skey, label, _nb in SHOVERS:
            out.append(f"  all-in from {label}")
            for (b, _s), rng in zip(BANDS, d["call"][key][skey]):
                out.append(f"    {b:<11} {rng}")
        out.append("")
    out.append("In the big blind, read the all-in table one stack band to the left (the small-blind row already does).")
    out.append(f"Over {TOP}bb: {DEEP_FIRST_IN} first in, {DEEP_OVER_RAISE} over a raise or an all-in.")
    out.append("A raise and an all-in, or two all-ins, in front: AA, KK (QQ and AK when the stacks are 12bb or less).")
    return "\n".join(out)
