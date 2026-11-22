"""Tight-aggressive preflop charts and opponent range models.

Positions are identified by ``n_behind``: how many players are still to act
after you preflop.  0 = BB, 1 = SB, 2 = BTN, 3 = CO, 4 = HJ, 5 = LJ; the seats
before those are UTG, UTG+1, UTG+2 counted from the first to act.  That works
for any table size: first to act 6-handed simply has 5 players behind.
``SEAT_LABELS`` is the one table of seat names for the whole program.

The charts are deliberately tight from early position and aggressive in late
position, and they are the baseline that stack depth, ICM and player reads
then move.
"""

from __future__ import annotations

from functools import lru_cache

from .cards import COMBO_COUNT, parse_range, range_pct, top_percent
from .equity import allin_order

# Seat names by table size, in the order the seats act before the flop.
# Every module that prints or reads a seat name goes through this table
# (``position_name`` below, ``preflop.pos_to_index`` the other way round).
SEAT_LABELS = {
    2: ["BTN/SB", "BB"],                 # heads-up the button posts the small blind and acts first
    3: ["BTN", "SB", "BB"],
    4: ["CO", "BTN", "SB", "BB"],
    5: ["HJ", "CO", "BTN", "SB", "BB"],
    6: ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
    7: ["UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    8: ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    9: ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
}


_POSITION_ALIASES = {"bb": 0, "sb": 1, "btn": 2, "bu": 2, "button": 2, "d": 2, "dealer": 2,
                     "co": 3, "cutoff": 3, "hj": 4, "hijack": 4, "mp3": 4, "lj": 5, "lojack": 5,
                     "mp2": 5, "utg+2": 6, "utg2": 6, "mp": 6, "mp1": 6, "utg+1": 7, "utg1": 7}


def position_name(n_behind: int, n_players: int) -> str:
    """Name of the seat with ``n_behind`` players still to act behind it (0 = big blind)."""
    labels = SEAT_LABELS.get(n_players)
    index = n_players - 1 - n_behind              # 0 = first to act before the flop
    if labels and 0 <= index < n_players:
        return labels[index]
    # outside the table (one player, or more than nine): the same rule, spelled out
    late = {0: "BB", 1: "SB", 2: "BTN", 3: "CO", 4: "HJ", 5: "LJ"}
    if n_behind in late:
        return late[n_behind]
    return "UTG" if index <= 0 else f"UTG+{index}"


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


# --------------------------------------------------------------------------
# The style of the charts
# --------------------------------------------------------------------------
# "tag": the tight-aggressive rows above.  It is the coach's default everywhere (the command line, the
#        table app, the sheets), and nothing changes it there.
# "win": the rows of a modern raise-first-in chart with antes in play, a few points wider in every seat
#        (every row holds the tight row of its seat), and the same rows for the opponents.  The quick
#        guide's tables are built with it (tools/build_guide.py).
# The style is set for a whole run (``use_style``), not per spot.

STYLES = ("tag", "win", "tight")         # tag: the default.  win and tight are the quick guide's two styles:
                                        # win has the wider rows; tight has the default rows, and both
                                        # use the guide's test for the big blind's call (preflop.bb_realised)
_style = "tag"

# By players behind (8 = first to act at a full table of nine ... 2 = button, 1 = small blind), then two
# wider rungs for a steal against tight blinds.  Percent of hands: 13, 17, 20, 23, 27, 36, 49; the small
# blind 50; the wider rungs 64 and 80.
_RFI_WIN = {
    8: "55+, A9s+, A5s-A3s, KTs+, QTs+, J9s+, T9s, 98s, AJo+, KQo",
    7: "44+, A7s+, A5s-A2s, K9s+, Q9s+, J9s+, T9s, 98s, 87s, ATo+, KJo+",
    6: "33+, A2s+, K8s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, ATo+, KJo+, QJo",
    5: "22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, ATo+, KTo+, QJo",
    4: "22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 76s, 65s, 54s, A9o+, KTo+, QTo+, JTo",
    3: "22+, A2s+, K2s+, Q6s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, A7o+, A5o, K9o+, Q9o+, J9o+, T9o",
    2: "22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 95s+, 85s+, 74s+, 64s+, 53s+, A2o+, K7o+, Q8o+, J8o+, T8o+, 98o, 87o",
    1: "22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A2o+, K5o+, Q8o+, J8o+, T8o+, 98o",
    0: "22+, A2s+, K2s+, Q2s+, J2s+, T4s+, 95s+, 84s+, 74s+, 63s+, 53s+, 43s, A2o+, K2o+, Q5o+, J7o+, T7o+, "
       "97o+, 86o+, 76o",
    -1: "80%",
}
_WIN_ORDER = (8, 7, 6, 5, 4, 3, 2, 0, -1)       # tightest first; the small blind's row (1) is a side branch


def style() -> str:
    return _style


def set_style(name: str) -> str:
    """Choose the charts for this run; returns the style that was set before."""
    global _style
    if name not in STYLES:
        raise ValueError(f"unknown style {name!r}: one of {', '.join(STYLES)}")
    before, _style = _style, name
    return before


class use_style:
    """``with use_style("win"): ...`` and the style is put back afterwards."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __enter__(self):
        self.before = set_style(self.name)
        return self

    def __exit__(self, *exc) -> None:
        set_style(self.before)


@lru_cache(maxsize=None)
def _win_rung(level: int) -> tuple[float, ...]:
    return tuple(parse_range(_RFI_WIN[level], list(allin_order())))


def _win_row(n_behind: int, shift: int) -> tuple[float, ...]:
    """The "win" row of a seat, ``shift`` rungs tighter (+) or looser (-)."""
    if n_behind <= 1 and shift == 0:
        return _win_rung(1)
    # the small blind tightens along button -> cutoff ..., and loosens to the two wide rungs
    at = _WIN_ORDER.index(2 if n_behind <= 1 else min(8, n_behind))
    if n_behind <= 1 and shift > 0:
        shift -= 1                              # one notch tighter than the small blind's row is the button's
    at = max(0, min(len(_WIN_ORDER) - 1, at - shift))
    return _win_rung(_WIN_ORDER[at])


def _row(n_behind: int, shift: int) -> tuple[float, ...]:
    """A seat's raise-first-in row in the style of this run."""
    if _style == "win":
        return _win_row(n_behind, shift)
    return _ladder(_shift_level(n_behind, shift))


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
    weights = list(_row(n_behind, shift))
    if eff_bb <= 25 and n_behind >= 3:
        drop = "98s, 87s, 76s, 65s, 54s, 97s, 86s, 75s, T8s, J8s"
        if _style == "win":             # the wider rows hold more of them: every small suited hand goes
            drop += ", J7s-J2s, T7s-T2s, 96s-92s, 85s-82s, 74s-72s, 64s-62s, 53s-52s, 43s-42s, 32s"
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
    return list(_row(max(1, n_behind), shift))


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


# The looser style's chart against a raise.  Only the rows that differ are written: the big blind's rows
# are the tight style's (its calls go by the price), and so is the raise from the small blind.  "LATE" is
# the cutoff and the button, where a call has few players left to act behind it; the seats before them
# ("IP") keep close to the tight lists.  The widths are about half-way from the tight chart to a solver's
# (button against a raise from the first seat, 100bb: 9% tight, 13% here, 25% a solver): a solver's calls
# in position need a solver's play after the flop.
_VS_OPEN_WIN = {
    ("EP", "IP"): dict(value="QQ+, AKs, AKo", bluff="A5s",
                       call="JJ-77, AQs, AJs, KQs", setmine="66-22",
                       deep="ATs, KJs, QJs, JTs, T9s"),
    ("EP", "LATE"): dict(value="QQ+, AKs, AKo", bluff="A5s-A4s",
                         call="JJ-66, AQs-ATs, KQs-KJs, QJs, JTs, AQo", setmine="55-22",
                         deep="KTs, QTs, T9s, 98s, 87s, KQo"),
    ("MP", "LATE"): dict(value="JJ+, AKs, AKo, AQs", bluff="A5s-A3s, KTs",
                         call="TT-66, AJs-A9s, KQs-KJs, QJs-QTs, JTs, T9s, 98s, AQo, KQo", setmine="55-22",
                         deep="87s, 76s, K9s, J9s, AJo"),
    ("MP", "SB"): dict(value="JJ+, AKs, AKo, AQs", bluff="A5s-A4s, KJs", call="TT-99, AJs, KQs",
                       setmine="", deep=""),
    ("LP", "LATE"): dict(value="TT+, AJs+, AQo+, KQs", bluff="A5s-A2s, K9s, Q9s, J9s, T8s",
                         call="99-44, ATs-A8s, KJs-KTs, QJs-QTs, JTs, T9s, 98s, 87s, AJo, KQo, KJo",
                         setmine="33-22", deep="76s, 65s, K8s, ATo, QJo"),
    ("LP", "SB"): dict(value="TT+, AJs+, AQo+, KQs", bluff="A5s-A2s, ATs, KJs-KTs, QJs, JTs, T9s, 99",
                       call="", setmine="", deep=""),
}


@lru_cache(maxsize=None)
def _vs_open_chart(style_name: str, opener_n_behind: int, hero_n_behind: int) -> dict:
    ocat = opener_category(opener_n_behind)
    hcat = "BB" if hero_n_behind == 0 else "SB" if hero_n_behind == 1 else "IP"
    if ocat == "SB":
        hcat = "BB"
    raw = _VS_OPEN[(ocat, hcat)]
    if style_name == "win":
        late = "LATE" if hcat == "IP" and hero_n_behind <= 3 else hcat
        raw = _VS_OPEN_WIN.get((ocat, late)) or _VS_OPEN_WIN.get((ocat, hcat)) or raw
    return {k: tuple(parse_range(v)) if v else tuple([0.0] * 169) for k, v in raw.items()}


def vs_open_chart(opener_n_behind: int, hero_n_behind: int) -> dict:
    """3-bet / call sets for hero facing an open, as 169-weight ranges (of the style in use)."""
    return _vs_open_chart(_style, opener_n_behind, hero_n_behind)


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
