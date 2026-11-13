"""Cards, the 169 starting-hand classes, and range notation.

Card encoding: ``card = rank * 4 + suit`` with rank 0 = deuce ... 12 = ace and
suit index into ``"cdhs"``.

Hand classes are indexed on the usual 13x13 grid with the ace first:
``index = row * 13 + col``; ``row < col`` is suited, ``row > col`` is offsuit
and the diagonal holds the pairs.  A *range* is a list of 169 weights in
``[0, 1]``.
"""

from __future__ import annotations

import re

RANKS = "23456789TJQKA"
SUITS = "cdhs"
GRID = "AKQJT98765432"

_SUIT_ALIASES = {"♣": "c", "♦": "d", "♥": "h", "♠": "s"}


def parse_card(text: str) -> int:
    t = text.strip()
    if len(t) == 3 and t[:2] == "10":
        t = "T" + t[2]
    if len(t) != 2:
        raise ValueError(f"bad card {text!r}")
    r, s = t[0].upper(), _SUIT_ALIASES.get(t[1], t[1].lower())
    if r not in RANKS or s not in SUITS:
        raise ValueError(f"bad card {text!r}")
    return RANKS.index(r) * 4 + SUITS.index(s)


def parse_cards(text: str) -> list[int]:
    """Parse ``"AhKd"``, ``"Ah Kd"``, ``"ah,kd,10s"`` ... into card ints."""
    if not text:
        return []
    t = text
    for k, v in _SUIT_ALIASES.items():
        t = t.replace(k, v)
    t = t.replace("10", "T")
    t = re.sub(r"[\s,/|-]+", "", t)
    if len(t) % 2:
        raise ValueError(f"bad card list {text!r}")
    cards = [parse_card(t[i : i + 2]) for i in range(0, len(t), 2)]
    if len(set(cards)) != len(cards):
        raise ValueError(f"duplicate card in {text!r}")
    return cards


def card_str(card: int) -> str:
    return RANKS[card >> 2] + SUITS[card & 3]


def cards_str(cards) -> str:
    return "".join(card_str(c) for c in cards)


# --------------------------------------------------------------------------
# Hand classes
# --------------------------------------------------------------------------

def _class_name(row: int, col: int) -> str:
    if row == col:
        return GRID[row] * 2
    if row < col:
        return GRID[row] + GRID[col] + "s"
    return GRID[col] + GRID[row] + "o"


HANDS: list[str] = [_class_name(i, j) for i in range(13) for j in range(13)]
HAND_INDEX: dict[str, int] = {h: i for i, h in enumerate(HANDS)}
N_CLASSES = 169
TOTAL_COMBOS = 1326


def _class_combos(idx: int) -> list[tuple[int, int]]:
    row, col = divmod(idx, 13)
    hi, lo = 12 - min(row, col), 12 - max(row, col)
    if row == col:
        return [(hi * 4 + a, hi * 4 + b) for a in range(4) for b in range(a + 1, 4)]
    if row < col:
        return [(hi * 4 + s, lo * 4 + s) for s in range(4)]
    return [(hi * 4 + a, lo * 4 + b) for a in range(4) for b in range(4) if a != b]


CLASS_COMBOS: list[list[tuple[int, int]]] = [_class_combos(i) for i in range(169)]
COMBO_COUNT: list[int] = [len(c) for c in CLASS_COMBOS]


def class_of(c1: int, c2: int) -> int:
    """Class index of two concrete cards."""
    r1, r2 = c1 >> 2, c2 >> 2
    if r1 == r2:
        return (12 - r1) * 14
    hi, lo = max(r1, r2), min(r1, r2)
    row, col = 12 - hi, 12 - lo
    if (c1 & 3) == (c2 & 3):
        return row * 13 + col
    return col * 13 + row


def parse_hand(text: str) -> tuple[int, tuple[int, int] | None]:
    """Parse hero's hand.

    Accepts concrete cards (``"AhKd"``) or a class (``"AKo"``, ``"AKs"``,
    ``"77"``).  Returns ``(class_index, concrete_cards_or_None)``.
    """
    t = text.strip().replace("10", "T")
    for k, v in _SUIT_ALIASES.items():
        t = t.replace(k, v)
    t = re.sub(r"[\s,]+", "", t)
    if len(t) == 4:
        c1, c2 = parse_cards(t)
        return class_of(c1, c2), (c1, c2)
    return class_index(t), None


def class_index(name: str) -> int:
    """Index of a class name; tolerant of order and case (``"kas"`` -> AKs)."""
    t = name.strip()
    if len(t) < 2:
        raise ValueError(f"bad hand {name!r}")
    r1, r2 = t[0].upper(), t[1].upper()
    if r1 not in RANKS or r2 not in RANKS:
        raise ValueError(f"bad hand {name!r}")
    if r1 == r2:
        return HAND_INDEX[r1 + r2]
    if RANKS.index(r1) < RANKS.index(r2):
        r1, r2 = r2, r1
    kind = t[2].lower() if len(t) > 2 else "o"
    if kind not in "so":
        raise ValueError(f"bad hand {name!r}")
    return HAND_INDEX[r1 + r2 + kind]


# --------------------------------------------------------------------------
# Range notation
# --------------------------------------------------------------------------

def empty_range() -> list[float]:
    return [0.0] * 169


def full_range() -> list[float]:
    return [1.0] * 169


def range_combos(weights) -> float:
    return sum(w * n for w, n in zip(weights, COMBO_COUNT))


def range_pct(weights) -> float:
    """Share of all 1326 starting combos, in percent."""
    return 100.0 * range_combos(weights) / TOTAL_COMBOS


def _rank(ch: str) -> int:
    return RANKS.index(ch.upper())


def _expand_token(tok: str) -> list[int]:
    """Expand one token such as ``77+``, ``ATs+``, ``KQ``, ``A5s-A2s``."""
    t = tok.strip()
    m = re.fullmatch(r"([2-9TJQKA])\1(\+)?", t, re.I)
    if m:  # pair or pair+
        r = _rank(m.group(1))
        top = 12 if m.group(2) else r
        return [HAND_INDEX[RANKS[x] * 2] for x in range(r, top + 1)]
    m = re.fullmatch(r"([2-9TJQKA])\1-([2-9TJQKA])\2", t, re.I)
    if m:  # pair span
        a, b = sorted((_rank(m.group(1)), _rank(m.group(2))))
        return [HAND_INDEX[RANKS[x] * 2] for x in range(a, b + 1)]

    def kinds(k: str | None) -> list[str]:
        return [k.lower()] if k else ["s", "o"]

    m = re.fullmatch(r"([2-9TJQKA])([2-9TJQKA])([so])?(\+)?", t, re.I)
    if m:  # AKs, AK, ATs+, AT+
        hi, lo = _rank(m.group(1)), _rank(m.group(2))
        if hi < lo:
            hi, lo = lo, hi
        if hi == lo:
            raise ValueError(f"bad range token {tok!r}")
        top = hi - 1 if m.group(4) else lo
        return [
            HAND_INDEX[RANKS[hi] + RANKS[x] + k]
            for k in kinds(m.group(3))
            for x in range(lo, top + 1)
        ]
    m = re.fullmatch(r"([2-9TJQKA])([2-9TJQKA])([so])?-([2-9TJQKA])([2-9TJQKA])([so])?", t, re.I)
    if m:  # A5s-A2s (same high card) or T9s-76s (same gap)
        h1, l1 = sorted((_rank(m.group(1)), _rank(m.group(2))), reverse=True)
        h2, l2 = sorted((_rank(m.group(4)), _rank(m.group(5))), reverse=True)
        ks = kinds(m.group(3) or m.group(6))
        out = []
        if h1 == h2:
            a, b = sorted((l1, l2))
            for k in ks:
                out += [HAND_INDEX[RANKS[h1] + RANKS[x] + k] for x in range(a, b + 1)]
            return out
        if h1 - l1 == h2 - l2:
            gap = h1 - l1
            a, b = sorted((h1, h2))
            for k in ks:
                out += [HAND_INDEX[RANKS[x] + RANKS[x - gap] + k] for x in range(a, b + 1)]
            return out
    raise ValueError(f"bad range token {tok!r}")


def parse_range(text: str, ordering: list[int] | None = None) -> list[float]:
    """Parse range notation into 169 weights.

    Tokens are comma or space separated: ``"77+, ATs+, KQo, A5s-A2s"``.
    ``"22%"`` / ``"top22"`` take the top share of hands by ``ordering`` (a list
    of class indices, strongest first); ``"any"`` / ``"random"`` is every hand.
    A token may carry a weight: ``"AJo:0.5"``.
    """
    weights = empty_range()
    for raw in re.split(r"[,\s;]+", text.strip()):
        if not raw:
            continue
        tok, w = raw, 1.0
        if ":" in raw:
            tok, ws = raw.split(":", 1)
            w = float(ws)
        low = tok.lower()
        if low in ("any", "random", "atc", "100%", "all"):
            idxs = list(range(169))
        else:
            m = re.fullmatch(r"(?:top)?(\d+(?:\.\d+)?)%?", low)
            if m and (low.startswith("top") or low.endswith("%")):
                if ordering is None:
                    raise ValueError("percentage ranges need a hand ordering")
                for i, wt in enumerate(top_percent(float(m.group(1)), ordering)):
                    if wt > 0:
                        weights[i] = max(weights[i], wt * w)
                continue
            idxs = _expand_token(tok)
        for i in idxs:
            weights[i] = max(weights[i], w)
    return weights


def top_percent(pct: float, ordering: list[int]) -> list[float]:
    """Range holding the top ``pct`` percent of combos along ``ordering``.

    The marginal class gets a fractional weight so the size is exact.
    """
    target = max(0.0, min(100.0, pct)) / 100.0 * TOTAL_COMBOS
    weights = empty_range()
    used = 0.0
    for idx in ordering:
        n = COMBO_COUNT[idx]
        if used + n <= target + 1e-9:
            weights[idx] = 1.0
            used += n
        else:
            weights[idx] = max(0.0, (target - used) / n)
            break
    return weights


def format_range(weights, threshold: float = 0.5) -> str:
    """Compact notation for a range (classes with weight >= threshold)."""
    inr = [w >= threshold for w in weights]
    parts: list[str] = []

    # pairs, as spans from the top
    pairs = [inr[i * 14] for i in range(13)]  # index 0 = AA
    i = 0
    while i < 13:
        if pairs[i]:
            j = i
            while j + 1 < 13 and pairs[j + 1]:
                j += 1
            hi, lo = GRID[i] * 2, GRID[j] * 2
            parts.append(f"{lo}+" if i == 0 and j > 0 else (hi if i == j else f"{hi}-{lo}"))
            i = j + 1
        else:
            i += 1

    for kind in ("s", "o"):
        for hi in range(12):  # grid index of the high card
            cells = []
            for lo in range(hi + 1, 13):
                idx = hi * 13 + lo if kind == "s" else lo * 13 + hi
                cells.append(inr[idx])
            k = 0
            while k < len(cells):
                if cells[k]:
                    e = k
                    while e + 1 < len(cells) and cells[e + 1]:
                        e += 1
                    top = GRID[hi] + GRID[hi + 1 + k] + kind
                    bot = GRID[hi] + GRID[hi + 1 + e] + kind
                    if k == 0 and e > 0:
                        parts.append(f"{bot}+")
                    elif k == e:
                        parts.append(top)
                    else:
                        parts.append(f"{top}-{bot}")
                    k = e + 1
                else:
                    k += 1
    return ", ".join(parts) if parts else "(nothing)"
