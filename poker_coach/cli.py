"""Command line for the poker coach.

    python -m poker_coach <command> [options]

Table tracking:  new, sync, set, seat, stack, bust, away, back, type, note,
                 button, next, payouts, show, undo, log
Decisions:       advise (uses the tracked table), quick (no table needed)
All-in or fold:  binary, binary-chart, binary-sheet (a whole tournament on two moves)
Spins:           spin, spin-sheet, spin-odds (3-player winner-take-all games)
Sheet:           tag-sheet (every preflop situation as text, for 6, 7 or 8 players)
Live reader:     live-setup, live-teach, live, live-test, live-app (play-money tables only: reads the screen, suggests)
Table app:       app (a page in the browser: you enter the table by hand, the coach answers; study and play money)
Tools:           equity, range, chart, icm
"""

from __future__ import annotations

import argparse
import json
import sys

from . import aof as A
from . import binary as BN
from . import latereg as L
from . import spin as SP
from . import tag as TG
from . import state as S
from .cards import (HANDS, cards_str, format_range, parse_cards, parse_hand, range_combos,
                    range_pct)
from .equity import eq_vs_range, hand_equity
from .icm import Prizes, default_payouts
from .postflop import PostflopSpot, Villain, advise_postflop, parse_line, range_from_spec
from .preflop import Spot, advise, parse_actions, parse_amount, pos_to_index, quick_spot
from .pushfold import HandSetup, nash_push_range, solve_open_shove
from .ranges import PLAYER_TYPES, norm_type, parse, position_name, rfi_range, set_style


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
        with open(a.file, encoding="utf-8") as fh:      # a snapshot is UTF-8 on every system: "José" stays José
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

# Up to this many paid places still to reach, an ICM value is worked out by the integral.  With more it takes
# seconds (quick, 9bb on the button: 8 s an answer at 60,000 entrants, 34 s at 150,000), and a decision has a
# clock running.  It is the table app's cap (``app.advice.PRIZE_PLACES``; a test keeps the two equal).
PRIZE_PLACES = 1000


def _large_field(prizes: Prizes, table: int) -> Prizes:
    """The prize model for a decision: in closed form when the field is very large.

    The condition is the table app's (``app.advice.thinned_prizes``): more than ``PRIZE_PLACES`` paid places
    that somebody can still finish in.  ``table`` is the number of players at hero's table, who are not part
    of ``prizes.field_n``.  The model is the same (``icm.large_field_equity``: the real ladder, field and
    places to go), so the answers of a smaller field do not move, and those of a larger one by the last
    printed digit at most.
    """
    reachable = min(len(prizes.raw_payouts), table + prizes.field_n)
    if prizes.chip_ev or prizes.large or reachable <= PRIZE_PLACES:
        return prizes
    return Prizes(prizes.raw_payouts, field_n=prizes.field_n, field_stack=prizes.field_stack,
                  itm_bonus=prizes.itm_bonus, label=prizes.label, large=True)


def _field_prizes(prizes: Prizes) -> Prizes:
    """What the opponents play for: the real prizes, without hero's bonus for cashing, by the same model."""
    if prizes.chip_ev:
        return Prizes()
    return Prizes(prizes.raw_payouts, prizes.field_n, prizes.field_stack, large=prizes.large)


def _state_spot(st: dict, a) -> tuple[Spot, list[int]]:
    setup, order = S.hand_setup(st)
    hero_seat = st["table"].get("hero")
    if hero_seat is None or hero_seat not in order:
        raise ValueError("hero's seat is not set (use: set hero=<seat>)")
    hero = order.index(hero_seat)
    hand, cards = parse_hand(a.hand)
    seats = [S.seats(st)[str(s)] for s in order]
    prizes = _large_field(S.build_prizes(st, a.goal), len(S.occupied(st)))
    field = _field_prizes(prizes)
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
            prizes = _large_field(S.build_prizes(st, a.goal), len(S.occupied(st)))

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
        set_style(getattr(a, "style", None) or "tag")
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
                prizes = _large_field(Prizes(pays, field_n, avg, itm_bonus=bonus,
                                             label=f"ICM ({a.remaining} left, {len(pays)} paid"
                                                   + (", ITM-first" if bonus else "") + ")"), a.players)
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
            spot.field_prizes = _field_prizes(prizes)
        if a.villain_type:
            # tag the first player mentioned in --facing, else everyone behind
            acted = [act.idx for act in spot.acts if act.idx != spot.hero]
            targets = acted[:1] if acted else list(range(spot.hero + 1, spot.setup.n))
            for i in targets:
                spot.types[i] = norm_type(a.villain_type[0])
        if getattr(a, "opponents", None):
            spot.types = [a.opponents] * spot.setup.n
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
    prizes = _large_field(S.build_prizes(st, a.goal), len(S.occupied(st)))
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


def cmd_latereg_chart(a) -> int:
    """The charts of the plan: wide, short-stack and tight, by seat."""
    charts = L.reference_charts(a.players, 10.0, a.callers, a.speed)
    titles = {"wide": "WIDE chart: under 20% of the sit-out line, stack of 6 big blinds or more",
              "short": "SHORT-STACK chart: under 20% of the line, stack under 6 big blinds",
              "tight": "TIGHT chart: 20% to 50% of the sit-out line"}
    for name in ("wide", "short", "tight"):
        ch = charts[name]
        _out(titles[name])
        for seat, w in ch["open"].items():
            _out(f"  {seat:<6} {range_pct(w):4.1f}%  {format_range(w) or 'nothing'}")
        _out(f"  over a raise from the cutoff or later: {format_range(ch['late']) or 'nothing'}")
        _out(f"  over an earlier raise, or an all-in:   {format_range(ch['early']) or 'nothing'}")
        _out()
    _out("50% to 100% of the line: fold everything; only aces, when nobody has raised.")
    _out("100% or more: sit out.  Stack over 20 big blinds: all-in with QQ+, AK only.")
    return 0


def _binary_seat(name: str, players: int) -> int:
    """Players still to act behind a named seat at a table of ``players`` (0 = big blind)."""
    i = pos_to_index(name, players)
    if i is None:
        raise ValueError(f"unknown position {name!r} at a {players}-handed table "
                         f"(seats: {', '.join(BN.seats(players).values())}, BB)")
    return players - 1 - i


def cmd_binary(a) -> int:
    """One all-in or fold decision, from the tables of the sheet."""
    hand, _cards = parse_hand(a.hand)
    BN.table(a.players)
    n_behind = _binary_seat(a.pos, a.players)
    facing, seat, size = "", None, None
    if a.facing:
        acts = []
        for part in a.facing.split(","):
            words = part.split()
            if len(words) < 2:
                raise ValueError("--facing is '<seat> raise' or '<seat> allin [big blinds]', "
                                 "with a comma between two players")
            verb = words[1].lower().replace("-", "")
            if verb in ("raise", "raises", "open", "opens", "minraise"):
                kind = "raise"
            elif verb in ("allin", "shove", "shoves", "jam", "jams", "push"):
                kind = "allin"
            else:
                raise ValueError(f"--facing: {words[1]!r} is neither a raise nor an all-in")
            amount = float(words[2].lower().replace("bb", "")) if len(words) > 2 else None
            acts.append((_binary_seat(words[0], a.players), kind, amount))
        if len(acts) == 1:
            seat, facing, size = acts[0]
            size = size if facing == "allin" else None
        elif any(kind == "allin" for _s, kind, _a in acts):
            # two all-ins, or a raise and an all-in: one row covers them
            facing = "allins"
            sizes = [amount for _s, kind, amount in acts if kind == "allin" and amount]
            size = max(sizes) if sizes else None
        else:
            raise ValueError("--facing: two raises and no all-in is not on the sheet: AA and KK only")
    action, why = BN.decide(hand, n_behind, a.stack, a.stage, facing, seat, size, a.bubble, a.players)
    seat_label = BN.seat_name(n_behind, a.players)
    _out(f">>> {action}   {HANDS[hand]} in {seat_label} with {a.stack:g}bb, {BN.STAGE_NAMES[BN._stage(a.stage)]}"
         + ("" if a.players == BN.PLAYERS else f", {a.players}-handed"))
    _out(f"  why: {why}")
    if not facing and n_behind:
        other = "money" if BN._stage(a.stage) == "before" else "before"
        lim = BN.limit(other, n_behind, hand, a.players)
        _out(f"  num: {seat_label} moves all-in with {BN.width(a.stage, n_behind, a.stack, a.players):.0f}% of hands at "
             f"this stack; {BN.STAGE_NAMES[other]} this hand goes to {lim or 'no'}{'bb' if lim else ' stack'}")
    return 0


def cmd_binary_chart(a) -> int:
    BN.table(a.players)
    seats = [_binary_seat(a.pos, a.players)] if a.pos else list(BN.seats(a.players))
    for k, nb in enumerate(seats):
        if nb == 0:
            raise ValueError("the big blind has no first-in chart: with no raise it checks")
        if k:
            _out()
        _out(BN.grid_text(a.stage, nb, a.players))
    return 0


def cmd_binary_sheet(a) -> int:
    _out(BN.sheet_text(a.players))
    return 0


def _spin_spot(a) -> str:
    """The row of the spin tables for a seat and what happened before it."""
    pos = a.pos.upper().replace("BUTTON", "BTN")
    players = a.players
    if players not in (2, 3):
        raise ValueError("spins are for 3 players, or 2 when one is out (--players 2)")
    if pos == "BTN" and players == 2:
        pos = "SB"                                    # heads-up the button is the small blind
    if pos not in ("BTN", "SB", "BB"):
        raise ValueError("--pos is BTN, SB or BB")
    shoved = sorted(w.upper() for w in (a.shoved or "").replace(",", " ").split())
    facing = (a.facing or "").lower().split()
    if facing:
        if len(facing) < 2 or facing[1] not in ("limp", "limps", "call", "raise", "raises", "minraise", "open"):
            raise ValueError("--facing is '<seat> limp' or '<seat> raise'")
        who, what = facing[0].upper(), ("limp" if facing[1] in ("limp", "limps", "call") else "raise")
        if players == 2:
            key = f"hu_bb_vs_{what}"
        else:
            key = {"SB": "sb", "BB": "bb"}.get(pos, "") + f"_vs_{who.lower()}_{what}"
        if key not in SP.OPENERS or pos == "BTN":
            raise ValueError(f"no row for {pos} facing '{a.facing}' with {players} players")
        return key
    if players == 2:
        if pos == "SB" and not shoved:
            return "hu_sb"
        if pos == "BB" and shoved == ["SB"]:
            return "hu_bb"
        raise ValueError("heads-up: SB first to act, or BB with --shoved SB (a big blind nobody raised has no decision)")
    key = {("BTN", ()): "btn", ("SB", ()): "sb", ("SB", ("BTN",)): "sb_vs_btn", ("BB", ("BTN",)): "bb_vs_btn",
           ("BB", ("SB",)): "bb_vs_sb", ("BB", ("BTN", "SB")): "bb_vs_both"}.get((pos, tuple(shoved)))
    if key is None:
        raise ValueError(f"no decision for {pos} with all-ins from {', '.join(shoved) or 'nobody'}")
    return key


def cmd_spin(a) -> int:
    """One all-in or fold decision in a 3-player winner-take-all game."""
    hand, _cards = parse_hand(a.hand)
    spot = _spin_spot(a)
    action, why = SP.decide(hand, spot, a.stack, a.vs)
    _out(f">>> {action}   {HANDS[hand]}, {a.stack:g}bb effective, {'heads-up' if a.players == 2 else 'three players'}")
    _out(f"  why: {why}")
    if spot in SP.SPOTS:
        _out(f"  num: this seat plays {SP.width(spot, a.stack, a.vs):.0f}% of hands here"
             + ("" if SP._profile(a.vs) != "solid" else
                f"; against players who call too wide, {SP.width(spot, a.stack, 'loose'):.0f}%"))
    return 0


def cmd_spin_sheet(a) -> int:
    _out(SP.sheet_text(a.vs))
    return 0


def cmd_spin_odds(a) -> int:
    """What a win rate is worth in Spin & Gold, and what the tables won in the simulation."""
    first, second, third = SP.average_prizes()
    _out(f"Spin & Gold, 3 players, {100 * SP.FEE:.0f}% fee: the three buy-ins pay back {first + second + third:.2f} on average")
    small = sum(share for m, share, _p in SP.PRIZES if m <= 3)
    _out("  " + ", ".join(f"x{m} in {100 * share:.1f}% of games" for m, share, _p in SP.PRIZES[:5])
         + f" (x2 or x3: {100 * small:.1f}%)")
    _out(f"  break even: win {100 * SP.break_even():.1f}% of games ({100 * SP.break_even(False):.1f}% if the jackpot never comes); "
         f"an even player wins 33.3% and loses {-100 * SP.roi(1 / 3):.0f}% a game")
    for w in ([a.win / 100.0] if a.win else [0.34, 0.36, 0.38, 0.40]):
        _out(f"  win {100 * w:.0f}%: {100 * SP.roi(w):+.1f}% of a buy-in a game")
    if SP.sim():
        _out("  whole games played all-in or fold (simulation, opponents also all-in or fold):")
        for hero, label in (("sheet", "the standard table"), ("sheet-loose", "the table for loose callers")):
            cells = []
            for opp in ("solid", "loose", "vloose"):
                w = SP.simulated_win(hero, opp)
                cells.append(f"{100 * w:.1f}% against {SP.PROFILE_NAMES[opp]} ({100 * SP.simulated_roi(hero, opp):+.1f}%)")
            _out(f"    {label}: wins " + "; ".join(cells))
    return 0


def cmd_tag_sheet(a) -> int:
    """The tight-aggressive sheet for a table size: every preflop situation, as text."""
    _out(TG.sheet_text(a.players))
    return 0


def _live_config(a):
    """The saved live settings, with this command's options on top."""
    from .live.app import LiveConfig

    cfg = LiveConfig.load()
    for key in ("mode", "reader", "seats", "model", "effort", "max_px", "min_gap", "goal", "entrants", "paid",
                "buyin", "monitor", "opponents"):
        val = getattr(a, key, None)
        if val is not None:
            setattr(cfg, key, val)
    if getattr(a, "marker", None):
        cfg.markers = list(dict.fromkeys(cfg.markers + a.marker))
    if getattr(a, "no_save", False):
        cfg.save_images = False
    if cfg.mode not in ("tag", "binary", "spin"):
        raise ValueError("--mode is tag, binary or spin")
    return cfg


def cmd_live_setup(a) -> int:
    """Mark the table and every box on it once (local reader), or just the table (vision reader)."""
    from .live.app import BOOK_PATH, CONFIG_PATH, LAYOUT_PATH, setup_from_rects, setup_window
    from .live.capture import Rect

    cfg = _live_config(a)
    if a.region:
        cfg = setup_from_rects(cfg, Rect.parse(a.region), Rect.parse(a.buttons) if a.buttons else None)
        if cfg.reader == "local":
            _out("the local reader also needs every box on the table marked: run live-setup without --region")
    elif cfg.reader == "local":
        from .live.wizard import setup_local

        redo = [x.strip() for x in (a.redo or "").split(",") if x.strip()]
        try:
            done = setup_local(cfg, LAYOUT_PATH, BOOK_PATH, cfg.seats, teach=not a.no_teach, redo=redo or None)
        except ImportError as exc:
            return _fail(f"the setup needs tkinter ({exc}): install Python from python.org, or on Linux python3-tk")
        except ValueError as exc:
            return _fail(str(exc))
        if done is None:
            return _fail("setup cancelled")
        cfg = done
        from .live.local import Layout

        _out(f"saved the table to {LAYOUT_PATH}")
        for note in Layout.load(LAYOUT_PATH).advice():
            _out(f"note: {note}")
    else:
        try:
            done = setup_window(cfg)
        except ImportError as exc:
            return _fail(f"the setup window needs tkinter ({exc}); give the table as --region left,top,width,height")
        if done is None:
            return _fail("setup cancelled")
        cfg = done
    cfg.save()
    _out(f"saved to {CONFIG_PATH}: table at {cfg.region}"
         + (f", action buttons at {cfg.buttons} (reads only on your turn)" if cfg.buttons
            else " (no button area: reads when the table changes)"))
    _out("play-money markers it looks for: " + ", ".join(cfg.markers))
    return 0


def cmd_live_teach(a) -> int:
    """Label the boxes the local reader cannot read yet (from the screen, a picture or the last session)."""
    import glob
    import os

    from PIL import Image

    from .live.app import BOOK_PATH, LAYOUT_PATH, LOG_ROOT
    from .live.local import Layout, teach_items
    from .live.vision import Book
    from .live.wizard import items_from_images, teach_console, teach_window

    if not os.path.exists(LAYOUT_PATH):
        return _fail("run live-setup first: the reader needs to know where everything is")
    cfg = _live_config(a)
    layout, book = Layout.load(LAYOUT_PATH), Book.load(BOOK_PATH)
    if a.image:
        items = teach_items(Image.open(a.image).convert("RGB"), layout, book, everything=a.all)
    elif a.log is not None:
        folder = a.log
        if not folder:
            sessions = sorted(glob.glob(os.path.join(LOG_ROOT, "*")))
            if not sessions:
                return _fail("no session log yet")
            folder = sessions[-1]
        items = items_from_images(glob.glob(os.path.join(folder, "*.png")), layout, book, limit=a.limit)
    else:
        from .live.capture import Rect, dpi_aware, grab_once

        if not cfg.region:
            return _fail("run live-setup first")
        dpi_aware()
        items = teach_items(grab_once(Rect(*cfg.region), cfg.monitor), layout, book, everything=a.all)
    if not items:
        _out("nothing to teach: every box with something in it is already readable")
        _out(book.summary())
        return 0
    if a.console:
        picture = os.path.join(os.path.dirname(BOOK_PATH), "teach-box.png")
        n = teach_console(items, book, BOOK_PATH, picture)
    else:
        try:
            n = teach_window(items, book, BOOK_PATH, confirm=a.all)
        except ImportError:
            n = teach_console(items, book, BOOK_PATH, os.path.join(os.path.dirname(BOOK_PATH), "teach-box.png"))
    _out(f"learned {n} of {len(items)} boxes; saved to {BOOK_PATH}")
    _out(Book.load(BOOK_PATH).summary())
    return 0


def cmd_live_app(a) -> int:
    """The launcher window: set up, teach, start."""
    from .live.wizard import launcher

    return launcher()


def cmd_live(a) -> int:
    """Watch the table and show what the coach would do, on play-money tables only."""
    from .live.app import run

    cfg = _live_config(a)
    if a.region:
        from .live.capture import Rect

        cfg.region = Rect.parse(a.region).as_list()
    if cfg.reader == "local":
        import os

        from .live.app import LAYOUT_PATH
        if not os.path.exists(LAYOUT_PATH) or not cfg.region:
            return _fail("the local reader is not set up yet: run live-setup first (or live-app for the launcher)")
    elif not cfg.region:
        _out("no table marked yet: reading the whole screen (run live-setup to mark the table)")
    return run(cfg, window=not a.no_window)


def cmd_live_test(a) -> int:
    """Read one saved screenshot (or a saved reading) and print the reading and the suggestion."""
    from .live.app import test_once
    from .live.reader import ReadError

    if a.screen:
        from .live.capture import Rect, dpi_aware, grab_once
        from .live.wizard import check_text

        cfg = _live_config(a)
        if not cfg.region:
            return _fail("run live-setup first")
        dpi_aware()
        _out(check_text(cfg, grab_once(Rect(*cfg.region), cfg.monitor)))
        return 0
    if not (a.image or a.json):
        return _fail("give --image <screenshot>, --json <saved reading> or --screen")
    try:
        _out(test_once(_live_config(a), a.image, a.json, force=not a.turn_only, save_json=a.save_json))
    except ReadError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(f"cannot open the file: {exc}")
    return 0


def _live_options(p, setup: bool = False) -> None:
    p.add_argument("--mode", choices=("tag", "binary", "spin"), help="tag (default): tight-aggressive engine; "
                   "binary: all-in or fold tables; spin: 3-player winner-take-all")
    p.add_argument("--marker", action="append", help="text your play-money tables show (repeatable); "
                   "default: Play Money, Play chips, Practice, Free chips, Fun chips, Play for fun")
    p.add_argument("--monitor", type=int, help="screen number (default 1, the main screen)")
    p.add_argument("--reader", choices=("local", "vision"), help="local (default): reads on this computer, no "
                   "network; vision: sends the screenshot to Claude (needs an API key, costs per read)")
    p.add_argument("--seats", type=int, help="seats at the table, for the local setup (default 6)")
    if setup:
        return
    p.add_argument("--opponents", choices=("unknown", "loose", "tight", "station", "nit", "lag", "maniac"),
                   help="how the table plays (default unknown; loose for tables that call too much)")
    p.add_argument("--model", help="vision model (default claude-opus-5-5; claude-haiku-5-5 is ~40x cheaper and faster)")
    p.add_argument("--effort", choices=("low", "medium", "high"), help="reading effort (default low)")
    p.add_argument("--max-px", type=int, dest="max_px", help="long edge of the image sent (default 1600)")
    p.add_argument("--goal", choices=("itm", "balanced", "chips"), help="tournament goal (default itm)")
    p.add_argument("--entrants", type=int, help="entrants, when the table does not show them")
    p.add_argument("--paid", type=int, help="places paid, when the table does not show them")
    p.add_argument("--buyin", type=float, help="buy-in")


def app_folder(path: str | None) -> str | None:
    """``--folder`` of the table app as a full path, made if it is not there yet.

    ``None`` when the option was not given: the app then uses ``$POKER_COACH_APP`` or its
    usual folder (``model.default_folder``).  A folder that cannot be used is a ``ValueError``.
    """
    if not path:
        return None
    import os

    folder = os.path.abspath(os.path.expanduser(path))      # "~" too: the Windows shell does not expand it
    try:
        os.makedirs(folder, exist_ok=True)                  # said now, not at the first save
    except OSError as exc:                                  # a file of that name, or no right to write there
        raise ValueError(f"--folder: {folder} cannot be used ({exc})") from None
    return folder


def cmd_app(a) -> int:
    """The table app: a local page where the table is entered by hand and the coach answers."""
    from .app.server import main as serve

    options = {"port": a.port, "open_browser": not a.no_browser, "verbose": a.verbose}
    folder = app_folder(a.folder)
    if folder:                          # a folder named here wins over $POKER_COACH_APP and the usual one
        options["folder"] = folder
    if getattr(a, "public_url", None):  # behind a web server on this machine: no browser is opened here
        options["public"] = a.public_url
        options["open_browser"] = False
    try:
        return serve(**options)
    except (OSError, ValueError) as exc:        # no free port; an address that is none
        return _fail(str(exc))


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
    p.add_argument("--style", choices=("tag", "win", "tight"), default="tag",
                   help="tag: the coach's ranges (default); win and tight: the quick guide's two styles "
                        "(win has the wider rows; both test the big blind's call by what the hand realises)")
    p.add_argument("--opponents", choices=sorted(PLAYER_TYPES), help="every opponent is of this type (the quick guide's Opponents)")
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

    p = sub.add_parser("latereg-chart", help="late-registration plan: the all-in charts by seat")
    p.add_argument("--players", type=int, default=8)
    p.add_argument("--speed", choices=list(L.SPEEDS), default="turbo")
    p.add_argument("--callers", choices=list(L.CALLERS), default="normal")
    p.set_defaults(fn=cmd_latereg_chart)

    p = sub.add_parser("latereg-safe", help="sit-out signal: can this stack fold into the money?")
    p.add_argument("--stack", help="your stack in chips (default: the tracked table)")
    p.add_argument("--avg", help="average stack in chips")
    p.add_argument("--left", type=int, help="players still in")
    p.add_argument("--paid", type=int, help="places paid")
    p.set_defaults(fn=cmd_latereg_safe)

    p = sub.add_parser("binary", help="all-in or fold for a whole tournament: one decision from the tables")
    p.add_argument("--hand", required=True)
    p.add_argument("--pos", required=True, help="your seat: UTG, UTG+1, LJ, HJ, CO, BTN, SB or BB")
    p.add_argument("--players", type=int, default=BN.PLAYERS, help="players at the table: 6, 7 or 8 (default 8)")
    p.add_argument("--stack", type=float, required=True, help="your stack in big blinds (the smaller of yours and "
                                                               "the biggest stack still to act)")
    p.add_argument("--stage", default="before", help="before (the money) or money")
    p.add_argument("--facing", help="'CO raise', 'HJ allin 9' (the all-in in big blinds), or two players: "
                                    "'HJ allin 9, CO allin 12'")
    p.add_argument("--bubble", action="store_true", help="on the bubble, or a final table against a stack that covers you")
    p.set_defaults(fn=cmd_binary)

    p = sub.add_parser("binary-chart", help="all-in or fold: the deepest stack that moves all-in, hand by hand")
    p.add_argument("--pos", help="one seat (default: every seat)")
    p.add_argument("--stage", default="before", help="before (the money) or money")
    p.add_argument("--players", type=int, default=BN.PLAYERS, help="players at the table: 6, 7 or 8 (default 8)")
    p.set_defaults(fn=cmd_binary_chart)

    p = sub.add_parser("binary-sheet", help="all-in or fold: every table as text")
    p.add_argument("--players", type=int, default=BN.PLAYERS, help="players at the table: 6, 7 or 8 (default 8)")
    p.set_defaults(fn=cmd_binary_sheet)

    p = sub.add_parser("spin", help="3-player winner-take-all game: all-in or fold this hand")
    p.add_argument("--hand", required=True)
    p.add_argument("--pos", required=True, help="BTN, SB or BB (heads-up: SB is the button)")
    p.add_argument("--stack", type=float, required=True, help="effective stack in big blinds: the smaller of yours "
                                                               "and the biggest stack that can still call")
    p.add_argument("--players", type=int, default=3, help="3, or 2 when one player is out")
    p.add_argument("--shoved", help="who is all-in before you: BTN, SB or 'BTN,SB'")
    p.add_argument("--facing", help="'SB limp', 'BTN raise' or 'SB raise' (a small raise)")
    p.add_argument("--vs", default="solid", help="solid (default), loose (they call 1.5 times too wide) or very-loose")
    p.set_defaults(fn=cmd_spin)

    p = sub.add_parser("spin-sheet", help="3-player games: every table as text, three players and heads-up")
    p.add_argument("--vs", default="solid", help="solid (default), loose or very-loose")
    p.set_defaults(fn=cmd_spin_sheet)

    p = sub.add_parser("spin-odds", help="Spin & Gold: the win rate that breaks even, and what a win rate is worth")
    p.add_argument("--win", type=float, help="your share of games won, in percent")
    p.set_defaults(fn=cmd_spin_odds)

    p = sub.add_parser("tag-sheet", help="tight-aggressive tournament sheet: every preflop situation as text")
    p.add_argument("--players", type=int, default=8, help="players at the table: 6, 7 or 8 (default 8)")
    p.set_defaults(fn=cmd_tag_sheet)

    p = sub.add_parser("live-setup", help="live reader: mark the poker table and its action buttons on the screen")
    p.add_argument("--region", help="the table as left,top,width,height (instead of the setup window)")
    p.add_argument("--buttons", help="the action-button area as left,top,width,height inside the table "
                                     "(taken now: it must not be your turn)")
    p.add_argument("--no-teach", action="store_true", help="local reader: do not ask what the boxes show at the end")
    p.add_argument("--redo", help="local reader: mark only these boxes again, e.g. pot,s3_bet,hero1 "
                                  "(marker, buttons, hero1-2, board1-5, pot, players_left, button_tpl, backs_tpl, "
                                  "s<seat>_stack/_bet/_button/_cards)")
    _live_options(p, setup=True)
    p.set_defaults(fn=cmd_live_setup)

    p = sub.add_parser("live-teach", help="live reader: label what the local reader cannot read yet")
    p.add_argument("--image", help="a screenshot of the table (default: the screen now)")
    p.add_argument("--log", nargs="?", const="", help="the screenshots of a session folder (default: the last one)")
    p.add_argument("--all", action="store_true", help="ask about every box, not only the unknown ones")
    p.add_argument("--limit", type=int, default=40, help="with --log: at most this many questions (default 40)")
    p.add_argument("--console", action="store_true", help="ask in the terminal instead of a window")
    _live_options(p, setup=True)
    p.set_defaults(fn=cmd_live_teach)

    p = sub.add_parser("live-app", help="live reader: the launcher window (set up, teach, start)")
    p.set_defaults(fn=cmd_live_app)

    p = sub.add_parser("live", help="live reader for play-money tables: reads the screen and suggests (never clicks)")
    p.add_argument("--region", help="the table as left,top,width,height (default: from live-setup)")
    p.add_argument("--min-gap", type=float, dest="min_gap", help="without a button area: seconds between reads (default 4)")
    p.add_argument("--no-window", action="store_true", help="print suggestions in the terminal (Enter = read now)")
    p.add_argument("--no-save", action="store_true", help="do not keep the screenshots in the session log")
    _live_options(p)
    p.set_defaults(fn=cmd_live)

    p = sub.add_parser("live-test", help="live reader: read one saved screenshot (or reading) and print the suggestion")
    p.add_argument("--image", help="a screenshot of a table")
    p.add_argument("--screen", action="store_true", help="read the table on the screen now and print what it sees")
    p.add_argument("--json", help="a saved reading (JSON) instead of a screenshot")
    p.add_argument("--save-json", help="also write the reading to this file")
    p.add_argument("--turn-only", action="store_true", help="suggest only if the screenshot shows your action buttons")
    _live_options(p)
    p.set_defaults(fn=cmd_live_test)

    p = sub.add_parser("app", help="table app: enter the table by hand in the browser, the coach answers "
                                   "(this computer only; nothing reads the screen)")
    p.add_argument("--port", type=int, default=8765, help="port on this computer (default 8765; the next free one if it is taken)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser: only print the address")
    p.add_argument("--folder", help="where the sessions are saved (default: tournament/app in this folder, "
                                    "or $POKER_COACH_APP; the packaged program: PokerCoach/app in the home folder)")
    p.add_argument("--verbose", action="store_true", help="log every request, and the coach's errors in full")
    p.add_argument("--public-url", metavar="URL",
                   help="on a server of your own: the address a web server on the same machine answers under "
                        "(https://menlo.bet/coach/). The program then answers what that web server passes on. "
                        "It has no login: the web server must ask for one")
    p.set_defaults(fn=cmd_app)
    return ap


def main(argv=None) -> int:
    try:
        # A name the console's code page lacks is printed with an escape, not with a crash
        # (Windows, when the output is piped: "charmap codec can't encode character").
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError, OSError):       # no console, or a stream that is not a text file
        pass
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ValueError as exc:
        return _fail(str(exc))
    except BrokenPipeError:
        return 0


_unused = (HandSetup, solve_open_shove)
