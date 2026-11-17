"""All-in or fold for 3-player winner-take-all sit & gos ("spins").

Three players, one prize in the common games: chips are money, there is no
ICM, and the exact all-in or fold solution of the chip game is the right
table.  That makes these tables much wider than the tournament ones in
``binary``, which carry a survival premium a spin does not have.

``data/spin.json`` (``tools/build_spin.py``) holds, for three players and for
heads-up, at stacks of 2 to 30 big blinds:

* ``solid``: the solved table (nobody can do better against it);
* ``loose`` / ``vloose``: the best reply to opponents who shove normally but
  call 1.5 times / twice too many hands;
* what each of those earns against each kind of opponent, in big blinds a hand;
* the hands that move all-in over a limp or a small raise.

Seats: ``BTN``, ``SB``, ``BB`` three-handed; ``SB`` (the button) and ``BB``
heads-up.  Stacks are effective: the smaller of yours and the biggest stack
that can still call.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from .cards import COMBO_COUNT, HAND_INDEX, HANDS, format_range, parse_range

_PATH = os.path.join(os.path.dirname(__file__), "data", "spin.json")
DATA_VERSION = 1

STACKS = (2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30)          # big blinds the game is solved at
PROFILES = {"solid": 1.0, "loose": 1.5, "vloose": 2.0}         # how many times too wide the opponents call
PROFILE_NAMES = {"solid": "players who call correctly", "loose": "players who call 1.5 times too wide",
                 "vloose": "players who call twice too wide"}
# the opponents of the whole-game simulation (tools/spin_sim.py)
SIM_OPPONENTS = {"solid": "They call correctly", "loose": "They call 1.5 times too wide",
                 "vloose": "They call twice too wide",
                 "passive": "They call 1.5 times too wide and move all-in half as often"}
# stack bands of the printed tables: (label, stack the column is read at)
BANDS = (("up to 5bb", 4), ("6 to 8bb", 7), ("9 to 12bb", 10), ("13 to 17bb", 15), ("18 to 24bb", 20), ("25bb or more", 30))

# (players, seat, who is already all-in) -> the solver's key, and how the row reads
SPOTS = {
    "btn": (3, "0:0", "BTN, nobody has entered", "all-in"),
    "sb": (3, "1:0", "SB, the button folded", "all-in"),
    "sb_vs_btn": (3, "1:1", "SB, the button is all-in", "call"),
    "bb_vs_btn": (3, "2:1", "BB, the button is all-in", "call"),
    "bb_vs_sb": (3, "2:2", "BB, the small blind is all-in", "call"),
    "bb_vs_both": (3, "2:3", "BB, both are all-in", "call"),
    "hu_sb": (2, "0:0", "SB (button), first to act", "all-in"),
    "hu_bb": (2, "1:1", "BB, the small blind is all-in", "call"),
}

# a limp or a small raise in front: (players, opener's players behind, hero's players behind,
# chips the opener has in front in big blinds, share of hands the opener does that with, label)
OPENERS = {
    "sb_vs_btn_raise": (3, 2, 1, 2.0, 45.0, "SB, the button raised small"),
    "bb_vs_btn_raise": (3, 2, 0, 2.0, 45.0, "BB, the button raised small"),
    "bb_vs_sb_raise": (3, 1, 0, 2.0, 55.0, "BB, the small blind raised small"),
    "bb_vs_sb_limp": (3, 1, 0, 1.0, 70.0, "BB, the small blind limped"),
    "hu_bb_vs_raise": (2, 1, 0, 2.0, 60.0, "BB, the small blind raised small"),
    "hu_bb_vs_limp": (2, 1, 0, 1.0, 75.0, "BB, the small blind limped"),
}


# GGPoker Spin & Gold, three players: (multiplier, share of games, prizes in buy-ins for 1st, 2nd, 3rd).
# From ggpoker.com/poker-games/spin-gold in November 2026, $1 to $10 games (the jackpot row differs by buy-in).
FEE = 0.07
PRIZES = (
    (2, 0.4786394, (2.0, 0.0, 0.0)),
    (3, 0.4462404, (3.0, 0.0, 0.0)),
    (4, 0.0265, (4.0, 0.0, 0.0)),
    (5, 0.025, (5.0, 0.0, 0.0)),
    (10, 0.0235, (8.0, 2.0, 0.0)),
    (50, 0.00008, (30.0, 15.0, 5.0)),
    (100, 0.00004, (60.0, 30.0, 10.0)),
    (100000, 0.0000002, (50000.0, 30000.0, 20000.0)),
)


def average_prizes(jackpot: bool = True) -> tuple[float, float, float]:
    """What 1st, 2nd and 3rd place are worth on average, in buy-ins."""
    rows = PRIZES if jackpot else PRIZES[:-1]
    return tuple(sum(share * pays[i] for _m, share, pays in rows) for i in range(3))


def roi(win: float, jackpot: bool = True) -> float:
    """Return per game (0.05 = 5% of a buy-in) for a player who wins ``win`` of the games.

    The games not won are split evenly between second and third place, which
    only matters in the 2.4% of games that pay more than one place.
    """
    first, second, third = average_prizes(jackpot)
    return win * first + (1.0 - win) * (second + third) / 2.0 - 1.0


def break_even(jackpot: bool = True) -> float:
    """The share of games a player has to win to get the buy-ins back."""
    first, second, third = average_prizes(jackpot)
    rest = (second + third) / 2.0
    return (1.0 - rest) / (first - rest)


def sim() -> dict:
    """Whole games played with these tables (tools/spin_sim.py), or {} if it was not run."""
    return data().get("sim", {})


def simulated_win(hero: str = "sheet", opp: str = "solid") -> float | None:
    """Share of games won in the simulation, over the five common game types by how often they come."""
    res = sim()
    if not res:
        return None
    total = weight = 0.0
    for name, st in res["structures"].items():
        cell = res["results"].get(name, {}).get(f"{hero}|{opp}")
        if cell:
            total += st["share"] * cell[0]
            weight += st["share"]
    return total / weight / 100.0 if weight else None


def simulated_roi(hero: str = "sheet", opp: str = "solid") -> float | None:
    """Return per game in the simulation, each kind of game with its own win rate and prizes."""
    res = sim()
    if not res:
        return None
    total = 0.0
    for mult, share, pays in PRIZES:
        name = f"x{mult}" if f"x{mult}" in res["results"] else "x10"      # the rare deep games: as x10
        w = res["results"][name][f"{hero}|{opp}"][0] / 100.0
        total += share * (w * pays[0] + (1.0 - w) / 2.0 * (pays[1] + pays[2]))
    return total - 1.0


# with this stack or less a small raise has committed the raiser: answer it as an all-in
COMMITTED_BB = 5.5
AS_ALLIN = {"sb_vs_btn_raise": "sb_vs_btn", "bb_vs_btn_raise": "bb_vs_btn", "bb_vs_sb_raise": "bb_vs_sb",
            "hu_bb_vs_raise": "hu_bb"}


@lru_cache(maxsize=1)
def data() -> dict:
    with open(_PATH) as fh:
        d = json.load(fh)
    if d.get("version") != DATA_VERSION:
        raise RuntimeError("data/spin.json is out of date: run python3 tools/build_spin.py")
    return d


def tidy(ev: list[float]) -> list[int]:
    """The range (0 or 1 per hand) that plays every hand worth playing, without gaps.

    The solver's answers for hands worth about nothing are noise, which prints
    as ranges like "K9s+, K7s".  Within each family (pairs, suited or offsuit
    hands with the same high card) this keeps the hands from the best kicker
    down to the cut that earns the most, so every family reads "K9s+".
    """
    out = [0] * 169
    families = [[i * 14 for i in range(13)]]
    for r in range(12):
        families.append([r * 13 + c for c in range(r + 1, 13)])          # suited
        families.append([c * 13 + r for c in range(r + 1, 13)])          # offsuit
    for fam in families:
        best, keep, total = 0.0, 0, 0.0
        for k, h in enumerate(fam, 1):
            total += ev[h]
            if total > best + 1e-9:
                best, keep = total, k
        for h in fam[:keep]:
            out[h] = 1
    return out


def nearest(stack_bb: float) -> int:
    """The solved stack closest to an effective stack (clamped to the grid)."""
    return min(STACKS, key=lambda s: (abs(s - stack_bb), s))


def band(stack_bb: float) -> int:
    tops = (5.5, 8.5, 12.5, 17.5, 24.5)
    for i, top in enumerate(tops):
        if stack_bb <= top:
            return i
    return len(tops)


def play(spot: str, stack_bb: float, vs: str = "solid") -> list[float]:
    """The range (weights 0 or 1) for a spot at the solved stack nearest to ``stack_bb``."""
    n, key, _label, _verb = SPOTS[spot]
    text = data()["games"][str(n)][f"{nearest(stack_bb):g}"]["play"][_profile(vs)][key]
    return [1.0 if c == "1" else 0.0 for c in text]


def edge(spot: str, stack_bb: float, hand: int | str, vs: str = "solid") -> float:
    """Big blinds the play earns over folding with this hand."""
    n, key, _label, _verb = SPOTS[spot]
    h = HAND_INDEX[hand] if isinstance(hand, str) else hand
    return data()["games"][str(n)][f"{nearest(stack_bb):g}"]["ev"][_profile(vs)][key][h] / 100.0   # stored in 0.01bb


def rows(vs: str = "solid") -> dict[str, list[str]]:
    """Every spot as text, one range per stack band (the printed table)."""
    return {spot: [format_range(play(spot, s, vs)) or "nothing" for _b, s in BANDS] for spot in SPOTS}


def raise_rows() -> dict[str, list[str]]:
    return data()["raise"]


def value(n: int, stack_bb: float, hero: str, opp: str) -> float:
    """Big blinds a hand that ``hero``'s table earns against ``opp`` opponents, averaged over the seats."""
    v = data()["games"][str(n)][f"{nearest(stack_bb):g}"]["value"][f"{_profile(hero)}|{_profile(opp)}"]
    return sum(v) / n


def width(spot: str, stack_bb: float, vs: str = "solid") -> float:
    return 100.0 * sum(c for c, w in zip(COMBO_COUNT, play(spot, stack_bb, vs)) if w) / 1326.0


def _profile(vs: str | None) -> str:
    p = {"solid": "solid", "": "solid", "none": "solid", "loose": "loose", "very-loose": "vloose",
         "vloose": "vloose"}.get(str(vs or "solid").lower())
    if p is None:
        raise ValueError(f"opponents are solid, loose or very-loose, not {vs!r}")
    return p


def decide(hand: int, spot: str, stack_bb: float, vs: str = "solid") -> tuple[str, str]:
    """(ALL-IN / CALL / FOLD / CHECK, the reason) for a spot of SPOTS or OPENERS."""
    name = HANDS[hand]
    if spot in AS_ALLIN and stack_bb <= COMMITTED_BB:
        action, why = decide(hand, AS_ALLIN[spot], stack_bb, vs)
        return action, f"a raise from a stack this short is an all-in. {why}"
    if spot in SPOTS:
        _n, _key, label, verb = SPOTS[spot]
        ok = play(spot, stack_bb, vs)[hand] >= 0.5
        e = edge(spot, stack_bb, hand, vs)
        action = ("ALL-IN" if verb == "all-in" else "CALL") if ok else "FOLD"
        close = ", close to a coin flip" if abs(e) < 0.05 else ""
        return action, (f"{label}, {stack_bb:g}bb effective: {name} earns {e:+.2f}bb against folding{close} "
                        f"(table read at {nearest(stack_bb)}bb, against {PROFILE_NAMES[_profile(vs)]})")
    if spot in OPENERS:
        label = OPENERS[spot][5]
        rng = raise_rows()[spot][band(stack_bb)]
        ok = parse_range(rng)[hand] >= 0.5
        fold = "CHECK" if spot.endswith("limp") else "FOLD"
        return ("ALL-IN" if ok else fold), f"{label}, {BANDS[band(stack_bb)][0]}: all-in with {rng}"
    raise ValueError(f"unknown spot {spot!r}: one of {', '.join(list(SPOTS) + list(OPENERS))}")


def sheet_text(vs: str = "solid") -> str:
    out = [f"SPINS: ALL-IN OR FOLD, three players and heads-up (against {PROFILE_NAMES[_profile(vs)]})", ""]
    table = rows(vs)
    for title, spots in (("THREE PLAYERS", [s for s in SPOTS if SPOTS[s][0] == 3]),
                         ("HEADS-UP", [s for s in SPOTS if SPOTS[s][0] == 2])):
        out.append(title)
        for spot in spots:
            out.append(f"  {SPOTS[spot][2]}: {SPOTS[spot][3]} with")
            for (b, _s), rng in zip(BANDS, table[spot]):
                out.append(f"    {b:<13} {rng}")
        out.append("")
    out.append("A LIMP OR A SMALL RAISE BEFORE YOU: all-in with (otherwise fold, or check a limp)")
    for spot, row in raise_rows().items():
        out.append(f"  {OPENERS[spot][5]} ({'three players' if OPENERS[spot][0] == 3 else 'heads-up'})")
        for (b, _s), rng in zip(BANDS, row):
            out.append(f"    {b:<13} {rng}")
    return "\n".join(out)
