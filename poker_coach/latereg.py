"""Late-registration min-cash system.

The plan: buy in at the very end of late registration, play shove-or-fold with
one objective (reach the first paid place), and stop playing as soon as the
stack can be blinded down safely until the bubble bursts.

Three questions decide whether a tournament suits the plan, and this module
answers each with numbers:

1. **How long until the money?**  ``forecast`` estimates how many hands pass
   before the field shrinks from ``remaining`` to ``paid`` players.
2. **What does waiting cost?**  ``fold_cost`` adds up the blinds and antes a
   folding player pays over those hands while the levels go up.
3. **How often does the best shove-or-fold play get there?**  ``solve`` runs a
   dynamic programme over (hand number, seat, stack): every hand the hero
   either folds or moves all-in, choosing whatever maximises the chance of
   being alive when the bubble bursts.

Units: stacks are in big blinds *at the moment of entry* (``bb0``) inside the
solver, and in current big blinds everywhere a person reads them.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, replace
from functools import lru_cache

from .cards import COMBO_COUNT, HANDS, format_range, range_pct
from .icm import Prizes, default_payouts, hero_equity
from .pushfold import HandSetup, build_shove_spot, solve_shove
from .ranges import villain_open_range

SB, BB, BB_ANTE = 0.5, 1.0, 1.0
ORBIT_COST = SB + BB + BB_ANTE          # big blinds a folding player pays per orbit (8-handed)
PLAYER_ANTE = 0.125                     # GGPoker: every player antes 12.5% of the big blind each hand
DEPTHS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0,
          25.0, 30.0, 40.0)
OPEN_RAISE = 2.1                        # what opponents raise to, in big blinds
_WEIGHT = [c / 1326.0 for c in COMBO_COUNT]

# Tournament speeds: hands dealt per blind level at one table, and how fast the
# blinds grow.  ``bust`` is the constant of the elimination model (see Field).
SPEEDS = {
    "hyper": {"hands_per_level": 3.5, "growth": 1.22, "label": "hyper turbo (3 min levels)"},
    "turbo": {"hands_per_level": 6.5, "growth": 1.20, "label": "turbo (5-6 min levels)"},
    "fast": {"hands_per_level": 9.0, "growth": 1.18, "label": "fast (8 min levels)"},
    "regular": {"hands_per_level": 12.0, "growth": 1.17, "label": "regular (10-12 min levels)"},
    "slow": {"hands_per_level": 18.0, "growth": 1.15, "label": "slow (15 min levels)"},
}
# How fast fields shrink.  Measured on thirteen GGPoker bracelet events (live
# reports of players left and blinds): away from the bubble a table loses a
# player at a rate of 180-210 per hour divided by the average stack in big
# blinds; inside the last 10% before the money that falls to about a quarter,
# and during hand-for-hand to about a tenth.
MIN_CASH_MULTIPLE = 2.0  # smallest prize / full price in GGPoker non-bounty events (1.9 to 2.15 measured)
HANDS_PER_MINUTE = 1.08  # about 65 hands an hour at an 8-handed table (assumed: GGPoker publishes no figure)
BUST_CONSTANT = 3.0      # eliminations per table per hand = BUST_CONSTANT / average stack in bb
BUST_SPREAD = 0.25       # uncertainty (log standard deviation) of that constant
NEAR_RATIO = 1.10        # players left / places paid below which the field tightens up
SLOW_NEAR = 0.28         # share of the normal elimination speed from there on
SLOW_HFH = 0.10          # ... and during hand-for-hand
HFH_PACE = 2.0           # a hand-for-hand hand takes about two normal hands of clock; the blinds keep rising
LAST_STRETCH = 0.20      # average speed over the whole last 10% (both phases), for the mental-math rule
SHALLOW, FORCED = 18.0, 6.0   # average stack (bb) where the slowdown starts to fade, and where it is gone


def hfh_left(paid: int) -> float:
    """Players from the money at which hand-for-hand starts (3 to 7 in the measured events)."""
    return min(7.0, 2.0 + 0.007 * paid)


# --------------------------------------------------------------------------
# Blinds
# --------------------------------------------------------------------------

@dataclass
class Blinds:
    """Big blind, relative to the big blind now, after any number of hands."""

    growth: float = 1.20
    hands_per_level: float = 6.5
    progress: float = 0.0               # share of the current level already played
    schedule: tuple = ()                # optional: big blinds from the current level on
    stall_from: float | None = None     # hand number at which hand-for-hand starts
    stall_pace: float = 1.0             # normal hands of clock used by each hand from then on

    def clock(self, hand: float) -> float:
        """Hands of normal pace that have gone by after ``hand`` hands."""
        if self.stall_from is None or hand <= self.stall_from:
            return hand
        return self.stall_from + (hand - self.stall_from) * self.stall_pace

    def level(self, hand: float) -> int:
        return int((self.clock(hand) + self.progress * self.hands_per_level) / self.hands_per_level + 1e-9)

    def mult(self, hand: float) -> float:
        lv = self.level(hand)
        if self.schedule:
            sched = self.schedule
            if lv < len(sched):
                return sched[lv] / sched[0]
            last = sched[-1] / sched[0]
            return last * self.growth ** (lv - len(sched) + 1)
        return self.growth ** lv

    def hands_until(self, mult: float) -> float:
        """Hands from now until the big blind has grown by ``mult`` (geometric within a level)."""
        if mult <= 1.0:
            return 0.0
        if self.schedule:
            lv = 0
            while self.mult(lv * self.hands_per_level - self.progress * self.hands_per_level + 1e-6) < mult \
                    and lv < 400:
                lv += 1
            return max(0.0, (lv - self.progress) * self.hands_per_level)
        return max(0.0, (math.log(mult) / math.log(self.growth) - self.progress) * self.hands_per_level)


def posted(seat: int, players: int = 8, ante: str = "player") -> float:
    """Big blinds a player loses by folding one hand in ``seat`` (0 = big blind, 1 = small blind).

    ``ante``: ``player`` = everyone antes 12.5% of the big blind every hand
    (GGPoker); ``bb`` = the big blind pays one big blind of ante for the table.
    """
    blind = BB if seat == 0 else SB if seat == 1 else 0.0
    if ante == "player":
        return blind + PLAYER_ANTE
    return blind + (BB_ANTE if seat == 0 else 0.0)


def orbit_cost(players: int = 8, ante: str = "player") -> float:
    """Big blinds a folding player pays per orbit."""
    return sum(posted(seat, players, ante) for seat in range(players))


def fold_cost(hands: int, blinds: Blinds, players: int = 8, seat: int | None = None,
              ante: str = "player") -> float:
    """Big blinds (of the current level) a folding player pays over the next ``hands`` hands.

    ``seat`` is the number of players still to act behind the hero on the first
    hand (0 = big blind); without it the cost is averaged over the seats.
    """
    if seat is None:
        per_hand = orbit_cost(players, ante) / players
        return sum(per_hand * blinds.mult(k) for k in range(int(hands)))
    total, pos = 0.0, seat
    for k in range(int(hands)):
        total += posted(pos, players, ante) * blinds.mult(k)
        pos = (pos + 1) % players
    return total


def level_ahead(hands: float, speed: str = "turbo") -> float:
    """The big blind ``hands`` hands from now, as a multiple of today's, when nobody says where in the
    level the table is: the average over that (between two levels it rises in a straight line)."""
    sp = SPEEDS[speed]
    levels = hands / sp["hands_per_level"]
    whole = int(levels + 1e-12)
    return sp["growth"] ** whole * (1.0 + (sp["growth"] - 1.0) * (levels - whole))


def fold_clock(stack_bb: float, players: int = 8, seat: int = 2, speed: str = "turbo", ante: str = "bb") -> dict:
    """What folding costs: the stack when the big blind reaches the seat, and after a whole round.

    ``seat`` is the number of players still to act behind (0 = big blind now).  A blind is paid at the
    level of the hand it is paid in, and a stack is counted in the big blinds of the hand it is counted
    at.  ``hands``: hands until the big blind; ``at_blind``: the stack then, before posting; ``orbit``:
    the stack after ``players`` hands of folding, back in the same seat; ``gone``: the blinds took all
    of it.  The quick guide shows these numbers (``clock`` in guide/guide.js is the same sum)."""
    hands = (players - seat) % players
    chips, at_blind = float(stack_bb), float(stack_bb)
    for j in range(players):
        if j == hands:
            at_blind = chips / level_ahead(j, speed)
        chips -= posted((seat + j) % players, players, ante) * level_ahead(j, speed)
    return {"hands": hands, "at_blind": max(0.0, at_blind), "orbit": max(0.0, chips / level_ahead(players, speed)),
            "gone": chips <= 0}


# --------------------------------------------------------------------------
# Field: how long until the bubble bursts
# --------------------------------------------------------------------------

@dataclass
class Forecast:
    """Distribution of the number of hands until the bubble bursts."""

    alive: list[float]                  # alive[k] = P(bubble has not burst after k hands)
    mean: float
    samples: list[int] = field(default_factory=list)
    blinds: Blinds | None = None        # blind schedule that goes with the forecast
    left: list[float] = field(default_factory=list)   # players left before each hand, central path
    paid: int = 0
    chips: float = 0.0                  # all chips in play, in big blinds of the entry level

    def field_at(self, hand: int) -> tuple[float, float]:
        """(players left, average stack in entry-level big blinds) before ``hand`` on the central path."""
        if not self.left:
            return 0.0, 0.0
        r = self.left[min(hand, len(self.left) - 1)]
        return r, self.chips / r if r > 0 else 0.0

    def quantile(self, q: float) -> int:
        for k, a in enumerate(self.alive):
            if 1.0 - a >= q:
                return k
        return len(self.alive)

    def hazard(self, k: int) -> float:
        """Chance the bubble bursts during hand ``k`` given it has not burst before it."""
        if k + 1 >= len(self.alive):
            return 1.0
        a = self.alive[k]
        return 1.0 if a <= 1e-12 else max(0.0, min(1.0, 1.0 - self.alive[k + 1] / a))


def bubble_path(remaining: int, paid: int, avg_bb: float, blinds: Blinds, players: int = 8,
                bust: float = BUST_CONSTANT, near: float = SLOW_NEAR, hfh: float = SLOW_HFH,
                limit: int = 4000, trace: list | None = None) -> tuple[int, int | None, float]:
    """(hands until the bubble bursts, hand at which hand-for-hand starts, its pace).

    Each hand every table loses a player with probability ``bust / A`` where
    ``A`` is the average stack in big blinds at that moment: shallow fields
    bust quickly, deep ones slowly.  Inside the last 10% before the money the
    field tightens (``near``), and for the last few players the tournament goes
    hand-for-hand (``hfh``): fewer eliminations per hand, and each hand takes
    longer while the blinds keep rising.  ``near=1, hfh=1`` switches both off.
    """
    if remaining <= paid:
        return 0, None, 1.0
    chips = remaining * avg_bb          # total chips in big blinds of the current level
    r = float(remaining)
    clock, stall, pace_used = 0.0, None, 1.0
    wait = hfh_left(paid)
    for k in range(limit):
        if trace is not None:
            trace.append(r)
        a = chips / (r * blinds.mult(clock))
        rate = bust / max(a, 1.5)
        pace = 1.0
        # tight bubble play only holds while stacks are deep enough to fold: under about
        # 18 big blinds of average stack the blinds start forcing all-ins again
        forced = max(0.0, min(1.0, (SHALLOW - a) / (SHALLOW - FORCED)))
        if hfh < 1.0 and r - paid <= wait + 0.5:
            rate *= hfh + (1.0 - hfh) * forced
            pace = 1.0 + (HFH_PACE - 1.0) * min(1.0, r / players / 10.0)
            if stall is None:
                stall, pace_used = k, pace
        elif r / paid < NEAR_RATIO:
            rate *= near + (1.0 - near) * forced
        r -= r / players * min(rate, 0.5)
        clock += pace
        if r <= paid:
            return k + 1, stall, pace_used
    return limit, stall, pace_used


def hands_to_bubble(remaining: int, paid: int, avg_bb: float, blinds: Blinds, players: int = 8,
                    bust: float = BUST_CONSTANT, near: float = SLOW_NEAR, hfh: float = SLOW_HFH) -> int:
    """Hands until ``remaining`` players have become ``paid`` (see ``bubble_path``)."""
    return bubble_path(remaining, paid, avg_bb, blinds, players, bust, near, hfh)[0]


def field_after(remaining: int, avg_bb: float, blinds: Blinds, hands: int, players: int = 8,
                bust: float = BUST_CONSTANT) -> float:
    """Players expected to be left after ``hands`` more hands (no bubble in between)."""
    chips = remaining * avg_bb
    r = float(remaining)
    for k in range(int(hands)):
        a = chips / (r * blinds.mult(k))
        r -= r / players * min(bust / max(a, 1.5), 0.5)
        if r <= 2:
            return 2.0
    return r


def forecast(remaining: int, paid: int, avg_bb: float, blinds: Blinds, players: int = 8,
             bust: float = BUST_CONSTANT, spread: float = BUST_SPREAD, points: int = 41) -> Forecast:
    """Forecast of the bubble time, with the uncertainty of the elimination speed.

    ``Forecast.blinds`` is the blind schedule to use with it: the same blinds,
    with the levels arriving faster per hand once hand-for-hand has started.
    """
    if remaining <= paid:
        return Forecast([0.0], 0.0, [0], blinds)
    samples, stalls, path = [], [], []
    for i in range(points):
        # evenly spaced quantiles of a log-normal speed
        z = _norm_ppf((i + 0.5) / points)
        trace = path if i == points // 2 else None
        hands, stall, pace = bubble_path(remaining, paid, avg_bb, blinds, players, bust * math.exp(spread * z),
                                         trace=trace)
        samples.append(hands)
        stalls.append((stall, pace))
    path.append(float(paid))
    stall, pace = stalls[points // 2]
    warped = replace(blinds, stall_from=stall, stall_pace=pace) if stall is not None else blinds
    # sampling noise of the eliminations themselves (few players to bust = noisy)
    to_bust = remaining - paid
    noise = 1.0 / math.sqrt(max(1.0, to_bust))
    spreaded = []
    for x in samples:
        for z in (-1.2, -0.4, 0.4, 1.2):
            spreaded.append(max(1, round(x * math.exp(noise * z * 0.8))))
    spreaded.sort()
    top = spreaded[-1] + 1
    alive = [sum(1 for x in spreaded if x > k) / len(spreaded) for k in range(top + 1)]
    return Forecast(alive, sum(spreaded) / len(spreaded), spreaded, warped, path, paid, remaining * avg_bb)


def forecast_fixed(hands: float, spread: float = 0.12) -> Forecast:
    """Forecast for a Day 1 that ends at a fixed level: the number of hands is nearly known.

    The only uncertainty is how many hands the table deals per level.
    """
    samples = sorted(max(1, round(hands * math.exp(spread * _norm_ppf((i + 0.5) / 41)))) for i in range(41))
    top = samples[-1] + 1
    alive = [sum(1 for x in samples if x > k) / len(samples) for k in range(top + 1)]
    return Forecast(alive, sum(samples) / len(samples), samples)


def _norm_ppf(p: float) -> float:
    """Inverse of the standard normal distribution (Acklam's approximation)."""
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - 0.02425:
        return -_norm_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


# --------------------------------------------------------------------------
# Shove spots: fold equity and equity when called, by seat and stack depth
# --------------------------------------------------------------------------

CALLERS = {"loose": -0.03, "normal": 0.0, "tight": 0.04}
DATA_VERSION = 2
SB_PLAYS = 0.70         # folded to the small blind, it raises, limps or shoves this often (the rest are walks)
_DATA = os.path.join(os.path.dirname(__file__), "data", "latereg.json")


@lru_cache(maxsize=1)
def _stored() -> dict:
    try:
        with open(_DATA) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _unpack(text: str) -> tuple:
    """169 probabilities stored as three digits each (thousandths)."""
    return tuple(int(text[i:i + 3]) / 999.0 for i in range(0, 507, 3))


def _pack(values) -> str:
    return "".join(f"{max(0, min(999, round(v * 999))):03d}" for v in values)


RAISERS = {"late": 3, "early": 6}      # who raised: the cutoff (3 behind) or an early seat (6 behind)


@lru_cache(maxsize=16)
def spots(players: int = 8, callers: str = "normal") -> dict:
    """For every seat and stack depth: per hand, P(everyone folds) and equity when called.

    The opponents cover the hero and call the way they would call a standard
    (chip-EV) shoving range from that seat, shifted by the ``callers`` profile:
    ``loose`` tables call 3 points of equity lighter, ``tight`` (bubble) tables
    4 points tighter.  ``raise`` holds the same for moving all-in over one open
    raise, from a late or an early seat; the raiser, who is priced in against a
    short stack, calls first.  Tables for 8 players are stored in
    ``data/latereg.json`` (``tools/build_latereg.py``); other sizes are solved
    on first use.
    """
    stored = _stored().get("spots", {}).get(f"{players}:{callers}")
    if stored and _stored().get("version") == DATA_VERSION:
        out = {"open": {}, "raise": {}, "depths": DEPTHS}
        for key, (fe, eq) in stored["open"].items():
            nb, d = key.split(":")
            out["open"][(int(nb), float(d))] = (_unpack(fe), _unpack(eq))
        for key, (fe, eq) in stored["raise"].items():
            kind, d = key.split(":")
            out["raise"][(kind, float(d))] = (_unpack(fe), _unpack(eq))
        return out
    return compute_spots(players, callers)


def compute_spots(players: int = 8, callers: str = "normal") -> dict:
    """Solve the spot tables (about 20 seconds for 8 players)."""
    shift = CALLERS[callers]
    out = {"open": {}, "raise": {}, "depths": DEPTHS}
    chips = Prizes()
    for nb in range(1, players):
        shover = players - 1 - nb
        for d in DEPTHS:
            stacks = [max(25.0, d + 5.0)] * players
            stacks[shover] = d
            setup = HandSetup(stacks, SB, BB, 0.0, BB_ANTE)
            v_fold, v_steal, cs = build_shove_spot(setup, shover, chips, use_types=False,
                                                   extra_req={j: shift for j in range(players)})
            sol = solve_shove(v_fold, v_steal, cs, iters=30)
            out["open"][(nb, d)] = (tuple(sol.fold_equity), tuple(sol.eq_called))
    # all-in over a raise: the hero is on the button
    if players >= 4:
        shover = players - 3
        for kind, behind in RAISERS.items():
            behind = max(3, min(behind, players - 1))
            opener = players - 1 - behind
            opener_range = villain_open_range(behind)
            for d in DEPTHS:
                stacks = [max(25.0, d + 5.0)] * players
                stacks[shover] = d
                setup = HandSetup(stacks, SB, BB, 0.0, BB_ANTE)
                bets = {opener: OPEN_RAISE}
                order = [opener] + [j for j in range(shover + 1, players)]
                extra = {j: 0.02 + shift for j in range(shover + 1, players)}
                extra[opener] = shift
                v_fold, v_steal, cs = build_shove_spot(setup, shover, chips, bets=bets,
                                                       priors={opener: opener_range}, caller_order=order,
                                                       fold_winner=opener, extra_req=extra, use_types=False)
                sol = solve_shove(v_fold, v_steal, cs, iters=30)
                out["raise"][(kind, d)] = (tuple(sol.fold_equity), tuple(sol.eq_called))
    return out


def _nearest_depth(b: float) -> float:
    best = DEPTHS[0]
    for d in DEPTHS:
        if abs(d - b) < abs(best - b):
            best = d
    return best


@lru_cache(maxsize=8)
def _folded_to(players: int) -> tuple:
    """P(nobody has entered the pot when the action reaches the seat with n players behind).

    For the big blind that is a walk: everyone folded and the small blind gave up too.
    """
    opens = [range_pct(villain_open_range(nb)) / 100.0 for nb in range(players)]
    out = []
    for nb in range(players):
        p = 1.0
        for j in range(max(nb + 1, 2), players):
            p *= 1.0 - opens[j]
        if nb == 0:
            p *= 1.0 - SB_PLAYS
        out.append(p)
    return tuple(out)


@lru_cache(maxsize=8)
def _early_raiser(players: int) -> tuple:
    """Given that someone raised before the seat with n players behind: P(it was an early seat)."""
    opens = [range_pct(villain_open_range(nb)) / 100.0 for nb in range(players)]
    out = []
    for nb in range(players):
        still, early, total = 1.0, 0.0, 0.0
        for j in range(players - 1, nb, -1):
            p = still * (SB_PLAYS if (j == 1 and nb == 0) else opens[j])
            total += p
            if j >= 5:
                early += p
            still *= 1.0 - (SB_PLAYS if (j == 1 and nb == 0) else opens[j])
        out.append(early / total if total > 0 else 0.0)
    return tuple(out)


# --------------------------------------------------------------------------
# The plan: dynamic programme over (hand, seat, stack)
# --------------------------------------------------------------------------

@dataclass
class Plan:
    """Solved shove-or-fold plan for one entry."""

    players: int
    blinds: Blinds
    fc: Forecast
    step: float                         # stack grid step, in bb0
    values: list                        # values[k][seat][i]: P(cash) with stack i*step before hand k
    dollars: list | None                # same shape: expected prize (buy-ins) under the same plan
    callers: str
    itm: float                          # P(cash) from the entry stack, averaged over the first seat
    fold_only: float                    # P(cash) if the hero never plays a hand
    prize: float | None                 # expected prize in buy-ins (None without payouts)
    stack_bb: float
    reward: list | None = None
    ante: str = "player"

    def _value(self, table, k: int, seat: int, stack: float) -> float:
        if stack <= 0:
            return 0.0
        k = min(k, len(table) - 1)
        row = table[k][seat]
        x = stack / self.step
        i = int(x)
        if i >= len(row) - 1:
            return row[-1]
        return row[i] + (row[i + 1] - row[i]) * (x - i)

    def chance(self, hand: int, seat: int, stack_bb_now: float) -> float:
        """P(cash) before hand number ``hand`` with a stack given in current big blinds."""
        return self._value(self.values, hand, seat, stack_bb_now * self.blinds.mult(hand))

    def shove_range(self, hand: int, seat: int, stack_bb_now: float, facing_raise: bool = False,
                    raiser: str = "late") -> list[float]:
        """Hands the plan moves all-in with (weights 0 or 1 per hand class).

        ``raiser``: with ``facing_raise``, whether the raise came from a late seat or an early one.
        """
        if seat == 0 and not facing_raise:
            return [0.0] * 169
        m = self.blinds.mult(hand)
        s = stack_bb_now * m
        nxt = _Next(self, hand, seat)
        a, b, c = _branch_stacks(seat, s, m, facing_raise, self.players, self.ante)
        va, vb, vc = nxt(a), nxt(b), nxt(c)
        d = _nearest_depth(stack_bb_now)
        tab = spots(self.players, self.callers)
        fe, eq = tab["raise"][(raiser, d)] if facing_raise else tab["open"][(seat, d)]
        return [1.0 if fe[h] * va + (1.0 - fe[h]) * eq[h] * vb > vc + 1e-9 else 0.0 for h in range(169)]


class _Next:
    """Value just after a hand: the bubble may burst, otherwise the next hand's value."""

    def __init__(self, plan: Plan, hand: int, seat: int, table=None, reward=None):
        self.plan = plan
        self.lam = plan.fc.hazard(hand)
        self.seat = (seat + 1) % plan.players
        self.hand = hand + 1
        self.table = table if table is not None else plan.values
        self.reward = reward

    def __call__(self, stack: float) -> float:
        if stack <= 0:
            return 0.0
        burst = 1.0 if self.reward is None else _interp(self.reward, stack / self.plan.step)
        if self.lam >= 1.0 or self.hand >= len(self.table):
            return burst
        return self.lam * burst + (1.0 - self.lam) * self.plan._value(self.table, self.hand, self.seat, stack)


def _interp(row, x: float) -> float:
    i = int(x)
    if i >= len(row) - 1:
        return row[-1]
    return row[i] + (row[i + 1] - row[i]) * (x - i)


def _branch_stacks(seat: int, s: float, m: float, facing_raise: bool, players: int = 8,
                   ante: str = "player") -> tuple[float, float, float]:
    """Stacks (bb0) after: everyone folds to the shove, the shove is called and wins, the hero folds.

    ``s`` is the stack before posting, ``m`` the big blind in bb0.  The caller
    is assumed to cover the hero.
    """
    fold = s - min(s, posted(seat, players, ante) * m)
    own_dead = 0.0                                  # chips of the hero's that cannot be matched
    if ante == "player":
        others = (players - 1) * PLAYER_ANTE        # antes of everyone else
        left = (players - 2) * PLAYER_ANTE          # ... except the caller's, which is matched
    elif seat == 0:
        others = left = 0.0
        own_dead = min(s, BB_ANTE * m)              # the big-blind ante is dead money
    else:
        others = left = BB_ANTE
    blind_in = BB if seat == 0 else SB if seat == 1 else 0.0   # the hero's own blind
    blinds_others = SB + BB - blind_in
    raise_in = OPEN_RAISE if facing_raise else 0.0
    live = s - own_dead
    if seat == 0 or facing_raise:
        # the raiser's chips are in the pot: they fold and leave them, or call and they are matched
        steal = s + (blinds_others + others + raise_in) * m
        win = 2.0 * live + own_dead + (blinds_others + left) * m
    else:
        steal = s + (blinds_others + others) * m
        # the caller is usually one of the blinds, so part of the blinds is matched, not dead
        dead_blinds = blinds_others - (0.75 if seat >= 2 else BB)
        win = 2.0 * live + own_dead + (dead_blinds + left) * m
    return steal, win, fold


def _groups(fe, eq, n_groups: int = 26) -> list[tuple[float, float, float]]:
    """Bundle the 169 hands into groups of similar strength: (weight, P(fold), P(called and win))."""
    hands = sorted(range(169), key=lambda h: (1.0 - fe[h]) * eq[h])
    out, acc_w, acc_u, acc_v, target = [], 0.0, 0.0, 0.0, 1.0 / n_groups
    for h in hands:
        w = _WEIGHT[h]
        acc_w += w
        acc_u += w * fe[h]
        acc_v += w * (1.0 - fe[h]) * eq[h]
        if acc_w >= target:
            out.append((acc_w, acc_u / acc_w, acc_v / acc_w))
            acc_w = acc_u = acc_v = 0.0
    if acc_w > 0:
        out.append((acc_w, acc_u / acc_w, acc_v / acc_w))
    return out


@lru_cache(maxsize=16)
def _group_tables(players: int, callers: str) -> dict:
    tab = spots(players, callers)
    return {"open": {key: _groups(*val) for key, val in tab["open"].items()},
            "raise": {key: _groups(*val) for key, val in tab["raise"].items()}}


# --------------------------------------------------------------------------
# The printed sheet as a fixed strategy
# --------------------------------------------------------------------------

SHORT_BB = 6.0          # under this stack the wide zone uses its short-stack chart
DEEP_BB = 20.0          # above this the charts stop: all-in with premiums only


@dataclass
class Sheet:
    """The rules of the printed sheet: one range per chart, seat and situation.

    ``charts[name]`` is ``{"open": {players behind: weights}, "late": weights, "early": weights}``
    for the names ``wide``, ``short``, ``tight``, ``aces`` and ``premium``.
    """

    charts: dict
    players: int = 8

    def pick(self, share: float, stack_bb: float) -> str | None:
        """Which chart applies to a stack that is ``share`` of the sit-out line (None = fold)."""
        if share >= 1.0:
            return None
        if share >= ZONES[1][1]:
            return "aces"
        if stack_bb > DEEP_BB:
            return "premium"
        if share >= ZONES[2][1]:
            return "tight"
        return "short" if stack_bb < SHORT_BB else "wide"

    def weights(self, name: str, kind: str, seat: int) -> list[float]:
        chart_ = self.charts[name]
        return chart_["open"][seat] if kind == "open" else chart_[kind]


def solve(stack_bb: float, fc: Forecast, blinds: Blinds, players: int = 8, callers: str = "normal",
          reward=None, policy: str = "itm", grid: int = 220, top: float | None = None,
          ante: str = "player", sheet: Sheet | None = None) -> Plan:
    """Best shove-or-fold plan for the chance of cashing.

    ``reward(stack_bb0)`` is the prize expectation (in buy-ins) of holding that
    stack when the bubble bursts; with it the plan also reports the expected
    prize.  ``policy``: ``itm`` maximises the chance of cashing, ``ev``
    maximises the expected prize, ``fold`` never plays a hand, ``nash`` shoves
    the chip-EV ranges whatever the situation, ``sheet`` follows the printed
    rules (``sheet``) exactly, so its result is what the sheet delivers.
    """
    blinds = fc.blinds or blinds
    horizon = min(len(fc.alive) - 1, 1500)
    top = top or max(4.0 * stack_bb, 40.0, 1.6 * fold_cost(fc.quantile(0.98), blinds, players, None, ante) + 10.0)
    walk_gain = SB + ((players - 1) * PLAYER_ANTE if ante == "player" else 0.0)
    step = top / grid
    reward_row = None
    if reward is not None:
        reward_row = [0.0] + [reward(i * step) for i in range(1, grid + 1)]
    gt = _group_tables(players, callers)
    tab = spots(players, callers)
    ft = _folded_to(players)
    early = _early_raiser(players)
    walk = ft[0]
    if policy == "sheet" and (sheet is None or not fc.left):
        raise ValueError("the sheet policy needs a sheet and a field forecast")
    coef_cache: dict = {}

    def coef(name: str, kind: str, seat: int, d: float) -> tuple[float, float, float]:
        """(share of hands played, P(played and all fold), P(played, called and win)) for a fixed range."""
        key = (name, kind, seat if kind == "open" else -1, d)
        got = coef_cache.get(key)
        if got is None:
            w = sheet.weights(name, kind, seat)
            fe, eq = tab["open"][(seat, d)] if kind == "open" else tab["raise"][(kind, d)]
            a = b = c = 0.0
            for h in range(169):
                if w[h] >= 0.5:
                    a += _WEIGHT[h]
                    b += _WEIGHT[h] * fe[h]
                    c += _WEIGHT[h] * (1.0 - fe[h]) * eq[h]
            got = coef_cache[key] = (a, b, c)
        return got

    plan = Plan(players=players, blinds=blinds, fc=fc, step=step, values=[], dollars=None, callers=callers,
                itm=0.0, fold_only=0.0, prize=None, stack_bb=stack_bb, reward=reward_row, ante=ante)
    values = [None] * (horizon + 1)
    dollars = [None] * (horizon + 1) if reward_row is not None else None
    objective_is_dollars = policy == "ev" and reward_row is not None
    for k in range(horizon, -1, -1):
        m = blinds.mult(k)
        lam = fc.hazard(k)
        last = k == horizon or lam >= 1.0
        line_k = 0.0
        if policy == "sheet":
            r_k, avg_k = fc.field_at(k)
            line_k = sit_out_line(avg_k, r_k, fc.paid)
        vrow_all, drow_all = [], []
        for seat in range(players):
            nseat = (seat + 1) % players
            nv = None if last else values[k + 1][nseat]
            nd = None if (last or dollars is None) else dollars[k + 1][nseat]

            def after(stack: float) -> tuple[float, float]:
                """(P(cash), prize) once this hand is over with ``stack`` chips left."""
                if stack <= 0:
                    return 0.0, 0.0
                x = stack / step
                burst_d = _interp(reward_row, x) if reward_row is not None else 0.0
                if nv is None:
                    return 1.0, burst_d
                v = lam + (1.0 - lam) * _interp(nv, x)
                dd = lam * burst_d + (1.0 - lam) * _interp(nd, x) if nd is not None else 0.0
                return v, dd

            p_raise = 1.0 - (walk if seat == 0 else ft[seat])
            p_open = 1.0 - p_raise
            kinds = [(kind, wk) for kind, wk in (("early", early[seat]), ("late", 1.0 - early[seat])) if wk > 1e-9]
            vrow, drow = [0.0] * (grid + 1), [0.0] * (grid + 1)
            for i in range(1, grid + 1):
                s = i * step
                b = s / m
                d = _nearest_depth(b)
                vc, dc = after(_branch_stacks(seat, s, m, False, players, ante)[2])
                chart_name = None
                if policy == "sheet":
                    chart_name = sheet.pick(s / line_k if line_k > 0 else 99.0, b)
                # --- someone raised before the hero (for the big blind: anything but a walk)
                if policy in ("fold", "nash") or (policy == "sheet" and chart_name is None):
                    acc_v, acc_d = vc, dc       # the chip-EV chart only covers first-in all-ins
                else:
                    steal, win, _ = _branch_stacks(seat, s, m, True, players, ante)
                    (va, da), (vb, db) = after(steal), after(win)
                    acc_v = acc_d = 0.0
                    for kind, wk in kinds:
                        if policy == "sheet":
                            wp, u, v = coef(chart_name, kind, seat, d)
                            acc_v += wk * (u * va + v * vb + (1.0 - wp) * vc)
                            acc_d += wk * (u * da + v * db + (1.0 - wp) * dc)
                            continue
                        for w, u, v in gt["raise"][(kind, d)]:
                            sv, sd = u * va + v * vb, u * da + v * db
                            if (sd > dc) if objective_is_dollars else (sv > vc):
                                acc_v += wk * w * sv
                                acc_d += wk * w * sd
                            else:
                                acc_v += wk * w * vc
                                acc_d += wk * w * dc
                tot_v, tot_d = p_raise * acc_v, p_raise * acc_d
                # --- nobody has entered the pot
                if seat == 0:
                    wv, wd = after(s + walk_gain * m)       # a walk: the blind and the antes come back
                    tot_v += p_open * wv
                    tot_d += p_open * wd
                elif policy == "fold" or (policy == "sheet" and chart_name is None):
                    tot_v += p_open * vc
                    tot_d += p_open * dc
                else:
                    steal, win, _ = _branch_stacks(seat, s, m, False, players, ante)
                    (va, da), (vb, db) = after(steal), after(win)
                    acc_v = acc_d = 0.0
                    if policy == "sheet":
                        wp, u, v = coef(chart_name, "open", seat, d)
                        acc_v = u * va + v * vb + (1.0 - wp) * vc
                        acc_d = u * da + v * db + (1.0 - wp) * dc
                    elif policy == "nash":
                        fe, eq = tab["open"][(seat, d)]
                        rng = _nash_range(seat, b)
                        for h in range(169):
                            w = _WEIGHT[h]
                            if rng[h] >= 0.5:
                                acc_v += w * (fe[h] * va + (1.0 - fe[h]) * eq[h] * vb)
                                acc_d += w * (fe[h] * da + (1.0 - fe[h]) * eq[h] * db)
                            else:
                                acc_v += w * vc
                                acc_d += w * dc
                    else:
                        for w, u, v in gt["open"][(seat, d)]:
                            sv, sd = u * va + v * vb, u * da + v * db
                            if (sd > dc) if objective_is_dollars else (sv > vc):
                                acc_v += w * sv
                                acc_d += w * sd
                            else:
                                acc_v += w * vc
                                acc_d += w * dc
                    tot_v += p_open * acc_v
                    tot_d += p_open * acc_d
                vrow[i], drow[i] = tot_v, tot_d
            vrow_all.append(vrow)
            drow_all.append(drow)
        values[k] = vrow_all
        if dollars is not None:
            dollars[k] = drow_all
    plan.values = values
    plan.dollars = dollars
    plan.itm = sum(plan._value(values, 0, seat, stack_bb) for seat in range(players)) / players
    if dollars is not None:
        plan.prize = sum(plan._value(dollars, 0, seat, stack_bb) for seat in range(players)) / players
    plan.fold_only = fold_only_chance(stack_bb, fc, blinds, players, ante)
    return plan


@lru_cache(maxsize=512)
def _nash_range_cached(seat: int, depth: int) -> tuple:
    from .pushfold import nash_push_range
    return tuple(nash_push_range(seat, float(depth)))


def _nash_range(seat: int, b: float) -> tuple:
    return _nash_range_cached(seat, max(1, min(25, int(round(b)))))


def fold_only_chance(stack_bb: float, fc: Forecast, blinds: Blinds, players: int = 8,
                     ante: str = "player") -> float:
    """P(cash) for a player who sits out from now on (posting blinds, never winning a pot)."""
    blinds = fc.blinds or blinds
    n = len(fc.samples)
    if not n:
        return 1.0
    top = fc.samples[-1]
    total = 0.0
    for seat in range(players):
        costs, paid, pos = [], 0.0, seat
        for k in range(top + 1):
            costs.append(paid)
            paid += posted(pos, players, ante) * blinds.mult(k)
            pos = (pos + 1) % players
        total += sum(1 for x in fc.samples if costs[min(x, top)] < stack_bb) / n
    return total / players


def safe_stack(fc: Forecast, blinds: Blinds, players: int = 8, confidence: float = 0.95,
               ante: str = "player") -> float:
    """Stack (current big blinds) with which sitting out cashes with the given confidence."""
    blinds = fc.blinds or blinds
    hands = fc.quantile(confidence)
    worst = max(fold_cost(hands, blinds, players, seat, ante) for seat in range(players))
    return worst + 0.5


# --------------------------------------------------------------------------
# The sit-out line: a rule a player can work out from the lobby
# --------------------------------------------------------------------------

LINE_FACTOR = ORBIT_COST / BUST_CONSTANT    # expected blinds paid, per chip the average stack must still grow

# The sit-out line: the stack, in average stacks, from which a player who folds
# every hand still reaches the money about 95 times in 100.  Rows are players
# left / places paid, for fields that pay 150 places or more.  Taken from the
# forecast (the highest value over hyper, turbo, regular and slow structures
# and average stacks of 15 to 40 big blinds), so it errs on the safe side.
SIT_OUT_TABLE = ((1.00, 0.0), (1.02, 0.50), (1.05, 0.65), (1.10, 0.85), (1.20, 1.00), (1.30, 1.15),
                 (1.50, 1.55), (2.00, 2.45), (3.00, 4.40), (4.00, 6.30))


def small_field_extra(paid: float) -> float:
    """Average stacks to add to the line when fewer than about 150 places are paid.

    With few players to bust, the bubble is a handful of eliminations whose
    timing is a lottery, so a folding player needs more.  No small-field
    bubble was measured; this is the forecast's own extrapolation.
    """
    return max(0.0, 40.0 / max(paid, 1.0) - 0.25)


ZONES = (
    # name, lowest share of the sit-out line, what to do
    ("safe", 1.0, "SIT OUT: the stack lasts until the money"),
    ("close", 0.5, "nearly there: fold everything; only aces, when nobody has raised"),
    ("short", 0.2, "one pot short: all-in with the tight chart"),
    ("far", 0.0, "a double-up or two short: all-in with the wide chart (short chart under 6 big blinds)"),
)
CHART_COVER = {"far": 0.12, "short": 0.32}     # share of the line at which each reference chart is solved


def expected_cost(avg: float, remaining: int, paid: int) -> float:
    """Blinds (in chips) a sitting-out player is expected to pay before the bubble bursts.

    While the field shrinks the average stack grows, and a folding player pays
    about ``LINE_FACTOR`` chips for every chip of that growth, whatever the
    speed of the blinds.  The last 10% of the eliminations take about five
    times as long as the rest, so they are charged five times.
    """
    if paid <= 0 or remaining <= paid:
        return 0.0
    rho = remaining / paid
    if rho >= NEAR_RATIO:
        growth = (rho / NEAR_RATIO - 1.0) + rho * (1.0 - 1.0 / NEAR_RATIO) / LAST_STRETCH
    else:
        growth = (rho - 1.0) / LAST_STRETCH
    return LINE_FACTOR * avg * growth


def sit_out_line(avg: float, remaining: float, paid: float) -> float:
    """Stack (chips) from which sitting out reaches the money about 95 times in 100."""
    if paid <= 0 or remaining <= paid:
        return 0.0
    rho = remaining / paid
    table = SIT_OUT_TABLE
    base = None
    if rho >= table[-1][0]:
        (x0, y0), (x1, y1) = table[-2], table[-1]
        base = y1 + (rho - x1) * (y1 - y0) / (x1 - x0)
    else:
        for (x0, y0), (x1, y1) in zip(table, table[1:]):
            if rho <= x1:
                base = y0 + (rho - x0) * (y1 - y0) / (x1 - x0)
                break
    return avg * (base + small_field_extra(paid))


def zone(stack: float, avg: float, remaining: int, paid: int) -> tuple[str, float, str]:
    """(zone name, cover = stack / sit-out line, advice) for a moment of the tournament."""
    line = sit_out_line(avg, remaining, paid)
    cover = stack / line if line > 0 else 99.0
    for name, low, text in ZONES:
        if cover >= low:
            return name, cover, text
    return ZONES[-1][0], cover, ZONES[-1][2]


# rough chance of cashing when following the sheet, by share of the sit-out line held
# (regular speed, the slower and so the lower of the two measured speeds)
_CASH_BY_COVER = ((0.0, 0.04), (0.08, 0.11), (0.15, 0.20), (0.25, 0.31), (0.35, 0.44), (0.45, 0.56),
                  (0.60, 0.70), (0.80, 0.91), (1.00, 0.98))


def cash_chance(cover: float) -> float:
    """Rough chance of cashing from a stack that is ``cover`` times the sit-out line."""
    pts = _CASH_BY_COVER
    if cover >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if cover <= x1:
            return y0 + (cover - x0) * (y1 - y0) / (x1 - x0)
    return pts[-1][1]


def describe_zone(stack: float, avg: float, remaining: int, paid: int) -> str:
    if remaining <= paid:
        return ">>> IN THE MONEY: the bubble has burst"
    name, cover, text = zone(stack, avg, remaining, paid)
    cost, line = expected_cost(avg, remaining, paid), sit_out_line(avg, remaining, paid)
    head = "SIT OUT" if name == "safe" else "KEEP PLAYING"
    lines = [f">>> {head}   stack {stack:,.0f} = {cover:.0%} of the sit-out line ({line:,.0f})",
             f"  {remaining} left, {paid} paid ({remaining / paid:.2f} per paid place): the line is "
             f"{line / avg:.2f} average stacks of {avg:,.0f}",
             f"  waiting is expected to cost about {cost:,.0f} in blinds and antes",
             f"  zone: {name.upper()} - {text}"]
    if name != "safe":
        lines.append(f"  short by {line - stack:,.0f}; rough chance of cashing from here {cash_chance(cover):.0%}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Scouting a tournament before registering
# --------------------------------------------------------------------------

@dataclass
class Scout:
    stack_bb: float
    remaining: int
    paid: int
    entrants: int
    ratio: float                        # players left per paid place
    avg_bb: float
    hands: float                        # expected hands until the bubble
    orbits: float
    cost_bb: float                      # blinds a sitting-out player pays until then
    safe_bb: float                      # stack that cashes by folding, 95% of the time
    cover: float                        # stack / cost: 1.0 = exactly enough to fold in
    fold_only: float
    itm: float
    prize: float | None                 # expected prize, in buy-ins
    roi: float | None
    min_cash: float | None              # buy-ins
    breakeven: float | None             # P(cash) needed if every cash were a min-cash
    verdict: str
    reasons: list[str]
    plan: Plan | None = None            # the solver's best plan (for charts at entry)
    best_itm: float | None = None       # its chance of cashing; ``itm`` is what the printed sheet delivers
    assumed_min_cash: bool = False


def payouts_with_min_cash(entrants: int, paid: int, pool: float, min_cash: float | None = None) -> list[float]:
    """A typical payout table for the pool, with the last paid place set to ``min_cash`` when known."""
    pays = default_payouts(entrants, paid, pool, pool / max(1, entrants))
    if not min_cash or paid < 2:
        return pays
    base = pays[-1]
    spare, target = pool - paid * base, pool - paid * min_cash
    if spare <= 0 or target <= 0:
        return [pool / paid] * paid
    return [min_cash + (p - base) * target / spare for p in pays]


def bubble_reward(entrants: int, paid: int, payouts: list[float] | None, buyin_total: float,
                  chips_bb0: float):
    """Expected prize (in buy-ins) of holding ``stack`` bb0 when the bubble bursts."""
    pays = payouts or default_payouts(entrants, paid, entrants * buyin_total, buyin_total)
    pays = [p / buyin_total for p in pays][:paid]
    cache: dict[int, float] = {}

    def reward(stack: float) -> float:
        key = int(stack * 4)
        if key not in cache:
            s = max(key / 4.0, 0.25)
            rest = max(chips_bb0 - s, 1.0) / max(1, paid - 1)
            cache[key] = hero_equity([s], 0, pays, field_n=paid - 1, field_stack=rest)
        return cache[key]
    return reward


def scout(stack_bb: float, remaining: int, paid: int | None = None, entrants: int | None = None,
          avg_bb: float | None = None, speed: str = "turbo", players: int = 8,
          hands_per_level: float | None = None, growth: float | None = None, progress: float = 0.0,
          schedule: tuple = (), callers: str = "normal", buyin: float = 1.0, fee: float = 0.0,
          payouts: list[float] | None = None, min_cash: float | None = None, bounty_share: float = 0.0,
          bust: float = BUST_CONSTANT, levels_left: float | None = None, ante: str = "player",
          with_plan: bool = True) -> Scout:
    """Rate one tournament for the late-registration min-cash plan.

    ``stack_bb``: the starting stack in big blinds at the level you would enter.
    ``remaining`` / ``paid``: players still in and places paid at that moment.
    ``entrants``: total entries (for the average stack; or pass ``avg_bb``).
    ``levels_left``: for a Day 1 flight that ends after a fixed level and pays
    everyone who survives it, the number of levels still to play; ``paid`` is
    then estimated when not given.
    Money: ``buyin`` is the part that goes to the prize pool, ``fee`` the rake;
    ``payouts`` or ``min_cash`` in the same currency.
    """
    sp = SPEEDS[speed]
    blinds = Blinds(growth or sp["growth"], hands_per_level or sp["hands_per_level"], progress, tuple(schedule))
    if avg_bb is None:
        avg_bb = stack_bb * (entrants / remaining) if entrants else stack_bb * 1.8
    entrants = entrants or int(round(remaining * avg_bb / stack_bb))
    if levels_left is not None:
        hands_fixed = max(1.0, (levels_left - progress) * blinds.hands_per_level)
        fc = forecast_fixed(hands_fixed)
        if paid is None:
            paid = max(2, int(round(field_after(remaining, avg_bb, blinds, int(round(hands_fixed)), players, bust))))
    else:
        if paid is None:
            raise ValueError("places paid are needed (or levels_left for a flight that ends at a fixed level)")
        fc = forecast(remaining, paid, avg_bb, blinds, players, bust)
    blinds = fc.blinds or blinds
    hands = fc.mean
    cost = fold_cost(int(round(hands)), blinds, players, None, ante)
    safe = safe_stack(fc, blinds, players, 0.95, ante)
    total = buyin + fee
    pool_share = 1.0 - bounty_share
    assumed = False
    if payouts:
        pays = list(payouts)
    else:
        if min_cash is None:
            # GGPoker pays about twice the full price to the last paid place of a non-bounty event,
            # and about 1.15 to 1.5 times when half the pool is bounties
            min_cash = total * (MIN_CASH_MULTIPLE * pool_share + 0.3 * bounty_share)
            assumed = True
        pays = payouts_with_min_cash(entrants, paid, entrants * buyin * pool_share, min_cash)
    mc = pays[-1] / total
    reward = bubble_reward(entrants, paid, pays, total, remaining * avg_bb)
    plan = best = None
    if with_plan:
        best = solve(stack_bb, fc, blinds, players, callers, reward=reward, ante=ante)
        # the verdict uses what the printed sheet delivers; the solver's optimum is kept for reference
        plan = sheet_plan(stack_bb, fc, blinds, players, callers, reward, ante) if fc.left else best
    itm = plan.itm if plan else fold_only_chance(stack_bb, fc, blinds, players, ante)
    prize = plan.prize if plan else None
    roi = prize - 1.0 if prize is not None else None
    reasons = []
    ratio = remaining / paid
    cover = stack_bb / cost if cost > 0 else 99.0
    if bounty_share > 0:
        reasons.append(f"{bounty_share:.0%} of the prize pool is bounties: the min-cash is small")
    if stack_bb >= safe:
        reasons.append("the stack covers the blinds until the money: you can sit out from the first hand")
    elif cover >= 0.7:
        reasons.append("one successful all-in (a steal or a double-up) makes the stack safe")
    elif cover >= 0.35:
        reasons.append("the stack needs a double-up before it can wait for the money")
    else:
        reasons.append("the money is too far for this stack: it needs more than one double-up")
    if mc < 1.8:
        reasons.append(f"the min-cash is only {mc:.2f} buy-ins")
    if roi is not None and roi > 0.05 and itm >= 0.5:
        verdict = "ENTER"
    elif roi is not None and roi > 0.0:
        verdict = "MARGINAL"
    else:
        verdict = "SKIP"
    return Scout(stack_bb=stack_bb, remaining=remaining, paid=paid, entrants=entrants, ratio=ratio,
                 avg_bb=avg_bb, hands=hands, orbits=hands / players, cost_bb=cost, safe_bb=safe, cover=cover,
                 fold_only=plan.fold_only if plan else itm, itm=itm, prize=prize, roi=roi, min_cash=mc,
                 breakeven=1.0 / mc if mc else None, verdict=verdict, reasons=reasons, plan=best,
                 best_itm=best.itm if best else None, assumed_min_cash=assumed)


def describe(sc: Scout) -> str:
    lines = [f">>> {sc.verdict}   cash {sc.itm:.0%} of the time"
             + (f", return {sc.roi:+.0%} per entry" if sc.roi is not None else "")
             + (f"   (a perfect solver: {sc.best_itm:.0%})" if sc.best_itm is not None else "")]
    lines.append(f"  field: {sc.remaining} left, {sc.paid} paid ({sc.ratio:.2f} players per paid place), "
                 f"average stack {sc.avg_bb:.0f}bb")
    lines.append(f"  bubble: about {sc.hands:.0f} hands away ({sc.orbits:.1f} orbits); sitting out until then "
                 f"costs {sc.cost_bb:.1f}bb")
    line = sit_out_line(sc.avg_bb, sc.remaining, sc.paid)
    name, share, text = zone(sc.stack_bb, sc.avg_bb, sc.remaining, sc.paid)
    lines.append(f"  you:   {sc.stack_bb:.0f}bb = {share:.0%} of the sit-out line ({line:.0f}bb, "
                 f"{line / sc.avg_bb:.2f} average stacks); folding every hand cashes {sc.fold_only:.0%}")
    lines.append(f"  zone:  {name.upper()} - {text}")
    if sc.min_cash:
        lines.append(f"  money: min-cash {sc.min_cash:.2f} buy-ins" + (" (assumed)" if sc.assumed_min_cash else "")
                     + f", so min-cashes alone break even at {sc.breakeven:.0%}"
                     + (f"; expected prize {sc.prize:.2f} buy-ins" if sc.prize else ""))
    for r in sc.reasons:
        lines.append(f"  why:   {r}")
    return "\n".join(lines)


def plan_for_cover(cover: float, stack_bb: float = 10.0, players: int = 8, callers: str = "normal",
                   speed: str = "turbo", avg_ratio: float = 2.5, paid: int = 200, grid: int = 180) -> Plan:
    """A solved plan for a player whose stack is ``cover`` times the sit-out line.

    Used to print reference charts: the ranges depend mostly on how far the
    stack is from the line and only a little on its depth in big blinds.
    """
    sp = SPEEDS[speed]
    blinds = Blinds(sp["growth"], sp["hands_per_level"])
    avg = avg_ratio * stack_bb
    lo, hi = 1.0005, 12.0
    for _ in range(50):                 # players per paid place at which the stack is that share of the line
        mid = (lo + hi) / 2.0
        if sit_out_line(avg, round(mid * 100000), 100000) * cover > stack_bb:
            hi = mid
        else:
            lo = mid
    remaining = max(paid + 1, int(round(paid * lo)))
    fc = forecast(remaining, paid, avg, blinds, players)
    return solve(stack_bb, fc, blinds, players, callers, grid=grid)


@lru_cache(maxsize=8)
def build_sheet(players: int = 8, callers: str = "normal", speed: str = "turbo") -> Sheet:
    """The printed sheet: wide, short-stack and tight charts plus the two fixed ranges.

    ``wide`` and ``tight`` are the solved plan at 10 big blinds, far from the
    sit-out line and one pot short of it; ``short`` is the same far plan a
    dozen hands later with 4 big blinds left.  The tight chart is kept inside
    the wide one.
    """
    from .cards import parse_range
    far = plan_for_cover(CHART_COVER["far"], 10.0, players, callers, speed)
    near = plan_for_cover(CHART_COVER["short"], 10.0, players, callers, speed)

    def read(plan: Plan, hand: int, stack: float) -> dict:
        return {"open": {seat: plan.shove_range(hand, seat, stack) for seat in range(1, players)},
                "late": plan.shove_range(hand, 2, stack, True, "late"),
                "early": plan.shove_range(hand, 2, stack, True, "early")}

    wide, tight = read(far, 0, 10.0), read(near, 0, 10.0)
    later = min(12, len(far.values) - 2)
    short = read(far, later, 4.0)
    for seat in wide["open"]:
        wide["open"][seat] = [max(a, b) for a, b in zip(wide["open"][seat], tight["open"][seat])]
    for kind in ("late", "early"):
        wide[kind] = [max(a, b) for a, b in zip(wide[kind], tight[kind])]
    none = [0.0] * 169
    aces, premium, kings = parse_range("AA"), parse_range("QQ+, AKs, AKo"), parse_range("KK+")
    charts = {"wide": wide, "short": short, "tight": tight,
              "aces": {"open": {seat: aces for seat in range(1, players)}, "late": none, "early": none},
              "premium": {"open": {seat: premium for seat in range(1, players)}, "late": premium, "early": kings}}
    sheet = Sheet(charts, players)
    sheet.itm = {"wide": far.itm, "tight": near.itm}
    return sheet


def reference_charts(players: int = 8, stack_bb: float = 10.0, callers: str = "normal",
                     speed: str = "turbo") -> dict:
    """The printed charts keyed by name (``wide``, ``short``, ``tight``), seats by name.

    Each is ``{"open": {seat name: weights}, "late": weights, "early": weights}``: all-in
    first in by seat, and over a raise from a late or an early seat.
    """
    sheet = build_sheet(players, callers, speed)
    out = {}
    for name in ("wide", "short", "tight"):
        ch = sheet.charts[name]
        out[name] = {"open": {seat_name(seat, players): ch["open"][seat] for seat in range(players - 1, 0, -1)},
                     "late": ch["late"], "early": ch["early"]}
    return out


def sheet_plan(stack_bb: float, fc: Forecast, blinds: Blinds, players: int = 8, callers: str = "normal",
               reward=None, ante: str = "player", grid: int = 220) -> Plan:
    """What the printed sheet delivers from this entry (the sheet played exactly, hand after hand)."""
    return solve(stack_bb, fc, blinds, players, callers, reward=reward, policy="sheet", grid=grid, ante=ante,
                 sheet=build_sheet(players, callers))


def seat_name(behind: int, players: int = 8) -> str:
    """Seat label from the number of players still to act behind it (0 = big blind)."""
    fixed = {0: "BB", 1: "SB", 2: "BTN", 3: "CO", 4: "HJ", 5: "LJ"}
    if behind in fixed and behind < players:
        return fixed[behind]
    early = players - 1 - behind        # 0 = first to act
    return "UTG" if early <= 0 else f"UTG+{early}"


def chart(plan: Plan, hand: int, stack_bb_now: float, players: int | None = None) -> dict[str, str]:
    """Shove ranges by seat for one moment of the plan, as range notation."""
    players = players or plan.players
    out = {}
    for seat in range(players - 1, 0, -1):
        rng = plan.shove_range(hand, seat, stack_bb_now)
        out[seat_name(seat, players)] = f"{range_pct(rng):.0f}%  {format_range(rng) or '-'}"
    return out
