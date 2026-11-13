"""Postflop decisions: equity against a narrowed range, pot odds, commitment.

The opponent starts with a preflop range (how they entered the pot) which is
then narrowed street by street by what they did (``flop=call turn=bet66``).
Hero's exact equity against the narrowed range is compared with the price,
with ICM added when the decision is for a big share of the stack.  The
recommendation follows tight-aggressive rules: bet made hands for value,
semi-bluff strong draws, c-bet dry boards heads-up, do not pay off big bets
with one pair, and do not fold strong hands when the stack-to-pot ratio is low.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cards import cards_str, format_range, range_pct
from .equity import expand_range, hand_equity
from .evaluator import (NIB, SBIT, SCNT, STRAIGHT_HI, CATEGORIES, describe, evaluate,
                        value_from_acc)
from .preflop import Advice, _pct
from .ranges import (PLAYER_TYPES, norm_type, parse, play_order, threebet_range, top_percent,
                     villain_limp_range, villain_open_range, vs_open_chart, _POSITION_ALIASES)

STREETS = {3: "flop", 4: "turn", 5: "river"}


@dataclass
class Villain:
    weights: list[float]
    ptype: str = "unknown"
    line: list[tuple[str, str, float | None]] = field(default_factory=list)  # (street, action, size)
    label: str = ""


def range_from_spec(spec: str, n_players: int = 9, ptype: str = "unknown",
                    hero_pos_nb: int | None = None) -> tuple[list[float], str]:
    """Turn a short description of how a player entered the pot into a range.

    ``open:CO``  opened from the cutoff          ``call:BB`` / ``defend`` called from the BB
    ``flat:BTN`` called an open in position      ``3bet`` / ``3bet:SB`` re-raised
    ``limp`` / ``limp:UTG``                      ``any``, ``35%``, or explicit ``"77+, AJs+"``
    """
    s = spec.strip()
    low = s.lower()
    kind, _, where = low.partition(":")

    def nb_of(name: str, default: int) -> int:
        name = name.strip()
        if not name:
            return default
        if name in ("utg", "ep"):
            return max(2, n_players - 1)
        return _POSITION_ALIASES.get(name, default)

    hero_nb = 3 if hero_pos_nb is None else hero_pos_nb
    if kind in ("open", "raise", "pfr", "opened"):
        nb = nb_of(where, 4)
        return villain_open_range(nb, ptype), f"open from {where.upper() or 'MP'}"
    if kind in ("call", "defend", "bbdefend", "bb", "flat", "called", "caller"):
        nb = nb_of(where, 0 if kind in ("defend", "bbdefend", "bb", "call") else 2)
        ch = vs_open_chart(max(1, hero_nb), nb)
        w = [max(c, sm, d) for c, sm, d in zip(ch["call"], ch["setmine"], ch["deep"])]
        # traps and the occasional flatted value hand
        w = [max(x, 0.25 * v) for x, v in zip(w, ch["value"])]
        return w, f"called from {where.upper() or ('BB' if nb == 0 else 'position')}"
    if kind in ("3bet", "threebet", "3b", "reraise"):
        return threebet_range(max(1, hero_nb), ptype), "3-bet range"
    if kind in ("limp", "limper", "limped"):
        return villain_limp_range(nb_of(where, 4), ptype), "limp range"
    if kind in ("any", "random", "atc"):
        return [1.0] * 169, "any two cards"
    m = re.fullmatch(r"(?:top)?\s*(\d+(?:\.\d+)?)\s*%", low)
    if m:
        return top_percent(float(m.group(1)), list(play_order())), f"top {m.group(1)}%"
    return parse(s), "custom range"


_ACTIONS = {"x": "check", "check": "check", "checks": "check", "c": "call", "call": "call",
            "calls": "call", "b": "bet", "bet": "bet", "bets": "bet", "cbet": "bet", "donk": "bet",
            "lead": "bet", "r": "raise", "raise": "raise", "raises": "raise", "xr": "raise",
            "checkraise": "raise", "s": "shove", "shove": "shove", "allin": "shove", "jam": "shove",
            "all-in": "shove"}
_STREET_KEYS = {"f": "flop", "flop": "flop", "t": "turn", "turn": "turn", "r": "river", "river": "river"}


def parse_line(text: str) -> list[tuple[str, str, float | None]]:
    """Parse ``"flop=call turn=bet66"`` (size in % of pot, optional)."""
    out = []
    for tok in re.split(r"[,\s;]+", (text or "").strip()):
        if not tok:
            continue
        m = re.fullmatch(r"([a-z]+)[=:]([a-z\-]+?)(\d+(?:\.\d+)?)?%?", tok.lower())
        if not m or m.group(1) not in _STREET_KEYS or m.group(2) not in _ACTIONS:
            raise ValueError(f"bad line token {tok!r} (use e.g. flop=call turn=bet66 river=check)")
        size = float(m.group(3)) / 100.0 if m.group(3) else None
        out.append((_STREET_KEYS[m.group(1)], _ACTIONS[m.group(2)], size))
    return out


def _draw_strength(c1: int, c2: int, board, bmask: int, bsuits: list[int]) -> float:
    """0 none, ~0.4 gutshot, ~0.9 open-ender, 1.0 flush draw (flop / turn only)."""
    best = 0.0
    for s in range(4):
        mine = (c1 & 3 == s) + (c2 & 3 == s)
        if mine and mine + bsuits[s] == 4:
            best = 1.0
    mask = bmask | (1 << (c1 >> 2)) | (1 << (c2 >> 2))
    if STRAIGHT_HI[mask] < 0:
        outs = 0
        for r in range(13):
            if not mask & (1 << r) and STRAIGHT_HI[mask | (1 << r)] >= 0 \
                    and STRAIGHT_HI[bmask | (1 << r)] < 0:
                outs += 1
        if outs >= 2:
            best = max(best, 0.9)
        elif outs == 1:
            best = max(best, 0.4)
    return best


def narrow(combos, weights, board, action: str, size: float | None, ptype: str,
           pfr_cbet: bool = False) -> list[float]:
    """Re-weight a villain's combos after one action on the given board."""
    n = len(combos)
    if not n:
        return []
    street = len(board)
    base = (0, 0, 0)
    acc = sacc = scnt = 0
    bmask = 0
    bsuits = [0, 0, 0, 0]
    for c in board:
        acc += NIB[c]
        sacc |= SBIT[c]
        scnt += SCNT[c]
        bmask |= 1 << (c >> 2)
        bsuits[c & 3] += 1
    del base
    vals = [value_from_acc(acc + NIB[a] + NIB[b], sacc | SBIT[a] | SBIT[b], scnt + SCNT[a] + SCNT[b])
            for a, b in combos]
    order = sorted(range(n), key=lambda i: -vals[i])
    total = sum(weights) or 1.0
    pct = [0.0] * n   # 0 = best hand in the range, 1 = worst
    run = 0.0
    i = 0
    while i < n:
        j = i
        grp = 0.0
        while j < n and vals[order[j]] == vals[order[i]]:
            grp += weights[order[j]]
            j += 1
        mid = (run + grp / 2) / total
        for k in range(i, j):
            pct[order[k]] = mid
        run += grp
        i = j
    t = norm_type(ptype)
    bluff_mult = {"nit": 0.4, "tight": 0.6, "station": 0.5, "loose": 0.7, "unknown": 1.0, "tag": 1.0,
                  "lag": 1.5, "maniac": 2.2}[t]
    call_shift = {"nit": -0.12, "tight": -0.06, "station": 0.2, "loose": 0.12, "maniac": 0.08}.get(t, 0.0)
    out = []
    for i, (a, b) in enumerate(combos):
        p = pct[i]
        draw = _draw_strength(a, b, board, bmask, bsuits) if street < 5 else 0.0
        if action == "check":
            m = 0.7 if p <= 0.12 else 1.0
        elif action == "call":
            top = {3: 0.60, 4: 0.52, 5: 0.45}[street] + call_shift
            if size is not None:
                top -= 0.25 * (size - 0.6)      # bigger bets get called tighter
            if p <= 0.08:
                m = 0.5
            elif p <= top:
                m = 1.0
            elif p <= top + 0.12:
                m = 0.35
            else:
                m = 0.03
            if street == 3:
                m = max(m, draw if draw >= 0.9 else draw * 1.2)
            elif street == 4:
                m = max(m, 0.8 if draw >= 0.9 else draw * 0.6)
        elif action == "bet":
            f = 0.6 if size is None else size
            value_top = max(0.22, min(0.60, 0.62 - 0.35 * f))
            air = {3: 0.30, 4: 0.15, 5: 0.10}[street]
            draw_w = {3: 0.8, 4: 0.6, 5: 0.0}[street]
            if pfr_cbet and street == 3:
                value_top += 0.15
                air = 0.5
            air = min(0.9, air * bluff_mult)
            if p <= value_top:
                m = 1.0
            elif p <= value_top + 0.2:
                m = 0.35
            else:
                m = air
            m = max(m, draw * draw_w * min(1.3, max(0.6, bluff_mult)))
        else:  # raise / shove
            top = 0.14 if action == "raise" else 0.20
            if p <= top:
                m = 1.0
            elif p <= top + 0.16:
                m = 0.2
            else:
                m = min(0.5, 0.03 * bluff_mult)
            draw_w = {3: 0.45, 4: 0.3, 5: 0.0}[street]
            m = max(m, draw * draw_w * min(1.5, bluff_mult))
        out.append(weights[i] * min(1.0, m))
    if sum(out) <= 0:
        return list(weights)
    return out


def _villain_combos(v: Villain, hero, board, pot_frac_now: float | None, facing: str | None,
                    hero_pfr: bool):
    known = set(hero) | set(board)
    combos, weights = expand_range(v.weights, known)
    line = list(v.line)
    street_now = STREETS[len(board)]
    if facing and not any(s == street_now for s, _, _ in line):
        line.append((street_now, facing, pot_frac_now))
    for street, action, size in line:
        n = {"flop": 3, "turn": 4, "river": 5}[street]
        if n > len(board):
            continue
        weights = narrow(combos, weights, board[:n], action, size, v.ptype,
                         pfr_cbet=(action == "bet" and street == "flop" and not hero_pfr))
    return combos, weights, line


def _range_snapshot(combos, weights, hero, board) -> dict:
    """What the villain range looks like right now compared with hero's hand."""
    hv = evaluate(list(hero) + list(board))
    total = sum(weights) or 1.0
    ahead = behind = tie = 0.0
    cats: dict[str, float] = {}
    for (a, b), w in zip(combos, weights):
        if w <= 0:
            continue
        v = evaluate([a, b] + list(board))
        if v > hv:
            behind += w
        elif v == hv:
            tie += w
        else:
            ahead += w
        c = CATEGORIES[v >> 24]
        cats[c] = cats.get(c, 0.0) + w
    top = sorted(cats.items(), key=lambda kv: -kv[1])[:4]
    return {"ahead": ahead / total, "behind": behind / total, "tie": tie / total,
            "mix": ", ".join(f"{k} {100 * w / total:.0f}%" for k, w in top)}


@dataclass
class PostflopSpot:
    hero: tuple[int, int]
    board: list[int]
    pot: float                    # chips in the middle now, including a bet hero faces
    to_call: float = 0.0
    hero_stack: float = 0.0       # hero's chips behind, before calling
    villain_stack: float | None = None
    villains: list[Villain] = field(default_factory=list)
    in_position: bool = True
    hero_pfr: bool = False        # hero raised last preflop
    facing: str | None = None     # bet | raise | shove (derived from to_call if omitted)
    bb: float = 1.0
    risk_premium: float = 0.0     # ICM premium against the main opponent
    stage: str = ""
    iters: int = 6000


def _size_txt(amount: float, pot: float, bb: float) -> str:
    return f"{amount:,.0f} ({amount / bb:.1f}bb, {100 * amount / pot:.0f}% pot)" if bb > 1.5 else \
        f"{amount:.1f}bb ({100 * amount / pot:.0f}% pot)"


def advise_postflop(spot: PostflopSpot) -> Advice:
    hero, board = tuple(spot.hero), list(spot.board)
    if len(board) not in STREETS:
        raise ValueError("board must have 3, 4 or 5 cards")
    street = STREETS[len(board)]
    d = describe(hero, board)
    tex = d["texture"]
    strength = d["strength"]
    nv = max(1, len(spot.villains))
    multiway = nv >= 2
    pot = spot.pot
    to_call = max(0.0, spot.to_call)
    eff_behind = spot.hero_stack
    if spot.villain_stack is not None:
        eff_behind = min(spot.hero_stack, spot.villain_stack + to_call)
    facing = spot.facing or ("bet" if to_call > 0 else None)
    bet_frac = to_call / max(pot - to_call, 1e-9) if to_call > 0 else None
    if to_call > 0 and spot.villain_stack is not None and spot.villain_stack <= 0.01 * pot:
        facing = "shove"

    packs = []
    for k, v in enumerate(spot.villains):
        packs.append(_villain_combos(v, hero, board, bet_frac if k == 0 else None,
                                     facing if k == 0 else None, spot.hero_pfr))
    vc = [(c, w) for c, w, _ in packs]
    res = hand_equity(hero, board, None, iters=spot.iters, villain_combos=vc)
    eq = res["equity"]
    raw = hand_equity(hero, board, [v.weights for v in spot.villains], iters=spot.iters)["equity"]
    snap = _range_snapshot(packs[0][0], packs[0][1], hero, board) if packs else {}

    spr = eff_behind / pot if pot > 0 else 99.0
    sit = (f"{cards_str(hero)} on {cards_str(board)} ({street}, {tex['label']}): {d['made']}"
           + (f" + {', '.join(d['draws'])}" if d["draws"] else "")
           + f" | pot {pot / spot.bb:.1f}bb, {eff_behind / spot.bb:.1f}bb behind (SPR {spr:.1f})"
           + (f", {nv} opponents" if multiway else ""))
    adv = Advice("CHECK", "standard", sit)
    adv.numbers.append(f"equity vs their range after this line: {_pct(eq)}"
                       + (f" (vs the range they started with: {_pct(raw)})" if abs(raw - eq) >= 0.03 else ""))
    if snap:
        adv.numbers.append(f"right now you are ahead of {_pct(snap['ahead'])} of their range, behind "
                           f"{_pct(snap['behind'])}; they hold: {snap['mix']}")
    adv.data.update(equity=eq, raw_equity=raw, strength=strength, spr=spr)

    vt = norm_type(spot.villains[0].ptype) if spot.villains else "unknown"
    passive = vt in ("nit", "tight", "station", "loose")
    rp = spot.risk_premium
    strong_draw = d["outs"] >= 12 and street != "river"
    any_draw = d["outs"] >= 8 and street != "river"
    icm_tight = rp >= 0.06

    # ------------------------------------------------------------------ facing a bet
    if to_call > 0:
        need = to_call / (pot + to_call)
        commit = to_call / max(spot.hero_stack, 1e-9)
        icm_add = rp * min(1.0, commit * 1.5) if commit >= 0.25 else 0.0
        margin = 0.02 if street != "river" and not spot.in_position else 0.0
        if street == "river":
            # big river bets and raises are under-bluffed, most of all by passive players
            if facing in ("raise", "shove"):
                margin += 0.08 if passive else 0.04
            elif bet_frac and bet_frac >= 0.6 and strength <= 5:
                margin += 0.06 if passive else 0.02
        elif facing in ("raise", "shove") and strength <= 5:
            margin += 0.04
        if multiway:
            margin += 0.03
        implied = 0.0
        if street != "river" and (any_draw or strength >= 6) and eff_behind > to_call:
            implied = min(eff_behind - to_call, 0.5 * (pot + to_call))
        need_eff = to_call / (pot + to_call + implied) if any_draw else need
        target = need_eff + margin + icm_add
        edge = eq - target
        adv.numbers.append(
            f"to call {_size_txt(to_call, pot - to_call, spot.bb)}: pot odds need {_pct(need)}"
            + (f", with implied odds {_pct(need_eff)}" if need_eff < need - 0.005 else "")
            + (f", +{100 * margin:.0f} pts safety" if margin >= 0.005 else "")
            + (f", +{100 * icm_add:.0f} pts ICM" if icm_add >= 0.005 else "")
            + f" -> need {_pct(target)}, have {_pct(eq)}")
        can_raise = eff_behind > to_call * 1.05 and facing != "shove"
        monster = strength >= 7
        if monster and eq >= 0.68 and can_raise:
            if spr <= 2.5 or (eff_behind - to_call) <= 2.2 * (pot + to_call):
                adv.action = "RAISE ALL-IN"
                adv.why.append("a very strong hand with a short stack-to-pot ratio: get the chips in now")
            elif tex["wet"] >= 1 or not spot.in_position or street != "flop":
                rs = min(eff_behind, to_call * 3.0 + (pot - to_call) * 0.3)
                adv.action = f"RAISE to {_size_txt(rs, pot, spot.bb)}"
                adv.why.append("raise for value and protection: the board is draw-heavy or you are out of position")
            else:
                adv.action = "CALL"
                adv.why.append("very strong on a dry board in position: call and let them keep betting; raise the next street")
                adv.alt.append("raising now is fine too, especially against a calling station")
            adv.confidence = "clear"
        elif strong_draw and can_raise and spr <= 4 and not multiway and eq >= 0.40 and not icm_tight \
                and vt not in ("station",):
            adv.action = "RAISE ALL-IN (semi-bluff)"
            adv.confidence = "standard"
            adv.why.append(f"a big draw (~{d['outs']} outs, {_pct(eq)} equity) with fold equity on top: shoving beats calling")
            adv.alt.append("CALL is fine if this player never folds")
        elif edge >= 0:
            adv.action = "CALL"
            adv.confidence = "clear" if edge >= 0.10 else "close" if edge < 0.03 else "standard"
            left = eff_behind - to_call
            if street != "river" and can_raise and strength >= 5 and eq >= 0.6 \
                    and left <= 0.6 * (pot + to_call):
                adv.action = "RAISE ALL-IN"
                adv.why.append("so little is left behind that calling commits you: shove now and deny the draws")
            adv.why.append("you have the equity for the price against the hands that bet this way")
            if strong_draw and can_raise and not multiway:
                adv.alt.append("raising as a semi-bluff is also strong with this much equity")
            if strength <= 4 and street != "river" and not any_draw:
                adv.warnings.append("a bluff-catcher: fold to a big bet on the next street unless you improve")
            elif any_draw and strength <= 3:
                adv.warnings.append("you are drawing: fold the river if you miss, value-bet if you hit")
        else:
            adv.action = "FOLD"
            adv.confidence = "clear" if edge <= -0.10 else "close" if edge > -0.03 else "standard"
            adv.why.append("not enough equity against the hands that bet this way")
            if strength >= 5 and spr <= 1.2:
                adv.warnings.append("stack-to-pot ratio is tiny: folding a strong hand here is only right "
                                    "against a player who never bluffs")
            if eq >= need and icm_add > 0:
                adv.why.append("on chips alone this is a call; ICM / survival is what makes it a fold")
        if strength >= 5 and spr <= 1.5 and adv.action == "FOLD" and not icm_tight and eq >= need - 0.05:
            adv.action = "CALL"
            adv.confidence = "close"
            adv.why = ["with a strong one-pair hand and less than 1.5x the pot behind you are committed"]
        return adv

    # ------------------------------------------------------------------ hero to act, no bet
    wet = tex["wet"]
    value_ok = eq >= (0.72 if multiway else 0.62) and strength >= 4
    if street == "river":
        value_ok = eq >= (0.75 if multiway else 0.64) and strength >= 4

    def bet(frac: float) -> float:
        return min(eff_behind, frac * pot)

    if strength >= 7 or (value_ok and strength >= 5):
        frac = 0.33 if (wet == 0 and street == "flop") else 0.66 if wet >= 1 else 0.5
        if street == "turn":
            frac = 0.66
        if street == "river":
            frac = 0.75 if strength >= 7 else 0.5
        amt = bet(frac)
        if spr <= 1.3 or amt >= 0.6 * eff_behind:
            adv.action = "BET ALL-IN"
            adv.why.append("value bet; with so little behind, put it all in")
        else:
            adv.action = f"BET {_size_txt(amt, pot, spot.bb)}"
            adv.why.append("bet for value: worse hands call" + (" and draws must pay" if wet >= 1 and street != "river" else ""))
        adv.confidence = "clear" if strength >= 6 else "standard"
        if strength >= 8 and wet == 0 and not multiway and street == "flop" and spot.in_position:
            adv.alt.append("checking once to trap is fine on this dry board")
    elif value_ok and strength == 4:
        amt = bet(0.33 if street == "flop" else 0.5)
        adv.action = f"BET {_size_txt(amt, pot, spot.bb)}"
        adv.why.append("thin value / protection with top pair: bet small and re-evaluate if raised")
        adv.warnings.append("fold to a raise unless this player is aggressive")
    elif any_draw and not multiway and (spot.hero_pfr or spot.in_position) and not icm_tight:
        amt = bet(0.6)
        if spr <= 1.5 and strong_draw:
            adv.action = "BET ALL-IN (semi-bluff)"
        else:
            adv.action = f"BET {_size_txt(amt, pot, spot.bb)} (semi-bluff)"
        adv.why.append(f"a draw with ~{d['outs']} outs: betting wins the pot now or builds it for when you hit")
        adv.alt.append("checking to take a free card is fine in position against a station")
    elif spot.hero_pfr and street == "flop" and not multiway and wet <= 1 \
            and (tex["high"] >= 10 or tex.get("paired")) and vt != "station" and not icm_tight:
        amt = bet(0.33)
        adv.action = f"BET {_size_txt(amt, pot, spot.bb)} (c-bet)"
        adv.confidence = "standard"
        adv.why.append("heads-up as the preflop raiser on a dry, high board: a small continuation bet "
                       "takes it down often enough, whatever you hold")
        adv.warnings.append("give up on the turn unless you improve or pick up a draw")
    else:
        adv.action = "CHECK"
        if strength in (2, 3, 4):
            adv.why.append("a medium-strength hand: keep the pot small, call one reasonable bet, fold to heavy pressure")
        elif multiway:
            adv.why.append("multi-way with nothing strong: no bluffing into several players")
        else:
            adv.why.append("no value and no good bluff here: check and give up unless you improve")
        if eq >= 0.55 and strength >= 3 and street == "river" and not multiway:
            adv.alt.append(f"a small value bet ({_size_txt(bet(0.33), pot, spot.bb)}) is fine against a station")
    if icm_tight and adv.action.startswith("BET") and strength < 5:
        adv.warnings.append("ICM pressure is high: no multi-street bluffs")
    return adv


def describe_villain(v: Villain) -> str:
    return f"{v.label or 'range'} {range_pct(v.weights):.0f}% [{format_range(v.weights)}]"
