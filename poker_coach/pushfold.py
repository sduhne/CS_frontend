"""All-in maths: an equilibrium solver for shove / call spots.

One player (the *shover*) moves all-in; the players left to act (the
*callers*) each call or fold.  The solver finds a pair of ranges that are best
responses to each other by fictitious play, valuing every outcome with the
tournament prize model (ICM) or with raw chips.  It covers

* open shoves (folded to the shover),
* re-shoves over an open raise (the opener is a caller whose range is capped
  by what they opened),
* and, by swapping roles, the range hero is up against when calling.

Simplifications: once somebody calls, the players behind fold (over-calls are
rare and need monsters), and card removal is applied against the shover's hand
only.  Both are standard in push/fold calculators.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

from .cards import HANDS, top_percent
from .equity import all_vs_range, allin_order
from .icm import Prizes
from .ranges import PLAYER_TYPES, norm_type

_CHART_PATH = os.path.join(os.path.dirname(__file__), "data", "nash_push.json")
_FULL = [1.0] * 169


class HandSetup:
    """Stacks and forced bets for one hand, players listed in preflop action order.

    Index 0 acts first preflop, the last two are SB and BB (heads-up: SB, BB).
    ``stacks`` are start-of-hand stacks, before antes and blinds.
    """

    def __init__(self, stacks, sb: float, bb: float, ante: float = 0.0, bb_ante: float = 0.0):
        n = len(stacks)
        if n < 2:
            raise ValueError("need at least two players")
        self.n = n
        self.start = [float(s) for s in stacks]
        self.sb, self.bb = float(sb), float(bb)
        self.antes = [min(float(ante), s) for s in self.start]
        if bb_ante:
            self.antes[n - 1] = min(self.start[n - 1], self.antes[n - 1] + float(bb_ante))
        self.blinds = [0.0] * n
        self.blinds[n - 2] = min(self.sb, self.start[n - 2] - self.antes[n - 2])
        self.blinds[n - 1] = min(self.bb, self.start[n - 1] - self.antes[n - 1])
        self.live = [s - a for s, a in zip(self.start, self.antes)]

    def dead_money(self) -> float:
        return sum(self.antes) + sum(self.blinds)

    def invested(self, bets: dict[int, float] | None = None) -> list[float]:
        """Live chips each player has in front (blind or a bet total, capped by stack)."""
        out = list(self.blinds)
        for i, amt in (bets or {}).items():
            out[i] = min(self.live[i], max(out[i], float(amt)))
        return out

    def fold_out(self, winner: int, bets: dict[int, float] | None = None) -> list[float]:
        """Stacks after everyone else gives up and ``winner`` takes the pot."""
        inv = self.invested(bets)
        # an uncalled bet comes back: the winner only wins what others put in
        out = [self.live[i] - inv[i] for i in range(self.n)]
        out[winner] = self.live[winner] + sum(inv[i] for i in range(self.n) if i != winner) \
            + sum(self.antes)
        return out

    def showdown(self, a: int, b: int, winner: int, bets: dict[int, float] | None = None) -> list[float]:
        """Stacks after ``a`` and ``b`` get all-in against each other."""
        inv = self.invested(bets)
        matched = min(self.live[a], self.live[b])
        pot = sum(self.antes) + 2.0 * matched + sum(inv[i] for i in range(self.n) if i not in (a, b))
        out = [self.live[i] - inv[i] for i in range(self.n)]
        loser = b if winner == a else a
        out[winner] = self.live[winner] - matched + pot
        out[loser] = self.live[loser] - matched
        return out


@dataclass
class Caller:
    idx: int
    label: str
    req: float            # equity this player needs to call
    v_win: float          # shover's value when the shover beats this caller
    v_lose: float         # shover's value when the shover loses to this caller
    prior: list[float] | None = None   # None = any two cards
    call_range: list[float] = field(default_factory=lambda: [0.0] * 169)
    chip_req: float = 0.0  # equity needed on pot odds alone (no ICM)


@dataclass
class Solution:
    ev: list[float]            # value of shoving minus value of folding, per hand class
    shove_range: list[float]
    callers: list[Caller]
    fold_equity: list[float]   # chance everyone folds, per shover hand class
    v_fold: float
    v_steal: float
    unit: float = 1.0          # value of one big blind, to express ev in bb
    eq_called: list[float] = field(default_factory=lambda: [0.5] * 169)  # equity when called

    def ev_bb(self, hand: int) -> float:
        return self.ev[hand] / self.unit if self.unit else 0.0

    def caller(self, idx: int) -> Caller | None:
        for c in self.callers:
            if c.idx == idx:
                return c
        return None


def beats_all(equities) -> float:
    """The chance to win a pot against several players at once, from the equity against each alone.

    Each opponent counts by his odds against the hand: 1 / (1 + the sum of (1 - e) / e).  Three hands of the
    same strength win a third each (the plain product of the equities would say a quarter), aces that have
    85% against each of two players win 74% against both, and against one player it is the equity itself."""
    against = 0.0
    for e in equities:
        if e <= 0.0:
            return 0.0
        against += (1.0 - e) / e
    return 1.0 / (1.0 + against)


def solve_shove(v_fold: float, v_steal: float, callers: list[Caller],
                shover_prior: list[float] | None = None, iters: int = 40,
                unit: float = 1.0, together: tuple | None = None) -> Solution:
    """Fictitious play between the shover's range and every caller's range.

    The shover is set against one caller at a time, in the order of ``callers``: when two would call, the
    first is the hand to beat and the other's chips are dead money.  ``together`` names callers for whom
    that is not good enough, as ``(members, values)``: they are taken first and as a group.  Each calls or
    folds on his own, and against those who call the shover has to beat all of them (``beats_all`` of his
    equities against each); ``values[mask]`` is ``(value when he does, value when he does not)`` for the
    members whose bit is set in ``mask``, in the order of ``members``.
    """
    prior = shover_prior or _FULL
    order = allin_order()
    shove = [min(p, w) for p, w in zip(prior, top_percent(35.0, order))]
    prior_mass = {}
    for c in callers:
        if c.prior is None:
            prior_mass[c.idx] = None
        else:
            prior_mass[c.idx] = all_vs_range(c.prior)[1]
        c.call_range = [0.0] * 169

    eq_called = [0.5] * 169

    members, group_values = together if together else ([], {})
    group = [c.idx for c in members]

    def shove_ev(use_callers):
        stay = [1.0] * 169
        ev = [0.0] * 169
        eq_num = [0.0] * 169
        if members:
            seen = [(all_vs_range(c.call_range), prior_mass[c.idx]) for c in members]
            k = len(members)
            for h in range(169):
                ps, es = [], []
                for (eqs, probs), pm in seen:
                    p = probs[h] if pm is None else (probs[h] / pm[h] if pm[h] > 0 else 0.0)
                    ps.append(1.0 if p > 1.0 else p)
                    es.append(eqs[h])
                for mask in range(1, 1 << k):
                    chance, odds = 1.0, [es[i] for i in range(k) if mask >> i & 1]
                    for i in range(k):
                        chance *= ps[i] if mask >> i & 1 else 1.0 - ps[i]
                    if chance <= 0.0:
                        continue
                    win = beats_all(odds)
                    vw, vl = group_values[mask]
                    ev[h] += chance * (win * vw + (1.0 - win) * vl)
                    eq_num[h] += chance * win
                for p in ps:
                    stay[h] *= 1.0 - p
        for c in use_callers:
            if c.idx in group:
                continue
            eqs, probs = all_vs_range(c.call_range)
            pm = prior_mass[c.idx]
            vw, vl = c.v_win, c.v_lose
            for h in range(169):
                p = probs[h] if pm is None else (probs[h] / pm[h] if pm[h] > 0 else 0.0)
                if p > 1.0:
                    p = 1.0
                e = eqs[h]
                ev[h] += stay[h] * p * (e * vw + (1.0 - e) * vl)
                eq_num[h] += stay[h] * p * e
                stay[h] *= 1.0 - p
        for h in range(169):
            ev[h] += stay[h] * v_steal - v_fold
            eq_called[h] = eq_num[h] / (1.0 - stay[h]) if stay[h] < 1.0 - 1e-12 else 0.5
        return ev, stay

    ev, stay = [0.0] * 169, [1.0] * 169
    for t in range(iters):
        step = 1.0 if t == 0 else 2.0 / (t + 3.0)
        eq_vs_shove, _ = all_vs_range(shove)
        for c in callers:
            pr = c.prior or _FULL
            cr = c.call_range
            req = c.req
            for h in range(169):
                target = pr[h] if eq_vs_shove[h] >= req else 0.0
                cr[h] += (target - cr[h]) * step
        ev, stay = shove_ev(callers)
        for h in range(169):
            target = prior[h] if ev[h] > 0 else 0.0
            shove[h] += (target - shove[h]) * step
    # tidy tiny weights left over from averaging
    for c in callers:
        c.call_range = [0.0 if w < 0.02 else w for w in c.call_range]
    ev, stay = shove_ev(callers)
    final = [prior[h] if ev[h] > 0 else 0.0 for h in range(169)]
    return Solution(ev=ev, shove_range=final, callers=callers, fold_equity=stay,
                    v_fold=v_fold, v_steal=v_steal, unit=unit, eq_called=list(eq_called))


def _call_req(v_fold: float, v_win: float, v_lose: float) -> float:
    span = v_win - v_lose
    if span <= 1e-12:
        return 1.0
    return max(0.0, min(1.0, (v_fold - v_lose) / span))


def _unit(prizes: Prizes, setup: HandSetup, idx: int) -> float:
    """Value of one big blind to player ``idx`` around their current stack."""
    if prizes.chip_ev:
        return setup.bb
    base = list(setup.live)
    up = list(base)
    step = min(setup.bb, max(base[idx] * 0.05, 1e-9))
    up[idx] += step
    d = prizes.value(up, idx) - prizes.value(base, idx)
    return d / step * setup.bb if d > 0 else 1e-9


def build_shove_spot(setup: HandSetup, shover: int, prizes: Prizes, *,
                     caller_prizes: Prizes | None = None,
                     types: list[str] | None = None, away: list[bool] | None = None,
                     bets: dict[int, float] | None = None,
                     priors: dict[int, list[float]] | None = None,
                     caller_order: list[int] | None = None,
                     fold_winner: int | None = None,
                     extra_req: dict[int, float] | None = None,
                     use_types: bool = True) -> tuple[float, float, list[Caller]]:
    """Value every branch of a shove.

    ``bets`` holds live chips already in front of players who raised or called
    (e.g. the opener's raise in a re-shove spot).  ``caller_order`` lists who
    may still call, in acting order; the default is everyone behind the shover.
    ``fold_winner`` is who takes the pot if the shover folds instead.

    ``prizes`` values the outcomes for the shover.  ``caller_prizes`` is what
    the callers play for (default: the same).  With ``use_types`` each caller
    only partly respects ICM, by player type: real opponents call wider on the
    bubble than a perfect ICM player would, and assuming otherwise makes
    shoving look far safer than it is.
    """
    cp = caller_prizes or prizes
    n = setup.n
    types = types or ["unknown"] * n
    away = away or [False] * n
    priors = priors or {}
    extra_req = extra_req or {}
    if caller_order is None:
        caller_order = [j for j in range(shover + 1, n)]
    caller_order = [j for j in caller_order if not away[j] and setup.live[j] > 0]
    if fold_winner is None:
        fold_winner = n - 1 if shover != n - 1 else (caller_order[0] if caller_order else 0)

    steal = setup.fold_out(shover, bets)
    v_steal = prizes.value(steal, shover)
    v_fold = prizes.value(setup.fold_out(fold_winner, bets), shover)
    inv = setup.invested(bets)
    callers = []
    for pos, j in enumerate(caller_order):
        win = setup.showdown(shover, j, shover, bets)
        lose = setup.showdown(shover, j, j, bets)
        matched = min(setup.live[shover], setup.live[j])
        to_call = matched - inv[j]
        pot_after = sum(setup.antes) + 2.0 * matched + sum(inv[i] for i in range(n) if i not in (shover, j))
        chip_req = to_call / pot_after if pot_after > 0 else 1.0
        if cp.chip_ev:
            req = chip_req
        else:
            req = _call_req(cp.value(steal, j), cp.value(lose, j), cp.value(win, j))
        adj = extra_req.get(j, 0.0)
        if use_types:
            info = PLAYER_TYPES[norm_type(types[j])]
            req = chip_req + info["icm_aware"] * (req - chip_req)
            adj += info["call_adj"]
        # players with opponents still to act behind them call a touch tighter
        adj += 0.004 * (len(caller_order) - 1 - pos)
        callers.append(Caller(
            idx=j, label=f"seat{j}", req=min(0.99, max(0.0, req + adj)),
            v_win=prizes.value(win, shover), v_lose=prizes.value(lose, shover),
            prior=priors.get(j), chip_req=chip_req,
        ))
    return v_fold, v_steal, callers


def solve_open_shove(setup: HandSetup, shover: int, prizes: Prizes, *, caller_prizes=None,
                     types=None, away=None, iters: int = 40, use_types: bool = True) -> Solution:
    v_fold, v_steal, callers = build_shove_spot(setup, shover, prizes, caller_prizes=caller_prizes,
                                                types=types, away=away, use_types=use_types)
    return solve_shove(v_fold, v_steal, callers, iters=iters, unit=_unit(prizes, setup, shover))


def solve_reshove(setup: HandSetup, shover: int, opener: int, raise_to: float, prizes: Prizes, *,
                  opener_range: list[float], flat_callers: dict[int, list[float]] | None = None,
                  caller_prizes=None, types=None, away=None, iters: int = 40,
                  use_types: bool = True) -> Solution:
    """Shover moves all-in over ``opener``'s raise (and any flat callers).

    Players behind the shover act first, then the opener, then the flat callers.
    """
    flat_callers = flat_callers or {}
    bets = {opener: raise_to}
    for j in flat_callers:
        bets[j] = raise_to
    n = setup.n
    behind = [j for j in range(shover + 1, n) if j != opener and j not in flat_callers]
    order = behind + [opener] + list(flat_callers)
    priors = {opener: opener_range}
    priors.update(flat_callers)
    extra = {j: 0.02 for j in behind}  # cold-calling a raise and a shove needs a real hand
    v_fold, v_steal, callers = build_shove_spot(
        setup, shover, prizes, caller_prizes=caller_prizes, types=types, away=away, bets=bets,
        priors=priors, caller_order=order, fold_winner=opener, extra_req=extra, use_types=use_types)
    return solve_shove(v_fold, v_steal, callers, iters=iters, unit=_unit(prizes, setup, shover))


# --------------------------------------------------------------------------
# Precomputed chip-EV Nash push charts (equal stacks), used to model how wide
# opponents shove and as a quick reference for hero.
# --------------------------------------------------------------------------

CHART_STACKS = list(range(1, 26))


def _chart_cell(args) -> tuple[str, int, int, list[int]]:
    ante_key, n_behind, stack = args
    n = n_behind + 1
    setup = HandSetup([float(stack)] * n, 0.5, 1.0, 0.0, 1.0 if ante_key == "ante" else 0.0)
    sol = solve_open_shove(setup, 0, Prizes(), iters=60, use_types=False)
    return ante_key, n_behind, stack, [h for h in range(169) if sol.ev[h] > 0]


def build_charts(processes: int = 4) -> dict:
    """Solve the equal-stack push ranges for every seat and stack depth."""
    from multiprocessing import Pool

    jobs = [(a, nb, s) for a in ("ante", "noante") for nb in range(1, 9) for s in CHART_STACKS]
    with Pool(processes) as pool:
        cells = pool.map(_chart_cell, jobs, chunksize=4)
    charts: dict = {"stacks": CHART_STACKS, "ante": {}, "noante": {}}
    for ante_key, nb, stack, hands in cells:
        table = charts[ante_key].setdefault(str(nb), {})
        for h in hands:
            name = HANDS[h]
            table[name] = max(table.get(name, 0), stack)
    with open(_CHART_PATH, "w") as fh:
        json.dump(charts, fh, separators=(",", ":"), sort_keys=True)
    return charts


@lru_cache(maxsize=1)
def _charts() -> dict:
    with open(_CHART_PATH) as fh:
        return json.load(fh)


def nash_push_range(n_behind: int, stack_bb: float, has_ante: bool = True) -> list[float]:
    """Equal-stack chip-EV Nash open-shoving range for a seat and stack depth."""
    table = _charts()["ante" if has_ante else "noante"][str(max(1, min(8, n_behind)))]
    s = max(1.0, stack_bb)
    if s > CHART_STACKS[-1]:
        # deeper than the charts: only hands that shove at the deepest charted
        # stack and do not mind getting it in
        keep = {"TT", "JJ", "QQ", "KK", "AA", "99", "88", "77", "AKs", "AKo", "AQs", "AQo", "AJs", "KQs"}
        return [1.0 if HANDS[h] in keep and table.get(HANDS[h], 0) >= CHART_STACKS[-1] else 0.0
                for h in range(169)]
    return [1.0 if table.get(HANDS[h], 0) >= s - 0.5 else 0.0 for h in range(169)]


def push_limit_bb(n_behind: int, hand: int, has_ante: bool = True) -> int:
    """Deepest equal stack (bb) at which the chart shoves this hand from this seat."""
    table = _charts()["ante" if has_ante else "noante"][str(max(1, min(8, n_behind)))]
    return int(table.get(HANDS[hand], 0))
