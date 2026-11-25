"""Tournament state: who sits where, stacks, blinds, how far the money is.

The state lives in one JSON file (``tournament/current.json`` by default, or
``$POKER_COACH_STATE``).  Every change keeps a few undo snapshots, and starting
a new tournament archives the old file.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from datetime import datetime

from .icm import Prizes, default_payouts
from .pushfold import HandSetup
from .ranges import norm_type, position_name

if getattr(sys, "frozen", False):          # the packaged program keeps its files in the home folder
    ROOT = os.path.join(os.path.expanduser("~"), "PokerCoach")
    STATE_PATH = os.environ.get("POKER_COACH_STATE") or os.path.join(ROOT, "current.json")
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    STATE_PATH = os.environ.get("POKER_COACH_STATE") or os.path.join(ROOT, "tournament", "current.json")
MAX_UNDO = 15
GOALS = ("itm", "balanced", "chips")
SEC_PER_HAND = {"online": 55, "fast": 35, "live": 120}


def _now() -> float:
    return time.time()


def blank_state() -> dict:
    return {
        "version": 1,
        "created": _now(),
        "tournament": {"name": "", "buyin": None, "entrants": None, "remaining": None,
                       "paid": None, "payouts": None, "prize_pool": None,
                       "start_stack": None, "avg_stack": None, "total_chips": None},
        "level": {"sb": None, "bb": None, "ante": 0, "bb_ante": 0, "number": None},
        "table": {"max_seats": 9, "button": None, "hero": None, "seats": {}},
        "config": {"goal": "itm", "pace": "online"},
        "history": [],
        "log": [],
        "undo": [],
    }


def load(path: str | None = None) -> dict:
    path = path or STATE_PATH
    if not os.path.exists(path):
        return blank_state()
    with open(path) as fh:
        state = json.load(fh)
    base = blank_state()
    for key, val in base.items():
        if key not in state:
            state[key] = val
        elif isinstance(val, dict):
            for k2, v2 in val.items():
                state[key].setdefault(k2, v2)
    return state


def save(state: dict, path: str | None = None) -> None:
    path = path or STATE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, path)


def exists(path: str | None = None) -> bool:
    return os.path.exists(path or STATE_PATH)


def checkpoint(state: dict) -> None:
    """Remember the current state so the next change can be undone."""
    snap = {k: copy.deepcopy(v) for k, v in state.items() if k != "undo"}
    state.setdefault("undo", []).append(snap)
    del state["undo"][:-MAX_UNDO]


def undo(state: dict) -> dict | None:
    if not state.get("undo"):
        return None
    snaps = state["undo"]
    prev = snaps.pop()
    prev["undo"] = snaps
    return prev


def archive(path: str | None = None) -> str | None:
    path = path or STATE_PATH
    if not os.path.exists(path):
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(os.path.dirname(path), f"archive-{stamp}.json")
    os.replace(path, dest)
    return dest


def log(state: dict, msg: str) -> None:
    state.setdefault("log", []).append({"t": _now(), "msg": msg})
    del state["log"][:-400]


# --------------------------------------------------------------------------
# Seats
# --------------------------------------------------------------------------

def seats(state: dict) -> dict:
    return state["table"]["seats"]


def occupied(state: dict) -> list[int]:
    """Seat numbers holding a player who is dealt in (active or sitting out)."""
    out = []
    for key, s in seats(state).items():
        if s and s.get("status", "active") in ("active", "away") and (s.get("stack") or 0) > 0:
            out.append(int(key))
    return sorted(out)


def find_seat(state: dict, who) -> int | None:
    """Resolve a seat number, ``s3``/``seat3``, ``hero`` or a (partial) player name."""
    if who is None:
        return None
    text = str(who).strip()
    low = text.lower()
    if low in ("hero", "me", "i"):
        return state["table"].get("hero")
    for prefix in ("seat", "s", "#"):
        if low.startswith(prefix) and low[len(prefix):].isdigit():
            return int(low[len(prefix):])
    if low.isdigit():
        return int(low)
    exact = [int(k) for k, s in seats(state).items() if s and s.get("name", "").lower() == low]
    if exact:
        return exact[0]
    part = [int(k) for k, s in seats(state).items() if s and low and low in s.get("name", "").lower()]
    return part[0] if len(part) == 1 else None


def set_seat(state: dict, seat: int, name: str | None = None, stack: float | None = None,
             status: str | None = None, ptype: str | None = None) -> dict:
    key = str(int(seat))
    cur = seats(state).get(key) or {"name": f"Seat{seat}", "stack": 0, "status": "active",
                                    "type": "unknown", "notes": []}
    if name is not None:
        cur["name"] = str(name)
    if stack is not None:
        cur["stack"] = float(stack)
    if status is not None:
        cur["status"] = status
    if ptype is not None:
        cur["type"] = norm_type(ptype)
    seats(state)[key] = cur
    state["table"]["max_seats"] = max(state["table"].get("max_seats") or 0, int(seat))
    return cur


def remove_seat(state: dict, seat: int, reason: str = "busted") -> str | None:
    key = str(int(seat))
    cur = seats(state).pop(key, None)
    if not cur:
        return None
    log(state, f"{cur.get('name', key)} (seat {seat}) {reason} with {cur.get('stack', 0):,.0f}")
    return cur.get("name", key)


def next_occupied(state: dict, seat: int) -> int | None:
    occ = occupied(state)
    if not occ:
        return None
    for s in occ:
        if s > seat:
            return s
    return occ[0]


def advance_button(state: dict) -> int | None:
    btn = state["table"].get("button")
    occ = occupied(state)
    if not occ:
        return None
    nxt = next_occupied(state, btn) if btn is not None else occ[0]
    state["table"]["button"] = nxt
    return nxt


def action_order(state: dict) -> list[int]:
    """Seat numbers in preflop acting order: first to act ... SB, BB."""
    occ = occupied(state)
    n = len(occ)
    if n < 2:
        return occ
    btn = state["table"].get("button")
    if btn is None:
        btn = occ[-1]
    # seats clockwise starting just after the button
    after = [s for s in occ if s > btn] + [s for s in occ if s <= btn]
    if n == 2:
        # heads-up: the button is the small blind and acts first preflop
        btn_seat = btn if btn in occ else after[-1]
        other = [s for s in occ if s != btn_seat][0]
        return [btn_seat, other]
    sb, bb = after[0], after[1]
    return after[2:] + [sb, bb]


def positions(state: dict) -> dict[int, str]:
    order = action_order(state)
    n = len(order)
    return {seat: position_name(n - 1 - i, n) for i, seat in enumerate(order)}


# --------------------------------------------------------------------------
# Derived tournament facts
# --------------------------------------------------------------------------

def blinds(state: dict) -> tuple[float, float, float, float]:
    lv = state["level"]
    bb = float(lv.get("bb") or 0)
    sb = float(lv.get("sb") or (bb / 2 if bb else 0))
    return sb, bb, float(lv.get("ante") or 0), float(lv.get("bb_ante") or 0)


def orbit_cost(state: dict) -> float:
    sb, bb, ante, bb_ante = blinds(state)
    n = max(2, len(occupied(state)))
    return sb + bb + ante * n + bb_ante


def hero_stack(state: dict) -> float | None:
    h = state["table"].get("hero")
    s = seats(state).get(str(h)) if h is not None else None
    return float(s["stack"]) if s else None


def total_chips(state: dict) -> float | None:
    t = state["tournament"]
    if t.get("total_chips"):
        # fixed when an average stack and a player count came from the same lobby view;
        # it also covers re-entries and add-ons, which entrants x starting stack misses
        return float(t["total_chips"])
    if t.get("entrants") and t.get("start_stack"):
        return float(t["entrants"]) * float(t["start_stack"])
    return None


def avg_stack(state: dict) -> float | None:
    t = state["tournament"]
    tot = total_chips(state)
    if tot and t.get("remaining"):
        return tot / float(t["remaining"])
    if t.get("avg_stack"):
        return float(t["avg_stack"])
    occ = occupied(state)
    if occ:
        return sum(seats(state)[str(s)]["stack"] for s in occ) / len(occ)
    return None


def paid_places(state: dict) -> int | None:
    t = state["tournament"]
    if t.get("paid"):
        return max(int(t["paid"]), len(t.get("payouts") or []))
    if t.get("payouts"):
        return len(t["payouts"])
    if t.get("entrants"):
        return len(default_payouts(int(t["entrants"])))
    return None


def payouts(state: dict) -> list[float] | None:
    """Payout table in buy-ins or currency; estimated when the real one is unknown."""
    t = state["tournament"]
    if t.get("payouts"):
        pays = [float(p) for p in t["payouts"]]
        # a lobby often shows only the top prizes: the rest get the last one listed
        pays += [pays[-1]] * max(0, int(t.get("paid") or 0) - len(pays))
        return pays
    entrants = t.get("entrants")
    if not entrants and t.get("paid"):
        entrants = max(int(t["paid"]) * 7, int(t.get("remaining") or 0))
    if not entrants:
        return None
    pool = t.get("prize_pool")
    if pool is None and t.get("buyin"):
        pool = float(t["buyin"]) * float(entrants)
    return default_payouts(int(entrants), t.get("paid"), pool)


def stage(state: dict) -> dict:
    """Where the tournament stands relative to the money."""
    t = state["tournament"]
    rem, paid = t.get("remaining"), paid_places(state)
    n_table = len(occupied(state))
    hs = hero_stack(state)
    sb, bb, _, _ = blinds(state)
    hero_bb = hs / bb if hs and bb else None
    info = {"remaining": rem, "paid": paid, "hero_bb": hero_bb, "code": "unknown",
            "label": "unknown stage", "to_money": None}
    if rem and paid:
        rem, paid = int(rem), int(paid)
        to_money = rem - paid
        info["to_money"] = to_money
        if to_money <= 0:
            if rem <= max(9, state["table"].get("max_seats") or 9) and rem <= n_table + 1:
                info.update(code="final_table", label=f"FINAL TABLE ({rem} left)")
            else:
                info.update(code="itm", label=f"IN THE MONEY ({rem} left, {paid} paid)")
        elif to_money <= max(2, round(paid * 0.04)):
            info.update(code="bubble", label=f"BUBBLE ({to_money} from the money)")
        elif rem <= paid * 1.3:
            info.update(code="near_bubble", label=f"NEAR THE BUBBLE ({to_money} from the money)")
        elif rem <= paid * 2:
            info.update(code="approach", label=f"APPROACHING THE MONEY ({to_money} to go)")
        elif rem <= paid * 3.5:
            info.update(code="middle", label="MIDDLE STAGE")
        else:
            info.update(code="early", label="EARLY STAGE")
    elif hero_bb is not None:
        info.update(code="early" if hero_bb > 60 else "middle",
                    label="stage unknown (tell me players left / places paid)")
    return info


STAGE_PLAN = {
    "early": "Deep stacks: play tight in early position, raise for value, set-mine and see cheap "
             "flops in position. No hero calls, no big bluffs; the blinds are not worth a fight yet.",
    "middle": "Antes are in: steal from CO/BTN/SB, re-shove over late opens with 12-25bb, keep your "
              "stack above 20bb. Avoid flat-calling raises out of position.",
    "approach": "Money is coming: keep stealing from players who are tightening, but stop calling "
                "off your stack without a premium. Raise-fold more, call-off less.",
    "near_bubble": "Bubble pressure is real: only get all-in against stacks that cover you with a "
                   "premium. Attack medium stacks who cannot call; do not tangle with the big stack.",
    "bubble": "BUBBLE: survival is worth more than chips. Fold marginal all-ins, never call off "
              "light, steal only where nobody can profitably call. If you are short, check the "
              "fold-to-cash clock before shoving.",
    "itm": "You are in the money: the ICM brake loosens. Go back to accumulating: steal, re-shove, "
           "and look at the next pay jump before calling off against bigger stacks.",
    "final_table": "Final table: every pay jump is large. Let shorter stacks bust, pressure "
                   "medium stacks with your opens, and call all-ins tighter than chip EV says.",
    "unknown": "Tell me players remaining and places paid and I will tune the risk for the bubble.",
}


def record_remaining(state: dict, remaining: int) -> None:
    hist = state.setdefault("history", [])
    if not hist or hist[-1]["remaining"] != remaining:
        hist.append({"t": _now(), "remaining": int(remaining)})
    del hist[:-200]


def bust_rate(state: dict) -> float | None:
    """Recent eliminations per minute across the tournament, or None if unknown."""
    hist = state.get("history") or []
    if len(hist) < 2:
        return None
    last = hist[-1]
    best = None
    for h in reversed(hist[:-1]):
        dt = (last["t"] - h["t"]) / 60.0
        if dt >= 3.0:
            best = h
            if dt >= 20.0:
                break
    if best is None:
        best = hist[0]
    dt = (last["t"] - best["t"]) / 60.0
    busts = best["remaining"] - last["remaining"]
    if dt < 1.0 or busts <= 0:
        return None
    return busts / dt


def fold_clock(state: dict) -> dict | None:
    """Can hero fold into the money?  Compares blind-out time with the bubble ETA."""
    hs = hero_stack(state)
    cost = orbit_cost(state)
    st = stage(state)
    if not hs or not cost:
        return None
    n = max(2, len(occupied(state)))
    pace = state["config"].get("pace", "online")
    sec = state["config"].get("sec_per_hand") or SEC_PER_HAND.get(pace, 55)
    orbits = hs / cost
    minutes = orbits * n * sec / 60.0
    out = {"orbits": orbits, "minutes": minutes, "eta": None, "verdict": None}
    to_money = st.get("to_money")
    rate = bust_rate(state)
    if to_money is not None and to_money > 0 and rate:
        eta = to_money / rate * 1.3  # eliminations slow down as the bubble nears
        out["eta"] = eta
        out["rate"] = rate
        if minutes > eta * 1.5:
            out["verdict"] = "safe"
        elif minutes > eta:
            out["verdict"] = "tight"
        else:
            out["verdict"] = "short"
    return out


def build_prizes(state: dict, goal: str | None = None) -> Prizes:
    """Prize model for the current moment (chip EV when the stage is unknown)."""
    goal = goal or state["config"].get("goal", "itm")
    t = state["tournament"]
    table = occupied(state)
    pays = payouts(state)
    rem = t.get("remaining")
    if goal == "chips" or not pays or not rem:
        return Prizes(label="chip EV")
    rem = max(int(rem), len(table))
    stacks = [seats(state)[str(s)]["stack"] for s in table]
    field_n = rem - len(table)
    field_stack = 0.0
    if field_n > 0:
        tot = total_chips(state)
        table_avg = sum(stacks) / len(stacks) if stacks else 1.0
        if tot:
            field_stack = max((tot - sum(stacks)) / field_n, 0.2 * table_avg)
        else:
            field_stack = table_avg
    paid = len(pays)
    bonus = 0.0
    if goal == "itm" and rem > paid:
        bonus = pays[-1]  # cashing counts double until the bubble bursts
    return Prizes(pays, field_n=field_n, field_stack=field_stack, itm_bonus=bonus,
                  label=f"ICM ({rem} left, {paid} paid" + (", ITM-first" if bonus else "") + ")")


def hand_setup(state: dict) -> tuple[HandSetup, list[int]]:
    """``HandSetup`` for the current table plus the seat number at each index."""
    order = action_order(state)
    sb, bb, ante, bb_ante = blinds(state)
    if not bb:
        raise ValueError("blinds are not set (use: set bb=... sb=...)")
    if len(order) < 2:
        raise ValueError("need at least two seated players")
    stacks = [seats(state)[str(s)]["stack"] for s in order]
    return HandSetup(stacks, sb, bb, ante, bb_ante), order


# --------------------------------------------------------------------------
# Snapshot sync (what the coach calls after reading a table picture)
# --------------------------------------------------------------------------

def _num(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    t = str(x).strip().lower().replace(",", "").replace("$", "")
    mult = 1.0
    if t.endswith("k"):
        mult, t = 1e3, t[:-1]
    elif t.endswith("m"):
        mult, t = 1e6, t[:-1]
    return float(t) * mult


def _same_player(a: str, b: str) -> bool:
    """Names read from a picture vary a little (l/1, O/0, cut-off endings)."""
    from difflib import SequenceMatcher

    x, y = a.strip().lower(), b.strip().lower()
    if x == y or (len(x) >= 4 and (x.startswith(y) or y.startswith(x))):
        return True
    return SequenceMatcher(None, x, y).ratio() >= 0.75


def apply_snapshot(state: dict, snap: dict) -> list[str]:
    """Merge a (possibly partial) table snapshot and describe what changed."""
    changes: list[str] = []
    t, lv, tb = state["tournament"], state["level"], state["table"]

    b = snap.get("blinds")
    if isinstance(b, (list, tuple)):
        b = {"sb": b[0], "bb": b[1], **({"ante": b[2]} if len(b) > 2 else {})}
    b = dict(b or {})
    for k in ("sb", "bb", "ante", "bb_ante"):
        if k in snap:
            b[k] = snap[k]
    if b:
        old = (lv.get("sb"), lv.get("bb"), lv.get("ante"), lv.get("bb_ante"))
        for k in ("sb", "bb", "ante", "bb_ante"):
            if k in b and b[k] is not None:
                lv[k] = _num(b[k])
        if "bb" in b and "sb" not in b and lv.get("sb") is None:
            lv["sb"] = lv["bb"] / 2
        new = (lv.get("sb"), lv.get("bb"), lv.get("ante"), lv.get("bb_ante"))
        if new != old:
            ante_txt = f" ante {lv['ante']:,.0f}" if lv.get("ante") else ""
            ante_txt += f" bb-ante {lv['bb_ante']:,.0f}" if lv.get("bb_ante") else ""
            changes.append(f"blinds now {lv['sb']:,.0f}/{lv['bb']:,.0f}{ante_txt}")
    if "level" in snap and snap["level"] is not None:
        lv["number"] = snap["level"]

    for k in ("name", "buyin", "entrants", "paid", "prize_pool", "start_stack", "avg_stack"):
        if k in snap and snap[k] is not None:
            val = snap[k] if k == "name" else _num(snap[k])
            if t.get(k) != val:
                t[k] = val
                if k in ("entrants", "paid"):
                    t[k] = int(val)
                    changes.append(f"{k} = {int(val)}")
    if snap.get("payouts"):
        t["payouts"] = [_num(p) for p in snap["payouts"]]
        changes.append(f"payout table set ({len(t['payouts'])} prizes listed)")
    if "remaining" in snap and snap["remaining"] is not None:
        rem = int(_num(snap["remaining"]))
        if t.get("remaining") != rem:
            changes.append(f"players remaining {t.get('remaining') or '?'} -> {rem}")
        t["remaining"] = rem
        record_remaining(state, rem)
    if snap.get("avg_stack") is not None and t.get("remaining"):
        t["total_chips"] = _num(snap["avg_stack"]) * float(t["remaining"])
    for k in ("goal", "pace"):
        if k in snap:
            state["config"][k] = snap[k]
    if "max_seats" in snap:
        tb["max_seats"] = int(snap["max_seats"])

    listed = snap.get("seats")
    if listed is not None:
        if isinstance(listed, list):
            listed = {str(e.get("seat")): e for e in listed}
        seen = set()
        for key, val in listed.items():
            seat = int(key)
            seen.add(seat)
            old = seats(state).get(str(seat))
            if val is None or val == "empty" or (isinstance(val, dict) and val.get("status") in ("out", "empty", "busted")):
                if old:
                    name = remove_seat(state, seat, "left / busted")
                    changes.append(f"seat {seat} {name} is OUT")
                continue
            if isinstance(val, (list, tuple)):
                val = {"name": val[0], "stack": val[1], **({"status": val[2]} if len(val) > 2 else {})}
            elif isinstance(val, (int, float, str)):
                val = {"stack": val}
            name = val.get("name")
            stack = _num(val["stack"]) if val.get("stack") is not None else None
            if old and name and old.get("name") and not _same_player(name, old["name"]) \
                    and not old["name"].startswith("Seat"):
                changes.append(f"seat {seat}: {old['name']} replaced by {name}")
                log(state, f"{old['name']} (seat {seat}) replaced by {name}")
                old = None
                seats(state).pop(str(seat), None)
            if old is None:
                cur = set_seat(state, seat, name or f"Seat{seat}", stack or 0,
                               val.get("status", "active"), val.get("type"))
                changes.append(f"seat {seat}: {cur['name']} sits with {cur['stack']:,.0f}")
            else:
                if stack is not None and abs(stack - old.get("stack", 0)) > 0.5:
                    delta = stack - old.get("stack", 0)
                    changes.append(f"seat {seat} {old['name']}: {old.get('stack', 0):,.0f} -> "
                                   f"{stack:,.0f} ({delta:+,.0f})")
                st_new = val.get("status")
                if st_new and st_new != old.get("status"):
                    changes.append(f"seat {seat} {old['name']} is now {st_new}")
                set_seat(state, seat, name, stack, st_new, val.get("type"))
            if val.get("note"):
                seats(state)[str(seat)].setdefault("notes", []).append(str(val["note"]))
            if val.get("hero"):
                tb["hero"] = seat
        if snap.get("complete"):
            for key in list(seats(state).keys()):
                if int(key) not in seen:
                    name = remove_seat(state, int(key), "no longer at the table")
                    changes.append(f"seat {key} {name} is OUT")
    for name in snap.get("busted") or []:
        seat = find_seat(state, name)
        if seat is not None and str(seat) in seats(state):
            who = remove_seat(state, seat, "busted")
            changes.append(f"seat {seat} {who} BUSTED")
    if "hero" in snap and snap["hero"] is not None:
        seat = find_seat(state, snap["hero"]) if not isinstance(snap["hero"], int) else snap["hero"]
        if seat is not None:
            tb["hero"] = int(seat)
    if "button" in snap and snap["button"] is not None:
        seat = find_seat(state, snap["button"]) if not isinstance(snap["button"], int) else snap["button"]
        if seat is not None:
            tb["button"] = int(seat)
    if tb.get("hero") is None:
        for key, s in seats(state).items():
            if s.get("name", "").strip().lower() in ("hero", "me", "you"):
                tb["hero"] = int(key)
    for c in changes:
        log(state, c)
    return changes


# --------------------------------------------------------------------------
# Text views
# --------------------------------------------------------------------------

def fmt_chips(x: float) -> str:
    return f"{x:,.0f}"


def render(state: dict) -> str:
    t, lv, tb = state["tournament"], state["level"], state["table"]
    sb, bb, ante, bb_ante = blinds(state)
    lines = []
    head = t.get("name") or "Tournament"
    if bb:
        head += f" | blinds {fmt_chips(sb)}/{fmt_chips(bb)}"
        if ante:
            head += f" ante {fmt_chips(ante)}"
        if bb_ante:
            head += f" bb-ante {fmt_chips(bb_ante)}"
    else:
        head += " | blinds NOT SET"
    if t.get("remaining"):
        head += f" | {t['remaining']}"
        if t.get("entrants"):
            head += f"/{t['entrants']}"
        head += " left"
    paid = paid_places(state)
    if paid:
        head += f" | {paid} paid" + ("" if t.get("paid") or t.get("payouts") else " (est.)")
    avg = avg_stack(state)
    if avg and bb:
        head += f" | avg {fmt_chips(avg)} ({avg / bb:.0f}bb)"
    lines.append(head)
    st = stage(state)
    lines.append(f"Stage: {st['label']} | goal: {state['config'].get('goal', 'itm')}")

    pos = positions(state)
    order = action_order(state)
    hero = tb.get("hero")
    lines.append(f"{'':2}{'Seat':<5}{'Pos':<8}{'Player':<16}{'Stack':>11}{'BB':>7}  Type / notes")
    for seat in sorted(int(k) for k in seats(state)):
        s = seats(state)[str(seat)]
        mark = "*" if seat == hero else " "
        btn = "(D)" if seat == tb.get("button") else ""
        stack = s.get("stack", 0)
        bbs = f"{stack / bb:.1f}" if bb else "?"
        notes = s.get("type", "unknown")
        if s.get("status") == "away":
            notes += " AWAY"
        if s.get("notes"):
            notes += " | " + "; ".join(s["notes"][-3:])
        p = pos.get(seat, "-") + btn
        lines.append(f"{mark:2}{seat:<5}{p:<8}{s.get('name', '')[:15]:<16}{fmt_chips(stack):>11}{bbs:>7}  {notes}")
    if hero is None:
        lines.append("Hero seat NOT SET (use: set hero=<seat>)")
    elif tb.get("button") is None:
        lines.append("Button NOT SET (use: set button=<seat>)")
    hs = hero_stack(state)
    if hs and bb:
        cost = orbit_cost(state)
        occ = occupied(state)
        rank = 1 + sum(1 for s in occ if seats(state)[str(s)]["stack"] > hs)
        line = f"Hero: {fmt_chips(hs)} = {hs / bb:.1f}bb, M {hs / cost:.1f}, {rank}/{len(occ)} at the table"
        if avg:
            line += f", {hs / avg:.2f}x average"
        lines.append(line)
        fc = fold_clock(state)
        if fc:
            txt = f"Fold clock: blinds eat you in ~{fc['orbits']:.1f} orbits (~{fc['minutes']:.0f} min)"
            if fc.get("eta") is not None:
                txt += f"; bubble ETA ~{fc['eta']:.0f} min ({fc['rate']:.1f} busts/min)"
                txt += {"safe": " -> you CAN fold into the money",
                        "tight": " -> folding into the money is close; steal once if a clean spot appears",
                        "short": " -> you CANNOT fold into the money; shove while you still have fold equity"}[fc["verdict"]]
            lines.append(txt)
    lines.append("Plan: " + STAGE_PLAN.get(st["code"], STAGE_PLAN["unknown"]))
    del order
    return "\n".join(lines)
