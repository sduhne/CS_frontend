"""Tight-aggressive preflop charts and opponent range models.

Positions are identified by ``n_behind``: how many players are still to act
after you preflop.  0 = BB, 1 = SB, 2 = BTN, 3 = CO, 4 = HJ, 5 = LJ,
6 = UTG+2, 7 = UTG+1, 8 = UTG (9-max).  That works for any table size:
first to act 6-handed simply has 5 players behind.  Only the names of the
seats before the LJ depend on the table: they count on from the first to act
(``UTG``, ``UTG+1``, ...), so six players behind is UTG+2 nine-handed and
UTG+1 eight-handed.

The charts are deliberately tight from early position and aggressive in late
position, and they are the baseline that stack depth, ICM and player reads
then move.
"""

from __future__ import annotations

from functools import lru_cache

from .cards import COMBO_COUNT, parse_range, range_pct, top_percent
from .equity import allin_order

POSITION_NAMES = {0: "BB", 1: "SB", 2: "BTN", 3: "CO", 4: "HJ", 5: "LJ"}


# Names that mean a fixed number of players behind.  UTG+1, UTG+2, ... are not
# here: they count from the first seat of the table (``preflop.pos_to_index``).
_POSITION_ALIASES = {"bb": 0, "sb": 1, "btn": 2, "bu": 2, "button": 2, "d": 2, "dealer": 2,
                     "co": 3, "cutoff": 3, "hj": 4, "hijack": 4, "mp3": 4, "lj": 5, "lojack": 5,
                     "mp2": 5, "mp": 6, "mp1": 6}


def position_name(n_behind: int, n_players: int) -> str:
    """Seat label for the table view, from the players still to act behind the seat.

    The same names as the sheets (``binary.seat_name``): the seats before the LJ
    are UTG, UTG+1, ... counted from the first to act, so the second of eight
    seats is UTG+1.  Two labels say more than the sheets do: heads-up the first
    seat is ``SB/BTN``, and at 4 to 6 players it is ``UTG(LJ)``, ``UTG(HJ)`` or
    ``UTG(CO)``, first to act with that seat's ranges.
    """
    if n_players == 2:
        return "SB/BTN" if n_behind == 1 else "BB"
    if n_behind >= 3 and n_behind == n_players - 1:
        return "UTG" if n_players >= 7 else f"UTG({POSITION_NAMES[n_behind]})"
    if n_behind in POSITION_NAMES:
        return POSITION_NAMES[n_behind]
    early = n_players - 1 - n_behind               # seats after the first to act
    return f"UTG+{early}" if early > 0 else "UTG"


# Raise-first-in ladder, tightest first.  Index = "tightness level"; a seat
# with n players behind uses level n by default, and reads / ICM shift it.
_RFI_LADDER = {
    11: "JJ+, AKs, AKo",
    10: "TT+, AQs+, AKo",
    9: "88+, ATs+, KJs+, QJs, AQo+",
    8: "77+, ATs+, A5s, KTs+, QTs+, JTs, AJo+, KQo",
    7: "66+, ATs+, A5s-A4s, KTs+, QTs+, JTs, T9s, AJo+, KQo",
    6: "55+, A9s+, A5s-A4s, KTs+, QTs+, JTs, T9s, 98s, AJo+, KQo",
    5: "44+, A8s+, A5s-A3s, K9s+, Q9s+, J9s+, T9s, 98s, 87s, ATo+, KJo+",
    4: "33+, A2s+, K9s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, ATo+, KJo+, QJo",
    3: "22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, A9o+, KTo+, QTo+, JTo",
    2: "22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, "
       "A2o+, K8o+, Q9o+, J9o+, T9o",
    1: "22+, A2s+, K4s+, Q7s+, J7s+, T7s+, 97s+, 86s+, 76s, 65s, A4o+, K9o+, Q9o+, J9o+, T9o",
    0: "22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 95s+, 85s+, 74s+, 64s+, 53s+, "
       "A2o+, K5o+, Q7o+, J8o+, T8o+, 97o+, 87o",
    -1: "80%",
}
_LADDER_MIN, _LADDER_MAX = -1, 11


@lru_cache(maxsize=None)
def _ladder(level: int) -> tuple[float, ...]:
    level = max(_LADDER_MIN, min(_LADDER_MAX, level))
    return tuple(parse_range(_RFI_LADDER[level], list(allin_order())))


def _wider_level(level: int) -> int:
    """Next looser rung.  The SB rung (1) is a side branch, not looser than BTN."""
    if level <= 2:
        return {2: 0, 1: 0}.get(level, level - 1)
    return level - 1


def _shift_level(n_behind: int, shift: int) -> int:
    """Apply a tighten (+) / loosen (-) shift measured in rungs."""
    level = min(n_behind, _LADDER_MAX)
    if shift >= 0:
        if level == 1:  # SB tightens along BTN -> CO -> ...
            return min(_LADDER_MAX, 2 + shift) if shift else 1
        return min(_LADDER_MAX, level + shift)
    for _ in range(-shift):
        level = _wider_level(level)
    return max(_LADDER_MIN, level)


def rfi_range(n_behind: int, eff_bb: float = 100.0, shift: int = 0) -> list[float]:
    """Hero's open-raise range first in.

    ``shift`` tightens (positive) or loosens (negative) by whole rungs.  Below
    about 25bb the speculative part of the range is dropped: those hands are
    either shoves (decided by the solver) or folds.
    """
    weights = list(_ladder(_shift_level(n_behind, shift)))
    if eff_bb <= 25 and n_behind >= 3:
        drop = "98s, 87s, 76s, 65s, 54s, 97s, 86s, 75s, T8s, J8s"
        if n_behind >= 6:
            drop += ", 22-55, T9s"
        elif n_behind >= 4:
            drop += ", 22-33"
        for i, w in enumerate(parse_range(drop)):
            if w:
                weights[i] = 0.0
    return weights


def open_size_bb(eff_bb: float, n_behind: int, has_ante: bool = True) -> float:
    """Standard open size in big blinds."""
    if n_behind == 1:  # SB into the BB, out of position
        return 2.5 if eff_bb < 25 else 3.0
    if eff_bb < 25:
        return 2.0
    if eff_bb < 40:
        return 2.2
    if eff_bb < 70 or has_ante:
        return 2.3 if has_ante else 2.5
    return 3.0


# --------------------------------------------------------------------------
# Opponent models
# --------------------------------------------------------------------------

# open_shift: rungs tighter (+) or looser (-) than a standard TAG opener
# call_adj:   added to the equity an opponent wants before calling an all-in
# icm_aware:  how much of the ICM adjustment they actually apply when calling
#             (1 = perfect bubble discipline, 0 = plays pot odds only)
# shove_mult: multiplier on the width of their equilibrium shoving range
PLAYER_TYPES = {
    "unknown": {"open_shift": 0, "call_adj": 0.00, "shove_mult": 0.90, "icm_aware": 0.50,
                "desc": "no read yet: assume a reasonable regular"},
    "nit": {"open_shift": 2, "call_adj": 0.05, "shove_mult": 0.60, "icm_aware": 0.90,
            "desc": "very tight: only plays strong hands, folds to pressure"},
    "tight": {"open_shift": 1, "call_adj": 0.025, "shove_mult": 0.80, "icm_aware": 0.80,
              "desc": "tight-passive / tight regular"},
    "tag": {"open_shift": 0, "call_adj": 0.00, "shove_mult": 1.00, "icm_aware": 0.75,
            "desc": "solid tight-aggressive regular"},
    "lag": {"open_shift": -1, "call_adj": -0.02, "shove_mult": 1.25, "icm_aware": 0.50,
            "desc": "loose-aggressive: opens and 3-bets wide"},
    "loose": {"open_shift": -1, "call_adj": -0.04, "shove_mult": 1.15, "icm_aware": 0.25,
              "desc": "loose-passive: sees many flops, calls too much"},
    "station": {"open_shift": -1, "call_adj": -0.06, "shove_mult": 1.00, "icm_aware": 0.10,
                "desc": "calling station: rarely folds, rarely bluffs"},
    "maniac": {"open_shift": -2, "call_adj": -0.05, "shove_mult": 1.60, "icm_aware": 0.20,
               "desc": "maniac: raises and shoves far too wide"},
}
_TYPE_ALIASES = {"fish": "loose", "rec": "loose", "reg": "tag", "rock": "nit",
                 "aggro": "lag", "whale": "station", "passive": "loose", "": "unknown"}


def norm_type(ptype: str | None) -> str:
    t = (ptype or "unknown").strip().lower()
    t = _TYPE_ALIASES.get(t, t)
    return t if t in PLAYER_TYPES else "unknown"


def villain_open_range(n_behind: int, ptype: str = "unknown", eff_bb: float = 100.0) -> list[float]:
    """Estimated open-raise range of an opponent from a given seat."""
    shift = PLAYER_TYPES[norm_type(ptype)]["open_shift"]
    return list(_ladder(_shift_level(max(1, n_behind), shift)))


def villain_limp_range(n_behind: int, ptype: str = "unknown") -> list[float]:
    """Open-limping range: mostly the weak-but-playable hands a raiser would skip."""
    level = _shift_level(max(1, n_behind), PLAYER_TYPES[norm_type(ptype)]["open_shift"])
    wide = _ladder(_wider_level(_wider_level(level)))
    strong = parse_range("TT+, AQs+, AKo")
    return [0.25 if s else w for w, s in zip(wide, strong)]


@lru_cache(maxsize=1)
def play_order() -> tuple[int, ...]:
    """Classes ordered the way opening ranges grow (playability, not raw equity)."""
    first_level = {}
    for level in range(_LADDER_MAX, _LADDER_MIN - 1, -1):
        if level == 1:
            continue
        for i, w in enumerate(_ladder(level)):
            if w >= 0.5 and i not in first_level:
                first_level[i] = level
    rank = {h: k for k, h in enumerate(allin_order())}
    return tuple(sorted(range(169), key=lambda h: (-first_level.get(h, -5), rank[h])))


def parse(text: str) -> list[float]:
    """Parse range notation, allowing ``"22%"`` (all-in strength order)."""
    return parse_range(text, list(allin_order()))


def scale_range(order_scores, target_pct: float, prior=None) -> list[float]:
    """Top ``target_pct`` percent of combos by ``order_scores`` (higher is better)."""
    order = sorted(range(169), key=lambda h: -order_scores[h])
    if prior is not None:
        order = [h for h in order if prior[h] > 0]
    return top_percent(target_pct, order)


# --------------------------------------------------------------------------
# Facing an open raise (stacks deep enough that a 3-bet is not all-in)
# --------------------------------------------------------------------------

def opener_category(n_behind: int) -> str:
    if n_behind >= 6:
        return "EP"
    if n_behind >= 4:
        return "MP"
    if n_behind >= 2:
        return "LP"
    return "SB"


_VS_OPEN = {
    ("EP", "IP"): dict(value="QQ+, AKs, AKo", bluff="",
                       call="JJ-77, AQs, AJs, KQs", setmine="66-22",
                       deep="QJs, JTs, T9s"),
    ("EP", "SB"): dict(value="QQ+, AKs, AKo", bluff="", call="JJ-TT, AQs", setmine="", deep=""),
    ("EP", "BB"): dict(value="QQ+, AKs, AKo", bluff="",
                       call="JJ-22, AQs-A2s, KQs-K9s, QJs-Q9s, JTs-J9s, T9s, 98s, 87s, 76s, 65s, "
                            "AQo-AJo, KQo", setmine="", deep=""),
    ("MP", "IP"): dict(value="JJ+, AKs, AKo, AQs", bluff="A5s-A4s",
                       call="TT-77, AJs-ATs, KQs-KJs, QJs, JTs, T9s, AQo", setmine="66-22",
                       deep="98s, 87s"),
    ("MP", "SB"): dict(value="JJ+, AKs, AKo, AQs", bluff="A5s-A4s", call="TT-99, AJs, KQs",
                       setmine="", deep=""),
    ("MP", "BB"): dict(value="JJ+, AKs, AKo, AQs", bluff="A5s-A4s",
                       call="TT-22, AJs-A2s, K8s+, Q9s+, J9s+, T8s+, 97s+, 86s+, 76s, 65s, 54s, "
                            "AQo-ATo, KQo-KJo, QJo", setmine="", deep=""),
    ("LP", "IP"): dict(value="TT+, AQs+, AKo, AQo, AJs, KQs", bluff="A5s-A2s, K9s",
                       call="99-55, ATs, KJs-KTs, QJs-QTs, JTs, T9s, 98s, AJo, KQo", setmine="44-22",
                       deep="87s, 76s"),
    ("LP", "SB"): dict(value="TT+, AJs+, AQo+, KQs", bluff="A5s-A2s, KJs-KTs, QJs, JTs",
                       call="", setmine="", deep=""),
    ("LP", "BB"): dict(value="TT+, AJs+, AQo+, KQs", bluff="A5s-A2s",
                       call="99-22, ATs-A6s, K2s+, Q5s+, J7s+, T7s+, 96s+, 85s+, 75s+, 64s+, 54s, "
                            "AJo-A5o, KQo-K9o, QJo-Q9o, JTo-J9o, T9o", setmine="", deep=""),
    ("SB", "BB"): dict(value="99+, AJs+, AQo+, KQs", bluff="A5s-A2s",
                       call="88-22, ATs-A6s, K2s+, Q4s+, J6s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, "
                            "AJo-A2o, K7o+, Q8o+, J8o+, T8o+, 98o", setmine="", deep=""),
}


@lru_cache(maxsize=None)
def vs_open_chart(opener_n_behind: int, hero_n_behind: int) -> dict:
    """3-bet / call sets for hero facing an open, as 169-weight ranges."""
    ocat = opener_category(opener_n_behind)
    hcat = "BB" if hero_n_behind == 0 else "SB" if hero_n_behind == 1 else "IP"
    if ocat == "SB":
        hcat = "BB"
    raw = _VS_OPEN[(ocat, hcat)]
    return {k: tuple(parse_range(v)) if v else tuple([0.0] * 169) for k, v in raw.items()}


def threebet_range(opener_n_behind: int, ptype: str = "unknown") -> list[float]:
    """Estimated (non all-in) 3-betting range against an open from that seat."""
    ocat = opener_category(opener_n_behind)
    base = {
        "EP": "QQ+, AKs, AKo, JJ:0.5, AQs:0.5, A5s:0.25",
        "MP": "JJ+, AQs+, AKo, TT:0.5, A5s-A4s:0.5, KQs:0.5",
        "LP": "TT+, AJs+, AQo+, KQs, 99:0.5, A5s-A2s:0.75, KJs:0.5, QJs:0.25, 76s:0.25",
        "SB": "TT+, AJs+, AQo+, KQs, 99:0.5, A5s-A2s:0.75, KJs:0.5, K9s:0.25, 87s:0.25",
    }[ocat]
    t = norm_type(ptype)
    if t == "nit":
        base = {"EP": "KK+, AKs:0.5", "MP": "QQ+, AKs", "LP": "JJ+, AKs, AKo",
                "SB": "JJ+, AKs, AKo"}[ocat]
    elif t == "tight":
        base = {"EP": "QQ+, AKs, AKo:0.5", "MP": "QQ+, AKs, AKo", "LP": "JJ+, AQs+, AKo",
                "SB": "JJ+, AQs+, AKo"}[ocat]
    elif t in ("lag", "maniac"):
        base += ", 99-88:0.5, ATs:0.5, KTs:0.5, QTs:0.5, JTs:0.5, T9s:0.5, 98s:0.5, AJo:0.5, KQo:0.5"
        if t == "maniac":
            base += ", 77-55, A9s-A6s, K9s, Q9s, J9s, 87s, 76s, ATo, KJo"
    return parse_range(base)


def describe_pct(weights) -> str:
    return f"{range_pct(weights):.1f}%"


def in_range(weights, hand: int) -> bool:
    return weights[hand] >= 0.5


def combos_in(weights) -> float:
    return sum(w * n for w, n in zip(weights, COMBO_COUNT))
