"""Prototype of the advice adapter's routing, to produce acceptance rows (scratch, not repository code)."""
import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-CS-frontend/aa601cb2-5545-5621-9e0c-8faa1c3fd22d/scratchpad/tableapp")
from h import mk, S, SimpleNamespace
from poker_coach.cli import _state_spot
from poker_coach.preflop import advise, Act
from poker_coach import binary as BN, spin as SP, aof as AOF, latereg as L
from poker_coach.cards import HAND_INDEX, HANDS, parse_hand

def table_players(n): return 8 if n >= 8 else 7 if n == 7 else 6

def table_lookup(spot, stage_code, ratio, speed="turbo"):
    """The all-in or fold table's answer for the engine spot (None when it has no row)."""
    n, hero = spot.setup.n, spot.hero
    bb = spot.setup.bb
    start = spot.setup.start
    players = table_players(n)
    raises = [a for a in spot.acts if a.kind in ("raise", "allin") and a.idx != hero]
    limps = [a for a in spot.acts if a.kind == "limp"]
    calls = [a for a in spot.acts if a.kind == "call"]
    hero_raised = any(a.idx == hero for a in spot.acts)
    rivals = [i for i in range(hero + 1, n) if not spot.away[i]] + [a.idx for a in spot.acts if a.idx != hero]
    rivals = rivals or [i for i in range(n) if i != hero]
    eff = min(start[hero], max(start[i] for i in rivals)) / bb
    close_r, bubble_r = (2.0, 1.3) if speed != "regular" else (1.5, 1.2)
    money = stage_code in ("itm", "final_table")
    stage = "money" if money else "before"
    bubble = (not money) and ratio is not None and ratio < bubble_r
    close = (not money) and ratio is not None and ratio <= close_r
    nb = n - 1 - hero
    allins = [a for a in raises if a.kind == "allin" or a.amount >= 0.33 * start[a.idx]]
    if len(raises) >= 2 and not allins:
        return ("ALL-IN" if HANDS[spot.hand] in ("AA", "KK") else "FOLD"), "two raises and no all-in: AA and KK only"
    if len(allins) >= 2 or (allins and len(raises) + len(calls) >= 2):
        size = min(start[hero], max(min(a.amount, start[a.idx]) for a in raises)) / bb
        return BN.decide(spot.hand, min(nb, players - 1), eff, stage, "allins", None, size, bubble, players)
    if allins:
        a = allins[0]
        size = min(start[hero], min(a.amount if a.kind != "allin" else start[a.idx], start[a.idx])) / bb
        return BN.decide(spot.hand, min(nb, players - 1), eff, stage, "allin", n - 1 - a.idx, size, bubble, players)
    if raises:
        a = raises[0]
        s = eff * (2 if close else 1)
        return BN.decide(spot.hand, min(nb, players - 1), s, stage, "raise", n - 1 - a.idx, None, bubble, players)
    if limps and nb > 0:
        nb = min(players - 1, nb + 1)
    s = eff * (2 if close else 1)
    return BN.decide(spot.hand, min(nb, players - 1), s, stage, "", None, None, bubble, players)

COMMIT = ("ALL-IN", "RE-RAISE ALL-IN", "CALL")
def tournament(stacks, hero, hand, acts=(), rem=None, paid=150, entrants=1000, goal="balanced", types=None, away=None, plan="full", bb=1000, speed="turbo"):
    st = mk(stacks, hero, bb=bb, entrants=entrants if rem else None, remaining=rem, paid=paid if rem else None, goal=goal, types=types, away=away)
    spot, order = _state_spot(st, SimpleNamespace(hand=hand, goal=goal, facing=""))
    spot.acts = [Act(i, k, a * bb) for i, k, a in acts]
    stg = S.stage(st)
    ratio = (rem / paid) if rem else None
    adv = advise(spot)
    tab = table_lookup(spot, stg["code"], ratio, speed)
    before_money = stg["code"] not in ("itm", "final_table")
    facing_allin = any(a.kind == "allin" for a in spot.acts if a.idx != spot.hero)
    commits = "ALL-IN" in adv.action or (adv.action.startswith("CALL") and facing_allin) or "call any all-in" in adv.action
    head, note = adv.action, "engine"
    if plan == "aof":
        head, note = tab[0], "table"
    elif before_money and not spot.desperate and commits and tab[0] in ("FOLD", "CHECK"):
        head, note = "FOLD", "survival fold"
    return adv, tab, head, note, stg, spot
