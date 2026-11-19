"""Preflop decisions for a tight-aggressive tournament player.

``advise(spot)`` looks at what happened before hero acts and routes to one of
the handlers below.  Short stacks and all-in spots are decided by the
equilibrium solver with ICM; deeper spots use the TAG charts, moved by stack
depth, ICM pressure and reads on the players involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cards import HANDS, format_range, parse_range, range_combos, range_pct, top_percent
from .equity import allin_order, eq_vs_range, hand_equity, preflop_equity
from .icm import Prizes
from .pushfold import (HandSetup, _call_req, build_shove_spot, solve_open_shove, solve_reshove,
                       solve_shove, _unit)
from .ranges import (PLAYER_TYPES, norm_type, open_size_bb, opener_category, position_name,
                     rfi_range, scale_range, threebet_range, villain_limp_range,
                     villain_open_range, vs_open_chart, _ladder, _POSITION_ALIASES)

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

    def __post_init__(self) -> None:
        n = self.setup.n
        if not self.names:
            self.names = [position_name(n - 1 - i, n) for i in range(n)]
        if not self.types:
            self.types = ["unknown"] * n
        if not self.away:
            self.away = [False] * n
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


def _reshove_plan(spot: Spot, open_to: float, hero_range: list[float]) -> list[str]:
    """What to do if a player behind moves all-in over hero's open."""
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
        verdict = "CALL" if res["edge"] >= 0 else "FOLD"
        out.append(f"if {spot.pos(j)} ({spot.bbs(setup.live[j]):.0f}bb) shoves: {verdict} "
                   f"(need {_pct(res['need'])}, have {_pct(res['eq'])} vs ~{res['pct']:.0f}% range)")
    return out


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
        adv.numbers.append(f"everyone folds {_pct(fe)}; when called you have {_pct(sol.eq_called[hand])}")
        tight_callers = [c for c in sol.callers if range_pct(c.call_range) > 0]
        if tight_callers:
            parts = [f"{spot.pos(c.idx)} {range_pct(c.call_range):.0f}%" for c in tight_callers[-3:]]
            adv.numbers.append("expected calling ranges: " + ", ".join(parts))
        if not prizes.chip_ev:
            chip = solve_open_shove(setup, hero, Prizes(), types=spot.types, away=spot.away, iters=30)
            adv.numbers.append(f"for reference, pure chip EV: {chip.ev_bb(hand):+.2f}bb "
                               f"(chip-EV range {range_pct(chip.shove_range):.0f}%)")
        adv.data.update(shove_ev_bb=ev, shove_pct=pct)

    pf_zone = 10.0
    mix_zone = 20.0 if (is_sb or heads_up) else 16.0
    if sol is not None and eff <= pf_zone:
        ev = sol.ev_bb(hand)
        if ev > 0.0:
            adv.action = "ALL-IN"
            adv.why.append(f"{eff:.0f}bb effective is push-or-fold territory and this shove makes money")
        else:
            adv.why.append(f"{eff:.0f}bb effective is push-or-fold territory and this hand loses as a shove")
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
        else:
            adv.confidence = _conf(ev, 0.35, 0.10)
            adv.why.append("not a profitable shove here, and raise-folding 2bb would burn too much of this stack")
        return _finish_first_in(spot, adv, behind)

    # raise / fold with real stacks
    own_nb = spot.nb(hero)

    def open_row(sh: int) -> list[float]:
        """The opening row for the active players behind, never tighter than this seat's own row."""
        # the small blind's row is tighter than the button's because it plays out of position:
        # it is for the small blind only, not for a later seat with one active player behind
        row = rfi_range(nb_eff if nb_eff != 1 or own_nb == 1 else 2, eff, sh)
        if nb_eff < own_nb:
            own = rfi_range(own_nb, eff, sh)
            if range_pct(own) > range_pct(row):
                row = own
        return row

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
        adv.why.append(f"inside the TAG opening range for {spot.pos(hero)} with {nb_eff} players behind")
        if eff <= 40:
            adv.numbers += _reshove_plan(spot, size * spot.bb, rfi)
    elif sol is not None and sol.ev_bb(hand) > 0.25 and _SHOVE_SHAPED[hand] and eff <= 20:
        adv.action = "ALL-IN"
        adv.confidence = "close"
        adv.why.append("outside the raise-fold range, but the shove itself is profitable at this depth")
    else:
        if wider[hand] >= 0.5:
            adv.confidence = "close"
            adv.alt.append("a raise is fine if the players behind are tight or sitting out")
        adv.why.append(f"outside the TAG opening range for {spot.pos(hero)} with {nb_eff} players behind")
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
    else:
        adv.action = free
        adv.why.append("not strong enough to raise, not suited to limping along")
    adv.why += notes
    return adv


def _pairs() -> set[int]:
    return {i * 14 for i in range(13)}


def _suited(hand: int) -> bool:
    row, col = divmod(hand, 13)
    return row < col


# --------------------------------------------------------------------------
# Facing an all-in
# --------------------------------------------------------------------------

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


def _scaled_range(sol, ptype: str) -> tuple[list[float], float]:
    base = range_pct(sol.shove_range)
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


def _allin_over_reraise(spot: Spot, shover: int, first_raiser: int | None) -> tuple[list[float], float]:
    """Range of a player who moves all-in over hero's re-raise: (weights, percent of hands).

    When he is the player hero re-raised (``first_raiser``) it is his opening range narrowed
    to the hands that play for stacks; a re-shove solved over hero's opening range would be
    several times too wide."""
    eff = min(spot.setup.live[spot.hero], spot.setup.live[shover]) / spot.bb
    line = _ALLIN_OVER_RERAISE_LINE[spot.types[shover]] + (1 if eff < 25 else 0)
    rng = parse_range(_ALLIN_OVER_RERAISE[min(line, len(_ALLIN_OVER_RERAISE) - 1)])
    if first_raiser is not None and first_raiser == shover:
        opened = villain_open_range(spot.nb(shover), spot.types[shover])
        narrowed = [min(a, b) for a, b in zip(rng, opened)]
        if range_combos(narrowed) > 0:
            rng = narrowed
    return rng, range_pct(rng)


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
        priors[raiser] = villain_open_range(spot.nb(raiser), spot.types[raiser])
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
        hero_range = rfi_range(max(1, spot.nb(hero)), min(live[hero], live[shover]) / spot.bb)
        sol = _shover_solution(spot, shover, hero, hero_open, hero_range)
        sit = _situation(spot, f"you opened, {spot.who(shover)} moved all-in for {shove_bb:.1f}bb")
    elif raiser is not None:
        orange = villain_open_range(spot.nb(raiser), spot.types[raiser])
        sol = _shover_solution(spot, shover, raiser, raise_to, orange)
        sit = _situation(spot, f"{spot.who(raiser)} raised, {spot.who(shover)} moved all-in for {shove_bb:.1f}bb")
    else:
        sol = _shover_solution(spot, shover, None, 0.0, None)
        sit = _situation(spot, f"{spot.who(shover)} moved all-in for {shove_bb:.1f}bb")
    if sol is not None:
        rng, pct = _scaled_range(sol, spot.types[shover])
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
    raise_edge = eq - need - margin                 # for an answer that puts the short stack all-in
    # A committed raiser with other players live: the answer may be a plain call of the raise.
    # That call is priced as what hero adds now against the pot as it stands; the raiser's last
    # chips go in after the flop, when hero can still fold, so they count for half.
    rest = 0.0
    if committed and others_live and live[shover] > level + 1e-9:
        now = setup.invested({**bets, shover: level, **{j: min(live[j], level) for j in callers}})
        to_call = max(0.0, min(live[hero], level) - now[hero])
        plain = to_call / (sum(setup.antes) + sum(now) + to_call)
        if plain < chip_need:
            rest = (chip_need - plain) / 2
            need, chip_need = need - (chip_need - plain), plain
    edge = eq - need - margin - rest

    adv = Advice("CALL" if edge >= 0 else "FOLD", _conf(edge, 0.05, 0.02), sit)
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
    if stack_bb <= _ISOLATE_ALLIN_BB or live[hero] <= _ISOLATE_ALLIN_X * live[shover]:
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
    # deeper: about 2.5 times the all-in, never under the smallest legal raise, in half big blinds
    before = max(raise_to, hero_open, bb)
    smallest = level + max(bb, level - before)
    size_bb = max(_ISOLATE_SIZE_X * short_bb, spot.bbs(smallest))
    size_bb = int(size_bb * 2 + 0.999) / 2.0
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
    r1, pct1 = _scaled_range(sol, spot.types[first])
    ranges = [r1]
    for j in allins[1:]:
        c = sol.caller(j)
        rj = c.call_range if c and range_combos(c.call_range) > 0 else parse_range("TT+, AQs+, AKo")
        ranges.append(rj)
    eq = preflop_equity(hand, spot.cards, ranges, iters=12000)
    call_amt = min(live[hero], max(live[j] for j in allins)) - setup.invested()[hero]
    pot = sum(setup.antes) + sum(setup.blinds) + sum(min(live[j], max(live[k] for k in allins)) for j in allins)
    need_chip = call_amt / (pot + call_amt)
    big = max(allins, key=lambda k: live[k])
    rp = 0.0 if spot.prizes.chip_ev or spot.desperate else spot.prizes.risk_premium(live, hero, big)
    # with two players already all-in, folding often means a free pay jump
    need = need_chip + rp * 1.2 + (0.03 if rp > 0 else 0.02)
    edge = eq - need
    names = " and ".join(spot.who(j) for j in allins)
    adv = Advice("CALL" if edge >= 0 else "FOLD", _conf(edge, 0.06, 0.025),
                 _situation(spot, f"{names} are all-in"))
    adv.numbers.append(f"equity vs both ranges {_pct(eq)}; need about {_pct(need)} "
                       f"(pot odds {_pct(need_chip)}, ICM/safety +{100 * (need - need_chip):.0f} pts)")
    adv.numbers.append(f"first shover ~{pct1:.0f}%, the caller much tighter [{format_range(ranges[-1])}]")
    adv.why.append("against two all-in ranges you need a hand that is ahead of calling ranges, "
                   "usually QQ+ / AK" if edge < 0 else "strong enough even against two ranges")
    adv.warnings.append("multi-way all-in: side pots are approximated")
    return adv


# --------------------------------------------------------------------------
# Facing an open raise
# --------------------------------------------------------------------------

# share of its equity a hand realises out of position (tools/build_tag.py reads it for the sheet)
_REALIZE = {"pair": 0.92, "suited_conn": 0.95, "suited": 0.86, "broadway_off": 0.80, "off": 0.64}

# Big blind closing the action against one raise: how far above the pot odds a hand's equity must
# be to call, by how badly that kind of hand plays after the flop (pairs least, then suited hands,
# then two offsuit cards ten or higher, then the other offsuit hands).  Half of the ICM risk
# premium comes on top.  It is one test for every hand, charted or not, so a stronger hand never
# folds where a weaker one calls; and no hand needs more than _BB_CALL_NET above the price.
# Every suited hand gets the same points: with fewer for the connected ones 32s would call
# where T2s folds.
_BB_CALL_MARGIN = {"pair": 0.02, "suited_conn": 0.06, "suited": 0.06, "broadway_off": 0.08, "off": 0.15}
_BB_CALL_NET = 0.15


def bb_call_points(kind: str, risk_premium: float = 0.0, callers: int = 0) -> float:
    """Equity the big blind needs above the pot odds to call one raise with a hand of this kind."""
    points = _BB_CALL_MARGIN[kind] + max(0.0, risk_premium) / 2
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
    open_rng = villain_open_range(o_nb, o_type, eff)
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
    bb_points = bb_call_points(kind, rp, len(flats))
    bb_edge = eq_open - need - bb_points if h_nb == 0 else -1.0
    if h_nb == 0:
        adv.numbers.append(f"big blind closing the action: to call you need {_pct(need + bb_points)} "
                           f"(the price plus {100 * bb_points:.0f} pts for how this hand plays after the flop"
                           + (", ICM included" if rp >= 0.01 and bb_points < _BB_CALL_NET else "") + ")")
        adv.data.update(bb_call_need=need + bb_points, bb_call_edge=bb_edge)

    if eff <= 25:
        flat_rngs = {j: [max(a, b) for a, b in zip(vs_open_chart(o_nb, spot.nb(j))["call"],
                                                    vs_open_chart(o_nb, spot.nb(j))["setmine"])]
                     for j in flats}
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
        if ev > 0.15:
            adv.action = jam_word
            adv.confidence = _conf(ev - 0.15, 0.6, 0.15)
            adv.why.append("re-shoving wins the pot often enough, and you have real equity when called")
            if _TRAP[hand] and eff >= 15:
                adv.alt.append("with a monster, a small 3-bet or a flat to trap is fine if players behind are aggressive")
        elif bb_edge >= 0 and to_call <= 0.12 * live[hero]:
            adv.action = "CALL"
            adv.confidence = "close"
            adv.why.append("not a profitable shove, but the big blind is getting the right price to see a flop")
            adv.warnings.append("play fit-or-fold after the flop: continue with top pair or better, or a strong draw")
        else:
            adv.confidence = _conf(ev - 0.15, 0.6, 0.15)
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
                if calls:
                    adv.why.append("do not fold to a 4-bet at this depth")
                elif _PREMIUM[hand]:
                    adv.alt.append("facing a small 4-bet: continue; an all-in for this much is a fold")
                else:
                    adv.alt.append("facing a 4-bet: continue with QQ+/AK, fold the rest")
                decided = True
            else:
                prizes = Prizes() if spot.desperate else spot.prizes
                flat_rngs = {j: [max(a, b) for a, b in zip(vs_open_chart(o_nb, spot.nb(j))["call"],
                                                            vs_open_chart(o_nb, spot.nb(j))["setmine"])]
                             for j in flats}
                sol = solve_reshove(setup, hero, opener, raise_to, prizes, opener_range=open_rng,
                                    flat_callers=flat_rngs, caller_prizes=spot.field_prizes,
                                    types=spot.types, away=spot.away)
                ev = sol.ev_bb(hand)
                can_call = h_nb == 0 or ip or max(call) >= 0.5
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
                    adv.data.update(reshove_ev_bb=ev)
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
    elif demoted and not (h_nb == 0 or ip or max(call) >= 0.5):
        adv.why.append("not strong enough to re-raise and call an all-in at this depth, and from the small "
                       "blind a call is worse than a fold")
    elif demoted or call[hand] >= 0.5 or (setmine[hand] >= 0.5 and odds_ok) or \
            (deep[hand] >= 0.5 and eff >= 50 and (h_nb <= 2 or flats)):
        # the big blind's charted hands pass the same price test as every other hand of his;
        # the small blind, out of position with players behind, drops the thin calls under ICM
        price_bad = h_nb == 0 and bb_edge < 0
        thin_oop = icm_tight and h_nb == 1 and kind in ("off", "broadway_off", "suited")
        if price_bad or thin_oop:
            adv.why.append("in the chart to defend, but the price / ICM makes it a fold here" if not demoted else
                           "not a re-raise at this depth (it could not call an all-in after it), and with this "
                           "much ICM pressure not a call out of position either")
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
        adv.confidence = "close"
        adv.why.append("closing the action in the big blind at a good price")
        adv.warnings.append("play fit-or-fold after the flop")
    else:
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

def vs_3bet(spot: Spot, villain: int, three_to: float, hero_open: float,
            reraised: int | None = None) -> Advice:
    """Hero raised and ``villain`` re-raised, not all-in.  ``reraised``: hero's raise was itself
    a re-raise, over the raise of that player."""
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
    rng = threebet_range(max(1, spot.nb(hero)), v_type)
    eq = eq_vs_range(hand, rng)[0]
    inv = setup.invested({hero: hero_open, villain: three_to})
    pot = sum(setup.antes) + sum(inv)
    to_call = three_to - hero_open
    need = to_call / (pot + to_call)
    villain_in_blinds = spot.nb(villain) <= 1
    ip = villain_in_blinds
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

    if eff <= 45:
        if ev > 0.5 and (eq >= 0.45 or _PREMIUM[hand]):
            adv.action = "ALL-IN"
            adv.confidence = "clear" if _PREMIUM[hand] and eq >= 0.5 else "standard"
            adv.why.append("at this depth a 4-bet is a shove, and this hand profits from it")
        else:
            adv.why.append("not strong enough to play for stacks against a 3-betting range")
            adv.confidence = _conf(ev - 0.5, 1.0, 0.3)
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
        else:
            adv.why.append("dominated too often by a 3-betting range; let it go")
    if v_type in ("nit", "tight"):
        adv.warnings.append(f"{spot.pos(villain)} is {v_type}: their 3-bet is almost always QQ+/AK")
    elif v_type in ("lag", "maniac") and adv.action == "FOLD" and eq >= 0.42:
        adv.alt.append("against this aggressive player a 4-bet shove with your best suited aces / pairs is reasonable")
    if rp >= 0.05:
        adv.why.append(f"ICM: {_pct(rp)} risk premium against {spot.pos(rp_who)}")
    return adv


def cold_vs_3bet(spot: Spot, opener: int, raise_to: float, threebettor: int, three_to: float) -> Advice:
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    bb = spot.bb
    eff = min(live[hero], max(live[opener], live[threebettor])) / bb
    rng = threebet_range(spot.nb(opener), spot.types[threebettor])
    open_rng = villain_open_range(spot.nb(opener), spot.types[opener])
    eq = eq_vs_range(hand, rng)[0]
    sit = _situation(spot, f"{spot.who(opener)} raised and {spot.who(threebettor)} 3-bet to {three_to / bb:.1f}bb")
    adv = Advice("FOLD", "standard", sit)
    adv.numbers.append(f"3-bettor's range ~{range_pct(rng):.1f}% [{format_range(rng)}]; your equity {_pct(eq)}")
    prizes = Prizes() if spot.desperate else spot.prizes
    v_fold, v_steal, callers = build_shove_spot(
        setup, hero, prizes, caller_prizes=spot.field_prizes, types=spot.types, away=spot.away,
        bets={opener: raise_to, threebettor: three_to}, priors={opener: open_rng, threebettor: rng},
        caller_order=[opener, threebettor], fold_winner=threebettor)
    sol = solve_shove(v_fold, v_steal, callers, unit=_unit(prizes, setup, hero))
    ev = sol.ev_bb(hand)
    adv.numbers.append(f"shove EV {ev:+.2f}bb vs folding; both fold {_pct(sol.fold_equity[hand])}; "
                       f"when called you have {_pct(sol.eq_called[hand])}")
    strong = parse_range("JJ+, AKs, AKo")
    if _TRAP[hand] or (strong[hand] >= 0.5 and ev > 0.5):
        adv.action = "ALL-IN" if eff <= 60 else f"4-BET to {2.3 * three_to / bb:.0f}bb"
        adv.confidence = "clear" if _TRAP[hand] else _conf(ev - 0.5, 2.0, 0.6)
        adv.why.append("a raise and a re-raise in front: only premiums continue, and they play for stacks")
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
        return done(vs_3bet(spot, r.idx, r.amount, hero_raise, reraised=reraised))
    if not later:
        adv = Advice("WAIT", "standard", "you raised and nobody has re-raised yet")
        return done(adv)
    adv = vs_3bet(spot, later[-1].idx, later[-1].amount, hero_raise)
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
               ante: bool = True, stage: dict | None = None) -> Spot:
    """A spot without table state: everyone has ``villain_bb`` (default hero's stack)."""
    n = max(2, players)
    hero = pos_to_index(pos, n)
    if hero is None:
        raise ValueError(f"unknown position {pos!r}")
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
