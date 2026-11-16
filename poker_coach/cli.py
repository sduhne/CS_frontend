"""Command line for the poker coach.

    python -m poker_coach <command> [options]

Table tracking:  new, sync, set, seat, stack, bust, away, back, type, note,
                 button, next, payouts, show, undo, log
Decisions:       advise (uses the tracked table), quick (no table needed)
Tools:           equity, range, chart, icm
"""

from __future__ import annotations

import argparse
import json
import sys

from . import aof as A
from . import latereg as L
from . import state as S
from .cards import (HANDS, cards_str, format_range, parse_cards, parse_hand, range_combos,
                    range_pct)
from .equity import eq_vs_range, hand_equity
from .icm import Prizes, default_payouts
from .postflop import PostflopSpot, Villain, advise_postflop, parse_line, range_from_spec
from .preflop import Spot, advise, parse_actions, parse_amount, pos_to_index, quick_spot
from .pushfold import HandSetup, nash_push_range, solve_open_shove
from .ranges import PLAYER_TYPES, norm_type, parse, position_name, rfi_range


def _out(text: str = "") -> None:
    print(text)


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 2


def _need_state() -> dict:
    return S.load()


def _commit(st: dict) -> None:
    S.save(st)


def _resolve(st: dict, who: str) -> int:
    seat = S.find_seat(st, who)
    if seat is None or str(seat) not in S.seats(st):
        # a position name (BTN, CO, ...) also identifies a player
        order = S.action_order(st)
        idx = pos_to_index(str(who), len(order)) if order else None
        if idx is not None:
            return order[idx]
        raise ValueError(f"no player matches {who!r}")
    return seat


# ----------------------------------------------------------------------------
# table tracking commands
# ----------------------------------------------------------------------------

def cmd_new(a) -> int:
    old = S.archive()
    st = S.blank_state()
    t = st["tournament"]
    t["name"] = a.name or ""
    for k in ("buyin", "entrants", "paid", "start_stack", "prize_pool"):
        v = getattr(a, k)
        if v is not None:
            t[k] = v
    if a.entrants and not a.remaining:
        t["remaining"] = int(a.entrants)
    if a.remaining:
        t["remaining"] = int(a.remaining)
    if t.get("remaining"):
        S.record_remaining(st, t["remaining"])
    st["table"]["max_seats"] = a.seats
    st["config"]["goal"] = a.goal
    st["config"]["pace"] = a.pace
    S.log(st, f"new tournament {t['name']!r}")
    _commit(st)
    _out(f"New tournament started{' (previous one archived to ' + old + ')' if old else ''}.")
    _out(S.render(st))
    return 0


def cmd_sync(a) -> int:
    raw = a.json
    if a.file:
        with open(a.file) as fh:
            raw = fh.read()
    if not raw:
        return _fail("give the snapshot as JSON")
    try:
        snap = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _fail(f"snapshot is not valid JSON: {exc}")
    st = _need_state()
    S.checkpoint(st)
    changes = S.apply_snapshot(st, snap)
    busted = len(snap.get("busted") or [])
    if busted and "remaining" not in snap and st["tournament"].get("remaining"):
        st["tournament"]["remaining"] = max(1, st["tournament"]["remaining"] - busted)
        S.record_remaining(st, st["tournament"]["remaining"])
    _commit(st)
    _out("Changes: " + ("; ".join(changes) if changes else "none"))
    _out(S.render(st))
    return 0


_SET_TOURNEY = {"buyin": float, "entrants": int, "remaining": int, "paid": int, "prize_pool": float,
                "start_stack": float, "avg_stack": float, "name": str}
_SET_LEVEL = {"sb": float, "bb": float, "ante": float, "bb_ante": float, "level": int}


def cmd_set(a) -> int:
    st = _need_state()
    S.checkpoint(st)
    done = []
    for item in a.pairs:
        if "=" not in item:
            return _fail(f"expected key=value, got {item!r}")
        key, val = item.split("=", 1)
        key = key.strip().lower().replace("-", "_")
        if key in _SET_TOURNEY:
            v = val if key == "name" else _SET_TOURNEY[key](S._num(val))
            st["tournament"][key] = v
            if key == "remaining":
                S.record_remaining(st, v)
            if key == "avg_stack" and st["tournament"].get("remaining"):
                st["tournament"]["total_chips"] = v * st["tournament"]["remaining"]
        elif key in _SET_LEVEL:
            st["level"]["number" if key == "level" else key] = _SET_LEVEL[key](S._num(val))
            if key == "bb" and not any(p.startswith("sb=") for p in a.pairs):
                st["level"]["sb"] = st["level"]["bb"] / 2
        elif key in ("button", "btn", "dealer"):
            st["table"]["button"] = _resolve(st, val)
        elif key == "hero":
            st["table"]["hero"] = int(val) if val.isdigit() else _resolve(st, val)
        elif key in ("goal",):
            if val not in S.GOALS:
                return _fail(f"goal must be one of {S.GOALS}")
            st["config"]["goal"] = val
        elif key == "pace":
            st["config"]["pace"] = val
        elif key in ("sec_per_hand", "max_seats"):
            (st["config"] if key == "sec_per_hand" else st["table"])[key] = int(float(val))
        else:
            return _fail(f"unknown setting {key!r}")
        done.append(f"{key}={val}")
    S.log(st, "set " + " ".join(done))
    _commit(st)
    _out("Set " + ", ".join(done))
    _out(S.render(st))
    return 0


def cmd_seat(a) -> int:
    st = _need_state()
    S.checkpoint(st)
    cur = S.set_seat(st, a.seat, a.name, S._num(a.stack) if a.stack is not None else None,
                     "away" if a.away else None, a.type)
    if a.hero:
        st["table"]["hero"] = a.seat
    S.log(st, f"seat {a.seat}: {cur['name']} {cur['stack']:,.0f}")
    _commit(st)
    _out(S.render(st))
    return 0


def cmd_stack(a) -> int:
    st = _need_state()
    if len(a.items) % 2:
        return _fail("give pairs: <player> <stack> [<player> <stack> ...]")
    S.checkpoint(st)
    for who, amt in zip(a.items[::2], a.items[1::2]):
        seat = _resolve(st, who)
        old = S.seats(st)[str(seat)]["stack"]
        new = S._num(amt)
        S.seats(st)[str(seat)]["stack"] = new
        S.log(st, f"{S.seats(st)[str(seat)]['name']}: {old:,.0f} -> {new:,.0f}")
    _commit(st)
    _out(S.render(st))
    return 0


def cmd_bust(a) -> int:
    st = _need_state()
    S.checkpoint(st)
    for who in a.who:
        seat = _resolve(st, who)
        if seat == st["table"].get("hero"):
            _out("Hero is out of the tournament. Use `new` to start the next one.")
        name = S.remove_seat(st, seat, "busted")
        _out(f"{name} (seat {seat}) busted.")
        if st["tournament"].get("remaining"):
            st["tournament"]["remaining"] = max(1, st["tournament"]["remaining"] - 1)
            S.record_remaining(st, st["tournament"]["remaining"])
    _commit(st)
    _out(S.render(st))
    return 0


def _status_cmd(status: str):
    def run(a) -> int:
        st = _need_state()
        S.checkpoint(st)
        for who in a.who:
            seat = _resolve(st, who)
            S.seats(st)[str(seat)]["status"] = status
        _commit(st)
        _out(S.render(st))
        return 0
    return run


def cmd_type(a) -> int:
    st = _need_state()
    t = norm_type(a.type)
    if t == "unknown" and a.type.lower() not in ("unknown", ""):
        return _fail(f"unknown player type {a.type!r}; use one of {', '.join(PLAYER_TYPES)}")
    S.checkpoint(st)
    seat = _resolve(st, a.who)
    S.seats(st)[str(seat)]["type"] = t
    _commit(st)
    _out(f"{S.seats(st)[str(seat)]['name']} is now tagged {t}: {PLAYER_TYPES[t]['desc']}")
    return 0


def cmd_note(a) -> int:
    st = _need_state()
    S.checkpoint(st)
    seat = _resolve(st, a.who)
    S.seats(st)[str(seat)].setdefault("notes", []).append(" ".join(a.text))
    _commit(st)
    _out(f"Noted on {S.seats(st)[str(seat)]['name']}.")
    return 0


def cmd_button(a) -> int:
    st = _need_state()
    S.checkpoint(st)
    if a.seat.lower() == "next":
        S.advance_button(st)
    else:
        st["table"]["button"] = _resolve(st, a.seat)
    _commit(st)
    _out(S.render(st))
    return 0


def cmd_next(a) -> int:
    """New hand: move the button and optionally update stacks."""
    st = _need_state()
    S.checkpoint(st)
    S.advance_button(st)
    if a.items:
        if len(a.items) % 2:
            return _fail("stack updates come in pairs: <player> <stack>")
        for who, amt in zip(a.items[::2], a.items[1::2]):
            S.seats(st)[str(_resolve(st, who))]["stack"] = S._num(amt)
    _commit(st)
    _out(S.render(st))
    return 0


def cmd_payouts(a) -> int:
    st = _need_state()
    S.checkpoint(st)
    t = st["tournament"]
    if len(a.values) == 1 and a.values[0].lower() == "auto":
        t["payouts"] = None
        _out("Using the estimated payout table.")
    else:
        table: dict[int, float] = {}
        seq: list[float] = []
        for tok in a.values:
            if ":" in tok:
                place, amt = tok.split(":", 1)
                if "-" in place:
                    lo, hi = place.split("-", 1)
                    for p in range(int(lo), int(hi) + 1):
                        table[p] = S._num(amt)
                else:
                    table[int(place)] = S._num(amt)
            else:
                seq.append(S._num(tok))
        if table:
            top = max(table)
            last = 0.0
            pays = []
            for p in range(top, 0, -1):
                last = table.get(p, last)
                pays.append(last)
            seq = pays[::-1]
        t["payouts"] = seq
    _commit(st)
    pays = S.payouts(st) or []
    _out(f"{len(pays)} places paid; 1st {pays[0]:,.2f}, min cash {pays[-1]:,.2f}" if pays else "no payout info")
    return 0


def cmd_show(a) -> int:
    st = _need_state()
    if not S.exists():
        _out("No tournament is being tracked yet. Start with `new` or `sync`.")
        return 0
    _out(S.render(st))
    if a.log:
        _out("Recent events:")
        for e in st.get("log", [])[-a.log:]:
            _out("  - " + e["msg"])
    return 0


def cmd_undo(a) -> int:
    st = _need_state()
    prev = S.undo(st)
    if prev is None:
        return _fail("nothing to undo")
    _commit(prev)
    _out("Reverted the last change.")
    _out(S.render(prev))
    return 0


def cmd_log(a) -> int:
    st = _need_state()
    if a.text:
        S.log(st, " ".join(a.text))
        _commit(st)
        _out("Logged.")
    else:
        for e in st.get("log", [])[-25:]:
            _out("- " + e["msg"])
    return 0


# ----------------------------------------------------------------------------
# decisions
# ----------------------------------------------------------------------------

def _state_spot(st: dict, a) -> tuple[Spot, list[int]]:
    setup, order = S.hand_setup(st)
    hero_seat = st["table"].get("hero")
    if hero_seat is None or hero_seat not in order:
        raise ValueError("hero's seat is not set (use: set hero=<seat>)")
    hero = order.index(hero_seat)
    hand, cards = parse_hand(a.hand)
    seats = [S.seats(st)[str(s)] for s in order]
    prizes = S.build_prizes(st, a.goal)
    field = Prizes(prizes.raw_payouts, prizes.field_n, prizes.field_stack) if not prizes.chip_ev else Prizes()
    stage = S.stage(st)
    fc = S.fold_clock(st)
    hero_bb = setup.start[hero] / setup.bb
    to_money = stage.get("to_money")
    desperate = bool(fc and fc.get("verdict") == "short" and hero_bb <= 6) or \
        (hero_bb <= 3 and (to_money is None or to_money > 3))
    spot = Spot(setup=setup, hero=hero, hand=hand, cards=cards,
                names=[s.get("name", "") for s in seats],
                types=[s.get("type", "unknown") for s in seats],
                away=[s.get("status") == "away" for s in seats],
                prizes=prizes, field_prizes=field, stage=stage, desperate=desperate)

    def resolve(name: str):
        idx = pos_to_index(name, len(order))
        if idx is not None:
            return idx
        seat = S.find_seat(st, name)
        return order.index(seat) if seat in order else None

    spot.acts = parse_actions(a.facing or "", setup, hero, resolve, chips=True)
    return spot, order


def _context_line(spot: Spot) -> str:
    parts = []
    for i in range(spot.setup.n):
        mark = "*" if i == spot.hero else ""
        nm = spot.names[i]
        nm = "" if nm == spot.pos(i) else f" {nm[:10]}"
        t = "" if spot.types[i] == "unknown" else f"({spot.types[i]})"
        aw = " AWAY" if spot.away[i] else ""
        parts.append(f"{mark}{spot.pos(i)}{nm}{t} {spot.bbs(spot.setup.start[i]):.0f}bb{aw}")
    s = spot.setup
    ante = f" ante {s.antes[0]:g}" if s.antes and s.antes[0] else ""
    if s.antes and s.antes[-1] > s.antes[0]:
        ante += f" bb-ante {s.antes[-1] - s.antes[0]:g}"
    return "ctx: " + " | ".join(parts) + f" || blinds {s.sb:g}/{s.bb:g}{ante} || {spot.prizes.label or 'chip EV'}"


def _postflop_from_args(a, bb: float, hero_stack: float, n_players: int, hero_nb: int | None,
                        rp_fn, types_by_ref, stage_label: str) -> PostflopSpot:
    _, cards = parse_hand(a.hand)
    if cards is None:
        raise ValueError("postflop advice needs your exact cards, e.g. --hand AhKd")
    board = parse_cards(a.board)
    chips = bb > 1.5

    def amt(x):
        return parse_amount(str(x), bb, chips) if x is not None else None

    pot = amt(a.pot)
    if pot is None:
        raise ValueError("--pot is required for postflop advice")
    to_call = amt(a.to_call) or 0.0
    stack = amt(a.stack) if a.stack is not None else hero_stack
    vstack = amt(a.villain_stack)
    specs = a.vs or ["35%"]
    lines = a.line or []
    types = a.villain_type or []
    villains = []
    for k, spec in enumerate(specs):
        ptype = types[k] if k < len(types) else types_by_ref(spec)
        w, label = range_from_spec(spec, n_players, ptype, hero_nb)
        villains.append(Villain(w, norm_type(ptype), parse_line(lines[k]) if k < len(lines) else [], label))
    facing = a.villain_action
    return PostflopSpot(hero=cards, board=board, pot=pot, to_call=to_call, hero_stack=stack,
                        villain_stack=vstack, villains=villains, in_position=not a.oop,
                        hero_pfr=a.pfr, facing=facing, bb=bb, risk_premium=rp_fn(), stage=stage_label)


def cmd_advise(a) -> int:
    st = _need_state()
    if not S.exists():
        return _fail("no table is being tracked; use `quick` for a one-off question or `sync` first")
    try:
        if a.board:
            setup, order = S.hand_setup(st)
            hero_seat = st["table"].get("hero")
            hero = order.index(hero_seat) if hero_seat in order else None
            prizes = S.build_prizes(st, a.goal)

            def rp_fn() -> float:
                if prizes.chip_ev or hero is None:
                    return 0.0
                target = None
                if a.villain:
                    seat = _resolve(st, a.villain)
                    target = order.index(seat) if seat in order else None
                if target is None:
                    others = [i for i in range(setup.n) if i != hero]
                    target = max(others, key=lambda i: setup.live[i])
                return prizes.risk_premium(setup.live, hero, target)

            def type_of(_spec: str) -> str:
                if a.villain:
                    return S.seats(st)[str(_resolve(st, a.villain))].get("type", "unknown")
                return "unknown"

            # tracked stacks are start-of-hand: take off each player's share of the pot so far
            chips = setup.bb > 1.5
            pot_now = parse_amount(str(a.pot), setup.bb, chips) if a.pot is not None else 0.0
            facing_amt = parse_amount(str(a.to_call), setup.bb, chips) if a.to_call else 0.0
            share = max(0.0, pot_now - facing_amt) / (len(a.vs or [1]) + 1)
            if a.villain and a.villain_stack is None:
                v_start = S.seats(st)[str(_resolve(st, a.villain))]["stack"]
                a.villain_stack = str(max(0.0, v_start - share - facing_amt))
            hero_stack = max(0.0, (S.hero_stack(st) or 0.0) - share)
            spot = _postflop_from_args(a, setup.bb, hero_stack, setup.n,
                                       setup.n - 1 - hero if hero is not None else None,
                                       rp_fn, type_of, S.stage(st)["label"])
            adv = advise_postflop(spot)
            _out(adv.render())
            for v in spot.villains:
                _out(f"  rng: {v.label}: {range_pct(v.weights):.0f}% preflop [{format_range(v.weights)}]")
            _out(f"ctx: {S.stage(st)['label']} || {prizes.label or 'chip EV'} || ICM risk premium "
                 f"{100 * spot.risk_premium:.0f}%")
            return 0
        spot, _ = _state_spot(st, a)
        adv = advise(spot)
        _out(adv.render())
        _out(_context_line(spot))
    except ValueError as exc:
        return _fail(str(exc))
    return 0


def cmd_quick(a) -> int:
    try:
        hand, cards = parse_hand(a.hand)
        prizes = Prizes()
        stage = {}
        if a.remaining and (a.paid or a.entrants):
            entrants = a.entrants or max(a.remaining, (a.paid or 0) * 7)
            pays = default_payouts(entrants, a.paid)
            field_n = max(0, a.remaining - a.players)
            avg = (a.avg_bb if a.avg_bb else a.stack)
            bonus = pays[-1] if (a.goal == "itm" and a.remaining > len(pays)) else 0.0
            if a.goal != "chips":
                prizes = Prizes(pays, field_n, avg, itm_bonus=bonus,
                                label=f"ICM ({a.remaining} left, {len(pays)} paid"
                                      + (", ITM-first" if bonus else "") + ")")
            to_money = a.remaining - len(pays)
            stage = {"label": f"{to_money} from the money" if to_money > 0 else "in the money",
                     "to_money": to_money}
        if a.board:
            def rp_fn() -> float:
                if prizes.chip_ev:
                    return 0.0
                stacks = [a.stack, a.villain_stack_bb or a.stack]
                return prizes.risk_premium(stacks, 0, 1)

            n_hero = pos_to_index(a.pos, a.players)
            hero_nb = a.players - 1 - n_hero if n_hero is not None else None
            a.villain_stack = a.villain_stack if a.villain_stack is not None else (
                str(a.villain_stack_bb) if a.villain_stack_bb else None)
            spot = _postflop_from_args(a, 1.0, a.stack, a.players, hero_nb, rp_fn,
                                       lambda _s: "unknown", stage.get("label", ""))
            adv = advise_postflop(spot)
            _out(adv.render())
            for v in spot.villains:
                _out(f"  rng: {v.label}: {range_pct(v.weights):.0f}% preflop [{format_range(v.weights)}]")
            return 0
        spot = quick_spot(hand, cards, a.stack, a.players, a.pos, a.facing or "",
                          a.villain_stack_bb, prizes, not a.no_ante, stage)
        if not prizes.chip_ev:
            spot.field_prizes = Prizes(prizes.raw_payouts, prizes.field_n, prizes.field_stack)
        if a.villain_type:
            # tag the first player mentioned in --facing, else everyone behind
            acted = [act.idx for act in spot.acts if act.idx != spot.hero]
            targets = acted[:1] if acted else list(range(spot.hero + 1, spot.setup.n))
            for i in targets:
                spot.types[i] = norm_type(a.villain_type[0])
        adv = advise(spot)
        _out(adv.render())
        _out(_context_line(spot))
    except ValueError as exc:
        return _fail(str(exc))
    return 0


# ----------------------------------------------------------------------------
# tools
# ----------------------------------------------------------------------------

def cmd_equity(a) -> int:
    try:
        hand, cards = parse_hand(a.hand)
        ranges = [parse(v) for v in a.vs]
        board = parse_cards(a.board) if a.board else []
        if not board and len(ranges) == 1:
            eq, prob = eq_vs_range(hand, ranges[0])
            _out(f"{HANDS[hand]} vs {range_pct(ranges[0]):.1f}% [{format_range(ranges[0])}]: "
                 f"equity {100 * eq:.1f}%")
            return 0
        if cards is None:
            from .cards import CLASS_COMBOS
            cards = CLASS_COMBOS[hand][0]
        res = hand_equity(cards, board, ranges, iters=a.iters)
        _out(f"{cards_str(cards)}{' on ' + cards_str(board) if board else ''} vs "
             f"{len(ranges)} range(s): equity {100 * res['equity']:.1f}% "
             f"(win {100 * res['win']:.1f}%, tie {100 * res['tie']:.1f}%; {res['method']})")
    except ValueError as exc:
        return _fail(str(exc))
    return 0


def _grid(weights) -> str:
    from .cards import GRID
    rows = ["    " + "  ".join(GRID)]
    for i in range(13):
        cells = []
        for j in range(13):
            w = weights[i * 13 + j]
            cells.append("##" if w >= 0.75 else "++" if w >= 0.25 else " .")
        rows.append(f" {GRID[i]}  " + " ".join(cells))
    rows.append("  (## in range, ++ sometimes; suited above the diagonal, offsuit below)")
    return "\n".join(rows)


def cmd_range(a) -> int:
    try:
        w = parse(" ".join(a.notation))
    except ValueError as exc:
        return _fail(str(exc))
    _out(f"{range_pct(w):.1f}% of hands, {range_combos(w):.0f} combos: {format_range(w)}")
    if a.grid:
        _out(_grid(w))
    return 0


def cmd_chart(a) -> int:
    n = a.players
    idx = pos_to_index(a.pos, n)
    if idx is None:
        return _fail(f"unknown position {a.pos!r}")
    nb = n - 1 - idx
    if a.kind == "push":
        w = nash_push_range(max(1, nb), a.stack, not a.no_ante)
        _out(f"Nash open-shove, {position_name(nb, n)} ({nb} behind), {a.stack:g}bb, "
             f"{'with' if not a.no_ante else 'no'} ante: {range_pct(w):.0f}%")
    else:
        w = rfi_range(max(1, nb), a.stack)
        _out(f"TAG open-raise, {position_name(nb, n)} ({nb} behind), {a.stack:g}bb: {range_pct(w):.0f}%")
    _out(format_range(w))
    _out(_grid(w))
    return 0


def cmd_icm(a) -> int:
    st = _need_state()
    try:
        setup, order = S.hand_setup(st)
    except ValueError as exc:
        return _fail(str(exc))
    prizes = S.build_prizes(st, a.goal)
    if prizes.chip_ev:
        _out("No ICM yet: I need players remaining and places paid (or entrants).")
        return 0
    hero_seat = st["table"].get("hero")
    hero = order.index(hero_seat) if hero_seat in order else None
    pays = prizes.raw_payouts
    _out(f"{prizes.label}; 1st {pays[0]:,.2f}, min cash {pays[-1]:,.2f}"
         f"{'' if st['tournament'].get('payouts') else ' (estimated payouts)'}")
    stacks = setup.start
    _out(f"{'':2}{'Pos':<8}{'Player':<16}{'Stack':>11}{'Value':>10}  Hero's risk premium vs them")
    for i, seat in enumerate(order):
        s = S.seats(st)[str(seat)]
        val = prizes.value(stacks, i)
        rp = ""
        if hero is not None and i != hero:
            rp = f"{100 * prizes.risk_premium(stacks, hero, i):.1f}% (bubble factor {prizes.bubble_factor(stacks, hero, i):.2f})"
        mark = "*" if i == hero else " "
        _out(f"{mark:2}{position_name(setup.n - 1 - i, setup.n):<8}{s.get('name', '')[:15]:<16}"
             f"{stacks[i]:>11,.0f}{val:>10.2f}  {rp}")
    _out("Risk premium = extra equity you need, above pot odds, to play for stacks against that player.")
    return 0


# ----------------------------------------------------------------------------
# All-In or Fold
# ----------------------------------------------------------------------------

def _aof_stacks(a, n: int) -> list[float]:
    stacks = [float(a.stack)] * n
    if getattr(a, "stacks", None):
        for item in a.stacks.replace(";", ",").split(","):
            if not item.strip():
                continue
            if "=" not in item:
                raise ValueError(f"stacks look like CO=8,BTN=6.5 (got {item!r})")
            seat, val = item.split("=", 1)
            stacks[A.position_index(seat, n)] = float(val)
    return stacks


def cmd_aof(a) -> int:
    hand, _ = parse_hand(a.hand)
    n = a.players
    hero = A.position_index(a.pos, n)
    mask = A.parse_shovers(a.shoved, n, hero)
    ans = A.decide(hand, n, hero, mask, _aof_stacks(a, n), A.family_for(a.mode, a.vs))
    _out(ans.render())
    return 0


def cmd_aof_chart(a) -> int:
    n = a.players
    hero = A.position_index(a.pos, n)
    mask = A.parse_shovers(a.shoved, n, hero)
    family = A.family_for(a.mode, a.vs)
    weights, ev, used = A.node_range(family, n, hero, mask, a.stack)
    solid = [1.0 if e > 0 else 0.0 for e in ev]
    _out(f"{A.describe_point(n, hero, mask)} | {n}-handed, {used:g}bb, {A.FAMILY_LABEL[family]}: "
         f"{range_pct(solid):.1f}% of hands")
    _out(format_range(solid))
    _out(_grid(weights))
    _out("  (++ here means shoving and folding are worth the same within 0.05bb)")
    return 0


def cmd_aof_sheet(a) -> int:
    _out(A.sheet(a.players, a.stack, A.family_for(a.mode, a.vs)))
    return 0


def cmd_aof_compare(a) -> int:
    """Which table to use: every table against every kind of opponent."""
    m = A.matrix()
    if not m:
        return _fail("no comparison stored; run tools/build_aof_exploit.py")
    heroes = [("solved", "Solved table"), ("cash-loose", "Loose-table ranges"), ("cash-vloose", "Very-loose ranges")]
    opps = [("solid", "solid"), ("cash-loose", "call 1.5x wide"), ("cash-vloose", "call 2x wide")]
    _out("4-handed, 8bb, 0.1bb fee: your result in bb per 100 hands (swing per hand in bb)")
    _out(f"{'You play':<20}" + "".join(f"{'vs ' + label:>22}" for _, label in opps))
    for hk, hl in heroes:
        cells = []
        for ok, _ in opps:
            c = m.get(f"{hk}|{ok}")
            cells.append(f"{c['bb100']:+.1f} ({c['sd']:.2f})" if c else "?")
        _out(f"{hl:<20}" + "".join(f"{c:>22}" for c in cells))
    return 0


def cmd_aof_quiz(a) -> int:
    import random

    rng = random.Random(a.seed)
    family = A.family_for(a.mode, a.vs)
    spots = [A.random_spot(rng, a.players, a.stack, family) for _ in range(a.count)]
    if a.print or not sys.stdin.isatty():
        _out(f"All-In or Fold drill: {a.players}-handed, {a.stack:g}bb, {A.FAMILY_LABEL[family]}")
        for k, sp in enumerate(spots, 1):
            _out(f"Q{k}. {sp.question()}")
        _out("")
        _out("Answers")
        for k, sp in enumerate(spots, 1):
            ans = sp.answer()
            _out(f"A{k}. {ans.action} ({ans.ev:+.2f}bb, {ans.confidence})")
        return 0
    right, lost = 0, 0.0
    for k, sp in enumerate(spots, 1):
        ans = sp.answer()
        reply = input(f"{k}/{len(spots)}  {sp.question()}  (a)ll-in or (f)old? ").strip().lower()
        if reply in ("q", "quit", "exit"):
            break
        mine = "FOLD" if reply.startswith("f") else "ALL-IN"
        if mine == ans.action or ans.confidence == "close":
            right += 1
            _out(f"   correct: {ans.action} ({ans.ev:+.2f}bb)")
        else:
            lost += abs(ans.ev)
            _out(f"   no: {ans.action} ({ans.ev:+.2f}bb). Range here: {format_range(ans.range_weights)}")
    _out(f"Score {right}/{len(spots)}; mistakes cost {lost:.2f}bb in total.")
    return 0


# ----------------------------------------------------------------------------

def _add_postflop_args(p) -> None:
    p.add_argument("--board", help="community cards, e.g. Ks7d2c")
    p.add_argument("--pot", help="pot right now, including any bet you face")
    p.add_argument("--to-call", dest="to_call", help="what you must put in to call (0 if checked to you)")
    p.add_argument("--vs", action="append", help="how each opponent entered the pot: open:CO, call:BB, "
                                                 "flat:BTN, 3bet, limp, 30%%, or a range. Repeat per opponent")
    p.add_argument("--line", action="append", help="opponent's postflop line so far, e.g. "
                                                   "'flop=call turn=bet66'. Repeat per opponent")
    p.add_argument("--villain-type", dest="villain_type", action="append", help="player type per opponent")
    p.add_argument("--villain-action", dest="villain_action", choices=["bet", "raise", "shove"],
                   help="what you face now (default: bet when --to-call > 0)")
    p.add_argument("--villain-stack", dest="villain_stack", help="main opponent's chips behind after their bet")
    p.add_argument("--oop", action="store_true", help="you are out of position (act first)")
    p.add_argument("--pfr", action="store_true", help="you were the last raiser preflop")


# ----------------------------------------------------------------------------
# late-registration min-cash system
# ----------------------------------------------------------------------------

def _stack_in_bb(a, what: str, chips, in_bb):
    if in_bb:
        return float(in_bb)
    if chips and a.bb:
        return parse_amount(str(chips), 1.0, True) / parse_amount(str(a.bb), 1.0, True)
    raise ValueError(f"give {what} in big blinds, or in chips together with --bb")


def cmd_latereg(a) -> int:
    """Rate a tournament for a last-minute entry that only wants the min-cash."""
    stack_bb = _stack_in_bb(a, "--stack", a.stack, a.stack_bb)
    avg_bb = None
    if a.avg_bb or (a.avg and a.bb):
        avg_bb = _stack_in_bb(a, "--avg", a.avg, a.avg_bb)
    if avg_bb is None and not a.entries:
        raise ValueError("give --entries (total entries) or the average stack (--avg-bb, or --avg with --bb)")
    hpl = a.level_min * L.HANDS_PER_MINUTE if a.level_min else None
    if a.paid is None and a.levels_left is None:
        raise ValueError("give --paid, or --levels-left for a Day 1 flight that ends at a fixed level")
    sc = L.scout(stack_bb, a.left, a.paid, entrants=a.entries, avg_bb=avg_bb, speed=a.speed, players=a.players,
                 hands_per_level=hpl, callers=a.callers, buyin=a.buyin, fee=a.fee, min_cash=a.min_cash,
                 bounty_share=a.bounty, levels_left=a.levels_left, ante=a.ante)
    _out(L.describe(sc))
    if a.chart and sc.plan:
        _out()
        _out(f"All-in ranges at entry ({stack_bb:.0f}bb), folded to you:")
        for seat, text in L.chart(sc.plan, 0, stack_bb).items():
            _out(f"  {seat:<6} {text}")
    return 0


def cmd_latereg_safe(a) -> int:
    """The sit-out signal: is the stack big enough to fold into the money?"""
    stack, avg, left, paid = a.stack, a.avg, a.left, a.paid
    if None in (stack, avg, left, paid) and S.exists():
        st = _need_state()
        stack = stack if stack is not None else S.hero_stack(st)
        avg = avg if avg is not None else S.avg_stack(st)
        left = left if left is not None else st["tournament"].get("remaining")
        paid = paid if paid is not None else S.paid_places(st)
    if None in (stack, avg, left, paid):
        raise ValueError("need --stack, --avg, --left and --paid (or a tracked tournament with them)")
    stack, avg = parse_amount(str(stack), 1.0, True), parse_amount(str(avg), 1.0, True)
    _out(L.describe_zone(stack, avg, int(left), int(paid)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="poker_coach", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="start tracking a new tournament")
    p.add_argument("--name")
    p.add_argument("--buyin", type=float)
    p.add_argument("--entrants", type=int)
    p.add_argument("--remaining", type=int)
    p.add_argument("--paid", type=int)
    p.add_argument("--start-stack", dest="start_stack", type=float)
    p.add_argument("--prize-pool", dest="prize_pool", type=float)
    p.add_argument("--seats", type=int, default=9)
    p.add_argument("--goal", choices=S.GOALS, default="itm")
    p.add_argument("--pace", choices=list(S.SEC_PER_HAND), default="online")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("sync", help="merge a table snapshot (JSON) read from a picture")
    p.add_argument("json", nargs="?")
    p.add_argument("--file")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("set", help="set fields: bb=200 sb=100 ante=25 button=4 hero=6 remaining=310 ...")
    p.add_argument("pairs", nargs="+")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("seat", help="add or edit a seat")
    p.add_argument("seat", type=int)
    p.add_argument("name", nargs="?")
    p.add_argument("stack", nargs="?")
    p.add_argument("--type")
    p.add_argument("--away", action="store_true")
    p.add_argument("--hero", action="store_true")
    p.set_defaults(fn=cmd_seat)

    p = sub.add_parser("stack", help="update stacks: <player> <stack> [...]")
    p.add_argument("items", nargs="+")
    p.set_defaults(fn=cmd_stack)

    p = sub.add_parser("bust", help="a player at the table is eliminated")
    p.add_argument("who", nargs="+")
    p.set_defaults(fn=cmd_bust)

    p = sub.add_parser("away", help="mark players as sitting out")
    p.add_argument("who", nargs="+")
    p.set_defaults(fn=_status_cmd("away"))
    p = sub.add_parser("back", help="mark players as back")
    p.add_argument("who", nargs="+")
    p.set_defaults(fn=_status_cmd("active"))

    p = sub.add_parser("type", help="tag a player: " + ", ".join(PLAYER_TYPES))
    p.add_argument("who")
    p.add_argument("type")
    p.set_defaults(fn=cmd_type)

    p = sub.add_parser("note", help="add a note on a player")
    p.add_argument("who")
    p.add_argument("text", nargs="+")
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("button", help="set the button seat, or 'next'")
    p.add_argument("seat")
    p.set_defaults(fn=cmd_button)

    p = sub.add_parser("next", help="new hand: advance the button, optionally update stacks")
    p.add_argument("items", nargs="*")
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("payouts", help="payout table: '1:500 2:300 3:200 4-6:100' or 'auto'")
    p.add_argument("values", nargs="+")
    p.set_defaults(fn=cmd_payouts)

    p = sub.add_parser("show", help="print the table")
    p.add_argument("--log", type=int, default=0)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("undo", help="revert the last change")
    p.set_defaults(fn=cmd_undo)

    p = sub.add_parser("log", help="add a free-text event, or list recent events")
    p.add_argument("text", nargs="*")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("advise", help="decision using the tracked table")
    p.add_argument("--hand", required=True, help="AhKd, or AKo / AKs / 77 preflop")
    p.add_argument("--facing", help="action before you: 'UTG raise 2.2bb, CO call' / 'hero raise 500, BB allin'")
    p.add_argument("--goal", choices=S.GOALS)
    p.add_argument("--stack", help="your chips behind right now (postflop; default: tracked stack "
                                   "minus your share of the pot)")
    p.add_argument("--villain", help="main opponent (seat / name / position) for stack, type and ICM")
    _add_postflop_args(p)
    p.set_defaults(fn=cmd_advise)

    p = sub.add_parser("quick", help="one-off decision without a tracked table (amounts in bb)")
    p.add_argument("--hand", required=True)
    p.add_argument("--stack", type=float, required=True, help="your stack in big blinds")
    p.add_argument("--pos", required=True, help="UTG, UTG+1, MP, LJ, HJ, CO, BTN, SB, BB")
    p.add_argument("--players", type=int, default=9)
    p.add_argument("--facing")
    p.add_argument("--villain-stack-bb", dest="villain_stack_bb", type=float,
                   help="everyone else's stack in bb (default: same as yours)")
    p.add_argument("--no-ante", action="store_true")
    p.add_argument("--remaining", type=int)
    p.add_argument("--paid", type=int)
    p.add_argument("--entrants", type=int)
    p.add_argument("--avg-bb", dest="avg_bb", type=float)
    p.add_argument("--goal", choices=S.GOALS, default="itm")
    _add_postflop_args(p)
    p.set_defaults(fn=cmd_quick)

    p = sub.add_parser("equity", help="equity of a hand against one or more ranges")
    p.add_argument("--hand", required=True)
    p.add_argument("--vs", action="append", required=True)
    p.add_argument("--board")
    p.add_argument("--iters", type=int, default=20000)
    p.set_defaults(fn=cmd_equity)

    p = sub.add_parser("range", help="size of a range, optionally as a grid")
    p.add_argument("notation", nargs="+")
    p.add_argument("--grid", action="store_true")
    p.set_defaults(fn=cmd_range)

    p = sub.add_parser("chart", help="reference chart: push or open")
    p.add_argument("kind", choices=["push", "open"])
    p.add_argument("--pos", required=True)
    p.add_argument("--stack", type=float, default=10.0)
    p.add_argument("--players", type=int, default=9)
    p.add_argument("--no-ante", action="store_true")
    p.set_defaults(fn=cmd_chart)

    p = sub.add_parser("icm", help="ICM value and risk premiums at the tracked table")
    p.add_argument("--goal", choices=S.GOALS)
    p.set_defaults(fn=cmd_icm)

    def aof_common(q, hand: bool) -> None:
        if hand:
            q.add_argument("--hand", required=True, help="AKo, 77, A5s or exact cards")
        q.add_argument("--players", type=int, default=4, help="players dealt in (2-4)")
        q.add_argument("--stack", type=float, default=8.0, help="stack in big blinds (default 8)")
        q.add_argument("--mode", choices=["cash", "tournament"], default="cash",
                       help="cash = 0.1bb fee per hand, 8bb cap; tournament = no fee, up to 20bb")
        q.add_argument("--vs", choices=["solid", "loose", "very-loose"], default="solid",
                       help="opponents: solid (the solved table), loose (they call 1.5x too wide) "
                            "or very-loose (2x); cash only")

    p = sub.add_parser("aof", help="All-In or Fold: shove or fold this hand")
    aof_common(p, True)
    p.add_argument("--pos", required=True, help="your seat: CO, BTN, SB, BB")
    p.add_argument("--shoved", help="players already all-in, e.g. 'CO' or 'CO,BTN'")
    p.add_argument("--stacks", help="unequal stacks, e.g. 'CO=8,BTN=6.5,SB=8,BB=5'")
    p.set_defaults(fn=cmd_aof)

    p = sub.add_parser("aof-chart", help="All-In or Fold: the whole range for one situation")
    aof_common(p, False)
    p.add_argument("--pos", required=True)
    p.add_argument("--shoved")
    p.set_defaults(fn=cmd_aof_chart)

    p = sub.add_parser("aof-sheet", help="All-In or Fold: every range of a format, as Markdown")
    aof_common(p, False)
    p.set_defaults(fn=cmd_aof_sheet)

    p = sub.add_parser("aof-quiz", help="All-In or Fold: drill random spots")
    aof_common(p, False)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--seed", type=int)
    p.add_argument("--print", action="store_true", help="print questions and answers instead of asking")
    p.set_defaults(fn=cmd_aof_quiz)

    p = sub.add_parser("aof-compare", help="All-In or Fold: each table against each kind of opponent")
    p.set_defaults(fn=cmd_aof_compare)

    p = sub.add_parser("latereg", help="late-registration min-cash plan: rate a tournament before entering")
    p.add_argument("--stack-bb", type=float, help="the starting stack in big blinds at the level you would enter")
    p.add_argument("--stack", help="... or the starting stack in chips, with --bb")
    p.add_argument("--bb", help="big blind at the level you would enter")
    p.add_argument("--left", type=int, required=True, help="players still in")
    p.add_argument("--paid", type=int, help="places paid")
    p.add_argument("--levels-left", type=float,
                   help="Day 1 flight that pays everyone who survives it: blind levels still to play")
    p.add_argument("--ante", choices=["player", "bb"], default="player",
                   help="player = everyone antes each hand (GGPoker); bb = big-blind ante")
    p.add_argument("--entries", type=int, help="total entries so far")
    p.add_argument("--avg-bb", type=float, help="average stack in big blinds")
    p.add_argument("--avg", help="... or the average stack in chips, with --bb")
    p.add_argument("--speed", choices=list(L.SPEEDS), default="turbo")
    p.add_argument("--level-min", type=float, help="minutes per blind level (overrides the speed's default)")
    p.add_argument("--players", type=int, default=8, help="seats per table")
    p.add_argument("--buyin", type=float, default=1.0, help="the part of the price that goes to the prize pool")
    p.add_argument("--fee", type=float, default=0.0, help="the fee on top")
    p.add_argument("--min-cash", type=float, help="smallest prize, same currency as --buyin")
    p.add_argument("--bounty", type=float, default=0.0, help="share of the prize pool paid as bounties (0.5 for PKO)")
    p.add_argument("--callers", choices=list(L.CALLERS), default="normal", help="how light the table calls all-ins")
    p.add_argument("--chart", action="store_true", help="also print the all-in ranges by seat at entry")
    p.set_defaults(fn=cmd_latereg)

    p = sub.add_parser("latereg-safe", help="sit-out signal: can this stack fold into the money?")
    p.add_argument("--stack", help="your stack in chips (default: the tracked table)")
    p.add_argument("--avg", help="average stack in chips")
    p.add_argument("--left", type=int, help="players still in")
    p.add_argument("--paid", type=int, help="places paid")
    p.set_defaults(fn=cmd_latereg_safe)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ValueError as exc:
        return _fail(str(exc))
    except BrokenPipeError:
        return 0


_unused = (HandSetup, solve_open_shove)
