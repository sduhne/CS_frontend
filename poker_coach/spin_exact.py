"""Spins solved exactly: three players (or two), no ante, one prize, stacks as they are.

A spin (GGPoker Spin & Gold, PokerStars Spin & Go) is played for one prize in nearly every game, so chips
are money and the chip game is the game.  It has no ante: GGPoker's Spin & Gold has none, unlike the
tournament tables of ``short`` (a big blind ante of one big blind), and an ante makes every player move in
and call with more hands.  Stacks are rarely equal, and the player with the most chips is often short in
big blinds too.  So this game is solved as it is played (``tools/build_spin_exact.py`` with the solver of
``tools/aof_solver.c``: real cards, every side pot), with unequal stacks:

* Of three stacks only two numbers matter.  The chips the biggest stack has over the second biggest can never
  change hands, so the biggest is cut down to the second.  What is left is two players with the same stack
  ``X`` and one with ``Y`` (no more than ``X``), in one of the three seats: that is the grid solved
  (``X`` from 2 to 30 big blinds, ``Y`` from 1 big blind up).  Between two solved stacks the answers are drawn
  in a straight line, first along ``Y``, then along ``X``.  Heads-up only the smaller stack matters.
* Every player moves all-in or folds.  That is how solvers play with about 10 big blinds or less.  Deeper they
  also raise small and limp; there the engine takes from this only what an all-in earns, first in, and what
  calling one or two all-ins earns (``preflop``).
* Three sets of answers: ``solid`` (the equilibrium), ``loose`` (the best reply to opponents who move all-in
  first in as solved but call with half as many hands again: the common mistake of low-stakes spins) and
  ``tight`` (the best reply to opponents who move all-in and call with four fifths of the solved hands).

Seats are the engine's places at the table: three players 0 the button, 1 the small blind, 2 the big blind;
heads-up 0 the small blind (the button), 1 the big blind.  A mask has the bit of every player all-in before.
"""
from __future__ import annotations

import bisect
import json
import os
from functools import lru_cache

from .cards import COMBO_COUNT

_PATH = os.path.join(os.path.dirname(__file__), "data", "spin_exact.json")
DATA_VERSION = 1
SEATS = ("BTN", "SB", "BB")
PROFILES = ("solid", "loose", "tight")
SHOVE_CALL = {"solid": (1.0, 1.0), "loose": (1.0, 1.5), "tight": (0.8, 0.8)}       # opponents' all-ins and calls,
                                                                                    # as a share of the solved ones
CLOSE_BB = 0.05             # a play worth less than this either way is close (more with a deeper stack: ``close``)
Y_FLOOR = 1.0               # a short stack under one big blind is read as one big blind (it is all-in from the blind)


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        with open(_PATH) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return d if d.get("version") == DATA_VERSION else {}


def available() -> bool:
    return bool(_data())


def x_grid() -> tuple[float, ...]:
    return tuple(float(v) for v in _data().get("x", ()))


def y_grid() -> tuple[float, ...]:
    return tuple(float(v) for v in _data().get("y", ()))


def hu_grid() -> tuple[float, ...]:
    return tuple(float(v) for v in _data().get("hu", ()))


def reduce(stacks: list[float] | tuple[float, ...]) -> tuple[float, float, int]:
    """Three stacks (button, small blind, big blind; big blinds) as ``(X, Y, seat of the short stack)``.

    The biggest stack is cut down to the second biggest; the seat is -1 when all three are then equal."""
    second = sorted(stacks)[1]
    capped = [min(v, second) for v in stacks]
    low = min(capped)
    if low >= second - 1e-9:
        return second, second, -1
    return second, low, capped.index(low)


def config_key(x: float, y: float, seat: int) -> str:
    """The key of a solved three-player configuration (``x`` and ``y`` on the grid)."""
    return f"{x:g}" if seat < 0 or y >= x - 1e-9 else f"{x:g},{y:g},{SEATS[seat]}"


def _table(players: int, key: str, player: int, mask: int, profile: str) -> list[int] | None:
    entry = _data()["games"][str(players)].get(key)
    if entry is None:
        return None
    return entry[profile].get(f"{player}:{mask}")


def _line(points: tuple[float, ...] | list[float], v: float) -> tuple[float, float, float]:
    """(lower point, upper point, weight of the upper) for ``v`` between two points of a sorted list."""
    v = min(max(v, points[0]), points[-1])
    i = bisect.bisect_left(points, v - 1e-9)
    if i < len(points) and abs(points[i] - v) <= 1e-9:
        return points[i], points[i], 0.0
    lo, hi = points[i - 1], points[i]
    return lo, hi, (v - lo) / (hi - lo)


def _mix(a: list[float], b: list[float], t: float) -> list[float]:
    return a if t == 0.0 else [x + (y - x) * t for x, y in zip(a, b)]


def _at_x(x: float, y: float, seat: int, player: int, mask: int, profile: str) -> list[float] | None:
    """One grid ``X``: the answers drawn along ``Y`` (the equal stacks are the last point)."""
    points = [v for v in y_grid() if v < x - 1e-9] + [x]
    lo, hi, t = _line(points, min(max(y, Y_FLOOR), x))
    a = _table(3, config_key(x, lo, seat), player, mask, profile)
    b = a if t == 0.0 else _table(3, config_key(x, hi, seat), player, mask, profile)
    if a is None or b is None:
        return None
    return _mix([v / 100.0 for v in a], [v / 100.0 for v in b], t)


def node(players: int, stacks: list[float] | tuple[float, ...], player: int, mask: int,
         profile: str = "solid") -> list[float] | None:
    """What going in earns over folding, in big blinds, for each of the 169 hands; None outside the grid.

    ``stacks``: the stacks in big blinds in seat order (three: button, small blind, big blind; heads-up: small
    blind, big blind); ``player`` decides now with the players of ``mask`` all-in before him."""
    if not available() or profile not in PROFILES or players not in (2, 3) or len(stacks) != players:
        return None
    if players == 2:
        grid = hu_grid()
        e = min(stacks)
        if not grid or e < grid[0] - 1e-9 or e > grid[-1] + 1e-9:
            return None
        lo, hi, t = _line(grid, e)
        a, b = _table(2, f"{lo:g}", player, mask, profile), _table(2, f"{hi:g}", player, mask, profile)
        if a is None or b is None:
            return None
        return _mix([v / 100.0 for v in a], [v / 100.0 for v in b], t)
    x, y, seat = reduce(stacks)
    grid = x_grid()
    if not grid or x < grid[0] - 1e-9 or x > grid[-1] + 1e-9:
        return None
    lo, hi, t = _line(grid, x)
    a = _at_x(lo, y, seat, player, mask, profile)
    b = a if t == 0.0 else _at_x(hi, y, seat, player, mask, profile)
    if a is None or b is None:
        return None
    return _mix(a, b, t)


def _valid(players: int, actor: int, mask: int) -> bool:
    if players == 2:
        return (actor, mask) in ((0, 0), (1, 1))
    return (actor, mask) in ((0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (2, 3))


def covered(setup, actor: int, all_in: list[int] | tuple = ()) -> tuple[float, ...] | None:
    """The stacks (big blinds, seat order) at which this spot is one of the solved game; None when it is not.

    It is the solved game with two or three players, blinds of a half and one big blind, no ante of any kind,
    every player before the actor folded or all-in for his whole stack, and the stacks on the grid."""
    n = setup.n
    if not available() or n not in (2, 3) or len(set(all_in)) != len(all_in):
        return None
    bb = setup.bb
    if bb <= 0 or abs(setup.sb - 0.5 * bb) > 1e-9 or any(abs(a) > 1e-9 for a in setup.antes):
        return None
    if any(j >= actor for j in all_in):
        return None
    mask = sum(1 << j for j in all_in)
    if not _valid(n, actor, mask):
        return None
    stacks = tuple(s / bb for s in setup.start)
    return stacks if node(n, stacks, actor, mask) is not None else None


def answer(setup, actor: int, all_in: list[int] | tuple = (), profile: str = "solid") -> list[float] | None:
    """``node`` for a spot of the engine: 169 numbers in big blinds, or None when the spot is not covered."""
    stacks = covered(setup, actor, all_in)
    if stacks is None:
        return None
    return node(setup.n, stacks, actor, sum(1 << j for j in all_in), profile)


def plays(evs: list[float], k: float = 1.0) -> list[float]:
    """The hands a player of the solved game plays (0 or 1 each), or ``k`` times as many of them, the best first:
    how the opponents of the ``loose`` and ``tight`` answers are taken to play."""
    if k == 1.0:
        return [1.0 if e > 0 else 0.0 for e in evs]
    base = sum(c for e, c in zip(evs, COMBO_COUNT) if e > 0)
    out, acc = [0.0] * 169, 0.0
    for h in sorted(range(169), key=lambda h: -evs[h]):
        if acc >= k * base - 1e-9:
            break
        out[h] = 1.0
        acc += COMBO_COUNT[h]
    return out


def profile_of(types, actor: int) -> str:
    """The answers for the players around ``actor``: loose or tight when every one of them is tagged so."""
    from .ranges import norm_type
    kinds = {norm_type(t) for j, t in enumerate(types or ()) if j != actor}
    kinds = {"unknown" if k == "tag" else k for k in kinds}
    if kinds == {"loose"}:
        return "loose"
    if kinds == {"tight"}:
        return "tight"
    return "solid"


def close(stack_bb: float, all_in: int = 1, profile: str = "solid") -> float:
    """How near to zero a play is called close, in big blinds: about twice the noise of the number.

    The equilibrium is sampled 50,000 times a hand, the best replies 20,000 times; the noise grows with the
    stack (an all-in of 20bb swings more than one of 5bb)."""
    base = max(CLOSE_BB, 0.005 * stack_bb)
    return base if profile == "solid" else base * 1.5


def width(evs: list[float]) -> float:
    """Percent of all hands that go in."""
    return 100.0 * sum(c for c, e in zip(COMBO_COUNT, evs) if e > 0) / 1326.0
