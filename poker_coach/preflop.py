"""Preflop decisions for a tight-aggressive tournament player.

``advise(spot)`` looks at what happened before hero acts and routes to one of
the handlers below.  Short stacks and all-in spots are decided by the
equilibrium solver with ICM; deeper spots use the TAG charts, moved by stack
depth, ICM pressure and reads on the players involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cards import HANDS, format_range, parse_range, range_combos, range_pct
from .equity import eq_vs_range, hand_equity, preflop_equity
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
    rfi = rfi_range(nb_eff, eff, shift) if not heads_up else list(_ladder(-1))
    wider = rfi_range(nb_eff, eff, shift - 1) if not heads_up else rfi
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
        adv.confidence = "clear" if rfi_range(nb_eff, eff, shift + 2)[hand] >= 0.5 else "standard"
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


def _call_vs_reshove(spot: Spot, shover: int, open_to: float, hero_range: list[float]) -> dict:
    sol = _shover_solution(spot, shover, spot.hero, open_to, hero_range)
    rng, pct = _scaled_range(sol, spot.types[shover])
    eq = eq_vs_range(spot.hand, rng)[0]
    need, chip = _call_numbers(spot, shover, {spot.hero: open_to, shover: spot.setup.live[shover]})
    return {"eq": eq, "need": need, "chip_need": chip, "edge": eq - need, "pct": pct, "range": rng,
            "sol": sol}


def vs_shove(spot: Spot, shover: int, *, raiser: int | None = None, raise_to: float = 0.0,
             hero_open: float = 0.0, callers: list[int] | None = None) -> Advice:
    """Hero faces one all-in.

    ``raiser`` is another player who raised before the shove and is still in;
    ``hero_open`` is hero's own raise if the shove came over the top of it.
    """
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    n = setup.n
    callers = callers or []
    shove_bb = spot.bbs(live[shover])
    if hero_open:
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
    rng, pct = _scaled_range(sol, spot.types[shover])

    bets = {shover: live[shover]}
    if hero_open:
        bets[hero] = hero_open
    if raiser is not None:
        bets[raiser] = raise_to
    need, chip_need = _call_numbers(spot, shover, bets)
    fresh_behind = [j for j in range(hero + 1, n)
                    if j not in (shover, raiser) and not spot.away[j] and live[j] > 0] if not hero_open else []
    margin = 0.008 * len(fresh_behind) + (0.03 if raiser is not None else 0.0)
    eq = eq_vs_range(hand, rng)[0]
    edge = eq - need - margin

    adv = Advice("CALL" if edge >= 0 else "FOLD", _conf(edge, 0.05, 0.02), sit)
    adv.numbers.append(f"their range ~{pct:.0f}% [{format_range(rng)}]")
    adv.numbers.append(f"your equity {_pct(eq)}; you need {_pct(need + margin)} "
                       f"(pot odds alone {_pct(chip_need)}"
                       + (f", ICM adds {100 * (need - chip_need):+.0f} pts" if abs(need - chip_need) >= 0.005 else "")
                       + (f", players still to act add {100 * margin:.0f} pts" if margin >= 0.005 else "") + ")")
    # how wide must the shove be for a call to break even?
    be = None
    for p in (2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 26, 30, 35, 40, 50, 60, 75, 100):
        if eq_vs_range(hand, scale_range(sol.ev, p))[0] >= need + margin:
            be = p
            break
    if be is None:
        adv.numbers.append("no realistic shoving range makes this a call")
    else:
        adv.numbers.append(f"calling is right whenever they shove at least ~{be}% of hands here")
    adv.data.update(equity=eq, need=need + margin, villain_pct=pct, breakeven_pct=be)
    if edge >= 0:
        adv.why.append("you beat the price against the range they shove here")
        if (fresh_behind or raiser is not None) and live[hero] > live[shover] * 1.3 and not _TRAP[hand]:
            adv.action = "RE-RAISE ALL-IN (isolate)" if spot.bbs(live[hero]) <= 40 else \
                f"RE-RAISE to {min(spot.bbs(live[hero]), 2.5 * shove_bb):.0f}bb (isolate)"
            adv.why.append("players are still to act: raise to get heads-up against the short stack")
        elif (fresh_behind or raiser is not None) and _TRAP[hand]:
            adv.alt.append("just calling to invite another player in is also fine with a monster")
    else:
        adv.why.append("you do not have the equity for the price"
                       + (", and busting here costs far more than the chips are worth" if need - chip_need > 0.04 else ""))
        if chip_need <= eq < need + margin:
            adv.why.append("on chips alone this is a call; ICM / survival is what makes it a fold")
    t = spot.types[shover]
    if t in ("nit", "tight") and edge < 0.04 and edge >= 0:
        adv.warnings.append(f"{spot.pos(shover)} is tagged {t}: this is thin against their real range")
    return adv


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

_REALIZE = {"pair": 0.92, "suited_conn": 0.95, "suited": 0.86, "broadway_off": 0.80, "off": 0.64}


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
        # the opener is committed: treat the raise as an all-in
        adv = vs_shove(spot, opener, callers=flats)
        adv.situation = _situation(spot, f"{spot.who(opener)} raised to {raise_to / bb:.1f}bb, "
                                         f"over 40% of their stack: they are committed")
        if adv.action == "CALL":
            adv.action = "ALL-IN"
            adv.why.append("re-raise all-in rather than call: they are not folding and you deny the flop")
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

    def bb_defend_ok(extra: float = 0.0) -> bool:
        if h_nb != 0:
            return False
        real = _REALIZE[kind] * (0.9 if flats and kind in ("off", "broadway_off") else 1.0)
        return eq_open * real >= need + 0.01 + rp / 2 + extra

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
        elif bb_defend_ok() and to_call <= 0.12 * live[hero]:
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
    if value[hand] >= 0.5:
        if size >= 0.35 * eff:
            adv.action = "ALL-IN"
            adv.why.append("a value 3-bet would commit you anyway, so move in")
        else:
            adv.action = f"3-BET to {size:.1f}bb"
            adv.why.append("3-bet for value: you are ahead of the range that continues")
            if _PREMIUM[hand] or eff <= 45:
                adv.why.append("do not fold to a 4-bet at this depth")
            else:
                adv.alt.append("facing a 4-bet: continue with QQ+/AK, fold the rest")
        adv.confidence = "clear" if _PREMIUM[hand] else "standard"
    elif call[hand] >= 0.5 or (setmine[hand] >= 0.5 and odds_ok) or \
            (deep[hand] >= 0.5 and eff >= 50 and (h_nb <= 2 or flats)):
        price_bad = h_nb == 0 and not bb_defend_ok(-0.02)
        thin_oop = icm_tight and in_blinds and kind in ("off", "broadway_off", "suited")
        if price_bad or thin_oop:
            adv.why.append("in the chart to defend, but the price / ICM makes it a fold here")
            adv.confidence = "close"
        else:
            adv.action = "CALL"
            if kind == "pair" and not _BIG_PAIRS[hand]:
                adv.why.append("set-mine: you have the implied odds; fold the flop without a set or an overpair")
            else:
                adv.why.append("playable against their range and deep enough to see a flop"
                               + (" in position" if ip else ""))
    elif bluff[hand] >= 0.5 and not icm_tight and eff >= 35 and o_type not in ("station", "loose", "maniac"):
        adv.action = f"3-BET to {size:.1f}bb (semi-bluff, fold to a 4-bet)"
        adv.confidence = "close"
        adv.why.append("a blocker hand that plays well as a 3-bet bluff against an opener who can fold")
        adv.alt.append("FOLD is completely fine, and better against a player who never folds")
    elif bb_defend_ok(0.03):
        adv.action = "CALL"
        adv.confidence = "close"
        adv.why.append("closing the action in the big blind at a good price")
        adv.warnings.append("play fit-or-fold after the flop")
    else:
        adv.why.append("not strong enough to continue against this opening range"
                       + (" out of position" if in_blinds else ""))
        if setmine[hand] >= 0.5 and not odds_ok:
            adv.why.append("no implied odds to set-mine at this stack depth")
    if icm_tight:
        adv.why.append(f"ICM: {_pct(rp)} risk premium against {spot.pos(rp_who)}: no light 3-bets or loose calls")
    return adv


# --------------------------------------------------------------------------
# Hero opened and got re-raised (not all-in), or a raise and a re-raise in front
# --------------------------------------------------------------------------

def vs_3bet(spot: Spot, villain: int, three_to: float, hero_open: float) -> Advice:
    setup, hero, hand = spot.setup, spot.hero, spot.hand
    live = setup.live
    bb = spot.bb
    eff = min(live[hero], live[villain]) / bb
    if three_to >= 0.4 * min(live[hero], live[villain]):
        adv = vs_shove(spot, villain, hero_open=hero_open)
        adv.situation = _situation(spot, f"you opened {hero_open / bb:.1f}bb, {spot.who(villain)} 3-bet to "
                                         f"{three_to / bb:.1f}bb: at these stacks this is for everything")
        if adv.action == "CALL":
            adv.action = "ALL-IN"
            adv.why.append("the 3-bet commits both stacks: move in rather than call")
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
        if eq >= 0.60:
            adv.action = f"4-BET to {2.3 * three_to / bb:.0f}bb"
            adv.confidence = "clear"
            adv.why.append("4-bet for value and get the money in")
        elif eq * (0.92 if ip else 0.78) >= need + 0.03 + rp and kind in ("pair", "suited_conn", "suited") \
                or (eq >= 0.48 and ip):
            adv.action = "CALL"
            adv.why.append("good enough to see a flop" + (" in position" if ip else " but play carefully out of position"))
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
                (allin_callers if raises[-1].kind == "allin" else flats).append(a.idx)
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
                return done(vs_shove(spot, r.idx))
            return done(vs_open(spot, r.idx, r.amount, flats))
        if len(raises) == 2:
            a, b = raises
            if b.kind == "allin":
                return done(vs_shove(spot, b.idx, raiser=a.idx, raise_to=a.amount))
            return done(cold_vs_3bet(spot, a.idx, a.amount, b.idx, b.amount))
        last = raises[-1]
        adv = cold_vs_3bet(spot, raises[0].idx, raises[0].amount, last.idx, last.amount)
        adv.warnings.append("several raises in front: only AA/KK are comfortable here")
        return done(adv)

    later = [r for r in raises if r.idx != hero and raises.index(r) > max(
        i for i, x in enumerate(raises) if x.idx == hero)]
    if len(later) == 1:
        r = later[0]
        if r.kind == "allin":
            return done(vs_shove(spot, r.idx, hero_open=hero_raise))
        return done(vs_3bet(spot, r.idx, r.amount, hero_raise))
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
    low = name.strip().lower()
    # the table view prints "SB/BTN" heads-up and "UTG(LJ)" at short tables
    if "(" in low:
        low = low.split("(", 1)[0].strip()
    if "/" in low:
        for part in low.split("/"):
            idx = pos_to_index(part, n)
            if idx is not None:
                return idx
        return None
    if low in ("utg", "ep", "ep1", "utg+0"):
        return 0
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
