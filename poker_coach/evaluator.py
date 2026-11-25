"""5/6/7-card hand evaluator and made-hand / draw description.

``evaluate(cards)`` returns an int; bigger is better, equal is a tie.  The top
byte is the category (0 high card ... 8 straight flush).

The evaluator keeps three running accumulators so Monte-Carlo loops can share
the fixed part of a hand (board, hole cards) and only add the varying cards:

* ``acc``  - 4 bits per rank holding how many of that rank are present
* ``sacc`` - 16 bits per suit holding the rank bitmask of that suit
* ``scnt`` - 4 bits per suit holding how many cards of that suit
"""

from __future__ import annotations

from .cards import RANKS

CATEGORIES = [
    "high card", "pair", "two pair", "three of a kind", "straight",
    "flush", "full house", "four of a kind", "straight flush",
]

NIB = [1 << (4 * (c >> 2)) for c in range(52)]
SBIT = [1 << (16 * (c & 3) + (c >> 2)) for c in range(52)]
SCNT = [1 << (4 * (c & 3)) for c in range(52)]


def _topn(mask: int, n: int) -> int:
    out = 0
    for r in range(12, -1, -1):
        if n and mask & (1 << r):
            out |= 1 << r
            n -= 1
    return out


def _straight_high(mask: int) -> int:
    for top in range(12, 3, -1):
        need = 0x1F << (top - 4)
        if mask & need == need:
            return top
    if mask & 0x100F == 0x100F:  # wheel
        return 3
    return -1


STRAIGHT_HI = [_straight_high(m) for m in range(8192)]
_FLUSH_VAL = [0] * 8192
for _m in range(8192):
    if bin(_m).count("1") >= 5:             # (int.bit_count is Python 3.10; this line keeps 3.9 starting)
        _st = STRAIGHT_HI[_m]
        _FLUSH_VAL[_m] = (8 << 24) | _st if _st >= 0 else (5 << 24) | _topn(_m, 5)

_RANK_CACHE: dict[int, int] = {}


def _rank_value(acc: int) -> int:
    """Value of a hand ignoring flushes, from the rank-count accumulator."""
    quad = -1
    trips: list[int] = []
    pairs: list[int] = []
    rm = 0
    for r in range(12, -1, -1):
        n = (acc >> (4 * r)) & 15
        if n:
            rm |= 1 << r
            if n == 4:
                quad = r
            elif n == 3:
                trips.append(r)
            elif n == 2:
                pairs.append(r)
    if quad >= 0:
        return (7 << 24) | (quad << 13) | _topn(rm & ~(1 << quad), 1)
    if trips and (len(trips) >= 2 or pairs):
        p = max(trips[1] if len(trips) >= 2 else -1, pairs[0] if pairs else -1)
        return (6 << 24) | (trips[0] << 4) | p
    st = STRAIGHT_HI[rm]
    if st >= 0:
        return (4 << 24) | st
    if trips:
        return (3 << 24) | (trips[0] << 13) | _topn(rm & ~(1 << trips[0]), 2)
    if len(pairs) >= 2:
        rest = rm & ~(1 << pairs[0]) & ~(1 << pairs[1])
        return (2 << 24) | (pairs[0] << 17) | (pairs[1] << 13) | _topn(rest, 1)
    if pairs:
        return (1 << 24) | (pairs[0] << 13) | _topn(rm & ~(1 << pairs[0]), 3)
    return _topn(rm, 5)


def value_from_acc(acc: int, sacc: int, scnt: int) -> int:
    f = (scnt + 0x3333) & 0x8888
    if f:
        suit = (f.bit_length() - 1) >> 2
        return _FLUSH_VAL[(sacc >> (16 * suit)) & 0x1FFF]
    v = _RANK_CACHE.get(acc)
    if v is None:
        v = _RANK_CACHE[acc] = _rank_value(acc)
    return v


def accumulate(cards, acc: int = 0, sacc: int = 0, scnt: int = 0) -> tuple[int, int, int]:
    for c in cards:
        acc += NIB[c]
        sacc |= SBIT[c]
        scnt += SCNT[c]
    return acc, sacc, scnt


def evaluate(cards) -> int:
    """Best 5-card value from 5 to 7 cards."""
    acc = sacc = scnt = 0
    for c in cards:
        acc += NIB[c]
        sacc |= SBIT[c]
        scnt += SCNT[c]
    return value_from_acc(acc, sacc, scnt)


def category(value: int) -> str:
    return CATEGORIES[value >> 24]


# --------------------------------------------------------------------------
# Human-readable description of hero's hand on a board
# --------------------------------------------------------------------------

def _rank_name(r: int) -> str:
    return RANKS[r]


def describe(hole, board) -> dict:
    """Describe hero's made hand and draws on a flop/turn/river.

    Returns a dict with ``made`` (text), ``strength`` (0 air ... 9 monster, a
    coarse tier used by the postflop heuristics), ``draws`` (list of text),
    ``outs`` (approximate clean outs to improve) and a few flags.
    """
    hole = list(hole)
    board = list(board)
    cards = hole + board
    val = evaluate(cards)
    cat = val >> 24
    board_val = evaluate(board) if len(board) >= 5 else None
    hr = sorted((c >> 2 for c in hole), reverse=True)
    br = sorted((c >> 2 for c in board), reverse=True)
    board_counts = {r: br.count(r) for r in set(br)}
    top_board = br[0]
    pocket_pair = hr[0] == hr[1]
    plays_board = board_val is not None and board_val == val

    made = CATEGORIES[cat]
    strength = 0
    flags: list[str] = []

    board_paired = any(n >= 2 for n in board_counts.values())
    suit_counts = [0, 0, 0, 0]
    for c in board:
        suit_counts[c & 3] += 1
    board_flushy = max(suit_counts)

    if cat == 0:
        overs = sum(1 for r in hr if r > top_board)
        if overs == 2:
            made, strength = "two overcards", 1
        elif hr[0] == 12:
            made, strength = "ace high", 1
        else:
            made, strength = "high card (air)", 0
    elif cat == 1:
        pair_rank = (val >> 13) & 15
        if pair_rank in board_counts and board_counts[pair_rank] >= 2:
            made, strength = "board pair only (no pair of your own)", 0 if hr[0] < 12 else 1
        elif pocket_pair:
            if hr[0] > top_board:
                made, strength = f"overpair ({_rank_name(hr[0])}{_rank_name(hr[0])})", 6
            else:
                higher = sum(1 for r in set(br) if r > hr[0])
                if higher == 1:
                    made, strength = "pocket pair below top card", 3
                else:
                    made, strength = "underpair", 2
        else:
            kicker = hr[0] if hr[1] == pair_rank else hr[1]
            distinct = sorted(set(br), reverse=True)
            pos = distinct.index(pair_rank)
            if pos == 0:
                if kicker >= 11 or (kicker == 10 and pair_rank != 12) or kicker == 12:
                    made, strength = f"top pair, strong kicker ({_rank_name(kicker)})", 5
                elif kicker >= 8:
                    made, strength = f"top pair, medium kicker ({_rank_name(kicker)})", 4
                else:
                    made, strength = f"top pair, weak kicker ({_rank_name(kicker)})", 4
            elif pos == 1:
                made, strength = "second pair", 3
            else:
                made, strength = "bottom/weak pair", 2
    elif cat == 2:
        hi_pair, lo_pair = (val >> 17) & 15, (val >> 13) & 15
        mine = [r for r in (hi_pair, lo_pair) if r in hr]
        if not mine:
            made, strength = "two pair on board (playing the board)", 0 if hr[0] < 12 else 1
        elif len(mine) == 2:  # both hole cards paired: a real two pair
            distinct = sorted(set(br), reverse=True)
            if hi_pair == distinct[0] and lo_pair == distinct[1]:
                made, strength = "top two pair", 7
            else:
                made, strength = "two pair", 6
            if board_paired:
                strength -= 1
        else:
            # the second pair lies on the board: really a one-pair hand
            my = mine[0]
            if pocket_pair and my > top_board:
                made, strength = "overpair on a paired board", 5
            elif my >= top_board:
                made, strength = "top pair on a paired board", 4
            else:
                made, strength = "pair on a paired board", 2
    elif cat == 3:
        trip_rank = (val >> 13) & 15
        if board_counts.get(trip_rank, 0) == 3:
            made, strength = "trips on board (playing kickers)", 1 if hr[0] < 12 else 2
        elif pocket_pair:
            made, strength = f"set of {_rank_name(trip_rank)}s", 8
        else:
            made, strength = f"trips ({_rank_name(trip_rank)}s)", 7
    elif cat == 4:
        made, strength = "straight", 8
        if plays_board:
            made, strength = "straight on board", 1
        elif board_flushy >= 4 or board_paired and len(board) == 5:
            strength = 6
    elif cat == 5:
        fsuit = max(range(4), key=lambda s: sum(1 for c in cards if c & 3 == s))
        my_flush = sorted((c >> 2 for c in hole if c & 3 == fsuit), reverse=True)
        on_board = sum(1 for c in board if c & 3 == fsuit)
        if not my_flush:
            made, strength = "flush on board", 1
        else:
            missing_higher = sum(
                1 for r in range(my_flush[0] + 1, 13)
                if all(not (c >> 2 == r and c & 3 == fsuit) for c in board)
            )
            if missing_higher == 0:
                made, strength = "nut flush", 9
            elif on_board >= 4:
                made = f"flush ({_rank_name(my_flush[0])}-high, one card)"
                strength = 6 if missing_higher <= 1 else 4
            else:
                made = f"flush ({_rank_name(my_flush[0])}-high)"
                strength = 8 if missing_higher <= 2 else 7
        if board_paired and strength > 6:
            strength -= 1
    elif cat == 6:
        made, strength = "full house", 9
        if plays_board:
            made, strength = "full house on board", 2
    elif cat == 7:
        made, strength = "four of a kind", 9
        if any(n == 4 for n in board_counts.values()):
            made, strength = "quads on board (kicker plays)", 2 if hr[0] < 12 else 8
    else:
        made, strength = "straight flush", 9

    draws: list[str] = []
    outs = 0
    if len(board) < 5:
        # flush draws
        for s in range(4):
            mine = [c >> 2 for c in hole if c & 3 == s]
            total = len(mine) + suit_counts[s]
            if mine and total == 4 and cat < 5:
                nut = max(mine) == max(
                    r for r in range(13) if all(not (c >> 2 == r and c & 3 == s) for c in board)
                )
                draws.append("nut flush draw" if nut else "flush draw")
                outs += 9
                flags.append("flush_draw")
            elif mine and total == 3 and len(board) == 3 and len(mine) == 2:
                draws.append("backdoor flush draw")
                flags.append("backdoor_fd")
        # straight draws: count ranks that complete a straight using a hole card
        if cat < 4:
            mask = 0
            for c in cards:
                mask |= 1 << (c >> 2)
            bmask = 0
            for c in board:
                bmask |= 1 << (c >> 2)
            completing = []
            for r in range(13):
                if mask & (1 << r):
                    continue
                with_r = mask | (1 << r)
                if STRAIGHT_HI[with_r] >= 0 and STRAIGHT_HI[bmask | (1 << r)] < STRAIGHT_HI[with_r]:
                    completing.append(r)
            if len(completing) >= 2:
                draws.append("open-ended / double-gutter straight draw")
                outs += 8 if "flush_draw" not in flags else 6
                flags.append("oesd")
            elif len(completing) == 1:
                draws.append("gutshot")
                outs += 4 if "flush_draw" not in flags else 3
                flags.append("gutshot")
        if cat == 0:
            overs = sum(1 for r in hr if r > top_board)
            if overs:
                if overs == 1:
                    draws.append("1 overcard")
                outs += 3 * overs if not board_paired else 2 * overs
        elif cat == 1 and strength in (2, 3, 4, 5):
            outs += 5 if not pocket_pair else 2

    texture = board_texture(board)
    return {
        "made": made,
        "category": CATEGORIES[cat],
        "strength": strength,
        "draws": draws,
        "outs": outs,
        "flags": flags,
        "texture": texture,
    }


def board_texture(board) -> dict:
    """Coarse board texture: wetness 0 (dry) .. 3 (very wet) and a label."""
    board = list(board)
    if len(board) < 3:
        return {"wet": 0, "label": "preflop"}
    ranks = sorted((c >> 2 for c in board), reverse=True)
    suits = [0, 0, 0, 0]
    for c in board:
        suits[c & 3] += 1
    maxsuit = max(suits)
    distinct = sorted(set(ranks), reverse=True)
    paired = len(distinct) < len(ranks)
    # connectedness: best count of distinct board ranks inside any 5-rank window
    conn = 0
    lows = set(distinct) | ({-1} if 12 in distinct else set())
    for lo in range(-1, 9):
        conn = max(conn, sum(1 for r in lows if lo <= r <= lo + 4))
    wet = 0
    labels = []
    if maxsuit >= 4:
        wet += 3
        labels.append("four to a flush")
    elif maxsuit == 3:
        wet += 2
        labels.append("monotone" if len(board) == 3 else "three to a flush")
    elif maxsuit == 2 and len(board) <= 4:
        wet += 1
        labels.append("two-tone")
    else:
        labels.append("rainbow")
    if conn >= 4:
        wet += 2
        labels.append("four to a straight")
    elif conn == 3:
        wet += 1
        labels.append("connected")
    if paired:
        labels.append("paired")
    high = RANKS[distinct[0]]
    labels.append(f"{high}-high")
    return {"wet": min(wet, 3), "label": ", ".join(labels), "paired": paired,
            "maxsuit": maxsuit, "high": distinct[0]}
