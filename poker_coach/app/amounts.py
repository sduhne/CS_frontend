"""One parser for every typed amount.

Every field that takes chips (a stack, a bet, the blinds, the average stack)
reads what was typed with ``parse_amount``, so the same spellings work
everywhere:

    1300    1,300      chips (in All-In or Fold: big blinds)
    12.500  1.300.000  the same with dots: thousands, where chips are whole
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

import math
import re

EXAMPLES = "1300, 12.5k, 25bb, 3x, 66%"
READ_FIX = f"Type it like {EXAMPLES}."

MAX_AMOUNT = 1e12                       # no stack, bet or prize is bigger: beyond it a typed number is a slip
MAX_COUNT = 10_000_000                  # players left, entrants, places paid
MAX_PLACES = 100_000                    # the paid places one typed prize list may cover


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


def _groups_of_three(text: str, mark: str) -> bool:
    """``12.500``, ``1.300.000``: up to three digits, then groups of exactly three after each mark."""
    first, *rest = text.split(mark)
    return bool(rest) and first.isdigit() and len(first) <= 3 and not first.startswith("0") \
        and all(len(g) == 3 and g.isdigit() for g in rest)


def _plain_number(text: str, typed: str, dots_are_thousands: bool = False, fix: str = READ_FIX) -> float:
    """``1300``, ``1,300``, ``12.5`` or ``12,5`` as a float; ``12.500`` as 12500 where the caller says so.

    Digits and separators only: ``nan``, ``inf`` and ``1e999`` are not amounts.
    """
    t = text
    if "," in t:
        groups = t.split(",")
        thousands = all(len(g) == 3 and g.isdigit() for g in groups[1:]) and groups[0].isdigit()
        if thousands:
            t = "".join(groups)                 # 1,300 and 1,300,000
        elif len(groups) == 2 and "." not in t:
            t = ".".join(groups)                # a decimal comma: 12,5k and 2,2bb
    elif dots_are_thousands and _groups_of_three(t, "."):
        t = t.replace(".", "")                  # 12.500 and 1.300.000, as Portuguese and Spanish write them
    if not re.fullmatch(r"\d+\.?\d*|\.\d+", t):
        raise AmountError(f"Cannot read {typed!r} as an amount.", fix)
    return float(t)


def _too_big(typed) -> AmountError:
    return AmountError(f"{typed} is more than any table holds.", f"The most a field takes is {fmt(MAX_AMOUNT)}.")


def parse_amount(text, bb: float | None = None, bet: float | None = None, pot: float | None = None,
                 current: float | None = None, step: float = 1, fix: str = READ_FIX,
                 dots_are_thousands: bool | None = None):
    """What the user typed, as a number of chips.

    ``bb``       the big blind, for ``25bb`` and ``2.2b``
    ``bet``      the bet being raised, for ``3x``
    ``pot``      the pot, for ``66%``
    ``current``  the value being edited, for ``+3k`` and ``-1500``
    ``step``     1 for chips, 0.1 where amounts are big blinds (All-In or Fold)
    ``fix``      what to type instead, said when the text cannot be read (each field has its own)

    Where chips are whole (``step`` 1) a number with no unit is whole too: ``12.500`` is twelve
    thousand five hundred, and ``12.5`` is refused with the spellings that work, never rounded to
    another number in silence.  ``dots_are_thousands`` asks for that reading of ``12.500`` where
    fractions exist as well (the blinds, money).
    """
    if isinstance(text, bool) or text is None:
        raise AmountError("No amount was typed.", fix)
    if isinstance(text, (int, float)):
        if text != text or text in (math.inf, -math.inf):
            raise AmountError(f"Cannot read {text!r} as an amount.", fix)
        if text < 0:
            raise AmountError("An amount cannot be negative.", "Type zero or more.")
        if text > MAX_AMOUNT:
            raise _too_big("That number")
        return tidy(text, step)

    typed = str(text).strip()
    t = typed.lower().replace("$", "").replace(" ", "").replace("_", "")
    if not t:
        raise AmountError("No amount was typed.", fix)
    if len(t) > 40:                                 # nothing a table holds takes forty characters
        if t.replace(".", "").replace(",", "").isdigit():
            raise _too_big("That number")
        raise AmountError(f"Cannot read {typed[:20] + '...'!r} as an amount.", fix)

    # a sign in front means "change the current value by this much"
    sign = 0
    if t[0] in "+-":
        sign = 1 if t[0] == "+" else -1
        t = t[1:]
        if current is None:
            raise AmountError(f"{typed!r} is a change, and there is no value here to change.",
                              "Type the amount itself, without + or -.")

    # the unit at the end says what the number counts
    times, unit = 1.0, ""
    if t.endswith("bb") or (t.endswith("b") and t[:-1].replace(".", "").replace(",", "").isdigit()):
        t, unit = (t[:-2] if t.endswith("bb") else t[:-1]), "bb"
    elif t[-1:] in ("x", "%", "k", "m"):
        t, unit = t[:-1], t[-1]
    if not any(ch.isdigit() for ch in t):
        raise AmountError(f"Cannot read {typed!r} as an amount.", fix)      # a unit and no number: "x", "bb"
    if unit == "bb":
        if not bb:
            raise AmountError(f"{typed!r} is in big blinds, and the blinds are not set.",
                              "Set the blinds first, or type chips.")
        times = float(bb)
    elif unit == "x":
        if not bet:
            raise AmountError(f"{typed!r} is a multiple of a bet, and there is no bet to raise.",
                              "Type chips, big blinds (3bb) or a share of the pot (66%).")
        times = float(bet)
    elif unit == "%":
        if pot is None:
            raise AmountError(f"{typed!r} is a share of the pot: that works for bets only.",
                              "Type chips or big blinds (25bb).")
        times = float(pot) / 100.0
    elif unit:
        times = {"k": 1e3, "m": 1e6}[unit]

    if dots_are_thousands is None:
        dots_are_thousands = step >= 1
    number = _plain_number(t, typed, dots_are_thousands and not unit, fix)
    value = number * times
    if not unit and step >= 1 and not float(number).is_integer():
        # chips are whole: 12.5 is a slip for 12500, 12.5k or 12.5bb, and is never rounded to 13
        mark = typed[0] if sign else ""
        ways = [f"{mark}{tidy(number * 1000)}", f"{mark}{t}k"] + ([f"{mark}{t}bb"] if bb else [])
        raise AmountError(f"{typed!r} has a fraction, and chips are whole.", "Type " + ", or ".join(ways) + ".")
    if value > MAX_AMOUNT:                          # also a number too long to be one (it reads as infinity)
        raise _too_big(repr(typed))
    if sign:
        value = float(current) + sign * value
        if value < 0:
            raise AmountError(f"{typed!r} takes more than there is ({fmt(current)}).",
                              "Type the new amount itself.")
        if value > MAX_AMOUNT:
            raise _too_big(repr(typed))
    return tidy(value, step)


def parse_count(text, what: str = "The number", example: int = 75, current: int | None = None) -> int:
    """A typed count (players left, places paid, entrants): a whole number.

    ``1,500``, ``1.500`` and ``1.5k`` are fifteen hundred; ``+10`` and ``-1`` change ``current``.
    ``what`` names the field, so the refusal says what belongs in it.
    """
    fix = f"{what} is a whole number, like {example}."
    if isinstance(text, bool) or text is None or (isinstance(text, str) and not text.strip()):
        raise AmountError("No number was typed.", fix)
    try:
        value = parse_amount(text, current=current, step=1, fix=fix)
    except AmountError as err:
        if "more than" in err.message and "takes" not in err.message:
            raise AmountError(f"{what} cannot be more than {fmt(MAX_COUNT)}.", fix) from None
        if isinstance(text, str) and text.strip()[:1] in "+-" and current is not None and "takes" in err.message:
            raise                                   # "-500 takes more than there is (96)": already clear
        shown = text if isinstance(text, str) else repr(text)
        raise AmountError(f"Cannot read {str(shown).strip()[:20]!r} as a number.", fix) from None
    if value > MAX_COUNT:
        raise AmountError(f"{what} cannot be more than {fmt(MAX_COUNT)}.", fix)
    return int(value)


# --------------------------------------------------------------------------
# Blinds, ladders, payouts
# --------------------------------------------------------------------------

BLINDS_FIX = "Type blinds like 300/600/75, 300/600, or 600 alone."


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
    shown = str(text if text is not None else "").strip()[:30]
    if not 1 <= len(parts) <= 3:
        raise AmountError(f"Cannot read {shown!r} as blinds.", BLINDS_FIX)
    try:
        # 1.000/2.000/250 is 1000/2000/250; a small blind of 62.5 keeps its half chip
        nums = [parse_amount(p, step=0.01, dots_are_thousands=True) for p in parts]
    except AmountError:
        raise AmountError(f"Cannot read {shown!r} as blinds.", BLINDS_FIX) from None
    if len(nums) == 1:
        sb, bb, ante = None, nums[0], None
    elif len(nums) == 2:
        sb, bb, ante = nums[0], nums[1], None
    else:
        sb, bb, ante = nums
    if not bb or bb <= 0:
        raise AmountError("The big blind must be above zero.", BLINDS_FIX)
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
    fix = "Type prizes like 1:1000 2:600 4-6:200, or auto."
    too_many = AmountError(f"A prize list covers {fmt(MAX_PLACES)} places at most.", fix)
    if isinstance(text, (list, tuple)):
        if len(text) > MAX_PLACES:
            raise too_many
        return [float(_prize(p, fix)) for p in text] or None
    words = [w.strip(",;") for w in re.split(r"[\s;]+", str(text)) if w.strip(",;")]
    if not words or (len(words) == 1 and words[0].lower() in ("auto", "none", "-")):
        return None
    if len(words) > MAX_PLACES:
        raise too_many
    by_place: dict[int, float] = {}
    in_order: list[float] = []
    for word in words:
        if ":" not in word:
            in_order.append(float(_prize(word, fix)))
            continue
        place, amount = word.split(":", 1)
        value = float(_prize(amount, fix, word))
        first, _, last = place.partition("-")
        if not (first.isdigit() and (last.isdigit() or not last) and len(first) <= 9 and len(last) <= 9):
            raise AmountError(f"Cannot read the prize {word[:30]!r}.", fix)
        first, last = int(first), int(last or first)
        if first < 1 or last < first:
            raise AmountError("Places start at 1, and a range runs upwards: 4-6.", fix)
        if last > MAX_PLACES:                       # 1-100000000:200 would fill the memory
            raise too_many
        for p in range(first, last + 1):
            by_place[p] = value
    if by_place:
        prizes, last = [], 0.0
        for place in range(max(by_place), 0, -1):       # walk up from the smallest prize
            last = by_place.get(place, last)
            prizes.append(last)
        return prizes[::-1]
    return in_order


def _prize(text, fix: str, word=None):
    """One prize: money, so 27.60 keeps its cents and 1.000 is a thousand."""
    try:
        return parse_amount(text, step=0.01, dots_are_thousands=True)
    except AmountError:
        shown = str(word if word is not None else text)[:30]
        raise AmountError(f"Cannot read the prize {shown!r}.", fix) from None


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
