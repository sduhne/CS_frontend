"""All-ins of 2 to 20 big blinds, solved exactly.

With ten big blinds or less a hand is an all-in or a fold for everybody, and the whole game before the
flop is a small tree: who has moved all-in before you.  ``tools/aof_solver.c`` solves that tree with
real cards and every showdown, side pots included; ``tools/build_short.py`` runs it for equal stacks and
a small blind of half a big blind, and ``data/short.json`` keeps the answers for stacks of 2 big blinds
up to ``top()``: for each player and each set of at most two players all-in before him, what going in
earns over folding, hand by hand.

Two games are solved, one for each kind of ante (``KINDS``), and kept side by side:

* ``"bb"``: the big blind pays an ante of one big blind for the table, before his blind.  Tables of 9, 6,
  5, 4 and 3 players; 7 and 8 players are read from the last seats of the nine (the seats that are not
  there count as players who folded, which costs about a thousandth of a big blind a hand at eight).
* ``"player"``: every player pays an ante of an eighth of a big blind (``PLAYER_ANTE``), as on GGPoker.
  Tables of 9, 8, 7, 6, 5, 4 and 3 players, every one solved as such: here the money in the pot goes with
  the number of players (1.125bb at nine, 1bb at eight, 0.75bb at six, 0.375bb at three), so a table of
  eight cannot be read from the nine.  Against the first game the big blind keeps one big blind more
  behind (with 2bb he is not all-in from posting) and a short-handed table plays for a smaller pot.

``covered`` says which of the two a spot of the engine is, from the antes of its setup.  An ante of
every player within ``ANTE_BAND`` of an eighth (0.12 and 0.133 are levels of the same structures) is
read from the solution for an eighth; ``same_ante`` says whether it is that ante to the chip.

Each is solved for every stack from 2 to 10 big blinds and for 12, 16 and 20; between two solved stacks
the answers are drawn in a straight line.  A stack is what a player holds when the hand begins, before
antes and blinds.  The numbers come from dealing cards, so they carry noise: the hands near zero, which
decide where a range ends, are sampled a second time with ten times the deals (``tools/build_short.py``
says how, and what it changed).  Above ten big blinds the tree is not the whole game any more (there are
small raises), but the all-in is still one of the plays, and what it earns first in, and what calling one
or two earns, is read here: the engine weighs a first-in all-in up to 20 big blinds.

Why it is needed.  The engine's own solver (``pushfold``) leaves two things out, and this short both
matter:

* It sets the player who moves all-in against one caller at a time: when two would call, the first is
  the hand to beat and the other's chips are dead money.  With a few big blinds the big blind calls with
  nearly everything and a second caller is the rule.  With 3bb and nine players it moved all-in first to
  act with 84% of hands where the answer is 26%, and called an all-in on the button with 76% where it is
  23%.
* It deals every opponent a hand from a full deck.  But the players who folded hold mostly the middle
  and low cards they folded, so those cards are rarer on the board and in the hands still to come, and
  the aces and kings are not: at a full table a hand like T8o is about three points worse against an
  all-in than its plain equity says, a small ace a little better.  With 6bb and nine players the big
  blind called a cutoff all-in with 65% of hands where the answer is 47%.

Against the published heads-up equilibrium, where neither matters, the engine's solver is right to a
hand in three hundred.

A spot of the engine is one of these games when it is played for chips with those blinds and one of
those antes, the players who are all-in hold the same stack, and nobody who still has to act holds less
(``covered``).  Two players are left to the engine's solver, which is exact heads-up.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from .cards import COMBO_COUNT

_PATH = os.path.join(os.path.dirname(__file__), "data", "short.json")
DATA_VERSION = 3            # 3: two kinds of ante side by side (2 was the big blind ante alone)
PLAYERS = 9                 # the biggest table solved; tables with no solution of their own are its last seats
MOST_ALL_IN = 2             # the answers are kept for at most this many players all-in before the one who decides
CLOSE_BB = 0.05             # a play worth less than this either way is close: with nobody or one player all-in before, a
                            # number near zero comes from the second pass and is good to about 0.03bb (tools/build_short.py)
CLOSE_TWO = 0.15            # ... and with two players all-in before, where the first pass stands: 0.05 to 0.2bb
KINDS = ("bb", "player")    # the kinds of ante: the big blind pays one big blind for the table; every player pays PLAYER_ANTE
PLAYER_ANTE = 0.125         # ... of a big blind, as on GGPoker (latereg.PLAYER_ANTE is the same number)
ANTE_BAND = 0.01            # an ante of every player this near to it is read from the same solution: 0.12 (30 at 125/250) and
                            # 0.133 (40 at 150/300) are levels of the structures whose other levels are an eighth


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        with open(_PATH) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return d if d.get("version") == DATA_VERSION else {}


def _games(kind: str) -> dict:
    return _data().get("antes", {}).get(kind, {}).get("games", {})


def available(kind: str | None = None) -> bool:
    """Is the solution there?  For one kind of ante, or (None) for any."""
    return bool(_games(kind)) if kind else any(_games(k) for k in KINDS)


def kinds() -> tuple[str, ...]:
    """The kinds of ante there is a solution for."""
    return tuple(k for k in KINDS if _games(k))


def games(kind: str = "bb") -> tuple[int, ...]:
    """The table sizes with a solution of their own."""
    return tuple(sorted(int(n) for n in _games(kind)))


def stacks(players: int = PLAYERS, kind: str = "bb") -> tuple[float, ...]:
    """The stacks (big blinds) the game is solved for at that table size, shortest first."""
    return tuple(float(s) for s in _games(kind).get(str(players), {}).get("stacks", ()))


def top(kind: str = "bb") -> float:
    """The deepest stack with an exact answer; 0 when the data is not there."""
    s = stacks(PLAYERS, kind)
    return s[-1] if s else 0.0


def close(stack: float, all_in: int = 1) -> float:
    """How near to zero a play is called close, in big blinds: about twice the noise of the number.

    The noise grows with the stack (an all-in of 20bb swings more than one of 5bb).  With nobody or one
    player all-in before, a number near zero is the second pass's: about 0.003bb for each big blind of the
    stack.  With two players all-in the first pass stands: about 0.01bb for each."""
    if all_in >= 2:
        return max(CLOSE_TWO, 0.015 * stack)
    return max(CLOSE_BB, 0.005 * stack)


def _node(stack: float, player: int, mask: int, players: int, kind: str) -> list[int] | None:
    return _games(kind)[str(players)]["nodes"].get(f"{stack:g}", {}).get(f"{player}:{mask}")


def node(stack: float, player: int, mask: int, players: int = PLAYERS, kind: str = "bb") -> list[float] | None:
    """What going in earns over folding, in big blinds, for each of the 169 hands.

    ``player`` and the bits of ``mask`` are places in acting order at a table of ``players`` (0 the
    first to act, the last two the blinds); ``mask`` has the bit of every player who is all-in already;
    ``kind`` is the ante of the game.  None when the game has no such decision or was not solved there."""
    grid = stacks(players, kind)
    if not grid or stack < grid[0] - 1e-9 or stack > grid[-1] + 1e-9 or bin(mask).count("1") > MOST_ALL_IN:
        return None
    lo = max(g for g in grid if g <= stack + 1e-9)
    hi = min(g for g in grid if g >= stack - 1e-9)
    a = _node(lo, player, mask, players, kind)
    if a is None:
        return None
    if hi == lo:
        return [x / 100.0 for x in a]
    b = _node(hi, player, mask, players, kind)
    if b is None:
        return None
    t = (stack - lo) / (hi - lo)
    return [(x + (y - x) * t) / 100.0 for x, y in zip(a, b)]


def seat(n: int, index: int) -> int:
    """A player of a table of ``n`` (0 the first to act) as a place at the table of nine."""
    return index + PLAYERS - n


def ante_kind(setup) -> str | None:
    """Which of the solved games the forced bets of a hand are: "bb", "player", or None for another game.

    The blinds are 0.5 and 1.  "bb": the big blind pays one big blind of ante and nobody else pays any.
    "player": every player pays the same ante, within ANTE_BAND of an eighth of a big blind, and the big
    blind no more than the others."""
    bb = setup.bb
    if bb <= 0 or abs(setup.sb - 0.5 * bb) > 1e-9:
        return None
    antes = setup.antes
    if all(abs(a) <= 1e-9 for a in antes[:-1]) and abs(antes[-1] - bb) <= 1e-9:
        return "bb"
    if all(abs(a - antes[0]) <= 1e-9 for a in antes) and abs(antes[0] / bb - PLAYER_ANTE) <= ANTE_BAND + 1e-9:
        return "player"
    return None


def same_ante(setup) -> bool:
    """Is the ante of this hand the solved game's to the chip?  (An ante of every player of 0.12 or 0.133 of a
    big blind is read from the solution for an eighth: ``ante_kind`` is "player" and this is False.)"""
    kind = ante_kind(setup)
    return kind == "bb" or (kind == "player" and abs(setup.antes[0] / setup.bb - PLAYER_ANTE) <= 1e-9)


def covered(setup, actor: int, all_in: list[int] | tuple = ()) -> float | None:
    """The stack, in big blinds, at which this spot is one of the solved games; None when it is not one.

    ``actor`` decides now, ``all_in`` are the players all-in before him (everybody else before him has
    folded).  It is a solved game when the blinds are 0.5 and 1 with one of the two antes (``ante_kind``),
    three to nine players, at most two players all-in and for the same stack, and the actor and everybody
    behind him hold at least that stack (first in: at least the actor's own)."""
    n = setup.n
    if not 3 <= n <= PLAYERS or len(all_in) > MOST_ALL_IN:
        return None
    kind = ante_kind(setup)
    if kind is None or not available(kind):
        return None
    if any(j >= actor for j in all_in) or len(set(all_in)) != len(all_in):
        return None
    start = setup.start
    size = start[all_in[0]] if all_in else start[actor]
    if any(abs(start[j] - size) > 1e-9 for j in all_in):
        return None
    if any(start[j] < size - 1e-9 for j in range(actor, n)):
        return None
    base = table_for(n, kind)
    if base is None:
        return None
    stack = size / setup.bb
    grid = stacks(base, kind)
    return stack if grid and grid[0] - 1e-9 <= stack <= grid[-1] + 1e-9 else None


def table_for(n: int, kind: str = "bb") -> int | None:
    """The solved table a table of ``n`` players is read from: its own, or with a big blind ante the nine.

    None when there is none: with an ante from every player the pot of the nine is not the pot of a
    smaller table, so a table without a solution of its own has no exact answer."""
    if n in games(kind):
        return n
    return PLAYERS if kind == "bb" else None


def answer(setup, actor: int, all_in: list[int] | tuple = ()) -> list[float] | None:
    """``node`` for a spot of the engine: 169 numbers in big blinds, or None when the spot is not covered."""
    stack = covered(setup, actor, all_in)
    if stack is None:
        return None
    kind = ante_kind(setup)
    base = table_for(setup.n, kind)
    mask = 0
    for j in all_in:
        mask |= 1 << (j + base - setup.n)
    return node(stack, actor + base - setup.n, mask, base, kind)


def width(evs: list[float]) -> float:
    """Percent of all hands that go in."""
    return 100.0 * sum(c for c, e in zip(COMBO_COUNT, evs) if e > 0) / 1326.0
