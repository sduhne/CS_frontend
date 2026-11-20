"""All-In or Fold hold'em: the equilibrium answer for any spot.

In this format every player either moves all-in or folds before the flop, so
the whole game is a small tree: with four players there are 14 decision
points (who you are, and who has already shoved).  ``tools/aof_solver.c``
solves that tree with real cards, multi-way showdowns and the per-hand fee,
and ``data/aof.json`` holds the solutions on a grid of stack sizes.  This
module looks a spot up and interpolates between stack sizes.

Two families are stored:

* ``cash``  - ring game with the 0.1bb fee taken from every pot, 2 to 8bb
  (the table cap);
* ``chips`` - no fee, 2 to 20bb: the baseline for All-In or Fold tournaments
  (no ICM: tighten calls near the money).

Stacks at the table are rarely all equal.  The lookup uses the *effective*
stack: what hero can actually win or lose against the players who matter.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from functools import lru_cache

from .cards import COMBO_COUNT, HANDS, class_of, format_range

_PATH = os.path.join(os.path.dirname(__file__), "data", "aof.json")

POSITIONS = {2: ["SB", "BB"], 3: ["BTN", "SB", "BB"], 4: ["CO", "BTN", "SB", "BB"]}
_ALIASES = {"utg": 0, "ep": 0, "co": "CO", "cutoff": "CO", "btn": "BTN", "bu": "BTN", "button": "BTN",
            "d": "BTN", "dealer": "BTN", "sb": "SB", "bb": "BB"}
FAMILIES = {"cash": "cash", "ring": "cash", "tournament": "chips", "sng": "chips", "chips": "chips",
            "mtt": "chips", "cash-loose": "cash-loose", "cash-vloose": "cash-vloose"}
# who you are up against: solid opponents call correctly (the equilibrium table);
# loose ones shove normally but call 1.5x or 2x too many hands
OPPONENTS = {"solid": "", "loose": "-loose", "very-loose": "-vloose", "vloose": "-vloose"}
FAMILY_LABEL = {"cash": "cash, 0.1bb fee", "chips": "tournament chips, no fee",
                "cash-loose": "cash, 0.1bb fee, opponents call 1.5x too wide",
                "cash-vloose": "cash, 0.1bb fee, opponents call 2x too wide"}
CLOSE_EV = 0.05      # bb: below this, shoving and folding are worth about the same


@lru_cache(maxsize=1)
def _solutions() -> dict:
    with open(_PATH) as fh:
        raw = json.load(fh)
    out = {}
    for sol in raw["solutions"]:
        for node in sol["nodes"].values():
            if "f" not in node:          # best-response tables are pure: shove when it earns
                node["f"] = [100 if e > 0 else 0 for e in node["e"]]
        out[(sol["family"], sol["n"], float(sol["stack"]))] = sol
    out["matrix"] = raw.get("matrix", {})
    return out


def family_for(mode: str = "cash", vs: str | None = None) -> str:
    """Table family for a game mode and an opponent type."""
    fam = FAMILIES.get(mode, mode)
    suffix = OPPONENTS.get((vs or "solid").lower())
    if suffix is None:
        raise ValueError(f"unknown opponent type {vs!r}; use solid, loose or very-loose")
    if suffix and fam != "cash":
        raise ValueError("ranges against loose opponents exist for the cash format only")
    return fam + suffix


def matrix() -> dict:
    """4-handed 8bb: every hero table against every opponent type (bb/100 and swings)."""
    return _solutions().get("matrix", {})


def available() -> bool:
    return os.path.exists(_PATH)


def stack_grid(family: str, n: int) -> list[float]:
    return sorted(k[2] for k in _solutions() if isinstance(k, tuple) and k[0] == family and k[1] == n)


def opponent_freq(family: str, n: int, stack: float, key: str) -> list[float]:
    """How the *other* players act at a decision point (used to deal drill spots)."""
    grid = stack_grid(family, n)
    near = min(grid, key=lambda g: abs(g - stack))
    node = _solutions()[(family, n, near)]["nodes"][key]
    if "o" in node:
        return [1.0 if ch == "1" else 0.0 for ch in node["o"]]
    return [f / 100.0 for f in node["f"]]


def position_index(name: str, n: int) -> int:
    """Index in acting order of a seat name at an ``n``-handed table."""
    if n not in POSITIONS:
        raise ValueError(f"All-In or Fold tables are solved for 2 to 4 players, not {n}")
    low = name.strip().lower()
    seat = _ALIASES.get(low)
    if seat == 0:
        return 0
    if n == 2 and low in ("btn", "bu", "button", "d", "dealer"):
        return 0                                   # heads-up the button is the small blind
    if seat is None or seat not in POSITIONS[n]:
        raise ValueError(f"no seat {name!r} at a {n}-handed table (seats: {', '.join(POSITIONS[n])})")
    return POSITIONS[n].index(seat)


def parse_shovers(text: str | None, n: int, hero: int) -> int:
    """Bitmask of the players who are already all-in, from ``"CO, BTN"``."""
    mask = 0
    for tok in (text or "").replace(",", " ").replace("+", " ").split():
        if tok.lower() in ("none", "nobody", "-"):
            continue
        k = position_index(tok, n)
        if k >= hero:
            raise ValueError(f"{tok.upper()} acts after {POSITIONS[n][hero]}, so cannot have shoved before you")
        mask |= 1 << k
    return mask


def _interp(family: str, n: int, stack: float, key: str) -> tuple[list[float], list[float], float]:
    """Shove EV (bb) and equilibrium frequency per class at a decision point."""
    grid = stack_grid(family, n)
    if not grid:
        raise ValueError(f"no {family} solution for {n} players")
    s = max(grid[0], min(grid[-1], stack))
    lo = max(g for g in grid if g <= s)
    hi = min(g for g in grid if g >= s)
    a = _solutions()[(family, n, lo)]["nodes"][key]
    if hi == lo:
        return [e / 100.0 for e in a["e"]], [f / 100.0 for f in a["f"]], s
    b = _solutions()[(family, n, hi)]["nodes"][key]
    t = (s - lo) / (hi - lo)
    ev = [(x + (y - x) * t) / 100.0 for x, y in zip(a["e"], b["e"])]
    fr = [(x + (y - x) * t) / 100.0 for x, y in zip(a["f"], b["f"])]
    return ev, fr, s


def effective_stack(stacks: list[float], hero: int, mask: int) -> float:
    """What hero plays for: capped by the biggest stack that can contest the pot."""
    if mask:
        other = max(stacks[k] for k in range(hero) if (mask >> k) & 1)
    else:
        behind = stacks[hero + 1:]
        other = max(behind) if behind else stacks[hero]
    return min(stacks[hero], other)


@dataclass
class Answer:
    action: str                 # ALL-IN or FOLD
    confidence: str             # clear | standard | close
    ev: float                   # bb earned by shoving instead of folding
    freq: float                 # how often the equilibrium shoves this hand here
    hand: str
    seat: str
    n: int
    shovers: list[str]
    stack: float                # effective stack used
    family: str
    range_weights: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def range_pct(self) -> float:
        return 100.0 * sum(w * c for w, c in zip(self.range_weights, COMBO_COUNT)) / 1326.0

    def render(self) -> str:
        vs = f"{' and '.join(self.shovers)} all-in" if self.shovers else "folded to you"
        fam = FAMILY_LABEL.get(self.family, self.family)
        verb = "calls" if self.shovers else "shoves"
        who = "the equilibrium" if self.family in ("cash", "chips") else "the best reply"
        lines = [
            f">>> {self.action}   [{self.confidence}]",
            f"{self.hand} in {self.seat}, {self.n}-handed, {self.stack:g}bb effective, {vs} | {fam}",
            f"  num: shoving earns {self.ev:+.2f}bb compared with folding",
            f"  num: {who} {verb} {self.range_pct:.1f}% of hands here "
            f"[{format_range(self.range_weights)}]",
        ]
        lines += [f"  !!   {n}" for n in self.notes]
        return "\n".join(lines)


def node_range(family: str, n: int, hero: int, mask: int, stack: float) -> tuple[list[float], list[float], float]:
    """Range at a decision point: weights (1 shove, 0.5 too close to call, 0 fold) and EVs."""
    ev, _, used = _interp(family, n, stack, f"{hero}:{mask}")
    weights = [1.0 if e > CLOSE_EV else 0.5 if e > -CLOSE_EV else 0.0 for e in ev]
    return weights, ev, used


def decide(hand: int, n: int, hero: int, mask: int = 0, stacks: list[float] | None = None,
           family: str = "cash") -> Answer:
    """The equilibrium decision for one hand at one decision point."""
    family = FAMILIES.get(family, family)
    if n not in POSITIONS:
        raise ValueError(f"All-In or Fold tables are solved for 2 to 4 players, not {n}")
    if hero == n - 1 and mask == 0:
        raise ValueError("everyone folded to the big blind: you win the pot, there is nothing to decide")
    stacks = list(stacks) if stacks else [8.0] * n
    if len(stacks) != n:
        raise ValueError(f"need {n} stacks, got {len(stacks)}")
    eff = effective_stack(stacks, hero, mask)
    ev, freq, used = _interp(family, n, eff, f"{hero}:{mask}")
    e = ev[hand]
    weights = [1.0 if x > 0 else 0.0 for x in ev]
    notes = []
    if abs(used - eff) > 1e-9:
        notes.append(f"stack {eff:g}bb is outside the solved range; answered for {used:g}bb")
    if len({round(s, 2) for s in stacks}) > 1:
        notes.append("stacks differ: answered for the effective stack, an approximation")
    if family == "chips":
        notes.append("chip EV only: near the money, call all-ins tighter than this")
    if family in ("cash-loose", "cash-vloose"):
        notes.append("assumes every opponent calls too wide; against solid players use the solved table")
    conf = "clear" if abs(e) >= 0.25 else "standard" if abs(e) >= CLOSE_EV else "close"
    names = POSITIONS[n]
    return Answer(action="ALL-IN" if e > 0 else "FOLD", confidence=conf, ev=e, freq=freq[hand],
                  hand=HANDS[hand], seat=names[hero], n=n,
                  shovers=[names[k] for k in range(hero) if (mask >> k) & 1],
                  stack=used, family=family, range_weights=weights, notes=notes)


def decision_points(n: int) -> list[tuple[int, int]]:
    """Every (player, shovers-mask) where a decision exists, in table order."""
    return [(i, m) for i in range(n) for m in range(1 << i) if not (i == n - 1 and m == 0)]


def describe_point(n: int, hero: int, mask: int) -> str:
    names = POSITIONS[n]
    sh = [names[k] for k in range(hero) if (mask >> k) & 1]
    return f"{names[hero]} - " + ("folded to you" if not sh else " and ".join(sh) + " all-in")


def table_value(family: str, n: int, stack: float) -> list[float] | None:
    sol = _solutions().get((family, n, float(stack)))
    return sol["value"] if sol else None


def sheet(n: int = 4, stack: float = 8.0, family: str = "cash") -> str:
    """Every range of the format as Markdown."""
    family = FAMILIES.get(family, family)
    fam = FAMILY_LABEL.get(family, family)
    out = [f"## {n}-handed, {stack:g}bb ({fam})", "",
           "| Seat | Situation | Shove / call | Range |", "|---|---|---|---|"]
    names = POSITIONS[n]
    for hero, mask in decision_points(n):
        weights, ev, _ = node_range(family, n, hero, mask, stack)
        solid = [1.0 if w >= 1.0 else 0.0 for w in weights]
        close = [HANDS[c] for c in range(169) if weights[c] == 0.5]
        pct = 100.0 * sum(w * c for w, c in zip([1.0 if e > 0 else 0.0 for e in ev], COMBO_COUNT)) / 1326.0
        sh = [names[k] for k in range(hero) if (mask >> k) & 1]
        rng = format_range(solid)
        if close:
            rng += f" *(coin flips: {', '.join(close)})*"
        out.append(f"| {names[hero]} | {'folded to you' if not sh else ' + '.join(sh) + ' all-in'} "
                   f"| {pct:.0f}% | {rng} |")
    val = table_value(family, n, stack)
    if val and family in ("cash", "chips"):
        per = ", ".join(f"{names[k]} {v:+.2f}" for k, v in enumerate(val))
        out += ["", f"Average result per hand when everyone plays this way (bb): {per}; "
                    f"together {sum(val):+.2f}, which is the fee."]
    elif val:
        per = ", ".join(f"{names[k]} {v:+.2f}" for k, v in enumerate(val))
        out += ["", f"Your average result per hand against these opponents (bb): {per}; "
                    f"overall {100 * sum(val) / len(val):+.1f}bb per 100 hands."]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Drills
# --------------------------------------------------------------------------

@dataclass
class Spot:
    n: int
    hero: int
    mask: int
    hand: int
    stack: float
    family: str

    def question(self) -> str:
        return f"{describe_point(self.n, self.hero, self.mask)}. You hold {HANDS[self.hand]}."

    def answer(self) -> Answer:
        return decide(self.hand, self.n, self.hero, self.mask, [self.stack] * self.n, self.family)


def random_spot(rng: random.Random, n: int = 4, stack: float = 8.0, family: str = "cash",
                hard: float = 0.75) -> Spot:
    """Deal a real hand, let the earlier players act by the equilibrium, and stop at hero.

    With probability ``hard`` the spot is redrawn until hero's hand is a real
    decision (within 0.5bb of break-even), so drills are not all 72o folds.
    """
    family = FAMILIES.get(family, family)
    want_hard = rng.random() < hard
    for _ in range(4000):
        deck = list(range(52))
        rng.shuffle(deck)
        classes = [class_of(deck[2 * k], deck[2 * k + 1]) for k in range(n)]
        # later seats have more situations to learn, so they come up more often
        hero = rng.choices(range(n), weights=[k + 1 for k in range(n)])[0]
        mask = 0
        for k in range(hero):
            freq = opponent_freq(family, n, stack, f"{k}:{mask & ((1 << k) - 1)}")
            if rng.random() < freq[classes[k]]:
                mask |= 1 << k
        if hero == n - 1 and mask == 0:
            continue
        ev, _, _ = _interp(family, n, stack, f"{hero}:{mask}")
        if want_hard and abs(ev[classes[hero]]) > 0.5:
            continue
        return Spot(n, hero, mask, classes[hero], stack, family)
    raise RuntimeError("could not draw a spot")
