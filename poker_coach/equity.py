"""Equity calculations.

Preflop all-in equities come from a precomputed 169x169 class matrix
(``data/preflop_equity.json``, built by ``tools/gen_preflop_equity.c``) so that
range-vs-range maths is instant.  Postflop equities are computed with the
evaluator: exact enumeration on the turn and river against one opponent,
Monte Carlo otherwise.
"""

from __future__ import annotations

import json
import os
import random
from functools import lru_cache

from .cards import CLASS_COMBOS, COMBO_COUNT, HANDS
from .evaluator import NIB, SBIT, SCNT, value_from_acc

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "preflop_equity.json")


class _Matrix:
    def __init__(self) -> None:
        with open(_DATA_PATH) as fh:
            data = json.load(fh)
        if data["hands"] != HANDS:
            raise RuntimeError("preflop equity table does not match the hand grid")
        self.eq: list[list[float]] = data["eq"]
        self.n: list[list[int]] = data["n"]
        # w[h][c] = pairs * equity, the numerator of a card-removal-aware average
        self.w = [[n * e for n, e in zip(nr, er)] for nr, er in zip(self.n, self.eq)]


@lru_cache(maxsize=1)
def matrix() -> _Matrix:
    return _Matrix()


def class_equity(a: int, b: int) -> float:
    """All-in preflop equity of class ``a`` against class ``b``."""
    return matrix().eq[a][b]


def eq_vs_range(hand: int, weights) -> tuple[float, float]:
    """Equity of a hand class against a range, and how often the range occurs.

    Returns ``(equity, prob)`` where ``prob`` is the chance that one random
    opponent hand falls in the range given hero's cards (card removal).
    """
    m = matrix()
    nr, wr = m.n[hand], m.w[hand]
    num = den = 0.0
    for c, wt in enumerate(weights):
        if wt:
            num += wt * wr[c]
            den += wt * nr[c]
    if den <= 0:
        return 0.5, 0.0
    return num / den, den / (COMBO_COUNT[hand] * 1225.0)


def all_vs_range(weights) -> tuple[list[float], list[float]]:
    """``eq_vs_range`` for all 169 hero classes at once (sparse over the range)."""
    m = matrix()
    idx = [c for c, wt in enumerate(weights) if wt]
    wts = [weights[c] for c in idx]
    eqs, probs = [0.5] * 169, [0.0] * 169
    if not idx:
        return eqs, probs
    for h in range(169):
        nr, wr = m.n[h], m.w[h]
        num = den = 0.0
        for c, wt in zip(idx, wts):
            num += wt * wr[c]
            den += wt * nr[c]
        if den > 0:
            eqs[h] = num / den
            probs[h] = den / (COMBO_COUNT[h] * 1225.0)
    return eqs, probs


def range_vs_range(a, b) -> float:
    """Equity of range ``a`` against range ``b``."""
    m = matrix()
    num = den = 0.0
    for h, wa in enumerate(a):
        if not wa:
            continue
        nr, wr = m.n[h], m.w[h]
        for c, wb in enumerate(b):
            if wb:
                num += wa * wb * wr[c]
                den += wa * wb * nr[c]
    return num / den if den else 0.5


@lru_cache(maxsize=1)
def allin_order() -> tuple[int, ...]:
    """The 169 classes ordered by all-in strength, strongest first.

    Blends equity against any two cards with equity against progressively
    tighter ranges, so it tracks how hands fare when called by good hands.
    """
    from .cards import top_percent

    full = [1.0] * 169
    score, _ = all_vs_range(full)
    order = sorted(range(169), key=lambda h: -score[h])
    for _ in range(2):
        total = [0.0] * 169
        for pct in (100.0, 50.0, 25.0, 12.0):
            eqs, _ = all_vs_range(top_percent(pct, order))
            for h in range(169):
                total[h] += eqs[h]
        order = sorted(range(169), key=lambda h: -total[h])
    return tuple(order)


# --------------------------------------------------------------------------
# Concrete cards (postflop, multiway)
# --------------------------------------------------------------------------

def expand_range(weights, dead=()) -> tuple[list[tuple[int, int]], list[float]]:
    """Concrete combos of a range that avoid the dead cards, with weights."""
    dead = set(dead)
    combos, wts = [], []
    for idx, wt in enumerate(weights):
        if wt <= 0:
            continue
        for c1, c2 in CLASS_COMBOS[idx]:
            if c1 in dead or c2 in dead:
                continue
            combos.append((c1, c2))
            wts.append(wt)
    return combos, wts


def _acc(cards, acc=0, sacc=0, scnt=0):
    for c in cards:
        acc += NIB[c]
        sacc |= SBIT[c]
        scnt += SCNT[c]
    return acc, sacc, scnt


def hand_equity(hero, board, villain_ranges, iters: int = 6000, seed: int | None = 7,
                villain_combos=None) -> dict:
    """Equity of hero's two concrete cards against one or more ranges.

    ``villain_ranges`` is a list of 169-weight ranges, one per opponent still
    in the hand.  ``villain_combos`` may instead give explicit
    ``(combos, weights)`` lists (already narrowed, e.g. by postflop action).
    Returns ``{"equity", "win", "tie", "method", "n"}``.
    """
    hero = tuple(hero)
    board = list(board)
    known = set(hero) | set(board)
    if villain_combos is None:
        villain_combos = [expand_range(r, known) for r in villain_ranges]
    else:
        villain_combos = [
            ([c for c in cs if c[0] not in known and c[1] not in known],
             [w for c, w in zip(cs, ws) if c[0] not in known and c[1] not in known])
            for cs, ws in villain_combos
        ]
    if any(not cs for cs, _ in villain_combos):
        return {"equity": 1.0, "win": 1.0, "tie": 0.0, "method": "empty range", "n": 0}
    need = 5 - len(board)
    base = _acc(board)
    hero_base = _acc(hero, *base)

    if len(villain_combos) == 1 and need <= 1:
        combos, wts = villain_combos[0]
        deck = [c for c in range(52) if c not in known]
        win = tie = total = 0.0
        if need == 0:
            hv = value_from_acc(*hero_base)
            for (c1, c2), wt in zip(combos, wts):
                vv = value_from_acc(base[0] + NIB[c1] + NIB[c2], base[1] | SBIT[c1] | SBIT[c2],
                                    base[2] + SCNT[c1] + SCNT[c2])
                total += wt
                if hv > vv:
                    win += wt
                elif hv == vv:
                    tie += wt
        else:
            for r in deck:
                ba, bs, bc = base[0] + NIB[r], base[1] | SBIT[r], base[2] + SCNT[r]
                hv = value_from_acc(hero_base[0] + NIB[r], hero_base[1] | SBIT[r], hero_base[2] + SCNT[r])
                for (c1, c2), wt in zip(combos, wts):
                    if c1 == r or c2 == r:
                        continue
                    vv = value_from_acc(ba + NIB[c1] + NIB[c2], bs | SBIT[c1] | SBIT[c2],
                                        bc + SCNT[c1] + SCNT[c2])
                    total += wt
                    if hv > vv:
                        win += wt
                    elif hv == vv:
                        tie += wt
        if total <= 0:
            return {"equity": 0.5, "win": 0.0, "tie": 0.0, "method": "empty range", "n": 0}
        return {"equity": (win + tie / 2) / total, "win": win / total, "tie": tie / total,
                "method": "exact", "n": int(total)}

    rng = random.Random(seed)
    deck = [c for c in range(52) if c not in known]
    draws = [rng.choices(cs, weights=ws, k=iters) for cs, ws in villain_combos]
    nv = len(villain_combos)
    score = wins = ties = 0.0
    n = 0
    sample = rng.sample
    for it in range(iters):
        used = set()
        ok = True
        for v in range(nv):
            c1, c2 = draws[v][it]
            if c1 in used or c2 in used:
                ok = False
                break
            used.add(c1)
            used.add(c2)
        if not ok:
            continue
        if need:
            run = sample(deck, need)
            while any(c in used for c in run):
                run = sample(deck, need)
            ba, bs, bc = _acc(run, *base)
            hv = value_from_acc(*_acc(run, *hero_base))
        else:
            ba, bs, bc = base
            hv = value_from_acc(*hero_base)
        best = -1
        nbest = 0
        for v in range(nv):
            c1, c2 = draws[v][it]
            vv = value_from_acc(ba + NIB[c1] + NIB[c2], bs | SBIT[c1] | SBIT[c2],
                                bc + SCNT[c1] + SCNT[c2])
            if vv > best:
                best, nbest = vv, 1
            elif vv == best:
                nbest += 1
        n += 1
        if hv > best:
            score += 1.0
            wins += 1.0
        elif hv == best:
            score += 1.0 / (nbest + 1)
            ties += 1.0
    if n == 0:
        return {"equity": 0.5, "win": 0.0, "tie": 0.0, "method": "no valid samples", "n": 0}
    return {"equity": score / n, "win": wins / n, "tie": ties / n, "method": "monte carlo", "n": n}


def preflop_equity(hand_class: int, hero_cards, villain_ranges, iters: int = 8000) -> float:
    """Preflop all-in equity against one or more ranges.

    One opponent uses the exact class matrix; several opponents use Monte
    Carlo with concrete cards (a representative combo if only a class is known).
    """
    if len(villain_ranges) == 1:
        return eq_vs_range(hand_class, villain_ranges[0])[0]
    hero = hero_cards or CLASS_COMBOS[hand_class][0]
    return hand_equity(hero, [], villain_ranges, iters=iters)["equity"]
