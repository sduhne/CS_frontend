"""Every preflop situation of a tight-aggressive tournament player, as text.

One sheet per table size (6, 7 and 8 players).  It is organised by what has
happened before the player acts:

1. nobody has entered: raise (17bb or more) or all-in (16bb or less);
2. players only called: raise, call along, check in the big blind, or all-in;
3. a raise: re-raise, call or fold with 25bb or more;
4. a raise with 24bb or less (all-in or fold), a raise and a call, a raise and
   a re-raise;
5. the player raised first and was re-raised, or met an all-in;
6. an all-in before the player has acted (one, or two);
7. the gears by stack, the stages of a tournament and the sizes.

``data/tag.json`` (``tools/build_tag.py``) holds the hands.  The raise, call
and re-raise ranges are what ``preflop.advise`` answers far from the money;
every all-in decision comes from the all-in or fold tables in ``binary``, so
the two sheets never disagree.  Stacks are effective, in big blinds.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from . import binary as B

_PATH = os.path.join(os.path.dirname(__file__), "data", "tag.json")
DATA_VERSION = 1
TABLES = B.TABLES                         # 6, 7 and 8 players
SHORT_STACKS = (15.0, 10.0, 6.0)          # the all-in columns: 12 to 16bb, 8 to 11bb, up to 7bb
SHORT_LABELS = ("12 to 16bb", "8 to 11bb", "up to 7bb")
RERAISE_STACKS = ("up to 24bb", "25 to 60bb", "more than 60bb")


def seats(players: int) -> dict[int, str]:
    """Seats that can act first: {players behind: name}, first to act first."""
    return B.seats(players)


def seat(n_behind: int, players: int) -> str:
    return B.seat_name(n_behind, players)


def order(players: int) -> list[str]:
    """Seat names in the order they act before the flop."""
    return [seat(nb, players) for nb in range(players - 1, -1, -1)]


def group_label(group: str, players: int) -> str:
    """Seats of a raiser group of the 25bb+ tables (the engine's early, middle, late)."""
    early = [seat(nb, players) for nb in range(players - 1, 5, -1)]
    return {"early": B._join(early) if early else "", "middle": "LJ or HJ", "late": "CO or BTN", "sb": "SB"}[group]


def groups(players: int) -> list[str]:
    return [g for g in ("early", "middle", "late", "sb") if group_label(g, players)]


@lru_cache(maxsize=1)
def data() -> dict:
    with open(_PATH) as fh:
        d = json.load(fh)
    if d.get("version") != DATA_VERSION:
        raise RuntimeError("data/tag.json is out of date: run python3 tools/build_tag.py")
    return d


def table(players: int) -> dict:
    if players not in TABLES:
        raise ValueError(f"the sheet exists for {B._join([str(t) for t in TABLES])} players, not {players}")
    return data()["tables"][str(players)]


WHERE = {"ip": "a later seat (you act after the raiser)", "sb": "the small blind", "bb": "the big blind"}
REP_SEAT = {"early": None, "middle": 4, "late": 3, "sb": 1}      # the seat a group's rows are solved for

# Big blind against one raise of 2.5bb or less, with 9 to 24bb: the hands that may call instead of
# folding.  The engine's own list (table()["bb_call"], and the hands that move all-in) is wider in
# offsuit hands, most against a late raise; this is the part of it that makes top pair or a real
# draw, and it is inside that list for every raiser.
BB_CALL_SHORT = "22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 82s+, 72s+, 62s+, 52s+, 42s+, 32s, A2o+, K9o+, Q9o+, J9o+, T9o"
BB_CALL_WORDS = "any pair, any suited hand, any ace, K9o+, Q9o+, J9o+ and T9o"
BANDS = tuple(reversed(B.BANDS))          # the all-in sizes, biggest first, as every page prints them
# Calling along behind players who only called (25bb or more, from the cutoff, the button or the
# small blind): these hands, when they are not on the raise list.  It is the engine's own set.
CALL_ALONG = "22-88, A2s-A9s, K9s, KTs, Q9s, QTs, J9s, JTs, T9s, 98s, 87s, 76s, 65s, 54s"

# rules that are the same at every table size (the sheet and the playbook print them)
GEARS = (
    ("40bb or more", "Full poker", "Raise 2.3bb. Re-raise for value. Small pairs and suited connectors may call in position."),
    ("25 to 39bb", "Careful poker", "Raise 2.2bb. No small pairs for a set under 35bb. A re-raise commits you: only hands that want all the chips in."),
    ("17 to 24bb", "Raise, then fold or call", "Raise 2bb. Over a raise it is all-in or fold. Decide before you raise which all-ins you call."),
    ("12 to 16bb", "All-in or fold", "Move all-in or fold. Only QQ+ and AK may raise 2bb first, and then call any all-in."),
    ("11bb or less", "All-in only", "No limping, no small raises, no calling raises. Under 5bb move in before the blinds reach you."),
)
STAGES = (
    ("Early, deep stacks", "Tight from the first seats. No big bluffs, no big calls with one pair. Doubling up is worth less than busting costs."),
    ("Middle, antes in", "Raise from CO, BTN and SB whenever nobody has entered. With 12 to 24bb, move all-in over late raises."),
    ("Close to the money", "Under 2 players left per paid place. Keep taking blinds from players who have tightened. Use the all-in column for twice your stack."),
    ("Bubble", "Under 1.3 players left per paid place. Call all-ins from the bubble table only. Do not fight the biggest stack. If the blinds will not finish your stack before the bubble bursts, fold; if they will, move in while they can still fold."),
    ("In the money", "Back to the normal tables. Look at the next prize before calling a bigger stack."),
    ("Final table", "Let shorter stacks bust first. Against an all-in player who has more chips than you, call from the bubble table."),
)
SIZES = (
    ("First raise", "2.3bb with 40bb or more, 2.2bb with 25 to 39bb, 2bb under 25bb. From the small blind 3bb (2.5bb under 25bb)."),
    ("Over callers", "3bb plus 1bb for each caller; from the blinds 4bb plus 1bb for each caller. If that is a third of your stack, move all-in."),
    ("Re-raise", "3 times the raise when you act after the raiser, 3.8 times from the blinds, plus one raise for each caller. If that is a third of your stack, move all-in."),
    ("Second re-raise", "2.3 times their re-raise with more than 60bb. With less, all-in."),
)
AFTER_FLOP = (
    ("You raised, one caller", "Bet a third of the pot on dry high boards (K-7-2, A-8-3). Check boards that hit callers (9-8-7) without a hand or a draw."),
    ("Several players", "Bet only real hands and strong draws."),
    ("Value", "Top pair with a good kicker or better: bet. Two thirds of the pot on wet boards and on the turn."),
    ("One pair", "is a two-street hand. Fold it to a turn raise or a big river bet."),
    ("Strong draw", "12 outs or more with 4 pots or less behind: all-in if they can fold. Otherwise call only at the right price."),
    ("Committed", "Top pair or better with less than 1.5 pots behind goes to showdown. Decide before you bet."),
    ("Free flop in the big blind", "Bet top pair or better and strong draws. Otherwise check, and fold to a bet."),
)


def opened(players: int, group: str) -> str:
    """The hands the seat a group stands for raises with 25bb or more."""
    nb = REP_SEAT[group] or players - 1
    return table(players)["first_in"][str(nb)]["raise"][0]


def over_raise(players: int, group: str, text: str) -> str:
    """A call range after hero's raise: named when it is the whole opening range."""
    return "every hand you raised" if text == opened(players, group) else text


def limp_rows(players: int) -> list[tuple[str, dict]]:
    """(seat name, row) for every seat that can have callers in front, big blind last."""
    t = table(players)["limpers"]
    return [(seat(int(nb), players), row) for nb, row in t.items()]


def sheet_text(players: int = 8) -> str:
    t = table(players)
    out = [f"TIGHT-AGGRESSIVE TOURNAMENT SHEET, {players} PLAYERS",
           f"Seats in the order they act: {', '.join(order(players))}. Stacks are effective, in big blinds.", ""]

    out.append("1. NOBODY HAS ENTERED")
    out.append("  17bb or more: raise with (otherwise fold)")
    for nb, name in seats(players).items():
        row = t["first_in"][str(nb)]
        under = "" if row["size"][1] == row["size"][0] else f" ({row['size'][1]}bb under 40bb)"
        out.append(f"    {name:6} 25bb or more, raise to {row['size'][0]}bb{under}: {row['raise'][0]}")
        out.append(f"    {'':6} 17 to 24bb, raise to {row['size'][2]}bb: {row['raise'][1]}")
    out.append("    17 to 24bb: fold to an all-in unless the hand is on the list in part 5.")
    out.append("  16bb or less: all-in with (otherwise fold)")
    for nb, name in seats(players).items():
        row = t["first_in"][str(nb)]
        for label, rng in zip(SHORT_LABELS, row["allin"]):
            out.append(f"    {name:6} {label:11} {rng}")
    out.append("    12 to 16bb with QQ+, AKs, AKo: you may raise to 2bb instead and call any all-in.")
    out.append("    Big blind and everybody folded: the pot is yours.")
    out.append("")

    out.append("2. PLAYERS ONLY CALLED (also: only the small blind called and you are the big blind)")
    out.append("  17bb or more: raise to 3bb plus 1bb per caller (4bb plus 1bb per caller from the blinds)")
    for name, row in limp_rows(players):
        for k, rng in enumerate(row["raise"]):
            who = ("one caller", "two callers", "three or more")[k]
            out.append(f"    {name:6} {who:13} raise: {rng}")
        out.append(f"    {'':6} otherwise: {'check' if name == 'BB' else 'fold'}")
    out.append(f"    Call along with 25bb or more from CO, BTN or SB, when the hand is not on your raise list: {CALL_ALONG}.")
    out.append("    17 to 24bb: the same raises without the suited connectors below T9s, and no calling along.")
    out.append("  16bb or less: all-in with (otherwise fold; the big blind checks)")
    for name, row in limp_rows(players):
        for label, rng in zip(SHORT_LABELS, row["allin"]):
            out.append(f"    {name:6} {label:11} {rng}")
    out.append("")

    out.append("3. A RAISE BEFORE YOU, 25BB OR MORE")
    for key, row in t["vs_raise"].items():
        group, where = key.split("|")
        out.append(f"  Raise from {group_label(group, players)}, you are in {WHERE[where]}")
        out.append(f"    re-raise: {row['value']}")
        if row["bluff"]:
            out.append(f"    re-raise as a bluff, more than 45bb, fold to another raise: {row['bluff']}")
        if row["call"]:
            out.append(f"    call: {row['call']}")
        if row.get("setmine"):
            out.append(f"    call with 35bb or more: {row['setmine']}")
        if row.get("button"):
            out.append(f"    call on the button or after a caller, 50bb or more: {row['button']}")
        out.append("    otherwise: fold")
    out.append("  25 to 45bb: re-raise small only with a hand that calls an all-in over it. The other hands on a "
               "re-raise list move all-in where that clearly earns; otherwise they call (in the small blind the "
               "weaker ones fold).")
    out.append("  More than 45bb: every hand on a re-raise list re-raises small.")
    out.append("")

    out.append("4. A RAISE BEFORE YOU, 24BB OR LESS: ALL-IN OR FOLD")
    for key, label, _nb in B.raisers(players):
        out.append(f"  Raise from {label}")
        for (band, _s), rng in reversed(list(zip(B.BANDS[:4], t["reshove"][key]))):
            out.append(f"    {band:11} all-in: {rng}")
    out.append(f"  Big blind only, 9bb or more, a raise of 2.5bb or less: instead of folding you may call with {BB_CALL_WORDS}.")
    out.append("  A raise and a call before you: the same hands; a bigger re-raise with 25bb or more.")
    out.append("  A raise and a re-raise before you: all-in (re-raise with more than 60bb) with")
    for group, row in t["cold"].items():
        cells = "; ".join(f"{label}: {rng or 'nothing'}" for label, rng in zip(RERAISE_STACKS, row))
        out.append(f"    first raise from {group_label(group, players)}: {cells}")
    out.append("")

    out.append("5. YOU RAISED FIRST")
    out.append("  You were re-raised (not all-in)")
    for group, row in t["reraised"].items():
        out.append(f"    you raised from {group_label(group, players)}: 45bb or less all-in with {row['allin']}; "
                   f"more than 45bb re-raise {row['fourbet']}, call {row['call']}; otherwise fold")
    out.append("    These lists are for a re-raise from the big blind: you act last after the flop, except in the SB row. "
               "Out of position QQ, AKs and AKo move all-in with 46 to 60bb.")
    out.append("  A player moved all-in over your raise: call with")
    for group, rows in t["shoved_on"].items():
        out.append(f"    you raised from {group_label(group, players)}")
        for (band, _s), rng, bub in reversed(list(zip(B.BANDS, rows["normal"], rows["bubble"]))):
            out.append(f"      all-in of {band:11} {over_raise(players, group, rng)} | on the bubble: {over_raise(players, group, bub)}")
    out.append("  You only called and a player raised: fold. With a pair and 15 times the raise behind you may call once.")
    out.append("")

    out.append("6. AN ALL-IN BEFORE YOU (you have not put chips in): call with")
    for name, title in (("normal", "Away from the bubble"), ("bubble", "On the bubble, or a final table against a bigger stack")):
        out.append(f"  {title}")
        for key, label, _nb in B.shovers(players):
            out.append(f"    all-in from {label}")
            for (band, _s), rng in reversed(list(zip(B.BANDS, t["call"][name][key]))):
                out.append(f"      {band:11} {rng}")
        out.append("    two all-ins, or a raise and an all-in")
        for (band, _s), rng in reversed(list(zip(B.BANDS, t["call"][name]["two"]))):
            out.append(f"      {band:11} {rng}")
    out.append("  In the big blind use the line for the next smaller all-in (not in the SB rows).")
    out.append("")

    out.append("7. THE PLAN")
    for stack, name, what in GEARS:
        out.append(f"  {stack:13} {name}: {what}")
    for name, what in STAGES:
        out.append(f"  {name}: {what}")
    for name, what in SIZES:
        out.append(f"  {name}: {what}")
    for name, what in AFTER_FLOP:
        out.append(f"  After the flop. {name}: {what}")
    return "\n".join(out)
