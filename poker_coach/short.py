"""All-ins of 2 to 20 big blinds, solved exactly.

With ten big blinds or less a hand is an all-in or a fold for everybody, and the whole game before the
flop is a small tree: who has moved all-in before you.  ``tools/aof_solver.c`` solves that tree with
real cards and every showdown, side pots included; ``tools/build_short.py`` runs it for equal stacks, a
small blind of half a big blind and a big blind ante of one, at tables of 9, 6, 5, 4 and 3 players, and
``data/short.json`` keeps the answers for stacks of 2 big blinds up to ``top()``: for each player and
each set of at most two players all-in before him, what going in earns over folding, hand by hand.

It is solved for every stack from 2 to 10 big blinds and for 12, 16 and 20; between two solved stacks
the answers are drawn in a straight line.  The numbers come from dealing cards, so they carry noise: the
hands near zero, which decide where a range ends, are sampled a second time with ten times the deals,
and first in the ones still nearest zero a third time with a hundred times (``tools/build_short.py``
says how; the data file keeps what each pass did and what its numbers are good to, stack by stack).
Above ten big blinds the tree is not the whole game any more (there are small raises), but the all-in
is still one of the plays, and what it earns first in, and what calling one or two earns, is read here:
the engine weighs a first-in all-in up to 20 big blinds.

Why it is needed.  The engine's own solver (``pushfold``) leaves two things out, and this short both
matter:

* It sets the player who moves all-in against one caller at a time: when two would call, the first is
  the hand to beat and the other's chips are dead money.  With a few big blinds the big blind calls with
  nearly everything and a second caller is the rule.  With 3bb and nine players it moved all-in first to
  act with 84% of hands where the answer is 25%, and called an all-in on the button with 76% where it is
  23%.
* It deals every opponent a hand from a full deck.  But the players who folded hold mostly the middle
  and low cards they folded, so those cards are rarer on the board and in the hands still to come, and
  the aces and kings are not: at a full table a hand like T8o is about three points worse against an
  all-in than its plain equity says, a small ace a little better.  With 6bb and nine players the big
  blind called a cutoff all-in with 65% of hands where the answer is 47%.

Against the published heads-up equilibrium, where neither matters, the engine's solver is right to a
hand in three hundred.

A spot of the engine is one of this game when it is played for chips with those blinds and that ante,
the players who are all-in hold the same stack, and nobody who still has to act holds less (``covered``).
Tables of 7 and 8 players are read from the last seats of the nine: the seats that are not there count as
players who folded, which costs about a thousandth of a big blind a hand at eight.  Two players are left
to the engine's solver, which is exact heads-up.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from .cards import COMBO_COUNT

_PATH = os.path.join(os.path.dirname(__file__), "data", "short.json")
DATA_VERSION = 3            # 3: the passes the file was made with and what they did; a number can be finer than a hundredth
PLAYERS = 9                 # the biggest table solved; tables with no solution of their own are its last seats
MOST_ALL_IN = 2             # the answers are kept for at most this many players all-in before the one who decides
CLOSE_BB = 0.05             # a call worth less than this either way is close: a number near zero comes from the second
                            # pass (tools/build_short.py), and with one player all-in before it is good to 0.02bb with
                            # 6bb and 0.035bb with 10bb
CLOSE_TWO = 0.05            # ... and with two players all-in before, where three stacks swing, to as much with 6bb and
                            # a third more with 20bb


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


def games() -> tuple[int, ...]:
    """The table sizes with a solution of their own."""
    return tuple(sorted(int(n) for n in _data().get("games", {})))


def stacks(players: int = PLAYERS) -> tuple[float, ...]:
    """The stacks (big blinds) the game is solved for at that table size, shortest first."""
    return tuple(float(s) for s in _data().get("games", {}).get(str(players), {}).get("stacks", ()))


def top() -> float:
    """The deepest stack with an exact answer; 0 when the data is not there."""
    s = stacks()
    return s[-1] if s else 0.0


def close(stack: float, all_in: int = 1) -> float:
    """How near to zero a call is called close, in big blinds: about one and a half times the noise of
    the number, and never less than 0.05bb (which is more than that with 8bb or less).

    The noise grows with the stack (an all-in of 20bb swings more than one of 5bb).  A number near zero
    is the second pass's, whoever is all-in before, and what it is good to is measured: about 0.003bb for
    each big blind of the stack with one player all-in before, about 0.004bb with two.  (The data file
    keeps the measure for every stack, and a test holds this band to it.)"""
    if all_in >= 2:
        return max(CLOSE_TWO, 0.0065 * stack)
    return max(CLOSE_BB, 0.005 * stack)


def _node(stack: float, player: int, mask: int, players: int) -> list[int] | None:
    return _data()["games"][str(players)]["nodes"].get(f"{stack:g}", {}).get(f"{player}:{mask}")


def node(stack: float, player: int, mask: int, players: int = PLAYERS) -> list[float] | None:
    """What going in earns over folding, in big blinds, for each of the 169 hands.

    ``player`` and the bits of ``mask`` are places in acting order at a table of ``players`` (0 the
    first to act, the last two the blinds); ``mask`` has the bit of every player who is all-in already.
    None when the game has no such decision or was not solved there."""
    grid = stacks(players)
    if not grid or stack < grid[0] - 1e-9 or stack > grid[-1] + 1e-9 or bin(mask).count("1") > MOST_ALL_IN:
        return None
    lo = max(g for g in grid if g <= stack + 1e-9)
    hi = min(g for g in grid if g >= stack - 1e-9)
    a = _node(lo, player, mask, players)
    if a is None:
        return None
    if hi == lo:
        return [x / 100.0 for x in a]
    b = _node(hi, player, mask, players)
    if b is None:
        return None
    t = (stack - lo) / (hi - lo)
    return [(x + (y - x) * t) / 100.0 for x, y in zip(a, b)]


def seat(n: int, index: int) -> int:
    """A player of a table of ``n`` (0 the first to act) as a place at the table of nine."""
    return index + PLAYERS - n


def covered(setup, actor: int, all_in: list[int] | tuple = ()) -> float | None:
    """The stack, in big blinds, at which this spot is one of the solved game; None when it is not one.

    ``actor`` decides now, ``all_in`` are the players all-in before him (everybody else before him has
    folded).  It is the solved game when the blinds are 0.5 and 1 with a big blind ante of 1 and no other
    ante, three to nine players, at most two players all-in and for the same stack, and the actor and
    everybody behind him hold at least that stack (first in: at least the actor's own)."""
    n = setup.n
    if not available() or not 3 <= n <= PLAYERS or len(all_in) > MOST_ALL_IN:
        return None
    bb = setup.bb
    if bb <= 0 or abs(setup.sb - 0.5 * bb) > 1e-9:
        return None
    if any(abs(a) > 1e-9 for a in setup.antes[:-1]) or abs(setup.antes[-1] - bb) > 1e-9:
        return None
    if any(j >= actor for j in all_in) or len(set(all_in)) != len(all_in):
        return None
    start = setup.start
    size = start[all_in[0]] if all_in else start[actor]
    if any(abs(start[j] - size) > 1e-9 for j in all_in):
        return None
    if any(start[j] < size - 1e-9 for j in range(actor, n)):
        return None
    stack = size / bb
    grid = stacks(table_for(n))
    return stack if grid and grid[0] - 1e-9 <= stack <= grid[-1] + 1e-9 else None


def table_for(n: int) -> int:
    """The solved table a table of ``n`` players is read from: its own, or the nine."""
    return n if n in games() else PLAYERS


def answer(setup, actor: int, all_in: list[int] | tuple = ()) -> list[float] | None:
    """``node`` for a spot of the engine: 169 numbers in big blinds, or None when the spot is not covered."""
    stack = covered(setup, actor, all_in)
    if stack is None:
        return None
    base = table_for(setup.n)
    mask = 0
    for j in all_in:
        mask |= 1 << (j + base - setup.n)
    return node(stack, actor + base - setup.n, mask, base)


def width(evs: list[float]) -> float:
    """Percent of all hands that go in."""
    return 100.0 * sum(c for c, e in zip(COMBO_COUNT, evs) if e > 0) / 1326.0
