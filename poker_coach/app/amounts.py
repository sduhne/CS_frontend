"""One parser for every typed amount.

Every field that takes chips (a stack, a bet, the blinds, the average stack)
reads what was typed with ``parse_amount``, so the same spellings work
everywhere:

    1300    1,300      chips (in All-In or Fold: big blinds)
    12.5k   1.2m       thousands, millions
    25bb    2.2b       times the big blind
    3x                 three times the bet being raised
    66%                of the pot (bets only)
    +3k     -1500      relative to the current value (stacks only)

The caller says what it knows (the big blind, the bet being raised, the pot,
the current value).  A spelling that needs something the caller did not give
is refused with one sentence saying why and one saying what to type instead.

Also here, because they are typed amounts too: the blinds (``300/600/75``),
a pasted blind ladder and a payout list (``1:1000 2:600 4-6:200``).
"""

from __future__ import annotations

import re

EXAMPLES = "1300, 12.5k, 25bb, 3x, 66%"


class AmountError(ValueError):
    """What was typed cannot be read.  ``message`` says why, ``fix`` what to type."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.message = message
        self.fix = fix


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

def tidy(value: float, step: float = 1):
    """Round to the table's step (whole chips, or tenths of a big blind); whole numbers become ints."""
    if step >= 1:
        return int(value + 0.5) if value >= 0 else -int(-value + 0.5)   # halves round up: 62.5 -> 63
    places = max(0, len(str(step).split(".")[-1]))
    value = round(value, places)
    return int(value) if float(value).is_integer() else value


def _plain_number(text: str, typed: str) -> float:
    """``1300``, ``1,300``, ``12.5`` or ``12,5`` as a float."""
    t = text
    if "," in t:
        groups = t.split(",")
        thousands = all(len(g) == 3 and g.isdigit() for g in groups[1:]) and groups[0].isdigit()
        if thousands:
            t = "".join(groups)                 # 1,300 and 1,300,000
        elif len(groups) == 2 and "." not in t:
            t = ".".join(groups)                # a decimal comma: 12,5k and 2,2bb
    try:
        return float(t)
    except ValueError:
        raise AmountError(f"Cannot read {typed!r} as an amount.", f"Type it like {EXAMPLES}.") from None


def parse_amount(text, bb: float | None = None, bet: float | None = None, pot: float | None = None,
                 current: float | None = None, step: float = 1):
    """What the user typed, as a number of chips.

    ``bb``       the big blind, for ``25bb`` and ``2.2b``
    ``bet``      the bet being raised, for ``3x``
    ``pot``      the pot, for ``66%``
    ``current``  the value being edited, for ``+3k`` and ``-1500``
    ``step``     1 for chips, 0.1 where amounts are big blinds (All-In or Fold)
    """
    if isinstance(text, bool) or text is None:
        raise AmountError("No amount was typed.", f"Type it like {EXAMPLES}.")
    if isinstance(text, (int, float)):
        if text < 0:
            raise AmountError("An amount cannot be negative.", "Type zero or more.")
        return tidy(text, step)

    typed = str(text).strip()
    t = typed.lower().replace("$", "").replace(" ", "").replace("_", "")
    if not t:
        raise AmountError("No amount was typed.", f"Type it like {EXAMPLES}.")

    # a sign in front means "change the current value by this much"
    sign = 0
    if t[0] in "+-":
        sign = 1 if t[0] == "+" else -1
        t = t[1:]
        if current is None:
            raise AmountError(f"{typed!r} is a change, and there is no value here to change.",
                              "Type the amount itself, without + or -.")

    # the unit at the end says what the number counts
    times = 1.0
    if t.endswith("bb") or (t.endswith("b") and t[:-1].replace(".", "").replace(",", "").isdigit()):
        t = t[:-2] if t.endswith("bb") else t[:-1]
        if not bb:
            raise AmountError(f"{typed!r} is in big blinds, and the blinds are not set.",
                              "Set the blinds first, or type chips.")
        times = float(bb)
    elif t.endswith("x"):
        t = t[:-1]
        if not bet:
            raise AmountError(f"{typed!r} is a multiple of a bet, and there is no bet to raise.",
                              "Type chips, big blinds (3bb) or a share of the pot (66%).")
        times = float(bet)
    elif t.endswith("%"):
        t = t[:-1]
        if pot is None:
            raise AmountError(f"{typed!r} is a share of the pot: that works for bets only.",
                              "Type chips or big blinds (25bb).")
        times = float(pot) / 100.0
    elif t.endswith("k"):
        t, times = t[:-1], 1e3
    elif t.endswith("m"):
        t, times = t[:-1], 1e6

    value = _plain_number(t, typed) * times
    if value < 0:
        raise AmountError("An amount cannot be negative.", "Type zero or more.")
    if sign:
        value = float(current) + sign * value
        if value < 0:
            raise AmountError(f"{typed!r} takes more than there is ({fmt(current)}).",
                              "Type the new amount itself.")
    return tidy(value, step)


# --------------------------------------------------------------------------
# Blinds, ladders, payouts
# --------------------------------------------------------------------------

def parse_blinds(text) -> dict:
    """``300/600/75`` -> small blind, big blind, ante.  ``600`` alone is the big blind.

    Parts that were not typed come back as ``None``; the caller fills them
    (the small blind is half the big blind, the ante follows the ante kind).
    """
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        parts = [text]
    else:
        cleaned = re.sub(r"\b(ante|a)\b", " ", str(text or "").lower())
        cleaned = re.sub(r"(?<=\d)\s*a\s*(?=\d)", " ", cleaned)      # "300/600 a75"
        parts = [p for p in re.split(r"[/\s;|]+", cleaned.strip()) if p]
    if not 1 <= len(parts) <= 3:
        raise AmountError(f"Cannot read {str(text)!r} as blinds.",
                          "Type them like 300/600/75, 300/600, or 600 alone.")
    nums = [parse_amount(p, step=0.01) for p in parts]
    if len(nums) == 1:
        sb, bb, ante = None, nums[0], None
    elif len(nums) == 2:
        sb, bb, ante = nums[0], nums[1], None
    else:
        sb, bb, ante = nums
    if not bb or bb <= 0:
        raise AmountError("The big blind must be above zero.", "Type the blinds like 300/600.")
    if sb is not None and sb > bb:
        raise AmountError(f"The small blind ({fmt(sb)}) is above the big blind ({fmt(bb)}).",
                          "Type the small blind first: 300/600.")
    return {"sb": sb, "bb": bb, "ante": ante}


def parse_ladder(text: str) -> list[dict]:
    """A pasted blind ladder, one level per line: ``100/200/25``, ``100/200`` or ``200``.

    A level number in front (``12:``, ``12.``, ``L12``) is ignored, and so are
    empty lines and lines that start with ``#``.
    """
    levels = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^(level|lvl|l)?\s*\d+\s*[:.)]\s+", "", line, flags=re.IGNORECASE)
        line = re.sub(r"^(level|lvl|l)\s*\d+\s+", "", line, flags=re.IGNORECASE)
        try:
            lv = parse_blinds(line)
        except AmountError:
            raise AmountError(f"Cannot read the ladder line {raw.strip()!r}.",
                              "One level per line: 100/200/25, 100/200 or 200.") from None
        if lv["sb"] is None:
            lv["sb"] = tidy(lv["bb"] / 2, 0.01)
        lv["ante"] = lv["ante"] or 0
        if levels and lv["bb"] < levels[-1]["bb"]:
            raise AmountError(f"The level {fmt(lv['sb'])}/{fmt(lv['bb'])} is below the one before it.",
                              "List the levels from the smallest blinds up.")
        levels.append(lv)
    if not levels:
        raise AmountError("The ladder is empty.", "Paste one level per line: 100/200/25.")
    return levels


def parse_payouts(text) -> list[float] | None:
    """``1:1000 2:600 4-6:200`` or ``1000 600 400`` -> prizes from first place down.

    ``auto`` (or nothing) returns ``None``: the estimated table is used.  A
    place that is not listed gets the prize of the next listed place below it,
    the same rule as the ``payouts`` command.
    """
    if text is None:
        return None
    if isinstance(text, (list, tuple)):
        return [float(parse_amount(p, step=0.01)) for p in text] or None
    words = [w.strip(",;") for w in re.split(r"[\s;]+", str(text)) if w.strip(",;")]
    if not words or (len(words) == 1 and words[0].lower() in ("auto", "none", "-")):
        return None
    by_place: dict[int, float] = {}
    in_order: list[float] = []
    for word in words:
        try:
            if ":" in word:
                place, amount = word.split(":", 1)
                value = float(parse_amount(amount, step=0.01))
                first, _, last = place.partition("-")
                for p in range(int(first), int(last or first) + 1):
                    by_place[p] = value
            else:
                in_order.append(float(parse_amount(word, step=0.01)))
        except (ValueError, AmountError):
            raise AmountError(f"Cannot read the prize {word!r}.",
                              "Type prizes like 1:1000 2:600 4-6:200, or auto.") from None
    if by_place:
        if min(by_place) < 1:
            raise AmountError("Places start at 1.", "Type prizes like 1:1000 2:600 4-6:200.")
        prizes, last = [], 0.0
        for place in range(max(by_place), 0, -1):       # walk up from the smallest prize
            last = by_place.get(place, last)
            prizes.append(last)
        return prizes[::-1]
    return in_order


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------

def fmt(value) -> str:
    """Chips with thousands separators: 12,900.  Fractions (big-blind tables) keep one or two decimals."""
    if value is None:
        return "?"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def fmt_bb(value, bb) -> str:
    """An amount in big blinds: 2.2bb, 21.5bb, 3bb."""
    if not bb:
        return fmt(value)
    x = round(float(value) / float(bb), 1)
    return (f"{int(x)}" if x.is_integer() else f"{x}") + "bb"
