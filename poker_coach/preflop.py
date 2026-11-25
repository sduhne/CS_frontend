"""Preflop decisions for a tight-aggressive tournament player.

``advise(spot)`` looks at what happened before hero acts and routes to one of
the handlers below.  Short stacks and all-in spots are decided by the
equilibrium solver with ICM; deeper spots use the TAG charts, moved by stack
depth, ICM pressure and reads on the players involved.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field

from .cards import HANDS, format_range, parse_range, range_combos, range_pct, top_percent
from .equity import all_vs_range, allin_order, eq_vs_range, hand_equity, preflop_equity
from .icm import Prizes
from . import pushfold as _solver
from . import short, spin_exact
from .pushfold import HandSetup, _call_req, beats_all, solve_shove, _unit
from .ranges import (PLAYER_TYPES, norm_type, open_size_bb, opener_category, position_name,
                     rfi_range, scale_range, threebet_range, villain_limp_range,
                     villain_open_range, vs_open_chart, _ladder, _POSITION_ALIASES,
                     style as chart_style)



# --------------------------------------------------------------------------
# The all-in solver, with a blind that was posted all-in put right
# --------------------------------------------------------------------------
#
# ``pushfold`` lists every player behind the shover as a caller who calls or folds, and takes the players
# behind a caller to fold.  A blind who posted his last chips has no decision: he needs nothing to "call",
# so he always calls, and nobody after him ever could.  With a big blind all-in for half a blind, an all-in
# over a raise then read as "the raiser never calls" and 7-2 offsuit showed +1.45bb for 20bb.  Here such a
# player is left out of the callers: his chips are in the pot, and the pot he can win goes to the shover at
# even odds when everybody else folds.  The three functions below take the solver's place in this file and
# in the table app.

def _posted_all_in(setup: HandSetup, shover: int, bets: dict | None = None) -> list[int]:
    """Players whose whole stack went in as a blind: no decision is left to them."""
    bets = bets or {}
    return [j for j in range(setup.n) if j != shover and j not in bets
            and setup.live[j] > 0 and setup.blinds[j] >= setup.live[j] - 1e-9]


def _shove_spot(setup: HandSetup, shover: int, prizes: Prizes, *, away=None, bets=None, **more):
    """(value of folding, value when everybody folds, the callers, swing).

    ``swing`` is what the showdown against a blind who is all-in from posting moves, in the same
    units: 0 when there is no such player.  The value "when everybody folds" then counts that
    showdown at even odds.
    """
    order = more.get("caller_order")
    if order:
        # The same for a raiser who has nothing left to call against this all-in (he is all-in himself, or
        # his raise covers the shover): he is in whatever happens, so he is asked last, after the players who
        # still decide.
        inv = setup.invested(bets)
        decided = [j for j in order if min(setup.live[shover], setup.live[j]) - inv[j] <= 1e-9]
        more = dict(more, caller_order=[j for j in order if j not in decided] + decided)
    gone = _posted_all_in(setup, shover, bets)
    if not gone:
        return _solver.build_shove_spot(setup, shover, prizes, away=away, bets=bets, **more) + (0.0,)
    out = list(away or [False] * setup.n)
    for j in gone:
        out[j] = True
    v_fold, v_steal, callers = _solver.build_shove_spot(setup, shover, prizes, away=out, bets=bets, **more)
    # When everybody else folds the shover still has to show his cards to the biggest of them, for the pot
    # that player can win (every stake up to his own, and the antes).
    j = max(gone, key=lambda k: setup.live[k])
    inv = setup.invested(bets)
    cap = setup.live[j]
    main = sum(setup.antes) + sum(min(cap, setup.live[i] if i == shover else inv[i]) for i in range(setup.n))
    lost = setup.fold_out(shover, bets)
    lost[shover] -= main
    lost[j] += main
    v_lost = prizes.value(lost, shover)
    return v_fold, 0.5 * (v_steal + v_lost), callers, v_steal - v_lost


def build_shove_spot(setup: HandSetup, shover: int, prizes: Prizes, *, away=None, bets=None, **more):
    """``pushfold.build_shove_spot``, without the players who are all-in from posting a blind among the callers."""
    return _shove_spot(setup, shover, prizes, away=away, bets=bets, **more)[:3]


_VS_ANY_TWO: list = []          # every hand's equity against a random hand, worked out once


def _solve(v_fold: float, v_steal: float, callers: list, swing: float, iters: int, unit: float, together=None):
    """``solve_shove``, and then the showdown against the blind who posted all-in, hand by hand: a strong
    hand wins that small pot more often than a weak one."""
    sol = solve_shove(v_fold, v_steal, callers, iters=iters, unit=unit, together=together) if together else \
        solve_shove(v_fold, v_steal, callers, iters=iters, unit=unit)
    if swing:
        if not _VS_ANY_TWO:
            _VS_ANY_TWO.extend(all_vs_range([1.0] * 169)[0])
        sol.ev = [ev + stay * (eq - 0.5) * swing for ev, stay, eq in zip(sol.ev, sol.fold_equity, _VS_ANY_TWO)]
        sol.shove_range = [1.0 if ev > 0 else 0.0 for ev in sol.ev]
    return sol


# The shortest stacks are not solved here: the answer is read from the exact solution of that game
# (``short``), where two and three callers are the rule and every one of them holds a hand.  It is the
# game played for chips, with nobody sitting out, against players the solved game can stand for: a read
# as strong as "never folds" or "only plays aces" is left to the solver above, which follows it.
_EXACT_TYPES = ("unknown", "tag", "tight", "loose")


def _exact_game(prizes: Prizes, caller_prizes=None, types=None, away=None) -> bool:
    if not prizes.chip_ev or (caller_prizes is not None and not caller_prizes.chip_ev):
        return False
    if away and any(away):
        return False
    return all(norm_type(t) in _EXACT_TYPES for t in (types or ()))


def _exact_evs(setup: HandSetup, actor: int, all_in=(), types=None) -> tuple[list[float] | None, str, str]:
    """(what going in earns, 169 numbers in big blinds; the game; the profile) from an exact solution, or
    (None, "", "solid") when neither covers the spot.

    ``short``: a big blind ante and equal stacks (tournaments).  ``spin_exact``: no ante, two or three players,
    the stacks as they are (spins); its answers are the best reply to the opponents' kind (``profile_of``)."""
    evs = short.answer(setup, actor, all_in)
    if evs is not None:
        return evs, "short", "solid"
    profile = spin_exact.profile_of(types, actor)
    evs = spin_exact.answer(setup, actor, all_in, profile)
    if evs is not None:
        return evs, "spin", profile
    return None, "", "solid"


def _exact_open(setup: HandSetup, shover: int, prizes: Prizes, caller_prizes=None, types=None, away=None):
    """The first-in all-in of a stack the exact game covers, as the solver's own kind of answer; else None.

    The tournament game (``short``) is played by players who call correctly, and a tag of tight or loose on
    the players behind does not move this answer.  (What they change was tried from the solver, its answer
    with them less its answer without: at these stacks it said to move in with far more hands against players
    who call too much, 63% for 38% from the cutoff with 4bb, which is the solver's one-caller shortcut
    again and not a reading of loose players.)  The spin game (``spin_exact``) has those answers solved: the
    best reply to players who call too much, or too little, when every player around is tagged so."""
    if not _exact_game(prizes, caller_prizes, types, away):
        return None
    evs, game, profile = _exact_evs(setup, shover, (), types)
    if evs is None:
        return None
    v_fold, v_steal, callers = _solver.build_shove_spot(setup, shover, prizes, use_types=False)
    stay, eq_num = [1.0] * 169, [0.0] * 169
    for c in callers:
        if game == "spin":
            called = spin_exact.answer(setup, c.idx, [shover], "solid")
            c.call_range = spin_exact.plays(called, spin_exact.SHOVE_CALL[profile][1]) if called else [0.0] * 169
        else:
            called = short.answer(setup, c.idx, [shover])
            c.call_range = [1.0 if e > 0 else 0.0 for e in called] if called else [0.0] * 169
        eqs, probs = all_vs_range(c.call_range)
        for h in range(169):
            p = min(1.0, probs[h])
            eq_num[h] += stay[h] * p * eqs[h]
            stay[h] *= 1.0 - p
    eq_called = [eq_num[h] / (1.0 - stay[h]) if stay[h] < 1.0 - 1e-12 else 0.5 for h in range(169)]
    return _solver.Solution(ev=[e * setup.bb for e in evs], shove_range=[1.0 if e > 0 else 0.0 for e in evs],
                            callers=callers, fold_equity=stay, v_fold=v_fold, v_steal=v_steal, unit=setup.bb,
                            eq_called=eq_called, exact=True, game=game, profile=profile)


def solve_open_shove(setup: HandSetup, shover: int, prizes: Prizes, *, caller_prizes=None, types=None, away=None,
                     iters: int = 40, use_types: bool = True):
    """``pushfold.solve_open_shove`` on ``_shove_spot`` above; the shortest stacks from the exact solution."""
    exact = _exact_open(setup, shover, prizes, caller_prizes, types, away)
    if exact is not None:
        return exact
    v_fold, v_steal, callers, swing = _shove_spot(setup, shover, prizes, caller_prizes=caller_prizes, types=types,
                                                  away=away, use_types=use_types)
    return _solve(v_fold, v_steal, callers, swing, iters, _unit(prizes, setup, shover))


def solve_reshove(setup: HandSetup, shover: int, opener: int, raise_to: float, prizes: Prizes, *, opener_range,
                  flat_callers=None, caller_prizes=None, types=None, away=None, iters: int = 40,
                  use_types: bool = True):
    """``pushfold.solve_reshove`` on ``_shove_spot`` above: the players behind act first, then the raiser,
    then the players who called him."""
    flat_callers = flat_callers or {}
    bets = {opener: raise_to}
    for j in flat_callers:
        bets[j] = raise_to
    behind = [j for j in range(shover + 1, setup.n) if j != opener and j not in flat_callers]
    priors = {opener: opener_range}
    priors.update(flat_callers)
    v_fold, v_steal, callers, swing = _shove_spot(
        setup, shover, prizes, caller_prizes=caller_prizes, types=types, away=away, bets=bets, priors=priors,
        caller_order=behind + [opener] + list(flat_callers), fold_winner=opener,
        extra_req={j: 0.02 for j in behind},        # calling a raise and an all-in cold needs a real hand
        use_types=use_types)
    members = _taken_together(callers, opener, flat_callers)
    together = (members, _together_values(setup, shover, [c.idx for c in members], bets, prizes)) if members else None
    return _solve(v_fold, v_steal, callers, swing, iters, _unit(prizes, setup, shover), together=together)


# The solver sets the shover against one caller at a time, in the order they act: when two players would
# call, the first is the hand to beat and the other's chips are dead money.  Players behind come first, and
# against a raiser who can still fold that is right: a call behind usually ends the raiser's hand.  Two
# cases are not like that, and there the raiser and the players who called him are taken first and
# together: each calls or folds on his own, and the shover has to beat every one of them who calls.
#   - A raiser who needs a third of the pot or less calls with whatever he raised, whoever else comes
#     along.  (The big blind's call, priced as heads-up with the raise as dead money, fed on itself: over a
#     2.5bb raise with 7bb the small blind moved all-in with T4o, "40% when called" against a range it has
#     28% against.)
#   - Players who called the raise: when the raiser calls the all-in their chips are not dead money, and
#     neither is his when one of them calls.  (The button moved all-in with 62% of hands for 11bb over a raise
#     to 4bb and two calls, and the small blind with 44% for 13bb over a raise to 2bb and two calls.)
_PRICED_IN = 0.34


def _taken_together(callers: list, opener: int, flat_callers) -> list:
    """The raiser and the players who called him, when they are to be taken together (above); [] when the
    order of the callers is all there is.  A raiser with nothing left to call (0) has been placed by
    ``_shove_spot``."""
    raiser = next((c for c in callers if c.idx == opener), None)
    if raiser is None or raiser.chip_req <= 0.0:
        return []
    flats = [c for c in callers if c.idx in flat_callers]
    if not flats and raiser.chip_req > _PRICED_IN:
        return []
    return [raiser] + flats


def _together_values(setup: HandSetup, shover: int, members: list, bets, prizes: Prizes) -> dict:
    """For every part of ``members`` (a bit mask, in their order) that may call: what the shover's stack is
    worth when he beats them all, and when he does not.  As ``HandSetup.showdown`` for one caller; with more,
    each puts in what the shover's stack can match, and the pot is won or lost whole."""
    inv = setup.invested(bets)
    out = {}
    for mask in range(1, 1 << len(members)):
        in_pot = [j for i, j in enumerate(members) if mask >> i & 1]
        matched = {j: min(setup.live[shover], setup.live[j]) for j in in_pot}
        mine = max(matched.values())
        pot = sum(setup.antes) + mine + sum(matched.values()) + \
            sum(inv[i] for i in range(setup.n) if i != shover and i not in in_pot)
        after = [setup.live[i] - inv[i] for i in range(setup.n)]
        for j in in_pot:
            after[j] = setup.live[j] - matched[j]
        won, lost = list(after), list(after)
        won[shover] = setup.live[shover] - mine + pot
        lost[shover] = setup.live[shover] - mine
        lost[in_pot[0]] += pot                     # to one of them: the raiser when he is in
        out[mask] = (prizes.value(won, shover), prizes.value(lost, shover))
    return out


# The looser style of the quick guide ("win", see ranges.py) keeps the engine and changes a few numbers:
# what an all-in must earn before it is made, and where a hand may raise small or call instead of folding.
# The default style ("tag") is the left-hand value everywhere.
def _win() -> bool:
    return chart_style() == "win"


def _guide() -> bool:
    """The quick guide's two styles: the big blind's call is tested by what the hand realises."""
    return chart_style() in ("win", "tight")


def _bar(tag: float, win: float) -> float:
    return win if _win() else tag


_RAISE_FOLD_FROM = 13.0            # win: from this stack a hand of the opening row that is no all-in raises small
_CALL_OVER_ALLIN_CLEAR = 0.25      # win: a big blind call worth this many big blinds more than the all-in is not close
_CALL_RERAISE_IP = parse_range("77+, ATs+, KTs+, QTs+, JTs")      # win: the hands that may call one re-raise in position
_FLAT_SHORT_FROM = 15.0            # win: from this stack a strong hand may call a raise in position (25bb or less)
_FLAT_SHORT_EDGE = 0.10            # ... with this much equity over the price

# The quick guide's test for the big blind's call of one raise.  A hand does not win its whole share of the
# pot when it has to play the flop out of position: it turns a part of its equity into chips, more when it
# is suited, connected or high, less when it is none of them.  The call is right when that part beats the
# price by a margin.  ``bb_realised`` is that part.  Against a solver's fold rates (GTO Wizard's, as printed
# by PokerNews in 2026: a raise from the first seat with 25, 50 and 100bb, from the cutoff with 100bb, and
# from the small blind) it folds a few points more often than the solver at 2bb and at 3bb.  Acting last
# (the raise came from the small blind) a hand keeps far more: the solver folds 1% of hands to a 2bb raise
# there and about a quarter to 3.5bb.  (The default test adds points by the kind of hand instead; it calls
# 32s where it folds T9o, because every suited hand gets the same points.)
_BB_MARGIN = {"win": 0.03, "tight": 0.05}      # realised equity over the price: the looser style, the tight one
_BB_OFFSUIT_DEEP = 0.02                        # offsuit hands lose this much of their share each time the stack doubles over 25bb
_BB_IN_POSITION = 0.22                         # a raise from the small blind: the big blind acts last and keeps this much more
_BB_SHARE_MOST = 1.05                          # no hand turns more than this share of its equity into chips ...
_BB_SHARE_MOST_LAST = 1.10                     # ... or this, acting last
_BB_CLOSE = 0.03                               # a call or a fold within this many points of the line is close


def bb_realised(hand: int, eff_bb: float, in_position: bool = False) -> float:
    """The share of its equity a hand turns into chips when the big blind calls a raise with it."""
    row, col = divmod(hand, 13)                        # 0 is the ace
    hi, lo = 14 - min(row, col), 14 - max(row, col)    # ranks, 14 down to 2
    if row == col:
        share = 0.76 + 0.02 * (hi - 2)
    else:
        suited = row < col
        gap = hi - lo - 1
        # cards that make straights, less so the low ones (their straights are the bottom end)
        connected = {0: 1.0, 1: 0.75, 2: 0.45, 3: 0.2}.get(gap, 0.0) * (0.5 + 0.5 * min(1.0, (lo - 2) / 5))
        share = 0.46 + 0.20 * (hi - 2) / 12 + 0.14 * (lo - 2) / 12 + 0.16 * connected + (0.20 if suited else 0.0)
        if hi == 14 and lo <= 5:
            share += 0.05 if suited else 0.03          # an ace with a wheel card
        if not suited and eff_bb > 25:
            share -= _BB_OFFSUIT_DEEP * math.log2(eff_bb / 25)
    if in_position:                                    # the raise came from the small blind: the big blind acts last
        share += _BB_IN_POSITION
    return min(_BB_SHARE_MOST_LAST if in_position else _BB_SHARE_MOST, share)


_PREMIUM = parse_range("QQ+, AKs, AKo")
_TRAP = parse_range("KK+")
_BIG_PAIRS = parse_range("JJ+")
_SHOVE_SHAPED = parse_range("22-JJ, A2s+, A7o+, KTs+, KQo, QJs, JTs")
_JAM_NOT_RAISE = parse_range("22-77, A2s-A9s, A8o-AJo, KQo")


@dataclass
class Act:
    idx: int
    kind: str          # limp | call | raise | allin
    amount: float      # total live chips in front after the action


@dataclass
class Advice:
    action: str
    confidence: str = "standard"      # clear | standard | close
    situation: str = ""
    why: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    alt: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def render(self) -> str:
        lines = [f">>> {self.action}   [{self.confidence}]"]
        if self.situation:
            lines.append(self.situation)
        lines += [f"  why: {w}" for w in self.why]
        lines += [f"  num: {n}" for n in self.numbers]
        lines += [f"  alt: {a}" for a in self.alt]
        lines += [f"  !!   {w}" for w in self.warnings]
        return "\n".join(lines)


@dataclass
class Spot:
    setup: HandSetup
    hero: int
    hand: int
    cards: tuple | None = None
    names: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    away: list[bool] = field(default_factory=list)
    prizes: Prizes = field(default_factory=Prizes)       # hero's utility (may hold an ITM bonus)
    field_prizes: Prizes = field(default_factory=Prizes)  # what opponents play for
    acts: list[Act] = field(default_factory=list)
    stage: dict = field(default_factory=dict)
    desperate: bool = False
    notes: list[str] = field(default_factory=list)
    # Who was sitting out when the hand was dealt.  ``away`` may also hold players who have folded
    # since hero raised (the table app marks them so); hero's own opening range is rebuilt from the
    # players who were there when he raised.  Left empty it is the same as ``away``.
    sitting_out: list[bool] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = self.setup.n
        if not self.names:
            self.names = [position_name(n - 1 - i, n) for i in range(n)]
        if not self.types:
            self.types = ["unknown"] * n
        if not self.away:
            self.away = [False] * n
        if not self.sitting_out:
            self.sitting_out = list(self.away)
        self.types = [norm_type(t) for t in self.types]

    # helpers -------------------------------------------------------------
    @property
    def bb(self) -> float:
        return self.setup.bb

    def nb(self, i: int) -> int:
        return self.setup.n - 1 - i

    def pos(self, i: int) -> str:
        return position_name(self.nb(i), self.setup.n)

    def who(self, i: int) -> str:
        p = self.pos(i)
        nm = self.names[i]
        t = self.types[i]
        tag = "" if t == "unknown" else f", {t}"
        return p if nm == p else f"{p} {nm}{tag}" if nm else p

    def bbs(self, chips: float) -> float:
        return chips / self.bb

    @property
    def has_ante(self) -> bool:
        return sum(self.setup.antes) > 0

    def hand_name(self) -> str:
        return HANDS[self.hand]


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _conf(edge: float, clear: float, close: float) -> str:
    a = abs(edge)
    return "clear" if a >= clear else "close" if a < close else "standard"


def _icm_pressure(spot: Spot, against: list[int]) -> tuple[float, int | None]:
    """Largest risk premium hero carries against any of the given players."""
    if spot.prizes.chip_ev or not against:
        return 0.0, None
    live = spot.setup.live
    best, who = 0.0, None
    # the biggest stacks are the ones that can bust hero
    for j in sorted(against, key=lambda k: -live[k])[:3]:
        rp = spot.prizes.risk_premium(live, spot.hero, j)
        if rp > best:
            best, who = rp, j
    return best, who


def _stage_txt(spot: Spot) -> str:
    return spot.stage.get("label", "") if spot.stage else ""


def _situation(spot: Spot, text: str) -> str:
    hs = spot.bbs(spot.setup.start[spot.hero])
    st = _stage_txt(spot)
    return f"{spot.hand_name()} in {spot.pos(spot.hero)} with {hs:.1f}bb, {text}" + (f" | {st}" if st else "")


def _value_note(spot: Spot) -> str:
    return "chip EV" if spot.prizes.chip_ev else spot.prizes.label


# --------------------------------------------------------------------------
# First in
# --------------------------------------------------------------------------

def _chart_shift(spot: Spot, behind: list[int]) -> tuple[int, list[str]]:
    """Tighten / loosen the opening chart for ICM and for who sits behind."""
    notes = []
    shift = 0
    live = spot.setup.live
    rp, who = _icm_pressure(spot, behind)
    covers_all = all(live[spot.hero] > live[j] * 1.15 for j in behind)
    if rp >= 0.10:
        shift += 2
        notes.append(f"heavy ICM pressure ({_pct(rp)} risk premium vs {spot.pos(who)}): open two notches tighter")
    elif rp >= 0.05:
        shift += 1
        notes.append(f"ICM pressure ({_pct(rp)} risk premium vs {spot.pos(who)}): open one notch tighter")
    elif covers_all and not spot.prizes.chip_ev and behind:
        theirs = max(spot.prizes.risk_premium(live, j, spot.hero)
                     for j in sorted(behind, key=lambda k: -live[k])[:2])
        if theirs >= 0.06:
            shift -= 1
            notes.append("you cover everyone left and they are under ICM pressure: open one notch wider")
    blind_types = [spot.types[j] for j in behind if spot.nb(j) <= 1]
    if blind_types and all(t in ("nit", "tight") for t in blind_types):
        shift -= 1
        notes.append("the blinds are tight: steal one notch wider")
    if any(spot.types[j] in ("maniac", "lag") and 8 <= spot.bbs(live[j]) <= 25 for j in behind):
        shift += 1
        notes.append("an aggressive re-shove stack sits behind: open one notch tighter")
    return shift, notes


def _open_row(nb_eff: int, own_nb: int, eff: float, shift: int) -> list[float]:
    """The opening row for the active players behind, never tighter than this seat's own row."""
    # the small blind's row is tighter than the button's because it plays out of position:
    # it is for the small blind only, not for a later seat with one active player behind
    row = rfi_range(nb_eff if nb_eff != 1 or own_nb == 1 else 2, eff, shift)
    if nb_eff < own_nb:
        own = rfi_range(own_nb, eff, shift)
        if range_pct(own) > range_pct(row):
            row = own
    return row


def hero_open_range(spot: Spot) -> list[float]:
    """Hero's opening range when he raises first in, exactly as ``first_in`` builds it.

    The plan under a raise ("if BB shoves: FOLD") and the answer to that all-in when it has come
    (``vs_shove(hero_open=...)``) both price the all-in against this one range, so the two answers
    of a hand cannot disagree.  The players behind are those who were there when hero raised
    (``spot.sitting_out``, not ``spot.away``: a player who folded since was still to act then)."""
    setup, hero = spot.setup, spot.hero
    live = setup.live
    if setup.n == 2:
        return list(_ladder(-1))                # heads-up the small blind is the button: the widest row
    behind = [j for j in range(hero + 1, setup.n) if not spot.sitting_out[j] and live[j] > 0]
    if not behind:
        return rfi_range(max(1, spot.nb(hero)), live[hero] / spot.bb)
    eff = min(live[hero], max(live[j] for j in behind)) / spot.bb
    return _open_row(len(behind), spot.nb(hero), eff, _chart_shift(spot, behind)[0])


def reshove_plan(spot: Spot, open_to: float, hero_range: list[float]) -> list[dict]:
    """What to do if a player behind moves all-in over hero's open, as numbers.

    One entry for the big blind and one for the biggest stack of 30bb or less behind hero:
    ``idx``, ``pos``, ``stack_bb``, ``need``, ``eq``, ``edge`` (unrounded: the answer to the
    all-in itself is made from the same three), ``pct`` (his range) and ``call``."""
    out = []
    setup, hero = spot.setup, spot.hero
    behind = [j for j in range(hero + 1, setup.n) if not spot.away[j] and setup.live[j] > 0]
    if not behind:
        return out
    cands = []
    bbi = setup.n - 1
    if bbi in behind:
        cands.append(bbi)
    short = [j for j in behind if spot.bbs(setup.live[j]) <= 30]
    if short:
        j = max(short, key=lambda k: setup.live[k])
        if j not in cands:
            cands.append(j)
    for j in cands[:2]:
        res = _call_vs_reshove(spot, j, open_to, hero_range)
        out.append({"idx": j, "pos": spot.pos(j), "stack_bb": spot.bbs(setup.live[j]), "need": res["need"],
                    "eq": res["eq"], "edge": res["edge"], "pct": res["pct"], "call": res["edge"] >= 0})
    return out


def _plan_line(entry: dict) -> str:
    return (f"if {entry['pos']} ({entry['stack_bb']:.0f}bb) shoves: {'CALL' if entry['call'] else 'FOLD'} "
            f"(need {_pct(entry['need'])}, have {_pct(entry['eq'])} vs ~{entry['pct']:.0f}% range)")


def _reshove_plan(spot: Spot, open_to: float, hero_range: list[float]) -> list[str]:
    """What to do if a player behind moves all-in over hero's open, as sentences."""
    return [_plan_line(entry) for entry in reshove_plan(spot, open_to, hero_range)]


def first_in(spot: Spot) -> Advice:
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    n = setup.n
    live = setup.live
    behind_all = list(range(hero + 1, n))
    behind = [j for j in behind_all if not spot.away[j] and live[j] > 0]
    sit = _situation(spot, "folded to you")
    if not behind_all:
        return Advice("CHECK / take the walk", "clear", sit, ["everyone folded: the pot is yours"])
    if not behind:
        return Advice(f"RAISE to {open_size_bb(50, 2):.1f}bb", "clear", sit,
                      ["every player behind you is sitting out: raise any two cards and take the blinds"])
    eff = min(live[hero], max(live[j] for j in behind)) / spot.bb
    hero_bb = live[hero] / spot.bb
    nb_eff = len(behind)
    is_sb = spot.nb(hero) == 1
    heads_up = n == 2
    shift, notes = _chart_shift(spot, behind)
    prizes = Prizes() if spot.desperate else spot.prizes
    adv = Advice("FOLD", "standard", sit)
    if spot.desperate:
        adv.warnings.append("desperation mode: you cannot fold into the money, so this is judged on chip EV")

    sol = None
    shove_cap = 25.0 if (is_sb or heads_up) else 20.0
    if eff <= shove_cap:
        sol = solve_open_shove(setup, hero, prizes, caller_prizes=spot.field_prizes,
                               types=spot.types, away=spot.away)
        ev = sol.ev_bb(hand)
        pct = range_pct(sol.shove_range)
        fe = sol.fold_equity[hand]
        adv.numbers.append(
            f"shove EV {ev:+.2f}bb vs folding ({_value_note(spot) if not spot.desperate else 'chip EV'}); "
            f"equilibrium shoves {pct:.0f}% of hands here")
        if sol.exact and sol.game == "spin":
            adv.numbers.append(f"everyone folds {_pct(fe)}; the all-in is solved exactly with these stacks (no ante, "
                               "every player who can still call)"
                               + {"loose": ", as the best reply to players who call too much",
                                  "tight": ", as the best reply to players who call too little"}.get(sol.profile, ""))
        elif sol.exact:
            adv.numbers.append(f"everyone folds {_pct(fe)}; the all-in is solved exactly at this stack, with two and "
                               "three callers and the cards that were folded counted")
        else:
            adv.numbers.append(f"everyone folds {_pct(fe)}; when called you have {_pct(sol.eq_called[hand])}")
        tight_callers = [c for c in sol.callers if range_pct(c.call_range) > 0]
        if tight_callers:
            parts = [f"{spot.pos(c.idx)} {range_pct(c.call_range):.0f}%" for c in tight_callers[-3:]]
            adv.numbers.append("expected calling ranges: " + ", ".join(parts))
        if not prizes.chip_ev:
            chip = solve_open_shove(setup, hero, Prizes(), types=spot.types, away=spot.away, iters=30)
            adv.numbers.append(f"for reference, pure chip EV: {chip.ev_bb(hand):+.2f}bb "
                               f"(chip-EV range {range_pct(chip.shove_range):.0f}%)")
        adv.data.update(shove_ev_bb=ev, shove_pct=pct, fold_equity=fe)
        if sol.exact:
            if eff <= 10.0:             # push or fold: the whole answer is the exact game's (deeper, only the all-in's number is)
                adv.data.update(exact=True)
        elif _several_will_call(setup, hero, live[hero]):
            adv.warnings.append(_SEVERAL_CALL)

    pf_zone = 10.0
    mix_zone = 20.0 if (is_sb or heads_up) else 16.0
    if sol is not None and eff <= pf_zone:
        ev = sol.ev_bb(hand)
        # under one big blind "0bb effective is push-or-fold territory" says nothing true: say who is that short
        if eff >= 1.0:
            depth = f"{eff:.0f}bb effective is push-or-fold territory and"
        elif live[hero] < spot.bb:
            depth = "with less than one big blind you are all-in or nearly, and"
        else:
            depth = "the players behind you hold less than one big blind, so they are all-in or nearly, and"
        if ev > 0.0:
            adv.action = "ALL-IN"
            adv.why.append(f"{depth} this shove makes money")
        else:
            adv.why.append(f"{depth} this hand loses as a shove")
        adv.confidence = _conf(ev, 0.35, 0.08)
        return _finish_first_in(spot, adv, behind)

    if sol is not None and eff <= mix_zone:
        ev = sol.ev_bb(hand)
        if _PREMIUM[hand] and eff >= 12:
            size = open_size_bb(eff, spot.nb(hero), spot.has_ante)
            adv.action = f"RAISE to {size:.1f}bb and call any all-in"
            adv.confidence = "clear"
            adv.why.append("a premium hand: the small raise invites a re-shove from worse; never fold it")
            adv.alt.append("ALL-IN is also fine if the players behind call light")
        elif ev > 0.05:
            adv.action = "ALL-IN"
            adv.confidence = _conf(ev, 0.35, 0.12)
            adv.why.append("too strong to fold and too awkward to raise-fold at this depth: take the "
                           "blinds and antes now")
        elif _win() and eff >= _RAISE_FOLD_FROM and \
                (list(_ladder(-1)) if heads_up else _open_row(nb_eff, spot.nb(hero), eff, shift))[hand] >= 0.5:
            # the looser style: a hand of the opening row that is no all-in is a small raise, not a fold
            size = 2.0
            row = list(_ladder(-1)) if heads_up else _open_row(nb_eff, spot.nb(hero), eff, shift)
            adv.action = f"RAISE to {size:.1f}bb"
            adv.confidence = "close"
            adv.why.append("in the opening range and not a profitable all-in at this depth: raise small, and "
                           "fold to an all-in unless the line below says call")
            plan = reshove_plan(spot, size * spot.bb, row)
            adv.numbers += [_plan_line(entry) for entry in plan]
            adv.data.update(plan=plan)
        else:
            adv.confidence = _conf(ev, 0.35, 0.10)
            adv.why.append("not a profitable shove here, and raise-folding 2bb would burn too much of this stack")
        return _finish_first_in(spot, adv, behind)

    # raise / fold with real stacks
    own_nb = spot.nb(hero)

    def open_row(sh: int) -> list[float]:
        return _open_row(nb_eff, own_nb, eff, sh)

    behind_txt = f"{nb_eff} player{'' if nb_eff == 1 else 's'} behind"
    rfi = open_row(shift) if not heads_up else list(_ladder(-1))
    wider = open_row(shift - 1) if not heads_up else rfi
    size = open_size_bb(eff, spot.nb(hero), spot.has_ante)
    if heads_up:
        size = 2.0 if eff < 25 else 2.2   # heads-up the small blind is the button: raise small
    adv.numbers.append(f"opening range here: {range_pct(rfi):.0f}% of hands [{format_range(rfi)}]")
    if sol is not None and rfi[hand] >= 0.5 and _JAM_NOT_RAISE[hand] and sol.ev_bb(hand) > 0.25 \
            and eff <= 20:
        adv.action = "ALL-IN"
        adv.why.append("this hand cannot call a re-shove and plays badly after the flop at this depth, "
                       "and the shove is profitable: move in rather than raise-fold")
        adv.alt.append(f"raising to {size:.1f}bb and folding to a shove is the lower-variance option")
    elif rfi[hand] >= 0.5:
        adv.action = f"RAISE to {size:.1f}bb"
        adv.confidence = "clear" if open_row(shift + 2)[hand] >= 0.5 else "standard"
        adv.why.append(f"inside the {'TAG ' if not _win() else ''}opening range for {spot.pos(hero)} with {behind_txt}")
        if eff <= 40:
            plan = reshove_plan(spot, size * spot.bb, rfi)
            adv.numbers += [_plan_line(entry) for entry in plan]
            adv.data.update(plan=plan)          # the same lines as numbers, unrounded
    elif sol is not None and sol.ev_bb(hand) > 0.25 and _SHOVE_SHAPED[hand] and eff <= 20:
        adv.action = "ALL-IN"
        adv.confidence = "close"
        adv.why.append("outside the raise-fold range, but the shove itself is profitable at this depth")
    else:
        if wider[hand] >= 0.5:
            adv.confidence = "close"
            adv.alt.append("a raise is fine if the players behind are tight or sitting out")
        adv.why.append(f"outside the {'TAG ' if not _win() else ''}opening range for {spot.pos(hero)} with {behind_txt}")
        if sol is not None and sol.ev_bb(hand) >= 0.005:
            # The shove's number is printed above this fold (the small blind's up to 25bb), and it is positive.
            # The fold is the chart's rule, not a slip: say so, or the two lines read as a contradiction.
            adv.why.append(f"a shove would earn {sol.ev_bb(hand):+.2f}bb on paper, but it puts {eff:.0f}bb at risk "
                           "to win the blinds: at this depth the plan is raise or fold, and this hand is not a raise")
            adv.data.update(fold_by_chart=True)
    reshovers = [j for j in behind if 8 <= spot.bbs(live[j]) <= 22]
    if adv.action.startswith("RAISE") and len(reshovers) >= 2 and eff > 25:
        adv.warnings.append(f"{len(reshovers)} re-shove stacks (8-22bb) behind you: decide now which shoves you call")
    del hero_bb
    adv.why += notes
    return adv


def _finish_first_in(spot: Spot, adv: Advice, behind: list[int]) -> Advice:
    """Solver-decided spots: just report how much ICM is weighing on the decision."""
    if not spot.desperate:
        rp, who = _icm_pressure(spot, behind)
        if rp >= 0.04 and who is not None:
            adv.why.append(f"ICM is priced in: {_pct(rp)} risk premium against {spot.pos(who)}")
    return adv


# --------------------------------------------------------------------------
# Limpers in front
# --------------------------------------------------------------------------

_LIMP_COMMITS = 6.0     # big blinds: with this stack or less a player who only called has a sixth of it in and does not fold
_FREE_FLOP = 0.2        # the share of the pot a free flop is worth to the big blind with a hand it would not move in with
_LIMP_CREDIT = 0.75     # how much of the gain against a caller's weaker hands is counted (the players behind take some back)


def _limp_credit(spot: Spot, limpers: list[int]) -> float:
    """What a hand gains, in big blinds, because the players who only called hold a caller's hands and not
    the hands of an all-in.

    The exact game has no call: its answer is for players who are all-in, with the ranges of an all-in.
    A player who only called holds the weak-but-playable hands a raiser skips and few of the best
    (``villain_limp_range``).  The hand's chance to win the pot is worked out against both sets of ranges
    (``beats_all`` of its equities), and the difference, times the pot hero and the callers play for, is
    the credit; _LIMP_CREDIT of it, because a player behind who comes along meets the same weaker hands."""
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    as_all_in, as_callers, seen = [], [], []
    for j in limpers:
        evs = _exact_evs(setup, j, seen)[0]
        if evs is None:
            return 0.0
        as_all_in.append(eq_vs_range(hand, [1.0 if e > 0 else 0.0 for e in evs])[0])
        as_callers.append(eq_vs_range(hand, villain_limp_range(spot.nb(j), spot.types[j]))[0])
        seen = seen + [j]
    size = setup.start[limpers[0]]
    inv = setup.invested()
    pot = sum(setup.antes) + sum(inv[i] for i in range(setup.n) if i != hero and i not in limpers) \
        + sum(min(size, setup.live[i]) for i in [hero] + list(limpers))
    return _LIMP_CREDIT * (beats_all(as_callers) - beats_all(as_all_in)) * pot / spot.bb


def vs_limp(spot: Spot, limpers: list[int]) -> Advice:
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    n = setup.n
    live = setup.live
    behind = [j for j in range(hero + 1, n) if not spot.away[j] and live[j] > 0]
    others = behind + limpers
    eff = min(live[hero], max(live[j] for j in others)) / spot.bb
    names = ", ".join(spot.pos(j) for j in limpers)
    sit = _situation(spot, f"{len(limpers)} limper{'s' if len(limpers) > 1 else ''} ({names})")
    adv = Advice("FOLD", "standard", sit)
    is_bb, is_sb = spot.nb(hero) == 0, spot.nb(hero) == 1
    free = "CHECK" if is_bb else "FOLD"
    shift, notes = _chart_shift(spot, behind)
    in_position = not (is_bb or is_sb)

    # A player who only calls with six big blinds or less has put a large part of his stack in and does not fold
    # to an all-in: the spot is his all-in, and the exact game has the answer (``short``).  The solver below
    # took him to fold most of the time and one caller to be the most there is: with 4bb it moved all-in
    # behind a caller with 84% of hands.  With three callers the first two are the all-ins the answer is read
    # for.  The big blind's other choice is not a fold but a free flop, which is worth a part of the pot as
    # it stands (_FREE_FLOP of it, for a hand that would rather not move in): he moves all-in when that earns
    # more than the flop is worth, and checks the rest.
    exact, game, profile = _exact_call_of(spot, limpers[:short.MOST_ALL_IN]) \
        if spot.bbs(setup.start[limpers[0]]) <= _LIMP_COMMITS else (None, "", "solid")
    if exact is not None:
        exact += _limp_credit(spot, limpers[:short.MOST_ALL_IN])
        flop = _FREE_FLOP * (sum(setup.antes) + sum(setup.invested({j: spot.bb for j in limpers}))) / spot.bb if is_bb else 0.0
        adv.action = "ALL-IN" if exact > flop else free
        adv.confidence = _exact_conf(exact - flop, spot.bbs(setup.start[limpers[0]]), min(2, len(limpers)), game, profile)
        adv.numbers.append(f"a player who only calls with a stack this short does not fold to an all-in: answered as "
                           f"his all-in from the exact solution, with the hands of a caller in place of the hands of an "
                           f"all-in. Moving in earns {exact:+.2f}bb against giving the pot up"
                           + (f"; the free flop is worth about {flop:.1f}bb of that" if is_bb else ""))
        adv.why.append("good enough against a caller who is not folding" + ("" if is_bb else ", and the players behind you")
                       if exact > flop else
                       "the free flop is worth more than moving in against a caller who is not folding" if is_bb else
                       "not good enough against a caller who is not folding, and the players behind you")
        if len(limpers) > short.MOST_ALL_IN:
            adv.why.append("with three callers in, the hands near the edge are folds")
        adv.data.update(exact=True, exact_ev=exact)
        adv.why += notes
        return adv
    if eff <= 16:
        bets = {j: spot.bb for j in limpers}
        priors = {j: villain_limp_range(spot.nb(j), spot.types[j]) for j in limpers}
        prizes = Prizes() if spot.desperate else spot.prizes
        v_fold, v_steal, callers = build_shove_spot(
            setup, hero, prizes, caller_prizes=spot.field_prizes, types=spot.types, away=spot.away,
            bets=bets, priors=priors, caller_order=behind + limpers, fold_winner=limpers[0])
        sol = solve_shove(v_fold, v_steal, callers, unit=_unit(prizes, setup, hero))
        ev = sol.ev_bb(hand)
        adv.numbers.append(f"shove EV {ev:+.2f}bb vs folding; everyone folds {_pct(sol.fold_equity[hand])}; "
                           f"when called you have {_pct(sol.eq_called[hand])}")
        if ev > 0.15:
            adv.action = "ALL-IN"
            adv.confidence = _conf(ev - 0.15, 0.4, 0.1)
            adv.why.append("limpers leave dead money and rarely call a shove: take it")
        else:
            adv.action = free
            adv.why.append("not strong enough to shove over the limpers at this stack")
            if is_sb and (hand in _pairs() or _suited(hand)) and eff >= 10:
                adv.alt.append("completing the small blind with a pair or suited hand is fine")
        adv.why += notes
        return adv

    iso = rfi_range(max(1, len(behind)) if in_position else 3, eff, shift + len(limpers))
    strong = parse_range("99+, AJs+, AQo+, KQs")
    iso = [max(a, b) for a, b in zip(iso, strong)]
    size = (3.0 if in_position else 4.0) + len(limpers)
    overlimp = parse_range("22-88, A2s-A9s, KTs-K9s, QTs-Q9s, JTs-J9s, T9s, 98s, 87s, 76s, 65s, 54s")
    adv.numbers.append(f"isolation range: {range_pct(iso):.0f}% [{format_range(iso)}]")
    if iso[hand] >= 0.5:
        adv.action = f"RAISE to {size:.0f}bb"
        adv.why.append("isolate the limper with a hand that dominates their range; play the pot in position"
                       if in_position else "raise for value: limpers call with worse")
        if size >= 0.33 * eff:
            adv.action = "ALL-IN"
            adv.why.append("a normal raise would commit a third of your stack, so shove instead")
    elif overlimp[hand] >= 0.5 and eff >= 25 and (spot.nb(hero) <= 3):
        adv.action = "CHECK" if is_bb else "CALL (limp behind)"
        adv.why.append("a speculative hand with implied odds: see a cheap flop, continue only with a big hit")
    elif _sb_completes(spot, limpers, eff, adv):
        adv.action = "CALL (limp behind)"
        adv.why.append("three-handed the small blind completes behind a limp: half a big blind for a pot of three, "
                       "and this hand keeps enough of it after the flop")
    else:
        adv.action = free
        adv.why.append("not strong enough to raise, not suited to limping along")
    adv.why += notes
    return adv


_SB_COMPLETE_MARGIN = 0.04      # over the price: the big blind raises two limpers about a fifth of the time, and
                                # the small blind gives its half big blind up then


def _sb_completes(spot: Spot, limpers: list[int], eff: float, adv: Advice | None = None) -> bool:
    """Three-handed, the small blind behind the button's limp: complete when the hand's equity against the
    limper and the big blind, times the share of it a hand keeps out of position (``bb_realised``), beats the
    price by ``_SB_COMPLETE_MARGIN``.  (Spin solvers complete most of the hands they do not raise there; the
    full-table rule, limping behind only with small pairs and suited cards from 25bb, folded three hands in
    four.)"""
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    if setup.n != 3 or spot.nb(hero) != 1 or len(limpers) != 1 or spot.nb(limpers[0]) != 2:
        return False
    inv = setup.invested({limpers[0]: spot.bb})
    to_call = spot.bb - inv[hero]
    price = to_call / (sum(setup.antes) + sum(inv) + to_call)
    limp = villain_limp_range(spot.nb(limpers[0]), spot.types[limpers[0]])
    eq = beats_all([eq_vs_range(hand, limp)[0], eq_vs_range(hand, [1.0] * 169)[0]])
    share = bb_realised(hand, eff, False)
    if adv is not None:
        adv.numbers.append(f"completing: {_pct(eq)} of the pot against the limper and the big blind, of which this "
                           f"hand keeps {_pct(share)}; the price {_pct(price)} plus {100 * _SB_COMPLETE_MARGIN:.0f} pts")
    return eq * share >= price + _SB_COMPLETE_MARGIN


def _pairs() -> set[int]:
    return {i * 14 for i in range(13)}


def _suited(hand: int) -> bool:
    row, col = divmod(hand, 13)
    return row < col


# --------------------------------------------------------------------------
# Facing an all-in
# --------------------------------------------------------------------------

def _opened(spot: Spot, raiser: int) -> list[float]:
    """The range a player raised first in with: his seat's, at the stack he has (heads-up, the range a small
    blind opens heads-up, as ``first_in`` does)."""
    return villain_open_range(spot.nb(raiser), spot.types[raiser], spot.bbs(spot.setup.live[raiser]),
                              heads_up=spot.setup.n == 2)


def _shover_solution(spot: Spot, shover: int, opener: int | None, raise_to: float,
                     opener_range: list[float] | None):
    """Equilibrium for the player who moved all-in, to estimate their range.

    Solved on chips: that is the push/fold chart most opponents approximate.
    Near the bubble good big stacks shove wider and scared stacks tighter, which
    the per-player type multiplier and the break-even line are there to cover.
    """
    chips = Prizes()
    if opener is None:
        return solve_open_shove(spot.setup, shover, chips, types=spot.types,
                                away=spot.away, use_types=False)
    return solve_reshove(spot.setup, shover, opener, raise_to, chips,
                         opener_range=opener_range, types=spot.types, away=spot.away,
                         use_types=False)


_SEVERAL_CALL = ("a stack this short is called by two players as often as by one, and the solver counts one caller at "
                 "a time: it reads weak hands too well here. The exact tables cover this depth with a big blind ante, "
                 "chips and nobody shorter behind (tournaments), or with no ante and two or three players up to 30bb "
                 "(spins)")


def _several_will_call(setup: HandSetup, actor: int, size: float) -> bool:
    """Is an all-in of ``size`` chips one that the big blind is priced in against, with another player
    between him and the actor?  There the one-caller-at-a-time solver is too kind to weak hands."""
    n = setup.n
    if n < 3 or actor >= n - 2:
        return False
    inv = setup.invested()
    matched = min(size, setup.live[n - 1])
    pot = sum(setup.antes) + 2.0 * matched + sum(inv[i] for i in range(n) if i not in (actor, n - 1))
    return pot > 0 and (matched - inv[n - 1]) / pot <= _PRICED_IN


def _exact_call_of(spot: Spot, in_for_stack: list[int]) -> tuple[float | None, str, str]:
    """(what calling earns over folding in big blinds, the game, the profile) where an exact game has the answer
    (``_exact_evs``): one or two players in for their stacks before hero, nothing of hero's own in the pot,
    chips.  The players still to act behind hero are part of that answer; (None, "", "solid") anywhere else."""
    prizes = Prizes() if spot.desperate else spot.prizes
    if not _exact_game(prizes, spot.field_prizes, spot.types, spot.away):
        return None, "", "solid"
    evs, game, profile = _exact_evs(spot.setup, spot.hero, sorted(in_for_stack), spot.types)
    if evs is None:
        return None, "", "solid"
    # the numbers are kept to a hundredth of a big blind: a hand worth exactly nothing is a fold, as it is first in
    return (evs[spot.hand] if evs[spot.hand] != 0.0 else -1e-9), game, profile


def _exact_call(spot: Spot, in_for_stack: list[int]) -> float | None:
    """``_exact_call_of`` without the game."""
    return _exact_call_of(spot, in_for_stack)[0]


_EXACT_OWN = 10.0       # big blinds: up to here every hand is an all-in or a fold, and an all-in is the exact game's own range
_EXACT_USUAL = 20.0     # from here a player with no read is taken a tenth tighter than a solver, as the deeper tables take him


def _exact_conf(ev: float, size_bb: float, all_in: int, game: str = "short", profile: str = "solid") -> str:
    """How sure an answer read from the exact game is: close within about twice the noise of its number
    (``short.close``, ``spin_exact.close``), clear from a quarter of a big blind and at least twice that band."""
    near = spin_exact.close(size_bb, all_in, profile) if game == "spin" else short.close(size_bb, all_in)
    return _conf(ev, max(0.25, 2.0 * near), near)


def _exact_width(ptype: str, size_bb: float = 0.0) -> float:
    """How wide a player moves all-in for ``size_bb``, as a multiple of the exact game's range.

    With ten big blinds or less the exact game is the game, and a player with no read holds its range.
    Deeper he has other plays than the all-in, and the engine takes the all-in of a player with no read a
    tenth tighter than a solver's (PLAYER_TYPES, shove_mult): the width goes down to that in a straight
    line from 10bb to 20bb, so the tables on both sides of 20bb make the same assumption.  A tight or a
    loose player: in the proportion of the other tables, at every depth.  A player tagged tag is the
    solver's own."""
    kind = norm_type(ptype)
    if kind == "tag":
        return 1.0
    usual = PLAYER_TYPES["unknown"]["shove_mult"]
    t = min(1.0, max(0.0, (size_bb - _EXACT_OWN) / (_EXACT_USUAL - _EXACT_OWN)))
    return (1.0 + (usual - 1.0) * t) * PLAYER_TYPES[kind]["shove_mult"] / usual


def _scaled_range(sol, ptype: str, size_bb: float = 0.0) -> tuple[list[float], float]:
    """The range of a player who moved all-in for ``size_bb``: the solver's, as wide as his type makes it."""
    base = range_pct(sol.shove_range)
    if sol.exact and sol.game == "spin":
        # the spin game's opponents: a tight player moves in with two thirds of the solved hands, every other
        # one with the solved hands (a loose player's mistake is calling too much, not moving in too much)
        if norm_type(ptype) != "tight":
            return list(sol.shove_range), base
        rng = spin_exact.plays(sol.ev, spin_exact.SHOVE_CALL["tight"][0])
        return rng, range_pct(rng)
    if sol.exact:
        width = _exact_width(ptype, size_bb)
        if width == 1.0:            # the exact game's own range: the call is priced against that, as it is
            return list(sol.shove_range), base
        pct = min(100.0, max(1.5, base * width))
        return scale_range(sol.ev, pct), pct
    pct = min(100.0, max(1.5, base * PLAYER_TYPES[norm_type(ptype)]["shove_mult"]))
    return scale_range(sol.ev, pct), pct


def _call_numbers(spot: Spot, shover: int, bets: dict[int, float]) -> tuple[float, float]:
    """Equity hero needs to call: (with hero's prize model, on chips alone)."""
    setup, hero = spot.setup, spot.hero
    win = setup.showdown(hero, shover, hero, bets)
    lose = setup.showdown(hero, shover, shover, bets)
    fold = setup.fold_out(shover, bets)
    prizes = Prizes() if spot.desperate else spot.prizes
    need = _call_req(prizes.value(fold, hero), prizes.value(win, hero), prizes.value(lose, hero))
    chip = _call_req(fold[hero], win[hero], lose[hero])
    return need, chip


# A player who moves all-in over a re-raise holds a narrow range, tightest first.  A player with
# no read (or tagged solid) uses the third line; tight players the lines before it, loose and
# aggressive ones the lines after it, and with under 25bb everybody is one line wider.
_ALLIN_OVER_RERAISE = ("QQ+, AKs", "JJ+, AKs, AKo", "TT+, AQs+, AKo", "99+, AJs+, AQo+, KQs",
                       "77+, ATs+, AJo+, KQs", "55+, A8s+, ATo+, KJs+, KQo")
_ALLIN_OVER_RERAISE_LINE = {"nit": 0, "tight": 1, "unknown": 2, "tag": 2, "station": 2, "loose": 3, "lag": 3,
                            "maniac": 4}
# 26 to 45bb, a hand that may not re-raise small (it would fold to an all-in): it moves all-in
# instead when that clearly earns.  The bar is this many bb; when the hand can call instead
# (in position, or in the big blind) the bar is also at least this share of the stack at risk.
_RESHOVE_CLEARLY = 1.0
_RESHOVE_CLEARLY_SHARE = 0.04
# ... and when it does not, the hand is played as a call where its seat calls at all.  The small
# blind has no calls against a late raise; these hands are too good to fold there all the same.
_SMALL_BLIND_CALLS = parse_range("TT+, AQs+, AKo")


def _allin_over_reraise(spot: Spot, shover: int, first_raiser: int | None) -> tuple[list[float], float]:
    """Range of a player who moves all-in over hero's re-raise: (weights, percent of hands).

    When he is the player hero re-raised (``first_raiser``) it is his opening range narrowed
    to the hands that play for stacks; a re-shove solved over hero's opening range would be
    several times too wide."""
    eff = min(spot.setup.live[spot.hero], spot.setup.live[shover]) / spot.bb
    line = _ALLIN_OVER_RERAISE_LINE[spot.types[shover]] + (1 if eff < 25 else 0)
    rng = parse_range(_ALLIN_OVER_RERAISE[min(line, len(_ALLIN_OVER_RERAISE) - 1)])
    if first_raiser is not None and first_raiser == shover:
        opened = _opened(spot, shover)
        narrowed = [min(a, b) for a, b in zip(rng, opened)]
        if range_combos(narrowed) > 0:
            rng = narrowed
    return rng, range_pct(rng)


# Hero raised first, a player re-raised and another raised again over both (usually all-in).  That
# last player holds the narrowest range there is before the flop: one line tighter than an all-in
# over one re-raise, and one more when hero's raise came from an early seat.  The first re-raiser,
# while he has chips, is still behind hero with a strong range of his own: the call needs this
# much equity more.
_RERAISER_BEHIND = 0.05


def vs_reraise_and_raise(spot: Spot, three: Act, last: Act, hero_raise: float) -> Advice:
    """Hero raised, ``three`` re-raised and ``last`` raised again over both: call or fold.

    The last raise is priced as an all-in, which it nearly always is."""
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    shover = last.idx
    eff = min(live[hero], live[shover]) / spot.bb
    line = (_ALLIN_OVER_RERAISE_LINE[spot.types[shover]] - 1 + (1 if eff < 25 else 0)
            - (1 if spot.nb(hero) >= 5 else 0))
    rng = parse_range(_ALLIN_OVER_RERAISE[max(0, min(line, len(_ALLIN_OVER_RERAISE) - 1))])
    pct = range_pct(rng)
    eq = eq_vs_range(hand, rng)[0]
    bets = {hero: hero_raise, three.idx: min(three.amount, live[three.idx]), shover: live[shover]}
    need, chip_need = _call_numbers(spot, shover, bets)
    behind = live[three.idx] > three.amount + 1e-9
    margin = _RERAISER_BEHIND if behind else 0.0
    edge = eq - need - margin
    allin = last.kind == "allin"
    sit = _situation(spot, f"you opened, {spot.who(three.idx)} re-raised to {spot.bbs(three.amount):.1f}bb and "
                           + (f"{spot.who(shover)} moved all-in for {spot.bbs(live[shover]):.1f}bb" if allin else
                              f"{spot.who(shover)} raised again to {spot.bbs(last.amount):.1f}bb: priced as an all-in"))
    adv = Advice("CALL" if edge >= 0 else "FOLD", _conf(edge, 0.05, 0.02), sit)
    adv.numbers.append(f"their range ~{pct:.1f}% [{format_range(rng)}]")
    adv.numbers.append(f"your equity {_pct(eq)}; you need {_pct(need + margin)} (pot odds alone {_pct(chip_need)}"
                       + (f", ICM adds {100 * (need - chip_need):+.0f} pts" if abs(need - chip_need) >= 0.005 else "")
                       + (f", the re-raiser still to act adds {100 * margin:.0f} pts" if margin else "") + ")")
    adv.data.update(equity=eq, need=need + margin, villain_pct=pct)
    if edge >= 0:
        adv.why.append("a raise over a raise and a re-raise is the narrowest range before the flop, "
                       "and you still beat the price against it")
        if not allin or (behind and live[hero] > live[shover] + 1e-9):
            adv.action = "ALL-IN"
            adv.why.append("move all-in rather than call: nobody should see a flop cheaply against this hand")
    else:
        adv.why.append("a raise over a raise and a re-raise is the narrowest range before the flop: "
                       "you do not have the equity for the price")
    return adv


def _call_allin_over_reraise(spot: Spot, shover: int, hero_to: float, first_raiser: int | None) -> dict:
    """Hero re-raised to ``hero_to`` and ``shover`` moves all-in: equity, price and the range.

    ``vs_open`` asks it before a re-raise (the plan) and ``vs_shove`` when the all-in has
    come, so the two answers of one hand cannot disagree."""
    rng, pct = _allin_over_reraise(spot, shover, first_raiser)
    eq = eq_vs_range(spot.hand, rng)[0]
    need, chip = _call_numbers(spot, shover, {spot.hero: hero_to, shover: spot.setup.live[shover]})
    return {"eq": eq, "need": need, "chip_need": chip, "edge": eq - need, "pct": pct, "range": rng}


def _call_vs_reshove(spot: Spot, shover: int, open_to: float, hero_range: list[float]) -> dict:
    sol = _shover_solution(spot, shover, spot.hero, open_to, hero_range)
    rng, pct = _scaled_range(sol, spot.types[shover])
    eq = eq_vs_range(spot.hand, rng)[0]
    need, chip = _call_numbers(spot, shover, {spot.hero: open_to, shover: spot.setup.live[shover]})
    return {"eq": eq, "need": need, "chip_need": chip, "edge": eq - need, "pct": pct, "range": rng,
            "sol": sol}


# Raising over a short all-in to play it heads-up ("isolate").  The all-in is the raise only for a
# stack of _ISOLATE_ALLIN_BB or less, or one no bigger than _ISOLATE_ALLIN_X times the short
# all-in; a deeper stack re-raises to about _ISOLATE_SIZE_X times the all-in instead.
_ISOLATE_ALLIN_BB = 20.0
_ISOLATE_ALLIN_X = 2.5
_ISOLATE_SIZE_X = 2.5
_ISOLATE_EV_ALLIN = 0.15      # bb the all-in must earn against folding, the players behind counted
_ISOLATE_EV_COMMIT = 0.5      # the same for a re-raise that puts a third of the stack in
_ISOLATE_EDGE = 0.05          # a deeper re-raise: equity above the price against the short stack
_CALLER_MARGIN = 0.04         # a player who called and has chips behind is still in the pot
_CALLER_SHARE = 0.75          # his range: this share of the solved calling range ...
_CALLER_WIDEST = 50.0         # ... and never more than this many percent of hands
_RAISE_OVER_CALLER = parse_range("TT+, AKs, AKo")


def _isolate_ev(spot: Spot, shover: int, rng: list[float], bets: dict[int, float], behind: list[int],
                live_callers: dict[int, list[float]], raiser: int | None) -> float:
    """What hero's own all-in over a short all-in earns against folding, in big blinds.

    The players still to act and the callers with chips behind may call it; the short stack
    is in the pot whatever happens."""
    setup, hero = spot.setup, spot.hero
    prizes = Prizes() if spot.desperate else spot.prizes
    priors = {shover: rng, **live_callers}
    order = list(behind)
    if raiser is not None and raiser not in live_callers:
        priors[raiser] = _opened(spot, raiser)
        order.append(raiser)
    order += list(live_callers) + [shover]
    v_fold, v_steal, callers = build_shove_spot(
        setup, hero, prizes, caller_prizes=spot.field_prizes, types=spot.types, away=spot.away, bets=bets,
        priors=priors, caller_order=order, fold_winner=shover, extra_req={j: 0.02 for j in behind})
    return solve_shove(v_fold, v_steal, callers, unit=_unit(prizes, setup, hero)).ev_bb(spot.hand)


def vs_shove(spot: Spot, shover: int, *, raiser: int | None = None, raise_to: float = 0.0,
             hero_open: float = 0.0, callers: list[int] | None = None, committed: float = 0.0,
             reraised: int | None = None) -> Advice:
    """Hero faces one all-in.

    ``raiser`` is another player who raised before the shove and is still in;
    ``hero_open`` is hero's own raise if the shove came over the top of it.
    ``reraised`` says that raise of hero's was a re-raise, over the raise of
    this player: an all-in over a re-raise is a narrow range.
    ``callers`` are players who called the all-in and still have chips: they are
    priced as callers (their chips are in the pot, hero adds what he is asked
    for), not as a second all-in.  ``committed`` is the raise of a player who is
    not all-in yet but has put 40% or more of his stack in: he is priced as
    all-in, and only heads-up does the answer become an all-in of hero's own.
    """
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    n = setup.n
    level = min(committed, live[shover]) if committed else live[shover]      # the bet hero faces
    callers = [j for j in (callers or []) if j not in (hero, shover)]
    shove_bb = spot.bbs(live[shover])
    sol = None
    if hero_open and reraised is not None:
        rng, pct = _allin_over_reraise(spot, shover, reraised)
        sit = _situation(spot, f"you re-raised to {spot.bbs(hero_open):.1f}bb, {spot.who(shover)} moved all-in "
                               f"for {shove_bb:.1f}bb")
    elif hero_open:
        # the range the plan line under that raise was priced with (``first_in``): one range for both
        sol = _shover_solution(spot, shover, hero, hero_open, hero_open_range(spot))
        sit = _situation(spot, f"you opened, {spot.who(shover)} moved all-in for {shove_bb:.1f}bb")
    elif raiser is not None:
        orange = _opened(spot, raiser)
        sol = _shover_solution(spot, shover, raiser, raise_to, orange)
        sit = _situation(spot, f"{spot.who(raiser)} raised, {spot.who(shover)} moved all-in for {shove_bb:.1f}bb")
    else:
        sol = _shover_solution(spot, shover, None, 0.0, None)
        sit = _situation(spot, f"{spot.who(shover)} moved all-in for {shove_bb:.1f}bb")
    if sol is not None:
        rng, pct = _scaled_range(sol, spot.types[shover], shove_bb)
        strength = sol.ev                     # which hands a wider or narrower all-in range holds
    else:
        strength = [0.0] * 169
        for k, h in enumerate(allin_order()):
            strength[h] = -float(k)

    # callers with chips behind: the range they call a short all-in with.  The solved calling
    # range goes by the pot odds alone and can be any two cards; a player who just calls with
    # others still in the hand is taken as tighter than that (three quarters of it, at most half
    # of all hands), which is the careful side for hero's call and for a re-raise.
    live_callers: dict[int, list[float]] = {}
    for j in callers:
        if live[j] > level + 1e-9:
            c = sol.caller(j) if sol is not None else None
            if c and range_combos(c.call_range) > 0:
                width = min(_CALLER_WIDEST, _CALLER_SHARE * range_pct(c.call_range))
                live_callers[j] = top_percent(width, list(allin_order()))
            else:
                live_callers[j] = parse_range("TT+, AQs+, AKo")
    if live_callers:
        names = " and ".join(spot.who(j) for j in live_callers)
        sit = sit.replace(" | ", f", {names} called | ", 1) if " | " in sit else f"{sit}, {names} called"

    # the short stack is priced as all-in for all of it; what the others put in is in the pot
    bets = {shover: live[shover]}
    if hero_open:
        bets[hero] = hero_open
    if raiser is not None:
        bets[raiser] = raise_to
    for j in callers:
        bets[j] = min(live[j], live[shover])
    need, chip_need = _call_numbers(spot, shover, bets)
    fresh_behind = [j for j in range(hero + 1, n)
                    if j not in (shover, raiser) and j not in callers and not spot.away[j] and live[j] > 0] \
        if not hero_open else []
    raiser_to_act = raiser is not None and raiser not in callers
    others_live = bool(fresh_behind or live_callers or raiser_to_act)
    margin = 0.008 * len(fresh_behind) + (0.03 if raiser_to_act else 0.0) \
        + (_CALLER_MARGIN if live_callers else 0.0)
    if live_callers:
        eq = preflop_equity(hand, spot.cards, [rng] + list(live_callers.values()), iters=12000)
    else:
        eq = eq_vs_range(hand, rng)[0]
    # Stacks of a few big blinds: the exact game has the answer, players behind and second callers
    # included.  It is said in this function's terms: what those players cost is the margin over the price.
    exact = exact_edge = None
    game, profile = "", "solid"
    if not hero_open and reraised is None and not live_callers and \
            (raiser is None or raise_to >= 0.4 * live[raiser]):
        exact, game, profile = _exact_call_of(spot, [shover] + ([raiser] if raiser is not None else []) + callers)
    if exact is not None:
        won = setup.showdown(hero, shover, hero, bets)[hero] - setup.showdown(hero, shover, shover, bets)[hero]
        exact_edge = None
        if raiser is not None or callers:
            # two players in for the stack (a raise that commits and an all-in, or an all-in and a call of all
            # of it) are two all-ins: the number of that spot, with its reading of what the first one holds
            two = multi_allin(spot, sorted([shover] + ([raiser] if raiser is not None else []) + callers))
            exact, exact_edge = two.data["exact_ev"], two.data["exact_edge"]
        elif sol is not None and sol.exact and game == "short":
            # the exact answer is against the hands of the exact game; where the player is taken to hold a
            # narrower or a wider range (a tight or a loose player; anybody above ten big blinds, a little),
            # the hand's equity against that range moves it by that much of the pot.  Nothing when the range
            # is the exact game's own.
            exact += (eq - eq_vs_range(hand, sol.shove_range)[0]) * won / spot.bb
        margin = eq - need - exact * spot.bb / won if won > 0 else margin
        if exact_edge is None:
            exact_edge = exact * spot.bb / won if won > 0 else 0.0      # the same answer in points of equity to spare
    raise_edge = eq - need - margin                 # for an answer that puts the short stack all-in
    # A committed raiser with other players live: the answer may be a plain call of the raise.
    # That call is priced as what hero adds now against the pot as it stands; the raiser's last
    # chips go in after the flop, when hero can still fold, so they count for half.
    rest = 0.0
    if committed and others_live and live[shover] > level + 1e-9 and exact is None:
        now = setup.invested({**bets, shover: level, **{j: min(live[j], level) for j in callers}})
        to_call = max(0.0, min(live[hero], level) - now[hero])
        plain = to_call / (sum(setup.antes) + sum(now) + to_call)
        if plain < chip_need:
            rest = (chip_need - plain) / 2
            need, chip_need = need - (chip_need - plain), plain
    edge = eq - need - margin - rest

    adv = Advice("CALL" if edge >= 0 else "FOLD", _conf(edge, 0.05, 0.02), sit)
    if exact is not None:
        # with two players in for the stack (a raise that commits and an all-in) the numbers are the first pass's
        adv.confidence = _exact_conf(exact, shove_bb, 2 if raiser is not None or callers else 1, game, profile)
        adv.data.update(exact=True, exact_ev=exact, exact_edge=exact_edge)
    adv.numbers.append(f"their range ~{pct:.0f}% [{format_range(rng)}]")
    added = "players still in or to act add" if live_callers else "players still to act add"
    adv.numbers.append(f"your equity {_pct(eq)}{' against all of them' if live_callers else ''}; "
                       f"you need {_pct(need + margin + rest)} "
                       f"(pot odds alone {_pct(chip_need)}"
                       + (f", ICM adds {100 * (need - chip_need):+.0f} pts" if abs(need - chip_need) >= 0.005 else "")
                       + (f", {added} {100 * margin:.0f} pts" if margin >= 0.005 else "")
                       + (f", the raiser's chips behind add {100 * rest:.0f} pts" if rest >= 0.005 else "") + ")")
    adv.data.update(equity=eq, need=need + margin + rest, villain_pct=pct)
    if committed and live[shover] > level + 1e-9:
        adv.numbers.append(f"{spot.pos(shover)} has {spot.bbs(live[shover] - level):.1f}bb behind the raise: "
                           + ("they go in after the flop" if rest else "priced as all-in"))
    if live_callers:
        for j, r in live_callers.items():
            adv.numbers.append(f"{spot.pos(j)} called with chips behind: about {range_pct(r):.0f}% of hands "
                               f"[{format_range(r)}]")
    elif exact is not None:
        adv.numbers.append(f"an all-in of this size is solved exactly, with every player who can still call: "
                           f"calling earns {exact:+.2f}bb against folding")
    else:
        # how wide must the shove be for a call to break even?
        be = None
        for p in (2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 26, 30, 35, 40, 50, 60, 75, 100):
            if eq_vs_range(hand, scale_range(strength, p))[0] >= need + margin + rest:
                be = p
                break
        if be is None:
            adv.numbers.append("no realistic shoving range makes this a call")
        else:
            adv.numbers.append(f"calling is right whenever they shove at least ~{be}% of hands here")
        adv.data.update(breakeven_pct=be)

    if sol is None:
        adv.numbers.append("an all-in over a re-raise is a narrow range: the hands they opened that play for "
                           "stacks, not a re-shove over a wide range")
    if exact is None and not hero_open and fresh_behind and _several_will_call(setup, hero, live[shover]):
        adv.warnings.append(_SEVERAL_CALL)
    if edge >= 0:
        adv.why.append(f"you beat the price against the {'raiser' if committed else 'all-in'} and the caller "
                       "together" if live_callers else
                       "you beat the price against a raiser who has committed his stack" if committed else
                       "you beat the price against the range they shove here")
        stack_bb = spot.bbs(live[hero])
        wants_raise = _RAISE_OVER_CALLER[hand] >= 0.5 if live_callers else not _TRAP[hand]
        if committed and not others_live:
            adv.action = "ALL-IN"
            adv.why.append("re-raise all-in rather than call: they are not folding and you deny the flop")
        elif others_live and live[hero] > live[shover] * 1.3 and wants_raise and raise_edge >= 0:
            _isolate(spot, adv, shover, rng, bets, level, fresh_behind, live_callers, raiser, raise_to,
                     hero_open, raise_edge, stack_bb)
        elif others_live and _TRAP[hand] and not live_callers:
            adv.alt.append("just calling to invite another player in is also fine with a monster")
        elif live_callers:
            adv.why.append("a player with chips is in the pot too: call, and re-raise only with TT+ or AK")
    else:
        adv.why.append("you do not have the equity for the price"
                       + (", and busting here costs far more than the chips are worth" if need - chip_need > 0.04 else ""))
        if chip_need <= eq < need + margin + rest:
            adv.why.append("on chips alone this is a call; ICM / survival is what makes it a fold"
                           if need - chip_need >= 0.005 and eq >= chip_need + margin + rest else
                           "the pot odds alone are met; the players still in the hand are what makes it a fold")
    t = spot.types[shover]
    if t in ("nit", "tight") and edge < 0.04 and edge >= 0:
        adv.warnings.append(f"{spot.pos(shover)} is tagged {t}: this is thin against their real range")
    return adv


def _isolate(spot: Spot, adv: Advice, shover: int, rng: list[float], bets: dict[int, float], level: float,
             behind: list[int], live_callers: dict[int, list[float]], raiser: int | None, raise_to: float,
             hero_open: float, edge: float, stack_bb: float) -> None:
    """The call is right and other players are live: all-in, a sized re-raise, or just the call."""
    hero, live, bb = spot.hero, spot.setup.live, spot.bb
    short_bb = spot.bbs(live[shover])
    heads_up = "players are still to act: raise to get heads-up against the short stack" if not live_callers \
        else "re-raise to play the short stack heads-up: the caller folds most of his hands"
    ev = None
    others = "with a caller in the pot" if live_callers else "with players still to act"
    note = _value_note(spot)
    counted = (f"{note}, " if note else "") + "the players still in the hand counted"
    # the sized re-raise: about 2.5 times the all-in, never under the smallest legal raise, in half big blinds
    before = max(raise_to, hero_open, bb)
    smallest = level + max(bb, level - before)
    size_bb = max(_ISOLATE_SIZE_X * short_bb, spot.bbs(smallest))
    size_bb = int(size_bb * 2 + 0.999) / 2.0
    if stack_bb <= _ISOLATE_ALLIN_BB or live[hero] <= _ISOLATE_ALLIN_X * live[shover] or size_bb >= stack_bb - 1:
        ev = _isolate_ev(spot, shover, rng, bets, behind, live_callers, raiser)
        if ev > _ISOLATE_EV_ALLIN:
            adv.action = "RE-RAISE ALL-IN (isolate)"
            adv.why.append(heads_up)
            adv.numbers.append(f"your all-in over it: shove EV {ev:+.2f}bb vs folding ({counted})")
            adv.data.update(isolate_ev_bb=ev)
        else:
            adv.why.append(f"just call: this hand is not strong enough to move all-in for {stack_bb:.0f}bb "
                           f"{others}")
        return
    if size_bb * 3 >= stack_bb:
        # a third of the stack goes in: the re-raise is for stacks if a player behind wakes up
        ev = _isolate_ev(spot, shover, rng, bets, behind, live_callers, raiser)
        strong = ev > _ISOLATE_EV_COMMIT
    else:
        strong = edge >= _ISOLATE_EDGE
    if strong:
        adv.action = f"RE-RAISE to {size_bb:g}bb (isolate)"
        adv.why.append(heads_up)
        if ev is not None:
            adv.numbers.append(f"the re-raise puts a third of your stack in; playing for all of it is worth "
                               f"{ev:+.2f}bb against folding ({counted})")
            adv.data.update(isolate_ev_bb=ev)
            adv.warnings.append("you are committed after this re-raise: do not fold to an all-in behind you")
        else:
            adv.warnings.append("if a player behind you moves all-in, fold without QQ+ or AK")
    else:
        adv.why.append(f"just call: this hand is not strong enough to re-raise to {size_bb:g}bb {others}")


def multi_allin(spot: Spot, allins: list[int], raiser: int | None = None, raise_to: float = 0.0) -> Advice:
    """Two or more players are all-in before hero acts (approximate)."""
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    first = allins[0]
    sol = _shover_solution(spot, first, None, 0.0, None)
    r1, pct1 = _scaled_range(sol, spot.types[first], spot.bbs(live[first]))
    ranges = [r1]
    for j in allins[1:]:
        c = sol.caller(j)
        rj = c.call_range if c and range_combos(c.call_range) > 0 else parse_range("TT+, AQs+, AKo")
        ranges.append(rj)
    exact, game, profile = _exact_call_of(spot, allins) if raiser is None else (None, "", "solid")   # the exact game answers
    if exact is not None:               # ... and the equity is only shown: the quick estimate will do (12,000 deals a hand will not)
        eq = beats_all([eq_vs_range(hand, r)[0] for r in ranges])
        moved = eq - beats_all([eq_vs_range(hand, r)[0] for r in [list(sol.shove_range)] + ranges[1:]]) \
            if sol.exact and game == "short" else 0.0      # the spin game's answers are already the reply to the opponents' kind
    else:
        eq = preflop_equity(hand, spot.cards, ranges, iters=12000)
    call_amt = min(live[hero], max(live[j] for j in allins)) - setup.invested()[hero]
    # the pot hero can win: of a bigger all-in only the part his own stack matches
    pot = sum(setup.antes) + sum(setup.blinds) + sum(min(live[j], live[hero]) for j in allins)
    need_chip = call_amt / (pot + call_amt)
    big = max(allins, key=lambda k: live[k])
    rp = 0.0 if spot.prizes.chip_ev or spot.desperate else spot.prizes.risk_premium(live, hero, big)
    # with two players already all-in, folding often means a free pay jump
    need = need_chip + rp * 1.2 + (0.03 if rp > 0 else 0.02)
    if exact is not None:
        exact += moved * (pot + call_amt) / spot.bb         # a first all-in taken narrower or wider than the exact game's: in equity
        need = eq - exact * spot.bb / (pot + call_amt)
    edge = eq - need
    names = " and ".join(spot.who(j) for j in allins)
    adv = Advice("CALL" if edge >= 0 else "FOLD", _conf(edge, 0.06, 0.025),
                 _situation(spot, f"{names} are all-in"))
    if exact is not None:
        adv.confidence = _exact_conf(exact, spot.bbs(live[first]), 2, game, profile)
        adv.data.update(exact=True, exact_ev=exact, exact_edge=edge)        # edge: the answer in points of equity to spare
        adv.numbers.append(f"equity vs both ranges about {_pct(eq)}; pot odds {_pct(need_chip)}")
        adv.numbers.append(f"an all-in of this size is solved exactly, with every player who can still call: "
                           f"calling earns {exact:+.2f}bb against folding")
    else:
        adv.numbers.append(f"equity vs both ranges {_pct(eq)}; need about {_pct(need)} "
                           f"(pot odds {_pct(need_chip)}, ICM/safety +{100 * (need - need_chip):.0f} pts)")
    adv.numbers.append(f"first shover ~{pct1:.0f}%, the caller much tighter [{format_range(ranges[-1])}]")
    adv.why.append("against two all-in ranges you need a hand that is ahead of calling ranges, "
                   "usually QQ+ / AK" if edge < 0 else "strong enough even against two ranges")
    if exact is None:
        adv.warnings.append("multi-way all-in: side pots are approximated")
    return adv


# --------------------------------------------------------------------------
# Facing an open raise
# --------------------------------------------------------------------------

# Big blind closing the action against one raise: how far above the pot odds a hand's equity must
# be to call, by how badly that kind of hand plays after the flop (pairs least, then suited hands,
# then two offsuit cards ten or higher, then the other offsuit hands).  Half of the ICM risk
# premium comes on top.  It is one test for every hand, charted or not, so a stronger hand never
# folds where a weaker one calls; and no hand needs more than _BB_CALL_NET above the price.
# Every suited hand gets the same points: with fewer for the connected ones 32s would call
# where T2s folds.
_BB_CALL_MARGIN = {"pair": 0.02, "suited_conn": 0.06, "suited": 0.06, "broadway_off": 0.08, "off": 0.15}
_BB_CALL_NET = 0.15
_BB_CALL_STACK_SHARE = 0.12      # with 25bb or less the default style calls a raise that costs this share of the stack at most


def bb_call_points(kind: str, risk_premium: float = 0.0, callers: int = 0, in_position: bool = False) -> float:
    """Equity the big blind needs above the pot odds to call one raise with a hand of this kind.

    ``in_position``: the raise came from the small blind and nobody else is in, so the big
    blind acts last after the flop and every kind of hand plays better (two thirds of the points)."""
    points = _BB_CALL_MARGIN[kind] * (2.0 / 3.0 if in_position else 1.0) + max(0.0, risk_premium) / 2
    if callers and kind in ("off", "broadway_off"):
        points += 0.03                    # offsuit hands lose the most with more players in the pot
    return min(_BB_CALL_NET, points)


def _hand_kind(hand: int) -> str:
    row, col = divmod(hand, 13)
    if row == col:
        return "pair"
    hi, lo = min(row, col), max(row, col)   # grid indices: 0 = ace
    gap = lo - hi
    if row < col:
        return "suited_conn" if gap <= 2 and hi >= 1 else "suited"
    return "broadway_off" if lo <= 4 else "off"


def flat_range(opener_n_behind: int, caller_n_behind: int) -> list[float]:
    """What a player is taken to hold who only called a raise: the hands his seat's chart calls with.

    The small blind's chart re-raises or folds (against the first seats it calls JJ, TT and AQs, against the
    late ones nothing), so a small blind who did call plays another way: he is given the button's calls
    against that raiser, and against a button raise the button's calls against the cutoff."""
    if caller_n_behind == 1:
        opener_n_behind, caller_n_behind = max(opener_n_behind, 3), 2
    chart = vs_open_chart(opener_n_behind, caller_n_behind)
    return [max(a, b) for a, b in zip(chart["call"], chart["setmine"])]


def vs_open(spot: Spot, opener: int, raise_to: float, flats: list[int]) -> Advice:
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    n = setup.n
    bb = spot.bb
    if raise_to >= 0.4 * live[opener]:
        # the opener is committed: price the raise as an all-in.  Heads-up the answer is hero's
        # own all-in; with a caller in the pot or players behind it is a call, a raise or a fold
        adv = vs_shove(spot, opener, callers=flats, committed=raise_to)
        called = f", {len(flats)} caller{'s' if len(flats) > 1 else ''}" if flats else ""
        adv.situation = _situation(spot, f"{spot.who(opener)} raised to {raise_to / bb:.1f}bb, "
                                         f"over 40% of their stack: they are committed{called}")
        return adv
    eff = min(live[hero], live[opener]) / bb
    hero_bb = live[hero] / bb
    o_nb, h_nb = spot.nb(opener), spot.nb(hero)
    o_type = spot.types[opener]
    open_rng = villain_open_range(o_nb, o_type, eff, heads_up=n == 2)
    eq_open = eq_vs_range(hand, open_rng)[0]
    inv = setup.invested({opener: raise_to, **{j: raise_to for j in flats}})
    pot = sum(setup.antes) + sum(inv)
    to_call = raise_to - inv[hero]
    need = to_call / (pot + to_call)
    in_blinds = h_nb <= 1
    ip = not in_blinds
    flat_txt = f" and {len(flats)} caller{'s' if len(flats) > 1 else ''}" if flats else ""
    sit = _situation(spot, f"{spot.who(opener)} raised to {raise_to / bb:.1f}bb{flat_txt}")
    adv = Advice("FOLD", "standard", sit)
    adv.numbers.append(f"their opening range ~{range_pct(open_rng):.0f}%; your equity vs it {_pct(eq_open)}; "
                       f"pot odds to call {_pct(need)}")
    behind = [j for j in range(hero + 1, n) if j != opener and j not in flats
              and not spot.away[j] and live[j] > 0]
    rp, rp_who = _icm_pressure(spot, [opener] + behind)
    icm_tight = rp >= 0.06
    kind = _hand_kind(hand)

    # the big blind closes the action: one price test for every hand, charted or not
    bb_last = o_nb == 1 and not flats and n > 2          # the raise came from the small blind: the big blind acts last
    bb_points = bb_call_points(kind, rp, len(flats), in_position=bb_last)
    bb_edge = eq_open - need - bb_points if h_nb == 0 else -1.0
    bb_share = 1.0
    eq_pot = eq_open                 # the share of the pot a call plays for: against the raiser, and his callers
    if flats and _guide():
        # the price of a call counts the callers' chips, so the equity has to count their hands
        eq_pot = beats_all([eq_open] + [eq_vs_range(hand, flat_range(o_nb, spot.nb(j)))[0] for j in flats])
        adv.numbers.append(f"against the raiser and the {'callers' if len(flats) > 1 else 'caller'} together "
                           f"you have about {_pct(eq_pot)}")
    if h_nb == 0 and _guide():
        # the quick guide's test: the part of its equity this hand turns into chips must beat the price
        bb_share = bb_realised(hand, eff, bb_last)
        # the margin is a part of a fair share of the pot: with callers the share is smaller, and so is the margin
        over = _BB_MARGIN[chart_style()] * 2.0 / (2 + len(flats)) + max(0.0, rp) / 2
        bb_points = (need + over) / bb_share - need
        bb_edge = eq_pot - need - bb_points
        adv.numbers.append(f"big blind closing the action: to call you need {_pct(need + bb_points)} (the price "
                           f"{_pct(need)} plus {100 * over:.0f} pts, over the {_pct(bb_share)} of its equity this "
                           "hand turns into chips after the flop)")
        adv.data.update(bb_call_need=need + bb_points, bb_call_edge=bb_edge, bb_realised=bb_share, bb_over=over,
                        bb_equity=eq_pot)
    elif h_nb == 0:
        adv.numbers.append(f"big blind closing the action: to call you need {_pct(need + bb_points)} "
                           f"(the price plus {100 * bb_points:.0f} pts for how this hand plays after the flop"
                           + (", ICM included" if rp >= 0.01 and bb_points < _BB_CALL_NET else "") + ")")
        adv.data.update(bb_call_need=need + bb_points, bb_call_edge=bb_edge)

    if eff <= 25:
        flat_rngs = {j: flat_range(o_nb, spot.nb(j)) for j in flats}
        prizes = Prizes() if spot.desperate else spot.prizes
        sol = solve_reshove(setup, hero, opener, raise_to, prizes, opener_range=open_rng,
                            flat_callers=flat_rngs, caller_prizes=spot.field_prizes,
                            types=spot.types, away=spot.away)
        ev = sol.ev_bb(hand)
        oc = sol.caller(opener)
        call_share = range_combos(oc.call_range) / max(1e-9, range_combos(open_rng)) if oc else 0.0
        adv.numbers.append(f"re-shove EV {ev:+.2f}bb vs folding ({_value_note(spot)}); "
                           f"everyone folds {_pct(sol.fold_equity[hand])}; when called you have "
                           f"{_pct(sol.eq_called[hand])}")
        if oc:
            adv.numbers.append(f"opener calls with ~{_pct(call_share)} of their opens [{format_range(oc.call_range)}]")
        adv.data.update(reshove_ev_bb=ev)
        jam_word = "ALL-IN" if hero_bb <= 32 else f"3-BET to {min(hero_bb, max(2.6 * raise_to / bb, eff)):.0f}bb (puts the opener all-in)"
        bar = 0.15
        chart = vs_open_chart(o_nb, h_nb)
        # The looser style also asks what the big blind's call is worth: the share of its equity this kind of
        # hand turns into chips after the flop, times the pot, less the call.  An all-in that earns less
        # than that is a call.  (Without it a suited connector moved all-in for 20bb to win 0.05bb.)
        # The default style calls a raise in the big blind only when it costs 12% of the stack or less: shorter
        # than that it moves all-in or folds.  The guide's styles go by the price alone, at every depth: with
        # 8bb the big blind is not folding half its hands to a raise that asks for 18% of the pot.
        affordable = _guide() or to_call <= _BB_CALL_STACK_SHARE * live[hero]
        price_call = h_nb == 0 and bb_edge >= 0 and affordable
        call_bb = (bb_share * eq_pot * (pot + to_call) - to_call) / bb if price_call else 0.0
        short_call = to_call > _BB_CALL_STACK_SHARE * live[hero]       # a call the default style does not make
        if _win() and price_call and ev > bar and call_bb >= ev:
            adv.action = "CALL"
            adv.confidence = "close" if call_bb - ev < _CALL_OVER_ALLIN_CLEAR else "standard"
            adv.why.append("the all-in earns, but less than the call is worth at this price: call, and go on "
                           + ("with any pair or any draw: this short the flop decides it" if short_call else
                              "with top pair or better or a strong draw"))
            adv.numbers.append(f"the call is worth about {call_bb:+.2f}bb, the all-in {ev:+.2f}bb")
            adv.data.update(call_value_bb=call_bb)
        elif ev > bar:
            adv.action = jam_word
            adv.confidence = _conf(ev - bar, 0.6, 0.15)
            adv.why.append("re-shoving wins the pot often enough, and you have real equity when called")
            if _TRAP[hand] and eff >= 15:
                adv.alt.append("with a monster, a small 3-bet or a flat to trap is fine if players behind are aggressive")
        elif _win() and ip and eff >= _FLAT_SHORT_FROM and eq_pot - need >= _FLAT_SHORT_EDGE and \
                max(chart["value"][hand], chart["call"][hand]) >= 0.5:
            # the looser style: a hand the chart plays against this raise, in position, is not folded
            # because the all-in does not earn; it calls
            adv.action = "CALL"
            adv.confidence = "close"
            adv.why.append("not a profitable all-in, and too strong to fold in position: call, and continue "
                           "with top pair or better or a strong draw")
        elif bb_edge >= 0 and affordable:
            adv.action = "CALL"
            # the guide's styles say "close" by the margin; the default says it of every such call
            adv.confidence = "standard" if _guide() and bb_edge >= _BB_CLOSE else "close"
            adv.why.append("not a profitable shove, but the big blind is getting the right price to see a flop")
            if short_call:
                adv.warnings.append("this short the flop decides it: all-in with any pair or any draw, otherwise give up")
            else:
                adv.warnings.append("play fit-or-fold after the flop: continue with top pair or better, or a strong draw")
        else:
            adv.confidence = _conf(ev - bar, 0.6, 0.15)
            adv.why.append("at this depth it is re-shove or fold, and this hand does not earn as a shove")
            if o_type in ("nit", "tight"):
                adv.why.append(f"the opener is {o_type}: their range is strong and calls a lot of the time")
        if rp >= 0.05:
            adv.why.append(f"ICM: {_pct(rp)} risk premium against {spot.pos(rp_who)}")
        return adv

    # deeper stacks: 3-bet / call / fold from the charts
    cats = ["EP", "MP", "LP"]
    ocat = opener_category(o_nb)
    chart_nb = o_nb
    tshift = PLAYER_TYPES[o_type]["open_shift"]
    if ocat in cats and tshift:
        k = max(0, min(2, cats.index(ocat) - (1 if tshift > 0 else -1)))
        chart_nb = {"EP": 8, "MP": 5, "LP": 3}[cats[k]]
    ch = vs_open_chart(chart_nb, h_nb)
    value, bluff, call, setmine, deep = (list(ch[k]) for k in ("value", "bluff", "call", "setmine", "deep"))
    if o_type == "nit" and ocat == "EP":
        value = parse_range("KK+, AKs")
        call = [max(a, b) for a, b in zip(call, parse_range("QQ, AKo"))]
    r_bb = raise_to / bb
    size = ((3.0 if ip else 3.8) + len(flats)) * r_bb
    odds_ok = eff / max(r_bb, 0.1) >= 15
    # A re-raise that is not all-in comes with a plan for the all-in it may meet.  With 45bb or
    # less it is only made with a hand that then calls: one that would fold moves all-in now
    # where that clearly earns, and is otherwise played as a call or a fold (``demoted``).
    decided = demoted = converted = False
    can_call = h_nb == 0 or ip or max(call) >= 0.5 or _SMALL_BLIND_CALLS[hand] >= 0.5
    if value[hand] >= 0.5:
        if size >= 0.35 * eff:
            adv.action = "ALL-IN"
            adv.why.append("a value 3-bet would commit you anyway, so move in")
            decided = True
        else:
            plan = _call_allin_over_reraise(spot, opener, size * bb, opener)
            calls = plan["edge"] >= 0
            plan_line = (f"if {spot.pos(opener)} ({spot.bbs(live[opener]):.0f}bb) shoves: "
                         f"{'CALL' if calls else 'FOLD'} (need {_pct(plan['need'])}, have {_pct(plan['eq'])} "
                         f"vs ~{plan['pct']:.0f}% range)")
            if calls or eff > 45:
                adv.action = f"3-BET to {size:.1f}bb"
                adv.why.append("3-bet for value: you are ahead of the range that continues")
                adv.numbers.append(plan_line)
                adv.data.update(plan=[{"idx": opener, "pos": spot.pos(opener), "stack_bb": spot.bbs(live[opener]),
                                       "need": plan["need"], "eq": plan["eq"], "edge": plan["edge"],
                                       "pct": plan["pct"], "call": calls}])
                if calls:
                    adv.why.append("do not fold to a 4-bet at this depth")
                elif _PREMIUM[hand]:
                    adv.alt.append("facing a small 4-bet: continue; an all-in for this much is a fold")
                else:
                    adv.alt.append("facing a 4-bet: continue with QQ+/AK, fold the rest")
                decided = True
            else:
                prizes = Prizes() if spot.desperate else spot.prizes
                flat_rngs = {j: flat_range(o_nb, spot.nb(j)) for j in flats}
                sol = solve_reshove(setup, hero, opener, raise_to, prizes, opener_range=open_rng,
                                    flat_callers=flat_rngs, caller_prizes=spot.field_prizes,
                                    types=spot.types, away=spot.away)
                ev = sol.ev_bb(hand)
                bar = max(_RESHOVE_CLEARLY, _RESHOVE_CLEARLY_SHARE * eff) if can_call else _RESHOVE_CLEARLY
                if ev >= bar:
                    adv.action = "ALL-IN" if hero_bb <= eff + 7 else \
                        f"3-BET to {eff:.0f}bb (puts the opener all-in)"
                    adv.why.append("a small re-raise would have to fold to an all-in with this hand: "
                                   "move all-in now, it earns")
                    adv.numbers.append(f"re-shove EV {ev:+.2f}bb vs folding ({_value_note(spot)}); "
                                       f"everyone folds {_pct(sol.fold_equity[hand])}; when called you have "
                                       f"{_pct(sol.eq_called[hand])}")
                    adv.numbers.append(plan_line.replace("if ", "after a small re-raise, if ", 1))
                    adv.data.update(reshove_ev_bb=ev, reshove_bar_bb=bar)    # the bar: what "close" is measured against
                    decided = converted = True
                else:
                    demoted = True
        if converted:
            adv.confidence = _conf(ev - bar, 1.5, 0.3)
        elif decided:
            adv.confidence = "clear" if _PREMIUM[hand] else "standard"
    # a demoted hand is stronger than the calls of its seat: it calls where that seat calls at all
    if decided:
        pass
    elif demoted and not can_call:
        adv.why.append("not strong enough to re-raise and call an all-in at this depth, and from the small "
                       "blind a call is worse than a fold")
    elif demoted or call[hand] >= 0.5 or (setmine[hand] >= 0.5 and odds_ok) or \
            (deep[hand] >= 0.5 and eff >= 50 and (h_nb <= 2 or flats)):
        # the big blind's charted hands pass the same price test as every other hand of his;
        # the small blind, out of position with players behind, drops the thin calls under ICM
        price_bad = h_nb == 0 and bb_edge < 0
        thin_oop = icm_tight and h_nb == 1 and kind in ("off", "broadway_off", "suited") and not demoted
        if price_bad or thin_oop:
            adv.why.append("in the chart to defend, but the price / ICM makes it a fold here")
            adv.confidence = "close"
        else:
            adv.action = "CALL"
            if h_nb == 0 and bb_edge < 0.03:
                adv.confidence = "close"
            if kind == "pair" and not _BIG_PAIRS[hand]:
                adv.why.append("set-mine: you have the implied odds; fold the flop without a set or an overpair")
            else:
                adv.why.append("playable against their range and deep enough to see a flop"
                               + (" in position" if ip else ""))
            if demoted:
                adv.why.append("not a re-raise at this depth: it could not call an all-in after it")
    elif bluff[hand] >= 0.5 and not icm_tight and eff > 45 and o_type not in ("station", "loose", "maniac"):
        adv.action = f"3-BET to {size:.1f}bb (semi-bluff, fold to a 4-bet)"
        adv.confidence = "close"
        adv.why.append("a blocker hand that plays well as a 3-bet bluff against an opener who can fold")
        adv.alt.append("FOLD is completely fine, and better against a player who never folds")
    elif bb_edge >= 0:
        adv.action = "CALL"
        adv.confidence = "standard" if _guide() and bb_edge >= _BB_CLOSE else "close"
        adv.why.append("closing the action in the big blind at a good price")
        adv.warnings.append("play fit-or-fold after the flop")
    else:
        if _guide() and h_nb == 0 and bb_edge >= -_BB_CLOSE:
            adv.confidence = "close"            # a fold that is nearly a call
        adv.why.append("not strong enough to continue against this opening range"
                       + (" out of position" if in_blinds else ""))
        if setmine[hand] >= 0.5 and not odds_ok:
            adv.why.append("no implied odds to set-mine at this stack depth")
    if icm_tight and h_nb == 0 and adv.action == "CALL":
        adv.why.append(f"ICM: {_pct(rp)} risk premium against {spot.pos(rp_who)}, counted in what you need to call")
    elif icm_tight:
        adv.why.append(f"ICM: {_pct(rp)} risk premium against {spot.pos(rp_who)}: no light 3-bets or loose calls")
    return adv


# --------------------------------------------------------------------------
# Hero opened and got re-raised (not all-in), or a raise and a re-raise in front
# --------------------------------------------------------------------------

def _acts_after(spot: Spot, a: int, b: int) -> bool:
    """After the flop, does player ``a`` act after player ``b``?  (Then ``a`` is in position.)

    The small blind acts first, then the big blind, then the others in their order before the
    flop, the button last.  Heads-up the button is the small blind and acts last."""
    n = spot.setup.n

    def turn(i: int) -> int:
        nb = spot.nb(i)
        if n == 2:
            return nb                    # the big blind (0 behind) first, the button last
        return 1 - nb if nb <= 1 else 1 + n - nb

    return turn(a) > turn(b)


# One re-raise.  With 45bb or less the reply was all-in or fold by the all-in's number alone, so a hand far
# ahead of the price was folded as soon as prizes made the all-in thin: queens with 53% against a range
# that asks 34%, 250 places from the money, where ace-king offsuit and kings played.  Now a hand that is
# too good to fold (the same hands as in the small blind against a late raise: TT+, AQs+, AKo) and has this
# much equity over the price and the risk premium is never folded to one re-raise: where its all-in does
# not clear the bar, it calls.  Aces and kings are never folded there at all.  The risk premium is in the
# test, so on the bubble against a stack that covers hero queens can still be a fold.
# The other hands keep the old answer: a small pair or a weak ace that calls a re-raise out of position
# does not get the equity it has on paper.
_NEVER_FOLD = _SMALL_BLIND_CALLS
_NEVER_FOLD_EDGE = 0.10
# ... and it moves all-in after all when a call would leave less than this many pots behind.
_CALL_LEAVES_POTS = 1.0


def vs_3bet(spot: Spot, villain: int, three_to: float, hero_open: float,
            reraised: int | None = None, alone: bool = True) -> Advice:
    """Hero raised and ``villain`` re-raised, not all-in.  ``reraised``: hero's raise was itself
    a re-raise, over the raise of that player.  ``alone``: nobody else re-raised, and nobody
    called the re-raise."""
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    bb = spot.bb
    eff = min(live[hero], live[villain]) / bb
    if three_to >= 0.4 * min(live[hero], live[villain]):
        adv = vs_shove(spot, villain, hero_open=hero_open, reraised=reraised)
        mine, theirs = ("re-raised to", "raised again to") if reraised is not None else ("opened", "3-bet to")
        adv.situation = _situation(spot, f"you {mine} {hero_open / bb:.1f}bb, {spot.who(villain)} {theirs} "
                                         f"{three_to / bb:.1f}bb: at these stacks this is for everything")
        if adv.action == "CALL":
            adv.action = "ALL-IN"
            adv.why.append("the 3-bet commits both stacks: move in rather than call" if reraised is None else
                           "this raise commits both stacks: move in rather than call")
        if reraised is None:
            adv.warnings.append("a small 3-bet where a shove was available is often a strong hand: "
                                "their range is modelled as a re-shove and may be tighter")
        return adv
    v_type = spot.types[villain]
    rng = threebet_range(max(1, spot.nb(hero)), v_type, setup.n)
    eq = eq_vs_range(hand, rng)[0]
    inv = setup.invested({hero: hero_open, villain: three_to})
    pot = sum(setup.antes) + sum(inv)
    to_call = three_to - hero_open
    need = to_call / (pot + to_call)
    # In position: the re-raise came from the blinds and hero acts after that player once the flop
    # is out.  The small blind who raised and is re-raised by the big blind acts first there, so he
    # is out of position (except heads-up, where the small blind is the button).
    ip = spot.nb(villain) <= 1 and _acts_after(spot, hero, villain)
    sit = _situation(spot, f"you opened {hero_open / bb:.1f}bb, {spot.who(villain)} 3-bet to {three_to / bb:.1f}bb")
    adv = Advice("FOLD", "standard", sit)
    adv.numbers.append(f"their 3-bet range ~{range_pct(rng):.1f}% [{format_range(rng, 0.5)}]; "
                       f"your equity {_pct(eq)}; pot odds {_pct(need)}")
    rp, rp_who = _icm_pressure(spot, [villain])
    kind = _hand_kind(hand)

    prizes = Prizes() if spot.desperate else spot.prizes
    v_fold, v_steal, callers = build_shove_spot(
        setup, hero, prizes, caller_prizes=spot.field_prizes, types=spot.types, away=spot.away,
        bets={hero: hero_open, villain: three_to}, priors={villain: rng},
        caller_order=[villain], fold_winner=villain)
    sol = solve_shove(v_fold, v_steal, callers, unit=_unit(prizes, setup, hero))
    ev = sol.ev_bb(hand)
    adv.numbers.append(f"4-bet shove EV {ev:+.2f}bb vs folding; they fold {_pct(sol.fold_equity[hand])}; "
                       f"when called you have {_pct(sol.eq_called[hand])}")

    one = alone and reraised is None                     # hero opened and one player re-raised

    edge_kept = _bar(_NEVER_FOLD_EDGE, 0.05)

    short_handed = setup.n <= 3

    def clears(h: int, e: float) -> bool:
        """45bb or less: the all-in earns what the engine wants of it.  At a full table it must also hold its own
        against the whole re-raising range (a re-raise there is mostly strong hands); with three players or two
        the re-raises are wide and bluff often (``threebet_range``), and what the all-in earns decides."""
        return sol.ev_bb(h) > _bar(0.5, 0.25) and (short_handed or e >= _bar(0.45, 0.42) or bool(_PREMIUM[h]))

    def kept(h: int, e: float) -> bool:
        """Never folded to one re-raise (``_NEVER_FOLD``)."""
        return one and bool(_TRAP[h] or (_NEVER_FOLD[h] >= 0.5 and e - need - rp >= edge_kept))

    keep = kept(hand, eq)
    if one and not keep and eff <= 45 and hand in _pairs():
        # no pair folds where a smaller pair plays
        keep = any(clears(p, e) or kept(p, e) for p in _pairs() if p > hand for e in [eq_vs_range(p, rng)[0]])
    ahead = (f"too far ahead of the price to fold to one re-raise: {_pct(eq)} against their range, and the "
             f"call needs {_pct(need)}" + (f" ({_pct(need + rp)} with the prizes counted)" if rp >= 0.005 else "")
             if eq - need - rp >= edge_kept and _NEVER_FOLD[hand] >= 0.5 else
             "aces and kings are never folded before the flop to one re-raise" if _TRAP[hand] else
             "a smaller pair plays here, so this one is not folded")

    if eff <= 45:
        if clears(hand, eq):
            adv.action = "ALL-IN"
            adv.confidence = "clear" if _PREMIUM[hand] and eq >= 0.5 else "standard"
            adv.why.append("at this depth a 4-bet is a shove, and this hand profits from it")
        elif keep:
            adv.why.append(ahead)
            counted = "" if prizes.chip_ev else " with prizes counted"
            if min(live[hero], live[villain]) - three_to < _CALL_LEAVES_POTS * (pot + to_call) and ev > 0:
                adv.action = "ALL-IN"
                adv.why.append("a call would leave less than the pot behind, so the chips go in now")
            else:
                adv.action = "CALL"
                # kings against a re-raiser tagged nit after an early raise are behind even at the price:
                # still no fold, but a close call, as it is with more than 45bb
                adv.confidence = "standard" if eq >= need + 0.03 else "close"
                adv.why.append(
                    f"the all-in is thin{counted} ({ev:+.2f}bb against folding): call, the lower-variance play"
                    if 0 < ev <= 0.5 else
                    f"the all-in does not earn{counted} ({ev:+.2f}bb against folding): call" if ev <= 0 else
                    f"called, an all-in has only {_pct(sol.eq_called[hand])}: call instead")
                if eq >= need + 0.03:
                    adv.why.append("after the flop the stack goes in with an overpair, top pair or better")
            adv.data.update(never_fold=True)
        elif _win() and one and ip and eff >= 25 and _CALL_RERAISE_IP[hand] >= 0.5 and \
                eq * 0.92 >= need + 0.03 + rp:
            # the looser style: in position, a middle pair or two big suited cards with the price see a flop
            # (a small pair has no odds for a set this shallow, and small suited cards are dominated)
            adv.action = "CALL"
            adv.confidence = "close"
            adv.why.append("good enough to see a flop in position against one re-raise: continue with top pair "
                           "or better, a set or a strong draw")
        else:
            adv.why.append("not strong enough to play for stacks against a 3-betting range")
            adv.confidence = _conf(ev - 0.5, 1.0, 0.3)
            if one and _NEVER_FOLD[hand] >= 0.5 and eq - need - rp >= 0.03:
                # ahead of the price, but by less than the points that make it a call: a close fold, said as one
                adv.confidence = "close"
                adv.alt.append(f"CALL is close: {_pct(eq)} against their range, and the call needs {_pct(need + rp)}"
                               + (" with the prizes counted" if rp >= 0.005 else ""))
                adv.data.update(close_call=(need + rp, eq, rp >= 0.005))
    else:
        # QQ+ and AK never fold to one re-raise this deep.  In position they call; out of position
        # with 60bb or less they move all-in when that all-in earns, otherwise they call too.
        calls = eq * (0.92 if ip else 0.78) >= need + 0.03 + rp and kind in ("pair", "suited_conn", "suited") \
            or (eq >= 0.48 and ip)
        if eq >= 0.60:
            adv.action = f"4-BET to {2.3 * three_to / bb:.0f}bb"
            adv.confidence = "clear"
            adv.why.append("4-bet for value and get the money in")
        elif _PREMIUM[hand] and not ip and eff <= 60 and ev > 0:
            adv.action = "ALL-IN"
            adv.confidence = "standard" if ev >= 0.5 else "close"
            adv.why.append("too strong to fold to one re-raise, and a call is hard to play out of position: "
                           "move all-in")
            adv.alt.append("CALL is the lower-variance play: continue after the flop with top pair or better")
        elif calls:
            adv.action = "CALL"
            adv.why.append("good enough to see a flop" + (" in position" if ip else " but play carefully out of position"))
        elif _PREMIUM[hand]:
            adv.action = "CALL"
            adv.confidence = "standard" if eq >= need + 0.03 else "close"
            adv.why.append("too strong to fold to one re-raise: call"
                           + (" in position" if ip else " and play carefully out of position"))
        elif keep:
            adv.action = "CALL"
            adv.why.append(ahead)
            adv.why.append("call" + (" in position" if ip else " and play carefully out of position"))
            adv.data.update(never_fold=True)
        else:
            adv.why.append("dominated too often by a 3-betting range; let it go")
    if v_type in ("nit", "tight"):
        adv.warnings.append(f"{spot.pos(villain)} is {v_type}: their 3-bet is almost always QQ+/AK")
    elif v_type in ("lag", "maniac") and adv.action == "FOLD" and eq >= 0.42:
        adv.alt.append("against this aggressive player a 4-bet shove with your best suited aces / pairs is reasonable")
    if rp >= 0.05:
        adv.why.append(f"ICM: {_pct(rp)} risk premium against {spot.pos(rp_who)}")
    return adv


# A raise and a re-raise in front: the only hands that ever move all-in there (aces and kings always, the
# others when the all-in earns).  The two players' calls are solved against a range inside these hands.
_COLD_ALLIN = parse_range("JJ+, AKs, AKo")
_COLD_ROUNDS = 120
# The first raise was an all-in and a player raised over it.  That raise isolates the all-in player and is made
# with far more hands than a re-raise over a full raise (see ``cold_vs_3bet``), so with 45bb or less other hands
# than the list above move all-in too: when the all-in earns twice the usual bar and the hand is ahead of the
# hands that raise.  Both, because the width of an isolation raise is an estimate.
_ISOLATED_BAR = 1.0
_ISOLATED_AHEAD = 0.55
# The estimate is the widest reading: every hand that plays against the all-in.  A player who raises with the
# better half of them only (the engine itself, in that seat, raises with fewer still) must not turn this
# all-in into a loss, so the hand must also hold its own against the top half of the estimate.
_ISOLATED_AHEAD_TOP = 0.50
_ISOLATED_UP_TO = 45.0
_COLD_MEMO: dict = {}             # the last spot solved on chips, see _cold_allin


def _cold_allin(spot: Spot, prizes: Prizes, bets: dict[int, float], priors: dict[int, list[float]],
                opener: int, threebettor: int):
    """Hero's all-in over a raise and a re-raise, priced: the solver's answer for every hand.

    The solver lets the players behind a caller fold, and starts from a 35% all-in range.  In this spot
    the two made a second solution that belongs to the model only.  Against 35% the first raiser's whole
    range has the price; when that player calls with all of it the re-raiser never gets to act, so the
    re-raise is dead money, and a wide all-in is then the best reply: the two keep each other up, however
    many rounds are played.  Queens showed +12.89bb for a 20bb stack on chips; any prize pressure took the
    first raiser's price away and the same hand was a fold at -0.57bb.  So here:

    * the calls are solved against the hands that ever move all-in in this spot, not against 35%;
    * with more rounds, because a handful of hands decide and 40 rounds had not settled;
    * twice, once with each of the two players answering first.  The first raiser first is the real
      order and counts their aces and kings; the re-raiser first counts that this player, with a narrow
      range and much of a short stack in, is nearly always there (asked second, they are still taken to
      fold whenever the first raiser calls);
    * and the solver as it was is kept as a third pricing: players who do not believe the all-in call
      it with more hands, and close to the money that is the lower number (against JJ+ and ace-king
      alone they fold kings there, and a 60bb all-in with ace-king showed +3bb on the bubble).

    The lowest of the three counts.  So no hand moves all-in here that folded before."""
    setup, hero = spot.setup, spot.hero
    # The solutions do not depend on hero's cards.  On chips they are kept for the next question about the
    # same spot: the sheet's builder asks all 169 hands of one.
    key = None
    if prizes.chip_ev and spot.field_prizes.chip_ev:
        key = (tuple(setup.start), setup.sb, setup.bb, tuple(setup.antes), hero, opener, threebettor,
               tuple(sorted(bets.items())), tuple((j, tuple(priors[j])) for j in sorted(priors)),
               tuple(spot.types), tuple(spot.away))
    solved = _COLD_MEMO.get(key)
    if solved is None:
        solved = []
        for order, inside, rounds in (([opener, threebettor], _COLD_ALLIN, _COLD_ROUNDS),
                                      ([threebettor, opener], _COLD_ALLIN, _COLD_ROUNDS),
                                      ([opener, threebettor], None, 40)):          # the last: as it was
            v_fold, v_steal, callers = build_shove_spot(
                setup, hero, prizes, caller_prizes=spot.field_prizes, types=spot.types, away=spot.away,
                bets=bets, priors=priors, caller_order=order, fold_winner=threebettor)
            solved.append(solve_shove(v_fold, v_steal, callers, shover_prior=inside, iters=rounds,
                                      unit=_unit(prizes, setup, hero)))
        if key is not None:
            _COLD_MEMO.clear()
            _COLD_MEMO[key] = solved
    return min(solved, key=lambda sol: sol.ev[spot.hand])


def cold_vs_3bet(spot: Spot, opener: int, raise_to: float, threebettor: int, three_to: float) -> Advice:
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    bb = spot.bb
    eff = min(live[hero], max(live[opener], live[threebettor])) / bb
    rng = threebet_range(spot.nb(opener), spot.types[threebettor], setup.n)
    open_rng = _opened(spot, opener)
    over_allin = raise_to >= live[opener] - 1e-9
    if over_allin:
        # The first raise was an all-in.  The player who raised over it holds the hands that play against that
        # all-in, not a re-raise over a full opening raise: the same reading as for a caller with chips (three
        # quarters of the solved calling range, at most half of all hands).  The all-in player holds his own
        # all-in range.
        pushed = _shover_solution(spot, opener, None, 0.0, None)
        over = pushed.caller(threebettor)
        if over and range_combos(over.call_range) > 0:
            width = min(_CALLER_WIDEST, _CALLER_SHARE * range_pct(over.call_range))
            rng = top_percent(max(width, range_pct(rng)), list(allin_order()))
        open_rng = _scaled_range(pushed, spot.types[opener], spot.bbs(live[opener]))[0]
    eq = eq_vs_range(hand, rng)[0]
    sit = _situation(spot, f"{spot.who(opener)} raised and {spot.who(threebettor)} 3-bet to {three_to / bb:.1f}bb")
    adv = Advice("FOLD", "standard", sit)
    adv.numbers.append(f"3-bettor's range ~{range_pct(rng):.1f}% [{format_range(rng)}]; your equity {_pct(eq)}")
    prizes = Prizes() if spot.desperate else spot.prizes
    strong = _COLD_ALLIN
    sol = _cold_allin(spot, prizes, {opener: raise_to, threebettor: three_to}, {opener: open_rng, threebettor: rng},
                      opener, threebettor)
    ev = sol.ev_bb(hand)
    adv.numbers.append(f"shove EV {ev:+.2f}bb vs folding; both fold {_pct(sol.fold_equity[hand])}; "
                       f"when called you have {_pct(sol.eq_called[hand])}")
    # The wide reading of a raise over an all-in is for a player with no read.  One tagged nit or tight raises
    # there with far fewer hands (the range above does not move with the tag), so against that player only the
    # list plays: eights are 56% against the estimate and 33% against TT+, AQs+ and AKo.
    tight_raiser = spot.types[threebettor] in ("nit", "tight")
    priced = over_allin and strong[hand] < 0.5 and eff <= _ISOLATED_UP_TO and ev > _ISOLATED_BAR
    eq_top = eq_vs_range(hand, top_percent(range_pct(rng) / 2, list(allin_order())))[0] if priced else 0.0
    ahead = priced and eq >= _ISOLATED_AHEAD and eq_top >= _ISOLATED_AHEAD_TOP
    if _TRAP[hand] or (strong[hand] >= 0.5 and ev > 0.5):
        adv.action = "ALL-IN" if eff <= 60 else f"4-BET to {2.3 * three_to / bb:.0f}bb"
        adv.confidence = "clear" if _TRAP[hand] else _conf(ev - 0.5, 2.0, 0.6)
        adv.why.append("a raise and a re-raise in front: only premiums continue, and they play for stacks")
    elif ahead and not tight_raiser:
        adv.action = "ALL-IN"
        adv.confidence = _conf(ev - _ISOLATED_BAR, 2.0, 0.6)
        adv.why.append(f"{spot.who(opener)} is all-in for {raise_to / bb:.1f}bb and {spot.who(threebettor)} raised "
                       "over it: that raise is made with far more hands than a re-raise over a full raise, "
                       "and against them the all-in earns")
        adv.data.update(allin_bar_bb=_ISOLATED_BAR)          # the bar: what "close" is measured against
    elif ahead and tight_raiser:
        adv.why.append(f"{spot.pos(threebettor)} is {spot.types[threebettor]}: from this player a raise over an all-in "
                       "is a strong hand, not the wide raise it usually is, so only JJ+ and ace-king move in")
        # ... and the range line says whose range it is (the fold was not made from it)
        adv.numbers[0] = (f"a raise over an all-in from a player with no read: ~{range_pct(rng):.1f}% "
                          f"[{format_range(rng)}], and you have {_pct(eq)} against that; "
                          f"{spot.pos(threebettor)} raises with fewer hands")
    elif priced:
        # the number alone would move in: say why the fold stands beside it
        adv.why.append(
            f"the all-in's number is positive because of the chips already in the pot, but this hand has only "
            f"{_pct(eq)} against the hands that raise over an all-in: not enough to move in over the raise"
            if eq < _ISOLATED_AHEAD else
            f"the all-in's number counts every hand that might raise over an all-in; against the better half of "
            f"them this hand has only {_pct(eq_top)}: not enough to move in over the raise")
    else:
        adv.confidence = "clear" if strong[hand] < 0.5 else _conf(ev - 0.5, 2.0, 0.6)
        adv.why.append("a raise and a re-raise in front: fold everything except the very top of your range")
        if strong[hand] >= 0.5:
            adv.alt.append("against two loose / aggressive players this hand is a shove")
    return adv


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------

def advise(spot: Spot) -> Advice:
    setup, hero = spot.setup, spot.hero
    live = setup.live
    bet_level = spot.bb
    raises: list[Act] = []
    limpers: list[int] = []
    flats: list[int] = []
    allin_callers: list[int] = []
    hero_raise = 0.0
    for a in spot.acts:
        is_allin = a.kind == "allin" or a.amount >= live[a.idx] - 1e-9
        if a.kind in ("raise", "allin") and a.amount > bet_level + 1e-9:
            raises.append(Act(a.idx, "allin" if is_allin else "raise", a.amount))
            bet_level = a.amount
            flats = []
            if a.idx == hero:
                hero_raise = a.amount
        elif a.kind in ("limp", "call", "allin"):
            if raises:
                # a player who calls an all-in and still has chips is a caller, not a second all-in
                (allin_callers if raises[-1].kind == "allin" and is_allin else flats).append(a.idx)
            else:
                limpers.append(a.idx)

    notes = list(spot.notes)
    hero_seen = False
    for a in spot.acts:
        if a.idx == hero:
            hero_seen = True
        elif a.idx > hero and not hero_seen and a.kind != "fold":
            notes.append(f"{spot.pos(a.idx)} acts after you preflop but is listed as acting before you: "
                         "check the button position and seats")
            break

    def done(adv: Advice) -> Advice:
        adv.warnings += notes
        return adv

    if not raises:
        return done(vs_limp(spot, limpers) if limpers else first_in(spot))

    allins = [r for r in raises if r.kind == "allin"]
    if allin_callers or len(allins) >= 2:
        involved = [r.idx for r in allins] + allin_callers
        return done(multi_allin(spot, [j for j in involved if j != hero]))

    if not hero_raise:
        if len(raises) == 1:
            r = raises[0]
            if r.kind == "allin":
                return done(vs_shove(spot, r.idx, callers=flats))
            return done(vs_open(spot, r.idx, r.amount, flats))
        # Two players who have both put in hero's whole stack or their own: for hero these are two all-ins.
        # (The solver prices one opponent at a time: with the first of them all-in it took the second to fold,
        # and an all-in read +40bb for a 15bb stack.)
        in_for_good = [r.idx for r in raises if r.amount >= min(live[hero], live[r.idx]) - 1e-9]
        if len(in_for_good) >= 2:
            return done(multi_allin(spot, in_for_good))
        if len(raises) == 2:
            a, b = raises
            if b.kind == "allin":
                return done(vs_shove(spot, b.idx, raiser=a.idx, raise_to=a.amount, callers=flats))
            return done(cold_vs_3bet(spot, a.idx, a.amount, b.idx, b.amount))
        last = raises[-1]
        adv = cold_vs_3bet(spot, raises[0].idx, raises[0].amount, last.idx, last.amount)
        adv.warnings.append("several raises in front: only AA/KK are comfortable here")
        return done(adv)

    hero_last = max(i for i, x in enumerate(raises) if x.idx == hero)
    later = [r for r in raises if r.idx != hero and raises.index(r) > hero_last]
    # hero's raise was a re-raise when another player had raised before it
    before = [x.idx for x in raises[:hero_last] if x.idx != hero]
    reraised = before[-1] if before else None
    if len(later) == 1:
        r = later[0]
        if r.kind == "allin":
            return done(vs_shove(spot, r.idx, hero_open=hero_raise, callers=flats, reraised=reraised))
        return done(vs_3bet(spot, r.idx, r.amount, hero_raise, reraised=reraised, alone=not flats))
    if not later:
        adv = Advice("WAIT", "standard", "you raised and nobody has re-raised yet")
        return done(adv)
    if later[0].kind != "allin":
        # a re-raise and another raise over it (the all-in of the two is the last one: two all-ins went
        # to ``multi_allin`` above)
        adv = vs_reraise_and_raise(spot, later[0], later[-1], hero_raise)
        if len(later) > 2:
            adv.warnings.append("more than two players raised behind you: continue only with AA/KK")
        return done(adv)
    # a short all-in and a raise over it: that raise is priced as a re-raise of hero's
    adv = vs_3bet(spot, later[-1].idx, later[-1].amount, hero_raise, alone=False)
    adv.warnings.append("more than one player re-raised: continue only with AA/KK")
    return done(adv)


# --------------------------------------------------------------------------
# Building a spot from text
# --------------------------------------------------------------------------

_POS_NB = _POSITION_ALIASES

_VERBS = {
    "fold": "fold", "folds": "fold", "f": "fold",
    "limp": "limp", "limps": "limp", "complete": "limp", "completes": "limp",
    "call": "call", "calls": "call", "flat": "call", "flats": "call", "c": "call",
    "raise": "raise", "raises": "raise", "open": "raise", "opens": "raise", "bet": "raise",
    "bets": "raise", "r": "raise", "3bet": "raise", "3-bet": "raise", "3bets": "raise",
    "reraise": "raise", "reraises": "raise", "4bet": "raise", "4-bet": "raise", "minraise": "raise",
    "min-raise": "raise", "minraises": "raise",
    "allin": "allin", "all-in": "allin", "shove": "allin", "shoves": "allin", "jam": "allin",
    "jams": "allin", "push": "allin", "pushes": "allin", "ai": "allin",
}


def pos_to_index(name: str, n: int) -> int | None:
    """Index in the preflop acting order (0 = first to act) of a seat name at a table of ``n``.

    Every name ``ranges.position_name`` prints comes back as its own seat.  The
    other spellings (button, cutoff, MP, EP ...) are read by players behind.
    """
    low = name.strip().lower()
    # older output wrote "UTG(LJ)" at short tables; heads-up the button is "BTN/SB"
    if "(" in low:
        low = low.split("(", 1)[0].strip()
    if "/" in low:
        for part in low.split("/"):
            idx = pos_to_index(part, n)
            if idx is not None:
                return idx
        return None
    labels = [position_name(n - 1 - i, n).lower() for i in range(n)]
    if low in labels:
        return labels.index(low)
    if low in ("utg", "ep", "ep1", "utg+0"):
        return 0
    if low in ("utg+1", "utg1", "utg+2", "utg2"):
        # no such seat at this table size: count from the first to act, but stay before the button
        return max(0, min(int(low[-1]), n - 4))
    if low in _POS_NB:
        nb = _POS_NB[low]
        if n == 2 and low in ("btn", "bu", "button", "d", "dealer", "sb"):
            return 0
        if nb > n - 1:
            return 0
        return n - 1 - nb
    return None


def parse_amount(text: str, bb: float, default_chips: bool) -> float:
    t = text.strip().lower().replace(",", "")
    if t.endswith("bb"):
        return float(t[:-2]) * bb
    if t.endswith("x"):
        return float(t[:-1]) * bb
    mult = 1.0
    if t.endswith("k"):
        mult, t = 1e3, t[:-1]
    elif t.endswith("m"):
        mult, t = 1e6, t[:-1]
    val = float(t) * mult
    return val if default_chips else val * bb


def parse_actions(text: str, setup: HandSetup, hero: int, resolve, chips: bool) -> list[Act]:
    """Parse ``"UTG raise 2.2bb, CO call, SB allin"`` into actions.

    ``resolve(name)`` maps a player reference (position, seat, name) to an
    index in action order.  Bare numbers are chips when ``chips`` is true and
    big blinds otherwise.
    """
    acts: list[Act] = []
    if not text or not text.strip():
        return acts
    bet_level = setup.bb
    n_raises = 0
    import re

    for part in re.split(r"[,;]+|\bthen\b", text):
        words = part.strip().split()
        if not words:
            continue
        verb_i = next((i for i, w in enumerate(words) if w.lower() in _VERBS), None)
        if verb_i is None:
            raise ValueError(f"no action word in {part.strip()!r} (use raise/call/limp/allin/fold)")
        who_txt = " ".join(words[:verb_i]) or "hero"
        idx = hero if who_txt.lower() in ("hero", "i", "me") else resolve(who_txt)
        if idx is None:
            raise ValueError(f"cannot tell who {who_txt!r} is")
        kind = _VERBS[words[verb_i].lower()]
        rest = [w for w in words[verb_i + 1:] if w.lower() not in ("to", "for", "all-in", "allin")]
        said_allin = any(w.lower() in ("all-in", "allin") for w in words[verb_i + 1:])
        amount = None
        for w in rest:
            try:
                amount = parse_amount(w, setup.bb, chips)
                break
            except ValueError:
                continue
        live = setup.live[idx]
        if kind == "fold":
            continue
        if said_allin and kind == "raise":
            kind = "allin"
        if kind == "limp":
            amount = min(live, setup.bb)
        elif kind == "call":
            amount = min(live, bet_level)
        elif kind == "allin":
            amount = live
        else:
            if amount is None:
                amount = (2.2 * setup.bb) if n_raises == 0 else 3.0 * bet_level
            amount = min(live, amount)
        if kind in ("raise", "allin") and amount > bet_level:
            bet_level = amount
            n_raises += 1
        acts.append(Act(idx, kind, amount))
    return acts


def quick_spot(hand: int, cards, stack_bb: float, players: int, pos: str, facing: str = "",
               villain_bb: float | None = None, prizes: Prizes | None = None,
               ante: bool = True, stage: dict | None = None, stacks: list[float] | None = None) -> Spot:
    """A spot without table state: everyone has ``villain_bb`` (default hero's stack), or each player the
    stack of ``stacks`` (big blinds, in the order players act before the flop: at three players the button,
    the small blind, the big blind)."""
    n = max(2, players)
    hero = pos_to_index(pos, n)
    if hero is None:
        raise ValueError(f"unknown position {pos!r}")
    if stacks is not None:
        if len(stacks) != n or any(s <= 0 for s in stacks):
            raise ValueError(f"stacks: one positive stack for each of the {n} players")
        stacks = [float(s) for s in stacks]
    else:
        other = villain_bb if villain_bb else stack_bb
        stacks = [other] * n
        stacks[hero] = stack_bb
    setup = HandSetup(stacks, 0.5, 1.0, 0.0, 1.0 if ante else 0.0)
    spot = Spot(setup=setup, hero=hero, hand=hand, cards=cards, prizes=prizes or Prizes(),
                field_prizes=prizes or Prizes(), stage=stage or {})
    spot.acts = parse_actions(facing, setup, hero, lambda name: pos_to_index(name, n), chips=False)
    return spot


def _unused(*_a) -> None:  # keep optional imports referenced for linters
    return None


_unused(hand_equity)
