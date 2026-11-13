"""Tournament equity (ICM) for any field size.

The Malmuth-Harville model says the chance of finishing first is proportional
to your stack, then repeats on the remaining players for second place, and so
on.  That is the same as giving every player an exponential clock with rate
equal to their stack and ranking by who rings first.  Conditional on hero's
clock time ``t`` the other players are independent, each ahead of hero with
probability ``1 - exp(-stack * t)``, so hero's finishing distribution is a
one-dimensional integral over ``t``:

* players whose stacks are known (hero's table) are convolved exactly,
* the rest of the field (other tables) is modelled as ``field_n`` players
  holding ``field_stack`` each, a binomial count.

This gives the exact ICM value on a final table and a sound value in the
middle of a 1,000-player field, in a few milliseconds either way.
"""

from __future__ import annotations

import math
from functools import lru_cache
from itertools import permutations


def mh_exact(stacks, payouts) -> list[float]:
    """Brute-force Malmuth-Harville equities (small tables; used for tests)."""
    n = len(stacks)
    pay = list(payouts)[:n] + [0.0] * max(0, n - len(payouts))
    eq = [0.0] * n
    live = [i for i in range(n) if stacks[i] > 0]
    dead = [i for i in range(n) if stacks[i] <= 0]
    for order in permutations(live):
        p = 1.0
        remaining = sum(stacks[i] for i in live)
        for i in order:
            p *= stacks[i] / remaining
            remaining -= stacks[i]
        for place, i in enumerate(order):
            eq[i] += p * pay[place]
    # players with no chips share the last places
    for k, i in enumerate(dead):
        eq[i] = pay[len(live) + k] if len(live) + k < len(pay) else 0.0
    return eq


def _tiers(payouts) -> list[tuple[int, float]]:
    """Payout steps: ``(k, d)`` meaning finishing in the top ``k`` earns ``d`` more."""
    tiers = []
    for k in range(1, len(payouts) + 1):
        nxt = payouts[k] if k < len(payouts) else 0.0
        d = payouts[k - 1] - nxt
        if d > 1e-12:
            tiers.append((k, d))
    return tiers


def hero_equity(stacks, idx: int, payouts, field_n: int = 0, field_stack: float = 0.0) -> float:
    """ICM value of player ``idx``.

    ``stacks`` are the known stacks (hero's table).  ``payouts`` lists the
    prizes from first place down.  ``field_n`` other players, each holding
    ``field_stack``, complete the field.  A player with no chips is treated as
    eliminated right now.
    """
    payouts = list(payouts)
    live_others = [s for i, s in enumerate(stacks) if i != idx and s > 0]
    n_total = len(live_others) + field_n + 1
    s_h = stacks[idx]
    if s_h <= 0:
        # hero busts now, behind everybody still holding chips
        return payouts[n_total - 1] if n_total - 1 < len(payouts) else 0.0
    if not payouts:
        return 0.0
    payouts = payouts[:n_total]
    tiers = _tiers(payouts)
    if not tiers:
        return 0.0
    kmax = tiers[-1][0]  # places beyond this pay nothing extra
    total = s_h + sum(live_others) + field_n * field_stack
    nt = len(live_others)

    # log-spaced trapezoid in t; see module docstring
    t_lo = 1e-5 / total
    t_hi = 40.0 / s_h
    step = 0.2
    if field_n > 0:
        step = min(0.2, 0.8 / math.sqrt(max(1.0, min(kmax, field_n))))
    y0, y1 = math.log(t_lo), math.log(t_hi)
    nodes = int((y1 - y0) / step) + 1
    exp = math.exp

    result = payouts[0] * (1.0 - exp(-s_h * t_lo))  # nobody can be ahead that early
    last_all_paid = payouts[n_total - 1] if n_total - 1 < len(payouts) else 0.0

    for i in range(nodes + 1):
        t = exp(y0 + i * step)
        dens = s_h * t * exp(-s_h * t)
        if dens < 1e-17:
            if s_h * t > 1:
                break
            continue
        # exact distribution of how many table players are ahead of hero
        dist = [1.0]
        for s in live_others:
            p = 1.0 - exp(-s * t)
            q = 1.0 - p
            new = [0.0] * (len(dist) + 1)
            for k, v in enumerate(dist):
                new[k] += v * q
                new[k + 1] += v * p
            dist = new[:kmax] if len(new) > kmax else new
        if field_n > 0:
            pf = 1.0 - exp(-field_stack * t)
            mean = field_n * pf
            sd = math.sqrt(max(mean * (1.0 - pf), 1e-12))
            if mean - 9.0 * sd > kmax:
                # the field alone pushes hero out of every paid place from here on
                break
            # binomial cdf up to kmax-1, truncated once the mass is exhausted
            cdf: list[float] = []
            limit = min(kmax, field_n + 1)
            acc = 0.0
            if pf >= 1.0:
                # every field player is ahead
                cdf = [0.0] * min(limit, field_n) + ([1.0] if limit > field_n else [])
            else:
                pmf = (1.0 - pf) ** field_n if pf > 0.0 else 1.0
                ratio = pf / (1.0 - pf)
                if pmf > 0.0 or pf <= 0.0:
                    cut = mean + 10.0 * sd + 12.0
                    for b in range(limit):
                        acc += pmf
                        cdf.append(acc)
                        if b > cut:
                            break
                        pmf *= (field_n - b) / (b + 1.0) * ratio
                else:
                    # (1-p)^n underflowed: walk the pmf in log space instead
                    logp = field_n * math.log1p(-pf)
                    logr = math.log(ratio)
                    for b in range(limit):
                        if logp > -700.0:
                            acc += exp(logp)
                        cdf.append(acc)
                        if b < field_n:
                            logp += math.log((field_n - b) / (b + 1.0)) + logr
            ncdf = len(cdf)
            g = 0.0
            for k, d in tiers:
                # P(table ahead + field ahead <= k-1)
                pk = 0.0
                for tcount, v in enumerate(dist):
                    m = k - 1 - tcount
                    if m < 0:
                        break
                    pk += v * (cdf[m] if m < ncdf else 1.0)
                g += d * pk
        else:
            g = 0.0
            run = 0.0
            ti = 0
            ntiers = len(tiers)
            for tcount, v in enumerate(dist):
                run += v
                # tiers with k-1 == tcount receive the running cdf
                while ti < ntiers and tiers[ti][0] - 1 == tcount:
                    g += tiers[ti][1] * run
                    ti += 1
            # tiers deeper than the table size are always satisfied
            while ti < ntiers:
                if tiers[ti][0] - 1 >= len(dist):
                    g += tiers[ti][1] * run
                ti += 1
        result += g * dens * step
    else:
        t = exp(y0 + nodes * step)
        result += last_all_paid * exp(-s_h * t)
    return result


def default_payouts(entrants: int, paid: int | None = None, pool: float | None = None,
                    buyin: float = 1.0) -> list[float]:
    """A typical top-heavy MTT payout table when the real one is unknown.

    About 15% of the field is paid, the minimum cash is about 1.8 buy-ins and
    places beyond the final table are grouped into tiers like real lobbies.
    """
    entrants = max(2, int(entrants))
    if paid is None:
        paid = max(1, round(entrants * 0.15)) if entrants > 10 else max(1, round(entrants / 3))
    paid = max(1, min(paid, entrants))
    pool = pool if pool is not None else entrants * buyin
    if paid == 1:
        return [pool]
    if paid <= 3:
        shares = {2: [0.65, 0.35], 3: [0.5, 0.3, 0.2]}[paid]
        return [pool * s for s in shares]
    min_cash = min(1.8 * pool / entrants, 0.6 * pool / paid)
    beta = 1.0

    # tier boundaries: single places to 9th, then widening groups
    bounds = []
    place = 1
    while place <= paid:
        size = 1 if place <= 9 else max(3, place // 4)
        end = min(paid, place + size - 1)
        bounds.append((place, end))
        place = end + 1
    shape = []
    for a, b in bounds:
        mid = math.sqrt(a * b)
        shape.append(mid ** -beta - paid ** -beta)
    weight = sum(s * (b - a + 1) for s, (a, b) in zip(shape, bounds))
    scale = (pool - paid * min_cash) / weight if weight > 0 else 0.0
    out: list[float] = []
    for s, (a, b) in zip(shape, bounds):
        out += [min_cash + scale * s] * (b - a + 1)
    return out


class Prizes:
    """What chips are worth for one decision: the payout table plus the field.

    ``value(stacks, idx)`` returns the tournament value of a stack
    configuration for the player at ``idx``.  With no tournament information
    it falls back to chip EV (value = chips).
    """

    def __init__(self, payouts=None, field_n: int = 0, field_stack: float = 0.0,
                 itm_bonus: float = 0.0, label: str = "") -> None:
        self.raw_payouts = list(payouts) if payouts else []
        self.field_n = max(0, int(field_n))
        self.field_stack = max(0.0, float(field_stack))
        self.itm_bonus = itm_bonus
        self.label = label
        # the utility hero maximises: real prizes plus an optional bonus for cashing
        self.payouts = [p + itm_bonus for p in self.raw_payouts]
        self._cache: dict = {}

    @property
    def chip_ev(self) -> bool:
        return not self.payouts

    def value(self, stacks, idx: int) -> float:
        if not self.payouts:
            return float(stacks[idx])
        key = (tuple(round(s, 3) for s in stacks), idx)
        v = self._cache.get(key)
        if v is None:
            v = self._cache[key] = hero_equity(stacks, idx, self.payouts, self.field_n, self.field_stack)
        return v

    def bubble_factor(self, stacks, hero: int, villain: int, amount: float | None = None) -> float:
        """Cost of losing an all-in against ``villain`` relative to the gain of winning.

        1.0 is chip EV; 1.5 means a lost chip hurts 1.5x as much as a won chip helps.
        """
        if not self.payouts:
            return 1.0
        amt = min(stacks[hero], stacks[villain]) if amount is None else amount
        base = self.value(stacks, hero)
        win = list(stacks)
        win[hero] += amt
        win[villain] -= amt
        lose = list(stacks)
        lose[hero] -= amt
        lose[villain] += amt
        gain = self.value(win, hero) - base
        loss = base - self.value(lose, hero)
        if gain <= 1e-12:
            return 99.0
        return loss / gain

    def risk_premium(self, stacks, hero: int, villain: int) -> float:
        """Extra equity needed over 50% for an even-money all-in against ``villain``."""
        bf = self.bubble_factor(stacks, hero, villain)
        return bf / (1.0 + bf) - 0.5


@lru_cache(maxsize=64)
def _cached_default_payouts(entrants: int, paid: int | None, pool: float | None) -> tuple:
    return tuple(default_payouts(entrants, paid, pool))
