"""The table app's advice adapter: the acceptance spots, the styles, the shape of the answer.
Run: python -m unittest tests.test_app_advice

Every spot is built the way the browser builds it: a ``model.Session``, the
table set up through intents, the hand dealt, the actions recorded, then
``advise(session)``.

The numbered rows are the 31 acceptance spots of the advice proposal.  Its
tournament rows: 8 players listed in acting order UTG to BB, blinds 500/1,000
with an ante of 125 each, 1,000 entrants, 150 paid, style "Survive, then win",
opponents unknown, folded to hero unless an action is listed.  The rows were
measured with the field's stacks taken from the table (no starting stack
typed), so the tests clear the starting stack too: that is ICM "estimated".
"""

import json
import random
import re
import time
import unittest

from poker_coach import aof as AOF
from poker_coach import binary as BN
from poker_coach import spin as SP
from poker_coach.app import advice as A
from poker_coach.app.model import ModelError, Session
from poker_coach.cards import HANDS, card_str, parse_hand, parse_range
from poker_coach.preflop import Advice

STACKS_A = [30, 25, 18, 40, 22, 12, 15, 20]         # big blinds, UTG to BB
STACKS_B = [30, 25, 18, 40, 14, 22, 16, 28]
UTG, UTG1, LJ, HJ, CO, BTN, SB, BB = range(8)       # a player's place in the acting order of 8

ANSWER_KEYS = {"rev", "status", "headline", "spot", "reason", "tiles", "flip", "also", "source", "plans",
               "warnings", "chart", "context"}
HEADLINE_KEYS = {"verb", "size_text", "qualifier", "tone", "sure", "follow"}


# --------------------------------------------------------------------------
# Building a table through intents
# --------------------------------------------------------------------------

def seat_of(index: int, hero: int, n: int) -> int:
    """The seat of the player at ``index`` in the acting order, when hero (seat 1) is at ``hero``."""
    return (index - hero) % n + 1


def tournament(stacks_bb, hero, cards, acts=(), left=400, paid=150, entrants=1000, bb=1000, plan=None, style=None,
               types=None, avg_bb=None, opponents=None):
    """A tournament hand at hero's decision.

    ``stacks_bb`` lists the players in acting order, ``hero`` is hero's place
    in it, ``acts`` are ``(place, kind, amount in bb)`` in the order they
    happened; everybody not mentioned takes the passive default.
    """
    n = len(stacks_bb)
    button = seat_of(n - 3, hero, n) if n > 2 else seat_of(0, hero, n)      # heads-up the button acts first
    s = Session(save=False)
    s.do("new_session", mode="tournament", size=n, start_stack=10000, button=button)
    s.do("set_level", text=f"{bb // 2}/{bb}/{bb // 8}")
    values = [None] * n
    for index, stack in enumerate(stacks_bb):
        values[seat_of(index, hero, n) - 1] = stack * bb
    s.do("set_stacks", values=values)
    if left:
        s.do("set_tournament", remaining=left, paid=paid, entrants=entrants, start_stack="")
    if avg_bb:
        s.do("set_tournament", avg_stack=avg_bb * bb)
    for key, value in (("plan", plan), ("style", style), ("opponents", opponents)):
        if value:
            s.do("set_config", **{key: value})
    for index, tag in (types or {}).items():
        s.do("set_type", seat=seat_of(index, hero, n), type=tag)
    s.do("deal", hero_cards=cards)
    for index, kind, amount in acts:
        s.do("act", seat=seat_of(index, hero, n), kind=kind, amount=None if amount is None else amount * bb)
    return s


def spin(stacks_bb, hero, cards, acts=(), bb=50, opponents=None):
    """A Spin hand: players in acting order (BTN, SB, BB; heads-up SB, BB)."""
    n = len(stacks_bb)
    s = Session(save=False)
    s.do("new_session", mode="spin", start_stack=stacks_bb[hero] * bb, button=seat_of(0, hero, n))
    s.do("set_level", text=f"{bb // 2}/{bb}")
    for index, stack in enumerate(stacks_bb):
        s.do("set_stack", seat=seat_of(index, hero, n), text=str(stack * bb))
    for seat in range(n + 1, 4):
        s.do("clear_seat", seat=seat)
    if opponents:
        s.do("set_config", opponents=opponents)
    s.do("deal", hero_cards=cards)
    for index, kind, amount in acts:
        s.do("act", seat=seat_of(index, hero, n), kind=kind, amount=None if amount is None else amount * bb)
    return s


def all_in_or_fold(stacks_bb, hero, cards, movers=(), opponents=None):
    """An All-In or Fold hand: four players in acting order (CO, BTN, SB, BB); ``movers`` moved all-in."""
    n = len(stacks_bb)
    s = Session(save=False)
    s.do("new_session", mode="aof", button=seat_of(n - 3, hero, n))
    for index, stack in enumerate(stacks_bb):
        s.do("set_stack", seat=seat_of(index, hero, n), text=str(stack))
    if opponents:
        s.do("set_config", opponents=opponents)
    s.do("deal", hero_cards=cards)
    for index in movers:
        s.do("act", seat=seat_of(index, hero, n), kind="allin")
    return s


def verb(answer) -> str:
    return answer["headline"]["verb"]


def codes(answer) -> list:
    return [w["code"] for w in answer["warnings"]]


def hero_cell(chart) -> str:
    row, column = divmod(HANDS.index(chart["hero"]), 13)
    return chart["cells"][row][column]


def check_shape(case, answer):
    """The answer has the shape of the build spec, section 7, and is plain JSON."""
    case.assertTrue(ANSWER_KEYS <= set(answer), set(answer))
    case.assertIn(answer["status"], ("ready", "none"))
    json.dumps(answer, allow_nan=False)
    case.assertEqual(set(answer["context"]), {"stage", "gear", "fold_clock"})
    for item in answer["warnings"]:
        case.assertEqual(set(item), {"code", "text"})
    case.assertIn(answer["icm"], ("off", "estimated", "on", "exact"))
    case.assertIn(answer["guard"], ("agrees", "survival", "edge", "close", "off", "none"))
    if answer["status"] == "none":
        case.assertIsNone(answer["headline"])
        case.assertTrue(answer["spot"])
        return
    headline = answer["headline"]
    case.assertEqual(set(headline), HEADLINE_KEYS)
    case.assertIn(headline["tone"], ("attack", "passive", "fold", "wait"))
    case.assertIn(headline["sure"], ("clear", "standard", "close", ""))
    for one in answer["tiles"]:
        case.assertEqual(set(one), {"label", "value", "note", "sign"})
        case.assertIn(one["sign"], (-1, 0, 1))
    chart = answer["chart"]
    if chart is not None:
        check_chart(case, chart)


def check_chart(case, chart):
    case.assertEqual(len(chart["cells"]), 13)
    for row in chart["cells"]:
        case.assertEqual(len(row), 13)
        case.assertTrue(set(row) <= set("rcxf"), row)
    if chart["numbers"] is not None:
        case.assertEqual([len(row) for row in chart["numbers"]], [13] * 13)
    case.assertIn(chart["hero"], HANDS)
    case.assertTrue(0 <= chart["share"] <= 100)
    case.assertTrue(chart["title"])
    case.assertTrue(all(set(item) == {"code", "label"} for item in chart["legend"]))


# --------------------------------------------------------------------------
# The 31 acceptance spots
# --------------------------------------------------------------------------

class TournamentFullPlan(unittest.TestCase):
    """T1 to T16: the engine answers, and before the money the survival guard has a say."""

    def test_T1_open_raise_with_a_plan(self):
        a = A.advise(tournament([30, 25, 18, 40, 15, 35, 16, 28], BTN, "QJs"))
        self.assertEqual(verb(a), "RAISE")
        self.assertEqual(a["headline"]["size_text"], "TO 2.2BB \u00b7 2,200")
        self.assertEqual(a["headline"]["follow"], {"kind": "raise", "to": 2200})
        self.assertEqual(a["headline"]["tone"], "attack")
        self.assertEqual(a["headline"]["sure"], "clear")
        self.assertTrue(any(p.startswith("If BB (28bb) moves all-in: FOLD") for p in a["plans"]), a["plans"])
        self.assertEqual(a["guard"], "none")            # a small raise does not risk the stack
        self.assertEqual(a["spot"], "QJs on the button, 35bb, folded to you")

    def test_T2_all_in_and_the_table_agrees(self):
        a = A.advise(tournament(STACKS_A, BTN, "A8o"))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertEqual(a["guard"], "agrees")
        self.assertEqual(a["headline"]["follow"], {"kind": "allin"})
        self.assertEqual(a["tiles"][0]["value"], "+1.20bb")
        self.assertEqual(a["tiles"][0]["sign"], 1)
        self.assertIn("up to 21bb", a["flip"])
        self.assertIn("the all-in table agrees", a["source"])

    def test_T3_survival_fold(self):
        a = A.advise(tournament(STACKS_B, CO, "K9s"))
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual(a["guard"], "survival")
        self.assertEqual(a["headline"]["qualifier"], "survival fold")
        self.assertEqual(a["headline"]["tone"], "fold")
        self.assertEqual(a["headline"]["follow"], {"kind": "fold"})
        self.assertIn("ALL-IN +0.15bb", a["also"])       # the engine's answer is the second line
        self.assertIn("SURVIVAL FOLD (engine: ALL-IN +0.15bb)", a["source"])
        self.assertEqual(hero_cell(a["chart"]), "f")     # the chart is the table's: it folds the hand

    def test_T4_premium_raises_and_calls(self):
        a = A.advise(tournament(STACKS_B, CO, "QQ"))
        self.assertEqual(verb(a), "RAISE")
        self.assertEqual(a["headline"]["qualifier"], "and call any all-in")
        self.assertEqual(a["headline"]["size_text"], "TO 2BB \u00b7 2,000")
        self.assertEqual(a["guard"], "agrees")

    def test_T5_bubble_survival_fold_and_max_ev(self):
        # two places from the money the chart folds; the default style follows it for a thin edge (under
        # +0.20bb, L1): A7o is worth +0.09bb here
        a = A.advise(tournament(STACKS_A, BTN, "A7o", left=152))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("counts double", a["reason"])
        # A8o is worth exactly +0.20bb, which is the line: a clear edge, played
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=152))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "edge"))
        self.assertIn("CLEAR EDGE (engine +0.20bb)", a["source"])
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=152, style="maxev"))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "off"))
        self.assertEqual(a["tiles"][0]["value"], "+0.20bb")

    def test_T6_close_to_the_money_reads_twice_the_stack(self):
        # the table at 24bb folds A5o (an all-in up to 15bb).  The strict guard of "Cash first" follows it ...
        a = A.advise(tournament(STACKS_A, BTN, "A5o", left=260, style="cash"))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("up to 15bb", a["reason"])
        self.assertIn("counts double", a["reason"])
        self.assertIn("ALL-IN +0.44bb", a["also"])
        # ... the default style only when the engine's edge is thin, and +0.55bb is not (PRE-7)
        a = A.advise(tournament(STACKS_A, BTN, "A5o", left=260))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "edge"))
        self.assertIn("CLEAR EDGE (engine +0.55bb): played although the all-in table folds", a["source"])

    def test_T7_close_fold_over_a_raise(self):
        stacks = [35, 25, 18, 22, 15, 25, 16, 18]
        a = A.advise(tournament(stacks, HJ, "TT", acts=[(UTG, "raise", 2.2)]))
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual(a["headline"]["sure"], "close")
        self.assertIn("close", codes(a))
        self.assertEqual(a["guard"], "none")
        early = A.advise(tournament(stacks, HJ, "TT", acts=[(UTG, "raise", 2.2)], left=800))
        self.assertEqual((verb(early), early["guard"]), ("ALL-IN", "agrees"))

    def test_T8_big_blind_calls_at_a_price(self):
        a = A.advise(tournament([30, 25, 18, 40, 22, 25, 15, 20], BB, "K9o", acts=[(BTN, "raise", 2)]))
        self.assertEqual(verb(a), "CALL")
        self.assertEqual(a["headline"]["sure"], "close")
        self.assertEqual(a["headline"]["tone"], "passive")
        self.assertEqual(a["headline"]["size_text"], "1BB \u00b7 1,000")
        self.assertEqual(a["headline"]["follow"], {"kind": "call"})
        self.assertEqual(hero_cell(a["chart"]), "c")

    def test_T9_calling_an_all_in(self):
        stacks = [30, 25, 18, 40, 15, 22, 16, 20]
        shove = [(CO, "allin", None)]
        a = A.advise(tournament(stacks, BB, "99", acts=shove))
        self.assertEqual((verb(a), a["guard"]), ("CALL", "agrees"))
        self.assertEqual(a["tiles"][0]["value"], "47% / 60%")
        self.assertEqual(a["spot"], "99 in the big blind, 20bb, CO is all-in for 14.9bb")
        bubble = A.advise(tournament(stacks, BB, "99", acts=shove, left=152, style="cash"))
        self.assertEqual((verb(bubble), bubble["guard"]), ("FOLD", "survival"))
        self.assertIn("TT+, AQs+, AKo", bubble["reason"])
        self.assertIn("CALL, 60% against 57%", bubble["also"])
        # the default style folds a thin call only: 7 points over the need is the least it plays this close
        bubble = A.advise(tournament(stacks, BB, "99", acts=shove, left=152))
        self.assertEqual((verb(bubble), bubble["guard"]), ("CALL", "edge"))
        self.assertIn("CLEAR EDGE (60% against 53%): played although the all-in table folds", bubble["source"])
        self.assertEqual(bubble["tiles"][-1], {"label": "The chart says", "value": "FOLD", "note": "TT+, AQs+, AKo",
                                               "sign": 0})
        read = A.advise(tournament(stacks, BB, "99", acts=shove, left=152, types={CO: "maniac"}))
        self.assertEqual((verb(read), read["guard"]), ("CALL", "off"))
        self.assertIn("a read on CO", read["source"])

    def test_T10_bubble_fold_then_call_in_the_money(self):
        stacks = [30, 25, 18, 40, 15, 25, 16, 18]
        shove = [(BTN, "allin", None)]
        a = A.advise(tournament(stacks, BB, "AJo", acts=shove, left=152))
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual(a["headline"]["sure"], "close")
        self.assertEqual(a["tiles"][0]["value"], "60% / 58%")
        money = A.advise(tournament(stacks, BB, "AJo", acts=shove, left=100))
        self.assertEqual((verb(money), money["guard"]), ("CALL", "off"))
        self.assertIn("in the money", money["source"])

    def test_T11_isolate_over_a_raise_and_an_all_in(self):
        a = A.advise(tournament([30, 25, 18, 40, 14, 20, 16, 18], BTN, "JJ",
                                acts=[(HJ, "raise", 2.2), (CO, "allin", None)]))
        self.assertEqual(verb(a), "RE-RAISE ALL-IN")
        self.assertEqual(a["headline"]["qualifier"], "isolate")
        self.assertEqual(a["headline"]["follow"], {"kind": "allin"})
        self.assertEqual(a["guard"], "agrees")

    def test_T12_fold_queens_to_a_raise_and_a_re_raise(self):
        a = A.advise(tournament([50] * 8, BTN, "QQ", acts=[(UTG, "raise", 2.3), (HJ, "raise", 7)], left=800))
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual(a["headline"]["sure"], "clear")
        self.assertEqual(a["spot"], "QQ on the button, 50bb, UTG raises to 2.3bb, HJ re-raises to 7bb")

    def test_T13_two_all_ins_near_the_bubble(self):
        two = [(HJ, "allin", None), (CO, "allin", None)]
        a = A.advise(tournament(STACKS_A, BTN, "TT", acts=two, left=185, style="cash"))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("CALL", a["also"])
        a = A.advise(tournament(STACKS_A, BTN, "TT", acts=two, left=185))       # 39% against 28%: no thin edge
        self.assertEqual((verb(a), a["guard"]), ("CALL", "edge"))

    def test_T14_final_table_guard_off(self):
        a = A.advise(tournament([30, 25, 18, 40, 22, 12, 15, 40], SB, "A9s", left=8))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "off"))
        self.assertIn("final table", a["source"])
        self.assertEqual(a["tiles"][0]["value"], "+1.83bb")

    def test_T15_desperate_stack_moves_in(self):
        a = A.advise(tournament([2.5, 25, 18, 40, 22, 12, 15, 20], UTG, "Q7o"))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "off"))
        self.assertEqual(a["spot"], "Q7o under the gun, 2.5bb, first to act")

    def test_T16_heads_up_warning(self):
        a = A.advise(tournament([18, 30], 0, "K5o", left=2))
        self.assertEqual(verb(a), "FOLD")
        self.assertIn("heads_up", codes(a))
        self.assertEqual(a["spot"], "K5o on the button, 18bb, first to act")


class TournamentAllInPlan(unittest.TestCase):
    """B1 to B4: one decision a hand, from the all-in or fold tables."""

    def test_B1_all_in_over_a_raise(self):
        a = A.advise(tournament([30, 25, 18, 40, 22, 15, 15, 20], BTN, "99", acts=[(CO, "raise", 2.2)], plan="allin"))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertIn("66+, ATs+, AJo+", a["reason"])
        self.assertIn("all-in or fold table", a["source"])
        self.assertIn("With all moves, on these stacks:", a["also"])       # the second line, always

    def test_B2_call_two_all_ins(self):
        a = A.advise(tournament([30, 25, 18, 12, 11, 10, 15, 20], BTN, "TT",
                                acts=[(HJ, "allin", None), (CO, "allin", None)], plan="allin"))
        self.assertEqual(verb(a), "CALL")
        self.assertIn("TT+, AKs, AKo", a["reason"])

    def test_B3_big_blind_behind_a_caller(self):
        stacks = [30, 25, 18, 40, 22, 12, 15, 15]
        limp = [(BTN, "call", None)]
        a = A.advise(tournament(stacks, BB, "J9s", acts=limp, plan="allin"))
        self.assertEqual(verb(a), "ALL-IN")                 # the small blind's range holds J9s ...
        b = A.advise(tournament(stacks, BB, "T7o", acts=limp, plan="allin"))
        self.assertEqual(verb(b), "CHECK")                  # ... not T7o: the big blind checks, never folds
        self.assertEqual(b["headline"]["follow"], {"kind": "check"})

    def test_B4_bubble_charts_by_the_sit_out_line(self):
        A.warm_bubble_charts(8)                             # in the app a background thread works them out
        stacks = [30, 25, 18, 40, 22, 8, 15, 20]
        a = A.advise(tournament(stacks, BTN, "A9o", left=165, avg_bb=30, plan="allin"))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertIn("31% of the sit-out line", a["reason"])
        self.assertIn("the tight chart", a["reason"])
        self.assertIn("55+, A6s+, KJs+, A8o+, KQo", a["reason"])
        b = A.advise(tournament(stacks, BTN, "K9s", left=165, avg_bb=30, plan="allin"))
        self.assertEqual(verb(b), "FOLD")
        self.assertIn("You hold 31% of what it takes to fold into the money (the sit-out line)", a["context"]["fold_clock"])


def six_handed(stacks_bb, hero, cards, **more):
    s = tournament(stacks_bb, hero, cards, **more)
    return s, lambda index: seat_of(index, hero, 6)


class AfterTheFlop(unittest.TestCase):
    """P1 to P4: six players (LJ, HJ, CO, BTN, SB, BB), roles and lines taken from the recorded actions."""

    def test_P1_value_bet_as_the_raiser(self):
        s, seat = six_handed([30] * 6, 2, "AhKd")           # hero in the cutoff
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat(5), kind="call")              # the big blind calls
        s.do("set_cards", slot="flop", text="Ks7d2c")
        s.do("act", seat=seat(5), kind="check")
        a = A.advise(s)
        self.assertEqual(verb(a), "BET")
        self.assertEqual(a["headline"]["sure"], "standard")
        self.assertEqual(a["tiles"][0], {"label": "Equity", "value": "91%", "sign": 0,
                                         "note": "against their range after this line"})
        follow = a["headline"]["follow"]
        self.assertEqual(follow["kind"], "bet")
        self.assertAlmostEqual(follow["to"] / s.view()["hand"]["pot"], 0.33, places=2)     # a third of the pot
        self.assertEqual(a["spot"], "AhKd on Ks7d2c, checked to you, pot 5.7bb")
        self.assertIsNone(a["chart"])

    def test_P2_semi_bluff_all_in(self):
        s, seat = six_handed([30, 30, 30, 30, 30, 24.3], 5, "QhJh")     # hero in the big blind
        s.do("act", seat=seat(3), kind="raise", amount=2200)            # the button raises
        s.do("act", seat=1, kind="call")
        s.do("set_cards", slot="flop", text="Th9h2c")
        s.do("act", seat=1, kind="check")
        s.do("act", seat=seat(3), kind="bet", amount=1900)
        a = A.advise(s)
        self.assertEqual(verb(a), "ALL-IN")
        self.assertEqual(a["headline"]["qualifier"], "semi-bluff")
        self.assertEqual(a["headline"]["follow"], {"kind": "allin"})
        self.assertEqual(a["spot"], "QhJh on Th9h2c, BTN bets 1.9bb into 5.7bb")
        self.assertIn(a["tiles"][0]["value"], ("64%", "65%"))

    def river_bet_from_the_big_blind(self, tag):
        """Hero raises the cutoff with AsTd, bets flop and turn, and the big blind leads the river for 12bb into 18bb."""
        s, seat = six_handed([80] * 6, 2, "AsTd", types={5: tag} if tag else None)
        villain = seat(5)
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=villain, kind="call")
        s.do("set_cards", slot="flop", text="Tc7h4s")
        s.do("act", seat=villain, kind="check")
        s.do("act", seat=1, kind="bet", amount=2000)
        s.do("act", seat=villain, kind="call")
        s.do("set_cards", slot="turn", text="2d")
        s.do("act", seat=villain, kind="check")
        s.do("act", seat=1, kind="bet", amount=4175)
        s.do("act", seat=villain, kind="call")
        s.do("set_cards", slot="river", text="Kh")
        s.do("act", seat=villain, kind="bet", amount=12000)
        return A.advise(s)

    def test_P3_playbook_check_folds_one_pair(self):
        a = self.river_bet_from_the_big_blind("station")
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual(a["headline"]["qualifier"], "playbook check")
        self.assertIn("By the numbers alone: CALL", a["also"])  # the engine calls there
        self.assertEqual(a["spot"], "AsTd on Tc7h4s2dKh, BB bets 12bb into 18bb")
        # the rule holds for a player without a tag as well (POST-7); only lag and maniac get the engine's call
        self.assertEqual(verb(self.river_bet_from_the_big_blind(None)), "FOLD")
        self.assertEqual(verb(self.river_bet_from_the_big_blind("maniac")), "CALL")

    def test_P4_close_call_with_icm_priced_in(self):
        # the bubble; the cutoff covers hero, raises to 3bb and moves all-in on the flop
        stacks = [30, 25, 18, 40, 30, 22, 16, 17]
        s = tournament(stacks, BB, "AhQd", acts=[(CO, "raise", 3)], left=152)
        s.do("act", seat=1, kind="call")
        s.do("set_cards", slot="flop", text="Qs8d3c")
        s.do("act", seat=1, kind="check")
        s.do("act", seat=seat_of(CO, BB, 8), kind="allin")
        # the engine's own answer (the Max EV style shows it): a close call
        s.do("set_config", style="maxev")
        a = A.advise(s)
        self.assertEqual(verb(a), "CALL")
        self.assertEqual(a["headline"]["sure"], "close")
        self.assertIn("close", codes(a))
        need, have = (int(x.strip("%")) for x in a["tiles"][1]["value"].split(" / "))
        self.assertTrue(have - 3 <= need <= have, (need, have))
        self.assertGreater(need, 55)                        # pot odds alone ask for 39%: the rest is the bubble
        # in the default style a close call before the money gives way to the fold (decision "close spots")
        s.do("set_config", style="survive")
        a = A.advise(s)
        self.assertEqual((verb(a), a["headline"]["qualifier"], a["guard"]), ("FOLD", "close: lower variance", "close"))
        self.assertIn("By the numbers alone: CALL", a["also"])


class Spin(unittest.TestCase):
    """S1 to S4: chips are money, so no ICM and no guard."""

    def test_S1_button_all_in(self):
        a = A.advise(spin([12, 12, 12], 0, "K7s"))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertEqual(a["tiles"][0]["value"], "+0.05bb")
        self.assertEqual(a["headline"]["size_text"], "12BB \u00b7 600")
        self.assertEqual((a["icm"], a["guard"]), ("off", "none"))
        self.assertIn("Spin table", a["source"])

    def test_S2_big_blind_calls_an_all_in(self):
        a = A.advise(spin([9, 9, 9], 2, "A5o", acts=[(0, "allin", None)]))
        self.assertEqual(verb(a), "CALL")
        self.assertEqual(a["tiles"][0]["value"], "+0.66bb")
        self.assertEqual(a["headline"]["follow"], {"kind": "call"})
        self.assertEqual(hero_cell(a["chart"]), "c")

    def test_S3_loose_callers_make_it_a_fold(self):
        solid = A.advise(spin([10, 10, 10], 1, "T5s"))
        self.assertEqual(verb(solid), "ALL-IN")
        self.assertEqual(solid["tiles"][0]["value"], "+0.07bb")
        self.assertIn("FOLD", solid["flip"])                # what flips it: players who call too much
        loose = A.advise(spin([10, 10, 10], 1, "T5s", opponents="loose"))
        self.assertEqual(verb(loose), "FOLD")
        self.assertEqual(loose["tiles"][0]["value"], "\u22120.37bb")
        self.assertEqual(loose["tiles"][0]["sign"], -1)

    def test_S4_deep_button_raises_small(self):
        a = A.advise(spin([25, 25, 25], 0, "K7s"))
        self.assertEqual(verb(a), "RAISE")
        self.assertEqual(a["headline"]["size_text"], "TO 2.2BB \u00b7 110")
        self.assertIn("+0.01bb", a["also"])                 # the table's all-in is the second line


class AllInOrFold(unittest.TestCase):
    """A1 to A3: the solved table for the seat and for who has moved in."""

    def test_A1_fold_to_an_all_in(self):
        a = A.advise(all_in_or_fold([8, 8, 8, 8], 1, "A5s", movers=[0]))
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual(a["headline"]["sure"], "clear")
        self.assertEqual(a["tiles"][0]["value"], "\u22120.28bb")

    def test_A2_unequal_stacks(self):
        a = A.advise(all_in_or_fold([8, 8, 8, 5.5], 2, "Q4o"))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertEqual(a["tiles"][0]["value"], "+0.12bb")
        self.assertIn("outside_tables", codes(a))           # answered for the effective stack: an approximation
        # the move as the All-in button records it, and what the big blind can match of it (D2)
        self.assertEqual(a["headline"]["size_text"], "8BB")
        self.assertEqual(a["headline"]["qualifier"], "5.5bb of your 8bb can be matched")
        self.assertEqual(a["headline"]["follow"], {"kind": "allin"})

    def test_A3_the_big_blind_calls(self):
        a = A.advise(all_in_or_fold([8, 8, 8, 8], 3, "JTs", movers=[2]))
        self.assertEqual(verb(a), "CALL")                   # the table says ALL-IN; against an all-in that is a call
        self.assertEqual(a["headline"]["tone"], "passive")
        self.assertEqual(a["headline"]["follow"], {"kind": "call"})     # ... on the Follow button too (OPS-17)
        self.assertEqual(a["headline"]["size_text"], "7BB")             # what is still to pay over the big blind
        self.assertEqual(a["tiles"][0]["value"], "+0.89bb")


# --------------------------------------------------------------------------
# Styles, tournament numbers, warnings
# --------------------------------------------------------------------------

class Styles(unittest.TestCase):
    def test_cash_first_folds_by_the_prize_model(self):
        # A8o on the button with 12bb on the bubble: counting the min-cash twice, the engine folds by itself
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=152, style="cash"))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "none"))

    def test_three_styles_on_one_call(self):
        # AJo in the big blind against a button all-in, 185 left of 150 paid
        stacks, shove = [30, 25, 18, 40, 15, 25, 16, 18], [(BTN, "allin", None)]
        cash = A.advise(tournament(stacks, BB, "AJo", acts=shove, left=185, style="cash"))
        survive = A.advise(tournament(stacks, BB, "AJo", acts=shove, left=185))
        max_ev = A.advise(tournament(stacks, BB, "AJo", acts=shove, left=185, style="maxev"))
        self.assertEqual((verb(cash), cash["guard"]), ("FOLD", "none"))             # the prize model folds
        self.assertEqual((verb(survive), survive["guard"]), ("FOLD", "survival"))   # the engine calls, the guard folds
        self.assertEqual((verb(max_ev), max_ev["guard"]), ("CALL", "off"))          # the engine alone
        need = lambda answer: int(next(t for t in answer["tiles"] if t["label"] == "Need / have")["value"][:2])
        self.assertGreater(need(cash), need(max_ev))

    def test_re_entry_open_is_chip_ev_without_the_guard(self):
        s = tournament(STACKS_B, CO, "K9s")
        s.do("set_config", reentry_open=True)
        a = A.advise(s)
        self.assertEqual((verb(a), a["guard"], a["icm"]), ("ALL-IN", "off", "off"))
        self.assertIn("reentry_open", codes(a))

    def test_all_in_plan_differs_from_the_full_plan(self):
        full = A.advise(tournament([30, 25, 18, 40, 15, 35, 16, 28], BTN, "QJs"))
        plan = A.advise(tournament([30, 25, 18, 40, 15, 35, 16, 28], BTN, "QJs", plan="allin"))
        self.assertEqual((verb(full), verb(plan)), ("RAISE", "FOLD"))
        self.assertIn("RAISE", plan["also"])


class TournamentNumbers(unittest.TestCase):
    def test_missing_numbers_mean_chip_ev_and_a_warning(self):
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=None))
        self.assertEqual(a["status"], "ready")
        self.assertEqual(a["icm"], "off")
        self.assertIn("icm_off", codes(a))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertEqual(a["tiles"][0]["value"], "+1.57bb")     # chip EV
        self.assertEqual(a["guard"], "agrees")                  # the guard treats the hand as before the money
        self.assertIn("ICM off", a["source"])

    def test_levels_of_icm(self):
        s = tournament(STACKS_A, BB, "A8o")                 # the big blind waits: the level is told all the same
        first = A.advise(s)
        self.assertEqual(first["icm"], "estimated")
        self.assertIn("icm_estimated", codes(first))
        s.do("set_tournament", avg_stack=40000)
        self.assertEqual(A.advise(s)["icm"], "on")
        s.do("set_tournament", payouts="1:1000 2:600 3:400 4-150:20")
        self.assertEqual(A.advise(s)["icm"], "exact")
        s.do("set_tournament", remaining="")
        self.assertEqual(A.advise(s)["icm"], "off")

    def test_players_left_goes_stale(self):
        s = tournament(STACKS_A, BB, "A8o")
        self.assertNotIn("left_stale", codes(A.advise(s)))
        an_hour_later = A.advise(s, now=time.time() + 3600)
        self.assertIn("left_stale", codes(an_hour_later))
        self.assertIn("hands old", an_hour_later["warnings"][0]["text"])

    def test_two_warnings_show_and_the_rest_are_counted(self):
        s = tournament([30, 25, 18, 40, 22, 25, 15, 20], BB, "K9o", acts=[(BTN, "raise", 2)])
        s.do("set_config", bounty=True)
        warnings = A.advise(s)["warnings"]
        self.assertEqual(len(warnings), 3)
        self.assertEqual(warnings[2]["code"], "more")
        self.assertTrue(warnings[2]["text"].startswith("2 more: "), warnings[2]["text"])

    def test_blinds_about_to_rise(self):
        s = tournament(STACKS_A, BTN, "72o", acts=[(UTG, "fold", None)])
        s.do("level_up")                                    # the new blinds wait for the next hand
        a = A.advise(s)
        self.assertTrue(any("After the rise" in w["text"] or "after the rise" in w["text"] for w in a["warnings"]),
                        a["warnings"])

    def test_context(self):
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=260))
        self.assertIn("110 from the money", a["context"]["stage"])
        self.assertTrue(a["context"]["gear"].startswith("12 to 16bb"))
        self.assertIn("The blinds take 35 minutes to eat your stack.", a["context"]["fold_clock"])
        self.assertEqual(A.advise(all_in_or_fold([8, 8, 8, 8], 1, "A5s", movers=[0]))["context"],
                         {"stage": "", "gear": "", "fold_clock": ""})


class EngineTraps(unittest.TestCase):
    """The spots where the engine needs help (advice proposal, section 10), and the warnings that say so."""

    def test_seats_are_named_like_the_table(self):
        a = A.advise(tournament(STACKS_A, UTG1, "AKs"))
        self.assertTrue(a["spot"].startswith("AKs in UTG+1, 25bb"), a["spot"])
        b = A.advise(tournament(STACKS_A, BB, "99", acts=[(UTG1, "raise", 2.2)]))
        self.assertIn("UTG+1 raises to 2.2bb", b["spot"])

    def test_a_caller_still_behind_is_flagged(self):
        # hero raises the cutoff, the button calls, the big blind moves all-in: the engine prices the all-in alone
        s = tournament([30, 25, 18, 40, 30, 25, 16, 25], CO, "TT")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat_of(BTN, CO, 8), kind="call")
        s.do("act", seat=seat_of(BB, CO, 8), kind="allin")
        a = A.advise(s)
        self.assertEqual(verb(a), "CALL")
        self.assertIn("caller_behind", codes(a))
        self.assertEqual(a["guard"], "agrees")              # the sheet's row for an all-in over hero's raise

    def test_called_and_then_raised_is_the_sheets_rule(self):
        s = tournament([30] * 8, BTN, "76s")
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat_of(BB, BTN, 8), kind="raise", amount=4000)
        a = A.advise(s)
        self.assertEqual(verb(a), "FOLD")
        self.assertIn("the sheet's rule", a["source"])
        deep = tournament([80] * 8, BTN, "55")
        deep.do("act", seat=1, kind="call")
        deep.do("act", seat=seat_of(BB, BTN, 8), kind="raise", amount=4000)
        self.assertEqual(verb(A.advise(deep)), "CALL")      # a pair with 15 times the raise behind may call once

    def test_final_table_call_against_a_bigger_stack(self):
        a = A.advise(tournament([30, 25, 18, 40, 14, 22, 16, 28], BB, "TT", acts=[(HJ, "allin", None)], left=8))
        self.assertEqual((verb(a), a["guard"]), ("CALL", "off"))
        self.assertIn("covered_call", codes(a))             # the bubble table would fold: JJ+

    def test_outside_the_tables(self):
        nine = A.advise(tournament([12] * 9, 0, "ATs", plan="allin"))
        self.assertIn("outside_tables", codes(nine))
        deep = A.advise(tournament([50] * 8, BTN, "AKs", plan="allin"))
        self.assertEqual(verb(deep), "FOLD")                # over 40bb the plan plays aces and kings only
        self.assertIn("outside_tables", codes(deep))
        limp = A.advise(spin([20, 20, 20], 1, "A9o", acts=[(0, "call", None)]))     # a button limp has no row
        self.assertIn("outside_tables", codes(limp))
        self.assertIn("no row", limp["source"])

    def test_bubble_charts_not_ready_yet(self):
        # until the charts are worked out the column for twice the stack answers, and the panel says so
        real = A.bubble_sheet
        A.bubble_sheet = lambda players, wait=False: None
        try:
            a = A.advise(tournament([30, 25, 18, 40, 22, 8, 15, 20], BTN, "A9o", left=165, avg_bb=30, plan="allin"))
        finally:
            A.bubble_sheet = real
        self.assertEqual(verb(a), "ALL-IN")                 # A9o from the button is an all-in up to 20bb
        self.assertIn("counts double", a["reason"])
        self.assertIn("charts_loading", codes(a))

    def test_a_note_on_a_player_in_the_pot_is_shown(self):
        s = tournament([30, 25, 18, 40, 15, 22, 16, 20], BB, "99")
        s.do("rename", seat=seat_of(CO, BB, 8), name="Kim")
        s.do("note", seat=seat_of(CO, BB, 8), text="moves in with any ace")
        s.do("act", seat=seat_of(CO, BB, 8), kind="allin")
        a = A.advise(s)
        self.assertEqual(a["spot"], "99 in the big blind, 20bb, Kim (CO) is all-in for 14.9bb")
        self.assertIn({"code": "note", "text": "Your note on Kim (CO): moves in with any ace"}, a["warnings"])


# --------------------------------------------------------------------------
# The chart
# --------------------------------------------------------------------------

class Charts(unittest.TestCase):
    def spots(self):
        """One spot for every route that has a chart: (name, session, the code of hero's own cell)."""
        A.warm_bubble_charts(8)
        deep = [50] * 8
        yield "opening range", tournament([30, 25, 18, 40, 15, 35, 16, 28], BTN, "QJs"), "r"
        yield "solver all-in", tournament(STACKS_A, BTN, "A8o"), "r"
        yield "table after a survival fold", tournament(STACKS_B, CO, "K9s"), "f"
        yield "all-in over a raise", tournament([35, 25, 18, 22, 15, 25, 16, 18], HJ, "TT",
                                                acts=[(UTG, "raise", 2.2)], left=800), "r"
        yield "calling an all-in", tournament([30, 25, 18, 40, 15, 22, 16, 20], BB, "99", acts=[(CO, "allin", None)]), "c"
        yield "re-raise chart", tournament(deep, BTN, "AKs", acts=[(LJ, "raise", 2.3)]), "r"
        yield "behind callers", tournament(deep, HJ, "AQs", acts=[(UTG, "call", None), (LJ, "call", None)]), "r"
        yield "a raise and a re-raise", tournament(deep, BTN, "QQ", acts=[(UTG, "raise", 2.3), (HJ, "raise", 7)],
                                                   left=800), "f"
        yield "two all-ins", tournament(STACKS_A, BTN, "AA", acts=[(HJ, "allin", None), (CO, "allin", None)]), "c"
        yield "all-in plan, first in", tournament(STACKS_A, BTN, "A8o", plan="allin"), "r"
        yield "all-in plan, over a raise", tournament([30, 25, 18, 40, 22, 15, 15, 20], BTN, "99",
                                                      acts=[(CO, "raise", 2.2)], plan="allin"), "r"
        yield "all-in plan, bubble chart", tournament([30, 25, 18, 40, 22, 8, 15, 20], BTN, "A9o", left=165,
                                                      avg_bb=30, plan="allin"), "r"
        yield "spin, first in", spin([12, 12, 12], 0, "AKs"), "r"
        yield "spin, over a limp", spin([14, 14, 14], 2, "KJo", acts=[(1, "call", None)]), "r"
        yield "spin, deep", spin([25, 25, 25], 0, "K7s"), "r"
        yield "all-in or fold", all_in_or_fold([8, 8, 8, 8], 1, "A5s", movers=[0]), "f"

    def test_thirteen_by_thirteen_with_hero_marked(self):
        for name, session, code in self.spots():
            with self.subTest(name):
                answer = A.advise(session)
                chart = answer["chart"]
                self.assertIsNotNone(chart, name)
                check_chart(self, chart)
                wanted = HANDS[parse_hand(session.data["hand"]["hero_cards"])[0]]
                self.assertEqual(chart["hero"], wanted)
                self.assertEqual(hero_cell(chart), code, verb(answer))

    def test_numbers_in_the_cells(self):
        solver = A.advise(tournament(STACKS_A, BTN, "A8o"))["chart"]
        row, column = divmod(HANDS.index("A8o"), 13)
        self.assertEqual(solver["numbers"][row][column], "+1.20bb")     # the engine's own number for hero's hand
        self.assertEqual(solver["numbers"][0][0][0], "+")               # aces earn
        call = A.advise(tournament([30, 25, 18, 40, 15, 22, 16, 20], BB, "99", acts=[(CO, "allin", None)]))["chart"]
        self.assertEqual(call["numbers"][5][5], "60%")                  # 99: its equity against the range
        table = A.advise(tournament(STACKS_B, CO, "K9s"))["chart"]
        self.assertEqual(table["numbers"][1][5], "all-in up to 8bb")    # K9s: the deepest stack that moves in
        self.assertIsNone(A.advise(tournament([30, 25, 18, 40, 15, 35, 16, 28], BTN, "QJs"))["chart"]["numbers"])

    def test_share_is_the_range(self):
        a = A.advise(tournament([30, 25, 18, 40, 15, 35, 16, 28], BTN, "QJs"))
        self.assertEqual(a["chart"]["share"], 41)           # the button's opening range
        self.assertEqual(a["tiles"][0]["value"], "41%")


# --------------------------------------------------------------------------
# Nothing to advise
# --------------------------------------------------------------------------

class NothingToAdvise(unittest.TestCase):
    def none(self, session, words):
        answer = A.advise(session)
        check_shape(self, answer)
        self.assertEqual(answer["status"], "none")
        self.assertIn(words, answer["spot"])
        return answer

    def test_what_is_awaited(self):
        s = Session(save=False)
        s.do("new_session", mode="tournament", size=6, start_stack=10000, button=1)
        self.none(s, "press N to deal")
        s.do("deal")
        self.none(s, "Type your two cards")
        s.do("set_cards", slot="hero", text="AKs")
        self.assertEqual(A.advise(s)["status"], "ready")
        s.do("act", seat=1, kind="raise", amount=440)
        self.none(s, "it is not your turn")
        s.do("act", seat=3, kind="call")
        self.none(s, "exact cards")                         # a class is enough before the flop only
        s.do("set_cards", slot="hero", text="AsKs")
        self.none(s, "Type the flop")
        s.do("set_cards", slot="flop", text="Kd7c2h")
        self.assertEqual(A.advise(s)["status"], "ready")
        s.do("act", seat=1, kind="fold")
        self.none(s, "press N for the next hand")

    def test_big_blind_waits_for_somebody_to_enter(self):
        s = tournament(STACKS_A, BB, "A8o")
        answer = self.none(s, "in the big blind you act last")
        self.assertEqual(answer["icm"], "estimated")        # the tournament's numbers are still told
        self.assertIn("icm_estimated", codes(answer))
        self.assertTrue(answer["context"]["stage"])

    def test_folded_and_all_in(self):
        s = tournament(STACKS_A, BTN, "72o")
        s.do("act", seat=1, kind="fold")                    # the blinds still have to act
        self.none(s, "You have folded")
        s = tournament(STACKS_A, CO, "AA", acts=[(UTG, "raise", 2.2)])
        s.do("act", seat=1, kind="allin")
        self.none(s, "You are all-in")

    def test_all_in_or_fold_big_blind_waits(self):
        self.none(all_in_or_fold([8, 8, 8, 8], 3, "JTs"), "Nobody has moved all-in yet")

    def test_spin_game_over(self):
        s = spin([2, 30, 30], 0, "72o")
        s.do("act", seat=1, kind="allin")
        s.do("act", seat=2, kind="call")
        s.do("act", seat=3, kind="fold")
        s.do("award", winner=2)
        self.none(s, "new game")


# --------------------------------------------------------------------------
# It never raises, and it never changes the table
# --------------------------------------------------------------------------

class NeverRaises(unittest.TestCase):
    def test_an_engine_error_becomes_no_advice(self):
        s = tournament(STACKS_A, BTN, "A8o")
        real = A.engine_advise

        def broken(spot):
            raise KeyError("UTG+3")

        A.engine_advise = broken
        try:
            answer = A.advise(s)
        finally:
            A.engine_advise = real
        check_shape(self, answer)
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(verb(answer), "NO ADVICE")
        self.assertEqual(answer["headline"]["tone"], "wait")
        self.assertIsNone(answer["headline"]["follow"])
        # the page gets plain words; the Python error is kept for the log and nowhere in the answer
        self.assertEqual(answer["reason"], "The coach cannot read this spot. Play it from the sheet; the next one is "
                                           "advised as usual.")
        self.assertNotIn("KeyError", json.dumps(answer))
        self.assertNotIn("UTG+3", json.dumps(answer))
        self.assertIn("KeyError: 'UTG+3'", A.last_fault)
        self.assertIn("Traceback", A.last_fault)
        self.assertTrue(answer["spot"].startswith("A8o on the button"))     # what was known stays
        self.assertTrue(answer["context"]["gear"])

    def test_anything_at_all_gets_an_answer(self):
        for junk in (None, object(), {"data": 1}):
            answer = A.advise(junk)
            self.assertEqual(verb(answer), "NO ADVICE")
            self.assertTrue(ANSWER_KEYS <= set(answer))
            json.dumps(answer, allow_nan=False)

    def test_the_session_is_only_read(self):
        s = tournament(STACKS_B, CO, "K9s")
        before = json.dumps(s.data, sort_keys=True), s.rev
        A.advise(s)
        self.assertEqual((json.dumps(s.data, sort_keys=True), s.rev), before)

    def test_answers_come_quickly(self):
        A.advise(tournament(STACKS_A, BTN, "A8o"))          # the first answer loads the tables
        for session in (tournament(STACKS_A, BTN, "A8o"), tournament(STACKS_B, CO, "K9s"),
                        tournament([30, 25, 18, 40, 15, 22, 16, 20], BB, "99", acts=[(CO, "allin", None)])):
            started = time.perf_counter()
            A.advise(session)
            self.assertLess(time.perf_counter() - started, 2.0)     # about a third of a second on a laptop


class RandomHands(unittest.TestCase):
    """Random legal hands in all three modes: an answer of the right shape every time, never an exception.

    Hero follows the coach most of the time, which also checks that the
    ``follow`` intent is one the table accepts.
    """

    def random_table(self, rng, mode):
        s = Session(save=False)
        if mode == "tournament":
            n = rng.randint(2, 9)
            bb = rng.choice([100, 600, 1000, 4000])
            s.do("new_session", mode=mode, size=n, start_stack=10000, button=rng.randint(1, n))
            s.do("set_level", text=f"{bb // 2}/{bb}/{rng.choice([0, bb // 8])}")
            if rng.random() < 0.2:
                s.do("set_ante_kind", kind="bb")
            # short tables bring out the all-in routes, deep ones the raise, re-raise and after-the-flop routes
            depths = rng.choice(([2, 5, 8, 12, 15, 20, 25, 35, 50, 80], [22, 28, 35, 45, 60, 80, 120]))
            s.do("set_stacks", values=[round(rng.choice(depths) * bb * rng.uniform(0.8, 1.2)) for _ in range(n)])
            if rng.random() < 0.8:
                paid = rng.choice([15, 50, 150])
                left = rng.choice([paid * 5, paid * 3, int(paid * 1.8), int(paid * 1.25), paid + 1, paid, paid // 2, n])
                numbers = {"remaining": max(left, 2), "paid": paid, "entrants": paid * 7}
                if rng.random() < 0.4:
                    numbers["start_stack"] = ""
                s.do("set_tournament", **numbers)
            s.do("set_config", plan=rng.choice(["full", "full", "allin"]),
                 style=rng.choice(["survive", "survive", "cash", "maxev"]),
                 opponents=rng.choice(["unknown", "unknown", "loose", "tight"]))
            if rng.random() < 0.15:
                s.do("set_config", reentry_open=True)
            for seat in range(2, n + 1):
                if rng.random() < 0.15:
                    s.do("set_type", seat=seat, type=rng.choice(["nit", "tight", "lag", "loose", "station", "maniac"]))
                if rng.random() < 0.05:
                    s.do("set_status", seat=seat, status="away")
        elif mode == "spin":
            bb = rng.choice([20, 40, 60, 100])
            s.do("new_session", mode=mode, start_stack=300, button=rng.randint(1, 3))
            s.do("set_level", text=f"{bb // 2}/{bb}")
            for seat in range(1, 4):
                s.do("set_stack", seat=seat, text=str(rng.choice([60, 150, 240, 300, 420, 600, 900])))
            if rng.random() < 0.25:
                s.do("clear_seat", seat=rng.choice([2, 3]))
            s.do("set_config", opponents=rng.choice(["solid", "loose", "very-loose"]))
        else:
            s.do("new_session", mode=mode, button=rng.randint(1, 4))
            for seat in range(1, 5):
                if rng.random() < 0.4:
                    s.do("set_stack", seat=seat, text=str(rng.choice([2, 3.5, 5.5, 6, 8])))
            s.do("set_config", opponents=rng.choice(["solid", "loose", "very-loose"]))
        return s

    def play_hand(self, rng, s, mode):
        """One hand from the deal to its end; returns how many answers were asked for."""
        deck = [card_str(card) for card in range(52)]
        rng.shuffle(deck)
        cards = deck.pop() + deck.pop()
        s.do("deal", hero_cards=cards)
        asked = 0
        for _step in range(80):
            answer = A.advise(s)                            # must not raise, whatever the table looks like
            asked += 1
            check_shape(self, answer)
            self.assertEqual(answer["rev"], s.rev)
            hand = s.view()["hand"]
            if hand is None or hand["needs"] == "next":
                return asked
            ready = answer["status"] == "ready"
            if ready:
                self.assertNotEqual(verb(answer), "NO ADVICE", f"{answer['reason']} | {answer['spot']}")
            elif answer["spot"].startswith("You have folded"):
                s.do("skip_hand")                           # nothing left to advise in this hand
                return asked
            if hand["needs"] == "board":
                street = {0: "flop", 3: "turn", 4: "river"}[len(hand["board"])]
                s.do("set_cards", slot=street, text="".join(deck.pop() for _ in range(3 if street == "flop" else 1)))
            elif hand["needs"] == "result":
                live = [seat["seat"] for seat in s.view()["table"]["seats"] if seat["in_hand"] and not seat["folded"]]
                s.do("award", ranking=[[seat] for seat in rng.sample(live, len(live))])
            elif hand["target_is_hero"]:
                self.assertTrue(ready, answer["spot"])      # hero's turn with his cards down: there is advice
                follow = answer["headline"]["follow"]
                if follow and rng.random() < 0.7:
                    s.do("act", seat=1, **follow)           # a ModelError here means the advice could not be carried out
                else:
                    self.random_action(rng, s, hand, mode)
            else:
                self.random_action(rng, s, hand, mode)
        self.fail("the hand did not end")

    def random_action(self, rng, s, hand, mode):
        legal = hand["legal"]
        options = ["fold"]
        if mode == "aof":
            options += ["fold", "allin"]
        else:
            options += ["check"] * 3 * bool(legal["check"]) + ["call"] * 3 * bool(legal["call"])
            options += ["bet"] * 2 * bool(legal["bet"]) + ["raise"] * 2 * bool(legal["raise"]) + ["allin"]
        kind = rng.choice(options)
        amount = None
        if kind in ("bet", "raise"):
            box = legal[kind]
            amount = rng.choice([box["min"], box["default"], min(box["max"], box["min"] * 2)])
        s.do("act", seat=hand["target"], kind=kind, amount=amount)

    def run_mode(self, mode, sessions, seed):
        rng = random.Random(seed)
        asked = 0
        for _ in range(sessions):
            s = self.random_table(rng, mode)
            for _hand in range(rng.randint(1, 3)):
                try:
                    asked += self.play_hand(rng, s, mode)
                except ModelError as err:                   # the table ran out of players, or a spin game ended
                    self.assertIn(err.message, ("A hand needs two players with chips.",), err.message)
                    break
                if mode == "spin" and s.data["game"]["over"]:
                    break
        return asked

    def test_tournament(self):
        self.assertGreater(self.run_mode("tournament", 28, seed=11), 150)

    def test_spin(self):
        self.assertGreater(self.run_mode("spin", 30, seed=12), 100)

    def test_all_in_or_fold(self):
        self.assertGreater(self.run_mode("aof", 80, seed=13), 150)


# --------------------------------------------------------------------------
# The review's findings (PRE-..., OPS-...): one test at least for each
# --------------------------------------------------------------------------

def source(answer) -> str:
    return answer["source"]


class engine_says:
    """For the length of a ``with`` block the engine gives this one answer: the adapter's own rules are then
    tested whatever the engine's numbers are today."""

    def __init__(self, action, confidence="standard", why=(), numbers=(), warnings=(), data=None):
        self.advice = Advice(action, confidence, "", list(why), list(numbers), [], list(warnings), dict(data or {}))

    def __enter__(self):
        self.real, A.engine_advise = A.engine_advise, lambda spot: self.advice
        return self

    def __exit__(self, *exc):
        A.engine_advise = self.real


class SurvivalGuardFindings(unittest.TestCase):
    """The guard's two strengths (strict in "Cash first", thin-edge in "Survive, then win") and its limits."""

    def test_pre_x1_a_re_raise_that_only_puts_a_short_raiser_all_in_is_not_the_stack(self):
        # button with 60bb, the cutoff has 10bb and raises to 2.2bb, the big blind has 60bb: the re-raise puts a
        # sixth of the stack at risk, so the guard has nothing to say, in either strength
        stacks = [20, 20, 20, 20, 10, 60, 20, 60]
        for style in (None, "cash"):
            for hand in ("QQ", "AKo"):
                with self.subTest(style=style, hand=hand):
                    a = A.advise(tournament(stacks, BTN, hand, acts=[(CO, "raise", 2.2)], left=300, paid=75,
                                            entrants=500, style=style))
                    self.assertEqual((verb(a), a["guard"]), ("RE-RAISE", "none"))
                    self.assertEqual(a["headline"]["qualifier"], "puts the raiser all-in")
                    self.assertEqual(a["headline"]["follow"], {"kind": "raise", "to": 10000})
        # the same hand as an all-in of 25bb with the big blind's 60bb behind does risk the stack: the strict
        # guard reads the table at those 25bb, and the default style plays a clear edge
        stacks[BTN] = 25
        strict = A.advise(tournament(stacks, BTN, "AJo", acts=[(CO, "raise", 2.2)], left=300, paid=75, entrants=500,
                                     style="cash"))
        self.assertEqual((verb(strict), strict["guard"]), ("FOLD", "survival"))
        self.assertIn("25 to 40bb", strict["reason"])
        default = A.advise(tournament(stacks, BTN, "AJo", acts=[(CO, "raise", 2.2)], left=300, paid=75, entrants=500))
        self.assertEqual((verb(default), default["guard"]), ("ALL-IN", "edge"))
        self.assertIn("CLEAR EDGE (engine +", source(default))
        self.assertIn("played although the all-in table folds", source(default))

    def test_pre_4_a_good_price_is_never_a_survival_fold(self):
        def short_big_blind(hand, hero_bb, shover, shove_bb, style):
            stacks = [20] * 8
            stacks[BB], stacks[shover] = hero_bb, shove_bb
            return A.advise(tournament(stacks, BB, hand, acts=[(shover, "allin", None)], style=style))

        for style in (None, "cash"):
            with self.subTest(style=style):
                # 875 more into a pot of 4,375: the blind already posted is no new risk, the guard does not look
                a = short_big_blind("K9o", 4, UTG, 2, style)
                self.assertEqual((verb(a), a["guard"]), ("CALL", "none"))
                # 1,375 into 4,875 is 3.5 to 1: the table would fold Q7o, the guard never folds that price
                a = short_big_blind("Q7o", 4, BTN, 2.5, style)
                self.assertEqual((verb(a), a["guard"]), ("CALL", "off"))
                self.assertIn("GUARD OFF (a good price: 3.5 to 1)", source(a))
                self.assertEqual(a["headline"]["follow"], {"kind": "call"})
                # 1,875 into 5,375 is worse than 3 to 1, but T8s has 21 points more than it needs
                a = short_big_blind("T8s", 6, BTN, 3, style)
                self.assertEqual((verb(a), a["guard"]), ("CALL", "off"))
                self.assertIn("GUARD OFF (a clear call: 48% against 27%)", source(a))
        # neither a good price nor a clear edge: the table still decides (72o, 32% against 29%)
        a = short_big_blind("72o", 5, SB, 3, None)
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("A thin edge (32% against 29%)", a["reason"])

    def test_pre_5_no_call_gets_tighter_at_41_big_blinds(self):
        # the table itself: every row of the call tables holds at 41bb (and deeper) what it holds at 40bb
        for players in BN.TABLES:
            for shover in ("early", "late", "button", "small", "two"):
                for bubble in (False, True):
                    for big_blind in (False, True):
                        at_40 = parse_range(BN.call(shover, 40, bubble, big_blind, players))
                        for deeper in (41, 60, 150):
                            row = parse_range(BN.call(shover, deeper, bubble, big_blind, players))
                            self.assertTrue(all(b >= a for a, b in zip(at_40, row)), (players, shover, bubble, deeper))
        # moving all-in first, or over a raise, with more than 40bb stays aces and kings
        self.assertEqual(BN.reshove("before", "late", 41), "AA, KK")
        self.assertEqual(BN.decide(HANDS.index("QQ"), 2, 41)[0], "FOLD")
        # through the coach, in the strict style: queens against a small blind all-in, tens against the cutoff's
        for stack in (40, 41):
            with self.subTest(stack=stack):
                a = A.advise(tournament([stack] * 8, BB, "QQ", acts=[(SB, "allin", None)], style="cash"))
                self.assertEqual((verb(a), a["guard"]), ("CALL", "agrees"))
                b = A.advise(tournament([stack] * 8, BTN, "TT", acts=[(CO, "allin", None)]))
                self.assertEqual((verb(b), b["guard"]), ("CALL", "agrees"))
        plan = A.advise(tournament([41] * 8, BB, "QQ", acts=[(SB, "allin", None)], plan="allin"))
        self.assertEqual(verb(plan), "CALL")
        self.assertIn("25 to 40bb column", " ".join(w["text"] for w in plan["warnings"]))

    def test_pre_6_no_find_an_all_in_beside_a_survival_fold(self):
        def with_clock(left, before, minutes):
            s = tournament([30, 25, 18, 40, 22, 12, 15, 20], BTN, "K7s", left=left)    # a thin edge: +0.18bb, +0.11bb
            now = time.time()                       # two "players left" marks: the field loses a player a minute
            s.data["tournament"]["history"] = [{"t": now - minutes * 60, "remaining": before},
                                               {"t": now, "remaining": left}]
            return A.advise(s)

        far = with_clock(300, 310, 10)              # 150 places from the money: hours away for a 12bb stack
        self.assertEqual((verb(far), far["guard"]), ("FOLD", "survival"))
        clock = far["context"]["fold_clock"]
        self.assertTrue(clock.startswith("The blinds give you about 4.8 orbits, about 35 minutes; the bubble is "
                                         "about 195 minutes away."), clock)
        everything = json.dumps(far).lower()
        self.assertNotIn("cannot fold", everything)
        self.assertNotIn("find an all-in", everything)
        near = with_clock(190, 200, 10)             # near the bubble the verdict is given, and "short" lifts the guard
        self.assertIn("You cannot fold into the money", near["context"]["fold_clock"])
        self.assertEqual((verb(near), near["guard"]), ("ALL-IN", "off"))
        self.assertIn("GUARD OFF (the fold clock says you cannot fold)", source(near))
        safe = with_clock(190, 230, 4)              # the same stack with the field busting fast: it can fold
        self.assertIn("You can fold into the money", safe["context"]["fold_clock"])
        self.assertEqual((verb(safe), safe["guard"]), ("FOLD", "survival"))
        self.assertIn("when the fold clock says you cannot fold", safe["flip"])

    def test_pre_7_the_default_style_only_folds_a_thin_edge(self):
        self.assertEqual((A.THIN_EV_BB_FAR, A.THIN_EV_BB_CLOSE), (0.20, 0.20))         # L1: one line for both
        self.assertEqual((A.THIN_EDGE_POINTS_FAR, A.THIN_EDGE_POINTS_CLOSE), (4, 7))
        # the measure itself: an all-in by the engine's "all-in against folding", a call by have minus need,
        # and a play without a number counts as thin
        for near in (False, True):
            self.assertEqual(A.engine_edge(A.Play("ALL-IN", "allin", facts={"ev": 0.20}), near),
                             (False, "engine +0.20bb"))
            self.assertEqual(A.engine_edge(A.Play("ALL-IN", "allin", facts={"ev": 0.19}), near),
                             (True, "engine +0.19bb"))
        call = A.Play("CALL", "call", facts={"need": 0.47, "equity": 0.53, "ev": 2.0})
        self.assertEqual(A.engine_edge(call, near=False), (False, "53% against 47%"))
        self.assertEqual(A.engine_edge(call, near=True), (True, "53% against 47%"))
        self.assertEqual(A.engine_edge(A.Play("RE-RAISE", "raise"), near=False), (True, ""))
        # thin and the table folds: the survival fold, in both styles (K9s in the cutoff, +0.15bb)
        for style in (None, "cash"):
            a = A.advise(tournament(STACKS_B, CO, "K9s", style=style))
            self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"), style)
        thin = A.advise(tournament(STACKS_B, CO, "K9s"))
        self.assertIn("A thin edge (+0.15bb)", thin["reason"])
        self.assertIn("with a clear edge", thin["flip"])
        # a clear edge far from the money: A8o on the button with 12bb at 300 left was a survival fold (+1.06bb)
        clear = A.advise(tournament(STACKS_A, BTN, "A8o", left=300))
        self.assertEqual(verb(clear), "ALL-IN")
        self.assertIn(clear["guard"], ("edge", "agrees"))

    def test_pre_7_seventeen_big_blinds_or_more_the_sheets_small_raise_not_a_fold(self):
        # 22 on the button with 18bb in "Cash first": the engine moves all-in for +0.35bb, the chart folds (22 is
        # an all-in up to 15bb there), and the sheet raises 22 from the button: the headline is that raise, with
        # the plan against an all-in.  (Cash first: since L1 the default style plays an edge of +0.20bb or more,
        # and the engine's all-ins with 17bb or more are all worth that.)
        s = tournament([18] * 8, BTN, "22", style="cash")
        a = A.advise(s)
        self.assertEqual((verb(a), a["guard"]), ("RAISE", "survival"))
        self.assertEqual(a["headline"]["qualifier"], "survival raise")
        self.assertEqual(a["headline"]["follow"], {"kind": "raise", "to": 2000})
        self.assertIn("SURVIVAL RAISE (engine: ALL-IN +0.35bb): the sheet's small raise", a["source"])
        self.assertIn("raise, and fold to an all-in", a["reason"])
        self.assertTrue(a["plans"] and all(": FOLD" in line for line in a["plans"]), a["plans"])
        self.assertEqual(hero_cell(a["chart"]), "r")
        # the next answer keeps that plan
        s.do("act", seat=1, kind="raise", amount=2000)
        s.do("act", seat=seat_of(BB, BTN, 8), kind="allin")
        self.assertEqual(verb(A.advise(s)), "FOLD")
        # the default style plays the same kind of edge: 44 in the cutoff with 18bb, +0.26bb
        default = A.advise(tournament([18] * 8, CO, "44"))
        self.assertEqual((verb(default), default["guard"]), ("ALL-IN", "edge"))
        self.assertIn("CLEAR EDGE (engine +0.26bb)", default["source"])
        # a hand the sheet does not raise from that seat is still a fold: K5o in the small blind (+0.07bb)
        fold = A.advise(tournament([18] * 8, SB, "K5o"))
        self.assertEqual((verb(fold), fold["guard"]), ("FOLD", "survival"))

    def test_pre_8_a_read_lifts_the_guard_only_when_it_makes_the_play_safer(self):
        def first_in(**more):                       # Q6o first in from the small blind with 10bb: a thin edge
            return A.advise(tournament([10] * 8, SB, "Q6o", **more))

        def call(**more):                           # A9o in the big blind (20bb) against a cutoff all-in of 15bb
            return A.advise(tournament([30, 25, 18, 40, 15, 22, 16, 20], BB, "A9o", acts=[(CO, "allin", None)], **more))

        # a big blind who folds too much makes the all-in safer; one who calls too much does not
        nit = first_in(types={BB: "nit"})
        self.assertEqual((verb(nit), nit["guard"]), ("ALL-IN", "off"))
        self.assertIn("GUARD OFF (a read on BB)", source(nit))
        for tag in ("station", "loose", "maniac"):
            with self.subTest(behind=tag):
                a = first_in(types={BB: tag})
                self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        # the player whose all-in hero calls: a wide raiser lifts it, a calling station does not
        self.assertEqual(verb(call()), "FOLD")
        station = call(types={CO: "station"})
        self.assertEqual((verb(station), station["guard"]), ("FOLD", "survival"))
        maniac = call(types={CO: "maniac"})
        self.assertEqual((verb(maniac), maniac["guard"]), ("CALL", "off"))
        self.assertIn("GUARD OFF (a read on CO)", source(maniac))
        # the table-wide setting is that tag on every untagged seat, for the guard as for the engine
        tight = first_in(opponents="tight")
        self.assertEqual((verb(tight), tight["guard"]), ("ALL-IN", "off"))
        self.assertIn("GUARD OFF (the table is set to tight)", source(tight))
        loose = first_in(opponents="loose")
        self.assertEqual((verb(loose), loose["guard"]), ("FOLD", "survival"))
        wild = call(opponents="maniac")
        self.assertEqual((verb(wild), wild["guard"]), ("CALL", "off"))
        self.assertIn("GUARD OFF (the table is set to maniac)", source(wild))

    def test_pre_12_raise_and_call_any_all_in_is_kept_when_the_all_in_comes(self):
        stacks = [14] + [30] * 7                    # hero under the gun with 14bb
        big_blind = seat_of(BB, UTG, 8)
        for left, hand in ((400, "AKo"), (185, "QQ")):
            with self.subTest(left=left, hand=hand):
                s = tournament(stacks, UTG, hand, left=left)
                first = A.advise(s)
                self.assertEqual(verb(first), "RAISE")
                self.assertEqual(first["headline"]["qualifier"], "and call any all-in")
                self.assertEqual(first["plans"], ["If anybody moves all-in: CALL"])
                self.assertEqual(first["guard"], "agrees")              # the guard looked at it as the whole stack
                s.do("act", seat=1, **first["headline"]["follow"])
                s.do("act", seat=big_blind, kind="allin")
                second = A.advise(s)
                self.assertEqual((verb(second), second["guard"]), ("CALL", "off"))
                self.assertIn("GUARD OFF (decided at your raise: call any all-in)", source(second))
        # on the bubble (185 left of 150 paid) the sheet folds ace-king to an all-in over a raise from the first
        # seats: the first answer is then not "raise and call any all-in" but the all-in itself
        for style in (None, "cash"):
            with self.subTest(style=style):
                bubble = A.advise(tournament(stacks, UTG, "AKo", left=185, style=style))
                self.assertEqual((verb(bubble), bubble["guard"]), ("ALL-IN", "agrees"))
                self.assertEqual(bubble["headline"]["qualifier"], "")
                self.assertEqual(bubble["plans"], [])
                self.assertIn("Do not raise and then fold", bubble["reason"])
    def test_pre_17_close_before_the_money_the_lower_variance_side_is_the_headline(self):
        small_raise = [(BTN, "raise", 2)]
        close_call = dict(action="CALL", confidence="close",
                          why=["not a profitable shove, but the big blind is getting the right price to see a flop"],
                          numbers=["their opening range ~41%; your equity vs it 33%; pot odds to call 18%"],
                          warnings=["play fit-or-fold after the flop"])
        with engine_says(**close_call):
            for style in (None, "cash"):
                with self.subTest(style=style):
                    # J2o is not on the sheet's big blind list: the fold leads, the engine's call is the second line
                    a = A.advise(tournament([18] * 8, BB, "J2o", acts=small_raise, style=style))
                    self.assertEqual((verb(a), a["guard"]), ("FOLD", "close"))
                    self.assertEqual(a["headline"]["qualifier"], "close: lower variance")
                    self.assertEqual(a["headline"]["sure"], "close")
                    self.assertEqual(a["headline"]["follow"], {"kind": "fold"})
                    self.assertIn("CLOSE: before the money the lower-variance side leads (engine: CALL, 33% against 18%)",
                                  source(a))
                    self.assertIn("By the numbers alone: CALL, 33% against 18%", a["also"])
                    self.assertIn("K9o+, Q9o+, J9o+ and T9o", a["reason"])
                    told = " ".join(w["text"] for w in a["warnings"])
                    self.assertNotIn("fit-or-fold", told)           # a warning about a call beside a fold
                    self.assertNotIn("close", codes(a))             # the reason says it
            # the sheet's list keeps the call: any pair, any suited hand, any ace, K9o+, Q9o+, J9o+, T9o
            for hand in ("K9o", "T2s", "A2o"):
                a = A.advise(tournament([18] * 8, BB, hand, acts=small_raise))
                self.assertEqual((verb(a), a["guard"]), ("CALL", "none"), hand)
                self.assertIn("the engine's close call is on the sheet's big blind list", source(a))
                close = next(w["text"] for w in a["warnings"] if w["code"] == "close")
                self.assertTrue(close.endswith("The sheet calls this hand in the big blind."), close)
                self.assertNotIn("lower-variance side leads", close)
            # with 25bb or more the sheet's own row for the big blind is read as well (against the button:
            # K3o+ and Q8o+), and the call is kept for the hands on that row and on the short list (D1), so
            # one more big blind of stack never turns a call into a fold; against a bigger raise the fold leads
            self.assertEqual(verb(A.advise(tournament([24] * 8, BB, "T2s", acts=small_raise))), "CALL")
            self.assertEqual(verb(A.advise(tournament([30] * 8, BB, "T2s", acts=small_raise))), "CALL")
            self.assertEqual(verb(A.advise(tournament([30] * 8, BB, "A3s", acts=small_raise))), "CALL")
            self.assertEqual(verb(A.advise(tournament([30] * 8, BB, "K9o", acts=small_raise))), "CALL")
            deep = A.advise(tournament([30] * 8, BB, "K2o", acts=small_raise))
            self.assertEqual((verb(deep), deep["guard"]), ("FOLD", "close"))
            self.assertIn("25bb or more against a raise from BTN", deep["reason"])
            self.assertEqual(verb(A.advise(tournament([18] * 8, BB, "T2s", acts=[(BTN, "raise", 3)]))), "FOLD")
            # in the money and in the Max EV style the engine's play stands, and no warning claims otherwise
            for more in (dict(left=100), dict(style="maxev")):
                a = A.advise(tournament([18] * 8, BB, "J2o", acts=small_raise, **more))
                self.assertEqual(verb(a), "CALL", more)
                self.assertNotIn("lower-variance side leads", " ".join(w["text"] for w in a["warnings"]))
        # a close raise gives way too: a re-raise as a bluff on the button
        with engine_says("3-BET to 6.6bb (semi-bluff, fold to a 4-bet)", "close",
                         numbers=["their opening range ~25%; your equity vs it 47%; pot odds to call 20%"]):
            a = A.advise(tournament([40] * 8, BTN, "A5s", acts=[(CO, "raise", 2.2)]))
            self.assertEqual((verb(a), a["guard"]), ("FOLD", "close"))
            self.assertIn("the raise and the fold are worth about the same", a["reason"])
            self.assertIn("(engine: RE-RAISE)", source(a))
        # ... but in the big blind the quieter play of a bluff re-raise is the call: A5s never folds where K2s calls
        with engine_says("3-BET to 8.4bb (semi-bluff, fold to a 4-bet)", "close",
                         numbers=["their opening range ~41%; your equity vs it 51%; pot odds to call 20%"]):
            a = A.advise(tournament([40] * 8, BB, "A5s", acts=[(BTN, "raise", 2.2)]))
            self.assertEqual((verb(a), a["guard"]), ("CALL", "close"))
            self.assertEqual(a["headline"]["follow"], {"kind": "call"})
            self.assertIn("lower-variance side leads: call", a["reason"])
        # when checking is free the quieter play is the check
        with engine_says("RAISE to 5bb", "close"):
            a = A.advise(tournament([30] * 8, BB, "KTo", acts=[(BTN, "call", None)]))
            self.assertEqual((verb(a), a["guard"]), ("CHECK", "close"))
            self.assertEqual(a["headline"]["follow"], {"kind": "check"})
        # and the engine as it is: K9o in the big blind with 20bb keeps its call (the sheet's list)
        real = A.advise(tournament([30, 25, 18, 40, 22, 25, 15, 20], BB, "K9o", acts=small_raise))
        self.assertEqual(verb(real), "CALL")

    def test_ops_note_queens_ace_king_and_king_jack_with_21_big_blinds_near_the_bubble(self):
        # the operations reviewer's hands: 96 left of 75 paid, 21.5bb, one raise to 2.2bb from UTG+1.  They were
        # survival folds: the table was read at 43bb ("aces and kings only"), a column it does not have
        raise_ = [(UTG1, "raise", 2.2)]
        numbers = dict(left=96, paid=75, entrants=500)
        for style in (None, "cash"):
            for hand in ("QQ", "AKs"):
                with self.subTest(style=style, hand=hand):
                    a = A.advise(tournament([21.5] * 8, BTN, hand, acts=raise_, style=style, **numbers))
                    self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "agrees"))
        # king-jack suited in the big blind: the engine's thin all-in gives way to the sheet's call, not to a fold
        a = A.advise(tournament([21.5] * 8, BB, "KJs", acts=raise_, **numbers))
        self.assertEqual((verb(a), a["guard"]), ("CALL", "survival"))
        self.assertEqual(a["headline"]["qualifier"], "survival call")
        self.assertEqual(a["headline"]["follow"], {"kind": "call"})
        self.assertIn("SURVIVAL CALL (engine: ALL-IN", source(a))
        self.assertIn("25 to 40bb", a["reason"])            # twice 21.5bb is read from the deepest column
        self.assertNotIn("AA, KK", a["reason"])
        # close to the money without being the bubble (130 left): the guard reads the same deepest column, and
        # the all-in plan keeps its own rule there: a hand must be good for twice the stack
        close = dict(numbers, left=130)
        guard = A.advise(tournament([21.5] * 8, BTN, "AKs", acts=raise_, style="cash", **close))
        self.assertEqual((verb(guard), guard["guard"]), ("ALL-IN", "agrees"))
        plan = A.advise(tournament([21.5] * 8, BTN, "AKs", acts=raise_, plan="allin", **close))
        self.assertEqual(verb(plan), "FOLD")
        self.assertIn("AA, KK", plan["reason"])

    def test_pre_11_a_re_raise_that_commits_is_judged_at_the_first_step_and_says_so(self):
        value = dict(action="3-BET to 6.6bb", why=["3-bet for value: you are ahead of the range that continues",
                                                   "do not fold to a 4-bet at this depth"],
                     numbers=["their opening range ~25%; your equity vs it 63%; pot odds to call 20%"])
        plan_line = "If anybody re-raises: do not fold, the chips go in at this depth"
        with engine_says(**value):
            # 30bb: the re-raise will not be folded, so the guard reads it as the whole stack, at this step
            tens = A.advise(tournament([30] * 8, BTN, "TT", acts=[(CO, "raise", 2.2)]))
            self.assertEqual((verb(tens), tens["guard"]), ("RE-RAISE", "agrees"))
            self.assertEqual(tens["headline"]["follow"], {"kind": "raise", "to": 6600})
            self.assertIn(plan_line, tens["plans"])
            for style in (None, "cash"):            # a hand the table does not play for 30bb: no number, so thin
                a = A.advise(tournament([30] * 8, BTN, "KQs", acts=[(CO, "raise", 2.2)], style=style))
                self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"), style)
                self.assertIn("SURVIVAL FOLD (engine: RE-RAISE)", source(a))
                self.assertIn("A re-raise at this depth commits the stack", a["reason"])
                self.assertEqual(a["plans"], [])
            # 60bb: a ninth of the stack, and the fold to another raise is still open: no guard, the line stays
            deep = A.advise(tournament([60] * 8, BTN, "TT", acts=[(CO, "raise", 2.2)]))
            self.assertEqual((verb(deep), deep["guard"]), ("RE-RAISE", "none"))
            self.assertIn(plan_line, deep["plans"])
        with engine_says("3-BET to 6.6bb", why=["re-raise for value", "never fold this hand to another raise here"]):
            self.assertIn(plan_line, A.advise(tournament([30] * 8, BTN, "QQ", acts=[(CO, "raise", 2.2)]))["plans"])
        with engine_says("3-BET to 6.6bb (semi-bluff, fold to a 4-bet)", why=["a blocker hand"]):
            bluff = A.advise(tournament([60] * 8, BTN, "A5s", acts=[(CO, "raise", 2.2)]))
            self.assertNotIn(plan_line, bluff["plans"])

    def test_the_plan_line_and_the_next_answer_count_the_same_players(self):
        # hero raises in the cutoff, the button folds, the small blind moves all-in, the big blind folds.  The
        # button was gone when the small blind moved; the big blind was still to act, as in the plan line
        s = tournament([30] * 8, CO, "TT")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat_of(SB, CO, 8), kind="allin")
        seen = A.read_table(s, s.view())
        self.assertEqual((seen.away[BTN], seen.away[BB]), (True, True))             # both are out of the hand
        self.assertEqual((seen.engine_away[BTN], seen.engine_away[BB]), (True, False))
        self.assertEqual(seen.engine_away[:CO + 1], [False] * (CO + 1))


    def test_l2_the_plan_line_and_the_next_answer_agree(self):
        plan = re.compile(r"If (.+?) \((\d+)bb\) moves all-in: (CALL|FOLD) \(need (\d+)%, have (\d+)%")
        # the review's example: the plan said FOLD (need 53%, have 49%) and the next answer CALL (57%)
        stacks = [27.3, 27.3, 12, 24, 9.5, 27.3]
        s = tournament(stacks, 3, "AJo", left=300, style="cash")
        first = A.advise(s)
        self.assertEqual(first["plans"], ["If BB (27bb) moves all-in: FOLD (need 53%, have 49%)"])
        s.do("act", seat=1, **first["headline"]["follow"])
        s.do("act", seat=seat_of(5, 3, 6), kind="allin")
        second = A.advise(s)
        self.assertEqual(verb(second), "FOLD")
        self.assertEqual(second["tiles"][0]["value"], "53% / 49%")
        # followed lines: every plan line under a raise, then that player's all-in
        followed, verdicts = 0, set()
        spots = [(stacks, 3, 300, None, ("AJo", "KQo", "99")),
                 ([30] * 8, CO, 160, None, ("AJo", "ATs", "88")),
                 ([35, 28, 22, 40, 18, 30, 14, 26], BTN, 185, "cash", ("AJo", "A8s", "66", "QJs")),
                 ([40, 22, 35, 28, 30, 25, 12, 38], HJ, 400, None, ("AQo", "TT", "KQs")),
                 ([38, 30, 26, 30], 1, 152, "maxev", ("ATs", "88", "KQo"))]
        for stacks, hero, left, style, hands in spots:
            n = len(stacks)
            for hand in hands:
                table = tournament(stacks, hero, hand, left=left, style=style)
                first = A.advise(table)
                if first["headline"]["follow"]["kind"] != "raise":
                    continue
                seen = A.read_table(table, table.view())
                for line in first["plans"]:
                    found = plan.match(line)
                    if not found:
                        continue
                    who = next(i for i in range(n) if i != hero and seen.who(i) == found.group(1))
                    again = tournament(stacks, hero, hand, left=left, style=style)
                    again.do("act", seat=1, **first["headline"]["follow"])
                    again.do("act", seat=seat_of(who, hero, n), kind="allin")
                    second = A.advise(again)
                    key = (stacks, hero, hand, left, style, line, verb(second), second["source"])
                    self.assertEqual(verb(second) == "FOLD", found.group(3) == "FOLD", key)
                    numbers = next(one["value"] for one in second["tiles"] if one["label"] == "Need / have")
                    self.assertEqual(numbers, f"{found.group(4)}% / {found.group(5)}%", key)
                    followed += 1
                    verdicts.add(found.group(3))
        self.assertGreaterEqual(followed, 12)
        self.assertEqual(verdicts, {"CALL", "FOLD"})

    def test_l2_the_plan_lines_close_is_judged_by_the_unrounded_numbers(self):
        # hero (60bb) raises to 2.2bb on the button and the big blind (10bb) moves all-in: a cheap call, which
        # the next answer folds only when the engine marks it close: less than 2 points apart, unrounded
        s = tournament([60, 60, 60, 60, 60, 60, 60, 10], BTN, "A9o")
        seen, money = A.read_table(s, s.view()), A.read_money(s)

        def folds(points, exact=None):
            return A.call_after_my_raise_folds(seen, money, BB, 2200, points, False, False, exact)

        self.assertEqual(folds((40, 42)), "")                       # no exact numbers: by the line's own points
        self.assertEqual(folds((40, 41)), "close")
        self.assertEqual(folds((40, 42), (0.4040, 0.4239)), "close")    # 1.99 points: the engine says close
        self.assertEqual(folds((40, 41), (0.3951, 0.4149)), "close")
        self.assertEqual(folds((40, 42), (0.3951, 0.4249)), "")         # 2.98 points
        self.assertEqual(folds((39, 41), (0.3949, 0.4149)), "")         # 2.00 points: not close
        self.assertEqual(folds((40, 41), (0.3951, 0.4151)), "")         # reads 1 point, is 2.00: not close
        # the numbers come from the engine's plan, by the name the line uses
        self.assertEqual(A.plan_numbers(seen, [{"idx": BB, "need": 0.4, "eq": 0.42}, {"idx": 99, "need": 0, "eq": 0}]),
                         {"BB": (0.4, 0.42)})
        s = tournament([35, 35, 35, 35, 35, 35, 35, 10], BTN, "A9o")
        seen, money = A.read_table(s, s.view()), A.read_money(s)
        play = A.full_plan_play(seen, money)
        exact = A.plan_numbers(seen, play.facts["plan"])
        self.assertTrue(play.plans and len(exact) == len(play.plans), (play.plans, exact))
        for line in play.plans:
            who, _stack, _verdict, need, have = A.PLAN_LINE.match(line).groups()
            self.assertEqual((f"{100 * exact[who][0]:.0f}", f"{100 * exact[who][1]:.0f}"), (need, have), line)

    def test_l3_an_all_in_and_a_caller_with_chips_is_one_all_in_for_the_guard(self):
        # the button is all-in for 10bb, the small blind (40bb) calls, hero is the big blind with 20bb.  The
        # engine's CALL is a call of the 10bb all-in with a caller in the pot: the guard reads the row for one
        # all-in from the button (KQs is on it), not the row for two all-ins (77+, AJs+, AQo+)
        stacks = [30, 30, 30, 30, 30, 10, 40, 20]
        acts = [(BTN, "allin", None), (SB, "call", None)]
        for style in (None, "cash"):
            a = A.advise(tournament(stacks, BB, "KQs", acts=acts, style=style))
            self.assertEqual((verb(a), a["guard"]), ("CALL", "agrees"), style)
            self.assertEqual(a["headline"]["size_text"], "8.9BB \u00b7 8,875")     # what is still to pay
        s = tournament(stacks, BB, "KQs", acts=acts)
        seen, money = A.read_table(s, s.view()), A.read_money(s)
        before = A.what_happened(seen)
        call = A.table_answer(seen, money, before, at_risk=20.0, calling=True)
        self.assertEqual(call.action, "CALL")
        self.assertIn("an all-in of 10bb from BTN", call.why)
        self.assertIn("a caller is in the pot", call.why)
        self.assertIn("an all-in from BTN with a caller in the pot", call.chart["title"])
        self.assertTrue(A.in_range(call.short, HANDS.index("KQs")))
        # a re-raise over the two of them plays for the caller's chips too: still the row for two all-ins,
        # and so does the all-in plan, which has one decision for the hand
        for says in (A.table_answer(seen, money, before, at_risk=20.0), A.table_answer(seen, money, before)):
            self.assertEqual(says.action, "FOLD")
            self.assertIn("two all-ins", says.why)
        plan = A.advise(tournament(stacks, BB, "KQs", acts=acts, plan="allin"))
        self.assertEqual(verb(plan), "FOLD")
        self.assertIn("two all-ins", plan["reason"])
        tens = A.advise(tournament(stacks, BB, "TT", acts=acts, left=185, style="cash"))
        self.assertEqual((verb(tens), tens["guard"]), ("FOLD", "survival"))
        self.assertIn("two all-ins", tens["reason"])
        # a caller who is all-in himself is a second all-in, whatever the play
        short = [30, 30, 30, 30, 30, 10, 9, 20]
        s = tournament(short, BB, "KQs", acts=acts)
        seen, money = A.read_table(s, s.view()), A.read_money(s)
        says = A.table_answer(seen, money, A.what_happened(seen), at_risk=20.0, calling=True)
        self.assertIn("two all-ins", says.why)


class VeryLargeFields(unittest.TestCase):
    """L6 (ROB-10): the prize model is thinned above ``PRIZE_PLACES`` paid places, so the answer stays quick."""

    @staticmethod
    def field(entrants, left, paid, bb=600, stacks=None, style=None, cards="AJs"):
        s = Session(save=False)
        s.do("new_session", mode="tournament", size=8, start_stack=20000, level=f"{bb // 2}/{bb}/{bb // 8}",
             entrants=entrants, remaining=left, paid=paid, button=2)
        if stacks:
            s.do("set_stacks", values=[x * bb for x in stacks])
        if style:
            s.do("set_config", style=style)
        if cards:
            s.do("deal", hero_cards=cards)
        return s

    @staticmethod
    def models(s):
        from poker_coach import state as S
        from poker_coach.app.model import goal_for
        state = s.engine_state()
        exact = S.build_prizes(state, goal_for(s.data))
        return exact, A.thinned_prizes(exact, len(S.occupied(state)))

    def test_l6_150_000_entrants_are_answered_quickly(self):
        s = self.field(150000, 30000, 22000)
        started = time.perf_counter()
        a = A.advise(s)
        took = time.perf_counter() - started
        self.assertEqual((a["status"], a["icm"]), ("ready", "on"))
        self.assertLess(took, 3.0, "12 seconds before the cap; about 0.2 s with it")
        exact, thin = self.models(s)
        self.assertEqual(len(exact.raw_payouts), 22000)
        self.assertLessEqual(len(thin.raw_payouts), A.PRIZE_PLACES + 8)      # the 8 players at the table stay as they are
        self.assertLessEqual(thin.field_n, 30000 // 22 + 2)
        self.assertEqual((thin.field_stack, thin.itm_bonus), (exact.field_stack, exact.itm_bonus))
        # the stage, the fold clock and the source line still read the real numbers
        self.assertIn("ICM", a["source"])
        self.assertEqual(A.read_money(s).stage["remaining"], 30000)

    def test_l6_a_5_000_entrant_field_is_not_touched(self):
        for left in (1200, 800, 755, 700, 40):
            exact, thin = self.models(self.field(5000, left, 750))
            self.assertIs(thin, exact, left)                       # 750 paid places: under the cap, the same object
        # and late in a huge field, with fewer players left than the cap, it is the exact ladder again
        exact, thin = self.models(self.field(150000, 900, 22000))
        self.assertIs(thin, exact)
        self.assertGreater(A.PRIZE_PLACES, 750)

    def test_l6_the_thinned_ladder_keeps_the_money_line_and_the_prizes(self):
        # before the money at least one place stays unpaid; in the money everybody left is paid
        for left, unpaid in ((30000, None), (22100, None), (22003, 1), (22001, 1), (22000, 0), (21000, 0), (5000, 0)):
            exact, thin = self.models(self.field(150000, left, 22000))
            places = 8 + thin.field_n
            key = (left, places, len(thin.raw_payouts))
            if left > 22000:
                self.assertLess(len(thin.raw_payouts), places, key)
                self.assertAlmostEqual((places - len(thin.raw_payouts)) / places, (left - 22000) / left, delta=0.002,
                                       msg=key)
            else:
                self.assertEqual(len(thin.raw_payouts), places, key)
            if unpaid is not None:
                self.assertEqual(places - len(thin.raw_payouts), unpaid, key)
            # the ladder still falls, top to bottom, ends on the smallest prize, and pays the same per player
            pays = thin.raw_payouts
            self.assertTrue(all(a >= b for a, b in zip(pays, pays[1:])), key)
            reachable = exact.raw_payouts[:min(22000, left)]
            self.assertAlmostEqual(pays[-1], reachable[-1], places=9, msg=key)
            self.assertAlmostEqual(sum(pays) / len(pays), sum(reachable) / len(reachable), delta=1e-6 * pays[0],
                                   msg=key)
            self.assertLess(len(set(pays)), 120, key)              # bands that pay one prize stay one pay jump

    def test_l6_the_thinned_model_prices_risk_like_the_exact_one(self):
        # 20,000 entrants and 3,000 paid, stacks around the average: far from the money, near it, on the
        # bubble and in the money.  The risk premium (points of equity) is the number the answers are made of
        stacks = [10, 60, 33, 33, 20, 45, 15, 80]
        for left, tolerance, styles in ((4000, 0.3, (None,)), (3010, 0.6, (None, "cash")), (3001, 1.5, ("cash",)),
                                        (2900, 0.3, (None,))):
            bb = max(100, int(20000 * 20000 / left / 30 / 100) * 100)
            for style in styles:
                exact, thin = self.models(self.field(20000, left, 3000, bb=bb, stacks=stacks, style=style, cards=""))
                self.assertIsNot(thin, exact)
                chips = [float(x * bb) for x in stacks]
                for hero, villain in ((0, 1), (1, 0), (3, 7)):
                    want, got = exact.risk_premium(chips, hero, villain), thin.risk_premium(chips, hero, villain)
                    self.assertAlmostEqual(100 * got, 100 * want, delta=tolerance, msg=(left, style, hero, villain))


class Words(unittest.TestCase):
    """L7 (VIS-17): plain words in every sentence the user reads; the source line alone keeps the manual's."""

    FORBIDDEN = ("engine", "guard", "all-in table", "table says", "table read", "spin table", "solved table",
                 "bubble table", "the tables", "table's", "traceback", "error", "exception")

    @staticmethod
    def sentences(answer):
        """Every string of an answer the page shows, except the source line."""
        out = [answer[key] for key in ("spot", "reason", "flip", "also", "provisional")]
        out += list(answer["plans"]) + [w["text"] for w in answer["warnings"]] + list(answer["context"].values())
        for one in answer["tiles"]:
            out += [one["label"], one["value"], one["note"]]
        if answer["headline"]:
            out += [answer["headline"]["qualifier"], answer["headline"]["size_text"]]
        if answer["chart"]:
            out += [answer["chart"]["title"]] + [item["label"] for item in answer["chart"]["legend"]]
        return [text for text in out if text]

    def spots(self):
        yield from ((name, session) for name, session, _code in Charts().spots())
        yield "survival fold, cash", tournament(STACKS_A, BTN, "A5o", left=260, style="cash")
        yield "survival fold, thin", tournament(STACKS_B, CO, "K9s")
        yield "clear edge", tournament(STACKS_A, BTN, "A5o", left=260)
        yield "survival raise", tournament([18] * 8, BTN, "22", style="cash")
        yield "close fold", tournament([35, 25, 18, 22, 15, 25, 16, 18], HJ, "TT", acts=[(UTG, "raise", 2.2)])
        yield "close call", tournament([30, 25, 18, 40, 22, 25, 15, 20], BB, "K9o", acts=[(BTN, "raise", 2)])
        yield "clear edge call", tournament([30, 25, 18, 40, 15, 22, 16, 20], BB, "99", acts=[(CO, "allin", None)],
                                            left=152)
        yield "good price", tournament([30, 30, 30, 30, 30, 30, 3, 30], BB, "T7o", acts=[(SB, "allin", None)])
        yield "final table", tournament([30, 25, 18, 40, 22, 12, 15, 40], SB, "A9s", left=8)
        yield "final table, covered", tournament([30, 25, 18, 40, 22, 40, 15, 20], BB, "AJo",
                                                 acts=[(BTN, "allin", None)], left=8)
        yield "prizes unknown", tournament(STACKS_A, BTN, "A8o", left=None)
        yield "heads-up", tournament([18, 30], 0, "K5o", left=2)
        yield "big blind, close", tournament([30] * 8, BB, "K7o", acts=[(BTN, "raise", 2.2)])
        yield "all-in plan, limped", tournament([15] * 8, BB, "T7o", acts=[(BTN, "call", None)], plan="allin")
        yield "all-in plan, deep", tournament([41] * 8, BB, "QQ", acts=[(SB, "allin", None)], plan="allin")
        yield "nine players", tournament([20] * 9, 6, "A8o", plan="allin")
        yield "spin, no row", spin([20, 20, 20], 1, "A9o", acts=[(0, "call", None)])
        yield "spin, stacks differ", spin([12, 9, 15], 0, "K7s")
        yield "all-in or fold, loose", all_in_or_fold([8, 8, 8, 8], 2, "T5s", opponents="loose")
        reentry = tournament(STACKS_A, BTN, "A8o")
        reentry.data["tournament"]["reentry_open"] = True
        yield "re-entry open", reentry

    def test_l7_no_engine_and_no_guard_outside_the_source_line(self):
        seen_sources = set()
        for name, session in self.spots():
            answer = A.advise(session)
            self.assertEqual(answer["status"], "ready", name)
            seen_sources.add(answer["source"].split(" \u00b7 ")[-1].split(" (")[0])
            for text in self.sentences(answer):
                low = text.lower()
                for word in self.FORBIDDEN:
                    self.assertNotIn(word, low, (name, text))
        # the source line keeps the words the manual documents
        self.assertTrue({"the engine decides", "the all-in table agrees", "SURVIVAL FOLD", "CLEAR EDGE",
                         "GUARD OFF"} <= seen_sources, seen_sources)

    def test_l7_the_second_line_says_by_the_numbers_alone(self):
        fold = A.advise(tournament(STACKS_A, BTN, "A5o", left=260, style="cash"))
        self.assertEqual(fold["also"], "By the numbers alone: ALL-IN +0.44bb (the Max EV style plays it).")
        self.assertEqual(fold["tiles"][0]["note"], "by the numbers alone")
        self.assertEqual(fold["tiles"][-1]["label"], "The chart says")
        self.assertEqual(fold["flip"], "Played by the numbers again once in the money, or with a read that makes "
                                       "it safer.")
        self.assertIn("SURVIVAL FOLD (engine: ALL-IN +0.44bb)", fold["source"])     # the source line: as documented
        self.assertEqual(A.by_the_numbers("CALL, 60% against 53%"), "By the numbers alone: CALL, 60% against 53%.")

    def test_l7_the_survival_fold_reason_is_short(self):
        # was: "Before the money the all-in table does not risk the stack here (A5o from BTN is an all-in only
        # up to 15bb before the money (read at twice your stack this close to the money))."
        strict = A.advise(tournament(STACKS_A, BTN, "A5o", left=260, style="cash"))
        self.assertEqual(strict["reason"], "Fold before the money: A5o from the button is an all-in only up to 15bb, "
                                           "and this close to the money your 12bb counts double.")
        thin = A.advise(tournament(STACKS_B, CO, "K9s"))
        self.assertEqual(thin["reason"], "A thin edge (+0.15bb): fold before the money. K9s from the cutoff is an "
                                         "all-in only up to 8bb.")
        small = A.advise(tournament([18] * 8, BTN, "22", style="cash"))
        self.assertEqual(small["reason"], "No all-in before the money: 22 from the button is an all-in only up to "
                                          "15bb. The sheet raises this hand small from this seat instead: raise, "
                                          "and fold to an all-in.")
        for answer in (strict, thin, small):
            self.assertNotIn("((", answer["reason"])
            self.assertNotIn("BTN", answer["reason"])
        # the all-in plan reads the same chart in the same words
        plan = A.advise(tournament(STACKS_A, BTN, "A5o", left=260, plan="allin"))
        self.assertEqual(plan["reason"], "A5o from the button is an all-in only up to 15bb before the money, and "
                                         "this close to the money your 12bb counts double.")
        self.assertEqual(plan["tiles"][0]["label"], "The chart")
        self.assertTrue(plan["also"].startswith("With all moves, on these stacks: "), plan["also"])

    def test_l7_no_advice_never_shows_a_python_error(self):
        import contextlib
        import io
        s = tournament(STACKS_A, BTN, "A8o")
        real, verbose = A.engine_advise, A.VERBOSE

        def broken(spot):
            raise KeyError("UTG+3")

        A.engine_advise = broken
        try:
            for setting, printed in ((False, False), (True, True)):
                A.VERBOSE = setting
                log = io.StringIO()
                with contextlib.redirect_stderr(log):
                    answer = A.advise(s)
                self.assertEqual(verb(answer), "NO ADVICE")
                self.assertEqual(answer["reason"], "The coach cannot read this spot. Play it from the sheet; the "
                                                   "next one is advised as usual.")
                whole = json.dumps(answer)
                for word in ("KeyError", "UTG+3", "Traceback", "engine"):
                    self.assertNotIn(word, whole)
                self.assertEqual("KeyError: 'UTG+3'" in log.getvalue(), printed, setting)   # --verbose: the detail
                self.assertIn("KeyError: 'UTG+3'", A.last_fault)
        finally:
            A.engine_advise, A.VERBOSE = real, verbose
        self.assertIsNone(A.VERBOSE)                    # as shipped: on when the program was started with --verbose

    def test_l7_one_player_is_not_one_players(self):
        a = A.advise(tournament([30] * 8, SB, "A2o"))
        self.assertEqual(a["reason"], "Outside the opening range for SB with 1 player behind.")
        heads_up = A.advise(tournament([30, 30], 0, "A2o", left=2))
        self.assertIn("with 1 player behind", heads_up["reason"])
        self.assertIn("with 2 players behind", A.advise(tournament([30] * 8, BTN, "QJs"))["reason"])

    def test_l7_the_fold_clock_line(self):
        def with_clock(left, before, minutes):
            s = tournament(STACKS_A, BTN, "K7s", left=left)
            now = time.time()
            if before:
                s.data["tournament"]["history"] = [{"t": now - minutes * 60, "remaining": before},
                                                   {"t": now, "remaining": left}]
            return A.advise(s)

        short = with_clock(190, 200, 10)["context"]["fold_clock"]
        self.assertRegex(short, r"^You cannot fold into the money: the blinds take 35 minutes to eat your stack, "
                                r"the bubble needs about \d+\. Find an all-in\.")
        safe = with_clock(190, 230, 4)["context"]["fold_clock"]
        self.assertRegex(safe, r"^You can fold into the money: the blinds take 35 minutes to eat your stack, "
                               r"the bubble needs about \d+\.")
        # near the bubble with nothing to time it by: the one fact, and the request is a warning, not the line
        unknown = with_clock(190, None, 0)
        self.assertTrue(unknown["context"]["fold_clock"].startswith("The blinds take 35 minutes to eat your stack."),
                        unknown["context"]["fold_clock"])
        s = tournament(STACKS_A, BTN, "K7s", left=190)
        money = A.read_money(s)
        self.assertTrue(A.no_bubble_estimate(money))
        texts = [w["text"] for w in A.standing_warnings(s.data, money, time.time())]
        self.assertIn("For the fold clock, change players left twice, a minute apart: then it can say whether you "
                      "can fold into the money.", texts)
        # far from the bubble the clock gives no verdict, so nothing is asked for
        far = tournament(STACKS_A, BTN, "K7s", left=400)
        self.assertFalse(A.no_bubble_estimate(A.read_money(far)))
        for answer in (unknown, A.advise(far), with_clock(300, 310, 10)):
            line = answer["context"]["fold_clock"]
            self.assertNotIn("Change players left", line)
            self.assertNotIn("orbits of blinds", line)
        # the sit-out line, in plain words
        a = A.advise(tournament([30, 25, 18, 40, 22, 8, 15, 20], BTN, "A9o", left=165, avg_bb=30, plan="allin"))
        self.assertIn("You hold 31% of what it takes to fold into the money (the sit-out line).",
                      a["context"]["fold_clock"])

    def test_l7_under_one_big_blind_is_not_0bb_effective(self):
        # the three players behind hero hold under one big blind each: they are all-in or nearly
        a = A.advise(tournament([30, 30, 30, 30, 30, 0.5, 0.7, 0.6], CO, "K9o"))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertEqual(a["reason"], "The players behind you hold less than one big blind, so they are all-in or "
                                      "nearly, and this all-in makes money.")
        self.assertNotIn("0bb effective", json.dumps(a))
        self.assertNotIn("1bb effective", json.dumps(a))
        self.assertEqual(a["headline"]["size_text"], "29.9BB \u00b7 29,875")  # the all-in as the button records it
        self.assertEqual(a["headline"]["qualifier"], "0.6bb of your 29.9bb can be matched")
        ordinary = A.advise(tournament([8] * 8, BTN, "A8o"))
        self.assertIn("8bb effective is all-in or fold territory", ordinary["reason"])


class PlanAndTableFindings(unittest.TestCase):
    """The all-in plan, the spin rows, All-In or Fold, the stage and the numbers on one answer."""

    def test_pre_13_the_all_in_plan_never_just_calls_a_raise(self):
        # the hijack has 6bb and raises to 2.5bb: a third of his stack is read as an all-in, and the table calls
        # it with ace-king.  He still has chips, so the play is the all-in: verb, size and the Follow button
        stacks = [20, 20, 20, 6, 20, 20, 20, 20]
        a = A.advise(tournament(stacks, BTN, "AKo", acts=[(HJ, "raise", 2.5)], plan="allin"))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertEqual(a["headline"]["follow"], {"kind": "allin"})
        self.assertEqual(a["headline"]["size_text"], "19.9BB \u00b7 19,875")
        self.assertEqual(a["headline"]["tone"], "attack")
        self.assertIn("move all-in yourself", a["reason"])
        self.assertNotEqual(verb(A.advise(tournament(stacks, BTN, "72o", acts=[(HJ, "raise", 2.5)], plan="allin"))),
                            "CALL")
        # against a real all-in the call stays a call
        b = A.advise(tournament(stacks, BTN, "AKo", acts=[(HJ, "allin", None)], plan="allin"))
        self.assertEqual(verb(b), "CALL")
        self.assertEqual(b["headline"]["follow"], {"kind": "call"})
        self.assertEqual(b["headline"]["size_text"], "5.9BB \u00b7 5,875")

    def test_pre_14_spin_a_small_raise_from_a_short_stack_is_all_in_or_fold(self):
        every_fourth = range(0, 169, 4)

        def same_as_the_table(stacks, hero, raiser, row, eff):
            for hand in every_fourth:
                a = A.advise(spin(stacks, hero, HANDS[hand], acts=[(raiser, "raise", 2)]))
                wanted = SP.decide(hand, row, eff)[0]
                self.assertEqual(verb(a), "ALL-IN" if wanted == "CALL" else wanted, (stacks, HANDS[hand]))
                self.assertNotEqual(a["headline"]["follow"], {"kind": "call"}, HANDS[hand])     # never a flat call

        same_as_the_table([6, 6, 6], 1, 0, "sb_vs_btn_raise", 6)       # the raise rows: all-in with a third, fold the rest
        same_as_the_table([5, 5, 5], 2, 1, "bb_vs_sb_raise", 5)        # 5.5bb or less: read as an all-in
        same_as_the_table([4, 10, 10], 2, 0, "bb_vs_btn_raise", 4)     # the raiser's stack counts, not the 2bb he put in
        # J4s in the big blind against a 5bb small blind who raised to 2bb: inside the calls, but he has chips
        # behind, so the play is the all-in
        a = A.advise(spin([5, 5, 5], 2, "J4s", acts=[(1, "raise", 2)]))
        self.assertEqual(verb(a), "ALL-IN")
        self.assertEqual(a["headline"]["follow"], {"kind": "allin"})
        self.assertEqual(a["tiles"][0]["label"], "All-in against folding")
        self.assertEqual(a["tiles"][1]["note"], "chart read at 5bb")
        self.assertIn("move all-in yourself", a["reason"])

    def test_pre_15_spin_both_all_in_with_equal_stacks_uses_the_solved_row(self):
        # the small blind's all-in only matches the button's, so it is recorded as a call: he is all-in all the same
        both = [(0, "allin", None), (1, "allin", None)]
        for stack, hand, wanted in ((10, "KQo", "CALL"), (10, "KTs", "CALL"), (10, "A8o", "FOLD"), (20, "AQo", "CALL"),
                                    (6, "A8o", "CALL")):
            with self.subTest(stack=stack, hand=hand):
                a = A.advise(spin([stack] * 3, 2, hand, acts=both))
                self.assertEqual(SP.decide(HANDS.index(hand), "bb_vs_both", stack)[0], wanted)
                self.assertEqual(verb(a), wanted)
                self.assertIn("Spin table", source(a))
                self.assertNotIn("outside_tables", codes(a))

    def test_pre_16_all_in_or_fold_the_big_blind_is_answered_from_the_loose_table(self):
        # nobody acts after the big blind, so the table is judged by the players who have already moved all-in
        cutoff_and_button = [0, 1]
        solid = A.advise(all_in_or_fold([8, 8, 8, 8], 3, "A9s", movers=cutoff_and_button))
        self.assertEqual(verb(solid), "FOLD")
        self.assertEqual(source(solid), "All-In or Fold table: cash, 0.1bb fee")
        for setting, family in (("loose", "cash-loose"), ("very-loose", "cash-vloose")):
            with self.subTest(setting):
                a = A.advise(all_in_or_fold([8, 8, 8, 8], 3, "A9s", movers=cutoff_and_button, opponents=setting))
                wanted = AOF.decide(HANDS.index("A9s"), 4, 3, 0b011, [8, 8, 8, 8], family)
                self.assertEqual((verb(a), wanted.action), ("CALL", "ALL-IN"))
                self.assertEqual(a["tiles"][0]["value"], f"+{wanted.ev:.2f}bb")
                self.assertIn("too wide", source(a))
        # a tag on the players who moved in counts before the setting: two solid players, the solid table
        s = all_in_or_fold([8, 8, 8, 8], 3, "A9s", opponents="loose")
        for index in cutoff_and_button:
            s.do("set_type", seat=seat_of(index, 3, 4), type="tight")
            s.do("act", seat=seat_of(index, 3, 4), kind="allin")
        self.assertEqual(verb(A.advise(s)), "FOLD")

    def test_ops_17_all_in_or_fold_a_call_says_what_is_still_to_pay(self):
        # the big blind has 8bb, the button moves all-in for 7.5bb: 6.5bb more, and the Follow button says call
        a = A.advise(all_in_or_fold([8, 7.5, 8, 8], 3, "KK", movers=[1]))
        self.assertEqual((verb(a), a["headline"]["size_text"]), ("CALL", "6.5BB"))
        self.assertEqual(a["headline"]["follow"], {"kind": "call"})
        s = all_in_or_fold([8, 7.5, 8, 8], 3, "KK", movers=[1])
        s.do("act", seat=1, **A.advise(s)["headline"]["follow"])       # the table takes it (as the all-in it is)
        self.assertEqual(s.view()["hand"]["needs"], "result")
        self.assertEqual(a["headline"]["qualifier"], "")
        # the small blind against a short button with the big blind behind: 2bb call the all-in, but in this
        # game the whole stack goes in and the big blind can call it: the headline says so
        short = A.advise(all_in_or_fold([8, 2.5, 8, 8], 2, "AA", movers=[1]))
        self.assertEqual((verb(short), short["headline"]["size_text"]), ("CALL", "2BB"))
        self.assertEqual(short["headline"]["qualifier"], "all your chips go in")
        self.assertEqual(short["headline"]["follow"], {"kind": "call"})
        # first in the headline is the all-in, with the whole stack
        first = A.advise(all_in_or_fold([8, 8, 8, 8], 2, "AA"))
        self.assertEqual((verb(first), first["headline"]["size_text"]), ("ALL-IN", "8BB"))
        self.assertEqual(first["headline"]["follow"], {"kind": "allin"})

    def test_pre_19_one_place_from_the_money_is_the_bubble_in_a_small_field(self):
        # 9 entrants, 3 paid: with 4 left there are 1.33 players a paid place, and one bust to the money
        def small_field(left, **more):
            return tournament([15] * 4, 3, "A8o", acts=[(2, "allin", None)], left=left, paid=3, entrants=9, **more)

        real = A.bubble_sheet                       # the bubble charts by the sit-out line are another matter:
        A.bubble_sheet = lambda players, wait=False: None       # here the call tables answer
        try:
            for left in (4, 5):                     # one and two places from the money: the engine's own bubble
                with self.subTest(left=left):
                    money = A.read_money(small_field(left))
                    self.assertTrue(money.bubble and money.close)
                    plan = A.advise(small_field(left, plan="allin"))
                    self.assertEqual(verb(plan), "FOLD")
                    self.assertIn("on the bubble the chart calls with", plan["reason"])
                    self.assertEqual(verb(A.advise(small_field(left))), "FOLD")     # the two plans agree
            self.assertFalse(A.read_money(small_field(6)).bubble)
            away = A.advise(small_field(6, plan="allin"))
            self.assertEqual(verb(away), "CALL")
            self.assertIn("away from the bubble", away["reason"])
        finally:
            A.bubble_sheet = real
        # a big field is judged by players left per paid place, as before: 260 of 150 is close, not the bubble
        big = A.read_money(tournament(STACKS_A, BTN, "A8o", left=260))
        self.assertEqual((big.close, big.bubble), (True, False))

    def test_pre_20_the_numbers_on_one_answer_agree_with_the_action(self):
        # (1) an all-in the engine makes by rule while its own all-in number is a loss: that tile is not shown
        facts = {"ev": -2.25, "all_fold": 68.0, "when_called": 27.0, "their_range": 3.0, "my_equity": 61.0}
        self.assertEqual([t["label"] for t in A.engine_tiles(facts, "allin", "ICM counted")], ["Their range"])
        shown = [t["label"] for t in A.engine_tiles(dict(facts, ev=0.4), "allin", "ICM counted")]
        self.assertEqual(shown, ["All-in against folding", "Everybody folds", "Their range"])
        kings = A.advise(tournament([60] * 8, BTN, "KK", acts=[(UTG, "raise", 2.2), (HJ, "raise", 7)]))
        if kings["headline"]["follow"]["kind"] in ("allin", "raise"):
            self.assertFalse([t for t in kings["tiles"] if t["sign"] < 0], kings["tiles"])
        # (2) All-In or Fold: the call is what is still to pay, the size the reason speaks of
        a = A.advise(all_in_or_fold([8, 2.5, 8, 8], 3, "K5o", movers=[1]))
        self.assertEqual((verb(a), a["headline"]["size_text"]), ("CALL", "1.5BB"))
        self.assertIn("2.5bb effective", a["reason"])
        # (3) the all-in's value is quoted beside an all-in only, never beside a check or a fold
        number = [A.tile("All-in against folding", "+0.11bb")]
        self.assertEqual(A.engine_summary(A.Play("CHECK", "check", tiles=number)), "CHECK")
        self.assertEqual(A.engine_summary(A.Play("FOLD", "fold", tiles=number)), "FOLD")
        self.assertEqual(A.engine_summary(A.Play("ALL-IN", "allin", tiles=number)), "ALL-IN +0.11bb")
        limped = A.advise(tournament([15] * 8, BB, "T7o", acts=[(BTN, "call", None)], plan="allin"))
        self.assertEqual(verb(limped), "CHECK")
        self.assertRegex(limped["also"], r"^With all moves, on these stacks: [A-Z-]+\.$")
        # (4) nothing typed about the tournament: the stage line says so, like the strip
        blank = A.advise(tournament(STACKS_A, BTN, "A8o", left=None))
        self.assertEqual(blank["context"]["stage"], "Stage unknown: enter players left and places paid.")
        known = A.advise(tournament(STACKS_A, BTN, "A8o"))
        self.assertTrue(known["context"]["stage"].startswith("Middle:"), known["context"]["stage"])


# --------------------------------------------------------------------------
# The review's findings after the flop (POST-...) and the sentences of OPS-6, OPS-15, OPS-16
# --------------------------------------------------------------------------

class postflop_says:
    """For the length of a ``with`` block the engine after the flop gives this one answer (``None``: its own),
    and the spot it was asked about is kept in ``spot``."""

    def __init__(self, action=None, confidence="standard", why=("the engine's reason",), numbers=(), warnings=(),
                 data=None):
        self.spot = None
        self.advice = None if action is None else Advice(
            action, confidence, "", list(why), list(numbers), [], list(warnings),
            dict(data or {"equity": 0.5, "spr": 5.0}))

    def __enter__(self):
        self.real, A.advise_postflop = A.advise_postflop, self.answer
        return self

    def answer(self, spot):
        self.spot = spot
        return self.advice if self.advice is not None else self.real(spot)

    def __exit__(self, *exc):
        A.advise_postflop = self.real


CALL_58_56 = ["to call 3,000 (3.0bb, 60% pot): pot odds need 27% -> need 56%, have 58%"]


def flop(s, cards, *acts):
    """Type the flop (or the next card) and the actions after it: ``(seat, kind)`` or ``(seat, kind, chips)``."""
    s.do("set_cards", slot={6: "flop", 2: "turn"}[len(cards)] if len(cards) != 2 or not s.view()["hand"]["board"][3:]
         else "river", text=cards)
    for seat, kind, *amount in acts:
        s.do("act", seat=seat, kind=kind, amount=amount[0] if amount else None)
    return s


def labels(spot) -> dict:
    """{"CO": "raised first", ...} from the opponents handed to the engine."""
    return dict(v.label.split(": ") for v in spot.villains)


def pct(weights) -> float:
    return sum(w * n for w, n in zip(weights, A.COMBO_COUNT)) / 13.26


class AfterTheFlopFindings(unittest.TestCase):
    """Eight players at 500/1,000 with an ante of 125 unless said; seats are named by their place in the order."""

    def three_way(self, cards, stacks, acts, hero=BTN, **more):
        s = tournament(stacks, hero, cards, acts=acts, **more)
        return s, lambda index: seat_of(index, hero, 8)

    # ---- POST-1 --------------------------------------------------------------------------------------------

    def test_post_1_three_players_the_stack_that_matters_is_the_deepest_that_can_call(self):
        deep = [30, 30, 30, 30, 10, 60, 30, 60]             # the cutoff has 10bb; hero (button) and the big blind 60bb
        # (1) the short cutoff raises, hero and the big blind call; checked to hero with top pair, top kicker
        s, seat = self.three_way("AhKd", deep, [(CO, "raise", 2.2)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BB), kind="call")
        flop(s, "Ks7d2c", (seat(BB), "check"), (seat(CO), "check"))
        with postflop_says() as engine:
            a = A.advise(s)
        self.assertGreater(engine.spot.villain_stack, 50000)            # the big blind's chips, not the cutoff's 7,675
        self.assertEqual(a["headline"]["follow"]["kind"], "bet")        # a value bet, not 57bb into 8bb
        self.assertLess(a["headline"]["follow"]["to"], s.view()["hand"]["pot"])
        # (2) a short player bets, a deep one is still behind hero: calling does not "commit" hero
        s, seat = self.three_way("AhKd", [10, 30, 30, 30, 60, 60, 30, 30], [(UTG, "raise", 2.2)], hero=CO)
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BTN), kind="call")
        flop(s, "Ks7d2c", (seat(UTG), "bet", 2500))
        with postflop_says() as engine:
            a = A.advise(s)
        self.assertGreater(engine.spot.villain_stack, 50000)
        self.assertNotEqual(verb(a), "ALL-IN")
        # (3) a player is all-in before the flop: the player bet into is the one who still has chips
        s, seat = self.three_way("7h7s", [5, 30, 30, 30, 30, 60, 30, 60], [(UTG, "allin", None)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BB), kind="call")
        flop(s, "Ks7d2c", (seat(BB), "check"))
        with postflop_says() as engine:
            a = A.advise(s)
        self.assertTrue(engine.spot.villains[0].label.startswith("BB"), engine.spot.villains[0].label)
        self.assertGreater(engine.spot.villain_stack, 50000)            # was 0: "0.0bb behind", and ALL-IN 55bb
        self.assertEqual(a["headline"]["follow"]["kind"], "bet")

    def test_post_1_a_bettor_with_chips_is_not_all_in_because_hero_is_the_short_one(self):
        # hero has 4bb left and faces a bet from a player with 50bb behind: for the engine that is a bet, not
        # an all-in (the villain's chips are what he has beyond hero's call)
        s, seat = six_handed([60, 60, 60, 60, 60, 6.325], 5, "AhKd", acts=[(3, "raise", 2.2)])
        s.do("act", seat=1, kind="call")
        flop(s, "Ks7d2c", (1, "check"), (seat(3), "bet", 6000))
        with postflop_says() as engine:
            a = A.advise(s)
        self.assertEqual(s.view()["hand"]["to_call"], 4000)             # all hero has
        self.assertGreater(engine.spot.villain_stack, 40000)
        self.assertIsNone(engine.spot.facing)
        self.assertEqual((verb(a), a["headline"]["follow"]), ("CALL", {"kind": "call"}))

    def test_post_1_an_all_in_meant_for_a_smaller_stack_is_a_bet_while_a_deeper_player_is_in(self):
        s, seat = self.three_way("AhKd", [30, 30, 30, 30, 10, 60, 30, 60], [(CO, "raise", 2.2)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BB), kind="call")
        flop(s, "Ks7d2c", (seat(BB), "check"), (seat(CO), "check"))
        real = A.matchable
        A.matchable = lambda seen, opponents: 7675          # as if only the cutoff's chips could be won
        try:
            with postflop_says("BET ALL-IN"):
                a = A.advise(s)
        finally:
            A.matchable = real
        self.assertEqual((verb(a), a["headline"]["follow"]), ("BET", {"kind": "bet", "to": 7675}))

    # ---- POST-2 --------------------------------------------------------------------------------------------

    def test_post_2_all_in_plan_a_strong_hand_is_never_folded_by_the_free_flop_rule(self):
        # (a) the small blind completes with 3bb left and moves all-in on the flop; hero has 29bb and top pair
        stacks = [30, 30, 30, 30, 30, 30, 4.125, 30]
        s = tournament(stacks, BB, "AhKd", acts=[(SB, "call", None)], plan="allin")
        s.do("act", seat=1, kind="check")
        flop(s, "Ks7d2c", (seat_of(SB, BB, 8), "allin"))
        a = A.advise(s)
        self.assertEqual((verb(a), a["headline"]["follow"]), ("CALL", {"kind": "call"}))
        self.assertEqual(a["headline"]["size_text"], "3BB · 3,000")
        self.assertEqual(a["tiles"][1]["label"], "Pots behind")        # measured on the 3bb that can be lost
        self.assertLess(float(a["tiles"][1]["value"]), 1.0)
        # (b) a full house facing a bet with 29bb behind: more than 4 pots, so the full engine's play
        s = tournament([30] * 8, BB, "7h7s", acts=[(UTG, "call", None), (BTN, "call", None)], plan="allin")
        s.do("act", seat=1, kind="check")
        flop(s, "7d2c2s", (1, "check"), (seat_of(UTG, BB, 8), "bet", 2500), (seat_of(BTN, BB, 8), "fold"))
        with postflop_says("RAISE to 8,850 (8.9bb, 126% pot)", "clear"):
            a = A.advise(s)
        self.assertEqual(verb(a), "RAISE")
        self.assertIn("more than 4 pots behind", source(a))
        # ... and whatever the engine says, the rule's own answer for that hand is never CHECK or FOLD
        with postflop_says("CALL", "clear"):
            self.assertEqual(verb(A.advise(s)), "CALL")
        # (c) a hand that fails the strength test still folds to the bet
        s = tournament([30] * 8, BB, "Qh3d", acts=[(UTG, "call", None), (BTN, "call", None)], plan="allin")
        s.do("act", seat=1, kind="check")
        flop(s, "7d2c2s", (1, "check"), (seat_of(UTG, BB, 8), "bet", 2500), (seat_of(BTN, BB, 8), "fold"))
        a = A.advise(s)
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual(a["reason"], "No top pair and no 12-out draw: check, and fold to a bet.")
        # ... but not at a tiny price: 0.2bb more into 3bb is the full engine's call
        s = tournament([30, 30, 30, 30, 30, 30, 1.325, 30], BB, "Qh3d", acts=[(SB, "call", None)], plan="allin")
        s.do("act", seat=1, kind="check")
        flop(s, "7d2c2s", (seat_of(SB, BB, 8), "allin"))
        with postflop_says("CALL", numbers=["to call 200: need 6%, have 11%"]):
            a = A.advise(s)
        self.assertEqual((verb(a), source(a).split(" \u00b7 ")[-1]), ("CALL", "all-in plan: a tiny price, the full engine's play"))
        with postflop_says("FOLD"):
            self.assertEqual(verb(A.advise(s)), "FOLD")
        # the second line is the other plan's answer: the engine's numbers only beside the engine's own play
        s = tournament([30, 30, 30, 30, 30, 30, 8, 30], BB, "AhKd", acts=[(SB, "call", None)], plan="allin")
        s.do("act", seat=1, kind="check")
        flop(s, "Ks7d2c", (seat_of(SB, BB, 8), "allin"))
        with postflop_says("CALL", "close", numbers=CALL_58_56):       # a close call: "all moves" folds it
            a = A.advise(s)
        self.assertEqual((verb(a), a["also"]), ("CALL", "With all moves: FOLD."))
        with postflop_says("CALL", "clear", numbers=CALL_58_56):
            self.assertEqual(A.advise(s)["also"], "With all moves: CALL, 58% against 56%.")
        # (d) top pair with 4 pots or less behind against a player who covers: all-in, as before
        s = tournament([30, 30, 30, 30, 30, 30, 30, 10], BB, "AhKd", acts=[(UTG, "call", None)], plan="allin")
        s.do("act", seat=1, kind="check")
        flop(s, "Ks7d2c")
        a = A.advise(s)
        self.assertEqual((verb(a), a["headline"]["follow"]), ("ALL-IN", {"kind": "allin"}))

    # ---- POST-4, POST-5 --------------------------------------------------------------------------------------

    def test_post_4_a_short_all_in_is_not_the_first_raise(self):
        def cutoff_raises_and_bets(utg_stack, utg_does):
            stacks = [utg_stack, 30, 30, 30, 30, 50, 30, 50]
            s, seat = self.three_way("KhQd", stacks, [(UTG, utg_does, None), (CO, "raise", 2.5)])
            s.do("act", seat=1, kind="call")
            s.do("act", seat=seat(SB), kind="fold")
            s.do("act", seat=seat(BB), kind="fold")
            flop(s, "Ks7d2c", (seat(CO), "bet", 3000))
            with postflop_says() as engine:
                A.advise(s)
            return engine.spot

        opening = A.villain_open_range(3, "unknown")                    # the cutoff's opening range
        short = cutoff_raises_and_bets(1.5, "allin")                    # all-in for 1.4bb: less than a full raise
        self.assertEqual(labels(short), {"CO": "raised over a short all-in", "UTG": "moved all-in"})
        self.assertEqual(short.villains[0].weights, opening)            # was "re-raised": JJ+, AQs+, AKo
        self.assertGreater(pct(short.villains[1].weights), 60)          # a 1.4bb stack moves in with most hands
        self.assertEqual(labels(cutoff_raises_and_bets(30, "fold")), {"CO": "raised first"})
        # an open all-in is a push range for its stack, not the seat's opening range; a raise over a real
        # all-in is read by the hands that call that all-in
        real = cutoff_raises_and_bets(6, "allin")
        self.assertEqual(labels(real), {"CO": "raised over an all-in", "UTG": "moved all-in"})
        self.assertNotEqual(real.villains[1].weights, A.villain_open_range(7, "unknown"))
        self.assertGreater(pct(real.villains[1].weights), pct(A.villain_open_range(7, "unknown")))
        self.assertGreater(pct(real.villains[0].weights), 5)            # far more than the 3% of a re-raise

    def test_post_5_four_ways_into_the_pot_get_their_own_range(self):
        queens, junk = HANDS.index("QQ"), [HANDS.index(h) for h in ("65s", "JTo", "72o")]
        # (1) the big blind raises over two players who only called
        s, seat = self.three_way("KhTh", [40] * 8, [(UTG, "call", None)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(SB), kind="fold")
        s.do("act", seat=seat(BB), kind="raise", amount=6000)
        s.do("act", seat=seat(UTG), kind="fold")
        s.do("act", seat=1, kind="call")
        flop(s, "Ks7d2c", (seat(BB), "bet", 8000))
        with postflop_says() as engine:
            A.advise(s)
        self.assertEqual(labels(engine.spot), {"BB": "raised over the callers"})
        self.assertEqual(engine.spot.villains[0].weights, A.isolation_range(0, "unknown", 2))
        self.assertLess(pct(engine.spot.villains[0].weights), 20)       # was the small blind's 36% opening range
        # (2) the big blind calls hero's re-raise cold; (3) the cutoff opens and calls it
        for caller, acts in ((BB, [(CO, "raise", 2.2)]), (CO, [(CO, "raise", 2.2)])):
            s, seat = self.three_way("QhQd", [60] * 8, acts)
            s.do("act", seat=1, kind="raise", amount=7000)
            if caller == BB:
                s.do("act", seat=seat(SB), kind="fold")
                s.do("act", seat=seat(BB), kind="call")
                s.do("act", seat=seat(CO), kind="fold")
            else:
                s.do("act", seat=seat(SB), kind="fold")
                s.do("act", seat=seat(BB), kind="fold")
                s.do("act", seat=seat(CO), kind="call")
            flop(s, "Js7d2c", (seat(caller), "check"))
            with postflop_says() as engine:
                A.advise(s)
            weights = engine.spot.villains[0].weights
            self.assertEqual(list(labels(engine.spot).values()), ["called a re-raise"])
            self.assertLess(pct(weights), 8)                            # was 33% and 26%
            self.assertEqual(weights[queens], 1.0)
            self.assertFalse(any(weights[h] for h in junk))
        # blind against blind is not an isolation raise: the big blind raises the small blind's call wide
        s = tournament([40] * 8, SB, "KhTh")
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat_of(BB, SB, 8), kind="raise", amount=3000)
        s.do("act", seat=1, kind="call")
        flop(s, "Ks7d2c", (1, "check"), (seat_of(BB, SB, 8), "bet", 3000))
        with postflop_says() as engine:
            A.advise(s)
        self.assertEqual(labels(engine.spot), {"BB": "raised over the small blind's call"})
        self.assertEqual(engine.spot.villains[0].weights, A.villain_open_range(1, "unknown"))
        usual, loose = (pct(parse_range(A.CONTINUE_VS_RERAISE[k])) for k in ("usual", "loose"))
        self.assertGreater(loose, usual)                                # wider for players who call too much
        # (4) the button moves all-in for 12bb, the small blind calls, hero calls in the big blind
        s = tournament([30, 30, 30, 30, 30, 12, 50, 50], BB, "AhQd", acts=[(BTN, "allin", None), (SB, "call", None)])
        s.do("act", seat=1, kind="call")
        flop(s, "Qs7d2c", (seat_of(SB, BB, 8), "bet", 6000))
        with postflop_says() as engine:
            A.advise(s)
        self.assertEqual(labels(engine.spot), {"SB": "called an all-in", "BTN": "moved all-in"})
        caller, pusher = (v.weights for v in engine.spot.villains)
        for hand in ("AA", "TT", "AKs", "AQs", "AKo"):                  # the hands that do call an all-in ...
            self.assertEqual(caller[HANDS.index(hand)], 1.0, hand)      # ... were missing from the old range
        self.assertFalse(caller[HANDS.index("76s")])
        self.assertNotEqual(pusher, A.villain_open_range(2, "unknown"))

    # ---- POST-7, POST-8 --------------------------------------------------------------------------------------

    def raised_on_the_turn(self, tag, hero_cards="AhKd"):
        """Hero raises the cutoff, bets flop and turn, and the big blind check-raises the turn."""
        s, seat = six_handed([100] * 6, 2, hero_cards, types={5: tag} if tag else None)
        villain = seat(5)
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=villain, kind="call")
        flop(s, "Ks7d2c", (villain, "check"), (1, "bet", 2000), (villain, "call"))
        flop(s, "9s", (villain, "check"), (1, "bet", 6000), (villain, "raise", 20000))
        with postflop_says("CALL", "clear", numbers=["to call 14,000: need 31%, have 63%"]):
            return A.advise(s)

    def test_post_7_one_pair_folds_to_a_turn_raise_from_a_player_without_a_tag(self):
        a = self.raised_on_the_turn(None)
        self.assertEqual((verb(a), a["headline"]["qualifier"]), ("FOLD", "playbook check"))
        self.assertEqual(a["reason"], "One pair facing a raise from BB: that is rarely a bluff, so the playbook folds.")
        self.assertEqual(a["also"], "By the numbers alone: CALL, 63% against 31%.")
        self.assertEqual(a["tiles"][1]["note"], "by the numbers alone")     # the numbers beside the fold are the engine's
        self.assertIn("tagged tight", self.raised_on_the_turn("tight")["reason"])
        for aggressive in ("lag", "maniac"):                            # only against these the engine's call stays
            self.assertEqual(verb(self.raised_on_the_turn(aggressive)), "CALL")
        # two pair is not one pair
        self.assertEqual(verb(self.raised_on_the_turn(None, "Kh7h")), "CALL")
        # a hand weaker than one pair never plays on where one pair folds
        self.assertEqual(verb(self.raised_on_the_turn(None, "AhQd")), "FOLD")
        self.assertEqual(verb(self.raised_on_the_turn(None, "JhJd")), "FOLD")
        # with a draw of 8 outs or more the engine decides
        self.assertEqual(verb(self.raised_on_the_turn(None, "QsJs")), "CALL")

    def thin_bet_then_raised(self, tag=None, stack=60, cards="Kh4h"):
        """Top pair, weak kicker: (the answer to the flop checked to hero, the answer after his bet is raised)."""
        s, seat = six_handed([stack] * 6, 2, cards, types={5: tag} if tag else None)
        villain = seat(5)
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=villain, kind="call")
        flop(s, "Ks7d2c", (villain, "check"))
        with postflop_says("BET 1,900 (1.9bb, 33% pot)", warnings=["fold to a raise unless this player is aggressive"]):
            first = A.advise(s)
        s.do("act", seat=1, **first["headline"]["follow"])
        s.do("act", seat=villain, kind="raise", amount=6000)
        with postflop_says("CALL", numbers=["to call 4,100: need 31%, have 34%"]):
            return first, A.advise(s)

    def test_post_8_the_answer_to_a_raise_keeps_what_the_bet_announced(self):
        announced = "Fold to a raise unless this player is aggressive."
        first, second = self.thin_bet_then_raised()
        self.assertIn(announced, [w["text"] for w in first["warnings"]])
        self.assertEqual((verb(second), second["headline"]["qualifier"]), ("FOLD", "playbook check"))
        self.assertIn("fold, as planned with the bet", second["reason"])
        self.assertEqual(second["also"], "By the numbers alone: CALL, 34% against 31%.")
        # against a player tagged aggressive, or with the stack committed, the engine's call stays: then the
        # bet does not announce a fold either
        for more in ({"tag": "lag"}, {"tag": "maniac"}, {"stack": 9}):
            first, second = self.thin_bet_then_raised(**more)
            self.assertNotIn(announced, [w["text"] for w in first["warnings"]], more)
            self.assertEqual(verb(second), "CALL", more)
        # second pair folds there too (a stronger hand never folds where a weaker one calls); top pair with a
        # strong kicker is the engine's decision on the flop
        self.assertEqual(verb(self.thin_bet_then_raised(cards="8h7h")[1]), "FOLD")
        self.assertEqual(verb(self.thin_bet_then_raised(cards="AhKd")[1]), "CALL")

    def test_post_8_a_bluff_catcher_only_announces_the_fold_that_follows(self):
        engine_warning = ["a bluff-catcher: fold to a big bet on the next street unless you improve"]

        def called_twice(tag=None, river_bet=20000):
            """The big blind calls the button's flop and turn bets with top pair, weak kicker: (flop, turn, river)."""
            s, seat = six_handed([60] * 6, 5, "Kh4h", acts=[(3, "raise", 2.2)], types={3: tag} if tag else None)
            answers = []
            s.do("act", seat=1, kind="call")
            for cards, bet in (("Ks7d2c", 2500), ("5c", 8000), ("3d", river_bet)):
                flop(s, cards, (1, "check"), (seat(3), "bet", bet))
                with postflop_says("CALL", numbers=["to call: need 32%, have 55%"], warnings=engine_warning):
                    answers.append(A.advise(s))
                if cards != "3d":
                    s.do("act", seat=1, kind="call")
            return answers

        said = lambda answer: [w["text"] for w in answer["warnings"] if w["code"] == "engine"]
        on_flop, on_turn, on_river = called_twice()
        # the engine's own line promises a fold on the next street that the next answer does not make
        self.assertEqual(said(on_flop), ["A bluff-catcher: it beats a bluff and nothing else."])
        self.assertEqual((verb(on_flop), verb(on_turn)), ("CALL", "CALL"))
        # what the turn announces, the river does: one pair folds to a big river bet
        self.assertEqual(said(on_turn), ["A bluff-catcher: fold the river to a bet of 60% of the pot or more "
                                         "unless you improve."])
        self.assertEqual((verb(on_river), on_river["headline"]["qualifier"]), ("FOLD", "playbook check"))
        self.assertEqual(verb(called_twice(river_bet=9000)[2]), "CALL")         # a smaller bet: the engine's answer
        # against a player tagged maniac the rule does not fold, so nothing is promised
        on_flop, on_turn, on_river = called_twice("maniac")
        self.assertEqual(said(on_turn), ["A bluff-catcher: it beats a bluff and nothing else."])
        self.assertEqual(verb(on_river), "CALL")

    # ---- POST-9 ----------------------------------------------------------------------------------------------

    def test_post_9_only_the_raisers_flop_bet_is_a_continuation_bet(self):
        # the engine is told who raised last before the flop
        s, seat = self.three_way("QhJh", [40] * 8, [(CO, "raise", 2.2)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BB), kind="call")
        flop(s, "As7h4d", (seat(BB), "bet", 3000), (seat(CO), "call"))
        with postflop_says() as engine:
            A.advise(s)
        self.assertEqual({v.label.split(":")[0]: v.pfr for v in engine.spot.villains}, {"BB": False, "CO": True})
        self.assertFalse(engine.spot.hero_pfr)

        def limped_pot(cards, bet, style=None):
            s = tournament([40] * 8, BB, cards, acts=[(SB, "call", None)], style=style)
            s.do("act", seat=1, kind="check")
            flop(s, "As7h4d", (seat_of(SB, BB, 8), "bet", bet))
            with postflop_says("CALL", numbers=["to call: need 33%, have 34%"]) as engine:
                return A.advise(s), engine.spot

        # no pair, no draw, a pot-sized bet from a player who only called before the flop: fold, whatever the engine says
        a, spot = limped_pot("QhTd", 2125)
        self.assertEqual([v.pfr for v in spot.villains], [False])       # nobody raised: no continuation bet
        self.assertEqual(verb(a), "FOLD")
        self.assertIn("did not raise before the flop", a["reason"])
        self.assertEqual(a["also"], "By the numbers alone: CALL, 34% against 33%.")
        self.assertEqual(verb(limped_pot("QhTd", 500)[0]), "CALL")      # a small bet: the engine's answer
        self.assertEqual(verb(limped_pot("Qh7d", 2125)[0]), "CALL")     # a pair
        self.assertEqual(verb(limped_pot("6h5h", 2125)[0]), "CALL")     # a draw of 8 outs or more
        # the raiser's own bet is left to the engine
        s, seat = six_handed([40] * 6, 5, "QhTd", acts=[(3, "raise", 2.2)])
        s.do("act", seat=1, kind="call")
        flop(s, "As7h4d", (1, "check"), (seat(3), "bet", 4000))
        with postflop_says("CALL", numbers=["to call: need 33%, have 34%"]) as engine:
            self.assertEqual(verb(A.advise(s)), "CALL")
        self.assertEqual([v.pfr for v in engine.spot.villains], [True])

    # ---- POST-10, POST-12 ------------------------------------------------------------------------------------

    def test_post_10_players_in_front_who_have_not_acted_are_named_as_an_assumption(self):
        s, seat = self.three_way("QhJh", [40] * 8, [(UTG, "raise", 2.2)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BB), kind="call")
        flop(s, "Th9h2c")                                               # nobody has acted on the flop yet
        self.assertEqual(s.view()["hand"]["before_target"], [seat(BB), seat(UTG)])
        with postflop_says("CHECK") as engine:
            a = A.advise(s)
        self.assertEqual(a["spot"], "QhJh on Th9h2c, if BB and UTG check, pot 8.1bb")
        self.assertEqual(a["provisional"], "if BB and UTG check")
        self.assertEqual(a["headline"]["qualifier"], "if BB and UTG check")
        self.assertEqual([v.line for v in engine.spot.villains], [[], []])     # no check narrows a range yet
        # one of them checks for real: he is no longer assumed, and his check is on his line
        s.do("act", seat=seat(BB), kind="check")
        with postflop_says("BET 2,700 (2.7bb, 33% pot) (semi-bluff)") as engine:
            a = A.advise(s)
        self.assertEqual(a["spot"], "QhJh on Th9h2c, if UTG checks, pot 8.1bb")
        self.assertEqual(a["headline"]["qualifier"], "semi-bluff, if UTG checks")
        self.assertEqual({v.label.split(":")[0]: len(v.line) for v in engine.spot.villains}, {"UTG": 0, "BB": 1})
        s.do("act", seat=seat(UTG), kind="check")
        a = A.advise(s)
        self.assertEqual((a["spot"], a["provisional"]), ("QhJh on Th9h2c, checked to you, pot 8.1bb", ""))
        # a bet in front of hero and a player between them who has not acted: he is assumed to fold
        s = tournament([40] * 8, BB, "AhKd", acts=[(UTG, "call", None), (BTN, "call", None)])
        s.do("act", seat=1, kind="check")
        flop(s, "Ks7d2c", (1, "check"), (seat_of(UTG, BB, 8), "bet", 2500))
        a = A.advise(s)
        self.assertEqual(a["spot"], "AhKd on Ks7d2c, UTG bets 2.5bb into 4.5bb, if BTN folds")
        self.assertEqual(a["provisional"], "if BTN folds")
        # before the flop "folded to you" stays as it is
        self.assertEqual(A.advise(tournament(STACKS_A, BTN, "A8o"))["provisional"], "")

    def test_post_12_the_spot_line_names_who_bet_and_who_called(self):
        s, seat = self.three_way("8h7h", [40] * 8, [(UTG, "call", None)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(SB), kind="fold")
        s.do("act", seat=seat(BB), kind="raise", amount=6000)
        s.do("act", seat=seat(UTG), kind="call")
        s.do("act", seat=1, kind="call")
        flop(s, "9s6d2c", (seat(BB), "bet", 4000), (seat(UTG), "call"))
        self.assertEqual(A.advise(s)["spot"], "8h7h on 9s6d2c, BB bets 4bb into 19.5bb, UTG calls")   # was "UTG bets"
        # a bet and a raise in front of hero: the raiser is named
        s, seat = self.three_way("7h7s", [90] * 8, [(UTG, "raise", 2.2)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BB), kind="call")
        flop(s, "Ks7d6d", (seat(BB), "bet", 3000), (seat(UTG), "raise", 9000))
        self.assertEqual(A.advise(s)["spot"], "7h7s on Ks7d6d, UTG raises to 9bb into 8.1bb")

    def test_a_check_with_a_good_hand_is_not_explained_as_nothing_strong(self):
        # the engine checks an overpair into two players and says "multi-way with nothing strong": the tile
        # beside it says "overpair", so the sentence is the one for a hand worth a call
        s, seat = self.three_way("AhAs", [40] * 8, [(UTG, "raise", 2.2)])
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BB), kind="call")
        flop(s, "Ts7s4d", (seat(BB), "check"), (seat(UTG), "check"))
        with postflop_says("CHECK", why=["multi-way with nothing strong: no bluffing into several players"]):
            a = A.advise(s)
        self.assertEqual(a["tiles"][-1]["value"], "overpair")
        self.assertEqual(a["reason"], "A good hand, but not one to bet for value here: keep the pot small and call "
                                      "one reasonable bet.")
        s, seat = self.three_way("QhJh", [40] * 8, [(UTG, "raise", 2.2)])           # with air the engine's own words
        s.do("act", seat=1, kind="call")
        s.do("act", seat=seat(BB), kind="call")
        flop(s, "Ts7s4d", (seat(BB), "check"), (seat(UTG), "check"))
        with postflop_says("CHECK", why=["multi-way with nothing strong: no bluffing into several players"]):
            self.assertIn("nothing strong", A.advise(s)["reason"])

    # ---- POST-11 ---------------------------------------------------------------------------------------------

    def test_post_11_the_all_in_headline_shows_what_can_be_matched(self):
        # after the flop: hero has 59bb, the only opponent 20bb
        s, seat = six_handed([60, 60, 60, 60, 60, 22.325], 2, "7h7s")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat(5), kind="call")
        flop(s, "Ks7d6d", (seat(5), "check"))
        with postflop_says("BET ALL-IN"):
            a = A.advise(s)
        self.assertEqual((verb(a), a["headline"]["follow"]), ("ALL-IN", {"kind": "allin"}))
        # hero's whole stack, as the All-in button records it, and beside it what is really at risk (D2)
        self.assertEqual(a["headline"]["size_text"], "57.7BB · 57,675")
        self.assertEqual(a["headline"]["qualifier"], "20bb of your 57.7bb can be matched")
        # before the flop: the small blind has 30bb and only the big blind, with 8bb, is left
        s = tournament([30, 30, 30, 30, 30, 30, 30, 8], SB, "AA")
        with engine_says("ALL-IN", data={"shove_ev_bb": 1.0}):
            a = A.advise(s)
        self.assertEqual((verb(a), a["headline"]["follow"]), ("ALL-IN", {"kind": "allin"}))
        self.assertEqual(a["headline"]["size_text"], "29.9BB · 29,875")
        self.assertEqual(a["headline"]["qualifier"], "7.9bb of your 29.9bb can be matched")   # the big blind's stack
        # hero is the short one: his own stack, as before
        s = tournament([30, 30, 30, 30, 30, 30, 12, 30], SB, "AA")
        with engine_says("ALL-IN", data={"shove_ev_bb": 1.0}):
            a = A.advise(s)
        self.assertEqual((a["headline"]["size_text"], a["headline"]["qualifier"]), ("11.9BB · 11,875", ""))

    # ---- POST-13 ---------------------------------------------------------------------------------------------

    def test_post_13_a_player_sitting_out_has_no_hand_after_the_flop(self):
        # heads-up against a big blind who is sitting out: the smallest bet takes the pot
        s = Session(save=False)
        s.do("new_session", mode="tournament", size=8, start_stack=30000, button=8)
        s.do("set_level", text="300/600/75")
        s.do("set_status", seat=2, status="away")                       # hero is the small blind, seat 2 the big blind
        s.do("deal", hero_cards="9h4d")
        s.do("act", seat=1, kind="call")
        flop(s, "As6d2c")
        a = A.advise(s)
        self.assertEqual((verb(a), a["headline"]["follow"]), ("BET", {"kind": "bet", "to": 600}))
        self.assertIn("sitting out", a["reason"])
        # three-way with the absent big blind: the engine is asked about the player who is there, alone
        s = Session(save=False)
        s.do("new_session", mode="tournament", size=8, start_stack=30000, button=1)
        s.do("set_level", text="300/600/75")
        s.do("set_status", seat=3, status="away")                       # hero on the button, seat 3 the big blind
        s.do("deal", hero_cards="QhJh")
        s.do("act", seat=4, kind="call")
        s.do("act", seat=1, kind="call")
        flop(s, "As6d2c", (4, "check"))
        with postflop_says() as engine:
            A.advise(s)
        self.assertEqual(list(labels(engine.spot)), ["UTG"])            # was UTG and "BB: any two cards"

    # ---- POST-14 ---------------------------------------------------------------------------------------------

    def test_post_14_bets_after_the_flop_are_amounts_the_chips_can_make(self):
        s, seat = six_handed([90] * 6, 2, "7h7s")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat(5), kind="call")
        flop(s, "Ks7d6d", (seat(5), "check"))
        seen = A.read_table(s, s.view())
        self.assertEqual(A.chip_step(seen), 25)                         # 500/1,000 with an ante of 125
        with postflop_says("BET 1,897 (1.9bb, 33% pot)"):
            a = A.advise(s)
        self.assertEqual(a["headline"]["follow"], {"kind": "bet", "to": 1900})
        self.assertEqual(a["headline"]["size_text"], "1.9BB · 1,900")
        with postflop_says("BET 311 (0.3bb, 5% pot)"):                  # under the smallest bet: lifted to it
            self.assertEqual(A.advise(s)["headline"]["follow"], {"kind": "bet", "to": 1000})
        s.do("act", seat=1, kind="bet", amount=1900)
        s.do("act", seat=seat(5), kind="raise", amount=5433)            # an odd raise: the smallest re-raise is odd too
        low = s.view()["hand"]["legal"]["raise"]["min"]
        with postflop_says("RAISE to 16,788 (16.8bb, 120% pot)"):
            a = A.advise(s)
        self.assertEqual(a["headline"]["follow"], {"kind": "raise", "to": 18700})      # 1,900 in front + 16,788
        self.assertEqual(low, 8966)
        with postflop_says(f"RAISE to {low - 1900 - 10:,} (7bb, 50% pot)"):            # 8,956 would round to 8,950
            self.assertEqual(A.advise(s)["headline"]["follow"]["to"], low)             # never under the minimum
        s.do("act", seat=1, **a["headline"]["follow"])                  # and the table takes it
        # a bet of every chip hero has stays an all-in, whatever the chips
        s, seat = six_handed([60, 60, 22.303, 60, 60, 60], 2, "7h7s")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat(5), kind="call")
        flop(s, "Ks7d6d", (seat(5), "check"))
        with postflop_says("BET 19,978 (20bb, 300% pot)"):
            a = A.advise(s)
        self.assertEqual((verb(a), a["headline"]["follow"]), ("ALL-IN", {"kind": "allin"}))
        self.assertEqual(a["headline"]["size_text"], "20BB \u00b7 19,978")
        seen = A.read_table(s, s.view())
        for level, step in (("300/600/75", 25), ("100/200/25", 25), ("1000/2000/250", 250), ("10/20", 10),
                            ("15/30", 5), ("300/600", 100), ("1/2", 1)):
            sb, bb, *ante = (int(x) for x in level.split("/"))
            seen.hand["level"].update(sb=sb, bb=bb, ante=ante[0] if ante else 0)
            self.assertEqual(A.chip_step(seen), step, level)

    # ---- close spots after the flop --------------------------------------------------------------------------

    def close_call(self, left=400, style=None, tag=None, numbers=CALL_58_56, why=("you have the equity",)):
        s, seat = six_handed([60] * 6, 5, "AhQd", acts=[(2, "raise", 2.2)], left=left, style=style,
                             types={2: tag} if tag else None)
        s.do("act", seat=1, kind="call")
        flop(s, "Qs8d3c", (1, "check"), (seat(2), "bet", 3000))
        with postflop_says("CALL", "close", why=why, numbers=numbers):
            return A.advise(s)

    def test_close_after_the_flop_the_lower_variance_side_leads_before_the_money(self):
        a = self.close_call()
        self.assertEqual((verb(a), a["headline"]["qualifier"], a["headline"]["sure"], a["guard"]),
                         ("FOLD", "close: lower variance", "close", "close"))
        self.assertEqual(a["reason"], "Close: the call and the fold are worth about the same. Before the money the "
                                      "lower-variance side leads: fold.")
        self.assertEqual(a["also"], "By the numbers alone: CALL, 58% against 56% (the Max EV style plays it).")
        self.assertTrue(source(a).endswith("CLOSE: before the money the lower-variance side leads "
                                           "(engine: CALL, 58% against 56%)"), source(a))
        self.assertNotIn("close", codes(a))                             # the reason says it
        self.assertEqual(verb(self.close_call(style="cash")), "FOLD")
        # the engine's play: Max EV, in the money, a final table, against a player tagged aggressive, a hand
        # the engine calls committed
        for more in ({"style": "maxev"}, {"left": 140}, {"left": 6}, {"tag": "maniac"},
                     {"why": ("with a strong one-pair hand and less than 1.5x the pot behind you are committed",)}):
            a = self.close_call(**more)
            self.assertEqual((verb(a), a["guard"]), ("CALL", "none"), more)
            self.assertIn("close", codes(a), more)
        # a close bluff becomes a check; a close value bet does not exist, and a standard bluff stays
        s, seat = six_handed([60] * 6, 2, "JhTh")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat(5), kind="call")
        flop(s, "Ks7d2c", (seat(5), "check"))
        with postflop_says("BET 1,900 (1.9bb, 33% pot) (c-bet)", "close"):
            a = A.advise(s)
        self.assertEqual((verb(a), a["guard"], a["headline"]["follow"]), ("CHECK", "close", {"kind": "check"}))
        self.assertIn("the bet and the check are worth about the same", a["reason"])
        with postflop_says("BET 1,900 (1.9bb, 33% pot) (c-bet)"):
            self.assertEqual(verb(A.advise(s)), "BET")
        # Spin: chips are money, the engine's play
        s = spin([15, 15, 15], 2, "AhQd", acts=[(0, "fold", None), (1, "call", None)])
        s.do("act", seat=1, kind="check")
        flop(s, "Qs8d3c", (seat_of(1, 2, 3), "bet", 100))
        with postflop_says("CALL", "close", numbers=CALL_58_56):
            self.assertEqual(verb(A.advise(s)), "CALL")

    # ---- OPS-6, OPS-15, OPS-16: the sentences --------------------------------------------------------------

    def test_ops_6_after_a_fold_the_line_says_press_n(self):
        s = tournament(STACKS_A, BTN, "72o")
        s.do("act", seat=1, kind="fold")                                # the blinds still have to act
        self.assertEqual(A.advise(s)["spot"], "You have folded: nothing left to decide. Press N for the next hand.")

    def lost_all_in(self, hero_stack):
        """Hero raises the cutoff, the big blind (40bb) moves all-in, hero calls and loses."""
        s, seat = six_handed([40, 40, hero_stack, 40, 40, 40], 2, "AhKd")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat(5), kind="allin")
        s.do("act", seat=1, kind="call")
        for cards in ("Qs7d2c", "3h", "9s"):
            flop(s, cards)
        s.do("award", winner=seat(5))
        return s, seat(5)

    def test_ops_15_the_result_names_the_winner_by_seat_and_the_next_hand(self):
        s, winner = self.lost_all_in(50)
        a = A.advise(s)
        self.assertEqual(a["status"], "none")
        # the seat names on the table are already the next hand's: the line gives the finished hand's
        self.assertEqual(a["spot"], f"Seat {winner} (BB) wins 81,000. The button is now on seat {winner - 1} and "
                                    "you are in the hijack: press N for the next hand.")
        self.assertEqual(s.view()["table"]["seats"][winner - 1]["pos"], "SB")
        # hero wins: "You (CO) win"
        s, seat = six_handed([40] * 6, 2, "AhKd")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat(5), kind="call")
        flop(s, "Ks7d2c", (seat(5), "check"), (1, "bet", 2000), (seat(5), "fold"))
        self.assertTrue(A.advise(s)["spot"].startswith("You (CO) win 5,650. The button is now on seat"))
        # a split pot names both
        s, seat = six_handed([40] * 6, 2, "AhKd")
        s.do("act", seat=1, kind="raise", amount=2200)
        s.do("act", seat=seat(5), kind="call")
        for cards in ("Ks7d2c", "3h", "9s"):
            flop(s, cards, (seat(5), "check"), (1, "check"))
        s.do("award", ranking=[[1, seat(5)]])
        self.assertTrue(A.advise(s)["spot"].startswith(f"You (CO) win 2,825, seat {seat(5)} (BB) wins 2,825. "),
                        A.advise(s)["spot"])

    def test_ops_16_without_chips_the_line_says_what_to_do_and_stays(self):
        s, winner = self.lost_all_in(30)
        told = "You have no chips left: type a new stack on your seat to re-enter, or start a new tournament."
        self.assertEqual(A.advise(s)["spot"], f"Seat {winner} (BB) wins 61,000. {told}")
        s.do("deal")                                                    # a hand dealt without hero: still there
        self.assertEqual(A.advise(s)["spot"], told)
        s.do("set_stack", seat=1, text="20000")
        self.assertNotIn("no chips", A.advise(s)["spot"])


# --------------------------------------------------------------------------
# The last round of checks: four decisions and what the sweeps found
# --------------------------------------------------------------------------

class FinalChecks(unittest.TestCase):
    """One test for each decision (D1 to D4) and each problem found by the last sweeps."""

    def test_d1_the_big_blind_keeps_a_close_call_only_on_the_row_and_the_short_list(self):
        raised = [(BTN, "raise", 2.2)]
        short = parse_range(A.TAG.BB_CALL_SHORT)
        for style in (None, "cash"):
            with self.subTest(style=style):
                # K5o is on the sheet's row for 25bb or more against a button raise (K3o+), and not a hand
                # that makes top pair or a real draw: the fold leads, the call is the second line
                a = A.advise(tournament([30] * 8, BB, "K5o", acts=raised, style=style))
                self.assertEqual((verb(a), a["guard"], a["headline"]["sure"]), ("FOLD", "close", "close"))
                self.assertIn("By the numbers alone: CALL", a["also"])
                self.assertIn("not a hand that makes top pair or a real draw", a["reason"])
                self.assertNotIn("The sheet says", [t["label"] for t in a["tiles"]])    # the sheet's row has it
        # every close call that stays the headline is on the short list, at 25, 30 and 60bb
        for stack in (25, 30, 60):
            s = tournament([stack] * 8, BB, "AA", acts=raised)
            for hand in ("K9o", "Q9o", "T9o", "A2o", "72s", "22", "K8o", "K3o", "Q8o", "J8o", "T8o", "98o"):
                s.do("set_cards", hero=hand, replace=True)
                a = A.advise(s)
                if a["headline"]["sure"] == "close" and verb(a) == "CALL":
                    self.assertGreaterEqual(short[HANDS.index(hand)], 0.5, (stack, hand, source(a)))
                if short[HANDS.index(hand)] < 0.5:
                    self.assertNotEqual(verb(a), "CALL", (stack, hand))
        # an answer the engine marks standard or clear is not touched, and neither is the money or Max EV
        self.assertEqual(verb(A.advise(tournament([30] * 8, BB, "ATs", acts=raised))), "CALL")
        for more in (dict(left=100), dict(style="maxev")):
            self.assertEqual(verb(A.advise(tournament([30] * 8, BB, "K5o", acts=raised, **more))), "CALL", more)

    def test_d2_an_all_in_nobody_can_match_shows_the_stack_and_what_is_at_risk(self):
        # All-In or Fold: the small blind has 8bb, the big blind 5.5bb.  The button says 8bb, so the headline
        # does; the pill says what can be matched.  5.5 is never on the screen as the size of the all-in.
        a = A.advise(all_in_or_fold([8, 8, 8, 5.5], 2, "AA"))
        head = a["headline"]
        self.assertEqual((head["verb"], head["size_text"], head["follow"]), ("ALL-IN", "8BB", {"kind": "allin"}))
        self.assertEqual(head["qualifier"], "5.5bb of your 8bb can be matched")
        self.assertEqual(head["size_text"], "8BB")
        legal = all_in_or_fold([8, 8, 8, 5.5], 2, "AA").view()["hand"]["legal"]
        self.assertEqual(legal["allin"], 8)                                 # what the All-in button records
        # the tournament has the same pair of numbers: the small blind with 30bb against a big blind with 8bb
        with engine_says("ALL-IN", data={"shove_ev_bb": 1.0}):
            a = A.advise(tournament([30, 30, 30, 30, 30, 30, 30, 8], SB, "AA"))
        self.assertEqual(a["headline"]["size_text"], "29.9BB \u00b7 29,875")
        self.assertEqual(a["headline"]["qualifier"], "7.9bb of your 29.9bb can be matched")
        # a qualifier of the play keeps its place in front
        with engine_says("RE-RAISE ALL-IN (isolate)", data={"need": 0.4, "equity": 0.6}):
            a = A.advise(tournament([30, 30, 30, 30, 30, 6, 30, 12], SB, "AA", acts=[(BTN, "allin", None)]))
        self.assertEqual(a["headline"]["qualifier"], "isolate, 11.9bb of your 29.9bb can be matched")
        # all of it can be matched: no words
        self.assertEqual(A.advise(all_in_or_fold([8, 8, 8, 8], 2, "AA"))["headline"]["qualifier"], "")

    def test_d3_the_line_after_a_hand_is_the_models_own_text(self):
        # All-In or Fold, a pot split after the fee: 7.95bb each, in the hand line and in the coach's line
        s = all_in_or_fold([8, 8, 8, 8], 3, "AhKd", movers=[2])
        s.do("act", seat=1, kind="call")
        s.do("award", ranking=[[1, seat_of(2, 3, 4)]])
        text = s.view()["hand"]["result"]["text"]
        self.assertIn("7.95bb", text)
        self.assertTrue(A.advise(s)["spot"].startswith(text + ". "), A.advise(s)["spot"])
        self.assertEqual(A.result_line(s.view()), text + ".")
        # a Spin game that is over: who won the last hand, then the new game
        for winner, words in ((1, "You (BTN/SB) win 1,000."), (2, "Seat 2 (BB) wins 1,000.")):
            s = spin([10, 10], 0, "AhAd")
            s.do("act", seat=1, kind="allin")
            s.do("act", seat=2, kind="call")
            s.do("award", winner=winner)
            self.assertEqual(s.view()["hand"]["result"]["text"] + ".", words)
            self.assertEqual(A.advise(s)["spot"], words + " The game is over: press N for a new game.")

    def test_d4_the_small_blind_against_a_big_blind_all_in_for_less_says_why_nothing_is_asked(self):
        # The big blind has 0.6bb: after the ante he posts 475, less than hero's small blind of 500.  If
        # everybody folds hero has nothing to decide, so the table waits for the first player; the line says so.
        for n in (3, 6, 8):
            with self.subTest(players=n):
                stacks = [20] * n
                stacks[-1] = 0.6
                s = tournament(stacks, n - 2, "A8o")
                a = A.advise(s)
                self.assertEqual(a["status"], "none")
                self.assertNotIn("Waiting for", a["spot"])
                self.assertEqual(a["spot"], "Nobody has entered yet, and the big blind is all-in for no more than "
                                            "you have posted: if everybody folds there is nothing to decide. "
                                            "Enter the first call or raise.")
                # a player enters: hero is asked, and the answer is a legal move
                s.do("act", seat=seat_of(0, n - 2, n), kind="raise", amount=2200)
                a = A.advise(s)
                self.assertEqual(a["status"], "ready")
                self.assertNotEqual(verb(a), "NO ADVICE")
                s.do("act", seat=1, **a["headline"]["follow"])
        # heads-up the hand is over at once; and a big blind with a little more leaves hero a call
        self.assertEqual(A.advise(tournament([20, 0.6], 0, "A8o"))["spot"], "The betting is over: say who won.")
        # in a later round a player in front of hero is still "waited for" in the usual words
        s = tournament([30] * 8, BTN, "AhKd", acts=[(BTN, "raise", 2.2), (BB, "call", None)])
        s.do("set_cards", slot="flop", text="Ks7d2c")
        s.do("act", seat=seat_of(BB, BTN, 8), kind="bet", amount=2000)
        s.do("act", seat=1, kind="call")
        s.do("set_cards", slot="turn", text="3h")
        self.assertNotIn("nothing to decide", A.advise(s)["spot"])

    def test_an_all_in_that_can_only_be_a_call_is_a_call(self):
        # heads-up and three-handed: the big blind (1bb) posted 875 and is all-in; hero in the small blind
        # may fold or call 375.  The engine's "all-in" is that call: the headline and Follow say CALL.
        for stacks, hero in (([20, 1.0], 0), ([20, 20, 1.0], 1), ([20] * 7 + [1.0], 6)):
            with self.subTest(players=len(stacks)):
                s = tournament(stacks, hero, "A8o")
                legal = s.view()["hand"]["legal"]
                self.assertEqual((legal["call"], legal["raise"]), (375, None))
                a = A.advise(s)
                head = a["headline"]
                self.assertEqual((head["verb"], head["size_text"], head["follow"]),
                                 ("CALL", "0.4BB \u00b7 375", {"kind": "call"}))
                self.assertNotIn("can be matched", head["qualifier"])
                self.assertIn("the all-in is that call", a["reason"])
                s.do("act", seat=1, **head["follow"])                   # and the table takes it
        # All-In or Fold, first in: no call is offered beside the all-in, so it stays ALL-IN
        self.assertEqual(verb(A.advise(all_in_or_fold([8, 8, 8, 5.5], 2, "AA"))), "ALL-IN")

    def test_a_blind_posted_all_in_does_not_turn_seven_deuce_into_an_all_in(self):
        # The big blind has 0.6bb and is all-in from posting.  The solver took him for a caller who always
        # calls, after whom nobody else could: 72o over an early raise showed +1.45bb for 20bb.
        for style in (None, "maxev"):
            for n, raiser in ((8, UTG), (3, 0)):
                with self.subTest(style=style, players=n):
                    stacks = [20] * n
                    stacks[-1] = 0.6
                    a = A.advise(tournament(stacks, n - 2, "72o", acts=[(raiser, "raise", 2.2)], style=style))
                    self.assertEqual(verb(a), "FOLD", a["source"])
                    value = next(t["value"] for t in a["tiles"] if t["label"] == "All-in against folding")
                    self.assertTrue(value.startswith("\u2212"), value)             # a loss, as with a full big blind
        # the same hand and table with a small blind who is all-in from posting, first in on the button
        stacks = [20] * 8
        stacks[SB] = 0.3
        self.assertEqual(verb(A.advise(tournament(stacks, BTN, "72o", style="maxev"))), "FOLD")
        # a strong hand still plays there
        stacks = [20] * 8
        stacks[BB] = 0.6
        self.assertEqual(verb(A.advise(tournament(stacks, SB, "QQ", acts=[(UTG, "raise", 2.2)], style="maxev"))), "ALL-IN")


if __name__ == "__main__":
    unittest.main()
